"""Week-over-week progress: milestone trend (MTA), PPC and the progress delta.

MTA: for each milestone, its forecast date in every update. Plotted against the update
date, a flat line is a stable forecast, a rising one a slipping milestone; a completed
milestone drops out of the updates whose data date is after its actual date: there it only
repeats that date below the diagonal (`plotted_trend`).

PPC (Percent Plan Complete): the commitments the W-1 update made for the week, kept in the
W update. A start commitment is an activity not started in W-1 whose W-1 start is on or
before W's data date, kept when W gives it an actual start on or before that data date; a
finish commitment is the same for an activity not complete in W-1, its finish and its
actual finish. PPC Start = starts kept / starts committed; PPC Finish = finishes kept /
finishes committed (Last Planner's PPC counts these only); PPC W/W-1 = (starts + finishes
kept) / (starts + finishes committed). No commitment: none, not 0. In a file P6 has
recalculated no forecast falls before its own data date, so these are the dates of the
week [W-1, W]; an unscheduled file with stale forecasts also counts its overdue work,
which was due and is not done.

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

    `open_only` keeps those in the latest update and not complete there (a deleted milestone
    is not open).
    """
    history = store.history
    milestones = history[history["is_milestone"]].sort_values("snapshot_idx").groupby("task_code").last()
    if open_only:
        in_latest = milestones.index.isin(store.latest.by_code.index)
        milestones = milestones[in_latest & ~milestones["is_complete"].astype(bool)]
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
    """First vs latest forecast per milestone, in working days of its own calendar (latest update).

    ``deleted``: not in the latest update (the changelog's Scope / deleted); its last move is
    blank, the latest update having none for it."""
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
    slips["deleted"] = ~slips.index.isin(latest.by_code.index)
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
    slips["last_week_wd"] = slips["last_week_wd"].mask(slips["deleted"])
    return slips.reset_index().sort_values("latest_forecast")


# --- PPC --------------------------------------------------------------------------------------


def committed(previous: Snapshot, current: Snapshot, include_overdue: bool = True) -> pd.DataFrame:
    """W-1's commitments for the week to W's data date, one row each, with their outcome in W.

    Committed: W-1's start (finish) on or before W's data date, the activity not started
    (not complete) in W-1. Kept: W's actual start (finish) on or before W's data date; an
    actual after it (P6 flags it as invalid progress) is a miss, and so is a started /
    complete status without the actual date. An actual entered late (before W-1's data date
    although W-1 showed the activity not started) still keeps it. An activity due to start
    and finish within the week is two commitments. Milestones (`committed_milestones`) and
    level of effort are left out: a milestone repeats its predecessor's date, so it would add
    a commitment the week the predecessor ends. ``include_overdue=False`` keeps only the
    dates after W-1's data date: work already late at W-1 is not this week's commitment.
    Without a W data date nothing is due: no commitment (`ppc_series` notes it)."""
    work = previous.activities
    work = work[~work["is_milestone"] & ~work["is_loe"]]
    finishes, starts = _due(work, previous, current, include_overdue)
    return _commitments(finishes, starts, current)


def committed_milestones(previous: Snapshot, current: Snapshot, include_overdue: bool = True) -> pd.DataFrame:
    """Milestone commitments, read as `committed` reads tasks, listed apart and out of the PPC
    counts: a start milestone commits its start, a finish milestone its finish."""
    work = previous.activities
    work = work[work["is_milestone"]]
    finishes, starts = _due(work, previous, current, include_overdue)
    return _commitments(finishes[~finishes["is_start_milestone"]], starts[starts["is_start_milestone"]], current)


