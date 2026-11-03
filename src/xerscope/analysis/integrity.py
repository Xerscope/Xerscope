"""Integrity: is the file what P6 would calculate from its own logic? One function per check.

Not a published standard: checks that make the other standards trustworthy. Thresholds
come from ``standards/integrity.toml``.
"""

from __future__ import annotations

import pandas as pd

from .cpm import CycleError, compare_assignments, compare_with_stored, schedule
from .populations import flagged_activities, links_between, predecessors_ahead, without_level_of_effort
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
    tasks = context.snapshot.by_code
    flagged = tasks.loc[sorted(differences)].reset_index()
    texts = ["; ".join(differences[task_code]) for task_code in flagged["task_code"]]
    different_values = sum(len(found) for found in differences.values())
    note = (
        f"{len(comparison) - different_values} of {len(comparison)} stored values reproduced; {_finish_note(context)}"
    )
    return RuleOutput(
        flagged_activities(flagged, differences=texts), len(differences), comparison["task_code"].nunique(), note=note
    )


def _finish_note(context) -> str:
    """The log's 'Latest Early Finish Date' (stored vs recalculated) and its count of activities with external dates."""
    snapshot = context.snapshot
    stored, recalculated = snapshot.finish_date, schedule(snapshot).finish
    external = (
        snapshot.activities.reindex(columns=["external_early_start_date", "external_late_end_date"]).notna().any(axis=1)
    )
    return (
        f"latest early finish stored {_date_text(stored)}, recalculated {_date_text(recalculated)}; "
        f"{int(external.sum())} activities with external dates"
    )


def _date_text(date) -> str:
    return "none" if date is None or pd.isna(date) else f"{date:%Y-%m-%d %H:%M}"


def _predecessors_ahead(links: pd.DataFrame, started: pd.DataFrame, tasks: pd.DataFrame) -> pd.Series:
    """For each started successor, its predecessors ahead of it as 'CODE (FS), CODE (SS)'."""
    ahead = predecessors_ahead(links, started, tasks)
    if ahead.empty:
        return pd.Series(dtype=object)
    return (ahead["pred_code"] + " (" + ahead["type"] + ")").groupby(ahead["succ_code"]).agg(", ".join)


@rule("int_02_out_of_sequence_progress", "count")
def int_02_out_of_sequence_progress(context) -> RuleOutput:
    """Progressed out of logic sequence.
    Counts: out of sequence /
    Excludes: level of effort.

    Started activities whose FS predecessor had not finished, or SS predecessor not started, at their
    actual start (P6 lists them in its scheduling log). Counts activities.
    """
    activities = without_level_of_effort(context.snapshot.activities)
    tasks = context.snapshot.by_code
    started = activities[activities["is_started"]].drop_duplicates("task_code").set_index("task_code")
    ahead_of = _predecessors_ahead(links_between(context.snapshot.relationships, started, tasks), started, tasks)
    flagged = started.loc[ahead_of.index].reset_index()
    texts = flagged["task_code"].map(ahead_of)
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
