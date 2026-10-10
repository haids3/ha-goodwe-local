"""GoodWe PV inverter selection settings entities."""

from typing import override

from goodwe import Inverter, OperationMode

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import MODE_TO_OPTION
from .coordinator import (
    SETTING_OPERATION_MODE,
    GoodweConfigEntry,
    GoodweSettingsCoordinator,
)
from .entity import GoodweDevice

PARALLEL_UPDATES = 1

_OPTION_TO_MODE: dict[str, OperationMode] = {
    value: key for key, value in MODE_TO_OPTION.items()
}

OPERATION_MODE = SelectEntityDescription(
    key=SETTING_OPERATION_MODE,
    entity_category=EntityCategory.CONFIG,
    translation_key="operation_mode",
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: GoodweConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the inverter select entities from a config entry."""
    runtime_data = config_entry.runtime_data
    settings = runtime_data.settings
    if runtime_data.allow_control and SETTING_OPERATION_MODE in settings.supported:
        async_add_entities(
            [
                InverterOperationModeEntity(
                    settings,
                    runtime_data.devices[GoodweDevice.WORK_MODE],
                    OPERATION_MODE,
                    runtime_data.inverter,
                )
            ]
        )


class InverterOperationModeEntity(
    CoordinatorEntity[GoodweSettingsCoordinator], SelectEntity
):
    """Entity representing the inverter operation mode."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GoodweSettingsCoordinator,
        device_info: DeviceInfo,
        description: SelectEntityDescription,
        inverter: Inverter,
    ) -> None:
        """Initialize the inverter operation mode setting entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{inverter.serial_number}-{description.key}"
        self._attr_device_info = device_info
        self._attr_options = [
            option
            for mode, option in MODE_TO_OPTION.items()
            if mode in coordinator.operation_modes
        ]
        self._inverter = inverter

    @property
    @override
    def current_option(self) -> str | None:
        """Return the active operation mode."""
        return MODE_TO_OPTION.get(self.coordinator.data.get(SETTING_OPERATION_MODE))

    @override
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self._inverter.set_operation_mode(_OPTION_TO_MODE[option])
        await self.coordinator.async_request_refresh()
