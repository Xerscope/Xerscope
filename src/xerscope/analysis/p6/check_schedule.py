"""P6 Professional 24 Check Schedule: one function per check, reading like the Oracle text.

The Oracle pages are cited in each docstring. Threshold and pass/fail come from
``standards/p6.toml``; the function only decides which activities are flagged.
"""

from __future__ import annotations

from ...xer.model import CONSTRAINT as _CONSTRAINT
from ..populations import (
    constrained_by,
    flagged_activities,
    has_predecessor_in_project,
    has_successor_in_project,
    open_activities,
    open_end_reason,
    without_level_of_effort,
    without_milestones,
)
from ..rules import RuleOutput, rule

HARD_CONSTRAINTS = ["CS_MANDSTART", "CS_MSO", "CS_MANDFIN", "CS_MEO"]
SOFT_CONSTRAINTS = ["CS_MSOB", "CS_MSOA", "CS_MEOB", "CS_MEOA", "CS_ALAP"]
LARGE_DURATION_HOURS = 352


@rule(
    "p6_01_logic",
    "%",
    wording=("open-ended", "checked", "Missing a predecessor or a successor"),
    notes=lambda _: [
        "Excludes: completed activities.",
        "No predecessor required for: started activities, start milestones.",
    ],
)
def p6_01_logic(ctx) -> RuleOutput:
    """101248: completed and WBS summary activities not included; started activities and start milestones
    need no predecessor; a finish milestone without successor is counted, as a P6 Professional r22.12
    report shows (Ten Six); external links pass (46291)
    """
    activities = open_activities(ctx)
    has_predecessor = has_predecessor_in_project(ctx, activities) | activities["has_external_pred"]
    has_successor = has_successor_in_project(ctx, activities) | activities["has_external_succ"]
    started = activities["is_started"]
    start_milestone = activities["is_start_milestone"]

    missing_predecessor = ~has_predecessor & ~started & ~start_milestone
    missing_successor = ~has_successor
    flagged = activities[missing_predecessor | missing_successor]
    reason = open_end_reason(missing_predecessor, missing_successor)[flagged.index]
    return RuleOutput(flagged_activities(flagged, reason=reason), len(flagged), len(activities))


@rule(
    "p6_02_hard_constraints",
    "%",
    wording=("constrained", "checked", "Constrained activities"),
    notes=lambda _: [
        "Excludes: completed activities, level of effort.",
        "Constraint types: Mandatory start, Start on, Mandatory finish, Finish on.",
    ],
)
def p6_02_hard_constraints(ctx) -> RuleOutput:
    """46286: WBS summary, actual-finish and LOE removed; start constraints ignored once started"""
    activities = without_level_of_effort(open_activities(ctx))
    has_hard_constraint = constrained_by(activities, HARD_CONSTRAINTS, ignore_started_starts=True)

    flagged = activities[has_hard_constraint]
    return RuleOutput(
        flagged_activities(flagged, constraint2=flagged["cstr_type2"].map(_CONSTRAINT)), len(flagged), len(activities)
    )


@rule(
    "p6_03_soft_constraints",
    "%",
    wording=("constrained", "checked", "Constrained activities"),
    notes=lambda _: [
        "Excludes: completed activities, level of effort.",
        "Constraint types: Start on or before, Start on or after, Finish on or before, "
        "Finish on or after, As late as possible.",
    ],
)
def p6_03_soft_constraints(ctx) -> RuleOutput:
    """46285: Start on or before / on or after, Finish on or before / on or after, As late as possible"""
    activities = without_level_of_effort(open_activities(ctx))
    has_soft_constraint = constrained_by(activities, SOFT_CONSTRAINTS, ignore_started_starts=True)

    flagged = activities[has_soft_constraint]
    return RuleOutput(
        flagged_activities(flagged, constraint2=flagged["cstr_type2"].map(_CONSTRAINT)), len(flagged), len(activities)
    )


@rule(
    "p6_04_large_durations",
    "%",
    wording=("flagged", "checked", "Activities outside the duration limit"),
    notes=lambda _: [
        "Excludes: completed activities, level of effort, milestones.",
        "Flagged when remaining duration > 352 hours.",
    ],
)
def p6_04_large_durations(ctx) -> RuleOutput:
    """101248: completed, WBS summary and LOE not included; milestones also out, as a P6 Professional
    r22.12 report shows (Ten Six) and EPPM's 46282 states
    """
    activities = without_milestones(without_level_of_effort(open_activities(ctx)))
    remaining_hours = activities["remain_drtn_hr_cnt"]

    flagged = activities[(remaining_hours > LARGE_DURATION_HOURS).fillna(False)]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities))
