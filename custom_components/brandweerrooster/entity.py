"""Base entity for Brandweerrooster."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import location as location_util

from .const import DOMAIN
from .coordinator import BrandweerRoosterCoordinator
from .incident import incident_coordinates


class BrandweerRoosterEntity(CoordinatorEntity[BrandweerRoosterCoordinator]):
    """Common device info, naming and unique id."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BrandweerRoosterCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Brandweerrooster",
            model="API",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.brandweerrooster.nl",
        )

    @property
    def incident(self) -> dict[str, Any] | None:
        return self.coordinator.latest_incident

    @property
    def statistics(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("statistics") or {}

    def incident_distance_km(self) -> float | None:
        """Distance from the Home Assistant home location to the incident."""
        latitude, longitude = incident_coordinates(self.incident)
        if latitude is None or longitude is None:
            return None
        meters = location_util.distance(
            self.hass.config.latitude, self.hass.config.longitude, latitude, longitude
        )
        return round(meters / 1000, 1) if meters is not None else None
