"""End-to-end tests of the PT Alarm state machine."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
import homeassistant.util.dt as dt_util

from custom_components.pt_alarm.const import DEFAULT_OPTIONS, DOMAIN, EVENT
from custom_components.pt_alarm.helpers import hash_code

ENTITY = "alarm_control_panel.house"
DOOR = "binary_sensor.front_door"
WINDOW = "binary_sensor.kitchen_window"
SMOKE = "binary_sensor.smoke"


def _sensor(modes, immediate=False, always_on=False, allow_open=False, kind="door"):
    return {
        "type": kind,
        "modes": modes,
        "immediate": immediate,
        "always_on": always_on,
        "allow_open": allow_open,
        "trigger_unavailable": False,
    }


def _options(**overrides):
    opts = {
        **DEFAULT_OPTIONS,
        "code_arm_required": False,
        "modes": {
            "armed_away": {"enabled": True, "exit_time": 10, "entry_time": 5, "trigger_time": 20},
            "armed_home": {"enabled": True, "exit_time": 0, "entry_time": 5, "trigger_time": 20},
            "armed_night": {"enabled": False},
        },
        "sensors": {
            DOOR: _sensor(["armed_away", "armed_home"]),
            WINDOW: _sensor(["armed_away"], immediate=True, kind="window"),
            SMOKE: _sensor([], immediate=True, always_on=True, allow_open=True, kind="environmental"),
        },
        "users": [{"id": "1", "name": "Alice", "can_arm": True, "can_disarm": True, **hash_code("1234")}],
        "max_attempts": 3,
        "lockout_time": 30,
    }
    opts.update(overrides)
    return opts


async def _setup(hass: HomeAssistant, **overrides) -> MockConfigEntry:
    for entity_id in (DOOR, WINDOW, SMOKE):
        hass.states.async_set(entity_id, "off")
    await async_setup_component(hass, "homeassistant", {})
    entry = MockConfigEntry(
        domain=DOMAIN, title="House", data={"name": "House"}, options=_options(**overrides)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _call(hass, service, **data):
    domain = DOMAIN if service == "arm" else "alarm_control_panel"
    await hass.services.async_call(domain, service, {"entity_id": ENTITY, **data}, blocking=True)
    await hass.async_block_till_done()


async def _advance(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_exit_delay_entry_delay_trigger_and_rearm(hass, freezer):
    await _setup(hass)
    assert hass.states.get(ENTITY).state == "disarmed"

    await _call(hass, "alarm_arm_away")
    state = hass.states.get(ENTITY)
    assert state.state == "arming"
    assert state.attributes["delay"] == 10

    await _advance(hass, freezer, 11)
    assert hass.states.get(ENTITY).state == "armed_away"

    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "pending"

    await _advance(hass, freezer, 6)
    state = hass.states.get(ENTITY)
    assert state.state == "triggered"
    assert state.attributes["triggered_by"] == DOOR

    # Trigger time elapses -> back to armed, the still-open door is bypassed
    await _advance(hass, freezer, 21)
    state = hass.states.get(ENTITY)
    assert state.state == "armed_away"
    assert DOOR in state.attributes["bypassed_sensors"]


async def test_immediate_sensor_and_disarm_code(hass):
    await _setup(hass)
    await _call(hass, "arm", mode="away", skip_delay=True)
    assert hass.states.get(ENTITY).state == "armed_away"

    hass.states.async_set(WINDOW, "on")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "triggered"

    with pytest.raises(ServiceValidationError):
        await _call(hass, "alarm_disarm", code="0000")
    with pytest.raises(ServiceValidationError):
        await _call(hass, "alarm_disarm")
    await _call(hass, "alarm_disarm", code="1234")
    state = hass.states.get(ENTITY)
    assert state.state == "disarmed"
    assert state.attributes["changed_by"] == "Alice"


async def test_open_sensor_blocks_arming_unless_forced(hass):
    await _setup(hass)
    events = []
    hass.bus.async_listen(EVENT, lambda e: events.append(e.data["event"]))
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await _call(hass, "alarm_arm_home")
    await hass.async_block_till_done()
    assert "failed_to_arm" in events
    assert hass.states.get(ENTITY).state == "disarmed"

    await _call(hass, "arm", mode="home", force=True)
    state = hass.states.get(ENTITY)
    assert state.state == "armed_home"
    assert state.attributes["bypassed_sensors"] == [DOOR]


async def test_always_on_sensor_triggers_when_disarmed(hass):
    await _setup(hass)
    hass.states.async_set(SMOKE, "on")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "triggered"


async def test_lockout_after_invalid_codes(hass):
    await _setup(hass)
    await _call(hass, "arm", mode="home")
    for _ in range(3):
        with pytest.raises(ServiceValidationError):
            await _call(hass, "alarm_disarm", code="9999")
    assert hass.states.get(ENTITY).attributes["locked_until"] is not None
    # Even the right code is refused while locked out
    with pytest.raises(ServiceValidationError):
        await _call(hass, "alarm_disarm", code="1234")
    assert hass.states.get(ENTITY).state == "armed_home"


async def test_disabled_mode_rejected(hass):
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "alarm_arm_night")


async def test_sensor_coming_online_does_not_trigger(hass):
    await _setup(hass)
    await _call(hass, "arm", mode="home")
    hass.states.async_set(DOOR, "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "armed_home"


async def test_card_is_served(hass, hass_client):
    await async_setup_component(hass, "http", {})
    await _setup(hass)
    client = await hass_client()
    resp = await client.get("/pt_alarm_static/pt-alarm-card.js")
    assert resp.status == 200
    assert "pt-alarm-card" in await resp.text()
