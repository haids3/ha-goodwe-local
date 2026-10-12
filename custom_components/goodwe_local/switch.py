"""GoodWe PV inverter work mode switch entities."""

from datetime import datetime, timedelta
from typing import Any, override

from goodwe import Inverter, WorkModeSwitch

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
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

# The inverter can apply a setting a moment after acknowledging its write
WRITE_CONFIRM_TIMEOUT = timedelta(seconds=30)

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


class GoodweSettingSwitchEntity(
    CoordinatorEntity[GoodweSettingsCoordinator], SwitchEntity
):
    """A switch whose written state holds until the inverter reads it back."""

    _attr_has_entity_name = True
    _written: bool | None = None
    _written_expired = False
    _cancel_confirm: CALLBACK_TYPE | None = None

    @property
    def _read_is_on(self) -> bool | None:
        raise NotImplementedError

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the written state until a read confirms it, then the read."""
        return self._written if self._written is not None else self._read_is_on

    async def _async_written(self, enabled: bool) -> None:
        """Show what was written while the read straight after may be stale.

        A read that agrees ends it; after WRITE_CONFIRM_TIMEOUT a read is
        forced and its value shows even if the write did not take.
        """
        self._written, self._written_expired = enabled, False
        self._cancel_pending_confirm()
        self._cancel_confirm = async_call_later(
            self.hass, WRITE_CONFIRM_TIMEOUT, self._async_confirm
        )
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def _async_confirm(self, _now: datetime) -> None:
        self._cancel_confirm = None
        self._written_expired = True
        await self.coordinator.async_request_refresh()

    def _cancel_pending_confirm(self) -> None:
        if self._cancel_confirm is not None:
            self._cancel_confirm()
            self._cancel_confirm = None

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        if self._written is not None and (
            self._written_expired or self._read_is_on == self._written
        ):
            self._written = None
            self._cancel_pending_confirm()
        super()._handle_coordinator_update()

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Stop waiting for a write to be confirmed."""
        self._cancel_pending_confirm()
        await super().async_will_remove_from_hass()


class InverterWorkModeSwitchEntity(GoodweSettingSwitchEntity):
    """Entity representing one of the inverter's independent work modes."""

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
    def _read_is_on(self) -> bool | None:
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
        await self._async_written(enabled)


class TouSlotSwitchEntity(GoodweSettingSwitchEntity):
    """Turns one existing TOU slot on or off; its schedule is set elsewhere."""

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
    def _read_is_on(self) -> bool | None:
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
        await self._async_written(enabled)
