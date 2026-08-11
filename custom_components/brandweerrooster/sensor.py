"""Sensors exposed by Brandweerrooster."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BrandweerRoosterCoordinator


def _split_p2000(body: str) -> dict[str, str]:
    result = {"melding": body, "straat": "", "plaats": "", "locatie": body}
    parts = [part.strip() for part in body.split(" - ") if part.strip()]
    if len(parts) >= 3:
        result.update(melding=parts[0], straat=parts[1], plaats=parts[2], locatie=" - ".join(parts[1:]))
    elif len(parts) == 2:
        result.update(melding=parts[0], locatie=parts[1])
    return result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
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


class BaseBrandweerSensor(CoordinatorEntity[BrandweerRoosterCoordinator], SensorEntity):
    """Base entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BrandweerRoosterCoordinator, name: str, unique_suffix: str) -> None:
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
    """Latest relevant incident."""

    _attr_icon = "mdi:fire-truck"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Laatste incident", "latest_incident")

    @property
    def native_value(self) -> str:
        incident = self.coordinator.data.get("latest_incident") if self.coordinator.data else None
        if not incident:
            return "Geen incident"
        return f"Incident {incident.get("id", "onbekend")}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        incident = self.coordinator.data.get("latest_incident") if self.coordinator.data else None
        if not incident:
            return {}
        body = str(incident.get("body") or incident.get("location") or "")
        parsed = _split_p2000(body)
        groups = incident.get("groups") or incident.get("group_ids") or []
        tasks = incident.get("task_ids") or []
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
            "alarmeringen": [self.coordinator.task_map.get(int(task_id), f"Taak {task_id}") for task_id in tasks if str(task_id).isdigit()],
            "groepen": [self.coordinator.group_map.get(int(group_id), f"Groep {group_id}") for group_id in groups if str(group_id).isdigit()],
            "opkomstreacties": incident.get("incident_responses") or [],
            "personeel": _personnel(incident, self.coordinator),
            "personeel_per_functie": _personnel_by_function(incident, self.coordinator),
        }


class CrewSensor(BaseBrandweerSensor):
    """Current assigned personnel."""

    _attr_icon = "mdi:account-group"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Ingezet personeel", "crew")

    @property
    def native_value(self) -> int:
        return len(_personnel(self.coordinator.data.get("latest_incident") if self.coordinator.data else None, self.coordinator))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        incident = self.coordinator.data.get("latest_incident") if self.coordinator.data else None
        return {"personeel": _personnel(incident, self.coordinator), "per_functie": _personnel_by_function(incident, self.coordinator)}


class ResponseSensor(BaseBrandweerSensor):
    """Incident response summary."""

    _attr_icon = "mdi:account-check"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Opkomst", "response")

    @property
    def native_value(self) -> int:
        return len(_responses(self.coordinator.data.get("latest_incident") if self.coordinator.data else None))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        responses = _responses(self.coordinator.data.get("latest_incident") if self.coordinator.data else None)
        summary = {"dispatched": 0, "no_show": 0, "overig": 0}
        for response in responses:
            status = response.get("reported_status")
            if status == "dispatched":
                summary["dispatched"] += 1
            elif status == "no_show":
                summary["no_show"] += 1
            else:
                summary["overig"] += 1
        return {"samenvatting": summary, "reacties": responses}


class CurrentUserSensor(BaseBrandweerSensor):
    """Logged-in Brandweerrooster user."""

    _attr_icon = "mdi:account"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Gebruiker", "current_user")

    @property
    def native_value(self) -> str:
        user = self.coordinator.data.get("current_user") if self.coordinator.data else {}
        return str(user.get("name") or user.get("nickname") or user.get("email") or user.get("id") or "Onbekend")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        user = self.coordinator.data.get("current_user") if self.coordinator.data else {}
        return {key: value for key, value in user.items() if key not in {"password", "access_token", "refresh_token"}}


class MyResponseSensor(BaseBrandweerSensor):
    """Current user's response to the latest incident."""

    _attr_icon = "mdi:account-arrow-right"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Mijn opkomst", "my_response")

    @property
    def native_value(self) -> str:
        response = _my_response(self.coordinator)
        return str(response.get("reported_status") or response.get("status") or "Geen actieve opkomst")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return _my_response(self.coordinator)


