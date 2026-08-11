"""Async client for the Brandweerrooster API."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .const import API_BASE_URL, API_TIMEOUT, OAUTH_TOKEN_URL


class BrandweerRoosterApiError(Exception):
    """Base exception for API errors."""


class BrandweerRoosterAuthenticationError(BrandweerRoosterApiError):
    """Authentication failed."""


class BrandweerRoosterConnectionError(BrandweerRoosterApiError):
    """Connection to the API failed."""


class BrandweerRoosterApi:
    """Small, dependency-free client for Brandweerrooster API v2."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username.strip()
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_lock = asyncio.Lock()

    async def async_authenticate(self) -> None:
        """Authenticate using the documented OAuth password grant."""
        async with self._token_lock:
            await self._async_request_password_token()

    async def _async_request_password_token(self) -> None:
        data = {
            "grant_type": "password",
            "username": self._username,
            "password": self._password,
        }
        try:
            async with self._session.post(
                OAUTH_TOKEN_URL,
                data=data,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as response:
                payload = await self._read_response(response)
        except asyncio.TimeoutError as err:
            raise BrandweerRoosterConnectionError("Timeout tijdens authenticatie") from err
        except aiohttp.ClientError as err:
            raise BrandweerRoosterConnectionError("Verbindingsfout tijdens authenticatie") from err

        if response.status not in (200, 201) or not isinstance(payload, dict):
            raise BrandweerRoosterAuthenticationError(self._extract_error(payload, "Ongeldige Brandweerrooster-inloggegevens"))

        token = payload.get("access_token")
        if not token:
            raise BrandweerRoosterAuthenticationError("Brandweerrooster gaf geen access_token terug")

        self._access_token = str(token)
        refresh_token = payload.get("refresh_token")
        self._refresh_token = str(refresh_token) if refresh_token else None

    async def _async_refresh_access_token(self) -> None:
        if not self._refresh_token:
            await self._async_request_password_token()
            return

        try:
            async with self._session.post(
                OAUTH_TOKEN_URL,
                data={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as response:
                payload = await self._read_response(response)
        except (asyncio.TimeoutError, aiohttp.ClientError):
            await self._async_request_password_token()
            return

        if response.status not in (200, 201) or not isinstance(payload, dict) or not payload.get("access_token"):
            await self._async_request_password_token()
            return

        self._access_token = str(payload["access_token"])
        if payload.get("refresh_token"):
            self._refresh_token = str(payload["refresh_token"])

    async def async_get(self, endpoint: str, params: dict[str, Any] | None = None, *, retry_auth: bool = True) -> Any:
        """Perform an authenticated GET request."""
        if not self._access_token:
            await self.async_authenticate()

        endpoint = endpoint.lstrip("/")
        url = f"{API_BASE_URL}/{endpoint}"
        if params:
            url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)}"

        headers = {"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"}
        try:
            async with self._session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as response:
                if response.status == 401:
                    if not retry_auth:
                        raise BrandweerRoosterAuthenticationError("Brandweerrooster-token is niet geldig")
                    async with self._token_lock:
                        await self._async_refresh_access_token()
                    return await self.async_get(endpoint, params, retry_auth=False)

                payload = await self._read_response(response)
                if response.status < 200 or response.status >= 300:
                    raise BrandweerRoosterApiError(self._extract_error(payload, f"Brandweerrooster API-fout HTTP {response.status}"))
                return payload
        except BrandweerRoosterApiError:
            raise
        except asyncio.TimeoutError as err:
            raise BrandweerRoosterConnectionError(f"Timeout bij Brandweerrooster API: {endpoint}") from err
        except aiohttp.ClientError as err:
            raise BrandweerRoosterConnectionError(f"Verbindingsfout bij Brandweerrooster API: {endpoint}") from err

    async def async_get_current_user(self) -> dict[str, Any]:
        payload = await self.async_get("users/current")
        return payload if isinstance(payload, dict) else {}

    async def async_get_groups(self) -> list[dict[str, Any]]:
        return self._as_list(await self.async_get("groups", {"page": 1, "per_page": 200}))

    async def async_get_tasks(self) -> list[dict[str, Any]]:
        return self._as_list(await self.async_get("tasks", {"page": 1, "per_page": 200}))

    async def async_get_skills(self) -> list[dict[str, Any]]:
        return self._as_list(await self.async_get("skills", {"page": 1, "per_page": 200}))

    async def async_get_incidents(
        self, *, per_page: int = 50, page: int = 1
    ) -> list[dict[str, Any]]:
        """Get one page of incidents.

        The Brandweerrooster API uses RFC-8288 pagination headers. The helper
        intentionally exposes pages so the statistics component can perform a
        one-time historical sync without downloading all history every poll.
        """
        payload = await self.async_get(
            "incidents", {"page": page, "per_page": per_page}
        )
        return self._as_list(payload)

    async def async_get_incident(self, incident_id: int) -> dict[str, Any]:
        payload = await self.async_get(f"incidents/{incident_id}")
        if not isinstance(payload, dict):
            raise BrandweerRoosterApiError(f"Ongeldig antwoord voor incident {incident_id}")
        return payload

    async def async_test_connection(self) -> dict[str, Any]:
        await self.async_authenticate()
        return await self.async_get_current_user()

    @staticmethod
    def _as_list(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("data", "items", "results", "incidents", "groups", "tasks", "skills"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    async def _read_response(response: aiohttp.ClientResponse) -> Any:
        try:
            return await response.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            text = await response.text()
            return {"error": text} if text else {}

    @staticmethod
    def _extract_error(payload: Any, default: str) -> str:
        if isinstance(payload, dict):
            for key in ("error_description", "message", "error", "detail"):
                if payload.get(key):
                    return str(payload[key])
        return default
