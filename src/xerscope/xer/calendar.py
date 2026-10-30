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
(CPLI, the CPM test axis); PV spreading works per day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

EXCEL_EPOCH = date(1899, 12, 30)


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

    def node() -> _Node:
        nonlocal pos
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
            children.append(node())
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
    return out


def _attrs(text: str) -> dict[str, str]:
    parts = text.split("|")
    return dict(zip(parts[0::2], parts[1::2], strict=False))  # an odd trailing key is ignored


Intervals = tuple[tuple[int, int], ...]  # working periods of one day, minutes from midnight


def _interval(n: _Node) -> tuple[int, int] | None:
    a = _attrs(n.attrs)
    if "s" not in a or "f" not in a:
        return None
    h0, m0 = map(int, a["s"].split(":"))
    h1, m1 = map(int, a["f"].split(":"))
    start, end = h0 * 60 + m0, h1 * 60 + m1
    if end <= start:  # "f|00:00" = midnight at the end of the day
        end += 24 * 60
    return start, min(end, 24 * 60)


def _day(n: _Node) -> Intervals:
    return _merge(i for i in (_interval(c) for c in n.children) if i)


def _merge(periods) -> Intervals:
    """Sorted, with overlapping or touching periods joined, so no minute counts twice."""
    out: list[list[int]] = []
    for a, b in sorted(periods):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return tuple((a, b) for a, b in out)


def _hours(iv: Intervals) -> float:
    return sum(b - a for a, b in iv) / 60


def parse_clndr_data(text: str) -> tuple[tuple[Intervals, ...], dict[date, Intervals]] | None:
    """Return (working periods Monday..Sunday, {date: periods} exceptions), or None."""
    if not isinstance(text, str) or "DaysOfWeek" not in text:
        return None
    try:
        roots = _parse_tree(text)
    except (ValueError, IndexError):
        return None
    dow = next((r.find("DaysOfWeek") for r in roots if r.find("DaysOfWeek")), None)
    if dow is None:
        return None
    week: list[Intervals] = [()] * 7
    for d in dow.children:
        if d.name.isdigit() and 1 <= int(d.name) <= 7:
            week[(int(d.name) + 5) % 7] = _day(d)  # P6 1=Sunday -> Python weekday 6
    exceptions: dict[date, Intervals] = {}
    exc = next((r.find("Exceptions") for r in roots if r.find("Exceptions")), None)
    for e in exc.children if exc is not None else []:
        serial = _attrs(e.attrs).get("d")
        if serial and serial.lstrip("-").isdigit():
            exceptions[EXCEL_EPOCH + timedelta(days=int(serial))] = _day(e)
    return tuple(week), exceptions


def _default_day(hpd: float) -> Intervals:
    if hpd >= 24:
        return ((0, 24 * 60),)
    return ((8 * 60, min(24 * 60, 8 * 60 + int(round(hpd * 60)))),)


