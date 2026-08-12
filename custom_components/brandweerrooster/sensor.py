"""Sensors exposed by Brandweerrooster."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .vehicles import resolve_vehicle_names, extract_vehicle_codes
from .coordinator import BrandweerRoosterCoordinator


def _incident_coordinates(incident: dict[str, Any] | None) -> tuple[float | None, float | None]:
    """Extract latitude/longitude from an incident payload.

    Brandweerrooster and the companion FireServiceRota integration may expose
    coordinates at different nesting levels, so accept common representations
    without making assumptions about one fixed API response shape.
    """
    if not incident:
        return None, None

    latitude: float | None = None
    longitude: float | None = None

    def as_float(value: Any) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def walk(value: Any) -> None:
        nonlocal latitude, longitude
        if latitude is not None and longitude is not None:
            return
        if isinstance(value, dict):
            if latitude is None:
                for key in ("latitude", "lat"):
                    if key in value:
                        latitude = as_float(value.get(key))
                        if latitude is not None:
                            break
            if longitude is None:
                for key in ("longitude", "lon", "lng"):
                    if key in value:
                        longitude = as_float(value.get(key))
                        if longitude is not None:
                            break
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(incident)
    return latitude, longitude


def _split_p2000(body: str) -> dict[str, str]:
    """Extract a readable location from a Dutch P2000 message."""
    raw = " ".join(str(body or "").split())
    without_codes = extract_vehicle_codes(raw, remove=True)
    without_codes = " ".join(without_codes.split())

    parts = [part.strip() for part in without_codes.split(" - ") if part.strip()]
    if len(parts) >= 3:
        return {
            "melding": parts[0],
            "straat": parts[1],
            "plaats": parts[2],
            "locatie": " - ".join(parts[1:]),
        }
    if len(parts) == 2:
        return {
            "melding": parts[0],
            "straat": "",
            "plaats": "",
            "locatie": parts[1],
        }

    text = re.sub(r"^P\s*\d+\s+", "", without_codes, flags=re.IGNORECASE)
    text = re.sub(r"^BLB-\d+\s*", "", text, flags=re.IGNORECASE)
    words = text.split()

    # Street/highway suffixes cover the common P2000 address forms.
    suffixes = (
        "weg", "straat", "laan", "dijk", "plein", "singel", "kade",
        "brug", "baan", "pad", "ring", "gracht", "hof", "wal", "veld",
        "steeg", "markt",
    )
    location_start = None
    for index, word in enumerate(words):
        clean = re.sub(r"[^A-Za-zÀ-ÿ0-9-]", "", word).casefold()
        if re.match(r"^[AN]\d+[A-Za-z]?$", clean, re.IGNORECASE):
            location_start = index
            break
        if any(clean.endswith(suffix) for suffix in suffixes):
            location_start = index
            break

    if location_start is None:
        location_words = words[-2:] if len(words) >= 2 else words
    else:
        location_words = words[location_start:]

    location = " ".join(location_words).strip()
    return {
        "melding": text,
        "straat": location_words[0] if location_words else "",
        "plaats": location_words[-1] if len(location_words) > 1 else "",
        "locatie": location,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BrandweerRoosterCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            LatestIncidentSensor(coordinator),
            CrewSensor(coordinator),
            ResponseSensor(coordinator),
            CurrentUserSensor(coordinator),
            MyResponseSensor(coordinator),
            UitrukMessageSensor(coordinator),
            UitrukkenDezeMaandSensor(coordinator),
            UitrukkenDitJaarSensor(coordinator),
            UitrukkenTotaalSensor(coordinator),
            UitrukkenOpgekomenNietIngedeeldSensor(coordinator),
            DiagnosticIncidentSensor(coordinator),
        ]
    )


class BaseBrandweerSensor(
    CoordinatorEntity[BrandweerRoosterCoordinator], SensorEntity
):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BrandweerRoosterCoordinator,
        name: str,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{unique_suffix}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": coordinator.entry.title,
            "manufacturer": "Brandweerrooster",
            "model": "API",
        }


class DiagnosticIncidentSensor(BaseBrandweerSensor):
    """Expose raw incident personnel data for API diagnostics.

    This sensor is intentionally read-only. It exposes the raw assignment/response objects and
    a compact merged view so API data can be compared with the actual crew
    roster when investigating personnel mismatches.
    """

    _attr_icon = "mdi:bug-check"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "API diagnose laatste incident", "api_diagnostic")

    @property
    def native_value(self) -> str:
        incident = self.coordinator.data.get("latest_incident") if self.coordinator.data else None
        if not incident:
            return "Geen incident"
        return str(incident.get("id") or "Onbekend")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        incident = self.coordinator.data.get("latest_incident") if self.coordinator.data else None
        if not incident:
            return {}

        assignments = [
            item for item in (incident.get("incident_skill_assignments") or [])
            if isinstance(item, dict)
        ]
        responses = [
            item for item in (incident.get("incident_responses") or [])
            if isinstance(item, dict)
        ]
        responses_by_user = {
            str(item.get("user_id")): item
            for item in responses
            if item.get("user_id") is not None
        }

        merged: list[dict[str, Any]] = []
        for assignment in assignments:
            user_id = assignment.get("user_id")
            response = responses_by_user.get(str(user_id), {})
            merged.append(
                {
                    "user_id": user_id,
                    "naam": (
                        response.get("user_name")
                        or response.get("user_nickname")
                        or assignment.get("user_name")
                    ),
                    "membership_id": assignment.get("membership_id") or response.get("membership_id"),
                    "group_id": assignment.get("group_id") or response.get("group_id"),
                    "skill_ids": assignment.get("skill_ids"),
                    "assigned_skill_ids": assignment.get("assigned_skill_ids"),
                    "original_rank_id": assignment.get("original_rank_id") or response.get("original_rank_id"),
                    "performed_rank_id": assignment.get("performed_rank_id") or response.get("performed_rank_id"),
                    "active_duty_function_ids": assignment.get("active_duty_function_ids") or response.get("active_duty_function_ids"),
                    "assignment_status": assignment.get("status"),
                    "reported_status": response.get("reported_status"),
                    "response_status": response.get("status"),
                    "available_at_incident_creation": response.get("available_at_incident_creation"),
                    "group_available_at_incident_creation": response.get("group_available_at_incident_creation"),
                    "on_duty": response.get("on_duty"),
                    "start_time": assignment.get("start_time") or response.get("start_time"),
                    "alerted_at": response.get("alerted_at"),
                }
            )

        return {
            "diagnostic_note": "Read-only API diagnostic data. Personnel selection is authoritative from incident_skill_assignments.",
            "incident_id": incident.get("id"),
            "incident_created_at": incident.get("created_at"),
            "incident_start_time": incident.get("start_time"),
            "incident_keys": sorted(str(key) for key in incident.keys()),
            "assignment_count": len(assignments),
            "response_count": len(responses),
            "personeel_diagnose": merged,
            "incident_skill_assignments_raw": assignments,
            "incident_responses_raw": responses,
        }


class LatestIncidentSensor(BaseBrandweerSensor):
    _attr_icon = "mdi:fire-truck"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Laatste incident", "latest_incident")

    @property
    def native_value(self) -> str:
        incident = self.coordinator.data.get("latest_incident") if self.coordinator.data else None
        if not incident:
            return "Geen incident"
        return f"Incident {incident.get('id', 'onbekend')}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        incident = self.coordinator.data.get("latest_incident") if self.coordinator.data else None
        if not incident:
            return {}
        body = str(incident.get("body") or incident.get("location") or "")
        parsed = _split_p2000(body)
        groups = incident.get("groups") or incident.get("group_ids") or []
        tasks = incident.get("task_ids") or []
        vehicles = _incident_vehicles(incident, self.coordinator)
        latitude, longitude = _incident_coordinates(incident)
        return {
            "incident_id": incident.get("id"),
            "melding": parsed["melding"],
            "straat": parsed["straat"],
            "plaats": parsed["plaats"],
            "locatie": parsed["locatie"],
            "prioriteit": incident.get("prio"),
            "incident_status": incident.get("state"),
            "type": incident.get("type"),
            "created_at": incident.get("created_at"),
            "start_time": incident.get("start_time"),
            "task_ids": tasks,
            "group_ids": groups,
            "alarmeringen": [
                self.coordinator.task_map.get(int(task_id), f"Taak {task_id}")
                for task_id in tasks
                if str(task_id).isdigit()
            ],
            "voertuigen": vehicles,
            "latitude": latitude,
            "longitude": longitude,
            "opkomstreacties": incident.get("incident_responses") or [],
            "personeel": _personnel(incident, self.coordinator),
            "personeel_per_functie": _personnel_by_function(incident, self.coordinator),
        }


class CrewSensor(BaseBrandweerSensor):
    _attr_icon = "mdi:account-group"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Ingezet personeel", "crew")

    @property
    def native_value(self) -> int:
        return len(
            _personnel(
                self.coordinator.data.get("latest_incident")
                if self.coordinator.data
                else None,
                self.coordinator,
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        incident = self.coordinator.data.get("latest_incident") if self.coordinator.data else None
        return {
            "personeel": _personnel(incident, self.coordinator),
            "per_functie": _personnel_by_function(incident, self.coordinator),
            "personeel_bron": "incident_skill_assignments",
            "laatste_uitruk_voertuigen": _incident_vehicles(incident, self.coordinator),
        }


class ResponseSensor(BaseBrandweerSensor):
    _attr_icon = "mdi:account-check"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Opkomst", "response")

    @property
    def native_value(self) -> int:
        return len(
            _responses(
                self.coordinator.data.get("latest_incident")
                if self.coordinator.data
                else None
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        responses = _responses(
            self.coordinator.data.get("latest_incident")
            if self.coordinator.data
            else None
        )
        summary = {"opgekomen": 0, "afgewezen": 0, "overig": 0}
        positive = {
            "acknowledged", "dispatched", "responded", "accepted", "coming",
            "on_the_way", "on-way", "arrived", "arrived_at_station",
        }
        negative = {
            "rejected", "declined", "no_show", "not_coming", "unavailable",
            "absent", "cancelled", "canceled",
        }
        for response in responses:
            status = str(
                response.get("reported_status") or response.get("status") or ""
            ).strip().lower().replace(" ", "_")
            if status in positive:
                summary["opgekomen"] += 1
            elif status in negative:
                summary["afgewezen"] += 1
            else:
                summary["overig"] += 1
        return {"samenvatting": summary, "reacties": responses}


class CurrentUserSensor(BaseBrandweerSensor):
    _attr_icon = "mdi:account"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Gebruiker", "current_user")

    @property
    def native_value(self) -> str:
        user = self.coordinator.data.get("current_user") if self.coordinator.data else {}
        return str(
            user.get("name")
            or user.get("nickname")
            or user.get("email")
            or user.get("id")
            or "Onbekend"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        user = self.coordinator.data.get("current_user") if self.coordinator.data else {}
        return {
            key: value
            for key, value in user.items()
            if key not in {"password", "access_token", "refresh_token"}
        }


class MyResponseSensor(BaseBrandweerSensor):
    _attr_icon = "mdi:account-arrow-right"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Mijn opkomst", "my_response")

    @property
    def native_value(self) -> str:
        response = _my_response(self.coordinator)
        return str(
            response.get("reported_status")
            or response.get("status")
            or "Geen actieve opkomst"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return _my_response(self.coordinator)


class UitrukMessageSensor(BaseBrandweerSensor):
    _attr_icon = "mdi:facebook"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Uitrukbericht", "uitrukbericht")

    @property
    def native_value(self) -> str:
        incident = self.coordinator.data.get("latest_incident") if self.coordinator.data else None
        return "Klaar om te kopiëren" if incident else "Geen uitruk"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        incident = self.coordinator.data.get("latest_incident") if self.coordinator.data else None
        return {"bericht": _facebook_message(incident, self.coordinator)}


def _my_response(coordinator: BrandweerRoosterCoordinator) -> dict[str, Any]:
    data = coordinator.data or {}
    user = data.get("current_user") or {}
    user_id = user.get("id")
    for response in _responses(data.get("latest_incident")):
        if user_id is not None and str(response.get("user_id")) == str(user_id):
            return dict(response)
    return {}


def _incident_vehicles(
    incident: dict[str, Any] | None,
    coordinator: BrandweerRoosterCoordinator,
) -> list[str]:
    """Return the vehicles actually present in the P2000/incident alert."""
    if not incident:
        return []

    codes = extract_vehicle_codes(
        str(incident.get("body") or incident.get("location") or ""),
    )

    # Prefer explicit vehicle objects when Brandweerrooster supplies them.
    explicit_keys = {
        "vehicles",
        "vehicle",
        "appliances",
        "appliance",
        "units",
        "unit",
        "voertuig_details",
        "assigned_vehicles",
        "assigned_appliances",
        "responding_vehicles",
        "responding_appliances",
    }
    names: list[str] = []
    seen: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).casefold() in explicit_keys:
                    candidates = child if isinstance(child, list) else [child]
                    for item in candidates:
                        if isinstance(item, str):
                            name = item.strip()
                        elif isinstance(item, dict):
                            candidate = (
                                item.get("display_name")
                                or item.get("vehicle_name")
                                or item.get("appliance_name")
                                or item.get("unit_name")
                                or item.get("name")
                                or item.get("title")
                            )
                            name = str(candidate).strip() if candidate else ""
                        else:
                            name = ""
                        if name and name not in seen:
                            seen.add(name)
                            names.append(name)
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(incident)
    if names:
        return names

    return resolve_vehicle_names(codes)


def _facebook_message(
    incident: dict[str, Any] | None,
    coordinator: BrandweerRoosterCoordinator,
) -> str:
    """Render the configurable Facebook dispatch message."""
    if not incident:
        return ""

    body = str(incident.get("body") or incident.get("location") or "Onbekend incident")
    parsed = _split_p2000(body)
    priority = _format_priority(incident.get("prio"))

    created_at = incident.get("created_at") or incident.get("start_time")
    alarm_time = ""
    alarm_date = ""
    if created_at:
        try:
            from homeassistant.util import dt as dt_util

            parsed_time = dt_util.parse_datetime(str(created_at))
            if parsed_time:
                parsed_time = dt_util.as_local(parsed_time)
                alarm_time = parsed_time.strftime("%H:%M") + " uur"
                alarm_date = parsed_time.strftime("%d-%m-%Y")
        except (TypeError, ValueError):
            pass

    incident_type = str(incident.get("type") or "uitruk").replace("_", " ").strip()
    classification = _incident_classification(parsed["melding"], incident_type)
    location = parsed["locatie"] or parsed["plaats"] or "onbekende locatie"
    vehicles = _incident_vehicles(incident, coordinator)
    station_name = _station_name_for_incident(incident, coordinator)

    values = {
        "kazerne": station_name,
        "uitrukbericht": f"Voor een {incident_type} is de brandweer gealarmeerd.",
        "incident_type": incident_type,
        "classificatie": classification,
        "melding": parsed["melding"],
        "locatie": location,
        "straat": parsed["straat"],
        "plaats": parsed["plaats"],
        "tijd": alarm_time,
        "datum": alarm_date,
        "prioriteit": priority,
        "voertuigen": ", ".join(vehicles),
        "incident_id": str(incident.get("id") or ""),
        "created_at": str(incident.get("created_at") or ""),
        "start_time": str(incident.get("start_time") or ""),
    }
    return coordinator.facebook_template.render(values)


def _incident_classification(melding: str, incident_type: str = "") -> str:
    """Return a short, human-readable fire/incident classification.

    The P2000 message is the primary source. Common Brandweerrooster/P2000
    abbreviations are normalized to readable Dutch labels; unknown values are
    preserved in a cleaned-up form rather than guessed.
    """
    text = " ".join(str(melding or "").split()).strip()
    lowered = text.casefold()

    mappings = (
        ("woning", "Woningbrand"),
        ("buiten", "Buitenbrand"),
        ("natuur", "Natuurbrand"),
        ("container", "Containerbrand"),
        ("voertuig", "Voertuigbrand"),
        ("schoorsteen", "Schoorsteenbrand"),
        ("industrie", "Industriebrand"),
        ("agrar", "Agrarische brand"),
        ("gebouw", "Gebouwbrand"),
    )
    for keyword, label in mappings:
        if keyword in lowered:
            return label

    cleaned = re.sub(r"^BR\s*", "", text, flags=re.IGNORECASE).strip(" -:")
    if cleaned:
        return cleaned[:1].upper() + cleaned[1:]

    return incident_type.replace("_", " ").strip().capitalize() or "Uitruk"


def _format_priority(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper().replace("PRIO", "P")
    if text in {"1", "P1"}:
        return "P1"
    if text in {"2", "P2"}:
        return "P2"
    return text


def _station_name_for_incident(
    incident: dict[str, Any] | None,
    coordinator: BrandweerRoosterCoordinator,
) -> str:
    """Determine the fire station from the incident/group data.

    The Home Assistant config-entry title can contain a local crew name such
    as ``Ploeg 2 (4292)`` and must never be used as the public station name.
    Prefer the group(s) attached to the incident because those identify the
    actual alarmed station/main group. Fall back to the configured station
    group only when the incident does not provide a usable group.
    """
    candidate_ids: list[int] = []

    if incident:
        for value in incident.get("groups") or incident.get("group_ids") or []:
            try:
                candidate_ids.append(int(value))
            except (TypeError, ValueError):
                continue

        # Some API responses expose the operational group only on responses.
        if not candidate_ids:
            for response in incident.get("incident_responses") or []:
                if not isinstance(response, dict):
                    continue
                try:
                    group_id = int(response.get("group_id"))
                except (TypeError, ValueError):
                    continue
                if group_id not in candidate_ids:
                    candidate_ids.append(group_id)

    if coordinator.station_group_id and coordinator.station_group_id not in candidate_ids:
        candidate_ids.append(coordinator.station_group_id)

    # Prefer a real station/main group over crew/task-style names.
    candidates: list[str] = []
    for group_id in candidate_ids:
        name = coordinator.group_map.get(group_id, "")
        if name:
            candidates.append(name)

    for name in candidates:
        normalized = str(name).casefold()
        if "ploeg" not in normalized and "team" not in normalized:
            return _station_display_name(name)

    if candidates:
        return _station_display_name(candidates[0])

    # Last-resort fallback for older config entries. Never expose the raw
    # entry title if it looks like a crew title.
    title = coordinator.entry.title
    if "ploeg" not in str(title).casefold():
        return _station_display_name(title)
    return "Brandweer"


def _station_display_name(title: str) -> str:
    """Turn a selected Brandweerrooster group into a station name."""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", str(title or "")).strip()
    name = re.sub(r"^Brandweer\s+", "", name, flags=re.IGNORECASE).strip()
    # Group names are commonly things such as ``Echt TS`` or
    # ``Amsterdam-West TS``. Remove the vehicle/group suffix, but keep the
    # actual station name.
    name = re.sub(
        r"\s+(?:TS|HV|HOVD|SHE|SIV|WO|AL|DA|HA|TST|SB|DV-HOD|DA-OVD|Ploeg(?:en)?|Kazerne(?:techniek)?|Groep(?:en)?)$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    return name or "Brandweer"


def _responses(incident: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not incident:
        return []
    return [
        x for x in (incident.get("incident_responses") or [])
        if isinstance(x, dict)
    ]


def _personnel(
    incident: dict[str, Any] | None,
    coordinator: BrandweerRoosterCoordinator,
) -> list[dict[str, Any]]:
    """Return the actual assigned crew from incident_skill_assignments.

    ``incident_responses`` is deliberately *not* used to decide who is crew.
    That API collection contains everyone who received/responded to the
    alarm, including people who did not show up or were not assigned to the
    appliance. It may therefore contain substantially more people than the
    actual crew.

    The assignment records are authoritative for crew membership and skill.
    A matching response record is used only to enrich an assigned person with
    their display name/status. The response can never add a person to the
    crew and can never change their assigned function.
    """
    if not incident:
        return []

    raw_assignments = incident.get("incident_skill_assignments") or []
    assignments = [item for item in raw_assignments if isinstance(item, dict)]

    # Responses are only an enrichment lookup keyed by user_id.
    responses_by_user: dict[str, dict[str, Any]] = {}
    for response in _responses(incident):
        user_id = response.get("user_id")
        if user_id is None:
            continue
        # Keep the first response for a user. The selection of crew remains
        # completely independent from this lookup.
        responses_by_user.setdefault(str(user_id), response)

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for assignment in assignments:
        user_id = assignment.get("user_id")
        if user_id is None:
            continue

        response = responses_by_user.get(str(user_id), {})
        name = (
            assignment.get("user_name")
            or assignment.get("user_nickname")
            or response.get("user_name")
            or response.get("user_nickname")
            or f"Gebruiker {user_id}"
        )

        skill_ids = assignment.get("skill_ids")
        if not isinstance(skill_ids, list):
            skill_ids = [skill_ids] if skill_ids not in (None, "") else []

        if not skill_ids:
            key = (str(user_id), "Onbekend")
            if key not in seen:
                seen.add(key)
                result.append(
                    {
                        "user_id": user_id,
                        "naam": str(name),
                        "functie": "Onbekend",
                        "status": response.get("status"),
                        "reported_status": response.get("reported_status"),
                    }
                )
            continue

        for skill_id in skill_ids:
            try:
                skill_key = int(skill_id)
            except (TypeError, ValueError):
                skill_key = None

            function_name = (
                coordinator.skill_map.get(skill_key, f"Skill {skill_id}")
                if skill_key is not None
                else f"Skill {skill_id}"
            )
            key = (str(user_id), str(function_name))
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "user_id": user_id,
                    "naam": str(name),
                    "skill_id": skill_id,
                    "functie": function_name,
                    "status": response.get("status"),
                    "reported_status": response.get("reported_status"),
                }
            )

    # Stable operational order instead of alphabetical role order. This also
    # keeps the dashboard readable when the API returns assignments in a
    # different order. Unknown/custom skills remain at the end.
    def role_sort(item: dict[str, Any]) -> tuple[int, str]:
        role = str(item.get("functie", ""))
        normalized = role.casefold()
        if "bevelvoerder" in normalized:
            order = 0
        elif "chauffeur" in normalized:
            order = 1
        elif "manschap" in normalized:
            order = 2
        elif "aspirant" in normalized:
            order = 3
        else:
            order = 4
        return order, str(item.get("naam", ""))

    result.sort(key=role_sort)
    return result


def _personnel_by_function(
    incident: dict[str, Any] | None,
    coordinator: BrandweerRoosterCoordinator,
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for person in _personnel(incident, coordinator):
        grouped.setdefault(
            str(person.get("functie", "Onbekend")),
            [],
        ).append(str(person.get("naam", "Onbekend")))
    return grouped


class UitrukkenDezeMaandSensor(BaseBrandweerSensor):
    _attr_icon = "mdi:calendar-month"
    _attr_native_unit_of_measurement = "uitrukken"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Uitrukken deze maand", "uitrukken_maand")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("statistics", {}).get("month", 0))


class UitrukkenDitJaarSensor(BaseBrandweerSensor):
    _attr_icon = "mdi:calendar"
    _attr_native_unit_of_measurement = "uitrukken"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Uitrukken dit jaar", "uitrukken_jaar")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("statistics", {}).get("year", 0))


class UitrukkenTotaalSensor(BaseBrandweerSensor):
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "uitrukken"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Uitrukken totaal", "uitrukken_totaal")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("statistics", {}).get("total", 0))


class UitrukkenOpgekomenNietIngedeeldSensor(BaseBrandweerSensor):
    _attr_icon = "mdi:account-alert"
    _attr_native_unit_of_measurement = "uitrukken"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(
            coordinator,
            "Opgekomen, niet ingedeeld",
            "uitrukken_niet_ingedeeld",
        )

    @property
    def native_value(self) -> int:
        return int(
            (self.coordinator.data or {})
            .get("statistics", {})
            .get("not_assigned", 0)
        )
