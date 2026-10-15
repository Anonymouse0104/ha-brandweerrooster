"""Vehicle names from Brandbase (brandbase.hetbrandweerforum.nl).

P2000 alerts name fire brigade units by call sign (235331 = 23-5331). Brandbase
lists the vehicle type and post per call sign, one page per veiligheidsregio.
The pages are fetched politely:

- only regions that actually appear in your incidents,
- each region at most once a week (failures retried after a day),
- one request at a time with at least REQUEST_DELAY seconds in between,
- a descriptive User-Agent, results cached in .storage across restarts.

Same approach as the P2000 Monitor integration.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import html
import logging
import re
from typing import Any

import aiohttp

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://brandbase.hetbrandweerforum.nl"
INDEX_URL = f"{BASE_URL}/voertuigen/regios/"
USER_AGENT = "Brandweerrooster-HomeAssistant (+https://github.com/Anonymouse0104/ha-brandweerrooster)"
REFRESH_AFTER = timedelta(days=7)
RETRY_AFTER = timedelta(days=1)
# robots.txt asks for a crawl delay of 10 seconds; stay above it.
REQUEST_DELAY = 15
TIMEOUT = aiohttp.ClientTimeout(total=30)
STORAGE_KEY = "brandweerrooster.brandbase"
STORAGE_VERSION = 1

_REGION_LINK = re.compile(r'href="(https://brandbase\.hetbrandweerforum\.nl/voertuigen/regio/(\d{2})-[^"/]+/)"')
_VEHICLE_LINK = re.compile(
    r'<a href="(https://brandbase\.hetbrandweerforum\.nl/voertuigen/[^"]+)">\s*(\d{2}-\d{4})\s+([^<]*)</a>'
)
_POST_HEADING = re.compile(r"^\s*(\d{2}-\d{2})\s+(.*)$")
# Indirection so tests can skip the real delay.
_sleep = asyncio.sleep

# Vehicle types as listed on Brandbase -> the short name used in Dutch
# dispatch messages. More specific names come first ("Tankautospuit
# Terreinvaardig" before "Tankautospuit"). A leading "Dienstvoertuig" is
# ignored, so "Dienstvoertuig Officier van Dienst" becomes OvD.
_TYPE_ABBREVIATIONS = (
    ("tankautospuit terreinvaardig", "TST"),
    ("tankautospuit", "TS"),
    ("hulpverleningsvoertuig", "HV"),
    ("autoladder", "AL"),
    ("hoogwerker", "HW"),
    ("redvoertuig", "RV"),
    ("waterongevallenvoertuig", "WO"),
    ("waterongevallenaanhanger", "WOA"),
    ("watertankhaakarmbak", "WTH"),
    ("watertankwagen", "WTW"),
    ("snel inzetbaar voertuig", "SIV"),
    ("ondersteuningsteamvoertuig", "OTV"),
    ("haakarmvoertuig", "HA"),
    ("hoofdofficier van dienst", "HOvD"),
    ("officier van dienst", "OvD"),
    ("officer van dienst", "OvD"),
    ("commandant van dienst", "CvD"),
    ("adviseur gevaarlijke stoffen", "AGS"),
    ("gaspakteamvoertuig", "GPT"),
    ("schuimblusvoertuig", "SB"),
    ("motorspuitaanhanger", "MSA"),
    ("personeel/materieelvoertuig", "PM"),
    ("logistiek voertuig", "LV"),
    ("commandovoertuig", "CO"),
    ("verkenningseenheid", "VE"),
    ("voorlichter", "VL"),
    ("dienstauto", "DA"),
    ("dienstbus", "DB"),
)


def parse_index(page: str) -> dict[str, str]:
    """Region number -> region page URL."""
    return {number: url for url, number in _REGION_LINK.findall(page)}


def parse_region(page: str) -> dict[str, dict[str, str]]:
    """Call sign -> {type, post, station, url} from a region page."""
    vehicles: dict[str, dict[str, str]] = {}
    for section in page.split("<h3>")[1:]:
        heading, _, body = section.partition("</h3>")
        heading = html.unescape(re.sub(r"<[^>]+>", "", heading)).strip()
        post, station = "", heading
        if match := _POST_HEADING.match(heading):
            post, station = match.group(1), match.group(2).strip()
        body = body.split("<h3>", 1)[0]
        for url, call_sign, vehicle_type in _VEHICLE_LINK.findall(body):
            vehicles.setdefault(
                call_sign,
                {"type": html.unescape(vehicle_type).strip(), "post": post, "station": station, "url": url},
            )
    return vehicles


def call_sign(code: str) -> str:
    """235331 / 23-5331 -> 23-5331."""
    digits = re.sub(r"\D", "", str(code))
    return f"{digits[:2]}-{digits[2:]}" if len(digits) == 6 else str(code)


def short_type(vehicle_type: str) -> str:
    """Tankautospuit Terreinvaardig -> TST; unknown types are kept (without plate numbers)."""
    cleaned = re.sub(r"\s*\([^)]*\)", "", vehicle_type).strip()
    lowered = re.sub(r"^dienstvoertuig\s+", "", cleaned.casefold())
    for name, abbreviation in _TYPE_ABBREVIATIONS:
        if lowered.startswith(name):
            return abbreviation
    return cleaned


def short_name(info: dict[str, str]) -> str:
    """{type: Tankautospuit, station: Echt} -> TS Echt."""
    vehicle_type = short_type(str(info.get("type") or "").strip())
    station = str(info.get("station") or "").strip()
    return f"{vehicle_type} {station}".strip() or str(info.get("post") or "")


class BrandbaseVehicles:
    """Cached, lazily filled lookup of fire brigade call signs."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {"index": {}, "regions": {}}
        self._pending: set[str] = set()
        self._worker: asyncio.Task | None = None
        self._listeners: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._data = {"index": stored.get("index") or {}, "regions": stored.get("regions") or {}}

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> CALLBACK_TYPE:
        """Called when new vehicle data arrived, so entities can refresh."""
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)

    async def async_stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._worker = None
        self._pending.clear()

    @callback
    def lookup(self, code: str) -> dict[str, str] | None:
        """Return Brandbase info for a call sign and queue its region when unknown or stale."""
        sign = call_sign(code)
        region = sign[:2]
        self._request(region)
        return (self._data["regions"].get(region) or {}).get("vehicles", {}).get(sign)

    @property
    def region_count(self) -> int:
        return len(self._data["regions"])

    def _region_due(self, region: str) -> bool:
        state = self._data["regions"].get(region)
        if not state:
            return True
        checked = dt_util.parse_datetime(state.get("checked", ""))
        wait = REFRESH_AFTER if state.get("ok") else RETRY_AFTER
        return checked is None or dt_util.utcnow() - checked > wait

    @callback
    def _request(self, region: str) -> None:
        if not region.isdigit() or region in self._pending or not self._region_due(region):
            return
        self._pending.add(region)
        if self._worker is None or self._worker.done():
            self._worker = self.hass.async_create_background_task(self._run(), "brandweerrooster brandbase")

    async def _fetch(self, url: str) -> str:
        session = async_get_clientsession(self.hass)
        async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT) as response:
            response.raise_for_status()
            return await response.text()

    async def _run(self) -> None:
        """Fetch queued regions one by one, REQUEST_DELAY seconds apart."""
        first = True
        while self._pending:
            region = min(self._pending)
            if not first:
                await _sleep(REQUEST_DELAY)
            first = False
            try:
                index = self._data["index"]
                checked = dt_util.parse_datetime(index.get("checked", ""))
                if not index.get("regions") or checked is None or dt_util.utcnow() - checked > REFRESH_AFTER:
                    regions = parse_index(await self._fetch(INDEX_URL))
                    self._data["index"] = {"checked": dt_util.utcnow().isoformat(), "regions": regions}
                    await _sleep(REQUEST_DELAY)
                url = self._data["index"].get("regions", {}).get(region)
                vehicles = parse_region(await self._fetch(url)) if url else {}
                self._data["regions"][region] = {
                    "checked": dt_util.utcnow().isoformat(),
                    "ok": bool(url),
                    "vehicles": vehicles,
                }
                _LOGGER.debug("Brandbase: %s voertuigen voor regio %s", len(vehicles), region)
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Brandbase regio %s niet beschikbaar: %s", region, err)
                previous = self._data["regions"].get(region) or {}
                self._data["regions"][region] = {**previous, "checked": dt_util.utcnow().isoformat(), "ok": False}
            self._pending.discard(region)
            self._store.async_delay_save(lambda: self._data, 5)
            for update_callback in list(self._listeners):
                update_callback()
