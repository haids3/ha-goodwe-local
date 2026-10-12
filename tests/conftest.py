"""Fixtures for the GoodWe Local tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from goodwe import Inverter, OperationMode, WorkModeSwitch
from goodwe.const import GOODWE_UDP_PORT
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from custom_components.goodwe_local.const import (
    CONF_ALLOW_CONTROL,
    CONF_CHECK_FIRMWARE,
    CONF_MODEL_FAMILY,
    CONF_SHOW_SETTINGS,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"

TEST_HOST = "1.2.3.4"
TEST_PORT = GOODWE_UDP_PORT
TEST_SERIAL = "123456789"


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Read snapshots from tests/snapshots whichever plugin loads first."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable the custom integration in every test."""


@pytest.fixture(name="mock_inverter")
def fixture_mock_inverter() -> Generator[MagicMock]:
    """Set up inverter fixture."""
    mock_inverter = MagicMock(spec=Inverter)
    mock_inverter.serial_number = TEST_SERIAL
    mock_inverter.arm_version = 1
    mock_inverter.arm_svn_version = 2
    mock_inverter.arm_firmware = "dummy.arm.version"
    mock_inverter.firmware = "dummy.fw.version"
    mock_inverter.model_name = "MOCK"
    mock_inverter.rated_power = 10000
    mock_inverter.dsp1_version = 3
    mock_inverter.dsp2_version = 4
    mock_inverter.dsp_svn_version = 5

    mock_inverter.sensors.return_value = ()
    mock_inverter.settings.return_value = ()
    mock_inverter.read_runtime_data = AsyncMock(return_value={})
    mock_inverter.get_grid_export_limit = AsyncMock(return_value=10000)
    mock_inverter.get_ongrid_battery_dod = AsyncMock(return_value=50)
    mock_inverter.get_work_mode_switches = AsyncMock(return_value={})
    mock_inverter.read_setting = AsyncMock(return_value=62)
    mock_inverter.read_battery_cluster_info = AsyncMock(return_value=[])
    mock_inverter.read_battery_clusters = AsyncMock(return_value=[])
    mock_inverter.get_operation_mode = AsyncMock(return_value=OperationMode.GENERAL)
    mock_inverter.get_operation_modes = AsyncMock(
        return_value=(OperationMode.GENERAL, OperationMode.ECO)
    )

    with (
        patch(
            "custom_components.goodwe_local.config_flow.connect",
            return_value=mock_inverter,
        ),
        patch("custom_components.goodwe_local.connect", return_value=mock_inverter),
    ):
        yield mock_inverter


@pytest.fixture
def mock_switches(mock_inverter: MagicMock) -> MagicMock:
    """Give the inverter work mode 3.0 switches with TOU on."""
    switches = {
        WorkModeSwitch.BACKUP: False,
        WorkModeSwitch.TOU: True,
        WorkModeSwitch.SMART_CHARGE: False,
        WorkModeSwitch.PEAK_SHAVING: False,
    }
    mock_inverter.get_work_mode_switches.return_value = switches
    # Home Assistant reads the switches back after changing one
    mock_inverter.set_work_mode_switch.side_effect = switches.__setitem__
    return mock_inverter


@pytest.fixture
def allow_control() -> bool:
    """Whether the entry allows controls; off, as for a new entry."""
    return False


@pytest.fixture
def show_settings() -> bool:
    """Whether the entry shows the stored settings; on, unlike a new entry."""
    return True


@pytest.fixture
def check_firmware() -> bool:
    """Whether the entry checks for firmware updates; on, as for a new entry."""
    return True


@pytest.fixture
def config_entry(
    allow_control: bool, show_settings: bool, check_firmware: bool
) -> MockConfigEntry:
    """Return a GoodWe config entry."""
    return MockConfigEntry(
        version=2,
        domain=DOMAIN,
        data={CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT, CONF_MODEL_FAMILY: "ET"},
        options={
            CONF_ALLOW_CONTROL: allow_control,
            CONF_SHOW_SETTINGS: show_settings,
            CONF_CHECK_FIRMWARE: check_firmware,
        },
    )


async def setup_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    platforms: list[Platform],
) -> None:
    """Set up the entry with only the given platforms."""
    config_entry.add_to_hass(hass)
    with patch("custom_components.goodwe_local.PLATFORMS", platforms):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
