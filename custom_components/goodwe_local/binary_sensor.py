"""GoodWe PV inverter work mode state entities."""

from typing import override

from goodwe import Inverter, WorkModeSwitch

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import (
    SETTING_WORK_MODE_SWITCHES,
    GoodweConfigEntry,
    GoodweSettingsCoordinator,
)
from .entity import GoodweDevice

# Coordinator handles all data updates, so parallel updates are not needed
PARALLEL_UPDATES = 0

WORK_MODES: dict[WorkModeSwitch, BinarySensorEntityDescription] = {
    switch: BinarySensorEntityDescription(
        key=f"work_mode_{switch.value}",
        translation_key=f"work_mode_{switch.value}",
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for switch in WorkModeSwitch
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: GoodweConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the work mode states when the stored settings are shown."""
    runtime_data = config_entry.runtime_data
    if not runtime_data.show_settings or (settings := runtime_data.settings) is None:
        return
    async_add_entities(
        InverterWorkModeBinarySensor(
            settings,
            runtime_data.devices[GoodweDevice.WORK_MODE],
            WORK_MODES[switch],
            runtime_data.inverter,
            switch,
        )
        for switch in settings.data.get(SETTING_WORK_MODE_SWITCHES, {})
    )


class InverterWorkModeBinarySensor(
    CoordinatorEntity[GoodweSettingsCoordinator], BinarySensorEntity
):
    """Whether one of the inverter's independent work modes is on."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GoodweSettingsCoordinator,
        device_info: DeviceInfo,
        description: BinarySensorEntityDescription,
        inverter: Inverter,
        switch: WorkModeSwitch,
    ) -> None:
        """Initialize the work mode state entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{inverter.serial_number}-{description.key}"
        self._attr_device_info = device_info
        self._switch = switch

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the work mode is on."""
        return self.coordinator.data.get(SETTING_WORK_MODE_SWITCHES, {}).get(
            self._switch
        )
