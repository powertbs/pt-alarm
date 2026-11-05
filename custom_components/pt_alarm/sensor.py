"""Zone status sensors for PT Alarm: one per alarm sensor, plus an open-zones count."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_ALLOW_OPEN,
    CONF_ALWAYS_ON,
    CONF_IMMEDIATE,
    CONF_SENSOR_MODES,
    CONF_SENSORS,
    CONF_TRIGGER_UNAVAILABLE,
    CONF_TYPE,
    DOMAIN,
    OPEN_STATES,
    UNAVAILABLE_STATES,
    signal_update,
)
from .helpers import merged_options

ZONE_CLOSED = "closed"
ZONE_OPEN = "open"
ZONE_BYPASSED = "bypassed"
ZONE_ALARM = "alarm"
ZONE_STATES = [ZONE_CLOSED, ZONE_OPEN, ZONE_BYPASSED, ZONE_ALARM]


def is_open(sensor: dict[str, Any], state_value: str | None) -> bool:
    """Whether a raw state counts as open for this sensor."""
    value = str(state_value or "").lower()
    if value in UNAVAILABLE_STATES:
        return bool(sensor.get(CONF_TRIGGER_UNAVAILABLE))
    return value in OPEN_STATES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the zone sensors."""
    sensors: dict[str, dict] = merged_options(dict(entry.options))[CONF_SENSORS]
    entities: list[SensorEntity] = [
        PTAlarmZoneSensor(entry, entity_id, cfg) for entity_id, cfg in sensors.items()
    ]
    entities.append(PTAlarmOpenZonesSensor(entry, sensors))
    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})


def _panel_info(hass: HomeAssistant, entry: ConfigEntry) -> tuple[list[str], str | None, str]:
    """(bypassed sensors, triggered_by, panel state) from the running panel."""
    panel = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if panel is None:
        return [], None, ""
    return list(panel.bypassed), panel.triggered_by, str(panel.alarm_state or "")


class _PanelLinkedSensor(SensorEntity):
    """Base: refreshes when the panel or a watched sensor changes."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, watched: list[str]) -> None:
        self._entry = entry
        self._watched = watched
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to panel updates and source sensor changes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self._entry.entry_id), self._async_refresh
            )
        )
        if self._watched:
            self.async_on_remove(
                async_track_state_change_event(self.hass, self._watched, self._async_changed)
            )
        self._update()

    @callback
    def _async_changed(self, _event: Event[EventStateChangedData]) -> None:
        self._async_refresh()

    @callback
    def _async_refresh(self) -> None:
        self._update()
        self.async_write_ha_state()

    def _update(self) -> None:
        raise NotImplementedError


class PTAlarmZoneSensor(_PanelLinkedSensor):
    """Status of one alarm zone: closed, open, bypassed or alarm."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ZONE_STATES
    _attr_translation_key = "zone"

    def __init__(self, entry: ConfigEntry, entity_id: str, cfg: dict[str, Any]) -> None:
        super().__init__(entry, [entity_id])
        self._source = entity_id
        self._cfg = cfg
        self._attr_unique_id = f"{entry.entry_id}_zone_{entity_id}"
        self._attr_name = entity_id.split(".", 1)[1].replace("_", " ").capitalize()

    def _update(self) -> None:
        source = self.hass.states.get(self._source)
        if source is not None and source.name:
            self._attr_name = source.name
        bypassed, triggered_by, panel_state = _panel_info(self.hass, self._entry)

        raw = source.state if source else None
        self._attr_available = source is not None and (
            raw not in UNAVAILABLE_STATES or bool(self._cfg.get(CONF_TRIGGER_UNAVAILABLE))
        )
        open_now = is_open(self._cfg, raw)
        if panel_state in ("triggered", "pending") and triggered_by == self._source:
            value = ZONE_ALARM
        elif self._source in bypassed:
            value = ZONE_BYPASSED
        elif open_now:
            value = ZONE_OPEN
        else:
            value = ZONE_CLOSED
        self._attr_native_value = value
        self._attr_extra_state_attributes = {
            ATTR_ENTITY_ID: self._source,
            "source_state": raw,
            "zone_type": self._cfg.get(CONF_TYPE),
            "active_modes": self._cfg.get(CONF_SENSOR_MODES, []),
            "immediate": self._cfg.get(CONF_IMMEDIATE, False),
            "always_on": self._cfg.get(CONF_ALWAYS_ON, False),
            "allow_open": self._cfg.get(CONF_ALLOW_OPEN, False),
            "is_open": open_now,
            "bypassed": self._source in bypassed,
        }


class PTAlarmOpenZonesSensor(_PanelLinkedSensor):
    """Number of open zones, with their names as an attribute."""

    _attr_translation_key = "open_zones"
    _attr_native_unit_of_measurement = "zones"

    def __init__(self, entry: ConfigEntry, sensors: dict[str, dict]) -> None:
        super().__init__(entry, list(sensors))
        self._sensors = sensors
        self._attr_unique_id = f"{entry.entry_id}_open_zones"

    def _update(self) -> None:
        bypassed, _triggered_by, _state = _panel_info(self.hass, self._entry)
        open_zones = []
        for entity_id, cfg in self._sensors.items():
            state = self.hass.states.get(entity_id)
            if state is not None and is_open(cfg, state.state):
                open_zones.append(entity_id)
        self._attr_native_value = len(open_zones)
        self._attr_extra_state_attributes = {
            "open_zones": open_zones,
            "open_zone_names": [self._name(e) for e in open_zones],
            "bypassed_zones": bypassed,
            "total_zones": len(self._sensors),
        }

    def _name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.name if state and state.name else entity_id
