"""Devices of a GoodWe inverter."""

from enum import StrEnum

from goodwe import Inverter

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER


class GoodweDevice(StrEnum):
    """The devices an inverter's entities are grouped on."""

    INVERTER = "inverter"
    BATTERY = "battery"
    BATTERY_2 = "battery_2"
    METER = "meter"
    WORK_MODE = "work_mode"


_SUB_DEVICES = {
    GoodweDevice.BATTERY: "Battery",
    GoodweDevice.BATTERY_2: "Battery 2",
    GoodweDevice.METER: "Smart meter",
    GoodweDevice.WORK_MODE: "Work mode",
}


def build_devices(
    entry: ConfigEntry, inverter: Inverter
) -> dict[GoodweDevice, DeviceInfo]:
    """Describe the inverter and the devices that hang off it.

    A device without entities is never registered, so every one is described.
    """
    serial = inverter.serial_number
    devices = {
        GoodweDevice.INVERTER: DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=inverter.model_name,
            sw_version=f"{inverter.firmware} / {inverter.arm_firmware}",
            serial_number=serial,
        )
    }
    for device, model in _SUB_DEVICES.items():
        devices[device] = DeviceInfo(
            identifiers={(DOMAIN, f"{serial}-{device}")},
            name=f"{entry.title} {model}",
            manufacturer=MANUFACTURER,
            model=model,
            via_device=(DOMAIN, serial),
        )
    return devices
