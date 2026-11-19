"""Unstarted task with Mandatory Finish and an expected finish: its late dates (CPM engine).

Source of the rule: P6 Professional 23.12.1 measured on the pinned held-out corpus (8 unstarted
tasks under Mandatory Finish with an expected finish earlier than the date whose late finish only
this rule gives, e.g. H29-02 A1160, H29-11 A1230); the project's reference, 26.8, is not measured.
The expected values of the cases below are hand calculations from that rule, not P6 readings.
Rule: with "Use Expected Finish Dates" on, the Mandatory Finish c of an unstarted task T (type
TT_Task) that has an expected finish a (earlier than c) no longer pins its late finish: it caps it.
Late finish of T = min(bound given by its successors and the project end, c). The expected finish
fixes the remaining duration of T from its early start to a, in working time of T's calendar, and
late start = late finish minus that duration. Early side: early start = data date, early finish = a.
Without an expected finish applied (option off), Mandatory Finish pins the late finish at c
whatever the successors say, and the remaining duration is the stated one (8 h).

Every case is a hand-made schedule on xerkit's calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00,
data date Monday 2026-03-02 08:00. T (8 h) is tested. Z (80 h, no link) ends Fri 13 Mar 17:00, which
makes the project's late bound Fri 13 Mar 17:00. To bound T by a successor, T -> S (FS, lag 0) with
S (8 h) carrying Finish On or Before d: S's late start is d minus 8 working hours and the bound on T
is the period end just before it.
With a = Tue 3 Mar 17:00 the remaining duration of T is the working time from Mon 2 Mar 08:00 to
Tue 3 Mar 17:00 = 8 h + 8 h = 16 h, and the total float is the working time from a to the late
finish (the same as late start minus early start).
Hand calculation, one line per case:
- bound after c: no successor, bound = Fri 13 Mar 17:00. c = Thu 5 Mar 17:00. min = c. Late start =
  c minus 16 h = Thu 5 Mar 08:00 minus 8 h = Wed 4 Mar 08:00. Float = Tue 3 17:00 to Thu 5 17:00 = 16 h.
- bound before c: d = Thu 5 Mar 17:00, S starts at the latest Thu 5 Mar 08:00, the bound is Wed 4 Mar
  17:00. c = Fri 6 Mar 17:00. min = Wed 4 Mar 17:00. Late start = Wed 4 08:00 minus 8 h = Tue 3 Mar
  08:00. Float = Tue 3 17:00 to Wed 4 17:00 = 8 h.
- option off: a ignored, duration 8 h, the dates of the case above. c = Fri 6 Mar 17:00 pins: late
  finish = c, late start = Fri 6 Mar 17:00 minus 8 h = Fri 6 Mar 08:00.
- bound equal to c: bound Wed 4 Mar 17:00 = c. min = Wed 4 Mar 17:00, late start Tue 3 Mar 08:00,
  float 8 h.
- c one working hour after the bound: c = Thu 5 Mar 09:00 (17:00 Wed is the end of the period, one
  hour later is 09:00 the next morning). min = Wed 4 Mar 17:00, late start Tue 3 Mar 08:00, float 8 h.
- c one working hour before the bound: c = Wed 4 Mar 16:00. min = Wed 4 Mar 16:00. 16 h back: Wed
  16:00 minus 7 h (Wed 08:00) minus 1 h = Tue 16:00; Tue 16:00 minus 7 h (Tue 08:00) minus 1 h =
  Mon 16:00. Late start = Mon 2 Mar 16:00. Float = Mon 2 Mar 08:00 to Mon 2 Mar 16:00 = 7 h.
- a start-to-start successor: T -> S (SS, lag 0), S (8 h) under Finish On or Before Wed 4 Mar 17:00,
  so S starts Wed 4 Mar 08:00 at the latest and so does T. c = Fri 6 Mar 17:00, a = Tue 3 Mar 17:00
  (16 h). Late start = Wed 4 Mar 08:00, late finish 16 h later = Thu 5 Mar 17:00, earlier than c.
  Float = Tue 3 17:00 to Thu 5 17:00 = 16 h. Standard backward pass through the link; the
  combination with a Mandatory Finish is not a P6 reading.
"""

import pandas as pd
import pytest
from xerkit import hours, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

T = pd.Timestamp
OPTION_ON = {"sched_use_expect_end_flag": "Y"}
OPTION_OFF = {"sched_use_expect_end_flag": "N"}


