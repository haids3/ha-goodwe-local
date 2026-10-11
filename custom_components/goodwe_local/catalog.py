"""Names, devices and visibility of the inverter's runtime sensors.

The library names its sensors after the Modbus documentation ("On-grid L1
Power", "Battery Mode code"). The ET family is curated here to read like the
GoodWe apps: each sensor gets a translated name, the device it belongs to
and whether it is shown by default. Other families, and sensors the table
does not know, keep the library's name and are hidden by default.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from goodwe import Inverter, Sensor, SensorKind
from goodwe.et import ET

from homeassistant.const import EntityCategory

from .entity import GoodweDevice


@dataclass(frozen=True, kw_only=True)
class SensorSpec:
    """How one runtime sensor is presented."""

    translation_key: str | None = None
    placeholders: Mapping[str, str] = field(default_factory=dict)
    device: GoodweDevice = GoodweDevice.INVERTER
    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC
    enabled: bool = False
    # Grid power is reported negative while importing; Home Assistant expects
    # import to be positive
    negate: bool = False
    # Enum sensors: the state for each code the inverter reports
    states: Mapping[int, str] | None = None


INVERTER = GoodweDevice.INVERTER
BATTERY = GoodweDevice.BATTERY
BATTERY_2 = GoodweDevice.BATTERY_2
METER = GoodweDevice.METER
WORK_MODE = GoodweDevice.WORK_MODE


def _main(key: str, device: GoodweDevice = INVERTER, **kwargs) -> SensorSpec:
    return SensorSpec(
        translation_key=key, device=device, entity_category=None, enabled=True, **kwargs
    )


def _diag(key: str, device: GoodweDevice = INVERTER, **kwargs) -> SensorSpec:
    return SensorSpec(translation_key=key, device=device, enabled=True, **kwargs)


def _hidden(key: str, device: GoodweDevice = INVERTER, **kwargs) -> SensorSpec:
    return SensorSpec(translation_key=key, device=device, **kwargs)


# 35187, WORK_MODES_ET
_STATUS = {
    0: "standby",
    1: "running",
    2: "running",
    3: "fault",
    4: "maintenance",
    5: "standby",
}
# 35136, GRID_MODES
_GRID = {0: "off_grid", 1: "on_grid", 2: "fault"}
# 35184, BATTERY_MODES
_BATTERY_STATUS = {
    0: "no_battery",
    1: "standby",
    2: "discharging",
    3: "charging",
    4: "to_be_charged",
    5: "to_be_discharged",
}
_GRID_DIRECTION = {0: "idle", 1: "exporting", 2: "importing"}
_PV_STRING_STATUS = {0: "not_connected", 1: "no_power", 2: "producing"}

# Labels the curated enum sensors already show
_SKIPPED = frozenset(
    {
        "work_mode_label",
        "grid_mode_label",
        "battery_mode_label",
        "battery2_mode_label",
        "grid_in_out_label",
        *(f"pv{n}_mode_label" for n in range(1, 5)),
    }
)


def _phased(
    ids: str, first: SensorSpec, key: str, device: GoodweDevice = INVERTER, **kwargs
) -> dict[str, SensorSpec]:
    """Phase 1 under its own spec, phases 2 and 3 as hidden "Phase N" sensors."""
    one, two, three = ids.split()
    return {
        one: first,
        two: _hidden(key, device, placeholders={"phase": "2"}, **kwargs),
        three: _hidden(key, device, placeholders={"phase": "3"}, **kwargs),
    }


def _battery(prefix: str, device: GoodweDevice) -> dict[str, SensorSpec]:
    """The BMS readings, shared by the first and second battery."""
    return {
        f"{prefix}_soh": _diag("state_of_health", device),
        f"{prefix}_temperature": _diag("temperature", device),
        f"{prefix}_status": _hidden("bms_status", device),
        f"{prefix}_modules": _hidden("battery_modules", device),
        f"{prefix}_protocol": _hidden("battery_protocol", device),
        f"{prefix}_error_l": _hidden("error_code_low", device),
        f"{prefix}_error_h": _hidden("error_code_high", device),
        f"{prefix}_warning_l": _hidden("warning_code_low", device),
        f"{prefix}_warning_h": _hidden("warning_code_high", device),
        f"{prefix}_error": _diag("errors", device),
        f"{prefix}_warning": _diag("warnings", device),
        f"{prefix}_charge_limit": _diag("max_charge_current", device),
        f"{prefix}_discharge_limit": _diag("max_discharge_current", device),
        f"{prefix}_max_cell_temp": _diag("max_cell_temperature", device),
        f"{prefix}_min_cell_temp": _diag("min_cell_temperature", device),
        f"{prefix}_max_cell_voltage": _diag("max_cell_voltage", device),
        f"{prefix}_min_cell_voltage": _diag("min_cell_voltage", device),
        f"{prefix}_max_cell_temp_id": _hidden("max_cell_temperature_id", device),
        f"{prefix}_min_cell_temp_id": _hidden("min_cell_temperature_id", device),
        f"{prefix}_max_cell_voltage_id": _hidden("max_cell_voltage_id", device),
        f"{prefix}_min_cell_voltage_id": _hidden("min_cell_voltage_id", device),
        f"{prefix}_sw_version": _diag("bms_software_version", device),
        f"{prefix}_hw_version": _diag("hardware_version", device),
    }


def _pv_strings() -> dict[str, SensorSpec]:
    specs: dict[str, SensorSpec] = {}
    for n in range(1, 5):
        placeholders = {"string": str(n)}
        specs[f"vpv{n}"] = _diag("pv_string_voltage", placeholders=placeholders)
        specs[f"ipv{n}"] = _diag("pv_string_current", placeholders=placeholders)
        specs[f"ppv{n}"] = _main("pv_string_power", placeholders=placeholders)
        specs[f"pv{n}_mode"] = _hidden(
            "pv_string_status", placeholders=placeholders, states=_PV_STRING_STATUS
        )
    # Larger models report voltage and current only, for up to 16 strings
    for n in range(5, 17):
        placeholders = {"string": str(n)}
        specs[f"vpv{n}"] = _hidden("pv_string_voltage", placeholders=placeholders)
        specs[f"ipv{n}"] = _hidden("pv_string_current", placeholders=placeholders)
    for n in range(1, 9):
        placeholders = {"mppt": str(n)}
        specs[f"pmppt{n}"] = _hidden("mppt_power", placeholders=placeholders)
        specs[f"imppt{n}"] = _hidden("mppt_current", placeholders=placeholders)
    return specs


ET_SENSORS: dict[str, SensorSpec] = {
    # Power flow and status, as on the app's home screen
    "ppv": _main("pv_power"),
    "active_power": _main("grid_power", negate=True),
    "house_consumption": _main("load_power"),
    "backup_ptotal": _main("backup_load_power"),
    "work_mode": _main("status", states=_STATUS),
    "grid_mode": _main("grid", states=_GRID),
    "grid_in_out": _hidden("grid_direction", states=_GRID_DIRECTION),
    "e_day": _main("pv_energy_today"),
    "e_total": _main("pv_energy_total"),
    "e_load_day": _main("consumption_today"),
    "e_load_total": _main("consumption_total"),
    # What passes the inverter's AC port; the meter has the grid's totals
    "e_day_exp": _hidden("ac_output_today"),
    "e_total_exp": _hidden("ac_output_total"),
    "e_day_imp": _hidden("ac_input_today"),
    "e_total_imp": _hidden("ac_input_total"),
    "h_total": _diag("operating_hours"),
    **_pv_strings(),
    "ppv_total": _hidden("pv_power_mppt_total"),
    "pv_channel": _hidden("pv_channels"),
    # Inverter AC side
    **_phased("vgrid vgrid2 vgrid3", _diag("ac_voltage"), "phase_ac_voltage"),
    **_phased("igrid igrid2 igrid3", _diag("ac_current"), "phase_ac_current"),
    **_phased("fgrid fgrid2 fgrid3", _diag("ac_frequency"), "phase_ac_frequency"),
    **_phased("pgrid pgrid2 pgrid3", _diag("ac_power"), "phase_ac_power"),
    "total_inverter_power": _hidden("inverter_power"),
    "reactive_power": _hidden("reactive_power"),
    "apparent_power": _hidden("apparent_power"),
    **_phased(
        "reactive_power1 reactive_power2 reactive_power3",
        _hidden("phase_reactive_power", placeholders={"phase": "1"}),
        "phase_reactive_power",
    ),
    **_phased(
        "apparent_power1 apparent_power2 apparent_power3",
        _hidden("phase_apparent_power", placeholders={"phase": "1"}),
        "phase_apparent_power",
    ),
    # Backup port
    **_phased(
        "backup_v1 backup_v2 backup_v3", _diag("backup_voltage"), "phase_backup_voltage"
    ),
    **_phased(
        "backup_i1 backup_i2 backup_i3", _diag("backup_current"), "phase_backup_current"
    ),
    **_phased(
        "backup_f1 backup_f2 backup_f3",
        _hidden("backup_frequency"),
        "phase_backup_frequency",
    ),
    **_phased(
        "backup_p1 backup_p2 backup_p3",
        _hidden("phase_backup_power", placeholders={"phase": "1"}),
        "phase_backup_power",
    ),
    **{
        f"load_mode{n}": _hidden("phase_load_mode", placeholders={"phase": str(n)})
        for n in range(1, 4)
    },
    **{
        f"load_p{n}": _hidden(
            "phase_on_grid_load_power", placeholders={"phase": str(n)}
        )
        for n in range(1, 4)
    },
    "load_ptotal": _hidden("on_grid_load_power"),
    "ups_load": _diag("backup_load_rate"),
    # Inverter health
    "temperature": _diag("temperature"),
    "temperature_air": _hidden("air_temperature"),
    "temperature_module": _hidden("module_temperature"),
    "bus_voltage": _hidden("bus_voltage"),
    "nbus_voltage": _hidden("negative_bus_voltage"),
    "function_bit": _hidden("function_bits"),
    "warning_code": _hidden("warning_code"),
    "error_codes": _hidden("error_code"),
    "errors": _diag("errors"),
    "diagnose_result": _hidden("diagnostic_status_code"),
    "diagnose_result_label": _diag("diagnostic_status"),
    "safety_country": _hidden("safety_country_code"),
    "safety_country_label": _hidden("safety_country"),
    "timestamp": _hidden("inverter_clock"),
    "operation_mode": _hidden("running_mode_code", WORK_MODE),
    # Battery
    "pbattery1": _main("battery_power", BATTERY),
    "battery_soc": _main("state_of_charge", BATTERY),
    "battery_mode": _main("status", BATTERY, states=_BATTERY_STATUS),
    "vbattery1": _diag("voltage", BATTERY),
    "ibattery1": _diag("current", BATTERY),
    "e_bat_charge_day": _main("charge_today", BATTERY),
    "e_bat_charge_total": _main("charge_total", BATTERY),
    "e_bat_discharge_day": _main("discharge_today", BATTERY),
    "e_bat_discharge_total": _main("discharge_total", BATTERY),
    "battery_bms": _hidden("bms", BATTERY),
    "battery_index": _hidden("battery_index", BATTERY),
    **_battery("battery", BATTERY),
    "pbattery2": _main("battery_power", BATTERY_2),
    "battery2_soc": _main("state_of_charge", BATTERY_2),
    "battery2_mode": _main("status", BATTERY_2, states=_BATTERY_STATUS),
    "vbattery2": _diag("voltage", BATTERY_2),
    "ibattery2": _diag("current", BATTERY_2),
    **_battery("battery2", BATTERY_2),
    # Smart meter
    "meter_e_total_exp": _main("export_total", METER),
    "meter_e_total_imp": _main("import_total", METER),
    **{
        f"meter_e_total_exp{n}": _hidden(
            "phase_export_total", METER, placeholders={"phase": str(n)}
        )
        for n in range(1, 4)
    },
    **{
        f"meter_e_total_imp{n}": _hidden(
            "phase_import_total", METER, placeholders={"phase": str(n)}
        )
        for n in range(1, 4)
    },
    "active_power_total": _diag("power", METER, negate=True),
    **{
        f"active_power{n}": _hidden(
            "phase_power", METER, placeholders={"phase": str(n)}, negate=True
        )
        for n in range(1, 4)
    },
    "meter_active_power_total": _hidden("active_power", METER, negate=True),
    **{
        f"meter_active_power{n}": _hidden(
            "phase_active_power", METER, placeholders={"phase": str(n)}, negate=True
        )
        for n in range(1, 4)
    },
    "reactive_power_total": _hidden("reactive_power", METER),
    "meter_reactive_power_total": _hidden("meter_reactive_power", METER),
    **{
        f"meter_reactive_power{n}": _hidden(
            "phase_reactive_power", METER, placeholders={"phase": str(n)}
        )
        for n in range(1, 4)
    },
    "meter_apparent_power_total": _hidden("apparent_power", METER),
    **{
        f"meter_apparent_power{n}": _hidden(
            "phase_apparent_power", METER, placeholders={"phase": str(n)}
        )
        for n in range(1, 4)
    },
    "meter_power_factor": _diag("power_factor", METER),
    **{
        f"meter_power_factor{n}": _hidden(
            "phase_power_factor", METER, placeholders={"phase": str(n)}
        )
        for n in range(1, 4)
    },
    "meter_freq": _diag("frequency", METER),
    **_phased(
        "meter_voltage1 meter_voltage2 meter_voltage3",
        _diag("voltage", METER),
        "phase_voltage",
        METER,
    ),
    **_phased(
        "meter_current1 meter_current2 meter_current3",
        _diag("current", METER),
        "phase_current",
        METER,
    ),
    "meter_comm_status": _hidden("communication_status", METER),
    "meter_test_status": _hidden("test_status", METER),
    "meter_type": _hidden("meter_type", METER),
    "meter_sw_version": _hidden("software_version", METER),
    "commode": _hidden("communication_mode", METER),
    "rssi": _hidden("signal_strength", METER),
    "manufacture_code": _hidden("manufacturer_code", METER),
    "meter2_active_power": _hidden("meter_2_power", METER, negate=True),
    "meter2_e_total_exp": _hidden("meter_2_export_total", METER),
    "meter2_e_total_imp": _hidden("meter_2_import_total", METER),
    "meter2_comm_status": _hidden("meter_2_communication_status", METER),
}

# Shown by default for families without a curated table, as Home Assistant's
# built-in integration does
_FALLBACK_MAIN = frozenset(
    {
        "ppv",
        "house_consumption",
        "active_power",
        "battery_soc",
        "e_day",
        "e_total",
        "meter_e_total_exp",
        "meter_e_total_imp",
        "e_bat_charge_total",
        "e_bat_discharge_total",
    }
)


def sensor_spec(inverter: Inverter, sensor: Sensor) -> SensorSpec | None:
    """How a runtime sensor is shown, or None if it is not worth an entity."""
    if isinstance(inverter, ET):
        if sensor.id_ in _SKIPPED:
            return None
        if (spec := ET_SENSORS.get(sensor.id_)) is not None:
            return spec
    if sensor.id_ in _FALLBACK_MAIN:
        return SensorSpec(
            device=_fallback_device(sensor), entity_category=None, enabled=True
        )
    return SensorSpec(device=_fallback_device(sensor))


def _fallback_device(sensor: Sensor) -> GoodweDevice:
    if sensor.id_.startswith("meter"):
        return METER
    if sensor.kind is SensorKind.BAT:
        return BATTERY
    return INVERTER
