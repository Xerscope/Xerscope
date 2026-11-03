"""P6 Professional 24 Check Schedule: one function per check, reading like the Oracle text.

The Oracle pages are cited in each docstring. Threshold and pass/fail come from
``standards/p6.toml``; the function only decides which activities are flagged.
"""

from __future__ import annotations

import operator

from ...xer.model import CONSTRAINT as _CONSTRAINT
from ...xer.model import forecast_dates
from ..populations import (
    LARGE_HOURS,
    Funnel,
    actual_after,
    as_flag,
    constrained_by,
    flagged_activities,
    flagged_relationships,
    has_driving_predecessor,
    has_driving_successor,
    has_predecessor_in_project,
    has_successor_in_project,
    invalid_date_reason,
    lag_flagged,
    links_between,
    not_complete,
    not_level_of_effort,
    not_milestone,
    open_end_reason,
    predecessors_ahead,
    with_baseline,
    without_level_of_effort,
    without_milestones,
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


def _activities(context) -> Funnel:
    """Every activity of the file (WBS summaries are never activities)."""
    return Funnel(context.snapshot.activities)


def _open(context) -> Funnel:
    return _activities(context).keep("not complete", "101248", not_complete)


def _open_not_loe(context) -> Funnel:
    return _open(context).keep("not level of effort", "101248", not_level_of_effort)


def _links(context) -> Funnel:
    return link_funnel(context, "not_both_complete", source="101248")


@rule("p6_01_logic", "%")
def p6_01_logic(context) -> RuleOutput:
    """Missing a predecessor or a successor.
    Counts: open-ended / checked
    Excludes: completed activities.
    No predecessor required for: started activities, start milestones.

    101248: completed and WBS summary activities not included; started activities and start milestones
    need no predecessor; a finish milestone without successor is counted, as a P6 Professional r22.12
    report shows (Ten Six); external links pass (46291)
    """
    funnel = _open(context)
    activities = funnel.rows
    has_predecessor = has_predecessor_in_project(context, activities) | activities["has_external_pred"]
    has_successor = has_successor_in_project(context, activities) | activities["has_external_succ"]
    started = activities["is_started"]
    start_milestone = activities["is_start_milestone"]

    missing_predecessor = ~has_predecessor & ~started & ~start_milestone
    missing_successor = ~has_successor
    flagged = activities[missing_predecessor | missing_successor]
    reason = open_end_reason(missing_predecessor, missing_successor)[flagged.index]
    return RuleOutput(
        flagged_activities(flagged, reason=reason), len(flagged), len(activities), checked=activities, funnel=funnel
    )


@rule("p6_02_hard_constraints", "%")
def p6_02_hard_constraints(context) -> RuleOutput:
    """Constrained activities.
    Counts: constrained / checked
    Excludes: completed activities, level of effort.
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
    """Constrained activities.
    Counts: constrained / checked
    Excludes: completed activities, level of effort.
    Constraint types: Start on or before, Start on or after, Finish on or before,
        Finish on or after, As late as possible.

    46285: Start on or before / on or after, Finish on or before / on or after, As late as possible"""
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
    """Activities outside the duration limit.
    Counts: flagged / checked
    Excludes: completed activities, level of effort, milestones.

    101248: completed, WBS summary and LOE not included; milestones also out, as a P6 Professional
    r22.12 report shows (Ten Six) and EPPM's 46282 states
    """
    funnel = _open_not_loe(context).keep("not milestone", "46282", not_milestone)
    activities = funnel.rows
    remaining_hours = activities["remain_drtn_hr_cnt"]

    flagged = activities[remaining_hours > limit_hours]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)


@rule("p6_05_long_lags", "%", links=True)
def p6_05_long_lags(context, limit_hours: float = LARGE_HOURS) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / checked
    Relationships counted: relationships where predecessor and successor are not both complete.

    46288: links between two actual-finished activities removed"""
    funnel = _links(context)
    relationships = funnel.rows

    flagged = lag_flagged(relationships, operator.gt, limit_hours)
    return RuleOutput(
        flagged_relationships(flagged), len(flagged), len(relationships), checked=relationships, funnel=funnel
    )


@rule("p6_06_large_float", "%")
def p6_06_large_float(context, limit_hours: float = LARGE_HOURS) -> RuleOutput:
    """Activities outside the float limit.
    Counts: flagged / checked
    Excludes: completed activities, level of effort.

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

    46290: links between two actual-finished activities removed"""
    funnel = _links(context)
    relationships = funnel.rows

    flagged = lag_flagged(relationships, operator.lt, 0)
    return RuleOutput(
        flagged_relationships(flagged), len(flagged), len(relationships), checked=relationships, funnel=funnel
    )


@rule("p6_10_invalid_progress_dates", "%")
def p6_10_invalid_progress_dates(context) -> RuleOutput:
    """Progress dates on the wrong side of the data date.
    Counts: with invalid dates / checked
    Excludes: level of effort, activities completed before the data date.
    An in-progress activity is flagged when its remaining early start is before the data date.

    101248: not started, start before the data date; in progress, remaining early start before it or
    actual start after it; completed, actual finish after it. Completed before the data date, WBS
    summary and LOE not included"""
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no data date")
    funnel = _activities(context).keep("not level of effort", "101248", not_level_of_effort)
    funnel.keep("not completed before the data date", "101248", lambda rows: ~(rows["act_end_date"] < data_date))
    activities = funnel.rows
    early_start, _early_finish = forecast_dates(activities)

    # a finish before the data date has its start before it too
    forecast = as_flag(~activities["is_complete"] & (early_start < data_date))
    actual = actual_after(activities, data_date)
    invalid = forecast | actual
    flagged = activities[invalid]
    reasons = invalid_date_reason(forecast, actual)[invalid]
    return RuleOutput(
        flagged_activities(flagged, reason=reasons), len(flagged), len(activities), checked=activities, funnel=funnel
    )


@rule("p6_11_resource_cost", "%")
def p6_11_resource_cost(context) -> RuleOutput:
    """Activities with no resource assignment.
    Counts: without resources / checked
    Excludes: milestones, level of effort.

    46279: WBS summary, milestones and LOE removed (completed activities stay in); a role assignment counts"""
    funnel = _activities(context).keep("not milestone", "101248", not_milestone)
    activities = funnel.keep("not level of effort", "101248", not_level_of_effort).rows
    has_resource_or_expense = activities["has_resource"] | activities["has_expense"]

    flagged = activities[~has_resource_or_expense]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)


