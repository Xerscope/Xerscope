"""Integrity: is the file what P6 would calculate from its own logic? One function per check.

Not a published standard: checks that make the other standards trustworthy. Thresholds
come from ``standards/integrity.toml``.
"""

from __future__ import annotations

import pandas as pd

from .cpm import CycleError, compare_assignments, compare_with_stored, schedule
from .populations import (
    actual_after,
    flagged_activities,
    has_predecessor_in_project,
    has_successor_in_project,
    links_between,
    open_end_reason,
    predecessors_ahead,
)
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
        return RuleOutput(numerator=0, denominator=0, note="no stored dates to compare", checked=pd.DataFrame())
    differences: dict[str, list[str]] = {}
    columns = ["task_code", "field", "stored", "computed", "agree"]
    for task_code, field_name, stored, computed, agrees in comparison[columns].itertuples(index=False):
        if not agrees:
            differences.setdefault(task_code, []).append(f"{field_name}: {stored} -> {computed}")
    tasks = context.snapshot.by_code
    flagged = tasks.loc[sorted(differences)].reset_index()
    texts = ["; ".join(differences[task_code]) for task_code in flagged["task_code"]]
    different_values = sum(len(found) for found in differences.values())
    compared = tasks.loc[sorted(comparison["task_code"].unique())].reset_index()
    note = (
        f"{len(comparison) - different_values} of {len(comparison)} stored values reproduced; {_finish_note(context)}"
    )
    return RuleOutput(
        flagged_activities(flagged, differences=texts), len(differences), len(compared), note=note, checked=compared
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


@rule("int_02_out_of_sequence_progress", "count")
def int_02_out_of_sequence_progress(context) -> RuleOutput:
    """Out of sequence activities.
    Counts: out of sequence / started

    Mirrors the P6 log warning 'Out of sequence activities': activities that have started before their
    predecessor has completed. Read at the data date, as P6 Check Schedule (P6-15) does: a started activity
    whose FS predecessor is not complete, or whose SS predecessor has not started. FF and SF links, and
    predecessors that finished after the successor's actual start, are not listed. Counts activities.
    """
    tasks = context.snapshot.by_code
    started = context.snapshot.activities[context.snapshot.activities["is_started"]]
    started = started.drop_duplicates("task_code").set_index("task_code")
    ahead = predecessors_ahead(links_between(context.snapshot.relationships, started, tasks), tasks)
    ahead_of = (ahead["pred_code"] + " (" + ahead["type"] + ")").groupby(ahead["succ_code"]).agg(", ".join)
    flagged = started.loc[ahead_of.index].reset_index()
    return RuleOutput(
        flagged_activities(flagged, ahead_of=flagged["task_code"].map(ahead_of)),
        len(flagged),
        len(started),
        checked=started.reset_index(),
    )


@rule("int_04_relationship_loops", "count")
def int_04_relationship_loops(context) -> RuleOutput:
    """Activities in a relationship loop.
    Counts: in a loop / activities
    Excludes: activities downstream of a loop, level of effort (its links are not part of the network).

    Mirrors the P6 log error 'Activities that have invalid relationship loops'. The loop is found by the
    CPM's topological pass (analysis/cpm.py), narrowed to the activities that lie on a loop.
    """
    try:
        schedule(context.snapshot)
    except CycleError as exc:
        members = list(exc.members)
    else:
        members = []
    activities = context.snapshot.activities
    flagged = activities[activities["task_code"].isin(members)]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities))


@rule("int_05_without_predecessors_or_successors", "count")
def int_05_without_predecessors_or_successors(context) -> RuleOutput:
    """Activities without a predecessor or a successor.
    Counts: without logic / activities

    Mirrors the P6 log warnings 'Activities without predecessors' and 'Activities without successors': the
    raw list, every activity (completed, started, milestones, level of effort) with no relationship in
    that direction; a relationship to another project counts. P6-01 applies the Check Schedule exclusions.
    """
    activities = context.snapshot.activities
    missing_predecessor = ~(has_predecessor_in_project(context, activities) | activities["has_external_pred"])
    missing_successor = ~(has_successor_in_project(context, activities) | activities["has_external_succ"])
    flagged = activities[missing_predecessor | missing_successor]
    reason = open_end_reason(missing_predecessor, missing_successor)[flagged.index]
    return RuleOutput(flagged_activities(flagged, reason=reason), len(flagged), len(activities))


@rule("int_06_actual_date_after_data_date", "count")
def int_06_actual_date_after_data_date(context) -> RuleOutput:
    """Activities with an actual date after the data date.
    Counts: with an actual date after the data date / activities

    Mirrors the P6 log warning 'Activities with actual date later than data date': any actual start or actual
    finish later than the data date, every activity (level of effort and milestones included). P6-10
    reads the same dates with the Check Schedule exclusions (06A506a for DECM).
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no data date")
    activities = context.snapshot.activities
    flagged = activities[actual_after(activities, data_date)]
    return RuleOutput(
        flagged_activities(flagged, actual_start=flagged["act_start_date"], actual_finish=flagged["act_end_date"]),
        len(flagged),
        len(activities),
    )


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
        return RuleOutput(
            numerator=0, denominator=0, note="no stored assignment dates to compare", checked=pd.DataFrame()
        )
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
    compared = comparison.groupby("taskrsrc_id")[["task_code", "rsrc"]].first().reset_index()
    return RuleOutput(
        flagged,
        different["taskrsrc_id"].nunique(),
        len(compared),
        note=f"{len(comparison) - len(different)} of {len(comparison)} stored assignment dates reproduced",
        checked=compared.rename(columns={"rsrc": "resource"}),
    )
