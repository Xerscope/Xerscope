"""Work under way under a Mandatory Start or Mandatory Finish: its late dates (CPM engine).

Source of the rule: P6 Professional 23.12.1 on the P6 probes of the pinned corpus, folder
oc-edges-xc (projects ZZ-CPP-XCR, ZZ-CPP-XCO): U6, under way with a Mandatory Finish earlier than
its early finish, and U3, under way with a Mandatory Start, both get the late dates of the network
(late finish = what the successor allows, total float 88 h), not the constraint date. Held-out
corpus: 205 values. The project's reference, 26.8, is not measured.
Rule: once work has started, a mandatory date no longer pins its late dates; they come from its
successors and the project end. Work not started keeps the pin, and a Finish On or Before still
caps the late finish of work under way (probe U7). The expected values below are hand
calculations from that rule, not P6 readings.

Every case is a hand-made schedule on xerkit's calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00,
data date Monday 2026-03-02 08:00. T is tested: started Mon 23 Feb 08:00, 40 h left, so its
remaining work runs Mon 2 Mar 08:00 -> Fri 6 Mar 17:00. T -> S (8 h, FS, lag 0). Z (80 h, no link)
ends Fri 13 Mar 17:00, the project finish. Backward: S finishes at the latest Fri 13 Mar 17:00 and
starts Fri 13 Mar 08:00, so T may finish Thu 12 Mar 17:00 at the latest.
Hand calculation, one line per case:
- under way, Mandatory Finish Wed 4 Mar 17:00: late finish Thu 12 Mar 17:00, late start 40 h before
  = Fri 6 Mar 08:00, total float = Fri 6 Mar 17:00 to Thu 12 Mar 17:00 = 4 days = 32 h.
- under way, Mandatory Start Mon 23 Feb 08:00: the same three values.
- under way, Finish On or Before Wed 4 Mar 17:00: the cap holds. Late finish Wed 4 Mar 17:00, late
  start 40 h before = Thu 26 Feb 08:00, total float = Fri 6 Mar 17:00 back to Wed 4 Mar 17:00 = -16 h.
- not started, 40 h, Mandatory Finish Wed 11 Mar 17:00: pinned. Late finish Wed 11 Mar 17:00 though
  S would allow Thu 12 Mar 17:00; late start 40 h before = Thu 5 Mar 08:00.
"""

import pandas as pd
import pytest
from xerkit import active, hours, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")


def row_of_t(task: dict) -> pd.Series:
    """The schedule row of ``task`` (code T) in T -> S, with Z setting the project finish."""
    tasks = [task, todo("S", **hours(8)), todo("Z", **hours(80))]
    return schedule(snap(tasks, [("T", "S", "FS", 0)])).frame.loc["T"]


@pytest.mark.parametrize(
    ("constraint_type", "constraint_date"),
    [
        pytest.param("CS_MANDFIN", "2026-03-04 17:00", id="mandatory-finish"),
        pytest.param("CS_MANDSTART", "2026-02-23 08:00", id="mandatory-start"),
    ],
)
def test_work_under_way_takes_the_late_dates_of_the_network(constraint_type, constraint_date):
    """Late finish Thu 12 Mar 17:00 (what S allows), late start Fri 6 Mar 08:00, total float 32 h."""
    row = row_of_t(active("T", cstr_type=constraint_type, cstr_date=constraint_date))
    assert row["lf"] == pd.Timestamp("2026-03-12 17:00")
    assert row["ls"] == pd.Timestamp("2026-03-06 08:00")
    assert row["tf_hr"] == 32


def test_finish_on_or_before_still_caps_work_under_way():
    """Finish On or Before Wed 4 Mar 17:00: late finish there, late start Thu 26 Feb 08:00, float -16 h."""
    row = row_of_t(active("T", cstr_type="CS_MEOB", cstr_date="2026-03-04 17:00"))
    assert row["lf"] == pd.Timestamp("2026-03-04 17:00")
    assert row["ls"] == pd.Timestamp("2026-02-26 08:00")
    assert row["tf_hr"] == -16


def test_work_not_started_keeps_the_mandatory_finish_pin():
    """Not started, Mandatory Finish Wed 11 Mar 17:00: late finish pinned there, late start Thu 5 Mar 08:00."""
    row = row_of_t(todo("T", cstr_type="CS_MANDFIN", cstr_date="2026-03-11 17:00", **hours(40)))
    assert row["lf"] == pd.Timestamp("2026-03-11 17:00")
    assert row["ls"] == pd.Timestamp("2026-03-05 08:00")
