"""Config and options flow tests."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.pt_alarm.const import DOMAIN

USER_FIELDS = {
    "can_arm": True,
    "can_disarm": True,
    "can_bypass": False,
    "days": ["mon", "tue", "wed", "thu", "fri"],
    "start_time": "08:00:00",
    "end_time": "18:00:00",
}


async def _create(hass: HomeAssistant, sensors=None, **user):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Home", **user}
    )
    assert result["step_id"] == "sensors"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"entities": list(sensors or {})}
    )
    if sensors:
        assert result["step_id"] == "sensor_types"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], sensors)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result


async def test_user_flow_with_sensors_and_type_guessing(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.front", "off", {"device_class": "door"})
    hass.states.async_set("binary_sensor.hall", "off", {"device_class": "motion"})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Home", "code": "12"}
    )
    assert result["errors"] == {"code": "code_too_short"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Home", "user_name": "Bob", "code": "4321"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"entities": ["binary_sensor.front", "binary_sensor.hall"]}
    )
    assert result["step_id"] == "sensor_types"
    # The type dropdowns are pre-filled from the device class
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    assert defaults == {"binary_sensor.front": "door", "binary_sensor.hall": "motion"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"binary_sensor.front": "door", "binary_sensor.hall": "window"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = result["options"]
    assert options["sensors"]["binary_sensor.front"]["type"] == "door"
    assert options["sensors"]["binary_sensor.hall"]["type"] == "window"
    assert options["sensors"]["binary_sensor.hall"]["immediate"] is True
    assert options["users"][0]["name"] == "Bob"
    assert options["users"][0]["can_bypass"] is True
    assert "4321" not in str(options["users"])


async def test_options_flow_saves_each_change_immediately(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.door", "off", {"device_class": "door"})
    result = await _create(hass)
    entry = result["result"]

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] is FlowResultType.MENU
    assert "save" not in flow["menu_options"]
    fid = flow["flow_id"]
    configure = hass.config_entries.options.async_configure

    await configure(fid, {"next_step_id": "sensor_add"})
    result = await configure(fid, {"entities": ["binary_sensor.door"]})
    assert result["step_id"] == "sensor_types"
    result = await configure(fid, {"binary_sensor.door": "door"})
    assert result["type"] is FlowResultType.MENU
    await hass.async_block_till_done()
    # Saved already, without any "save" step
    assert entry.options["sensors"]["binary_sensor.door"]["type"] == "door"

    await configure(fid, {"next_step_id": "user_add"})
    result = await configure(fid, {"name": "Carol", "code": "5555", **USER_FIELDS})
    assert result["type"] is FlowResultType.MENU
    await hass.async_block_till_done()
    carol = entry.options["users"][0]
    assert carol["name"] == "Carol"
    assert carol["days"] == ["mon", "tue", "wed", "thu", "fri"]
    old_hash = carol["code_hash"]

    # Edit: rename and set dates, keep the code by leaving it empty
    result = await configure(fid, {"next_step_id": "user_edit"})
    result = await configure(fid, {"user": carol["id"]})
    assert result["step_id"] == "user_settings"
    result = await configure(
        fid,
        {
            "name": "Carol B",
            **USER_FIELDS,
            "can_bypass": True,
            "valid_from": "2026-12-01",
            "valid_until": "2026-11-01",
        },
    )
    assert result["errors"] == {"valid_until": "dates_reversed"}
    result = await configure(
        fid,
        {"name": "Carol B", **USER_FIELDS, "can_bypass": True, "valid_from": "2026-12-01"},
    )
    assert result["type"] is FlowResultType.MENU
    await hass.async_block_till_done()
    carol = entry.options["users"][0]
    assert carol["name"] == "Carol B"
    assert carol["can_bypass"] is True
    assert carol["valid_from"] == "2026-12-01"
    assert carol["code_hash"] == old_hash

    state = hass.states.get("alarm_control_panel.home")
    assert state is not None
    assert state.attributes["code_format"] == "number"
    assert hass.states.get("sensor.home_door").state == "closed"
