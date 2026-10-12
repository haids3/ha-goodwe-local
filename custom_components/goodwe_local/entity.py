"""Devices of a GoodWe inverter."""

from enum import StrEnum

from goodwe import BatteryClusterInfo, Inverter

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
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
    hass: HomeAssistant, entry: ConfigEntry, inverter: Inverter
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
    # Sub-devices link to the inverter by registry id, so it must exist first
    inverter_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **devices[GoodweDevice.INVERTER]
    )
    for device, model in _SUB_DEVICES.items():
        devices[device] = DeviceInfo(
            identifiers={(DOMAIN, f"{serial}-{device}")},
            name=f"{entry.title} {model}",
            manufacturer=MANUFACTURER,
            model=model,
            via_device_id=inverter_device.id,
        )
    return devices


def rack_device_info(
    entry: ConfigEntry,
    inverter: Inverter,
    rack: BatteryClusterInfo,
    battery_device_id: str,
) -> DeviceInfo:
    """A battery rack, connected via the battery."""
    serial = inverter.serial_number
    return DeviceInfo(
        identifiers={(DOMAIN, f"{serial}-battery_rack_{rack.index}")},
        name=f"{entry.title} Battery rack {rack.index}",
        manufacturer=MANUFACTURER,
        model="Battery rack",
        serial_number=rack.serial_number or None,
        # The rack BMS's master and slave software versions
        sw_version=f"{rack.master_version} / {rack.slave_version}",
        via_device_id=battery_device_id,
    )
