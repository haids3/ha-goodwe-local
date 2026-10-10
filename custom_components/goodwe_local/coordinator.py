"""Update coordinator for Goodwe."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Any, override

from goodwe import Inverter, InverterError, OperationMode, RequestFailedException

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import SCAN_INTERVAL, SETTINGS_SCAN_INTERVAL
from .entity import GoodweDevice

_LOGGER = logging.getLogger(__name__)

type GoodweConfigEntry = ConfigEntry[GoodweRuntimeData]


@dataclass
class GoodweRuntimeData:
    """Data class for runtime data."""

    inverter: Inverter
    coordinator: GoodweUpdateCoordinator
    settings: GoodweSettingsCoordinator
    devices: dict[GoodweDevice, DeviceInfo]
    allow_control: bool


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

_SETTINGS: dict[str, Callable[[Inverter], Awaitable[Any]]] = {
    SETTING_GRID_EXPORT_LIMIT: lambda inv: inv.get_grid_export_limit(),
    SETTING_BATTERY_DISCHARGE_DEPTH: lambda inv: inv.get_ongrid_battery_dod(),
    SETTING_WORK_MODE_SWITCHES: lambda inv: inv.get_work_mode_switches(),
    SETTING_OPERATION_MODE: lambda inv: inv.get_operation_mode(),
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
        self.operation_modes: tuple[OperationMode, ...] = ()

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
        if SETTING_OPERATION_MODE in data:
            self.operation_modes = await self.inverter.get_operation_modes(False)
        self.supported = frozenset(data)
        return data
