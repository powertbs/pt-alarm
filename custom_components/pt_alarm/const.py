"""Constants for PT Alarm."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "pt_alarm"
NAME = "PT Alarm"
VERSION = "0.0.3"
MANUFACTURER = "PowerTech Security & Communications"

PLATFORMS: list[Platform] = [Platform.ALARM_CONTROL_PANEL, Platform.SENSOR]

# Frontend (dashboard card) served by the integration itself
FRONTEND_URL_BASE = "/pt_alarm_static"
CARD_FILENAME = "pt-alarm-card.js"

EVENT = f"{DOMAIN}_event"


def signal_update(entry_id: str) -> str:
    """Dispatcher signal sent whenever a panel's state changes."""
    return f"{DOMAIN}_{entry_id}_update"

# ---------------------------------------------------------------------------
# Arm modes
# ---------------------------------------------------------------------------
MODE_AWAY = "armed_away"
MODE_HOME = "armed_home"
MODE_NIGHT = "armed_night"
MODE_VACATION = "armed_vacation"
MODE_CUSTOM = "armed_custom_bypass"

ARM_MODES: list[str] = [MODE_AWAY, MODE_HOME, MODE_NIGHT, MODE_VACATION, MODE_CUSTOM]

# Alarm-industry wording ("Home" is Home Assistant's name for "Stay")
MODE_LABELS: dict[str, str] = {
    MODE_AWAY: "away",
    MODE_HOME: "stay",
    MODE_NIGHT: "night",
    MODE_VACATION: "vacation",
    MODE_CUSTOM: "custom",
}


def mode_label(mode: str | None) -> str:
    """Display word for an arm mode, e.g. armed_home -> stay."""
    return MODE_LABELS.get(mode or "", str(mode or "").replace("armed_", "").replace("_", " "))

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
CONF_SENSOR_NAME = "name"
CONF_AREA = "area"

CONF_USERS = "users"
CONF_USER_ID = "id"
CONF_USER_NAME = "name"
CONF_CODE = "code"
CONF_CODE_HASH = "code_hash"
CONF_SALT = "salt"
CONF_NUMERIC = "numeric"
CONF_CAN_ARM = "can_arm"
CONF_CAN_DISARM = "can_disarm"
CONF_CAN_BYPASS = "can_bypass"
CONF_DAYS = "days"
CONF_START_TIME = "start_time"
CONF_END_TIME = "end_time"
CONF_VALID_FROM = "valid_from"
CONF_VALID_UNTIL = "valid_until"
CONF_BLOCKED_BY = "blocked_by"
CONF_PARTITIONS = "partitions"
CONF_ACCESS_IDS = "access_ids"

# Automations and access control
CONF_AUTOMATION_ALLOWED = "automation_allowed"
CONF_AUTOMATION_OPEN_ZONES = "automation_open_zones"
CONF_AUTOMATION_ANONYMOUS = "automation_anonymous"
OPEN_ZONES_REFUSE = "refuse"
OPEN_ZONES_BYPASS = "bypass"
BLOCKING_DOMAINS = ["calendar", "binary_sensor", "input_boolean", "switch", "schedule"]

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_START_TIME = "00:00:00"
DEFAULT_END_TIME = "23:59:59"

CONF_SIREN_ENTITIES = "siren_entities"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_NOTIFY_EVENTS = "notify_events"  # legacy (moved to push)
CONF_EMAIL_SERVICES = "email_services"
CONF_EMAIL_EVENTS = "email_events"
CONF_EMAIL_HTML = "email_html"
CONF_PUSH_SERVICES = "push_services"
CONF_PUSH_EVENTS = "push_events"

DEFAULT_EMAIL_EVENTS = [
    "alarm", "fire", "bypassed", "failed_to_arm", "invalid_code",
    "locked_out", "trouble", "access_denied",
]
DEFAULT_PUSH_EVENTS = [
    "alarm", "fire", "pending", "failed_to_arm", "locked_out", "trouble", "access_denied",
]

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

# ---------------------------------------------------------------------------
# Zone types (how a zone behaves) - alarm-industry zone definitions
# ---------------------------------------------------------------------------
CONF_ZONE_TYPE = "zone_type"
CONF_CHIME = "chime"
CONF_ENTRY_DELAY_1 = "entry_delay_1"
CONF_ENTRY_DELAY_2 = "entry_delay_2"
CONF_INSTANT = "instant"

