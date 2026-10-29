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


def _frame(a: pd.DataFrame, start: pd.Series, finish: pd.Series, ev_basis: str) -> pd.DataFrame:
    if ev_basis not in EV_BASES:
        raise ValueError(f"ev_basis must be one of {sorted(EV_BASES)}")
    planned = ev_basis == "budgeted_planned"
    # an activity without planned dates (some exporters) falls back to its current dates
    ev_start = a["target_start_date"].combine_first(start) if planned else start
    ev_finish = a["target_end_date"].combine_first(finish) if planned else finish
    at_completion = a["labor_actual_hr"].fillna(0.0) + a["labor_remaining_hr"].fillna(0.0)
    frame = pd.DataFrame(
        {
            "bl_start": start.values,
            "bl_finish": finish.values,
            "bl_labor_hr": a["labor_budget_hr"].values,
            "bl_duration_hr": a["target_drtn_hr_cnt"].values,
            "bl_clndr_id": a["clndr_id"].values,
            "bl_name": a["task_name"].values,
            "ev_start": ev_start.values,
            "ev_finish": ev_finish.values,
            "ev_labor_hr": (at_completion if ev_basis == "at_completion_current" else a["labor_budget_hr"]).values,
        },
        index=pd.Index(a["task_code"], name="task_code"),
    )
    return frame[~frame.index.duplicated()]


@dataclass
class Baseline:
    frame: pd.DataFrame  # index task_code, columns COLS
    label: str
    snapshot: Snapshot | None = None  # source file, for its calendars (PV spreading)
    ev_basis: str = DEFAULT_EV_BASIS

    @classmethod
    def from_snapshot(cls, bl: Snapshot, ev_basis: str = DEFAULT_EV_BASIS) -> Baseline:
        a = bl.activities
        return cls(_frame(a, a["start"], a["finish"], ev_basis), f"BL {bl.label}", bl, ev_basis)

    @classmethod
    def planned(cls, snap: Snapshot, ev_basis: str = DEFAULT_EV_BASIS) -> Baseline:
        a = snap.activities
        frame = _frame(a, a["target_start_date"], a["target_end_date"], ev_basis)
        return cls(frame, "planned dates (target_*)", snap, ev_basis)

    @property
    def bac_hours(self) -> float:
        """Budget at completion, labour hours, on the EV basis."""
        return float(self.frame["ev_labor_hr"].sum())
