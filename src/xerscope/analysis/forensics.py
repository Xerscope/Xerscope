"""Half-step reading of one week: what moved the project finish between two updates.

AACE RP 29R-03 (Forensic Schedule Analysis, 2011) MIP 3.2, contemporaneous period analysis,
as Hegazy & Zhang ("Daily Windows Delay Analysis", 2005) run it: the earlier update is
rescheduled with the later update's changes applied one kind at a time, and the move of the
finish at each step is what that kind of change did. Here the kinds are the categories of the
changelog, applied in ``STEPS`` order, each step a derived snapshot the CPM engine
(``analysis.cpm.schedule``) recalculates. The baseline is not read: the two updates are.

The first step, progress, gives the finish the project would show had nothing been
replanned since the earlier update: the delay of the week. The steps after it are the
replanning that absorbed it or added to it. When every step is applied the derived snapshot
holds all the later update's inputs, so its finish is the later update's recalculated finish;
``residual_wd`` records any difference (a change the changelog does not see).

Conventions no source settles, set here and stated on the page:

- the order of the steps: progress first, because it is the only change P6 itself imposes on a
  recalculation; then scope, durations, logic, constraints, calendars and options;
- the remaining duration of work under way belongs to progress (P6 updates it with the
  status); that of work not started is a plan change and belongs to durations.

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
from .cpm import Schedule, schedule

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

    A column the later update's file does not carry is left as it is.
    """
    out = tasks.copy()
    rows = out["task_code"].isin(codes)
    for column in columns:
        if column not in derivation.new.by_code.columns:
            continue
        values = derivation.new.by_code[column].reindex(out.loc[rows, "task_code"])
        out.loc[rows, column] = values.to_numpy()
    return out


def _apply_progress(derivation: _Derivation, before: Snapshot) -> Snapshot:
    """Carry the later status date, statuses and actual dates onto the earlier plan.

    The remaining duration of the work under way comes along: P6 updates it with the status.
    """
    tasks = _with_columns_of_new(before.tasks, derivation, derivation.common, PROGRESS_COLUMNS)
    started = derivation.new.by_code.index[derivation.new.by_code["is_started"].astype(bool)]
    tasks = _with_columns_of_new(tasks, derivation, started.intersection(derivation.common), ["remain_drtn_hr_cnt"])
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

    Original durations, expected finishes, the remaining duration of work not started, and the
    resource assignments (their remaining units drive resource-dependent work).
    """
    tasks = _with_columns_of_new(before.tasks, derivation, derivation.common, DURATION_COLUMNS)
    not_started = derivation.new.by_code.index[~derivation.new.by_code["is_started"].astype(bool)]
    tasks = _with_columns_of_new(tasks, derivation, not_started.intersection(derivation.common), ["remain_drtn_hr_cnt"])
    kept = before.assignments[~before.assignments["task_code"].isin(derivation.common)]
    replanned = derivation.new.assignments[derivation.new.assignments["task_code"].isin(derivation.common)]
    return replace(before, tasks=tasks, assignments=pd.concat([kept, replanned], ignore_index=True))


def _apply_logic(derivation: _Derivation, before: Snapshot) -> Snapshot:
    """Carry the later update's relationships between the activities both updates hold."""
    common = set(derivation.common)

    def is_between_common(links: pd.DataFrame) -> pd.Series:
        return links["pred_code"].isin(common) & links["succ_code"].isin(common)

    kept = before.relationships[~is_between_common(before.relationships)]
    replanned = derivation.new.relationships[is_between_common(derivation.new.relationships)]
    return replace(before, relationships=pd.concat([kept, replanned], ignore_index=True))


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


