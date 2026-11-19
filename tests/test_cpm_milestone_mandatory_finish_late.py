"""Unstarted finish milestone with Mandatory Finish and an expected finish: its late finish (CPM engine).

Source of every value: P6 Professional 23.12.1 measured on the pinned held-out corpus (14 finish
milestones); the project's reference, 26.8, is not measured. Rule: with "Use Expected Finish
Dates" on, the Mandatory Finish c of an unstarted finish milestone M that has an expected finish
a (earlier than c) no longer pins its late finish: it caps it. Late finish of M = min(bound given
by its successors, c). The late start of a finish milestone is its late finish. Measured example
(H23-07 A1250): c = 16 Jun 12:00, a = 11 Jun 12:00, successors' bound = 15 Jun 12:00; P6 gives
15 Jun 12:00, not c. Without an expected finish applied (option off, or no expected finish),
Mandatory Finish pins the late finish at c whatever the successors say.

Every case is a hand-made schedule on xerkit's calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00,
data date Monday 2026-03-02 08:00. Chain P (8 h) -> M (finish milestone) -> S (8 h), FS, lag 0.
S carries Finish On or Before d, so S's late start is d minus 8 working hours and the bound on M
is the period end just before that late start. Z (80 h, no link) ends Fri 13 Mar 17:00, which
makes the project's late bound Fri 13 Mar 17:00 and keeps d, not the project end, the limit on S.
Hand calculation, one line per case:
- bound before c: d = Thu 5 Mar 17:00, so S starts at the latest Thu 5 Mar 08:00 and the bound
  is Wed 4 Mar 17:00. c = Fri 6 Mar 17:00. min(Wed 4 17:00, c) = Wed 4 Mar 17:00. The same with
  a = Wed 4 Mar 17:00 (the case as first stated) and a = Tue 3 Mar 17:00 (a differs from the bound).
- bound after c: d = Fri 13 Mar 17:00, S starts at the latest Fri 13 Mar 08:00, the bound is
  Thu 12 Mar 17:00. c = Thu 5 Mar 17:00, a = Tue 3 Mar 17:00. min = c = Thu 5 Mar 17:00.
- option off: a ignored; the dates of the first case. Mandatory Finish pins: c = Fri 6 Mar 17:00.
- no expected finish, option on: the dates of the first case. Pinned: c = Fri 6 Mar 17:00.
- bound equal to c: d = Thu 5 Mar 17:00, bound = Wed 4 Mar 17:00 = c. min = Wed 4 Mar 17:00.
- c one working hour after the bound: c = Thu 5 Mar 09:00 (17:00 Wed is the end of the period,
  one hour later is 09:00 the next morning). min(Wed 4 17:00, Thu 5 09:00) = Wed 4 Mar 17:00.
- c one working hour before the bound: c = Wed 4 Mar 16:00. min(Wed 4 17:00, 16:00) = Wed 4 16:00.
"""

import pandas as pd
import pytest
from xerkit import FM, hours, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

T = pd.Timestamp
OPTION_ON = {"sched_use_expect_end_flag": "Y"}
OPTION_OFF = {"sched_use_expect_end_flag": "N"}


def finish_milestone_row(
    mandatory_finish: str,
    expected_finish: str,
    successor_finish_on_or_before: str,
    sched: dict = OPTION_ON,
) -> pd.Series:
    """The schedule row of the finish milestone M in P -> M -> S, with Z setting the project end.

    M has Mandatory Finish on ``mandatory_finish`` and, unless ``expected_finish`` is empty, that
    expected finish. S has Finish On or Before on ``successor_finish_on_or_before``."""
    milestone = todo("M", cstr_type="CS_MANDFIN", cstr_date=mandatory_finish, **FM)
    if expected_finish:
        milestone["expect_end_date"] = expected_finish
    tasks = [
        todo("P", **hours(8)),
        milestone,
        todo("S", cstr_type="CS_MEOB", cstr_date=successor_finish_on_or_before, **hours(8)),
        todo("Z", **hours(80)),
    ]
    links = [("P", "M", "FS", 0), ("M", "S", "FS", 0)]
    return schedule(snap(tasks, links, sched=sched)).frame.loc["M"]


