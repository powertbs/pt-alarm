"""PT Alarm - a fully featured alarm system for Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CARD_FILENAME, DOMAIN, FRONTEND_URL_BASE, PLATFORMS, VERSION

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the dashboard card so it is available without manual resources."""
    hass.data.setdefault(DOMAIN, {})
    if hass.http is not None:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    FRONTEND_URL_BASE,
                    str(Path(__file__).parent / "frontend"),
                    cache_headers=False,
                )
            ]
        )
        if "frontend" in hass.config.components:
            add_extra_js_url(hass, f"{FRONTEND_URL_BASE}/{CARD_FILENAME}?v={VERSION}")
            _LOGGER.debug("Registered PT Alarm card at %s/%s", FRONTEND_URL_BASE, CARD_FILENAME)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a PT Alarm panel from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the panel when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
