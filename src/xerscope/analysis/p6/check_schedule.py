"""P6 Professional 24 Check Schedule: one function per check, reading like the Oracle text.

The Oracle pages are cited in each docstring. Threshold and pass/fail come from
``standards/p6.toml``; the function only decides which tasks are flagged.
"""

from __future__ import annotations

import operator

from ...xer.model import CONSTRAINT as _CONSTRAINT
from ...xer.model import forecast_dates
from ..populations import (
    Funnel,
    activity_funnel,
    actual_after,
    as_flag,
    constrained_by,
    flagged_activities,
    flagged_relationships,
    has_driving_predecessor,
    has_driving_successor,
    has_predecessor_in_project,
    has_successor_in_project,
    lag_flagged,
    links_between,
    open_end_reason,
    predecessors_ahead,
    with_baseline,
    without,
)
from ..rules import (
    RuleOutput,
    late_output,
    link_funnel,
    rule,
    share_of_type,
)

P6_HARD_CONSTRAINTS = ["CS_MANDSTART", "CS_MSO", "CS_MANDFIN", "CS_MEO"]
SOFT_CONSTRAINTS = ["CS_MSOB", "CS_MSOA", "CS_MEOB", "CS_MEOA", "CS_ALAP"]
# The constraints the Dangling Finish options name (113174), not those of P6-02 / P6-03: Start On and
# Finish On are soft there.
DANGLING_SOFT_CONSTRAINTS = ["CS_MSO", "CS_MSOA", "CS_MSOB", "CS_MEO", "CS_MEOA", "CS_MEOB", "CS_ALAP"]
DANGLING_HARD_CONSTRAINTS = ["CS_MANDSTART", "CS_MANDFIN"]
# The "x" of P6-04, P6-05 and P6-06 in hours: 352 h, the value report R1 prints for the Check Schedule
# dialog (docs/standards.md, Sources). It is P6's own setting, not DCMA's 44 working days; p6.toml repeats it.
LARGE_HOURS = 352


def _activities(context) -> Funnel:
    return activity_funnel(context.snapshot)


def _open(context) -> Funnel:
    return _activities(context).exclude("complete", "101248")


def _open_not_loe(context) -> Funnel:
    return _open(context).exclude("loe", "101248")


def _links(context) -> Funnel:
    return link_funnel(context, "not_both_complete", source="101248")


@rule("p6_01_logic", "%")
def p6_01_logic(context) -> RuleOutput:
    """Missing a predecessor or a successor.
    Counts: open-ended / checked
    Excludes: completed tasks.
    No predecessor required for: started tasks.

    101248: completed and WBS summary tasks not included; started tasks need no predecessor.
    101248 also exempts start milestones, but a P6 Professional 26.8 report lists a not-started start
    milestone without predecessor (tests/test_p6_checksched.py), as the r22.12 report analysed by Ten Six
    lists its Notice to Proceed milestone: the reports win. A finish milestone without successor is
    counted (same reports); external links pass (46291)
    """
    funnel = _open(context)
    activities = funnel.rows
    has_predecessor = has_predecessor_in_project(context.snapshot, activities) | activities["has_external_pred"]
    has_successor = has_successor_in_project(context.snapshot, activities) | activities["has_external_succ"]
    started = activities["is_started"]

    missing_predecessor = ~has_predecessor & ~started
    missing_successor = ~has_successor
    flagged = activities[missing_predecessor | missing_successor]
    reason = open_end_reason(missing_predecessor, missing_successor)[flagged.index]
    return RuleOutput(
        flagged_activities(flagged, reason=reason), len(flagged), len(activities), checked=activities, funnel=funnel
    )


@rule("p6_02_hard_constraints", "%")
def p6_02_hard_constraints(context) -> RuleOutput:
    """Constrained tasks.
    Counts: constrained / checked
    Excludes: completed tasks, level of effort.
    Constraint types: Mandatory start, Start on, Mandatory finish, Finish on.

    46286: WBS summary, actual-finish and LOE removed; start constraints ignored once started"""
    funnel = _open_not_loe(context)
    activities = funnel.rows
    has_hard_constraint = constrained_by(activities, P6_HARD_CONSTRAINTS, ignore_started_starts=True)

    flagged = activities[has_hard_constraint]
    return RuleOutput(
        flagged_activities(flagged, constraint2=flagged["cstr_type2"].map(_CONSTRAINT)),
        len(flagged),
        len(activities),
        checked=activities,
        funnel=funnel,
    )


