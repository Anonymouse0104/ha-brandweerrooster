"""Data coordinator for Brandweerrooster."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import BrandweerRoosterApi, BrandweerRoosterApiError, BrandweerRoosterRateLimitError
from .const import (
    CONF_MONITORED_GROUP_IDS,
    CONF_MONITORED_TASK_IDS,
    CONF_PERSON_NAME,
    CONF_STATION_GROUP_ID,
    DOMAIN,
    FIRESERVICEROTA_INCIDENT_ENTITY,
    HISTORY_PAGE_DELAY,
)
from .statistics import PersonalIncidentStatistics

_LOGGER = logging.getLogger(__name__)


class BrandweerRoosterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Maintain Brandweerrooster data and react to FireServiceRota incidents."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: BrandweerRoosterApi) -> None:
        self.entry = entry
        self.api = api
        self.station_group_id = int(entry.data.get(CONF_STATION_GROUP_ID, 0) or 0)
        self.monitored_group_ids = {int(x) for x in entry.data.get(CONF_MONITORED_GROUP_IDS, [])}
        self.monitored_task_ids = {int(x) for x in entry.data.get(CONF_MONITORED_TASK_IDS, [])}
        self.person_name = str(entry.data.get(CONF_PERSON_NAME, "")).strip()
        self.skill_map: dict[int, str] = {}
        self.group_map: dict[int, str] = {}
        self.task_map: dict[int, str] = {}
        self.statistics = PersonalIncidentStatistics(hass, entry.entry_id)
        self._current_user: dict[str, Any] = {}
        self._last_incident_id: int | None = None
        self._incident_lock = asyncio.Lock()
        self._history_task: asyncio.Task | None = None
        self._unsub_incident_listener = None
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
            always_update=False,
        )

    async def _async_setup(self) -> None:
        """Load persistent state and user data once during setup."""
        await self.statistics.async_load()
        self._current_user = await self.api.async_get_current_user()

    async def _async_update_data(self) -> dict[str, Any]:
        """Build initial data from the current FireServiceRota incident only."""
        state = self.hass.states.get(FIRESERVICEROTA_INCIDENT_ENTITY)
        latest = await self._async_fetch_incident_from_state(state)
        return self._build_data(latest)

    async def async_start(self) -> None:
        """Start listening for new FireServiceRota incidents."""
        if self._unsub_incident_listener is None:
            self._unsub_incident_listener = async_track_state_change_event(
                self.hass, [FIRESERVICEROTA_INCIDENT_ENTITY], self._async_fire_service_state_changed
            )
        if not self.statistics.initialized and self._history_task is None:
            self._history_task = self.hass.async_create_task(
                self._async_initial_history_sync(),
                f"{DOMAIN}_history_sync_{self.entry.entry_id}",
            )

    async def async_stop(self) -> None:
        """Stop listeners and background tasks."""
        if self._unsub_incident_listener is not None:
            self._unsub_incident_listener()
            self._unsub_incident_listener = None
        if self._history_task is not None and not self._history_task.done():
            self._history_task.cancel()
            try:
                await self._history_task
            except asyncio.CancelledError:
                pass
        self._history_task = None

    async def _async_fire_service_state_changed(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        incident_id = self._incident_id_from_state(new_state)
        if incident_id is None or incident_id == self._last_incident_id:
            return
        await self.async_process_incident(incident_id)

    async def async_process_incident(self, incident_id: int) -> None:
        """Fetch and process exactly one new incident from the API."""
        async with self._incident_lock:
            if incident_id == self._last_incident_id:
                return
            try:
                incident = await self.api.async_get_incident(incident_id)
                if not self._is_relevant(incident):
                    _LOGGER.debug("Incident %s is niet relevant voor %s", incident_id, self.entry.title)
                    return
                await self._async_ensure_reference_data()
                self._last_incident_id = incident_id
                self.statistics.record_incident(incident, self._current_user, self.person_name)
                await self.statistics.async_save(history_complete=self.statistics.initialized)
                self.async_set_updated_data(self._build_data(incident))
            except BrandweerRoosterRateLimitError as err:
                _LOGGER.warning(
                    "Brandweerrooster rate-limit bij incident %s; %s",
                    incident_id,
                    err,
                )
            except BrandweerRoosterApiError as err:
                _LOGGER.warning("Incident %s kon niet worden opgehaald: %s", incident_id, err)

    async def _async_fetch_incident_from_state(self, state) -> dict[str, Any] | None:
        incident_id = self._incident_id_from_state(state)
        if incident_id is None:
            return None
        try:
            incident = await self.api.async_get_incident(incident_id)
        except BrandweerRoosterApiError as err:
            _LOGGER.warning("Huidig FireServiceRota-incident %s kon niet worden opgehaald: %s", incident_id, err)
            return None
        if not self._is_relevant(incident):
            return None
        await self._async_ensure_reference_data()
        self._last_incident_id = incident_id
        if self.statistics.record_incident(incident, self._current_user, self.person_name):
            await self.statistics.async_save(history_complete=self.statistics.initialized)
        return incident

    async def _async_ensure_reference_data(self) -> None:
        """Load labels only when incident data actually needs them."""
        if not self.group_map:
            groups = await self.api.async_get_groups()
            self.group_map = {int(item["id"]): str(item.get("name") or item.get("title") or item["id"]) for item in groups if item.get("id") is not None}
        if not self.task_map:
            tasks = await self.api.async_get_tasks()
            self.task_map = {int(item["id"]): str(item.get("name") or item.get("title") or item["id"]) for item in tasks if item.get("id") is not None}
        if not self.skill_map:
            skills = await self.api.async_get_skills()
            self.skill_map = {int(item["id"]): str(item.get("name") or item.get("title") or item["id"]) for item in skills if item.get("id") is not None}

    async def _async_initial_history_sync(self) -> None:
        """Synchronize personal history once, in the background, with throttling."""
        page = self.statistics.history_page
        try:
            while True:
                await asyncio.sleep(HISTORY_PAGE_DELAY if page > self.statistics.history_page else 0)
                incidents = await self.api.async_get_incidents(per_page=100, page=page)
                if not incidents:
                    await self.statistics.async_save(history_complete=True, history_page=1)
                    self._refresh_statistics_data()
                    _LOGGER.info("Historische Brandweerrooster-statistieken zijn gesynchroniseerd")
                    return

                for incident in incidents:
                    if not self._is_relevant(incident):
                        continue
                    detail = incident
                    if incident.get("id") is not None and not incident.get("incident_responses") and not incident.get("incident_skill_assignments"):
                        try:
                            detail = await self.api.async_get_incident(int(incident["id"]))
                        except BrandweerRoosterApiError as err:
                            _LOGGER.debug("Incident %s kon niet worden verrijkt tijdens historie-sync: %s", incident.get("id"), err)
                            continue
                    self.statistics.record_incident(detail, self._current_user, self.person_name)

                page += 1
                await self.statistics.async_save(history_complete=False, history_page=page)
                if len(incidents) < 100 or page > 1000:
                    await self.statistics.async_save(history_complete=True, history_page=1)
                    self._refresh_statistics_data()
                    return
                await asyncio.sleep(HISTORY_PAGE_DELAY)
        except BrandweerRoosterRateLimitError as err:
            _LOGGER.warning("Historische synchronisatie gepauzeerd door rate-limit: %s", err)
        except asyncio.CancelledError:
            raise
        except BrandweerRoosterApiError as err:
            _LOGGER.warning("Historische synchronisatie gestopt: %s", err)
        except Exception:
            _LOGGER.exception("Onverwachte fout tijdens historische synchronisatie")

    def _refresh_statistics_data(self) -> None:
        data = dict(self.data or {})
        data["statistics"] = self.statistics.counts(dt_util.now())
        data["current_user"] = self._current_user
        self.async_set_updated_data(data)

    def _build_data(self, latest: dict[str, Any] | None) -> dict[str, Any]:
        relevant = [latest] if latest else []
        return {
            "current_user": self._current_user,
            "latest_incident": latest,
            "incident_count": len(relevant),
            "incidents": relevant,
            "statistics": self.statistics.counts(dt_util.now()),
        }

    def _is_relevant(self, incident: dict[str, Any]) -> bool:
        if not (self.monitored_group_ids or self.monitored_task_ids or self.station_group_id):
            return True
        groups = self._int_set(incident.get("groups") or incident.get("group_ids") or [])
        tasks = self._int_set(incident.get("task_ids") or [])
        if self.station_group_id and self.station_group_id in groups:
            return True
        if groups & self.monitored_group_ids:
            return True
        if tasks & self.monitored_task_ids:
            return True
        return False

    @staticmethod
    def _incident_id_from_state(state) -> int | None:
        if state is None:
            return None
        raw = state.attributes.get("id") or state.attributes.get("incident_id")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _int_set(values: list[Any]) -> set[int]:
        result: set[int] = set()
        for value in values:
            try:
                result.add(int(value))
            except (TypeError, ValueError):
                continue
        return result
