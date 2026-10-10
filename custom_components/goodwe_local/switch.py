"""GoodWe PV inverter work mode switch entities."""

from datetime import timedelta
import logging
from typing import Any, override

from goodwe import Inverter, InverterError, WorkModeSwitch

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import GoodweConfigEntry

_LOGGER = logging.getLogger(__name__)

# Picks up changes made in the GoodWe apps without adding much Modbus traffic
SCAN_INTERVAL = timedelta(minutes=5)
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
    inverter = config_entry.runtime_data.inverter
    device_info = config_entry.runtime_data.device_info

    try:
        switches = await inverter.get_work_mode_switches()
    except InverterError:
        _LOGGER.debug("Could not read inverter work mode switches")
        return
    async_add_entities(
        InverterWorkModeSwitchEntity(
            device_info, WORK_MODE_SWITCHES[switch], inverter, switch, is_on
        )
        for switch, is_on in switches.items()
    )


class InverterWorkModeSwitchEntity(SwitchEntity):
    """Entity representing one of the inverter's independent work modes."""

    _attr_has_entity_name = True

    def __init__(
        self,
        device_info: DeviceInfo,
        description: SwitchEntityDescription,
        inverter: Inverter,
        switch: WorkModeSwitch,
        is_on: bool,
    ) -> None:
        """Initialize the work mode switch entity."""
        self.entity_description = description
        self._attr_unique_id = f"{inverter.serial_number}-{description.key}"
        self._attr_device_info = device_info
        self._attr_is_on = is_on
        self._inverter = inverter
        self._switch = switch

    async def async_update(self) -> None:
        """Get the current state from the inverter."""
        try:
            switches = await self._inverter.get_work_mode_switches()
        except InverterError:
            self._attr_available = False
            return
        self._attr_available = True
        self._attr_is_on = switches[self._switch]

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
        self._attr_is_on = enabled
        self.async_write_ha_state()
