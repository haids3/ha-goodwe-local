"""Test the GoodWe controls option and the read-only settings."""

from unittest.mock import MagicMock

from goodwe import WorkModeSwitch
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.goodwe_local.const import CONF_ALLOW_CONTROL, PLATFORMS

from .conftest import setup_integration

SWITCH_ENTITY_ID = "switch.mock_title_work_mode_tou_mode"

V3_SWITCHES = {
    WorkModeSwitch.BACKUP: True,
    WorkModeSwitch.TOU: True,
    WorkModeSwitch.SMART_CHARGE: False,
    WorkModeSwitch.PEAK_SHAVING: False,
}


@pytest.mark.parametrize(
    "allow_control",
    [pytest.param(False, id="read_only"), pytest.param(True, id="controls")],
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
    """Test settings always show read-only, and controls only when allowed."""
    mock_inverter.get_work_mode_switches.return_value = work_mode_switches

    await setup_integration(hass, config_entry, PLATFORMS)

    assert {
        entry.entity_id: (hass.states.get(entry.entity_id).state, entry.entity_category)
        for entry in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
    } == snapshot


@pytest.mark.usefixtures("mock_switches")
async def test_allow_control_option(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    config_entry: MockConfigEntry,
) -> None:
    """Test allowing controls in the options adds them without a restart."""
    await setup_integration(hass, config_entry, PLATFORMS)
    assert hass.states.get(SWITCH_ENTITY_ID) is None

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ALLOW_CONTROL: True}
    )
    await hass.async_block_till_done()

    assert config_entry.options == {CONF_ALLOW_CONTROL: True}
    assert hass.states.get(SWITCH_ENTITY_ID)
    # The read-only view stays, so turning controls on or off removes nothing
    assert hass.states.get("binary_sensor.mock_title_work_mode_tou_mode")
