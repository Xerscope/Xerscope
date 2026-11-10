"""Threshold, calendar and planned-value boundaries of the P6, DCMA and DECM checks.

Expected values written by hand from the cited texts.
"""

import pandas as pd
import pytest
from rulekit import STANDARDS, codes, counts, links, run
from xerkit import DD, FM, MON_FRI_8H, active, done, snap, todo

from xerscope.analysis import Baseline
from xerscope.analysis.evm import ev_point, pv_curve
from xerscope.xer.calendar import WorkCalendar

pytestmark = pytest.mark.oracle("standard")
P6, DCMA, DECM = STANDARDS["P6"], STANDARDS["DCMA"], STANDARDS["DECM"]

SUNDAY_ONLY_BLOB = (
    "(0||CalendarData()((0||DaysOfWeek()((0||1()((0||0(s|00:00|f|00:00)())))"
    "(0||2()())(0||3()())(0||4()())(0||5()())(0||6()())(0||7()())))"
    "(0||Exceptions()((0||0(d|46118)((0||0(s|08:00|f|12:00)())))))))"
)


def _calendar(blob, day_hr_cnt):
    return WorkCalendar.from_row(pd.Series({"clndr_id": "X", "day_hr_cnt": day_hr_cnt, "clndr_data": blob}))


def test_bei_on_the_boundary():
    """BEI = 19 completed / 20 baseline activities = 0.95.

    P6-13 requires a value strictly greater than 0.95 (report R1; Oracle EPPM
    help 91574 words it as "0.95 or greater", the project follows the report):
    0.95 is not > 0.95, so the verdict is fail. Flagged = baseline-due and not
    completed = T20.
    DCMA-14 = 19 completed / 20 due = 0.95; target >= 0.95: pass.
    Baseline finish 2026-03-13 17:00 is on or before the data date 2026-03-16.
    """
    task_codes = [f"T{i:02d}" for i in range(1, 21)]
    bl = Baseline.from_snapshot(snap([todo(c) for c in task_codes]))
    current = snap(
        [done(c) for c in task_codes[:19]]
        + [todo("T20", early_start_date="2026-03-16 08:00", early_end_date="2026-03-20 17:00")],
        data_date="2026-03-16 08:00",
    )

    r13 = run(P6, "P6-13", current, baseline=bl)
    assert counts(r13) == (19, 20)
    assert r13.value == pytest.approx(0.95)
    assert r13.status == "fail"
    assert codes(r13) == ["T20"]

    r14 = run(DCMA, "DCMA-14", current, baseline=bl)
    assert counts(r14) == (19, 20)
    assert r14.value == pytest.approx(0.95)
    assert r14.status == "pass"


def test_p6_hard_constraints_one_in_hundred():
    """P6-02: 1 Mandatory Finish / 100 checked = 1.0 %; target < 1 % strict: fail."""
    tasks = [todo(f"T{i:03d}") for i in range(1, 100)]
    tasks.append(todo("T100", cstr_type="CS_MANDFIN", cstr_date="2026-03-13 17:00"))
    r = run(P6, "P6-02", snap(tasks))
    assert counts(r) == (1, 100)
    assert r.value == pytest.approx(1.0)
    assert r.status == "fail"


def test_dcma_hard_constraints_one_in_twenty():
    """DCMA-05: 1 Start On / 20 incomplete = 5.0 %; target <= 5 % inclusive: pass."""
    tasks = [todo(f"T{i:02d}") for i in range(1, 20)]
    tasks.append(todo("T20", cstr_type="CS_MSO", cstr_date="2026-03-02 08:00"))
    r = run(DCMA, "DCMA-05", snap(tasks))
    assert counts(r) == (1, 20)
    assert r.value == pytest.approx(5.0)
    assert r.status == "pass"


