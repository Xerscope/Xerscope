"""Integrity: is the file what P6 would calculate from its own logic? One function per check.

Not a published standard: checks that make the other standards trustworthy. Thresholds
come from ``standards/integrity.toml``.
"""

from __future__ import annotations

import pandas as pd

from .cpm import CycleError, ScheduleError, compare_assignments, compare_with_stored, schedule
from .populations import (
    Funnel,
    activity_funnel,
    actual_after,
    as_flag,
    flagged_activities,
    flagged_relationships,
    has_predecessor_in_project,
    has_successor_in_project,
    links_between,
    open_end_reason,
    predecessors_ahead,
)
from .rules import RuleOutput, link_funnel, rule

STORED_FIELDS = ["early_start_date", "early_end_date", "late_start_date", "late_end_date", "total_float_hr_cnt"]


@rule("int_01_recalculated", "%")
def int_01_recalculated(context) -> RuleOutput:
    """Stored dates differ from the recalculation.
    Counts: different / open tasks

    Open tasks whose stored dates or float differ from a P6-style recalculation.

    A difference means the file was edited after the last F9, or uses a scheduling
    feature xerscope does not model (see analysis/cpm.py). Exact to the minute.
    """
    try:
        comparison = compare_with_stored(context.snapshot)
    except ScheduleError as exc:  # a loop, or a duration / lag the engine cannot place
        return RuleOutput(note=f"cannot schedule: {exc}")
    comparison = comparison[comparison["field"].isin(STORED_FIELDS) & comparison["stored"].notna()]
    funnel = Funnel(context.snapshot.by_code.reset_index().sort_values("task_code"))
    funnel.keep(
        "with stored dates to compare", "xerscope", lambda rows: rows["task_code"].isin(comparison["task_code"])
    )
    if comparison.empty:
        return RuleOutput(
            numerator=0, denominator=0, note="no stored dates to compare", checked=funnel.rows, funnel=funnel
        )
    differences: dict[str, list[str]] = {}
    columns = ["task_code", "field", "stored", "computed", "agree"]
    for task_code, field_name, stored, computed, agrees in comparison[columns].itertuples(index=False):
        if not agrees:
            differences.setdefault(task_code, []).append(f"{field_name}: {stored} -> {computed}")
    tasks = context.snapshot.by_code
    flagged = tasks.loc[sorted(differences)].reset_index()
    texts = ["; ".join(differences[task_code]) for task_code in flagged["task_code"]]
    different_values = sum(len(found) for found in differences.values())
    compared = funnel.rows
    note = (
        f"{len(comparison) - different_values} of {len(comparison)} stored values reproduced; {_finish_note(context)}"
    )
    return RuleOutput(
        flagged_activities(flagged, differences=texts),
        len(differences),
        len(compared),
        note=note,
        checked=compared,
        funnel=funnel,
    )


def _finish_note(context) -> str:
    """The log's 'Latest Early Finish Date' (stored vs recalculated) and its count of tasks with external dates."""
    snapshot = context.snapshot
    stored, recalculated = snapshot.finish_date, schedule(snapshot).finish
    external = (
        snapshot.activities.reindex(columns=["external_early_start_date", "external_late_end_date"]).notna().any(axis=1)
    )
    return (
        f"latest early finish stored {_date_text(stored)}, recalculated {_date_text(recalculated)}; "
        f"{int(external.sum())} tasks with external dates"
    )


def _date_text(date) -> str:
    return "none" if date is None or pd.isna(date) else f"{date:%Y-%m-%d %H:%M}"


@rule("int_02_out_of_sequence_progress", "count")
def int_02_out_of_sequence_progress(context) -> RuleOutput:
    """Out of sequence tasks.
    Counts: out of sequence / started

    Mirrors the P6 log warning 'Out of sequence tasks': tasks that have started before their
    predecessor has completed. Read at the status date, as P6 Check Schedule (P6-15) does: a started task
    whose FS predecessor is not complete, or whose SS predecessor has not started. FF and SF links, and
    predecessors that finished after the successor's actual start, are not listed. Counts tasks.
    """
    tasks = context.snapshot.by_code
    funnel = activity_funnel(context.snapshot)
    funnel.keep("started", "xerscope", lambda rows: as_flag(rows["is_started"]))
    funnel.keep("first row of the Task ID", "xerscope", lambda rows: ~rows.duplicated("task_code"))
    started = funnel.rows.set_index("task_code")
    ahead = predecessors_ahead(links_between(context.snapshot.relationships, started, tasks), tasks)
    ahead_of = (ahead["pred_code"] + " (" + ahead["type"] + ")").groupby(ahead["succ_code"]).agg(", ".join)
    flagged = started.loc[ahead_of.index].reset_index()
    return RuleOutput(
        flagged_activities(flagged, ahead_of=flagged["task_code"].map(ahead_of)),
        len(flagged),
        len(started),
        checked=funnel.rows,
        funnel=funnel,
    )


