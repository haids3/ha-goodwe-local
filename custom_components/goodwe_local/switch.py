"""GoodWe PV inverter work mode switch entities."""

from typing import Any, override

from goodwe import Inverter, WorkModeSwitch

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import (
    SETTING_TOU_SLOTS,
    SETTING_WORK_MODE_SWITCHES,
    GoodweConfigEntry,
    GoodweSettingsCoordinator,
)
from .entity import GoodweDevice
from .tou import TouSlot, async_set_tou_slot

# The dongle may limit concurrent connections
PARALLEL_UPDATES = 1

WORK_MODE_SWITCHES: dict[WorkModeSwitch, SwitchEntityDescription] = {
    switch: SwitchEntityDescription(
        key=f"work_mode_{switch.value}",
        translation_key=f"work_mode_{switch.value}",
        entity_category=EntityCategory.CONFIG,
    )
    for switch in WorkModeSwitch
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: GoodweConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the inverter work mode switches from a config entry."""
    runtime_data = config_entry.runtime_data
    if not runtime_data.allow_control:
        return
    settings = runtime_data.settings
    device_info = runtime_data.devices[GoodweDevice.WORK_MODE]
    entities: list[SwitchEntity] = [
        InverterWorkModeSwitchEntity(
            settings,
            device_info,
            WORK_MODE_SWITCHES[switch],
            runtime_data.inverter,
            switch,
        )
        for switch in settings.data.get(SETTING_WORK_MODE_SWITCHES, {})
    ]
    entities.extend(
        TouSlotSwitchEntity(settings, device_info, runtime_data.inverter, slot)
        for slot in settings.data.get(SETTING_TOU_SLOTS, {}).values()
    )
    async_add_entities(entities)


class InverterWorkModeSwitchEntity(
    CoordinatorEntity[GoodweSettingsCoordinator], SwitchEntity
):
    """Entity representing one of the inverter's independent work modes."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GoodweSettingsCoordinator,
        device_info: DeviceInfo,
        description: SwitchEntityDescription,
        inverter: Inverter,
        switch: WorkModeSwitch,
    ) -> None:
        """Initialize the work mode switch entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{inverter.serial_number}-{description.key}"
        self._attr_device_info = device_info
        self._inverter = inverter
        self._switch = switch

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the work mode is on."""
        return self.coordinator.data.get(SETTING_WORK_MODE_SWITCHES, {}).get(
            self._switch
        )

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the work mode on."""
        await self._async_set(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the work mode off."""
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        try:
            await self._inverter.set_work_mode_switch(self._switch, enabled)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="work_mode_switch_rejected",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class TouSlotSwitchEntity(CoordinatorEntity[GoodweSettingsCoordinator], SwitchEntity):
    """Turns one existing TOU slot on or off; its schedule is set elsewhere."""

    _attr_has_entity_name = True
    _attr_translation_key = "tou_slot"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: GoodweSettingsCoordinator,
        device_info: DeviceInfo,
        inverter: Inverter,
        slot: TouSlot,
    ) -> None:
        """Initialize the TOU slot switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{inverter.serial_number}-tou_slot_{slot.index}"
        self._attr_device_info = device_info
        self._attr_translation_placeholders = {"slot": str(slot.index)}
        self._attr_entity_registry_enabled_default = slot.configured
        self._inverter = inverter
        self._index = slot.index

    @property
    def _slot(self) -> TouSlot | None:
        return self.coordinator.data.get(SETTING_TOU_SLOTS, {}).get(self._index)

    @property
    @override
    def available(self) -> bool:
        """Return whether the slot can be switched."""
        slot = self._slot
        return super().available and slot is not None and slot.configured

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the slot is on."""
        return None if (slot := self._slot) is None else slot.enabled

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the slot on."""
        await self._async_set(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the slot off."""
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        try:
            await async_set_tou_slot(self._inverter, self._index, enabled)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="tou_slot_rejected",
                translation_placeholders={"slot": str(self._index), "error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
