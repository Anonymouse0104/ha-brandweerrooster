"""Config, reauthentication and options flow for Brandweerrooster."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import facebook_template
from .api import (
    BrandweerRoosterApi,
    BrandweerRoosterApiError,
    BrandweerRoosterAuthenticationError,
    BrandweerRoosterConnectionError,
    BrandweerRoosterRateLimitError,
)
from .const import (
    CONF_CREW_MIN_SIZE,
    CONF_FACEBOOK_TEMPLATE,
    CONF_INCIDENT_ENTITY,
    CONF_INSTALL_BLUEPRINTS,
    CONF_MONITORED_GROUP_IDS,
    CONF_MONITORED_TASK_IDS,
    CONF_PERSON_NAME,
    CONF_STATION_GROUP_ID,
    CONF_TURNOUT_MODE,
    CONF_VEHICLE_NAMES,
    DEFAULT_CREW_MIN_SIZE,
    DEFAULT_INCIDENT_ENTITY,
    DOMAIN,
    TURNOUT_MODE_RESPONSE,
    TURNOUT_MODES,
)
from .helpers import get_setting
from .vehicles import DEFAULT_VEHICLE_TEXT, invalid_vehicle_lines

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
MULTILINE_SELECTOR = TextSelector(TextSelectorConfig(multiline=True))
CREW_SIZE_SELECTOR = NumberSelector(NumberSelectorConfig(min=1, max=20, step=1, mode=NumberSelectorMode.BOX))
INCIDENT_ENTITY_SELECTOR = EntitySelector(EntitySelectorConfig(domain="sensor"))
TURNOUT_MODE_SELECTOR = SelectSelector(
    SelectSelectorConfig(options=TURNOUT_MODES, mode=SelectSelectorMode.LIST, translation_key=CONF_TURNOUT_MODE)
)


def _label(item: dict[str, Any]) -> str:
    name = item.get("name") or item.get("title") or item.get("description") or "Onbekend"
    return f"{name} ({item.get('id')})"


def _options(items: list[dict[str, Any]], extra_ids: list[int] | None = None) -> list[dict[str, str]]:
    options = [{"value": str(item.get("id")), "label": _label(item)} for item in items if item.get("id") is not None]
    known = {option["value"] for option in options}
    for item_id in extra_ids or []:
        if str(item_id) not in known:
            options.append({"value": str(item_id), "label": f"Groep/taak {item_id}"})
    return options


def _scope_schema(
    groups: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    defaults: Mapping[str, Any],
) -> dict[Any, Any]:
    station = defaults.get(CONF_STATION_GROUP_ID)
    group_ids = [int(x) for x in defaults.get(CONF_MONITORED_GROUP_IDS, [])]
    task_ids = [int(x) for x in defaults.get(CONF_MONITORED_TASK_IDS, [])]
    group_options = _options(groups, ([int(station)] if station else []) + group_ids)
    task_options = _options(tasks, task_ids)
    if not group_options:
        group_options = [{"value": "0", "label": "Geen groepen gevonden"}]

    station_key = (
        vol.Required(CONF_STATION_GROUP_ID, default=str(station))
        if station is not None
        else vol.Required(CONF_STATION_GROUP_ID)
    )
    return {
        vol.Required(CONF_PERSON_NAME, default=defaults.get(CONF_PERSON_NAME, "")): str,
        station_key: SelectSelector(SelectSelectorConfig(options=group_options, mode=SelectSelectorMode.DROPDOWN)),
        vol.Optional(CONF_MONITORED_GROUP_IDS, default=[str(x) for x in group_ids]): SelectSelector(
            SelectSelectorConfig(options=group_options, multiple=True, mode=SelectSelectorMode.DROPDOWN)
        ),
        vol.Optional(CONF_MONITORED_TASK_IDS, default=[str(x) for x in task_ids]): SelectSelector(
            SelectSelectorConfig(options=task_options, multiple=True, mode=SelectSelectorMode.DROPDOWN)
        ),
        vol.Required(
            CONF_INCIDENT_ENTITY, default=defaults.get(CONF_INCIDENT_ENTITY, DEFAULT_INCIDENT_ENTITY)
        ): INCIDENT_ENTITY_SELECTOR,
        vol.Required(
            CONF_TURNOUT_MODE, default=defaults.get(CONF_TURNOUT_MODE, TURNOUT_MODE_RESPONSE)
        ): TURNOUT_MODE_SELECTOR,
        vol.Required(
            CONF_CREW_MIN_SIZE, default=defaults.get(CONF_CREW_MIN_SIZE, DEFAULT_CREW_MIN_SIZE)
        ): CREW_SIZE_SELECTOR,
    }


def _scope_values(user_input: dict[str, Any]) -> dict[str, Any]:
    station = int(user_input[CONF_STATION_GROUP_ID])
    monitored_groups = sorted({int(x) for x in user_input.get(CONF_MONITORED_GROUP_IDS, [])} | {station})
    return {
        CONF_PERSON_NAME: str(user_input.get(CONF_PERSON_NAME, "")).strip(),
        CONF_STATION_GROUP_ID: station,
        CONF_MONITORED_GROUP_IDS: monitored_groups,
        CONF_MONITORED_TASK_IDS: sorted({int(x) for x in user_input.get(CONF_MONITORED_TASK_IDS, [])}),
        CONF_INCIDENT_ENTITY: user_input.get(CONF_INCIDENT_ENTITY) or DEFAULT_INCIDENT_ENTITY,
        CONF_CREW_MIN_SIZE: int(user_input.get(CONF_CREW_MIN_SIZE, DEFAULT_CREW_MIN_SIZE)),
        CONF_TURNOUT_MODE: user_input.get(CONF_TURNOUT_MODE) or TURNOUT_MODE_RESPONSE,
    }


def _error_key(err: Exception) -> str:
    if isinstance(err, BrandweerRoosterAuthenticationError):
        return "invalid_auth"
    if isinstance(err, BrandweerRoosterRateLimitError):
        return "rate_limited"
    if isinstance(err, BrandweerRoosterConnectionError):
        return "cannot_connect"
    if isinstance(err, BrandweerRoosterApiError):
        return "api_error"
    return "unknown"


class BrandweerroosterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup of Brandweerrooster."""

    VERSION = 1

    def __init__(self) -> None:
        self._username = ""
        self._password = ""
        self._groups: list[dict[str, Any]] = []
        self._tasks: list[dict[str, Any]] = []
        self._user: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BrandweerroosterOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input:
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]
            await self.async_set_unique_id(self._username.lower())
            self._abort_if_unique_id_configured()
            api = BrandweerRoosterApi(async_get_clientsession(self.hass), self._username, self._password)
            try:
                self._user = await api.async_test_connection()
                self._groups = await api.async_get_groups()
                self._tasks = await api.async_get_tasks()
            except Exception as err:  # noqa: BLE001 - mapped to a form error
                errors["base"] = _error_key(err)
                if errors["base"] == "unknown":
                    _LOGGER.exception("Onverwachte fout tijdens Brandweerrooster-configuratie")
            else:
                return await self.async_step_scope()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=self._username): str,
                    vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
                }
            ),
            errors=errors,
        )

    async def async_step_scope(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input:
            values = _scope_values(user_input)
            return self.async_create_entry(
                title=self._title(values[CONF_STATION_GROUP_ID]),
                data={CONF_USERNAME: self._username, CONF_PASSWORD: self._password, **values},
                options={
                    CONF_FACEBOOK_TEMPLATE: facebook_template.DEFAULT_TEMPLATE,
                    CONF_VEHICLE_NAMES: DEFAULT_VEHICLE_TEXT,
                    CONF_INSTALL_BLUEPRINTS: True,
                },
            )

        defaults = {
            CONF_PERSON_NAME: self._default_person_name(),
            CONF_INCIDENT_ENTITY: self._default_incident_entity(),
        }
        return self.async_show_form(
            step_id="scope",
            data_schema=vol.Schema(_scope_schema(self._groups, self._tasks, defaults)),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._username = str(entry_data.get(CONF_USERNAME, ""))
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input:
            api = BrandweerRoosterApi(async_get_clientsession(self.hass), self._username, user_input[CONF_PASSWORD])
            try:
                await api.async_test_connection()
            except Exception as err:  # noqa: BLE001 - mapped to a form error
                errors["base"] = _error_key(err)
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            description_placeholders={"username": self._username},
            errors=errors,
        )

    def _default_person_name(self) -> str:
        name = self._user.get("name") or self._user.get("full_name") or self._user.get("nickname")
        return str(name or "")

    def _default_incident_entity(self) -> str:
        if self.hass.states.get(DEFAULT_INCIDENT_ENTITY) is not None:
            return DEFAULT_INCIDENT_ENTITY
        for state in self.hass.states.async_all("sensor"):
            if state.entity_id.endswith("_incidents") and "id" in state.attributes:
                return state.entity_id
        return DEFAULT_INCIDENT_ENTITY

    def _title(self, station_id: int) -> str:
        for group in self._groups:
            try:
                if int(group.get("id", -1)) == station_id:
                    return _label(group)
            except (TypeError, ValueError):
                continue
        return f"Brandweerrooster {station_id}"


class BrandweerroosterOptionsFlow(OptionsFlowWithReload):
    """Change every setting of the integration from the UI (reloads on save)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}
        placeholders = {
            "details": "",
            "placeholders": " ".join("{" + name + "}" for name in facebook_template.PLACEHOLDERS),
        }

        if user_input is not None:
            template = str(user_input.get(CONF_FACEBOOK_TEMPLATE) or "").strip()
            vehicles = str(user_input.get(CONF_VEHICLE_NAMES) or "")
            unknown = facebook_template.unknown_placeholders(template)
            invalid = invalid_vehicle_lines(vehicles)
            if not template:
                errors[CONF_FACEBOOK_TEMPLATE] = "template_empty"
            elif unknown:
                errors[CONF_FACEBOOK_TEMPLATE] = "template_unknown_placeholder"
                placeholders["details"] = ", ".join("{" + name + "}" for name in unknown)
            if invalid:
                errors[CONF_VEHICLE_NAMES] = "vehicle_invalid"
                placeholders["details"] = ", ".join(invalid[:5])
            if not errors:
                return self.async_create_entry(
                    data={
                        **_scope_values(user_input),
                        CONF_FACEBOOK_TEMPLATE: template,
                        CONF_VEHICLE_NAMES: vehicles.strip(),
                        CONF_INSTALL_BLUEPRINTS: bool(user_input.get(CONF_INSTALL_BLUEPRINTS, True)),
                    }
                )

        groups, tasks = await self._async_load_choices()
        current = {
            key: get_setting(entry, key)
            for key in (
                CONF_PERSON_NAME,
                CONF_STATION_GROUP_ID,
                CONF_MONITORED_GROUP_IDS,
                CONF_MONITORED_TASK_IDS,
                CONF_INCIDENT_ENTITY,
                CONF_CREW_MIN_SIZE,
                CONF_TURNOUT_MODE,
            )
            if get_setting(entry, key) is not None
        }
        if user_input is not None:
            current.update({k: v for k, v in _scope_values(user_input).items()})
        schema = _scope_schema(groups, tasks, current)
        if user_input is not None:
            vehicle_default = str(user_input.get(CONF_VEHICLE_NAMES) or "")
        else:
            vehicle_default = str(get_setting(entry, CONF_VEHICLE_NAMES, DEFAULT_VEHICLE_TEXT) or "")
        schema.update(
            {
                vol.Required(
                    CONF_FACEBOOK_TEMPLATE,
                    default=(user_input or {}).get(CONF_FACEBOOK_TEMPLATE)
                    or get_setting(entry, CONF_FACEBOOK_TEMPLATE, facebook_template.DEFAULT_TEMPLATE),
                ): MULTILINE_SELECTOR,
                vol.Optional(CONF_VEHICLE_NAMES, default=vehicle_default): MULTILINE_SELECTOR,
                vol.Required(
                    CONF_INSTALL_BLUEPRINTS, default=bool(get_setting(entry, CONF_INSTALL_BLUEPRINTS, True))
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _async_load_choices(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        entry = self.config_entry
        if entry.state is ConfigEntryState.LOADED:
            api = entry.runtime_data.api
        else:
            api = BrandweerRoosterApi(
                async_get_clientsession(self.hass), entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
            )
        try:
            return await api.async_get_groups(), await api.async_get_tasks()
        except BrandweerRoosterApiError as err:
            _LOGGER.warning("Groepen en taken konden niet worden geladen: %s", err)
            return [], []
