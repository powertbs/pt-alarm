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
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    ARM_MODES,
    CONF_ALLOW_OPEN,
    CONF_ALWAYS_ON,
    CONF_AUTO_BYPASS,
    CONF_CAN_ARM,
    CONF_CAN_DISARM,
    CONF_CODE,
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
    CONF_SENSOR_MODES,
    CONF_SENSORS,
    CONF_SIREN_ENTITIES,
    CONF_TRIGGER_TIME,
    CONF_TRIGGER_UNAVAILABLE,
    CONF_TYPE,
    CONF_USER_ID,
    CONF_USER_NAME,
    CONF_USERS,
    DEFAULT_OPTIONS,
    DOMAIN,
    NAME,
    NOTIFY_EVENTS,
    SENSOR_DOMAINS,
    SENSOR_TYPE_DEFAULTS,
    SENSOR_TYPES,
)
from .helpers import hash_code, merged_options

CONF_NAME = "name"
CONF_ENTITIES = "entities"
CONF_ENTITY = "entity"
CONF_MODE = "mode"
CONF_FIRST_USER = "user_name"

MIN_CODE_LENGTH = 4


def _seconds(max_value: int = 3600) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=max_value, step=1, mode=selector.NumberSelectorMode.BOX,
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


def _new_user(name: str, code: str, can_arm: bool, can_disarm: bool) -> dict[str, Any]:
    return {
        CONF_USER_ID: uuid.uuid4().hex,
        CONF_USER_NAME: name,
        CONF_CAN_ARM: can_arm,
        CONF_CAN_DISARM: can_disarm,
        **hash_code(code),
    }


class PTAlarmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a new PT Alarm panel."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Name the panel and (optionally) set a first user code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            code = user_input.get(CONF_CODE, "").strip()
            self._async_abort_entries_match({CONF_NAME: name})
            if code and (err := _validate_code(code)):
                errors[CONF_CODE] = err
            if not errors:
                options = copy.deepcopy(DEFAULT_OPTIONS)
                if code:
                    user = await self.hass.async_add_executor_job(
                        _new_user, user_input.get(CONF_FIRST_USER) or "Admin", code, True, True
                    )
                    options[CONF_USERS] = [user]
                return self.async_create_entry(
                    title=name, data={CONF_NAME: name}, options=options
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=NAME): str,
                vol.Optional(CONF_FIRST_USER, default="Admin"): str,
                vol.Optional(CONF_CODE): _code_selector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return PTAlarmOptionsFlow()


