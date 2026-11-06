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


def _sensor(zone_type, kind="door", chime=False):
    return {"type": kind, "zone_type": zone_type, "chime": chime, "trigger_unavailable": False}


def _options(**overrides):
    opts = {
        **DEFAULT_OPTIONS,
        "code_arm_required": False,
        "modes": {
            "armed_away": {"enabled": True, "exit_time": 10, "trigger_time": 20},
            "armed_home": {"enabled": True, "exit_time": 0, "trigger_time": 20},
            "armed_night": {"enabled": False},
        },
        "entry_delay_1": 5,
        "entry_delay_2": 15,
        "sensors": {
            DOOR: _sensor("entry_exit_1"),
            WINDOW: _sensor("perimeter", kind="window"),
            SMOKE: _sensor("fire", kind="environmental"),
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

    await _call(hass, "arm", mode="home", force=True, code="1234")
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


def _user(name, code, **extra):
    return {"id": name, "name": name, "can_arm": True, "can_disarm": True, **hash_code(code), **extra}


async def test_bypass_needs_permission(hass):
    users = [_user("Alice", "1234", can_bypass=True), _user("Kid", "5678", can_bypass=False)]
    await _setup(hass, users=users)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    # Force without a code, and with a code lacking the permission, are refused
    with pytest.raises(ServiceValidationError):
        await _call(hass, "arm", mode="home", force=True)
    with pytest.raises(ServiceValidationError, match="bypass"):
        await _call(hass, "arm", mode="home", force=True, code="5678")
    assert hass.states.get(ENTITY).state == "disarmed"

    await _call(hass, "arm", mode="home", force=True, code="1234")
    assert hass.states.get(ENTITY).state == "armed_home"


async def test_user_schedule_and_dates(hass, freezer):
    freezer.move_to("2026-11-04 12:00:00")  # a Wednesday, noon (UTC)
    await hass.config.async_set_time_zone("UTC")
    users = [
        _user("Night", "1111", days=["wed"], start_time="22:00:00", end_time="06:00:00"),
        _user("Guest", "2222", valid_from="2026-11-01", valid_until="2026-11-03"),
        _user("Owner", "3333"),
    ]
    await _setup(hass, users=users)
    await _call(hass, "arm", mode="home")

    with pytest.raises(ServiceValidationError, match="not valid at this time"):
        await _call(hass, "alarm_disarm", code="1111")  # outside 22:00-06:00
    with pytest.raises(ServiceValidationError, match="not valid at this time"):
        await _call(hass, "alarm_disarm", code="2222")  # guest code expired

    freezer.move_to("2026-11-05 03:00:00")  # Thursday 03:00, inside Wednesday's overnight window
    await _call(hass, "alarm_disarm", code="1111")
    assert hass.states.get(ENTITY).state == "disarmed"


async def test_zone_sensors(hass):
    await _setup(hass)
    door_zone = "sensor.house_front_door"
    open_zones = "sensor.house_open_zones"
    assert hass.states.get(door_zone).state == "closed"
    assert hass.states.get(door_zone).attributes["zone_type"] == "entry_exit_1"
    assert hass.states.get(door_zone).attributes["device_kind"] == "door"
    assert hass.states.get(open_zones).state == "0"

    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert hass.states.get(door_zone).state == "open"
    assert hass.states.get(open_zones).state == "1"

    await _call(hass, "arm", mode="home", force=True, code="1234")
    assert hass.states.get(door_zone).state == "bypassed"

    await _call(hass, "alarm_disarm", code="1234")
    assert hass.states.get(door_zone).state == "open"

    hass.states.async_set(DOOR, "off")
    await hass.async_block_till_done()
    await _call(hass, "arm", mode="away", skip_delay=True)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "pending"
    assert hass.states.get(door_zone).state == "alarm"


async def test_cleaner_mondays_8_to_4_not_on_holidays(hass, freezer):
    await hass.config.async_set_time_zone("UTC")
    hass.states.async_set("calendar.holidays", "off")
    cleaner = _user(
        "Cleaner", "4444", days=["mon"], start_time="08:00:00", end_time="16:00:00",
        blocked_by=["calendar.holidays"],
    )
    await _setup(hass, users=[cleaner, _user("Owner", "3333")])

    freezer.move_to("2026-11-09 10:00:00")  # Monday 10:00
    await _call(hass, "arm", mode="home")
    await _call(hass, "alarm_disarm", code="4444")
    assert hass.states.get(ENTITY).state == "disarmed"

    await _call(hass, "arm", mode="home")
    freezer.move_to("2026-11-09 17:00:00")  # Monday after 16:00
    with pytest.raises(ServiceValidationError, match="not valid at this time"):
        await _call(hass, "alarm_disarm", code="4444")

    freezer.move_to("2026-11-10 10:00:00")  # Tuesday
    with pytest.raises(ServiceValidationError, match="not valid at this time"):
        await _call(hass, "alarm_disarm", code="4444")

    freezer.move_to("2026-11-16 10:00:00")  # Monday, but a holiday
    hass.states.async_set("calendar.holidays", "on")
    with pytest.raises(ServiceValidationError, match="not valid at this time"):
        await _call(hass, "alarm_disarm", code="4444")
    assert hass.states.get(ENTITY).state == "armed_home"


async def test_activity_log_names_the_alarm_user(hass, freezer):
    from custom_components.pt_alarm import logbook as pt_logbook

    describers = {}
    pt_logbook.async_describe_events(hass, lambda d, e, fn: describers.setdefault(e, fn))
    await _setup(hass, code_arm_required=True)
    events = []
    hass.bus.async_listen(EVENT, events.append)

    await _call(hass, "alarm_arm_away", code="1234")
    await _advance(hass, freezer, 11)  # exit delay ends: still credited to Alice
    await _call(hass, "alarm_disarm", code="1234")
    with pytest.raises(ServiceValidationError):
        await _call(hass, "alarm_disarm", code="0000")
    await hass.async_block_till_done()

    messages = [describers[EVENT](e)["message"] for e in events]
    assert messages == [
        "started arming away by Alice (10s exit delay)",
        "armed away by Alice",
        "disarmed by Alice",
        "invalid code entered",
    ]
    assert describers[EVENT](events[0])["entity_id"] == ENTITY


async def test_motion_zone_custom_name_and_location(hass):
    from homeassistant.helpers import area_registry as ar

    office = ar.async_get(hass).async_create("Office")
    motion = "binary_sensor.secretary_office_presence_detector_ld2410"
    hass.states.async_set(motion, "off")
    sensors = {
        **_options()["sensors"],
        motion: {**_sensor("interior_follower", kind="motion"),
                 "name": "Office motion", "area": office.id},
    }
    await _setup(hass, sensors=sensors)

    zone = "sensor.house_office_motion"
    state = hass.states.get(zone)
    assert state is not None, "zone sensor uses the custom name"
    assert state.state == "clear"
    assert state.attributes["location"] == "Office"
    assert state.attributes["options"] == ["clear", "motion", "bypassed", "alarm"]

    hass.states.async_set(motion, "on")
    await hass.async_block_till_done()
    assert hass.states.get(zone).state == "motion"

    zones = hass.states.get(ENTITY).attributes["zones"]
    assert zones[motion] == {"name": "Office motion", "type": "motion", "zone_type": "interior_follower", "location": "Office"}

    # Activity log and notifications use the short name and the location
    from custom_components.pt_alarm.logbook import describe_event
    assert describe_event(
        {"event": "triggered", "sensor_name": "Office motion", "sensor_location": "Office"}
    ) == "ALARM triggered by Office motion in Office"


async def test_ready_to_arm_and_stay_label(hass):
    from custom_components.pt_alarm.logbook import describe_event

    await _setup(hass)
    assert hass.states.get(ENTITY).attributes["ready_to_arm"] is True
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    attrs = hass.states.get(ENTITY).attributes
    assert attrs["ready_to_arm"] is False
    assert attrs["not_ready_sensors"] == [DOOR]

    await _call(hass, "arm", mode="stay", force=True, code="1234")
    assert hass.states.get(ENTITY).state == "armed_home"
    assert describe_event({"event": "armed", "mode": "armed_home", "user": "Alice"}) == "armed stay by Alice"


async def test_disarm_always_clears_bypass(hass):
    await _setup(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await _call(hass, "arm", mode="stay", force=True, code="1234")
    assert hass.states.get(ENTITY).attributes["bypassed_sensors"] == [DOOR]

    await _call(hass, "alarm_disarm", code="1234")
    assert hass.states.get(ENTITY).attributes["bypassed_sensors"] == []
    # Arming again without bypassing is refused while the door is still open
    with pytest.raises(ServiceValidationError):
        await _call(hass, "arm", mode="stay")



# ---------------------------------------------------------------- zone types
HALL = "binary_sensor.hall_motion"
LIVING = "binary_sensor.living_motion"
BACK = "binary_sensor.back_door"
LEAK = "binary_sensor.basement_leak"
TAMPER = "binary_sensor.panel_tamper"


def _zone_options(**overrides):
    sensors = {
        **_options()["sensors"],
        HALL: _sensor("interior_follower", kind="motion"),
        LIVING: _sensor("interior", kind="motion"),
        BACK: _sensor("entry_exit_2", chime=True),
        LEAK: _sensor("supervisory", kind="environmental"),
        TAMPER: _sensor("tamper", kind="tamper"),
    }
    return {"sensors": sensors, **overrides}


async def _zone_setup(hass, **overrides):
    for entity_id in (HALL, LIVING, BACK, LEAK, TAMPER):
        hass.states.async_set(entity_id, "off")
    return await _setup(hass, **_zone_options(**overrides))


async def _open(hass, entity_id, value="on"):
    hass.states.async_set(entity_id, value)
    await hass.async_block_till_done()


async def test_stay_ignores_interior_zones(hass):
    await _zone_setup(hass)
    await _call(hass, "arm", mode="stay")
    await _open(hass, LIVING)
    await _open(hass, HALL)
    assert hass.states.get(ENTITY).state == "armed_home"
    await _open(hass, WINDOW)  # perimeter is instant in stay
    assert hass.states.get(ENTITY).state == "triggered"


async def test_interior_follower_follows_entry_delay(hass):
    await _zone_setup(hass)
    await _call(hass, "arm", mode="away", skip_delay=True)
    await _open(hass, DOOR)
    assert hass.states.get(ENTITY).state == "pending"
    await _open(hass, HALL)  # follower waits for the running entry delay
    assert hass.states.get(ENTITY).state == "pending"
    await _open(hass, LIVING)  # interior is instant, even during the entry delay
    state = hass.states.get(ENTITY)
    assert state.state == "triggered"
    assert state.attributes["triggered_by"] == LIVING


async def test_interior_follower_is_instant_without_entry_delay(hass):
    await _zone_setup(hass)
    await _call(hass, "arm", mode="away", skip_delay=True)
    await _open(hass, HALL)
    assert hass.states.get(ENTITY).state == "triggered"


async def test_entry_exit_2_uses_delay_2(hass):
    await _zone_setup(hass)
    await _call(hass, "arm", mode="away", skip_delay=True)
    await _open(hass, BACK)
    state = hass.states.get(ENTITY)
    assert state.state == "pending"
    assert state.attributes["delay"] == 15


async def test_instant_mode_has_no_entry_delay(hass):
    await _zone_setup(
        hass, modes={"armed_home": {"enabled": True, "exit_time": 0, "instant": True}}
    )
    await _call(hass, "arm", mode="stay")
    await _open(hass, BACK)
    assert hass.states.get(ENTITY).state == "triggered"


async def test_tamper_and_supervisory_are_troubles_not_alarms(hass):
    await _zone_setup(hass)
    events = []
    hass.bus.async_listen(EVENT, lambda e: events.append(e.data["event"]))
    await _call(hass, "arm", mode="away", skip_delay=True)

    await _open(hass, TAMPER)
    await _open(hass, LEAK)
    state = hass.states.get(ENTITY)
    assert state.state == "armed_away"
    assert set(state.attributes["troubles"]) == {TAMPER, LEAK}
    assert events.count("trouble") == 2

    await _open(hass, LEAK, "off")
    assert set(hass.states.get(ENTITY).attributes["troubles"]) == {TAMPER}
    assert "trouble_restored" in events


async def test_fire_alarm_needs_a_code_to_reset(hass):
    await _zone_setup(hass, code_disarm_required=False)
    await _open(hass, SMOKE)
    state = hass.states.get(ENTITY)
    assert state.state == "triggered"
    assert state.attributes["alarm_type"] == "fire"
    assert state.attributes["expiration"] is None  # sounds until reset

    with pytest.raises(ServiceValidationError):
        await _call(hass, "alarm_disarm")  # refused without a code
    await _call(hass, "alarm_disarm", code="1234")
    state = hass.states.get(ENTITY)
    assert state.state == "disarmed"
    assert state.attributes["alarm_type"] is None


async def test_fire_beats_a_burglary_alarm(hass):
    await _zone_setup(hass)
    await _call(hass, "arm", mode="away", skip_delay=True)
    await _open(hass, WINDOW)
    assert hass.states.get(ENTITY).attributes["alarm_type"] == "burglary"
    await _open(hass, SMOKE)
    assert hass.states.get(ENTITY).attributes["alarm_type"] == "fire"


async def test_chime_only_while_disarmed(hass):
    await _zone_setup(hass)
    chimes = []

    def _on_event(event):
        if event.data["event"] == "chime":
            chimes.append(event.data["sensor"])

    hass.bus.async_listen(EVENT, _on_event)
    await _open(hass, BACK)  # chime enabled
    await _open(hass, DOOR)  # chime disabled
    assert chimes == [BACK]
    assert hass.states.get(ENTITY).attributes["last_chime"]["entity_id"] == BACK

    await _open(hass, BACK, "off")
    await _open(hass, DOOR, "off")
    await _call(hass, "arm", mode="away", skip_delay=True)
    await _open(hass, BACK)
    assert chimes == [BACK]


async def test_old_sensor_settings_are_migrated(hass):
    legacy = {
        DOOR: {"type": "door", "modes": ["armed_away"], "immediate": False},
        WINDOW: {"type": "window", "modes": ["armed_away"], "immediate": True},
        SMOKE: {"type": "environmental", "always_on": True},
    }
    await _setup(hass, sensors=legacy)
    zones = hass.states.get(ENTITY).attributes["zones"]
    assert zones[DOOR]["zone_type"] == "entry_exit_1"
    assert zones[WINDOW]["zone_type"] == "perimeter"
    assert zones[SMOKE]["zone_type"] == "fire"
