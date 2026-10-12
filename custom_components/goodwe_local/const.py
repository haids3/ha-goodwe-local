"""Constants for the Goodwe component."""

from datetime import timedelta

from goodwe import OperationMode

from homeassistant.const import Platform

DOMAIN = "goodwe_local"

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

DEFAULT_NAME = "GoodWe"
MANUFACTURER = "GoodWe"
SCAN_INTERVAL = timedelta(seconds=10)
# Picks up changes made in the GoodWe apps without adding much Modbus traffic
SETTINGS_SCAN_INTERVAL = timedelta(minutes=5)
# Six racks are six requests, so they are read less often than the runtime data
BATTERY_RACK_SCAN_INTERVAL = timedelta(seconds=60)
FIRMWARE_CHECK_INTERVAL = timedelta(days=1)

CONF_MODEL_FAMILY = "model_family"
CONF_ALLOW_CONTROL = "allow_control"
CONF_SHOW_SETTINGS = "show_settings"
CONF_CHECK_FIRMWARE = "check_firmware"

MODE_TO_OPTION: dict[OperationMode, str] = {
    OperationMode.GENERAL: "general",
    OperationMode.OFF_GRID: "off_grid",
    OperationMode.BACKUP: "backup",
    OperationMode.ECO: "eco",
    OperationMode.PEAK_SHAVING: "peak_shaving",
    OperationMode.ECO_CHARGE: "eco_charge",
    OperationMode.ECO_DISCHARGE: "eco_discharge",
}