class PTAlarmOptionsFlow(OptionsFlow):
    """Menu-driven configuration of a PT Alarm panel."""

    def __init__(self) -> None:
        """Initialize."""
        self._opts: dict[str, Any] | None = None
        self._selected: str | None = None

    @property
    def opts(self) -> dict[str, Any]:
        if self._opts is None:
            self._opts = merged_options(dict(self.config_entry.options))
        return self._opts

    # ------------------------------------------------------------------ menu
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Main menu."""
        menu = ["general", "modes", "sensor_add"]
        if self.opts[CONF_SENSORS]:
            menu += ["sensor_edit", "sensor_remove"]
        menu.append("user_add")
        if self.opts[CONF_USERS]:
            menu.append("user_remove")
        menu += ["actions", "save"]
        return self.async_show_menu(
            step_id="init",
            menu_options=menu,
            description_placeholders={
                "sensors": str(len(self.opts[CONF_SENSORS])),
                "users": str(len(self.opts[CONF_USERS])),
            },
        )

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Save all changes."""
        return self.async_create_entry(data=self.opts)

    # --------------------------------------------------------------- general
    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """General settings."""
        if user_input is not None:
            for key in (CONF_MAX_ATTEMPTS, CONF_LOCKOUT_TIME):
                user_input[key] = int(user_input[key])
            self.opts.update(user_input)
            return await self.async_step_init()

        o = self.opts
        schema = vol.Schema(
            {
                vol.Required(CONF_CODE_ARM_REQUIRED, default=o[CONF_CODE_ARM_REQUIRED]): bool,
                vol.Required(CONF_CODE_DISARM_REQUIRED, default=o[CONF_CODE_DISARM_REQUIRED]): bool,
                vol.Required(CONF_AUTO_BYPASS, default=o[CONF_AUTO_BYPASS]): bool,
                vol.Required(CONF_DISARM_AFTER_TRIGGER, default=o[CONF_DISARM_AFTER_TRIGGER]): bool,
                vol.Required(CONF_MAX_ATTEMPTS, default=o[CONF_MAX_ATTEMPTS]): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=20, step=1, mode=selector.NumberSelectorMode.BOX)
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

    async def async_step_mode_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
            return await self.async_step_init()

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
    async def async_step_sensor_add(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Add one or more sensors with type defaults."""
        if user_input is not None:
            sensor_type = user_input[CONF_TYPE]
            for entity_id in user_input[CONF_ENTITIES]:
                self.opts[CONF_SENSORS][entity_id] = {
                    CONF_TYPE: sensor_type,
                    CONF_TRIGGER_UNAVAILABLE: False,
                    **copy.deepcopy(SENSOR_TYPE_DEFAULTS[sensor_type]),
                }
            return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required(CONF_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=SENSOR_DOMAINS,
                        multiple=True,
                        exclude_entities=list(self.opts[CONF_SENSORS]),
                    )
                ),
                vol.Required(CONF_TYPE, default="door"): _select(SENSOR_TYPES, "sensor_type"),
            }
        )
        return self.async_show_form(step_id="sensor_add", data_schema=schema)

    async def async_step_sensor_edit(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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

    async def async_step_sensor_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit one sensor."""
        entity_id = self._selected
        assert entity_id is not None
        if user_input is not None:
            self.opts[CONF_SENSORS][entity_id] = user_input
            return await self.async_step_init()

        s = self.opts[CONF_SENSORS][entity_id]
        schema = vol.Schema(
            {
                vol.Required(CONF_TYPE, default=s.get(CONF_TYPE, "other")): _select(SENSOR_TYPES, "sensor_type"),
                vol.Optional(CONF_SENSOR_MODES, default=s.get(CONF_SENSOR_MODES, [])): _select(
                    ARM_MODES, "arm_mode", multiple=True
                ),
                vol.Required(CONF_IMMEDIATE, default=s.get(CONF_IMMEDIATE, False)): bool,
                vol.Required(CONF_ALWAYS_ON, default=s.get(CONF_ALWAYS_ON, False)): bool,
                vol.Required(CONF_ALLOW_OPEN, default=s.get(CONF_ALLOW_OPEN, False)): bool,
                vol.Required(CONF_TRIGGER_UNAVAILABLE, default=s.get(CONF_TRIGGER_UNAVAILABLE, False)): bool,
            }
        )
        return self.async_show_form(
            step_id="sensor_settings",
            data_schema=schema,
            description_placeholders={"entity": entity_id},
        )

    async def async_step_sensor_remove(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Remove sensors."""
        if user_input is not None:
            for entity_id in user_input[CONF_ENTITIES]:
                self.opts[CONF_SENSORS].pop(entity_id, None)
            return await self.async_step_init()
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
    async def async_step_user_add(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Add a user with a code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_USER_NAME].strip()
            code = user_input[CONF_CODE].strip()
            if err := _validate_code(code):
                errors[CONF_CODE] = err
            elif any(u[CONF_USER_NAME].lower() == name.lower() for u in self.opts[CONF_USERS]):
                errors[CONF_USER_NAME] = "user_exists"
            if not errors:
                user = await self.hass.async_add_executor_job(
                    _new_user, name, code, user_input[CONF_CAN_ARM], user_input[CONF_CAN_DISARM]
                )
                self.opts[CONF_USERS].append(user)
                return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required(CONF_USER_NAME): str,
                vol.Required(CONF_CODE): _code_selector(),
                vol.Required(CONF_CAN_ARM, default=True): bool,
                vol.Required(CONF_CAN_DISARM, default=True): bool,
            }
        )
        return self.async_show_form(step_id="user_add", data_schema=schema, errors=errors)

    async def async_step_user_remove(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Remove users."""
        if user_input is not None:
            remove = set(user_input[CONF_USERS])
            self.opts[CONF_USERS] = [
                u for u in self.opts[CONF_USERS] if u[CONF_USER_ID] not in remove
            ]
            return await self.async_step_init()
        schema = vol.Schema(
            {
                vol.Required(CONF_USERS): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=u[CONF_USER_ID], label=u[CONF_USER_NAME])
                            for u in self.opts[CONF_USERS]
                        ],
                        multiple=True,
                    )
                )
            }
        )
        return self.async_show_form(step_id="user_remove", data_schema=schema)

    # --------------------------------------------------------------- actions
    async def async_step_actions(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Sirens and notifications."""
        if user_input is not None:
            self.opts[CONF_SIREN_ENTITIES] = user_input.get(CONF_SIREN_ENTITIES, [])
            self.opts[CONF_NOTIFY_SERVICES] = user_input.get(CONF_NOTIFY_SERVICES, [])
            self.opts[CONF_NOTIFY_EVENTS] = user_input.get(CONF_NOTIFY_EVENTS, [])
            return await self.async_step_init()

        notify_services = sorted(
            f"notify.{name}"
            for name in self.hass.services.async_services().get("notify", {})
            if name not in ("send_message", "persistent_notification")
        )
        current = [s for s in self.opts[CONF_NOTIFY_SERVICES] if s not in notify_services]
        schema = vol.Schema(
            {
                vol.Optional(CONF_SIREN_ENTITIES, default=self.opts[CONF_SIREN_ENTITIES]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["siren", "switch", "light", "input_boolean", "script"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_NOTIFY_SERVICES, default=self.opts[CONF_NOTIFY_SERVICES]): selector.SelectSelector(
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