@rule("p6_03_soft_constraints", "%")
def p6_03_soft_constraints(context) -> RuleOutput:
    """Constrained tasks.
    Counts: constrained / checked
    Excludes: completed tasks, level of effort.
    Constraint types: Start on or before, Start on or after, Finish on or before,
        Finish on or after, As late as possible.

    101248 and 113176: Start on or before / on or after, Finish on or before / on or after, As late as
    possible. 46285 (EPPM): WBS summary, actual-finish and LOE removed; start constraints ignored once
    started (its own soft set, with Start on and Finish on, is EPPM's)"""
    funnel = _open_not_loe(context)
    activities = funnel.rows
    has_soft_constraint = constrained_by(activities, SOFT_CONSTRAINTS, ignore_started_starts=True)

    flagged = activities[has_soft_constraint]
    return RuleOutput(
        flagged_activities(flagged, constraint2=flagged["cstr_type2"].map(_CONSTRAINT)),
        len(flagged),
        len(activities),
        checked=activities,
        funnel=funnel,
    )


@rule("p6_04_large_durations", "%")
def p6_04_large_durations(context, limit_hours: float = LARGE_HOURS) -> RuleOutput:
    """Tasks outside the duration limit.
    Counts: flagged / checked
    Excludes: completed tasks, level of effort, milestones.

    101248: completed, WBS summary and LOE not included; milestones also out, as a P6 Professional
    r22.12 report shows (Ten Six) and EPPM's 46282 states
    """
    funnel = _open_not_loe(context).exclude("milestones", "46282")
    activities = funnel.rows
    remaining_hours = activities["remain_drtn_hr_cnt"]

    flagged = activities[remaining_hours > limit_hours]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)


@rule("p6_05_long_lags", "%", links=True)
def p6_05_long_lags(context, limit_hours: float = LARGE_HOURS) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / checked
    Relationships counted: relationships where predecessor and successor are not both complete.

    46288: links between two actual-finished tasks removed"""
    funnel = _links(context)
    relationships = funnel.rows

    flagged = lag_flagged(relationships, operator.gt, limit_hours)
    return RuleOutput(
        flagged_relationships(flagged), len(flagged), len(relationships), checked=relationships, funnel=funnel
    )


@rule("p6_06_large_float", "%")
def p6_06_large_float(context, limit_hours: float = LARGE_HOURS) -> RuleOutput:
    """Tasks outside the float limit.
    Counts: flagged / checked
    Excludes: completed tasks, level of effort.

    46284: WBS summary, actual-finish and LOE removed"""
    funnel = _open_not_loe(context)
    activities = funnel.rows

    flagged = activities[activities["total_float_hr_cnt"] > limit_hours]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)


@rule("p6_07_relationship_types", "%", links=True)
def p6_07_relationship_types(context) -> RuleOutput:
    """Relationships of another type.
    Counts: of the required type / checked
    Relationships counted: relationships where predecessor and successor are not both complete.
    Counts relationships of type FS; the list shows the others.

    46287: actual = share of FS links in the subset"""
    funnel = _links(context)
    out = share_of_type(funnel.rows, "FS")
    out.funnel = funnel
    return out


@rule("p6_08_lags", "%", links=True)
def p6_08_lags(context) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / checked
    Relationships counted: relationships where predecessor and successor are not both complete.
    Flagged when lag > 0 hours.

    46289"""
    funnel = _links(context)
    relationships = funnel.rows

    flagged = lag_flagged(relationships, operator.gt, 0)
    return RuleOutput(
        flagged_relationships(flagged), len(flagged), len(relationships), checked=relationships, funnel=funnel
    )


@rule("p6_09_negative_lags", "%", links=True)
def p6_09_negative_lags(context) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / checked
    Relationships counted: relationships where predecessor and successor are not both complete.
    Flagged when lag < 0 hours.

    46290: links between two actual-finished tasks removed"""
    funnel = _links(context)
    relationships = funnel.rows

    flagged = lag_flagged(relationships, operator.lt, 0)
    return RuleOutput(
        flagged_relationships(flagged), len(flagged), len(relationships), checked=relationships, funnel=funnel
    )


def _progress_dates(context) -> Funnel:
    """101248, Invalid Progress Dates: completed before the status date, WBS summary and LOE not included."""
    return _activities(context).exclude("loe", "101248").exclude("complete_before_data_date", "101248")


@rule("p6_10a_invalid_progress_before", "%")
def p6_10a_invalid_progress_before(context) -> RuleOutput:
    """Forecast before the status date.
    Counts: with invalid dates / checked
    Excludes: level of effort, tasks completed before the status date.
    An in-progress task is flagged when its remaining early start is before the status date.

    101248: not started, start before the status date; in progress, remaining early start before it.
    P6 Professional 26.8 reports this half of Invalid Progress Dates on its own line, "Invalid Progress
    Before Status Date", with its own target (tests/test_p6_checksched.py)"""
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    funnel = _progress_dates(context)
    activities = funnel.rows
    early_start, _early_finish = forecast_dates(activities)

    # a finish before the data date has its start before it too
    forecast = as_flag(~activities["is_complete"] & (early_start < data_date))
    flagged = activities[forecast]
    return RuleOutput(
        flagged_activities(flagged, reason="forecast before status date"),
        len(flagged),
        len(activities),
        checked=activities,
        funnel=funnel,
    )


