"""Pure helpers that turn a Brandweerrooster incident payload into readable data.

Nothing in this module performs I/O; everything is deterministic so it can be
unit tested and shared between the sensor, event, geo_location and service
code.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import re
from typing import Any

from homeassistant.util import dt as dt_util

from .vehicles import extract_vehicle_codes, resolve_vehicle_names

# ``reported_status`` is the user's explicit response in the incident.
# ``dispatched`` is used by FireServiceRota for an accepted/coming response.
# The other values make the logic tolerant of API variations.
POSITIVE_RESPONSE_STATUSES = frozenset(
    {
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
)
NEGATIVE_RESPONSE_STATUSES = frozenset(
    {
        "no_show",
        "declined",
        "rejected",
        "not_coming",
        "unavailable",
        "absent",
        "cancelled",
        "canceled",
        "expired",
    }
)

# Brandweerrooster API v2: ``status`` is the alarm response (acknowledged,
# rejected, expired, pending, not_sent) and ``reported_status`` the attendance
# filled in afterwards (dispatched, shown_up, no_show, unknown). Until the
# attendance is filled in, ``reported_status`` is ``unknown``.
_UNSET_REPORTED_STATUSES = frozenset({"", "unknown"})

_ROLE_ORDER = (
    ("bevelvoerder", 0),
    ("chauffeur", 1),
    ("manschap", 2),
    ("aspirant", 3),
)


def normalize_status(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def response_status(response: dict[str, Any]) -> str:
    """Return the effective status: the reported attendance when filled in, else the alarm response."""
    reported = normalize_status(response.get("reported_status"))
    if reported not in _UNSET_REPORTED_STATUSES:
        return reported
    return normalize_status(response.get("status")) or reported


def response_is_positive(response: dict[str, Any]) -> bool:
    status = response_status(response)
    return bool(status) and status in POSITIVE_RESPONSE_STATUSES


def response_is_negative(response: dict[str, Any]) -> bool:
    return response_status(response) in NEGATIVE_RESPONSE_STATUSES


def incident_id(incident: dict[str, Any] | None) -> int | None:
    if not incident:
        return None
    try:
        return int(incident.get("id"))
    except (TypeError, ValueError):
        return None


def incident_body(incident: dict[str, Any] | None) -> str:
    if not incident:
        return ""
    return str(incident.get("body") or incident.get("location") or "")


def int_set(values: Any) -> set[int]:
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    result: set[int] = set()
    for value in values:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def incident_groups(incident: dict[str, Any]) -> set[int]:
    return int_set(incident.get("groups") or incident.get("group_ids") or [])


def incident_tasks(incident: dict[str, Any]) -> set[int]:
    return int_set(incident.get("task_ids") or [])


def incident_coordinates(incident: dict[str, Any] | None) -> tuple[float | None, float | None]:
    """Extract latitude/longitude from an incident payload.

    Brandweerrooster and FireServiceRota may expose coordinates at different
    nesting levels, so accept common representations.
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
    if latitude is not None and not -90 <= latitude <= 90:
        latitude = None
    if longitude is not None and not -180 <= longitude <= 180:
        longitude = None
    if latitude is None or longitude is None or (latitude == 0 and longitude == 0):
        return None, None
    return latitude, longitude


def split_p2000(body: str) -> dict[str, str]:
    """Extract a readable message and location from a Dutch P2000 message."""
    raw = " ".join(str(body or "").split())
    without_codes = extract_vehicle_codes(raw, remove=True)
    without_codes = " ".join(str(without_codes).split())

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


def classification(melding: str, incident_type: str = "") -> str:
    """Return a short, human-readable incident classification."""
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


def category(melding: str) -> str:
    """Return a coarse category: brand, hulpverlening, oms, overig."""
    text = " ".join(str(melding or "").split()).casefold()
    if re.search(
        r"\boms\b|\baob\b|\bautom(atische?|\.)?\s*(brand)?(melding|alarm)|\bloos\s+alarm", text
    ):
        return "OMS / automatische melding"
    if re.search(r"\bbr\b|brand|rook|vuur", text):
        return "Brand"
    if re.search(r"\bhv\b|\bth\b|hulpverlening|ongeval|letsel|beknelling|water|dier|gaslek|gas", text):
        return "Hulpverlening"
    return "Overig"


