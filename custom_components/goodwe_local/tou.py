"""Time-of-use slots, read from the inverter's eco mode groups."""

from dataclasses import dataclass
from typing import Self

from goodwe import Inverter
from goodwe.sensor import Schedule, ScheduleType

TOU_SLOTS = 4
# Work mode 3.0 firmware has 8, like the SEMS portal shows
TOU_SLOTS_V3 = 8

_WEEKDAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
_ALL_MONTHS = 0x0FFF


@dataclass(frozen=True, slots=True)
class TouSlot:
    """One eco mode group as the GoodWe apps show it."""

    index: int
    # Unused groups hold 48 (0x30) as their hours, or no days at all
    configured: bool
    enabled: bool
    charging: bool
    start: str | None
    end: str | None
    # Percent of the rated power
    power: int
    # A discharge slot limits grid export rather than battery discharge
    export_limited: bool
    cutoff_soc: int
    days: tuple[str, ...]
    months: tuple[int, ...]

    @classmethod
    def from_schedule(cls, index: int, schedule: Schedule) -> Self:
        """Convert the library's group, which it reuses for every read."""
        configured = (
            0 <= schedule.start_h <= 23
            and 0 <= schedule.end_h <= 23
            and schedule.day_bits & 0x7F != 0
            and schedule.schedule_type is not ScheduleType.NOT_SET
        )
        power = schedule.get_power()
        return cls(
            index=index,
            configured=configured,
            # On is stored as -1 - schedule type, off as the type itself
            enabled=schedule.on_off < 0,
            charging=power < 0,
            start=_time(schedule.start_h, schedule.start_m) if configured else None,
            end=_time(schedule.end_h, schedule.end_m) if configured else None,
            power=abs(power),
            export_limited=bool(schedule.export_limit) and power >= 0,
            cutoff_soc=schedule.soc,
            days=_days(schedule.day_bits),
            months=_months(schedule.month_bits),
        )


def _time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _days(bits: int) -> tuple[str, ...]:
    bits &= 0x7F
    return tuple(day for n, day in enumerate(_WEEKDAYS) if bits & (1 << n))


def _months(bits: int) -> tuple[int, ...]:
    # Bit 12 is the export limit flag, not a month
    bits &= _ALL_MONTHS
    if bits == 0:
        bits = _ALL_MONTHS
    return tuple(month + 1 for month in range(12) if bits & (1 << month))


# Groups of other types (peak shaving, smart charge, dry contact) belong to
# other modes, which their own switches control
_TOU_TYPES = (ScheduleType.ECO_MODE, ScheduleType.ECO_MODE_745)


async def async_set_tou_slot(inverter: Inverter, index: int, enabled: bool) -> None:
    """Turn an existing slot on or off, writing only its on/off byte.

    Everything else about a slot is set in the GoodWe app or through SEMS+,
    which check the values before they reach the inverter.
    """
    schedule = await inverter.read_setting(f"eco_mode_{index}")
    if not isinstance(schedule, Schedule):
        raise ValueError("this firmware's eco mode groups are not supported")
    if not TouSlot.from_schedule(index, schedule).configured:
        raise ValueError("the slot has no times; set it up in the GoodWe app first")
    schedule_type = schedule.schedule_type
    if schedule_type not in _TOU_TYPES:
        raise ValueError(f"the slot holds a {schedule_type.name.lower()} schedule")
    # The high byte of the group's third register; the day bits beside it
    # are read back and kept
    await inverter.write_setting(
        f"eco_mode_{index}_switch",
        -1 - schedule_type if enabled else int(schedule_type),
    )


async def async_read_tou_slots(inverter: Inverter) -> dict[int, TouSlot]:
    """Read the eco mode groups; older firmware has no slots in this form."""
    count = TOU_SLOTS_V3 if getattr(inverter, "has_work_mode_v3", False) else TOU_SLOTS
    slots: dict[int, TouSlot] = {}
    for index in range(1, count + 1):
        schedule = await inverter.read_setting(f"eco_mode_{index}")
        if not isinstance(schedule, Schedule):
            raise ValueError("Eco mode groups without SOC and months")
        slots[index] = TouSlot.from_schedule(index, schedule)
    return slots
