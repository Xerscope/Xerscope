"""P6 work calendars, read from ``CALENDAR.clndr_data``.

The blob is a tree of nodes ``(0||<name>(<attrs>)(<children>))``::

    (0||CalendarData()(
      (0||DaysOfWeek()(
        (0||1()())                                  1 = Sunday ... 7 = Saturday
        (0||2()((0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())))
        ...))
      (0||Exceptions()(
        (0||0(d|43650)())                           non-working day (Excel serial date)
        (0||1(d|43651)((0||0(s|08:00|f|12:00)())))  working day with its own hours

Working periods are kept per day, so working hours between two timestamps are exact
(CPM, float, durations).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..config import DEFAULT_SETTINGS
from .parser import XerError

EXCEL_EPOCH = date(1899, 12, 30)
DAY_START_MINUTE = 8 * 60  # a calendar without a blob works from 08:00
MINUTES_PER_DAY = 24 * 60
DEFAULT_WORKING_DAYS = 5  # a calendar with neither blob nor week hours is Monday to Friday
AXIS_MARGIN_DAYS = 366  # the axis starts a year before the first exception date
AXIS_SPAN_DAYS = 3 * 366  # and runs three years after it, then grows on demand
DAYS_DECIMALS = 6  # a minute is 7e-4 day of a 24 h day: rounding at 1e-6 day merges no two minutes
MIN_HOURS_PER_DAY = 1 / 60  # a working day shorter than a minute has no working time on the axis
MAX_TREE_DEPTH = 32  # a clndr_data tree is 5 levels deep; deeper is not a calendar
# The axis works in nanoseconds since the epoch (``Timestamp.value``): the dates it can hold, and the
# exception dates a calendar keeps (the axis opens AXIS_MARGIN_DAYS before the first exception and
# AXIS_SPAN_DAYS after it). An exception outside that range is a malformed blob.
AXIS_FIRST_DATE = (pd.Timestamp.min + pd.Timedelta(days=1)).date()  # 1677-09-22
AXIS_LAST_DATE = (pd.Timestamp.max - pd.Timedelta(days=1)).date()  # 2262-04-10
EXCEPTION_FIRST_DATE = AXIS_FIRST_DATE + timedelta(days=AXIS_MARGIN_DAYS)
EXCEPTION_LAST_DATE = AXIS_LAST_DATE - timedelta(days=AXIS_SPAN_DAYS)


def hours_to_days(hours, hours_per_day):
    """Working days from working hours, for a number, a Series or an array.

    P6 stores N days of a calendar as N x its hours per day, in decimal hours, and the
    binary division does not always give N back: 360.8 h / 8.2 is 44.00000000000001, and
    44 days would then count as more than 44. Rounded to ``DAYS_DECIMALS``.
    """
    return np.round(hours / hours_per_day, DAYS_DECIMALS)


@dataclass
class _Node:
    name: str
    attrs: str
    children: list[_Node] = field(default_factory=list)

    def find(self, name: str) -> _Node | None:
        if self.name == name:
            return self
        for c in self.children:
            hit = c.find(name)
            if hit is not None:
                return hit
        return None


def _parse_tree(text: str) -> list[_Node]:
    # Exporters separate nodes with whitespace or DEL (\x7f) characters: drop them.
    s = "".join(ch for ch in text if ch not in " \t\r\n\x7f")
    pos = 0

    def node(depth: int = 0) -> _Node:
        nonlocal pos
        if depth > MAX_TREE_DEPTH:
            raise ValueError(f"nested deeper than {MAX_TREE_DEPTH} levels at {pos}")
        if s[pos] != "(":
            raise ValueError(f"expected '(' at {pos}")
        bar = s.index("||", pos)
        name_end = s.index("(", bar + 2)
        name = s[bar + 2 : name_end]
        attrs_end = s.index(")", name_end)
        attrs = s[name_end + 1 : attrs_end]
        pos = attrs_end + 1
        if s[pos] != "(":
            raise ValueError(f"expected children at {pos}")
        pos += 1
        children = []
        while s[pos] == "(":
            children.append(node(depth + 1))
        if s[pos] != ")":
            raise ValueError(f"expected ')' at {pos}")
        pos += 1  # end of children
        if s[pos] != ")":
            raise ValueError(f"expected ')' at {pos}")
        pos += 1  # end of node
        return _Node(name, attrs, children)

    out = []
    while pos < len(s) and s[pos] == "(":
        out.append(node())
    if pos != len(s):
        raise ValueError(f"unexpected text at {pos}: {s[pos : pos + 20]!r}")
    return out


def _attrs(text: str) -> dict[str, str]:
    parts = text.split("|")
    return dict(zip(parts[0::2], parts[1::2], strict=False))  # an odd trailing key is ignored


Intervals = tuple[tuple[int, int], ...]  # working periods of one day, minutes from midnight


def _minute(text: str) -> int:
    """'HH:MM' -> minutes from midnight; anything else is a malformed period."""
    hours, sep, minutes = text.partition(":")
    if not (sep and hours.isdigit() and minutes.isdigit() and int(hours) <= 24 and int(minutes) < 60):
        raise ValueError(f"malformed working period time {text!r}")
    return int(hours) * 60 + int(minutes)


# A period P6's calendar dialog cannot enter, read the way MPXJ reads it: overview, "Limits".
LIMIT_MARK = "dates on this calendar may differ from P6"


def _interval(n: _Node, notes: list[str] | None = None) -> tuple[int, int] | None:
    """One working period, minutes from midnight; None for an empty one.

    Only "f|00:00" ends at midnight, as MPXJ 16.10 reads it (LocalTimeHelper.getMillisecondsInRange:
    an end at MIDNIGHT runs to the end of the day, any other end gives end - start). A period
    ending at its start is empty. One ending before its start (22:00-06:00) crosses midnight:
    P6's dialog enters a night shift day by day (22:00-24:00, then 00:00-06:00 the next day) and
    no reference file holds one, so its meaning is unknown. It counts no work, as MPXJ reads it
    (0 h), and is named in ``notes`` with LIMIT_MARK.
    """
    a = _attrs(n.attrs)
    if "s" not in a or "f" not in a:
        raise ValueError(f"working period without start and finish {n.attrs!r}")
    start, end = _minute(a["s"]), _minute(a["f"])
    if end == 0:  # "f|00:00" = midnight at the end of the day
        end = MINUTES_PER_DAY
    if end < start:
        note = f"working period {a['s']}-{a['f']} crosses midnight: no work counted; {LIMIT_MARK}"
        if notes is not None and note not in notes:
            notes.append(note)
        return None
    return (start, min(end, MINUTES_PER_DAY)) if end > start else None


def _day(n: _Node, notes: list[str] | None = None) -> Intervals:
    return _merge(i for i in (_interval(c, notes) for c in n.children) if i)


def _merge(periods) -> Intervals:
    """Sorted, with overlapping or touching periods joined, so no minute counts twice."""
    out: list[list[int]] = []
    for a, b in sorted(periods):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return tuple((a, b) for a, b in out)


def parse_clndr_data(
    text: str, notes: list[str] | None = None
) -> tuple[tuple[Intervals, ...], dict[date, Intervals]] | None:
    """Return (working periods Monday..Sunday, {date: periods} exceptions), or None when the
    blob holds no week. P6 never writes a malformed blob: one raises ValueError naming the fault
    (a malformed node, a period time that is not ``HH:MM``, a tree nested past ``MAX_TREE_DEPTH``,
    an exception dated outside ``EXCEPTION_FIRST_DATE`` .. ``EXCEPTION_LAST_DATE``).
    A period read with a limit (see ``_interval``) adds one line to ``notes`` when given."""
    if not isinstance(text, str) or "DaysOfWeek" not in text:
        return None
    try:
        return _read_blob(text, notes)
    except (IndexError, RecursionError) as err:
        raise ValueError(f"malformed calendar data ({type(err).__name__})") from err


def _read_blob(text: str, notes: list[str] | None) -> tuple[tuple[Intervals, ...], dict[date, Intervals]] | None:
    roots = _parse_tree(text)
    dow = next((r.find("DaysOfWeek") for r in roots if r.find("DaysOfWeek")), None)
    if dow is None:
        return None
    week: list[Intervals] = [()] * 7
    for d in dow.children:
        if d.name.isdigit() and 1 <= int(d.name) <= 7:
            week[(int(d.name) + 5) % 7] = _day(d, notes)  # P6 1=Sunday -> Python weekday 6
    exceptions: dict[date, Intervals] = {}
    exc = next((r.find("Exceptions") for r in roots if r.find("Exceptions")), None)
    first, last = (EXCEPTION_FIRST_DATE - EXCEL_EPOCH).days, (EXCEPTION_LAST_DATE - EXCEL_EPOCH).days
    for e in exc.children if exc is not None else []:
        serial = _attrs(e.attrs).get("d", "")
        if not serial.isdigit():
            raise ValueError(f"malformed exception date {serial!r}")
        if not first <= int(serial) <= last:
            raise ValueError(
                f"exception date out of range {serial!r} (outside {EXCEPTION_FIRST_DATE}..{EXCEPTION_LAST_DATE})"
            )
        exceptions[EXCEL_EPOCH + timedelta(days=int(serial))] = _day(e, notes)
    return tuple(week), exceptions


def _default_day(hpd: float) -> Intervals:
    """One working period from 08:00, ``hpd`` hours long, at least a minute, at most to midnight."""
    if hpd >= 24:
        return ((0, MINUTES_PER_DAY),)
    end = min(MINUTES_PER_DAY, DAY_START_MINUTE + int(round(hpd * 60)))
    return ((DAY_START_MINUTE, max(end, DAY_START_MINUTE + 1)),)


@dataclass(frozen=True)
class WorkCalendar:
    clndr_id: str
    name: str
    hours_per_day: float
    week: tuple[Intervals, ...]  # Monday .. Sunday
    exceptions: dict[date, Intervals] = field(default_factory=dict, hash=False, compare=False)
    from_data: bool = True  # False = workweek guessed from the day/week hour counts
    notes: tuple[str, ...] = field(default=(), compare=False, hash=False)  # what from_row had to repair
    # the calendar's own TimeAxis, built on first use (a cache, not part of the value)
    _axis: TimeAxis | None = field(default=None, init=False, repr=False, hash=False, compare=False)

    @classmethod
    def from_row(cls, row: pd.Series, default_hpd: float = DEFAULT_SETTINGS.default_hours_per_day) -> WorkCalendar:
        notes: list[str] = []
        hpd = pd.to_numeric(row.get("day_hr_cnt"), errors="coerce")
        if pd.notna(hpd) and 0 < hpd < MIN_HOURS_PER_DAY:
            notes.append(f"day_hr_cnt {hpd} is under one minute; {default_hpd} h/day used")
        hpd = float(hpd) if pd.notna(hpd) and hpd >= MIN_HOURS_PER_DAY else default_hpd
        try:
            parsed = parse_clndr_data(row.get("clndr_data", ""), notes)
        except ValueError as err:
            raise XerError(
                f"CALENDAR {row['clndr_id']} {str(row.get('clndr_name', ''))!r}: {err}; P6 does not write this"
            ) from err
        if parsed is not None and any(parsed[0]):
            week, exc = parsed
            return cls(str(row["clndr_id"]), str(row.get("clndr_name", "")), hpd, week, exc, notes=tuple(notes))
        # No usable blob, or one without a working weekday: infer the number of working days
        # from the week's hour count. The blob's exceptions still hold (MPXJ, ProjectCalendarHelper
        # .ensureWorkingTime, also fills in a default week and keeps them).
        if parsed is not None:
            notes.append("no working weekday in clndr_data; workweek inferred from the hour counts")
        whc = pd.to_numeric(row.get("week_hr_cnt"), errors="coerce")
        n = int(round(whc / hpd)) if pd.notna(whc) and whc > 0 else DEFAULT_WORKING_DAYS
        n = min(max(n, 1), 7)
        day = _default_day(hpd)
        return cls(
            str(row["clndr_id"]),
            str(row.get("clndr_name", "")),
            hpd,
            tuple([day] * n + [()] * (7 - n)),
            parsed[1] if parsed is not None else {},
            from_data=False,
            notes=tuple(notes),
        )

    @classmethod
    def standard(cls, hpd: float = DEFAULT_SETTINGS.default_hours_per_day) -> WorkCalendar:
        day = _default_day(hpd)
        return cls(
            "",
            "Standard (Mon-Fri)",
            hpd,
            (day,) * DEFAULT_WORKING_DAYS + ((),) * (7 - DEFAULT_WORKING_DAYS),
            {},
            from_data=False,
        )

    def periods(self, d: date) -> Intervals:
        return self.exceptions.get(d, self.week[d.weekday()])

    def axis(self) -> TimeAxis:
        """This calendar's TimeAxis, built once and grown on demand: one arithmetic for all.

        The window starts around the first exception date, else around a fixed origin, and
        grows to whatever dates are asked of it: results never depend on the day the axis
        was built (``work_hours`` returns differences). The frozen dataclass keeps the cache
        in a declared field, set once through ``object.__setattr__``.
        """
        if self._axis is None:
            origin = min(self.exceptions) if self.exceptions else date(2020, 1, 1)
            ax = TimeAxis(self, origin - timedelta(days=AXIS_MARGIN_DAYS), origin + timedelta(days=AXIS_SPAN_DAYS))
            object.__setattr__(self, "_axis", ax)
        return self._axis

    def work_hours(self, a: pd.Timestamp, b: pd.Timestamp) -> float:
        """Working hours from ``a`` to ``b`` (negative if ``b`` is earlier), to the minute."""
        if a is None or b is None or pd.isna(a) or pd.isna(b):
            return float("nan")
        return self.axis().between(pd.Timestamp(a), pd.Timestamp(b)) / 60

    def working_days(self, a: pd.Timestamp, b: pd.Timestamp) -> float:
        """Working time from ``a`` to ``b`` in days of this calendar; NaN when a date is missing."""
        h = self.work_hours(a, b)
        return float("nan") if pd.isna(h) else float(hours_to_days(h, self.hours_per_day))


class TimeAxis:
    """One calendar's working periods on an absolute minute axis, for exact date arithmetic.

    ``work(ts)`` = working minutes from the axis origin to ``ts`` (non-working time maps to
    the next period's start, so the mapping is continuous and monotone). ``at(w, finish)``
    is its inverse. On a boundary the two conventions P6 uses differ:

    - a start is the beginning of a working period (Tuesday 08:00), and
    - a finish is the end of one (Monday 17:00),

    which are the same working-minute value. Every scheduled date is produced through
    ``at`` with the right convention, so durations land exactly as P6 shows them.

    The axis grows on demand (a 600-day critical path test runs years ahead, negative
    float runs back before the data date). Work values are anchored on the first origin,
    so a value computed before the axis grew stays valid after (it can be negative).
    """

    def __init__(self, cal: WorkCalendar, first: date, last: date):
        self.cal = cal
        self._check_range(first, last)
        self.anchor_ns = pd.Timestamp(first).value
        # the most working minutes any day of this calendar holds: bounds how far ``at`` may reach
        days = [*cal.week, *cal.exceptions.values()]
        self.max_day_minutes = max(1, *(sum(b - a for a, b in periods if b > a) for periods in days))
        self._build(first, last)

    def _periods(self, first: date, last: date) -> tuple[np.ndarray, np.ndarray]:
        """Working periods of [first, last] as minute offsets from ``first``, in day order then
        period order: the weekday pattern laid out with numpy, the exception days replaced."""
        n_days = (last - first).days + 1
        dated = {(d - first).days: periods for d, periods in self.cal.exceptions.items() if first <= d <= last}
        dated_days = np.fromiter(dated, dtype=np.int64, count=len(dated))
        day_of, starts, ends = [], [], []
        for weekday in range(7):
            periods = [(a, b) for a, b in self.cal.week[weekday] if b > a]
            if not periods:
                continue
            on_days = np.arange((weekday - first.weekday()) % 7, n_days, 7, dtype=np.int64)
            if len(dated):
                on_days = on_days[~np.isin(on_days, dated_days)]
            midnight = on_days * MINUTES_PER_DAY
            for a, b in periods:
                day_of.append(on_days)
                starts.append(midnight + a)
                ends.append(midnight + b)
        for day, periods in dated.items():
            for a, b in periods:
                if b > a:
                    day_of.append(np.array([day], dtype=np.int64))
                    starts.append(np.array([day * MINUTES_PER_DAY + a], dtype=np.int64))
                    ends.append(np.array([day * MINUTES_PER_DAY + b], dtype=np.int64))
        if not starts:
            return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
        all_starts, all_ends, all_days = np.concatenate(starts), np.concatenate(ends), np.concatenate(day_of)
        del starts, ends, day_of
        order = np.lexsort((all_starts, all_days))
        return all_starts[order], all_ends[order]

    def _check_range(self, first: date, last: date) -> None:
        if first < AXIS_FIRST_DATE or last > AXIS_LAST_DATE:
            raise ValueError(
                f"date out of range: calendar {self.cal.name!r} would run {first}..{last}, "
                f"outside {AXIS_FIRST_DATE}..{AXIS_LAST_DATE}"
            )

    def _build(self, first: date, last: date) -> None:
        self._check_range(first, last)
        starts, ends = self._periods(first, last)
        while len(starts) == 0:  # e.g. a short window over a shutdown: look further ahead
            if (last - first).days > 20 * 366:
                raise ValueError(f"calendar {self.cal.name!r} has no working time")
            last += timedelta(days=400)
            starts, ends = self._periods(first, last)
        self.first, self.last = first, last
        self.t0 = pd.Timestamp(first)
        self.t0_ns = self.t0.value
        self.span_min = ((last - first).days + 1) * 1440
        self.starts = starts
        self.ends = ends
        lengths = self.ends - self.starts
        self.cum = np.concatenate([[0], np.cumsum(lengths)]).astype(np.int64)  # work before period i
        self.base = int(self._raw(np.array([(self.anchor_ns - self.t0_ns) // 60_000_000_000]))[0])

    def _raw(self, m: np.ndarray) -> np.ndarray:
        """Working minutes from this build's first day to minute offsets ``m``."""
        i = np.searchsorted(self.ends, m, side="left")  # first period ending at/after m
        ic = np.minimum(i, len(self.starts) - 1)
        w = np.where(m <= self.starts[ic], self.cum[ic], self.cum[ic] + (m - self.starts[ic]))
        return np.where(i >= len(self.starts), self.cum[-1], w)

    def _grow(self, earlier: bool) -> None:
        """Double the window towards the past or the future, up to the dates the axis can hold."""
        span = timedelta(days=max(400, (self.last - self.first).days))
        first = max(AXIS_FIRST_DATE, self.first - span) if earlier else self.first
        last = self.last if earlier else min(AXIS_LAST_DATE, self.last + span)
        if (first, last) == (self.first, self.last):
            raise ValueError(f"date out of range: calendar {self.cal.name!r} ends at {first}..{last}")
        self._build(first, last)

    def _ensure(self, ts: pd.Timestamp, margin_days: int = 400) -> None:
        d = ts.date()
        if d < self.first or d > self.last:
            margin = timedelta(days=margin_days)
            first = min(self.first, max(AXIS_FIRST_DATE, d - margin))
            last = max(self.last, min(AXIS_LAST_DATE, d + margin))
            self._build(first, last)  # raises "date out of range" when ``d`` itself is outside

    def minute(self, ts) -> int:
        ts = ts if isinstance(ts, pd.Timestamp) else pd.Timestamp(ts)
        try:
            ns = ts.value
        except OverflowError as exc:  # a Timestamp with a coarser unit, outside the nanosecond range
            raise ValueError(f"date out of range: {ts} is outside {AXIS_FIRST_DATE}..{AXIS_LAST_DATE}") from exc
        m = (ns - self.t0_ns) // 60_000_000_000
        if m < 0 or m >= self.span_min:
            self._ensure(ts)
            m = (ts.value - self.t0_ns) // 60_000_000_000
        return int(m)

    def work(self, ts) -> int:
        """Working minutes from the anchor (the first origin) to ``ts``."""
        m = self.minute(ts)
        return int(self._raw(np.array([m]))[0]) - self.base

    def work_many(self, stamps) -> np.ndarray:
        """``work`` for an array of timestamps at once (NaT -> 0, check for NaT yourself)."""
        ts = pd.DatetimeIndex(pd.to_datetime(pd.Series(stamps).reset_index(drop=True))).as_unit("ns")
        ok = ~ts.isna()
        if not ok.any():
            return np.zeros(len(ts), dtype=np.int64)
        self._ensure(ts[ok].min())
        self._ensure(ts[ok].max())
        m = (ts.asi8 - self.t0_ns) // 60_000_000_000
        return np.where(ok, self._raw(m) - self.base, 0).astype(np.int64)

    def at(self, w: float, finish: bool) -> pd.Timestamp:
        """Timestamp after ``w`` working minutes; on a boundary, a period end if ``finish``."""
        w = int(round(w))
        # No day holds more than ``max_day_minutes`` of work: a value that needs more calendar days
        # than the Timestamp range has left fails here, before the axis grows towards it.
        r = w + self.base
        days_needed = abs(r) // self.max_day_minutes - 1
        room = (AXIS_LAST_DATE - self.first).days if r >= 0 else (self.first - AXIS_FIRST_DATE).days
        if days_needed > room:
            raise ValueError(f"date out of range: {w} working minutes on calendar {self.cal.name!r}")
        while w + self.base < 0 or (finish and w + self.base == 0):
            self._grow(earlier=True)
        while w + self.base > self.cum[-1] or (not finish and w + self.base == self.cum[-1]):
            self._grow(earlier=False)
        r = w + self.base
        if finish:
            i = int(np.searchsorted(self.cum[1:], r, side="left"))  # first period whose end >= r
            m = self.ends[i] - (self.cum[i + 1] - r)
        else:
            i = int(np.searchsorted(self.cum[1:], r, side="right"))  # first period whose end > r
            m = self.starts[i] + (r - self.cum[i])
        return pd.Timestamp(self.t0_ns + int(m) * 60_000_000_000)

    # convenience ------------------------------------------------------------------------
    def is_working(self, ts) -> bool:
        """``ts`` lies inside a working period or on one of its bounds."""
        m = self.minute(ts)
        i = int(np.searchsorted(self.ends, m, side="left"))
        return i < len(self.starts) and self.starts[i] <= m

    def keep_or_next(self, ts) -> pd.Timestamp:
        """``ts`` if working (bounds included), else the next period's start."""
        return pd.Timestamp(ts) if self.is_working(ts) else self.snap_start(ts)

    def keep_or_previous(self, ts) -> pd.Timestamp:
        """``ts`` if working (bounds included), else the previous period's end."""
        return pd.Timestamp(ts) if self.is_working(ts) else self.snap_finish(ts)

    def snap_start(self, ts) -> pd.Timestamp:
        return self.at(self.work(ts), finish=False)

    def snap_finish(self, ts) -> pd.Timestamp:
        return self.at(self.work(ts), finish=True)

    def add(self, ts, minutes: float, finish: bool = True) -> pd.Timestamp:
        return self.at(self.work(ts) + minutes, finish)

    def between(self, a, b) -> int:
        """Working minutes from a to b (negative if b is earlier)."""
        return self.work(b) - self.work(a)
