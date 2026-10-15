"""Event entity for Brandweerrooster incidents."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrandweerRoosterConfigEntry
from .coordinator import BrandweerRoosterCoordinator
from .entity import BrandweerRoosterEntity
from .incident import (
    category,
    classification,
    format_priority,
    incident_body,
    incident_coordinates,
    incident_id,
    incident_vehicles,
    split_p2000,
    station_name,
)

EVENT_TYPES = ["new_incident", "p1_incident", "p2_incident"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrandweerRoosterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Brandweerrooster incident event entity."""
    async_add_entities([BrandweerRoosterIncidentEvent(entry.runtime_data.coordinator)])


class BrandweerRoosterIncidentEvent(BrandweerRoosterEntity, EventEntity):
    """Fire a Home Assistant event for every new incident."""

    _attr_icon = "mdi:fire-alert"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "new_incident")
        self._last_seen_incident_id = incident_id(coordinator.latest_incident)

    @callback
    def _handle_coordinator_update(self) -> None:
        incident = self.coordinator.latest_incident
        current_id = incident_id(incident)
        if current_id is not None and current_id != self._last_seen_incident_id:
            self._last_seen_incident_id = current_id
            self._trigger_event(_event_type(incident), self._event_data(incident))
        self.async_write_ha_state()

    def _event_data(self, incident: dict[str, Any] | None) -> dict[str, Any]:
        if not incident:
            return {}
        coordinator = self.coordinator
        parsed = split_p2000(incident_body(incident))
        latitude, longitude = incident_coordinates(incident)
        data: dict[str, Any] = {
            "incident_id": incident.get("id"),
            "melding": parsed["melding"],
            "classificatie": classification(parsed["melding"], str(incident.get("type") or "")),
            "categorie": category(parsed["melding"]),
            "locatie": parsed["locatie"],
            "straat": parsed["straat"],
            "plaats": parsed["plaats"],
            "prioriteit": format_priority(incident.get("prio")) or incident.get("prio"),
            "incident_type": incident.get("type"),
            "created_at": incident.get("created_at"),
            "start_time": incident.get("start_time"),
            "kazerne": station_name(
                incident, coordinator.group_map, coordinator.station_group_id, coordinator.config_entry.title
            ),
            "voertuigen": incident_vehicles(incident, coordinator.vehicle_names),
            "bericht": coordinator.render_message(incident),
        }
        if latitude is not None and longitude is not None:
            data["latitude"] = latitude
            data["longitude"] = longitude
            data["afstand_km"] = self.incident_distance_km()
        return data


def _event_type(incident: dict[str, Any] | None) -> str:
    priority = format_priority((incident or {}).get("prio"))
    if priority == "P1":
        return "p1_incident"
    if priority == "P2":
        return "p2_incident"
    return "new_incident"
