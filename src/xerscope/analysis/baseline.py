"""Baseline: the reference plan every weekly snapshot is measured against.

Normally a designated XER (the contract baseline, exported from P6), matched to each
snapshot by Activity ID. ``Baseline.planned`` instead uses the planned dates stored in
the snapshot itself (target_*), for files that carry no separate baseline.

Two sets of baseline dates, as in P6:

- ``bl_start`` / ``bl_finish``: the baseline's current Start / Finish (P6 "BL Project
  Start / Finish"), what variances and the schedule checks compare against;
- ``ev_start`` / ``ev_finish`` / ``ev_labor_hr``: what earned value spreads, set by P6's
  Admin Preferences > Earned Value > "When calculating earned value from a baseline use"
  (``EV_BASES``). Default: budgeted values with planned dates, P6's out-of-the-box setting.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..xer import Snapshot

COLS = ["bl_start", "bl_finish", "bl_labor_hr", "bl_duration_hr", "bl_clndr_id", "bl_name",
        "ev_start", "ev_finish", "ev_labor_hr"]  # fmt: skip
EV_BASES = {
    "budgeted_planned": "Budgeted values with planned dates",
    "budgeted_current": "Budgeted values with current dates",
    "at_completion_current": "At Completion values with current dates",
}
DEFAULT_EV_BASIS = "budgeted_planned"


def _frame(activities: pd.DataFrame, start: pd.Series, finish: pd.Series, ev_basis: str) -> pd.DataFrame:
    if ev_basis not in EV_BASES:
        raise ValueError(f"ev_basis must be one of {sorted(EV_BASES)}")
    planned = ev_basis == "budgeted_planned"
    # an activity without planned dates (some exporters) falls back to its current dates
    ev_start = activities["target_start_date"].combine_first(start) if planned else start
    ev_finish = activities["target_end_date"].combine_first(finish) if planned else finish
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


@dataclass
class Baseline:
    frame: pd.DataFrame  # index task_code, columns COLS
    label: str
    snapshot: Snapshot  # source file, for its calendars (PV spreading)
    ev_basis: str = DEFAULT_EV_BASIS
    is_planned: bool = False  # the planned dates (target_*) of the snapshot itself, no baseline file
    source: str = ""  # where it comes from, when the app chose it for an update (shown with every result)

    @classmethod
    def from_snapshot(cls, baseline_snapshot: Snapshot, ev_basis: str = DEFAULT_EV_BASIS) -> Baseline:
        activities = baseline_snapshot.activities
        frame = _frame(activities, activities["start"], activities["finish"], ev_basis)
        return cls(frame, f"BL {baseline_snapshot.label}", baseline_snapshot, ev_basis)

    @classmethod
    def planned(cls, snapshot: Snapshot, ev_basis: str = DEFAULT_EV_BASIS) -> Baseline:
        activities = snapshot.activities
        frame = _frame(activities, activities["target_start_date"], activities["target_end_date"], ev_basis)
        return cls(frame, f"planned dates (target_*) of {snapshot.label}", snapshot, ev_basis, is_planned=True)

    @property
    def bac_hours(self) -> float:
        """Budget at completion, labour hours, on the EV basis."""
        return float(self.frame["ev_labor_hr"].sum())
