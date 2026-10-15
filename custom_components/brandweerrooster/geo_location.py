"""Show the latest incident of each function on the Home Assistant map."""

from __future__ import annotations

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrandweerRoosterConfigEntry
from .const import DOMAIN
from .coordinator import BrandweerRoosterCoordinator
from .entity import ProfileEntity
from .incident import incident_coordinates
from .profile import Profile


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrandweerRoosterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    for subentry_id, profile in coordinator.profiles.items():
        async_add_entities([IncidentLocation(coordinator, profile)], config_subentry_id=subentry_id)


class IncidentLocation(ProfileEntity, GeolocationEvent):
    """Location of the latest incident (only when the source provides coordinates)."""

    _attr_icon = "mdi:fire"
    _attr_source = DOMAIN
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(self, coordinator: BrandweerRoosterCoordinator, profile: Profile) -> None:
        super().__init__(coordinator, profile, "incident_location")

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
