"""Unstarted task under a Mandatory Finish with an expected finish that a finish-to-finish bound
overtakes (CPM engine).

Source of the rule: P6 Professional 23.12.1 on the pinned held-out corpus, H25-02 A1240, H27-08
A1150 and H23-10 A1070 (Mandatory Finish, an expected finish, an FF or SF predecessor whose bound
is later than the expected finish: P6 finishes the task at that bound, not at the Mandatory Finish
date), and on the P6 probes h23-shapes; rule XP of the probes xf-mandatory: an expected finish in
force on work not started lifts the Mandatory Finish pin and the date caps the late finish. The
project's reference, 26.8, is not measured.
Rule: with "Use Expected Finish Dates" on, the Mandatory Finish of work not started that carries
an expected finish does not pin its early finish, whether or not the expected finish sets its
duration. An FF bound later than the expected finish gives the early finish, the task keeps its
duration, and the late finish is the lesser of what the successors allow and the date. With the
option off the Mandatory Finish pins both sides. The expected values below are hand calculations
from that rule, not P6 readings.

Every case is a hand-made schedule on xerkit's calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00,
data date Monday 2026-03-02 08:00. T (8 h) is tested: Mandatory Finish Fri 6 Mar 17:00, expected
finish Tue 3 Mar 17:00, and Q -> T finish-to-finish, lag 0, Q starting at the data date. Z (80 h,
no link) ends Fri 13 Mar 17:00, the project finish.
Hand calculation, one line per case:
- Q of 32 h ends Thu 5 Mar 17:00, later than the expected finish: early finish Thu 5 Mar 17:00,
  early start 8 h before = Thu 5 Mar 08:00. Late finish = min(project finish, date) = Fri 6 Mar
  17:00, late start Fri 6 Mar 08:00, total float 8 h.
- the same with a successor S (8 h, FS) under Finish On or Before Fri 6 Mar 17:00: S starts Fri 6
  Mar 08:00 at the latest, so T's late finish is Thu 5 Mar 17:00, late start Thu 5 Mar 08:00, float 0.
- option off, Q of 32 h: pinned. Early and late finish Fri 6 Mar 17:00, start Fri 6 Mar 08:00.
- Q of 16 h ends Tue 3 Mar 17:00, equal to the expected finish: the expected finish sets the
  duration, Mon 2 Mar 08:00 -> Tue 3 Mar 17:00 = 16 h. Late finish Fri 6 Mar 17:00, total float =
  Wed 4 + Thu 5 + Fri 6 Mar = 24 h.
- Q of 17 h ends Wed 4 Mar 09:00, one working hour after the expected finish: early finish Wed 4
  Mar 09:00, early start 8 h before = Tue 3 Mar 09:00. Total float = Wed 4 Mar 09:00 to Fri 6 Mar
  17:00 = 7 h + 8 h + 8 h = 23 h.
"""

import pandas as pd
import pytest
from xerkit import hours, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

OPTION_ON = {"sched_use_expect_end_flag": "Y"}
OPTION_OFF = {"sched_use_expect_end_flag": "N"}


def row_of_t(predecessor_hours: int, successor_finish_on_or_before: str = "", sched: dict = OPTION_ON) -> pd.Series:
    """The schedule row of T, with Q (``predecessor_hours``) -> T finish-to-finish and Z setting the
    project finish. Unless ``successor_finish_on_or_before`` is empty, T -> S (8 h) with that constraint."""
    task = todo(
        "T", cstr_type="CS_MANDFIN", cstr_date="2026-03-06 17:00", expect_end_date="2026-03-03 17:00", **hours(8)
    )
    tasks = [todo("Q", **hours(predecessor_hours)), task, todo("Z", **hours(80))]
    links = [("Q", "T", "FF", 0)]
    if successor_finish_on_or_before:
        tasks.append(todo("S", cstr_type="CS_MEOB", cstr_date=successor_finish_on_or_before, **hours(8)))
        links.append(("T", "S", "FS", 0))
    return schedule(snap(tasks, links, sched=sched)).frame.loc["T"]


def test_the_finish_to_finish_bound_gives_the_early_finish_not_the_mandatory_date():
    """Q ends Thu 5 Mar 17:00: T runs Thu 5 Mar 08:00 -> 17:00; late finish Fri 6 Mar 17:00, float 8 h."""
    row = row_of_t(32)
    assert row["es"] == pd.Timestamp("2026-03-05 08:00")
    assert row["ef"] == pd.Timestamp("2026-03-05 17:00")
    assert row["lf"] == pd.Timestamp("2026-03-06 17:00")
    assert row["ls"] == pd.Timestamp("2026-03-06 08:00")
    assert row["tf_hr"] == 8


def test_a_successor_that_needs_it_earlier_lowers_the_late_finish():
    """S must finish by Fri 6 Mar 17:00, so T by Thu 5 Mar 17:00: late start Thu 5 Mar 08:00, float 0."""
    row = row_of_t(32, "2026-03-06 17:00")
    assert row["lf"] == pd.Timestamp("2026-03-05 17:00")
    assert row["ls"] == pd.Timestamp("2026-03-05 08:00")
    assert row["tf_hr"] == 0


def test_option_off_the_mandatory_finish_pins_both_sides():
    """Option off: early and late finish Fri 6 Mar 17:00, early and late start Fri 6 Mar 08:00."""
    row = row_of_t(32, sched=OPTION_OFF)
    assert row["es"] == pd.Timestamp("2026-03-06 08:00")
    assert row["ef"] == pd.Timestamp("2026-03-06 17:00")
    assert row["ls"] == pd.Timestamp("2026-03-06 08:00")
    assert row["lf"] == pd.Timestamp("2026-03-06 17:00")


@pytest.mark.parametrize(
    ("predecessor_hours", "early_start", "early_finish", "total_float_hr"),
    [
        pytest.param(16, "2026-03-02 08:00", "2026-03-03 17:00", 24, id="bound-equal-to-the-expected-finish"),
        pytest.param(17, "2026-03-03 09:00", "2026-03-04 09:00", 23, id="bound-one-working-hour-after"),
    ],
)
def test_boundary_between_the_bound_and_the_expected_finish(
    predecessor_hours, early_start, early_finish, total_float_hr
):
    """Equal: the expected finish sets the duration. One hour later: the bound gives the finish and the
    task keeps its 8 h. Late finish Fri 6 Mar 17:00 in both; see the module docstring."""
    row = row_of_t(predecessor_hours)
    assert row["es"] == pd.Timestamp(early_start)
    assert row["ef"] == pd.Timestamp(early_finish)
    assert row["lf"] == pd.Timestamp("2026-03-06 17:00")
    assert row["tf_hr"] == total_float_hr
