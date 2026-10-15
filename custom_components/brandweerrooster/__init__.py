"""Brandweerrooster API integration for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from . import facebook_template
from .api import (
    BrandweerRoosterApi,
    BrandweerRoosterApiError,
    BrandweerRoosterAuthenticationError,
)
from .const import CONF_FACEBOOK_TEMPLATE, CONF_INSTALL_BLUEPRINTS, DOMAIN, PLATFORMS
from .coordinator import BrandweerRoosterCoordinator
from .helpers import get_setting
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

BLUEPRINT_SOURCE = Path(__file__).parent / "blueprints"


@dataclass
class BrandweerRoosterData:
    """Runtime data of a config entry."""

    api: BrandweerRoosterApi
    coordinator: BrandweerRoosterCoordinator


type BrandweerRoosterConfigEntry = ConfigEntry[BrandweerRoosterData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration domain."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BrandweerRoosterConfigEntry) -> bool:
    """Set up a Brandweerrooster config entry."""
    await _async_import_legacy_template(hass, entry)
    if get_setting(entry, CONF_INSTALL_BLUEPRINTS, True):
        await hass.async_add_executor_job(_install_blueprints, Path(hass.config.path("blueprints", "automation", DOMAIN)))

    api = BrandweerRoosterApi(async_get_clientsession(hass), entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    try:
        await api.async_authenticate()
    except BrandweerRoosterAuthenticationError as err:
        raise ConfigEntryAuthFailed("Brandweerrooster-authenticatie mislukt") from err
    except BrandweerRoosterApiError as err:
        raise ConfigEntryNotReady(f"Brandweerrooster is niet bereikbaar: {err}") from err

    coordinator = BrandweerRoosterCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = BrandweerRoosterData(api=api, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start()
    entry.async_on_unload(coordinator.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BrandweerRoosterConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_import_legacy_template(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move a customised pre-1.4 YAML template into the options (once)."""
    if CONF_FACEBOOK_TEMPLATE in entry.options:
        return
    template = await facebook_template.async_read_legacy_template(hass)
    options: dict[str, Any] = dict(entry.options)
    options[CONF_FACEBOOK_TEMPLATE] = template or facebook_template.DEFAULT_TEMPLATE
    hass.config_entries.async_update_entry(entry, options=options)
    if template:
        _LOGGER.info(
            "Je eigen Facebook-sjabloon is overgenomen in de integratie-opties. "
            "Het bestand /config/brandweerrooster/facebook_template.yaml wordt niet meer gebruikt"
        )


def _install_blueprints(target: Path) -> None:
    """Copy the bundled automation blueprints to the blueprint folder.

    Existing files are only replaced when they were installed by this
    integration and not changed by the user.
    """
    try:
        target.mkdir(parents=True, exist_ok=True)
        for source in BLUEPRINT_SOURCE.glob("*.yaml"):
            destination = target / source.name
            if destination.exists():
                current = destination.read_text(encoding="utf-8")
                if "# managed-by: brandweerrooster" not in current:
                    continue
                if current == source.read_text(encoding="utf-8"):
                    continue
            shutil.copyfile(source, destination)
    except OSError as err:
        _LOGGER.warning("Blueprints konden niet worden geïnstalleerd: %s", err)
