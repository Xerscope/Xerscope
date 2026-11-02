"""Tunable defaults. Thresholds that come from a standard live in analysis/standards.py."""

from dataclasses import dataclass

DATE_FMT = "%Y-%m-%d"
DATETIME_FMT = "%Y-%m-%d %H:%M"  # P6's own XER and screen format


@dataclass(frozen=True)
class Settings:
    default_hours_per_day: float = 8.0  # used when a task's calendar is missing
    critical_float_days: float = 0.0  # total float <= this => critical
    near_critical_float_days: float = 10.0  # Gantt colouring only


DEFAULT_SETTINGS = Settings()
