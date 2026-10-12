"""Support for GoodWe inverter via UDP."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import logging
from typing import Any, override

from goodwe import BatteryCluster, BatteryClusterInfo, Inverter, Sensor, SensorKind

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactivePower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .catalog import SensorSpec, sensor_spec
from .const import MODE_TO_OPTION
from .coordinator import (
    SETTING_BATTERY_DISCHARGE_DEPTH,
    SETTING_GRID_EXPORT_LIMIT,
    SETTING_GRID_INPUT_CURRENT_LIMIT,
    SETTING_OPERATION_MODE,
    SETTING_TOU_SLOTS,
    GoodweBatteryRackCoordinator,
    GoodweConfigEntry,
    GoodweSettingsCoordinator,
    GoodweUpdateCoordinator,
    setting_unit,
)
from .entity import GoodweDevice, rack_device_info
from .tou import TouSlot

# Coordinator handles all data updates, so parallel updates are not needed
PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)

_STATE_OF_CHARGE = frozenset({"battery_soc", "battery2_soc"})

# Sensors that are reset to 0 at midnight.
# The inverter is only powered by the solar panels and not
# mains power, so it goes dead when the sun goes down.
# The "_day" sensors are reset to 0 when the inverter wakes
# up in the morning when the sun comes up and power to the
# inverter is restored.
# This makes sure daily values are reset at midnight instead
# of at sunrise.
# When the inverter has a battery connected, HomeAssistant
# will not reset the values but let the inverter reset them
# by looking at the unavailable state of the inverter.
DAILY_RESET = ["e_day", "e_load_day"]

_ICONS: dict[SensorKind, str] = {
    SensorKind.PV: "mdi:solar-power",
    SensorKind.AC: "mdi:power-plug-outline",
    SensorKind.UPS: "mdi:power-plug-off-outline",
    SensorKind.BAT: "mdi:battery-high",
    SensorKind.GRID: "mdi:transmission-tower",
}


@dataclass(frozen=True)
class GoodweSensorEntityDescription(SensorEntityDescription):
    """Class describing Goodwe sensor entities."""

    value: Callable[[GoodweUpdateCoordinator, str], Any] = lambda coordinator, sensor: (
        coordinator.sensor_value(sensor)
    )
    available: Callable[[GoodweUpdateCoordinator], bool] = lambda coordinator: (
        coordinator.last_update_success
    )


_DESCRIPTIONS: dict[str, GoodweSensorEntityDescription] = {
    "A": GoodweSensorEntityDescription(
        key="A",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    ),
    "V": GoodweSensorEntityDescription(
        key="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
    ),
    "W": GoodweSensorEntityDescription(
        key="W",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    "kWh": GoodweSensorEntityDescription(
        key="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value=lambda coordinator, sensor: coordinator.total_sensor_value(sensor),
        available=lambda coordinator: coordinator.data is not None,
    ),
    "VA": GoodweSensorEntityDescription(
        key="VA",
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        entity_registry_enabled_default=False,
    ),
    "var": GoodweSensorEntityDescription(
        key="var",
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        entity_registry_enabled_default=False,
    ),
    "C": GoodweSensorEntityDescription(
        key="C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    "Hz": GoodweSensorEntityDescription(
        key="Hz",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
    ),
    "h": GoodweSensorEntityDescription(
        key="h",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_registry_enabled_default=False,
    ),
    "%": GoodweSensorEntityDescription(
        key="%",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
}
DIAG_SENSOR = GoodweSensorEntityDescription(
    key="_",
    state_class=SensorStateClass.MEASUREMENT,
)
TEXT_SENSOR = GoodweSensorEntityDescription(
    key="text",
)


@dataclass(frozen=True, kw_only=True)
class GoodweSettingSensorEntityDescription(SensorEntityDescription):
    """Class describing a read-only view of an inverter setting."""

    device: GoodweDevice
    value: Callable[[Any], StateType] = lambda value: value


SETTING_SENSORS = (
    GoodweSettingSensorEntityDescription(
        key=SETTING_GRID_EXPORT_LIMIT,
        translation_key="grid_export_limit",
        entity_category=EntityCategory.DIAGNOSTIC,
        device=GoodweDevice.INVERTER,
    ),
    GoodweSettingSensorEntityDescription(
        key=SETTING_BATTERY_DISCHARGE_DEPTH,
        translation_key="battery_discharge_depth",
        entity_category=EntityCategory.DIAGNOSTIC,
        device=GoodweDevice.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
    ),
    GoodweSettingSensorEntityDescription(
        key=SETTING_OPERATION_MODE,
        translation_key="operation_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        device=GoodweDevice.WORK_MODE,
        device_class=SensorDeviceClass.ENUM,
        options=list(MODE_TO_OPTION.values()),
        value=MODE_TO_OPTION.get,
    ),
    GoodweSettingSensorEntityDescription(
        key=SETTING_GRID_INPUT_CURRENT_LIMIT,
        translation_key="on_grid_point_rated_protection",
        entity_category=EntityCategory.DIAGNOSTIC,
        device=GoodweDevice.INVERTER,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: GoodweConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the GoodWe inverter from a config entry."""
    entities: list[SensorEntity] = []
    inverter = config_entry.runtime_data.inverter
    coordinator = config_entry.runtime_data.coordinator
    settings = config_entry.runtime_data.settings
    devices = config_entry.runtime_data.devices

    for sensor in inverter.sensors():
        if (
            sensor.id_.startswith("xx")
            or (spec := sensor_spec(inverter, sensor)) is None
        ):
            continue
        entities.append(
            InverterSensor(coordinator, devices[spec.device], inverter, sensor, spec)
        )
    if config_entry.runtime_data.show_settings and settings is not None:
        entities.extend(_setting_sensors(settings, devices, inverter))

    entities.extend(
        InverterFirmwareSensor(devices[GoodweDevice.INVERTER], inverter, description)
        for description in FIRMWARE_SENSORS
    )
    if (racks := config_entry.runtime_data.racks) is not None:
        # Racks link to the battery by registry id, so it must exist first
        battery_device = dr.async_get(hass).async_get_or_create(
            config_entry_id=config_entry.entry_id, **devices[GoodweDevice.BATTERY]
        )
        for index, info in racks.info.items():
            device_info = rack_device_info(
                config_entry, inverter, info, battery_device.id
            )
            entities.extend(
                BatteryRackSensor(racks, device_info, inverter, index, description)
                for description in RACK_SENSORS
            )
            entities.extend(
                BatteryRackInfoSensor(device_info, inverter, info, description)
                for description in RACK_INFO_SENSORS
            )

    async_add_entities(entities)


