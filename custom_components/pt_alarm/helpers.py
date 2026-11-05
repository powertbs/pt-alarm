"""Shared helpers for PT Alarm."""

from __future__ import annotations

import copy
from datetime import date, datetime, time
import hashlib
import hmac
import secrets
from typing import Any

from .const import (
    ARM_MODES,
    CONF_CODE_HASH,
    CONF_DAYS,
    CONF_END_TIME,
    CONF_MODES,
    CONF_NUMERIC,
    CONF_SALT,
    CONF_START_TIME,
    CONF_VALID_FROM,
    CONF_VALID_UNTIL,
    DEFAULT_END_TIME,
    DEFAULT_MODE_SETTINGS,
    DEFAULT_OPTIONS,
    DEFAULT_START_TIME,
    WEEKDAYS,
)

HASH_ITERATIONS = 60_000


def hash_code(code: str, salt: str | None = None) -> dict[str, Any]:
    """Hash a user code. Returns the fields to store on the user record."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", code.encode("utf-8"), bytes.fromhex(salt), HASH_ITERATIONS
    ).hex()
    return {CONF_CODE_HASH: digest, CONF_SALT: salt, CONF_NUMERIC: code.isdigit()}


def check_code(user: dict[str, Any], code: str) -> bool:
    """Check a code against a stored user record (blocking, run in executor)."""
    salt = user.get(CONF_SALT)
    stored = user.get(CONF_CODE_HASH)
    if not salt or not stored or not code:
        return False
    digest = hash_code(code, salt)[CONF_CODE_HASH]
    return hmac.compare_digest(digest, stored)


def merged_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """Return options merged on top of the defaults (deep copy)."""
    result = copy.deepcopy(DEFAULT_OPTIONS)
    for key, value in (options or {}).items():
        result[key] = copy.deepcopy(value)

    modes = copy.deepcopy(DEFAULT_MODE_SETTINGS)
    for mode in ARM_MODES:
        modes[mode].update((options or {}).get(CONF_MODES, {}).get(mode, {}))
    result[CONF_MODES] = modes
    return result


def _parse_time(value: str | None, default: str) -> time:
    try:
        return time.fromisoformat(value or default)
    except ValueError:
        return time.fromisoformat(default)


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def user_allowed_now(user: dict[str, Any], now: datetime) -> bool:
    """Whether the user's schedule (dates, days, time window) allows use right now."""
    valid_from = _parse_date(user.get(CONF_VALID_FROM))
    valid_until = _parse_date(user.get(CONF_VALID_UNTIL))
    if valid_from and now.date() < valid_from:
        return False
    if valid_until and now.date() > valid_until:
        return False
    days = user.get(CONF_DAYS) or WEEKDAYS
    start = _parse_time(user.get(CONF_START_TIME), DEFAULT_START_TIME)
    end = _parse_time(user.get(CONF_END_TIME), DEFAULT_END_TIME)
    current = now.replace(microsecond=0).time()
    today = WEEKDAYS[now.weekday()]
    yesterday = WEEKDAYS[(now.weekday() - 1) % 7]

    if start <= end:
        return today in days and start <= current <= end
    # Overnight window, e.g. 22:00 -> 06:00: the early-morning part belongs
    # to the window that started on the previous day.
    if current >= start:
        return today in days
    if current <= end:
        return yesterday in days
    return False


def schedule_text(user: dict[str, Any]) -> str:
    """Short human-readable schedule, e.g. 'mon-fri 08:00-18:00'."""
    days = user.get(CONF_DAYS) or WEEKDAYS
    start = (user.get(CONF_START_TIME) or DEFAULT_START_TIME)[:5]
    end = (user.get(CONF_END_TIME) or DEFAULT_END_TIME)[:5]
    day_text = "every day" if len(days) == 7 else ", ".join(days)
    text = day_text if (start == "00:00" and end == "23:59") else f"{day_text} {start}-{end}"
    valid_from = user.get(CONF_VALID_FROM)
    valid_until = user.get(CONF_VALID_UNTIL)
    if valid_from or valid_until:
        text += f", {valid_from or '...'} to {valid_until or '...'}"
    if user.get("blocked_by"):
        text += ", not on holidays"
    return text