ZT_ENTRY_EXIT_1 = "entry_exit_1"
ZT_ENTRY_EXIT_2 = "entry_exit_2"
ZT_PERIMETER = "perimeter"
ZT_INTERIOR_FOLLOWER = "interior_follower"
ZT_INTERIOR = "interior"
ZT_PANIC = "panic"
ZT_FIRE = "fire"
ZT_SUPERVISORY = "supervisory"
ZT_TAMPER = "tamper"

ZONE_TYPES = [
    ZT_ENTRY_EXIT_1,
    ZT_ENTRY_EXIT_2,
    ZT_PERIMETER,
    ZT_INTERIOR_FOLLOWER,
    ZT_INTERIOR,
    ZT_FIRE,
    ZT_PANIC,
    ZT_SUPERVISORY,
    ZT_TAMPER,
]

BURGLARY_ZONES = {ZT_ENTRY_EXIT_1, ZT_ENTRY_EXIT_2, ZT_PERIMETER, ZT_INTERIOR_FOLLOWER, ZT_INTERIOR}
INTERIOR_ZONES = {ZT_INTERIOR_FOLLOWER, ZT_INTERIOR}
# Zones that keep the system "not ready" while open
BLOCKING_ZONES = {ZT_ENTRY_EXIT_1, ZT_ENTRY_EXIT_2, ZT_PERIMETER}
# Zones that never sound the alarm, they report a trouble
TROUBLE_ZONES = {ZT_SUPERVISORY, ZT_TAMPER}
ENTRY_DELAY_ZONES = {ZT_ENTRY_EXIT_1: CONF_ENTRY_DELAY_1, ZT_ENTRY_EXIT_2: CONF_ENTRY_DELAY_2}
# Stay and Night leave the interior (motion) zones off
STAY_MODES = {MODE_HOME, MODE_NIGHT}

ALARM_BURGLARY = "burglary"
ALARM_FIRE = "fire"
ALARM_PANIC = "panic"


def zone_armed_in(zone_type: str, mode: str | None) -> bool:
    """Whether a burglary zone is armed in the given arm mode."""
    if zone_type not in BURGLARY_ZONES or mode is None:
        return False
    return not (zone_type in INTERIOR_ZONES and mode in STAY_MODES)


# Default zone type for each device kind
KIND_ZONE_TYPES: dict[str, str] = {
    SENSOR_DOOR: ZT_ENTRY_EXIT_1,
    SENSOR_WINDOW: ZT_PERIMETER,
    SENSOR_MOTION: ZT_INTERIOR_FOLLOWER,
    SENSOR_TAMPER: ZT_TAMPER,
    SENSOR_ENVIRONMENTAL: ZT_FIRE,
    SENSOR_OTHER: ZT_PERIMETER,
}

# Device classes that clearly call for a specific zone type
DEVICE_CLASS_ZONE_TYPES: dict[str, str] = {
    "smoke": ZT_FIRE,
    "heat": ZT_FIRE,
    "gas": ZT_FIRE,
    "carbon_monoxide": ZT_FIRE,
    "moisture": ZT_SUPERVISORY,
    "cold": ZT_SUPERVISORY,
    "problem": ZT_SUPERVISORY,
    "tamper": ZT_TAMPER,
    "safety": ZT_PANIC,
    "window": ZT_PERIMETER,
}

SENSOR_DOMAINS = [
    "binary_sensor",
    "lock",
    "cover",
    "input_boolean",
    "switch",
    "device_tracker",
]