def _description(sensor: Sensor, spec: SensorSpec) -> GoodweSensorEntityDescription:
    """Combine the unit's description with how the table shows the sensor."""
    if spec.states is not None:
        base = GoodweSensorEntityDescription(
            key=sensor.id_,
            device_class=SensorDeviceClass.ENUM,
            options=sorted(set(spec.states.values())),
        )
    elif sensor.unit in _DESCRIPTIONS:
        base = _DESCRIPTIONS[sensor.unit]
    elif "Enum" in type(sensor).__name__ or sensor.id_ == "timestamp":
        base = TEXT_SENSOR
    else:
        base = DIAG_SENSOR
    return replace(
        base,
        key=sensor.id_,
        translation_key=spec.translation_key,
        entity_category=spec.entity_category,
        entity_registry_enabled_default=spec.enabled,
        device_class=(
            SensorDeviceClass.BATTERY
            if sensor.id_ in _STATE_OF_CHARGE
            else base.device_class
        ),
    )


class InverterSensor(CoordinatorEntity[GoodweUpdateCoordinator], SensorEntity):
    """Entity representing individual inverter sensor."""

    _attr_has_entity_name = True
    entity_description: GoodweSensorEntityDescription

    def __init__(
        self,
        coordinator: GoodweUpdateCoordinator,
        device_info: DeviceInfo,
        inverter: Inverter,
        sensor: Sensor,
        spec: SensorSpec,
    ) -> None:
        """Initialize an inverter sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{inverter.serial_number}-{sensor.id_}"
        self._attr_device_info = device_info
        self.entity_description = _description(sensor, spec)
        if spec.translation_key is None:
            self._attr_name = sensor.name.strip()
            self._attr_icon = _ICONS.get(sensor.kind)
        else:
            self._attr_translation_placeholders = dict(spec.placeholders)
        if self.entity_description.device_class is None and not spec.states:
            # Units the table of descriptions does not know
            self._attr_native_unit_of_measurement = sensor.unit or None
        self._sensor = sensor
        self._spec = spec
        self._stop_reset: Callable[[], None] | None = None

    @property
    @override
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Return the value reported by the sensor."""
        value = self.entity_description.value(self.coordinator, self._sensor.id_)
        if self._spec.states is not None:
            return self._spec.states.get(value)
        if self._spec.negate and value is not None:
            return -value
        return value

    @property
    @override
    def available(self) -> bool:
        """Return if entity is available.

        We delegate the behavior to entity description lambda, since
        some sensors (like energy produced today) should report themselves
        as available even when the (non-battery) pv inverter is off-line during night
        and most of the sensors are actually unavailable.
        """
        return self.entity_description.available(self.coordinator)

    @callback
    def async_reset(self, now):
        """Reset the value back to 0 at midnight.

        Some sensors values like daily produced energy are kept available,
        even when the inverter is in sleep mode and no longer responds to request.
        In contrast to "total" sensors, these "daily" sensors
        need to be reset to 0 on midnight.
        """
        if not self.coordinator.last_update_success:
            self.coordinator.reset_sensor(self._sensor.id_)
            self.async_write_ha_state()
            _LOGGER.debug("Goodwe reset %s to 0", self.name)
        next_midnight = dt_util.start_of_local_day(
            dt_util.now() + timedelta(days=1, minutes=1)
        )
        self._stop_reset = async_track_point_in_time(
            self.hass, self.async_reset, next_midnight
        )

    @override
    async def async_added_to_hass(self) -> None:
        """Schedule reset task at midnight."""
        if self._sensor.id_ in DAILY_RESET:
            next_midnight = dt_util.start_of_local_day(
                dt_util.now() + timedelta(days=1)
            )
            self._stop_reset = async_track_point_in_time(
                self.hass, self.async_reset, next_midnight
            )
        await super().async_added_to_hass()

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Remove reset task at midnight."""
        if self._sensor.id_ in DAILY_RESET and self._stop_reset is not None:
            self._stop_reset()
        await super().async_will_remove_from_hass()


def _setting_sensors(
    settings: GoodweSettingsCoordinator,
    devices: dict[GoodweDevice, DeviceInfo],
    inverter: Inverter,
) -> list[SensorEntity]:
    """Create the read-only views of the stored settings and TOU slots."""
    entities: list[SensorEntity] = [
        InverterSettingSensor(
            settings, devices[description.device], description, inverter
        )
        for description in SETTING_SENSORS
        if description.key in settings.supported
    ]
    device_info = devices[GoodweDevice.WORK_MODE]
    for slot in settings.data.get(SETTING_TOU_SLOTS, {}).values():
        entities.append(
            TouSlotStatusSensor(settings, device_info, inverter, slot, TOU_SLOT_STATUS)
        )
        entities.extend(
            TouSlotSensor(settings, device_info, inverter, slot, description)
            for description in TOU_SLOT_FIELDS
        )
    return entities


class InverterSettingSensor(CoordinatorEntity[GoodweSettingsCoordinator], SensorEntity):
    """Entity showing an inverter setting."""

    _attr_has_entity_name = True
    entity_description: GoodweSettingSensorEntityDescription

    def __init__(
        self,
        coordinator: GoodweSettingsCoordinator,
        device_info: DeviceInfo,
        description: GoodweSettingSensorEntityDescription,
        inverter: Inverter,
    ) -> None:
        """Initialize the setting sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        # Runtime sensors already use some setting keys, e.g. operation_mode
        self._attr_unique_id = f"{inverter.serial_number}-setting_{description.key}"
        self._attr_device_info = device_info
        if description.key == SETTING_GRID_EXPORT_LIMIT:
            if setting_unit(inverter, SETTING_GRID_EXPORT_LIMIT) == PERCENTAGE:
                self._attr_native_unit_of_measurement = PERCENTAGE
            else:
                self._attr_device_class = SensorDeviceClass.POWER
                self._attr_native_unit_of_measurement = UnitOfPower.WATT

    @property
    @override
    def native_value(self) -> StateType:
        """Return the setting's value."""
        value = self.coordinator.data.get(self.entity_description.key)
        return None if value is None else self.entity_description.value(value)


