"""Week-over-week progress: milestone trend (MTA), PPC and the progress delta.

MTA: for each milestone, its forecast date in every update. Plotted against the update
date, a flat line is a stable forecast, a rising one a slipping milestone; a completed
milestone meets the diagonal (forecast = reporting date).

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


def milestone_codes(store: SnapshotStore) -> list[str]:
    """Milestones present in any update, ordered by their latest forecast."""
    h = store.history
    ms = h[h["is_milestone"]].sort_values("snapshot_idx").groupby("task_code").last()
    return ms.sort_values("finish").index.tolist()


def milestone_trend(store: SnapshotStore, codes: list[str] | None = None) -> pd.DataFrame:
    h = store.history
    codes = milestone_codes(store) if codes is None else codes
    m = h[h["task_code"].isin(codes)].copy()
    # a start milestone's date is its start; anything else is tracked on its finish
    m["forecast"] = np.where(m["is_start_milestone"], m["start"], m["finish"])
    m["forecast"] = pd.to_datetime(m["forecast"])
    cols = ["snapshot_idx", "data_date", "task_code", "task_name", "forecast", "is_complete", "is_milestone"]
    return m[cols].sort_values(["task_code", "snapshot_idx"]).reset_index(drop=True)


def milestone_slips(trend: pd.DataFrame, store: SnapshotStore) -> pd.DataFrame:
    """First vs latest forecast per milestone, in working days of its own calendar (latest update)."""
    latest = store.latest
    cal_of = latest.activities.drop_duplicates("task_code").set_index("task_code")["clndr_id"]
    g = trend.groupby("task_code")
    out = pd.DataFrame(
        {
            "task_name": g["task_name"].last(),
            "first_forecast": g["forecast"].first(),
            "latest_forecast": g["forecast"].last(),
            "complete": g["is_complete"].last(),
            "updates": g.size(),
        }
    )
    cal = {c: latest.calendar(cal_of.get(c)) for c in out.index}
    out["slip_wd"] = [
        round(cal[c].working_days(a, b), 1)
        for c, a, b in zip(out.index, out["first_forecast"], out["latest_forecast"], strict=True)
    ]
    last2 = trend.sort_values("snapshot_idx").groupby("task_code").tail(2).groupby("task_code")["forecast"]
    prev = last2.first()
    out["last_week_wd"] = [
        round(cal[c].working_days(prev[c], out.loc[c, "latest_forecast"]), 1) if c in prev.index else 0.0
        for c in out.index
    ]
    return out.reset_index().sort_values("latest_forecast")


# --- PPC --------------------------------------------------------------------------------------


def committed(prev: Snapshot, cur: Snapshot, include_milestones: bool = True) -> pd.DataFrame:
    """Activities W-1 forecast to finish before W's data date, with their outcome in W."""
    p = prev.activities
    p = p[~p["is_complete"] & ~p["is_loe"]]
    if not include_milestones:
        p = p[~p["is_milestone"]]
    plan = p[p["finish"] < cur.data_date][["task_code", "task_name", "wbs_code", "finish"]]
    now = cur.activities.drop_duplicates("task_code").set_index("task_code")
    plan = plan.rename(columns={"finish": "planned_finish"})
    plan["in_update"] = plan["task_code"].isin(now.index)
    plan["completed"] = plan["task_code"].map(now["is_complete"]).fillna(False).astype(bool)
    plan["actual_finish"] = plan["task_code"].map(now["act_end_date"])
    plan["forecast_finish_now"] = plan["task_code"].map(now["finish"])
    plan["status_now"] = plan["task_code"].map(now["status"]).fillna("deleted")
    return plan.reset_index(drop=True)


def ppc_series(store: SnapshotStore, include_milestones: bool = True) -> pd.DataFrame:
    rows = []
    for i in range(1, len(store)):
        c = committed(store[i - 1], store[i], include_milestones)
        c = c[c["in_update"]]  # deleted activities are scope changes, not missed commitments
        n, done = len(c), int(c["completed"].sum())
        rows.append(
            {
                "snapshot_idx": i,
                "week_start": store[i - 1].data_date,
                "data_date": store[i].data_date,
                "committed": n,
                "completed": done,
                "ppc": 100 * done / n if n else None,
            }
        )
    return pd.DataFrame(rows, columns=["snapshot_idx", "week_start", "data_date", "committed", "completed", "ppc"])


# --- progress delta --------------------------------------------------------------------------


def progress_delta(prev: Snapshot, cur: Snapshot, baseline=None) -> pd.DataFrame:
    """Per activity: % complete W-1, W, change; earned labour hours this week.

    With a ``baseline``, earned hours are the week's EV gain, as on the Earned value page:
    BL hours x change in Performance % Complete (WBS EV technique), so the weekly figures
    add up to EV. Without, budget hours of W x change in % complete.
    """
    from .evm import performance_pct

    a = prev.activities.drop_duplicates("task_code").set_index("task_code")
    b = cur.activities.drop_duplicates("task_code").set_index("task_code")
    df = b[["task_name", "wbs_code", "wbs_l1", "status", "labor_budget_hr", "labor_actual_hr"]].copy()
    df["pct_prev"] = a["pct_complete"].reindex(df.index).fillna(0.0)
    df["pct_now"] = b["pct_complete"]
    df["pct_delta"] = (df["pct_now"] - df["pct_prev"]).round(2)
    if baseline is None:
        df["earned_hr_week"] = df["labor_budget_hr"] * df["pct_delta"] / 100
    else:
        bl_hr = baseline.frame["ev_labor_hr"].reindex(df.index).fillna(0.0)
        gain = performance_pct(cur)["perf_pct"].reindex(df.index).fillna(0.0) - performance_pct(prev)[
            "perf_pct"
        ].reindex(df.index).fillna(0.0)
        df["labor_budget_hr"] = bl_hr  # the weights EV uses
        df["earned_hr_week"] = bl_hr * gain / 100
    df["actual_hr_week"] = df["labor_actual_hr"] - a["labor_actual_hr"].reindex(df.index).fillna(0.0)
    df["new"] = ~df.index.isin(a.index)
    return df.reset_index()


def rollup_delta(delta: pd.DataFrame, by: str = "wbs_l1") -> pd.DataFrame:
    """Earned hours and %-points gained per group, weighted by budget hours."""
    g = delta.groupby(by, sort=False)
    out = pd.DataFrame(
        {
            "budget_hr": g["labor_budget_hr"].sum(),
            "earned_hr_week": g["earned_hr_week"].sum(),
            "actual_hr_week": g["actual_hr_week"].sum(),
            "activities_progressed": g["pct_delta"].apply(lambda s: int((s > 0).sum())),
        }
    )
    out["progress_pts"] = np.where(out["budget_hr"] > 0, 100 * out["earned_hr_week"] / out["budget_hr"], np.nan)
    total = out.sum(numeric_only=True)
    total["progress_pts"] = 100 * total["earned_hr_week"] / total["budget_hr"] if total["budget_hr"] else np.nan
    out.loc["Project"] = total
    return out.reset_index().rename(columns={"index": by})
