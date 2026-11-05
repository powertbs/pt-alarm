"""Shared helpers for PT Alarm."""

from __future__ import annotations

import copy
import hashlib
import hmac
import secrets
from typing import Any

from .const import (
    ARM_MODES,
    CONF_CODE_HASH,
    CONF_MODES,
    CONF_NUMERIC,
    CONF_SALT,
    DEFAULT_MODE_SETTINGS,
    DEFAULT_OPTIONS,
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