_WEEKDAY_NAMES = {
    "sun": "Sun",
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
}
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri")
_MONTH_NAMES = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def _days(slot: TouSlot) -> str:
    days = set(slot.days)
    if len(days) == 7:
        return "Every day"
    if days == set(_WEEKDAYS):
        return "Weekdays"
    if days == {"sat", "sun"}:
        return "Weekends"
    # Monday first, as the GoodWe apps list them
    order = (*_WEEKDAYS, "sat", "sun")
    return ", ".join(_WEEKDAY_NAMES[day] for day in order if day in days) or "No days"


def _months(slot: TouSlot) -> str:
    if len(slot.months) == 12:
        return "All year"
    return ", ".join(_MONTH_NAMES[month - 1] for month in slot.months)


def _status(slot: TouSlot) -> str:
    if not slot.enabled:
        return "off"
    return "charge" if slot.charging else "discharge"


@dataclass(frozen=True, kw_only=True)
class TouSlotSensorEntityDescription(SensorEntityDescription):
    """Class describing one field of a TOU slot."""

    value: Callable[[TouSlot], StateType]


TOU_SLOT_STATUS = TouSlotSensorEntityDescription(
    key="status",
    translation_key="tou_slot_status",
    device_class=SensorDeviceClass.ENUM,
    options=["off", "charge", "discharge"],
    value=_status,
)

