"""Buttons for Brandweerrooster."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrandweerRoosterConfigEntry
from .coordinator import BrandweerRoosterCoordinator
from .entity import BrandweerRoosterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrandweerRoosterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities([RefreshIncidentButton(coordinator), ResyncStatisticsButton(coordinator)])


class RefreshIncidentButton(BrandweerRoosterEntity, ButtonEntity):
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "refresh_incident")

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_latest_incident()


class ResyncStatisticsButton(BrandweerRoosterEntity, ButtonEntity):
    _attr_icon = "mdi:database-sync"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "resync_statistics")

    async def async_press(self) -> None:
        self.coordinator.async_start_history_sync(reset=True)