def task_row(
    mandatory_finish: str,
    expected_finish: str,
    successor_finish_on_or_before: str = "",
    sched: dict = OPTION_ON,
) -> pd.Series:
    """The schedule row of the task T, with Z setting the project end.

    T (8 h) has Mandatory Finish on ``mandatory_finish`` and the expected finish
    ``expected_finish``. Unless ``successor_finish_on_or_before`` is empty, T -> S (S: 8 h, Finish
    On or Before on that date) bounds T."""
    task = todo("T", cstr_type="CS_MANDFIN", cstr_date=mandatory_finish, expect_end_date=expected_finish, **hours(8))
    tasks = [task, todo("Z", **hours(80))]
    links = []
    if successor_finish_on_or_before:
        tasks.append(todo("S", cstr_type="CS_MEOB", cstr_date=successor_finish_on_or_before, **hours(8)))
        links.append(("T", "S", "FS", 0))
    return schedule(snap(tasks, links, sched=sched)).frame.loc["T"]


# --- the bound given by the successors and the project end is later than the Mandatory Finish ----------


def test_bound_after_the_mandatory_finish_leaves_the_late_finish_at_it():
    """No successor, bound = project end Fri 13 Mar 17:00; c = Thu 5 Mar 17:00, a = Tue 3 Mar 17:00:
    late finish = c = Thu 5 Mar 17:00, late start Wed 4 Mar 08:00 (16 h), float 16 h."""
    row = task_row("2026-03-05 17:00", "2026-03-03 17:00")
    assert row["lf"] == T("2026-03-05 17:00")
    assert row["ls"] == T("2026-03-04 08:00")
    assert row["tf_hr"] == 16


# --- the bound given by the successors is earlier than the Mandatory Finish -------------------------


def test_bound_before_the_mandatory_finish_caps_the_late_finish_at_the_bound():
    """Bound Wed 4 Mar 17:00 (S Finish On or Before Thu 5 Mar 17:00), c = Fri 6 Mar 17:00,
    a = Tue 3 Mar 17:00: late finish = min = Wed 4 Mar 17:00, late start Tue 3 Mar 08:00, float 8 h."""
    row = task_row("2026-03-06 17:00", "2026-03-03 17:00", "2026-03-05 17:00")
    assert row["lf"] == T("2026-03-04 17:00")
    assert row["ls"] == T("2026-03-03 08:00")
    assert row["tf_hr"] == 8


# --- option off: the Mandatory Finish pins the late finish, as before -------------------------------


def test_option_off_the_mandatory_finish_pins_the_late_finish():
    """Option off: a (Tue 3 Mar 17:00) is ignored, the bound is Wed 4 Mar 17:00, c = Fri 6 Mar
    17:00: late finish pinned at c, late start Fri 6 Mar 08:00 (duration 8 h)."""
    row = task_row("2026-03-06 17:00", "2026-03-03 17:00", "2026-03-05 17:00", OPTION_OFF)
    assert row["lf"] == T("2026-03-06 17:00")
    assert row["ls"] == T("2026-03-06 08:00")


# --- boundary between the bound and the Mandatory Finish --------------------------------------------


@pytest.mark.parametrize(
    ("mandatory_finish", "expected_late_finish", "expected_late_start", "expected_total_float_hr"),
    [
        pytest.param("2026-03-04 17:00", "2026-03-04 17:00", "2026-03-03 08:00", 8, id="equal"),
        pytest.param("2026-03-05 09:00", "2026-03-04 17:00", "2026-03-03 08:00", 8, id="one-working-hour-after"),
        pytest.param("2026-03-04 16:00", "2026-03-04 16:00", "2026-03-02 16:00", 7, id="one-working-hour-before"),
    ],
)
def test_boundary_between_the_successor_bound_and_the_mandatory_finish(
    mandatory_finish, expected_late_finish, expected_late_start, expected_total_float_hr
):
    """Bound Wed 4 Mar 17:00 (S Finish On or Before Thu 5 Mar 17:00), a = Tue 3 Mar 17:00:
    late finish = min(bound, c), late start 16 h before it; see the module docstring."""
    row = task_row(mandatory_finish, "2026-03-03 17:00", "2026-03-05 17:00")
    assert row["lf"] == T(expected_late_finish)
    assert row["ls"] == T(expected_late_start)
    assert row["tf_hr"] == expected_total_float_hr


# --- a successor linked start-to-start bounds the late start ----------------------------------------


def test_start_to_start_successor_bounds_the_late_start_under_the_cap():
    """S (SS after T) must start by Wed 4 Mar 08:00, so must T: late start Wed 4 Mar 08:00, late finish
    16 h later = Thu 5 Mar 17:00 (earlier than c = Fri 6 Mar 17:00), float 16 h."""
    task = todo(
        "T", cstr_type="CS_MANDFIN", cstr_date="2026-03-06 17:00", expect_end_date="2026-03-03 17:00", **hours(8)
    )
    successor = todo("S", cstr_type="CS_MEOB", cstr_date="2026-03-04 17:00", **hours(8))
    tasks = [task, successor, todo("Z", **hours(80))]
    row = schedule(snap(tasks, [("T", "S", "SS", 0)], sched=OPTION_ON)).frame.loc["T"]
    assert row["ls"] == T("2026-03-04 08:00")
    assert row["lf"] == T("2026-03-05 17:00")
    assert row["tf_hr"] == 16
