"""Configurable Facebook dispatch message template.

The template is edited in the integration options (Settings → Devices &
services → Brandweerrooster → Configure). Older versions stored it in
``/config/brandweerrooster/facebook_template.yaml``; a customised file is
imported into the options once.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

import yaml

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

LEGACY_TEMPLATE_PATH = ("brandweerrooster", "facebook_template.yaml")

DEFAULT_TEMPLATE = """🚒 Brandweer {kazerne} uitgerukt – {classificatie}

{uitrukbericht}
📍 {locatie}
🕐 Alarmering: {tijd}
📟 Prioriteit: {prioriteit}
🚒 Voertuigen: {voertuigen}

Meer informatie volgt indien beschikbaar.

#Brandweer #Hulpverlening"""

# Built-in defaults of earlier versions. A legacy file that still contains one
# of these was never customised and is not imported.
_LEGACY_DEFAULT_BODIES = (
    DEFAULT_TEMPLATE,
    """🚒 Brandweer {kazerne} uitgerukt

{uitrukbericht}
📍 {locatie}
🕐 Alarmering: {tijd}
📟 Prioriteit: {prioriteit}
🚒 Voertuigen: {voertuigen}

Meer informatie volgt indien beschikbaar.

#Brandweer #Hulpverlening""",
)

PLACEHOLDERS = (
    "kazerne",
    "uitrukbericht",
    "incident_type",
    "classificatie",
    "categorie",
    "melding",
    "locatie",
    "straat",
    "plaats",
    "tijd",
    "datum",
    "prioriteit",
    "voertuigen",
    "incident_id",
    "created_at",
    "start_time",
)

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def find_placeholders(template: str) -> list[str]:
    return _PLACEHOLDER_RE.findall(template)


def unknown_placeholders(template: str) -> list[str]:
    return sorted({name for name in find_placeholders(template) if name not in PLACEHOLDERS})


def render(template: str | None, values: dict[str, Any]) -> str:
    """Render the template with the supplied placeholder values.

    A line whose placeholder has no value is left out, so for example the
    vehicle line disappears when no vehicles are known.
    """
    template = template if template and template.strip() else DEFAULT_TEMPLATE
    result_lines: list[str] = []

    for line in template.splitlines():
        names = [name for name in find_placeholders(line) if name in PLACEHOLDERS]
        if any(not str(values.get(name, "") or "").strip() for name in names):
            continue
        rendered = _PLACEHOLDER_RE.sub(lambda match: str(values.get(match.group(1), "") or ""), line)
        result_lines.append(rendered.rstrip())

    # Collapse runs of blank lines left behind by removed lines.
    text = "\n".join(result_lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


async def async_read_legacy_template(hass: HomeAssistant) -> str | None:
    """Return a customised template from the pre-1.4 YAML file, if any."""
    path = Path(hass.config.path(*LEGACY_TEMPLATE_PATH))
    return await hass.async_add_executor_job(_read_legacy_sync, path)


def _read_legacy_sync(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as err:
        _LOGGER.warning("Oud Facebook-sjabloon %s kon niet worden gelezen: %s", path, err)
        return None
    template: Any = raw.get("facebook_template") if isinstance(raw, dict) else raw
    if not isinstance(template, str) or not template.strip():
        return None
    template = template.rstrip("\n")
    if template.strip() in {body.strip() for body in _LEGACY_DEFAULT_BODIES}:
        return None
    return template
