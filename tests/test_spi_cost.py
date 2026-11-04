"""P6 cost SPI: baseline budget cost per activity, planned value per assignment, earned value cost.

Every expected number is written by hand from the schedule built in the test (Oracle P6 Professional 26
help, glossary: Budget At Completion, Planned Value Cost, Earned Value Cost, Schedule Performance Index).
"""

import pandas as pd
import pytest
from xerkit import active, snap, todo

from xerscope.analysis import Baseline, evm
from xerscope.analysis.evm import earned, ev_point, evm_series
from xerscope.store import SnapshotStore

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


# --- planned value, earned value and SPI in cost -----------------------------------------------

WED = "2026-03-04 08:00"  # two working days after Monday 08:00


def _update(*tasks, data_date=WED):
    return snap(list(tasks), data_date=data_date)


def test_cost_spi_with_two_activities_at_different_rates_and_an_expense():
    """BAC = 5000 + 10000 + 1000 + 500 = 16500. At Wednesday 08:00, 2 of 5 working days of the
    baseline week are elapsed (0.4): PV = 16500 x 0.4 = 6600. A is 50 % complete (remaining 20 of
    40 h): EV = 16000 x 0.5 = 8000, B and C have not started. SPI = 8000 / 6600."""
    baseline = Baseline.from_snapshot(_costed())
    update = _update(active("A", **{**WEEK, "remain_drtn_hr_cnt": "20"}), todo("B", **WEEK), todo("C", **WEEK))
    point = ev_point(update, baseline)
    assert (point.bac_cost, point.pv_cost, point.ev_cost) == pytest.approx((16500, 6600, 8000))
    assert point.spi_cost == pytest.approx(8000 / 6600)
    row = evm_series(SnapshotStore([update]), baseline).iloc[0]
    assert (row["bac_cost"], row["pv_cost"], row["ev_cost"]) == pytest.approx((16500, 6600, 8000))
    assert row["spi_cost"] == pytest.approx(80 / 66)


def test_planned_value_cost_is_the_sum_over_assignments_on_their_own_dates():
    """Activity Mon 03-02 to Mon 03-09 (6 working days). Assignment 1 (1000): Mon-Fri, 16 of 40 h elapsed
    at Wednesday 08:00 = 0.4 -> 400. Assignment 2 (3000): Tue-Mon, 8 of 40 h = 0.2 -> 600. PV = 1000,
    where the activity's own dates (2/6) would give 4000 / 3 = 1333. A is 25 % complete: EV = 1000."""
    long_week = {**WEEK, "early_end_date": "2026-03-09 17:00", "target_drtn_hr_cnt": "48"}
    baseline = Baseline.from_snapshot(
        snap(
            [todo("A", **long_week)],
            assign=[
                _assignment("A", 1000, target_start_date=MON, target_end_date=FRI),
                _assignment("A", 3000, target_start_date="2026-03-03 08:00", target_end_date="2026-03-09 17:00"),
            ],
        )
    )
    point = ev_point(_update(active("A", **{**long_week, "remain_drtn_hr_cnt": "36"})), baseline)
    assert (point.pv_cost, point.ev_cost, point.spi_cost) == pytest.approx((1000, 1000, 1.0))


def test_activity_without_resource_takes_the_activity_schedule_percent():
    """An expense only (800), no assignment: PV = BAC x Schedule % = 800 x 0.4 = 320. D has no cost: 0."""
    baseline = Baseline.from_snapshot(
        snap([todo("C", **WEEK), todo("D", **WEEK)], costs=[dict(task_code="C", target_cost="800")])
    )
    update = _update(todo("C", **WEEK), todo("D", **WEEK))
    point = ev_point(update, baseline)
    assert (point.bac_cost, point.pv_cost, point.ev_cost) == pytest.approx((800, 320, 0))
    costs = earned(update, baseline)[["bl_cost", "pv_cost", "ev_cost"]]
    assert costs.loc["C"].tolist() == pytest.approx([800, 320, 0]) and costs.loc["D"].tolist() == [0, 0, 0]


def test_no_cost_data_gives_no_cost_spi_and_leaves_the_hours_alone():
    baseline = Baseline.from_snapshot(snap([todo("A", **WEEK, target_work_qty="40")], rsrc=["A"]))
    update = _update(active("A", **{**WEEK, "target_work_qty": "40", "remain_drtn_hr_cnt": "20"}))
    point = ev_point(update, baseline)
    assert (point.bac_cost, point.pv_cost, point.ev_cost, point.spi_cost) == (0, 0, 0, None)
    assert (point.pv_hr, point.ev_hr, point.spi) == pytest.approx((16, 20, 1.25))
    assert pd.isna(evm_series(SnapshotStore([update]), baseline).iloc[0]["spi_cost"])


def test_planned_value_cost_before_the_baseline_start_is_zero():
    baseline = Baseline.from_snapshot(_costed())
    assert ev_point(_update(todo("A", **WEEK), data_date="2026-03-01 08:00"), baseline).spi_cost is None


def test_assignment_planned_value_follows_the_resource_calendar():
    """400 over Fri 03-06 to Mon 03-09 at Saturday 08:00. 7-day resource calendar: 8 of 32 h = 0.25 -> 100.
    The activity's Monday-Friday calendar would give 8 of 16 h = 0.5 -> 200."""
    dates = dict(early_start_date="2026-03-06 08:00", early_end_date="2026-03-09 17:00")
    baseline = Baseline.from_snapshot(
        snap(
            [todo("A", **dates)],
            assign=[_assignment("A", 400)],
            resources=[dict(rsrc_id="R1", rsrc_type="RT_Labor", clndr_id="C7D")],
        )
    )
    assert ev_point(_update(todo("A", **dates), data_date="2026-03-07 08:00"), baseline).pv_cost == pytest.approx(100)


def test_calendar_time_switch(monkeypatch):
    """700 over Mon 03-02 08:00 to Mon 03-09 08:00 at Wednesday 08:00: working time 2 of 5 days -> 280;
    calendar time 2 of 7 days -> 200."""
    dates = dict(early_start_date=MON, early_end_date="2026-03-09 08:00")
    baseline = Baseline.from_snapshot(snap([todo("A", **dates)], assign=[_assignment("A", 700)]))
    update = _update(todo("A", **dates))
    assert ev_point(update, baseline).pv_cost == pytest.approx(280)
    monkeypatch.setattr(evm, "PV_COST_WORKING_TIME", False)
    assert ev_point(update, baseline).pv_cost == pytest.approx(200)


def test_resource_curves_are_listed_as_not_modelled():
    baseline = Baseline.from_snapshot(
        snap([todo("A", **WEEK), todo("B", **WEEK)], assign=[_assignment("A", 100, curv_id="5"), _assignment("B", 100)])
    )
    assert ev_point(_update(todo("A", **WEEK), todo("B", **WEEK)), baseline).not_modelled_cost == ["A"]


def test_hours_columns_come_first_and_keep_their_keys():
    baseline = Baseline.from_snapshot(_costed())
    row = evm_series(SnapshotStore([_update(todo("A", **WEEK))]), baseline).iloc[0]
    assert list(row.index[-4:]) == ["bac_cost", "pv_cost", "ev_cost", "spi_cost"] and "spi" in row.index
