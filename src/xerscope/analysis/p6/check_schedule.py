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
    actual_after,
    as_flag,
    constrained_by,
    flagged_activities,
    flagged_relationships,
    has_predecessor_in_project,
    has_successor_in_project,
    invalid_date_reason,
    lag_flagged,
    open_activities,
    open_end_reason,
    with_baseline,
    without_level_of_effort,
    without_milestones,
)
from ..rules import (
    RuleOutput,
    bei_from_baseline,
    late_output,
    link_population,
    rule,
    share_of_type,
)

P6_HARD_CONSTRAINTS = ["CS_MANDSTART", "CS_MSO", "CS_MANDFIN", "CS_MEO"]
SOFT_CONSTRAINTS = ["CS_MSOB", "CS_MSOA", "CS_MEOB", "CS_MEOA", "CS_ALAP"]


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
    activities = open_activities(context)
    has_predecessor = has_predecessor_in_project(context, activities) | activities["has_external_pred"]
    has_successor = has_successor_in_project(context, activities) | activities["has_external_succ"]
    started = activities["is_started"]
    start_milestone = activities["is_start_milestone"]

    missing_predecessor = ~has_predecessor & ~started & ~start_milestone
    missing_successor = ~has_successor
    flagged = activities[missing_predecessor | missing_successor]
    reason = open_end_reason(missing_predecessor, missing_successor)[flagged.index]
    return RuleOutput(flagged_activities(flagged, reason=reason), len(flagged), len(activities))


@rule("p6_02_hard_constraints", "%")
def p6_02_hard_constraints(context) -> RuleOutput:
    """Constrained activities.
    Counts: constrained / checked
    Excludes: completed activities, level of effort.
    Constraint types: Mandatory start, Start on, Mandatory finish, Finish on.

    46286: WBS summary, actual-finish and LOE removed; start constraints ignored once started"""
    activities = without_level_of_effort(open_activities(context))
    has_hard_constraint = constrained_by(activities, P6_HARD_CONSTRAINTS, ignore_started_starts=True)

    flagged = activities[has_hard_constraint]
    return RuleOutput(
        flagged_activities(flagged, constraint2=flagged["cstr_type2"].map(_CONSTRAINT)), len(flagged), len(activities)
    )


@rule("p6_03_soft_constraints", "%")
def p6_03_soft_constraints(context) -> RuleOutput:
    """Constrained activities.
    Counts: constrained / checked
    Excludes: completed activities, level of effort.
    Constraint types: Start on or before, Start on or after, Finish on or before,
        Finish on or after, As late as possible.

    46285: Start on or before / on or after, Finish on or before / on or after, As late as possible"""
    activities = without_level_of_effort(open_activities(context))
    has_soft_constraint = constrained_by(activities, SOFT_CONSTRAINTS, ignore_started_starts=True)

    flagged = activities[has_soft_constraint]
    return RuleOutput(
        flagged_activities(flagged, constraint2=flagged["cstr_type2"].map(_CONSTRAINT)), len(flagged), len(activities)
    )


@rule("p6_04_large_durations", "%")
def p6_04_large_durations(context) -> RuleOutput:
    """Activities outside the duration limit.
    Counts: flagged / checked
    Excludes: completed activities, level of effort, milestones.
    Flagged when remaining duration > 352 hours.

    101248: completed, WBS summary and LOE not included; milestones also out, as a P6 Professional
    r22.12 report shows (Ten Six) and EPPM's 46282 states
    """
    activities = without_milestones(without_level_of_effort(open_activities(context)))
    remaining_hours = activities["remain_drtn_hr_cnt"]

    flagged = activities[remaining_hours > LARGE_HOURS]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities))


