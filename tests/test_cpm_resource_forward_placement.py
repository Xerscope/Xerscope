"""Resource-dependent work placed forward: finish bound, assignments with no work, second placement.

Source of the rules: P6 Professional 23.12.1 on the public probes of the pinned corpus (folders of
rounds H8 to H27: ZZ-CPP-RD2F, -RDSF, -RSRC, -RDZA to -RDZD, -AVR, -RDU, -HLX, -KD) and the held-out
corpus (H8-11 A1040, H9-09 A1230, H10-04 A1040, H12-01 A1200, H13-06 A1230, H20-03 A1060, H23-12
A1230, H24-03 A1150, H24-10 A1160, H27-08 A1260). The project's reference, 26.8, is not measured.
Rules, as stated in the probes:
- a finish bound (FF, SF), off the activity calendar's working time, moves to its next opening; each
  assignment with work reaches it at its resource's last close at or before it; the earliest start so
  found, at the activity calendar's next opening, is the start; each assignment then starts where its
  resource first works at or after it;
- an assignment with no work left sits at its calendar's next opening at or after the start; a finish
  bound moves it, to its next opening after the bound, only when no assignment has work left;
- P6 places the work a second time from the activity calendar's next opening after the first
  placement's start: the dates shown and the float are that placement's, the successors follow the
  first.
The expected values below are hand calculations from those rules, not P6 readings.

Data date Monday 2026-03-02 08:00. Calendars written out: A = Mon-Fri 08:00-17:00 without a break;
R = Mon-Fri 12:00-18:00 (a resource that opens at noon); AM = Mon-Fri 08:00-12:00; PM = Mon-Fri
13:00-18:00; C10 = Mon-Fri 08:00-18:00.
"""

import pandas as pd
import pytest
from xerkit import clndr_data, hours, labour_assignment, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

CALENDARS = [
    {"clndr_id": "A", "clndr_name": "Mon-Fri 9h", "day_hr_cnt": "9", "clndr_type": "CA_Base",
     "clndr_data": clndr_data(range(2, 7), [("08:00", "17:00")])},
    {"clndr_id": "R", "clndr_name": "Mon-Fri noon 6h", "day_hr_cnt": "6", "clndr_type": "CA_Base",
     "clndr_data": clndr_data(range(2, 7), [("12:00", "18:00")])},
    {"clndr_id": "AM", "clndr_name": "Mon-Fri mornings", "day_hr_cnt": "4", "clndr_type": "CA_Base",
     "clndr_data": clndr_data(range(2, 7), [("08:00", "12:00")])},
    {"clndr_id": "PM", "clndr_name": "Mon-Fri afternoons", "day_hr_cnt": "5", "clndr_type": "CA_Base",
     "clndr_data": clndr_data(range(2, 7), [("13:00", "18:00")])},
]  # fmt: skip


def resource(rsrc_id: str, calendar: str) -> dict:
    return {"rsrc_id": rsrc_id, "rsrc_short_name": rsrc_id, "rsrc_type": "RT_Labor", "clndr_id": calendar}


def frame_of(tasks, links, resources, assignments):
    return schedule(snap(tasks, links, resources=resources, assign=assignments, calendars=CALENDARS)).frame


def test_the_work_starts_where_its_resource_first_works_after_the_start_a_finish_bound_sets():
    """T on A, 5.5 h of work on R; P (A, 36 h: Mon 08:00 -> Thu 17:00) finish-to-finish to T.
    The bound Thu 17:00 is working time of A; R reaches it at Thu 17:00 and works 5.5 h back: Thu
    12:00-17:00 (5 h), then Wed 17:30. On A that is the next opening, Thu 08:00, later than the data
    date: the start. R first works at or after it Thu 12:00: the work runs Thu 12:00-17:30. No working
    time of A separates Thu 17:30 from the bound: the finish stays Thu 17:30. The second placement,
    from A's opening at Thu 12:00, is the same. Early start Thu 12:00, early finish Thu 17:30."""
    tasks = [
        todo("P", clndr_id="A", **hours(36)),
        todo("T", clndr_id="A", task_type="TT_Rsrc", **hours(6)),
    ]
    frame = frame_of(tasks, [("P", "T", "FF", 0)], [resource("R1", "R")], [labour_assignment("T", "R1", 5.5)])
    assert (frame.at["T", "es"], frame.at["T", "ef"]) == (
        pd.Timestamp("2026-03-05 12:00"),
        pd.Timestamp("2026-03-05 17:30"),
    )


