"""Test the Goodwe config flow."""

from ipaddress import ip_address
from unittest.mock import MagicMock, patch

from goodwe import InverterError
from goodwe.const import GOODWE_TCP_PORT, GOODWE_UDP_PORT
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from custom_components.goodwe_local.const import (
    CONF_MODEL_FAMILY,
    DEFAULT_NAME,
    DOMAIN,
)

from .conftest import TEST_SERIAL

TEST_HOST = "1.2.3.4"
TEST_PORT = GOODWE_UDP_PORT


async def test_manual_setup(hass: HomeAssistant, mock_inverter: MagicMock) -> None:
    """Test manually setting up."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result["errors"]

    with (
        patch(
            "custom_components.goodwe_local.async_setup_entry", return_value=True
        ) as mock_setup_entry,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: TEST_HOST}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert result["data"] == {
        CONF_HOST: TEST_HOST,
        CONF_PORT: TEST_PORT,
        CONF_MODEL_FAMILY: "MagicMock",
    }
    assert len(mock_setup_entry.mock_calls) == 1


async def test_manual_setup_already_exists(
    hass: HomeAssistant, mock_inverter: MagicMock
) -> None:
    """Test manually setting up and the device already exists."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: TEST_HOST},
        unique_id=TEST_SERIAL,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result["errors"]

    with patch("custom_components.goodwe_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: TEST_HOST}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_manual_setup_device_offline(hass: HomeAssistant) -> None:
    """Test manually setting up, device offline."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result["errors"]

    with patch(
        "custom_components.goodwe_local.config_flow.connect",
        side_effect=InverterError,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: TEST_HOST}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "connection_error"}


def _zeroconf_info(properties: dict[str, str]) -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(TEST_HOST),
        ip_addresses=[ip_address(TEST_HOST)],
        hostname="72101WLA00000000.local.",
        name="72101WLA00000000._goodwe._tcp.local.",
        port=502,
        type="_goodwe._tcp.local.",
        properties=properties,
    )


ZEROCONF_INFO = _zeroconf_info(
    {
        "device_type": "goodwe_mdns_2",
        "board": "72101WLA00000000",
        "inverter-modbustcp-port": "502",
        "datalogger-modbustcp-port": "502",
    }
)


@pytest.mark.parametrize(
    ("discovery_info", "tcp_error", "port"),
    [
        pytest.param(ZEROCONF_INFO, [], GOODWE_TCP_PORT, id="modbus-tcp"),
        pytest.param(
            _zeroconf_info({"inverter-modbustcp-port": "not-a-port"}),
            [],
            GOODWE_TCP_PORT,
            id="bad-port-record",
        ),
        pytest.param(ZEROCONF_INFO, [InverterError], GOODWE_UDP_PORT, id="udp"),
    ],
)
async def test_zeroconf_discovery(
    hass: HomeAssistant,
    mock_inverter: MagicMock,
    discovery_info: ZeroconfServiceInfo,
    tcp_error: list[type[Exception]],
    port: int,
) -> None:
    """A discovered dongle is set up after confirming, over TCP or else UDP."""
    with patch(
        "custom_components.goodwe_local.config_flow.connect",
        side_effect=[*tcp_error, mock_inverter],
    ) as mock_connect:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=discovery_info
        )
    assert mock_connect.call_args.kwargs["port"] == port
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"] == {
        "serial_number": TEST_SERIAL,
        "host": TEST_HOST,
    }

    with patch("custom_components.goodwe_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert result["result"].unique_id == TEST_SERIAL
    assert result["data"] == {
        CONF_HOST: TEST_HOST,
        CONF_PORT: port,
        CONF_MODEL_FAMILY: "MagicMock",
    }


async def test_zeroconf_cannot_connect(hass: HomeAssistant) -> None:
    """A dongle whose inverter does not answer is not offered."""
    with patch(
        "custom_components.goodwe_local.config_flow.connect",
        side_effect=InverterError,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF_INFO
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_zeroconf_host_already_configured(
    hass: HomeAssistant, mock_inverter: MagicMock
) -> None:
    """A known host is not contacted again."""
    MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: TEST_HOST}, unique_id=TEST_SERIAL
    ).add_to_hass(hass)

    with patch(
        "custom_components.goodwe_local.config_flow.connect",
        return_value=mock_inverter,
    ) as mock_connect:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF_INFO
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_connect.assert_not_called()


@pytest.mark.usefixtures("mock_inverter")
async def test_zeroconf_updates_moved_inverter(hass: HomeAssistant) -> None:
    """A configured inverter found at a new address gets its host updated."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "1.1.1.1", CONF_PORT: GOODWE_UDP_PORT},
        unique_id=TEST_SERIAL,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF_INFO
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == TEST_HOST
    # The configured transport is kept; the inverter may answer on both.
    assert entry.data[CONF_PORT] == GOODWE_UDP_PORT
