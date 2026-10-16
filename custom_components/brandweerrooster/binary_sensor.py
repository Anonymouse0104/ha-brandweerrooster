"""Binary sensors exposed by Brandweerrooster."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrandweerRoosterConfigEntry
from .coordinator import BrandweerRoosterCoordinator
from .entity import AccountEntity, ProfileEntity
from .incident import crew_status, personnel
from .profile import Profile


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrandweerRoosterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities([ApiOnlineSensor(coordinator)])
    for subentry_id, profile in coordinator.profiles.items():
        async_add_entities([CrewCompleteSensor(coordinator, profile)], config_subentry_id=subentry_id)


class ApiOnlineSensor(AccountEntity, BinarySensorEntity):
    """Whether the most recent Brandweerrooster API call succeeded."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "api_online")

    @property
    def is_on(self) -> bool:
        available = self.coordinator.api.available
        return self.coordinator.last_update_success if available is None else available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        api = self.coordinator.api
        return {
            "laatste_fout": api.last_error,
            "laatste_succes": api.last_success.isoformat() if api.last_success else None,
            "historie_synchronisatie_bezig": self.coordinator.history_sync_running,
        }


class CrewCompleteSensor(ProfileEntity, BinarySensorEntity):
    """Whether the assigned crew has a commander, a driver and enough people."""

    _attr_icon = "mdi:account-group-outline"

    def __init__(self, coordinator: BrandweerRoosterCoordinator, profile: Profile) -> None:
        super().__init__(coordinator, profile, "crew_complete")

    def _status(self) -> dict[str, Any]:
        crew = personnel(self.incident, self.coordinator.skill_map)
        return crew_status(crew, self.profile.crew_min_size)

    @property
    def is_on(self) -> bool:
        # Off (not "unknown") while there is no incident yet.
        return bool(self.incident) and self._status()["compleet"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._status()
        if not self.incident:
            label = "Geen incident"
        else:
            label = "Compleet" if status["compleet"] else "Niet compleet"
        return {
            "status": label,
            "aantal": status["aantal"],
            "minimaal": status["minimaal"],
            "bevelvoerder": status["bevelvoerder"],
            "chauffeur": status["chauffeur"],
            "per_functie": status["per_functie"],
            "ontbreekt": status["ontbreekt"],
        }
