"""Data coordinator for Brandweerrooster."""

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
from .const import (
    CONF_CREW_MIN_SIZE,
    CONF_FACEBOOK_TEMPLATE,
    CONF_INCIDENT_ENTITY,
    CONF_MONITORED_GROUP_IDS,
    CONF_MONITORED_TASK_IDS,
    CONF_PERSON_NAME,
    CONF_STATION_GROUP_ID,
    CONF_VEHICLE_NAMES,
    DEFAULT_CREW_MIN_SIZE,
    DEFAULT_INCIDENT_ENTITY,
    DOMAIN,
    ENRICHMENT_DELAYS,
    HISTORY_DETAIL_DELAY,
    HISTORY_MAX_PAGES,
    HISTORY_PAGE_DELAY,
    HISTORY_PAGE_SIZE,
    INCIDENT_ENTITY_GRACE_PERIOD,
    RATE_LIMIT_DEFAULT_RETRY,
)
from .helpers import get_setting
from .incident import incident_groups, incident_tasks, int_set, message_values
from .statistics import PersonalIncidentStatistics, find_user_response
from .vehicles import DEFAULT_VEHICLE_TEXT, parse_vehicle_names

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
        self.entry = entry
        self.api = api
        api.status_listener = self._async_api_status_changed

        self.station_group_id = int(get_setting(entry, CONF_STATION_GROUP_ID, 0) or 0)
        self.monitored_group_ids = int_set(get_setting(entry, CONF_MONITORED_GROUP_IDS, []))
        self.monitored_task_ids = int_set(get_setting(entry, CONF_MONITORED_TASK_IDS, []))
        self.person_name = str(get_setting(entry, CONF_PERSON_NAME, "") or "").strip()
        self.incident_entity = str(get_setting(entry, CONF_INCIDENT_ENTITY, DEFAULT_INCIDENT_ENTITY) or DEFAULT_INCIDENT_ENTITY)
        self.crew_min_size = int(get_setting(entry, CONF_CREW_MIN_SIZE, DEFAULT_CREW_MIN_SIZE) or DEFAULT_CREW_MIN_SIZE)
        self.message_template = str(
            get_setting(entry, CONF_FACEBOOK_TEMPLATE, facebook_template.DEFAULT_TEMPLATE)
            or facebook_template.DEFAULT_TEMPLATE
        )
        self.vehicle_names = parse_vehicle_names(get_setting(entry, CONF_VEHICLE_NAMES, DEFAULT_VEHICLE_TEXT))

        self.skill_map: dict[int, str] = {}
        self.group_map: dict[int, str] = {}
        self.task_map: dict[int, str] = {}
        self.statistics = PersonalIncidentStatistics(hass, entry.entry_id)
        self.history_sync_running = False
        self.history_report: dict[str, Any] | None = None
        self._current_user: dict[str, Any] = {}
        self._last_incident_id: int | None = None
        # Incidents for other stations; FireServiceRota updates the same
        # incident often, so don't fetch them again on every state change.
        self._ignored_incident_ids: set[int] = set()
        self._incident_lock = asyncio.Lock()
        self._history_task: asyncio.Task | None = None
        self._startup_incident_task: asyncio.Task | None = None
        self._incident_enrichment_task: asyncio.Task | None = None
        self._incident_enrichment_id: int | None = None
        self._unsubs: list[CALLBACK_TYPE] = []
        self._history_retry_unsub: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------------
    # Setup and lifecycle
    # ------------------------------------------------------------------

    async def _async_setup(self) -> None:
        """Load persistent state, user data and labels once during setup."""
        await self.statistics.async_load()
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
        latest: dict[str, Any] | None = None
        if incident_id is not None:
            latest = await self._async_load_incident(incident_id, state)
        if latest is None and self.data:
            latest = self.data.get("latest_incident")
        return self._build_data(latest)

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

        self._startup_incident_task = self.config_entry.async_create_background_task(
            self.hass,
            self._async_startup_incident_check(),
            f"{DOMAIN}_startup_incident_check_{self.config_entry.entry_id}",
        )

        if not self.statistics.initialized:
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
        for task in (self._history_task, self._startup_incident_task, self._incident_enrichment_task):
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
        """Fetch and publish exactly one incident from the API."""
        async with self._incident_lock:
            if incident_id == self._last_incident_id and not force:
                return
            state = self.hass.states.get(self.incident_entity)
            incident = await self._async_load_incident(incident_id, state)
            if incident is None:
                return
            self.async_set_updated_data(self._build_data(incident))
            self._schedule_incident_enrichment(incident_id)

    async def async_refresh_latest_incident(self) -> None:
        """Fetch the latest incident again (service/button)."""
        incident_id = self._last_incident_id
        if incident_id is None:
            incident_id = self._incident_id_from_state(self.hass.states.get(self.incident_entity))
        if incident_id is None:
            return
        await self.async_process_incident(incident_id, force=True)

    async def _async_load_incident(self, incident_id: int, state: State | None) -> dict[str, Any] | None:
        """Fetch an incident; fall back to the FireServiceRota state when the API fails.

        Returns None when the incident is not relevant for this entry.
        """
        try:
            incident = await self.api.async_get_incident(incident_id)
        except BrandweerRoosterApiError as err:
            if isinstance(err, BrandweerRoosterAuthenticationError):
                self._start_reauth()
            current = self.latest_incident
            if current and current.get("id") == incident_id and not current.get("_fallback"):
                # Keep the complete data we already have for this incident.
                return current
            if type(err) is BrandweerRoosterApiError:
                # A 4xx (e.g. 403/404) means this account can't see the
                # incident, so it belongs to another station.
                _LOGGER.debug("Incident %s is niet zichtbaar voor dit account: %s", incident_id, err)
                self._ignored_incident_ids.add(incident_id)
                return None
            # FireServiceRota already contains the live alert text. Keep the
            # incident visible instead of replacing it with "Geen incident".
            # The enrichment task keeps trying the API.
            _LOGGER.warning(
                "Incident %s kon niet via de API worden opgehaald (%s); FireServiceRota-gegevens worden gebruikt",
                incident_id,
                err,
            )
            incident = self._fallback_incident(incident_id, state)
        if incident is None:
            return None
        if not self._is_relevant(incident):
            if not incident.get("_fallback"):
                self._ignored_incident_ids.add(incident_id)
            _LOGGER.debug("Incident %s is niet relevant voor %s", incident_id, self.config_entry.title)
            return None
        await self._async_ensure_reference_data_safe()
        self._last_incident_id = incident_id
        await self._async_record(incident)
        return incident

    def _fallback_incident(self, incident_id: int, state: State | None) -> dict[str, Any] | None:
        if state is None or self._incident_id_from_state(state) != incident_id:
            return None
        attrs = state.attributes
        return {
            "_fallback": True,
            "id": incident_id,
            "body": str(state.state or ""),
            "location": str(state.state or ""),
            "prio": attrs.get("prio"),
            "type": attrs.get("type"),
            "created_at": attrs.get("created_at") or attrs.get("start_time"),
            "start_time": attrs.get("start_time") or attrs.get("created_at"),
            "group_ids": attrs.get("group_ids")
            or attrs.get("groups")
            or ([self.station_group_id] if self.station_group_id else []),
            "task_ids": attrs.get("task_ids") or [],
            "latitude": attrs.get("latitude"),
            "longitude": attrs.get("longitude"),
            "formatted_address": attrs.get("formatted_address"),
        }

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

                if not self._is_relevant(incident):
                    return
                await self._async_ensure_reference_data_safe()
                await self._async_record(incident)
                if incident != (self.data or {}).get("latest_incident"):
                    self.async_set_updated_data(self._build_data(incident))

                if not _incident_needs_enrichment(incident) and incident == previous:
                    _LOGGER.debug("Incident %s is compleet en stabiel; verrijking gestopt", incident_id)
                    return
                previous = incident
        finally:
            if self._incident_enrichment_id == incident_id:
                self._incident_enrichment_task = None
                self._incident_enrichment_id = None

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    async def _async_record(self, incident: dict[str, Any]) -> None:
        if self.statistics.record_incident(incident, self._current_user, self.person_name, self.skill_map):
            await self.statistics.async_save()

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
            self.statistics.reset_history()
        self._history_task = self.config_entry.async_create_background_task(
            self.hass,
            self._async_history_sync(),
            f"{DOMAIN}_history_sync_{self.config_entry.entry_id}",
        )

    async def _async_history_sync(self) -> None:
        """Synchronise personal history once, in the background, with throttling."""
        page = self.statistics.history_page
        first = True
        cancelled = False
        self.history_sync_running = True
        report = self.history_report = _new_report(page)
        self.async_update_listeners()
        try:
            while True:
                if not first:
                    await asyncio.sleep(HISTORY_PAGE_DELAY)
                first = False
                incidents = await self.api.async_get_incidents(per_page=HISTORY_PAGE_SIZE, page=page)
                report["paginas"] += 1
                await self._async_record_page(incidents, report)
                page += 1
                done = len(incidents) < HISTORY_PAGE_SIZE or page > HISTORY_MAX_PAGES
                await self.statistics.async_save(
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
            report["vastgelegd_totaal"] = len(self.statistics.events)
            if not cancelled:
                self._refresh_statistics_data()

    @callback
    def _async_resume_history(self, _now: datetime) -> None:
        self._history_retry_unsub = None
        self.async_start_history_sync()

    async def _async_record_page(
        self, incidents: list[dict[str, Any]], report: dict[str, Any] | None = None
    ) -> None:
        """Record a page of incidents, fetching details when the list lacks them."""
        report = report if report is not None else _new_report(1)
        await self._async_ensure_reference_data_safe()
        for incident in incidents:
            report["incidenten"] += 1
            detail = incident
            needs_detail = incident.get("id") is not None and (
                not incident.get("incident_responses") or not _has_scope_fields(incident)
            )
            if not self._is_relevant(incident) and _has_scope_fields(incident):
                _add_sample(report, incident)
                continue
            if needs_detail:
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
                if not self._is_relevant(detail):
                    _add_sample(report, detail)
                    continue
            report["relevant"] += 1
            if find_user_response(detail, self._current_user, self.person_name) is None:
                report["zonder_jouw_reactie"] += 1
                continue
            report["met_jouw_reactie"] += 1
            self.statistics.record_incident(detail, self._current_user, self.person_name, self.skill_map)

    async def _async_daily_sync(self, _now: datetime) -> None:
        """Catch up on the most recent incidents once a day."""
        if not self.statistics.initialized:
            return
        try:
            incidents = await self.api.async_get_incidents(per_page=50, page=1)
            await self._async_record_page(incidents)
        except BrandweerRoosterAuthenticationError:
            self._start_reauth()
            return
        except BrandweerRoosterApiError as err:
            _LOGGER.info("Dagelijkse statistiek-synchronisatie overgeslagen: %s", err)
            return
        await self.statistics.async_save()
        self._refresh_statistics_data()

    async def _async_midnight(self, _now: datetime) -> None:
        self._refresh_statistics_data()

    @callback
    def _refresh_statistics_data(self) -> None:
        data = dict(self.data or {})
        data["statistics"] = self.statistics.counts(dt_util.now())
        data["current_user"] = self._current_user
        self.async_set_updated_data(data)

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def render_message(self, incident: dict[str, Any] | None, template: str | None = None) -> str:
        """Render the dispatch message for an incident."""
        if not incident:
            return ""
        values = message_values(
            incident,
            group_map=self.group_map,
            station_group_id=self.station_group_id,
            fallback_title=self.config_entry.title,
            vehicle_names=self.vehicle_names,
        )
        return facebook_template.render(template or self.message_template, values)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _async_ensure_reference_data(self) -> None:
        """Load group/task/skill labels (cached after the first success)."""
        if not self.group_map:
            groups = await self.api.async_get_groups()
            self.group_map = _label_map(groups)
        if not self.task_map:
            tasks = await self.api.async_get_tasks()
            self.task_map = _label_map(tasks)
        if not self.skill_map:
            skills = await self.api.async_get_skills()
            self.skill_map = _label_map(skills)

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

    @property
    def latest_incident(self) -> dict[str, Any] | None:
        return (self.data or {}).get("latest_incident")

    def _build_data(self, latest: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "current_user": self._current_user,
            "latest_incident": latest,
            "statistics": self.statistics.counts(dt_util.now()),
        }

    def _is_relevant(self, incident: dict[str, Any]) -> bool:
        if not (self.monitored_group_ids or self.monitored_task_ids or self.station_group_id):
            return True
        groups = incident_groups(incident)
        if self.station_group_id and self.station_group_id in groups:
            return True
        if groups & self.monitored_group_ids:
            return True
        return bool(incident_tasks(incident) & self.monitored_task_ids)

    @staticmethod
    def _incident_id_from_state(state: State | None) -> int | None:
        if state is None:
            return None
        raw = state.attributes.get("id") or state.attributes.get("incident_id")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None


def _new_report(page: int) -> dict[str, Any]:
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
        "vastgelegd_totaal": 0,
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


def _has_scope_fields(incident: dict[str, Any]) -> bool:
    return any(key in incident for key in ("groups", "group_ids", "task_ids"))


def _label_map(items: list[dict[str, Any]]) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in items:
        try:
            item_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        result[item_id] = str(item.get("name") or item.get("title") or item_id)
    return result
