"""Personal incident statistics for Brandweerrooster."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 2

# Brandweerrooster uses reported_status for the user's explicit response in the
# incident. ``dispatched`` is the status used by the existing FireServiceRota
# integration for an accepted/coming response. The additional values make the
# statistic tolerant of API versions that use a more descriptive status.
POSITIVE_RESPONSE_STATUSES = {
    "acknowledged",
    "shown_up",
    "dispatched",
    "responded",
    "accepted",
    "coming",
    "on_the_way",
    "on-way",
    "arrived",
    "arrived_at_station",
}
NEGATIVE_RESPONSE_STATUSES = {
    "no_show",
    "declined",
    "rejected",
    "not_coming",
    "unavailable",
    "absent",
    "cancelled",
    "canceled",
}


class PersonalIncidentStatistics:
    """Persist and calculate personal incident statistics."""

    def __init__(self, hass, entry_id: str) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.statistics_{entry_id}")
        self.events: dict[str, dict[str, Any]] = {}
        self.initialized = False
        self.history_page = 1

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict):
            events = data.get("events", {})
            if isinstance(events, dict):
                self.events = {str(k): v for k, v in events.items() if isinstance(v, dict)}
        if isinstance(data, dict):
            self.initialized = bool(data.get("history_complete"))
            try:
                self.history_page = max(1, int(data.get("history_page", 1)))
            except (TypeError, ValueError):
                self.history_page = 1
        else:
            self.initialized = False

    async def async_save(self, *, history_complete: bool | None = None, history_page: int | None = None) -> None:
        if history_complete is not None:
            self.initialized = history_complete
        if history_page is not None:
            self.history_page = max(1, history_page)
        await self._store.async_save(
            {
                "history_complete": self.initialized,
                "history_page": self.history_page,
                "events": self.events,
            }
        )

    def record_incident(self, incident: dict[str, Any], user: dict[str, Any], person_name: str) -> bool:
        """Record a qualifying personal response. Returns True when changed."""
        incident_id = incident.get("id")
        if incident_id is None:
            return False

        response = _find_user_response(incident, user, person_name)
        if not response or not _response_is_positive(response):
            # A previously recorded incident can be corrected later if the
            # response changed to a decline/cancelled state.
            if str(incident_id) in self.events:
                del self.events[str(incident_id)]
                return True
            return False

        assigned = _user_is_assigned(incident, user, person_name)
        timestamp = _incident_timestamp(incident)
        event_type = "opgekomen_ingedeeld" if assigned else "opgekomen_niet_ingedeeld"
        new_event = {
            "incident_id": incident_id,
            "timestamp": timestamp,
            "type": event_type,
            "response_status": response.get("reported_status") or response.get("status"),
            "response_id": response.get("id"),
        }
        key = str(incident_id)
        if self.events.get(key) == new_event:
            return False
        self.events[key] = new_event
        return True

    def counts(self, now: datetime) -> dict[str, int]:
        month = 0
        year = 0
        total = 0
        not_assigned = 0
        for event in self.events.values():
            if event.get("type") == "opgekomen_ingedeeld":
                total += 1
                try:
                    timestamp = datetime.fromisoformat(str(event.get("timestamp")))
                except (TypeError, ValueError):
                    continue
                if timestamp.year == now.year:
                    year += 1
                    if timestamp.month == now.month:
                        month += 1
            elif event.get("type") == "opgekomen_niet_ingedeeld":
                not_assigned += 1
        return {
            "month": month,
            "year": year,
            "total": total,
            "not_assigned": not_assigned,
        }


def _find_user_response(
    incident: dict[str, Any], user: dict[str, Any], person_name: str
) -> dict[str, Any] | None:
    user_id = user.get("id")
    wanted_name = _normalize_name(person_name)
    for response in incident.get("incident_responses") or []:
        if not isinstance(response, dict):
            continue
        if user_id is not None and str(response.get("user_id")) == str(user_id):
            return response
        names = (
            response.get("user_name"),
            response.get("user_nickname"),
            response.get("name"),
        )
        if wanted_name and any(_normalize_name(name) == wanted_name for name in names if name):
            return response
    return None


def _user_is_assigned(
    incident: dict[str, Any], user: dict[str, Any], person_name: str
) -> bool:
    user_id = user.get("id")
    wanted_name = _normalize_name(person_name)
    for assignment in incident.get("incident_skill_assignments") or []:
        if not isinstance(assignment, dict):
            continue
        if user_id is not None and str(assignment.get("user_id")) == str(user_id):
            return True
        assignment_name = assignment.get("user_name") or assignment.get("name")
        if wanted_name and assignment_name and _normalize_name(assignment_name) == wanted_name:
            return True
    return False


def _response_is_positive(response: dict[str, Any]) -> bool:
    # Prefer reported_status because that represents the user's reported
    # response. Fall back to status when the API doesn't provide it.
    status = response.get("reported_status") or response.get("status")
    if status is None:
        return False
    normalized = str(status).strip().lower().replace(" ", "_")
    if normalized in NEGATIVE_RESPONSE_STATUSES:
        return False
    return normalized in POSITIVE_RESPONSE_STATUSES


def _incident_timestamp(incident: dict[str, Any]) -> str:
    value = incident.get("start_time") or incident.get("created_at")
    if value:
        return str(value)
    return datetime.now().astimezone().isoformat()


def _normalize_name(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().split())
