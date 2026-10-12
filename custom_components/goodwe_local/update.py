"""GoodWe inverter firmware update entity; it checks, but never installs."""

from typing import override

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import GoodweConfigEntry, GoodweFirmwareCoordinator
from .entity import GoodweDevice
from .firmware import FIRMWARE_ARM, FIRMWARE_DSP

# Coordinator handles all data updates, so parallel updates are not needed
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: GoodweConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the firmware update entity when the check is on."""
    runtime_data = config_entry.runtime_data
    if (firmware := runtime_data.firmware) is None:
        return
    async_add_entities(
        [GoodweFirmwareUpdate(firmware, runtime_data.devices[GoodweDevice.INVERTER])]
    )


class GoodweFirmwareUpdate(CoordinatorEntity[GoodweFirmwareCoordinator], UpdateEntity):
    """Whether GoodWe offers newer DSP or ARM firmware for the inverter.

    Installing is left to the GoodWe app or the installer.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: GoodweFirmwareCoordinator, device_info: DeviceInfo
    ) -> None:
        """Initialize the firmware update entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}-firmware"
        self._attr_device_info = device_info
        self._attr_installed_version = coordinator.installed.summary

    @property
    @override
    def available(self) -> bool:
        """Return whether the last check answered."""
        return super().available and self.coordinator.data is not None

    @property
    @override
    def latest_version(self) -> str | None:
        """Return the installed versions with any newer ones in their place."""
        if (releases := self.coordinator.data) is None:
            return None
        installed = self.coordinator.installed
        newer = {release.firmware_type: release.version for release in releases}
        dsp = newer.get(FIRMWARE_DSP, installed.dsp)
        arm = newer.get(FIRMWARE_ARM, installed.arm)
        return f"{dsp} / {arm}"

    @property
    @override
    def release_summary(self) -> str | None:
        """Return whether the update is mandatory, and its files."""
        if not (releases := self.coordinator.data):
            return None
        kind = (
            "Mandatory"
            if any(release.mandatory for release in releases)
            else "Optional"
        )
        files = ", ".join(release.file_name for release in releases)
        summary = (
            f"{kind} update: {files}. "
            "Install it with the GoodWe app or ask your installer."
        )
        # Home Assistant limits the summary to 255 characters
        return summary[:255]

    @override
    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """GoodWe only answers with firmware newer than the installed one."""
        return bool(self.coordinator.data)
