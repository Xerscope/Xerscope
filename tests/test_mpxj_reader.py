"""The normalisers of the MPXJ comparison: both readers' values are brought to one text or number,
without hiding a difference. No Java needed. Expected values are written from the docstrings of
``xerscope.verify.mpxj_reader`` ("to the minute", "to two decimals", None when blank)."""

import pandas as pd
import pytest

from xerscope.verify.mpxj_reader import _date_text, _rounded

pytestmark = pytest.mark.oracle("property")


@pytest.mark.parametrize(
    "date, text",
    [
        (pd.Timestamp("2024-01-01 08:00"), "2024-01-01 08:00"),
        (pd.Timestamp("2024-01-01 08:00:59"), "2024-01-01 08:00"),
        ("2024-01-01T08:00:00", "2024-01-01 08:00"),
        ("2024-01-01T09:30:45", "2024-01-01 09:30"),
        (None, None),
        (pd.NaT, None),
    ],
)
def test_a_date_of_either_reader_is_text_to_the_minute(date, text):
    assert _date_text(date) == text


def test_two_dates_one_hour_or_one_day_apart_stay_apart():
    assert _date_text(pd.Timestamp("2024-01-01 08:00")) != _date_text(pd.Timestamp("2024-01-01 09:00"))
    assert _date_text("2024-01-01T08:00:00") != _date_text("2024-01-02T08:00:00")


@pytest.mark.parametrize(
    "value, number",
    [("8.004", 8.0), (8.006, 8.01), (8.0, 8.0), ("12", 12.0), (None, None), (float("nan"), None), ("n/a", None)],
)
def test_a_number_of_either_reader_is_rounded_to_two_decimals(value, number):
    assert _rounded(value) == number


def test_two_numbers_one_apart_stay_apart():
    assert _rounded(8.0) != _rounded(9.0)
    assert _rounded(8.0) != _rounded(8.02)  # two hundredths is still a difference
