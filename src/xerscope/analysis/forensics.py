"""Half-step reading of one week: what moved the project finish between two updates.

AACE RP 29R-03, Forensic Schedule Analysis (rev. April 25, 2011), MIP 3.4 "Observational /
Dynamic / Contemporaneous Split", the bifurcated or half-stepped update analysis (3.4.K.4): the
earlier update is updated with the progress data of the later one and recalculated at the later
status date (the half-step schedule, H1); the move of its finish from the earlier update is the
slip due to progress, the move from H1 to the later update is due to the non-progress revisions,
and the two add up to the move between the updates (3.4.K.4.d to f). The SCL Delay and Disruption
Protocol, 2nd edition (February 2017), describes the same reading as the time slice windows
analysis (11.6(c)). Here the non-progress revisions are applied one kind at a time as well, in
``STEPS`` order, each step a derived snapshot the CPM engine (``analysis.cpm.schedule``)
recalculates, so the replanning is read by kind. The baseline is not read: the two updates are.

What is progress and what is a revision follows 3.4.K.4: progress is the actual start, the actual
finish, an increased percent complete and a decreased remaining duration (3.4.K.4.b); the
revisions are activities added or deleted, logic links and lags, constraints, original durations,
a remaining duration increased or changed without a change in percent complete, calendar and
holiday assignments. Hence the remaining duration of an activity started in the later update
belongs to progress when it decreased, and to the durations step otherwise.

Conventions no source settles, set here and stated on the page: the order in which the kinds of
revision are applied (scope, durations, logic, constraints, calendars and options); and where the
P6 fields the RP does not name go: suspend and resume dates and the external bounds of links to
other projects with progress, the expected finish and the resource assignments with durations, the
scheduling options with the calendars. The percent complete is carried with progress but is not
an input of the recalculation.

``residual_wd`` records the move the steps do not account for (a change the changelog does not
see): 0 when every step is applied. 3.4.K.4.g: a progress variance larger than the period itself
is suspect (a revision in the half-step, or work pushed into a non-working stretch);
``period_wd`` gives the period for that check.

The reading moves one number, the recalculated finish, so it is worth what the engine is worth on
the file: ``engine_gap_wd`` compares the recalculated finish of each update with the one P6 stored
in it, and a reading with a gap is flagged (``is_finish_reproduced``), its shifts possibly the
engine's and not the schedule's (docs/formulas.md 5.1, measured on the held-out corpus).

Shifts are working days of the later update's project calendar, days lost negative, as the
changelog and the finish variances read them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

import pandas as pd

from ..store import SnapshotStore
from ..xer import Snapshot
from .changelog import changelog
from .cpm import Schedule, ScheduleError, schedule
from .populations import has_successor_in_project, without

PROGRESS_COLUMNS = [
    "status_code",
    "status",
    "is_complete",
    "is_started",
    "act_start_date",
    "act_end_date",
    "suspend_date",
    "resume_date",
    "phys_complete_pct",
    # the bounds the links to other projects set, as P6 stored them at the later status date
    "external_early_start_date",
    "external_late_end_date",
]
TYPE_COLUMNS = ["task_type", "type", "is_milestone", "is_start_milestone", "is_loe", "is_wbs_summary"]
DURATION_COLUMNS = ["target_drtn_hr_cnt", "expect_end_date"]
CONSTRAINT_COLUMNS = ["cstr_type", "cstr_date", "cstr_type2", "cstr_date2", "has_hard_constraint"]
CALENDAR_COLUMNS = ["clndr_id", "hours_per_day"]

AS_SCHEDULED = "as scheduled (earlier update)"


@dataclass(frozen=True)
class _Derivation:
    """Both updates and the activity codes they share: what every step reads."""

    old: Snapshot
    new: Snapshot
    common: list[str]

    @property
    def added(self) -> list[str]:
        return sorted(set(self.new.by_code.index) - set(self.old.by_code.index))

    @property
    def deleted(self) -> list[str]:
        return sorted(set(self.old.by_code.index) - set(self.new.by_code.index))


def _with_columns_of_new(tasks: pd.DataFrame, derivation: _Derivation, codes, columns: list[str]) -> pd.DataFrame:
    """``tasks`` with ``columns`` of the activities ``codes`` read from the later update.

    A column the later update's file does not carry is left as it is. The column takes the type
    that holds both updates' values: a file whose hours are all whole reads them as integers, and
    the next may hold 19.2.
    """
    out = tasks.copy()
    rows = out["task_code"].isin(codes)
    if not rows.any():
        return out
    for column in columns:
        if column not in derivation.new.by_code.columns:
            continue
        values = derivation.new.by_code[column].reindex(out.loc[rows, "task_code"])
        carried = pd.Series(values.to_numpy(), index=out.index[rows])
        out[column] = pd.concat([out.loc[~rows, column], carried]).reindex(out.index)
    return out


def _remaining_decreased_on_started(derivation: _Derivation) -> pd.Index:
    """Codes of both updates started in the later one whose remaining duration decreased.

    Progress data under 3.4.K.4.b (iv); any other change of a remaining duration is a revision
    (3.4.K.4).
    """
    old, new = derivation.old.by_code, derivation.new.by_code
    common = new.index.intersection(old.index)
    started = new.loc[common, "is_started"].astype(bool)
    decreased = new.loc[common, "remain_drtn_hr_cnt"] < old.loc[common, "remain_drtn_hr_cnt"] - 1e-9
    return common[started & decreased]


def _apply_progress(derivation: _Derivation, before: Snapshot) -> Snapshot:
    """Carry the progress data of the later update onto the earlier plan, at the later status date.

    3.4.K.4.b: actual start, actual finish, percent complete, decreased remaining duration.
    """
    tasks = _with_columns_of_new(before.tasks, derivation, derivation.common, PROGRESS_COLUMNS)
    progressed = _remaining_decreased_on_started(derivation)
    tasks = _with_columns_of_new(tasks, derivation, progressed, ["remain_drtn_hr_cnt"])
    return replace(before, tasks=tasks, data_date=derivation.new.data_date)


def _apply_scope(derivation: _Derivation, before: Snapshot) -> Snapshot:
    """Carry the work the later plan holds.

    Activities added come with the links and assignments that reach them, deleted ones go with
    theirs, and types changed are carried.
    """
    added, deleted = derivation.added, derivation.deleted
    tasks = _with_columns_of_new(before.tasks, derivation, derivation.common, TYPE_COLUMNS)
    new_rows = derivation.new.tasks[derivation.new.tasks["task_code"].isin(added)]
    tasks = pd.concat([tasks[~tasks["task_code"].isin(deleted)], new_rows], ignore_index=True)
    links = before.relationships
    links = links[~links["pred_code"].isin(deleted) & ~links["succ_code"].isin(deleted)]
    new_links = derivation.new.relationships
    reaches_added = new_links["pred_code"].isin(added) | new_links["succ_code"].isin(added)
    links = pd.concat([links, new_links[reaches_added]], ignore_index=True)
    assignments = before.assignments[~before.assignments["task_code"].isin(deleted)]
    new_assignments = derivation.new.assignments[derivation.new.assignments["task_code"].isin(added)]
    assignments = pd.concat([assignments, new_assignments], ignore_index=True)
    return replace(before, tasks=tasks, relationships=links, assignments=assignments)


def _apply_durations(derivation: _Derivation, before: Snapshot) -> Snapshot:
    """Carry the replanned effort.

    Original durations, expected finishes, every remaining duration the progress step left (an
    increase, or a change on work not started: revisions under 3.4.K.4), and the resource
    assignments (their remaining units drive resource-dependent work).
    """
    tasks = _with_columns_of_new(before.tasks, derivation, derivation.common, DURATION_COLUMNS)
    revised = pd.Index(derivation.common).difference(_remaining_decreased_on_started(derivation))
    tasks = _with_columns_of_new(tasks, derivation, revised, ["remain_drtn_hr_cnt"])
    kept = before.assignments[~before.assignments["task_code"].isin(derivation.common)]
    replanned = derivation.new.assignments[derivation.new.assignments["task_code"].isin(derivation.common)]
    return replace(before, tasks=tasks, assignments=pd.concat([kept, replanned], ignore_index=True))


def _apply_logic(derivation: _Derivation, before: Snapshot) -> Snapshot:
    """Carry every relationship of the later update.

    The scope step already brought the links that reach an added activity; the rest are the links
    between activities of both updates and the links to other projects, whose far end is no
    activity of either update.
    """
    return replace(before, relationships=derivation.new.relationships)


def _apply_constraints(derivation: _Derivation, before: Snapshot) -> Snapshot:
    """Carry the activity constraints and the project's Must Finish By of the later update."""
    tasks = _with_columns_of_new(before.tasks, derivation, derivation.common, CONSTRAINT_COLUMNS)
    options = {**before.options, "must_finish_by": derivation.new.options.get("must_finish_by")}
    return replace(before, tasks=tasks, options=options)


