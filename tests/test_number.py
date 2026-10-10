"""Test the GoodWe number platform."""

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.goodwe_local.const import DOMAIN

from .conftest import TEST_SERIAL, setup_integration

EXPORT_LIMIT_ENTITY_ID = "number.mock_title_grid_export_limit"


@pytest.fixture
def allow_control() -> bool:
    """Numbers exist only with controls allowed."""
    return True


@pytest.mark.parametrize(
    ("rated_power", "expected_max"),
    [
        pytest.param(29900, 29900, id="above_default_max"),
        pytest.param(5000, 10000, id="below_default_max"),
    ],
)
async def test_grid_export_limit_max(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
    rated_power: int,
    expected_max: int,
) -> None:
    """Test the export limit in watts goes up to the rated power of the inverter."""
    mock_inverter.rated_power = rated_power
    mock_inverter.get_grid_export_limit.return_value = 14400

    await setup_integration(hass, config_entry, [Platform.NUMBER])

    entity_id = entity_registry.async_get_entity_id(
        Platform.NUMBER, DOMAIN, f"{TEST_SERIAL}-grid_export_limit"
    )
    assert entity_id
    state = hass.states.get(entity_id)
    assert state
    assert state.attributes[ATTR_MAX] == expected_max


async def test_set_value(
    hass: HomeAssistant,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test setting a number writes it and shows the value read back."""
    await setup_integration(hass, config_entry, [Platform.NUMBER])
    assert hass.states.get(EXPORT_LIMIT_ENTITY_ID).state == "10000.0"
    mock_inverter.get_grid_export_limit.return_value = 5000

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: EXPORT_LIMIT_ENTITY_ID, ATTR_VALUE: 5000},
        blocking=True,
    )

    mock_inverter.set_grid_export_limit.assert_awaited_once_with(5000)
    assert hass.states.get(EXPORT_LIMIT_ENTITY_ID).state == "5000.0"
