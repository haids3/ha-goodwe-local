"""Time-of-use slots, read from the inverter's eco mode groups."""

from dataclasses import dataclass
from typing import Self

from goodwe import Inverter
from goodwe.sensor import Schedule

TOU_SLOTS = 4

_WEEKDAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
_ALL_MONTHS = 0x0FFF


@dataclass(frozen=True, slots=True)
class TouSlot:
    """One eco mode group as the GoodWe apps show it."""

    index: int
    # Unused groups hold 48 (0x30) as their hours
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
        configured = 0 <= schedule.start_h <= 23 and 0 <= schedule.end_h <= 23
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


async def async_read_tou_slots(inverter: Inverter) -> dict[int, TouSlot]:
    """Read the eco mode groups; older firmware has no slots in this form."""
    slots: dict[int, TouSlot] = {}
    for index in range(1, TOU_SLOTS + 1):
        schedule = await inverter.read_setting(f"eco_mode_{index}")
        if not isinstance(schedule, Schedule):
            raise ValueError("Eco mode groups without SOC and months")
        slots[index] = TouSlot.from_schedule(index, schedule)
    return slots
