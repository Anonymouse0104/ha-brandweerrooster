"""Event entity for Brandweerrooster incidents."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BrandweerRoosterCoordinator
from .sensor import _incident_coordinates, _incident_vehicles, _split_p2000, _station_name_for_incident


EVENT_TYPES = [
    "new_incident",
    "p1_incident",
    "p2_incident",
    "other_incident",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Brandweerrooster incident event entity."""
    coordinator: BrandweerRoosterCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([BrandweerRoosterIncidentEvent(coordinator)])


class BrandweerRoosterIncidentEvent(
    CoordinatorEntity[BrandweerRoosterCoordinator], EventEntity
):
    """Expose new Brandweerrooster incidents as Home Assistant events."""

    _attr_has_entity_name = True
    _attr_translation_key = "new_incident"
    _attr_icon = "mdi:fire-alert"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_new_incident"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": coordinator.entry.title,
            "manufacturer": "Brandweerrooster",
            "model": "API",
        }
        incident = (coordinator.data or {}).get("latest_incident")
        self._last_seen_incident_id = _incident_id(incident)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fire an event when a new incident becomes available."""
        incident = (self.coordinator.data or {}).get("latest_incident")
        incident_id = _incident_id(incident)
        if incident_id is not None and incident_id != self._last_seen_incident_id:
            self._last_seen_incident_id = incident_id
            self._trigger_event(_event_type(incident), _event_data(incident, self.coordinator))
            self.async_write_ha_state()
            return
        self.async_write_ha_state()


def _incident_id(incident: dict[str, Any] | None) -> int | None:
    if not incident:
        return None
    try:
        return int(incident.get("id"))
    except (TypeError, ValueError):
        return None


def _event_type(incident: dict[str, Any] | None) -> str:
    priority = str((incident or {}).get("prio") or "").strip().upper().replace("PRIO", "P")
    if priority == "P1" or priority == "1":
        return "p1_incident"
    if priority == "P2" or priority == "2":
        return "p2_incident"
    return "new_incident"


def _event_data(
    incident: dict[str, Any] | None,
    coordinator: BrandweerRoosterCoordinator,
) -> dict[str, Any]:
    if not incident:
        return {}

    body = str(incident.get("body") or incident.get("location") or "")
    parsed = _split_p2000(body)
    latitude, longitude = _incident_coordinates(incident)
    vehicles = _incident_vehicles(incident, coordinator)

    data: dict[str, Any] = {
        "incident_id": incident.get("id"),
        "melding": parsed["melding"],
        "locatie": parsed["locatie"],
        "straat": parsed["straat"],
        "plaats": parsed["plaats"],
        "prioriteit": incident.get("prio"),
        "incident_type": incident.get("type"),
        "created_at": incident.get("created_at"),
        "start_time": incident.get("start_time"),
        "kazerne": _station_name_for_incident(incident, coordinator),
        "voertuigen": vehicles,
    }
    if latitude is not None:
        data["latitude"] = latitude
    if longitude is not None:
        data["longitude"] = longitude
    return data
