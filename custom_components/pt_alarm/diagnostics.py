"""Diagnostics for PT Alarm (codes are redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_CODE_HASH, CONF_SALT

TO_REDACT = {CONF_CODE_HASH, CONF_SALT}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return {
        "title": entry.title,
        "options": async_redact_data(dict(entry.options), TO_REDACT),
    }
