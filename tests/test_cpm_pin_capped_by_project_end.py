"""A mandatory date whose pin falls after the project's late finish (CPM engine).

Source of the rule: P6 Professional 23.12.1 on the public probes ZZ-CPP-MSNP and -MSNR (M1, M2, M4, M5,
M9 against M3, M6, M8) and the held-out corpus (H12-09 A1330, H28-12 A1200 and 140 values in all).
The project's reference, 26.8, is not measured.
Rule: the project's late finish (its Must Finish By, else its early finish) still caps a pinned late
date. Where the pin would put the late finish after it, P6 keeps the late finish the project gives and
the late start that much earlier, so the float goes negative; a pin before it holds.
The expected values below are hand calculations from that rule, not P6 readings.

Data date Mon 2026-03-02 08:00, calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00, Must Finish By Fri 13
Mar 00:00, which P6 reads as Thu 12 Mar 17:00 on C8.
"""

import pandas as pd
import pytest
from xerkit import hours, labour_assignment, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

MUST_FINISH_BY = {"plan_end_date": "2026-03-13 00:00"}


def row_of_t(**constraint) -> pd.Series:
    tasks = [todo("T", **hours(16), **constraint), todo("Z", **hours(8))]
    return schedule(snap(tasks, project=MUST_FINISH_BY)).frame.loc["T"]


def test_a_mandatory_start_pinned_after_the_project_finish_is_capped():
    """Mandatory Start Thu 12 Mar 08:00, 16 h: the pin finishes Fri 13 Mar 17:00, after Thu 12 Mar 17:00.
    Late finish Thu 12 Mar 17:00, late start 16 h before = Wed 11 Mar 08:00; total float = Fri 13 Mar
    17:00 back to Thu 12 Mar 17:00 = -8 h."""
    row = row_of_t(cstr_type="CS_MANDSTART", cstr_date="2026-03-12 08:00")
    assert (row["ls"], row["lf"], row["tf_hr"]) == (
        pd.Timestamp("2026-03-11 08:00"),
        pd.Timestamp("2026-03-12 17:00"),
        -8,
    )


def test_a_mandatory_finish_pinned_after_the_project_finish_is_capped():
    """Mandatory Finish Fri 13 Mar 17:00: late finish Thu 12 Mar 17:00, late start Wed 11 Mar 08:00."""
    row = row_of_t(cstr_type="CS_MANDFIN", cstr_date="2026-03-13 17:00")
    assert (row["ls"], row["lf"]) == (pd.Timestamp("2026-03-11 08:00"), pd.Timestamp("2026-03-12 17:00"))


def test_a_pin_before_the_project_finish_holds():
    """Mandatory Start Mon 9 Mar 08:00: the pin finishes Tue 10 Mar 17:00, before the cap: late start
    Mon 9 Mar 08:00, late finish Tue 10 Mar 17:00, as pinned."""
    row = row_of_t(cstr_type="CS_MANDSTART", cstr_date="2026-03-09 08:00")
    assert (row["ls"], row["lf"]) == (pd.Timestamp("2026-03-09 08:00"), pd.Timestamp("2026-03-10 17:00"))


def test_resource_dependent_work_pinned_after_the_project_finish_is_capped():
    """The first case on resource-dependent work, 16 h of work on a resource of C8: the pin's span is
    16 h, its finish Fri 13 Mar 17:00, capped at Thu 12 Mar 17:00; the assignment runs back 16 h from
    there: late start Wed 11 Mar 08:00."""
    resources = [{"rsrc_id": "R1", "rsrc_short_name": "R1", "rsrc_type": "RT_Labor", "clndr_id": "C8"}]
    task = todo("T", task_type="TT_Rsrc", cstr_type="CS_MANDSTART", cstr_date="2026-03-12 08:00", **hours(16))
    snapshot = snap([task, todo("Z", **hours(8))], project=MUST_FINISH_BY, resources=resources,
                    assign=[labour_assignment("T", "R1", 16)])  # fmt: skip
    row = schedule(snapshot).frame.loc["T"]
    assert (row["ls"], row["lf"]) == (pd.Timestamp("2026-03-11 08:00"), pd.Timestamp("2026-03-12 17:00"))
