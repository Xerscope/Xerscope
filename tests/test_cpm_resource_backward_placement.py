"""Resource-dependent work placed back, slid "as late as possible", pinned by a Mandatory Start.

Source of the rules: P6 Professional 23.12.1 on the public probes of the pinned corpus (ZZ-CPP-RDSF,
-RD2S, -ZRA, -AFF, -QF1, -LC1, -MM1, -XNR) and the held-out corpus (H9-08 A1050, H12-11 A1160,
H23-02 A1220, H28-12 A1080, H29-05 A1710). The project's reference, 26.8, is not measured.
Rules, as stated in the probes:
- with two or more assignments under a start bound, the latest finish any of them reaches, at the
  activity calendar's last close at or before it, is the late finish; all run back from it;
- As Late As Possible work holds no free float, even where its slide stops short of its successors;
- As Late As Possible work with no work left runs forward from its bound, at the activity calendar's
  next opening;
- a Mandatory Start on resource-dependent work pins a late finish: the date's opening plus the span,
  on the activity calendar, of the work placed forward from the date on its resources' calendars;
  the assignments run back from it.
The expected values below are hand calculations from those rules, not P6 readings.

Data date Monday 2026-03-02 08:00. C8 = Mon-Fri 08:00-12:00 / 13:00-17:00; C10 = Mon-Fri 08:00-18:00.
"""

import pandas as pd
import pytest
from xerkit import hours, labour_assignment, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")


def resource(rsrc_id: str, calendar: str) -> dict:
    return {"rsrc_id": rsrc_id, "rsrc_short_name": rsrc_id, "rsrc_type": "RT_Labor", "clndr_id": calendar}


def frame_of(tasks, links=(), resources=(), assignments=()):
    return schedule(snap(tasks, links, resources=list(resources), assign=list(assignments))).frame


def test_a_mandatory_start_pins_the_span_of_the_work_on_its_resources():
    """T on C8, 16 h left, 20 h of work on a resource of C10, Mandatory Start Wed 4 Mar 08:00; Z (C8, 80 h)
    ends the project Fri 13 Mar 17:00. Forward from the date on C10: Wed 10 h, Thu 10 h: Thu 18:00, a
    span on C8 of Wed 08:00 to Thu 17:00 = 16 h. The pin's late finish: Wed 08:00 + 16 h on C8 = Thu
    17:00. The assignment runs back 20 h on C10 from its last close at or before it, Thu 17:00: Thu
    9 h, Wed 10 h, Tue 1 h: late start Tue 17:00."""
    task = todo("T", task_type="TT_Rsrc", cstr_type="CS_MANDSTART", cstr_date="2026-03-04 08:00", **hours(16))
    frame = frame_of([task, todo("Z", **hours(80))], resources=[resource("R1", "C10")],
                     assignments=[labour_assignment("T", "R1", 20)])  # fmt: skip
    assert (frame.at["T", "ls"], frame.at["T", "lf"]) == (
        pd.Timestamp("2026-03-03 17:00"),
        pd.Timestamp("2026-03-05 17:00"),
    )


def test_as_late_as_possible_work_holds_no_free_float():
    """T on C8, 8 h of work on a resource of C10, As Late As Possible, finish-to-start to S (C8, 8 h)
    that another predecessor P (C8, 40 h) holds to Mon 9 Mar 08:00. T slides back from Fri 6 Mar 17:00:
    C10 runs 8 h back from 17:00, Fri 09:00. Whatever is left between its finish and S, its free float
    is 0."""
    tasks = [
        todo("T", task_type="TT_Rsrc", cstr_type="CS_ALAP", **hours(8)),
        todo("P", **hours(40)),
        todo("S", **hours(8)),
    ]
    links = [("T", "S", "FS", 0), ("P", "S", "FS", 0)]
    frame = frame_of(tasks, links, [resource("R1", "C10")], [labour_assignment("T", "R1", 8)])
    assert frame.at["T", "ef"] == pd.Timestamp("2026-03-06 17:00")
    assert frame.at["T", "ff_hr"] == 0


def test_as_late_as_possible_work_with_no_work_left_sits_at_the_next_opening_after_its_bound():
    """T on C8, one assignment with no work, As Late As Possible, finish-to-start to S, held to Mon 9 Mar
    08:00 by P (C8, 40 h, Mon 2 Mar -> Fri 6 Mar 17:00). The bound is S's start, Mon 9 Mar 08:00; T runs
    forward from the activity calendar's opening there and sits at Mon 9 Mar 08:00."""
    tasks = [
        todo("T", task_type="TT_Rsrc", cstr_type="CS_ALAP", **hours(0)),
        todo("P", **hours(40)),
        todo("S", **hours(8)),
    ]
    links = [("T", "S", "FS", 0), ("P", "S", "FS", 0)]
    frame = frame_of(tasks, links, [resource("R1", "C8")], [labour_assignment("T", "R1", 0)])
    assert (frame.at["T", "es"], frame.at["T", "ef"]) == (
        pd.Timestamp("2026-03-09 08:00"),
        pd.Timestamp("2026-03-09 08:00"),
    )


def test_a_lag_with_no_work_gives_the_earlier_of_the_bound_and_its_lag_back_from_the_finish():
    """T (C8, Mandatory Start Wed 4 Mar 08:00, no work) holds one assignment on a resource of C10 with
    0 units and a lag of 4.5 h; Z (C8, 80 h) ends the project. The bound, Wed 08:00, binds. The assignment
    starts a lag after it, Wed 08:00 + 4.5 h on C10 = Wed 12:30; its finish is the last working time of C8
    at or before that, Wed 12:00 (C8 is closed 12:00-13:00). Back from Wed 12:00 on C10 by the 4.5 h lag:
    Wed 08:00-12:00 is 4 h, 0.5 h more is Tue 17:30. The late start is the earlier of the bound and that,
    Tue 17:30; the late finish Wed 12:00 (rule of resource_placement.lag_only_at_bound, probes ZZ-CPP-ZLA,
    -ZBS)."""
    lagged = {**labour_assignment("T", "R1", 0), "target_lag_drtn_hr_cnt": "4.5", "relag_drtn_hr_cnt": "4.5"}
    task = todo("T", task_type="TT_Rsrc", cstr_type="CS_MSO", cstr_date="2026-03-04 08:00", clndr_id="C8", **hours(0))
    frame = frame_of([task, todo("Z", **hours(80))], resources=[resource("R1", "C10")], assignments=[lagged])
    assert (frame.at["T", "ls"], frame.at["T", "lf"]) == (
        pd.Timestamp("2026-03-03 17:30"),
        pd.Timestamp("2026-03-04 12:00"),
    )
