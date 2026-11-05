"""Config and options flow for PT Alarm."""

from __future__ import annotations

import copy
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    ARM_MODES,
    BLOCKING_DOMAINS,
    CONF_ALLOW_OPEN,
    CONF_ALWAYS_ON,
    CONF_AUTO_BYPASS,
    CONF_BLOCKED_BY,
    CONF_CAN_ARM,
    CONF_CAN_BYPASS,
    CONF_CAN_DISARM,
    CONF_CODE,
    CONF_CODE_ARM_REQUIRED,
    CONF_CODE_DISARM_REQUIRED,
    CONF_DAYS,
    CONF_DISARM_AFTER_TRIGGER,
    CONF_ENABLED,
    CONF_END_TIME,
    CONF_ENTRY_TIME,
    CONF_EXIT_TIME,
    CONF_IMMEDIATE,
    CONF_LOCKOUT_TIME,
    CONF_MAX_ATTEMPTS,
    CONF_MODES,
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_SERVICES,
    CONF_SENSOR_MODES,
    CONF_SENSORS,
    CONF_SIREN_ENTITIES,
    CONF_START_TIME,
    CONF_TRIGGER_TIME,
    CONF_TRIGGER_UNAVAILABLE,
    CONF_TYPE,
    CONF_USER_ID,
    CONF_USER_NAME,
    CONF_USERS,
    CONF_VALID_FROM,
    CONF_VALID_UNTIL,
    DEFAULT_END_TIME,
    DEFAULT_OPTIONS,
    DEFAULT_START_TIME,
    DEVICE_CLASS_TYPES,
    DOMAIN,
    NAME,
    NOTIFY_EVENTS,
    SENSOR_DOMAINS,
    SENSOR_OTHER,
    SENSOR_TYPE_DEFAULTS,
    SENSOR_TYPES,
    WEEKDAYS,
)
from .helpers import hash_code, merged_options, schedule_text

CONF_NAME = "name"
CONF_ENTITIES = "entities"
CONF_ENTITY = "entity"
CONF_MODE = "mode"
CONF_USER = "user"
CONF_FIRST_USER = "user_name"

MIN_CODE_LENGTH = 4


# ---------------------------------------------------------------------------
# Selectors and schema helpers
# ---------------------------------------------------------------------------
def _seconds(max_value: int = 3600) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=max_value,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


def _select(options: list[str], key: str, multiple: bool = False) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            translation_key=key,
            multiple=multiple,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _code_selector() -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


def _validate_code(code: str) -> str | None:
    if len(code) < MIN_CODE_LENGTH:
        return "code_too_short"
    return None


def _sensor_picker(exclude: list[str], required: bool = True) -> vol.Schema:
    key = vol.Required(CONF_ENTITIES) if required else vol.Optional(CONF_ENTITIES, default=[])
    return vol.Schema(
        {
            key: selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=SENSOR_DOMAINS, multiple=True, exclude_entities=exclude
                )
            )
        }
    )


def _guess_type(hass: HomeAssistant, entity_id: str) -> str:
    """Guess a sensor type from the entity's device class."""
    state = hass.states.get(entity_id)
    device_class = str(state.attributes.get("device_class", "")) if state else ""
    if entity_id.startswith("lock."):
        return DEVICE_CLASS_TYPES["lock"]
    return DEVICE_CLASS_TYPES.get(device_class, SENSOR_OTHER)


def _sensor_types_schema(hass: HomeAssistant, entities: list[str]) -> vol.Schema:
    """One type dropdown per sensor; the field label is the entity id."""
    return vol.Schema(
        {
            vol.Required(entity_id, default=_guess_type(hass, entity_id)): _select(
                SENSOR_TYPES, "sensor_type"
            )
            for entity_id in entities
        }
    )


def _sensor_list_text(hass: HomeAssistant, entities: list[str]) -> str:
    lines = []
    for entity_id in entities:
        state = hass.states.get(entity_id)
        name = state.name if state else entity_id
        lines.append(f"- **{name}**: `{entity_id}`")
    return "\n".join(lines)


def _new_sensor(sensor_type: str) -> dict[str, Any]:
    return {
        CONF_TYPE: sensor_type,
        CONF_TRIGGER_UNAVAILABLE: False,
        **copy.deepcopy(SENSOR_TYPE_DEFAULTS[sensor_type]),
    }


