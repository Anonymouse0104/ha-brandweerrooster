"""P2000 vehicle extraction and short vehicle-name resolution."""

from __future__ import annotations

import re
from typing import Any

# The Brandweerrooster incident endpoint does not currently expose the P2000
# vehicle number -> display-name relation in every incident payload.  The
# mapping below covers the Limburg-Noord vehicle codes used by the integration
# and is deliberately kept in a separate module so it can be extended without
# touching sensor logic.
VEHICLE_NAMES: dict[str, str] = {
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


def resolve_vehicle_names(codes: list[str]) -> list[str]:
    """Resolve known P2000 vehicle codes to short, Facebook-friendly names."""
    result: list[str] = []
    seen: set[str] = set()
    for code in codes:
        normalized = str(code).replace("-", "")
        name = VEHICLE_NAMES.get(normalized)
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result
