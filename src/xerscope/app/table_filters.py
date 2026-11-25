"""Read the text typed in a column filter, for a text, a number or a date column; no Streamlit."""

from __future__ import annotations

import re
from collections.abc import Callable

import pandas as pd

from xerscope.analysis.query import fold
from xerscope.xer.model import to_datetime

# Column filters. One text per column, all of them must hold (AND); an empty text filters nothing.
#   text     beton            contains, ignoring case and accents
#   number   <0  >=5  =3  -10..0
#   date     >2026-11-01  2026-11  2026-11..2026-12   (a year, month or day; ranges are inclusive)
FILTER_HINT = {
    "text": "contains…",
    "number": "<0, >=5, -10..0",
    "date": ">2026-11-01, 2026-11, 2026-11..2026-12",
}
FILTER_RULE = "Every filter must hold; an empty text filters nothing."
_OPERATOR = re.compile(r"^(<=|>=|<|>|=)?\s*(.+)$")
_YEAR_MONTH_OR_DAY = re.compile(r"\d{4}(-\d{2}(-\d{2})?)?")


def as_dates(values: pd.Series) -> pd.Series:
    """Return a column as dates: left as it is when already one, else read as the XER writes dates.

    The XER form is "YYYY-MM-DD HH:MM", ISO 8601, seconds tolerated. Never a guess from the first value,
    which pandas would otherwise make and then apply to the rest (a date without time becomes NaT after
    one with seconds), nor a dateutil fallback on a label.
    """
    if pd.api.types.is_datetime64_any_dtype(values):
        return values
    return to_datetime(values.astype("string").fillna(""))


def _number(text: str) -> float:
    return float(text.replace("−", "-").replace(",", "").replace("%", "").strip())


def _range(text: str) -> tuple[str, str] | None:
    """Bounds of "a..b"; the split skips the first character so "-10..0" keeps its sign."""
    cut = text.find("..", 1)
    return (text[:cut], text[cut + 2 :]) if cut > 0 else None


def _operator_and_value(text: str) -> tuple[str, str]:
    """Split a filter into the comparison it starts with ("" when it has none) and the value after it."""
    found = _OPERATOR.match(text)
    if found is None:  # the pattern reads one line: a value holding a line break is not a filter
        raise ValueError(f"not a filter: {text!r}")
    operator, value = found.groups()
    return operator or "", value


def _number_test(text: str) -> Callable[[pd.Series], pd.Series]:
    """Return the test a number filter stands for, to apply to a column of numbers.

    "a..b" keeps the values between the bounds, inclusive; an operator and a number compare each value,
    and a bare number keeps the values equal to it.
    """
    bounds = _range(text)
    if bounds:
        low, high = _number(bounds[0]), _number(bounds[1])
        return lambda values: values.between(low, high)
    operator, value = _operator_and_value(text)
    number = _number(value)
    return {
        "<": lambda values: values < number,
        "<=": lambda values: values <= number,
        ">": lambda values: values > number,
        ">=": lambda values: values >= number,
    }.get(operator or "=", lambda values: values == number)


def _period(text: str) -> pd.Period:
    """Return the year, month or day a filter names (2026, 2026-11, 2026-11-01).

    Any other text is refused: read loosely, "3 4" would be 4 March of the year 1.
    """
    written = text.strip()
    if not _YEAR_MONTH_OR_DAY.fullmatch(written):
        raise ValueError(f"not a year, a month or a day: {text!r}")
    return pd.Period(written)


def _date_test(text: str) -> Callable[[pd.Series], pd.Series]:
    """Return the test a date filter stands for, to apply to a column of dates.

    A date may be a year, a month or a day: "=" keeps the whole period, ">" what is after it.
    """
    bounds = _range(text)
    if bounds:
        start, end = _period(bounds[0]).start_time, _period(bounds[1]).end_time
        return lambda values: (values >= start) & (values <= end)
    operator, value = _operator_and_value(text)
    period = _period(value)
    start, end = period.start_time, period.end_time
    return {
        "<": lambda values: values < start,
        "<=": lambda values: values <= end,
        ">": lambda values: values > end,
        ">=": lambda values: values >= start,
    }.get(operator or "=", lambda values: (values >= start) & (values <= end))


def keep_mask(kind: str, text: str, values: pd.Series) -> pd.Series:
    """Return which of ``values`` the filter ``text`` keeps, read as a number, date or text filter.

    A missing value is not kept. Raises ValueError when ``text`` cannot be read as a ``kind`` filter.
    """
    masks = {
        "number": lambda: _number_test(text)(values).fillna(False),
        "date": lambda: _date_test(text)(as_dates(values)).fillna(False),
        "text": lambda: values.map(fold).str.contains(fold(text), regex=False),
    }
    return masks[kind]()
