"""Test the GoodWe select platform."""

from unittest.mock import MagicMock

from goodwe import InverterError, OperationMode, WorkModeSwitch
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant

from .conftest import setup_integration

ENTITY_ID = "select.mock_title_inverter_operation_mode"


@pytest.fixture
def allow_control() -> bool:
    """Selects exist only with controls allowed."""
    return True


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
    config_entry: MockConfigEntry,
    get_switches: dict,
    expected_entities: list[str],
) -> None:
    """Test the operation mode select is only added without work mode switches."""
    mock_inverter.get_work_mode_switches.configure_mock(**get_switches)

    await setup_integration(hass, config_entry, [Platform.SELECT])

    assert hass.states.async_entity_ids(SELECT_DOMAIN) == expected_entities


async def test_select_option(
    hass: HomeAssistant,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test selecting a mode writes it and shows the mode read back."""
    await setup_integration(hass, config_entry, [Platform.SELECT])
    state = hass.states.get(ENTITY_ID)
    assert state.state == "general"
    assert state.attributes[ATTR_OPTIONS] == ["general", "eco"]
    mock_inverter.get_operation_mode.return_value = OperationMode.ECO

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_OPTION: "eco"},
        blocking=True,
    )

    mock_inverter.set_operation_mode.assert_awaited_once_with(OperationMode.ECO)
    assert hass.states.get(ENTITY_ID).state == "eco"
