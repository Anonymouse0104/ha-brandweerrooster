"""Config, reauthentication, options and function-profile flows for Brandweerrooster.

- Adding the integration signs in to an account and creates its first
  function profile.
- "Functie toevoegen" adds more profiles (OvD West, TS Echt, ...), each with
  its own groups/tasks, turnout counting and sensors.
- Configure holds the account-wide settings.
"""

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
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
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
    CONF_BRANDBASE,
    CONF_CREW_MIN_SIZE,
    CONF_FACEBOOK_TEMPLATE,
    CONF_GROUP_IDS,
    CONF_INCIDENT_ENTITY,
    CONF_INSTALL_BLUEPRINTS,
    CONF_PERSON_NAME,
    CONF_TASK_IDS,
    CONF_TURNOUT_MODE,
    CONF_VEHICLE_NAMES,
    DEFAULT_CREW_MIN_SIZE,
    DEFAULT_INCIDENT_ENTITY,
    DOMAIN,
    SUBENTRY_PROFILE,
    TURNOUT_MODE_RESPONSE,
    TURNOUT_MODES,
)
from .vehicles import invalid_vehicle_lines

_LOGGER = logging.getLogger(__name__)

CONF_NAME = "name"

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
            options.append({"value": str(item_id), "label": str(item_id)})
    return options


def _profile_schema(
    groups: list[dict[str, Any]], tasks: list[dict[str, Any]], defaults: Mapping[str, Any]
) -> vol.Schema:
    group_ids = [int(x) for x in defaults.get(CONF_GROUP_IDS, [])]
    task_ids = [int(x) for x in defaults.get(CONF_TASK_IDS, [])]
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Optional(CONF_GROUP_IDS, default=[str(x) for x in group_ids]): SelectSelector(
                SelectSelectorConfig(
                    options=_options(groups, group_ids), multiple=True, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional(CONF_TASK_IDS, default=[str(x) for x in task_ids]): SelectSelector(
                SelectSelectorConfig(options=_options(tasks, task_ids), multiple=True, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(
                CONF_TURNOUT_MODE, default=defaults.get(CONF_TURNOUT_MODE, TURNOUT_MODE_RESPONSE)
            ): TURNOUT_MODE_SELECTOR,
            vol.Required(
                CONF_CREW_MIN_SIZE, default=defaults.get(CONF_CREW_MIN_SIZE, DEFAULT_CREW_MIN_SIZE)
            ): CREW_SIZE_SELECTOR,
        }
    )


def _profile_values(user_input: Mapping[str, Any]) -> dict[str, Any]:
    # Keep the chosen order: the first group names the station in messages.
    groups: list[int] = []
    for value in user_input.get(CONF_GROUP_IDS, []):
        if int(value) not in groups:
            groups.append(int(value))
    return {
        CONF_GROUP_IDS: groups,
        CONF_TASK_IDS: sorted({int(x) for x in user_input.get(CONF_TASK_IDS, [])}),
        CONF_TURNOUT_MODE: user_input.get(CONF_TURNOUT_MODE) or TURNOUT_MODE_RESPONSE,
        CONF_CREW_MIN_SIZE: int(user_input.get(CONF_CREW_MIN_SIZE, DEFAULT_CREW_MIN_SIZE)),
    }


def _profile_errors(name: str, values: Mapping[str, Any], taken: set[str]) -> dict[str, str]:
    if not name:
        return {CONF_NAME: "name_required"}
    if name.casefold() in taken:
        return {CONF_NAME: "name_exists"}
    if not values[CONF_GROUP_IDS] and not values[CONF_TASK_IDS]:
        return {"base": "no_scope"}
    return {}


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


def _default_incident_entity(hass: HomeAssistant) -> str:
    if hass.states.get(DEFAULT_INCIDENT_ENTITY) is not None:
        return DEFAULT_INCIDENT_ENTITY
    for state in hass.states.async_all("sensor"):
        if "incident" in state.entity_id and "id" in state.attributes:
            return state.entity_id
    return DEFAULT_INCIDENT_ENTITY


class BrandweerroosterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in to an account and create its first function profile."""

    VERSION = 2

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

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_PROFILE: ProfileSubentryFlow}

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
                return await self.async_step_profile()

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

    async def async_step_profile(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Account settings plus the first function profile."""
        errors: dict[str, str] = {}
        if user_input:
            name = str(user_input.get(CONF_NAME, "")).strip()
            values = _profile_values(user_input)
            if not (errors := _profile_errors(name, values, set())):
                return self.async_create_entry(
                    title=self._title(),
                    data={CONF_USERNAME: self._username, CONF_PASSWORD: self._password},
                    options={
                        CONF_PERSON_NAME: str(user_input.get(CONF_PERSON_NAME, "")).strip(),
                        CONF_INCIDENT_ENTITY: user_input.get(CONF_INCIDENT_ENTITY) or DEFAULT_INCIDENT_ENTITY,
                        CONF_FACEBOOK_TEMPLATE: facebook_template.DEFAULT_TEMPLATE,
                        CONF_VEHICLE_NAMES: "",
                        CONF_BRANDBASE: True,
                        CONF_INSTALL_BLUEPRINTS: True,
                    },
                    subentries=[
                        {"subentry_type": SUBENTRY_PROFILE, "title": name, "data": values, "unique_id": None}
                    ],
                )

        defaults: dict[str, Any] = dict(user_input or {})
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PERSON_NAME, default=defaults.get(CONF_PERSON_NAME, self._default_person_name())
                ): str,
                vol.Required(
                    CONF_INCIDENT_ENTITY,
                    default=defaults.get(CONF_INCIDENT_ENTITY, _default_incident_entity(self.hass)),
                ): INCIDENT_ENTITY_SELECTOR,
            }
        ).extend(_profile_schema(self._groups, self._tasks, defaults).schema)
        return self.async_show_form(step_id="profile", data_schema=schema, errors=errors)

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
                entry = self._get_reauth_entry()
                if entry.state is not ConfigEntryState.LOADED:
                    # Not running, so no update listener to reload it.
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                    )
                # A loaded entry reloads through its update listener.
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            description_placeholders={"username": self._username},
            errors=errors,
        )

    def _default_person_name(self) -> str:
        name = self._user.get("name") or self._user.get("full_name") or self._user.get("nickname")
        return str(name or "")

    def _title(self) -> str:
        name = self._default_person_name()
        return f"Brandweerrooster ({name})" if name else "Brandweerrooster"


