"""Update coordinator for Goodwe."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Any, override

from goodwe import (
    BatteryCluster,
    BatteryClusterInfo,
    Inverter,
    InverterError,
    RequestFailedException,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BATTERY_RACK_SCAN_INTERVAL,
    FIRMWARE_CHECK_INTERVAL,
    SCAN_INTERVAL,
    SETTINGS_SCAN_INTERVAL,
)
from .entity import GoodweDevice
from .firmware import (
    FirmwareCheckError,
    FirmwareRelease,
    InstalledFirmware,
    async_check_firmware,
)
from .tou import async_read_tou_slots

_LOGGER = logging.getLogger(__name__)

type GoodweConfigEntry = ConfigEntry[GoodweRuntimeData]


@dataclass
class GoodweRuntimeData:
    """Data class for runtime data."""

    inverter: Inverter
    coordinator: GoodweUpdateCoordinator
    # Read only when settings are shown or controls are allowed
    settings: GoodweSettingsCoordinator | None
    devices: dict[GoodweDevice, DeviceInfo]
    racks: GoodweBatteryRackCoordinator | None
    firmware: GoodweFirmwareCoordinator | None
    allow_control: bool
    show_settings: bool


class GoodweUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Gather data for the energy device."""

    config_entry: GoodweConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GoodweConfigEntry,
        inverter: Inverter,
    ) -> None:
        """Initialize update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=SCAN_INTERVAL,
        )
        self.inverter: Inverter = inverter
        self._last_data: dict[str, Any] = {}

    @override
    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the inverter."""
        try:
            self._last_data = self.data or {}
            return await self.inverter.read_runtime_data()
        except RequestFailedException as ex:
            # UDP communication with inverter is by definition unreliable.
            # It is rather normal in many environments to fail to receive
            # proper response in usual time, so we intentionally ignore isolated
            # failures and report problem with availability only after
            # consecutive streak of 3 of failed requests.
            if ex.consecutive_failures_count < 3:
                _LOGGER.debug(
                    "No response received (streak of %d)", ex.consecutive_failures_count
                )
                # return last known data
                return self._last_data
            # Inverter does not respond anymore (e.g. it went to sleep mode)
            _LOGGER.debug(
                "Inverter not responding (streak of %d)", ex.consecutive_failures_count
            )
            raise UpdateFailed(ex) from ex
        except InverterError as ex:
            raise UpdateFailed(ex) from ex

    def sensor_value(self, sensor: str) -> Any:
        """Answer current (or last known) value of the sensor."""
        val = self.data.get(sensor)
        return val if val is not None else self._last_data.get(sensor)

    def total_sensor_value(self, sensor: str) -> Any:
        """Answer current value of the 'total' (never 0) sensor."""
        val = self.data.get(sensor)
        return val or self._last_data.get(sensor)

    def reset_sensor(self, sensor: str) -> None:
        """Reset sensor value to 0.

        Intended for "daily" cumulative sensors (e.g. PV energy produced today),
        which should be explicitly reset to 0 at midnight if inverter is suspended.
        """
        self._last_data[sensor] = 0
        self.data[sensor] = 0


SETTING_GRID_EXPORT_LIMIT = "grid_export_limit"
SETTING_BATTERY_DISCHARGE_DEPTH = "battery_discharge_depth"
SETTING_WORK_MODE_SWITCHES = "work_mode_switches"
SETTING_OPERATION_MODE = "operation_mode"
SETTING_TOU_SLOTS = "tou_slots"
SETTING_GRID_INPUT_CURRENT_LIMIT = "grid_input_current_limit"

_SETTINGS: dict[str, Callable[[Inverter], Awaitable[Any]]] = {
    SETTING_GRID_EXPORT_LIMIT: lambda inv: inv.get_grid_export_limit(),
    SETTING_BATTERY_DISCHARGE_DEPTH: lambda inv: inv.get_ongrid_battery_dod(),
    SETTING_WORK_MODE_SWITCHES: lambda inv: inv.get_work_mode_switches(),
    SETTING_OPERATION_MODE: lambda inv: inv.get_operation_mode(),
    SETTING_TOU_SLOTS: async_read_tou_slots,
    SETTING_GRID_INPUT_CURRENT_LIMIT: lambda inv: inv.read_setting(
        "grid_input_current_limit"
    ),
}


def setting_unit(inverter: Inverter, setting: str) -> str:
    """Return the unit of an inverter setting."""
    return next((s.unit for s in inverter.settings() if s.id_ == setting), "")


class GoodweSettingsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Read the inverter settings, so changes made in the GoodWe apps show up.

    The first read finds which settings the inverter supports; later reads ask
    only for those.
    """

    config_entry: GoodweConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GoodweConfigEntry,
        inverter: Inverter,
    ) -> None:
        """Initialize the settings coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} settings",
            update_interval=SETTINGS_SCAN_INTERVAL,
        )
        self.inverter = inverter
        self.supported: frozenset[str] | None = None

    @override
    async def _async_update_data(self) -> dict[str, Any]:
        """Read the supported settings from the inverter."""
        if self.supported is None:
            return await self._async_probe()
        data: dict[str, Any] = {}
        try:
            for key in self.supported:
                data[key] = await _SETTINGS[key](self.inverter)
        except (InverterError, ValueError) as err:
            raise UpdateFailed(err) from err
        return data

    async def _async_probe(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for key, read in _SETTINGS.items():
            # Firmware with work mode switches has no single operation mode
            if key == SETTING_OPERATION_MODE and data.get(SETTING_WORK_MODE_SWITCHES):
                continue
            try:
                value = await read(self.inverter)
            except InverterError, ValueError, NotImplementedError:
                _LOGGER.debug("Could not read inverter setting %s", key)
                continue
            # An empty switch set means the firmware has none
            if value is not None and value != {}:
                data[key] = value
        self.supported = frozenset(data)
        return data


class GoodweBatteryRackCoordinator(DataUpdateCoordinator[dict[int, BatteryCluster]]):
    """Read each battery rack (BMS cluster) of systems built from racks."""

    config_entry: GoodweConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GoodweConfigEntry,
        inverter: Inverter,
        info: list[BatteryClusterInfo],
    ) -> None:
        """Initialize the battery rack coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} battery racks",
            update_interval=BATTERY_RACK_SCAN_INTERVAL,
        )
        self.inverter = inverter
        # Serial, versions, cells and SOH, read once at setup
        self.info = {rack.index: rack for rack in info}

    @override
    async def _async_update_data(self) -> dict[int, BatteryCluster]:
        """Read the racks' live data."""
        try:
            racks = await self.inverter.read_battery_clusters()
        except InverterError as err:
            raise UpdateFailed(err) from err
        return {rack.index: rack for rack in racks}


class GoodweFirmwareCoordinator(DataUpdateCoordinator[list[FirmwareRelease]]):
    """Ask GoodWe once a day whether newer inverter firmware exists."""

    config_entry: GoodweConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GoodweConfigEntry,
        inverter: Inverter,
        installed: InstalledFirmware,
    ) -> None:
        """Initialize the firmware coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} firmware",
            update_interval=FIRMWARE_CHECK_INTERVAL,
        )
        self.serial: str = inverter.serial_number
        self.installed = installed

    @override
    async def _async_update_data(self) -> list[FirmwareRelease]:
        """Check for newer firmware."""
        try:
            return await async_check_firmware(
                async_get_clientsession(self.hass), self.serial, self.installed
            )
        except FirmwareCheckError as err:
            raise UpdateFailed(err) from err
