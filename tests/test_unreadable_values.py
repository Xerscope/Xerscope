"""XER-01: a cell the file fills but the reader cannot type reads as blank, as before, and is now warned of.

Hand cases: a decimal comma, a month 13, a year past the readable range (1900-2200) and an infinite number
are each read as blank and named, by table, column, count and Activity ID; a file P6 writes clean gives
no such warning; an unreadable status date says where the status date was taken from instead.
"""

import pytest
from xerkit import todo, xer_text

from xerscope.xer import load_snapshot

pytestmark = pytest.mark.oracle("property")

WARNING = "unreadable or out of range"


def _snapshot(tasks, **kwargs):
    return load_snapshot(xer_text(tasks, **kwargs).encode(), name="a.xer")


def _unreadable(snapshot) -> list[str]:
    return [warning for warning in snapshot.warnings if WARNING in warning]


def test_each_unreadable_cell_is_read_blank_and_named():
    snapshot = _snapshot(
        [
            todo("A1", target_drtn_hr_cnt="8,5"),
            todo("A2", act_start_date="2026-13-01 08:00", target_work_qty="1e400"),
            todo("A3", act_start_date="2301-01-01 08:00"),
            todo("A4", target_drtn_hr_cnt="16"),
        ]
    )
    tasks = snapshot.activities.set_index("task_code")
    assert tasks.loc["A1", "target_drtn_hr_cnt"] != tasks.loc["A1", "target_drtn_hr_cnt"]  # NaN, as before
    assert tasks.loc[["A2", "A3"], "act_start_date"].isna().all()
    assert sorted(_unreadable(snapshot)) == [
        f"a.xer: TASK.act_start_date: 2 value(s) {WARNING}, read as blank ['A2', 'A3']",
        f"a.xer: TASK.target_drtn_hr_cnt: 1 value(s) {WARNING}, read as blank ['A1']",
        f"a.xer: TASK.target_work_qty: 1 value(s) {WARNING}, read as blank ['A2']",
    ]


def test_a_clean_file_gives_no_such_warning():
    snapshot = _snapshot([todo("A1", target_drtn_hr_cnt="8.5", act_start_date="2026-03-02 08:00")])
    assert _unreadable(snapshot) == []


def test_an_unreadable_status_date_says_where_the_status_date_comes_from():
    """last_recalc_date unreadable: the reader falls back on plan_start_date, as before, and says so."""
    snapshot = _snapshot([todo("A1")], project={"last_recalc_date": "2026-02-30 08:00"})
    assert any(
        "PROJECT.last_recalc_date '2026-02-30 08:00' unreadable or out of range: status date taken from "
        "plan_start_date" in warning
        for warning in snapshot.warnings
    ), snapshot.warnings