@pytest.mark.parametrize(
    "total_float, expected, status",
    [("-8", 0.95, "pass"), ("-9", 0.94375, "fail")],
    ids=["float-minus-8h", "float-minus-9h"],
)
def test_cpli_on_the_boundary(total_float, expected, status):
    """CPL = working days on C8 from Mon 2026-03-02 08:00 to Fri 2026-03-27 17:00.

    Weeks: 03-02..03-06 = 5, 03-09..03-13 = 5, 03-16..03-20 = 5,
    03-23..03-27 = 5; no holiday (the only one is 2026-04-03); CPL = 20 days.
    TF = -8 h / 8 h per day = -1 day: CPLI = (20 - 1) / 20 = 0.95, >= 0.95: pass.
    TF = -9 h / 8 = -1.125 days: CPLI = 18.875 / 20 = 0.94375 < 0.95: fail.
    """
    s = snap(
        [
            todo("A"),
            todo("B"),
            todo(
                "Z",
                **FM,
                early_end_date="2026-03-27 17:00",
                total_float_hr_cnt=total_float,
            ),
        ],
        preds=[("A", "B", "FS", 0), ("B", "Z", "FS", 0)],
        project={"plan_end_date": "2026-03-25 17:00"},
        data_date=DD,
    )
    r = run(DCMA, "DCMA-13", s)
    assert r.value == pytest.approx(expected)
    assert r.status == status


def test_total_float_exactly_zero():
    """Z has float 0 and N has -8 h; both are not started (population 2).

    P6-14 and DCMA-07: float < 0 flags N only (0 is not negative); P6-14 = 1/2.
    P6-06 and DCMA-06: float > 352 h (44 days x 8 h) flags nobody: 0/2.
    DECM 06A211a: float > 44 days flags nobody: 0/2, informative.
    DCMA-07 is a task count with target <= 0: one flagged task fails.
    """
    s = snap([todo("Z", total_float_hr_cnt="0"), todo("N", total_float_hr_cnt="-8")])

    r = run(P6, "P6-14", s)
    assert counts(r) == (1, 2)
    assert codes(r) == ["N"]
    assert r.status == "fail"

    r = run(DCMA, "DCMA-07", s)
    assert codes(r) == ["N"]
    assert r.status == "fail"

    r = run(P6, "P6-06", s)
    assert counts(r) == (0, 2)
    assert codes(r) == []
    assert r.status == "pass"

    r = run(DCMA, "DCMA-06", s)
    assert counts(r) == (0, 2)
    assert codes(r) == []
    assert r.status == "pass"

    r = run(DECM, "06A211a", s)
    assert counts(r) == (0, 2)
    assert codes(r) == []
    assert r.status == "info"


def test_resource_dependent_activity_is_an_ordinary_activity():
    """RD (TT_Rsrc, remaining 400 h, float 400 h) and T (80 h, float 0); population 2.

    P6-04: remaining > 352 h flags RD: 1/2.
    P6-06: float > 352 h flags RD: 1/2.
    P6-11: no resource assigned flags RD and T: 2/2.
    P6-01: no predecessor and no successor flags RD and T: 2/2.
    """
    s = snap(
        [
            todo(
                "RD",
                task_type="TT_Rsrc",
                target_drtn_hr_cnt="400",
                remain_drtn_hr_cnt="400",
                total_float_hr_cnt="400",
            ),
            todo("T"),
        ]
    )

    r = run(P6, "P6-04", s)
    assert counts(r) == (1, 2)
    assert codes(r) == ["RD"]

    r = run(P6, "P6-06", s)
    assert counts(r) == (1, 2)
    assert codes(r) == ["RD"]

    r = run(P6, "P6-11", s)
    assert counts(r) == (2, 2)
    assert codes(r) == ["RD", "T"]

    r = run(P6, "P6-01", s)
    assert counts(r) == (2, 2)
    assert codes(r) == ["RD", "T"]


