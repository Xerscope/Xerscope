"""Unstarted task with an expected finish under a Finish On or a Finish On or After (CPM engine).

Source of the rule: P6 Professional 23.12.1 on the P6 probes of the pinned corpus: oc-edges-xc N5
(Finish On or After Fri 11 Dec, expected finish Wed 9 Dec: P6 finishes it Wed 9 Dec 17:00, late
finish from the network, 88 h) and N7 (Finish On Fri 11 Dec: Wed 9 Dec 17:00, late finish Fri 11
Dec 17:00, 16 h); xf-mandatory M7. Held-out corpus: H24-08 A1100. The project's reference, 26.8,
is not measured.
Rule: with "Use Expected Finish Dates" on, an expected finish in force on work not started drops
the early side of Finish On and Finish On or After: the task starts where its logic puts it and
finishes at its expected finish. The late side of Finish On stays a cap; Finish On or After has
none. With the option off the constraint holds. The expected values below are hand calculations
from that rule, not P6 readings.

Every case is a hand-made schedule on xerkit's calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00,
data date Monday 2026-03-02 08:00. P (8 h) runs Mon 2 Mar 08:00 -> 17:00. A (16 h, FS after P)
starts Tue 3 Mar 08:00 and has the expected finish Thu 5 Mar 17:00, so its duration becomes Tue 3
Mar 08:00 -> Thu 5 Mar 17:00 = 24 h. Its constraint is dated Wed 11 Mar 17:00. Z (80 h, no link)
ends Fri 13 Mar 17:00, the project finish; A has no successor.
Hand calculation, one line per case:
- Finish On or After: early start Tue 3 Mar 08:00, early finish Thu 5 Mar 17:00. Late finish = the
  project finish Fri 13 Mar 17:00, late start 24 h before = Wed 11 Mar 08:00, total float = Thu 5
  Mar 17:00 to Fri 13 Mar 17:00 = 6 days = 48 h.
- Finish On: the same early dates. Late finish capped at Wed 11 Mar 17:00, late start 24 h before =
  Mon 9 Mar 08:00, total float = Thu 5 Mar 17:00 to Wed 11 Mar 17:00 = 4 days = 32 h.
- option off, either constraint: the expected finish is ignored and the constraint pushes the
  finish to Wed 11 Mar 17:00; the start is 16 h before, Tue 10 Mar 08:00.
"""

import pandas as pd
import pytest
from xerkit import hours, snap, todo

from xerscope.analysis.cpm import schedule
from xerscope.xer.calendar import TimeAxis

pytestmark = pytest.mark.oracle("p6")

OPTION_ON = {"sched_use_expect_end_flag": "Y"}
OPTION_OFF = {"sched_use_expect_end_flag": "N"}


def row_of_a(constraint_type: str, sched: dict = OPTION_ON) -> pd.Series:
    """The schedule row of A (16 h, FS after P) under ``constraint_type`` dated Wed 11 Mar 17:00."""
    task = todo(
        "A", cstr_type=constraint_type, cstr_date="2026-03-11 17:00", expect_end_date="2026-03-05 17:00", **hours(16)
    )
    tasks = [todo("P", **hours(8)), task, todo("Z", **hours(80))]
    return schedule(snap(tasks, [("P", "A", "FS", 0)], sched=sched)).frame.loc["A"]


@pytest.mark.parametrize("constraint_type", ["CS_MEOA", "CS_MEO"])
def test_the_task_finishes_at_its_expected_finish_not_at_the_constraint(constraint_type):
    """Early start Tue 3 Mar 08:00 (the logic), early finish Thu 5 Mar 17:00 (the expected finish)."""
    row = row_of_a(constraint_type)
    assert row["es"] == pd.Timestamp("2026-03-03 08:00")
    assert row["ef"] == pd.Timestamp("2026-03-05 17:00")


def test_finish_on_or_after_leaves_the_late_dates_to_the_network():
    """Late finish Fri 13 Mar 17:00 (the project finish), late start Wed 11 Mar 08:00, total float 48 h."""
    row = row_of_a("CS_MEOA")
    assert row["lf"] == pd.Timestamp("2026-03-13 17:00")
    assert row["ls"] == pd.Timestamp("2026-03-11 08:00")
    assert row["tf_hr"] == 48


def test_finish_on_still_caps_the_late_finish():
    """Late finish Wed 11 Mar 17:00 (the constraint), late start Mon 9 Mar 08:00, total float 32 h."""
    row = row_of_a("CS_MEO")
    assert row["lf"] == pd.Timestamp("2026-03-11 17:00")
    assert row["ls"] == pd.Timestamp("2026-03-09 08:00")
    assert row["tf_hr"] == 32


@pytest.mark.parametrize("constraint_type", ["CS_MEOA", "CS_MEO"])
def test_option_off_the_constraint_holds(constraint_type):
    """Option off: early finish Wed 11 Mar 17:00 (the constraint), early start 16 h before, Tue 10 Mar 08:00."""
    row = row_of_a(constraint_type, OPTION_OFF)
    assert row["es"] == pd.Timestamp("2026-03-10 08:00")
    assert row["ef"] == pd.Timestamp("2026-03-11 17:00")


def test_an_expected_finish_equal_to_the_finish_bound_still_sets_the_remaining_work():
    """is_expected_finish_applied docstring: the expected finish applies when it is after the
    assignment's start "and not before the finish bound", so a tie applies. Tuesday 3 Mar
    08:00 to Thursday 5 Mar 17:00 on C8 (Mon-Fri 08:00-12:00 / 13:00-17:00) is 3 working
    days = 24 h = 1440 minutes, against a base duration of 40 h (2400 minutes) that is kept
    when the expected finish does not apply."""
    from xerscope.analysis.resource_placement import Assignment, is_expected_finish_applied, sized_minutes

    start = pd.Timestamp("2026-03-03 08:00")
    thursday = pd.Timestamp("2026-03-05 17:00")
    assert is_expected_finish_applied(thursday, start, thursday)
    assert not is_expected_finish_applied(thursday, start, thursday + pd.Timedelta(minutes=1))

    snapshot = snap([todo("A", **hours(40))], [])
    axis = TimeAxis(snapshot.calendar(None), start.date(), pd.Timestamp("2026-03-13").date())
    assignment = Assignment("R1", "RS", axis, 0.0, 2400.0, True)
    durations, expected_applies = sized_minutes([assignment], {"R1": 2400.0}, start, thursday, thursday)
    assert expected_applies
    assert durations == {"R1": 1440.0}
