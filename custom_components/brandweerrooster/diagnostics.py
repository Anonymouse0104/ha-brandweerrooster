"""Diagnostics download for Brandweerrooster (replaces the old diagnostic sensor)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import BrandweerRoosterConfigEntry

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "person_name",
    "email",
    "phone",
    "phone_number",
    "mobile",
    "address",
    "user_name",
    "user_nickname",
    "name",
    "nickname",
    "full_name",
    "first_name",
    "last_name",
    "access_token",
    "refresh_token",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BrandweerRoosterConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    incident = coordinator.latest_incident or {}
    stats = dict(coordinator.statistics.counts(dt_util.now()))
    if stats.get("last_turnout") is not None:
        stats["last_turnout"] = stats["last_turnout"].isoformat()
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "api": {
            "available": coordinator.api.available,
            "last_error": coordinator.api.last_error,
            "last_success": coordinator.api.last_success.isoformat() if coordinator.api.last_success else None,
        },
        "incident_entity": coordinator.incident_entity,
        "incident_entity_state_present": hass.states.get(coordinator.incident_entity) is not None,
        "group_map": coordinator.group_map,
        "skill_map": coordinator.skill_map,
        "latest_incident_keys": sorted(str(key) for key in incident),
        "latest_incident": async_redact_data(incident, TO_REDACT),
        "statistics": {
            "history_complete": coordinator.statistics.initialized,
            "history_page": coordinator.statistics.history_page,
            "history_sync_running": coordinator.history_sync_running,
            "history_report": coordinator.history_report,
            "station_group_id": coordinator.station_group_id,
            "monitored_group_ids": sorted(coordinator.monitored_group_ids),
            "monitored_task_ids": sorted(coordinator.monitored_task_ids),
            "current_user_id_known": coordinator.current_user.get("id") is not None,
            "recorded_incidents": len(coordinator.statistics.events),
            "counts": stats,
        },
    }