def test_level_of_effort_is_excluded_from_baseline_checks():
    """Baseline finish 2026-03-10 17:00 for A, LOE2, LOE3; data date 2026-03-16.

    Current: A not started, forecast finish 03-20 (late); LOE2 in progress,
    forecast 03-20; LOE3 completed 2026-03-12, after its baseline finish.
    LOE is excluded from every population below.
    P6-12: checked = {A}; late = {A}: 1/1.
    DCMA-11: due = {A}; missed = {A}: 1/1.
    P6-13: completed 0 (LOE3 excluded) / baseline activities 1 (A) = 0.0;
    flagged = baseline-due and not completed = A.
    DCMA-14: completed 0 / due 1 = 0.0 < 0.95: fail.
    """
    bl = Baseline.from_snapshot(
        snap(
            [
                todo("A", early_start_date="2026-03-02 08:00", early_end_date="2026-03-10 17:00"),
                todo(
                    "LOE2",
                    task_type="TT_LOE",
                    early_start_date="2026-03-02 08:00",
                    early_end_date="2026-03-10 17:00",
                ),
                todo(
                    "LOE3",
                    task_type="TT_LOE",
                    early_start_date="2026-03-02 08:00",
                    early_end_date="2026-03-10 17:00",
                ),
            ]
        )
    )
    current = snap(
        [
            todo("A", early_start_date="2026-03-16 08:00", early_end_date="2026-03-20 17:00"),
            active("LOE2", task_type="TT_LOE", early_end_date="2026-03-20 17:00"),
            done(
                "LOE3",
                task_type="TT_LOE",
                act_start_date="2026-03-02 08:00",
                act_end_date="2026-03-12 17:00",
            ),
        ],
        data_date="2026-03-16 08:00",
    )

    r = run(P6, "P6-12", current, baseline=bl)
    assert counts(r) == (1, 1)
    assert codes(r) == ["A"]

    r = run(DCMA, "DCMA-11", current, baseline=bl)
    assert counts(r) == (1, 1)
    assert codes(r) == ["A"]

    r = run(P6, "P6-13", current, baseline=bl)
    assert counts(r) == (0, 1)
    assert r.value == pytest.approx(0.0)
    assert codes(r) == ["A"]
    assert r.status == "fail"

    r = run(DCMA, "DCMA-14", current, baseline=bl)
    assert counts(r) == (0, 1)
    assert r.value == pytest.approx(0.0)
    assert r.status == "fail"


def test_lag_boundaries():
    """Chain T1 -> T2 -> T3 -> T4 -> T5 with FS lags 353, 352, 1, 0 h; 4 relationships.

    P6-05: lag > 352 h: only 353 -> (T1, T2): 1/4 = 25 %, target < 5 %: fail.
    P6-08: lag > 0: 353, 352 and 1 -> 3/4 = 75 %, target < 5 %: fail.
    """
    s = snap(
        [todo(f"T{i}") for i in range(1, 6)],
        preds=[
            ("T1", "T2", "FS", 353),
            ("T2", "T3", "FS", 352),
            ("T3", "T4", "FS", 1),
            ("T4", "T5", "FS", 0),
        ],
    )

    r = run(P6, "P6-05", s)
    assert counts(r) == (1, 4)
    assert links(r) == [("T1", "T2")]
    assert r.value == pytest.approx(25.0)
    assert r.status == "fail"

    r = run(P6, "P6-08", s)
    assert counts(r) == (3, 4)
    assert links(r) == [("T1", "T2"), ("T2", "T3"), ("T3", "T4")]
    assert r.value == pytest.approx(75.0)
    assert r.status == "fail"


