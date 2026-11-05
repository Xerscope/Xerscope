"""Debug block 10: planned value labour units of xerscope against a P6 Activities export."""

import io
import math
import zipfile

import pandas as pd
import pytest
from xerkit import active, snap, todo

from xerscope.analysis import Baseline, builtin_standards
from xerscope.analysis.evm import pv_p6_comparison
from xerscope.app.diagnostic import (
    compare_p6_export,
    diagnostic_frames,
    p6_export_columns,
    p6_export_frame,
    p6_number,
    pv_p6_frames,
    read_p6_export,
)

MON, FRI = "2026-03-02 08:00", "2026-03-06 17:00"
NEXT_MON, NEXT_FRI = "2026-03-09 08:00", "2026-03-13 17:00"
WED = "2026-03-04 08:00"  # two of the five working days of the baseline week are elapsed: 0.4
WEEK = dict(early_start_date=MON, early_end_date=FRI, target_drtn_hr_cnt="40", remain_drtn_hr_cnt="40")
NEXT_WEEK = {**WEEK, "early_start_date": NEXT_MON, "early_end_date": NEXT_FRI}
HALF_DONE = {**WEEK, "remain_drtn_hr_cnt": "20"}  # duration % complete 50

# Baseline: A 100 h, C 40 h next week, E 30 h, F 40 h, G 20 h (G and E are 40% planned).
BASELINE = [
    todo("A", **WEEK, target_work_qty="100"),
    todo("C", **NEXT_WEEK, target_work_qty="40"),
    todo("E", **WEEK, target_work_qty="30"),
    todo("F", **WEEK, target_work_qty="40"),
    todo("G", **WEEK, target_work_qty="20"),
]
# Update at Wednesday 08:00: A half done, G deleted, H new (not in the baseline).
UPDATE = [
    active("A", **HALF_DONE, target_work_qty="100"),
    todo("C", **NEXT_WEEK, target_work_qty="40"),
    todo("E", **WEEK, target_work_qty="30"),
    todo("F", **WEEK, target_work_qty="40"),
    todo("H", **WEEK, target_work_qty="10"),
]

# xerscope PV / EV: A 40 / 50, C 0 / 0 (baseline next week), E 12 / 0, F 16 / 0, G 8 / 0, H 0 / 0.
# P6: A 50 / 62.5 (125 h), C 16 / 0 (as if its baseline were this week), F 16 / 0, G 8 / 0,
# H 5 / 0 (baselined in P6), D 8 / 0 (in neither file); E is not in the export.
P6 = pd.DataFrame(
    {
        "pv_hr": [50.0, 16.0, 8.0, 16.0, 8.0, 5.0],
        "ev_hr": [62.5, 0.0, 0.0, 0.0, 0.0, 0.0],
        "schedule_pct": [40.0, 40.0, 20.0, 40.0, 40.0, 40.0],
        "bl_hr": [125.0, 40.0, 40.0, 40.0, 20.0, 10.0],
        "status": ["Active", "Not Started", "Not Started", "Not Started", "Not Started", "Not Started"],
        "bl_start": ["02-Mar-26"] * 6,
    },
    index=pd.Index(["A", "C", "D", "F", "G", "H"], name="task_code"),
)


def _compare(p6=P6, update=UPDATE, tolerance=0.01):
    return pv_p6_comparison(snap(update, data_date=WED), Baseline.from_snapshot(snap(BASELINE)), p6, tolerance)


def _compare_total(total):
    baseline = Baseline.from_snapshot(snap(BASELINE))
    return pv_p6_comparison(snap(UPDATE, data_date=WED), baseline, P6, p6_total_pv_hr=total)


@pytest.fixture(scope="module")
def comparison():
    return _compare()


def test_totals_by_group_with_pv_and_ev_on_both_sides(comparison):
    totals = comparison.totals.set_index("group")
    columns = ["activities", "pv_xerscope_hr", "pv_p6_hr", "pv_gap_hr", "ev_xerscope_hr", "ev_p6_hr", "ev_gap_hr"]
    expected = {
        "all": [7, 76, 103, -27, 50, 62.5, -12.5],
        "matched": [5, 64, 95, -31, 50, 62.5, -12.5],  # A C F G H
        "only P6": [1, 0, 8, -8, 0, 0, 0],  # D
        "only xerscope": [1, 12, 0, 12, 0, 0, 0],  # E
        "in update, not in baseline": [1, 0, 5, -5, 0, 0, 0],  # H: PV in P6 only
        "in baseline, not in update": [1, 8, 8, 0, 0, 0, 0],  # G: PV still from the baseline
    }
    assert totals.index.tolist() == list(expected)
    for group, values in expected.items():
        assert totals.loc[group, columns].tolist() == pytest.approx(values), group
    assert totals.loc["all", "activities"] == sum(totals.loc[["matched", "only P6", "only xerscope"], "activities"])


