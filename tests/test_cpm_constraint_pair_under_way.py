"""Work under way with two constraints: when the late side drops both (CPM engine).

Source of the rule: P6 Professional 23.12.1 on the P6 probes of the pinned corpus. Folder
h1-situations (ZZ-CPP-H1S-P P7, P10, P14; ZZ-CPP-H1S-C and -O K10): when either constraint slot of
work under way holds a Start On or Before or a Mandatory Start, P6 applies neither constraint on the
late side, so a Finish On or Before beside it is dropped too; beside a Start On or After or a Start On
it still applies (P8, P9). Folder h27-causes (ZZ-CPP-KB1 to KB8): a Finish On or Before and a
Mandatory Finish on work under way, in either order, P6 applies neither (KB1-KB5); each alone (KB6,
KB7) and the pair on work not started (KB8) are as before. Held-out corpus: 65 tasks under way with
such a pair. The project's reference, 26.8, is not measured.
Rule: on work under way, a Start On or Before, a Mandatory Start or a Mandatory Finish in either slot
removes both constraints from the backward pass; the late dates come from the network.
The expected values below are hand calculations from that rule, not P6 readings.

Same schedule as test_cpm_mandatory_under_way: calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00, data
date Mon 2026-03-02 08:00. T started Mon 23 Feb 08:00, 40 h left: its work runs Mon 2 Mar 08:00 ->
Fri 6 Mar 17:00. T -> S (8 h, FS). Z (80 h, no link) ends Fri 13 Mar 17:00, the project finish.
Hand calculation:
- constraints dropped: late finish = what S allows, Thu 12 Mar 17:00; late start 40 h before =
  Fri 6 Mar 08:00; total float Fri 6 Mar 17:00 -> Thu 12 Mar 17:00 = 32 h.
- Finish On or Before Wed 4 Mar 17:00 kept: late finish Wed 4 Mar 17:00, late start Thu 26 Feb
  08:00, total float -16 h.
"""

import pandas as pd
import pytest
from xerkit import active, hours, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

FINISH_ON_OR_BEFORE = ("CS_MEOB", "2026-03-04 17:00")
NETWORK = (pd.Timestamp("2026-03-12 17:00"), pd.Timestamp("2026-03-06 08:00"), 32)
CAPPED = (pd.Timestamp("2026-03-04 17:00"), pd.Timestamp("2026-02-26 08:00"), -16)


def late_dates_of_t(task: dict) -> tuple:
    """Late finish, late start and total float in hours of ``task`` (code T) in T -> S, Z ending the project."""
    tasks = [task, todo("S", **hours(8)), todo("Z", **hours(80))]
    row = schedule(snap(tasks, [("T", "S", "FS", 0)])).frame.loc["T"]
    return row["lf"], row["ls"], row["tf_hr"]


def with_pair(first: tuple, second: tuple) -> dict:
    """T under way with ``first`` in the primary slot and ``second`` in the secondary slot."""
    return active("T", cstr_type=first[0], cstr_date=first[1], cstr_type2=second[0], cstr_date2=second[1])


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(("CS_MANDFIN", "2026-03-04 17:00"), FINISH_ON_OR_BEFORE, id="mandatory-finish-then-fob"),
        pytest.param(FINISH_ON_OR_BEFORE, ("CS_MANDFIN", "2026-03-04 17:00"), id="fob-then-mandatory-finish"),
        pytest.param(("CS_MANDSTART", "2026-02-23 08:00"), FINISH_ON_OR_BEFORE, id="mandatory-start-then-fob"),
        pytest.param(FINISH_ON_OR_BEFORE, ("CS_MANDSTART", "2026-02-23 08:00"), id="fob-then-mandatory-start"),
        pytest.param(("CS_MSOB", "2026-02-23 08:00"), FINISH_ON_OR_BEFORE, id="sob-then-fob"),
        pytest.param(FINISH_ON_OR_BEFORE, ("CS_MSOB", "2026-02-23 08:00"), id="fob-then-sob"),
    ],
)
def test_the_finish_on_or_before_is_dropped_too(first, second):
    """Late finish Thu 12 Mar 17:00, late start Fri 6 Mar 08:00, total float 32 h: the network's dates."""
    assert late_dates_of_t(with_pair(first, second)) == NETWORK


@pytest.mark.parametrize(
    "other",
    [
        pytest.param(("CS_MSOA", "2026-02-23 08:00"), id="start-on-or-after"),
        pytest.param(("CS_MSO", "2026-02-23 08:00"), id="start-on"),
    ],
)
def test_the_finish_on_or_before_holds_beside_other_start_constraints(other):
    """Probes P8, P9: late finish Wed 4 Mar 17:00, late start Thu 26 Feb 08:00, total float -16 h."""
    assert late_dates_of_t(with_pair(other, FINISH_ON_OR_BEFORE)) == CAPPED


def test_the_pair_on_work_not_started_still_caps():
    """Probe KB8: not started, 40 h, Finish On or Before Wed 4 Mar 17:00 then Mandatory Finish Wed 11 Mar
    17:00 (a Finish On in the second slot): late finish Wed 4 Mar 17:00, late start Thu 26 Feb 08:00."""
    task = todo(
        "T", cstr_type="CS_MEOB", cstr_date="2026-03-04 17:00", cstr_type2="CS_MANDFIN",
        cstr_date2="2026-03-11 17:00", **hours(40),
    )  # fmt: skip
    finish, start, _ = late_dates_of_t(task)
    assert (finish, start) == CAPPED[:2]
