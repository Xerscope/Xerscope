"""DCMA 14-Point Schedule Assessment (DCMA-EA PAM 200.1, Oct 2012): one function per check.

Section 4.0 sets the population: incomplete tasks, without LOE and milestones. Threshold
and pass/fail come from ``standards/dcma.toml``; the function only decides what is flagged.
"""

from __future__ import annotations

import operator

import pandas as pd

from ...xer.model import CONSTRAINT, HARD_CONSTRAINTS
from ..cpm import schedule
from ..populations import (
    Funnel,
    activity_funnel,
    actual_after,
    as_flag,
    constrained_by,
    finish_driver,
    flagged_activities,
    flagged_relationships,
    forecast_before,
    has_predecessor_in_project,
    has_successor_in_project,
    invalid_date_reason,
    lag_flagged,
    open_end_reason,
    with_baseline,
)
from ..rules import RuleOutput, bei_from_snapshot, critical_path_output, link_funnel, rule, share_of_type

DCMA_HIGH_DAYS = 44  # PAM 200.1 §4.6 and §4.8: "two months" of work, in working days of the activity's calendar
# The pamphlet gives no slip length (§4.12); 600 working days is xerscope's choice.
DCMA_SLIP_DAYS = 600

# Start On, Start On or Before, Finish On, Finish On or Before, Mandatory Start, Mandatory Finish:
# the model's set.
DCMA_HARD_CONSTRAINTS = HARD_CONSTRAINTS


def _discrete_tasks(funnel: Funnel) -> Funnel:
    """PAM 200.1 section 4.0: LOE and milestones are not tasks."""
    return funnel.exclude("loe", "PAM 200.1").exclude("milestones", "PAM 200.1")


def _open_tasks(context) -> Funnel:
    """The DCMA population: incomplete, non-LOE, non-milestone tasks."""
    return _discrete_tasks(activity_funnel(context.snapshot).exclude("complete", "PAM 200.1"))


def _links_into_open_tasks(context) -> Funnel:
    """PAM 200.1 section 4.0: a link counts when its successor is an incomplete, non-LOE, non-milestone task."""
    return link_funnel(context, "all", exclude=("complete", "loe", "milestones"), source="PAM 200.1")


@rule("dcma_01_logic", "%")
def dcma_01_logic(context) -> RuleOutput:
    """Missing a predecessor or a successor.
    Counts: open-ended / checked
    Excludes: completed tasks, level of effort, milestones.

    DCMA-EA PAM 200.1 §4.1: any incomplete task missing a predecessor and/or a successor; no project
    start/finish exemption and no dangling case; §4.0: milestones excluded; a link to another project
    counts as logic (rule default)
    """
    funnel = _open_tasks(context)
    tasks = funnel.rows
    has_predecessor = has_predecessor_in_project(context.snapshot, tasks) | tasks["has_external_pred"]
    has_successor = has_successor_in_project(context.snapshot, tasks) | tasks["has_external_succ"]

    missing_predecessor = ~has_predecessor
    missing_successor = ~has_successor
    flagged = tasks[missing_predecessor | missing_successor]
    reason = open_end_reason(missing_predecessor, missing_successor)[flagged.index]
    return RuleOutput(
        flagged_activities(flagged, reason=reason), len(flagged), len(tasks), checked=tasks, funnel=funnel
    )


@rule("dcma_02_leads", "%", links=True)
def dcma_02_leads(context) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / relationships checked
    Relationships whose successor is excluded: level of effort, milestones.
    Relationships counted: relationships into an incomplete successor.
    Flagged when lag < 0 hours.

    DCMA-EA PAM 200.1 §4.2: logic links with a lead (negative lag) in predecessor relationships for
    incomplete tasks; §4.0: completed, LOE, summary tasks and milestones are excluded, so a link counts
    when its successor is kept
    """
    funnel = _links_into_open_tasks(context)
    relationships = funnel.rows

    leads = lag_flagged(relationships, operator.lt, 0)
    return RuleOutput(
        flagged_relationships(leads), len(leads), len(relationships), checked=relationships, funnel=funnel
    )


@rule("dcma_03_lags", "%", links=True)
def dcma_03_lags(context) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / relationships checked
    Relationships whose successor is excluded: level of effort, milestones.
    Relationships counted: relationships into an incomplete successor.
    Flagged when lag > 0 hours.

    DCMA-EA PAM 200.1 §4.3: lags in predecessor logic relationships for incomplete tasks; §4.0:
    completed, LOE, summary tasks and milestones are excluded, so a link counts when its successor is
    kept
    """
    funnel = _links_into_open_tasks(context)
    relationships = funnel.rows

    lags = lag_flagged(relationships, operator.gt, 0)
    return RuleOutput(flagged_relationships(lags), len(lags), len(relationships), checked=relationships, funnel=funnel)