TOU_SLOT_FIELDS = (
    TouSlotSensorEntityDescription(
        key="mode",
        translation_key="tou_slot_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["charge", "discharge"],
        value=lambda slot: "charge" if slot.charging else "discharge",
    ),
    TouSlotSensorEntityDescription(
        key="start",
        translation_key="tou_slot_start",
        value=lambda slot: slot.start,
    ),
    TouSlotSensorEntityDescription(
        key="end",
        translation_key="tou_slot_end",
        value=lambda slot: slot.end,
    ),
    TouSlotSensorEntityDescription(
        key="power",
        translation_key="tou_slot_power",
        native_unit_of_measurement=PERCENTAGE,
        value=lambda slot: slot.power,
    ),
    TouSlotSensorEntityDescription(
        key="discharge_limit",
        translation_key="tou_slot_discharge_limit",
        device_class=SensorDeviceClass.ENUM,
        options=["battery", "export"],
        # A charging slot limits neither
        value=lambda slot: (
            None if slot.charging else ("export" if slot.export_limited else "battery")
        ),
    ),
    TouSlotSensorEntityDescription(
        key="cutoff_soc",
        translation_key="tou_slot_cutoff_soc",
        native_unit_of_measurement=PERCENTAGE,
        value=lambda slot: slot.cutoff_soc,
    ),
    TouSlotSensorEntityDescription(
        key="days",
        translation_key="tou_slot_days",
        value=_days,
    ),
    TouSlotSensorEntityDescription(
        key="months",
        translation_key="tou_slot_months",
        value=_months,
    ),
)


