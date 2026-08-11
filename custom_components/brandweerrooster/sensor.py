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
    if not incident:
        return ""

    body = str(incident.get("body") or incident.get("location") or "Onbekend incident")
    parsed = _split_p2000(body)
    priority = incident.get("prio")
    location = parsed["locatie"] or parsed["plaats"] or "onbekende locatie"

    created_at = incident.get("created_at") or incident.get("start_time")
    alarm_time = ""
    if created_at:
        try:
            from homeassistant.util import dt as dt_util
            parsed_time = dt_util.parse_datetime(str(created_at))
            if parsed_time:
                alarm_time = parsed_time.strftime("%H:%M")
        except (TypeError, ValueError):
            pass

    vehicles = _incident_vehicles(incident, coordinator)

    # Gebruik de daadwerkelijk geconfigureerde hoofdgroep uit Brandweerrooster.
    # Dit voorkomt dat een oude/aangepaste HA-entrytitel zoals "Ploeg 2"
    # in het Facebookbericht terechtkomt.
    configured_group_name = coordinator.group_map.get(coordinator.station_group_id, "")
    station_name = _station_display_name(configured_group_name or coordinator.entry.title)
    lines = [
        f"🚒 Brandweer {station_name} uitgerukt",
        "",
        "Voor een incident alert is de brandweer gealarmeerd.",
        f"📍 {location}",
    ]

    if alarm_time:
        lines.append(f"🕐 Alarmering: {alarm_time} uur")

    priority_text = _format_priority(priority)
    if priority_text:
        lines.append(f"📟 Prioriteit: {priority_text}")

    if vehicles:
        lines.append(f"🚒 Voertuigen: {', '.join(vehicles)}")

    lines.extend(
        [
            "",
            "Meer informatie volgt indien beschikbaar.",
            "",
            "#Brandweer #Hulpverlening",
        ]
    )
    return "\n".join(lines)


def _format_priority(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper().replace("PRIO", "P")
    if text in {"1", "P1"}:
        return "P1"
    if text in {"2", "P2"}:
        return "P2"
    return text


def _station_display_name(title: str) -> str:
    """Turn a configured group title such as 'Echt TS (5421)' into 'Echt'."""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", str(title or "")).strip()
    name = re.sub(r"^Brandweer\s+", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(
        r"\s+(?:TS|HV|SHE|SIV|Ploeg(?:en)?|Kazerne(?:techniek)?|Groep(?:en)?)$",
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
    if not incident:
        return []
    assignments = incident.get("incident_skill_assignments") or []
    responses = {
        str(x.get("user_id")): x
        for x in _responses(incident)
        if x.get("user_id") is not None
    }
    result: list[dict[str, Any]] = []
    for assignment in assignments:
        user_id = assignment.get("user_id")
        response = responses.get(str(user_id), {})
        name = (
            response.get("user_name")
            or response.get("user_nickname")
            or f"Gebruiker {user_id}"
        )
        skill_ids = assignment.get("skill_ids") or []
        if not skill_ids:
            result.append(
                {
                    "user_id": user_id,
                    "naam": name,
                    "functie": "Onbekend",
                    "status": response.get("status"),
                    "reported_status": response.get("reported_status"),
                }
            )
        else:
            for skill_id in skill_ids:
                result.append(
                    {
                        "user_id": user_id,
                        "naam": name,
                        "skill_id": skill_id,
                        "functie": coordinator.skill_map.get(
                            int(skill_id), f"Skill {skill_id}"
                        ),
                        "status": response.get("status"),
                        "reported_status": response.get("reported_status"),
                    }
                )
    result.sort(
        key=lambda item: (
            str(item.get("functie", "")),
            str(item.get("naam", "")),
        )
    )
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
