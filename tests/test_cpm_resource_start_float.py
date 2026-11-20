"""Start float of resource-dependent work: run to the late finish less its span (CPM engine).

Source of the rule: P6 Professional 23.12.1 on the public probes ZZ-CPP-RDTF T1-T11, -RDTR, -FA2 and
the held-out corpus (H9-01 A1280, H11-10 A1220, H20-05 A1040). The project's reference, 26.8, is not
measured.
Rule: on resource-dependent work under FT_Start, and on such work under way under Progress Override,
P6 runs start float to the late finish less the remaining span on the activity calendar, not to the
late start its assignments set: it equals finish float. Not under FT_SS, the code P6's dialog writes
for "Start Float"; under Retained Logic, work under way keeps its own late start.
The expected values below are hand calculations from that rule, not P6 readings.

Data date Mon 2026-03-02 08:00. T on C10 = Mon-Fri 08:00-18:00, under way since Fri 27 Feb, 8 h of
work left on a resource of SHORTFRI = Mon-Thu 08:00-12:00 / 13:00-17:00, Fri 08:00-10:00: it works
Mon 08:00-17:00. Z (C10, 50 h) ends the project Fri 6 Mar 18:00. Late: the resource's last close at
or before Fri 18:00 is Fri 10:00; 8 h back: Fri 2 h, Thu 13:00-17:00, Thu 10:00-12:00: late start Thu
10:00, late finish Fri 10:00. Finish float on C10: Mon 17:00 -> Fri 10:00 = 1 + 30 + 2 = 33 h; start
float to the assignments' late start: Mon 08:00 -> Thu 10:00 = 10 + 20 + 2 = 32 h.
"""

import pytest
from xerkit import active, hours, labour_assignment, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

RESOURCES = [{"rsrc_id": "R1", "rsrc_short_name": "R1", "rsrc_type": "RT_Labor", "clndr_id": "SHORTFRI"}]
DAY = "(0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())"
FRIDAY = "(0||0(s|08:00|f|10:00)())"
WEEK = "".join(f"(0||{day}()({DAY if day in (2, 3, 4, 5) else FRIDAY if day == 6 else ''}))" for day in range(1, 8))
SHORT_FRIDAY = {
    "clndr_id": "SHORTFRI", "clndr_name": "Short Friday", "day_hr_cnt": "8", "clndr_type": "CA_Base",
    "clndr_data": f"(0||CalendarData()((0||DaysOfWeek()({WEEK}))(0||Exceptions()())))",
}  # fmt: skip


def total_float_of_t(**sched) -> float:
    task = active("T", clndr_id="C10", task_type="TT_Rsrc", act_start_date="2026-02-27 08:00", remain_drtn_hr_cnt="9")
    snapshot = snap([task, todo("Z", clndr_id="C10", **hours(50))], sched=sched, resources=RESOURCES,
                    assign=[labour_assignment("T", "R1", 8)], calendars=[SHORT_FRIDAY])  # fmt: skip
    return schedule(snapshot).frame.at["T", "tf_hr"]


def test_under_progress_override_the_smallest_float_is_the_finish_float():
    """FT_Min under Progress Override: start float equals finish float, 33 h."""
    sched = {"sched_float_type": "FT_Min", "sched_retained_logic": "N", "sched_progress_override": "Y"}
    assert total_float_of_t(**sched) == 33


def test_under_retained_logic_work_under_way_keeps_its_own_late_start():
    """FT_Min under Retained Logic: the smaller of 33 h and 32 h, 32 h."""
    sched = {"sched_float_type": "FT_Min", "sched_retained_logic": "Y", "sched_progress_override": "N"}
    assert total_float_of_t(**sched) == 32


def test_under_ft_ss_start_float_runs_to_the_assignments_late_start():
    """FT_SS under Progress Override: start float to the assignments' late start, 32 h."""
    sched = {"sched_float_type": "FT_SS", "sched_retained_logic": "N", "sched_progress_override": "Y"}
    assert total_float_of_t(**sched) == 32


def test_work_not_started_under_progress_override_keeps_its_own_late_start():
    """The same work not started, 9 h left, under FT_Min and Progress Override (probe ZZ-CPP-RDTF T9;
    corpus H9-01 A1060): it runs Mon 08:00-17:00 as above, the smaller float is the start float, 32 h."""
    sched = {"sched_float_type": "FT_Min", "sched_retained_logic": "N", "sched_progress_override": "Y"}
    task = todo("T", clndr_id="C10", task_type="TT_Rsrc", **hours(9))
    snapshot = snap([task, todo("Z", clndr_id="C10", **hours(50))], sched=sched, resources=RESOURCES,
                    assign=[labour_assignment("T", "R1", 8)], calendars=[SHORT_FRIDAY])  # fmt: skip
    assert schedule(snapshot).frame.at["T", "tf_hr"] == 32