class TouSlotSensor(CoordinatorEntity[GoodweSettingsCoordinator], SensorEntity):
    """One field of a TOU slot, read-only, shown with the stored settings.

    Names start "TOU slot N", so a slot's sensors sort together on the work
    mode device, next to the slot's switch. Unused slots start disabled.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    entity_description: TouSlotSensorEntityDescription

    def __init__(
        self,
        coordinator: GoodweSettingsCoordinator,
        device_info: DeviceInfo,
        inverter: Inverter,
        slot: TouSlot,
        description: TouSlotSensorEntityDescription,
    ) -> None:
        """Initialize the TOU slot sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        key = f"tou_slot_{slot.index}"
        if description is not TOU_SLOT_STATUS:
            key = f"{key}_{description.key}"
        self._attr_unique_id = f"{inverter.serial_number}-{key}"
        self._attr_device_info = device_info
        self._attr_translation_placeholders = {"slot": str(slot.index)}
        self._attr_entity_registry_enabled_default = slot.configured
        self._index = slot.index

    @property
    def _slot(self) -> TouSlot | None:
        return self.coordinator.data.get(SETTING_TOU_SLOTS, {}).get(self._index)

    @property
    @override
    def native_value(self) -> StateType:
        """Return the field's value."""
        if (slot := self._slot) is None or not slot.configured:
            return None
        return self.entity_description.value(slot)


class TouSlotStatusSensor(TouSlotSensor):
    """A TOU slot at a glance: off, charge or discharge, with its schedule."""

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the slot's schedule, as the SEMS+ integration does."""
        if (slot := self._slot) is None:
            return None
        return {
            "mode": "charge" if slot.charging else "discharge",
            "start": slot.start,
            "end": slot.end,
            "power": slot.power,
            "power_limit": None
            if slot.charging
            else ("export" if slot.export_limited else "battery"),
            "cutoff_soc": slot.cutoff_soc,
            "days": list(slot.days),
            "months": list(slot.months),
        }


@dataclass(frozen=True, kw_only=True)
class GoodweFirmwareSensorEntityDescription(SensorEntityDescription):
    """Class describing a version the inverter reports when connecting."""

    value: Callable[[Inverter], StateType]


FIRMWARE_SENSORS = (
    GoodweFirmwareSensorEntityDescription(
        key="dsp_firmware",
        translation_key="dsp_firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda inverter: inverter.firmware,
    ),
    GoodweFirmwareSensorEntityDescription(
        key="arm_firmware",
        translation_key="arm_firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda inverter: inverter.arm_firmware,
    ),
    GoodweFirmwareSensorEntityDescription(
        key="dsp_beta_version",
        translation_key="dsp_beta_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda inverter: inverter.dsp_svn_version,
    ),
    GoodweFirmwareSensorEntityDescription(
        key="arm_beta_version",
        translation_key="arm_beta_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda inverter: inverter.arm_svn_version,
    ),
    GoodweFirmwareSensorEntityDescription(
        key="dsp_master_version",
        translation_key="dsp_master_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda inverter: inverter.dsp1_version,
    ),
    GoodweFirmwareSensorEntityDescription(
        key="dsp_slave_version",
        translation_key="dsp_slave_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda inverter: inverter.dsp2_version,
    ),
    GoodweFirmwareSensorEntityDescription(
        key="arm_version",
        translation_key="arm_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda inverter: inverter.arm_version,
    ),
)


