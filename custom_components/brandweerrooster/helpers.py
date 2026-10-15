"""Small shared helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry


def get_setting(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Return a setting, preferring the options over the original setup data."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)