@rule("dcma_04_relationship_types", "%", links=True)
def dcma_04_relationship_types(context) -> RuleOutput:
    """Relationships of another type.
    Counts: of the required type / relationships checked
    Relationships whose successor is excluded: level of effort, milestones.
    Relationships counted: relationships into an incomplete successor.
    Counts relationships of type FS; the list shows the others.

    DCMA-EA PAM 200.1 §4.4: a count of incomplete tasks containing each type of logic link; §4.0:
    completed, LOE, summary tasks and milestones are excluded, so a link counts when its successor is
    kept
    """
    funnel = _links_into_open_tasks(context)
    share = share_of_type(funnel.rows, "FS")
    share.funnel = funnel
    return share


@rule("dcma_05_hard_constraints", "%")
def dcma_05_hard_constraints(context) -> RuleOutput:
    """Constrained tasks.
    Counts: constrained / checked
    Excludes: completed tasks, level of effort, milestones.
    Constraint types: Start on, Start on or before, Finish on, Finish on or before, Mandatory start,
        Mandatory finish.

    DCMA-EA PAM 200.1 §4.5 (and §4.0: milestones excluded); MSO = Start On / Mandatory Start, MFO = Finish
    On / Mandatory Finish, SNLT = Start On or Before, FNLT = Finish On or Before
    """
    funnel = _open_tasks(context)
    tasks = funnel.rows
    hard = tasks[constrained_by(tasks, DCMA_HARD_CONSTRAINTS, ignore_started_starts=False)]
    return RuleOutput(
        flagged_activities(hard, constraint2=hard["cstr_type2"].map(CONSTRAINT)),
        len(hard),
        len(tasks),
        checked=tasks,
        funnel=funnel,
    )


@rule("dcma_06_high_float", "%")
def dcma_06_high_float(context, limit_days: float = DCMA_HIGH_DAYS) -> RuleOutput:
    """Tasks outside the float limit.
    Counts: flagged / checked
    Excludes: completed tasks, level of effort, milestones.

    DCMA-EA PAM 200.1 §4.6: incomplete task with total float greater than 44 working days (2 months);
    §4.0: milestones excluded
    """
    funnel = _open_tasks(context)
    tasks = funnel.rows
    high_float = tasks[tasks["total_float_d"] > limit_days]
    return RuleOutput(flagged_activities(high_float), len(high_float), len(tasks), checked=tasks, funnel=funnel)


@rule("dcma_07_negative_float", "%")
def dcma_07_negative_float(context) -> RuleOutput:
    """Tasks outside the float limit.
    Counts: flagged / checked
    Excludes: completed tasks, level of effort, milestones.
    Flagged when total float < 0 days.

    DCMA-EA PAM 200.1 §4.7: incomplete task with total float less than 0 working days; §4.0: milestones
    excluded
    """
    funnel = _open_tasks(context)
    tasks = funnel.rows
    negative_float = tasks[tasks["total_float_d"] < 0]
    return RuleOutput(flagged_activities(negative_float), len(negative_float), len(tasks), checked=tasks, funnel=funnel)


@rule("dcma_08_high_duration", "%")
def dcma_08_high_duration(context, limit_days: float = DCMA_HIGH_DAYS) -> RuleOutput:
    """Tasks outside the duration limit.
    Counts: flagged / checked
    Excludes: completed tasks, level of effort, milestones.

    DCMA-EA PAM 200.1 §4.8: an incomplete task with a baseline duration greater than 44 working days (2
    months) and a baseline start within the detail planning period or rolling wave; §4.0: LOE and
    milestones excluded. UNRESOLVED: inputs are weekly XERs with no detail planning window, so every
    baseline start qualifies. UNRESOLVED: baseline hours are divided by the task's current hours per
    day, not the baseline calendar. A task absent from the baseline is not flagged; without a
    baseline the check is n/a
    """
    if context.baseline is None:
        return RuleOutput(note="needs a baseline")
    funnel = _open_tasks(context)
    tasks = funnel.rows
    baseline_hours = tasks["task_code"].map(context.baseline.frame["bl_duration_hr"])
    long_tasks = tasks[baseline_hours / tasks["hours_per_day"] > limit_days]
    return RuleOutput(flagged_activities(long_tasks), len(long_tasks), len(tasks), checked=tasks, funnel=funnel)


