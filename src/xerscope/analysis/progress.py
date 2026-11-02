"""Week-over-week progress: milestone trend (MTA), PPC and the progress delta.

MTA: for each milestone, its forecast date in every update. Plotted against the update
date, a flat line is a stable forecast, a rising one a slipping milestone; a completed
milestone meets the diagonal (forecast = reporting date) and its line ends there: later
updates only repeat the actual date below the diagonal (`plotted_trend`).

PPC (Percent Plan Complete, Last Planner): of the activities the W-1 update forecast to
finish before the W data date, the share that the W update shows complete. In a file P6
has recalculated no open activity finishes before its own data date, so these are the
activities forecast to finish during the week [W-1, W); an unscheduled file with stale
forecasts also counts its overdue work, which was due and is not done.

Progress delta ("actual W - actual W-1"): per activity, % complete and earned hours
gained during the week (budget hours of week W x change in % complete), rolled up by WBS.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..store import SnapshotStore
from ..xer import Snapshot

# --- milestone trend -----------------------------------------------------------------------


def milestone_codes(store: SnapshotStore, open_only: bool = False) -> list[str]:
    """Milestones present in any update, ordered by their latest forecast.

    `open_only` keeps those not complete in the last update that holds them.
    """
    history = store.history
    milestones = history[history["is_milestone"]].sort_values("snapshot_idx").groupby("task_code").last()
    if open_only:
        milestones = milestones[~milestones["is_complete"].astype(bool)]
    return milestones.sort_values("finish").index.tolist()


def milestone_trend(store: SnapshotStore, codes: list[str] | None = None) -> pd.DataFrame:
    history = store.history
    codes = milestone_codes(store) if codes is None else codes
    milestones = history[history["task_code"].isin(codes)].copy()
    # a start milestone's date is its start; anything else is tracked on its finish
    milestones["forecast"] = np.where(milestones["is_start_milestone"], milestones["start"], milestones["finish"])
    milestones["forecast"] = pd.to_datetime(milestones["forecast"])
    columns = ["snapshot_idx", "data_date", "task_code", "task_name", "forecast", "is_complete", "is_milestone"]
    return milestones[columns].sort_values(["task_code", "snapshot_idx"]).reset_index(drop=True)


def plotted_trend(trend: pd.DataFrame) -> pd.DataFrame:
    """MTA chart rows: each line stops at the first update that reports it complete.

    Later updates repeat the actual date below the diagonal and carry no trend; a line
    already complete in its first update has none in this series and is left out.
    Slippage (`milestone_slips`) still reads the full trend.
    """
    done = trend["is_complete"].astype(bool)
    done_before = done.groupby(trend["task_code"]).transform(lambda d: d.cumsum().shift(fill_value=0) > 0)
    done_at_start = done.groupby(trend["task_code"]).transform("first")
    return trend[~done_before & ~done_at_start].reset_index(drop=True)


def milestone_slips(trend: pd.DataFrame, store: SnapshotStore) -> pd.DataFrame:
    """First vs latest forecast per milestone, in working days of its own calendar (latest update)."""
    latest = store.latest
    calendar_ids = latest.by_code["clndr_id"]
    by_milestone = trend.groupby("task_code")
    slips = pd.DataFrame(
        {
            "task_name": by_milestone["task_name"].last(),
            "first_forecast": by_milestone["forecast"].first(),
            "latest_forecast": by_milestone["forecast"].last(),
            "complete": by_milestone["is_complete"].last(),
            "updates": by_milestone.size(),
        }
    )
    calendars = {code: latest.calendar(calendar_ids.get(code)) for code in slips.index}
    slips["slip_wd"] = [
        round(calendars[code].working_days(first, latest_forecast), 1)
        for code, first, latest_forecast in zip(
            slips.index, slips["first_forecast"], slips["latest_forecast"], strict=True
        )
    ]
    # the forecast one update before the latest (the first of each milestone's last two)
    last_two = trend.sort_values("snapshot_idx").groupby("task_code").tail(2).groupby("task_code")["forecast"]
    previous_forecast = last_two.first()
    slips["last_week_wd"] = [
        round(calendars[code].working_days(previous_forecast[code], slips.loc[code, "latest_forecast"]), 1)
        if code in previous_forecast.index
        else 0.0
        for code in slips.index
    ]
    return slips.reset_index().sort_values("latest_forecast")


# --- PPC --------------------------------------------------------------------------------------


def committed(previous: Snapshot, current: Snapshot, include_milestones: bool = True) -> pd.DataFrame:
    """Activities W-1 forecast to finish before W's data date, with their outcome in W."""
    open_work = previous.activities
    open_work = open_work[~open_work["is_complete"] & ~open_work["is_loe"]]
    if not include_milestones:
        open_work = open_work[~open_work["is_milestone"]]
    plan = open_work[open_work["finish"] < current.data_date][["task_code", "task_name", "wbs_code", "finish"]]
    now = current.by_code
    plan = plan.rename(columns={"finish": "planned_finish"})
    plan["in_update"] = plan["task_code"].isin(now.index)
    plan["completed"] = plan["task_code"].map(now["is_complete"]).fillna(False).astype(bool)
    plan["actual_finish"] = plan["task_code"].map(now["act_end_date"])
    plan["forecast_finish_now"] = plan["task_code"].map(now["finish"])
    plan["status_now"] = plan["task_code"].map(now["status"]).fillna("deleted")
    return plan.reset_index(drop=True)