class BrandweerroosterOptionsFlow(OptionsFlow):
    """Account-wide settings; the entry reloads through its update listener."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = self.config_entry.options
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
                        CONF_PERSON_NAME: str(user_input.get(CONF_PERSON_NAME, "")).strip(),
                        CONF_INCIDENT_ENTITY: user_input.get(CONF_INCIDENT_ENTITY) or DEFAULT_INCIDENT_ENTITY,
                        CONF_FACEBOOK_TEMPLATE: template,
                        CONF_BRANDBASE: bool(user_input.get(CONF_BRANDBASE, True)),
                        CONF_VEHICLE_NAMES: vehicles.strip(),
                        CONF_INSTALL_BLUEPRINTS: bool(user_input.get(CONF_INSTALL_BLUEPRINTS, True)),
                    }
                )

        current = {**options, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Required(CONF_PERSON_NAME, default=current.get(CONF_PERSON_NAME, "")): str,
                vol.Required(
                    CONF_INCIDENT_ENTITY, default=current.get(CONF_INCIDENT_ENTITY) or DEFAULT_INCIDENT_ENTITY
                ): INCIDENT_ENTITY_SELECTOR,
                vol.Required(
                    CONF_FACEBOOK_TEMPLATE,
                    default=current.get(CONF_FACEBOOK_TEMPLATE) or facebook_template.DEFAULT_TEMPLATE,
                ): MULTILINE_SELECTOR,
                vol.Required(CONF_BRANDBASE, default=bool(current.get(CONF_BRANDBASE, True))): BooleanSelector(),
                vol.Optional(
                    CONF_VEHICLE_NAMES, default=str(current.get(CONF_VEHICLE_NAMES) or "")
                ): MULTILINE_SELECTOR,
                vol.Required(
                    CONF_INSTALL_BLUEPRINTS, default=bool(current.get(CONF_INSTALL_BLUEPRINTS, True))
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors, description_placeholders=placeholders
        )


class ProfileSubentryFlow(ConfigSubentryFlow):
    """Add or change a function profile (OvD West, TS Echt, ...)."""

    def _taken(self, own_subentry_id: str | None = None) -> set[str]:
        return {
            sub.title.strip().casefold()
            for sub_id, sub in self._get_entry().subentries.items()
            if sub_id != own_subentry_id
        }

    async def _async_choices(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        entry = self._get_entry()
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

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input.get(CONF_NAME, "")).strip()
            values = _profile_values(user_input)
            if not (errors := _profile_errors(name, values, self._taken())):
                return self.async_create_entry(title=name, data=values)
        groups, tasks = await self._async_choices()
        return self.async_show_form(
            step_id="user", data_schema=_profile_schema(groups, tasks, user_input or {}), errors=errors
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input.get(CONF_NAME, "")).strip()
            values = _profile_values(user_input)
            if not (errors := _profile_errors(name, values, self._taken(subentry.subentry_id))):
                # Keep migration keys (legacy ids) next to the new settings;
                # the entry reloads through its update listener.
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=name, data={**subentry.data, **values}
                )
        defaults = user_input or {CONF_NAME: subentry.title, **subentry.data}
        groups, tasks = await self._async_choices()
        return self.async_show_form(
            step_id="reconfigure", data_schema=_profile_schema(groups, tasks, defaults), errors=errors
        )