# --- the bound given by the successors is earlier than the Mandatory Finish ------------------------


@pytest.mark.parametrize("expected_finish", ["2026-03-04 17:00", "2026-03-03 17:00"])
def test_bound_before_the_mandatory_finish_caps_the_late_finish(expected_finish):
    """Bound Wed 4 Mar 17:00 (S Finish On or Before Thu 5 Mar 17:00, late start Thu 5 Mar 08:00),
    c = Fri 6 Mar 17:00: late finish = late start = min = Wed 4 Mar 17:00, with a equal to the
    bound and with a one day before it."""
    row = finish_milestone_row("2026-03-06 17:00", expected_finish, "2026-03-05 17:00")
    assert row["lf"] == T("2026-03-04 17:00")
    assert row["ls"] == T("2026-03-04 17:00")


# --- the bound given by the successors is later than the Mandatory Finish --------------------------


def test_bound_after_the_mandatory_finish_leaves_the_late_finish_at_it():
    """S Finish On or Before Fri 13 Mar 17:00 gives the bound Thu 12 Mar 17:00; c = Thu 5 Mar 17:00:
    min = c = Thu 5 Mar 17:00."""
    row = finish_milestone_row("2026-03-05 17:00", "2026-03-03 17:00", "2026-03-13 17:00")
    assert row["lf"] == T("2026-03-05 17:00")
    assert row["ls"] == T("2026-03-05 17:00")


# --- without an expected finish applied, the Mandatory Finish pins the late finish ------------------


def test_option_off_the_mandatory_finish_pins_the_late_finish():
    """Option off: a (Wed 4 Mar 17:00) is ignored, the bound is Wed 4 Mar 17:00, c = Fri 6 Mar
    17:00: the late finish is pinned at c = Fri 6 Mar 17:00."""
    row = finish_milestone_row("2026-03-06 17:00", "2026-03-04 17:00", "2026-03-05 17:00", OPTION_OFF)
    assert row["lf"] == T("2026-03-06 17:00")
    assert row["ls"] == T("2026-03-06 17:00")


def test_no_expected_finish_the_mandatory_finish_pins_the_late_finish():
    """Option on but M has no expected finish: bound Wed 4 Mar 17:00, c = Fri 6 Mar 17:00: the late
    finish is pinned at c = Fri 6 Mar 17:00."""
    row = finish_milestone_row("2026-03-06 17:00", "", "2026-03-05 17:00")
    assert row["lf"] == T("2026-03-06 17:00")
    assert row["ls"] == T("2026-03-06 17:00")


# --- boundary between the bound and the Mandatory Finish --------------------------------------------


@pytest.mark.parametrize(
    ("mandatory_finish", "expected_late_finish"),
    [
        pytest.param("2026-03-04 17:00", "2026-03-04 17:00", id="equal"),
        pytest.param("2026-03-05 09:00", "2026-03-04 17:00", id="one-working-hour-after-the-bound"),
        pytest.param("2026-03-04 16:00", "2026-03-04 16:00", id="one-working-hour-before-the-bound"),
    ],
)
def test_boundary_between_the_successor_bound_and_the_mandatory_finish(mandatory_finish, expected_late_finish):
    """Bound Wed 4 Mar 17:00 (S Finish On or Before Thu 5 Mar 17:00), a = Tue 3 Mar 17:00:
    late finish = min(bound, c), see the module docstring."""
    row = finish_milestone_row(mandatory_finish, "2026-03-03 17:00", "2026-03-05 17:00")
    assert row["lf"] == T(expected_late_finish)
    assert row["ls"] == T(expected_late_finish)