@rule("p6_10b_invalid_progress_after", "%")
def p6_10b_invalid_progress_after(context) -> RuleOutput:
    """Actual dates after the status date.
    Counts: with invalid dates / checked
    Excludes: level of effort, tasks completed before the status date.

    101248: in progress, actual start after the status date; completed, actual finish after it. P6
    Professional 26.8 reports this half of Invalid Progress Dates on its own line, "Invalid Progress
    After Status Date", with its own target (tests/test_p6_checksched.py)"""
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    funnel = _progress_dates(context)
    activities = funnel.rows

    flagged = activities[actual_after(activities, data_date)]
    return RuleOutput(
        flagged_activities(flagged, reason="actual after status date"),
        len(flagged),
        len(activities),
        checked=activities,
        funnel=funnel,
    )


@rule("p6_11_resource_cost", "%")
def p6_11_resource_cost(context) -> RuleOutput:
    """Tasks with no resource assignment.
    Counts: without resources / checked
    Excludes: milestones, level of effort.

    46279: WBS summary, milestones and LOE removed (completed tasks stay in); a role assignment counts"""
    funnel = _activities(context).exclude("milestones", "101248").exclude("loe", "101248")
    activities = funnel.rows
    has_resource_or_expense = activities["has_resource"] | activities["has_expense"]

    flagged = activities[~has_resource_or_expense]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)


@rule("p6_12_late_activities", "%", needs_baseline=True)
def p6_12_late_activities(context) -> RuleOutput:
    """Forecast to finish after their baseline finish.
    Counts: late / checked
    Excludes: completed tasks, milestones, level of effort.
    Variance is working time on the task's calendar, as P6's Finish Variance.
    A task with no baseline finish is late when its finish is later than its planned finish.

    101248: milestones, WBS summary and LOE not included; a P6 Professional report checks the Large
    Durations population here, so completed tasks are out too. No baseline counterpart = late when
    the remaining early finish is later than the planned finish. 46278: finish variance in working time"""
    funnel = _activities(context).exclude("complete", "R1").exclude("milestones", "101248").exclude("loe", "101248")
    activities = with_baseline(context.baseline, funnel.rows)
    activities["bl_finish"] = activities["bl_finish"].combine_first(activities["target_end_date"])
    out = late_output(context, activities)
    out.funnel = funnel
    return out


@rule("p6_13_bei", "ratio", needs_baseline=True)
def p6_13_bei(context) -> RuleOutput:
    """Completed tasks against the baseline's tasks.
    Counts: completed / baseline tasks
    Excludes: level of effort, milestones.
    The list shows the tasks due by the status date in the baseline and not completed.

    101248 says baseline tasks finishing before the status date, but a P6 Professional report (R1,
    docs/standards.md) divides by a total equal to its Resources/Cost total: P6 counts every baseline
    task, whatever its finish date. The report wins. Milestones, WBS summary
    and LOE not included on either side"""
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    activities = with_baseline(context.baseline, without(context.snapshot.activities, data_date, ("milestones", "loe")))
    funnel = activity_funnel(context.baseline.snapshot).exclude("milestones", "101248").exclude("loe", "101248")
    baseline_activities = funnel.rows
    completed = int(activities["is_complete"].sum())
    due = activities[as_flag(activities["bl_finish"] <= data_date) & ~activities["is_complete"]]
    total = len(baseline_activities)
    gone = len(set(baseline_activities["task_code"]) - set(context.snapshot.activities["task_code"]))
    note = f"{completed} completed / {total} baseline tasks"
    if gone:
        note += f"; {gone} of them no longer in the schedule"
    index = completed / total if total else None
    return RuleOutput(
        flagged_activities(due, bl_finish=due["bl_finish"]),
        completed,
        total,
        index,
        note,
        checked=baseline_activities,
        counted=activities[activities["is_complete"]],
        funnel=funnel,
    )