class UitrukMessageSensor(BaseBrandweerSensor):
    """Ready-to-copy Dutch Facebook incident message."""

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


def _facebook_message(incident: dict[str, Any] | None, coordinator: BrandweerRoosterCoordinator) -> str:
    if not incident:
        return ""
    body = str(incident.get("body") or incident.get("location") or "Onbekend incident")
    parsed = _split_p2000(body)
    incident_type = str(incident.get("type") or "uitruk").replace("_", " ")
    priority = incident.get("prio")
    location = parsed["locatie"] or parsed["plaats"] or "onbekende locatie"
    task_ids = incident.get("task_ids") or []
    task_names = [coordinator.task_map.get(int(task_id), f"Taak {task_id}") for task_id in task_ids if str(task_id).isdigit()]
    units = ", ".join(dict.fromkeys(task_names))
    lines = [f"🚒 Brandweer {coordinator.entry.title.split(' - ')[0] if ' - ' in coordinator.entry.title else coordinator.entry.title} uitgerukt", "", f"Voor een {incident_type} is de brandweer gealarmeerd.", f"📍 {location}"]
    if priority is not None:
        lines.append(f"📟 Prioriteit: P{priority}")
    if units:
        lines.append(f"🚒 Inzet: {units}")
    lines.extend(["", "Meer informatie volgt indien beschikbaar.", "", "#Brandweer #Brandweerrooster"])
    return "\n".join(lines)


def _responses(incident: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not incident:
        return []
    return [x for x in (incident.get("incident_responses") or []) if isinstance(x, dict)]


def _personnel(incident: dict[str, Any] | None, coordinator: BrandweerRoosterCoordinator) -> list[dict[str, Any]]:
    if not incident:
        return []
    assignments = incident.get("incident_skill_assignments") or []
    responses = {x.get("user_id"): x for x in _responses(incident)}
    result: list[dict[str, Any]] = []
    for assignment in assignments:
        user_id = assignment.get("user_id")
        response = responses.get(user_id, {})
        name = response.get("user_name") or response.get("user_nickname") or f"Gebruiker {user_id}"
        skill_ids = assignment.get("skill_ids") or []
        if not skill_ids:
            result.append({"user_id": user_id, "naam": name, "functie": "Onbekend", "status": response.get("status"), "reported_status": response.get("reported_status")})
        else:
            for skill_id in skill_ids:
                result.append({"user_id": user_id, "naam": name, "skill_id": skill_id, "functie": coordinator.skill_map.get(int(skill_id), f"Skill {skill_id}"), "status": response.get("status"), "reported_status": response.get("reported_status")})
    result.sort(key=lambda item: (str(item.get("functie", "")), str(item.get("naam", ""))))
    return result


def _personnel_by_function(incident: dict[str, Any] | None, coordinator: BrandweerRoosterCoordinator) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for person in _personnel(incident, coordinator):
        grouped.setdefault(str(person.get("functie", "Onbekend")), []).append(str(person.get("naam", "Onbekend")))
    return grouped


class UitrukkenDezeMaandSensor(BaseBrandweerSensor):
    """Number of personal attended incidents this calendar month."""

    _attr_icon = "mdi:calendar-month"
    _attr_native_unit_of_measurement = "uitrukken"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Uitrukken deze maand", "uitrukken_maand")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("statistics", {}).get("month", 0))


class UitrukkenDitJaarSensor(BaseBrandweerSensor):
    """Number of personal attended incidents this calendar year."""

    _attr_icon = "mdi:calendar"
    _attr_native_unit_of_measurement = "uitrukken"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Uitrukken dit jaar", "uitrukken_jaar")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("statistics", {}).get("year", 0))


class UitrukkenTotaalSensor(BaseBrandweerSensor):
    """Lifetime number of personal attended and assigned incidents."""

    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "uitrukken"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Uitrukken totaal", "uitrukken_totaal")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("statistics", {}).get("total", 0))


class UitrukkenOpgekomenNietIngedeeldSensor(BaseBrandweerSensor):
    """Lifetime count of attended incidents without a crew assignment."""

    _attr_icon = "mdi:account-alert"
    _attr_native_unit_of_measurement = "uitrukken"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "Opgekomen, niet ingedeeld", "uitrukken_niet_ingedeeld")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("statistics", {}).get("not_assigned", 0))
