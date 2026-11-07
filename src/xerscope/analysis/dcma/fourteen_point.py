"""DCMA 14-Point Schedule Assessment (DCMA-EA PAM 200.1, Oct 2012): one function per check.

Section 4.0 sets the population: incomplete tasks, without LOE and milestones. Threshold
and pass/fail come from ``standards/dcma.toml``; the function only decides what is flagged.
"""

from __future__ import annotations

import operator
from typing import Literal

import pandas as pd

from ...xer.calendar import hours_to_days
from ...xer.model import CONSTRAINT, HARD_CONSTRAINTS
from ..cpm import schedule
from ..populations import (
    Funnel,
    activity_funnel,
    actual_after,
    as_flag,
    at_grain,
    constrained_by,
    finish_driver,
    flagged_activities,
    flagged_relationships,
    forecast_before,
    has_predecessor_in_project,
    has_successor_in_project,
    invalid_date_reason,
    lag_flagged,
    open_end_reason,
    with_baseline,
)
from ..rules import RuleOutput, bei_from_snapshot, critical_path_output, link_funnel, rule, share_of_type

DCMA_HIGH_DAYS = 44  # PAM 200.1 §4.6 and §4.8: "two months" of work, in working days of the activity's calendar
# The pamphlet gives no slip length (§4.12); 600 working days is xerscope's choice.
DCMA_SLIP_DAYS = 600

# Start On, Start On or Before, Finish On, Finish On or Before, Mandatory Start, Mandatory Finish:
# the model's set.
DCMA_HARD_CONSTRAINTS = HARD_CONSTRAINTS


def _discrete_tasks(funnel: Funnel) -> Funnel:
    """PAM 200.1 section 4.0: LOE and milestones are not tasks."""
    return funnel.exclude("loe", "PAM 200.1").exclude("milestones", "PAM 200.1")


def _open_tasks(context) -> Funnel:
    """The DCMA population: incomplete, non-LOE, non-milestone tasks."""
    return _discrete_tasks(activity_funnel(context.snapshot).exclude("complete", "PAM 200.1"))


def _links_into_open_tasks(context) -> Funnel:
    """PAM 200.1 section 4.0: a link counts when its successor is an incomplete, non-LOE, non-milestone task."""
    return link_funnel(context, "all", exclude=("complete", "loe", "milestones"), source="PAM 200.1")


@rule("dcma_01_logic", "%")
def dcma_01_logic(context) -> RuleOutput:
    """Missing a predecessor or a successor.
    Counts: open-ended / checked
    Excludes: completed tasks, level of effort, milestones.

    DCMA-EA PAM 200.1 §4.1: any incomplete task missing a predecessor and/or a successor; no project
    start/finish exemption and no dangling case; §4.0: milestones excluded; a link to another project
    counts as logic (rule default)
    """
    funnel = _open_tasks(context)
    tasks = funnel.rows
    has_predecessor = has_predecessor_in_project(context.snapshot, tasks) | tasks["has_external_pred"]
    has_successor = has_successor_in_project(context.snapshot, tasks) | tasks["has_external_succ"]

    missing_predecessor = ~has_predecessor
    missing_successor = ~has_successor
    flagged = tasks[missing_predecessor | missing_successor]
    reason = open_end_reason(missing_predecessor, missing_successor)[flagged.index]
    return RuleOutput(
        flagged_activities(flagged, reason=reason), len(flagged), len(tasks), checked=tasks, funnel=funnel
    )


@rule("dcma_02_leads", "%", links=True)
def dcma_02_leads(context) -> RuleOutput:
    """Relationships with the lag in question.
    Counts: flagged / relationships checked
    Relationships whose successor is excluded: completed tasks, level of effort, milestones.
    Relationships counted: relationships into an incomplete successor.
    Flagged when lag < 0 hours.

    DCMA-EA PAM 200.1 §4.2: logic links with a lead (negative lag) in predecessor relationships for
    incomplete tasks; §4.0: completed, LOE, summary tasks and milestones are excluded, so a link counts
    when its successor is kept
    """
    funnel = _links_into_open_tasks(context)
    relationships = funnel.rows

    leads = lag_flagged(relationships, operator.lt, 0)
    return RuleOutput(
        flagged_relationships(leads), len(leads), len(relationships), checked=relationships, funnel=funnel
    )


