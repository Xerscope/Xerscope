"""Clauses made of several words: comparisons ("float < 10 d", "durée supérieure à 20 jours",
"marge nulle") and dates ("starting next week", "finissent avant fin décembre", "due this
month", "between 01/11 and 30/11").

Dates count from the update's data date (``Vocabulary.data_date``): a week is the ISO week
(Monday to Monday) holding it, a month the calendar month. Every date is a half-open range
[from, to): before X = [-, X.from), after X = [X.to, -), by X = [-, X.to), since X =
[X.from, -), in / on X = [X.from, X.to). A numeric date is day/month (31/12), as the page
writes dates; a missing year is the one nearest the data date."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .grammar import And, Atom, Expr

Item = tuple[int, str, object]
PARTS = {"measure", "cmp", "sign", "unit", "anchor", "prep", "period", "month", "edge", "between"}
DAY = pd.Timedelta(days=1)


def raw(token: str) -> tuple[str, object] | None:
    """A token no phrase holds that a clause may use: a number, or a date."""
    if re.fullmatch(r"\d+(?:[.,]\d+)?", token):
        return "num", float(token.replace(",", "."))
    if match := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", token):
        year, month, day = map(int, match.groups())
        return "day", (day, month, year)
    if match := re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", token):
        day_text, month_text, year_text = match.groups()
        full_year = None if year_text is None else int(year_text) + (2000 if len(year_text) == 2 else 0)
        return "day", (int(day_text), int(month_text), full_year)
    return None


@dataclass
class Composer:
    """Reads the clause parts the lexer found, in sentence order, into ``x`` items; a part left
    alone goes back to the file's labels ("en" of "mise en service", "fin" of a name) and, if
    nothing reads it there, is a word left out."""

    tokens: list[str]
    parts: list[tuple[int, int, str, object]]  # (index, size, kind, value), sorted
    data_date: pd.Timestamp | None
    at: int = 0
    out: list[Item] = field(default_factory=list)
    used: set[int] = field(default_factory=set)  # raw tokens a clause took
    freed: set[int] = field(default_factory=set)  # tokens of parts left alone, for the file's labels
    end: int | None = None  # the token after the clause's last part: the next part must start there
    instant: pd.Timestamp | None = None  # "fin décembre" / "début janvier": the edge itself, for before / after

    def run(self) -> tuple[list[Item], set[int], set[int]]:
        while self.at < len(self.parts):
            start, self.end, self.instant = self.at, None, None
            kind = self.parts[start][2]
            done = self._comparison() if kind in ("measure", "sign") else self._date() if kind in DATE_START else False
            if not done:
                self.at = start
                self._leave()
        return self.out, self.used, self.freed

    # --- reading -----------------------------------------------------------------------------

    def _peek(self, offset: int = 0) -> tuple[int, int, str, object] | None:
        i = self.at + offset
        return self.parts[i] if i < len(self.parts) else None

    def _next(self, *kinds: str) -> object:
        """The next part's value when it is one of ``kinds`` and follows the current one; else None."""
        nxt = self._peek()
        if nxt is None or nxt[2] not in kinds or (self.end is not None and nxt[0] != self.end):
            return None
        self.at += 1
        self.end = nxt[0] + nxt[1]
        if nxt[2] in ("num", "day"):
            self.used.add(nxt[0])
        return nxt[3] if nxt[3] is not None else True

    def _take(self) -> tuple[int, int, str, object]:
        part = self.parts[self.at]
        self.at += 1
        self.end = part[0] + part[1]
        return part

    def _emit(self, index: int, expr: Expr) -> bool:
        self.out.append((index, "x", expr))
        return True

    def _leave(self) -> None:
        """The current part alone: a status for a date anchor that is one; any other clause part
        is freed for the file's labels; operators and expressions pass through."""
        index, size, kind, value = self._take()
        if kind not in PARTS and kind not in ("num", "day"):
            self.out.append((index, kind, value))
        elif kind == "anchor" and value[1] is not None:
            self.out.append((index, "x", value[1]))
        elif kind in PARTS:
            self.freed.update(range(index, index + size))

    # --- comparisons ---------------------------------------------------------------------------

    def _comparison(self) -> bool:
        """measure cmp number [unit] | measure sign | sign measure | measure between n and n."""
        index, _, kind, value = self._take()
        if kind == "sign":
            measure = self._next("measure")
            return measure is not None and self._emit(index, _compare(measure, value, 0.0, None))
        if (sign := self._next("sign")) is not None:
            return self._emit(index, _compare(value, sign, 0.0, None))
        if (op := self._next("cmp")) is not None:
            quantity = self._quantity(value)
            return quantity is not None and self._emit(index, _compare(value, op, *quantity))
        if self._next("between") is not None:
            low, joined, high = self._quantity(value), self._next("and"), self._quantity(value)
            if low is None or joined is None or high is None:
                return False
            unit = high[1] if low[1] is None else low[1]
            return self._emit(index, And((_compare(value, ">=", low[0], unit), _compare(value, "<=", high[0], unit))))
        return False

    def _quantity(self, measure: str) -> tuple[float, str | None] | None:
        """A number and its unit (None: the measure's own); None for a unit the measure refuses."""
        number = self._next("num")
        if number is None:
            return None
        unit = self._next("unit")
        allowed = ("%",) if measure == "pct" else ("d", "h")
        return None if unit is not None and unit not in allowed else (number, unit)

    # --- dates ---------------------------------------------------------------------------------

    def _date(self) -> bool:
        index, _, kind, value = self.parts[self.at]
        column = "active"
        if kind == "anchor":
            self._take()
            column = value[0]
        span = self._period() or self._prepositioned() or self._between() or self._point()
        return span is not None and self._emit(index, Atom("date", (column, *span)))

    def _period(self) -> tuple | None:
        period = self._next("period")
        if period is None or self.data_date is None:
            return None
        unit, offset = period
        if unit == "week":
            monday = self.data_date.normalize() - pd.Timedelta(days=self.data_date.weekday())
            start = monday + pd.Timedelta(weeks=offset)
            return start, start + pd.Timedelta(weeks=1)
        start = (self.data_date.normalize().replace(day=1) + pd.DateOffset(months=offset)).normalize()
        return start, start + pd.DateOffset(months=1)

    def _prepositioned(self) -> tuple | None:
        prep = self._next("prep")
        if prep is None:
            return None
        point = self._point()
        if point is None:
            return None
        low, high = point
        if self.instant is not None:  # before / after the end of a month: the edge, not its last day
            low = high = self.instant
        return {"before": (None, low), "after": (high, None), "by": (None, high), "since": (low, None)}.get(prep, point)

    def _between(self) -> tuple | None:
        if self._next("between") is None:
            return None
        first, joined, last = self._point(), self._next("and"), self._point()
        return None if first is None or joined is None or last is None else (first[0], last[1])

    def _point(self) -> tuple | None:
        """A day, a month, the end or the beginning of a month: [from, to)."""
        if (day := self._next("day")) is not None:
            return self._day(*day)
        edge = self._next("edge")
        number = self._next("num") if edge is None else None
        month = self._next("month")
        if month is None:
            return None
        if number is None and edge is None:
            number = self._next("num")
        year = self._year(number)
        if number is not None and number >= 1900:  # "décembre 2026"
            number = None
        return self._month(month, edge, number, year)

    def _year(self, number) -> float | None:
        """A year after the day ("31 décembre 2026", "december 31 2026"), or after the month."""
        if number is not None and number >= 1900:
            return number
        part = self._peek()
        if part and part[2] == "num" and part[3] >= 1900:
            return self._next("num")
        return None

    def _month(self, month: int, edge, day, year) -> tuple | None:
        if day is not None:
            return self._day(int(day), month, None if year is None else int(year))
        first = self._dated(1, month, None if year is None else int(year))
        if first is None:
            return None
        after = first + pd.DateOffset(months=1)
        if edge == "end":
            self.instant = after
            return after - DAY, after
        if edge == "begin":
            self.instant = first
            return first, first + DAY
        return first, after

    def _day(self, day: int, month: int, year: int | None) -> tuple | None:
        start = self._dated(day, month, year)
        return None if start is None else (start, start + DAY)

    def _dated(self, day: int, month: int, year: int | None) -> pd.Timestamp | None:
        """The date; without a year, the one nearest the data date (a year before, the same, after)."""
        try:
            if year is not None:
                return pd.Timestamp(year=year, month=month, day=day)
            if self.data_date is None:
                return None
            near = [pd.Timestamp(year=self.data_date.year + k, month=month, day=day) for k in (-1, 0, 1)]
        except ValueError:  # 31/02, month 13
            return None
        return min(near, key=lambda d: abs(d - self.data_date))


DATE_START = {"anchor", "period", "prep", "between", "month", "edge", "day", "num"}


def _compare(measure: str, op: str, number: float, unit: str | None) -> Atom:
    """measure op number unit; a number without unit is in working days (% for % complete)."""
    return Atom("cmp", (measure, op, number, unit or ("%" if measure == "pct" else "d")))