def test_gap_by_schedule_pct_band(comparison):
    cross = comparison.cross
    assert cross[["xerscope_pct_band", "p6_pct_band", "activities"]].values.tolist() == [
        ["0", "in progress", 1],  # C
        ["in progress", "in progress", 3],  # A, F, G
        ["in progress", "absent", 1],  # E
        ["absent", "in progress", 2],  # H (not in baseline), D
    ]
    assert cross["pv_gap_hr"].tolist() == pytest.approx([-16, -10, 12, -13])
    assert cross["pv_gap_hr"].sum() == pytest.approx(comparison.totals.set_index("group").loc["all", "pv_gap_hr"])


def test_gap_causes(comparison):
    """In gap: A (PV -10, EV -12.5), C (-16), E (+12, one side), D (-8, one side), H (-5).
    BL hours differ for A (100 against 125) and H (0, not in the baseline, against 10); Schedule % for
    C only (0 against 40); not started in the update: C, E, H."""
    row = comparison.causes.iloc[0]
    assert (row["gap_activities"], row["only_p6"], row["only_xerscope"]) == (5, 1, 1)
    assert (row["pv_gap_hr"], row["ev_gap_hr"]) == pytest.approx((-27, -12.5))
    assert (row["bl_hr_differs"], row["schedule_pct_differs"], row["not_started_in_update"]) == (2, 1, 3)


def test_activity_list_is_in_gap_largest_first(comparison):
    listed = comparison.activities
    assert listed["task_code"].tolist() == ["C", "A", "E", "D", "H"]  # |gap| 16, 12.5 (EV), 12, 8, 5
    first = listed.iloc[0]
    assert (first["status"], first["bl_labor_hr"], first["p6_bl_hr"]) == ("Not started", 40, 40)
    assert (first["schedule_pct"], first["p6_schedule_pct"]) == pytest.approx((0, 40))
    assert (first["pv_hr"], first["p6_pv_hr"]) == pytest.approx((0, 16))
    assert first["bl_start"] == pd.Timestamp(NEXT_MON) and first["p6_bl_start"] == "02-Mar-26"
    assert first["start"] == pd.Timestamp(NEXT_MON)
    a = listed.set_index("task_code").loc["A"]
    assert a["status"] == "In progress" and (a["ev_hr"], a["p6_ev_hr"], a["ev_gap_hr"]) == pytest.approx(
        (50, 62.5, -12.5)
    )


def test_started_activity_with_a_known_gap_in_progress():
    """A alone: PV 40 against P6 50 (125 h x 0.4), EV 50 against 62.5 (125 h x 0.5)."""
    result = _compare(P6.loc[["A"]])
    a = result.activities.set_index("task_code").loc["A"]
    assert (a["pv_gap_hr"], a["ev_gap_hr"]) == pytest.approx((-10, -12.5))


def test_not_started_activity_due_in_p6_but_not_in_the_baseline_week(comparison):
    """C: baseline next week, so PV 0; P6 counts it 40% done (16 h)."""
    c = comparison.activities.set_index("task_code").loc["C"]
    assert (c["pv_hr"], c["p6_pv_hr"], c["pv_gap_hr"]) == pytest.approx((0, 16, -16))
    assert c["status"] == "Not started"


def test_update_activity_missing_from_the_baseline_has_zero_and_shows_p6_value(comparison):
    h = comparison.activities.set_index("task_code").loc["H"]
    assert (h["pv_hr"], h["ev_hr"], h["p6_pv_hr"]) == pytest.approx((0, 0, 5))
    assert h["bl_labor_hr"] == 0 and h["p6_bl_hr"] == 10


def test_activity_deleted_from_the_update_keeps_its_baseline_value():
    """G left the update: the comparison still holds its baseline PV (8 h, 20 h x 0.4), which ev_point
    leaves out; an export of the update does not list it, so it is only xerscope's."""
    result = _compare(P6.drop("G"))
    totals = result.totals.set_index("group")
    assert totals.loc["in baseline, not in update", ["activities", "pv_xerscope_hr", "pv_p6_hr"]].tolist() == (
        pytest.approx([1, 8, 0])
    )
    row = result.activities.set_index("task_code").loc["G"]
    assert row["status"] == "not in update" and row["pv_hr"] == pytest.approx(8) and row["p6_pv_hr"] == 0


