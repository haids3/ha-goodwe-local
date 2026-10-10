"""Test the GoodWe sensor platform."""

from typing import Any
from unittest.mock import MagicMock

from goodwe import Inverter
from goodwe.et import ET
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import TEST_SERIAL, setup_integration

# A battery charging from PV while the house imports a little from the grid.
# Sensors not listed read 0.
RUNTIME_DATA: dict[str, Any] = {
    "ppv": 3000,
    "ppv3": 1600,
    "ppv4": 1400,
    "vpv3": 380.0,
    "ipv3": 4.2,
    "pv3_mode": 2,
    "pv4_mode": 2,
    "active_power": -200,
    "active_power_total": -210,
    "meter_active_power_total": -210,
    "house_consumption": 1200,
    "pbattery1": -2000,
    "battery_soc": 60,
    "battery_mode": 3,
    "work_mode": 1,
    "grid_mode": 1,
    "grid_in_out": 2,
    "e_day": 12.5,
    "e_total": 1000.0,
    "meter_e_total_exp": 400.0,
    "meter_e_total_imp": 300.0,
    "e_bat_charge_total": 500.0,
    "e_bat_discharge_total": 450.0,
    "errors": "",
    "diagnose_result_label": "",
    "timestamp": None,
}


def _et_sensors() -> list:
    inverter = ET("127.0.0.1", 502)
    inverter._has_battery = True
    inverter._has_mppt = True
    return list(inverter.sensors())


@pytest.fixture
def et_inverter(mock_inverter: MagicMock) -> MagicMock:
    """Make the mock an ET inverter with every ET sensor."""
    mock_inverter.__class__ = type("MockET", (MagicMock, ET), {})
    sensors = _et_sensors()
    mock_inverter.sensors.return_value = sensors
    mock_inverter.read_runtime_data.return_value = {
        sensor.id_: RUNTIME_DATA.get(sensor.id_, 0) for sensor in sensors
    }
    return mock_inverter


def _summary(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    config_entry: MockConfigEntry,
) -> dict[str, tuple]:
    """Each entity's device, state and whether it is shown by default."""
    summary = {}
    for entry in er.async_entries_for_config_entry(
        entity_registry, config_entry.entry_id
    ):
        state = hass.states.get(entry.entity_id)
        device = device_registry.async_get(entry.device_id)
        summary[entry.entity_id] = (
            device.name,
            state.state if state else None,
            entry.unit_of_measurement,
            entry.entity_category,
            entry.disabled_by is None,
        )
    return summary


@pytest.mark.usefixtures("et_inverter")
async def test_et_sensors(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test ET sensors get curated names, devices and visibility."""
    await setup_integration(hass, config_entry, [Platform.SENSOR])

    assert _summary(hass, entity_registry, device_registry, config_entry) == snapshot


@pytest.mark.usefixtures("et_inverter")
@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        pytest.param("sensor.mock_title_grid_power", "200", id="import_positive"),
        pytest.param("sensor.mock_title_battery_power", "-2000", id="charging"),
        pytest.param("sensor.mock_title_status", "running", id="status"),
        pytest.param("sensor.mock_title_grid", "on_grid", id="grid"),
        pytest.param("sensor.mock_title_battery_status", "charging", id="battery"),
        pytest.param("sensor.mock_title_battery_state_of_charge", "60", id="soc"),
    ],
)
async def test_et_values(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_id: str,
    expected: str,
) -> None:
    """Test values are signed and labelled as in the GoodWe apps."""
    await setup_integration(hass, config_entry, [Platform.SENSOR])

    assert hass.states.get(entity_id).state == expected


async def test_unknown_code(
    hass: HomeAssistant,
    et_inverter: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test a status code the table does not know shows as unknown."""
    et_inverter.read_runtime_data.return_value["work_mode"] = 99

    await setup_integration(hass, config_entry, [Platform.SENSOR])

    assert hass.states.get("sensor.mock_title_status").state == "unknown"


async def test_other_family(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test families without a table keep library names, main sensors shown."""
    sensors = {sensor.id_: sensor for sensor in _et_sensors()}
    mock_inverter.sensors.return_value = [
        sensors["ppv"],
        sensors["bus_voltage"],
        sensors["battery_temperature"],
        sensors["meter_freq"],
    ]
    mock_inverter.read_runtime_data.return_value = {"ppv": 3000}
    assert not isinstance(mock_inverter, ET)
    assert isinstance(mock_inverter, Inverter)

    await setup_integration(hass, config_entry, [Platform.SENSOR])

    entries = {
        entry.unique_id: entry
        for entry in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
    }
    assert {
        unique_id.removeprefix(f"{TEST_SERIAL}-"): (
            entry.original_name,
            entry.disabled_by is None,
        )
        for unique_id, entry in entries.items()
        if "-setting_" not in unique_id
    } == {
        "ppv": ("PV Power", True),
        "bus_voltage": ("Bus Voltage", False),
        "battery_temperature": ("Battery Temperature", False),
        "meter_freq": ("Meter Frequency", False),
    }
