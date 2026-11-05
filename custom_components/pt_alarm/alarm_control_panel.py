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
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.util.dt as dt_util

from .const import (
    ARM_MODES,
    ATTR_CODE,
    ATTR_FORCE,
    ATTR_MODE,
    ATTR_SKIP_DELAY,
    CONF_ALLOW_OPEN,
    CONF_ALWAYS_ON,
    CONF_AUTO_BYPASS,
    CONF_BLOCKED_BY,
    CONF_CAN_ARM,
    CONF_CAN_BYPASS,
    CONF_CAN_DISARM,
    CONF_CODE_ARM_REQUIRED,
    CONF_CODE_DISARM_REQUIRED,
    CONF_DISARM_AFTER_TRIGGER,
    CONF_ENABLED,
    CONF_ENTRY_TIME,
    CONF_EXIT_TIME,
    CONF_IMMEDIATE,
    CONF_LOCKOUT_TIME,
    CONF_MAX_ATTEMPTS,
    CONF_MODES,
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_SERVICES,
    CONF_NUMERIC,
    CONF_SENSOR_MODES,
    CONF_SENSORS,
    CONF_SIREN_ENTITIES,
    CONF_TRIGGER_TIME,
    CONF_TRIGGER_UNAVAILABLE,
    CONF_USER_NAME,
    CONF_USERS,
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
    MANUFACTURER,
    MODE_AWAY,
    MODE_CUSTOM,
    MODE_HOME,
    MODE_NIGHT,
    MODE_VACATION,
    OPEN_STATES,
    SERVICE_ARM,
    UNAVAILABLE_STATES,
    VERSION,
    signal_update,
)
from .helpers import check_code, merged_options, user_allowed_now

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
    EVENT_FAILED_TO_ARM: "{name} could not be armed, open sensors: {sensors}",
    EVENT_INVALID_CODE: "{name}: an invalid code was entered",
    EVENT_LOCKED_OUT: "{name}: too many invalid codes, keypad locked",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the PT Alarm panel."""
    async_add_entities([PTAlarmPanel(entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_ARM,
        {
            vol.Required(ATTR_MODE): vol.In(ARM_MODES + [m.removeprefix("armed_") for m in ARM_MODES]),
            vol.Optional(ATTR_CODE, default=""): cv.string,
            vol.Optional(ATTR_FORCE, default=False): cv.boolean,
            vol.Optional(ATTR_SKIP_DELAY, default=False): cv.boolean,
        },
        "async_service_arm",
    )


class PTAlarmPanel(AlarmControlPanelEntity, RestoreEntity):
    """A virtual alarm panel driven by Home Assistant sensors."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the panel."""
        self._entry = entry
        self._cfg = merged_options(dict(entry.options))
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
        self._timer_unsub: Callable[[], None] | None = None
        self._lockout_unsub: Callable[[], None] | None = None
        self._expiration: datetime | None = None
        self._delay: int | None = None
        self._open_sensors: dict[str, str] = {}
        self._bypassed: list[str] = []
        self._triggered_by: str | None = None
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
        if not (self._cfg[CONF_CODE_ARM_REQUIRED] or self._cfg[CONF_CODE_DISARM_REQUIRED]):
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
        return {
            "arm_mode": self._arm_mode,
            "supported_modes": self.enabled_modes,
            "code_disarm_required": bool(self._users)
            and self._cfg[CONF_CODE_DISARM_REQUIRED],
            "delay": self._delay,
            "expiration": self._expiration.isoformat() if self._expiration else None,
            "open_sensors": dict(self._open_sensors),
            "bypassed_sensors": list(self._bypassed),
            "triggered_by": self._triggered_by,
            "locked_until": self._locked_until.isoformat() if self._locked_until else None,
            "sensor_count": len(self._sensors),
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
        """Disarm the alarm."""
        user = await self._async_validate_code(code, disarm=True)
        self._cancel_timer()
        self._arm_mode = None
        self._bypassed = []
        self._triggered_by = None
        self._set_state(STATE.DISARMED, user)
        await self._async_sirens(False)
        self._fire(EVENT_DISARMED, user=user)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Arm away."""
        await self._async_arm(MODE_AWAY, code)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Arm home."""
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
        self._trigger(None)

    async def async_service_arm(
        self, mode: str, code: str = "", force: bool = False, skip_delay: bool = False
    ) -> None:
        """Handle the pt_alarm.arm service."""
        if not mode.startswith("armed_"):
            mode = f"armed_{mode}"
        await self._async_arm(mode, code, force=force, skip_delay=skip_delay)

    # ------------------------------------------------------------------
    # Arming / disarming logic
    # ------------------------------------------------------------------
    async def _async_arm(
        self,
        mode: str,
        code: str | None,
        force: bool = False,
        skip_delay: bool = False,
    ) -> None:
        if mode not in self.enabled_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="mode_not_enabled",
                translation_placeholders={"mode": mode},
            )
        if self._state == STATE.TRIGGERED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="disarm_first"
            )

        blocking = self._blocking_sensors(mode)
        # Bypassing open sensors by hand needs a user with the bypass permission.
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
            self._fire(EVENT_FAILED_TO_ARM, mode=mode, sensors=blocking, sensor_names=names)
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

        exit_time = 0 if (skip_delay or was_armed) else int(self._modes[mode][CONF_EXIT_TIME])
        if exit_time > 0:
            self._start_timer(exit_time, self._arming_done)
            self._set_state(STATE.ARMING, user)
            self._fire(EVENT_ARMING, mode=mode, delay=exit_time, user=user)
        else:
            self._complete_arm(user)

    @callback
    def _arming_done(self, _now: datetime) -> None:
        self._timer_unsub = None
        self._complete_arm(None)

    @callback
    def _complete_arm(self, user: dict | None) -> None:
        assert self._arm_mode is not None
        self._clear_delay()
        self._set_state(MODE_TO_STATE[self._arm_mode], user)
        self._fire(EVENT_ARMED, mode=self._arm_mode, user=user, bypassed=self._bypassed)
        # A sensor left open at the end of the exit delay starts the entry delay.
        for entity_id in list(self._open_sensors):
            if self._state not in ARMED_STATES:
                break
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

    def _blocking_sensors(self, mode: str) -> list[str]:
        """Open sensors that would prevent arming in the given mode."""
        return [
            entity_id
            for entity_id in self._open_sensors
            if (sensor := self._sensors.get(entity_id))
            and mode in sensor.get(CONF_SENSOR_MODES, [])
            and not sensor.get(CONF_ALWAYS_ON)
            and not sensor.get(CONF_ALLOW_OPEN)
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

        if is_open and not was_open and not came_online:
            self._evaluate(entity_id)
        self.async_write_ha_state()

    @callback
    def _evaluate(self, entity_id: str) -> None:
        """Decide what an opened sensor means in the current state."""
        sensor = self._sensors[entity_id]

        if sensor.get(CONF_ALWAYS_ON):
            if self._state != STATE.TRIGGERED:
                self._trigger(entity_id)
            return

        if self._state in (STATE.DISARMED, STATE.ARMING, STATE.TRIGGERED):
            return
        if self._arm_mode not in sensor.get(CONF_SENSOR_MODES, []):
            return
        if entity_id in self._bypassed:
            return

        entry_time = int(self._modes[self._arm_mode][CONF_ENTRY_TIME])
        if self._state == STATE.PENDING:
            if sensor.get(CONF_IMMEDIATE):
                self._trigger(entity_id)
            return

        if sensor.get(CONF_IMMEDIATE) or entry_time <= 0:
            self._trigger(entity_id)
        else:
            self._triggered_by = entity_id
            self._start_timer(entry_time, self._entry_done)
            self._set_state(STATE.PENDING)
            self._fire(
                EVENT_PENDING,
                mode=self._arm_mode,
                delay=entry_time,
                sensor=entity_id,
                sensor_name=self._friendly(entity_id),
            )

    @callback
    def _entry_done(self, _now: datetime) -> None:
        self._timer_unsub = None
        self._trigger(self._triggered_by)

    @callback
    def _trigger(self, entity_id: str | None) -> None:
        self._cancel_timer()
        self._triggered_by = entity_id
        # Always-on sensor or panic while disarmed uses the away trigger time.
        trigger_time = int(self._modes[self._arm_mode or MODE_AWAY][CONF_TRIGGER_TIME])
        if trigger_time > 0:
            self._start_timer(trigger_time, self._trigger_done)
        self._set_state(STATE.TRIGGERED)
        self.hass.async_create_task(self._async_sirens(True))
        self._fire(
            EVENT_TRIGGERED,
            mode=self._arm_mode,
            sensor=entity_id,
            sensor_name=self._friendly(entity_id) if entity_id else "manual trigger",
        )

    @callback
    def _trigger_done(self, _now: datetime) -> None:
        """Trigger time elapsed: re-arm (or disarm) and silence the sirens."""
        self._timer_unsub = None
        self.hass.async_create_task(self._async_sirens(False))
        if self._arm_mode is None or self._cfg[CONF_DISARM_AFTER_TRIGGER]:
            self._arm_mode = None
            self._bypassed = []
            self._set_state(STATE.DISARMED)
            self._fire(EVENT_DISARMED, reason="trigger_time_elapsed")
            return
        # Re-arm, bypassing whatever is still open so we don't loop forever.
        for entity_id in self._open_sensors:
            if entity_id not in self._bypassed:
                self._bypassed.append(entity_id)
        self._clear_delay()
        self._set_state(MODE_TO_STATE[self._arm_mode])
        self._fire(EVENT_ARMED, mode=self._arm_mode, reason="trigger_time_elapsed")

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

    def _friendly(self, entity_id: str | None) -> str:
        if not entity_id:
            return ""
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
    def _fire(self, event_type: str, user: dict | None = None, **data: Any) -> None:
        payload = {
            ATTR_ENTITY_ID: self.entity_id,
            "name": self._entry.title,
            "event": event_type,
            "state": self._state.value,
            "user": user.get(CONF_USER_NAME) if user else None,
            **data,
        }
        self.hass.bus.async_fire(EVENT, payload)

        if event_type not in self._cfg[CONF_NOTIFY_EVENTS]:
            return
        services = self._cfg[CONF_NOTIFY_SERVICES]
        if not services:
            return
        message = EVENT_MESSAGES[event_type].format(
            name=self._entry.title,
            mode=str(data.get("mode") or "").replace("armed_", "").replace("_", " "),
            delay=data.get("delay", ""),
            sensor=data.get("sensor_name") or data.get("sensor") or "",
            sensors=data.get("sensor_names", ""),
        )
        if user:
            message += f" by {user.get(CONF_USER_NAME)}"
        self.hass.async_create_task(self._async_notify(services, message))

    async def _async_notify(self, services: list[str], message: str) -> None:
        for service in services:
            domain, _, name = service.partition(".")
            if not name:
                domain, name = "notify", service
            try:
                await self.hass.services.async_call(
                    domain,
                    name,
                    {"title": self._entry.title, "message": message},
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("PT Alarm could not notify via %s.%s", domain, name)