@rule("p6_15_out_of_sequence", "%")
def p6_15_out_of_sequence(context) -> RuleOutput:
    """Progressed while a predecessor is still open.
    Counts: out of sequence / tasks
    One row per task and predecessor, as P6 lists them; the count is of tasks.

    P6 Professional report: 'Tasks which are completed or in-progress before their predecessors'.
    Report R1 lists pairs and counts tasks once: each started task has an FS
    predecessor not completed at the status date; started tasks whose predecessor finished late but
    before the status date are not listed. SS: predecessor not started. UNRESOLVED: FF and SF"""
    funnel = _activities(context)
    activities = funnel.rows
    tasks = context.snapshot.by_code
    started = activities[activities["is_started"]]
    links = links_between(context.snapshot.relationships, started.set_index("task_code"), tasks)
    ahead = predecessors_ahead(links, tasks).sort_values(["succ_code", "pred_code"])
    rows = started.drop_duplicates("task_code").set_index("task_code").loc[ahead["succ_code"]].reset_index()
    extra = {"predecessor": ahead["pred_code"].to_numpy(), "type": ahead["type"].to_numpy()}
    out_of_sequence = ahead["succ_code"].nunique()
    return RuleOutput(
        flagged_activities(rows, **extra), out_of_sequence, len(activities), checked=activities, funnel=funnel
    )


@rule("p6_16_dangling_start", "%")
def p6_16_dangling_start(context, ignore_in_progress: bool = True) -> RuleOutput:
    """Start not driven by any predecessor.
    Counts: dangling / tasks
    Counted among: not started tasks that are not milestones, in-progress tasks too when
        'Ignore in-progress activities' is off; the others stay in the denominator.
    A task with no predecessor at all is the Logic check's, not this one's.

    P6 Professional report: 'Tasks with start dates that are not driven by predecessors', against the
    total of tasks; the report lists a task without any predecessor under Logic only. Read as:
    predecessors exist, none of them FS or SS. ``ignore_in_progress``: 113174 'Ignore in-progress
    activities for dangling start activities', checked in R1; Oracle documents no default. Read as: the
    task leaves the numerator, not the denominator. Milestones are out: the report shows 0 for milestones
    with FF / SS logic only. UNRESOLVED: completed tasks are never counted, a reading no Oracle text
    states. UNRESOLVED: a predecessor in another project is not read here (P6-01 lets it pass, 46291);
    Oracle (113174, 101496) does not say how Dangling Start treats it"""
    funnel = _activities(context)
    activities = funnel.rows
    relationships = context.snapshot.relationships
    candidates = activities[~activities["is_complete"] & ~activities["is_milestone"]]
    if ignore_in_progress:
        candidates = candidates[~candidates["is_started"]]
    has_logic = candidates["task_code"].isin(relationships["succ_code"])
    driven = has_driving_predecessor(candidates["task_code"], relationships)
    flagged = candidates[has_logic & ~driven]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)


@rule("p6_17_dangling_finish", "%")
def p6_17_dangling_finish(
    context, ignore_soft_constraints: bool = False, ignore_hard_constraints: bool = False
) -> RuleOutput:
    """Finish that drives no successor.
    Counts: dangling / tasks
    Counted among: not complete tasks that are not milestones, less the constrained tasks the
        dialog options leave out; the others stay in the denominator.
    A task with no successor at all is the Logic check's, not this one's.

    P6 Professional report: 'Tasks with finish dates that do not drive successors', against the total
    of tasks; a task without any successor is listed under Logic only. Read as: successors
    exist, none of them FS or FF. ``ignore_soft_constraints`` / ``ignore_hard_constraints``: 113174
    'Ignore activities with soft constraints' (Start On, Start On or After, Start On or Before, Finish On,
    Finish On or After, Finish On or Before, As Late As Possible) and 'Ignore activities with hard
    constraints' (Mandatory Start, Mandatory Finish); Oracle documents no default. Read as: the primary or
    the secondary constraint is one of them, and the task leaves the numerator, not the denominator.
    UNRESOLVED: completed tasks are never counted, a reading no Oracle text states. UNRESOLVED: a
    successor in another project is not read here (P6-01 lets it pass, 46291); Oracle (113174, 101497)
    does not say how Dangling Finish treats it"""
    funnel = _activities(context)
    activities = funnel.rows
    relationships = context.snapshot.relationships
    candidates = activities[~activities["is_complete"] & ~activities["is_milestone"]]
    ignored = (DANGLING_SOFT_CONSTRAINTS if ignore_soft_constraints else []) + (
        DANGLING_HARD_CONSTRAINTS if ignore_hard_constraints else []
    )
    candidates = candidates[~constrained_by(candidates, ignored, ignore_started_starts=False)]
    has_logic = candidates["task_code"].isin(relationships["pred_code"])
    driving = has_driving_successor(candidates["task_code"], relationships)
    flagged = candidates[has_logic & ~driving]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)


@rule("p6_14_negative_float", "%")
def p6_14_negative_float(context) -> RuleOutput:
    """Tasks outside the float limit.
    Counts: flagged / checked
    Excludes: completed tasks, level of effort.
    Flagged when total float < 0 hours.

    46283: WBS summary, actual-finish and LOE removed"""
    funnel = _open_not_loe(context)
    activities = funnel.rows

    flagged = activities[activities["total_float_hr_cnt"] < 0]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)