def test_an_assignment_with_no_work_moves_past_the_bound_when_none_has_work():
    """T on C10, one assignment with no work on C10; P (C10, 30 h: Mon 08:00 -> Wed 18:00) finish-to-
    finish to T. No assignment has work: the bound moves it to its calendar's next opening after Wed
    18:00, Thu 08:00, where it starts and finishes."""
    tasks = [todo("P", clndr_id="C10", **hours(30)), todo("T", clndr_id="C10", task_type="TT_Rsrc", **hours(0))]
    frame = frame_of(tasks, [("P", "T", "FF", 0)], [resource("R1", "C10")], [labour_assignment("T", "R1", 0)])
    assert (frame.at["T", "es"], frame.at["T", "ef"]) == (
        pd.Timestamp("2026-03-05 08:00"),
        pd.Timestamp("2026-03-05 08:00"),
    )


def test_an_assignment_with_no_work_beside_work_keeps_its_place():
    """As above, with a second assignment of 8 h on C10: it reaches the bound Wed 18:00 from Wed 10:00,
    the start. The assignment with no work sits at Wed 10:00, its calendar's opening at the start, and
    the finish is the working one's, Wed 18:00."""
    tasks = [todo("P", clndr_id="C10", **hours(30)), todo("T", clndr_id="C10", task_type="TT_Rsrc", **hours(8))]
    assignments = [labour_assignment("T", "R1", 0), labour_assignment("T", "R2", 8)]
    resources = [resource("R1", "C10"), resource("R2", "C10")]
    frame = frame_of(tasks, [("P", "T", "FF", 0)], resources, assignments)
    assert (frame.at["T", "es"], frame.at["T", "ef"]) == (
        pd.Timestamp("2026-03-04 10:00"),
        pd.Timestamp("2026-03-04 18:00"),
    )


def test_the_dates_shown_are_the_second_placement_and_the_successors_follow_the_first():
    """T on AM, 8 h on a resource of PM, from the data date Mon 08:00. The first placement: PM first
    works Mon 13:00, a time AM does not work; 5 h Monday, 3 h Tuesday: Mon 13:00 -> Tue 16:00. AM's next
    opening after Mon 13:00 is Tue 08:00: the second placement starts there, PM works from Tue 13:00,
    5 h Tuesday, 3 h Wednesday: Tue 13:00 -> Wed 16:00, the dates T shows. S (AM, 1 h, finish-to-start)
    follows the first finish, Tue 16:00: AM's next opening Wed 08:00, S runs Wed 08:00 -> 09:00."""
    tasks = [todo("T", clndr_id="AM", task_type="TT_Rsrc", **hours(8)), todo("S", clndr_id="AM", **hours(1))]
    frame = frame_of(tasks, [("T", "S", "FS", 0)], [resource("R1", "PM")], [labour_assignment("T", "R1", 8)])
    assert (frame.at["T", "es"], frame.at["T", "ef"]) == (
        pd.Timestamp("2026-03-03 13:00"),
        pd.Timestamp("2026-03-04 16:00"),
    )
    assert (frame.at["S", "es"], frame.at["S", "ef"]) == (
        pd.Timestamp("2026-03-04 08:00"),
        pd.Timestamp("2026-03-04 09:00"),
    )
