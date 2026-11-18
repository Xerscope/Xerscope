"""Unstarted milestones with an expected finish: the early date sits at it (CPM engine).

Source of every value: docs/deep-dive/engine-gaps.md, "Experiment 2 - family C" and 3.C,
read off P6 23.12 exports (witnesses H23-09 A1200, H26-08 A1390, H28-11 A1330 for finish
milestones, H26-11 A1370 for start milestones). Rule: with "Use Expected Finish Dates" on, an
unstarted milestone's early date is max(logic bound, expected finish); the early side of Finish
On, Finish On or After and Mandatory Finish is dropped (their late side still caps); a start
milestone writes the instant as a task start (next period start), a finish milestone as a finish.

Every case is a hand-made schedule on xerkit's calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00,
data date Monday 2026-03-02 08:00 (DD). Predecessor P (8 h) runs Mon 2 Mar 08:00 -> 17:00.
Calendar of the days used: Tue 3, Wed 4, Thu 5, Fri 6, Wed 11 March.

The document's own example puts the expected finish at DD+5d 17:00, a Saturday on C8, where the
start milestone's "DD+6d 08:00" is a Sunday: the contract does not say what P6 does off the
calendar. These tests use Thu 5 Mar 17:00 (DD+3d), a period end, to stay on working time.
"""

import pandas as pd
import pytest
from xerkit import FM, SM, hours, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

T = pd.Timestamp
OPTION_ON = {"sched_use_expect_end_flag": "Y"}
OPTION_OFF = {"sched_use_expect_end_flag": "N"}
EXPECTED_FINISH_THURSDAY = "2026-03-05 17:00"  # DD+3d 17:00, later than P's finish (Mon 17:00)


def milestone_after_p(milestone: dict, sched: dict = OPTION_ON) -> pd.Series:
    """The schedule row of ``milestone`` when P (8 h) is its FS predecessor."""
    tasks = [todo("P", **hours(8)), milestone]
    links = [("P", milestone["task_code"], "FS", 0)]
    return schedule(snap(tasks, links, sched=sched)).frame.loc[milestone["task_code"]]


# --- a finish milestone with an expected finish later than the logic ----------------------------


def test_finish_milestone_sits_at_the_expected_finish():
    """P finishes Mon 2 Mar 17:00; the expected finish is Thu 5 Mar 17:00, later, a period end,
    so the finish milestone is kept as is: early start = early finish = Thu 5 Mar 17:00."""
    row = milestone_after_p(todo("FM1", expect_end_date=EXPECTED_FINISH_THURSDAY, **FM))
    assert row["es"] == T("2026-03-05 17:00")
    assert row["ef"] == T("2026-03-05 17:00")


def test_successor_of_the_finish_milestone_follows_it():
    """FM1 at Thu 5 Mar 17:00; S (8 h, FS after FM1) starts at the next working minute, Fri 6
    Mar 08:00, and finishes Fri 6 Mar 17:00."""
    tasks = [
        todo("P", **hours(8)),
        todo("FM1", expect_end_date=EXPECTED_FINISH_THURSDAY, **FM),
        todo("S", **hours(8)),
    ]
    links = [("P", "FM1", "FS", 0), ("FM1", "S", "FS", 0)]
    row = schedule(snap(tasks, links, sched=OPTION_ON)).frame.loc["S"]
    assert row["es"] == T("2026-03-06 08:00")
    assert row["ef"] == T("2026-03-06 17:00")


@pytest.mark.parametrize("constraint", ["CS_MEO", "CS_MEOA", "CS_MANDFIN"])
def test_finish_constraint_early_side_is_dropped(constraint):
    """Finish On, Finish On or After and Mandatory Finish, dated Wed 11 Mar 17:00 (DD+9d), no
    longer push the milestone: it sits at the expected finish, Thu 5 Mar 17:00 (H23-09 A1200)."""
    row = milestone_after_p(
        todo("FM2", cstr_type=constraint, cstr_date="2026-03-11 17:00", expect_end_date=EXPECTED_FINISH_THURSDAY, **FM)
    )
    assert row["ef"] == T("2026-03-05 17:00")


def test_finish_on_late_side_still_caps_the_late_finish():
    """Finish On Wed 4 Mar 17:00, expected finish Thu 5 Mar 17:00. Only the early side is
    dropped; the late side stays a cap: late finish = Wed 4 Mar 17:00 (engine-gaps.md,
    Experiment 2: "their late side stays a cap")."""
    row = milestone_after_p(
        todo("FM3", cstr_type="CS_MEO", cstr_date="2026-03-04 17:00", expect_end_date=EXPECTED_FINISH_THURSDAY, **FM)
    )
    assert row["lf"] == T("2026-03-04 17:00")


def test_option_off_the_finish_on_keeps_its_early_side():
    """Option "Use Expected Finish Dates" off: the expected finish is ignored and Finish On Wed 11
    Mar 17:00 pushes the milestone there, as it always did."""
    row = milestone_after_p(
        todo("FM2", cstr_type="CS_MEO", cstr_date="2026-03-11 17:00", expect_end_date=EXPECTED_FINISH_THURSDAY, **FM),
        OPTION_OFF,
    )
    assert row["ef"] == T("2026-03-11 17:00")


