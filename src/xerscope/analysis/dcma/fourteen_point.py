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

_RELATIONSHIP_POPULATION_NOTES = [
    "Relationships whose successor is excluded: level of effort, milestones.",
    "Relationships counted: relationships into an incomplete successor.",
]


def _relationships_into_open_tasks(ctx) -> pd.DataFrame:
    """PAM 200.1 section 4.0: a link counts when its successor is an incomplete, non-LOE, non-milestone task."""
    open_tasks = without_milestones(without_level_of_effort(open_activities(ctx)))
    return relationships_into(ctx, open_tasks)


@rule(
    "dcma_01_logic",
    "%",
    wording=("open-ended", "checked", "Missing a predecessor or a successor"),
    notes=lambda _: ["Excludes: completed activities, level of effort, milestones."],
)
def dcma_01_logic(ctx) -> RuleOutput:
    """DCMA-EA PAM 200.1 §4.1: any incomplete task missing a predecessor and/or a successor; no project
    start/finish exemption and no dangling case; §4.0: milestones excluded; a link to another project
    counts as logic (rule default)
    """
    tasks = without_milestones(without_level_of_effort(open_activities(ctx)))
    has_predecessor = has_predecessor_in_project(ctx, tasks) | tasks["has_external_pred"]
    has_successor = has_successor_in_project(ctx, tasks) | tasks["has_external_succ"]

    missing_predecessor = ~has_predecessor
    missing_successor = ~has_successor
    flagged = tasks[missing_predecessor | missing_successor]
    reason = open_end_reason(missing_predecessor, missing_successor)[flagged.index]
    return RuleOutput(flagged_activities(flagged, reason=reason), len(flagged), len(tasks))


@rule(
    "dcma_02_leads",
    "%",
    wording=("flagged", "relationships checked", "Relationships with the lag in question"),
    links=True,
    notes=lambda _: [*_RELATIONSHIP_POPULATION_NOTES, "Flagged when lag < 0 hours."],
)
def dcma_02_leads(ctx) -> RuleOutput:
    """DCMA-EA PAM 200.1 §4.2: logic links with a lead (negative lag) in predecessor relationships for
    incomplete tasks; §4.0: completed, LOE, summary tasks and milestones are excluded, so a link counts
    when its successor is kept
    """
    relationships = _relationships_into_open_tasks(ctx)
    lag_hours = relationships["lag_hr"].fillna(0)

    leads = relationships[lag_hours < 0]
    return RuleOutput(flagged_relationships(leads), len(leads), len(relationships))


@rule(
    "dcma_03_lags",
    "%",
    wording=("flagged", "relationships checked", "Relationships with the lag in question"),
    links=True,
    notes=lambda _: [*_RELATIONSHIP_POPULATION_NOTES, "Flagged when lag > 0 hours."],
)
def dcma_03_lags(ctx) -> RuleOutput:
    """DCMA-EA PAM 200.1 §4.3: lags in predecessor logic relationships for incomplete tasks; §4.0:
    completed, LOE, summary tasks and milestones are excluded, so a link counts when its successor is
    kept
    """
    relationships = _relationships_into_open_tasks(ctx)
    lag_hours = relationships["lag_hr"].fillna(0)

    lags = relationships[lag_hours > 0]
    return RuleOutput(flagged_relationships(lags), len(lags), len(relationships))


@rule(
    "dcma_04_relationship_types",
    "%",
    wording=("of the required type", "relationships checked", "Relationships of another type"),
    links=True,
    notes=lambda _: [*_RELATIONSHIP_POPULATION_NOTES, "Counts relationships of type FS; the list shows the others."],
)
def dcma_04_relationship_types(ctx) -> RuleOutput:
    """DCMA-EA PAM 200.1 §4.4: a count of incomplete tasks containing each type of logic link; §4.0:
    completed, LOE, summary tasks and milestones are excluded, so a link counts when its successor is
    kept
    """
    relationships = _relationships_into_open_tasks(ctx)
    finish_to_start = relationships["type"] == "FS"

    share = 100.0 * finish_to_start.sum() / len(relationships) if len(relationships) else None
    type_mix = ", ".join(f"{kind} {n}" for kind, n in relationships["type"].value_counts().items())
    other_types = relationships[~finish_to_start]
    return RuleOutput(
        flagged_relationships(other_types), int(finish_to_start.sum()), len(relationships), share, note=type_mix
    )