def format_priority(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper().replace("PRIO", "P").replace(" ", "")
    if text in {"1", "P1", "A1"}:
        return "P1"
    if text in {"2", "P2", "A2"}:
        return "P2"
    if text in {"3", "P3", "B1", "B2"}:
        return "P3"
    return text


def alarm_datetime(incident: dict[str, Any] | None) -> datetime | None:
    """Return the incident creation time as an aware local datetime."""
    if not incident:
        return None
    raw = incident.get("created_at") or incident.get("start_time")
    if not raw:
        return None
    try:
        parsed = dt_util.parse_datetime(str(raw))
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_local(parsed)


def incident_vehicles(
    incident: dict[str, Any] | None,
    vehicle_names: dict[str, str] | None = None,
    lookup: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Return the vehicles actually present in the incident/P2000 alert."""
    if not incident:
        return []

    codes = extract_vehicle_codes(incident_body(incident))

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

    return resolve_vehicle_names(list(codes), vehicle_names, lookup)


def responses(incident: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not incident:
        return []
    return [x for x in (incident.get("incident_responses") or []) if isinstance(x, dict)]


def response_summary(incident: dict[str, Any] | None) -> dict[str, int]:
    summary = {"opgekomen": 0, "afgewezen": 0, "overig": 0}
    for response in responses(incident):
        if response_is_positive(response):
            summary["opgekomen"] += 1
        elif response_is_negative(response):
            summary["afgewezen"] += 1
        else:
            summary["overig"] += 1
    return summary


def personnel(
    incident: dict[str, Any] | None,
    skill_map: dict[int, str],
) -> list[dict[str, Any]]:
    """Return the actual assigned crew from ``incident_skill_assignments``.

    ``incident_responses`` is deliberately *not* used to decide who is crew:
    it contains everyone who received/responded to the alarm. A matching
    response is only used to enrich an assigned person with name/status.
    """
    if not incident:
        return []

    assignments = [
        item for item in (incident.get("incident_skill_assignments") or []) if isinstance(item, dict)
    ]

    responses_by_user: dict[str, dict[str, Any]] = {}
    for response in responses(incident):
        user_id = response.get("user_id")
        if user_id is not None:
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
                skill_key: int | None = int(skill_id)
            except (TypeError, ValueError):
                skill_key = None

            function_name = (
                skill_map.get(skill_key, f"Skill {skill_id}") if skill_key is not None else f"Skill {skill_id}"
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

    def role_sort(item: dict[str, Any]) -> tuple[int, str]:
        normalized = str(item.get("functie", "")).casefold()
        for keyword, order in _ROLE_ORDER:
            if keyword in normalized:
                return order, str(item.get("naam", ""))
        return 4, str(item.get("naam", ""))

    result.sort(key=role_sort)
    return result


def personnel_by_function(crew: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for person in crew:
        grouped.setdefault(str(person.get("functie", "Onbekend")), []).append(
            str(person.get("naam", "Onbekend"))
        )
    return grouped


def crew_status(crew: list[dict[str, Any]], min_size: int) -> dict[str, Any]:
    """Return whether the crew is complete: a commander, a driver and enough people."""
    people = {str(person.get("user_id")) for person in crew}
    functions = [str(person.get("functie", "")).casefold() for person in crew]
    has_commander = any("bevelvoerder" in function for function in functions)
    has_driver = any("chauffeur" in function or "machinist" in function for function in functions)
    counts: dict[str, int] = {}
    for person in crew:
        function = str(person.get("functie", "Onbekend"))
        counts[function] = counts.get(function, 0) + 1
    missing: list[str] = []
    if not has_commander:
        missing.append("bevelvoerder")
    if not has_driver:
        missing.append("chauffeur")
    if len(people) < min_size:
        missing.append(f"{min_size - len(people)} persoon/personen")
    return {
        "compleet": bool(crew) and not missing,
        "aantal": len(people),
        "minimaal": min_size,
        "bevelvoerder": has_commander,
        "chauffeur": has_driver,
        "per_functie": counts,
        "ontbreekt": missing,
    }


def station_name(
    incident: dict[str, Any] | None,
    group_map: dict[int, str],
    station_group_id: int,
    fallback_title: str,
) -> str:
    """Determine the public fire station name from the incident/group data.

    The config-entry title can contain a crew name such as ``Ploeg 2 (4292)``
    and must never be used as the public station name.
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
            for response in responses(incident):
                try:
                    group_id = int(response.get("group_id"))
                except (TypeError, ValueError):
                    continue
                if group_id not in candidate_ids:
                    candidate_ids.append(group_id)

    if station_group_id and station_group_id not in candidate_ids:
        candidate_ids.append(station_group_id)

    candidates = [group_map[group_id] for group_id in candidate_ids if group_map.get(group_id)]

    for name in candidates:
        normalized = str(name).casefold()
        if "ploeg" not in normalized and "team" not in normalized:
            return station_display_name(name)

    if candidates:
        return station_display_name(candidates[0])

    if "ploeg" not in str(fallback_title).casefold():
        return station_display_name(fallback_title)
    return "Brandweer"


def station_display_name(title: str) -> str:
    """Turn a selected Brandweerrooster group into a station name."""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", str(title or "")).strip()
    name = re.sub(r"^Brandweer\s+", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(
        r"\s+(?:TS|HV|HOVD|SHE|SIV|WO|AL|DA|HA|TST|SB|DV-HOD|DA-OVD|Ploeg(?:en)?|Kazerne(?:techniek)?|Groep(?:en)?)$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    return name or "Brandweer"


def message_values(
    incident: dict[str, Any],
    *,
    group_map: dict[int, str],
    station_group_id: int,
    fallback_title: str,
    vehicle_names: dict[str, str] | None,
    lookup: Callable[[str], str | None] | None = None,
) -> dict[str, str]:
    """Build the placeholder values for the dispatch message template."""
    body = incident_body(incident) or "Onbekend incident"
    parsed = split_p2000(body)
    alarm = alarm_datetime(incident)
    incident_type = str(incident.get("type") or "uitruk").replace("_", " ").strip()
    location = parsed["locatie"] or parsed["plaats"] or "onbekende locatie"
    return {
        "kazerne": station_name(incident, group_map, station_group_id, fallback_title),
        "uitrukbericht": f"Voor een {incident_type} is de brandweer gealarmeerd.",
        "incident_type": incident_type,
        "classificatie": classification(parsed["melding"], incident_type),
        "categorie": category(parsed["melding"]),
        "melding": parsed["melding"],
        "locatie": location,
        "straat": parsed["straat"],
        "plaats": parsed["plaats"],
        "tijd": alarm.strftime("%H:%M") + " uur" if alarm else "",
        "datum": alarm.strftime("%d-%m-%Y") if alarm else "",
        "prioriteit": format_priority(incident.get("prio")),
        "voertuigen": ", ".join(incident_vehicles(incident, vehicle_names, lookup)),
        "incident_id": str(incident.get("id") or ""),
        "created_at": str(incident.get("created_at") or ""),
        "start_time": str(incident.get("start_time") or ""),
    }
