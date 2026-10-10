"""Test the GoodWe initialization."""

from unittest.mock import MagicMock, patch

from goodwe import InverterError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.goodwe_local.const import CONF_MODEL_FAMILY, DOMAIN

from .conftest import TEST_HOST, TEST_PORT


async def test_migration(
    hass: HomeAssistant,
    mock_inverter: MagicMock,
) -> None:
    """Test config entry migration."""

    config_entry = MockConfigEntry(
        version=1,
        domain=DOMAIN,
        data={
            CONF_HOST: TEST_HOST,
            CONF_MODEL_FAMILY: "MagicMock",
        },
        entry_id="3bd2acb0e4f0476d40865546d0d91921",
    )
    config_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})

    assert config_entry.version == 2
    assert config_entry.data[CONF_HOST] == TEST_HOST
    assert config_entry.data[CONF_MODEL_FAMILY] == "MagicMock"
    assert config_entry.data[CONF_PORT] == TEST_PORT


async def test_setup_connect_not_ready(hass: HomeAssistant) -> None:
    """Test that setup raises ConfigEntryNotReady when inverter is unreachable."""
    config_entry = MockConfigEntry(
        version=2,
        domain=DOMAIN,
        data={
            CONF_HOST: TEST_HOST,
            CONF_PORT: TEST_PORT,
            CONF_MODEL_FAMILY: "ET",
        },
    )
    config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.goodwe_local.connect",
            side_effect=InverterError,
        ) as mock_connect,
        patch(
            "custom_components.goodwe_local.config_flow.connect",
            side_effect=InverterError,
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    # Verify connect is called with limited retries to avoid blocking startup
    assert mock_connect.call_args.kwargs["retries"] <= 3
