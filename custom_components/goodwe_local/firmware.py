"""Ask GoodWe whether newer inverter firmware exists, as the SEMS+ app does.

The app checks before anyone signs in, with a token built into it; this
sends the same request: the inverter's serial and its DSP and ARM versions.
The endpoint is undocumented, so GoodWe may change it at any time.
"""

from dataclasses import dataclass
import json
import re
from typing import Any, Self

from aiohttp import ClientError, ClientSession, ClientTimeout
from goodwe import Inverter

CHECK_URL = "https://solargo.sems.com.cn/api/Solargo/CheckUpgradePlus_v3"
# The app's token before sign-in
_TOKEN = json.dumps(
    {
        "uid": "",
        "token": "a5b3t89bf7",
        "projectname": "pvmaster",
        "timestamp": 0,
        "client": "semsplus_android",
        "language": "en",
    },
    separators=(",", ":"),
)
_TIMEOUT = ClientTimeout(total=30)

FIRMWARE_DSP = 1
FIRMWARE_ARM = 2
# Mandatory updates have upgrade type 2; optional ones 0
_MANDATORY = 2

# "04082-07-S08": the version is the middle part
_VERSION = re.compile(r"^(\d+-(\d+))-")
# "410-02169-07(140)OL-R-APP_20260901161411204.bin"
_FILE_VERSION = re.compile(r"-(\d+-\d+)\(")


class FirmwareCheckError(Exception):
    """GoodWe could not answer whether newer firmware exists."""


@dataclass(frozen=True, slots=True)
class InstalledFirmware:
    """The inverter's DSP and ARM firmware, as the check sends them."""

    dsp: str
    dsp_version: int
    dsp_svn: int
    arm: str
    arm_version: int
    arm_svn: int

    @classmethod
    def from_inverter(cls, inverter: Inverter) -> Self | None:
        """Read the versions from the firmware strings; None if they differ in form."""
        dsp = _VERSION.match(inverter.firmware or "")
        arm = _VERSION.match(inverter.arm_firmware or "")
        if dsp is None or arm is None:
            return None
        return cls(
            dsp=inverter.firmware,
            dsp_version=int(dsp.group(2)),
            dsp_svn=inverter.dsp_svn_version or 0,
            arm=inverter.arm_firmware,
            arm_version=int(arm.group(2)),
            arm_svn=inverter.arm_svn_version or 0,
        )

    @property
    def summary(self) -> str:
        """Both versions, as the device shows them."""
        return f"{self.dsp} / {self.arm}"


@dataclass(frozen=True, slots=True)
class FirmwareRelease:
    """Newer firmware for one of the inverter's modules."""

    firmware_type: int
    version: str
    file_name: str
    mandatory: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        """Convert one item of the check's answer."""
        file_name = str(data.get("flashFileName") or "")
        if match := _FILE_VERSION.search(file_name):
            version = match.group(1)
        else:
            version = f"version {data.get('flashVersion')}"
        return cls(
            firmware_type=int(data.get("flashType") or 0),
            version=version,
            file_name=file_name,
            mandatory=data.get("upgradeType") == _MANDATORY,
        )


async def async_check_firmware(
    session: ClientSession, serial: str, installed: InstalledFirmware
) -> list[FirmwareRelease]:
    """Return the newer firmware GoodWe offers; empty when up to date."""
    body = [
        {
            "sn": serial,
            "type": "1",
            "firmwares": [
                {
                    "FirmwareType": str(FIRMWARE_DSP),
                    "FirmwareVersion": f"{installed.dsp_version:02d}",
                    "svnVersion": str(installed.dsp_svn),
                },
                {
                    "FirmwareType": str(FIRMWARE_ARM),
                    "FirmwareVersion": f"{installed.arm_version:02d}",
                    "svnVersion": str(installed.arm_svn),
                },
            ],
        }
    ]
    try:
        async with session.post(
            CHECK_URL, json=body, headers={"Token": _TOKEN}, timeout=_TIMEOUT
        ) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    except (ClientError, TimeoutError, ValueError) as err:
        raise FirmwareCheckError(err) from err
    if not isinstance(data, dict) or str(data.get("code")) != "0":
        raise FirmwareCheckError(
            data.get("msg") if isinstance(data, dict) else "unexpected answer"
        )
    return [
        FirmwareRelease.from_api(item)
        for item in data.get("data") or []
        if isinstance(item, dict)
    ]
