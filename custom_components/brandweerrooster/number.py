"""Own corrections of the turnout counters, per function."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrandweerRoosterConfigEntry
from .coordinator import BrandweerRoosterCoordinator
from .entity import ProfileEntity
from .profile import Profile


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrandweerRoosterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    for subentry_id, profile in coordinator.profiles.items():
        async_add_entities(
            [
                TurnoutCorrection(coordinator, profile, "total"),
                TurnoutCorrection(coordinator, profile, "year"),
            ],
            config_subentry_id=subentry_id,
        )


class TurnoutCorrection(ProfileEntity, NumberEntity):
    """Turnouts to add to the counted ones, e.g. from another system.

    The total correction is added to "Uitrukken totaal", the year correction
    to "Uitrukken dit jaar" (and back to 0 on 1 January). Negative values
    correct an over-count.
    """

    _attr_icon = "mdi:counter"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = -9999
    _attr_native_max_value = 99999
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "uitrukken"

    def __init__(self, coordinator: BrandweerRoosterCoordinator, profile: Profile, kind: str) -> None:
        super().__init__(coordinator, profile, f"correction_{kind}")
        self._kind = kind

    @property
    def native_value(self) -> int:
        stats = self.profile.statistics
        return stats.correction_year() if self._kind == "year" else stats.correction_total

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_correction(self.profile, self._kind, int(value))