def _user_schema(user: dict[str, Any] | None, editing: bool) -> vol.Schema:
    user = user or {}
    code_key = vol.Optional(CONF_CODE) if editing else vol.Required(CONF_CODE)
    return vol.Schema(
        {
            vol.Required(CONF_USER_NAME, default=user.get(CONF_USER_NAME, vol.UNDEFINED)): str,
            code_key: _code_selector(),
            vol.Required(CONF_CAN_ARM, default=user.get(CONF_CAN_ARM, True)): bool,
            vol.Required(CONF_CAN_DISARM, default=user.get(CONF_CAN_DISARM, True)): bool,
            vol.Required(CONF_CAN_BYPASS, default=user.get(CONF_CAN_BYPASS, False)): bool,
            vol.Required(CONF_DAYS, default=user.get(CONF_DAYS) or WEEKDAYS): _select(
                WEEKDAYS, "weekday", multiple=True
            ),
            vol.Required(
                CONF_START_TIME, default=user.get(CONF_START_TIME) or DEFAULT_START_TIME
            ): selector.TimeSelector(),
            vol.Required(
                CONF_END_TIME, default=user.get(CONF_END_TIME) or DEFAULT_END_TIME
            ): selector.TimeSelector(),
            vol.Optional(
                CONF_VALID_FROM,
                description={"suggested_value": user.get(CONF_VALID_FROM)},
            ): selector.DateSelector(),
            vol.Optional(
                CONF_VALID_UNTIL,
                description={"suggested_value": user.get(CONF_VALID_UNTIL)},
            ): selector.DateSelector(),
            vol.Optional(
                CONF_BLOCKED_BY,
                description={"suggested_value": user.get(CONF_BLOCKED_BY) or []},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=BLOCKING_DOMAINS, multiple=True)
            ),
        }
    )


def _user_record(user_input: dict[str, Any], base: dict[str, Any] | None) -> dict[str, Any]:
    """Build a stored user from form input (blocking: hashes the code)."""
    record = dict(base) if base else {CONF_USER_ID: uuid.uuid4().hex}
    record.update(
        {
            CONF_USER_NAME: user_input[CONF_USER_NAME].strip(),
            CONF_CAN_ARM: user_input[CONF_CAN_ARM],
            CONF_CAN_DISARM: user_input[CONF_CAN_DISARM],
            CONF_CAN_BYPASS: user_input[CONF_CAN_BYPASS],
            CONF_DAYS: user_input[CONF_DAYS] or WEEKDAYS,
            CONF_START_TIME: user_input[CONF_START_TIME],
            CONF_END_TIME: user_input[CONF_END_TIME],
            CONF_VALID_FROM: user_input.get(CONF_VALID_FROM) or None,
            CONF_VALID_UNTIL: user_input.get(CONF_VALID_UNTIL) or None,
            CONF_BLOCKED_BY: user_input.get(CONF_BLOCKED_BY) or [],
        }
    )
    code = (user_input.get(CONF_CODE) or "").strip()
    if code:
        record.update(hash_code(code))
    return record


def _check_user_input(
    user_input: dict[str, Any], users: list[dict], editing_id: str | None
) -> dict[str, str]:
    errors: dict[str, str] = {}
    name = user_input[CONF_USER_NAME].strip()
    code = (user_input.get(CONF_CODE) or "").strip()
    if not name:
        errors[CONF_USER_NAME] = "name_required"
    elif any(
        u[CONF_USER_NAME].lower() == name.lower() and u[CONF_USER_ID] != editing_id
        for u in users
    ):
        errors[CONF_USER_NAME] = "user_exists"
    if (code or editing_id is None) and (err := _validate_code(code)):
        errors[CONF_CODE] = err
    if not user_input[CONF_DAYS]:
        errors[CONF_DAYS] = "no_days"
    valid_from = user_input.get(CONF_VALID_FROM)
    valid_until = user_input.get(CONF_VALID_UNTIL)
    if valid_from and valid_until and valid_from > valid_until:
        errors[CONF_VALID_UNTIL] = "dates_reversed"
    return errors


