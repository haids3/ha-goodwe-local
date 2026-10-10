"""Fixtures for the GoodWe Local tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from goodwe import Inverter
from goodwe.const import GOODWE_UDP_PORT
import pytest
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

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

    mock_inverter.read_runtime_data = AsyncMock(return_value={})
    mock_inverter.get_work_mode_switches = AsyncMock(return_value={})

    with (
        patch(
            "custom_components.goodwe_local.config_flow.connect",
            return_value=mock_inverter,
        ),
        patch("custom_components.goodwe_local.connect", return_value=mock_inverter),
    ):
        yield mock_inverter
