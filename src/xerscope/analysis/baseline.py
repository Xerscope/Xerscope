"""Baseline: the reference plan every weekly snapshot is measured against.

Normally a designated XER (the contract baseline, exported from P6), matched to each
snapshot by Activity ID. ``Baseline.planned`` instead uses the planned dates stored in
the snapshot itself (target_*), for files that carry no separate baseline.

Two sets of baseline dates, as in P6:

- ``bl_start`` / ``bl_finish``: the baseline's current Start / Finish (P6 "BL Project
  Start / Finish"), what variances and the schedule checks compare against;
- ``bl_cost``: the budgeted cost of the activity (P6 "Budget At Completion" cost fields, Pro 26
  glossary): Σ ``TASKRSRC.target_cost`` of its assignments, every resource type, plus
  Σ ``PROJCOST.target_cost`` of its expenses. ``Baseline.assignment_costs`` keeps the assignments
  one by one with their dates, for the per-assignment planned value cost;
- ``ev_start`` / ``ev_finish`` / ``ev_labor_hr``: what earned value spreads, set by P6's
  Admin Preferences > Earned Value > "When calculating earned value from a baseline use"
  (``EV_BASES``). Default: budgeted values with planned dates, P6's out-of-the-box setting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..xer import Snapshot
from ..xer.model import to_number

COLS = ["bl_start", "bl_finish", "bl_labor_hr", "bl_duration_hr", "bl_clndr_id", "bl_name",
        "ev_start", "ev_finish", "ev_labor_hr", "bl_cost"]  # fmt: skip
EV_COLS = ["ev_start", "ev_finish", "ev_labor_hr"]  # set by the EV basis; no schedule check reads them
ASSIGNMENT_COST_COLS = ["task_code", "cost", "start", "finish", "clndr_id", "curve", "labor", "labor_hr"]
EV_BASES = {
    "budgeted_planned": "Budgeted values with planned dates",
    "budgeted_current": "Budgeted values with current dates",
    "at_completion_current": "At Completion values with current dates",
}
DEFAULT_EV_BASIS = "budgeted_planned"


def _frame(activities: pd.DataFrame, start: pd.Series, finish: pd.Series, ev_basis: str) -> pd.DataFrame:
    """``start`` / ``finish``: the baseline dates (bl_*). The EV dates are the planned dates (target_*) on
    the planned basis, else the activity's current Start / Finish (``activities`` ``start`` / ``finish``:
    actual, else remaining, else early)."""
    if ev_basis not in EV_BASES:
        raise ValueError(f"ev_basis must be one of {sorted(EV_BASES)}")
    planned = ev_basis == "budgeted_planned"
    # an activity without planned dates (some exporters) falls back to its baseline dates
    ev_start = activities["target_start_date"].combine_first(start) if planned else activities["start"]
    ev_finish = activities["target_end_date"].combine_first(finish) if planned else activities["finish"]
    at_completion = activities["labor_actual_hr"].fillna(0.0) + activities["labor_remaining_hr"].fillna(0.0)
    frame = pd.DataFrame(
        {
            "bl_start": start.values,
            "bl_finish": finish.values,
            "bl_labor_hr": activities["labor_budget_hr"].values,
            "bl_duration_hr": activities["target_drtn_hr_cnt"].values,
            "bl_clndr_id": activities["clndr_id"].values,
            "bl_name": activities["task_name"].values,
            "ev_start": ev_start.values,
            "ev_finish": ev_finish.values,
            "ev_labor_hr": (
                at_completion if ev_basis == "at_completion_current" else activities["labor_budget_hr"]
            ).values,
        },
        index=pd.Index(activities["task_code"], name="task_code"),
    )
    return frame[~frame.index.duplicated()]


def _with_costs(snapshot: Snapshot, frame: pd.DataFrame, current_dates: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``frame`` with ``bl_cost``, and the assignments of its activities with their cost and dates.

    Assignment dates follow the activity dates of the EV basis: planned dates (target_*) on
    the planned basis, else actual, then remaining, then target; a blank date takes the activity's.
    The calendar is the resource's, else the activity's. ``curve``: the assignment names a
    resource curve (``curv_id``), which is not modelled. ``labor`` / ``labor_hr``: the assignment is
    labour (labour resource or role, as ``xer.model._labor_hours``) and its ``target_qty``.
    """
    assignments = snapshot.assignments
    assignments = assignments[assignments["task_code"].isin(frame.index)]
    if assignments.empty:
        costs = pd.DataFrame(columns=ASSIGNMENT_COST_COLS)
    else:
        start, finish = assignments["target_start_date"], assignments["target_end_date"]
        if current_dates:
            start = assignments["act_start_date"].combine_first(assignments["restart_date"]).combine_first(start)
            finish = assignments["act_end_date"].combine_first(assignments["reend_date"]).combine_first(finish)
        own_calendar = assignments["rsrc_clndr_id"].where(assignments["rsrc_clndr_id"] != "")
        costs = pd.DataFrame(
            {
                "task_code": assignments["task_code"].values,
                "cost": assignments["target_cost"].fillna(0.0).values,
                "start": start.combine_first(assignments["task_code"].map(frame["ev_start"])).values,
                "finish": finish.combine_first(assignments["task_code"].map(frame["ev_finish"])).values,
                "clndr_id": own_calendar.combine_first(assignments["task_code"].map(frame["bl_clndr_id"])).values,
                "curve": (assignments["curv_id"].fillna("").astype(str).str.strip() != "").values,
                "labor": assignments["rsrc_type"].isin(("RT_Labor", "role", "")).values,
                "labor_hr": assignments["target_qty"].fillna(0.0).values,
            }
        )
    total = costs.groupby("task_code")["cost"].sum()
    expenses = snapshot.expenses
    if "target_cost" in expenses.columns:
        codes = expenses["task_id"].map(snapshot.tasks.drop_duplicates("task_id").set_index("task_id")["task_code"])
        total = total.add(to_number(expenses["target_cost"]).groupby(codes.values).sum(), fill_value=0.0)
    frame = frame.assign(bl_cost=total.reindex(frame.index).fillna(0.0))
    return frame, costs


