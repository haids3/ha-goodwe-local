"""Support for GoodWe inverter via UDP."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import logging
from typing import Any, override

from goodwe import Inverter, Sensor, SensorKind

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
    SETTING_OPERATION_MODE,
    GoodweConfigEntry,
    GoodweSettingsCoordinator,
    GoodweUpdateCoordinator,
    setting_unit,
)
from .entity import GoodweDevice

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
    # Settings show read-only whether or not controls are allowed
    entities.extend(
        InverterSettingSensor(
            settings, devices[description.device], description, inverter
        )
        for description in SETTING_SENSORS
        if description.key in settings.supported
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