def test_p6_total_typed_by_hand_less_the_export_rows():
    """P6 total 110 h against 103 h in the export rows (50 + 16 + 8 + 16 + 8 + 5): 7 h on
    activities the view does not show. Without the total, no such row."""
    totals = _compare_total(110.0).totals.set_index("group")
    row = totals.loc["P6 total - export rows"]
    assert row["pv_p6_hr"] == pytest.approx(7) and pd.isna(row["activities"]) and pd.isna(row["pv_xerscope_hr"])
    assert "P6 total - export rows" not in _compare().totals["group"].tolist()


def test_without_the_optional_columns_the_causes_say_so():
    result = _compare(P6[["pv_hr", "ev_hr", "schedule_pct"]])
    assert pd.isna(result.causes.loc[0, "bl_hr_differs"])
    assert "p6_bl_hr" not in result.activities and "p6_status" not in result.activities


def test_tolerance_hides_rounding():
    near = P6.copy()
    near.loc["A", ["pv_hr", "ev_hr"]] = [40.004, 50.004]
    assert "A" not in _compare(near).activities["task_code"].tolist()


# --- reading the export ------------------------------------------------------------------------

HEADERS = [
    "  activity   ID ",
    "PLANNED VALUE LABOR UNITS",
    "Earned Value Labor Units",
    "schedule % complete",
    "Budgeted Labor Units",
    "Planned Start",
]
ROWS = [
    ["A", "1,234.5", "1,000", "40%", "2,500", "02-Mar-26 08:00 A"],
    ["B", "12,5", "0,5", "40,25 %", "1.234,5h", "09-Mar-26 08:00"],
    ["", "9,999", "9,999", "100%", "9,999", ""],  # band / total row
    ["A", "1", "1", "1%", "1", ""],  # repeated Activity ID
    ["C", "n/a", "", "", "", ""],
]


def _csv(rows, headers=HEADERS, sep=",") -> bytes:
    def cell(value):
        return f'"{value}"' if sep in value or " " in value else value

    return "\n".join(sep.join(cell(v) for v in row) for row in [headers, *rows]).encode("utf-8")


def _read(name, content):
    raw = read_p6_export(name, content)
    return p6_export_frame(raw, p6_export_columns(raw))


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("1,234.5", 1234.5), ("1.234,5", 1234.5), ("12,5", 12.5), ("1,234", 1234.0), ("40%", 40.0),
        ("40,25 %", 40.25), ("2 500", 2500.0), ("1,234.5h", 1234.5), ("-3.5", -3.5), ("0.00", 0.0),
    ],
)  # fmt: skip
def test_p6_numbers_as_displayed(text, number):
    assert p6_number(text) == pytest.approx(number)


@pytest.mark.parametrize("text", ["", "  ", "n/a", "inf", "nan", "1,2,3x"])
def test_unreadable_p6_numbers_are_nan(text):
    assert math.isnan(p6_number(text))


def test_csv_with_thousands_separators_percent_and_blank_cells():
    frame, notes = _read("export.csv", _csv(ROWS))
    assert frame.index.tolist() == ["A", "B", "C"]
    assert frame["pv_hr"].iloc[:2].tolist() == pytest.approx([1234.5, 12.5])
    assert frame["ev_hr"].iloc[:2].tolist() == pytest.approx([1000, 0.5])
    assert frame["schedule_pct"].iloc[:2].tolist() == pytest.approx([40, 40.25])
    assert frame["bl_hr"].iloc[:2].tolist() == pytest.approx([2500, 1234.5])
    assert frame["start"].tolist()[0] == "02-Mar-26 08:00" and "status" not in frame
    assert notes == {"rows_without_id": 1, "duplicate_ids": 1, "unreadable_values": 1}


def test_semicolon_csv_in_cp1252():
    content = ";".join(
        ["Activity ID", "Planned Value Labor Units", "Earned Value Labor Units", "Schedule % Complete"]
    ).encode() + "\nÉ1;12,5;1,5;40 %".encode("cp1252")
    frame, _ = _read("export.csv", content)
    assert frame.index.tolist() == ["\xc91"] and frame.loc["\xc91", "pv_hr"] == pytest.approx(12.5)