def ppc_series(store: SnapshotStore, include_milestones: bool = True) -> pd.DataFrame:
    rows = []
    for index in range(1, len(store)):
        commitments = committed(store[index - 1], store[index], include_milestones)
        commitments = commitments[commitments["in_update"]]  # deleted activities are scope changes, not misses
        planned, done = len(commitments), int(commitments["completed"].sum())
        rows.append(
            {
                "snapshot_idx": index,
                "week_start": store[index - 1].data_date,
                "data_date": store[index].data_date,
                "committed": planned,
                "completed": done,
                "ppc": 100 * done / planned if planned else None,
            }
        )
    return pd.DataFrame(rows, columns=["snapshot_idx", "week_start", "data_date", "committed", "completed", "ppc"])


# --- progress delta --------------------------------------------------------------------------


def progress_delta(previous: Snapshot, current: Snapshot, baseline=None) -> pd.DataFrame:
    """Per activity: % complete W-1, W, change; earned labour hours this week.

    With a ``baseline``, earned hours are the week's EV gain, as on the Earned value page:
    BL hours x change in Performance % Complete (WBS EV technique), so the weekly figures
    add up to EV. Without, budget hours of W (of W-1 for an activity deleted in W) x change
    in % complete.
    """
    from .evm import performance_pct

    before = previous.by_code
    after = current.by_code
    columns = ["task_name", "wbs_code", "wbs_l1", "status", "labor_budget_hr", "labor_actual_hr"]
    # every activity of either update: one deleted since W-1 gives its earned hours back,
    # so the week's figures still add up to the change in EV
    codes = after.index.union(before.index, sort=False)
    delta = after[columns].reindex(codes)
    deleted = ~codes.isin(after.index)
    if deleted.any():
        delta.loc[deleted, columns] = before.loc[codes[deleted], columns].to_numpy()
        delta.loc[deleted, "status"] = "deleted"
    delta["pct_prev"] = before["pct_complete"].reindex(codes).fillna(0.0)
    delta["pct_now"] = after["pct_complete"].reindex(codes).fillna(0.0)
    delta["pct_delta"] = (delta["pct_now"] - delta["pct_prev"]).round(2)
    if baseline is None:
        delta["earned_hr_week"] = delta["labor_budget_hr"] * delta["pct_delta"] / 100
    else:
        baseline_hours = baseline.frame["ev_labor_hr"].reindex(codes).fillna(0.0)
        performance_now = performance_pct(current)["perf_pct"].reindex(codes).fillna(0.0)
        performance_before = performance_pct(previous)["perf_pct"].reindex(codes).fillna(0.0)
        delta["labor_budget_hr"] = baseline_hours  # the weights EV uses
        delta["earned_hr_week"] = baseline_hours * (performance_now - performance_before) / 100
    actual_now = after["labor_actual_hr"].reindex(codes).fillna(0.0)
    delta["actual_hr_week"] = actual_now - before["labor_actual_hr"].reindex(codes).fillna(0.0)
    delta["new"] = ~codes.isin(before.index)
    delta["deleted"] = deleted
    return delta.reset_index()


def rollup_delta(delta: pd.DataFrame, by: str = "wbs_l1") -> pd.DataFrame:
    """Earned hours and %-points gained per group, weighted by budget hours."""
    groups = delta.groupby(by, sort=False)
    progressed = (delta["pct_delta"] > 0).groupby(delta[by], sort=False).sum()
    out = pd.DataFrame(
        {
            "budget_hr": groups["labor_budget_hr"].sum(),
            "earned_hr_week": groups["earned_hr_week"].sum(),
            "actual_hr_week": groups["actual_hr_week"].sum(),
            "activities_progressed": progressed,
        }
    )
    out["progress_pts"] = np.where(out["budget_hr"] > 0, 100 * out["earned_hr_week"] / out["budget_hr"], np.nan)
    total = out.sum(numeric_only=True)
    total["progress_pts"] = 100 * total["earned_hr_week"] / total["budget_hr"] if total["budget_hr"] else np.nan
    out.loc["Project"] = total
    return out.reset_index().rename(columns={"index": by})


def finish_shift_since_first(store: SnapshotStore) -> float | None:
    """Working days (project calendar) the forecast finish moved since the first update; None if unknown."""
    first, latest = store.first.finish_date, store.latest.finish_date
    if len(store) < 2 or first is None or latest is None:
        return None
    return store.latest.calendar().working_days(first, latest)
