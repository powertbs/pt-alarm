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
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    selector,
)

from .const import (
    ARM_MODES,
    CONF_ACCESS_IDS,
    CONF_AUTOMATION_ALLOWED,
    CONF_AUTOMATION_ANONYMOUS,
    CONF_AUTOMATION_OPEN_ZONES,
    OPEN_ZONES_BYPASS,
    OPEN_ZONES_REFUSE,
    BLOCKING_DOMAINS,
    CONF_AREA,
    CONF_AUTO_BYPASS,
    CONF_BLOCKED_BY,
    CONF_CAN_ARM,
    CONF_CAN_BYPASS,
    CONF_CAN_DISARM,
    CONF_CHIME,
    CONF_CODE,
    CONF_CODE_ARM_REQUIRED,
    CONF_CODE_DISARM_REQUIRED,
    CONF_DAYS,
    CONF_DISARM_AFTER_TRIGGER,
    CONF_ENABLED,
    CONF_END_TIME,
    CONF_ENTRY_DELAY_1,
    CONF_ENTRY_DELAY_2,
    CONF_EXIT_TIME,
    CONF_INSTANT,
    CONF_LOCKOUT_TIME,
    CONF_MAX_ATTEMPTS,
    CONF_MODES,
    CONF_EMAIL_EVENTS,
    CONF_EMAIL_HTML,
    CONF_EMAIL_SERVICES,
    CONF_PUSH_EVENTS,
    CONF_PUSH_SERVICES,
    CONF_PARTITIONS,
    CONF_SENSOR_NAME,
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
    CONF_ZONE_TYPE,
    DEFAULT_END_TIME,
    DEFAULT_OPTIONS,
    DEFAULT_START_TIME,
    DEVICE_CLASS_TYPES,
    DEVICE_CLASS_ZONE_TYPES,
    ENTRY_DELAY_ZONES,
    KIND_ZONE_TYPES,
    DOMAIN,
    NAME,
    SENSOR_DOMAINS,
    SENSOR_OTHER,
    SENSOR_TYPES,
    WEEKDAYS,
    ZONE_TYPES,
    mode_label,
)
from .helpers import hash_code, merged_options, schedule_text, zone_type_of
from .notifications import NC_TEST, NOTIFY_CATEGORIES, async_send

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


