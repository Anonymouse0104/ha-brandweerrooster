"""Brandweerrooster API integration for Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv

from .api import (
    BrandweerRoosterApi,
    BrandweerRoosterApiError,
    BrandweerRoosterAuthenticationError,
    BrandweerRoosterConnectionError,
)
from .const import DOMAIN, PLATFORMS
from .coordinator import BrandweerRoosterCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

_LOGGER = logging.getLogger(__name__)


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Brandweerrooster config entry."""
    session = async_get_clientsession(hass)
    api = BrandweerRoosterApi(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    try:
        await api.async_authenticate()
    except BrandweerRoosterAuthenticationError as err:
        raise ConfigEntryAuthFailed("Brandweerrooster-authenticatie mislukt") from err
    except BrandweerRoosterConnectionError as err:
        raise ConfigEntryNotReady("Brandweerrooster is niet bereikbaar") from err
    except BrandweerRoosterApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = BrandweerRoosterCoordinator(hass, entry, api)
    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as err:
        raise ConfigEntryNotReady(str(err)) from err

    hass.data[DOMAIN][entry.entry_id] = {"api": api, "coordinator": coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start()
    entry.async_on_unload(coordinator.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok

