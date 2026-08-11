"""Config flow for Brandweerrooster API."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import (
    BrandweerRoosterApi,
    BrandweerRoosterApiError,
    BrandweerRoosterAuthenticationError,
    BrandweerRoosterConnectionError,
)
from .const import (
    CONF_MONITORED_GROUP_IDS,
    CONF_MONITORED_TASK_IDS,
    CONF_PERSON_NAME,
    CONF_SCAN_INTERVAL,
    CONF_STATION_GROUP_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class BrandweerroosterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle setup of Brandweerrooster."""

    VERSION = 1

    def __init__(self) -> None:
        self._username = ""
        self._password = ""
        self._api: BrandweerRoosterApi | None = None
        self._groups: list[dict[str, Any]] = []
        self._tasks: list[dict[str, Any]] = []
        self._user: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input:
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]
            await self.async_set_unique_id(self._username.lower())
            self._abort_if_unique_id_configured()
            self._api = BrandweerRoosterApi(
                async_get_clientsession(self.hass), self._username, self._password
            )
            try:
                self._user = await self._api.async_test_connection()
                self._groups = await self._api.async_get_groups()
                self._tasks = await self._api.async_get_tasks()
            except BrandweerRoosterAuthenticationError:
                errors["base"] = "invalid_auth"
            except BrandweerRoosterConnectionError:
                errors["base"] = "cannot_connect"
            except BrandweerRoosterApiError:
                errors["base"] = "api_error"
            except Exception:
                _LOGGER.exception("Onverwachte fout tijdens Brandweerrooster-configuratie")
                errors["base"] = "unknown"
            else:
                return await self.async_step_scope()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    async def async_step_scope(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input:
            station = int(user_input[CONF_STATION_GROUP_ID])
            monitored_groups = [int(x) for x in user_input.get(CONF_MONITORED_GROUP_IDS, [])]
            monitored_tasks = [int(x) for x in user_input.get(CONF_MONITORED_TASK_IDS, [])]
            monitored_groups = sorted(set(monitored_groups) | {station})
            return self.async_create_entry(
                title=self._title(station),
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_STATION_GROUP_ID: station,
                    CONF_MONITORED_GROUP_IDS: monitored_groups,
                    CONF_MONITORED_TASK_IDS: monitored_tasks,
                    CONF_SCAN_INTERVAL: int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                    CONF_PERSON_NAME: str(user_input.get(CONF_PERSON_NAME, "")).strip(),
                },
            )

        group_options = [
            {"value": str(item.get("id")), "label": self._label(item)}
            for item in self._groups
            if item.get("id") is not None
        ]
        task_options = [
            {"value": str(item.get("id")), "label": self._label(item)}
            for item in self._tasks
            if item.get("id") is not None
        ]
        if not group_options:
            group_options = [{"value": "0", "label": "Geen groepen gevonden (handmatige configuratie vereist)"}]

        schema = vol.Schema(
            {
                vol.Required(CONF_PERSON_NAME, default=self._default_person_name()): str,
                vol.Required(CONF_STATION_GROUP_ID): SelectSelector(
                    SelectSelectorConfig(options=group_options, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(CONF_MONITORED_GROUP_IDS, default=[]): SelectSelector(
                    SelectSelectorConfig(options=group_options, multiple=True, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(CONF_MONITORED_TASK_IDS, default=[]): SelectSelector(
                    SelectSelectorConfig(options=task_options, multiple=True, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): NumberSelector(
                    NumberSelectorConfig(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL, step=1, mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="scope", data_schema=schema)


    def _default_person_name(self) -> str:
        name = self._user.get("name") or self._user.get("full_name") or self._user.get("nickname")
        return str(name or "")

    def _title(self, station_id: int) -> str:
        for group in self._groups:
            if int(group.get("id", -1)) == station_id:
                return self._label(group)
        return f"Brandweerrooster {station_id}"

    @staticmethod
    def _label(item: dict[str, Any]) -> str:
        name = item.get("name") or item.get("title") or item.get("description") or "Onbekend"
        return f"{name} ({item.get('id')})"