def _automation_schema(o: dict[str, Any]) -> vol.Schema:
    """Questions about arming/disarming by automations and access control."""
    return vol.Schema(
        {
            vol.Required(CONF_AUTOMATION_ALLOWED, default=o[CONF_AUTOMATION_ALLOWED]): bool,
            vol.Required(
                CONF_AUTOMATION_OPEN_ZONES, default=o[CONF_AUTOMATION_OPEN_ZONES]
            ): _select([OPEN_ZONES_REFUSE, OPEN_ZONES_BYPASS], "open_zones_action"),
            vol.Required(CONF_AUTOMATION_ANONYMOUS, default=o[CONF_AUTOMATION_ANONYMOUS]): bool,
        }
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


def _device_class(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    return str(state.attributes.get("device_class", "")) if state else ""


def _guess_type(hass: HomeAssistant, entity_id: str) -> str:
    """Guess the device kind from the entity's device class."""
    if entity_id.startswith("lock."):
        return DEVICE_CLASS_TYPES["lock"]
    return DEVICE_CLASS_TYPES.get(_device_class(hass, entity_id), SENSOR_OTHER)


def _guess_zone_type(hass: HomeAssistant, entity_id: str) -> str:
    """Guess the zone type (behaviour) from the device class / kind."""
    device_class = _device_class(hass, entity_id)
    if device_class in DEVICE_CLASS_ZONE_TYPES:
        return DEVICE_CLASS_ZONE_TYPES[device_class]
    return KIND_ZONE_TYPES[_guess_type(hass, entity_id)]


def _source_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    return state.name if state and state.name else entity_id


def _source_area(hass: HomeAssistant, entity_id: str) -> str | None:
    """Area of the source entity (or its device), if any."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return None
    if entry.area_id:
        return entry.area_id
    if entry.device_id and (device := dr.async_get(hass).async_get(entry.device_id)):
        return device.area_id
    return None


def _details_schema(
    name: str, sensor_type: str, zone_type: str, area: str | None
) -> vol.Schema:
    """Name, device kind, zone type, location and chime of one sensor."""
    return vol.Schema(
        {
            vol.Required(CONF_SENSOR_NAME, default=name): str,
            vol.Required(CONF_ZONE_TYPE, default=zone_type): _select(ZONE_TYPES, "zone_type"),
            vol.Required(CONF_TYPE, default=sensor_type): _select(SENSOR_TYPES, "sensor_type"),
            vol.Optional(
                CONF_AREA, description={"suggested_value": area}
            ): selector.AreaSelector(),
            vol.Required(CONF_CHIME, default=zone_type in ENTRY_DELAY_ZONES): bool,
        }
    )


def _new_sensor(details: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_SENSOR_NAME: details[CONF_SENSOR_NAME].strip(),
        CONF_AREA: details.get(CONF_AREA) or None,
        CONF_TYPE: details[CONF_TYPE],
        CONF_ZONE_TYPE: details[CONF_ZONE_TYPE],
        CONF_CHIME: bool(details.get(CONF_CHIME)),
        CONF_TRIGGER_UNAVAILABLE: False,
    }


class _SensorDetailsMixin:
    """Shared 'one screen per new sensor' loop for setup and the Configure menu."""

    hass: HomeAssistant
    _pending: list[str]
    _details_total: int

    def _start_details(self, entities: list[str]) -> None:
        self._pending = list(entities)
        self._details_total = len(entities)

    def _details_form(self, step_id: str) -> ConfigFlowResult:
        entity_id = self._pending[0]
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id=step_id,
            data_schema=_details_schema(
                _source_name(self.hass, entity_id),
                _guess_type(self.hass, entity_id),
                _guess_zone_type(self.hass, entity_id),
                _source_area(self.hass, entity_id),
            ),
            description_placeholders={
                "entity": entity_id,
                "number": str(self._details_total - len(self._pending) + 1),
                "total": str(self._details_total),
            },
        )

    def _take_details(self, user_input: dict[str, Any], sensors: dict[str, dict]) -> None:
        entity_id = self._pending.pop(0)
        if not user_input[CONF_SENSOR_NAME].strip():
            user_input[CONF_SENSOR_NAME] = _source_name(self.hass, entity_id)
        sensors[entity_id] = _new_sensor(user_input)


def _user_schema(
    user: dict[str, Any] | None,
    editing: bool,
    partitions: list[selector.SelectOptionDict] | None = None,
    member_of: list[str] | None = None,
) -> vol.Schema:
    user = user or {}
    name_key = (
        vol.Required(CONF_USER_NAME, default=user.get(CONF_USER_NAME, ""))
        if editing
        else vol.Optional(CONF_USER_NAME)
    )
    return vol.Schema(
        {
            name_key: str,
            vol.Optional(CONF_CODE): _code_selector(),
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
            vol.Optional(
                CONF_ACCESS_IDS,
                description={"suggested_value": user.get(CONF_ACCESS_IDS) or []},
            ): selector.TextSelector(selector.TextSelectorConfig(multiple=True)),
            **(
                {
                    vol.Required(CONF_PARTITIONS, default=member_of or []): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=partitions,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
                if partitions and len(partitions) > 1
                else {}
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
            CONF_ACCESS_IDS: [
                str(a).strip() for a in user_input.get(CONF_ACCESS_IDS) or [] if str(a).strip()
            ],
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
    name = (user_input.get(CONF_USER_NAME) or "").strip()
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
    if CONF_PARTITIONS in user_input and not user_input[CONF_PARTITIONS]:
        errors[CONF_PARTITIONS] = "no_partitions"
    valid_from = user_input.get(CONF_VALID_FROM)
    valid_until = user_input.get(CONF_VALID_UNTIL)
    if valid_from and valid_until and valid_from > valid_until:
        errors[CONF_VALID_UNTIL] = "dates_reversed"
    return errors


# ---------------------------------------------------------------------------
# Initial setup
# ---------------------------------------------------------------------------
class PTAlarmConfigFlow(_SensorDetailsMixin, ConfigFlow, domain=DOMAIN):
    """Create a new PT Alarm panel: name + first user, then sensors."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._name = ""
        self._options: dict[str, Any] = copy.deepcopy(DEFAULT_OPTIONS)
        self._pending: list[str] = []
        self._details_total = 0

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
                return await self.async_step_automations()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=NAME): str,
                vol.Optional(CONF_FIRST_USER, default="Admin"): str,
                vol.Optional(CONF_CODE): _code_selector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_automations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how automations and access control may arm/disarm."""
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_sensors()
        return self.async_show_form(
            step_id="automations", data_schema=_automation_schema(self._options)
        )

    async def async_step_sensors(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick sensors right away (optional)."""
        if user_input is not None:
            self._start_details(user_input.get(CONF_ENTITIES, []))
            if self._pending:
                return await self.async_step_sensor_details()
            return self._finish()
        return self.async_show_form(
            step_id="sensors", data_schema=_sensor_picker([], required=False)
        )

    async def async_step_sensor_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name, type and location for each picked sensor, one at a time."""
        if user_input is not None:
            self._take_details(user_input, self._options[CONF_SENSORS])
            if not self._pending:
                return self._finish()
        return self._details_form("sensor_details")

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
class PTAlarmOptionsFlow(_SensorDetailsMixin, OptionsFlow):
    """Menu-driven configuration of a PT Alarm panel."""

    def __init__(self) -> None:
        """Initialize."""
        self._opts: dict[str, Any] | None = None
        self._selected: str | None = None
        self._pending: list[str] = []
        self._details_total = 0

    @property
    def opts(self) -> dict[str, Any]:
        if self._opts is None:
            self._opts = merged_options(dict(self.config_entry.options))
        return self._opts

    async def _save_and_menu(self) -> ConfigFlowResult:
        """Save the options now (the panel reloads) and return to the menu."""
        if self.opts != merged_options(dict(self.config_entry.options)):
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
        menu += ["automations", "notifications", "notify_test", "sirens"]
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
            for key in (CONF_MAX_ATTEMPTS, CONF_LOCKOUT_TIME, CONF_ENTRY_DELAY_1, CONF_ENTRY_DELAY_2):
                user_input[key] = int(user_input[key])
            self.opts.update(user_input)
            return await self._save_and_menu()

        o = self.opts
        schema = vol.Schema(
            {
                vol.Required(CONF_ENTRY_DELAY_1, default=o[CONF_ENTRY_DELAY_1]): _seconds(),
                vol.Required(CONF_ENTRY_DELAY_2, default=o[CONF_ENTRY_DELAY_2]): _seconds(),
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
            if not user_input.get(CONF_MODE):
                return await self.async_step_init()
            self._selected = user_input[CONF_MODE]
            return await self.async_step_mode_settings()
        schema = vol.Schema({vol.Optional(CONF_MODE): _select(ARM_MODES, "arm_mode")})
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
                CONF_TRIGGER_TIME: int(user_input[CONF_TRIGGER_TIME]),
                CONF_INSTANT: user_input[CONF_INSTANT],
            }
            return await self._save_and_menu()

        m = self.opts[CONF_MODES][mode]
        schema = vol.Schema(
            {
                vol.Required(CONF_ENABLED, default=m[CONF_ENABLED]): bool,
                vol.Required(CONF_EXIT_TIME, default=m[CONF_EXIT_TIME]): _seconds(),
                vol.Required(CONF_TRIGGER_TIME, default=m[CONF_TRIGGER_TIME]): _seconds(86400),
                vol.Required(CONF_INSTANT, default=bool(m.get(CONF_INSTANT))): bool,
            }
        )
        return self.async_show_form(
            step_id="mode_settings",
            data_schema=schema,
            description_placeholders={"mode": mode_label(mode)},
        )

    # --------------------------------------------------------------- sensors
    async def async_step_sensor_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick sensors to add."""
        if user_input is not None:
            self._start_details(user_input.get(CONF_ENTITIES) or [])
            if not self._pending:
                return await self.async_step_init()
            return await self.async_step_sensor_details()
        return self.async_show_form(
            step_id="sensor_add",
            data_schema=_sensor_picker(list(self.opts[CONF_SENSORS]), required=False),
        )

    async def async_step_sensor_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name, type and location for each new sensor, one at a time."""
        if user_input is not None:
            self._take_details(user_input, self.opts[CONF_SENSORS])
            if not self._pending:
                return await self._save_and_menu()
        return self._details_form("sensor_details")

    async def async_step_sensor_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a sensor to edit."""
        if user_input is not None:
            if not user_input.get(CONF_ENTITY):
                return await self.async_step_init()
            self._selected = user_input[CONF_ENTITY]
            return await self.async_step_sensor_settings()
        schema = vol.Schema(
            {
                vol.Optional(CONF_ENTITY): selector.EntitySelector(
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
            user_input[CONF_SENSOR_NAME] = (
                user_input.get(CONF_SENSOR_NAME) or ""
            ).strip() or _source_name(self.hass, entity_id)
            user_input[CONF_AREA] = user_input.get(CONF_AREA) or None
            self.opts[CONF_SENSORS][entity_id] = user_input
            return await self._save_and_menu()

        s = self.opts[CONF_SENSORS][entity_id]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SENSOR_NAME,
                    default=s.get(CONF_SENSOR_NAME) or _source_name(self.hass, entity_id),
                ): str,
                vol.Optional(
                    CONF_AREA, description={"suggested_value": s.get(CONF_AREA)}
                ): selector.AreaSelector(),
                vol.Required(
                    CONF_ZONE_TYPE,
                    default=zone_type_of(s, _device_class(self.hass, entity_id) or None),
                ): _select(ZONE_TYPES, "zone_type"),
                vol.Required(CONF_TYPE, default=s.get(CONF_TYPE, SENSOR_OTHER)): _select(
                    SENSOR_TYPES, "sensor_type"
                ),
                vol.Required(CONF_CHIME, default=bool(s.get(CONF_CHIME))): bool,
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
            for entity_id in user_input.get(CONF_ENTITIES) or []:
                self.opts[CONF_SENSORS].pop(entity_id, None)
            return await self._save_and_menu()
        schema = vol.Schema(
            {
                vol.Optional(CONF_ENTITIES, default=[]): selector.EntitySelector(
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

    def _partition_options(self) -> list[selector.SelectOptionDict]:
        return [
            selector.SelectOptionDict(value=entry.entry_id, label=entry.title)
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        ]

    def _member_of(self, user_id: str) -> list[str]:
        """Partitions (config entries) that contain this user."""
        result = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            users = (
                self.opts[CONF_USERS]
                if entry.entry_id == self.config_entry.entry_id
                else merged_options(dict(entry.options))[CONF_USERS]
            )
            if any(u[CONF_USER_ID] == user_id for u in users):
                result.append(entry.entry_id)
        return result

    def _sync_user(self, record: dict[str, Any] | None, user_id: str, selected: list[str]) -> None:
        """Put the user in the selected partitions and take it out of the others.

        record=None removes the user everywhere.
        """
        current = self.config_entry.entry_id
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == current:
                users = self.opts[CONF_USERS]
            else:
                opts = merged_options(dict(entry.options))
                users = opts[CONF_USERS]
            index = next((i for i, u in enumerate(users) if u[CONF_USER_ID] == user_id), None)
            keep = record is not None and entry.entry_id in selected
            new_users = [u for u in users if u[CONF_USER_ID] != user_id]
            if keep:
                new_users.insert(index if index is not None else len(new_users), record)
            if entry.entry_id == current:
                self.opts[CONF_USERS] = new_users
            elif new_users != users:
                opts[CONF_USERS] = new_users
                self.hass.config_entries.async_update_entry(entry, options=opts)

    def _find_user(self, user_id: str | None) -> dict[str, Any] | None:
        return next((u for u in self.opts[CONF_USERS] if u[CONF_USER_ID] == user_id), None)

    async def async_step_user_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a user with a code, permissions and schedule."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not (user_input.get(CONF_USER_NAME) or "").strip() and not user_input.get(CONF_CODE):
                return await self.async_step_init()
            errors = _check_user_input(user_input, self.opts[CONF_USERS], None)
            if not errors:
                record = await self.hass.async_add_executor_job(_user_record, user_input, None)
                selected = user_input.get(CONF_PARTITIONS) or [self.config_entry.entry_id]
                self._sync_user(record, record[CONF_USER_ID], selected)
                return await self._save_and_menu()
        return self.async_show_form(
            step_id="user_add",
            data_schema=self.add_suggested_values_to_schema(
                _user_schema(
                    None,
                    editing=False,
                    partitions=self._partition_options(),
                    member_of=[self.config_entry.entry_id],
                ),
                user_input or {},
            ),
            errors=errors,
        )

    async def async_step_user_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a user to edit."""
        if user_input is not None:
            if not user_input.get(CONF_USER):
                return await self.async_step_init()
            self._selected = user_input[CONF_USER]
            return await self.async_step_user_settings()
        schema = vol.Schema(
            {
                vol.Optional(CONF_USER): selector.SelectSelector(
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
                selected = user_input.get(CONF_PARTITIONS) or [self.config_entry.entry_id]
                self._sync_user(record, user[CONF_USER_ID], selected)
                return await self._save_and_menu()
        return self.async_show_form(
            step_id="user_settings",
            data_schema=_user_schema(
                user,
                editing=True,
                partitions=self._partition_options(),
                member_of=self._member_of(user[CONF_USER_ID]),
            ),
            errors=errors,
            description_placeholders={"user": user[CONF_USER_NAME]},
        )

    async def async_step_user_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove users."""
        if user_input is not None:
            for user_id in user_input.get(CONF_USERS) or []:
                self._sync_user(None, user_id, [])
            return await self._save_and_menu()
        schema = vol.Schema(
            {
                vol.Optional(CONF_USERS, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._user_options(), multiple=True)
                )
            }
        )
        return self.async_show_form(step_id="user_remove", data_schema=schema)

    # ----------------------------------------------------------- automations
    async def async_step_automations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Automations and access control."""
        if user_input is not None:
            self.opts.update(user_input)
            return await self._save_and_menu()
        return self.async_show_form(
            step_id="automations", data_schema=_automation_schema(self.opts)
        )

    # --------------------------------------------------------------- actions
    def _notify_services(self, current: list[str]) -> list[selector.SelectOptionDict]:
        """Old-style notify services (HTML capable) and new-style notify entities."""
        options: dict[str, str] = {}
        for name in sorted(self.hass.services.async_services().get("notify", {})):
            if name not in ("send_message", "persistent_notification"):
                options[f"notify.{name}"] = f"notify.{name}"
        for entity_id in sorted(self.hass.states.async_entity_ids("notify")):
            if entity_id not in options:
                state = self.hass.states.get(entity_id)
                name = state.name if state else entity_id
                options[entity_id] = f"{name} ({entity_id}, plain text)"
        for value in current:
            options.setdefault(value, value)
        return [selector.SelectOptionDict(value=v, label=l) for v, l in options.items()]

    def _services_selector(self, current: list[str]) -> selector.SelectSelector:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=self._notify_services(current), multiple=True, custom_value=True
            )
        )

    def _events_selector(self) -> selector.SelectSelector:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=NOTIFY_CATEGORIES,
                translation_key="notify_category",
                multiple=True,
                mode=selector.SelectSelectorMode.LIST,
            )
        )

    async def async_step_sirens(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sirens."""
        if user_input is not None:
            self.opts[CONF_SIREN_ENTITIES] = user_input.get(CONF_SIREN_ENTITIES, [])
            return await self._save_and_menu()
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
            }
        )
        return self.async_show_form(step_id="sirens", data_schema=schema)

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Email and push notifications, each with its own on/off list of events."""
        if user_input is not None:
            for key in (CONF_EMAIL_SERVICES, CONF_EMAIL_EVENTS, CONF_PUSH_SERVICES, CONF_PUSH_EVENTS):
                self.opts[key] = user_input.get(key, [])
            self.opts[CONF_EMAIL_HTML] = user_input.get(CONF_EMAIL_HTML, True)
            return await self._save_and_menu()
        o = self.opts
        schema = vol.Schema(
            {
                vol.Optional(CONF_EMAIL_SERVICES, default=o[CONF_EMAIL_SERVICES]): self._services_selector(
                    o[CONF_EMAIL_SERVICES]
                ),
                vol.Required(CONF_EMAIL_HTML, default=o[CONF_EMAIL_HTML]): bool,
                vol.Optional(CONF_EMAIL_EVENTS, default=o[CONF_EMAIL_EVENTS]): self._events_selector(),
                vol.Optional(CONF_PUSH_SERVICES, default=o[CONF_PUSH_SERVICES]): self._services_selector(
                    o[CONF_PUSH_SERVICES]
                ),
                vol.Optional(CONF_PUSH_EVENTS, default=o[CONF_PUSH_EVENTS]): self._events_selector(),
            }
        )
        return self.async_show_form(step_id="notifications", data_schema=schema)

    async def async_step_notify_test(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Send a test email / push with the current settings."""
        if user_input is not None:
            if user_input.get("send"):
                await async_send(
                    self.hass,
                    self.opts,
                    self.config_entry.title,
                    [NC_TEST],
                    {"user": "Test"},
                    "This is a test notification from PT Alarm.",
                    force=True,
                )
            return await self.async_step_init()
        has_any = bool(self.opts[CONF_EMAIL_SERVICES] or self.opts[CONF_PUSH_SERVICES])
        return self.async_show_form(
            step_id="notify_test",
            data_schema=vol.Schema({vol.Required("send", default=has_any): bool}),
            description_placeholders={
                "email": ", ".join(self.opts[CONF_EMAIL_SERVICES]) or "none",
                "push": ", ".join(self.opts[CONF_PUSH_SERVICES]) or "none",
            },
        )
