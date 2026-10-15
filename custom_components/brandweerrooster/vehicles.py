"""P2000 vehicle extraction and short vehicle-name resolution."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

# The vehicle list of versions before 1.5 (Limburg-Noord). Names now come from
# Brandbase; the options only hold your own exceptions. This list is used to
# recognise an untouched pre-1.5 list during migration.
DEFAULT_VEHICLE_NAMES: dict[str, str] = {
    "235151": "HW Roermond",
    "235191": "DA-OVD Roermond",
    "235231": "TST Montfort",
    "235331": "TS Echt",
    "235371": "HV Echt",
    "235379": "SIV Echt",
    "235431": "TS Susteren",
    "235461": "WTH Susteren",
    "235481": "HA Susteren",
    "235531": "TS Wessem",
    "235731": "TS Stevensweert",
    "235831": "TST Reuver",
    "236121": "AGS Regionaal",
    "236122": "AGS Regionaal",
    "236134": "TS Regionaal",
    "236165": "Bijzonder materieel Regionaal",
    "236183": "TDV Meijel",
    "236192": "DV-HOD Roermond",
    "236196": "DV-VL Roermond",
    "236197": "DV-OVD Roermond",
    "233231": "TS Venlo",
    "233261": "SB Venlo",
    "233291": "DA-OVD Venlo",
    "232631": "TS Panningen",
    "232661": "WTH Panningen",
    "232682": "HA Panningen",
    "232731": "TS Kessel",
    "232931": "TS Maasbree",
    "234331": "TST Heythuysen",
    "234431": "TS Weert",
    "234631": "TS Hunsel",
    "234491": "Staf- en Commandomaterieel Regionaal",
}

VEHICLE_CODE_RE = re.compile(r"(?<!\d)(?:\d{6}|\d{2}-\d{4})(?!\d)")
_VEHICLE_LINE_RE = re.compile(r"^\s*(\d{2}-?\d{4})\s*[=:;,\t ]\s*(.+?)\s*$")


def extract_vehicle_codes(value: Any, *, remove: bool = False) -> list[str] | str:
    """Extract unique six-digit P2000 vehicle numbers from text."""
    text = str(value or "")
    matches = VEHICLE_CODE_RE.findall(text)
    codes = []
    seen: set[str] = set()
    for match in matches:
        code = match.replace("-", "")
        if code not in seen:
            seen.add(code)
            codes.append(code)
    if remove:
        return VEHICLE_CODE_RE.sub(" ", text)
    return codes


def resolve_vehicle_names(
    codes: list[str],
    mapping: dict[str, str] | None = None,
    lookup: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Resolve P2000 vehicle codes to short, Facebook-friendly names.

    Your own names (``mapping``) win; otherwise ``lookup`` (Brandbase) is
    asked. Unknown codes are never guessed.
    """
    names = DEFAULT_VEHICLE_NAMES if mapping is None and lookup is None else (mapping or {})
    result: list[str] = []
    seen: set[str] = set()
    for code in codes:
        normalized = str(code).replace("-", "")
        name = names.get(normalized) or (lookup(normalized) if lookup else None)
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def parse_vehicle_names(text: str | None) -> dict[str, str]:
    """Parse the options text (one ``code = name`` per line) into a mapping.

    Empty lines and lines starting with ``#`` are ignored. Invalid lines are
    returned by :func:`invalid_vehicle_lines` so the options flow can reject
    them.
    """
    result: dict[str, str] = {}
    for line in str(text or "").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        match = _VEHICLE_LINE_RE.match(line)
        if match:
            result[match.group(1).replace("-", "")] = match.group(2)
    return result


def invalid_vehicle_lines(text: str | None) -> list[str]:
    """Return the non-empty lines that are not a valid ``code = name`` pair."""
    return [
        line.strip()
        for line in str(text or "").splitlines()
        if line.strip()
        and not line.strip().startswith("#")
        and not _VEHICLE_LINE_RE.match(line)
    ]


def format_vehicle_names(mapping: dict[str, str]) -> str:
    """Format a mapping as options text."""
    return "\n".join(f"{code} = {name}" for code, name in mapping.items())


DEFAULT_VEHICLE_TEXT = format_vehicle_names(DEFAULT_VEHICLE_NAMES)