def _apply_calendars_and_options(derivation: _Derivation, before: Snapshot) -> Snapshot:
    """Carry the calendars (assigned and defined) and the scheduling options of the later update.

    After this step the snapshot holds every input of the later update the engine reads.
    """
    tasks = _with_columns_of_new(before.tasks, derivation, derivation.common, CALENDAR_COLUMNS)
    new = derivation.new
    return replace(
        before,
        tasks=tasks,
        calendars=new.calendars,
        work_calendars=new.work_calendars,
        options=dict(new.options),
        planned_start=new.planned_start,
    )


@dataclass(frozen=True)
class Step:
    """One kind of change of the week.

    Its name, the changelog categories it accounts for, and how it carries that kind from the
    later update onto the snapshot before it. ``half_step`` reads the steps through this type
    only, so a new kind of change is a new ``Step`` in ``STEPS``, nothing else.
    """

    name: str
    categories: tuple[str, ...]
    apply: Callable[[_Derivation, Snapshot], Snapshot]
    # the kinds of the changelog's Tasks category the step carries: a rename or a move to
    # another WBS is no input of the recalculation and belongs to no step
    task_changes: tuple[str, ...] = ()

    def is_carried(self, log: pd.DataFrame) -> pd.Series:
        """Flag the rows of a changelog this step accounts for."""
        in_tasks = (log["category"] == "Tasks") & log["change"].isin(self.task_changes)
        return log["category"].isin(self.categories) | in_tasks


