"""Binary sensors exposed by Brandweerrooster."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BrandweerRoosterCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: BrandweerRoosterCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([ApiOnlineSensor(coordinator)])


class ApiOnlineSensor(CoordinatorEntity[BrandweerRoosterCoordinator], BinarySensorEntity):
    """Indicate whether the API coordinator has valid data."""

    _attr_has_entity_name = True
    _attr_name = "API beschikbaar"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:cloud-check"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_api_online"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": coordinator.entry.title,
            "manufacturer": "Brandweerrooster",
            "model": "API",
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success
