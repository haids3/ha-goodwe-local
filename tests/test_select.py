"""Test the GoodWe select platform."""

from unittest.mock import MagicMock, patch

from goodwe import InverterError, OperationMode, WorkModeSwitch
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from custom_components.goodwe_local import CONF_MODEL_FAMILY, DOMAIN

from .conftest import TEST_HOST, TEST_PORT

ENTITY_ID = "select.mock_title_inverter_operation_mode"


@pytest.mark.parametrize(
    ("get_switches", "expected_entities"),
    [
        pytest.param({"return_value": {}}, [ENTITY_ID], id="no_switches"),
        pytest.param({"side_effect": InverterError}, [ENTITY_ID], id="read_error"),
        pytest.param(
            {"return_value": {WorkModeSwitch.TOU: True}}, [], id="work_mode_switches"
        ),
    ],
)
async def test_operation_mode_replaced_by_switches(
    hass: HomeAssistant,
    mock_inverter: MagicMock,
    get_switches: dict,
    expected_entities: list[str],
) -> None:
    """Test the operation mode select is only added without work mode switches."""
    mock_inverter.get_work_mode_switches.configure_mock(**get_switches)
    mock_inverter.get_operation_modes.return_value = (
        OperationMode.GENERAL,
        OperationMode.ECO,
    )
    mock_inverter.get_operation_mode.return_value = OperationMode.GENERAL
    config_entry = MockConfigEntry(
        version=2,
        domain=DOMAIN,
        data={CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT, CONF_MODEL_FAMILY: "ET"},
    )
    config_entry.add_to_hass(hass)

    with patch("custom_components.goodwe_local.PLATFORMS", [Platform.SELECT]):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.async_entity_ids(SELECT_DOMAIN) == expected_entities