STEPS = [
    Step("progress", ("Progress",), _apply_progress),
    Step("scope", ("Scope",), _apply_scope, task_changes=("type changed",)),
    Step("durations", ("Durations", "Resources"), _apply_durations),
    Step("logic", ("Relationships",), _apply_logic),
    Step("constraints", ("Constraints",), _apply_constraints),
    Step("calendars and options", ("Calendars", "Options"), _apply_calendars_and_options, ("calendar changed",)),
]
STEP_NAMES = [step.name for step in STEPS]
STEP_COLUMNS = ["step", "finish", "shift_wd", "changes"]


@dataclass(frozen=True)
class HalfStep:
    """One week read step by step.

    ``steps``: the ``AS_SCHEDULED`` row, then one row per step: ``finish`` the recalculated finish
    once the step is applied, ``shift_wd`` its move from the row before (project calendar of the
    later update, days lost negative), ``changes`` the changelog rows of the step's categories.
    ``residual_wd``: the later update's recalculated finish against the last step's, 0 when the
    steps account for every change. ``period_wd``: working days between the two status dates on
    the later update's project calendar, the bound of 3.4.K.4.g (a slip beyond it is suspect).
    ``old_engine_gap_wd`` / ``new_engine_gap_wd``: ``engine_gap_wd`` of each update.
    """

    steps: pd.DataFrame
    old_finish: pd.Timestamp | None
    new_finish: pd.Timestamp | None
    residual_wd: float
    period_wd: float
    old_engine_gap_wd: float
    new_engine_gap_wd: float
    matched: int
    added: int
    deleted: int

    @property
    def finish_before_replanning(self) -> pd.Timestamp | None:
        """Finish once progress alone is applied.

        Where the earlier plan lands with the later update's status, nothing replanned.
        """
        return self.steps.set_index("step").loc["progress", "finish"]

    @property
    def slip_wd(self) -> float:
        """What the week's progress did to the finish: the shift of the progress step."""
        return float(self.steps.set_index("step").loc["progress", "shift_wd"])

    @property
    def replanning_wd(self) -> float:
        """What the replanning did: the shifts of every step after progress, summed."""
        return float(self.steps.set_index("step").loc[STEP_NAMES[1:], "shift_wd"].sum())

    @property
    def is_finish_reproduced(self) -> bool:
        """Both updates recalculate to the finish P6 stored in them: the shifts are the schedule's."""
        return self.old_engine_gap_wd == 0.0 and self.new_engine_gap_wd == 0.0

    @property
    def is_slip_beyond_period(self) -> bool:
        """3.4.K.4.g: the progress step lost more than the period holds.

        A revision slipped into the half-step, or the lack of progress pushed work into a
        non-working stretch of a calendar.
        """
        return pd.notna(self.period_wd) and self.slip_wd < -self.period_wd - 0.005


def _shift_wd(new: Snapshot, before: pd.Timestamp | None, after: pd.Timestamp | None) -> float:
    """Working days from ``before`` to ``after`` on the later update's project calendar, days lost negative.

    ``0.0 - x``, not ``-x``: an unmoved finish reads 0.0, never -0.0.
    """
    if before is None or after is None:
        return float("nan")
    return 0.0 - round(new.project_working_days(before, after), 2)


