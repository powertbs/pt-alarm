"""Email / push notifications and the HTML email template."""

from __future__ import annotations

from pathlib import Path

import pytest

from homeassistant.core import ServiceCall
from homeassistant.exceptions import ServiceValidationError

from custom_components.pt_alarm.const import DOMAIN

from .test_alarm import DOOR, ENTITY, WINDOW, _call, _setup


@pytest.fixture
def outbox(hass):
    """Fake notify.email and notify.phone services that record what was sent."""
    sent: dict[str, list[dict]] = {"email": [], "phone": []}

    async def _email(call: ServiceCall) -> None:
        sent["email"].append(dict(call.data))

    async def _phone(call: ServiceCall) -> None:
        sent["phone"].append(dict(call.data))

    hass.services.async_register("notify", "email", _email)
    hass.services.async_register("notify", "phone", _phone)
    return sent


def _channels(**overrides):
    return {
        "email_services": ["notify.email"],
        "push_services": ["notify.phone"],
        **overrides,
    }


async def test_alarm_sends_branded_email_and_urgent_push(hass, outbox):
    await _setup(hass, **_channels())
    await _call(hass, "arm", mode="away", skip_delay=True)
    assert outbox["email"] == []  # "armed" is not ticked by default

    hass.states.async_set(WINDOW, "on")
    await hass.async_block_till_done()

    email = outbox["email"][-1]
    assert email["title"].endswith("Alarm – House")
    html = email["data"]["html"]
    assert "#c62828" in html  # red banner
    assert ">Alarm<" in html
    assert "kitchen window" in html.lower()
    assert "PowerTech Security &amp; Communications" in html

    push = outbox["phone"][-1]
    assert "ALARM" in push["message"]
    assert push["data"]["priority"] == "high"


async def test_events_can_be_switched_on_and_off(hass, outbox):
    await _setup(hass, **_channels(email_events=["armed", "disarmed"], push_events=[]))
    await _call(hass, "arm", mode="stay")
    await _call(hass, "alarm_disarm", code="1234")
    titles = [e["title"] for e in outbox["email"]]
    assert any("Armed Stay" in t for t in titles)
    assert any("Disarmed" in t for t in titles)
    assert outbox["phone"] == []

    await _call(hass, "arm", mode="stay")
    count = len(outbox["email"])
    hass.states.async_set(WINDOW, "on")  # alarm is not ticked for email -> no email
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "triggered"
    assert len(outbox["email"]) == count


async def test_bypass_and_wrong_code_emails(hass, outbox):
    await _setup(hass, **_channels())
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await _call(hass, "arm", mode="stay", force=True, code="1234")
    html = outbox["email"][-1]["data"]["html"]
    assert "Armed with bypassed zones" in html
    assert "front door" in html.lower()

    with pytest.raises(ServiceValidationError):
        await _call(hass, "alarm_disarm", code="9999")
    await hass.async_block_till_done()
    assert "Wrong code" in outbox["email"][-1]["title"]


async def test_plain_text_email_when_html_is_off(hass, outbox):
    await _setup(hass, **_channels(email_html=False))
    hass.states.async_set("binary_sensor.smoke", "on")
    await hass.async_block_till_done()
    email = outbox["email"][-1]
    assert "FIRE ALARM" in email["message"]
    assert "data" not in email


async def test_own_email_design_is_used(hass, outbox):
    custom = Path(hass.config.path("pt_alarm_email.html"))
    custom.write_text("<h1>MY DESIGN $title for $partition</h1>", encoding="utf-8")
    try:
        await _setup(hass, **_channels())
        hass.states.async_set("binary_sensor.smoke", "on")
        await hass.async_block_till_done()
        assert outbox["email"][-1]["data"]["html"] == "<h1>MY DESIGN Fire alarm for House</h1>"
    finally:
        custom.unlink()


def test_old_notification_settings_move_to_push():
    from custom_components.pt_alarm.helpers import merged_options

    old = {"notify_services": ["notify.phone"], "notify_events": ["triggered", "trouble"]}
    opts = merged_options(old)
    assert opts["push_services"] == ["notify.phone"]
    assert set(opts["push_events"]) == {"alarm", "fire", "trouble"}
    # New-style settings are left alone
    assert merged_options({"push_services": [], **old})["push_services"] == []


async def test_send_test_notification_from_the_menu(hass, outbox):
    entry = await _setup(hass, **_channels())
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert "notifications" in flow["menu_options"]
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "notify_test"}
    )
    await hass.config_entries.options.async_configure(result["flow_id"], {"send": True})
    await hass.async_block_till_done()
    assert "Test" in outbox["email"][-1]["title"]
    assert outbox["phone"][-1]["message"].startswith("This is a test")
    assert DOMAIN in entry.domain


async def test_new_style_notify_entity_gets_plain_text(hass):
    """SMTP set up from the UI is a notify entity: use notify.send_message."""
    sent = []

    async def _send_message(call: ServiceCall) -> None:
        sent.append(dict(call.data))

    hass.services.async_register("notify", "send_message", _send_message)
    hass.states.async_set("notify.ui_email", "unknown", {"friendly_name": "UI email"})
    await _setup(hass, email_services=["notify.ui_email"], push_services=[])
    hass.states.async_set("binary_sensor.smoke", "on")
    await hass.async_block_till_done()

    assert sent[-1]["entity_id"] == "notify.ui_email"
    assert "Fire alarm" in sent[-1]["title"]
    assert "FIRE ALARM" in sent[-1]["message"]
    assert "data" not in sent[-1]
