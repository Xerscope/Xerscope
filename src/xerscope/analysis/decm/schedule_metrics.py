"""DCMA EVMS Compliance Metrics v8.0 (21 Aug 2025), Guideline 6 schedule tests: one function per metric.

Each docstring quotes the specification sheet. Threshold and pass/fail come from
``standards/decm.toml``; the function only decides what is flagged.

DECM vocabulary -> P6: status date = status date; incomplete = no actual finish; summary task
= WBS summary task. "On or before the status date" (the end of the reported period) is
"before the status date" in P6, whose status date is the first instant of remaining work.
"""

from __future__ import annotations

import pandas as pd

from ...xer.calendar import hours_to_days
from ...xer.model import CONSTRAINT
from ..baseline import Baseline
from ..populations import (
    Funnel,
    activity_funnel,
    actual_after,
    as_flag,
    constrained_by,
    flagged_activities,
    flagged_relationships,
    forecast_before,
    has_driving_predecessor,
    has_driving_successor,
    joined_sorted,
    with_baseline,
)
from ..rules import RuleOutput, critical_path_output, rule

DECM_HARD_CONSTRAINTS = ["CS_MANDSTART", "CS_MANDFIN"]  # Primavera's hard constraints
# Defaults of the parameters below; decm.toml repeats each with its DECM v8.0 metric.
HIGH_FLOAT_DAYS = 44  # 06A211a: total float limit, working days of the activity's calendar
SLIP_DAYS = 600  # working days added to the first open critical task; xerscope's choice, the 06A401a sheet gives none
STATUS_PERIOD_DAYS = 28  # 06A504a / 06A504b / 06A506c: an update is compared with the one a period older
RIDING_WINDOW_WD = 3  # 06A506c: a forecast start this close to the data date "rides" it
RIDING_REMAINING_TOLERANCE_WD = 2  # 06A506c: a remaining duration that moved by no more "rides" it too


def _update_a_period_ago(context, status_period_days: float):
    """The latest update at least one status period older than the snapshot, or None."""
    store, snapshot = context.store, context.snapshot
    if store is None or snapshot.data_date is None:
        return None
    cutoff = snapshot.data_date - pd.Timedelta(days=status_period_days)
    earlier = [update for update in store if update.data_date is not None and update.data_date <= cutoff]
    return earlier[-1] if earlier else None


# --- logic ---------------------------------------------------------------------------------


@rule("decm_06a204b_dangling_logic", "%")
def decm_06a204b_dangling_logic(context) -> RuleOutput:
    """Open start or open finish.
    Counts: with an open start or finish / incomplete tasks and milestones
    Excludes: completed tasks, level of effort.
    Open start: a task whose predecessors are only FF / SF, or none; a milestone with no predecessor.
        Open finish: a task whose successors are only SS / SF, or none; a milestone with no successor.
    Exempt: the earliest baseline start (start test) and the latest baseline finish (finish test) among
        the Non-LOE activities, finished ones included; the planned dates when no baseline is loaded.

    06A204b: open start = only FF/SF or no predecessor (milestone: none); open finish = only SS/SF or no
    successor (milestone: none); earliest baseline start / latest baseline finish exempt
    """
    funnel = activity_funnel(context.snapshot).exclude("complete", "DECM 8.0").exclude("loe", "DECM 8.0")
    tasks = funnel.rows
    relationships = context.snapshot.relationships
    codes = tasks["task_code"]
    external_predecessor, external_successor = tasks["has_external_pred"], tasks["has_external_succ"]
    has_predecessor = codes.isin(relationships["succ_code"]) | external_predecessor
    has_successor = codes.isin(relationships["pred_code"]) | external_successor
    driven_start = has_driving_predecessor(codes, relationships) | external_predecessor
    drives_finish = has_driving_successor(codes, relationships) | external_successor
    milestone = tasks["is_milestone"]
    open_start = (~has_predecessor).where(milestone, ~driven_start)
    open_finish = (~has_successor).where(milestone, ~drives_finish)

    # The project's first start and last finish are looked up over the baseline's Non-LOE activities
    # (the metric's population, block 6), finished ones included: once the first activity is done, the
    # next one in line is not the project start.
    baseline = context.baseline or Baseline.planned(context.snapshot)
    in_baseline = baseline.snapshot.activities
    frame = baseline.frame.drop(index=in_baseline.loc[in_baseline["is_loe"], "task_code"], errors="ignore")
    is_first = codes.map(frame["bl_start"]) == frame["bl_start"].min()
    is_last = codes.map(frame["bl_finish"]) == frame["bl_finish"].max()
    open_start &= ~as_flag(is_first)
    open_finish &= ~as_flag(is_last)

    reason = pd.Series("", index=tasks.index)
    reason = reason.mask(open_finish, "open finish (no FS/FF successor)")
    reason = reason.mask(open_start, "open start (no FS/SS predecessor)")
    reason = reason.mask(open_start & open_finish, "open start and finish")
    flagged = tasks[reason != ""]
    note = "first/last by baseline dates"
    if context.baseline is None:
        note = "no baseline: first/last by planned dates"
    return RuleOutput(
        flagged_activities(flagged, reason=reason[flagged.index]),
        len(flagged),
        len(tasks),
        note=note,
        checked=tasks,
        funnel=funnel,
    )