def test_working_exception_replaces_the_day():
    """Sunday-only calendar; Monday 2026-04-06 is an exception worked 08:00-12:00.

    Hours from Mon 04-06 08:00 to Tue 04-07 08:00: Monday 08:00-12:00 = 4 h;
    Tuesday 00:00-08:00 is not a working day = 0 h; total 4 h.
    Adding 240 working minutes to Mon 08:00 = 4 h: reaches Mon 12:00, the end of
    the exception period.
    """
    cal = _calendar(SUNDAY_ONLY_BLOB, "24")
    hours = cal.work_hours(pd.Timestamp("2026-04-06 08:00"), pd.Timestamp("2026-04-07 08:00"))
    assert hours == pytest.approx(4.0)
    reached = cal.axis().add(pd.Timestamp("2026-04-06 08:00"), 240, finish=True)
    assert reached == pd.Timestamp("2026-04-06 12:00")


def test_inside_a_holiday():
    """C8 with the holiday Fri 2026-04-03.

    Hours from Fri 04-03 10:00 to Mon 04-06 08:00: holiday 0 h, weekend 0 h,
    Monday 00:00-08:00 before the first period 0 h; total 0 h.
    Adding 60 working minutes to Thu 04-02 17:00 (end of Thursday): Friday is a
    holiday and the weekend is off, so counting starts Mon 04-06 08:00 and ends
    Mon 04-06 09:00.
    """
    cal = _calendar(MON_FRI_8H, "8")
    hours = cal.work_hours(pd.Timestamp("2026-04-03 10:00"), pd.Timestamp("2026-04-06 08:00"))
    assert hours == pytest.approx(0.0)
    reached = cal.axis().add(pd.Timestamp("2026-04-02 17:00"), 60, finish=True)
    assert reached == pd.Timestamp("2026-04-06 09:00")


def test_planned_value_at_the_bounds():
    """Budget 80 h over 2026-03-02 08:00 to 2026-03-13 17:00 on C8 (10 days x 8 h = 80 h).

    At the baseline start the share elapsed is 0: PV = 0 h.
    At the baseline finish the share is 1: PV = 80 h.
    One minute after the finish and the next morning: capped at the full budget, 80 h.
    """
    bl = Baseline.from_snapshot(
        snap(
            [
                todo(
                    "A",
                    target_work_qty="80",
                    early_start_date="2026-03-02 08:00",
                    early_end_date="2026-03-13 17:00",
                )
            ]
        )
    )
    expected = {
        "2026-03-02 08:00": 0.0,
        "2026-03-13 17:00": 80.0,
        "2026-03-13 17:01": 80.0,
        "2026-03-14 08:00": 80.0,
    }
    for instant, pv in expected.items():
        assert ev_point(snap([todo("A")], data_date=instant), bl).pv_hr == pytest.approx(pv)


def test_planned_value_with_a_holiday_on_the_first_day():
    """Budget 80 h from 2026-04-03 08:00 to 2026-04-09 17:00 on C8.

    Fri 04-03 is a holiday (0 working h); working time is Mon 04-06, Tue 04-07,
    Wed 04-08 and Thu 04-09 = 4 x 8 = 32 h; rate = 80 / 32 = 2.5 per working
    hour, i.e. 20 h per working day.
    Row convention: the row dated D holds the day before D.
    Row 04-04 (Fri 04-03) = 0; rows 04-07, 04-08, 04-09, 04-10 = 20 each;
    cumulative at the end = 4 x 20 = 80.
    """
    bl = Baseline.from_snapshot(
        snap(
            [
                todo(
                    "A",
                    target_work_qty="80",
                    early_start_date="2026-04-03 08:00",
                    early_end_date="2026-04-09 17:00",
                )
            ]
        )
    )
    curve = pv_curve(bl).set_index("date")
    assert curve.loc["2026-04-04", "pv_hr"] == pytest.approx(0.0)
    for row in ("2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10"):
        assert curve.loc[row, "pv_hr"] == pytest.approx(20.0)
    assert curve.loc["2026-04-10", "pv_cum_hr"] == pytest.approx(80.0)
    assert curve["pv_cum_hr"].iloc[-1] == pytest.approx(80.0)
