"""Test the GoodWe controls and settings options."""

from unittest.mock import MagicMock

from goodwe import WorkModeSwitch
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.goodwe_local.const import (
    CONF_ALLOW_CONTROL,
    CONF_CHECK_FIRMWARE,
    CONF_SHOW_SETTINGS,
    DOMAIN,
    PLATFORMS,
)

from .conftest import setup_integration

SWITCH_ENTITY_ID = "switch.mock_title_work_mode_tou_mode"
BINARY_SENSOR_ENTITY_ID = "binary_sensor.mock_title_work_mode_tou_mode"
SETTING_ENTITY_ID = "sensor.mock_title_work_mode_tou_slot_1_status"

V3_SWITCHES = {
    WorkModeSwitch.BACKUP: True,
    WorkModeSwitch.TOU: True,
    WorkModeSwitch.SMART_CHARGE: False,
    WorkModeSwitch.PEAK_SHAVING: False,
}


@pytest.mark.parametrize(
    ("show_settings", "allow_control"),
    [
        pytest.param(False, False, id="readings"),
        pytest.param(True, False, id="settings"),
        pytest.param(False, True, id="controls"),
        pytest.param(True, True, id="settings_and_controls"),
    ],
)
@pytest.mark.parametrize(
    "work_mode_switches",
    [
        pytest.param({}, id="operation_mode"),
        pytest.param(V3_SWITCHES, id="work_mode_switches"),
    ],
)
async def test_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
    work_mode_switches: dict[WorkModeSwitch, bool],
    snapshot: SnapshotAssertion,
) -> None:
    """Test settings and controls show only when their option is on."""
    mock_inverter.get_work_mode_switches.return_value = work_mode_switches

    await setup_integration(hass, config_entry, PLATFORMS)

    summary = {}
    for entry in er.async_entries_for_config_entry(
        entity_registry, config_entry.entry_id
    ):
        state = hass.states.get(entry.entity_id)
        summary[entry.entity_id] = (
            state.state if state else None,
            entry.entity_category,
        )
    assert summary == snapshot


@pytest.mark.parametrize("show_settings", [False])
async def test_readings_only_skip_settings(
    hass: HomeAssistant,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test the settings aren't read when nothing shows them."""
    await setup_integration(hass, config_entry, PLATFORMS)

    mock_inverter.get_grid_export_limit.assert_not_called()
    mock_inverter.get_work_mode_switches.assert_not_called()


@pytest.mark.usefixtures("mock_switches")
async def test_allow_control_option(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Test allowing controls in the options adds them after a warning."""
    await setup_integration(hass, config_entry, PLATFORMS)
    assert hass.states.get(SWITCH_ENTITY_ID) is None

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHOW_SETTINGS: True, CONF_ALLOW_CONTROL: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm_control"
    # Nothing changes until the warning is accepted
    assert config_entry.options[CONF_ALLOW_CONTROL] is False

    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert config_entry.options == {
        CONF_SHOW_SETTINGS: True,
        CONF_CHECK_FIRMWARE: True,
        CONF_ALLOW_CONTROL: True,
    }
    assert hass.states.get(SWITCH_ENTITY_ID)
    assert hass.states.get(BINARY_SENSOR_ENTITY_ID)


@pytest.mark.parametrize(
    ("allow_control", "user_input"),
    [
        pytest.param(
            True,
            {CONF_SHOW_SETTINGS: True, CONF_ALLOW_CONTROL: True},
            id="keep_controls",
        ),
        pytest.param(
            True,
            {CONF_SHOW_SETTINGS: True, CONF_ALLOW_CONTROL: False},
            id="remove_controls",
        ),
        pytest.param(
            False,
            {CONF_SHOW_SETTINGS: False, CONF_ALLOW_CONTROL: False},
            id="hide_settings",
        ),
    ],
)
@pytest.mark.usefixtures("mock_switches")
async def test_options_without_warning(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    user_input: dict[str, bool],
) -> None:
    """Test only turning controls on asks for confirmation."""
    await setup_integration(hass, config_entry, PLATFORMS)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The firmware check defaults to on
    assert config_entry.options == {**user_input, CONF_CHECK_FIRMWARE: True}


@pytest.mark.parametrize("allow_control", [True])
@pytest.mark.usefixtures("mock_switches")
async def test_turning_options_off_removes_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test entities of an option turned off are removed, not left unavailable."""
    await setup_integration(hass, config_entry, PLATFORMS)
    work_mode_device = (DOMAIN, f"{mock_inverter.serial_number}-work_mode")
    assert device_registry.async_get_device_by_identifier(
        work_mode_device, config_entry.entry_id
    )

    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_SHOW_SETTINGS: False, CONF_ALLOW_CONTROL: False},
    )
    await hass.async_block_till_done()

    for entity_id in (SWITCH_ENTITY_ID, BINARY_SENSOR_ENTITY_ID, SETTING_ENTITY_ID):
        assert entity_registry.async_get(entity_id) is None
    assert (
        device_registry.async_get_device_by_identifier(
            work_mode_device, config_entry.entry_id
        )
        is None
    )
    # Other entities stay
    assert entity_registry.async_get("sensor.mock_title_arm_firmware")
