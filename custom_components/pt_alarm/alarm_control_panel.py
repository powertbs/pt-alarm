"""PT Alarm control panel entity: the alarm state machine."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    entity_platform,
    entity_registry as er,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.util.dt as dt_util

from .const import (
    ALARM_BURGLARY,
    ALARM_FIRE,
    ALARM_PANIC,
    ARM_MODES,
    ATTR_CODE,
    ATTR_FORCE,
    ATTR_MODE,
    ATTR_SKIP_DELAY,
    ATTR_SOURCE,
    ATTR_USER,
    BLOCKING_ZONES,
    CONF_ACCESS_IDS,
    CONF_AREA,
    CONF_AUTO_BYPASS,
    CONF_AUTOMATION_ALLOWED,
    CONF_AUTOMATION_ANONYMOUS,
    CONF_AUTOMATION_OPEN_ZONES,
    CONF_BLOCKED_BY,
    CONF_CAN_ARM,
    CONF_CAN_BYPASS,
    CONF_CAN_DISARM,
    CONF_CHIME,
    CONF_CODE_ARM_REQUIRED,
    CONF_CODE_DISARM_REQUIRED,
    CONF_DISARM_AFTER_TRIGGER,
    CONF_ENABLED,
    CONF_EXIT_TIME,
    CONF_INSTANT,
    CONF_LOCKOUT_TIME,
    CONF_MAX_ATTEMPTS,
    CONF_MODES,
    CONF_EMAIL_SERVICES,
    CONF_PUSH_SERVICES,
    CONF_NUMERIC,
    CONF_SENSOR_NAME,
    CONF_SENSORS,
    CONF_SIREN_ENTITIES,
    CONF_TRIGGER_TIME,
    CONF_TRIGGER_UNAVAILABLE,
    CONF_TYPE,
    CONF_USER_NAME,
    CONF_USERS,
    CONF_ZONE_TYPE,
    DATA_CONTEXT_SOURCES,
    DOMAIN,
    ENTRY_DELAY_ZONES,
    EVENT,
    EVENT_ACCESS_DENIED,
    EVENT_ARMED,
    EVENT_ARMING,
    EVENT_CHIME,
    EVENT_DISARMED,
    EVENT_FAILED_TO_ARM,
    EVENT_INVALID_CODE,
    EVENT_LOCKED_OUT,
    EVENT_PENDING,
    EVENT_TRIGGERED,
    EVENT_TROUBLE,
    EVENT_TROUBLE_RESTORED,
    MANUFACTURER,
    MODE_AWAY,
    MODE_CUSTOM,
    MODE_HOME,
    MODE_NIGHT,
    MODE_VACATION,
    OPEN_STATES,
    OPEN_ZONES_BYPASS,
    SERVICE_ARM,
    TROUBLE_ZONES,
    UNAVAILABLE_STATES,
    VERSION,
    ZT_ENTRY_EXIT_1,
    ZT_ENTRY_EXIT_2,
    ZT_FIRE,
    ZT_INTERIOR_FOLLOWER,
    ZT_PANIC,
    mode_label,
    signal_update,
    zone_armed_in,
)
from .helpers import check_code, merged_options, user_allowed_now, zone_type_of
from .notifications import async_send, categories_for

_LOGGER = logging.getLogger(__name__)

STATE = AlarmControlPanelState

MODE_TO_STATE: dict[str, AlarmControlPanelState] = {
    MODE_AWAY: STATE.ARMED_AWAY,
    MODE_HOME: STATE.ARMED_HOME,
    MODE_NIGHT: STATE.ARMED_NIGHT,
    MODE_VACATION: STATE.ARMED_VACATION,
    MODE_CUSTOM: STATE.ARMED_CUSTOM_BYPASS,
}
MODE_TO_FEATURE: dict[str, AlarmControlPanelEntityFeature] = {
    MODE_AWAY: AlarmControlPanelEntityFeature.ARM_AWAY,
    MODE_HOME: AlarmControlPanelEntityFeature.ARM_HOME,
    MODE_NIGHT: AlarmControlPanelEntityFeature.ARM_NIGHT,
    MODE_VACATION: AlarmControlPanelEntityFeature.ARM_VACATION,
    MODE_CUSTOM: AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS,
}
ARMED_STATES = set(MODE_TO_STATE.values())

EVENT_MESSAGES = {
    EVENT_ARMING: "{name} is arming ({mode}), exit delay {delay}s",
    EVENT_ARMED: "{name} is armed ({mode})",
    EVENT_DISARMED: "{name} is disarmed",
    EVENT_PENDING: "{name}: {sensor} opened, entry delay {delay}s",
    EVENT_TRIGGERED: "ALARM! {name} was triggered by {sensor}",
    "triggered_fire": "FIRE ALARM! {name}: {sensor}",
    "triggered_panic": "PANIC ALARM! {name}: {sensor}",
    EVENT_FAILED_TO_ARM: "{name} could not be armed, open sensors: {sensors}",
    EVENT_INVALID_CODE: "{name}: an invalid code was entered",
    EVENT_LOCKED_OUT: "{name}: too many invalid codes, keypad locked",
    EVENT_TROUBLE: "{name}: TROUBLE - {sensor}",
    EVENT_TROUBLE_RESTORED: "{name}: {sensor} is back to normal",
    EVENT_ACCESS_DENIED: "{name}: refused {action}{who} ({reason})",
}

DENY_REASONS = {
    "automation_disabled": "automations are not allowed to arm or disarm",
    "in_alarm": "not allowed during an alarm, use the keypad",
    "not_allowed": "user is not allowed to do that",
    "outside_schedule": "outside the user's allowed time",
    "unknown_user": "unknown user",
    "anonymous_disabled": "no user given",
}


def normalize_sensors(hass: HomeAssistant, sensors: dict[str, dict]) -> None:
    """Give every sensor a zone type (sensors set up before zone types existed)."""
    registry = er.async_get(hass)
    for entity_id, sensor in sensors.items():
        if CONF_ZONE_TYPE in sensor:
            continue
        entry = registry.async_get(entity_id)
        device_class = (entry.device_class or entry.original_device_class) if entry else None
        if device_class is None and (state := hass.states.get(entity_id)):
            device_class = state.attributes.get("device_class")
        sensor[CONF_ZONE_TYPE] = zone_type_of(sensor, device_class)
        sensor.setdefault(CONF_CHIME, False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the PT Alarm panel."""
    async_add_entities([PTAlarmPanel(hass, entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_ARM,
        {
            vol.Required(ATTR_MODE): vol.In(
                [*ARM_MODES, *(m.removeprefix("armed_") for m in ARM_MODES), "stay"]
            ),
            vol.Optional(ATTR_CODE, default=""): cv.string,
            vol.Optional(ATTR_FORCE, default=False): cv.boolean,
            vol.Optional(ATTR_SKIP_DELAY, default=False): cv.boolean,
            vol.Optional(ATTR_USER): cv.string,
            vol.Optional(ATTR_SOURCE): cv.string,
        },
        "async_service_arm",
    )
    platform.async_register_entity_service(
        "disarm",
        {
            vol.Optional(ATTR_CODE, default=""): cv.string,
            vol.Optional(ATTR_USER): cv.string,
            vol.Optional(ATTR_SOURCE): cv.string,
        },
        "async_service_disarm",
    )


class PTAlarmPanel(AlarmControlPanelEntity, RestoreEntity):
    """A virtual alarm panel (one partition) driven by Home Assistant sensors."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the panel."""
        self._entry = entry
        self._cfg = merged_options(dict(entry.options))
        normalize_sensors(hass, self._cfg[CONF_SENSORS])
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model="Virtual alarm panel",
            sw_version=VERSION,
        )

        self._state: AlarmControlPanelState = STATE.DISARMED
        self._arm_mode: str | None = None  # the armed mode we are in / heading to
        self._alarm_type: str | None = None  # burglary / fire / panic while triggered
        self._timer_unsub: Callable[[], None] | None = None
        self._lockout_unsub: Callable[[], None] | None = None
        self._expiration: datetime | None = None
        self._delay: int | None = None
        self._open_sensors: dict[str, str] = {}
        self._bypassed: list[str] = []
        self._troubles: dict[str, dict[str, Any]] = {}
        self._last_chime: dict[str, Any] | None = None
        self._triggered_by: str | None = None
        self._arm_user: dict | None = None  # user who started the current arming
        self._arm_label: str | None = None  # name shown for automation arming
        self._arm_source: str | None = None  # automation / access system that armed
        self._failed_attempts = 0
        self._locked_until: datetime | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def _modes(self) -> dict[str, dict]:
        return self._cfg[CONF_MODES]

    @property
    def _sensors(self) -> dict[str, dict]:
        return self._cfg[CONF_SENSORS]

    @property
    def _users(self) -> list[dict]:
        return self._cfg[CONF_USERS]

    def _zone(self, entity_id: str) -> str:
        return self._sensors[entity_id][CONF_ZONE_TYPE]

    @property
    def enabled_modes(self) -> list[str]:
        """Arm modes enabled in the configuration."""
        return [m for m in ARM_MODES if self._modes[m][CONF_ENABLED]]

    @property
    def bypassed(self) -> list[str]:
        """Sensors bypassed for the current arming."""
        return self._bypassed

    @property
    def triggered_by(self) -> str | None:
        """Sensor that caused the current entry delay or trigger."""
        return self._triggered_by

    @callback
    def async_write_ha_state(self) -> None:
        """Write state and let the zone sensors know."""
        super().async_write_ha_state()
        async_dispatcher_send(self.hass, signal_update(self._entry.entry_id))

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        """Return the current alarm state."""
        return self._state

    @property
    def supported_features(self) -> AlarmControlPanelEntityFeature:
        """Return the features supported by this panel."""
        features = AlarmControlPanelEntityFeature.TRIGGER
        for mode in self.enabled_modes:
            features |= MODE_TO_FEATURE[mode]
        return features

    @property
    def code_format(self) -> CodeFormat | None:
        """Return the code format shown in the UI keypad."""
        if not self._users:
            return None
        if not (
            self._cfg[CONF_CODE_ARM_REQUIRED]
            or self._cfg[CONF_CODE_DISARM_REQUIRED]
            or self._alarm_type == ALARM_FIRE
        ):
            return None
        if all(u.get(CONF_NUMERIC, True) for u in self._users):
            return CodeFormat.NUMBER
        return CodeFormat.TEXT

    @property
    def code_arm_required(self) -> bool:
        """Whether a code is needed to arm."""
        return bool(self._users) and self._cfg[CONF_CODE_ARM_REQUIRED]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Extra attributes used by the dashboard card and automations."""
        not_ready = self._not_ready_sensors()
        return {
            "arm_mode": self._arm_mode,
            "alarm_type": self._alarm_type,
            "supported_modes": self.enabled_modes,
            "code_disarm_required": bool(self._users)
            and (self._cfg[CONF_CODE_DISARM_REQUIRED] or self._alarm_type == ALARM_FIRE),
            "delay": self._delay,
            "expiration": self._expiration.isoformat() if self._expiration else None,
            "open_sensors": dict(self._open_sensors),
            "not_ready_sensors": not_ready,
            "ready_to_arm": not not_ready,
            "bypassed_sensors": list(self._bypassed),
            "troubles": dict(self._troubles),
            "last_chime": self._last_chime,
            "triggered_by": self._triggered_by,
            "locked_until": self._locked_until.isoformat() if self._locked_until else None,
            "sensor_count": len(self._sensors),
            "zones": {
                entity_id: {
                    "name": self._friendly(entity_id),
                    "type": sensor.get(CONF_TYPE),
                    "zone_type": sensor.get(CONF_ZONE_TYPE),
                    "location": self._location(entity_id),
                }
                for entity_id, sensor in self._sensors.items()
            },
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def async_added_to_hass(self) -> None:
        """Restore state and start listening to sensors."""
        await super().async_added_to_hass()
        self.hass.data.setdefault(DOMAIN, {})[self._entry.entry_id] = self

        if self._sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, list(self._sensors), self._async_sensor_changed
                )
            )
        for entity_id, sensor in self._sensors.items():
            state = self.hass.states.get(entity_id)
            if state and self._is_open(sensor, state):
                self._open_sensors[entity_id] = state.state
                if self._zone(entity_id) in TROUBLE_ZONES:
                    self._troubles[entity_id] = self._trouble_info(entity_id)

        last = await self.async_get_last_state()
        if last is None:
            return
        attrs = last.attributes
        mode = attrs.get("arm_mode")
        if mode in self.enabled_modes and last.state in {
            *(s.value for s in ARMED_STATES),
            STATE.ARMING.value,
            STATE.PENDING.value,
            STATE.TRIGGERED.value,
        }:
            # Never resume a countdown or a siren after a restart: go back to armed.
            self._arm_mode = mode
            self._state = MODE_TO_STATE[mode]
            self._bypassed = [
                e for e in attrs.get("bypassed_sensors", []) if e in self._sensors
            ]
            _LOGGER.debug("%s restored to %s", self.entity_id, self._state)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up timers."""
        self.hass.data.get(DOMAIN, {}).pop(self._entry.entry_id, None)
        self._cancel_timer()
        if self._lockout_unsub:
            self._lockout_unsub()
            self._lockout_unsub = None
        await super().async_will_remove_from_hass()

    # ------------------------------------------------------------------
    # Service handlers
    # ------------------------------------------------------------------
    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Disarm the alarm (also resets a fire alarm and clears all bypasses)."""
        fire = self._alarm_type == ALARM_FIRE
        user = await self._async_validate_code(
            code, disarm=True, required=True if fire and self._users else None
        )
        await self._async_do_disarm(user)

    async def _async_do_disarm(
        self, user: dict | None, label: str | None = None, source: str | None = None
    ) -> None:
        fire = self._alarm_type == ALARM_FIRE
        self._cancel_timer()
        self._arm_mode = None
        self._alarm_type = None
        self._bypassed = []
        self._triggered_by = None
        self._set_state(STATE.DISARMED, user)
        if label and user is None:
            self._attr_changed_by = label
            self.async_write_ha_state()
        await self._async_sirens(False)
        self._fire(
            EVENT_DISARMED,
            user=user,
            user_label=label,
            source=source,
            reason="fire_reset" if fire else None,
        )

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Arm away."""
        await self._async_arm(MODE_AWAY, code)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Arm stay."""
        await self._async_arm(MODE_HOME, code)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Arm night."""
        await self._async_arm(MODE_NIGHT, code)

    async def async_alarm_arm_vacation(self, code: str | None = None) -> None:
        """Arm vacation."""
        await self._async_arm(MODE_VACATION, code)

    async def async_alarm_arm_custom_bypass(self, code: str | None = None) -> None:
        """Arm custom bypass."""
        await self._async_arm(MODE_CUSTOM, code)

    async def async_alarm_trigger(self, code: str | None = None) -> None:
        """Manually trigger the alarm (panic)."""
        await self._async_validate_code(code, disarm=False, required=False)
        self._trigger(None, ALARM_PANIC)

    async def async_service_arm(
        self,
        mode: str,
        code: str = "",
        force: bool = False,
        skip_delay: bool = False,
        user: str | None = None,
        source: str | None = None,
    ) -> None:
        """Handle the pt_alarm.arm service (keypad, scripts, automations, access control)."""
        if mode == "stay":
            mode = MODE_HOME
        if not mode.startswith("armed_"):
            mode = f"armed_{mode}"
        src = self._call_source(source)
        if code or not (user or src):
            await self._async_arm(mode, code, force=force, skip_delay=skip_delay, source=src)
            return
        pt_user, label = self._authorize_automation("arm", user, src)
        await self._async_arm(
            mode,
            None,
            force=force,
            skip_delay=skip_delay,
            automation=True,
            pt_user=pt_user,
            label=label,
            source=src,
        )

    async def async_service_disarm(
        self, code: str = "", user: str | None = None, source: str | None = None
    ) -> None:
        """Handle the pt_alarm.disarm service (keypad, scripts, automations, access control)."""
        src = self._call_source(source)
        if code or not (user or src):
            fire = self._alarm_type == ALARM_FIRE
            pt_user = await self._async_validate_code(
                code, disarm=True, required=True if fire and self._users else None
            )
            await self._async_do_disarm(pt_user, source=src)
            return
        pt_user, label = self._authorize_automation("disarm", user, src)
        await self._async_do_disarm(pt_user, label, src)

    # ------------------------------------------------------------------
    # Automations and access control
    # ------------------------------------------------------------------
    def _call_source(self, source: str | None) -> str | None:
        """Text for the log: given source, else the automation/script that called us."""
        if source:
            return source
        if self._context is None:
            return None
        return self.hass.data.get(DATA_CONTEXT_SOURCES, {}).get(self._context.id)

    def _find_user(self, ident: str) -> dict | None:
        """Find a PT user by name or by one of their access IDs."""
        wanted = ident.strip().lower()
        for user in self._users:
            names = [user.get(CONF_USER_NAME, ""), *(user.get(CONF_ACCESS_IDS) or [])]
            if any(str(n).strip().lower() == wanted for n in names if n):
                return user
        return None

    def _authorize_automation(
        self, action: str, ident: str | None, source: str | None
    ) -> tuple[dict | None, str | None]:
        """Check an arm/disarm request from an automation. Returns (PT user, name to show)."""

        def deny(reason: str, key: str, **placeholders: str) -> None:
            self._fire(
                EVENT_ACCESS_DENIED,
                action=action,
                reason=reason,
                user_label=ident,
                source=source,
            )
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=key,
                translation_placeholders=placeholders or None,
            )

        if not self._cfg[CONF_AUTOMATION_ALLOWED]:
            deny("automation_disabled", "automation_disabled")
        if action == "disarm" and self._state == STATE.TRIGGERED:
            deny("in_alarm", "automation_in_alarm")

        pt_user = self._find_user(ident) if ident else None
        if pt_user is not None:
            if not pt_user.get(CONF_CAN_DISARM if action == "disarm" else CONF_CAN_ARM, True):
                deny("not_allowed", "not_allowed")
            if not user_allowed_now(pt_user, dt_util.now()) or self._blocked(pt_user):
                deny("outside_schedule", "outside_schedule", user=pt_user.get(CONF_USER_NAME, ""))
            return pt_user, pt_user.get(CONF_USER_NAME)

        # Not a PT user: trust the access system / automation only if allowed.
        if action == "disarm" and not self._cfg[CONF_AUTOMATION_ANONYMOUS]:
            if ident:
                deny("unknown_user", "automation_unknown_user", user=ident)
            deny("anonymous_disabled", "automation_anonymous")
        return None, ident

    # ------------------------------------------------------------------
    # Arming / disarming logic
    # ------------------------------------------------------------------
    async def _async_arm(
        self,
        mode: str,
        code: str | None,
        force: bool = False,
        skip_delay: bool = False,
        automation: bool = False,
        pt_user: dict | None = None,
        label: str | None = None,
        source: str | None = None,
    ) -> None:
        if mode not in self.enabled_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="mode_not_enabled",
                translation_placeholders={"mode": mode_label(mode)},
            )
        if self._state == STATE.TRIGGERED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="disarm_first"
            )

        blocking = self._blocking_sensors(mode)
        if automation:
            user = pt_user
            # The installer chooses: refuse, or bypass the open zones and notify.
            if self._cfg[CONF_AUTOMATION_OPEN_ZONES] == OPEN_ZONES_BYPASS:
                force = True
        else:
            # Bypassing open zones by hand needs a user with the bypass permission.
            manual_bypass = bool(blocking) and force and not self._cfg[CONF_AUTO_BYPASS]
            user = await self._async_validate_code(
                code, disarm=False, required=True if manual_bypass and self._users else None
            )
            if manual_bypass and user is not None and not user.get(CONF_CAN_BYPASS, True):
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="bypass_not_allowed"
                )

        if blocking and not (force or self._cfg[CONF_AUTO_BYPASS]):
            names = ", ".join(self._friendly(e) for e in blocking)
            self._fire(
                EVENT_FAILED_TO_ARM,
                user=user,
                user_label=label,
                source=source,
                mode=mode,
                sensors=blocking,
                sensor_names=names,
            )
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="open_sensors",
                translation_placeholders={"sensors": names},
            )

        self._cancel_timer()
        was_armed = self._state in ARMED_STATES
        self._arm_mode = mode
        self._bypassed = blocking
        self._triggered_by = None
        self._arm_user = user
        self._arm_label = label
        self._arm_source = source
        if label and user is None:
            self._attr_changed_by = label

        exit_time = 0 if (skip_delay or was_armed) else int(self._modes[mode][CONF_EXIT_TIME])
        if exit_time > 0:
            self._start_timer(exit_time, self._arming_done)
            self._set_state(STATE.ARMING, user)
            self._fire(
                EVENT_ARMING, mode=mode, delay=exit_time, user=user, user_label=label, source=source
            )
        else:
            self._complete_arm(user)

    @callback
    def _arming_done(self, _now: datetime) -> None:
        self._timer_unsub = None
        self._complete_arm(self._arm_user)

    @callback
    def _complete_arm(self, user: dict | None) -> None:
        assert self._arm_mode is not None
        self._clear_delay()
        self._set_state(MODE_TO_STATE[self._arm_mode], user)
        self._fire(
            EVENT_ARMED,
            mode=self._arm_mode,
            user=user,
            user_label=self._arm_label,
            source=self._arm_source,
            bypassed=list(self._bypassed),
            bypassed_names=[self._friendly(e) for e in self._bypassed],
        )
        self._arm_label = None
        self._arm_source = None
        # A zone left open at the end of the exit delay is treated as just opened.
        for entity_id in list(self._open_sensors):
            if self._state not in ARMED_STATES:
                break
            if self._zone(entity_id) not in TROUBLE_ZONES:
                self._evaluate(entity_id)

    # ------------------------------------------------------------------
    # Sensor handling
    # ------------------------------------------------------------------
    def _is_open(self, sensor: dict, state: State | None) -> bool:
        if state is None:
            return False
        value = str(state.state).lower()
        if value in UNAVAILABLE_STATES:
            return bool(sensor.get(CONF_TRIGGER_UNAVAILABLE))
        return value in OPEN_STATES

    def _not_ready_sensors(self) -> list[str]:
        """Open zones that block at least one enabled arm mode."""
        result: list[str] = []
        for mode in self.enabled_modes:
            for entity_id in self._blocking_sensors(mode):
                if entity_id not in result:
                    result.append(entity_id)
        return result

    def _blocking_sensors(self, mode: str) -> list[str]:
        """Open entry/exit and perimeter zones that prevent arming in this mode."""
        return [
            entity_id
            for entity_id in self._open_sensors
            if entity_id in self._sensors
            and self._zone(entity_id) in BLOCKING_ZONES
            and zone_armed_in(self._zone(entity_id), mode)
        ]

    @callback
    def _async_sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        sensor = self._sensors.get(entity_id)
        if sensor is None:
            return
        new_state = event.data["new_state"]
        old_state = event.data["old_state"]
        is_open = self._is_open(sensor, new_state)
        was_open = entity_id in self._open_sensors
        # A sensor coming back online (e.g. after a restart) is not an "opening".
        came_online = (
            old_state is None or str(old_state.state).lower() in UNAVAILABLE_STATES
        ) and not sensor.get(CONF_TRIGGER_UNAVAILABLE)

        if is_open:
            self._open_sensors[entity_id] = new_state.state  # type: ignore[union-attr]
        else:
            self._open_sensors.pop(entity_id, None)

        if is_open and not was_open:
            if self._zone(entity_id) in TROUBLE_ZONES:
                self._add_trouble(entity_id)
            elif not came_online:
                self._chime(entity_id)
                self._evaluate(entity_id)
        elif was_open and not is_open and entity_id in self._troubles:
            self._clear_trouble(entity_id)
        self.async_write_ha_state()

    @callback
    def _evaluate(self, entity_id: str) -> None:
        """Decide what an opened zone means in the current state."""
        zone_type = self._zone(entity_id)

        if zone_type in TROUBLE_ZONES:
            self._add_trouble(entity_id)
            return
        if zone_type == ZT_FIRE:
            # Fire has priority over everything and works in every state.
            if self._alarm_type != ALARM_FIRE:
                self._trigger(entity_id, ALARM_FIRE)
            return
        if zone_type == ZT_PANIC:
            if self._state != STATE.TRIGGERED:
                self._trigger(entity_id, ALARM_PANIC)
            return

        # Burglary zones
        if self._state in (STATE.DISARMED, STATE.ARMING, STATE.TRIGGERED):
            return
        if not zone_armed_in(zone_type, self._arm_mode) or entity_id in self._bypassed:
            return

        if self._state == STATE.PENDING:
            # Entry/exit zones and interior followers follow the running entry delay;
            # perimeter and interior zones go into alarm right away.
            if zone_type in (ZT_ENTRY_EXIT_1, ZT_ENTRY_EXIT_2, ZT_INTERIOR_FOLLOWER):
                return
            self._trigger(entity_id, ALARM_BURGLARY)
            return

        delay_key = ENTRY_DELAY_ZONES.get(zone_type)
        instant = bool(self._modes[self._arm_mode].get(CONF_INSTANT))
        entry_time = int(self._cfg.get(delay_key, 0)) if delay_key and not instant else 0
        if entry_time <= 0:
            self._trigger(entity_id, ALARM_BURGLARY)
            return

        self._triggered_by = entity_id
        self._start_timer(entry_time, self._entry_done)
        self._set_state(STATE.PENDING)
        self._fire(
            EVENT_PENDING,
            mode=self._arm_mode,
            delay=entry_time,
            sensor=entity_id,
            sensor_name=self._friendly(entity_id),
            sensor_location=self._location(entity_id),
        )

    @callback
    def _entry_done(self, _now: datetime) -> None:
        self._timer_unsub = None
        self._trigger(self._triggered_by, ALARM_BURGLARY)

    @callback
    def _trigger(self, entity_id: str | None, alarm_type: str = ALARM_BURGLARY) -> None:
        self._cancel_timer()
        self._triggered_by = entity_id
        self._alarm_type = alarm_type
        # A fire alarm keeps sounding until it is reset with a code.
        if alarm_type != ALARM_FIRE:
            trigger_time = int(self._modes[self._arm_mode or MODE_AWAY][CONF_TRIGGER_TIME])
            if trigger_time > 0:
                self._start_timer(trigger_time, self._trigger_done)
        self._set_state(STATE.TRIGGERED)
        self.hass.async_create_task(self._async_sirens(True))
        self._fire(
            EVENT_TRIGGERED,
            mode=self._arm_mode,
            alarm_type=alarm_type,
            sensor=entity_id,
            sensor_name=self._friendly(entity_id) if entity_id else "manual trigger",
            sensor_location=self._location(entity_id),
        )

    @callback
    def _trigger_done(self, _now: datetime) -> None:
        """Trigger time elapsed: re-arm (or disarm) and silence the sirens."""
        self._timer_unsub = None
        self._alarm_type = None
        self.hass.async_create_task(self._async_sirens(False))
        if self._arm_mode is None or self._cfg[CONF_DISARM_AFTER_TRIGGER]:
            self._arm_mode = None
            self._bypassed = []
            self._set_state(STATE.DISARMED)
            self._fire(EVENT_DISARMED, reason="trigger_time_elapsed")
            return
        # Re-arm, bypassing whatever is still open so we don't loop forever.
        for entity_id in self._open_sensors:
            if entity_id not in self._bypassed and self._zone(entity_id) not in TROUBLE_ZONES:
                self._bypassed.append(entity_id)
        self._clear_delay()
        self._set_state(MODE_TO_STATE[self._arm_mode])
        self._fire(EVENT_ARMED, mode=self._arm_mode, reason="trigger_time_elapsed")

    # ------------------------------------------------------------------
    # Troubles and chime
    # ------------------------------------------------------------------
    def _trouble_info(self, entity_id: str) -> dict[str, Any]:
        return {
            "name": self._friendly(entity_id),
            "zone_type": self._zone(entity_id),
            "location": self._location(entity_id),
            "since": dt_util.utcnow().isoformat(),
        }

    @callback
    def _add_trouble(self, entity_id: str) -> None:
        if entity_id in self._troubles:
            return
        self._troubles[entity_id] = self._trouble_info(entity_id)
        self._fire(
            EVENT_TROUBLE,
            zone_type=self._zone(entity_id),
            sensor=entity_id,
            sensor_name=self._friendly(entity_id),
            sensor_location=self._location(entity_id),
        )

    @callback
    def _clear_trouble(self, entity_id: str) -> None:
        self._troubles.pop(entity_id, None)
        self._fire(
            EVENT_TROUBLE_RESTORED,
            zone_type=self._zone(entity_id),
            sensor=entity_id,
            sensor_name=self._friendly(entity_id),
            sensor_location=self._location(entity_id),
        )

    @callback
    def _chime(self, entity_id: str) -> None:
        """Door chime: only while disarmed, only for zones with chime enabled."""
        if self._state != STATE.DISARMED or not self._sensors[entity_id].get(CONF_CHIME):
            return
        self._last_chime = {
            "entity_id": entity_id,
            "name": self._friendly(entity_id),
            "time": dt_util.utcnow().isoformat(),
        }
        self._fire(EVENT_CHIME, sensor=entity_id, sensor_name=self._friendly(entity_id))

    # ------------------------------------------------------------------
    # Codes
    # ------------------------------------------------------------------
    async def _async_validate_code(
        self, code: str | None, disarm: bool, required: bool | None = None
    ) -> dict | None:
        """Validate a code. Returns the matching user (or None if not needed)."""
        if not self._users:
            return None
        if required is None:
            required = self._cfg[
                CONF_CODE_DISARM_REQUIRED if disarm else CONF_CODE_ARM_REQUIRED
            ]
        if not code:
            if required:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="code_required"
                )
            return None

        if self._locked_until and dt_util.utcnow() < self._locked_until:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="locked_out",
                translation_placeholders={
                    "seconds": str(int((self._locked_until - dt_util.utcnow()).total_seconds()))
                },
            )

        permission = CONF_CAN_DISARM if disarm else CONF_CAN_ARM
        for user in self._users:
            if await self.hass.async_add_executor_job(check_code, user, code):
                if not user.get(permission, True):
                    raise ServiceValidationError(
                        translation_domain=DOMAIN, translation_key="not_allowed"
                    )
                if not user_allowed_now(user, dt_util.now()) or self._blocked(user):
                    self._fire(EVENT_INVALID_CODE, user=user, reason="outside_schedule")
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="outside_schedule",
                        translation_placeholders={"user": user.get(CONF_USER_NAME, "")},
                    )
                self._failed_attempts = 0
                return user

        if not required:
            # Code was optional; a wrong one is ignored.
            return None

        self._failed_attempts += 1
        self._fire(EVENT_INVALID_CODE, attempts=self._failed_attempts)
        max_attempts = int(self._cfg[CONF_MAX_ATTEMPTS])
        if max_attempts and self._failed_attempts >= max_attempts:
            lockout = int(self._cfg[CONF_LOCKOUT_TIME])
            self._failed_attempts = 0
            if lockout > 0:
                self._locked_until = dt_util.utcnow() + timedelta(seconds=lockout)
                if self._lockout_unsub:
                    self._lockout_unsub()
                self._lockout_unsub = async_call_later(self.hass, lockout, self._lockout_done)
                self._fire(EVENT_LOCKED_OUT, seconds=lockout)
                self.async_write_ha_state()
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_code"
        )

    def _blocked(self, user: dict) -> bool:
        """True while any of the user's 'not allowed while' entities is on."""
        for entity_id in user.get(CONF_BLOCKED_BY) or []:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state == "on":
                return True
        return False

    @callback
    def _lockout_done(self, _now: datetime) -> None:
        self._lockout_unsub = None
        self._locked_until = None
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _start_timer(self, seconds: int, action: Callable[[datetime], None]) -> None:
        self._cancel_timer()
        self._delay = seconds
        self._expiration = dt_util.utcnow() + timedelta(seconds=seconds)
        self._timer_unsub = async_call_later(self.hass, seconds, action)

    def _cancel_timer(self) -> None:
        if self._timer_unsub:
            self._timer_unsub()
            self._timer_unsub = None
        self._clear_delay()

    def _clear_delay(self) -> None:
        self._delay = None
        self._expiration = None

    @callback
    def _set_state(self, state: AlarmControlPanelState, user: dict | None = None) -> None:
        self._state = state
        if user is not None:
            self._attr_changed_by = user.get(CONF_USER_NAME)
        if state in (STATE.DISARMED, *ARMED_STATES) and self._timer_unsub is None:
            self._clear_delay()
        self.async_write_ha_state()

    def _location(self, entity_id: str | None) -> str | None:
        area_id = self._sensors.get(entity_id or "", {}).get(CONF_AREA)
        area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
        return area.name if area else None

    def _friendly(self, entity_id: str | None) -> str:
        if not entity_id:
            return ""
        if custom := (self._sensors.get(entity_id, {}).get(CONF_SENSOR_NAME) or "").strip():
            return custom
        state = self.hass.states.get(entity_id)
        if state and state.name:
            return state.name
        return entity_id

    async def _async_sirens(self, turn_on: bool) -> None:
        entities = self._cfg[CONF_SIREN_ENTITIES]
        if not entities:
            return
        try:
            await self.hass.services.async_call(
                "homeassistant",
                "turn_on" if turn_on else "turn_off",
                {ATTR_ENTITY_ID: entities},
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to switch sirens %s", "on" if turn_on else "off")

    @callback
    def _fire(
        self,
        event_type: str,
        user: dict | None = None,
        user_label: str | None = None,
        **data: Any,
    ) -> None:
        payload = {
            ATTR_ENTITY_ID: self.entity_id,
            "name": self._entry.title,
            "event": event_type,
            "state": self._state.value,
            "user": user.get(CONF_USER_NAME) if user else user_label,
            **data,
        }
        # Link the entry to the Home Assistant login that pressed the button.
        self.hass.bus.async_fire(EVENT, payload, context=self._context)

        categories = categories_for(event_type, data)
        if not categories or event_type not in EVENT_MESSAGES:
            return
        if not (self._cfg.get(CONF_EMAIL_SERVICES) or self._cfg.get(CONF_PUSH_SERVICES)):
            return
        sensor = data.get("sensor_name") or data.get("sensor") or ""
        if data.get("sensor_location"):
            sensor = f"{sensor} in {data['sensor_location']}"
        template = EVENT_MESSAGES[event_type]
        if event_type == EVENT_TRIGGERED and data.get("alarm_type") in (ALARM_FIRE, ALARM_PANIC):
            template = EVENT_MESSAGES[f"triggered_{data['alarm_type']}"]
        who_name = payload["user"]
        source = data.get("source")
        who = (
            f" by {who_name} via {source}"
            if who_name and source
            else f" by {who_name}"
            if who_name
            else f" by {source}"
            if source
            else ""
        )
        message = template.format(
            name=self._entry.title,
            mode=mode_label(data.get("mode")),
            delay=data.get("delay", ""),
            sensor=sensor,
            sensors=data.get("sensor_names", ""),
            action=data.get("action", ""),
            who=who,
            reason=DENY_REASONS.get(data.get("reason", ""), data.get("reason", "")),
        )
        if event_type != EVENT_ACCESS_DENIED:
            message += who
        if data.get("bypassed_names"):
            message += ". Bypassed: " + ", ".join(data["bypassed_names"])
        self.hass.async_create_task(
            async_send(
                self.hass,
                self._cfg,
                self._entry.title,
                categories,
                {**data, "user": who_name},
                message,
            )
        )