@rule("int_04_relationship_loops", "count")
def int_04_relationship_loops(context) -> RuleOutput:
    """Tasks in a relationship loop.
    Counts: in a loop / tasks
    Excludes: tasks downstream of a loop, level of effort (its links are not part of the network).

    Mirrors the P6 log error 'Tasks that have invalid relationship loops'. The loop is found by the
    CPM's topological pass (analysis/cpm.py), narrowed to the tasks that lie on a loop.
    """
    try:
        schedule(context.snapshot)
    except CycleError as exc:
        members = list(exc.members)
    except ScheduleError:  # unschedulable for another reason (a duration or lag out of range): no loop found
        members = []
    else:
        members = []
    funnel = activity_funnel(context.snapshot)
    activities = funnel.rows
    flagged = activities[activities["task_code"].isin(members)]
    return RuleOutput(flagged_activities(flagged), len(flagged), len(activities), checked=activities, funnel=funnel)


@rule("int_05_without_predecessors_or_successors", "count")
def int_05_without_predecessors_or_successors(context) -> RuleOutput:
    """Tasks without a predecessor or a successor.
    Counts: without logic / tasks

    Mirrors the P6 log warnings 'Tasks without predecessors' and 'Tasks without successors': the
    raw list, every task (completed, started, milestones, level of effort) with no relationship in
    that direction; a relationship to another project counts. P6-01 applies the Check Schedule exclusions.
    """
    funnel = activity_funnel(context.snapshot)
    activities = funnel.rows
    missing_predecessor = ~(has_predecessor_in_project(context.snapshot, activities) | activities["has_external_pred"])
    missing_successor = ~(has_successor_in_project(context.snapshot, activities) | activities["has_external_succ"])
    flagged = activities[missing_predecessor | missing_successor]
    reason = open_end_reason(missing_predecessor, missing_successor)[flagged.index]
    return RuleOutput(
        flagged_activities(flagged, reason=reason), len(flagged), len(activities), checked=activities, funnel=funnel
    )


