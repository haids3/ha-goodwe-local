"""Constants for the Goodwe component."""

from datetime import timedelta

from goodwe import OperationMode

from homeassistant.const import Platform

DOMAIN = "goodwe_local"

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

DEFAULT_NAME = "GoodWe"
SCAN_INTERVAL = timedelta(seconds=10)
# Picks up changes made in the GoodWe apps without adding much Modbus traffic
SETTINGS_SCAN_INTERVAL = timedelta(minutes=5)

CONF_MODEL_FAMILY = "model_family"
CONF_ALLOW_CONTROL = "allow_control"

MODE_TO_OPTION: dict[OperationMode, str] = {
    OperationMode.GENERAL: "general",
    OperationMode.OFF_GRID: "off_grid",
    OperationMode.BACKUP: "backup",
    OperationMode.ECO: "eco",
    OperationMode.PEAK_SHAVING: "peak_shaving",
    OperationMode.ECO_CHARGE: "eco_charge",
    OperationMode.ECO_DISCHARGE: "eco_discharge",
}
