"""Event entity per function profile: fires once for every new incident."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrandweerRoosterConfigEntry
from .const import TURNOUT_MODE_DUTY
from .coordinator import BrandweerRoosterCoordinator
from .entity import ProfileEntity
from .incident import (
    category,
    classification,
    format_priority,
    incident_body,
    incident_coordinates,
    incident_id,
    split_p2000,
    station_name,
)
from .profile import Profile

EVENT_TYPES = ["new_incident", "p1_incident", "p2_incident"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrandweerRoosterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    for subentry_id, profile in coordinator.profiles.items():
        async_add_entities([BrandweerRoosterIncidentEvent(coordinator, profile)], config_subentry_id=subentry_id)


class BrandweerRoosterIncidentEvent(ProfileEntity, EventEntity):
    """Fire a Home Assistant event for every new incident of this function."""

    _attr_icon = "mdi:fire-alert"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: BrandweerRoosterCoordinator, profile: Profile) -> None:
        super().__init__(coordinator, profile, "new_incident")
        self._last_seen_incident_id = incident_id(profile.latest_incident)

    @callback
    def _handle_coordinator_update(self) -> None:
        incident = self.incident
        current_id = incident_id(incident)
        if current_id is not None and current_id != self._last_seen_incident_id:
            self._last_seen_incident_id = current_id
            # Incidents shown again after a restart or filled in from the
            # history are not new alarms.
            if current_id not in self.profile.restored_ids:
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
            "functie": self.profile.name,
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
                incident, coordinator.group_map, self.profile.station_group_id, self.profile.name
            ),
            "voertuigen": self.vehicles(),
            "bericht": coordinator.render_message(self.profile, incident),
        }
        if self.profile.turnout_mode == TURNOUT_MODE_DUTY:
            # Lets automations act only while you have standby duty.
            data["piketdienst"] = self.profile.statistics.on_duty
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
