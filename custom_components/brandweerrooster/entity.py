"""Base entities for Brandweerrooster: account-wide and per function profile."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import location as location_util

from .const import DOMAIN
from .coordinator import BrandweerRoosterCoordinator
from .incident import incident_coordinates, incident_vehicles
from .profile import Profile


class AccountEntity(CoordinatorEntity[BrandweerRoosterCoordinator]):
    """Entity of the account device (API status, user, buttons, combined total)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BrandweerRoosterCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_account")},
            name=entry.title,
            manufacturer="Brandweerrooster",
            model="Account",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.brandweerrooster.nl",
        )


class ProfileEntity(CoordinatorEntity[BrandweerRoosterCoordinator]):
    """Entity of one function profile; one device per profile."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BrandweerRoosterCoordinator, profile: Profile, key: str) -> None:
        super().__init__(coordinator)
        self.profile = profile
        self._attr_translation_key = key
        self._attr_unique_id = f"{profile.unique_prefix}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, profile.unique_prefix)},
            name=profile.name,
            manufacturer="Brandweerrooster",
            model="Functie",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.brandweerrooster.nl",
        )

    @property
    def incident(self) -> dict[str, Any] | None:
        return self.profile.latest_incident

    @property
    def statistics(self) -> dict[str, Any]:
        return self.profile.counts

    def incident_distance_km(self) -> float | None:
        """Distance from the Home Assistant home location to the incident."""
        latitude, longitude = incident_coordinates(self.incident)
        if latitude is None or longitude is None:
            return None
        meters = location_util.distance(
            self.hass.config.latitude, self.hass.config.longitude, latitude, longitude
        )
        return round(meters / 1000, 1) if meters is not None else None

    def vehicles(self) -> list[str]:
        return incident_vehicles(self.incident, self.coordinator.vehicle_names, self.coordinator.vehicle_lookup)