@rule("decm_06a205a_lags", "%")
def decm_06a205a_lags(context) -> RuleOutput:
    """Tasks with a lag on a predecessor.
    Counts: with a lag / incomplete tasks and milestones
    Excludes: completed tasks.
    Level of effort is kept; only positive lags count, leads (negative lags) do not.

    06A205a: X/Y <= 10%; the sheet does not say whether LOE count or whether leads (negative lags) do:
    LOE kept, positive lags only
    """
    funnel = activity_funnel(context.snapshot).exclude("complete", "DECM 8.0")
    tasks = funnel.rows
    relationships = context.snapshot.relationships
    lags = relationships[relationships["lag_hr"].fillna(0) > 0]
    lagged_from = lags.groupby("succ_code")["pred_code"].agg(joined_sorted)
    flagged = tasks[tasks["task_code"].isin(lagged_from.index)]
    return RuleOutput(
        flagged_activities(flagged, lagged_from=flagged["task_code"].map(lagged_from)),
        len(flagged),
        len(tasks),
        checked=tasks,
        funnel=funnel,
    )


@rule("decm_06a208a_summary_logic", "count")
def decm_06a208a_summary_logic(context) -> RuleOutput:
    """Summary tasks carrying logic.
    Counts: with logic /

    06A208a: X = 0 (summary tasks are the P6 WBS summaries; flagged when they have a predecessor or
    a successor)
    """
    funnel = Funnel(context.snapshot.tasks).keep("WBS summary", "DECM 8.0", lambda rows: rows["is_wbs_summary"])
    summaries = funnel.rows
    relationships = context.snapshot.relationships
    has_logic = summaries["task_code"].isin(relationships["pred_code"]) | summaries["task_code"].isin(
        relationships["succ_code"]
    )
    flagged = summaries[has_logic]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(summaries), checked=summaries, funnel=funnel)


@rule("decm_06a209a_hard_constraints", "%")
def decm_06a209a_hard_constraints(context) -> RuleOutput:
    """Constrained tasks.
    Counts: constrained / checked
    Excludes: completed tasks.
    Constraint types: Mandatory start, Mandatory finish.

    06A209a: X/Y = 0%; Primavera P6 hard constraints = Mandatory Start, Mandatory Finish; the sheet does
    not say whether LOE count: kept
    """
    funnel = activity_funnel(context.snapshot).exclude("complete", "DECM 8.0")
    tasks = funnel.rows
    hard = tasks[constrained_by(tasks, DECM_HARD_CONSTRAINTS, ignore_started_starts=False)]
    return RuleOutput(
        flagged_activities(hard, constraint2=hard["cstr_type2"].map(CONSTRAINT)),
        len(hard),
        len(tasks),
        checked=tasks,
        funnel=funnel,
    )


@rule("decm_06a210a_loe_successors", "%")
def decm_06a210a_loe_successors(context) -> RuleOutput:
    """LOE driving discrete work.
    Counts: with a discrete successor / incomplete LOE
    Excludes: completed tasks.

    06A210a: X = 0 (incomplete LOE tasks with a discrete, non-LOE, successor)
    """
    funnel = activity_funnel(context.snapshot).exclude("complete", "DECM 8.0")
    funnel.keep("level of effort", "DECM 8.0", lambda rows: as_flag(rows["is_loe"]))
    open_loe = funnel.rows
    is_loe_by_code = context.snapshot.by_code["is_loe"]
    relationships = context.snapshot.relationships
    from_loe = relationships[
        relationships["pred_code"].isin(open_loe["task_code"]) & relationships["succ_code"].isin(is_loe_by_code.index)
    ]
    successor_is_loe = as_flag(from_loe["succ_code"].map(is_loe_by_code))
    drives = from_loe[~successor_is_loe].groupby("pred_code")["succ_code"].agg(joined_sorted)
    flagged = open_loe[open_loe["task_code"].isin(drives.index)]
    return RuleOutput(
        flagged_activities(flagged, drives=flagged["task_code"].map(drives)),
        len(flagged),
        len(open_loe),
        checked=open_loe,
        funnel=funnel,
    )