def test_a_missing_column_is_chosen_by_the_user():
    headers = ["Activity ID", "PV h", "Earned Value Labor Units", "Schedule % Complete"]
    raw = read_p6_export("export.csv", _csv([["A", "5", "2", "40%"]], headers))
    columns = p6_export_columns(raw)
    assert columns["pv_hr"] is None and columns["schedule_pct"] == "Schedule % Complete"
    with pytest.raises(ValueError, match="pv_hr"):
        p6_export_frame(raw, columns)
    frame, _ = p6_export_frame(raw, p6_export_columns(raw, {"pv_hr": "PV h"}))
    assert frame.loc["A", "pv_hr"] == 5


@pytest.mark.parametrize("name", ["export.csv", "export.xlsx", "export.txt"])
def test_a_file_that_is_not_a_csv_export_is_refused(name):
    """XLSX is refused with the way out; no content in the message."""
    with pytest.raises(ValueError) as error:
        read_p6_export(name, b"\x00\x01 not a table")
    assert "not a table" not in str(error.value)


def test_csv_of_a_known_gap_end_to_end():
    """From the file's text to the comparison: A in gap by PV 10 h and EV 12.5 h."""
    baseline, update = Baseline.from_snapshot(snap(BASELINE)), snap(UPDATE, data_date=WED)
    headers = ["Activity ID", "Planned Value Labor Units", "Earned Value Labor Units", "Schedule % Complete"]
    rows = [["A", "50.0", "62.5", "40.00%"], ["F", "16", "0", "40%"]]
    raw = read_p6_export("a.csv", _csv(rows, headers))
    result, _ = compare_p6_export(update, baseline, raw, p6_export_columns(raw))
    assert result.totals.set_index("group").loc["matched", "activities"] == 2
    a = result.activities.set_index("task_code").loc["A"]
    assert (a["pv_gap_hr"], a["ev_gap_hr"]) == pytest.approx((-10, -12.5))


def test_gap_by_baseline_calendar():
    """X on calendar 8 (8 h days): 40 h x 0.4 = 16 against P6 20, in gap by -4. Y on calendar 10
    (10 h days, Mon 08:00 to Fri 18:00, 20 of 50 h elapsed = 0.4): 16 both ways, not in gap."""
    week_10h = {**WEEK, "early_end_date": "2026-03-06 18:00", "clndr_id": "C10"}
    tasks = [todo("X", **WEEK, target_work_qty="40"), todo("Y", **week_10h, target_work_qty="40")]
    baseline = Baseline.from_snapshot(snap(tasks))
    p6 = pd.DataFrame(
        {"pv_hr": [20.0, 16.0], "ev_hr": [0.0, 0.0], "schedule_pct": [50.0, 40.0]},
        index=pd.Index(["X", "Y"], name="task_code"),
    )
    result = pv_p6_comparison(snap(tasks, data_date=WED), baseline, p6).by_calendar
    assert result["clndr_id"].tolist() == ["10", "8"]
    assert result["matched"].tolist() == [1, 1] and result["in_gap"].tolist() == [0, 1]
    assert result["pv_xerscope_hr"].tolist() == pytest.approx([16, 16])
    assert result["pv_p6_hr"].tolist() == pytest.approx([16, 20])
    assert result["pv_gap_hr"].tolist() == pytest.approx([0, -4])


# --- the diagnostic zip ------------------------------------------------------------------------


def test_zip_holds_counts_and_hours_without_code_or_name():
    """Block 10 in the zip: four tables, no activity list, no Activity ID or name in any cell."""
    comparison = _compare_total(110.0)
    from xerkit import xer_text

    from xerscope.anonymize import Anonymizer
    from xerscope.xer import parse_text

    update = snap(UPDATE, data_date=WED)
    frames = {**diagnostic_frames(update, None, builtin_standards()["P6"]), **pv_p6_frames(comparison)}
    anonymous = Anonymizer.from_raws([parse_text(xer_text(UPDATE, data_date=WED), source="test.xer")])
    with zipfile.ZipFile(io.BytesIO(anonymous.zip_frames(frames))) as archive:
        names = archive.namelist()
        text = "".join(archive.read(name).decode("utf-8-sig") for name in names if name.startswith("10_"))
    assert {
        "10_pv_p6_totals.csv",
        "10_pv_p6_by_schedule_pct.csv",
        "10_pv_p6_gap_causes.csv",
        "10_pv_p6_by_calendar.csv",
    } <= set(names)
    assert len(names) == len(frames) and not any("activities" in name for name in names)
    assert "task_name" not in text and "task_code" not in text
    codes = set(update.activities["task_code"]) | set(update.activities["task_name"])
    cells = {cell for line in text.splitlines() for cell in line.split(",")}
    assert not cells & {code for code in codes if len(code) > 1}
