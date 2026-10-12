"""The Goodwe inverter component."""

import logging

from goodwe import Inverter, InverterError, connect
from goodwe.const import GOODWE_UDP_PORT

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .config_flow import GoodweFlowHandler
from .const import (
    CONF_ALLOW_CONTROL,
    CONF_MODEL_FAMILY,
    CONF_SHOW_SETTINGS,
    PLATFORMS,
)
from .coordinator import (
    GoodweBatteryRackCoordinator,
    GoodweConfigEntry,
    GoodweRuntimeData,
    GoodweSettingsCoordinator,
    GoodweUpdateCoordinator,
)
from .entity import GoodweDevice, build_devices

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: GoodweConfigEntry) -> bool:
    """Set up the Goodwe components from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, GOODWE_UDP_PORT)
    model_family = entry.data[CONF_MODEL_FAMILY]

    # Connect to Goodwe inverter
    try:
        inverter = await connect(
            host=host,
            port=port,
            family=model_family,
            retries=3,
        )
    except InverterError as err:
        try:
            inverter = await async_check_port(hass, entry, host)
        except InverterError:
            raise ConfigEntryNotReady from err

    # Create update coordinator
    coordinator = GoodweUpdateCoordinator(hass, entry, inverter)

    # Fetch initial data so we have data when entities subscribe
    await coordinator.async_config_entry_first_refresh()
    # Controls are opt-in because they write to real hardware; settings
    # because they lag the inverter and the GoodWe cloud
    allow_control = entry.options.get(CONF_ALLOW_CONTROL, False)
    show_settings = entry.options.get(CONF_SHOW_SETTINGS, False)
    settings: GoodweSettingsCoordinator | None = None
    if allow_control or show_settings:
        settings = GoodweSettingsCoordinator(hass, entry, inverter)
        await settings.async_config_entry_first_refresh()
    racks = await _async_setup_battery_racks(hass, entry, inverter)

    entry.runtime_data = GoodweRuntimeData(
        inverter=inverter,
        coordinator=coordinator,
        settings=settings,
        devices=build_devices(hass, entry, inverter),
        racks=racks,
        allow_control=allow_control,
        show_settings=show_settings,
    )
    _async_remove_hidden_entities(hass, entry)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


def _async_remove_hidden_entities(
    hass: HomeAssistant, entry: GoodweConfigEntry
) -> None:
    """Remove the entities of options turned off, rather than leave them unavailable."""
    runtime_data = entry.runtime_data
    serial = runtime_data.inverter.serial_number
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        key = entity.unique_id.removeprefix(f"{serial}-")
        if (entity.domain == Platform.SWITCH and not runtime_data.allow_control) or (
            not runtime_data.show_settings and _is_setting_entity(entity.domain, key)
        ):
            entity_registry.async_remove(entity.entity_id)
    if runtime_data.allow_control or runtime_data.show_settings:
        return
    device_registry = dr.async_get(hass)
    (identifier,) = runtime_data.devices[GoodweDevice.WORK_MODE]["identifiers"]
    if device := device_registry.async_get_device_by_identifier(
        identifier, entry.entry_id
    ):
        device_registry.async_update_device(
            device.id, remove_config_entry_id=entry.entry_id
        )


def _is_setting_entity(domain: str, key: str) -> bool:
    """Whether an entity shows a stored inverter setting."""
    return domain == Platform.BINARY_SENSOR or (
        domain == Platform.SENSOR and key.startswith(("setting_", "tou_slot_"))
    )


async def _async_setup_battery_racks(
    hass: HomeAssistant, entry: GoodweConfigEntry, inverter: Inverter
) -> GoodweBatteryRackCoordinator | None:
    """Find the battery racks; most batteries don't report any."""
    try:
        info = await inverter.read_battery_cluster_info()
    except InverterError:
        _LOGGER.debug("Could not read battery racks", exc_info=True)
        return None
    if not info:
        return None
    racks = GoodweBatteryRackCoordinator(hass, entry, inverter, info)
    await racks.async_config_entry_first_refresh()
    return racks


async def async_check_port(
    hass: HomeAssistant, entry: GoodweConfigEntry, host: str
) -> Inverter:
    """Check the communication port of the inverter.

    It may have changed after a firmware update.
    """
    inverter, port = await GoodweFlowHandler.async_detect_inverter_port(host=host)
    family = type(inverter).__name__
    hass.config_entries.async_update_entry(
        entry,
        data={
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_MODEL_FAMILY: family,
        },
    )
    return inverter


async def async_unload_entry(
    hass: HomeAssistant, config_entry: GoodweConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)


async def update_listener(hass: HomeAssistant, config_entry: GoodweConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: GoodweConfigEntry
) -> bool:
    """Migrate old config entries."""

    if config_entry.version == 1:
        # Update from version 1 to version 2 adding the PROTOCOL to the config entry
        host = config_entry.data[CONF_HOST]
        try:
            inverter, port = await GoodweFlowHandler.async_detect_inverter_port(
                host=host
            )
        except InverterError as err:
            raise ConfigEntryNotReady from err
        new_data = {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_MODEL_FAMILY: type(inverter).__name__,
        }
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)

    return True
