"""Personal incident statistics for Brandweerrooster."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STATISTICS_SCHEMA
from .incident import (
    category,
    classification,
    format_priority,
    incident_body,
    response_is_positive,
    split_p2000,
)

STORAGE_VERSION = 2

TYPE_ASSIGNED = "opgekomen_ingedeeld"
TYPE_NOT_ASSIGNED = "opgekomen_niet_ingedeeld"
TYPE_NO_TURNOUT = "geen_opkomst"

DAYPARTS = (
    (0, 6, "nacht"),
    (6, 12, "ochtend"),
    (12, 18, "middag"),
    (18, 24, "avond"),
)


class PersonalIncidentStatistics:
    """Persist and calculate personal incident statistics."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.statistics_{entry_id}")
        self.events: dict[str, dict[str, Any]] = {}
        self.initialized = False
        self.history_page = 1

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if not isinstance(data, dict):
            self.initialized = False
            return
        events = data.get("events", {})
        if isinstance(events, dict):
            self.events = {str(k): v for k, v in events.items() if isinstance(v, dict)}
        self.initialized = bool(data.get("history_complete"))
        try:
            self.history_page = max(1, int(data.get("history_page", 1)))
        except (TypeError, ValueError):
            self.history_page = 1
        if int(data.get("schema", 2) or 2) < STATISTICS_SCHEMA and self.initialized:
            # Older data lacks per-incident details (function, category) and
            # declined alarms. Re-sync history once; existing events are kept
            # and simply overwritten with richer data.
            self.initialized = False
            self.history_page = 1

    async def async_save(self, *, history_complete: bool | None = None, history_page: int | None = None) -> None:
        if history_complete is not None:
            self.initialized = history_complete
        if history_page is not None:
            self.history_page = max(1, history_page)
        await self._store.async_save(
            {
                "schema": STATISTICS_SCHEMA,
                "history_complete": self.initialized,
                "history_page": self.history_page,
                "events": self.events,
            }
        )

    def reset_history(self) -> None:
        """Mark history as incomplete so it is synchronised again."""
        self.initialized = False
        self.history_page = 1

    def record_incident(
        self,
        incident: dict[str, Any],
        user: dict[str, Any],
        person_name: str,
        skill_map: dict[int, str] | None = None,
    ) -> bool:
        """Record the user's response to an incident. Returns True when changed.

        Incidents without a response from the user (or incomplete fallback
        data built from the FireServiceRota state) never remove an existing
        record; a recorded incident only changes when the API reports a
        different response for this user.
        """
        incident_id = incident.get("id")
        if incident_id is None or incident.get("_fallback"):
            return False

        response = find_user_response(incident, user, person_name)
        if not response:
            return False

        if response_is_positive(response):
            assigned_functions = user_functions(incident, user, person_name, skill_map or {})
            event_type = TYPE_ASSIGNED if assigned_functions is not None else TYPE_NOT_ASSIGNED
        else:
            assigned_functions = None
            event_type = TYPE_NO_TURNOUT

        melding = split_p2000(incident_body(incident))["melding"]
        new_event = {
            "incident_id": incident_id,
            "timestamp": incident_timestamp(incident),
            "type": event_type,
            "response_status": response.get("reported_status") or response.get("status"),
            "response_id": response.get("id"),
            "functies": assigned_functions or [],
            "classificatie": classification(melding, str(incident.get("type") or "")),
            "categorie": category(melding),
            "prioriteit": format_priority(incident.get("prio")),
        }
        key = str(incident_id)
        if self.events.get(key) == new_event:
            return False
        self.events[key] = new_event
        return True

    def counts(self, now: datetime) -> dict[str, Any]:
        """Calculate all statistics relative to ``now`` (local time)."""
        now = dt_util.as_local(now)
        previous_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)

        month = year = total = not_assigned = previous = 0
        alarmed_year = turned_out_year = 0
        functions_total: dict[str, int] = {}
        functions_year: dict[str, int] = {}
        categories_year: dict[str, int] = {}
        classifications_year: dict[str, int] = {}
        dayparts_year: dict[str, int] = {name: 0 for _, _, name in DAYPARTS}
        last_turnout: datetime | None = None

        for event in self.events.values():
            event_type = event.get("type")
            timestamp = parse_timestamp(event.get("timestamp"))
            this_year = timestamp is not None and timestamp.year == now.year

            if this_year:
                alarmed_year += 1
                if event_type in (TYPE_ASSIGNED, TYPE_NOT_ASSIGNED):
                    turned_out_year += 1

            if event_type == TYPE_NOT_ASSIGNED:
                not_assigned += 1
                continue
            if event_type != TYPE_ASSIGNED:
                continue

            total += 1
            for function in event.get("functies") or []:
                functions_total[function] = functions_total.get(function, 0) + 1
            if timestamp is None:
                continue
            if last_turnout is None or timestamp > last_turnout:
                last_turnout = timestamp
            if (timestamp.year, timestamp.month) == previous_month:
                previous += 1
            if not this_year:
                continue
            year += 1
            if timestamp.month == now.month:
                month += 1
            for function in event.get("functies") or []:
                functions_year[function] = functions_year.get(function, 0) + 1
            cat = event.get("categorie") or "Overig"
            categories_year[cat] = categories_year.get(cat, 0) + 1
            cls = event.get("classificatie") or "Onbekend"
            classifications_year[cls] = classifications_year.get(cls, 0) + 1
            for start, end, name in DAYPARTS:
                if start <= timestamp.hour < end:
                    dayparts_year[name] += 1

        return {
            "month": month,
            "previous_month": previous,
            "year": year,
            "total": total,
            "not_assigned": not_assigned,
            "response_rate_year": round(100 * turned_out_year / alarmed_year, 1) if alarmed_year else None,
            "alarmed_year": alarmed_year,
            "turned_out_year": turned_out_year,
            "functions_total": _sorted(functions_total),
            "functions_year": _sorted(functions_year),
            "categories_year": _sorted(categories_year),
            "classifications_year": _sorted(classifications_year),
            "dayparts_year": dayparts_year,
            "last_turnout": last_turnout,
        }