@rule("p6_12_late_activities", "%", needs_baseline=True)
def p6_12_late_activities(context) -> RuleOutput:
    """Forecast to finish after their baseline finish.
    Counts: late / checked
    Excludes: completed activities, milestones, level of effort.
    Variance is working time on the activity's calendar, as P6's Finish Variance.
    An activity with no baseline finish is late when its finish is later than its planned finish.

    101248: milestones, WBS summary and LOE not included; a P6 Professional report checks the Large
    Durations population here, so completed activities are out too. No baseline counterpart = late when
    the remaining early finish is later than the planned finish. 46278: finish variance in working time"""
    funnel = _activities(context).keep("not complete", "R1", not_complete)
    funnel.keep("not milestone", "101248", not_milestone).keep("not level of effort", "101248", not_level_of_effort)
    activities = with_baseline(context, funnel.rows)
    activities["bl_finish"] = activities["bl_finish"].combine_first(activities["target_end_date"])
    out = late_output(context, activities)
    out.funnel = funnel
    return out


@rule("p6_13_bei", "ratio", needs_baseline=True)
def p6_13_bei(context) -> RuleOutput:
    """Completed activities against the baseline's activities.
    Counts: completed / baseline activities
    Excludes: level of effort, milestones.
    The list shows the activities due by the data date in the baseline and not completed.

    101248 says baseline activities finishing before the data date, but a P6 Professional report (R1,
    docs/standards.md) divides by a total equal to its Resources/Cost total: P6 counts every baseline
    activity, whatever its finish date. The report wins. Milestones, WBS summary
    and LOE not included on either side"""
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no data date")
    activities = with_baseline(context, without_level_of_effort(without_milestones(context.snapshot.activities)))
    funnel = Funnel(context.baseline.snapshot.activities).keep("not milestone", "101248", not_milestone)
    baseline_activities = funnel.keep("not level of effort", "101248", not_level_of_effort).rows
    completed = int(activities["is_complete"].sum())
    due = activities[as_flag(activities["bl_finish"] <= data_date) & ~activities["is_complete"]]
    total = len(baseline_activities)
    gone = len(set(baseline_activities["task_code"]) - set(context.snapshot.activities["task_code"]))
    note = f"{completed} completed / {total} baseline activities"
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
    Counts: out of sequence / activities
    One row per activity and predecessor, as P6 lists them; the count is of activities.

    P6 Professional report: 'Activities which are completed or in-progress before their predecessors'.
    Report R1 lists pairs and counts activities once: each started activity has an FS
    predecessor not completed at the data date; started activities whose predecessor finished late but
    before the data date are not listed. SS: predecessor not started. UNRESOLVED: FF and SF"""
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
def p6_16_dangling_start(context) -> RuleOutput:
    """Start not driven by any predecessor.
    Counts: dangling / activities
    Counted among: not started activities that are not milestones (P6's 'Ignore In Progress
        Activities', checked); the others stay in the denominator.
    An activity with no predecessor at all is the Logic check's, not this one's.

    P6 Professional report: 'Activities with start dates that are not driven by predecessors', against the
    total of activities; the report lists an activity without any predecessor under Logic only. Read as:
    predecessors exist, none of them FS or SS. UNRESOLVED: 'Ignore activities with soft/hard constraints'
    (unchecked by default) is not read. Milestones are out: the report shows 0 for milestones with FF / SS
    logic only"""
    funnel = _activities(context)
    activities = funnel.rows
    relationships = context.snapshot.relationships
    candidates = activities[~activities["is_started"] & ~activities["is_milestone"]]
    has_logic = candidates["task_code"].isin(relationships["succ_code"])
    driven = has_driving_predecessor(candidates["task_code"], relationships)
    flagged = candidates[has_logic & ~driven]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)


@rule("p6_17_dangling_finish", "%")
def p6_17_dangling_finish(context) -> RuleOutput:
    """Finish that drives no successor.
    Counts: dangling / activities
    Counted among: not complete activities that are not milestones; the others stay in the
        denominator.
    An activity with no successor at all is the Logic check's, not this one's.

    P6 Professional report: 'Activities with finish dates that do not drive successors', against the total
    of activities; an activity without any successor is listed under Logic only. Read as: successors
    exist, none of them FS or FF"""
    funnel = _activities(context)
    activities = funnel.rows
    relationships = context.snapshot.relationships
    candidates = activities[~activities["is_complete"] & ~activities["is_milestone"]]
    has_logic = candidates["task_code"].isin(relationships["pred_code"])
    driving = has_driving_successor(candidates["task_code"], relationships)
    flagged = candidates[has_logic & ~driving]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)


@rule("p6_14_negative_float", "%")
def p6_14_negative_float(context) -> RuleOutput:
    """Activities outside the float limit.
    Counts: flagged / checked
    Excludes: completed activities, level of effort.
    Flagged when total float < 0 hours.

    46283: WBS summary, actual-finish and LOE removed"""
    funnel = _open_not_loe(context)
    activities = funnel.rows

    flagged = activities[activities["total_float_hr_cnt"] < 0]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)