@rule("dcma_03_lags", "%", links=True)
def dcma_03_lags(context) -> RuleOutput:
    """Relationships with a positive lag.
    Counts: flagged / relationships checked
    Relationships whose successor is excluded: completed tasks, level of effort, milestones.
    Relationships counted: relationships into an incomplete successor, a predecessor in another
        project of the file included.
    Flagged when lag > 0 hours (a negative lag is a lead, DCMA-02).

    DCMA-EA PAM 200.1 §4.3: lags in predecessor logic relationships for incomplete tasks; §4.0:
    completed, LOE, summary tasks and milestones are excluded, so a link counts when its successor is
    kept (xerscope's reading of §4.0, which names tasks, not links)
    """
    funnel = _links_into_open_tasks(context)
    relationships = funnel.rows

    lags = lag_flagged(relationships, operator.gt, 0)
    return RuleOutput(flagged_relationships(lags), len(lags), len(relationships), checked=relationships, funnel=funnel)


@rule("dcma_04_relationship_types", "%", links=True)
def dcma_04_relationship_types(context) -> RuleOutput:
    """Relationships of another type.
    Counts: of the required type / relationships checked
    Relationships whose successor is excluded: completed tasks, level of effort, milestones.
    Relationships counted: relationships into an incomplete successor.
    Counts relationships of type FS; the list shows the others.

    DCMA-EA PAM 200.1 §4.4: a count of incomplete tasks containing each type of logic link; §4.0:
    completed, LOE, summary tasks and milestones are excluded, so a link counts when its successor is
    kept
    """
    funnel = _links_into_open_tasks(context)
    share = share_of_type(funnel.rows, "FS")
    share.funnel = funnel
    return share


@rule("dcma_05_hard_constraints", "%")
def dcma_05_hard_constraints(context) -> RuleOutput:
    """Constrained tasks.
    Counts: constrained / checked
    Excludes: completed tasks, level of effort, milestones.
    Constraint types: Start on, Start on or before, Finish on, Finish on or before, Mandatory start,
        Mandatory finish.

    DCMA-EA PAM 200.1 §4.5 (and §4.0: milestones excluded); MSO = Start On / Mandatory Start, MFO = Finish
    On / Mandatory Finish, SNLT = Start On or Before, FNLT = Finish On or Before
    """
    funnel = _open_tasks(context)
    tasks = funnel.rows
    hard = tasks[constrained_by(tasks, DCMA_HARD_CONSTRAINTS, ignore_started_starts=False)]
    return RuleOutput(
        flagged_activities(hard, constraint2=hard["cstr_type2"].map(CONSTRAINT)),
        len(hard),
        len(tasks),
        checked=tasks,
        funnel=funnel,
    )


def _no_float_note(tasks: pd.DataFrame) -> str:
    """PAM 200.1 is silent on a task without a float: it stays in "# of incomplete tasks" and cannot be
    flagged, so the reader is told how many."""
    missing = int(tasks["total_float_d"].isna().sum())
    return f"{missing} without total float (kept in the checked population, cannot be flagged)" if missing else ""


@rule("dcma_06_high_float", "%")
def dcma_06_high_float(context, limit_days: float = DCMA_HIGH_DAYS) -> RuleOutput:
    """Tasks outside the float limit.
    Counts: flagged / checked
    Excludes: completed tasks, level of effort, milestones.

    DCMA-EA PAM 200.1 §4.6: incomplete task with total float greater than 44 working days (2 months);
    §4.0: milestones excluded
    """
    funnel = _open_tasks(context)
    tasks = funnel.rows
    high_float = tasks[tasks["total_float_d"] > limit_days]
    return RuleOutput(
        flagged_activities(high_float),
        len(high_float),
        len(tasks),
        note=_no_float_note(tasks),
        checked=tasks,
        funnel=funnel,
    )