def engine_gap_wd(snapshot: Snapshot, recomputed: Schedule | None = None) -> float:
    """Recalculated finish of ``snapshot`` against the finish P6 stored in the file.

    Working days of the project calendar, a recalculated finish later than the file's negative;
    0.0 when the engine reproduces P6's finish to the minute, missing when either is. The file's
    finish is its latest activity finish (``Snapshot.finish_date``).
    """
    recomputed = schedule(snapshot) if recomputed is None else recomputed
    return _shift_wd(snapshot, snapshot.finish_date, recomputed.finish)


def _step_row(name: str, before: pd.Timestamp | None, after: pd.Timestamp | None, changes: int, new: Snapshot) -> dict:
    return {"step": name, "finish": after, "shift_wd": _shift_wd(new, before, after), "changes": changes}


def half_step(old: Snapshot, new: Snapshot) -> HalfStep:
    """Finish of ``old`` rescheduled with ``new``'s changes applied one step at a time (``STEPS``).

    Raises ``ScheduleError`` when one of the snapshots, or a derived one, cannot be scheduled.
    """
    derivation = _Derivation(old, new, sorted(set(old.by_code.index) & set(new.by_code.index)))
    log = changelog(old, new)
    old_schedule, new_schedule = schedule(old), schedule(new)
    old_finish, new_finish = old_schedule.finish, new_schedule.finish
    period_wd = float("nan") if old.data_date is None else new.project_working_days(old.data_date, new.data_date)
    rows = [{"step": AS_SCHEDULED, "finish": old_finish, "shift_wd": float("nan"), "changes": 0}]
    derived, finish = old, old_finish
    for step in STEPS:
        derived = step.apply(derivation, derived)
        stepped_finish = schedule(derived).finish
        changes = int(step.is_carried(log).sum())
        rows.append(_step_row(step.name, finish, stepped_finish, changes, new))
        finish = stepped_finish
    return HalfStep(
        steps=pd.DataFrame(rows, columns=STEP_COLUMNS),
        old_finish=old_finish,
        new_finish=new_finish,
        residual_wd=_shift_wd(new, finish, new_finish),
        period_wd=period_wd,
        old_engine_gap_wd=engine_gap_wd(old, old_schedule),
        new_engine_gap_wd=engine_gap_wd(new, new_schedule),
        matched=len(derivation.common),
        added=len(derivation.added),
        deleted=len(derivation.deleted),
    )


# --- where the revisions fall ---------------------------------------------------------------------

WITHIN_LOOKAHEAD = "within the lookahead"
BEYOND_LOOKAHEAD = "beyond the lookahead"
HORIZON_COLUMNS = ["step", WITHIN_LOOKAHEAD, BEYOND_LOOKAHEAD, "beyond_pct"]


def revisions_by_horizon(old: Snapshot, new: Snapshot, lookahead_weeks: float) -> pd.DataFrame:
    """Non-progress revisions of the week by step, split by where the revised activity sits in time.

    One row per step after progress, then ``all``: the changelog rows the step carries that name
    an activity, ``within the lookahead`` when the activity starts on or before the later status
    date plus ``lookahead_weeks`` (work under way included), ``beyond the lookahead`` otherwise;
    ``beyond_pct`` the share beyond. The start is the later update's, the earlier one's for an
    activity deleted since; a row without an activity or a start is left out.

    The lookahead is where a Last Planner team makes work ready; revisions mostly beyond it
    reshape the far plan (docs/formulas.md 5.1: the source, and what is xerscope's reading).
    """
    log = changelog(old, new)
    starts = new.by_code["start"].combine_first(old.by_code["start"])
    start = log["task_code"].map(starts)
    limit = new.data_date + pd.Timedelta(weeks=lookahead_weeks) if new.data_date is not None else pd.NaT
    is_within = start <= limit
    is_beyond = start > limit
    rows = []
    for step in STEPS[1:]:
        carried = step.is_carried(log)
        rows.append(_horizon_row(step.name, int((carried & is_within).sum()), int((carried & is_beyond).sum())))
    rows.append(
        _horizon_row("all", sum(row[WITHIN_LOOKAHEAD] for row in rows), sum(row[BEYOND_LOOKAHEAD] for row in rows))
    )
    return pd.DataFrame(rows, columns=HORIZON_COLUMNS)


