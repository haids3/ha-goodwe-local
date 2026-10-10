"""Test the GoodWe TOU slot sensors."""

from unittest.mock import MagicMock

from goodwe.protocol import ProtocolResponse
from goodwe.sensor import EcoModeV1, EcoModeV2
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import setup_integration

# Eco mode groups on the 745 platform: start h:m, end h:m, on/off (-7 on,
# 6 off), weekday bits (bit 0 Sunday), power x10 (negative charges), cutoff
# SOC, month bits (bit 12 limits export instead of battery discharge).
SLOTS = {
    # Charge at 100% every day from 12:00 to 15:00, on
    1: "0c000f00f97ffc1800640fff",
    # Limit export to 16% every day from 18:00 to 21:00, off
    2: "12001500067f00a000321fff",
    # Never set up
    3: "300030000600000000640000",
    # Discharge at 50% down to 30% SOC on weekdays, June to August, 17:30 to
    # 20:45, on
    4: "111e142df93e01f4001e00e0",
}


def _schedule(index: int) -> EcoModeV2:
    return EcoModeV2(f"eco_mode_{index}", 0, "Eco Mode").read_value(
        ProtocolResponse(bytes.fromhex(SLOTS[index]), None)
    )


@pytest.fixture
def tou_inverter(mock_inverter: MagicMock) -> MagicMock:
    """Give the inverter the four eco mode groups above."""

    async def read_setting(setting: str) -> object:
        return _schedule(int(setting.removeprefix("eco_mode_")))

    mock_inverter.read_setting.side_effect = read_setting
    return mock_inverter


@pytest.mark.usefixtures("tou_inverter")
async def test_tou_slots(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test each slot shows its state and schedule; unused ones start disabled."""
    await setup_integration(hass, config_entry, [Platform.SENSOR])

    slots = {}
    for index in range(1, 5):
        entity_id = f"sensor.mock_title_work_mode_tou_slot_{index}_status"
        entry = entity_registry.async_get(entity_id)
        state = hass.states.get(entity_id)
        slots[entity_id] = (
            entry.disabled_by is None,
            state.state if state else None,
            dict(state.attributes) if state else None,
        )
    assert slots == snapshot


async def test_eco_mode_v1(
    hass: HomeAssistant,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test firmware with the older eco mode groups gets no TOU slots."""
    mock_inverter.read_setting.return_value = EcoModeV1("eco_mode_1", 0, "Eco Mode")

    await setup_integration(hass, config_entry, [Platform.SENSOR])

    assert hass.states.get("sensor.mock_title_work_mode_tou_slot_1_status") is None
