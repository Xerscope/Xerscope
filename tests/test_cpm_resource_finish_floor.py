"""A finish floor on resource-dependent work moves it by its start (CPM engine).

Source of the rule: P6 Professional 23.12.1 on the public probes ZZ-CPP-QD1 and -RD1 to -RD3 (against
-QD4) and the held-out corpus (H28-09 A1220, H30-10 A1450). The project's reference, 26.8, is not
measured.
Rule: on resource-dependent work not started, with no expected finish in force, a Finish On or After,
a Finish On or a Mandatory Finish in the second slot gives a start: its date, at the activity
calendar's last close at or before it, less the activity's remaining duration. Where that start is
later than the work's own, the work is placed again from it, and its resources' calendars can finish
it after the date.
The expected values below are hand calculations from that rule, not P6 readings.

Data date Mon 2026-03-02 08:00. T on C8 = Mon-Fri 08:00-12:00 / 13:00-17:00, 8 h left; one assignment
of 8 h on a half-time resource of AM = Mon-Fri 08:00-12:00. From the data date it would run Mon and Tue
mornings, finishing Tue 12:00.
"""

import pandas as pd
import pytest
from xerkit import clndr_data, hours, labour_assignment, snap, todo

from xerscope.analysis.cpm import schedule

pytestmark = pytest.mark.oracle("p6")

MORNINGS = {"clndr_id": "AM", "clndr_name": "Mornings", "day_hr_cnt": "4", "clndr_type": "CA_Base",
            "clndr_data": clndr_data(range(2, 7), [("08:00", "12:00")])}  # fmt: skip
RESOURCES = [{"rsrc_id": "R1", "rsrc_short_name": "R1", "rsrc_type": "RT_Labor", "clndr_id": "AM"}]


def early_dates_of_t(**task_fields) -> tuple:
    task = todo("T", task_type="TT_Rsrc", **hours(8), **task_fields)
    snapshot = snap([task, todo("Z", **hours(80))], resources=RESOURCES, calendars=[MORNINGS],
                    assign=[labour_assignment("T", "R1", 8)])  # fmt: skip
    row = schedule(snapshot).frame.loc["T"]
    return row["es"], row["ef"]


def test_a_finish_on_or_after_moves_the_work_to_the_date_less_its_duration():
    """Finish On or After Wed 4 Mar 17:00: 8 h before on C8 is Wed 08:00, later than Mon 08:00. The work
    runs from there on its mornings, Wed and Thu: Wed 4 Mar 08:00 -> Thu 5 Mar 12:00, after the date."""
    dates = early_dates_of_t(cstr_type="CS_MEOA", cstr_date="2026-03-04 17:00")
    assert dates == (pd.Timestamp("2026-03-04 08:00"), pd.Timestamp("2026-03-05 12:00"))


def test_a_floor_before_the_works_start_moves_nothing():
    """Finish On or After Mon 2 Mar 17:00: 8 h before is Mon 08:00, not later than the work's start;
    it runs Mon 2 Mar 08:00 -> Tue 3 Mar 12:00 as from the data date."""
    dates = early_dates_of_t(cstr_type="CS_MEOA", cstr_date="2026-03-02 17:00")
    assert dates == (pd.Timestamp("2026-03-02 08:00"), pd.Timestamp("2026-03-03 12:00"))
