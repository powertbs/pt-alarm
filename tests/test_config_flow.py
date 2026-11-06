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


async def _create(hass: HomeAssistant, sensors=None, automations=None, **user):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Home", **user}
    )
    assert result["step_id"] == "automations"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], automations or {})
    assert result["step_id"] == "sensors"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"entities": list(sensors or {})}
    )
    for details in (sensors or {}).values():
        assert result["step_id"] == "sensor_details"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], details)
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
    assert result["step_id"] == "automations"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"automation_allowed": True, "automation_open_zones": "bypass"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"entities": ["binary_sensor.front", "binary_sensor.hall"]}
    )
    # One screen per sensor, pre-filled with its name and guessed type
    assert result["step_id"] == "sensor_details"
    assert result["description_placeholders"]["number"] == "1"
    defaults = {str(k): k.default() for k in result["data_schema"].schema if str(k) != "area"}
    assert defaults == {"name": "front", "type": "door", "zone_type": "entry_exit_1", "chime": True}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Front door", "type": "door"}
    )
    assert result["step_id"] == "sensor_details"
    defaults = {str(k): k.default() for k in result["data_schema"].schema if str(k) != "area"}
    assert defaults == {"name": "hall", "type": "motion", "zone_type": "interior_follower", "chime": False}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Hall", "type": "motion", "zone_type": "interior"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = result["options"]
    assert options["sensors"]["binary_sensor.front"]["type"] == "door"
    assert options["sensors"]["binary_sensor.front"]["name"] == "Front door"
    assert options["sensors"]["binary_sensor.hall"]["type"] == "motion"
    assert options["sensors"]["binary_sensor.hall"]["zone_type"] == "interior"
    assert options["users"][0]["name"] == "Bob"
    assert options["automation_allowed"] is True
    assert options["automation_open_zones"] == "bypass"
    assert options["automation_anonymous"] is False
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
    assert result["step_id"] == "sensor_details"
    result = await configure(fid, {"name": "Back door", "type": "door"})
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
    assert hass.states.get("sensor.home_back_door").state == "closed"


async def test_empty_submit_goes_back_to_menu(hass: HomeAssistant):
    result = await _create(hass)
    entry = result["result"]
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    fid = flow["flow_id"]
    configure = hass.config_entries.options.async_configure

    for step in ("sensor_add", "modes", "user_add"):
        result = await configure(fid, {"next_step_id": step})
        assert result["step_id"] == step
        result = await configure(fid, {})
        assert result["type"] is FlowResultType.MENU, step

    result = await configure(fid, {"next_step_id": "user_add"})
    result = await configure(fid, {"name": "Dan"})
    assert result["errors"] == {"code": "code_too_short"}


async def test_user_partitions_are_kept_in_sync(hass: HomeAssistant):
    office = (await _create(hass))["result"]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Warehouse"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"entities": []})
    warehouse = result["result"]
    await hass.async_block_till_done()

    flow = await hass.config_entries.options.async_init(office.entry_id)
    fid = flow["flow_id"]
    configure = hass.config_entries.options.async_configure
    result = await configure(fid, {"next_step_id": "user_add"})
    assert "partitions" in [str(k) for k in result["data_schema"].schema]

    # Manager: both partitions. Worker: warehouse only.
    await configure(fid, {"name": "Manager", "code": "1111", **USER_FIELDS,
                          "partitions": [office.entry_id, warehouse.entry_id]})
    await configure(fid, {"next_step_id": "user_add"})
    await configure(fid, {"name": "Worker", "code": "2222", **USER_FIELDS,
                          "partitions": [warehouse.entry_id]})
    await hass.async_block_till_done()
    assert [u["name"] for u in office.options["users"]] == ["Manager"]
    assert [u["name"] for u in warehouse.options["users"]] == ["Manager", "Worker"]

    # Take the manager out of the warehouse
    manager_id = office.options["users"][0]["id"]
    await configure(fid, {"next_step_id": "user_edit"})
    result = await configure(fid, {"user": manager_id})
    defaults = {str(k): k.default() for k in result["data_schema"].schema if str(k) == "partitions"}
    assert sorted(defaults["partitions"]) == sorted([office.entry_id, warehouse.entry_id])
    await configure(fid, {"name": "Manager", **USER_FIELDS, "partitions": [office.entry_id]})
    await hass.async_block_till_done()
    assert [u["name"] for u in warehouse.options["users"]] == ["Worker"]

    # Removing a user deletes it from every partition
    worker_id = warehouse.options["users"][0]["id"]
    flow2 = await hass.config_entries.options.async_init(warehouse.entry_id)
    await configure(flow2["flow_id"], {"next_step_id": "user_remove"})
    await configure(flow2["flow_id"], {"users": [worker_id]})
    await hass.async_block_till_done()
    assert warehouse.options["users"] == []
