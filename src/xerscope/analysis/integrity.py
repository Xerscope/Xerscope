"""Integrity: is the file what P6 would calculate from its own logic? One function per check.

Not a published standard: checks that make the other standards trustworthy. Thresholds
come from ``standards/integrity.toml``.
"""

from __future__ import annotations

import pandas as pd

from .cpm import CycleError, compare_assignments, compare_with_stored
from .populations import flagged_activities, without_level_of_effort
from .rules import RuleOutput, rule

STORED_FIELDS = ["early_start_date", "early_end_date", "late_start_date", "late_end_date", "total_float_hr_cnt"]


@rule("int_01_recalculated", "%")
def int_01_recalculated(context) -> RuleOutput:
    """Stored dates differ from the recalculation.
    Counts: different / open activities

    Open activities whose stored dates or float differ from a P6-style recalculation.

    A difference means the file was edited after the last F9, or uses a scheduling
    feature xerscope does not model (see analysis/cpm.py). Exact to the minute.
    """
    try:
        comparison = compare_with_stored(context.snapshot)
    except CycleError as exc:
        return RuleOutput(note=f"cannot schedule: {exc}")
    comparison = comparison[comparison["field"].isin(STORED_FIELDS) & comparison["stored"].notna()]
    if comparison.empty:
        return RuleOutput(numerator=0, denominator=0, note="no stored dates to compare")
    differences: dict[str, list[str]] = {}
    columns = ["task_code", "field", "stored", "computed", "agree"]
    for task_code, field_name, stored, computed, agrees in comparison[columns].itertuples(index=False):
        if not agrees:
            differences.setdefault(task_code, []).append(f"{field_name}: {stored} -> {computed}")
    tasks = context.snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    flagged = tasks.loc[sorted(differences)].reset_index()
    texts = ["; ".join(differences[task_code]) for task_code in flagged["task_code"]]
    different_values = sum(len(found) for found in differences.values())
    return RuleOutput(
        flagged_activities(flagged, differences=texts),
        len(differences),
        comparison["task_code"].nunique(),
        note=f"{len(comparison) - different_values} of {len(comparison)} stored values reproduced",
    )


@rule("int_02_out_of_sequence_progress", "count")
def int_02_out_of_sequence_progress(context) -> RuleOutput:
    """Progressed out of logic sequence.
    Counts: out of sequence /
    Excludes: level of effort.

    Started activities whose FS predecessor had not finished, or SS predecessor not started, at their
    actual start (P6 lists them in its scheduling log). Counts activities.
    """
    activities = without_level_of_effort(context.snapshot.activities)
    tasks = context.snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    started = activities[activities["is_started"]].drop_duplicates("task_code").set_index("task_code")
    relationships = context.snapshot.relationships
    relationships = relationships[
        relationships["succ_code"].isin(started.index) & relationships["pred_code"].isin(tasks.index)
    ]
    ahead_of: dict[str, list[str]] = {}
    columns = ["pred_code", "succ_code", "type"]
    for predecessor, successor, link_type in relationships[columns].itertuples(index=False):
        start = started.at[successor, "act_start_date"]
        predecessor_finish = tasks.at[predecessor, "act_end_date"]
        predecessor_start = tasks.at[predecessor, "act_start_date"]
        finish_after = link_type == "FS" and (pd.isna(predecessor_finish) or predecessor_finish > start)
        start_after = link_type == "SS" and (pd.isna(predecessor_start) or predecessor_start > start)
        if finish_after or start_after:
            ahead_of.setdefault(successor, []).append(f"{predecessor} ({link_type})")
    flagged = started.loc[sorted(ahead_of)].reset_index()
    texts = [", ".join(ahead_of[task_code]) for task_code in flagged["task_code"]]
    return RuleOutput(flagged_activities(flagged, ahead_of=texts), len(flagged), len(started))


def _describe_differences(group: pd.DataFrame) -> str:
    """One assignment's stored-vs-recalculated fields as 'field: stored -> computed; ...'."""
    pairs = group[["field", "stored", "computed"]].itertuples(index=False)
    return "; ".join(f"{field_name}: {stored} -> {computed}" for field_name, stored, computed in pairs)


@rule("int_03_assignments_recalculated", "%")
def int_03_assignments_recalculated(context) -> RuleOutput:
    """Assignment dates differ from the recalculation.
    Counts: different / open assignments

    Open resource assignments whose stored remaining early/late dates differ from a recalculation.

    Same idea as ``int_01_recalculated``, on TASKRSRC: activity dates + assignment lag, duration
    = remaining units / units per hour, on the resource's calendar for resource-dependent
    activities.
    """
    try:
        comparison = compare_assignments(context.snapshot)
    except CycleError as exc:
        return RuleOutput(note=f"cannot schedule: {exc}")
    comparison = comparison[comparison["stored"].notna()]
    if comparison.empty:
        return RuleOutput(numerator=0, denominator=0, note="no stored assignment dates to compare")
    different = comparison[~comparison["agree"]]
    flagged = pd.DataFrame()
    if not different.empty:
        by_assignment = different.groupby("taskrsrc_id")
        flagged = pd.DataFrame(
            {
                "task_code": by_assignment["task_code"].first(),
                "resource": by_assignment["rsrc"].first(),
                "differences": by_assignment.apply(_describe_differences, include_groups=False),
            }
        ).reset_index()
    return RuleOutput(
        flagged,
        different["taskrsrc_id"].nunique(),
        comparison["taskrsrc_id"].nunique(),
        note=f"{len(comparison) - len(different)} of {len(comparison)} stored assignment dates reproduced",
    )