@rule("decm_06a211a_high_float", "%")
def decm_06a211a_high_float(context, limit_days: float = HIGH_FLOAT_DAYS) -> RuleOutput:
    """Tasks outside the float limit.
    Counts: flagged / checked
    Excludes: completed tasks, level of effort.

    06A211a: the population DECM samples; X/Y <= 20% of the sample with inadequate rationale. The
    rationale review is yours
    """
    funnel = activity_funnel(context.snapshot).exclude("complete", "DECM 8.0").exclude("loe", "DECM 8.0")
    tasks = funnel.rows
    high_float = tasks[tasks["total_float_d"] > limit_days]
    return RuleOutput(flagged_activities(high_float), len(high_float), len(tasks), checked=tasks, funnel=funnel)


@rule("decm_06a212a_out_of_sequence", "count", links=True)
def decm_06a212a_out_of_sequence(context) -> RuleOutput:
    """Progressed out of logic sequence.
    Counts: out of sequence /
    Relationships counted: relationships from an incomplete predecessor (the sheet's population;
        once the predecessor has finished, a successor that started before it is no longer out of
        sequence, as in P6's own check).
    Actual dates first, else forecast; lags are not added, so a lead that lets work overlap is also an
        out-of-sequence condition.

    06A212a: X = 0; FS (S.AS|S.FS) < P.FF, SS (S.AS|S.FS) < P.FS, FF (S.AF|S.FF) < P.FF, SF (S.AF|S.FF) <
    P.FS
    """
    tasks = context.snapshot.by_code
    open_codes = activity_funnel(context.snapshot).exclude("complete", "DECM 8.0").rows["task_code"]
    funnel = Funnel(context.snapshot.relationships)
    funnel.keep("into a task", "model", lambda rows: rows["succ_code"].isin(tasks.index))
    funnel.keep("predecessor not complete", "DECM 8.0", lambda rows: rows["pred_code"].isin(open_codes))
    links = funnel.rows
    if links.empty:
        return RuleOutput(flagged_relationships(links), 0, 0, checked=links, funnel=funnel)
    pred_start, pred_finish = links["pred_code"].map(tasks["start"]), links["pred_code"].map(tasks["finish"])
    succ_start, succ_finish = links["succ_code"].map(tasks["start"]), links["succ_code"].map(tasks["finish"])
    kind = links["type"]
    out_of_sequence = (
        ((kind == "FS") & (succ_start < pred_finish))
        | ((kind == "SS") & (succ_start < pred_start))
        | ((kind == "FF") & (succ_finish < pred_finish))
        | ((kind == "SF") & (succ_finish < pred_start))
    )
    flagged = links[out_of_sequence]
    names = tasks["task_name"]
    shown = flagged_relationships(
        flagged.assign(pred_name=flagged["pred_code"].map(names), succ_name=flagged["succ_code"].map(names))
    )
    shown = shown.assign(
        pred_start=pred_start[flagged.index],
        pred_finish=pred_finish[flagged.index],
        succ_start=succ_start[flagged.index],
        succ_finish=succ_finish[flagged.index],
    )
    return RuleOutput(shown, len(flagged), len(links), checked=links, funnel=funnel)


# --- critical path -------------------------------------------------------------------------


@rule("decm_06a401a_critical_path_test", "pass/fail")
def decm_06a401a_critical_path_test(context, slip_days: float = SLIP_DAYS) -> RuleOutput:
    """Add the slip (working days) to the first open critical task; the finish must slip as much.

    06A401a asks whether the critical path is the longest path; its sheet (v8.0) tests that with a
    constraint six months before the baseline finish and compares the critical sets. This rule runs the
    slip test of DCMA-12 instead: an approximation of 06A401a, not its method
    """
    return critical_path_output(context, slip_days)


