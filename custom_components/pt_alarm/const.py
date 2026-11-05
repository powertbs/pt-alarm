"""Constants for PT Alarm."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "pt_alarm"
NAME = "PT Alarm"
VERSION = "0.0.1"
MANUFACTURER = "PowerTech Security & Communications"

PLATFORMS: list[Platform] = [Platform.ALARM_CONTROL_PANEL]

# Frontend (dashboard card) served by the integration itself
FRONTEND_URL_BASE = "/pt_alarm_static"
CARD_FILENAME = "pt-alarm-card.js"

EVENT = f"{DOMAIN}_event"

# ---------------------------------------------------------------------------
# Arm modes
# ---------------------------------------------------------------------------
MODE_AWAY = "armed_away"
MODE_HOME = "armed_home"
MODE_NIGHT = "armed_night"
MODE_VACATION = "armed_vacation"
MODE_CUSTOM = "armed_custom_bypass"

ARM_MODES: list[str] = [MODE_AWAY, MODE_HOME, MODE_NIGHT, MODE_VACATION, MODE_CUSTOM]

# ---------------------------------------------------------------------------
# Option keys
# ---------------------------------------------------------------------------
CONF_CODE_ARM_REQUIRED = "code_arm_required"
CONF_CODE_DISARM_REQUIRED = "code_disarm_required"
CONF_DISARM_AFTER_TRIGGER = "disarm_after_trigger"
CONF_AUTO_BYPASS = "auto_bypass"
CONF_MAX_ATTEMPTS = "max_attempts"
CONF_LOCKOUT_TIME = "lockout_time"

CONF_MODES = "modes"
CONF_ENABLED = "enabled"
CONF_EXIT_TIME = "exit_time"
CONF_ENTRY_TIME = "entry_time"
CONF_TRIGGER_TIME = "trigger_time"

CONF_SENSORS = "sensors"
CONF_TYPE = "type"
CONF_SENSOR_MODES = "modes"
CONF_IMMEDIATE = "immediate"
CONF_ALWAYS_ON = "always_on"
CONF_ALLOW_OPEN = "allow_open"
CONF_TRIGGER_UNAVAILABLE = "trigger_unavailable"

CONF_USERS = "users"
CONF_USER_ID = "id"
CONF_USER_NAME = "name"
CONF_CODE = "code"
CONF_CODE_HASH = "code_hash"
CONF_SALT = "salt"
CONF_NUMERIC = "numeric"
CONF_CAN_ARM = "can_arm"
CONF_CAN_DISARM = "can_disarm"

CONF_SIREN_ENTITIES = "siren_entities"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_NOTIFY_EVENTS = "notify_events"

# ---------------------------------------------------------------------------
# Sensor types and their defaults
# ---------------------------------------------------------------------------
SENSOR_DOOR = "door"
SENSOR_WINDOW = "window"
SENSOR_MOTION = "motion"
SENSOR_TAMPER = "tamper"
SENSOR_ENVIRONMENTAL = "environmental"
SENSOR_OTHER = "other"

SENSOR_TYPES = [
    SENSOR_DOOR,
    SENSOR_WINDOW,
    SENSOR_MOTION,
    SENSOR_TAMPER,
    SENSOR_ENVIRONMENTAL,
    SENSOR_OTHER,
]

SENSOR_TYPE_DEFAULTS: dict[str, dict] = {
    SENSOR_DOOR: {
        CONF_SENSOR_MODES: [MODE_AWAY, MODE_HOME, MODE_NIGHT, MODE_VACATION],
        CONF_IMMEDIATE: False,
        CONF_ALWAYS_ON: False,
        CONF_ALLOW_OPEN: False,
    },
    SENSOR_WINDOW: {
        CONF_SENSOR_MODES: [MODE_AWAY, MODE_HOME, MODE_NIGHT, MODE_VACATION],
        CONF_IMMEDIATE: True,
        CONF_ALWAYS_ON: False,
        CONF_ALLOW_OPEN: False,
    },
    SENSOR_MOTION: {
        CONF_SENSOR_MODES: [MODE_AWAY, MODE_VACATION],
        CONF_IMMEDIATE: False,
        CONF_ALWAYS_ON: False,
        CONF_ALLOW_OPEN: True,
    },
    SENSOR_TAMPER: {
        CONF_SENSOR_MODES: [],
        CONF_IMMEDIATE: True,
        CONF_ALWAYS_ON: True,
        CONF_ALLOW_OPEN: True,
    },
    SENSOR_ENVIRONMENTAL: {
        CONF_SENSOR_MODES: [],
        CONF_IMMEDIATE: True,
        CONF_ALWAYS_ON: True,
        CONF_ALLOW_OPEN: True,
    },
    SENSOR_OTHER: {
        CONF_SENSOR_MODES: [MODE_AWAY],
        CONF_IMMEDIATE: False,
        CONF_ALWAYS_ON: False,
        CONF_ALLOW_OPEN: False,
    },
}

SENSOR_DOMAINS = [
    "binary_sensor",
    "sensor",
    "lock",
    "cover",
    "input_boolean",
    "switch",
    "device_tracker",
]

# States that count as "open" / "active" for a sensor
OPEN_STATES = {"on", "open", "opening", "unlocked", "detected", "true", "not_home"}
UNAVAILABLE_STATES = {"unavailable", "unknown"}

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
EVENT_ARMING = "arming"
EVENT_ARMED = "armed"
EVENT_DISARMED = "disarmed"
EVENT_PENDING = "pending"
EVENT_TRIGGERED = "triggered"
EVENT_FAILED_TO_ARM = "failed_to_arm"
EVENT_INVALID_CODE = "invalid_code"
EVENT_LOCKED_OUT = "locked_out"

NOTIFY_EVENTS = [
    EVENT_ARMING,
    EVENT_ARMED,
    EVENT_DISARMED,
    EVENT_PENDING,
    EVENT_TRIGGERED,
    EVENT_FAILED_TO_ARM,
    EVENT_INVALID_CODE,
    EVENT_LOCKED_OUT,
]

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_MODE_SETTINGS: dict[str, dict] = {
    MODE_AWAY: {CONF_ENABLED: True, CONF_EXIT_TIME: 60, CONF_ENTRY_TIME: 30, CONF_TRIGGER_TIME: 180},
    MODE_HOME: {CONF_ENABLED: True, CONF_EXIT_TIME: 0, CONF_ENTRY_TIME: 30, CONF_TRIGGER_TIME: 180},
    MODE_NIGHT: {CONF_ENABLED: True, CONF_EXIT_TIME: 0, CONF_ENTRY_TIME: 30, CONF_TRIGGER_TIME: 180},
    MODE_VACATION: {CONF_ENABLED: False, CONF_EXIT_TIME: 60, CONF_ENTRY_TIME: 30, CONF_TRIGGER_TIME: 300},
    MODE_CUSTOM: {CONF_ENABLED: False, CONF_EXIT_TIME: 0, CONF_ENTRY_TIME: 30, CONF_TRIGGER_TIME: 180},
}

DEFAULT_OPTIONS: dict = {
    CONF_CODE_ARM_REQUIRED: False,
    CONF_CODE_DISARM_REQUIRED: True,
    CONF_DISARM_AFTER_TRIGGER: False,
    CONF_AUTO_BYPASS: False,
    CONF_MAX_ATTEMPTS: 5,
    CONF_LOCKOUT_TIME: 60,
    CONF_MODES: DEFAULT_MODE_SETTINGS,
    CONF_SENSORS: {},
    CONF_USERS: [],
    CONF_SIREN_ENTITIES: [],
    CONF_NOTIFY_SERVICES: [],
    CONF_NOTIFY_EVENTS: [EVENT_TRIGGERED, EVENT_FAILED_TO_ARM],
}

# Services
SERVICE_ARM = "arm"
SERVICE_DISARM = "disarm"
ATTR_MODE = "mode"
ATTR_CODE = "code"
ATTR_FORCE = "force"
ATTR_SKIP_DELAY = "skip_delay"
