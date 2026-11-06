"""Arming and disarming by automations and access control."""

from __future__ import annotations

import pytest

from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component

from custom_components.pt_alarm.const import DOMAIN, EVENT
from custom_components.pt_alarm.helpers import hash_code
from custom_components.pt_alarm.logbook import describe_event

from .test_alarm import DOOR, ENTITY, _setup

JOHN = {
    "id": "john",
    "name": "John",
    "can_arm": True,
    "can_disarm": True,
    "access_ids": ["jsmith", "card-1234"],
    **hash_code("1111"),
}
CLEANER = {
    "id": "cleaner",
    "name": "Cleaner",
    "can_arm": True,
    "can_disarm": True,
    "days": ["mon"],
    "start_time": "08:00:00",
    "end_time": "16:00:00",
    **hash_code("2222"),
}


async def _auto_setup(hass, **overrides):
    opts = {"users": [JOHN, CLEANER], "automation_allowed": True, **overrides}
    return await _setup(hass, **opts)


def _events(hass):
    seen = []
    hass.bus.async_listen(EVENT, lambda e: seen.append(dict(e.data)))
    return seen


async def _svc(hass, service, **data):
    await hass.services.async_call(DOMAIN, service, {"entity_id": ENTITY, **data}, blocking=True)
    await hass.async_block_till_done()


async def test_automations_are_off_by_default(hass):
    await _setup(hass, users=[JOHN])
    events = _events(hass)
    with pytest.raises(ServiceValidationError, match="turned off"):
        await _svc(hass, "arm", mode="away", source="Closing schedule")
    assert events[-1]["event"] == "access_denied"
    assert describe_event(events[-1]) == "refused arm by Closing schedule: automations are not allowed"


async def test_badge_disarms_by_access_id_and_logs_who(hass):
    await _auto_setup(hass)
    events = _events(hass)
    await _svc(hass, "arm", mode="away", skip_delay=True, source="Closing schedule")
    assert hass.states.get(ENTITY).state == "armed_away"

    # Door opens -> entry delay; the badge event disarms during the entry delay
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "pending"
    await _svc(hass, "disarm", user="jsmith", source="UniFi Access (Front door)")
    state = hass.states.get(ENTITY)
    assert state.state == "disarmed"
    assert state.attributes["changed_by"] == "John"
    assert describe_event(events[-1]) == "disarmed by John via UniFi Access (Front door)"


async def test_badge_never_disarms_during_an_alarm(hass):
    await _auto_setup(hass, automation_anonymous=True)
    await _svc(hass, "arm", mode="away", skip_delay=True, source="Schedule")
    hass.states.async_set("binary_sensor.kitchen_window", "on")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "triggered"
    with pytest.raises(ServiceValidationError, match="keypad"):
        await _svc(hass, "disarm", user="John", source="UniFi Access")
    assert hass.states.get(ENTITY).state == "triggered"


async def test_unknown_people_need_trust_access_control(hass):
    await _auto_setup(hass)
    await _svc(hass, "arm", mode="stay", source="Schedule")
    with pytest.raises(ServiceValidationError, match="Unknown user"):
        await _svc(hass, "disarm", user="visitor7", source="UniFi Access")
    with pytest.raises(ServiceValidationError, match="user is required"):
        await _svc(hass, "disarm", source="Door unlocked")
    assert hass.states.get(ENTITY).state == "armed_home"


async def test_trust_access_control_keeps_the_name(hass):
    await _auto_setup(hass, automation_anonymous=True)
    events = _events(hass)
    await _svc(hass, "arm", mode="stay", source="Schedule")
    await _svc(hass, "disarm", user="visitor7", source="UniFi Access (Lobby)")
    assert hass.states.get(ENTITY).state == "disarmed"
    assert describe_event(events[-1]) == "disarmed by visitor7 via UniFi Access (Lobby)"

    await _svc(hass, "arm", mode="stay", source="Schedule")
    await _svc(hass, "disarm", source="Door unlocked")
    assert describe_event(events[-1]) == "disarmed by Door unlocked"


async def test_pt_user_rules_still_apply(hass, freezer):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-11-10 10:00:00")  # Tuesday
    await _auto_setup(hass, automation_anonymous=True)
    events = _events(hass)
    await _svc(hass, "arm", mode="stay", source="Schedule")
    with pytest.raises(ServiceValidationError, match="not valid at this time"):
        await _svc(hass, "disarm", user="Cleaner", source="UniFi Access")
    assert describe_event(events[-1]) == "refused disarm by Cleaner via UniFi Access: outside the allowed time"


async def test_open_zones_refused(hass):
    await _auto_setup(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await _svc(hass, "arm", mode="away", source="Closing schedule")
    assert hass.states.get(ENTITY).state == "disarmed"


async def test_open_zones_bypass_and_notify(hass):
    await _auto_setup(hass, automation_open_zones="bypass")
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    events = _events(hass)
    await _svc(hass, "arm", mode="away", skip_delay=True, source="Closing schedule")
    state = hass.states.get(ENTITY)
    assert state.state == "armed_away"
    assert state.attributes["bypassed_sensors"] == [DOOR]
    assert describe_event(events[-1]) == "armed away by Closing schedule (bypassed: front door)"


async def test_automation_name_is_detected(hass):
    await _auto_setup(hass)
    events = _events(hass)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "alias": "Closing time",
                "triggers": [{"trigger": "event", "event_type": "close_up"}],
                "actions": [
                    {
                        "action": "pt_alarm.arm",
                        "target": {"entity_id": ENTITY},
                        "data": {"mode": "stay"},
                    }
                ],
            }
        },
    )
    hass.bus.async_fire("close_up")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "armed_home"
    armed = [e for e in events if e["event"] == "armed"][-1]
    assert armed["source"] == 'automation "Closing time"'
    assert describe_event(armed) == 'armed stay by automation "Closing time"'


async def test_keypad_code_still_works_and_needs_no_automation_switch(hass):
    await _setup(hass, users=[JOHN])
    await _svc(hass, "arm", mode="stay", code="1111")
    await _svc(hass, "disarm", code="1111")
    assert hass.states.get(ENTITY).state == "disarmed"