@rule("dcma_07_negative_float", "%")
def dcma_07_negative_float(context) -> RuleOutput:
    """Tasks outside the float limit.
    Counts: flagged / checked
    Excludes: completed tasks, level of effort, milestones.
    Flagged when total float < 0 days.

    DCMA-EA PAM 200.1 §4.7: incomplete task with total float less than 0 working days; §4.0: milestones
    excluded
    """
    funnel = _open_tasks(context)
    tasks = funnel.rows
    negative_float = tasks[tasks["total_float_d"] < 0]
    return RuleOutput(
        flagged_activities(negative_float),
        len(negative_float),
        len(tasks),
        note=_no_float_note(tasks),
        checked=tasks,
        funnel=funnel,
    )


@rule("dcma_08_high_duration", "%")
def dcma_08_high_duration(context, limit_days: float = DCMA_HIGH_DAYS) -> RuleOutput:
    """Tasks outside the duration limit.
    Counts: flagged / checked
    Excludes: completed tasks, level of effort, milestones.

    DCMA-EA PAM 200.1 §4.8: an incomplete task with a baseline duration greater than 44 working days (2
    months) and a baseline start within the detail planning period or rolling wave; §4.0: LOE and
    milestones excluded. UNRESOLVED: inputs are weekly XERs with no detail planning window, so every
    baseline start qualifies. UNRESOLVED: baseline hours are divided by the task's current hours per
    day, not the baseline calendar. A task absent from the baseline is not flagged; without a
    baseline the check is n/a
    """
    if context.baseline is None:
        return RuleOutput(note="needs a baseline")
    funnel = _open_tasks(context)
    tasks = funnel.rows
    baseline_hours = tasks["task_code"].map(context.baseline.frame["bl_duration_hr"])
    long_tasks = tasks[hours_to_days(baseline_hours, tasks["hours_per_day"]) > limit_days]
    return RuleOutput(flagged_activities(long_tasks), len(long_tasks), len(tasks), checked=tasks, funnel=funnel)


