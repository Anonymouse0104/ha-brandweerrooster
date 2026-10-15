"""Brandweerrooster API integration for Home Assistant.

One config entry per Brandweerrooster account. Each function (OvD West,
TS Echt, ...) is a "profile" subentry with its own device and sensors.
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import logging
from pathlib import Path
import re
import shutil
from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from . import facebook_template
from .api import (
    BrandweerRoosterApi,
    BrandweerRoosterApiError,
    BrandweerRoosterAuthenticationError,
)
from .const import (
    CONF_BRANDBASE,
    CONF_CREW_MIN_SIZE,
    CONF_FACEBOOK_TEMPLATE,
    CONF_GROUP_IDS,
    CONF_INCIDENT_ENTITY,
    CONF_INSTALL_BLUEPRINTS,
    CONF_LEGACY_IDS,
    CONF_MONITORED_GROUP_IDS,
    CONF_MONITORED_TASK_IDS,
    CONF_PERSON_NAME,
    CONF_STATION_GROUP_ID,
    CONF_TASK_IDS,
    CONF_TURNOUT_MODE,
    CONF_VEHICLE_NAMES,
    DEFAULT_CREW_MIN_SIZE,
    DEFAULT_INCIDENT_ENTITY,
    DOMAIN,
    PLATFORMS,
    SUBENTRY_PROFILE,
    TURNOUT_MODE_RESPONSE,
)
from .coordinator import BrandweerRoosterCoordinator
from .services import async_setup_services
from .statistics import async_remove_statistics
from .vehicles import DEFAULT_VEHICLE_NAMES, parse_vehicle_names

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

BLUEPRINT_SOURCE = Path(__file__).parent / "blueprints"

# Entities that belong to the account, not to a function profile.
ACCOUNT_ENTITY_KEYS = {"api_online", "current_user", "refresh_incident", "resync_statistics", "uitrukken_totaal_alle"}


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
    """Set up a Brandweerrooster account."""
    await _async_import_legacy_template(hass, entry)
    if entry.options.get(CONF_INSTALL_BLUEPRINTS, True):
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
    # Reload after options, a profile (subentry) or the password changed.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BrandweerRoosterConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: BrandweerRoosterConfigEntry) -> None:
    """Reload, and drop the statistics of removed profiles."""
    removed = [
        profile.storage_id
        for subentry_id, profile in entry.runtime_data.coordinator.profiles.items()
        if subentry_id not in entry.subentries
    ]
    await hass.config_entries.async_reload(entry.entry_id)
    for storage_id in removed:
        await async_remove_statistics(hass, storage_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the stored statistics of a removed account."""
    for subentry in entry.subentries.values():
        storage_id = entry.entry_id if subentry.data.get(CONF_LEGACY_IDS) else subentry.subentry_id
        await async_remove_statistics(hass, storage_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Turn a pre-1.5 entry (one function per entry) into an account with one profile.

    The function settings move to a profile subentry. Its entities keep their
    unique ids (and so their entity ids and history) and its statistics keep
    their storage; they are linked to the new profile.
    """
    if entry.version > 2:
        return False
    if entry.version == 2:
        return True

    old: dict[str, Any] = {**entry.data, **entry.options}
    station = int(old.get(CONF_STATION_GROUP_ID) or 0)
    groups = [station] if station else []
    groups += sorted(int(x) for x in old.get(CONF_MONITORED_GROUP_IDS, []) if int(x) != station)
    profile_data = {
        CONF_GROUP_IDS: groups,
        CONF_TASK_IDS: sorted(int(x) for x in old.get(CONF_MONITORED_TASK_IDS, [])),
        CONF_TURNOUT_MODE: old.get(CONF_TURNOUT_MODE) or TURNOUT_MODE_RESPONSE,
        CONF_CREW_MIN_SIZE: int(old.get(CONF_CREW_MIN_SIZE) or DEFAULT_CREW_MIN_SIZE),
        CONF_LEGACY_IDS: True,
    }
    title = re.sub(r"\s*\(\d+\)\s*$", "", entry.title).strip() or "Functie"

    vehicle_text = str(old.get(CONF_VEHICLE_NAMES) or "")
    if not vehicle_text.strip() or parse_vehicle_names(vehicle_text) == DEFAULT_VEHICLE_NAMES:
        # The untouched built-in list: Brandbase provides these names now.
        vehicle_text = ""
    options: dict[str, Any] = {
        CONF_PERSON_NAME: str(old.get(CONF_PERSON_NAME) or ""),
        CONF_INCIDENT_ENTITY: old.get(CONF_INCIDENT_ENTITY) or DEFAULT_INCIDENT_ENTITY,
        CONF_VEHICLE_NAMES: vehicle_text,
        CONF_BRANDBASE: True,
        CONF_INSTALL_BLUEPRINTS: bool(old.get(CONF_INSTALL_BLUEPRINTS, True)),
    }
    if old.get(CONF_FACEBOOK_TEMPLATE):
        options[CONF_FACEBOOK_TEMPLATE] = old[CONF_FACEBOOK_TEMPLATE]

    subentry = ConfigSubentry(
        data=MappingProxyType(profile_data),
        subentry_type=SUBENTRY_PROFILE,
        title=title,
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    hass.config_entries.async_update_entry(
        entry,
        title="Brandweerrooster",
        data={CONF_USERNAME: entry.data[CONF_USERNAME], CONF_PASSWORD: entry.data[CONF_PASSWORD]},
        options=options,
        version=2,
    )

    ent_reg = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        key = reg_entry.unique_id.removeprefix(prefix)
        if key not in ACCOUNT_ENTITY_KEYS:
            ent_reg.async_update_entity(reg_entry.entity_id, config_subentry_id=subentry.subentry_id)

    dev_reg = dr.async_get(hass)
    device = next(
        (
            device
            for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
            if (DOMAIN, entry.entry_id) in device.identifiers
        ),
        None,
    )
    if device is not None:
        # The existing device becomes the profile's device.
        if "new_config_subentry_id" in inspect.signature(dev_reg.async_update_device).parameters:
            # Home Assistant 2026.x: a device belongs to exactly one (sub)entry.
            dev_reg.async_update_device(
                device.id,
                new_config_entry_id=entry.entry_id,
                new_config_subentry_id=subentry.subentry_id,
                name=title,
            )
        else:
            dev_reg.async_update_device(
                device.id,
                add_config_entry_id=entry.entry_id,
                add_config_subentry_id=subentry.subentry_id,
                name=title,
            )
            dev_reg.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id, remove_config_subentry_id=None
            )
    _LOGGER.info("Brandweerrooster: instellingen omgezet naar functieprofiel '%s'", title)
    return True


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
