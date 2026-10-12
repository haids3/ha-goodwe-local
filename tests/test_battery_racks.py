"""Test the GoodWe battery rack devices."""

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from goodwe import BatteryCluster, BatteryClusterInfo, InverterError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.goodwe_local.const import DOMAIN

from .conftest import TEST_SERIAL, setup_integration

INFO = [
    BatteryClusterInfo(
        index=1,
        serial_number="SYNTHRACK0001",
        master_version=7,
        slave_version=8,
        cells_in_series=26,
        soh=100.0,
        cycles=0,
    ),
    BatteryClusterInfo(
        index=2,
        serial_number="SYNTHRACK0002",
        master_version=7,
        slave_version=8,
        cells_in_series=26,
        soh=98.5,
        cycles=0,
    ),
]


def _rack(index: int, current: float) -> BatteryCluster:
    return BatteryCluster(
        index=index,
        status=3,
        fault=0,
        soc=88.1,
        current=current,
        voltage=88.0,
        charge_current_limit=93.0,
        discharge_current_limit=107.0,
        charged_total=1234.5,
        discharged_total=678.9,
        max_temperature=27.0,
        min_temperature=25.0,
        max_cell_voltage=3.383,
        min_cell_voltage=3.379,
    )


@pytest.fixture
def rack_inverter(mock_inverter: MagicMock) -> MagicMock:
    """Give the inverter two racks, both charging."""
    mock_inverter.read_battery_cluster_info.return_value = INFO
    mock_inverter.read_battery_clusters.return_value = [
        _rack(1, -13.72),
        _rack(2, -13.5),
    ]
    return mock_inverter


@pytest.mark.usefixtures("rack_inverter")
async def test_racks(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test each rack is a device under the battery with its readings."""
    await setup_integration(hass, config_entry, [Platform.SENSOR])

    battery = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{TEST_SERIAL}-battery"), config_entry.entry_id
    )
    racks = {}
    for index in (1, 2):
        device = device_registry.async_get_device_by_identifier(
            (DOMAIN, f"{TEST_SERIAL}-battery_rack_{index}"), config_entry.entry_id
        )
        assert device.via_device_id == battery.id
        sensors = {}
        for entry in er.async_entries_for_device(
            entity_registry, device.id, include_disabled_entities=True
        ):
            state = hass.states.get(entry.entity_id)
            sensors[entry.entity_id] = (
                state.state if state else None,
                entry.unit_of_measurement,
                entry.entity_category,
                entry.disabled_by is None,
            )
        racks[device.name] = (
            device.model,
            device.serial_number,
            device.sw_version,
            sensors,
        )
    assert racks == snapshot


async def test_rack_stops_reporting(
    hass: HomeAssistant,
    rack_inverter: MagicMock,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a rack missing from a read shows unavailable, the others don't."""
    await setup_integration(hass, config_entry, [Platform.SENSOR])
    rack_inverter.read_battery_clusters.return_value = [_rack(1, -13.72)]

    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.mock_title_battery_rack_1_power").state == "-1207"
    assert (
        hass.states.get("sensor.mock_title_battery_rack_2_power").state
        == STATE_UNAVAILABLE
    )


async def test_rack_read_fails(
    hass: HomeAssistant,
    rack_inverter: MagicMock,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test racks show unavailable while they can't be read."""
    await setup_integration(hass, config_entry, [Platform.SENSOR])
    rack_inverter.read_battery_clusters.side_effect = InverterError

    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (
        hass.states.get("sensor.mock_title_battery_rack_1_power").state
        == STATE_UNAVAILABLE
    )


@pytest.mark.parametrize(
    "info",
    [
        pytest.param({"return_value": []}, id="no_racks"),
        pytest.param({"side_effect": InverterError}, id="not_supported"),
    ],
)
async def test_no_racks(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
    info: dict,
) -> None:
    """Test batteries without racks get no rack devices."""
    mock_inverter.read_battery_cluster_info.configure_mock(**info)

    await setup_integration(hass, config_entry, [Platform.SENSOR])

    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, f"{TEST_SERIAL}-battery_rack_1"), config_entry.entry_id
        )
        is None
    )
    mock_inverter.read_battery_clusters.assert_not_awaited()