@rule("dcma_09_invalid_dates", "%")
def dcma_09_invalid_dates(context, date_grain: Literal["timestamp", "day"] = "timestamp") -> RuleOutput:
    """Progress dates on the wrong side of the status date.
    Counts: with invalid dates / checked
    Excludes: level of effort, milestones, tasks completed before the status date.

    DCMA-EA PAM 200.1 §4.9: incomplete tasks with a forecast start/finish before the status date, or an
    actual start/finish beyond it, compared by calendar day as the pamphlet does ("on or before 8/1/09,
    not after 8/1/09"; ``date_grain``, "timestamp" being P6's reading); §4.0: LOE and milestones
    excluded. Completed tasks: §4.0 excludes them all, §4.9 flags an actual date beyond the status date,
    so xerscope keeps the tasks completed on or after it (its reading of §4.9 over §4.0)
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    funnel = _discrete_tasks(activity_funnel(context.snapshot)).exclude("complete_before_data_date", "PAM 200.1")
    tasks = funnel.rows

    forecast = forecast_before(tasks, data_date, date_grain)
    actual = actual_after(tasks, data_date, date_grain)
    invalid = forecast | actual
    reasons = invalid_date_reason(forecast, actual)[invalid]
    return RuleOutput(
        flagged_activities(tasks[invalid], reason=reasons),
        int(invalid.sum()),
        len(tasks),
        note=f"dates compared by {date_grain}",
        checked=tasks,
        funnel=funnel,
    )


@rule("dcma_10_resources", "%")
def dcma_10_resources(context) -> RuleOutput:
    """Tasks with no resource assignment.
    Counts: without resources / checked
    Excludes: completed tasks, level of effort, milestones, tasks with no original duration.

    DCMA-EA PAM 200.1 §4.10: "all tasks with durations greater than zero have dollars or hours assigned";
    incomplete tasks without them over incomplete tasks; §4.0 exclusions apply. Cost or hours = a
    resource assignment or an expense. The test applies to a resource-loaded schedule only: n/a when the
    project has no assignment and no budgeted labour hours on its tasks (expenses alone do not load it);
    hours without assignments still fail, with a note on the export. Target 0 %, the pamphlet and Acumen
    giving none
    """
    snapshot = context.snapshot
    if snapshot.assignments.empty:
        if not (snapshot.activities["labor_budget_hr"] > 0).any():
            return RuleOutput(
                note="PAM 200.1 §4.10: applies to a resource-loaded schedule only; "
                "no resource assignment and no labour hours"
            )
        note = "labour hours on tasks but no resource assignment: check the export (TASKRSRC)"
    else:
        note = ""
    funnel = _open_tasks(context).exclude("no_duration", "PAM 200.1")
    tasks = funnel.rows
    without_cost = tasks[~(tasks["has_resource"] | tasks["has_expense"])]
    return RuleOutput(
        flagged_activities(without_cost), len(without_cost), len(tasks), note=note, checked=tasks, funnel=funnel
    )


@rule("dcma_11_missed_tasks", "%", needs_baseline=True)
def dcma_11_missed_tasks(context, date_grain: Literal["timestamp", "day"] = "timestamp") -> RuleOutput:
    """Due by the status date and not finished on time.
    Counts: missed / due by the status date
    Excludes: level of effort, milestones.
    Due = baseline start and finish set, baseline finish on or before the status date. Missed = actual
        (else forecast) finish on a later calendar day than the baseline finish, or later by any
        working time on the task's calendar (the pamphlet's two readings, joined by "or").

    DCMA-EA PAM 200.1 (Oct 2012) 4.11: baseline finish on or before the status date, actual or forecast
    finish after it; base excludes tasks missing a baseline start or finish. 4.0 excludes completed
    tasks, LOE, summary tasks and milestones; 4.11 measures actual finishes, so completed tasks stay here
    (4.11 overrides 4.0 on that point). Due is read by calendar day, as the pamphlet does
    (``date_grain``; "timestamp" is P6's reading). Missed: "after the baseline finish date OR the
    Finish Variance (Early Finish minus Baseline Finish) is greater than zero", Finish Variance being
    working time in MS Project and P6: a Saturday actual against a Friday baseline is late by date, a
    17:00 actual against a 12:00 baseline the same day is late by variance; both count
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    funnel = Funnel(with_baseline(context.baseline, context.snapshot.activities), data_date)
    tasks = _discrete_tasks(funnel).rows
    unmatched = int((tasks["bl_start"].isna() | tasks["bl_finish"].isna()).sum())
    funnel.keep(
        "baseline finish on or before the status date",
        "PAM 200.1",
        lambda rows: (
            rows["bl_start"].notna() & (at_grain(rows["bl_finish"], date_grain) <= at_grain(data_date, date_grain))
        ),
    )
    due = funnel.rows
    date_after = as_flag(at_grain(due["finish"], date_grain) > at_grain(due["bl_finish"], date_grain))
    variance_hours = context.snapshot.work_hours(due["clndr_id"], due["bl_finish"], due["finish"])
    variance_after = as_flag(variance_hours > 0)
    missed = due[date_after | variance_after]
    reason = pd.Series("both", index=missed.index)
    reason[date_after[missed.index] & ~variance_after[missed.index]] = "date after baseline finish"
    only_variance = variance_after[missed.index] & ~date_after[missed.index]
    reason[only_variance] = [f"finish variance {h:g} h" for h in variance_hours[missed.index][only_variance]]
    # a baseline that matches few activities shrinks the due population silently: say so
    note = f"due by {date_grain}"
    if unmatched:
        note += f"; {unmatched} without baseline dates left out of {len(tasks)} tasks"
    return RuleOutput(
        flagged_activities(missed, bl_finish=missed["bl_finish"], reason=reason),
        len(missed),
        len(due),
        note=note,
        checked=due,
        funnel=funnel,
    )


@rule("dcma_12_critical_path_test", "pass/fail")
def dcma_12_critical_path_test(context, slip_days: float = DCMA_SLIP_DAYS) -> RuleOutput:
    """Add the slip (working days) to the first open critical task; the finish must slip as much.

    DCMA-EA PAM 200.1 §4.12: the project completion date must move "in direct proportion" to the
    "intentional slip" introduced. The pamphlet gives no slip length; 600 working days is xerscope's
    choice, DECM 06A401a gives none either
    """
    return critical_path_output(context, slip_days)


Margin = tuple[RuleOutput | None, str, float, str, pd.Timestamp | None]


def _baseline_margin(context, last_task) -> Margin:
    """Margin of the open end milestone that finishes last to its baseline finish, in project working days.

    Returns (n/a output or None, milestone code, margin, baseline finish text, forecast finish of the
    milestone): the CPL is measured to that same milestone (PAM §3.1.2.3, "the next program milestone
    that is being measured").
    """
    snapshot = context.snapshot
    if context.baseline is None:
        return (
            RuleOutput(note="no Must Finish By date and no baseline: no reference date for the float"),
            "",
            0,
            "",
            None,
        )
    activities = snapshot.activities
    ends = activities[
        ~activities["is_complete"] & ~activities["is_loe"] & (activities["task_type"] == "TT_FinMile")
    ].dropna(subset=["finish"])
    if ends.empty:
        note = "no Must Finish By date and no open finish milestone to measure the float on"
        return RuleOutput(note=note), "", 0, "", None
    end = ends.sort_values(["finish", "task_code"]).iloc[-1]
    forecast = schedule(snapshot).frame["ef"].get(end["task_code"], end["finish"])
    if context.baseline.is_planned:
        # the planned finish of a not-started milestone is its early finish (Oracle 47222): margin 0
        return None, end["task_code"], 0.0, f"{forecast:%Y-%m-%d}", forecast
    baseline_finish = context.baseline.frame["bl_finish"].get(end["task_code"], pd.NaT)
    if pd.isna(baseline_finish):
        return RuleOutput(note=f"{end['task_code']} has no baseline finish"), "", 0, "", None
    margin = snapshot.project_working_days(forecast, baseline_finish)
    return None, end["task_code"], margin, f"{baseline_finish:%Y-%m-%d}", forecast


@rule("dcma_13_cpli", "ratio")
def dcma_13_cpli(context) -> RuleOutput:
    """Critical Path Length Index = (CPL + TF) / CPL.

    DCMA-EA PAM 200.1 §3.1.2.3: CPLI = (CPL + TF) / CPL, TF being the total float of the completion
    milestone ("the amount of days a project can be delayed before delaying the project completion
    date"). CPL = working days from the status date to the forecast finish, TF = that float, both in working
    days of the project calendar (PAM and Acumen say days without naming a calendar).
    P6 writes that float against the Must Finish By date. Without one, the open finish milestone ending
    last is the measured milestone: CPL runs to its forecast finish and TF is its margin to its baseline
    finish (PAM: CPL "until the next program milestone that is being measured", TF "relative to the
    baselined finish date, when constrained") (recalculated early finish, project calendar;
    negative when late); n/a without a baseline or without a baseline finish for it. With the planned
    dates baseline the value is reported for review, not judged: the planned finish of a not-started
    milestone follows its early finish (Oracle 47222), so the margin is 0 and the CPLI 1.00 by
    construction, whatever the schedule. No constraint is read
    """
    snapshot = context.snapshot
    last_task = finish_driver(snapshot)
    if snapshot.data_date is None:
        return RuleOutput(note="no status date")
    if last_task is None:
        return RuleOutput(note="no remaining work")
    margin_note = ""
    end_finish = last_task["finish"]
    if snapshot.options.get("must_finish_by") is None:
        unavailable, code, margin, baseline_finish, end_finish = _baseline_margin(context, last_task)
        if unavailable is not None:
            return unavailable
        margin_note = f"to {code}, margin of {code} to its BL finish {baseline_finish}: {margin:g} wd"
    calendar = snapshot.calendar()
    length = snapshot.project_working_days(snapshot.data_date, end_finish)
    if length <= 0:
        return RuleOutput(note="critical path length is 0")
    if margin_note:
        total_float = margin
        note = f"CPL {length:g} wd {margin_note}"
        if context.baseline.is_planned:
            note = (
                f"by construction: planned-dates baseline, the planned finish of a not-started milestone follows "
                f"its early finish (Oracle 47222), so the margin is {margin:g} wd and the CPLI "
                f"{(length + total_float) / length:.2f} whatever the schedule; {note}; choose a baseline file or "
                "set a Must Finish By for a measure"
            )
            return RuleOutput(value=(length + total_float) / length, note=note, status="info")
    else:
        if pd.isna(last_task["total_float_hr_cnt"]):
            code = last_task["task_code"]
            return RuleOutput(note=f"total float missing on {code}: CPLI not computed (a missing float is not 0)")
        if not calendar.hours_per_day:
            return RuleOutput(note="project calendar has no hours per day: CPLI not computed")
        total_float = float(last_task["total_float_hr_cnt"]) / calendar.hours_per_day
        note = f"CPL {length:g} wd to {last_task['task_code']}, total float {total_float:g} wd"
    return RuleOutput(value=(length + total_float) / length, note=note)


@rule("dcma_14_bei", "ratio", needs_baseline=True)
def dcma_14_bei(context, date_grain: Literal["timestamp", "day"] = "timestamp") -> RuleOutput:
    """Due by the status date but not completed.
    Counts: completed / due by the status date
    Excludes: level of effort, milestones, tasks with no original duration.
    Tasks without a baseline finish are counted as due. Due = baseline finish on or before the status
        date; completed = actual finish on or before it, early ones included; both compared at
        ``date_grain`` (by calendar day for the pamphlet).

    DCMA-EA PAM 200.1 §3.1.2.4: Baseline Execution Index = tasks completed / tasks due by the
    status date; step 1 filters out LOE, summary and zero duration tasks (milestones), so a task with
    no original duration is out whatever its type; steps 2 and 5 keep the baseline finishes and the
    actual finishes "up to the current reporting period", the same bound for both; tasks missing
    baseline finish dates are included in the denominator

    UNRESOLVED: "Tasks missing baseline finish dates are included in the denominator" is read as "with
    no baseline finish date" (as §4.11's "tasks missing baseline start or finish dates"), so a task
    added since the baseline is due. Steps 2-3 count only dates "up to the current reporting period",
    which a task with no date cannot pass, and the formula's second term is "Total # of Tasks Missing
    Baseline Finish Date"; a reading of "missing" as "missed" (incomplete and past its baseline finish)
    would leave those tasks out
    """
    data_date = context.snapshot.data_date
    if data_date is None:
        return RuleOutput(note="no status date")
    funnel = Funnel(with_baseline(context.baseline, context.snapshot.activities), data_date)
    tasks = _discrete_tasks(funnel).exclude("no_duration", "PAM 200.1").rows
    zero_duration = funnel.steps[-1]
    funnel.keep(
        "due by the status date",
        "PAM 200.1",
        lambda rows: (
            as_flag(at_grain(rows["bl_finish"], date_grain) <= at_grain(data_date, date_grain))
            | rows["bl_finish"].isna()
        ),
    )
    bei = bei_from_snapshot(
        tasks, data_date, missing_baseline_is_due=True, completed_by_data_date=True, date_grain=date_grain
    )
    if len(zero_duration.removed):
        bei.note += f"; {len(zero_duration.removed)} without original duration left out (PAM step 1)"
    bei.funnel = funnel
    return bei