# --- baseline, forecast and actual dates ---------------------------------------------------


@rule("decm_06a501a_missing_baseline", "%", needs_baseline=True)
def decm_06a501a_missing_baseline(context) -> RuleOutput:
    """Missing a baseline start or finish.
    Counts: without baseline dates / tasks and milestones

    06A501a: X/Y <= 5%, summaries excluded
    """
    funnel = Funnel(with_baseline(context.baseline, context.snapshot.activities))
    tasks = funnel.rows
    flagged = tasks[tasks["bl_start"].isna() | tasks["bl_finish"].isna()]
    # a low match rate means the wrong baseline file or project, not a schedule defect
    note = f"{len(tasks) - len(flagged)} of {len(tasks)} tasks matched in {context.baseline.label}"
    return RuleOutput(flagged_activities(flagged), len(flagged), len(tasks), note=note, checked=tasks, funnel=funnel)


def _actual_date_changed(context, column: str, status_period_days: float) -> RuleOutput:
    """Tasks whose actual date differs from the one the update a status period older reported.

    X = tasks whose date differs from (or was removed since) the earlier one; Y = tasks with
    that date in either update, so a removed date counts on both sides and the share never exceeds 100 %.
    """
    previous = _update_a_period_ago(context, status_period_days)
    if previous is None:
        return RuleOutput(note=f"needs an update {status_period_days:g} days older")
    now = context.snapshot.by_code
    before = previous.by_code[column].dropna()
    common = before.index.intersection(now.index)
    changed = [code for code in common if now.at[code, column] != before[code]]
    flagged = now.loc[changed].reset_index()
    shown = flagged_activities(flagged, previous=[before[code] for code in changed], now=flagged.get(column))
    dated = set(now.index[now[column].notna()]) | set(common)
    funnel = Funnel(now.reset_index().sort_values("task_code")).keep(
        "with that actual date in either update", "DECM 8.0", lambda rows: rows["task_code"].isin(dated)
    )
    checked = funnel.rows
    return RuleOutput(shown, len(flagged), len(checked), checked=checked, funnel=funnel)


@rule("decm_06a504a_actual_starts_changed", "%")
def decm_06a504a_actual_starts_changed(context, status_period_days: float = STATUS_PERIOD_DAYS) -> RuleOutput:
    """Actual date changed since the previous update.
    Counts: changed / with that actual date

    06A504a: X/Y <= 10%, Y = tasks with an actual start; compared with the update one status period
    earlier
    """
    return _actual_date_changed(context, "act_start_date", status_period_days)


@rule("decm_06a504b_actual_finishes_changed", "%")
def decm_06a504b_actual_finishes_changed(context, status_period_days: float = STATUS_PERIOD_DAYS) -> RuleOutput:
    """Actual date changed since the previous update.
    Counts: changed / with that actual date

    06A504b: X/Y <= 10%, Y = tasks with an actual finish; compared with the update one status period
    earlier
    """
    return _actual_date_changed(context, "act_end_date", status_period_days)


@rule("decm_06a505a_in_progress_without_actual_start", "%")
def decm_06a505a_in_progress_without_actual_start(context) -> RuleOutput:
    """Progress without the matching actual.
    Counts: without the actual date / showing that progress

    06A505a: X/Y <= 5% (% complete > 0, or status in progress, but no actual start)
    """
    funnel = activity_funnel(context.snapshot).keep(
        "progress reported",
        "DECM 8.0",
        lambda rows: as_flag(rows["pct_complete"] > 0) | as_flag(rows["is_started"]),
    )
    in_progress = funnel.rows
    flagged = in_progress[in_progress["act_start_date"].isna()]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(in_progress), checked=in_progress, funnel=funnel)


@rule("decm_06a505b_complete_without_actual_finish", "%")
def decm_06a505b_complete_without_actual_finish(context) -> RuleOutput:
    """Progress without the matching actual.
    Counts: without the actual date / showing that progress

    06A505b: X/Y <= 5% (100 % complete, or status complete, but no actual finish)
    """
    funnel = activity_funnel(context.snapshot).keep(
        "completion reported",
        "DECM 8.0",
        lambda rows: as_flag(rows["pct_complete"] >= 100) | as_flag(rows["is_complete"]),
    )
    complete = funnel.rows
    flagged = complete[complete["act_end_date"].isna()]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(complete), checked=complete, funnel=funnel)


