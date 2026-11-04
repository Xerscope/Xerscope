"""P6 cost SPI: baseline budget cost per activity, planned value per assignment, earned value cost.

Every expected number is written by hand from the schedule built in the test (Oracle P6 Professional 26
help, glossary: Budget At Completion, Planned Value Cost, Earned Value Cost, Schedule Performance Index).
"""

import pandas as pd
import pytest
from xerkit import active, snap, todo

from xerscope.analysis import Baseline

MON = "2026-03-02 08:00"
FRI = "2026-03-06 17:00"
WEEK = dict(early_start_date=MON, early_end_date=FRI, target_drtn_hr_cnt="40", remain_drtn_hr_cnt="40")


def _assignment(code, cost, qty="100", **kw):
    return dict(task_code=code, rsrc_id="R1", rsrc_type="RT_Labor", target_qty=qty, target_cost=str(cost), **kw)


def _costed(**kw):
    """A: 100 h x 50 + 100 h x 100 + an expense of 1000; B: nonlabor 200 + material 300; C: no cost."""
    return snap(
        [todo("A", **WEEK), todo("B", **WEEK), todo("C", **WEEK)],
        assign=[
            _assignment("A", 5000),
            _assignment("A", 10000),
            dict(task_code="B", rsrc_id="R2", rsrc_type="RT_Equip", target_qty="4", target_cost="200"),
            dict(task_code="B", rsrc_id="R3", rsrc_type="RT_Mat", target_qty="10", target_cost="300"),
        ],
        costs=[dict(task_code="A", target_cost="1000")],
        **kw,
    )


def test_bl_cost_is_assignment_and_expense_target_cost_of_every_resource_type():
    frame = Baseline.from_snapshot(_costed()).frame
    assert frame["bl_cost"].to_dict() == {"A": 16000.0, "B": 500.0, "C": 0.0}


def test_bl_cost_is_zero_without_cost_data():
    frame = Baseline.from_snapshot(snap([todo("A", **WEEK)], rsrc=["A"])).frame
    assert frame["bl_cost"].to_dict() == {"A": 0.0}


def test_bl_cost_is_read_on_the_baseline_snapshot():
    baseline = Baseline.from_snapshot(_costed())
    assert Baseline.planned(_costed()).frame["bl_cost"].equals(baseline.frame["bl_cost"])
    assert baseline.frame["bl_cost"].sum() == 16500


def test_assignment_dates_come_from_the_activity_when_blank_and_from_the_assignment_otherwise():
    snapshot = snap(
        [todo("A", **WEEK)],
        assign=[
            _assignment("A", 100),
            _assignment("A", 300, target_start_date="2026-03-03 08:00", target_end_date="2026-03-04 17:00"),
        ],
    )
    costs = Baseline.from_snapshot(snapshot).assignment_costs
    assert costs["cost"].tolist() == [100, 300]
    assert costs["start"].tolist() == [pd.Timestamp(MON), pd.Timestamp("2026-03-03 08:00")]
    assert costs["finish"].tolist() == [pd.Timestamp(FRI), pd.Timestamp("2026-03-04 17:00")]
