"""Email and push notifications for PT Alarm (with the PowerTech HTML email design)."""

from __future__ import annotations

from html import escape
import logging
from pathlib import Path
from string import Template
from typing import Any

from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util

from .const import (
    DEFAULT_EMAIL_EVENTS,  # noqa: F401  (re-exported for the config flow)
    DEFAULT_PUSH_EVENTS,  # noqa: F401
    CONF_EMAIL_EVENTS,
    CONF_EMAIL_HTML,
    CONF_EMAIL_SERVICES,
    CONF_PUSH_EVENTS,
    CONF_PUSH_SERVICES,
    DOMAIN,
    mode_label,
)

_LOGGER = logging.getLogger(__name__)

LOGO_URL = "https://raw.githubusercontent.com/powertbs/pt-alarm/main/docs/logo.png"
TEMPLATE_FILE = Path(__file__).parent / "email_template.html"
OVERRIDE_FILE = "pt_alarm_email.html"  # in the Home Assistant config folder

# Notification categories the user can switch on/off per channel
NC_ARMING = "arming"
NC_ARMED = "armed"
NC_DISARMED = "disarmed"
NC_PENDING = "pending"
NC_ALARM = "alarm"
NC_FIRE = "fire"
NC_BYPASSED = "bypassed"
NC_FAILED_TO_ARM = "failed_to_arm"
NC_INVALID_CODE = "invalid_code"
NC_LOCKED_OUT = "locked_out"
NC_TROUBLE = "trouble"
NC_TROUBLE_RESTORED = "trouble_restored"
NC_ACCESS_DENIED = "access_denied"
NC_TEST = "test"

NOTIFY_CATEGORIES = [
    NC_ALARM,
    NC_FIRE,
    NC_ARMING,
    NC_ARMED,
    NC_DISARMED,
    NC_PENDING,
    NC_BYPASSED,
    NC_FAILED_TO_ARM,
    NC_INVALID_CODE,
    NC_LOCKED_OUT,
    NC_TROUBLE,
    NC_TROUBLE_RESTORED,
    NC_ACCESS_DENIED,
]


GREEN, RED, AMBER, FIRE, ORANGE, SLATE = "#2e7d32", "#c62828", "#ef8f00", "#d84315", "#ef6c00", "#455a64"

# category -> (banner colour, icon)
STYLE = {
    NC_ARMING: (AMBER, "&#9203;"),          # hourglass
    NC_ARMED: (RED, "&#128274;"),           # lock
    NC_BYPASSED: (RED, "&#128274;"),
    NC_DISARMED: (GREEN, "&#9989;"),        # check mark
    NC_PENDING: (AMBER, "&#9203;"),
    NC_ALARM: (RED, "&#128680;"),           # siren
    NC_FIRE: (FIRE, "&#128293;"),           # fire
    NC_FAILED_TO_ARM: (SLATE, "&#9888;&#65039;"),
    NC_INVALID_CODE: (SLATE, "&#128273;"),  # key
    NC_LOCKED_OUT: (SLATE, "&#128683;"),
    NC_TROUBLE: (ORANGE, "&#9888;&#65039;"),
    NC_TROUBLE_RESTORED: (GREEN, "&#9989;"),
    NC_ACCESS_DENIED: (SLATE, "&#9940;"),
    NC_TEST: ("#1e88e5", "&#128276;"),      # bell
}
SUBJECT_ICON = {
    NC_ALARM: "\U0001f6a8 ", NC_FIRE: "\U0001f525 ", NC_TROUBLE: "⚠️ ",
    NC_DISARMED: "✅ ", NC_ARMED: "\U0001f512 ", NC_BYPASSED: "\U0001f512 ",
}


def categories_for(event_type: str, data: dict[str, Any]) -> list[str]:
    """Notification categories for an event, most specific first."""
    if event_type == "triggered":
        return [NC_FIRE] if data.get("alarm_type") == "fire" else [NC_ALARM]
    if event_type == "armed":
        return [NC_BYPASSED, NC_ARMED] if data.get("bypassed_names") else [NC_ARMED]
    if event_type in NOTIFY_CATEGORIES:
        return [event_type]
    return []


def headline(category: str, data: dict[str, Any]) -> tuple[str, str]:
    """Banner title and subtitle."""
    mode = mode_label(data.get("mode")).title()
    titles = {
        NC_ARMING: ("Arming", f"Arming {mode} · {data.get('delay', '')} seconds to leave"),
        NC_ARMED: (f"Armed {mode}", "The system is armed"),
        NC_BYPASSED: (f"Armed {mode}", "Armed with bypassed zones"),
        NC_DISARMED: ("Fire alarm reset", "The fire alarm was reset")
        if data.get("reason") == "fire_reset"
        else ("Disarmed", "The system is disarmed"),
        NC_PENDING: ("Entry delay", f"{data.get('delay', '')} seconds to disarm"),
        NC_ALARM: ("Panic alarm" if data.get("alarm_type") == "panic" else "Alarm", "The alarm is sounding"),
        NC_FIRE: ("Fire alarm", "Fire / CO detected"),
        NC_FAILED_TO_ARM: ("Not armed", "Zones are open"),
        NC_INVALID_CODE: ("Wrong code", "An invalid code was entered"),
        NC_LOCKED_OUT: ("Keypad locked", "Too many wrong codes"),
        NC_TROUBLE: ("Trouble", "Tamper" if data.get("zone_type") == "tamper" else "Supervisory"),
        NC_TROUBLE_RESTORED: ("Trouble restored", "Back to normal"),
        NC_ACCESS_DENIED: ("Refused", f"{str(data.get('action', '')).capitalize()} was refused"),
        NC_TEST: ("Test", "PT Alarm notifications are working"),
    }
    return titles.get(category, (category, ""))