@rule("decm_06a506a_actual_dates_after_status_date", "%")
def decm_06a506a_actual_dates_after_status_date(context) -> RuleOutput:
    """Progress dates on the wrong side of the status date.
    Counts: with invalid dates / with an actual start

    06A506a: X/Y <= 5%, Y = tasks with an actual start (an actual start or finish after the status date)
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    tasks = context.snapshot.activities
    flagged = tasks[actual_after(tasks, data_date)]
    funnel = activity_funnel(context.snapshot).keep(
        "with an actual start", "DECM 8.0", lambda rows: rows["act_start_date"].notna()
    )
    started = funnel.rows
    return RuleOutput(
        flagged_activities(flagged, reason="actual after status date"),
        len(flagged),
        len(started),
        checked=started,
        funnel=funnel,
    )


@rule("decm_06a506b_forecast_dates_before_status_date", "%")
def decm_06a506b_forecast_dates_before_status_date(context) -> RuleOutput:
    """Progress dates on the wrong side of the status date.
    Counts: with invalid dates / checked

    06A506b: X = 0, forecast on or before the status date (= before P6's status date); an incomplete
    task is flagged when its start (not started) or its finish is before the status date
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    funnel = activity_funnel(context.snapshot)
    tasks = funnel.rows
    flagged = tasks[forecast_before(tasks, data_date)]
    return RuleOutput(
        flagged_activities(flagged, reason="forecast before status date"),
        len(flagged),
        len(tasks),
        checked=tasks,
        funnel=funnel,
    )


def _start_near_data_date(snapshot, activities: pd.DataFrame, riding_window_wd: float) -> pd.Series:
    """True where the forecast start is within the riding window after the status date."""
    data_dates = pd.Series(snapshot.data_date, index=activities.index)
    hours = snapshot.work_hours(activities["clndr_id"], data_dates, activities["start"])
    return (hours >= 0) & (hours_to_days(hours, activities["hours_per_day"]) <= riding_window_wd)


@rule("decm_06a506c_riding_status_date", "%")
def decm_06a506c_riding_status_date(
    context,
    status_period_days: float = STATUS_PERIOD_DAYS,
    riding_window_wd: float = RIDING_WINDOW_WD,
    remaining_tolerance_wd: float = RIDING_REMAINING_TOLERANCE_WD,
) -> RuleOutput:
    """Forecasts riding the status date.
    Counts: riding the status date / checked
    Excludes: completed tasks, level of effort.

    06A506c: X/Y <= 1%; start within the riding window of the status date in both updates, or remaining
    duration within the tolerance. Compared with the latest update at least one status period older: a
    not-started task rides when its forecast start is within the riding window of the status date in
    both; a started one when its remaining duration moved by no more than the tolerance (its finish
    slides with the status date)
    """
    previous = _update_a_period_ago(context, status_period_days)
    if previous is None:
        return RuleOutput(note=f"needs an update {status_period_days:g} days older")
    previous_tasks = previous.by_code
    funnel = activity_funnel(context.snapshot).exclude("complete", "DECM 8.0").exclude("loe", "DECM 8.0")
    funnel.keep("in the earlier update", "DECM 8.0", lambda rows: rows["task_code"].isin(previous_tasks.index))
    tasks = funnel.rows
    before = previous_tasks.loc[tasks["task_code"]].set_index(tasks.index)

    start_rides = _start_near_data_date(context.snapshot, tasks, riding_window_wd) & ~tasks["is_started"]
    start_rode = _start_near_data_date(previous, before, riding_window_wd) & ~before["is_started"]
    remaining_change = (tasks["remaining_d"] - before["remaining_d"]).abs()
    both_started = tasks["is_started"] & before["is_started"]
    finish_rides = both_started & (remaining_change <= remaining_tolerance_wd)
    riding = as_flag((start_rides & start_rode) | finish_rides)

    reason = pd.Series(f"start within {riding_window_wd:g} wd of the status date in both updates", index=tasks.index)
    reason = reason.mask(finish_rides, "remaining duration unchanged")
    flagged = tasks[riding]
    return RuleOutput(
        flagged_activities(flagged, reason=reason[riding]),
        len(flagged),
        len(tasks),
        note=f"vs update of {previous.data_date:%Y-%m-%d}",
        checked=tasks,
        funnel=funnel,
    )
