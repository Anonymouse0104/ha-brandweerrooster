"""Show the latest incident on the Home Assistant map."""

from __future__ import annotations

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrandweerRoosterConfigEntry
from .const import DOMAIN
from .coordinator import BrandweerRoosterCoordinator
from .entity import BrandweerRoosterEntity
from .incident import incident_coordinates


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrandweerRoosterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([IncidentLocation(entry.runtime_data.coordinator)])


class IncidentLocation(BrandweerRoosterEntity, GeolocationEvent):
    """Location of the latest incident (only when the source provides coordinates)."""

    _attr_icon = "mdi:fire"
    _attr_source = DOMAIN
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(self, coordinator: BrandweerRoosterCoordinator) -> None:
        super().__init__(coordinator, "incident_location")

    @property
    def available(self) -> bool:
        return super().available and self.latitude is not None

    @property
    def latitude(self) -> float | None:
        return incident_coordinates(self.incident)[0]

    @property
    def longitude(self) -> float | None:
        return incident_coordinates(self.incident)[1]

    @property
    def distance(self) -> float | None:
        return self.incident_distance_km()