# --- a start milestone with an expected finish ---------------------------------------------------


def test_start_milestone_sits_at_the_expected_finish_written_as_a_start():
    """Expected finish Thu 5 Mar 17:00, a period end: written as a task start it is the next
    period start, Fri 6 Mar 08:00 (H26-11 A1370: Mon 8 Mar 07:00 in the corpus's calendar)."""
    row = milestone_after_p(todo("SM1", expect_end_date=EXPECTED_FINISH_THURSDAY, **SM))
    assert row["es"] == T("2026-03-06 08:00")
    assert row["ef"] == T("2026-03-06 08:00")


# --- boundaries between the expected finish and the logic bound (finish milestone) ----------------


def test_finish_milestone_expected_finish_one_minute_before_the_logic_stays_on_the_logic():
    """P finishes Mon 2 Mar 17:00; the expected finish Mon 2 Mar 16:59 is earlier: P6 ignores
    it (engine-gaps.md 3.C, xs 76-80 % right), the milestone stays at Mon 2 Mar 17:00."""
    row = milestone_after_p(todo("FM4", expect_end_date="2026-03-02 16:59", **FM))
    assert row["ef"] == T("2026-03-02 17:00")


def test_finish_milestone_expected_finish_equal_to_the_logic():
    """The expected finish equals P's finish, Mon 2 Mar 17:00: max of two equal dates."""
    row = milestone_after_p(todo("FM5", expect_end_date="2026-03-02 17:00", **FM))
    assert row["ef"] == T("2026-03-02 17:00")


def test_finish_milestone_expected_finish_one_minute_after_the_logic():
    """P finishes Mon 2 Mar 17:00; the expected finish Tue 3 Mar 08:01 is later than the logic
    and inside working time: max = Tue 3 Mar 08:01. The contract only gives max(logic, expected
    finish); no source says P6 keeps a one-minute finish."""
    row = milestone_after_p(todo("FM6", expect_end_date="2026-03-03 08:01", **FM))
    assert row["ef"] == T("2026-03-03 08:01")


def test_start_milestone_expected_finish_before_the_logic_stays_on_the_logic():
    """Expected finish Mon 2 Mar 12:00 is before P's finish: the start milestone follows P, at
    the next working minute, Tue 3 Mar 08:00."""
    row = milestone_after_p(todo("SM2", expect_end_date="2026-03-02 12:00", **SM))
    assert row["es"] == T("2026-03-03 08:00")


# --- option off ----------------------------------------------------------------------------------


def test_option_off_the_finish_milestone_stays_on_the_logic():
    """Option off: the expected finish Thu 5 Mar 17:00 is ignored, the milestone sits at P's
    finish, Mon 2 Mar 17:00."""
    row = milestone_after_p(todo("FM1", expect_end_date=EXPECTED_FINISH_THURSDAY, **FM), OPTION_OFF)
    assert row["ef"] == T("2026-03-02 17:00")


def test_option_off_the_start_milestone_stays_on_the_logic():
    """Option off: the start milestone sits right after P, Tue 3 Mar 08:00."""
    row = milestone_after_p(todo("SM1", expect_end_date=EXPECTED_FINISH_THURSDAY, **SM), OPTION_OFF)
    assert row["es"] == T("2026-03-03 08:00")


# --- control: a task with an expected finish does not change -------------------------------------


def test_task_with_an_expected_finish_is_unchanged():
    """Task A (16 h, FS after P) starts Tue 3 Mar 08:00; the expected finish Thu 5 Mar 17:00 is
    later than its logic finish (Wed 4 Mar 17:00) and stands in for it: early finish Thu 5 Mar
    17:00 (docs/cpm.md: the expected finish stands in for start + remaining)."""
    tasks = [todo("P", **hours(8)), todo("A", expect_end_date=EXPECTED_FINISH_THURSDAY, **hours(16))]
    row = schedule(snap(tasks, [("P", "A", "FS", 0)], sched=OPTION_ON)).frame.loc["A"]
    assert row["es"] == T("2026-03-03 08:00")
    assert row["ef"] == T("2026-03-05 17:00")


@pytest.mark.oracle("characterization")
def test_task_finish_on_later_than_its_expected_finish_still_wins():
    """Characterization of the engine as it was before milestones were handled: a task is not
    placed like a milestone. Task A (16 h, FS after P) has a Finish On Wed 11 Mar 17:00 later than
    its expected finish Thu 5 Mar 17:00; the later finish bound wins (cpm.py, expected_finish: "an
    FF / SF bound later than that finish wins"): early finish Wed 11 Mar 17:00, start 16 h before,
    Tue 10 Mar 08:00. Hand calculation: Tue 10 08:00 + 16 working hours (8 h + 8 h) = Wed 11 17:00."""
    tasks = [
        todo("P", **hours(8)),
        todo("A", cstr_type="CS_MEO", cstr_date="2026-03-11 17:00", expect_end_date=EXPECTED_FINISH_THURSDAY, **hours(16)),
    ]
    row = schedule(snap(tasks, [("P", "A", "FS", 0)], sched=OPTION_ON)).frame.loc["A"]
    assert row["es"] == T("2026-03-10 08:00")
    assert row["ef"] == T("2026-03-11 17:00")