def _row(label: str, value: Any) -> str:
    if value in (None, "", []):
        return ""
    return (
        '<tr><td style="padding:9px 10px;border-bottom:1px solid #eceef1;color:#6b7280;width:38%;">'
        f"{escape(label)}</td>"
        '<td style="padding:9px 10px;border-bottom:1px solid #eceef1;font-weight:600;color:#1f2933;">'
        f"{escape(str(value))}</td></tr>"
    )


def build_content(
    hass: HomeAssistant, partition: str, category: str, data: dict[str, Any], message: str
) -> dict[str, str]:
    """Everything the templates need."""
    title, subtitle = headline(category, data)
    color, icon = STYLE.get(category, (SLATE, "&#128276;"))
    now = dt_util.now()
    zone = data.get("sensor_name") or ""
    if zone and data.get("sensor_location"):
        zone = f"{zone} ({data['sensor_location']})"
    rows = "".join(
        [
            _row("Partition", partition),
            _row("Zone", zone),
            _row("Open zones", data.get("sensor_names")),
            _row("Bypassed zones", ", ".join(data.get("bypassed_names") or [])),
            _row("User", data.get("user")),
            _row("Via", data.get("source")),
            _row("Time", now.strftime("%A, %B %d, %Y  %H:%M:%S")),
        ]
    )
    url = hass.config.external_url or hass.config.internal_url
    button = (
        f'<a href="{escape(url)}" style="display:inline-block;background:#1f2933;color:#ffffff;'
        'text-decoration:none;font-weight:600;padding:12px 26px;border-radius:8px;">'
        "Open Home Assistant</a>"
        if url
        else ""
    )
    return {
        "subject": f"{SUBJECT_ICON.get(category, '')}{title} – {partition}",
        "title": escape(title),
        "subtitle": escape(f"{partition} · {subtitle}" if subtitle else partition),
        "message": escape(message),
        "icon": icon,
        "color": color,
        "partition": escape(partition),
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "year": str(now.year),
        "rows": rows,
        "button": button,
        "logo_url": LOGO_URL,
        "preheader": escape(message),
    }


def _load_template(hass: HomeAssistant) -> str:
    override = Path(hass.config.path(OVERRIDE_FILE))
    path = override if override.is_file() else TEMPLATE_FILE
    return path.read_text(encoding="utf-8")


async def async_render_html(hass: HomeAssistant, content: dict[str, str]) -> str:
    """Render the HTML email (your own pt_alarm_email.html wins over the built-in design)."""
    text = await hass.async_add_executor_job(_load_template, hass)
    return Template(text).safe_substitute(content)


def _split(service: str) -> tuple[str, str]:
    domain, _, name = service.partition(".")
    return (domain, name) if name else ("notify", service)


async def async_send(
    hass: HomeAssistant,
    cfg: dict[str, Any],
    partition: str,
    categories: list[str],
    data: dict[str, Any],
    message: str,
    force: bool = False,
) -> None:
    """Send email and/or push for the first enabled category (force: test message)."""

    def pick(enabled: list[str]) -> str | None:
        if force:
            return categories[0]
        return next((c for c in categories if c in enabled), None)

    email_cat = pick(cfg.get(CONF_EMAIL_EVENTS, []))
    push_cat = pick(cfg.get(CONF_PUSH_EVENTS, []))

    if email_cat and cfg.get(CONF_EMAIL_SERVICES):
        content = build_content(hass, partition, email_cat, data, message)
        payload: dict[str, Any] = {"title": content["subject"], "message": message}
        if cfg.get(CONF_EMAIL_HTML, True):
            payload["data"] = {"html": await async_render_html(hass, content)}
        for service in cfg[CONF_EMAIL_SERVICES]:
            await _call(hass, service, payload)

    if push_cat and cfg.get(CONF_PUSH_SERVICES):
        title = build_content(hass, partition, push_cat, data, message)["subject"]
        payload = {"title": title, "message": message}
        if push_cat in (NC_ALARM, NC_FIRE):
            # Break through quiet modes on phones (iOS / Android companion apps).
            payload["data"] = {
                "push": {"interruption-level": "time-sensitive"},
                "ttl": 0,
                "priority": "high",
                "tag": f"{DOMAIN}_{partition}",
            }
        for service in cfg[CONF_PUSH_SERVICES]:
            await _call(hass, service, payload)


async def _call(hass: HomeAssistant, service: str, payload: dict[str, Any]) -> None:
    domain, name = _split(service)
    try:
        if not hass.services.has_service(domain, name) and hass.states.get(f"{domain}.{name}"):
            # New-style notify entity (e.g. SMTP set up from the UI): title + message only.
            await hass.services.async_call(
                "notify",
                "send_message",
                {
                    "entity_id": f"{domain}.{name}",
                    "title": payload.get("title"),
                    "message": payload["message"],
                },
                blocking=False,
            )
            return
        await hass.services.async_call(domain, name, payload, blocking=False)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("PT Alarm could not notify via %s.%s", domain, name)