def _sorted(counter: dict[str, int]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a stored timestamp to an aware local datetime."""
    if not value:
        return None
    try:
        parsed = dt_util.parse_datetime(str(value))
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_local(parsed)


def find_user_response(
    incident: dict[str, Any], user: dict[str, Any], person_name: str
) -> dict[str, Any] | None:
    user_id = user.get("id")
    wanted_name = _normalize_name(person_name)
    by_name: dict[str, Any] | None = None
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
        if by_name is None and wanted_name and any(_normalize_name(name) == wanted_name for name in names if name):
            by_name = response
    # A name match is only a fallback when the user id is not available.
    if by_name is not None and (user_id is None or by_name.get("user_id") is None):
        return by_name
    return None


def user_functions(
    incident: dict[str, Any],
    user: dict[str, Any],
    person_name: str,
    skill_map: dict[int, str],
) -> list[str] | None:
    """Return the user's assigned functions, or None when not assigned."""
    user_id = user.get("id")
    wanted_name = _normalize_name(person_name)
    found = False
    functions: list[str] = []
    for assignment in incident.get("incident_skill_assignments") or []:
        if not isinstance(assignment, dict):
            continue
        matches = user_id is not None and str(assignment.get("user_id")) == str(user_id)
        if not matches and (user_id is None or assignment.get("user_id") is None):
            assignment_name = assignment.get("user_name") or assignment.get("name")
            matches = bool(wanted_name and assignment_name and _normalize_name(assignment_name) == wanted_name)
        if not matches:
            continue
        found = True
        skill_ids = assignment.get("skill_ids")
        if not isinstance(skill_ids, list):
            skill_ids = [skill_ids] if skill_ids not in (None, "") else []
        for skill_id in skill_ids:
            try:
                name = skill_map.get(int(skill_id), f"Skill {skill_id}")
            except (TypeError, ValueError):
                name = f"Skill {skill_id}"
            if name not in functions:
                functions.append(name)
    return functions if found else None


def incident_timestamp(incident: dict[str, Any]) -> str:
    value = incident.get("start_time") or incident.get("created_at")
    if value:
        return str(value)
    return dt_util.now().isoformat()


def _normalize_name(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().split())