class InverterFirmwareSensor(SensorEntity):
    """A version the inverter reported when Home Assistant connected."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: GoodweFirmwareSensorEntityDescription

    def __init__(
        self,
        device_info: DeviceInfo,
        inverter: Inverter,
        description: GoodweFirmwareSensorEntityDescription,
    ) -> None:
        """Initialize the firmware sensor."""
        self.entity_description = description
        self._attr_unique_id = f"{inverter.serial_number}-{description.key}"
        self._attr_device_info = device_info
        self._attr_native_value = description.value(inverter)


@dataclass(frozen=True, kw_only=True)
class BatteryRackSensorEntityDescription(SensorEntityDescription):
    """Class describing a live reading of a battery rack."""

    value: Callable[[BatteryCluster], StateType]


def _rack_power(rack: BatteryCluster) -> int:
    # Positive while discharging, like the battery's power
    return round(rack.voltage * rack.current)


RACK_SENSORS = (
    BatteryRackSensorEntityDescription(
        key="soc",
        translation_key="state_of_charge",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value=lambda rack: rack.soc,
    ),
    BatteryRackSensorEntityDescription(
        key="power",
        translation_key="battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value=_rack_power,
    ),
    BatteryRackSensorEntityDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda rack: rack.current,
    ),
    BatteryRackSensorEntityDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda rack: rack.voltage,
    ),
    BatteryRackSensorEntityDescription(
        key="max_temperature",
        translation_key="max_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda rack: rack.max_temperature,
    ),
    BatteryRackSensorEntityDescription(
        key="min_temperature",
        translation_key="min_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda rack: rack.min_temperature,
    ),
    BatteryRackSensorEntityDescription(
        key="max_cell_voltage",
        translation_key="max_cell_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda rack: rack.max_cell_voltage,
    ),
    BatteryRackSensorEntityDescription(
        key="min_cell_voltage",
        translation_key="min_cell_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda rack: rack.min_cell_voltage,
    ),
    BatteryRackSensorEntityDescription(
        key="charge_current_limit",
        translation_key="max_charge_current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda rack: rack.charge_current_limit,
    ),
    BatteryRackSensorEntityDescription(
        key="discharge_current_limit",
        translation_key="max_discharge_current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda rack: rack.discharge_current_limit,
    ),
    BatteryRackSensorEntityDescription(
        key="fault_code",
        translation_key="fault_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda rack: rack.fault,
    ),
    # The codes' meanings are not documented
    BatteryRackSensorEntityDescription(
        key="status_code",
        translation_key="status_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda rack: rack.status,
    ),
    BatteryRackSensorEntityDescription(
        key="charged_total",
        translation_key="charged_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="Ah",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda rack: rack.charged_total,
    ),
    BatteryRackSensorEntityDescription(
        key="discharged_total",
        translation_key="discharged_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="Ah",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda rack: rack.discharged_total,
    ),
)


class BatteryRackSensor(CoordinatorEntity[GoodweBatteryRackCoordinator], SensorEntity):
    """A live reading of one battery rack."""

    _attr_has_entity_name = True
    entity_description: BatteryRackSensorEntityDescription

    def __init__(
        self,
        coordinator: GoodweBatteryRackCoordinator,
        device_info: DeviceInfo,
        inverter: Inverter,
        index: int,
        description: BatteryRackSensorEntityDescription,
    ) -> None:
        """Initialize the battery rack sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{inverter.serial_number}-battery_rack_{index}_{description.key}"
        )
        self._attr_device_info = device_info
        self._index = index

    @property
    @override
    def available(self) -> bool:
        """Return whether the rack reported this time."""
        return super().available and self._index in self.coordinator.data

    @property
    @override
    def native_value(self) -> StateType:
        """Return the rack's reading."""
        if (rack := self.coordinator.data.get(self._index)) is None:
            return None
        return self.entity_description.value(rack)


@dataclass(frozen=True, kw_only=True)
class BatteryRackInfoSensorEntityDescription(SensorEntityDescription):
    """Class describing a fixed detail of a battery rack."""

    value: Callable[[BatteryClusterInfo], StateType]


RACK_INFO_SENSORS = (
    BatteryRackInfoSensorEntityDescription(
        key="soh",
        translation_key="state_of_health",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda info: info.soh,
    ),
    BatteryRackInfoSensorEntityDescription(
        key="cells_in_series",
        translation_key="cells_in_series",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda info: info.cells_in_series,
    ),
)


class BatteryRackInfoSensor(SensorEntity):
    """A detail of one battery rack, read when Home Assistant connected."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: BatteryRackInfoSensorEntityDescription

    def __init__(
        self,
        device_info: DeviceInfo,
        inverter: Inverter,
        info: BatteryClusterInfo,
        description: BatteryRackInfoSensorEntityDescription,
    ) -> None:
        """Initialize the battery rack detail sensor."""
        self.entity_description = description
        self._attr_unique_id = (
            f"{inverter.serial_number}-battery_rack_{info.index}_{description.key}"
        )
        self._attr_device_info = device_info
        self._attr_native_value = description.value(info)
