"""PPC Start / Finish / W-W-1 and the weekly date variances, checked by hand on tiny XER pairs.

Updates W-1 and W are successive weekly XER. Committed: in W-1, a planned start (finish) on or
before W's data date; an activity started in W-1 commits only its finish, a complete one nothing.
Kept: in W, an actual start (finish) on or before W's data date; a started / complete status
without the actual date is a miss. PPC Start = starts kept / starts committed, PPC Finish =
finishes kept / finishes committed, PPC W/W-1 = (starts kept + finishes kept) / (starts
committed + finishes committed), in percent.

Calendar C8: Mon-Fri 08:00-12:00 13:00-17:00, holiday Fri 2026-04-03. C7D: 7 days 08:00-16:00.
"""

from __future__ import annotations

import warnings

import pandas as pd
import pytest
from xerkit import FM, SM, active, done, snap, todo

from xerscope.analysis import progress
from xerscope.store import SnapshotStore

DD_W1 = "2026-03-02 08:00"  # Monday, data date of W-1
DD_W = "2026-03-09 08:00"  # Monday, data date of W


def week(previous, current, **kw) -> pd.Series:
    """The ppc_series row of W, for the pair (W-1, W)."""
    table = progress.ppc_series(SnapshotStore([previous, current]), **kw)
    return table.loc[table["snapshot_idx"] == 1].iloc[0]


def counts(row: pd.Series) -> tuple[int, int, int, int]:
    return (
        int(row["starts_committed"]),
        int(row["starts_kept"]),
        int(row["finishes_committed"]),
        int(row["finishes_kept"]),
    )


def outcomes(previous, current) -> set[tuple[str, str, bool]]:
    frame = progress.committed(previous, current)
    return {(r.task_code, r.commitment, bool(r.kept)) for r in frame.itertuples()}


