"""Diagnostics download for Brandweerrooster."""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

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
    # Per-person identifiers and data anywhere in the payload.
    "user_id",
    "membership_id",
    "user_photo",
    "complainant_name",
    "notes",
    "location",
}

# Only these fields of each crew member's response / assignment are kept; the
# rest (account and membership ids, photo, GPS location, ETA, response times)
# identifies colleagues and is dropped.
_RESPONSE_FIELDS = (
    "status",
    "reported_status",
    "channel",
    "group_id",
    "assigned_skill_ids",
    "active_duty_function_ids",
    "original_rank_id",
    "performed_rank_id",
    "on_duty",
    "available_at_incident_creation",
    "group_available_at_incident_creation",
    "arrived_at_station",
    "times_overridden",
)
_ASSIGNMENT_FIELDS = ("skill_ids",)


def _crew_list(items: Any, fields: tuple[str, ...], user_id: Any) -> list[dict[str, Any]]:
    """Strip a crew list to non-personal fields; mark only whether an item is yours."""
    result: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        kept = {key: item[key] for key in fields if key in item}
        kept["jij"] = user_id is not None and str(item.get("user_id")) == str(user_id)
        result.append(kept)
    return result


def redact_incident(incident: dict[str, Any], user_id: Any) -> dict[str, Any]:
    """An incident for a diagnostics file that may be attached to a public issue."""
    if not incident:
        return {}
    data = dict(incident)
    data["incident_responses"] = _crew_list(data.get("incident_responses"), _RESPONSE_FIELDS, user_id)
    data["incident_skill_assignments"] = _crew_list(
        data.get("incident_skill_assignments"), _ASSIGNMENT_FIELDS, user_id
    )
    return async_redact_data(data, TO_REDACT)


def _jsonable_counts(counts: dict[str, Any]) -> dict[str, Any]:
    result = dict(counts)
    if result.get("last_turnout") is not None:
        result["last_turnout"] = result["last_turnout"].isoformat()
    return result


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BrandweerRoosterConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    profiles: dict[str, Any] = {}
    for profile in coordinator.profiles.values():
        incident = profile.latest_incident or {}
        events = profile.statistics.events.values()
        profiles[profile.name] = {
            "group_ids": profile.group_ids_ordered,
            "task_ids": sorted(profile.task_ids),
            "turnout_mode": profile.turnout_mode,
            "crew_min_size": profile.crew_min_size,
            "legacy_ids": profile.unique_prefix == entry.entry_id,
            "latest_incident_keys": sorted(str(key) for key in incident),
            "latest_incident": redact_incident(incident, coordinator.current_user.get("id")),
            "unknown_vehicle_codes": coordinator.unknown_vehicle_codes(incident),
            "statistics": {
                "history_complete": profile.statistics.initialized,
                "history_page": profile.statistics.history_page,
                "mode": profile.statistics.mode,
                "recorded_incidents": len(profile.statistics.events),
                "recorded_by_type": dict(Counter(str(e.get("type")) for e in events)),
                "recorded_by_status": dict(Counter(str(e.get("response_status")) for e in events)),
                "counts": _jsonable_counts(profile.counts),
            },
        }
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
        "current_user_id_known": coordinator.current_user.get("id") is not None,
        "brandbase": {
            "enabled": coordinator.brandbase is not None,
            "regions_cached": coordinator.brandbase.region_count if coordinator.brandbase else 0,
            "own_vehicle_names": len(coordinator.vehicle_names),
        },
        "group_map": coordinator.group_map,
        "skill_map": coordinator.skill_map,
        "history_sync_running": coordinator.history_sync_running,
        "history_report": coordinator.history_report,
        "combined": coordinator.combined,
        "profiles": profiles,
    }
