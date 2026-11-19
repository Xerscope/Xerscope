"""Unstarted start milestone with Mandatory Start and an expected finish (CPM engine).

Source of every value: P6 Professional 23.12.1 measured on the pinned held-out corpus
(schedules built for the purpose); the project's reference, 26.8, is not measured.
Rule: with "Use Expected Finish Dates" on, the early start (= early finish of a milestone) of an
unstarted start milestone with Mandatory Start c and expected finish a is max(c, a), the logic
(predecessors) ignored. A start milestone writes the instant as a task start: a working instant
is kept, a period end (17:00) becomes the next opening (08:00 the next working day). With the
option off, a is ignored: c alone. The data date is a floor (no start before it).

Every case is a hand-made schedule on xerkit's calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00,
data date Monday 2026-03-02 08:00. Predecessor P (8 h) runs Mon 2 Mar 08:00 -> 17:00.
Hand calculation, one line per case:
- a after c: c = Tue 3 Mar 08:00, a = Thu 5 Mar 17:00. max = a. Written as a start, 17:00 ends
  the period: Fri 6 Mar 08:00 (start and finish).
- a before c: a = Tue 3 Mar 17:00, c = Thu 5 Mar 08:00. max = c = Thu 5 Mar 08:00, working.
- option off, a after c: a ignored, c = Tue 3 Mar 08:00.
- logic later than c and a: P of 40 h runs Mon 2 -> Fri 6 Mar 17:00, so the logic would give
  Mon 9 Mar 08:00. The result stays max(c, a): c = Tue 3 08:00, a = Thu 5 17:00 -> Fri 6 08:00.
- a equal to c: both Thu 5 Mar 08:00, max = Thu 5 Mar 08:00.
- a one minute after c (same day, working): c = Thu 5 Mar 10:00, a = 10:01, max = 10:01.
- a one minute before c: c = Thu 5 Mar 10:00, a = 09:59, max = c = 10:00.
- control, a task (16 h): Mandatory Start c = Tue 3 Mar 08:00 gives the start; the expected
  finish a = Thu 5 Mar 17:00 stands in for start + 16 h (Wed 4 Mar 17:00), so finish = a.
"""

import pandas as pd
import pytest
from xerkit import SM, hours, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

OPTION_ON = {"sched_use_expect_end_flag": "Y"}
OPTION_OFF = {"sched_use_expect_end_flag": "N"}


def row_after_predecessor(
    activity: dict, predecessor_hours: int = 8, sched: dict = OPTION_ON, constraint_date: str = ""
) -> pd.Series:
    """The schedule row of ``activity``, FS successor of P (``predecessor_hours`` long),
    under Mandatory Start on ``constraint_date``."""
    activity = {**activity, "cstr_type": "CS_MANDSTART", "cstr_date": constraint_date}
    tasks = [todo("P", **hours(predecessor_hours)), activity]
    links = [("P", activity["task_code"], "FS", 0)]
    return schedule(snap(tasks, links, sched=sched)).frame.loc[activity["task_code"]]


def mandatory_start_milestone(
    constraint_date: str,
    expected_finish: str,
    predecessor_hours: int = 8,
    sched: dict = OPTION_ON,
) -> pd.Series:
    """The schedule row of a start milestone with Mandatory Start and an expected finish."""
    milestone = todo("SM1", expect_end_date=expected_finish, **SM)
    return row_after_predecessor(milestone, predecessor_hours, sched, constraint_date)


def test_expected_finish_after_the_mandatory_start_wins():
    """c = Tue 3 Mar 08:00, a = Thu 5 Mar 17:00: max = a, written as a start = Fri 6 Mar 08:00."""
    row = mandatory_start_milestone("2026-03-03 08:00", "2026-03-05 17:00")
    assert row["es"] == pd.Timestamp("2026-03-06 08:00")
    assert row["ef"] == pd.Timestamp("2026-03-06 08:00")


def test_mandatory_start_after_the_expected_finish_wins():
    """a = Tue 3 Mar 17:00, c = Thu 5 Mar 08:00: max = c = Thu 5 Mar 08:00."""
    row = mandatory_start_milestone("2026-03-05 08:00", "2026-03-03 17:00")
    assert row["es"] == pd.Timestamp("2026-03-05 08:00")
    assert row["ef"] == pd.Timestamp("2026-03-05 08:00")


def test_option_off_the_expected_finish_is_ignored():
    """Option off, c = Tue 3 Mar 08:00, a = Thu 5 Mar 17:00: a is ignored, result = c."""
    row = mandatory_start_milestone("2026-03-03 08:00", "2026-03-05 17:00", sched=OPTION_OFF)
    assert row["es"] == pd.Timestamp("2026-03-03 08:00")
    assert row["ef"] == pd.Timestamp("2026-03-03 08:00")


def test_logic_later_than_both_dates_is_ignored():
    """P of 40 h ends Fri 6 Mar 17:00 (logic would give Mon 9 Mar 08:00); c = Tue 3 Mar 08:00,
    a = Thu 5 Mar 17:00: the result stays max(c, a) written as a start = Fri 6 Mar 08:00."""
    row = mandatory_start_milestone("2026-03-03 08:00", "2026-03-05 17:00", predecessor_hours=40)
    assert row["es"] == pd.Timestamp("2026-03-06 08:00")
    assert row["ef"] == pd.Timestamp("2026-03-06 08:00")


@pytest.mark.parametrize(
    ("constraint_date", "expected_finish", "expected_start"),
    [
        pytest.param("2026-03-05 08:00", "2026-03-05 08:00", "2026-03-05 08:00", id="equal"),
        pytest.param("2026-03-05 10:00", "2026-03-05 10:01", "2026-03-05 10:01", id="one-minute-after"),
        pytest.param("2026-03-05 10:00", "2026-03-05 09:59", "2026-03-05 10:00", id="one-minute-before"),
    ],
)
def test_boundary_between_the_expected_finish_and_the_mandatory_start(constraint_date, expected_finish, expected_start):
    """Same day, working time: the result is max(c, a) to the minute (see the module docstring)."""
    row = mandatory_start_milestone(constraint_date, expected_finish)
    assert row["es"] == pd.Timestamp(expected_start)
    assert row["ef"] == pd.Timestamp(expected_start)


def test_task_under_mandatory_start_keeps_its_start_and_ends_at_the_expected_finish():
    """Task of 16 h, c = Tue 3 Mar 08:00, a = Thu 5 Mar 17:00: start = c, finish = a (later than
    start + 16 h = Wed 4 Mar 17:00). Non-regression: a task is not placed like a milestone."""
    task = todo("A", expect_end_date="2026-03-05 17:00", **hours(16))
    row = row_after_predecessor(task, constraint_date="2026-03-03 08:00")
    assert row["es"] == pd.Timestamp("2026-03-03 08:00")
    assert row["ef"] == pd.Timestamp("2026-03-05 17:00")