def _horizon_row(step: str, within: int, beyond: int) -> dict:
    total = within + beyond
    return {
        "step": step,
        WITHIN_LOOKAHEAD: within,
        BEYOND_LOOKAHEAD: beyond,
        "beyond_pct": 100 * beyond / total if total else None,
    }


# --- how the project's finish is held -----------------------------------------------------------

LAST_ACTIVITY = "last task"
MUST_FINISH_BY = "must finish by"
MANDATORY_FINISH = "mandatory finish"


def finish_case(snapshot: Snapshot, recomputed: Schedule | None = None) -> tuple[str, pd.Timestamp | None]:
    """How the finish of ``snapshot`` is held, and the date that holds it.

    ``must finish by``: the project has one (PROJECT.plan_end_date); a Must Finish By bounds the
    late dates only, so the early finish still moves and float turns negative past the date.
    ``mandatory finish``: an end point (nothing follows it) carries a Mandatory Finish; its date
    cannot move, and the delay shows in the float of what precedes it. ``last task``: the
    finish is the latest early finish and moves freely. A completed activity holds nothing:
    P6 does not schedule it, so its constraint has no effect (Oracle P6 help, Constraints).
    """
    must_finish_by = snapshot.options.get("must_finish_by")
    if must_finish_by is not None:
        return MUST_FINISH_BY, must_finish_by
    activities = without(snapshot.activities, snapshot.data_date, ["loe", "complete"])
    at_the_end = ~has_successor_in_project(snapshot, activities)
    mandatory = activities[at_the_end & (activities["cstr_type"] == "CS_MANDFIN")]
    if not mandatory.empty:
        return MANDATORY_FINISH, mandatory["cstr_date"].max()
    recomputed = schedule(snapshot) if recomputed is None else recomputed
    return LAST_ACTIVITY, recomputed.finish


def longest_path_float_d(snapshot: Snapshot, recomputed: Schedule | None = None) -> float | None:
    """Lowest total float of the recalculated longest path, in days of the project calendar.

    Under a Must Finish By or a Mandatory Finish, this is where the delay the finish cannot show
    goes. None when nothing is on the longest path.
    """
    recomputed = schedule(snapshot) if recomputed is None else recomputed
    on_path = recomputed.frame[recomputed.frame["longest_path"].astype(bool)]
    if on_path.empty:
        return None
    return float(on_path["tf_hr"].min()) / snapshot.calendar().hours_per_day


# --- the series -----------------------------------------------------------------------------------

SERIES_COLUMNS = [
    "data_date",
    "finish_case",
    "held_by",
    "finish",
    "finish_before_replanning",
    "slip_wd",
    "replanning_wd",
    "residual_wd",
    "period_wd",
    "engine_gap_wd",
    "longest_path_float_d",
    "tasks_matched",
    "tasks_added",
    "tasks_deleted",
    "note",
]


def half_step_series(store: SnapshotStore) -> pd.DataFrame:
    """One row per update after the first, the week read against the update before it.

    Its finish, the finish before replanning, the week's slip and replanning, the residual, how
    the finish is held, the longest path's float, the activities matched, added and deleted. A
    finish held still week after week while ``slip_wd`` stays negative is a delay absorbed by
    replanning. The sum of the moves over the series equals the move between the first and the
    last update (3.4.E.16), the residuals apart. A week that cannot be scheduled (the update
    itself, or a step: links carried one kind at a time can close a loop the two updates do not
    have) keeps its row, with the reason in ``note`` and no figure.
    """
    rows = []
    for index in range(1, len(store)):
        old, new = store[index - 1], store[index]
        try:
            rows.append(_series_row(old, new))
        except ScheduleError as error:
            rows.append({"data_date": new.data_date, "note": f"not read: {error}"})
    return pd.DataFrame(rows, columns=SERIES_COLUMNS)


def _series_row(old: Snapshot, new: Snapshot) -> dict:
    read = half_step(old, new)
    case, held_by = finish_case(new)
    return {
        "data_date": new.data_date,
        "finish_case": case,
        "held_by": held_by,
        "finish": read.new_finish,
        "finish_before_replanning": read.finish_before_replanning,
        "slip_wd": read.slip_wd,
        "replanning_wd": read.replanning_wd,
        "residual_wd": read.residual_wd,
        "period_wd": read.period_wd,
        "engine_gap_wd": read.new_engine_gap_wd,
        "longest_path_float_d": longest_path_float_d(new),
        "tasks_matched": read.matched,
        "tasks_added": read.added,
        "tasks_deleted": read.deleted,
        "note": "",
    }
