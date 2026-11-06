"""Activity (logbook) entries for PT Alarm, showing which alarm user did what."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    DOMAIN,
    EVENT,
    EVENT_ARMED,
    EVENT_ARMING,
    EVENT_DISARMED,
    EVENT_FAILED_TO_ARM,
    EVENT_INVALID_CODE,
    EVENT_LOCKED_OUT,
    EVENT_PENDING,
    EVENT_TRIGGERED,
    EVENT_TROUBLE,
    EVENT_TROUBLE_RESTORED,
    EVENT_CHIME,
    mode_label,
)


def _mode(data: dict[str, Any]) -> str:
    return mode_label(data.get("mode"))


def _by(data: dict[str, Any]) -> str:
    user, source = data.get("user"), data.get("source")
    if user and source:
        return f" by {user} via {source}"
    if user:
        return f" by {user}"
    if source:
        return f" by {source}"
    return ""


DENY_TEXT = {
    "automation_disabled": "automations are not allowed",
    "in_alarm": "not allowed during an alarm",
    "not_allowed": "user not allowed",
    "outside_schedule": "outside the allowed time",
    "unknown_user": "unknown user",
    "anonymous_disabled": "no user given",
}


def describe_event(data: dict[str, Any]) -> str:
    """Human-readable message for a pt_alarm_event."""
    event = data.get("event")
    sensor = data.get("sensor_name") or data.get("sensor") or ""
    if data.get("sensor_location"):
        sensor = f"{sensor} in {data['sensor_location']}"
    if event == EVENT_ARMING:
        return f"started arming {_mode(data)}{_by(data)} ({data.get('delay')}s exit delay)"
    if event == EVENT_ARMED:
        if data.get("reason") == "trigger_time_elapsed":
            return f"re-armed {_mode(data)} after the alarm time ended"
        bypassed = data.get("bypassed_names") or []
        extra = f" (bypassed: {', '.join(bypassed)})" if bypassed else ""
        return f"armed {_mode(data)}{_by(data)}{extra}"
    if event == EVENT_DISARMED:
        if data.get("reason") == "trigger_time_elapsed":
            return "disarmed automatically after the alarm time ended"
        if data.get("reason") == "fire_reset":
            return f"fire alarm reset{_by(data)}"
        return f"disarmed{_by(data)}"
    if event == EVENT_PENDING:
        return f"entry delay started by {sensor} ({data.get('delay')}s)"
    if event == EVENT_TRIGGERED:
        if data.get("alarm_type") == "fire":
            return f"FIRE ALARM: {sensor}"
        if data.get("alarm_type") == "panic":
            return f"PANIC ALARM: {sensor or 'manual trigger'}"
        return f"ALARM triggered by {sensor or 'manual trigger'}"
    if event == EVENT_FAILED_TO_ARM:
        return f"could not arm {_mode(data)}{_by(data)}, open: {data.get('sensor_names', '')}"
    if event == EVENT_INVALID_CODE:
        if data.get("reason") == "outside_schedule":
            return f"code of {data.get('user')} refused, outside its allowed time"
        return "invalid code entered"
    if event == "access_denied":
        reason = DENY_TEXT.get(data.get("reason", ""), data.get("reason", ""))
        return f"refused {data.get('action', '')}{_by(data)}: {reason}"
    if event == EVENT_TROUBLE:
        kind = "Tamper" if data.get("zone_type") == "tamper" else "Supervisory"
        return f"TROUBLE ({kind}): {sensor}"
    if event == EVENT_TROUBLE_RESTORED:
        return f"trouble restored: {sensor}"
    if event == EVENT_CHIME:
        return f"chime: {sensor} opened"
    if event == EVENT_LOCKED_OUT:
        return f"keypad locked for {data.get('seconds')}s after too many invalid codes"
    return str(event)


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe PT Alarm events for the activity log."""

    @callback
    def async_describe(event: Event) -> dict[str, str]:
        data = event.data
        entry = {
            LOGBOOK_ENTRY_NAME: data.get("name") or "PT Alarm",
            LOGBOOK_ENTRY_MESSAGE: describe_event(data),
        }
        if data.get(ATTR_ENTITY_ID):
            entry[LOGBOOK_ENTRY_ENTITY_ID] = data[ATTR_ENTITY_ID]
        return entry

    async_describe_event(DOMAIN, EVENT, async_describe)
