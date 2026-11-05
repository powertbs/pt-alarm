"""Config and options flow tests."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.pt_alarm.const import DOMAIN


async def test_user_flow_creates_entry(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Home", "code": "12"}
    )
    assert result["errors"] == {"code": "code_too_short"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Home", "user_name": "Bob", "code": "4321"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    users = result["options"]["users"]
    assert users[0]["name"] == "Bob"
    assert "4321" not in str(users)


async def test_options_flow_add_sensor_mode_and_save(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.door", "off")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Home"})
    entry = result["result"]
    await hass.async_block_till_done()

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] is FlowResultType.MENU
    fid = flow["flow_id"]
    configure = hass.config_entries.options.async_configure

    result = await configure(fid, {"next_step_id": "sensor_add"})
    result = await configure(fid, {"entities": ["binary_sensor.door"], "type": "door"})
    assert result["type"] is FlowResultType.MENU

    result = await configure(fid, {"next_step_id": "modes"})
    result = await configure(fid, {"mode": "armed_away"})
    result = await configure(
        fid, {"enabled": True, "exit_time": 30, "entry_time": 15, "trigger_time": 60}
    )
    result = await configure(fid, {"next_step_id": "user_add"})
    result = await configure(
        fid, {"name": "Carol", "code": "5555", "can_arm": True, "can_disarm": True}
    )
    assert result["type"] is FlowResultType.MENU

    result = await configure(fid, {"next_step_id": "save"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options["sensors"]["binary_sensor.door"]["type"] == "door"
    assert entry.options["modes"]["armed_away"]["exit_time"] == 30
    assert entry.options["users"][0]["name"] == "Carol"
    state = hass.states.get("alarm_control_panel.home")
    assert state is not None
    assert state.attributes["code_format"] == "number"