@rule("p6_05_long_lags", "%", links=True)
def p6_05_long_lags(context) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / checked
    Relationships counted: relationships where predecessor and successor are not both complete.
    Flagged when lag > 352 hours.

    46288: links between two actual-finished activities removed"""
    relationships = link_population(context, "not_both_complete")

    flagged = lag_flagged(relationships, operator.gt, LARGE_HOURS)
    return RuleOutput(flagged_relationships(flagged), len(flagged), len(relationships))


@rule("p6_06_large_float", "%")
def p6_06_large_float(context) -> RuleOutput:
    """Activities outside the float limit.
    Counts: flagged / checked
    Excludes: completed activities, level of effort.
    Flagged when total float > 352 hours.

    46284: WBS summary, actual-finish and LOE removed"""
    activities = without_level_of_effort(open_activities(context))

    flagged = activities[activities["total_float_hr_cnt"] > LARGE_HOURS]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities))


@rule("p6_07_relationship_types", "%", links=True)
def p6_07_relationship_types(context) -> RuleOutput:
    """Relationships of another type.
    Counts: of the required type / checked
    Relationships counted: relationships where predecessor and successor are not both complete.
    Counts relationships of type FS; the list shows the others.

    46287: actual = share of FS links in the subset"""
    return share_of_type(link_population(context, "not_both_complete"), "FS")


@rule("p6_08_lags", "%", links=True)
def p6_08_lags(context) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / checked
    Relationships counted: relationships where predecessor and successor are not both complete.
    Flagged when lag > 0 hours.

    46289"""
    relationships = link_population(context, "not_both_complete")

    flagged = lag_flagged(relationships, operator.gt, 0)
    return RuleOutput(flagged_relationships(flagged), len(flagged), len(relationships))


@rule("p6_09_negative_lags", "%", links=True)
def p6_09_negative_lags(context) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / checked
    Relationships counted: relationships where predecessor and successor are not both complete.
    Flagged when lag < 0 hours.

    46290: links between two actual-finished activities removed"""
    relationships = link_population(context, "not_both_complete")

    flagged = lag_flagged(relationships, operator.lt, 0)
    return RuleOutput(flagged_relationships(flagged), len(flagged), len(relationships))


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
    activities = without_level_of_effort(context.snapshot.activities)
    activities = activities[~(activities["act_end_date"] < data_date)]
    early_start, _early_finish = forecast_dates(activities)

    # a finish before the data date has its start before it too
    forecast = as_flag(~activities["is_complete"] & (early_start < data_date))
    actual = actual_after(activities, data_date)
    invalid = forecast | actual
    flagged = activities[invalid]
    reasons = invalid_date_reason(forecast, actual)[invalid]
    return RuleOutput(flagged_activities(flagged, reason=reasons), len(flagged), len(activities))


@rule("p6_11_resource_cost", "%")
def p6_11_resource_cost(context) -> RuleOutput:
    """Activities with no resource assignment.
    Counts: without resources / checked
    Excludes: milestones, level of effort.

    46279: WBS summary, milestones and LOE removed (completed activities stay in); a role assignment counts"""
    activities = without_level_of_effort(without_milestones(context.snapshot.activities))
    has_resource_or_expense = activities["has_resource"] | activities["has_expense"]

    flagged = activities[~has_resource_or_expense]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities))


@rule("p6_12_late_activities", "%", needs_baseline=True)
def p6_12_late_activities(context) -> RuleOutput:
    """Forecast to finish after their baseline finish.
    Counts: late / checked
    Excludes: milestones, level of effort.
    Variance is working time on the activity's calendar, as P6's Finish Variance.
    An activity with no baseline finish is late when its finish is later than its planned finish.

    101248: milestones, WBS summary and LOE not included (completed stay in); no baseline counterpart =
    late when the remaining early finish is later than the planned finish. 46278: finish variance in
    working time"""
    activities = without_level_of_effort(without_milestones(context.snapshot.activities))
    activities = with_baseline(context, activities)
    activities["bl_finish"] = activities["bl_finish"].combine_first(activities["target_end_date"])
    return late_output(context, activities)


@rule("p6_13_bei", "ratio", needs_baseline=True)
def p6_13_bei(context) -> RuleOutput:
    """Due by the data date but not completed.
    Counts: completed / due by the data date
    Excludes: level of effort, milestones.
    Due = baseline activities finishing on or before the data date, counted in the baseline:
        an activity added since is never due, one deleted since still is.
        Completed = all completed activities in the population, early ones included.

    101248: completed activities of the open project / baseline activities finishing before its data
    date; milestones, WBS summary and LOE not included on either side (EPPM's 46277 instead counts an
    activity with no baseline finish as due)"""
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no data date")
    activities = with_baseline(context, without_level_of_effort(without_milestones(context.snapshot.activities)))
    baseline_activities = without_level_of_effort(without_milestones(context.baseline.snapshot.activities))
    return bei_from_baseline(context, activities, baseline_activities)


@rule("p6_14_negative_float", "%")
def p6_14_negative_float(context) -> RuleOutput:
    """Activities outside the float limit.
    Counts: flagged / checked
    Excludes: completed activities, level of effort.
    Flagged when total float < 0 hours.

    46283: WBS summary, actual-finish and LOE removed"""
    activities = without_level_of_effort(open_activities(context))

    flagged = activities[activities["total_float_hr_cnt"] < 0]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities))
