"""Column filters of the app tables (ui.filter_rows): one text per column, all must hold."""

import pandas as pd
import pytest

from xerscope.app import ui

FRAME = pd.DataFrame(
    {
        "task_code": ["A1040", "A1210", "M0100", "B2000"],
        "task_name": ["Béton niveau 3", "Install HVAC risers", "Mechanical completion", None],
        "total_float_d": [-3.0, -12.5, 0.0, 25.0],
        "finish": pd.to_datetime(["2026-10-31 17:00", "2026-11-01 08:00", "2026-11-30 17:00", "2026-12-15 17:00"]),
    }
)


def codes(filters: dict) -> list[str]:
    rows, errors = ui.filter_rows(FRAME, filters)
    assert errors == {}
    return rows["task_code"].tolist()


def test_kinds_follow_the_column():
    assert ui.filter_kind("task_name", FRAME["task_name"]) == "text"
    assert ui.filter_kind("total_float_d", FRAME["total_float_d"]) == "number"
    assert ui.filter_kind("finish", FRAME["finish"]) == "date"
    # a number column holding text (debug tables cast to str) is filtered as text
    assert ui.filter_kind("total_float_d", FRAME["total_float_d"].astype(str)) == "text"


def test_empty_filters_keep_every_row():
    assert codes({}) == ["A1040", "A1210", "M0100", "B2000"]
    assert codes({"task_name": "  ", "total_float_d": ""}) == ["A1040", "A1210", "M0100", "B2000"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("beton", ["A1040"]),  # accents and case ignored
        ("MECH", ["M0100"]),
        ("i", ["A1040", "A1210", "M0100"]),  # a missing name matches nothing
    ],
)
def test_text_contains(text, expected):
    assert codes({"task_name": text}) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<0", ["A1040", "A1210"]),
        ("<=0", ["A1040", "A1210", "M0100"]),
        (">0", ["B2000"]),
        (">= -3", ["A1040", "M0100", "B2000"]),
        ("0", ["M0100"]),
        ("=-12.5", ["A1210"]),
        ("−12.5", ["A1210"]),  # typographic minus
        ("-12.5..-3", ["A1040", "A1210"]),  # inclusive, negative bounds
        ("-5..25", ["A1040", "M0100", "B2000"]),
    ],
)
def test_number_comparisons_and_ranges(text, expected):
    assert codes({"total_float_d": text}) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-11", ["A1210", "M0100"]),  # the whole month, times included
        ("2026-11-01", ["A1210"]),
        (">2026-11-01", ["M0100", "B2000"]),  # after that day
        (">=2026-11", ["A1210", "M0100", "B2000"]),
        ("<2026-11", ["A1040"]),
        ("<=2026-11-30", ["A1040", "A1210", "M0100"]),
        ("2026-11..2026-12", ["A1210", "M0100", "B2000"]),
        ("2026", ["A1040", "A1210", "M0100", "B2000"]),
    ],
)
def test_date_periods(text, expected):
    assert codes({"finish": text}) == expected


def test_filters_combine_with_and():
    assert codes({"total_float_d": "<0", "finish": "2026-11"}) == ["A1210"]


def test_a_filter_that_cannot_be_read_is_reported_and_skipped():
    rows, errors = ui.filter_rows(FRAME, {"total_float_d": "abc", "finish": "next week", "task_name": "hvac"})
    assert rows["task_code"].tolist() == ["A1210"]
    assert set(errors) == {"total_float_d", "finish"}
    assert "number" in errors["total_float_d"] and "date" in errors["finish"]


@pytest.mark.parametrize("text", [">3\n4", "3\n4", "2026-11\n2026-12", "a\nb"])
def test_a_filter_holding_a_line_break_is_reported_not_raised(text):
    """A pasted text may hold a line break inside its value. On a number or a date column it cannot
    be read: the filter is reported and skipped like any other unread filter, and the other filter
    still applies. (A line break at either end is stripped with the spaces: "3\\n" is the filter "3".)"""
    rows, errors = ui.filter_rows(FRAME, {"total_float_d": text, "finish": text, "task_name": "hvac"})
    assert rows["task_code"].tolist() == ["A1210"]
    assert set(errors) == {"total_float_d", "finish"}


def test_dates_are_read_as_iso_8601_never_guessed():
    """A date column still held as text (an export, a diagnostic frame) is read with the XER format,
    "YYYY-MM-DD HH:MM" (ISO 8601): no element-by-element guess, so no dateutil fallback and no
    ambiguity between day and month. Text that is not ISO is not a date (NaT), not a guess."""
    import warnings

    frame = pd.DataFrame({"finish": ["2026-10-31 17:00:00", "2026-11-01 08:00", "2026-11-02", "01/02/2026", None]})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        # pandas alone would take the format of the first value (with seconds) and lose the next two
        assert ui.as_dates(frame["finish"]).notna().tolist() == [True, True, True, False, False]
        rows, errors = ui.filter_rows(frame, {"finish": "2026-11"})
        assert errors == {} and rows["finish"].tolist() == ["2026-11-01 08:00", "2026-11-02"]
        rows, _ = ui.filter_rows(frame, {"finish": "2026-02"})
        assert rows.empty  # "01/02/2026" is not read as 1 February (nor as 2 January)
        assert ui._has_time(frame["finish"]) is True
        assert ui._has_time(pd.Series(["2026-10-31", "01/02/2026"])) is False
        assert ui._has_time(pd.Series(["2026-03-02 · update.xer"])) is False  # a label: no dateutil fallback
