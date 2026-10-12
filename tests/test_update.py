"""Test the GoodWe firmware update check."""

import json
from typing import Any
from unittest.mock import MagicMock

from aiohttp import ClientError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from homeassistant.components.update import ATTR_LATEST_VERSION, ATTR_RELEASE_SUMMARY
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.goodwe_local.firmware import CHECK_URL

from .conftest import TEST_SERIAL, setup_integration

ENTITY_ID = "update.mock_title_firmware"
INSTALLED = "04082-07-S08 / 02169-06-S01"

ARM_RELEASE = {
    "flashId": "17ec78d987c89724ea507e8a6d9fb04a",
    "flashType": 2,
    "flashFileName": "410-02169-07(140)OL-R-APP_20261001120000000.bin",
    "ossAddress": [
        "http://iot-eu.oss-eu-central-1.aliyuncs.com/410-02169-07(140)OL-R-APP_20261001120000000.bin"
    ],
    "flashVersion": 7.0,
    "inverterTypes": "NAH,NBO",
    "upgradeType": 0,
}


@pytest.fixture
def firmware_inverter(mock_inverter: MagicMock) -> MagicMock:
    """Give the inverter the firmware of a work mode 3.0 EHA."""
    mock_inverter.firmware = "04082-07-S08"
    mock_inverter.arm_firmware = "02169-06-S01"
    mock_inverter.dsp_svn_version = 7008
    mock_inverter.arm_svn_version = 135
    return mock_inverter


def _answer(data: list[dict[str, Any]], code: str = "0") -> dict[str, Any]:
    return {"hasError": code != "0", "msg": "success", "code": code, "data": data}


async def _setup(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    await setup_integration(hass, config_entry, [Platform.UPDATE])
    # The check runs in the background
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.usefixtures("firmware_inverter")
@pytest.mark.parametrize(
    ("releases", "state", "latest", "summary"),
    [
        pytest.param([], STATE_OFF, INSTALLED, None, id="up_to_date"),
        pytest.param(
            [ARM_RELEASE],
            STATE_ON,
            "04082-07-S08 / 02169-07",
            "Optional update: 410-02169-07(140)OL-R-APP_20261001120000000.bin. "
            "Install it with the GoodWe app or ask your installer.",
            id="optional",
        ),
        pytest.param(
            [{**ARM_RELEASE, "upgradeType": 2}],
            STATE_ON,
            "04082-07-S08 / 02169-07",
            "Mandatory update: 410-02169-07(140)OL-R-APP_20261001120000000.bin. "
            "Install it with the GoodWe app or ask your installer.",
            id="mandatory",
        ),
    ],
)
async def test_firmware_check(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    releases: list[dict[str, Any]],
    state: str,
    latest: str,
    summary: str | None,
) -> None:
    """Test the entity shows whether GoodWe offers newer firmware."""
    aioclient_mock.post(CHECK_URL, json=_answer(releases))

    await _setup(hass, config_entry)

    entity = hass.states.get(ENTITY_ID)
    assert entity.state == state
    assert entity.attributes["installed_version"] == INSTALLED
    assert entity.attributes[ATTR_LATEST_VERSION] == latest
    assert entity.attributes[ATTR_RELEASE_SUMMARY] == summary
    # Check only: there is nothing to install from here
    assert entity.attributes["supported_features"] == 0


@pytest.mark.usefixtures("firmware_inverter")
async def test_firmware_check_request(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Test the check sends the serial and versions as the GoodWe app does."""
    aioclient_mock.post(CHECK_URL, json=_answer([]))

    await _setup(hass, config_entry)

    assert aioclient_mock.call_count == 1
    _, _, body, headers = aioclient_mock.mock_calls[0]
    assert body == [
        {
            "sn": TEST_SERIAL,
            "type": "1",
            "firmwares": [
                {"FirmwareType": "1", "FirmwareVersion": "07", "svnVersion": "7008"},
                {"FirmwareType": "2", "FirmwareVersion": "06", "svnVersion": "135"},
            ],
        }
    ]
    assert json.loads(headers["Token"])["uid"] == ""


@pytest.mark.usefixtures("firmware_inverter")
@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"status": 500}, id="http_error"),
        pytest.param({"json": _answer([], code="100001")}, id="error_code"),
        pytest.param({"exc": ClientError()}, id="connection_error"),
        pytest.param({"text": "not json"}, id="not_json"),
    ],
)
async def test_firmware_check_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    response: dict[str, Any],
) -> None:
    """Test a failed check leaves the entity unavailable, not wrong."""
    aioclient_mock.post(CHECK_URL, **response)

    await _setup(hass, config_entry)

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("check_firmware", "firmware"),
    [
        pytest.param(False, "04082-07-S08", id="turned_off"),
        pytest.param(True, "dummy.fw.version", id="unknown_version_form"),
    ],
)
async def test_no_firmware_check(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    aioclient_mock: AiohttpClientMocker,
    firmware_inverter: MagicMock,
    config_entry: MockConfigEntry,
    firmware: str,
) -> None:
    """Test nothing is sent, and no entity made, without a check."""
    firmware_inverter.firmware = firmware

    await _setup(hass, config_entry)

    assert entity_registry.async_get(ENTITY_ID) is None
    assert aioclient_mock.call_count == 0
