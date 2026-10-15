"""Actions (services) of the Brandweerrooster integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_TEMPLATE,
    DOMAIN,
    SERVICE_GENERATE_MESSAGE,
    SERVICE_REFRESH_INCIDENT,
    SERVICE_RESYNC_STATISTICS,
)

if TYPE_CHECKING:
    from .coordinator import BrandweerRoosterCoordinator

ENTRY_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})
MESSAGE_SCHEMA = ENTRY_SCHEMA.extend({vol.Optional(ATTR_TEMPLATE): cv.string})


def _coordinators(hass: HomeAssistant, call: ServiceCall) -> list[BrandweerRoosterCoordinator]:
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED and (entry_id is None or entry.entry_id == entry_id)
    ]
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
        )
    return [entry.runtime_data.coordinator for entry in entries]


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration actions."""

    async def generate_message(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinators(hass, call)[0]
        incident = coordinator.latest_incident
        return {
            "incident_id": incident.get("id") if incident else None,
            "bericht": coordinator.render_message(incident, call.data.get(ATTR_TEMPLATE)),
        }

    async def refresh_incident(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass, call):
            await coordinator.async_refresh_latest_incident()

    async def resync_statistics(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass, call):
            coordinator.async_start_history_sync(reset=True)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_MESSAGE,
        generate_message,
        schema=MESSAGE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH_INCIDENT, refresh_incident, schema=ENTRY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RESYNC_STATISTICS, resync_statistics, schema=ENTRY_SCHEMA)
