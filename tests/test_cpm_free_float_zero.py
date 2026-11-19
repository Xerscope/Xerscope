"""Free float P6 leaves at zero whatever the successors' early dates (CPM engine).

Source of the rule: P6 Professional 23.12.1 measured on the pinned held-out corpus and on its P6
probes; no Oracle page states it, and the project's reference, 26.8, is not measured.
- Work not started under a primary Mandatory Start or Mandatory Finish has no free float: 508
  values of 508 on the corpus (e.g. H25-11 A1110, H28-01 A1170), 76 of 76 on the probes (e.g.
  oc-edges-xc E14).
- With "Use Expected Finish Dates" on, an activity that carries an expected finish and is not as
  late as possible has no free float, whether or not the expected finish sets its duration: 707
  values of 707 on the corpus (e.g. H1-08 A1090, H29-12 A1290).
Elsewhere the free float is the working time, on the activity's calendar, from its early finish to
the earliest start its successors allow. The expected values below are hand calculations from
these rules, not P6 readings.

Every case is a hand-made schedule on xerkit's calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00,
data date Monday 2026-03-02 08:00. T (8 h) is tested; its successor S (8 h, FS, lag 0) carries a
Start On or After, so S's early start is that date.
Hand calculation, one line per case:
- Mandatory Finish Tue 3 Mar 17:00: T runs Tue 3 Mar 08:00 -> 17:00. S starts Thu 5 Mar 08:00. The
  gap is Wed 4 Mar, 8 h; the rule gives 0.
- Mandatory Start Tue 3 Mar 08:00: the same dates, the same gap; the rule gives 0.
- Start On or After Tue 3 Mar 08:00 (not mandatory): the same dates; free float = the gap = 8 h.
- T under way (8 h left from the data date: Mon 2 Mar 08:00 -> 17:00) under Mandatory Finish: the
  rule is for work not started. Free float = Tue 3 + Wed 4 Mar = 16 h.
- expected finish Tue 3 Mar 17:00 and a finish-to-finish predecessor Q (32 h, Mon 2 Mar 08:00 ->
  Thu 5 Mar 17:00): the FF bound is later than the expected finish, so T keeps its 8 h and runs
  Thu 5 Mar 08:00 -> 17:00. S starts Mon 9 Mar 08:00. The gap is Fri 6 Mar, 8 h; the rule gives 0.
  With the option off the expected finish is ignored: 8 h.
- expected finish Wed 4 Mar 17:00, no other bound: T runs Mon 2 Mar 08:00 -> Wed 4 Mar 17:00 (the
  expected finish sets the duration). S starts Mon 9 Mar 08:00; the rule gives 0.
"""

import pytest
from xerkit import active, hours, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

OPTION_ON = {"sched_use_expect_end_flag": "Y"}
OPTION_OFF = {"sched_use_expect_end_flag": "N"}


def free_float_of_t(task: dict, successor_start: str, predecessors: tuple = (), sched: dict = OPTION_ON) -> float:
    """Free float in hours of ``task`` (code T), whose FS successor S starts on or after ``successor_start``."""
    successor = todo("S", cstr_type="CS_MSOA", cstr_date=successor_start, **hours(8))
    tasks = [task, successor, *[todo(code, **hours(duration)) for code, duration, _ in predecessors]]
    links = [("T", "S", "FS", 0)] + [(code, "T", link_type, 0) for code, _, link_type in predecessors]
    return schedule(snap(tasks, links, sched=sched)).frame.at["T", "ff_hr"]


# --- work not started under a primary mandatory constraint ------------------------------------------


@pytest.mark.parametrize(
    ("constraint_type", "constraint_date"),
    [
        pytest.param("CS_MANDFIN", "2026-03-03 17:00", id="mandatory-finish"),
        pytest.param("CS_MANDSTART", "2026-03-03 08:00", id="mandatory-start"),
    ],
)
def test_unstarted_work_under_a_mandatory_constraint_has_no_free_float(constraint_type, constraint_date):
    """T runs Tue 3 Mar 08:00 -> 17:00, S starts Thu 5 Mar 08:00: the gap is 8 h, the free float 0."""
    task = todo("T", cstr_type=constraint_type, cstr_date=constraint_date, **hours(8))
    assert free_float_of_t(task, "2026-03-05 08:00") == 0


def test_a_constraint_that_is_not_mandatory_leaves_the_gap_as_free_float():
    """Start On or After Tue 3 Mar 08:00: the same dates as above, free float = Wed 4 Mar = 8 h."""
    task = todo("T", cstr_type="CS_MSOA", cstr_date="2026-03-03 08:00", **hours(8))
    assert free_float_of_t(task, "2026-03-05 08:00") == 8


def test_work_under_way_under_a_mandatory_finish_keeps_its_free_float():
    """T under way, 8 h left: Mon 2 Mar 08:00 -> 17:00. S starts Thu 5 Mar 08:00: Tue 3 + Wed 4 = 16 h."""
    task = active("T", cstr_type="CS_MANDFIN", cstr_date="2026-03-03 17:00", remain_drtn_hr_cnt="8")
    assert free_float_of_t(task, "2026-03-05 08:00") == 16


# --- an expected finish in force ---------------------------------------------------------------------


def test_expected_finish_that_does_not_set_the_duration_still_leaves_no_free_float():
    """Q (32 h, FF) ends Thu 5 Mar 17:00, later than the expected finish Tue 3 Mar 17:00: T keeps 8 h,
    Thu 5 Mar 08:00 -> 17:00. S starts Mon 9 Mar 08:00: the gap is Fri 6 Mar, 8 h, the free float 0."""
    task = todo("T", expect_end_date="2026-03-03 17:00", **hours(8))
    assert free_float_of_t(task, "2026-03-09 08:00", predecessors=(("Q", 32, "FF"),)) == 0


def test_option_off_the_expected_finish_gives_no_rule():
    """The same schedule with "Use Expected Finish Dates" off: free float = Fri 6 Mar = 8 h."""
    task = todo("T", expect_end_date="2026-03-03 17:00", **hours(8))
    assert free_float_of_t(task, "2026-03-09 08:00", predecessors=(("Q", 32, "FF"),), sched=OPTION_OFF) == 8


def test_expected_finish_that_sets_the_duration_leaves_no_free_float():
    """Expected finish Wed 4 Mar 17:00 sets T at Mon 2 Mar 08:00 -> Wed 4 Mar 17:00; S starts Mon 9
    Mar 08:00: free float 0, as before this rule was widened."""
    task = todo("T", expect_end_date="2026-03-04 17:00", **hours(8))
    assert free_float_of_t(task, "2026-03-09 08:00") == 0