def _due(
    work: pd.DataFrame, previous: Snapshot, current: Snapshot, include_overdue: bool
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rows of ``work`` due to finish, and due to start, by W's data date."""
    due = current.data_date
    if due is None:
        return work.iloc[0:0], work.iloc[0:0]
    finishes = work[~work["is_complete"] & (work["finish"] <= due)]
    starts = work[~work["is_started"] & (work["start"] <= due)]
    if not include_overdue and previous.data_date is not None:
        finishes = finishes[finishes["finish"] > previous.data_date]
        starts = starts[starts["start"] > previous.data_date]
    return finishes, starts


def _commitments(finishes: pd.DataFrame, starts: pd.DataFrame, current: Snapshot) -> pd.DataFrame:
    due, now = current.data_date, current.by_code
    return pd.concat(
        [
            _outcome(finishes, now, due, "Finish", date="finish", actual="act_end_date", done="is_complete"),
            _outcome(starts, now, due, "Start", date="start", actual="act_start_date", done="is_started"),
        ],
        ignore_index=True,
    )


def _outcome(
    plan: pd.DataFrame, now: pd.DataFrame, due: pd.Timestamp | None, commitment: str, date: str, actual: str, done: str
) -> pd.DataFrame:
    codes = plan["task_code"]
    actual_now = codes.map(now[actual])
    on_time = actual_now.notna() & (actual_now <= due) if due is not None else False
    return pd.DataFrame(
        {
            "task_code": codes,
            "task_name": plan["task_name"],
            "wbs_code": plan["wbs_code"],
            "commitment": commitment,
            "planned_date": plan[date],
            "in_update": codes.isin(now.index),
            "kept": codes.map(now[done]).fillna(False).astype(bool) & on_time,
            "actual_date": actual_now,
            "forecast_now": codes.map(now[date]),
            "status_now": codes.map(now["status"]).fillna("deleted"),
        }
    )


def unplanned_work(previous: Snapshot, current: Snapshot) -> pd.DataFrame:
    """Tasks new in W (Activity ID absent from W-1) with an actual start on or before W's data
    date: work done that W-1 did not plan, out of the PPC counts. Milestones and level of effort
    left out, as in `committed`; a started status without the actual date is not evidence of
    work, as for a commitment."""
    work = current.activities
    work = work[~work["is_milestone"] & ~work["is_loe"] & ~work["task_code"].isin(previous.by_code.index)]
    columns = ["task_code", "task_name", "wbs_code", "status", "act_start_date", "act_end_date"]
    if current.data_date is None:
        return work.loc[[], columns]
    return work.loc[work["act_start_date"] <= current.data_date, columns].reset_index(drop=True)


def renumbered(previous: Snapshot, current: Snapshot) -> pd.DataFrame:
    """Activities whose Activity ID changed between W-1 and W: same P6 ``task_id``, old ID gone
    from W, new ID absent from W-1. xerscope's identity is the Activity ID, so PPC reads such
    an activity as deleted (its commitments leave the counts) and created (new in W); this list
    lets the page warn about it. ``task_id`` is P6's internal key: only meaningful between
    exports of the same database."""
    before = previous.activities[["task_id", "task_code"]].drop_duplicates("task_id")
    after = current.activities[["task_id", "task_code"]].drop_duplicates("task_id")
    pairs = before.merge(after, on="task_id", suffixes=("_before", "_now"))
    changed = (
        (pairs["task_code_before"] != pairs["task_code_now"])
        & ~pairs["task_code_before"].isin(after["task_code"])
        & ~pairs["task_code_now"].isin(before["task_code"])
    )
    return pairs.loc[changed, ["task_code_before", "task_code_now"]].reset_index(drop=True)


RENUMBERED_SHOWN = 5


def _renumbered_note(previous: Snapshot, current: Snapshot) -> str | None:
    pairs = renumbered(previous, current)
    if pairs.empty:
        return None
    shown = ", ".join(f"{a} → {b}" for a, b in pairs.head(RENUMBERED_SHOWN).itertuples(index=False))
    more = f" and {len(pairs) - RENUMBERED_SHOWN} more" if len(pairs) > RENUMBERED_SHOWN else ""
    return f"{len(pairs)} Activity ID(s) changed since W-1, counted as deleted + new: {shown}{more}"


PPC_WEEK_DAYS = 7


def _gap_note(previous: Snapshot, current: Snapshot) -> str | None:
    """Note for a pair more than a week apart: an update is missing, so the point holds the
    commitments of every week between the two data dates. Calendar days: Monday 08:00 to the
    next Monday 17:00 is one week. A W without a data date has no commitment: noted too."""
    if current.data_date is None:
        return "no status date in this update: its commitments cannot be read"
    if previous.data_date is None:
        return None
    days = (current.data_date.normalize() - previous.data_date.normalize()).days
    if days <= PPC_WEEK_DAYS:
        return None
    return f"{days} days since the previous update: this point covers more than one week"


def _notes(previous: Snapshot, current: Snapshot) -> str | None:
    notes = [n for n in (_gap_note(previous, current), _renumbered_note(previous, current)) if n]
    return "; ".join(notes) or None


def ppc_series(store: SnapshotStore, include_overdue: bool = True) -> pd.DataFrame:
    """One row per week W (update 1 onward): the counts and the three PPC of `committed`."""
    rows = []
    for index in range(1, len(store)):
        commitments = committed(store[index - 1], store[index], include_overdue)
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
                "ppc_start": _share(starts_kept, len(starts)),
                "ppc_finish": _share(finishes_kept, len(finishes)),
                "ppc_week": _share(kept, planned),
                "note": _notes(store[index - 1], store[index]),
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
            "ppc_start",
            "ppc_finish",
            "ppc_week",
            "note",
        ],
    )


