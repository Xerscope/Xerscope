"""Week-over-week progress: milestone trend (MTA), PPC and the progress delta.

MTA: for each milestone, its forecast date in every update. Plotted against the update
date, a flat line is a stable forecast, a rising one a slipping milestone; a completed
milestone drops out of the updates whose data date is after its actual date: there it only
repeats that date below the diagonal (`plotted_trend`).

PPC (Percent Plan Complete): the commitments the W-1 update made for the week, kept in the
W update. A finish commitment is an open activity forecast to finish before the W data
date, kept when W shows it complete (Last Planner's PPC counts these only); a start
commitment is a not-started activity forecast to start before that date, kept when W shows
it started. PPC (Last Planner: complete / planned) = finishes kept / finishes committed;
PPC Start = starts kept / starts committed; PPC all = kept / committed over both kinds.
In a file P6 has recalculated no forecast
falls before its own data date, so these are the dates of the week [W-1, W); an
unscheduled file with stale forecasts also counts its overdue work, which was due and is
not done.

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
    """MTA chart rows: an update hides a milestone complete before its data date.

    Such a point only repeats the actual date below the diagonal: its forecast is blanked
    (NaT), the row kept, so the line breaks there instead of joining across the update.
    Every other update keeps the milestone: open, reopened, or complete on a date not
    before the data date (P6 would flag that actual as invalid; shown so it can be seen).
    Slippage (`milestone_slips`) still reads the full trend.
    """
    gone = trend["is_complete"].astype(bool) & (trend["forecast"] < trend["data_date"])
    return trend.assign(forecast=trend["forecast"].mask(gone))


def milestone_slips(trend: pd.DataFrame, store: SnapshotStore) -> pd.DataFrame:
    """First vs latest forecast per milestone, in working days of its own calendar (latest update)."""
    latest = store.latest
    calendar_ids = latest.by_code["clndr_id"]
    by_milestone = trend.groupby("task_code")
    slips = pd.DataFrame(
        {
            "task_name": by_milestone["task_name"].last(),
            "first_forecast": by_milestone["forecast"].first(),
            # the latest update's own forecast, missing included: not an earlier one carried over
            "latest_forecast": by_milestone["forecast"].last(skipna=False),
            "complete": by_milestone["is_complete"].last(),
            "updates": by_milestone.size(),
        }
    )
    slips["slip_wd"] = [
        round(latest.activity_working_days(calendar_ids.get(code), first, latest_forecast), 1)
        for code, first, latest_forecast in zip(
            slips.index, slips["first_forecast"], slips["latest_forecast"], strict=True
        )
    ]
    # the forecast one update before the latest (the first of each milestone's last two)
    last_two = trend.sort_values("snapshot_idx").groupby("task_code").tail(2).groupby("task_code")["forecast"]
    previous_forecast = last_two.first(skipna=False)
    slips["last_week_wd"] = [
        round(
            latest.activity_working_days(
                calendar_ids.get(code), previous_forecast[code], slips.loc[code, "latest_forecast"]
            ),
            1,
        )
        if code in previous_forecast.index
        else 0.0
        for code in slips.index
    ]
    return slips.reset_index().sort_values("latest_forecast")


# --- PPC --------------------------------------------------------------------------------------


def committed(previous: Snapshot, current: Snapshot) -> pd.DataFrame:
    """W-1's commitments for the week to W's data date, one row each, with their outcome in W.

    An activity due to start and finish within the week is two commitments. Milestones and
    level of effort are left out: a milestone repeats its predecessor's date, so it would
    add a commitment the week the predecessor ends."""
    work = previous.activities
    work = work[~work["is_milestone"] & ~work["is_loe"]]
    due, now = current.data_date, current.by_code
    finishes = work[~work["is_complete"] & (work["finish"] < due)]
    starts = work[~work["is_started"] & (work["start"] < due)]
    return pd.concat(
        [
            _outcome(finishes, now, "Finish", date="finish", actual="act_end_date", kept="is_complete"),
            _outcome(starts, now, "Start", date="start", actual="act_start_date", kept="is_started"),
        ],
        ignore_index=True,
    )


def _outcome(plan: pd.DataFrame, now: pd.DataFrame, commitment: str, date: str, actual: str, kept: str) -> pd.DataFrame:
    codes = plan["task_code"]
    return pd.DataFrame(
        {
            "task_code": codes,
            "task_name": plan["task_name"],
            "wbs_code": plan["wbs_code"],
            "commitment": commitment,
            "planned_date": plan[date],
            "in_update": codes.isin(now.index),
            "kept": codes.map(now[kept]).fillna(False).astype(bool),
            "actual_date": codes.map(now[actual]),
            "forecast_now": codes.map(now[date]),
            "status_now": codes.map(now["status"]).fillna("deleted"),
        }
    )


PPC_WEEK_DAYS = 7


def _gap_note(previous: Snapshot, current: Snapshot) -> str | None:
    """Note for a pair more than a week apart: an update is missing, so the point holds the
    commitments of every week between the two data dates. Calendar days: Monday 08:00 to the
    next Monday 17:00 is one week."""
    if previous.data_date is None or current.data_date is None:
        return None
    days = (current.data_date.normalize() - previous.data_date.normalize()).days
    if days <= PPC_WEEK_DAYS:
        return None
    return f"{days} days since the previous update: this point covers more than one week"


def ppc_series(store: SnapshotStore) -> pd.DataFrame:
    rows = []
    for index in range(1, len(store)):
        commitments = committed(store[index - 1], store[index])
        commitments = commitments[commitments["in_update"]]  # deleted activities are scope changes, not misses
        finishes = commitments[commitments["commitment"] == "Finish"]
        starts = commitments[commitments["commitment"] == "Start"]
        planned, kept = len(commitments), int(commitments["kept"].sum())
        finishes_kept, starts_kept = int(finishes["kept"].sum()), int(starts["kept"].sum())
        rows.append(
            {
                "snapshot_idx": index,
                "week_start": store[index - 1].data_date,
                "data_date": store[index].data_date,
                "finishes_committed": len(finishes),
                "finishes_kept": finishes_kept,
                "starts_committed": len(starts),
                "starts_kept": starts_kept,
                "committed": planned,
                "kept": kept,
                "ppc": _share(finishes_kept, len(finishes)),
                "ppc_start": _share(starts_kept, len(starts)),
                "ppc_all": _share(kept, planned),
                "note": _gap_note(store[index - 1], store[index]),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "snapshot_idx",
            "week_start",
            "data_date",
            "finishes_committed",
            "finishes_kept",
            "starts_committed",
            "starts_kept",
            "committed",
            "kept",
            "ppc",
            "ppc_start",
            "ppc_all",
            "note",
        ],
    )


def _share(kept: int, committed: int) -> float | None:
    """Percent kept, None when nothing was committed."""
    return 100 * kept / committed if committed else None


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
    return store.latest.project_working_days(first, latest)


def activity_finish_shift(store: SnapshotStore, history: pd.DataFrame) -> float | None:
    """Working days between an activity's first and last forecast finish, on its calendar in the
    last row of ``history`` (as the latest update defines it); None with one update or a missing finish."""
    if len(history) < 2 or history["finish"].isna().any():
        return None
    clndr_id = history["clndr_id"].iloc[-1]
    return store.latest.activity_working_days(
        clndr_id if isinstance(clndr_id, str) else None, history["finish"].iloc[0], history["finish"].iloc[-1]
    )