def test_start_and_finish_commitments_and_ratios():
    """DD W-1 03-02, DD W 03-09.
    W-1: A not started 03-02 -> 03-06; B not started 03-05 -> 03-20; C started, finish 03-06;
    D complete; E not started 03-10 -> 03-20.
    Committed: A start 03-02 <= 03-09, A finish 03-06 <= 03-09, B start 03-05 <= 03-09,
    C finish 03-06 (start already done, not committed); D nothing; E start 03-10 > 03-09.
    W: A complete 03-02 / 03-06, B not started, C complete 03-06, E not started.
    Kept: A start, A finish, C finish; missed: B start.
    PPC Start 1/2 = 50 %, PPC Finish 2/2 = 100 %, PPC W/W-1 (1+2)/(2+2) = 75 %."""
    prev = snap(
        [
            todo("A", early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00"),
            todo("B", early_start_date="2026-03-05 08:00", early_end_date="2026-03-20 17:00"),
            active("C", early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00"),
            done("D"),
            todo("E", early_start_date="2026-03-10 08:00", early_end_date="2026-03-20 17:00"),
        ],
        data_date=DD_W1,
    )
    cur = snap(
        [
            done("A", act_start_date="2026-03-02 08:00", act_end_date="2026-03-06 17:00"),
            todo("B", early_start_date="2026-03-09 08:00", early_end_date="2026-03-24 17:00"),
            done("C", act_start_date="2026-02-23 08:00", act_end_date="2026-03-06 17:00"),
            done("D"),
            todo("E", early_start_date="2026-03-10 08:00", early_end_date="2026-03-20 17:00"),
        ],
        data_date=DD_W,
    )
    assert outcomes(prev, cur) == {
        ("A", "Start", True),
        ("A", "Finish", True),
        ("B", "Start", False),
        ("C", "Finish", True),
    }
    row = week(prev, cur)
    assert counts(row) == (2, 1, 2, 2)
    assert row["ppc_start"] == pytest.approx(50.0)
    assert row["ppc_finish"] == pytest.approx(100.0)
    assert row["ppc_week"] == pytest.approx(75.0)


def test_planned_on_the_data_date_is_committed_and_actual_on_it_is_kept():
    """DD W 03-09 08:00. W-1: F not started, start 03-09 08:00 (= DD W, so <= : committed),
    finish 03-20; G not started, start 03-09 08:00.
    W: F started 03-09 08:00 (= DD W, so <= : kept); G not started (missed).
    PPC Start 1/2 = 50 %; no finish committed."""
    prev = snap(
        [
            todo("F", early_start_date="2026-03-09 08:00", early_end_date="2026-03-20 17:00"),
            todo("G", early_start_date="2026-03-09 08:00", early_end_date="2026-03-20 17:00"),
        ],
        data_date=DD_W1,
    )
    cur = snap(
        [
            active("F", act_start_date="2026-03-09 08:00", early_end_date="2026-03-20 17:00"),
            todo("G", early_start_date="2026-03-09 08:00", early_end_date="2026-03-20 17:00"),
        ],
        data_date=DD_W,
    )
    row = week(prev, cur)
    assert counts(row) == (2, 1, 0, 0)
    assert row["ppc_start"] == pytest.approx(50.0)


def test_actual_after_the_data_date_is_missed():
    """DD W 03-09 08:00. W-1: A not started 03-03 -> 03-06.
    Committed: A start 03-03, A finish 03-06.
    W: A complete, actual start 03-03 (kept), actual finish 03-10 17:00 > DD W (missed).
    PPC Start 1/1, PPC Finish 0/1, PPC W/W-1 1/2 = 50 %."""
    prev = snap(
        [todo("A", early_start_date="2026-03-03 08:00", early_end_date="2026-03-06 17:00")],
        data_date=DD_W1,
    )
    cur = snap(
        [done("A", act_start_date="2026-03-03 08:00", act_end_date="2026-03-10 17:00")],
        data_date=DD_W,
    )
    row = week(prev, cur)
    assert counts(row) == (1, 1, 1, 0)
    assert row["ppc_week"] == pytest.approx(50.0)


def test_status_without_actual_date_is_missed():
    """W-1: A not started 03-02 -> 03-06; B started, finish 03-05.
    Committed: A start, A finish, B finish.
    W: A 'In progress' with no actual start (start missed; finish not done, missed);
    B 'Complete' with no actual finish (missed).
    PPC Start 0/1, PPC Finish 0/2, PPC W/W-1 0/3 = 0 %."""
    prev = snap(
        [
            todo("A", early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00"),
            active("B", early_start_date="2026-03-02 08:00", early_end_date="2026-03-05 17:00"),
        ],
        data_date=DD_W1,
    )
    cur = snap(
        [
            active("A", act_start_date="", early_start_date="2026-03-09 08:00", early_end_date="2026-03-13 17:00"),
            done("B", act_start_date="2026-02-23 08:00", act_end_date=""),
        ],
        data_date=DD_W,
    )
    row = week(prev, cur)
    assert counts(row) == (1, 0, 2, 0)
    assert row["ppc_week"] == pytest.approx(0.0)


# Case 1: commitments already late at W-1's data date.
DD_LATE_W1 = "2026-03-09 08:00"
DD_LATE_W = "2026-03-16 08:00"


def late_pair():
    """W-1 (DD 03-09): B not started, start 03-04 (< DD W-1, late); C started, finish 03-05
    (< DD W-1, late); T not started 03-10 -> 03-13.
    W (DD 03-16): B still not started; C complete 03-11; T complete 03-10 / 03-13."""
    prev = snap(
        [
            todo("B", early_start_date="2026-03-04 08:00", early_end_date="2026-03-20 17:00"),
            active("C", early_start_date="2026-03-02 08:00", early_end_date="2026-03-05 17:00"),
            todo("T", early_start_date="2026-03-10 08:00", early_end_date="2026-03-13 17:00"),
        ],
        data_date=DD_LATE_W1,
    )
    cur = snap(
        [
            todo("B", early_start_date="2026-03-16 08:00", early_end_date="2026-03-27 17:00"),
            done("C", act_start_date="2026-02-23 08:00", act_end_date="2026-03-11 17:00"),
            done("T", act_start_date="2026-03-10 08:00", act_end_date="2026-03-13 17:00"),
        ],
        data_date=DD_LATE_W,
    )
    return prev, cur


def test_late_commitments_stay_committed_by_default():
    """Committed (default, late ones kept): starts B (03-04), T (03-10); finishes C (03-05),
    T (03-13), all <= DD W 03-16.
    Kept: T start, C finish, T finish; missed: B start.
    PPC Start 1/2 = 50 %, PPC Finish 2/2 = 100 %, PPC W/W-1 3/4 = 75 %."""
    row = week(*late_pair())
    assert counts(row) == (2, 1, 2, 2)
    assert row["ppc_start"] == pytest.approx(50.0)
    assert row["ppc_finish"] == pytest.approx(100.0)
    assert row["ppc_week"] == pytest.approx(75.0)


def test_late_commitments_left_out_with_the_option():
    """With the option, only planned dates > DD W-1 (03-09 08:00) commit: T start 03-10,
    T finish 03-13; B start 03-04 and C finish 03-05 are out.
    Kept: T start, T finish. PPC Start 1/1, PPC Finish 1/1, PPC W/W-1 2/2 = 100 %."""
    row = week(*late_pair(), include_overdue=False)
    assert counts(row) == (1, 1, 1, 1)
    assert row["ppc_week"] == pytest.approx(100.0)


def test_actual_before_previous_data_date_is_kept():
    """Case 2. W-1 (DD 03-02): B not started, start 03-04 -> 03-20. Committed: B start.
    W (DD 03-09): B started, actual start 02-27, before DD W-1 although W-1 said not started.
    02-27 <= DD W: kept. PPC Start 1/1 = 100 %."""
    prev = snap(
        [todo("B", early_start_date="2026-03-04 08:00", early_end_date="2026-03-20 17:00")],
        data_date=DD_W1,
    )
    cur = snap(
        [active("B", act_start_date="2026-02-27 08:00", early_end_date="2026-03-20 17:00")],
        data_date=DD_W,
    )
    row = week(prev, cur)
    assert counts(row) == (1, 1, 0, 0)
    assert row["ppc_start"] == pytest.approx(100.0)


def renamed_pair():
    """Same task_id (1): Activity ID A in W-1, A-NEW in W.
    W-1: A not started 03-02 -> 03-06; B not started 03-03 -> 03-20.
    W: A-NEW complete 03-02 / 03-06; B started 03-03."""
    prev = snap(
        [
            todo("A", early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00"),
            todo("B", early_start_date="2026-03-03 08:00", early_end_date="2026-03-20 17:00"),
        ],
        data_date=DD_W1,
    )
    cur = snap(
        [
            done("A-NEW", act_start_date="2026-03-02 08:00", act_end_date="2026-03-06 17:00"),
            active("B", act_start_date="2026-03-03 08:00", early_end_date="2026-03-20 17:00"),
        ],
        data_date=DD_W,
    )
    return prev, cur


def test_renamed_activity_leaves_the_counts():
    """Case 3. A's commitments (start 03-02, finish 03-06) leave the denominator (A deleted);
    A-NEW is new in W (not committed, not kept). Committed: B start 03-03. Kept: B start.
    PPC Start 1/1; finishes 0/0."""
    row = week(*renamed_pair())
    assert counts(row) == (1, 1, 0, 0)
    assert row["ppc_start"] == pytest.approx(100.0)


def test_renamed_activity_is_warned():
    """Case 3. The change of Activity ID A -> A-NEW is reported: in the W row's note, as a Python
    warning, or among W's snapshot warnings; the message names both IDs."""
    prev, cur = renamed_pair()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        row = week(prev, cur)
    messages = [str(row["note"] or "")] + [str(w.message) for w in caught] + [str(w) for w in cur.warnings]
    assert any("A-NEW" in m and "A" in m.replace("A-NEW", "") for m in messages), messages


def milestone_pair():
    """W-1: M finish milestone, finish 03-04; S start milestone, start 03-03; T not started
    03-02 -> 03-20. W: M complete 03-04; S not started; T started 03-02."""
    prev = snap(
        [
            todo("M", early_start_date="2026-03-04 17:00", early_end_date="2026-03-04 17:00", **FM),
            todo("S", early_start_date="2026-03-03 08:00", early_end_date="2026-03-03 08:00", **SM),
            todo("T", early_start_date="2026-03-02 08:00", early_end_date="2026-03-20 17:00"),
        ],
        data_date=DD_W1,
    )
    cur = snap(
        [
            done("M", act_start_date="2026-03-04 17:00", act_end_date="2026-03-04 17:00", **FM),
            todo("S", early_start_date="2026-03-10 08:00", early_end_date="2026-03-10 08:00", **SM),
            active("T", act_start_date="2026-03-02 08:00", early_end_date="2026-03-20 17:00"),
        ],
        data_date=DD_W,
    )
    return prev, cur


def test_milestones_left_out_of_the_counts():
    """Case 5. M (finish 03-04) and S (start 03-03) are out. Committed: T start 03-02, kept.
    PPC Start 1/1; finishes 0/0."""
    prev, cur = milestone_pair()
    row = week(prev, cur)
    assert counts(row) == (1, 1, 0, 0)
    assert {r.task_code for r in progress.committed(prev, cur).itertuples()} == {"T"}


@pytest.mark.xfail(strict=True, reason="API à créer: liste à part des engagements de jalons (engagés / tenus)")
def test_milestones_listed_apart():
    """Case 5. Milestones listed apart: M finish committed 03-04, kept (actual 03-04);
    S start committed 03-03, missed."""
    prev, cur = milestone_pair()
    frame = progress.committed_milestones(prev, cur)
    assert {(r.task_code, r.commitment, bool(r.kept)) for r in frame.itertuples()} == {
        ("M", "Finish", True),
        ("S", "Start", False),
    }


def test_level_of_effort_and_wbs_summary_left_out():
    """Case 6. W-1: L level of effort 03-02 -> 03-06, W WBS summary 03-02 -> 03-06, T task
    03-02 -> 03-06, all not started. W: all three complete 03-02 / 03-06.
    Committed: T start, T finish only. PPC Start 1/1, PPC Finish 1/1."""
    dates = dict(early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00")
    actuals = dict(act_start_date="2026-03-02 08:00", act_end_date="2026-03-06 17:00")
    prev = snap(
        [
            todo("L", task_type="TT_LOE", **dates),
            todo("W", task_type="TT_WBS", **dates),
            todo("T", **dates),
        ],
        data_date=DD_W1,
    )
    cur = snap(
        [
            done("L", task_type="TT_LOE", **actuals),
            done("W", task_type="TT_WBS", **actuals),
            done("T", **actuals),
        ],
        data_date=DD_W,
    )
    row = week(prev, cur)
    assert counts(row) == (1, 1, 1, 1)


def unplanned_pair():
    """W-1: T not started 03-02 -> 03-06. W: T complete 03-02 / 03-06; N, absent from W-1,
    complete 03-03 / 03-05."""
    prev = snap(
        [todo("T", early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00")],
        data_date=DD_W1,
    )
    cur = snap(
        [
            done("T", act_start_date="2026-03-02 08:00", act_end_date="2026-03-06 17:00"),
            done("N", act_start_date="2026-03-03 08:00", act_end_date="2026-03-05 17:00"),
        ],
        data_date=DD_W,
    )
    return prev, cur


def test_unplanned_work_left_out_of_the_counts():
    """Case 10. Committed: T start, T finish; N not in W-1, so neither committed nor kept.
    Starts 1/1, finishes 1/1 (with N counted it would read 2/2)."""
    row = week(*unplanned_pair())
    assert counts(row) == (1, 1, 1, 1)


@pytest.mark.xfail(strict=True, reason="API à créer: liste du travail non planifié (absent de W-1, fait dans W)")
def test_unplanned_work_listed():
    """Case 10. N, absent from W-1 and complete in W (03-03 / 03-05), is listed as unplanned
    work; T, planned in W-1, is not."""
    frame = progress.unplanned_work(*unplanned_pair())
    assert set(frame["task_code"]) == {"N"}


def test_activity_deleted_in_w_left_out():
    """Scope change. W-1: T not started 03-02 -> 03-06; B not started 03-03 -> 03-20.
    W: T complete 03-02 / 03-06; B deleted.
    Committed: T start, T finish (B's start 03-03 is out). Starts 1/1, finishes 1/1."""
    prev = snap(
        [
            todo("T", early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00"),
            todo("B", early_start_date="2026-03-03 08:00", early_end_date="2026-03-20 17:00"),
        ],
        data_date=DD_W1,
    )
    cur = snap(
        [done("T", act_start_date="2026-03-02 08:00", act_end_date="2026-03-06 17:00")],
        data_date=DD_W,
    )
    row = week(prev, cur)
    assert counts(row) == (1, 1, 1, 1)


def variance_store() -> SnapshotStore:
    """W-2 (DD 03-02), W-1 (DD 03-09), W (DD 03-16).
    X (C8): start 03-09 / 03-10 / 03-12 (actual), finish 03-13 / 03-16 / 03-18.
    Y: absent from W-2; start Fri 03-13 08:00 on C8 in W-1, Mon 03-16 08:00 on C7D in W;
    finish 03-20 16:00 in both.
    Z (C8): start 04-01 in all; finish Wed 04-01 / Thu 04-02 / Mon 04-06 (Fri 04-03 holiday).
    E (C8): start 03-20 / 03-18 in W-1 / W (earlier); finish 03-27 in both.
    L: level of effort 03-02 -> 03-27 in all."""
    loe = dict(task_type="TT_LOE", early_start_date="2026-03-02 08:00", early_end_date="2026-03-27 17:00")
    w2 = snap(
        [
            todo("X", early_start_date="2026-03-09 08:00", early_end_date="2026-03-13 17:00"),
            todo("Z", early_start_date="2026-04-01 08:00", early_end_date="2026-04-01 17:00"),
            todo("E", early_start_date="2026-03-20 08:00", early_end_date="2026-03-27 17:00"),
            todo("L", **loe),
        ],
        data_date="2026-03-02 08:00",
    )
    w1 = snap(
        [
            todo("X", early_start_date="2026-03-10 08:00", early_end_date="2026-03-16 17:00"),
            todo("Z", early_start_date="2026-04-01 08:00", early_end_date="2026-04-02 17:00"),
            todo("E", early_start_date="2026-03-20 08:00", early_end_date="2026-03-27 17:00"),
            todo("L", **loe),
            todo("Y", early_start_date="2026-03-13 08:00", early_end_date="2026-03-20 16:00"),
        ],
        data_date="2026-03-09 08:00",
    )
    w = snap(
        [
            active("X", act_start_date="2026-03-12 08:00", early_end_date="2026-03-18 17:00"),
            todo("Z", early_start_date="2026-04-01 08:00", early_end_date="2026-04-06 17:00"),
            todo("E", early_start_date="2026-03-18 08:00", early_end_date="2026-03-27 17:00"),
            todo("L", **loe),
            todo("Y", clndr_id="C7D", early_start_date="2026-03-16 08:00", early_end_date="2026-03-20 16:00"),
        ],
        data_date="2026-03-16 08:00",
    )
    return SnapshotStore([w2, w1, w])


def variances() -> pd.DataFrame:
    return progress.date_variances(variance_store(), 2).set_index("task_code")


def test_variances_in_working_days_reference_minus_current():
    """Case 12, C8, reference − current in working days (negative = late).
    X start: W-1 03-10 -> W 03-12 = -2 (Wed, Thu); W-2 03-09 -> 03-12 = -3.
    X finish: W-1 Mon 03-16 -> Wed 03-18 = -2; W-2 Fri 03-13 -> Wed 03-18 = -3 (Mon, Tue, Wed;
    5 calendar days).
    E start: W-1 Fri 03-20 -> W Wed 03-18 = +2 (earlier); W-2 same as W-1 = +2. E finish 0, 0."""
    v = variances()
    assert v.loc["X", "start_var_w1"] == -2
    assert v.loc["X", "start_var_w2"] == -3
    assert v.loc["X", "finish_var_w1"] == -2
    assert v.loc["X", "finish_var_w2"] == -3
    assert v.loc["E", "start_var_w1"] == 2
    assert v.loc["E", "start_var_w2"] == 2
    assert v.loc["E", "finish_var_w1"] == 0
    assert v.loc["E", "finish_var_w2"] == 0


def test_variances_skip_holidays():
    """Case 12, Z on C8 with Fri 04-03 a holiday.
    Finish: W-1 Thu 04-02 17:00 -> W Mon 04-06 17:00 = -1 (Fri holiday, weekend);
    W-2 Wed 04-01 17:00 -> Mon 04-06 17:00 = -2 (Thu, Mon). Start unchanged: 0, 0."""
    v = variances()
    assert v.loc["Z", "finish_var_w1"] == -1
    assert v.loc["Z", "finish_var_w2"] == -2
    assert v.loc["Z", "start_var_w1"] == 0


def test_variances_use_the_calendar_of_w():
    """Case 12, Y moved from C8 (W-1) to C7D (W). Start Fri 03-13 08:00 -> Mon 03-16 08:00:
    on C7D (calendar in W) Fri, Sat, Sun = -3 (on C8 it would be -1). Finish 03-20 16:00 in
    both = 0. Y absent from W-2: w2 columns blank."""
    v = variances()
    assert v.loc["Y", "start_var_w1"] == -3
    assert v.loc["Y", "finish_var_w1"] == 0
    assert pd.isna(v.loc["Y", "start_var_w2"])
    assert pd.isna(v.loc["Y", "finish_var_w2"])


def test_variances_leave_out_level_of_effort():
    """Case 12. L (level of effort) has no variance row."""
    assert "L" not in variances().index
