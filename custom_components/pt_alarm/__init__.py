"""PT Alarm - a fully featured alarm system for Home Assistant."""

from __future__ import annotations

from collections import OrderedDict
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CARD_FILENAME,
    DATA_CONTEXT_SOURCES,
    DOMAIN,
    FRONTEND_URL_BASE,
    PLATFORMS,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the dashboard card and remember which automation called us."""
    hass.data.setdefault(DOMAIN, {})
    sources: OrderedDict[str, str] = OrderedDict()
    hass.data[DATA_CONTEXT_SOURCES] = sources

    @callback
    def _remember(event: Event, kind: str) -> None:
        """Map the run context of an automation/script to its name."""
        name = event.data.get("name") or event.data.get("entity_id") or kind
        sources[event.context.id] = f'{kind} "{name}"'
        while len(sources) > 200:
            sources.popitem(last=False)

    @callback
    def _automation(event: Event) -> None:
        _remember(event, "automation")

    @callback
    def _script(event: Event) -> None:
        _remember(event, "script")

    hass.bus.async_listen("automation_triggered", _automation)
    hass.bus.async_listen("script_started", _script)
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
