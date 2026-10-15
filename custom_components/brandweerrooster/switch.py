"""The "Piketdienst" switch of standby functions (OvD, piket)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrandweerRoosterConfigEntry
from .const import TURNOUT_MODE_DUTY
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
        if profile.turnout_mode == TURNOUT_MODE_DUTY:
            async_add_entities([StandbyDutySwitch(coordinator, profile)], config_subentry_id=subentry_id)


class StandbyDutySwitch(ProfileEntity, SwitchEntity):
    """On while you have standby duty: alarms for this function then count as turnouts.

    Brandweerrooster's own on-duty flag reflects the volunteer availability,
    so it can't tell whether you are the OvD on duty. The periods this switch
    was on are stored, so history syncs use the same rule.
    """

    _attr_icon = "mdi:shield-account"

    def __init__(self, coordinator: BrandweerRoosterCoordinator, profile: Profile) -> None:
        super().__init__(coordinator, profile, "standby_duty")

    @property
    def is_on(self) -> bool:
        return self.profile.statistics.on_duty

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        stats = self.profile.statistics
        current = stats.duty_periods[-1][0] if stats.on_duty else None
        since = stats.duty_since
        return {
            "dienst_sinds": current,
            "telt_vanaf": since.isoformat() if since else None,
            "aantal_diensten": len(stats.duty_periods),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_duty(self.profile, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_duty(self.profile, False)
