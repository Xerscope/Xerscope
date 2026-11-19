"""A driving assignment without units per hour on resource-dependent work: how long it lasts (CPM engine).

Source of the rule: P6 Professional 23.12.1 on the pinned held-out corpus, where P6's import leaves
185 such assignments on unfinished resource-dependent work (p6-imported/*.json), e.g. H25-09 A1480
(P6 finishes it Sat 31 Oct 09:30; without the assignment the engine finished it Wed 28 Oct 14:30).
The public probes name the two rules ZW and ZU (folder zero-units, not fetched by this
repository). The project's reference, 26.8, is not measured.
Rule: remaining units / units per hour gives no duration without a rate. The assignment then lasts
the working time, on its own calendar, of its own remaining window (remaining start to remaining
finish; its planned dates when it has none). The window gives a duration, not dates: the work is
placed like any other. On work under way, its lag runs only for the part the time since the actual
start has not used up. The expected values below are hand calculations from that rule, not P6
readings.

Every case is a hand-made schedule, data date Monday 2026-03-02 08:00. T is resource dependent on
xerkit's calendar C8 = Mon-Fri 08:00-12:00 / 13:00-17:00, its resource on C10 = Mon-Fri 08:00-18:00.
"""

import pandas as pd
import pytest
from xerkit import active, hours, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

WINDOW = {"restart_date": "2026-03-02 08:00", "reend_date": "2026-03-04 12:00"}  # 10 + 10 + 4 = 24 h on C10


def frame_of(
    tasks: list[dict], links: list[tuple] = (), resource_calendar: str = "C10", **assignment_fields
) -> pd.DataFrame:
    """The schedule of ``tasks`` with one driving assignment on T, without units per hour unless given."""
    resources = [{"rsrc_id": "R1", "rsrc_short_name": "CREW", "rsrc_type": "RT_Labor", "clndr_id": resource_calendar}]
    assignment = {
        "task_code": "T", "rsrc_id": "R1", "target_qty": "0", "remain_qty": "0", "act_reg_qty": "0",
        "act_ot_qty": "0", "target_qty_per_hr": "0", "remain_qty_per_hr": "0",
        "target_lag_drtn_hr_cnt": "0", "relag_drtn_hr_cnt": "0", "rollup_dates_flag": "Y",
    } | assignment_fields  # fmt: skip
    return schedule(snap(tasks, links, resources=resources, assign=[assignment])).frame


def test_the_assignment_lasts_the_working_time_of_its_window():
    """Window Mon 2 Mar 08:00 to Wed 4 Mar 12:00 = 24 h on C10. From the data date: 10 h Monday,
    10 h Tuesday, 4 h Wednesday. T ends Wed 4 Mar 12:00, not Tue 3 Mar 17:00 (its own 16 h on C8)."""
    row = frame_of([todo("T", task_type="TT_Rsrc", **hours(16))], **WINDOW).loc["T"]
    assert (row["es"], row["ef"]) == (pd.Timestamp("2026-03-02 08:00"), pd.Timestamp("2026-03-04 12:00"))


def test_the_window_gives_a_duration_not_dates():
    """P (8 h) -> T: the logic starts T Tue 3 Mar 08:00, a day after its window opens. The 24 h run
    from there: Tuesday, Wednesday, 4 h Thursday. T ends Thu 5 Mar 12:00."""
    tasks = [todo("P", **hours(8)), todo("T", task_type="TT_Rsrc", **hours(16))]
    row = frame_of(tasks, [("P", "T", "FS", 0)], **WINDOW).loc["T"]
    assert (row["es"], row["ef"]) == (pd.Timestamp("2026-03-03 08:00"), pd.Timestamp("2026-03-05 12:00"))


def test_the_planned_dates_stand_in_for_a_missing_remaining_window():
    """No remaining dates on the assignment, planned Mon 2 Mar 08:00 to Wed 4 Mar 12:00: the same 24 h."""
    planned = {"target_start_date": "2026-03-02 08:00", "target_end_date": "2026-03-04 12:00"}
    row = frame_of([todo("T", task_type="TT_Rsrc", **hours(16))], **planned).loc["T"]
    assert row["ef"] == pd.Timestamp("2026-03-04 12:00")


def test_the_remaining_window_wins_over_the_planned_dates():
    """Remaining window of 24 h, planned dates of 10 h (Mon 2 Mar 08:00 to 18:00): the remaining one counts."""
    planned = {"target_start_date": "2026-03-02 08:00", "target_end_date": "2026-03-02 18:00"}
    row = frame_of([todo("T", task_type="TT_Rsrc", **hours(16))], **WINDOW, **planned).loc["T"]
    assert row["ef"] == pd.Timestamp("2026-03-04 12:00")


def test_a_resource_without_a_calendar_leaves_the_work_on_the_activity_calendar():
    """The resource names no calendar: the assignment has no duration, as before, and T runs its own
    16 h on C8, to Tue 3 Mar 17:00."""
    row = frame_of([todo("T", task_type="TT_Rsrc", **hours(16))], resource_calendar="", **WINDOW).loc["T"]
    assert row["ef"] == pd.Timestamp("2026-03-03 17:00")


def test_work_under_way_waits_only_for_the_lag_not_yet_used_up():
    """T started Mon 23 Feb 08:00; its assignment has a 100 h lag and a 10 h window. From the actual
    start to the data date the resource worked 5 days of 10 h: 50 h of the lag are used, 50 h remain.
    From Mon 2 Mar 08:00, 50 h on C10 end Fri 6 Mar 18:00: the assignment starts Mon 9 Mar 08:00 and
    its 10 h end Mon 9 Mar 18:00. With the whole lag it would end Mon 16 Mar 18:00."""
    window = {"restart_date": "2026-03-09 08:00", "reend_date": "2026-03-09 18:00", "relag_drtn_hr_cnt": "100"}
    row = frame_of([active("T", task_type="TT_Rsrc")], **window).loc["T"]
    assert row["ef"] == pd.Timestamp("2026-03-09 18:00")


def test_an_assignment_with_a_rate_keeps_its_units_over_its_rate():
    """8 units at 1 unit an hour: 8 h on C10 from the data date, whatever its window says. T ends Mon 2 Mar 16:00."""
    rated = {"remain_qty": "8", "target_qty": "8", "remain_qty_per_hr": "1", "target_qty_per_hr": "1"}
    row = frame_of([todo("T", task_type="TT_Rsrc", **hours(16))], **WINDOW, **rated).loc["T"]
    assert row["ef"] == pd.Timestamp("2026-03-02 16:00")


def test_task_dependent_work_ignores_an_assignment_without_a_rate():
    """T task dependent: its 16 h on C8 end Tue 3 Mar 17:00, the assignment's window changes nothing."""
    row = frame_of([todo("T", **hours(16))], **WINDOW).loc["T"]
    assert row["ef"] == pd.Timestamp("2026-03-03 17:00")