STEPS = [
    Step("progress", ("Progress",), _apply_progress),
    Step("scope", ("Scope",), _apply_scope),
    Step("durations", ("Durations", "Resources"), _apply_durations),
    Step("logic", ("Relationships",), _apply_logic),
    Step("constraints", ("Constraints",), _apply_constraints),
    Step("calendars and options", ("Calendars", "Options", "Tasks"), _apply_calendars_and_options),
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
    steps account for every change.
    """

    steps: pd.DataFrame
    old_finish: pd.Timestamp | None
    new_finish: pd.Timestamp | None
    residual_wd: float
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


def _shift_wd(new: Snapshot, before: pd.Timestamp | None, after: pd.Timestamp | None) -> float:
    """Working days from ``before`` to ``after`` on the later update's project calendar, days lost negative.

    ``0.0 - x``, not ``-x``: an unmoved finish reads 0.0, never -0.0.
    """
    if before is None or after is None:
        return float("nan")
    return 0.0 - round(new.project_working_days(before, after), 2)


def _step_row(name: str, before: pd.Timestamp | None, after: pd.Timestamp | None, changes: int, new: Snapshot) -> dict:
    return {"step": name, "finish": after, "shift_wd": _shift_wd(new, before, after), "changes": changes}


def half_step(old: Snapshot, new: Snapshot) -> HalfStep:
    """Finish of ``old`` rescheduled with ``new``'s changes applied one step at a time (``STEPS``).

    Raises ``ScheduleError`` when one of the snapshots, or a derived one, cannot be scheduled.
    """
    derivation = _Derivation(old, new, sorted(set(old.by_code.index) & set(new.by_code.index)))
    log = changelog(old, new)
    old_finish, new_finish = schedule(old).finish, schedule(new).finish
    rows = [{"step": AS_SCHEDULED, "finish": old_finish, "shift_wd": float("nan"), "changes": 0}]
    derived, finish = old, old_finish
    for step in STEPS:
        derived = step.apply(derivation, derived)
        stepped_finish = schedule(derived).finish
        changes = int(log["category"].isin(step.categories).sum())
        rows.append(_step_row(step.name, finish, stepped_finish, changes, new))
        finish = stepped_finish
    return HalfStep(
        steps=pd.DataFrame(rows, columns=STEP_COLUMNS),
        old_finish=old_finish,
        new_finish=new_finish,
        residual_wd=_shift_wd(new, finish, new_finish),
        matched=len(derivation.common),
        added=len(derivation.added),
        deleted=len(derivation.deleted),
    )


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
    finish is the latest early finish and moves freely.
    """
    must_finish_by = snapshot.options.get("must_finish_by")
    if must_finish_by is not None:
        return MUST_FINISH_BY, must_finish_by
    activities = snapshot.activities
    has_successor = set(snapshot.relationships["pred_code"])
    at_the_end = ~activities["task_code"].isin(has_successor) & ~activities["is_loe"].astype(bool)
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
    "longest_path_float_d",
    "matched",
    "added",
    "deleted",
]


def half_step_series(store: SnapshotStore) -> pd.DataFrame:
    """One row per update after the first, the week read against the update before it.

    Its finish, the finish before replanning, the week's slip and replanning, the residual, how
    the finish is held, the longest path's float, the activities matched, added and deleted. A
    finish held still week after week while ``slip_wd`` stays negative is a delay absorbed by
    replanning.
    """
    rows = []
    for index in range(1, len(store)):
        old, new = store[index - 1], store[index]
        read = half_step(old, new)
        case, held_by = finish_case(new)
        rows.append(
            {
                "data_date": new.data_date,
                "finish_case": case,
                "held_by": held_by,
                "finish": read.new_finish,
                "finish_before_replanning": read.finish_before_replanning,
                "slip_wd": read.slip_wd,
                "replanning_wd": read.replanning_wd,
                "residual_wd": read.residual_wd,
                "longest_path_float_d": longest_path_float_d(new),
                "matched": read.matched,
                "added": read.added,
                "deleted": read.deleted,
            }
        )
    return pd.DataFrame(rows, columns=SERIES_COLUMNS)