@dataclass
class Baseline:
    frame: pd.DataFrame  # index task_code, columns COLS
    label: str
    snapshot: Snapshot  # source file, for its calendars (PV spreading)
    ev_basis: str = DEFAULT_EV_BASIS
    is_planned: bool = False  # the planned dates (target_*) of the snapshot itself, no baseline file
    source: str = ""  # where it comes from, when the app chose it for an update (shown with every result)
    assignment_costs: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=ASSIGNMENT_COST_COLS))

    @classmethod
    def from_snapshot(cls, baseline_snapshot: Snapshot, ev_basis: str = DEFAULT_EV_BASIS) -> Baseline:
        activities = baseline_snapshot.activities
        frame = _frame(activities, activities["start"], activities["finish"], ev_basis)
        frame, costs = _with_costs(baseline_snapshot, frame, current_dates=ev_basis != "budgeted_planned")
        return cls(frame, f"BL {baseline_snapshot.label}", baseline_snapshot, ev_basis, assignment_costs=costs)

    @classmethod
    def planned(cls, snapshot: Snapshot, ev_basis: str = DEFAULT_EV_BASIS) -> Baseline:
        activities = snapshot.activities
        frame = _frame(activities, activities["target_start_date"], activities["target_end_date"], ev_basis)
        frame, costs = _with_costs(snapshot, frame, current_dates=ev_basis != "budgeted_planned")
        return cls(
            frame, f"planned dates (target_*) of {snapshot.label}", snapshot, ev_basis, is_planned=True,
            assignment_costs=costs,
        )  # fmt: skip

    @property
    def bac_hours(self) -> float:
        """Budget at completion, labour hours, on the EV basis."""
        return float(self.frame["ev_labor_hr"].sum())

    @property
    def bac_cost(self) -> float:
        """Budget at completion, cost: Σ bl_cost."""
        return float(self.frame["bl_cost"].sum())
