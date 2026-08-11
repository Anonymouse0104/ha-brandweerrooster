"""Data coordinator for Brandweerrooster."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BrandweerRoosterApi, BrandweerRoosterApiError
from .const import CONF_PERSON_NAME, DOMAIN
from .statistics import PersonalIncidentStatistics

_LOGGER = logging.getLogger(__name__)


class BrandweerRoosterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch current incident data and maintain personal statistics."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: BrandweerRoosterApi) -> None:
        self.entry = entry
        self.api = api
        self.station_group_id = int(entry.data.get("station_group_id", 0) or 0)
        self.monitored_group_ids = {int(x) for x in entry.data.get("monitored_group_ids", [])}
        self.monitored_task_ids = {int(x) for x in entry.data.get("monitored_task_ids", [])}
        self.person_name = str(entry.data.get(CONF_PERSON_NAME, "")).strip()
        self.skill_map: dict[int, str] = {}
        self.group_map: dict[int, str] = {}
        self.task_map: dict[int, str] = {}
        self.statistics = PersonalIncidentStatistics(hass, entry.entry_id)
        interval = int(entry.data.get("scan_interval", 30))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
            always_update=False,
        )

    async def _async_setup(self) -> None:
        """Load reference data and restore/synchronise statistics."""
        skills = await self.api.async_get_skills()
        groups = await self.api.async_get_groups()
        tasks = await self.api.async_get_tasks()
        self.skill_map = {int(item["id"]): str(item.get("name") or item.get("title") or item["id"]) for item in skills if item.get("id") is not None}
        self.group_map = {int(item["id"]): str(item.get("name") or item.get("title") or item["id"]) for item in groups if item.get("id") is not None}
        self.task_map = {int(item["id"]): str(item.get("name") or item.get("title") or item["id"]) for item in tasks if item.get("id") is not None}
        await self.statistics.async_load()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            current_user = await self.api.async_get_current_user()
            incidents = await self.api.async_get_incidents(per_page=100, page=1)
            if not self.statistics.initialized:
                incidents = await self._async_initial_history_sync(incidents, current_user)
            else:
                incidents = await self._async_enrich_recent_incidents(incidents, current_user)
        except BrandweerRoosterApiError as err:
            raise UpdateFailed(str(err)) from err

        relevant = [incident for incident in incidents if self._is_relevant(incident)]
        relevant.sort(key=self._incident_sort_key, reverse=True)
        latest = relevant[0] if relevant else None
        if latest and latest.get("id") is not None and not latest.get("incident_responses"):
            try:
                latest = await self.api.async_get_incident(int(latest["id"]))
                self.statistics.record_incident(latest, current_user, self.person_name)
                await self.statistics.async_save()
            except BrandweerRoosterApiError as err:
                _LOGGER.warning("Volledige details van incident %s konden niet worden opgehaald: %s", latest.get("id"), err)

        counts = self.statistics.counts(self.hass.config.now())
        return {
            "current_user": current_user,
            "latest_incident": latest,
            "incident_count": len(relevant),
            "incidents": relevant[:10],
            "statistics": counts,
        }

    async def _async_initial_history_sync(
        self, first_page: list[dict[str, Any]], current_user: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Build the persistent lifetime history once."""
        all_recent: list[dict[str, Any]] = []
        page = 1
        current_page = first_page
        while current_page:
            for incident in current_page:
                if self._is_relevant(incident):
                    detail = incident
                    if incident.get("id") is not None and not incident.get("incident_responses"):
                        try:
                            detail = await self.api.async_get_incident(int(incident["id"]))
                        except BrandweerRoosterApiError as err:
                            _LOGGER.debug("Incident %s kon niet worden verrijkt: %s", incident.get("id"), err)
                            continue
                    self.statistics.record_incident(detail, current_user, self.person_name)
                    all_recent.append(detail)
            page += 1
            # Do not refetch page 1; subsequent pages are only needed during
            # the initial historical import.
            current_page = await self.api.async_get_incidents(per_page=100, page=page)
            if page > 1000:
                _LOGGER.warning("Historische incident-synchronisatie afgebroken na 1000 pagina's")
                break
        await self.statistics.async_save()
        return all_recent

    async def _async_enrich_recent_incidents(
        self, incidents: list[dict[str, Any]], current_user: dict[str, Any]
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for incident in incidents:
            if not self._is_relevant(incident):
                continue
            detail = incident
            if incident.get("id") is not None:
                try:
                    detail = await self.api.async_get_incident(int(incident["id"]))
                except BrandweerRoosterApiError as err:
                    _LOGGER.debug("Incident %s kon niet worden verrijkt: %s", incident.get("id"), err)
            self.statistics.record_incident(detail, current_user, self.person_name)
            enriched.append(detail)
        await self.statistics.async_save()
        return enriched

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
    def _incident_sort_key(incident: dict[str, Any]) -> str:
        return str(incident.get("start_time") or incident.get("created_at") or incident.get("id") or "")

    @staticmethod
    def _int_set(values: list[Any]) -> set[int]:
        result: set[int] = set()
        for value in values:
            try:
                result.add(int(value))
            except (TypeError, ValueError):
                continue
        return result