def _share(kept: int, committed: int) -> float | None:
    """Percent kept, None when nothing was committed."""
    return 100 * kept / committed if committed else None


# --- start and finish variances against earlier updates ----------------------------------------

VARIANCE_COLUMNS = ["start_var_w1", "finish_var_w1", "start_var_w2", "finish_var_w2"]


def date_variances(store: SnapshotStore, index: int) -> pd.DataFrame:
    """Per activity of update ``index`` (W): its start and finish against update W-1 and W-2.

    ``<end>_var_w<k> = working_days(date in W, date in W-k)``, i.e. reference − current, on the
    activity's calendar in W: negative = later than the reference (late), positive = earlier.
    Dates are P6's Start / Finish (actual, else forecast). Blank, not 0, when either date is
    missing: no such update, the activity not in it, or no date. A start milestone has only
    the start columns, a finish milestone only the finish ones. Level of effort has no row: its
    dates follow the activities it spans, so its variance repeats theirs.
    """
    current = store[index]
    now = current.by_code
    now = now[~now["is_loe"]]
    out = now[["task_name", "wbs_code", "status", "start", "finish"]].copy()
    for back in (1, 2):
        reference = store[index - back].by_code if index >= back else None
        for end in ("start", "finish"):
            column = f"{end}_var_w{back}"
            if reference is None:
                out[column] = np.nan
            else:
                then = reference[end].reindex(now.index)
                out[column] = current.working_days(now["clndr_id"], now[end], then)
    finish_milestone = now["is_milestone"] & ~now["is_start_milestone"]
    out.loc[now["is_start_milestone"], ["finish_var_w1", "finish_var_w2"]] = np.nan
    out.loc[finish_milestone, ["start_var_w1", "start_var_w2"]] = np.nan
    return out.reset_index()


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
    last row of ``history``, as the update of that row defines it (the latest update for an
    activity still in it; for one deleted since, the last update that holds it, where its
    calendar exists); None with one update or a missing finish."""
    if len(history) < 2 or history["finish"].isna().any():
        return None
    clndr_id = history["clndr_id"].iloc[-1]
    last_update = store[int(history["snapshot_idx"].iloc[-1])]
    return last_update.activity_working_days(
        clndr_id if isinstance(clndr_id, str) else None, history["finish"].iloc[0], history["finish"].iloc[-1]
    )
