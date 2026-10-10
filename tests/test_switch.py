"""Test the GoodWe switch platform."""

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from goodwe import InverterError, WorkModeSwitch
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import setup_integration

TOU_ENTITY_ID = "switch.mock_title_work_mode_tou_mode"
PEAK_SHAVING_ENTITY_ID = "switch.mock_title_work_mode_peak_shaving_mode"


@pytest.fixture
def allow_control() -> bool:
    """Switches exist only with controls allowed."""
    return True


async def _setup(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    await setup_integration(hass, config_entry, [Platform.SWITCH])


@pytest.mark.usefixtures("mock_switches")
async def test_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test a switch is created for each work mode switch."""
    await _setup(hass, config_entry)

    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


@pytest.mark.parametrize(
    "get_switches",
    [
        pytest.param({"return_value": {}}, id="unsupported"),
        pytest.param({"side_effect": InverterError}, id="read_error"),
    ],
)
async def test_no_entities(
    hass: HomeAssistant,
    mock_inverter: MagicMock,
    config_entry: MockConfigEntry,
    get_switches: dict,
) -> None:
    """Test no switches are created without work mode switches."""
    mock_inverter.get_work_mode_switches.configure_mock(**get_switches)

    await _setup(hass, config_entry)

    assert hass.states.async_entity_ids(SWITCH_DOMAIN) == []


@pytest.mark.parametrize(
    ("service", "entity_id", "switch", "enabled", "expected_state"),
    [
        pytest.param(
            SERVICE_TURN_OFF,
            TOU_ENTITY_ID,
            WorkModeSwitch.TOU,
            False,
            STATE_OFF,
            id="turn_off",
        ),
        pytest.param(
            SERVICE_TURN_ON,
            PEAK_SHAVING_ENTITY_ID,
            WorkModeSwitch.PEAK_SHAVING,
            True,
            STATE_ON,
            id="turn_on",
        ),
    ],
)
async def test_turn_on_off(
    hass: HomeAssistant,
    mock_switches: MagicMock,
    config_entry: MockConfigEntry,
    service: str,
    entity_id: str,
    switch: WorkModeSwitch,
    enabled: bool,
    expected_state: str,
) -> None:
    """Test switching a work mode sets only that switch."""
    await _setup(hass, config_entry)

    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )

    mock_switches.set_work_mode_switch.assert_awaited_once_with(switch, enabled)
    assert hass.states.get(entity_id).state == expected_state


async def test_turn_on_rejected(
    hass: HomeAssistant,
    mock_switches: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Test a work mode the inverter library rejects keeps its state."""
    mock_switches.set_work_mode_switch.side_effect = ValueError(
        "peak_shaving cannot be on together with tou"
    )
    await _setup(hass, config_entry)

    with pytest.raises(
        ServiceValidationError,
        match="peak_shaving cannot be on together with tou",
    ):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: PEAK_SHAVING_ENTITY_ID},
            blocking=True,
        )

    assert hass.states.get(PEAK_SHAVING_ENTITY_ID).state == STATE_OFF


async def test_polling(
    hass: HomeAssistant,
    mock_switches: MagicMock,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a work mode changed outside Home Assistant shows up when polled."""
    await _setup(hass, config_entry)
    mock_switches.get_work_mode_switches.return_value = {
        **mock_switches.get_work_mode_switches.return_value,
        WorkModeSwitch.TOU: False,
    }

    freezer.tick(timedelta(minutes=4))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(TOU_ENTITY_ID).state == STATE_ON

    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(TOU_ENTITY_ID).state == STATE_OFF


async def test_polling_error(
    hass: HomeAssistant,
    mock_switches: MagicMock,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a switch is unavailable while the inverter cannot be read."""
    await _setup(hass, config_entry)
    switches = mock_switches.get_work_mode_switches.return_value
    mock_switches.get_work_mode_switches.side_effect = InverterError

    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(TOU_ENTITY_ID).state == STATE_UNAVAILABLE

    mock_switches.get_work_mode_switches.side_effect = None
    mock_switches.get_work_mode_switches.return_value = switches
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(TOU_ENTITY_ID).state == STATE_ON
