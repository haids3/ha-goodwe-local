"""GoodWe PV inverter numeric settings entities."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import override

from goodwe import Inverter

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import (
    SETTING_BATTERY_DISCHARGE_DEPTH,
    SETTING_GRID_EXPORT_LIMIT,
    GoodweConfigEntry,
    GoodweSettingsCoordinator,
    setting_unit,
)
from .entity import GoodweDevice

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class GoodweNumberEntityDescription(NumberEntityDescription):
    """Class describing Goodwe number entities."""

    device: GoodweDevice
    setter: Callable[[Inverter, int], Awaitable[None]]
    filter: Callable[[Inverter], bool]


NUMBERS = (
    # Only one of the export limits are added.
    # Availability is checked in the filter method.
    # Export limit in W
    GoodweNumberEntityDescription(
        key=SETTING_GRID_EXPORT_LIMIT,
        translation_key="grid_export_limit",
        entity_category=EntityCategory.CONFIG,
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        native_step=100,
        native_min_value=0,
        native_max_value=10000,
        device=GoodweDevice.INVERTER,
        setter=lambda inv, val: inv.set_grid_export_limit(val),
        filter=lambda inv: setting_unit(inv, SETTING_GRID_EXPORT_LIMIT) != "%",
    ),
    # Export limit in %
    GoodweNumberEntityDescription(
        key=SETTING_GRID_EXPORT_LIMIT,
        translation_key="grid_export_limit",
        entity_category=EntityCategory.CONFIG,
        native_unit_of_measurement=PERCENTAGE,
        native_step=1,
        native_min_value=0,
        native_max_value=200,
        device=GoodweDevice.INVERTER,
        setter=lambda inv, val: inv.set_grid_export_limit(val),
        filter=lambda inv: setting_unit(inv, SETTING_GRID_EXPORT_LIMIT) == "%",
    ),
    GoodweNumberEntityDescription(
        key=SETTING_BATTERY_DISCHARGE_DEPTH,
        translation_key="battery_discharge_depth",
        entity_category=EntityCategory.CONFIG,
        native_unit_of_measurement=PERCENTAGE,
        native_step=1,
        native_min_value=0,
        native_max_value=99,
        device=GoodweDevice.BATTERY,
        setter=lambda inv, val: inv.set_ongrid_battery_dod(val),
        filter=lambda inv: True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: GoodweConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the inverter number entities from a config entry."""
    runtime_data = config_entry.runtime_data
    if not runtime_data.allow_control:
        return
    settings = runtime_data.settings
    async_add_entities(
        InverterNumberEntity(
            settings,
            runtime_data.devices[description.device],
            description,
            runtime_data.inverter,
        )
        for description in NUMBERS
        if description.key in settings.supported
        and description.filter(runtime_data.inverter)
    )


class InverterNumberEntity(CoordinatorEntity[GoodweSettingsCoordinator], NumberEntity):
    """Inverter numeric setting entity."""

    _attr_has_entity_name = True
    entity_description: GoodweNumberEntityDescription

    def __init__(
        self,
        coordinator: GoodweSettingsCoordinator,
        device_info: DeviceInfo,
        description: GoodweNumberEntityDescription,
        inverter: Inverter,
    ) -> None:
        """Initialize the number inverter setting entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{inverter.serial_number}-{description.key}"
        self._attr_device_info = device_info
        self._inverter = inverter
        # Larger inverters can export more than the default maximum; inverter
        # families that don't report their rated power leave it at 0
        if description.native_unit_of_measurement == UnitOfPower.WATT:
            self._attr_native_max_value = max(
                description.native_max_value, inverter.rated_power
            )

    @property
    @override
    def native_value(self) -> float | None:
        """Return the setting's value."""
        value = self.coordinator.data.get(self.entity_description.key)
        return None if value is None else float(value)

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.entity_description.setter(self._inverter, int(value))
        await self.coordinator.async_request_refresh()
