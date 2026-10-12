"""Test the GoodWe TOU slot sensors."""

from unittest.mock import MagicMock

from goodwe.protocol import ProtocolResponse
from goodwe.sensor import EcoModeV1, EcoModeV2
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.goodwe_local.sensor import _days
from custom_components.goodwe_local.tou import TouSlot

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


def _schedule_from(data: str) -> EcoModeV2:
    return EcoModeV2("eco_mode", 0, "Eco Mode").read_value(
        ProtocolResponse(bytes.fromhex(data), None)
    )


@pytest.fixture
def slots() -> dict[int, str]:
    """The groups the inverter holds; tests may change them after setup."""
    return dict(SLOTS)


@pytest.fixture
def tou_inverter(mock_inverter: MagicMock, slots: dict[int, str]) -> MagicMock:
    """Give the inverter the four eco mode groups above."""

    async def read_setting(setting: str) -> object:
        return _schedule_from(slots[int(setting.removeprefix("eco_mode_"))])

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


@pytest.mark.usefixtures("tou_inverter")
async def test_tou_slot_fields(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test each slot's settings show as read-only diagnostic sensors."""
    await setup_integration(hass, config_entry, [Platform.SENSOR])

    fields = {}
    for entry in er.async_entries_for_config_entry(
        entity_registry, config_entry.entry_id
    ):
        if "tou_slot" not in entry.unique_id:
            continue
        state = hass.states.get(entry.entity_id)
        fields[entry.entity_id] = (
            state.state if state else None,
            entry.unit_of_measurement,
            entry.entity_category,
            entry.disabled_by is None,
        )
    assert fields == snapshot


@pytest.mark.parametrize(
    ("has_work_mode_v3", "expected"),
    [
        pytest.param(False, {1: True, 2: True, 3: False, 4: True}, id="four_slots"),
        pytest.param(
            True,
            {
                1: True,
                2: True,
                3: False,
                4: True,
                5: False,
                6: False,
                7: True,
                8: False,
            },
            id="work_mode_v3",
        ),
    ],
)
async def test_work_mode_v3_slots(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    tou_inverter: MagicMock,
    slots: dict[int, str],
    config_entry: MockConfigEntry,
    has_work_mode_v3: bool,
    expected: dict[int, bool],
) -> None:
    """Test work mode 3.0 has 8 slots, and empty groups start disabled."""
    tou_inverter.has_work_mode_v3 = has_work_mode_v3
    slots.update(
        {
            # As read from a work mode 3.0 EHA that never used these groups
            5: "000000005500000000000000",
            6: "000000000000000000000000",
            # Discharge at 50% down to 30% SOC every day, 08:00 to 10:00, on
            7: "08000a00f97f01f4001e0fff",
            8: "000000000000000000000000",
        }
    )

    await setup_integration(hass, config_entry, [Platform.SENSOR])

    enabled = {}
    for index in range(1, 9):
        entry = entity_registry.async_get(
            f"sensor.mock_title_work_mode_tou_slot_{index}_status"
        )
        if entry is not None:
            enabled[index] = entry.disabled_by is None
    assert enabled == expected


async def test_eco_mode_v1(
    hass: HomeAssistant,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test firmware with the older eco mode groups gets no TOU slots."""
    mock_inverter.read_setting.return_value = EcoModeV1("eco_mode_1", 0, "Eco Mode")

    await setup_integration(hass, config_entry, [Platform.SENSOR])

    assert hass.states.get("sensor.mock_title_work_mode_tou_slot_1_status") is None


@pytest.mark.usefixtures("tou_inverter")
@pytest.mark.parametrize("allow_control", [True])
@pytest.mark.parametrize(
    ("service", "slot", "written"),
    [
        pytest.param(SERVICE_TURN_OFF, 1, 6, id="turn_off"),
        pytest.param(SERVICE_TURN_ON, 2, -7, id="turn_on"),
    ],
)
async def test_tou_slot_switch(
    hass: HomeAssistant,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
    service: str,
    slot: int,
    written: int,
) -> None:
    """Test a slot switch writes only the slot's on/off byte."""
    await setup_integration(hass, config_entry, [Platform.SWITCH])

    await hass.services.async_call(
        SWITCH_DOMAIN,
        service,
        {ATTR_ENTITY_ID: f"switch.mock_title_work_mode_tou_slot_{slot}"},
        blocking=True,
    )

    mock_inverter.write_setting.assert_awaited_once_with(
        f"eco_mode_{slot}_switch", written
    )


@pytest.mark.usefixtures("tou_inverter")
@pytest.mark.parametrize("allow_control", [True])
async def test_unused_slot_switch(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    config_entry: MockConfigEntry,
) -> None:
    """Test a slot without times starts disabled and can't be switched."""
    await setup_integration(hass, config_entry, [Platform.SWITCH])
    entity_id = "switch.mock_title_work_mode_tou_slot_3"
    assert entity_registry.async_get(entity_id).disabled_by is not None

    entity_registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


@pytest.mark.usefixtures("tou_inverter")
@pytest.mark.parametrize("allow_control", [True])
@pytest.mark.parametrize(
    ("group", "error"),
    [
        pytest.param(SLOTS[3], "set it up in the GoodWe app first", id="cleared"),
        pytest.param(
            "12001500fc7f001000320000", "holds a peak_shaving schedule", id="peak"
        ),
    ],
)
async def test_tou_slot_switch_rejected(
    hass: HomeAssistant,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
    slots: dict[int, str],
    group: str,
    error: str,
) -> None:
    """Test a slot changed in the app since the last read is not written."""
    await setup_integration(hass, config_entry, [Platform.SWITCH])
    slots[2] = group

    with pytest.raises(ServiceValidationError, match=error):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.mock_title_work_mode_tou_slot_2"},
            blocking=True,
        )

    mock_inverter.write_setting.assert_not_awaited()


@pytest.mark.parametrize(
    ("day_bits", "expected"),
    [
        pytest.param(0x41, "Weekends", id="weekends"),
        pytest.param(0x2B, "Mon, Wed, Fri, Sun", id="list"),
        pytest.param(0x00, "No days", id="none"),
    ],
)
def test_days(day_bits: int, expected: str) -> None:
    """Test day sets read as the GoodWe apps list them."""
    slot = TouSlot.from_schedule(
        1, _schedule_from(f"0c000f00f9{day_bits:02x}fc1800640fff")
    )

    assert _days(slot) == expected