@rule("int_06_actual_date_after_data_date", "count")
def int_06_actual_date_after_data_date(context) -> RuleOutput:
    """Tasks with an actual date after the status date.
    Counts: with an actual date after the status date / tasks

    Mirrors the P6 log warning 'Tasks with actual date later than status date': any actual start or actual
    finish later than the status date, every task (level of effort and milestones included). P6-10b
    reads the same dates with the Check Schedule exclusions (06A506a for DECM).
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    funnel = activity_funnel(context.snapshot)
    activities = funnel.rows
    flagged = activities[actual_after(activities, data_date)]
    return RuleOutput(
        flagged_activities(flagged, actual_start=flagged["act_start_date"], actual_finish=flagged["act_end_date"]),
        len(flagged),
        len(activities),
        checked=activities,
        funnel=funnel,
    )


# Constraint type -> (side of the activity it bounds, what its date requires of the recalculated date)
CONSTRAINT_RULES = {
    "CS_MSOB": ("start", "<=", "Start on or before"),
    "CS_MSOA": ("start", ">=", "Start on or after"),
    "CS_MSO": ("start", "==", "Start on"),
    "CS_MANDSTART": ("start", "==", "Mandatory start"),
    "CS_MEOB": ("finish", "<=", "Finish on or before"),
    "CS_MEOA": ("finish", ">=", "Finish on or after"),
    "CS_MEO": ("finish", "==", "Finish on"),
    "CS_MANDFIN": ("finish", "==", "Mandatory finish"),
}


@rule("int_07_unsatisfied_constraints", "count")
def int_07_unsatisfied_constraints(context) -> RuleOutput:
    """Tasks whose recalculated dates do not meet their constraint.
    Counts: unsatisfied / constrained
    Excludes: completed tasks, level of effort, start constraints of started tasks.

    xerscope's reading of the P6 log exception 'Tasks with unsatisfied constraints', not confirmed
    against a P6 log: the recalculated early start (or finish) must be on the required side of the
    constraint date (Start on or before: not later; Start on or after: not earlier; Start on, Finish on,
    Mandatory start and finish: equal). Primary and secondary constraints are both read. Compared in
    working time of the activity's calendar, as the CPM places them: a date in non-working time is the
    start of the next working period, so a Start On at 00:00 is met by an early start at 08:00.
    """
    try:
        dates = schedule(context.snapshot).frame
    except ScheduleError as exc:  # a loop, or a duration / lag the engine cannot place
        return RuleOutput(note=f"cannot schedule: {exc}")
    funnel = activity_funnel(context.snapshot).exclude("complete", "xerscope").exclude("loe", "xerscope")
    funnel.keep("first row of the Task ID", "xerscope", lambda rows: ~rows.duplicated("task_code"))
    funnel.keep("in the recalculation", "xerscope", lambda rows: rows["task_code"].isin(dates.index))
    activities = funnel.rows
    early = {
        "start": activities["task_code"].map(dates["es"]),
        "finish": activities["task_code"].map(dates["ef"]),
    }
    reasons: dict[str, list[str]] = {}
    constrained: set[str] = set()
    for type_column, date_column in (("cstr_type", "cstr_date"), ("cstr_type2", "cstr_date2")):
        for constraint_type, (side, requirement, label) in CONSTRAINT_RULES.items():
            applies = (activities[type_column] == constraint_type) & activities[date_column].notna()
            if side == "start":
                applies &= ~activities["is_started"]
            wanted, actual = activities[date_column], early[side]
            late_by = context.snapshot.work_hours(activities["clndr_id"], wanted, actual)  # working hours
            met = {"<=": late_by <= 0, ">=": late_by >= 0, "==": late_by == 0}[requirement]
            constrained |= set(activities.loc[applies, "task_code"])
            for index in activities.index[applies & ~met.fillna(False)]:
                code = activities.at[index, "task_code"]
                reasons.setdefault(code, []).append(
                    f"{label} {wanted[index]:%Y-%m-%d %H:%M}: early {side} {actual[index]}"
                )
    flagged = activities[activities["task_code"].isin(reasons)]
    texts = flagged["task_code"].map(lambda code: "; ".join(reasons[code]))
    funnel.keep("constrained", "xerscope", lambda rows: rows["task_code"].isin(constrained))
    checked = funnel.rows
    return RuleOutput(
        flagged_activities(flagged, unsatisfied=texts), len(flagged), len(constrained), checked=checked, funnel=funnel
    )


@rule("int_08_unsatisfied_relationships", "count", links=True)
def int_08_unsatisfied_relationships(context) -> RuleOutput:
    """Relationships the successor's dates break.
    Counts: unsatisfied / relationships checked
    Excludes: level of effort, relationships to other projects, relationships with a lead (negative lag),
        relationships whose successor end is an actual date.

    xerscope's reading of the P6 log exception 'Tasks with unsatisfied relationships'. The
    successor end the relationship bounds (start for FS / SS, finish for FF / SF) must be a recalculated
    date: an actual date there is out-of-sequence progress, which the log lists under its own warning
    and not here (P6 Professional 26.8 log, tests/test_p6_checksched.py). The predecessor is read at its
    actual date, else at its recalculated early date. FS: the successor starts before the predecessor
    finishes; SS: before it starts; FF: the successor finishes before the predecessor finishes; SF:
    before it starts. The lag is not added (it needs a calendar), so a relationship with a positive lag
    is listed only when it is broken even at zero lag.
    """
    try:
        dates = schedule(context.snapshot).frame
    except ScheduleError as exc:  # a loop, or a duration / lag the engine cannot place
        return RuleOutput(note=f"cannot schedule: {exc}")
    tasks = context.snapshot.by_code
    start = tasks["act_start_date"].combine_first(dates["es"])
    finish = tasks["act_end_date"].combine_first(dates["ef"])
    funnel = link_funnel(context, "all", exclude_loe=True, source="xerscope")
    funnel.keep(
        "between recalculated tasks",
        "xerscope",
        lambda rows: rows["pred_code"].isin(dates.index) & rows["succ_code"].isin(dates.index),
    )
    funnel.keep("no lead", "xerscope", lambda rows: rows["lag_hr"].fillna(0) >= 0)

    def successor_end_is_actual(rows: pd.DataFrame) -> pd.Series:
        bounds_start = rows["type"].isin(("FS", "SS"))
        actual_start = rows["succ_code"].map(tasks["act_start_date"]).notna()
        actual_finish = rows["succ_code"].map(tasks["act_end_date"]).notna()
        return actual_start.where(bounds_start, actual_finish)

    funnel.keep("successor end not an actual date", "xerscope", lambda rows: ~successor_end_is_actual(rows))
    links = funnel.rows
    successor_start = links["succ_code"].map(start)
    successor_finish = links["succ_code"].map(finish)
    broken = (
        ((links["type"] == "FS") & (successor_start < links["pred_code"].map(finish)))
        | ((links["type"] == "SS") & (successor_start < links["pred_code"].map(start)))
        | ((links["type"] == "FF") & (successor_finish < links["pred_code"].map(finish)))
        | ((links["type"] == "SF") & (successor_finish < links["pred_code"].map(start)))
    )
    flagged = links[broken]
    successor_side = flagged["type"].map({"FS": "start", "SS": "start", "FF": "finish", "SF": "finish"})
    reason = [
        f"successor {side} {(start if side == 'start' else finish)[succ]} before predecessor "
        f"{'finish' if kind in ('FS', 'FF') else 'start'} {(finish if kind in ('FS', 'FF') else start)[pred]}"
        for side, succ, kind, pred in zip(
            successor_side, flagged["succ_code"], flagged["type"], flagged["pred_code"], strict=True
        )
    ]
    return RuleOutput(
        flagged_relationships(flagged).assign(reason=reason), len(flagged), len(links), checked=links, funnel=funnel
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

    Same idea as ``int_01_recalculated``, on TASKRSRC: task dates + assignment lag, duration
    = remaining units / units per hour, on the resource's calendar for resource-dependent
    tasks.
    """
    try:
        comparison = compare_assignments(context.snapshot)
    except ScheduleError as exc:  # a loop, or a duration / lag the engine cannot place
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