@dataclass(frozen=True)
class WorkCalendar:
    clndr_id: str
    name: str
    hours_per_day: float
    week: tuple[Intervals, ...]  # Monday .. Sunday
    exceptions: dict[date, Intervals] = field(default_factory=dict, hash=False, compare=False)
    from_data: bool = True  # False = workweek guessed from the day/week hour counts
    # the calendar's own TimeAxis, built on first use (a cache, not part of the value)
    _axis: TimeAxis | None = field(default=None, init=False, repr=False, hash=False, compare=False)

    @classmethod
    def from_row(cls, row: pd.Series, default_hpd: float = 8.0) -> WorkCalendar:
        hpd = pd.to_numeric(row.get("day_hr_cnt"), errors="coerce")
        hpd = float(hpd) if pd.notna(hpd) and hpd > 0 else default_hpd
        parsed = parse_clndr_data(row.get("clndr_data", ""))
        if parsed is not None and any(parsed[0]):
            week, exc = parsed
            return cls(str(row["clndr_id"]), str(row.get("clndr_name", "")), hpd, week, exc)
        # No usable blob: infer the number of working days from the week's hour count.
        whc = pd.to_numeric(row.get("week_hr_cnt"), errors="coerce")
        n = int(round(whc / hpd)) if pd.notna(whc) and whc > 0 else 5
        n = min(max(n, 1), 7)
        day = _default_day(hpd)
        return cls(
            str(row["clndr_id"]),
            str(row.get("clndr_name", "")),
            hpd,
            tuple([day] * n + [()] * (7 - n)),
            {},
            from_data=False,
        )

    @classmethod
    def standard(cls, hpd: float = 8.0) -> WorkCalendar:
        day = _default_day(hpd)
        return cls("", "Standard (Mon-Fri)", hpd, (day,) * 5 + ((), ()), {}, from_data=False)

    @property
    def week_hours(self) -> tuple[float, ...]:
        return tuple(_hours(d) for d in self.week)

    def periods(self, d: date) -> Intervals:
        return self.exceptions.get(d, self.week[d.weekday()])

    def hours_on(self, d: date) -> float:
        return _hours(self.periods(d))

    def axis(self) -> TimeAxis:
        """This calendar's TimeAxis, built once and grown on demand: one arithmetic for all.

        The window starts around the first exception date, else around a fixed origin, and
        grows to whatever dates are asked of it: results never depend on the day the axis
        was built (``work_hours`` returns differences). The frozen dataclass keeps the cache
        in a declared field, set once through ``object.__setattr__``.
        """
        if self._axis is None:
            origin = min(self.exceptions) if self.exceptions else date(2020, 1, 1)
            ax = TimeAxis(self, origin - timedelta(days=366), origin + timedelta(days=3 * 366))
            object.__setattr__(self, "_axis", ax)
        return self._axis

    def work_hours(self, a: pd.Timestamp, b: pd.Timestamp) -> float:
        """Working hours from ``a`` to ``b`` (negative if ``b`` is earlier), to the minute."""
        if a is None or b is None or pd.isna(a) or pd.isna(b):
            return float("nan")
        return self.axis().between(pd.Timestamp(a), pd.Timestamp(b)) / 60

    def working_days(self, a: pd.Timestamp, b: pd.Timestamp) -> float:
        """Working time from ``a`` to ``b`` in days of this calendar."""
        h = self.work_hours(a, b)
        return 0.0 if pd.isna(h) else h / self.hours_per_day


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
        self.anchor_ns = pd.Timestamp(first).value
        self._build(first, last)

    def _periods(self, first: date, last: date) -> tuple[list[int], list[int]]:
        """Working periods of [first, last] as minute offsets from ``first``."""
        starts, ends = [], []
        d, day = first, 0
        while d <= last:
            for a, b in self.cal.periods(d):
                if b > a:
                    starts.append(day * 1440 + a)
                    ends.append(day * 1440 + b)
            d += timedelta(days=1)
            day += 1
        return starts, ends

    def _build(self, first: date, last: date) -> None:
        starts, ends = self._periods(first, last)
        while not starts:  # e.g. a short window over a shutdown: look further ahead
            if (last - first).days > 20 * 366:
                raise ValueError(f"calendar {self.cal.name!r} has no working time")
            last += timedelta(days=400)
            starts, ends = self._periods(first, last)
        self.first, self.last = first, last
        self.t0 = pd.Timestamp(first)
        self.t0_ns = self.t0.value
        self.span_min = ((last - first).days + 1) * 1440
        self.starts = np.array(starts, dtype=np.int64)
        self.ends = np.array(ends, dtype=np.int64)
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
        span = max(400, (self.last - self.first).days)
        if earlier:
            self._build(self.first - timedelta(days=span), self.last)
        else:
            self._build(self.first, self.last + timedelta(days=span))

    def _ensure(self, ts: pd.Timestamp, margin_days: int = 400) -> None:
        d = ts.date()
        if d < self.first or d > self.last:
            self._build(
                min(self.first, d - timedelta(days=margin_days)), max(self.last, d + timedelta(days=margin_days))
            )

    def minute(self, ts) -> int:
        ts = ts if isinstance(ts, pd.Timestamp) else pd.Timestamp(ts)
        m = (ts.value - self.t0_ns) // 60_000_000_000
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