@rule("dcma_09_invalid_dates", "%")
def dcma_09_invalid_dates(context) -> RuleOutput:
    """Progress dates on the wrong side of the status date.
    Counts: with invalid dates / checked
    Excludes: level of effort, milestones, tasks completed before the status date.

    DCMA-EA PAM 200.1 §4.9: incomplete tasks with a forecast start/finish before the status date, or an
    actual start/finish beyond it; §4.0: LOE and milestones excluded; a task completed before the status
    date is out too, so only an actual date beyond it can flag a completed task
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    funnel = _discrete_tasks(activity_funnel(context.snapshot)).exclude("complete_before_data_date", "PAM 200.1")
    tasks = funnel.rows

    forecast = forecast_before(tasks, data_date)
    actual = actual_after(tasks, data_date)
    invalid = forecast | actual
    reasons = invalid_date_reason(forecast, actual)[invalid]
    return RuleOutput(
        flagged_activities(tasks[invalid], reason=reasons), int(invalid.sum()), len(tasks), checked=tasks, funnel=funnel
    )


@rule("dcma_10_resources", "%")
def dcma_10_resources(context) -> RuleOutput:
    """Tasks with no resource assignment.
    Counts: without resources / checked
    Excludes: completed tasks, level of effort, milestones, tasks with no original duration.

    DCMA-EA PAM 200.1 §4.10: "all tasks with durations greater than zero have dollars or hours assigned";
    incomplete tasks without them over incomplete tasks; §4.0 exclusions apply. Cost or hours = a
    resource assignment or an expense. The test applies to a resource-loaded schedule only: n/a when the
    project has no assignment and no budgeted labour hours on its tasks (expenses alone do not load it);
    hours without assignments still fail, with a note on the export. Target 0 %, the pamphlet and Acumen
    giving none
    """
    snapshot = context.snapshot
    if snapshot.assignments.empty:
        if not (snapshot.activities["labor_budget_hr"] > 0).any():
            return RuleOutput(
                note="PAM 200.1 §4.10: applies to a resource-loaded schedule only; "
                "no resource assignment and no labour hours"
            )
        note = "labour hours on tasks but no resource assignment: check the export (TASKRSRC)"
    else:
        note = ""
    funnel = _open_tasks(context).exclude("no_duration", "PAM 200.1")
    tasks = funnel.rows
    without_cost = tasks[~(tasks["has_resource"] | tasks["has_expense"])]
    return RuleOutput(
        flagged_activities(without_cost), len(without_cost), len(tasks), note=note, checked=tasks, funnel=funnel
    )


@rule("dcma_11_missed_tasks", "%", needs_baseline=True)
def dcma_11_missed_tasks(context) -> RuleOutput:
    """Due by the status date and not finished on time.
    Counts: missed / due by the status date
    Excludes: level of effort, milestones.
    Due = baseline start and finish set, baseline finish on or before the status date. Missed = actual
        (else forecast) finish on a later day than the baseline finish.

    DCMA-EA PAM 200.1 (Oct 2012) 4.11: baseline finish on or before the status date, actual or forecast
    finish after it; base excludes tasks missing a baseline start or finish. 4.0 excludes completed
    tasks, LOE, summary tasks and milestones; 4.11 measures actual finishes, so completed tasks stay here
    (4.11 overrides 4.0 on that point). UNRESOLVED: the pamphlet's Finish Variance is working time; the
    calendar date is compared here, as an actual on a non-working day is still late
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    funnel = Funnel(with_baseline(context.baseline, context.snapshot.activities), data_date)
    tasks = _discrete_tasks(funnel).rows
    unmatched = int((tasks["bl_start"].isna() | tasks["bl_finish"].isna()).sum())
    funnel.keep(
        "baseline finish on or before the status date",
        "PAM 200.1",
        lambda rows: rows["bl_start"].notna() & (rows["bl_finish"] <= data_date),
    )
    due = funnel.rows
    finishes_later = due["finish"].dt.normalize() > due["bl_finish"].dt.normalize()
    missed = due[as_flag(finishes_later)]
    # a baseline that matches few activities shrinks the due population silently: say so
    note = f"{unmatched} without baseline dates left out of {len(tasks)} tasks" if unmatched else ""
    return RuleOutput(
        flagged_activities(missed, bl_finish=missed["bl_finish"]),
        len(missed),
        len(due),
        note=note,
        checked=due,
        funnel=funnel,
    )


@rule("dcma_12_critical_path_test", "pass/fail")
def dcma_12_critical_path_test(context, slip_days: float = DCMA_SLIP_DAYS) -> RuleOutput:
    """Add the slip (working days) to the first open critical task; the finish must slip as much.

    DCMA-EA PAM 200.1 §4.12: the project completion date must move "in direct proportion" to the
    "intentional slip" introduced. The pamphlet gives no slip length; 600 working days is xerscope's
    choice, DECM 06A401a gives none either
    """
    return critical_path_output(context, slip_days)


