"""Resource-dependent work not started under a primary Mandatory Finish: its early dates (CPM engine).

Source of the rule: P6 Professional 23.12.1 on the pinned corpus. Probes xf-mandatory, rule MR
("resource dependent work not yet started takes the mandatory pin, as a task does, on the
activity's calendar, its assignments running on from it": ZZ-CPP-XMN M10, ZZ-CPP-XNR R1 to R3,
ZZ-CPP-XQR Q1 to Q4). Held-out corpus: H28-04 A1100 (Mandatory Finish Sat 25 Jul 18:00; P6 starts
it Mon 20 Jul 07:00 and finishes it Fri 24 Jul 07:30, before the date). The project's reference,
26.8, is not measured.
Rule: the date, less the activity's remaining duration on the activity's calendar, gives the
start; the driving assignments then run forward from that start on their own calendars, and the
early finish is theirs. On a resource that works longer days than the activity, the work ends
before the date. The expected values below are hand calculations from that rule, not P6 readings.

Every case is a hand-made schedule, data date Monday 2026-03-02 08:00. T is resource dependent on
xerkit's calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00, 24 h left, Mandatory Finish Fri 6 Mar
17:00. One driving assignment: 24 units at 1 unit an hour, 24 h of work on the resource's calendar.
The pin's start: Fri 6 Mar 17:00 less 24 h on C8 = Wed 4 Mar 08:00.
"""

import pandas as pd
import pytest
from xerkit import hours, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")


def row_of_t(resource_calendar: str, units: str = "24", **task_fields) -> pd.Series:
    """The schedule row of T, ``units`` hours of work on a resource of ``resource_calendar``; Z ends the
    project Fri 13 Mar."""
    resources = [{"rsrc_id": "R1", "rsrc_short_name": "CREW", "rsrc_type": "RT_Labor", "clndr_id": resource_calendar}]
    assignment = {
        "task_code": "T", "rsrc_id": "R1", "target_qty": units, "remain_qty": units, "act_reg_qty": "0",
        "act_ot_qty": "0", "target_qty_per_hr": "1", "remain_qty_per_hr": "1",
        "target_lag_drtn_hr_cnt": "0", "relag_drtn_hr_cnt": "0", "rollup_dates_flag": "Y",
    }  # fmt: skip
    task = todo("T", cstr_type="CS_MANDFIN", cstr_date="2026-03-06 17:00", **hours(24), **task_fields)
    tasks = [task, todo("Z", **hours(80))]
    return schedule(snap(tasks, resources=resources, assign=[assignment])).frame.loc["T"]


def test_the_assignments_run_forward_from_the_pinned_start_and_end_before_the_date():
    """Resource on C10 = Mon-Fri 08:00-18:00. From Wed 4 Mar 08:00: 10 h Wednesday, 10 h Thursday,
    4 h Friday: the work ends Fri 6 Mar 12:00, five hours of the resource's day before the date."""
    row = row_of_t("C10", task_type="TT_Rsrc")
    assert (row["es"], row["ef"]) == (pd.Timestamp("2026-03-04 08:00"), pd.Timestamp("2026-03-06 12:00"))


def test_the_late_dates_stay_pinned_and_the_float_is_what_the_resource_gains():
    """The late finish is the date, Fri 6 Mar 17:00; the assignment runs back from it on C10: 9 h
    Friday, 10 h Thursday, 5 h Wednesday, late start Wed 4 Mar 13:00. Total float = Fri 6 Mar 12:00
    to 17:00 on the activity calendar, less its lunch hour = 4 h."""
    row = row_of_t("C10", task_type="TT_Rsrc")
    assert (row["ls"], row["lf"]) == (pd.Timestamp("2026-03-04 13:00"), pd.Timestamp("2026-03-06 17:00"))
    assert row["tf_hr"] == 4


def test_a_resource_on_the_activity_calendar_ends_at_the_date():
    """Resource on C8, the activity's own calendar: 24 h from Wed 4 Mar 08:00 end Fri 6 Mar 17:00, the date."""
    row = row_of_t("C8", task_type="TT_Rsrc")
    assert (row["es"], row["ef"]) == (pd.Timestamp("2026-03-04 08:00"), pd.Timestamp("2026-03-06 17:00"))


def test_task_dependent_work_keeps_its_finish_at_the_date():
    """The same activity task dependent, its assignment holding 12 h of work only: an assignment sets
    no date of task-dependent work, the 24 h of the activity end at the date."""
    row = row_of_t("C10", units="12")
    assert (row["es"], row["ef"]) == (pd.Timestamp("2026-03-04 08:00"), pd.Timestamp("2026-03-06 17:00"))