# ---------------------------------------------------------------------------
# Initial setup
# ---------------------------------------------------------------------------
class PTAlarmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a new PT Alarm panel: name + first user, then sensors."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._name = ""
        self._options: dict[str, Any] = copy.deepcopy(DEFAULT_OPTIONS)
        self._pending: list[str] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Name the panel and (optionally) set a first user code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._name = user_input[CONF_NAME].strip()
            code = (user_input.get(CONF_CODE) or "").strip()
            self._async_abort_entries_match({CONF_NAME: self._name})
            if code and (err := _validate_code(code)):
                errors[CONF_CODE] = err
            if not errors:
                if code:
                    admin = {
                        CONF_USER_NAME: user_input.get(CONF_FIRST_USER) or "Admin",
                        CONF_CODE: code,
                        CONF_CAN_ARM: True,
                        CONF_CAN_DISARM: True,
                        CONF_CAN_BYPASS: True,
                        CONF_DAYS: WEEKDAYS,
                        CONF_START_TIME: DEFAULT_START_TIME,
                        CONF_END_TIME: DEFAULT_END_TIME,
                    }
                    record = await self.hass.async_add_executor_job(_user_record, admin, None)
                    self._options[CONF_USERS] = [record]
                return await self.async_step_sensors()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=NAME): str,
                vol.Optional(CONF_FIRST_USER, default="Admin"): str,
                vol.Optional(CONF_CODE): _code_selector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_sensors(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick sensors right away (optional)."""
        if user_input is not None:
            self._pending = user_input.get(CONF_ENTITIES, [])
            if self._pending:
                return await self.async_step_sensor_types()
            return self._finish()
        return self.async_show_form(
            step_id="sensors", data_schema=_sensor_picker([], required=False)
        )

    async def async_step_sensor_types(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a type for each picked sensor."""
        if user_input is not None:
            for entity_id in self._pending:
                self._options[CONF_SENSORS][entity_id] = _new_sensor(user_input[entity_id])
            return self._finish()
        return self.async_show_form(
            step_id="sensor_types",
            data_schema=_sensor_types_schema(self.hass, self._pending),
            description_placeholders={"sensors": _sensor_list_text(self.hass, self._pending)},
        )

    def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._name, data={CONF_NAME: self._name}, options=self._options
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return PTAlarmOptionsFlow()


# ---------------------------------------------------------------------------
# Configure menu (every change is saved immediately)
# ---------------------------------------------------------------------------
class PTAlarmOptionsFlow(OptionsFlow):
    """Menu-driven configuration of a PT Alarm panel."""

    def __init__(self) -> None:
        """Initialize."""
        self._opts: dict[str, Any] | None = None
        self._selected: str | None = None
        self._pending: list[str] = []

    @property
    def opts(self) -> dict[str, Any]:
        if self._opts is None:
            self._opts = merged_options(dict(self.config_entry.options))
        return self._opts

    async def _save_and_menu(self) -> ConfigFlowResult:
        """Save the options now (the panel reloads) and return to the menu."""
        self.hass.config_entries.async_update_entry(
            self.config_entry, options=copy.deepcopy(self.opts)
        )
        return await self.async_step_init()

    # ------------------------------------------------------------------ menu
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Main menu."""
        menu = ["general", "modes", "sensor_add"]
        if self.opts[CONF_SENSORS]:
            menu += ["sensor_edit", "sensor_remove"]
        menu.append("user_add")
        if self.opts[CONF_USERS]:
            menu += ["user_edit", "user_remove"]
        menu.append("actions")
        return self.async_show_menu(
            step_id="init",
            menu_options=menu,
            description_placeholders={
                "sensors": str(len(self.opts[CONF_SENSORS])),
                "users": str(len(self.opts[CONF_USERS])),
            },
        )

    # --------------------------------------------------------------- general
    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """General settings."""
        if user_input is not None:
            for key in (CONF_MAX_ATTEMPTS, CONF_LOCKOUT_TIME):
                user_input[key] = int(user_input[key])
            self.opts.update(user_input)
            return await self._save_and_menu()

        o = self.opts
        schema = vol.Schema(
            {
                vol.Required(CONF_CODE_ARM_REQUIRED, default=o[CONF_CODE_ARM_REQUIRED]): bool,
                vol.Required(CONF_CODE_DISARM_REQUIRED, default=o[CONF_CODE_DISARM_REQUIRED]): bool,
                vol.Required(CONF_AUTO_BYPASS, default=o[CONF_AUTO_BYPASS]): bool,
                vol.Required(CONF_DISARM_AFTER_TRIGGER, default=o[CONF_DISARM_AFTER_TRIGGER]): bool,
                vol.Required(CONF_MAX_ATTEMPTS, default=o[CONF_MAX_ATTEMPTS]): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=20, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_LOCKOUT_TIME, default=o[CONF_LOCKOUT_TIME]): _seconds(),
            }
        )
        return self.async_show_form(step_id="general", data_schema=schema)

    # ----------------------------------------------------------------- modes
    async def async_step_modes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the arm mode to configure."""
        if user_input is not None:
            self._selected = user_input[CONF_MODE]
            return await self.async_step_mode_settings()
        schema = vol.Schema({vol.Required(CONF_MODE): _select(ARM_MODES, "arm_mode")})
        return self.async_show_form(step_id="modes", data_schema=schema)

    async def async_step_mode_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one arm mode."""
        mode = self._selected
        assert mode is not None
        if user_input is not None:
            self.opts[CONF_MODES][mode] = {
                CONF_ENABLED: user_input[CONF_ENABLED],
                CONF_EXIT_TIME: int(user_input[CONF_EXIT_TIME]),
                CONF_ENTRY_TIME: int(user_input[CONF_ENTRY_TIME]),
                CONF_TRIGGER_TIME: int(user_input[CONF_TRIGGER_TIME]),
            }
            return await self._save_and_menu()

        m = self.opts[CONF_MODES][mode]
        schema = vol.Schema(
            {
                vol.Required(CONF_ENABLED, default=m[CONF_ENABLED]): bool,
                vol.Required(CONF_EXIT_TIME, default=m[CONF_EXIT_TIME]): _seconds(),
                vol.Required(CONF_ENTRY_TIME, default=m[CONF_ENTRY_TIME]): _seconds(),
                vol.Required(CONF_TRIGGER_TIME, default=m[CONF_TRIGGER_TIME]): _seconds(86400),
            }
        )
        return self.async_show_form(
            step_id="mode_settings",
            data_schema=schema,
            description_placeholders={"mode": mode.replace("armed_", "").replace("_", " ")},
        )

    # --------------------------------------------------------------- sensors
    async def async_step_sensor_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick sensors to add."""
        if user_input is not None:
            self._pending = user_input[CONF_ENTITIES]
            return await self.async_step_sensor_types()
        return self.async_show_form(
            step_id="sensor_add", data_schema=_sensor_picker(list(self.opts[CONF_SENSORS]))
        )

    async def async_step_sensor_types(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a type for each new sensor."""
        if user_input is not None:
            for entity_id in self._pending:
                self.opts[CONF_SENSORS][entity_id] = _new_sensor(user_input[entity_id])
            self._pending = []
            return await self._save_and_menu()
        return self.async_show_form(
            step_id="sensor_types",
            data_schema=_sensor_types_schema(self.hass, self._pending),
            description_placeholders={"sensors": _sensor_list_text(self.hass, self._pending)},
        )

    async def async_step_sensor_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a sensor to edit."""
        if user_input is not None:
            self._selected = user_input[CONF_ENTITY]
            return await self.async_step_sensor_settings()
        schema = vol.Schema(
            {
                vol.Required(CONF_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(include_entities=list(self.opts[CONF_SENSORS]))
                )
            }
        )
        return self.async_show_form(step_id="sensor_edit", data_schema=schema)

    async def async_step_sensor_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one sensor."""
        entity_id = self._selected
        assert entity_id is not None
        if user_input is not None:
            self.opts[CONF_SENSORS][entity_id] = user_input
            return await self._save_and_menu()

        s = self.opts[CONF_SENSORS][entity_id]
        schema = vol.Schema(
            {
                vol.Required(CONF_TYPE, default=s.get(CONF_TYPE, SENSOR_OTHER)): _select(
                    SENSOR_TYPES, "sensor_type"
                ),
                vol.Optional(CONF_SENSOR_MODES, default=s.get(CONF_SENSOR_MODES, [])): _select(
                    ARM_MODES, "arm_mode", multiple=True
                ),
                vol.Required(CONF_IMMEDIATE, default=s.get(CONF_IMMEDIATE, False)): bool,
                vol.Required(CONF_ALWAYS_ON, default=s.get(CONF_ALWAYS_ON, False)): bool,
                vol.Required(CONF_ALLOW_OPEN, default=s.get(CONF_ALLOW_OPEN, False)): bool,
                vol.Required(
                    CONF_TRIGGER_UNAVAILABLE, default=s.get(CONF_TRIGGER_UNAVAILABLE, False)
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="sensor_settings",
            data_schema=schema,
            description_placeholders={"entity": entity_id},
        )

    async def async_step_sensor_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove sensors."""
        if user_input is not None:
            for entity_id in user_input[CONF_ENTITIES]:
                self.opts[CONF_SENSORS].pop(entity_id, None)
            return await self._save_and_menu()
        schema = vol.Schema(
            {
                vol.Required(CONF_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        include_entities=list(self.opts[CONF_SENSORS]), multiple=True
                    )
                )
            }
        )
        return self.async_show_form(step_id="sensor_remove", data_schema=schema)

    # ----------------------------------------------------------------- users
    def _user_options(self) -> list[selector.SelectOptionDict]:
        return [
            selector.SelectOptionDict(
                value=u[CONF_USER_ID], label=f"{u[CONF_USER_NAME]} ({schedule_text(u)})"
            )
            for u in self.opts[CONF_USERS]
        ]

    def _find_user(self, user_id: str | None) -> dict[str, Any] | None:
        return next((u for u in self.opts[CONF_USERS] if u[CONF_USER_ID] == user_id), None)

    async def async_step_user_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a user with a code, permissions and schedule."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_user_input(user_input, self.opts[CONF_USERS], None)
            if not errors:
                record = await self.hass.async_add_executor_job(_user_record, user_input, None)
                self.opts[CONF_USERS].append(record)
                return await self._save_and_menu()
        return self.async_show_form(
            step_id="user_add",
            data_schema=self.add_suggested_values_to_schema(
                _user_schema(None, editing=False), user_input or {}
            ),
            errors=errors,
        )

    async def async_step_user_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a user to edit."""
        if user_input is not None:
            self._selected = user_input[CONF_USER]
            return await self.async_step_user_settings()
        schema = vol.Schema(
            {
                vol.Required(CONF_USER): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._user_options())
                )
            }
        )
        return self.async_show_form(step_id="user_edit", data_schema=schema)

    async def async_step_user_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one user. Leave the code empty to keep the current code."""
        user = self._find_user(self._selected)
        if user is None:
            return await self.async_step_init()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_user_input(user_input, self.opts[CONF_USERS], user[CONF_USER_ID])
            if not errors:
                record = await self.hass.async_add_executor_job(_user_record, user_input, user)
                self.opts[CONF_USERS] = [
                    record if u[CONF_USER_ID] == user[CONF_USER_ID] else u
                    for u in self.opts[CONF_USERS]
                ]
                return await self._save_and_menu()
        return self.async_show_form(
            step_id="user_settings",
            data_schema=_user_schema(user, editing=True),
            errors=errors,
            description_placeholders={"user": user[CONF_USER_NAME]},
        )

    async def async_step_user_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove users."""
        if user_input is not None:
            remove = set(user_input[CONF_USERS])
            self.opts[CONF_USERS] = [
                u for u in self.opts[CONF_USERS] if u[CONF_USER_ID] not in remove
            ]
            return await self._save_and_menu()
        schema = vol.Schema(
            {
                vol.Required(CONF_USERS): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._user_options(), multiple=True)
                )
            }
        )
        return self.async_show_form(step_id="user_remove", data_schema=schema)

    # --------------------------------------------------------------- actions
    async def async_step_actions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sirens and notifications."""
        if user_input is not None:
            self.opts[CONF_SIREN_ENTITIES] = user_input.get(CONF_SIREN_ENTITIES, [])
            self.opts[CONF_NOTIFY_SERVICES] = user_input.get(CONF_NOTIFY_SERVICES, [])
            self.opts[CONF_NOTIFY_EVENTS] = user_input.get(CONF_NOTIFY_EVENTS, [])
            return await self._save_and_menu()

        notify_services = sorted(
            f"notify.{name}"
            for name in self.hass.services.async_services().get("notify", {})
            if name not in ("send_message", "persistent_notification")
        )
        current = [s for s in self.opts[CONF_NOTIFY_SERVICES] if s not in notify_services]
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SIREN_ENTITIES, default=self.opts[CONF_SIREN_ENTITIES]
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["siren", "switch", "light", "input_boolean", "script"],
                        multiple=True,
                    )
                ),
                vol.Optional(
                    CONF_NOTIFY_SERVICES, default=self.opts[CONF_NOTIFY_SERVICES]
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=notify_services + current,
                        multiple=True,
                        custom_value=True,
                    )
                ),
                vol.Optional(CONF_NOTIFY_EVENTS, default=self.opts[CONF_NOTIFY_EVENTS]): _select(
                    NOTIFY_EVENTS, "notify_event", multiple=True
                ),
            }
        )
        return self.async_show_form(step_id="actions", data_schema=schema)