def _baseline_margin(context, last_task) -> tuple[RuleOutput | None, str, float, float]:
    """Margin of the open end milestone that finishes last to its baseline finish, in project working days.

    Returns (n/a output or None, milestone code, margin, baseline finish text).
    """
    snapshot = context.snapshot
    if context.baseline is None:
        return RuleOutput(note="no Must Finish By date and no baseline: no reference date for the float"), "", 0, ""
    if context.baseline.is_planned:
        note = (
            "baseline = planned dates of this file: a not-started milestone's planned finish follows its early "
            "finish (Oracle 47222); choose a baseline file"
        )
        return RuleOutput(note=note), "", 0, ""
    activities = snapshot.activities
    ends = activities[
        ~activities["is_complete"] & ~activities["is_loe"] & (activities["task_type"] == "TT_FinMile")
    ].dropna(subset=["finish"])
    if ends.empty:
        return RuleOutput(note="no Must Finish By date and no open finish milestone to measure the float on"), "", 0, ""
    end = ends.sort_values(["finish", "task_code"]).iloc[-1]
    baseline_finish = context.baseline.frame["bl_finish"].get(end["task_code"], pd.NaT)
    if pd.isna(baseline_finish):
        return RuleOutput(note=f"{end['task_code']} has no baseline finish"), "", 0, ""
    forecast = schedule(snapshot).frame["ef"].get(end["task_code"], end["finish"])
    margin = snapshot.project_working_days(forecast, baseline_finish)
    return None, end["task_code"], margin, f"{baseline_finish:%Y-%m-%d}"


@rule("dcma_13_cpli", "ratio")
def dcma_13_cpli(context) -> RuleOutput:
    """Critical Path Length Index = (CPL + TF) / CPL.

    DCMA-EA PAM 200.1 §3.1.2.3: CPLI = (CPL + TF) / CPL, TF being the total float of the completion
    milestone ("the amount of days a project can be delayed before delaying the project completion
    date"). CPL = working days from the status date to the forecast finish, TF = that float, both in working
    days of the project calendar (PAM and Acumen say days without naming a calendar).
    P6 writes that float against the Must Finish By date. Without one, TF is the margin of the open
    finish milestone ending last to its baseline finish (PAM: TF "relative to the baselined finish
    date, when constrained") (recalculated early finish, project calendar;
    negative when late); n/a without a baseline, with the planned dates baseline (the planned finish of a
    not-started milestone follows its early finish: margin 0 by construction, Oracle 47222) or without a
    baseline finish for it. No constraint is read
    """
    snapshot = context.snapshot
    last_task = finish_driver(snapshot)
    if snapshot.data_date is None:
        return RuleOutput(note="no status date")
    if last_task is None:
        return RuleOutput(note="no remaining work")
    margin_note = ""
    if snapshot.options.get("must_finish_by") is None:
        unavailable, code, margin, baseline_finish = _baseline_margin(context, last_task)
        if unavailable is not None:
            return unavailable
        margin_note = f"margin of {code} to its BL finish {baseline_finish}: {margin:g} wd"
    calendar = snapshot.calendar()
    length = snapshot.project_working_days(snapshot.data_date, last_task["finish"])
    if length <= 0:
        return RuleOutput(note="critical path length is 0")
    if margin_note:
        total_float = margin
        note = f"CPL {length:g} wd, {margin_note}"
    else:
        float_hours = float(last_task["total_float_hr_cnt"]) if pd.notna(last_task["total_float_hr_cnt"]) else 0.0
        total_float = float_hours / calendar.hours_per_day if calendar.hours_per_day else 0.0
        note = f"CPL {length:g} wd to {last_task['task_code']}, total float {total_float:g} wd"
    return RuleOutput(value=(length + total_float) / length, note=note)


@rule("dcma_14_bei", "ratio", needs_baseline=True)
def dcma_14_bei(context) -> RuleOutput:
    """Due by the status date but not completed.
    Counts: completed / due by the status date
    Excludes: level of effort, milestones.
    Tasks without a baseline finish are counted as due. Completed = all completed tasks in the
        population, early ones included.

    DCMA-EA PAM 200.1 §3.1.2.4: Baseline Execution Index = tasks completed / tasks due by the
    status date; step 1 filters out LOE, summary and zero duration tasks (milestones); tasks missing
    baseline finish dates are included in the denominator
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    funnel = Funnel(with_baseline(context.baseline, context.snapshot.activities), data_date)
    tasks = _discrete_tasks(funnel).rows
    funnel.keep(
        "due by the status date",
        "PAM 200.1",
        lambda rows: as_flag(rows["bl_finish"] <= data_date) | rows["bl_finish"].isna(),
    )
    bei = bei_from_snapshot(tasks, data_date, missing_baseline_is_due=True)
    bei.funnel = funnel
    return bei
