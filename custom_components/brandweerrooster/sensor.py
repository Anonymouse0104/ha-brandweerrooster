"""Sensors exposed by Brandweerrooster."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrandweerRoosterConfigEntry
from .coordinator import BrandweerRoosterCoordinator
from .entity import BrandweerRoosterEntity
from .incident import (
    alarm_datetime,
    category,
    classification,
    crew_status,
    format_priority,
    incident_body,
    incident_coordinates,
    incident_vehicles,
    personnel,
    personnel_by_function,
    response_status,
    response_summary,
    responses,
    split_p2000,
)

# Personnel names, raw responses and similar lists are useful on dashboards
# but should not end up in the recorder database.
_PERSONNEL_ATTRIBUTES = frozenset(
    {"personeel", "personeel_per_functie", "per_functie", "opkomstreacties", "reacties", "bericht"}
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrandweerRoosterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            LatestIncidentSensor(coordinator),
            LastAlarmSensor(coordinator),
            IncidentDistanceSensor(coordinator),
            CrewSensor(coordinator),
            ResponseSensor(coordinator),
            CurrentUserSensor(coordinator),
            MyResponseSensor(coordinator),
            UitrukMessageSensor(coordinator),
            StatisticSensor(coordinator, "uitrukken_maand", "month"),
            StatisticSensor(coordinator, "uitrukken_vorige_maand", "previous_month"),
            StatisticSensor(coordinator, "uitrukken_jaar", "year"),
            StatisticSensor(coordinator, "uitrukken_totaal", "total"),
            StatisticSensor(coordinator, "uitrukken_niet_ingedeeld", "not_assigned"),
            ResponseRateSensor(coordinator),
            LastTurnoutSensor(coordinator),
        ]
    )


class BrandweerSensor(BrandweerRoosterEntity, SensorEntity):
    """Base sensor."""


class LatestIncidentSensor(BrandweerSensor):
    _attr_icon = "mdi:fire-truck"
    _unrecorded_attributes = _PERSONNEL_ATTRIBUTES

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "latest_incident")

    @property
    def native_value(self) -> str:
        incident = self.incident
        if not incident:
            return "Geen incident"
        return f"Incident {incident.get('id', 'onbekend')}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        incident = self.incident
        if not incident:
            return {}
        coordinator = self.coordinator
        parsed = split_p2000(incident_body(incident))
        tasks = incident.get("task_ids") or []
        latitude, longitude = incident_coordinates(incident)
        crew = personnel(incident, coordinator.skill_map)
        return {
            "incident_id": incident.get("id"),
            "melding": parsed["melding"],
            "classificatie": classification(parsed["melding"], str(incident.get("type") or "")),
            "categorie": category(parsed["melding"]),
            "straat": parsed["straat"],
            "plaats": parsed["plaats"],
            "locatie": parsed["locatie"],
            "adres": _formatted_address(incident),
            "prioriteit": format_priority(incident.get("prio")) or incident.get("prio"),
            "incident_status": incident.get("state"),
            "type": incident.get("type"),
            "created_at": incident.get("created_at"),
            "start_time": incident.get("start_time"),
            "task_ids": tasks,
            "group_ids": incident.get("groups") or incident.get("group_ids") or [],
            "alarmeringen": [
                coordinator.task_map.get(int(task_id), f"Taak {task_id}")
                for task_id in tasks
                if str(task_id).isdigit()
            ],
            "voertuigen": incident_vehicles(incident, coordinator.vehicle_names),
            "latitude": latitude,
            "longitude": longitude,
            "afstand_km": self.incident_distance_km(),
            "bron": "FireServiceRota" if incident.get("_fallback") else "Brandweerrooster API",
            "opkomstreacties": responses(incident),
            "personeel": crew,
            "personeel_per_functie": personnel_by_function(crew),
        }


def _formatted_address(incident: dict[str, Any]) -> str | None:
    address = incident.get("address")
    if isinstance(address, dict) and address.get("formatted_address"):
        return str(address["formatted_address"])
    return incident.get("formatted_address")


class LastAlarmSensor(BrandweerSensor):
    _attr_icon = "mdi:alarm-light"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "last_alarm")

    @property
    def native_value(self) -> datetime | None:
        return alarm_datetime(self.incident)


class IncidentDistanceSensor(BrandweerSensor):
    _attr_icon = "mdi:map-marker-distance"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "incident_distance")

    @property
    def native_value(self) -> float | None:
        return self.incident_distance_km()


class CrewSensor(BrandweerSensor):
    _attr_icon = "mdi:account-group"
    _attr_native_unit_of_measurement = "personen"
    _unrecorded_attributes = _PERSONNEL_ATTRIBUTES

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "crew")

    @property
    def native_value(self) -> int:
        return len({person.get("user_id") for person in personnel(self.incident, self.coordinator.skill_map)})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        crew = personnel(self.incident, self.coordinator.skill_map)
        status = crew_status(crew, self.coordinator.crew_min_size)
        return {
            "personeel": crew,
            "per_functie": personnel_by_function(crew),
            "aantal_per_functie": status["per_functie"],
            "bezetting_compleet": status["compleet"],
            "personeel_bron": "incident_skill_assignments",
            "laatste_uitruk_voertuigen": incident_vehicles(self.incident, self.coordinator.vehicle_names),
        }


class ResponseSensor(BrandweerSensor):
    _attr_icon = "mdi:account-check"
    _attr_native_unit_of_measurement = "reacties"
    _unrecorded_attributes = _PERSONNEL_ATTRIBUTES

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "response")

    @property
    def native_value(self) -> int:
        return len(responses(self.incident))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = response_summary(self.incident)
        return {**summary, "samenvatting": summary, "reacties": responses(self.incident)}


class CurrentUserSensor(BrandweerSensor):
    _attr_icon = "mdi:account"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "current_user")

    @property
    def native_value(self) -> str:
        user = self.coordinator.current_user
        return str(user.get("name") or user.get("nickname") or user.get("id") or "Onbekend")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        user = self.coordinator.current_user
        # Only non-sensitive identification; e-mail, phone numbers and
        # addresses are deliberately not exposed.
        return {key: user.get(key) for key in ("id", "name", "nickname") if user.get(key) is not None}


class MyResponseSensor(BrandweerSensor):
    _attr_icon = "mdi:account-arrow-right"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "my_response")

    def _response(self) -> dict[str, Any]:
        user_id = self.coordinator.current_user.get("id")
        if user_id is None:
            return {}
        for response in responses(self.incident):
            if str(response.get("user_id")) == str(user_id):
                return response
        return {}

    @property
    def native_value(self) -> str:
        return response_status(self._response()) or "Geen actieve opkomst"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._response())


class UitrukMessageSensor(BrandweerSensor):
    _attr_icon = "mdi:facebook"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "uitrukbericht")

    @property
    def native_value(self) -> str:
        return "Klaar om te kopiëren" if self.incident else "Geen uitruk"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"bericht": self.coordinator.render_message(self.incident)}


class StatisticSensor(BrandweerSensor):
    _attr_native_unit_of_measurement = "uitrukken"
    _attr_state_class = SensorStateClass.MEASUREMENT

    _ICONS = {
        "month": "mdi:calendar-month",
        "previous_month": "mdi:calendar-arrow-left",
        "year": "mdi:calendar",
        "total": "mdi:counter",
        "not_assigned": "mdi:account-alert",
    }

    def __init__(self, coordinator: BrandweerRoosterCoordinator, key: str, statistic: str) -> None:
        super().__init__(coordinator, key)
        self._statistic = statistic
        self._attr_icon = self._ICONS.get(statistic)

    @property
    def native_value(self) -> int:
        return int(self.statistics.get(self._statistic, 0) or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        stats = self.statistics
        if self._statistic == "year":
            return {
                "per_functie": stats.get("functions_year", {}),
                "per_categorie": stats.get("categories_year", {}),
                "per_classificatie": stats.get("classifications_year", {}),
                "per_dagdeel": stats.get("dayparts_year", {}),
                "synchronisatie_bezig": self.coordinator.history_sync_running,
            }
        if self._statistic == "total":
            return {
                "per_functie": stats.get("functions_total", {}),
                "historie_compleet": self.coordinator.statistics.initialized,
                "synchronisatie_bezig": self.coordinator.history_sync_running,
                "historie_samenvatting": self.coordinator.history_report,
            }
        return None


class ResponseRateSensor(BrandweerSensor):
    _attr_icon = "mdi:percent-circle"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "response_rate_year")

    @property
    def native_value(self) -> float | None:
        return self.statistics.get("response_rate_year")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "gealarmeerd": self.statistics.get("alarmed_year", 0),
            "opgekomen": self.statistics.get("turned_out_year", 0),
        }


class LastTurnoutSensor(BrandweerSensor):
    _attr_icon = "mdi:fire-truck"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "last_turnout")

    @property
    def native_value(self) -> datetime | None:
        return self.statistics.get("last_turnout")
