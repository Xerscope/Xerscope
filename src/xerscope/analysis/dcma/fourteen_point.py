"""DCMA 14-Point Schedule Assessment (DCMA-EA PAM 200.1, Oct 2012): one function per check.

Section 4.0 sets the population: incomplete tasks, without LOE and milestones. Threshold
and pass/fail come from ``standards/dcma.toml``; the function only decides what is flagged.
"""

from __future__ import annotations

import pandas as pd

from ..populations import (
    flagged_activities,
    flagged_relationships,
    has_predecessor_in_project,
    has_successor_in_project,
    open_activities,
    open_end_reason,
    relationships_into,
    without_level_of_effort,
    without_milestones,
)
from ..rules import RuleOutput, rule


def _relationships_into_open_tasks(context) -> pd.DataFrame:
    """PAM 200.1 section 4.0: a link counts when its successor is an incomplete, non-LOE, non-milestone task."""
    open_tasks = without_milestones(without_level_of_effort(open_activities(context)))
    return relationships_into(context, open_tasks)


@rule("dcma_01_logic", "%")
def dcma_01_logic(context) -> RuleOutput:
    """Missing a predecessor or a successor.
    Counts: open-ended / checked
    Excludes: completed activities, level of effort, milestones.

    DCMA-EA PAM 200.1 §4.1: any incomplete task missing a predecessor and/or a successor; no project
    start/finish exemption and no dangling case; §4.0: milestones excluded; a link to another project
    counts as logic (rule default)
    """
    tasks = without_milestones(without_level_of_effort(open_activities(context)))
    has_predecessor = has_predecessor_in_project(context, tasks) | tasks["has_external_pred"]
    has_successor = has_successor_in_project(context, tasks) | tasks["has_external_succ"]

    missing_predecessor = ~has_predecessor
    missing_successor = ~has_successor
    flagged = tasks[missing_predecessor | missing_successor]
    reason = open_end_reason(missing_predecessor, missing_successor)[flagged.index]
    return RuleOutput(flagged_activities(flagged, reason=reason), len(flagged), len(tasks))


@rule("dcma_02_leads", "%")
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
    relationships = _relationships_into_open_tasks(context)
    lag_hours = relationships["lag_hr"].fillna(0)

    leads = relationships[lag_hours < 0]
    return RuleOutput(flagged_relationships(leads), len(leads), len(relationships))


@rule("dcma_03_lags", "%")
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
    relationships = _relationships_into_open_tasks(context)
    lag_hours = relationships["lag_hr"].fillna(0)

    lags = relationships[lag_hours > 0]
    return RuleOutput(flagged_relationships(lags), len(lags), len(relationships))


@rule("dcma_04_relationship_types", "%")
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
    relationships = _relationships_into_open_tasks(context)
    finish_to_start = relationships["type"] == "FS"

    share = 100.0 * finish_to_start.sum() / len(relationships) if len(relationships) else None
    type_mix = ", ".join(f"{kind} {n}" for kind, n in relationships["type"].value_counts().items())
    other_types = relationships[~finish_to_start]
    return RuleOutput(
        flagged_relationships(other_types), int(finish_to_start.sum()), len(relationships), share, note=type_mix
    )
