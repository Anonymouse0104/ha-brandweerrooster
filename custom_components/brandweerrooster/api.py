"""Async client for the Brandweerrooster API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, UTC
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


class BrandweerRoosterRateLimitError(BrandweerRoosterApiError):
    """The API is temporarily rate limiting requests."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class BrandweerRoosterApi:
    """Small, dependency-free client for Brandweerrooster API v2."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username.strip()
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        # Incremented on every new access token, so concurrent requests that
        # all receive a 401 refresh the token only once.
        self._token_generation = 0
        self._token_lock = asyncio.Lock()

        # Health information for the "API beschikbaar" entity.
        self.available: bool | None = None
        self.last_error: str | None = None
        self.last_success: datetime | None = None
        self.status_listener: Callable[[], None] | None = None

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
                status = response.status
        except TimeoutError as err:
            self._set_status(False, "Timeout tijdens authenticatie")
            raise BrandweerRoosterConnectionError("Timeout tijdens authenticatie") from err
        except aiohttp.ClientError as err:
            self._set_status(False, "Verbindingsfout tijdens authenticatie")
            raise BrandweerRoosterConnectionError("Verbindingsfout tijdens authenticatie") from err

        if status == 429:
            self._set_status(False, "Rate-limit tijdens authenticatie")
            raise BrandweerRoosterRateLimitError("Brandweerrooster rate-limit tijdens authenticatie")
        if status >= 500:
            self._set_status(False, f"HTTP {status} tijdens authenticatie")
            raise BrandweerRoosterConnectionError(f"Brandweerrooster gaf HTTP {status} tijdens authenticatie")
        if status not in (200, 201) or not isinstance(payload, dict):
            self._set_status(False, "Ongeldige inloggegevens")
            raise BrandweerRoosterAuthenticationError(
                self._extract_error(payload, "Ongeldige Brandweerrooster-inloggegevens")
            )

        token = payload.get("access_token")
        if not token:
            raise BrandweerRoosterAuthenticationError("Brandweerrooster gaf geen access_token terug")

        self._access_token = str(token)
        self._token_generation += 1
        refresh_token = payload.get("refresh_token")
        self._refresh_token = str(refresh_token) if refresh_token else None

    async def _async_refresh_access_token(self, generation: int) -> None:
        """Refresh the token unless another request already did so."""
        async with self._token_lock:
            if generation != self._token_generation:
                return
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
                    status = response.status
            except (TimeoutError, aiohttp.ClientError):
                await self._async_request_password_token()
                return

            if status not in (200, 201) or not isinstance(payload, dict) or not payload.get("access_token"):
                await self._async_request_password_token()
                return

            self._access_token = str(payload["access_token"])
            self._token_generation += 1
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

        generation = self._token_generation
        headers = {"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"}
        try:
            async with self._session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as response:
                status = response.status
                if status == 401:
                    if not retry_auth:
                        self._set_status(False, "Token niet geldig")
                        raise BrandweerRoosterAuthenticationError("Brandweerrooster-token is niet geldig")
                    payload = None
                else:
                    payload = await self._read_response(response)
                    retry_header = response.headers.get("Retry-After")
        except TimeoutError as err:
            self._set_status(False, f"Timeout bij {endpoint}")
            raise BrandweerRoosterConnectionError(f"Timeout bij Brandweerrooster API: {endpoint}") from err
        except aiohttp.ClientError as err:
            self._set_status(False, f"Verbindingsfout bij {endpoint}")
            raise BrandweerRoosterConnectionError(f"Verbindingsfout bij Brandweerrooster API: {endpoint}") from err

        if status == 401:
            await self._async_refresh_access_token(generation)
            return await self.async_get(endpoint, params, retry_auth=False)

        if status == 429:
            retry_after: int | None = None
            if retry_header:
                try:
                    retry_after = max(1, int(retry_header))
                except ValueError:
                    retry_after = None
            self._set_status(False, "Rate-limit bereikt")
            raise BrandweerRoosterRateLimitError(
                self._extract_error(
                    payload,
                    "Brandweerrooster rate-limit bereikt; probeer het later opnieuw.",
                ),
                retry_after,
            )
        if status >= 500:
            self._set_status(False, f"HTTP {status}")
            raise BrandweerRoosterConnectionError(f"Brandweerrooster API-fout HTTP {status}")
        if status < 200 or status >= 300:
            # A 4xx for a single resource says nothing about API health.
            raise BrandweerRoosterApiError(self._extract_error(payload, f"Brandweerrooster API-fout HTTP {status}"))

        self._set_status(True, None)
        return payload

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
        """Get one page of incidents (newest first)."""
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

    def _set_status(self, available: bool, error: str | None) -> None:
        changed = available != self.available or error != self.last_error
        self.available = available
        self.last_error = error
        if available:
            self.last_success = datetime.now(UTC)
        if changed and self.status_listener is not None:
            self.status_listener()

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