# Guess a sensor type from its device class
DEVICE_CLASS_TYPES: dict[str, str] = {
    "door": SENSOR_DOOR,
    "garage_door": SENSOR_DOOR,
    "opening": SENSOR_DOOR,
    "lock": SENSOR_DOOR,
    "garage": SENSOR_DOOR,
    "gate": SENSOR_DOOR,
    "window": SENSOR_WINDOW,
    "shutter": SENSOR_WINDOW,
    "blind": SENSOR_WINDOW,
    "motion": SENSOR_MOTION,
    "occupancy": SENSOR_MOTION,
    "presence": SENSOR_MOTION,
    "moving": SENSOR_MOTION,
    "tamper": SENSOR_TAMPER,
    "vibration": SENSOR_TAMPER,
    "smoke": SENSOR_ENVIRONMENTAL,
    "gas": SENSOR_ENVIRONMENTAL,
    "carbon_monoxide": SENSOR_ENVIRONMENTAL,
    "moisture": SENSOR_ENVIRONMENTAL,
    "heat": SENSOR_ENVIRONMENTAL,
    "cold": SENSOR_ENVIRONMENTAL,
    "safety": SENSOR_ENVIRONMENTAL,
}

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
EVENT_TROUBLE = "trouble"
EVENT_TROUBLE_RESTORED = "trouble_restored"
EVENT_CHIME = "chime"
EVENT_ACCESS_DENIED = "access_denied"

NOTIFY_EVENTS = [
    EVENT_ARMING,
    EVENT_ARMED,
    EVENT_DISARMED,
    EVENT_PENDING,
    EVENT_TRIGGERED,
    EVENT_FAILED_TO_ARM,
    EVENT_INVALID_CODE,
    EVENT_LOCKED_OUT,
    EVENT_TROUBLE,
    EVENT_TROUBLE_RESTORED,
    EVENT_ACCESS_DENIED,
]

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_MODE_SETTINGS: dict[str, dict] = {
    MODE_AWAY: {CONF_ENABLED: True, CONF_EXIT_TIME: 60, CONF_TRIGGER_TIME: 180, CONF_INSTANT: False},
    MODE_HOME: {CONF_ENABLED: True, CONF_EXIT_TIME: 60, CONF_TRIGGER_TIME: 180, CONF_INSTANT: False},
    MODE_NIGHT: {CONF_ENABLED: True, CONF_EXIT_TIME: 0, CONF_TRIGGER_TIME: 180, CONF_INSTANT: False},
    MODE_VACATION: {CONF_ENABLED: False, CONF_EXIT_TIME: 60, CONF_TRIGGER_TIME: 300, CONF_INSTANT: False},
    MODE_CUSTOM: {CONF_ENABLED: False, CONF_EXIT_TIME: 0, CONF_TRIGGER_TIME: 180, CONF_INSTANT: False},
}

DEFAULT_OPTIONS: dict = {
    CONF_CODE_ARM_REQUIRED: False,
    CONF_CODE_DISARM_REQUIRED: True,
    CONF_DISARM_AFTER_TRIGGER: False,
    CONF_AUTO_BYPASS: False,
    CONF_MAX_ATTEMPTS: 5,
    CONF_LOCKOUT_TIME: 60,
    CONF_ENTRY_DELAY_1: 30,
    CONF_ENTRY_DELAY_2: 45,
    CONF_AUTOMATION_ALLOWED: False,
    CONF_AUTOMATION_OPEN_ZONES: OPEN_ZONES_REFUSE,
    CONF_AUTOMATION_ANONYMOUS: False,
    CONF_MODES: DEFAULT_MODE_SETTINGS,
    CONF_SENSORS: {},
    CONF_USERS: [],
    CONF_SIREN_ENTITIES: [],
    CONF_EMAIL_SERVICES: [],
    CONF_EMAIL_EVENTS: DEFAULT_EMAIL_EVENTS,
    CONF_EMAIL_HTML: True,
    CONF_PUSH_SERVICES: [],
    CONF_PUSH_EVENTS: DEFAULT_PUSH_EVENTS,
    CONF_NOTIFY_SERVICES: [],
    CONF_NOTIFY_EVENTS: [EVENT_TRIGGERED, EVENT_FAILED_TO_ARM, EVENT_TROUBLE, EVENT_ACCESS_DENIED],
}

# Services
SERVICE_ARM = "arm"
SERVICE_DISARM = "disarm"
ATTR_MODE = "mode"
ATTR_CODE = "code"
ATTR_FORCE = "force"
ATTR_SKIP_DELAY = "skip_delay"
ATTR_USER = "user"
ATTR_SOURCE = "source"

# Remember which automation / script started a service call (by context id)
DATA_CONTEXT_SOURCES = f"{DOMAIN}_context_sources"
