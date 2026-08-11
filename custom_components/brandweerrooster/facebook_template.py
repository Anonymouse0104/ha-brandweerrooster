"""Configurable Facebook dispatch message templates."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

TEMPLATE_DIRECTORY = "brandweerrooster"
TEMPLATE_FILENAME = "facebook_template.yaml"

DEFAULT_TEMPLATE = """# Brandweerrooster Facebook dispatch message template
#
# Available placeholders:
# {kazerne}
# {uitrukbericht}
# {incident_type}
# {melding}
# {locatie}
# {straat}
# {plaats}
# {tijd}
# {datum}
# {prioriteit}
# {voertuigen}
# {incident_id}
# {created_at}
# {start_time}
#
# You can change the text, line breaks, emojis and hashtags below.
# The integration will not overwrite this file after it has been created.

facebook_template: |
  🚒 Brandweer {kazerne} uitgerukt

  {uitrukbericht}
  📍 {locatie}
  🕐 Alarmering: {tijd}
  📟 Prioriteit: {prioriteit}
  🚒 Voertuigen: {voertuigen}

  Meer informatie volgt indien beschikbaar.

  #Brandweer #Hulpverlening
"""

PLACEHOLDERS = (
    "kazerne",
    "uitrukbericht",
    "incident_type",
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


class FacebookTemplate:
    """Load and render the user-configurable Facebook message template."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.path = Path(hass.config.path(TEMPLATE_DIRECTORY, TEMPLATE_FILENAME))
        self.template = ""

    async def async_load(self) -> None:
        """Create the default file when needed and load the configured template."""
        await self.hass.async_add_executor_job(self._load_sync)

    def _load_sync(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self.path.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
            raw_text = self.path.read_text(encoding="utf-8")
            raw = yaml.safe_load(raw_text)
        except (OSError, yaml.YAMLError) as err:
            _LOGGER.error(
                "Unable to read Facebook template %s: %s. Using the built-in default.",
                self.path,
                err,
            )
            self.template = _extract_default_template()
            return

        template: Any = raw.get("facebook_template") if isinstance(raw, dict) else raw
        if not isinstance(template, str) or not template.strip():
            _LOGGER.error(
                "Facebook template %s does not contain a non-empty 'facebook_template' value. "
                "Using the built-in default.",
                self.path,
            )
            self.template = _extract_default_template()
            return

        self.template = template.rstrip("\n")
        unknown = sorted(
            {
                name
                for name in _find_placeholders(self.template)
                if name not in PLACEHOLDERS
            }
        )
        if unknown:
            _LOGGER.warning(
                "Facebook template %s contains unknown placeholders: %s",
                self.path,
                ", ".join(unknown),
            )

        _LOGGER.debug("Loaded Facebook template from %s", self.path)

    async def async_reload(self) -> None:
        """Reload the template from disk."""
        await self.async_load()

    def render(self, values: dict[str, Any]) -> str:
        """Render the configured template with the supplied placeholder values."""
        template = self.template or _extract_default_template()
        result_lines: list[str] = []

        for line in template.splitlines():
            original = line
            rendered = _replace_placeholders(line, values)

            # If a placeholder has no value, remove a line that consists of
            # that placeholder plus its usual label/punctuation. This keeps
            # the default template clean when, for example, no vehicle data
            # is available.
            if _line_has_empty_placeholder(original, values):
                if not rendered.strip() or _is_placeholder_only_line(original):
                    continue
                # For labelled lines such as "🚒 Voertuigen: {voertuigen}",
                # remove the whole line when its placeholder is empty.
                empty_names = [
                    name
                    for name in PLACEHOLDERS
                    if "{" + name + "}" in original
                    and not str(values.get(name, "") or "").strip()
                ]
                if empty_names:
                    continue

            result_lines.append(rendered.rstrip())

        return "\n".join(result_lines).strip()


def _extract_default_template() -> str:
    """Return the default template body without the YAML wrapper."""
    raw = yaml.safe_load(DEFAULT_TEMPLATE)
    return str(raw["facebook_template"]).rstrip("\n")


def _find_placeholders(template: str) -> list[str]:
    return re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", template)


def _replace_placeholders(template: str, values: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(values.get(name, "") or "")

    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, template)


def _line_has_empty_placeholder(line: str, values: dict[str, Any]) -> bool:
    return any(
        "{" + name + "}" in line and not str(values.get(name, "") or "").strip()
        for name in PLACEHOLDERS
    )


def _is_placeholder_only_line(line: str) -> bool:
    return bool(re.fullmatch(r"\s*\{[A-Za-z_][A-Za-z0-9_]*\}\s*", line))
