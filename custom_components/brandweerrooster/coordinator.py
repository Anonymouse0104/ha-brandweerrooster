"""Data coordinator for Brandweerrooster.

One coordinator per account. It listens to FireServiceRota, fetches each new
incident once and hands it to every function profile it is relevant for.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import facebook_template
from .api import (
    BrandweerRoosterApi,
    BrandweerRoosterApiError,
    BrandweerRoosterAuthenticationError,
    BrandweerRoosterRateLimitError,
)
from .brandbase import BrandbaseVehicles, short_name
from .const import (
    CONF_BRANDBASE,
    CONF_FACEBOOK_TEMPLATE,
    CONF_INCIDENT_ENTITY,
    CONF_PERSON_NAME,
    CONF_VEHICLE_NAMES,
    DEFAULT_INCIDENT_ENTITY,
    DOMAIN,
    ENRICHMENT_DELAYS,
    HISTORY_DETAIL_DELAY,
    HISTORY_MAX_PAGES,
    HISTORY_PAGE_DELAY,
    HISTORY_PAGE_SIZE,
    INCIDENT_ENTITY_GRACE_PERIOD,
    RATE_LIMIT_DEFAULT_RETRY,
    SUBENTRY_PROFILE,
    TURNOUT_MODE_DUTY,
)
from .incident import incident_body, incident_groups, incident_id, incident_tasks, message_values
from .profile import Profile
from .statistics import combined_counts, find_user_response
from .vehicles import extract_vehicle_codes, parse_vehicle_names

if TYPE_CHECKING:
    from . import BrandweerRoosterConfigEntry

_LOGGER = logging.getLogger(__name__)

ISSUE_INCIDENT_ENTITY_MISSING = "incident_entity_missing"
STARTUP_POLL_INTERVAL = 5


def _incident_needs_enrichment(incident: dict[str, Any] | None) -> bool:
    """Return True while the incident still lacks assigned personnel."""
    if not incident:
        return False
    if incident.get("_fallback"):
        return True
    assignments = incident.get("incident_skill_assignments") or []
    return not any(isinstance(item, dict) and item.get("user_id") is not None for item in assignments)


FILL_LATEST_MAX_PAGES = 4


def _newer(incident: dict[str, Any], other: dict[str, Any]) -> bool:
    """Whether an incident is more recent than another (alarm time, then id)."""

    def key(item: dict[str, Any]) -> tuple[str, int]:
        return (str(item.get("created_at") or item.get("start_time") or ""), incident_id(item) or 0)

    return key(incident) > key(other)


def _has_scope_fields(incident: dict[str, Any]) -> bool:
    return any(key in incident for key in ("groups", "group_ids", "task_ids"))


class BrandweerRoosterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Maintain Brandweerrooster data and react to FireServiceRota incidents."""

    config_entry: BrandweerRoosterConfigEntry

    def __init__(self, hass: HomeAssistant, entry: BrandweerRoosterConfigEntry, api: BrandweerRoosterApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,
            always_update=False,
        )
        self.api = api
        api.status_listener = self._async_api_status_changed

        options = entry.options
        self.person_name = str(options.get(CONF_PERSON_NAME) or "").strip()
        self.incident_entity = str(options.get(CONF_INCIDENT_ENTITY) or DEFAULT_INCIDENT_ENTITY)
        self.message_template = str(
            options.get(CONF_FACEBOOK_TEMPLATE) or facebook_template.DEFAULT_TEMPLATE
        )
        self.vehicle_names = parse_vehicle_names(options.get(CONF_VEHICLE_NAMES, ""))
        self.brandbase: BrandbaseVehicles | None = (
            BrandbaseVehicles(hass) if options.get(CONF_BRANDBASE, True) else None
        )

        self.profiles: dict[str, Profile] = {
            subentry_id: Profile(hass, entry.entry_id, subentry)
            for subentry_id, subentry in entry.subentries.items()
            if subentry.subentry_type == SUBENTRY_PROFILE
        }

        self.skill_map: dict[int, str] = {}
        self.group_map: dict[int, str] = {}
        self.task_map: dict[int, str] = {}
        self.history_sync_running = False
        self.history_report: dict[str, Any] | None = None
        self.combined: dict[str, Any] = {}
        self._current_user: dict[str, Any] = {}
        self._last_incident_id: int | None = None
        # Incidents for none of the profiles; FireServiceRota updates the same
        # incident often, so don't fetch them again on every state change.
        self._ignored_incident_ids: set[int] = set()
        self._incident_lock = asyncio.Lock()
        self._history_task: asyncio.Task | None = None
        self._startup_incident_task: asyncio.Task | None = None
        self._incident_enrichment_task: asyncio.Task | None = None
        self._incident_enrichment_id: int | None = None
        self._fill_latest_task: asyncio.Task | None = None
        self._unsubs: list[CALLBACK_TYPE] = []
        self._history_retry_unsub: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------------
    # Setup and lifecycle
    # ------------------------------------------------------------------

    async def _async_setup(self) -> None:
        """Load persistent state, user data and labels once during setup."""
        for profile in self.profiles.values():
            await profile.statistics.async_load()
            profile.statistics.set_mode(profile.turnout_mode)
            # Show the function's own latest incident again right away, even
            # when FireServiceRota now shows an incident of another function.
            if profile.statistics.latest_incident is not None:
                profile.latest_incident = profile.statistics.latest_incident
                if (restored_id := incident_id(profile.latest_incident)) is not None:
                    profile.restored_ids.add(restored_id)
        if self.brandbase is not None:
            await self.brandbase.async_load()
        try:
            self._current_user = await self.api.async_get_current_user()
        except BrandweerRoosterAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BrandweerRoosterApiError as err:
            raise UpdateFailed(f"Brandweerrooster-gebruiker kon niet worden geladen: {err}") from err
        try:
            await self._async_ensure_reference_data()
        except BrandweerRoosterAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BrandweerRoosterApiError as err:
            _LOGGER.warning("Kon Brandweerrooster groeps-/functienamen niet laden: %s", err)

    async def _async_update_data(self) -> dict[str, Any]:
        """Build initial data from the current FireServiceRota incident."""
        state = self.hass.states.get(self.incident_entity)
        incident_id = self._incident_id_from_state(state)
        if incident_id is not None:
            await self._async_load_incident(incident_id, state)
        return self._build_data()

    async def async_start(self) -> None:
        """Start listeners and background work."""
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [self.incident_entity], self._async_fire_service_state_changed
            )
        )
        # Month/year counters roll over at midnight without a new incident.
        self._unsubs.append(
            async_track_time_change(self.hass, self._async_midnight, hour=0, minute=0, second=5)
        )
        # Daily catch-up for incidents missed while Home Assistant was offline
        # and for later corrections of responses/assignments.
        self._unsubs.append(
            async_track_time_change(self.hass, self._async_daily_sync, hour=3, minute=17, second=0)
        )
        if self.brandbase is not None:
            self._unsubs.append(self.brandbase.async_add_listener(self.async_update_listeners))

        self._startup_incident_task = self.config_entry.async_create_background_task(
            self.hass,
            self._async_startup_incident_check(),
            f"{DOMAIN}_startup_incident_check_{self.config_entry.entry_id}",
        )

        if any(profile.latest_incident is None for profile in self.profiles.values()):
            self._fill_latest_task = self.config_entry.async_create_background_task(
                self.hass,
                self._async_fill_latest_from_history(),
                f"{DOMAIN}_fill_latest_{self.config_entry.entry_id}",
            )

        if any(not profile.statistics.initialized for profile in self.profiles.values()):
            self.async_start_history_sync()

    async def async_stop(self) -> None:
        """Stop listeners and background tasks."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._history_retry_unsub is not None:
            self._history_retry_unsub()
            self._history_retry_unsub = None
        self.api.status_listener = None
        if self.brandbase is not None:
            await self.brandbase.async_stop()
        for task in (
            self._history_task,
            self._startup_incident_task,
            self._incident_enrichment_task,
            self._fill_latest_task,
        ):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._history_task = None
        self._startup_incident_task = None
        self._incident_enrichment_task = None
        self._incident_enrichment_id = None

    # ------------------------------------------------------------------
    # Live incidents
    # ------------------------------------------------------------------

    async def _async_startup_incident_check(self) -> None:
        """Pick up an incident when FireServiceRota loads after this integration."""
        waited = 0
        while waited <= INCIDENT_ENTITY_GRACE_PERIOD:
            state = self.hass.states.get(self.incident_entity)
            if state is not None:
                self._clear_entity_issue()
                incident_id = self._incident_id_from_state(state)
                if incident_id is not None and incident_id != self._last_incident_id:
                    await self.async_process_incident(incident_id)
                if incident_id is not None or waited >= 30:
                    return
            await asyncio.sleep(STARTUP_POLL_INTERVAL)
            waited += 5
        if self.hass.states.get(self.incident_entity) is None:
            self._raise_entity_issue()

    async def _async_fire_service_state_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data.get("new_state")
        if new_state is not None:
            self._clear_entity_issue()
        incident_id = self._incident_id_from_state(new_state)
        if (
            incident_id is None
            or incident_id == self._last_incident_id
            or incident_id in self._ignored_incident_ids
        ):
            return
        await self.async_process_incident(incident_id)

    async def async_process_incident(self, incident_id: int, *, force: bool = False) -> None:
        """Fetch one incident from the API and publish it to its profiles."""
        async with self._incident_lock:
            if incident_id == self._last_incident_id and not force:
                return
            state = self.hass.states.get(self.incident_entity)
            if not await self._async_load_incident(incident_id, state):
                return
            self.async_set_updated_data(self._build_data())
            self._schedule_incident_enrichment(incident_id)

    async def async_refresh_latest_incident(self) -> None:
        """Fetch the latest incident again (service/button)."""
        incident_id = self._last_incident_id
        if incident_id is None:
            incident_id = self._incident_id_from_state(self.hass.states.get(self.incident_entity))
        if incident_id is None:
            return
        await self.async_process_incident(incident_id, force=True)

    async def _async_load_incident(self, incident_id: int, state: State | None) -> bool:
        """Fetch an incident and apply it; fall back to FireServiceRota data when the API fails.

        Returns True when at least one profile received the incident.
        """
        try:
            incident = await self.api.async_get_incident(incident_id)
        except BrandweerRoosterApiError as err:
            if isinstance(err, BrandweerRoosterAuthenticationError):
                self._start_reauth()
            if incident_id == self._last_incident_id and any(
                (profile.latest_incident or {}).get("id") == incident_id
                and not profile.latest_incident.get("_fallback")
                for profile in self.profiles.values()
            ):
                # Keep the complete data we already have for this incident.
                return True
            if type(err) is BrandweerRoosterApiError:
                # A 4xx (e.g. 403/404) means this account can't see the
                # incident, so it belongs to another station.
                _LOGGER.debug("Incident %s is niet zichtbaar voor dit account: %s", incident_id, err)
                self._ignored_incident_ids.add(incident_id)
                return False
            # FireServiceRota already contains the live alert text. Keep the
            # incident visible; the enrichment task keeps trying the API.
            _LOGGER.warning(
                "Incident %s kon niet via de API worden opgehaald (%s); FireServiceRota-gegevens worden gebruikt",
                incident_id,
                err,
            )
            incident = self._fallback_incident(incident_id, state)
            if incident is None:
                return False
        if not await self._async_apply_incident(incident):
            if not incident.get("_fallback"):
                self._ignored_incident_ids.add(incident_id)
            _LOGGER.debug("Incident %s is niet relevant voor %s", incident_id, self.config_entry.title)
            return False
        self._last_incident_id = incident_id
        return True

    async def _async_apply_incident(self, incident: dict[str, Any]) -> bool:
        """Give an incident to every relevant profile and record statistics."""
        await self._async_ensure_reference_data_safe()
        incident_id = incident.get("id")
        # FireServiceRota fallback data usually has no group/task ids; then
        # show it on every profile until the API tells which one it is for.
        broadcast = bool(incident.get("_fallback")) and not _has_scope_fields(incident)
        applied = False
        for profile in self.profiles.values():
            current = profile.latest_incident or {}
            changed = False
            if broadcast or profile.is_relevant(incident):
                applied = True
                if (
                    incident.get("_fallback")
                    and current.get("id") == incident_id
                    and not current.get("_fallback")
                ):
                    # Keep the complete API version we already have (e.g. restored).
                    continue
                if current.get("id") != incident_id:
                    profile.previous_incident = profile.latest_incident
                profile.latest_incident = incident
                changed = profile.statistics.record_incident(
                    incident, self._current_user, self.person_name, self.skill_map
                )
            elif current.get("id") == incident_id and current.get("_fallback"):
                # The API shows this alarm was not for this function after all.
                profile.latest_incident = profile.previous_incident
            else:
                continue
            # Remember the incident so the function's sensors survive a restart.
            if profile.statistics.set_latest_incident(profile.latest_incident) or changed:
                await profile.statistics.async_save()
        return applied

    def _fallback_incident(self, incident_id: int, state: State | None) -> dict[str, Any] | None:
        if state is None or self._incident_id_from_state(state) != incident_id:
            return None
        attrs = state.attributes
        incident: dict[str, Any] = {
            "_fallback": True,
            "id": incident_id,
            "body": str(state.state or ""),
            "location": str(state.state or ""),
            "prio": attrs.get("prio"),
            "type": attrs.get("type"),
            "created_at": attrs.get("created_at") or attrs.get("start_time"),
            "start_time": attrs.get("start_time") or attrs.get("created_at"),
            "latitude": attrs.get("latitude"),
            "longitude": attrs.get("longitude"),
            "formatted_address": attrs.get("formatted_address"),
        }
        groups = attrs.get("group_ids") or attrs.get("groups")
        if groups:
            incident["groups"] = groups
        if attrs.get("task_ids"):
            incident["task_ids"] = attrs.get("task_ids")
        return incident

    def _schedule_incident_enrichment(self, incident_id: int) -> None:
        """Re-fetch a new incident on a bounded, slowing schedule.

        Crew assignments and responses are often added minutes after the
        alarm. The schedule stops early once crew is known and the data no
        longer changes; this is not continuous polling.
        """
        if (
            self._incident_enrichment_task is not None
            and not self._incident_enrichment_task.done()
            and self._incident_enrichment_id == incident_id
        ):
            return
        if self._incident_enrichment_task is not None and not self._incident_enrichment_task.done():
            self._incident_enrichment_task.cancel()

        self._incident_enrichment_id = incident_id
        self._incident_enrichment_task = self.config_entry.async_create_background_task(
            self.hass,
            self._async_enrich_incident(incident_id),
            f"{DOMAIN}_incident_enrichment_{self.config_entry.entry_id}_{incident_id}",
        )

    async def _async_enrich_incident(self, incident_id: int) -> None:
        previous: dict[str, Any] | None = None
        try:
            for delay in ENRICHMENT_DELAYS:
                await asyncio.sleep(delay)
                if incident_id != self._last_incident_id:
                    return
                try:
                    incident = await self.api.async_get_incident(incident_id)
                except BrandweerRoosterAuthenticationError:
                    self._start_reauth()
                    return
                except BrandweerRoosterApiError as err:
                    _LOGGER.debug("Incident %s kon niet worden verrijkt: %s", incident_id, err)
                    continue

                changed = incident != previous
                if changed:
                    if not await self._async_apply_incident(incident):
                        self.async_set_updated_data(self._build_data())
                        return
                    self.async_set_updated_data(self._build_data())

                if not _incident_needs_enrichment(incident) and not changed:
                    _LOGGER.debug("Incident %s is compleet en stabiel; verrijking gestopt", incident_id)
                    return
                previous = incident
        finally:
            if self._incident_enrichment_id == incident_id:
                self._incident_enrichment_task = None
                self._incident_enrichment_id = None

    async def _async_fill_latest_from_history(self) -> None:
        """Give functions without a stored latest incident the most recent one from the API.

        Runs once after updating from a version that didn't store it (or for a
        new function). The incident is shown, not announced as new and not
        counted again (the history sync records statistics).
        """
        missing = [profile for profile in self.profiles.values() if profile.latest_incident is None]
        candidates: dict[str, dict[str, Any]] = {}
        try:
            for page in range(1, FILL_LATEST_MAX_PAGES + 1):
                if page > 1:
                    await asyncio.sleep(HISTORY_PAGE_DELAY)
                incidents = await self.api.async_get_incidents(per_page=HISTORY_PAGE_SIZE, page=page)
                for incident in incidents:
                    for profile in missing:
                        best = candidates.get(profile.subentry_id)
                        if profile.is_relevant(incident) and (best is None or _newer(incident, best)):
                            candidates[profile.subentry_id] = incident
                if not incidents or all(profile.subentry_id in candidates for profile in missing):
                    break
            details: dict[Any, dict[str, Any]] = {}
            for subentry_id, incident in candidates.items():
                profile = self.profiles[subentry_id]
                if profile.latest_incident is not None:
                    continue  # a live incident arrived meanwhile
                key = incident.get("id")
                if key not in details:
                    await asyncio.sleep(HISTORY_DETAIL_DELAY)
                    details[key] = await self.api.async_get_incident(int(key))
                if profile.latest_incident is not None:
                    continue
                profile.latest_incident = details[key]
                if (restored_id := incident_id(details[key])) is not None:
                    profile.restored_ids.add(restored_id)
                if profile.statistics.set_latest_incident(details[key]):
                    await profile.statistics.async_save()
        except BrandweerRoosterAuthenticationError:
            self._start_reauth()
            return
        except BrandweerRoosterApiError as err:
            _LOGGER.debug("Laatste incident per functie kon niet uit de historie worden gehaald: %s", err)
            return
        if candidates:
            self.async_set_updated_data(self._build_data())

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    @callback
    def async_start_history_sync(self, *, reset: bool = False) -> None:
        """Start (or restart) the throttled history synchronisation."""
        if self._history_retry_unsub is not None:
            self._history_retry_unsub()
            self._history_retry_unsub = None
        if self._history_task is not None and not self._history_task.done():
            if not reset:
                return
            self._history_task.cancel()
        if reset:
            for profile in self.profiles.values():
                profile.statistics.reset_history()
        self._history_task = self.config_entry.async_create_background_task(
            self.hass,
            self._async_history_sync(),
            f"{DOMAIN}_history_sync_{self.config_entry.entry_id}",
        )

    async def _async_history_sync(self) -> None:
        """Synchronise history for profiles that need it, in the background, throttled."""
        targets = [profile for profile in self.profiles.values() if not profile.statistics.initialized]
        if not targets:
            return
        page = min(profile.statistics.history_page for profile in targets)
        first = True
        previous_ids: set[Any] = set()
        cancelled = False
        self.history_sync_running = True
        report = self.history_report = _new_report(page, targets)
        self.async_update_listeners()
        try:
            while True:
                if not first:
                    await asyncio.sleep(HISTORY_PAGE_DELAY)
                first = False
                incidents = await self.api.async_get_incidents(per_page=HISTORY_PAGE_SIZE, page=page)
                # The API may return fewer items per page than requested (it
                # caps per_page), so only an empty page - or the same page
                # again - marks the end of the history.
                ids = {incident.get("id") for incident in incidents}
                repeated = bool(incidents) and ids == previous_ids
                if incidents and not repeated:
                    report["paginas"] += 1
                    await self._async_record_page(incidents, targets, report)
                    self.async_update_listeners()  # show progress in the attributes
                done = not incidents or repeated or page >= HISTORY_MAX_PAGES
                previous_ids = ids
                page += 1
                for profile in targets:
                    await profile.statistics.async_save(
                        history_complete=True if done else False,
                        history_page=1 if done else page,
                    )
                if done:
                    report["status"] = "klaar"
                    _LOGGER.info("Historische Brandweerrooster-statistieken zijn gesynchroniseerd: %s", report)
                    return
        except BrandweerRoosterRateLimitError as err:
            delay = err.retry_after or RATE_LIMIT_DEFAULT_RETRY
            report["status"] = f"gepauzeerd door rate-limit, nieuwe poging over {delay} s"
            _LOGGER.warning("Historische synchronisatie gepauzeerd door rate-limit; nieuwe poging over %s s", delay)
            self._history_retry_unsub = async_call_later(self.hass, delay, self._async_resume_history)
        except BrandweerRoosterAuthenticationError:
            report["status"] = "gestopt: opnieuw aanmelden nodig"
            self._start_reauth()
        except BrandweerRoosterApiError as err:
            report["status"] = f"onderbroken ({err}), nieuwe poging over 1 uur"
            _LOGGER.warning("Historische synchronisatie onderbroken (%s); nieuwe poging over 1 uur", err)
            self._history_retry_unsub = async_call_later(self.hass, 3600, self._async_resume_history)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as err:
            report["status"] = f"fout: {type(err).__name__}"
            _LOGGER.exception("Onverwachte fout tijdens historische synchronisatie")
        finally:
            self.history_sync_running = False
            for profile in targets:
                report["per_functie"][profile.name]["vastgelegd"] = len(profile.statistics.events)
            if not cancelled:
                self._refresh_statistics_data()

    @callback
    def _async_resume_history(self, _now: datetime) -> None:
        self._history_retry_unsub = None
        self.async_start_history_sync()

    async def _async_record_page(
        self,
        incidents: list[dict[str, Any]],
        targets: list[Profile],
        report: dict[str, Any] | None = None,
    ) -> None:
        """Record a page of incidents for the target profiles, fetching details when needed."""
        report = report if report is not None else _new_report(1, targets)
        await self._async_ensure_reference_data_safe()
        for incident in incidents:
            report["incidenten"] += 1
            detail = incident
            if _has_scope_fields(incident) and not any(p.is_relevant(incident) for p in targets):
                _add_sample(report, incident)
                continue
            if incident.get("id") is not None and (
                not incident.get("incident_responses") or not _has_scope_fields(incident)
            ):
                await asyncio.sleep(HISTORY_DETAIL_DELAY)
                try:
                    detail = await self.api.async_get_incident(int(incident["id"]))
                except (BrandweerRoosterRateLimitError, BrandweerRoosterAuthenticationError):
                    raise
                except BrandweerRoosterApiError as err:
                    _LOGGER.debug("Incident %s kon niet worden verrijkt: %s", incident.get("id"), err)
                    report["detail_mislukt"] += 1
                    continue
                report["details_opgehaald"] += 1
            relevant = [profile for profile in targets if profile.is_relevant(detail)]
            if not relevant:
                _add_sample(report, detail)
                continue
            report["relevant"] += 1
            response = find_user_response(detail, self._current_user, self.person_name)
            if response is None:
                report["zonder_jouw_reactie"] += 1
                # Standby duties count by their "Piketdienst" switch, not by a response.
                relevant = [p for p in relevant if p.turnout_mode == TURNOUT_MODE_DUTY]
            else:
                report["met_jouw_reactie"] += 1
                key = (
                    f"{response.get('status') or '-'} / {response.get('reported_status') or '-'}"
                    f" / dienst={response.get('on_duty')}"
                )
                statuses: dict[str, int] = report["jouw_statussen"]
                statuses[key] = statuses.get(key, 0) + 1
            for profile in relevant:
                report["per_functie"][profile.name]["relevant"] += 1
                profile.statistics.record_incident(detail, self._current_user, self.person_name, self.skill_map)

    async def _async_daily_sync(self, _now: datetime) -> None:
        """Catch up on the most recent incidents once a day."""
        targets = [profile for profile in self.profiles.values() if profile.statistics.initialized]
        if not targets:
            return
        try:
            incidents = await self.api.async_get_incidents(per_page=HISTORY_PAGE_SIZE, page=1)
            await self._async_record_page(incidents, targets)
        except BrandweerRoosterAuthenticationError:
            self._start_reauth()
            return
        except BrandweerRoosterApiError as err:
            _LOGGER.info("Dagelijkse statistiek-synchronisatie overgeslagen: %s", err)
            return
        for profile in targets:
            await profile.statistics.async_save()
        self._refresh_statistics_data()

    async def async_set_duty(self, profile: Profile, on: bool) -> None:
        """Turn the "Piketdienst" switch of a standby function on or off."""
        if profile.statistics.set_duty(on):
            await profile.statistics.async_save()
            _LOGGER.debug("Piketdienst %s: %s", profile.name, "aan" if on else "uit")
        self.async_set_updated_data(self._build_data())

    async def async_set_correction(self, profile: Profile, kind: str, value: int) -> None:
        """Store an own correction of the turnout counters of a function."""
        profile.statistics.set_correction(kind, value)
        await profile.statistics.async_save()
        self.async_set_updated_data(self._build_data())

    async def _async_midnight(self, _now: datetime) -> None:
        self._refresh_statistics_data()

    @callback
    def _refresh_statistics_data(self) -> None:
        self.async_set_updated_data(self._build_data())

    # ------------------------------------------------------------------
    # Messages and vehicles
    # ------------------------------------------------------------------

    def vehicle_lookup(self, code: str) -> str | None:
        """Brandbase short name (TS Echt) of a P2000 call sign, if known."""
        if self.brandbase is None:
            return None
        info = self.brandbase.lookup(code)
        return short_name(info) if info else None

    def render_message(
        self, profile: Profile, incident: dict[str, Any] | None, template: str | None = None
    ) -> str:
        """Render the dispatch message for an incident of a profile."""
        if not incident:
            return ""
        values = message_values(
            incident,
            group_map=self.group_map,
            station_group_id=profile.station_group_id,
            fallback_title=profile.name,
            vehicle_names=self.vehicle_names,
            lookup=self.vehicle_lookup,
        )
        return facebook_template.render(template or self.message_template, values)

    def unknown_vehicle_codes(self, incident: dict[str, Any] | None) -> list[str]:
        """Call signs in the alert without a name (for troubleshooting)."""
        codes = extract_vehicle_codes(incident_body(incident))
        return [
            code for code in codes if code not in self.vehicle_names and self.vehicle_lookup(code) is None
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _async_ensure_reference_data(self) -> None:
        """Load group/task/skill labels (cached after the first success)."""
        if not self.group_map:
            self.group_map = _label_map(await self.api.async_get_groups())
        if not self.task_map:
            self.task_map = _label_map(await self.api.async_get_tasks())
        if not self.skill_map:
            self.skill_map = _label_map(await self.api.async_get_skills())

    async def _async_ensure_reference_data_safe(self) -> None:
        try:
            await self._async_ensure_reference_data()
        except BrandweerRoosterAuthenticationError:
            self._start_reauth()
        except BrandweerRoosterApiError as err:
            _LOGGER.debug("Labels konden niet worden geladen: %s", err)

    @callback
    def _async_api_status_changed(self) -> None:
        self.async_update_listeners()

    @callback
    def _start_reauth(self) -> None:
        _LOGGER.warning("Brandweerrooster-inloggegevens zijn niet meer geldig; opnieuw aanmelden is nodig")
        self.config_entry.async_start_reauth(self.hass)

    def _raise_entity_issue(self) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{ISSUE_INCIDENT_ENTITY_MISSING}_{self.config_entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_INCIDENT_ENTITY_MISSING,
            translation_placeholders={"entity_id": self.incident_entity, "title": self.config_entry.title},
        )

    def _clear_entity_issue(self) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, f"{ISSUE_INCIDENT_ENTITY_MISSING}_{self.config_entry.entry_id}")

    @property
    def current_user(self) -> dict[str, Any]:
        return self._current_user

    def _build_data(self) -> dict[str, Any]:
        now = dt_util.now()
        for profile in self.profiles.values():
            profile.counts = profile.statistics.counts(now)
        self.combined = combined_counts([p.statistics for p in self.profiles.values()], now)
        return {
            "current_user": self._current_user,
            "latest_incidents": {
                subentry_id: profile.latest_incident for subentry_id, profile in self.profiles.items()
            },
            "counts": {subentry_id: profile.counts for subentry_id, profile in self.profiles.items()},
            "combined": self.combined,
        }

    @staticmethod
    def _incident_id_from_state(state: State | None) -> int | None:
        if state is None:
            return None
        raw = state.attributes.get("id") or state.attributes.get("incident_id")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None


def _new_report(page: int, targets: list[Profile]) -> dict[str, Any]:
    """Counters that explain the outcome of a history synchronisation."""
    return {
        "status": "bezig",
        "gestart": dt_util.now().isoformat(timespec="seconds"),
        "startpagina": page,
        "paginas": 0,
        "incidenten": 0,
        "details_opgehaald": 0,
        "detail_mislukt": 0,
        "relevant": 0,
        "met_jouw_reactie": 0,
        "zonder_jouw_reactie": 0,
        # "status / reported_status / on duty" of your responses.
        "jouw_statussen": {},
        "per_functie": {profile.name: {"relevant": 0, "vastgelegd": 0} for profile in targets},
        "voorbeelden_niet_relevant": [],
    }


def _add_sample(report: dict[str, Any], incident: dict[str, Any]) -> None:
    """Keep a few group/task ids of skipped incidents (no personal data)."""
    samples: list[dict[str, Any]] = report["voorbeelden_niet_relevant"]
    if len(samples) < 5:
        samples.append(
            {
                "incident_id": incident.get("id"),
                "groups": sorted(incident_groups(incident)),
                "task_ids": sorted(incident_tasks(incident)),
            }
        )


def _label_map(items: list[dict[str, Any]]) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in items:
        try:
            item_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        result[item_id] = str(item.get("name") or item.get("title") or item_id)
    return result
