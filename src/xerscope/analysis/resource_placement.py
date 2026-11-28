"""Placing resource-dependent work on its assignments' calendars (CPM engine).

Pure functions: they receive the driving assignments of one activity, the activity's time axis and
its bounds, and return dates; they keep no state. ``analysis/cpm.py`` computes the bounds, calls them
and records what they return. The rules each one follows, and their sources in the P6 corpus, are
given where the engine calls them (``_Run.rsrc_early``, ``_Run.place_late``).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..xer.calendar import TimeAxis

AssignmentDates = dict[str, tuple[pd.Timestamp, pd.Timestamp]]  # taskrsrc_id -> start, finish


@dataclass
class Assignment:
    """One open assignment as the CPM schedules it."""

    taskrsrc_id: str
    rsrc: str
    axis: TimeAxis
    lag_minutes: float  # remaining assignment lag, minutes
    duration_minutes: float  # remaining duration, minutes (None = the activity's)
    driving: bool


@dataclass(frozen=True)
class ForwardPlacement:
    """Early dates of a resource-dependent activity and of each of its driving assignments."""

    start: pd.Timestamp
    finish: pd.Timestamp
    assignment_minutes: dict[str, float]  # taskrsrc_id -> remaining minutes as placed
    assignment_dates: AssignmentDates
    expected_finish_applies: bool


@dataclass(frozen=True)
class BackwardPlacement:
    """Late dates of a resource-dependent activity and of each of its driving assignments."""

    start: pd.Timestamp
    finish: pd.Timestamp
    assignment_dates: AssignmentDates
    start_bound: pd.Timestamp | None = None


def shift(axis: TimeAxis, instant: pd.Timestamp, lag_minutes: float) -> pd.Timestamp:
    """``instant`` moved by a lag (a lead when negative) in working minutes of ``axis``."""
    return instant if lag_minutes == 0 else axis.add(instant, lag_minutes, finish=lag_minutes > 0)


def lagged_start(assignment: Assignment, measured_from: pd.Timestamp) -> pd.Timestamp:
    """Start of an assignment placed from an instant: shifted by its lag, on its calendar."""
    return assignment.axis.snap_start(shift(assignment.axis, measured_from, assignment.lag_minutes))


def finish_run_from(assignment: Assignment, assignment_start: pd.Timestamp, duration_minutes: float) -> pd.Timestamp:
    """Finish of an assignment that works its duration from a start, on its calendar.

    The start itself when no work is left.
    """
    if not duration_minutes:
        return assignment_start
    return assignment.axis.add(assignment_start, duration_minutes, finish=True)


def is_expected_finish_applied(
    expected_date: pd.Timestamp | None, assignment_start: pd.Timestamp, finish_bound: pd.Timestamp | None
) -> bool:
    """Whether the expected finish sets the remaining work of an assignment.

    It does when there is one, after the assignment's start and not before the finish bound.
    """
    return (
        expected_date is not None
        and expected_date > assignment_start
        and (finish_bound is None or expected_date >= finish_bound)
    )


def place_forward(
    axis: TimeAxis,
    assignments: list[Assignment],
    base_minutes: dict[str, float],
    lower_start: pd.Timestamp,
    finish_bound: pd.Timestamp | None,
    expected_date: pd.Timestamp | None,
) -> ForwardPlacement:
    """Early dates of a resource-dependent activity from its lower start and its finish bound.

    ``base_minutes`` gives the remaining minutes each driving assignment would work; an expected finish
    that applies resizes it first, on the assignment's calendar from its placement. A finish bound may
    then move the start later (``start_set_by_finish_bound``). Each assignment starts at its own
    calendar's first working time at or after the activity's start, works after its lag, and the
    activity spans them (``assignment_dates_from``).
    """
    durations, expected_applies = sized_minutes(assignments, base_minutes, lower_start, finish_bound, expected_date)
    activity_start = lower_start
    bound_start = start_set_by_finish_bound(axis, assignments, durations, finish_bound)
    set_by_bound = bound_start is not None and bound_start > activity_start
    if set_by_bound:
        activity_start = bound_start
    starts, dates = assignment_dates_from(assignments, durations, activity_start, finish_bound)
    finish = max(finish for _, finish in dates.values())
    if set_by_bound:
        finish = finish_printed_at_bound(axis, finish, finish_bound)
    return ForwardPlacement(min(starts), finish, durations, dates, expected_applies)


def sized_minutes(
    assignments: list[Assignment],
    base_minutes: dict[str, float],
    lower_start: pd.Timestamp,
    finish_bound: pd.Timestamp | None,
    expected_date: pd.Timestamp | None,
) -> tuple[dict[str, float], bool]:
    """Remaining minutes of each assignment, and whether an expected finish set any of them.

    An expected finish after an assignment's start and not before the finish bound sets its work,
    measured on its calendar from where it is placed (H26-11 A1090; H14-05 A1040 keeps the file's).
    """
    durations, expected_applies = {}, False
    for assignment in assignments:
        duration_minutes = base_minutes[assignment.taskrsrc_id]
        assignment_start = lagged_start(assignment, lower_start)
        if is_expected_finish_applied(expected_date, assignment_start, finish_bound):
            duration_minutes = float(assignment.axis.between(assignment_start, expected_date))
            expected_applies = True
        durations[assignment.taskrsrc_id] = duration_minutes
    return durations, expected_applies


def start_set_by_finish_bound(
    axis: TimeAxis, assignments: list[Assignment], durations: dict[str, float], finish_bound: pd.Timestamp | None
) -> pd.Timestamp | None:
    """Start a finish bound (FF, SF link) gives the activity, None when there is none.

    The bound, off the activity calendar's working time, first moves to its next opening. Each
    assignment with work reaches it at its own calendar's last close at or before it, its work and
    then its lag before; so does one with no work but a lag, beside one with work. The earliest of
    those starts, at the activity calendar's next opening, is the start the bound gives. P6 23.12.1,
    26.8 not measured: probes ZZ-CPP-RD2F, -RDSF, -RSRC, -KD; corpus H9-09 A1230, H10-04 A1040,
    H27-08 A1260.
    """
    if finish_bound is None:
        return None
    reached = axis.keep_or_next(finish_bound)
    has_work = any(durations[assignment.taskrsrc_id] > 0 for assignment in assignments)
    starts = []
    for assignment in assignments:
        duration = durations[assignment.taskrsrc_id]
        if duration <= 0 and not (assignment.lag_minutes > 0 and has_work):
            continue
        work_start = assignment.axis.add(reached, -duration, finish=False)
        starts.append(shift(assignment.axis, work_start, -assignment.lag_minutes))
    return axis.snap_start(min(starts)) if starts else None


def assignment_dates_from(
    assignments: list[Assignment],
    durations: dict[str, float],
    activity_start: pd.Timestamp,
    finish_bound: pd.Timestamp | None,
) -> tuple[list[pd.Timestamp], AssignmentDates]:
    """Where each assignment opens and its start and finish, all run from one activity start.

    Each opens at its own calendar's first working time at or after that start (a resource that opens
    later, or has that day off, starts the work later: H24-03 A1150, H24-10 A1160) and works after its
    lag. One with no work left sits where it opens; a finish bound moves it to its next opening after
    the bound only when no assignment has work left (H13-06 A1230; H12-01 A1200 keeps its Monday).
    """
    has_work = any(durations[assignment.taskrsrc_id] > 0 for assignment in assignments)
    starts, dates = [], {}
    for assignment in assignments:
        opening = assignment.axis.snap_start(activity_start)
        start = lagged_start(assignment, opening)
        duration = durations[assignment.taskrsrc_id]
        if duration > 0:
            finish = assignment.axis.add(start, duration, finish=True)
        else:
            if finish_bound is not None and not has_work:
                start = max(start, assignment.axis.snap_start(finish_bound))
                opening = max(opening, shift(assignment.axis, start, -assignment.lag_minutes))
            finish = start
        starts.append(opening)
        dates[assignment.taskrsrc_id] = (start, finish)
    return starts, dates


def finish_printed_at_bound(axis: TimeAxis, finish: pd.Timestamp, finish_bound: pd.Timestamp) -> pd.Timestamp:
    """Early finish of work whose start the finish bound set.

    At the bound as it stands on the activity calendar (at a close, or the next opening after it) when
    no working time separates them.
    """
    if axis.between(min(finish, finish_bound), max(finish, finish_bound)) == 0:
        return max(finish, axis.keep_or_next(finish_bound))
    return finish


def place_backward(
    axis: TimeAxis,
    assignments: list[Assignment],
    durations: dict[str, float],
    late_finish_bound: pd.Timestamp | None,
    late_start_bound: pd.Timestamp | None,
) -> BackwardPlacement:
    """Late dates of a resource-dependent activity from its late finish bound and its late start bound.

    ``durations`` gives the remaining minutes each driving assignment works. Each runs back from the
    activity calendar's last close at or before the finish bound, on its own calendar
    (``assignment_late_dates``). A start bound (SS, SF link, start constraint) binds only where the
    activity's late start does not already meet it (``held_start_bound``) and where it moves some
    assignment's finish earlier; with two or more assignments the latest finish it gives is the
    activity's, and all run back from it (``common_late_finish``). ``start_bound`` is the bound as
    it binds, at the activity calendar's close before it when off its working time, for the caller to
    print the late start there. P6 23.12.1, 26.8 not measured.
    """
    if late_finish_bound is None:
        # a pinned start and no finish bound: the work runs forward from the pin
        late_finish_bound = max(
            finish_run_from(assignment, lagged_start(assignment, late_start_bound), durations[assignment.taskrsrc_id])
            for assignment in assignments
        )
    finish_limit = axis.snap_finish(late_finish_bound)
    start_bound = held_start_bound(assignments, durations, finish_limit, late_start_bound)
    bound_at = None if start_bound is None else axis.keep_or_previous(start_bound)
    placed = [assignment_late_dates(axis, assignment, durations[assignment.taskrsrc_id], finish_limit, bound_at)
              for assignment in assignments]  # fmt: skip
    if len(assignments) > 1 and any(late.bound_taken for late in placed):
        placed = common_late_finish(axis, assignments, durations, placed)
    if bound_at is not None and not any(
        late.finish < assignment.axis.snap_finish(late_finish_bound)
        for assignment, late in zip(assignments, placed, strict=True)
    ):
        # the bound moves no assignment's finish: placed as with no bound (probe ZZ-CPP-ZLB B1, B2)
        return place_backward(axis, assignments, durations, late_finish_bound, None)
    dates = {
        assignment.taskrsrc_id: (late.start, late.finish) for assignment, late in zip(assignments, placed, strict=True)
    }
    start = min(late.activity_start for late in placed)
    finish = max(late.finish for late in placed)
    return BackwardPlacement(start, finish, dates, bound_at)


def held_start_bound(
    assignments: list[Assignment],
    durations: dict[str, float],
    finish_limit: pd.Timestamp,
    late_start_bound: pd.Timestamp | None,
) -> pd.Timestamp | None:
    """Return the start bound, or None where the activity's late start already meets it.

    That late start is the earliest of the assignments' own, each run back from the finish limit
    with its work and its lag; where it is no later than the bound, no assignment takes the bound,
    not even one whose own late start is later (probe ZZ-CPP-RD2S; corpus H12-11 A1160).
    """
    if late_start_bound is None:
        return None
    first = min(
        shift(
            assignment.axis,
            run_back(assignment, durations[assignment.taskrsrc_id], finish_limit),
            -assignment.lag_minutes,
        )
        for assignment in assignments
    )
    return None if late_start_bound > first else late_start_bound


def run_back(assignment: Assignment, duration: float, finish_limit: pd.Timestamp) -> pd.Timestamp:
    """Start of an assignment that works its duration back from its last close at or before a limit."""
    finish = assignment.axis.snap_finish(finish_limit)
    return assignment.axis.add(finish, -duration, finish=False) if duration > 0 else finish


@dataclass(frozen=True)
class LateAssignment:
    """Late dates of one assignment and what the activity's dates need from it.

    The start it gives the activity, whether a bound set it, and the start a lagged assignment with no
    work took at the bound (None otherwise).
    """

    start: pd.Timestamp
    finish: pd.Timestamp
    activity_start: pd.Timestamp
    bound_taken: bool = False
    start_at_bound: pd.Timestamp | None = None


def assignment_late_dates(
    axis: TimeAxis,
    assignment: Assignment,
    duration: float,
    finish_limit: pd.Timestamp,
    bound_at: pd.Timestamp | None,
) -> LateAssignment:
    """Late dates of one driving assignment, run back from the finish limit on its own calendar.

    A start bound applies on the assignment's calendar at its next opening at or after it (probe
    ZZ-CPP-SSNA; corpus H13-09 A1130), and binds where it is no later than the start the assignment
    gives the activity. Then the assignment starts at the bound, its lag later, and runs forward;
    with work, its finish falls back to the activity calendar's last close at or before it (probe
    ZZ-CPP-RDSF B3). With no work but a lag, it lands its lag after the bound, at the activity
    calendar's last working time at or before that, and gives the earlier of the bound and its lag
    back from there (probes ZZ-CPP-ZLA, -ZBS; corpus H23-08 A1340, H24-12 A1180). With neither, it
    sits at its last working time at or before the earlier of the limit and the bound.
    """
    calendar = assignment.axis
    lag = assignment.lag_minutes
    bound = None if bound_at is None else calendar.snap_start(bound_at)
    if duration <= 0 and not lag:
        finish = calendar.snap_finish(finish_limit if bound is None else min(finish_limit, bound))
        return LateAssignment(finish, finish, finish)
    start = run_back(assignment, duration, finish_limit)
    activity_start = shift(calendar, start, -lag)
    if bound is None or bound > activity_start:
        return LateAssignment(start, calendar.snap_finish(finish_limit), activity_start)
    activity_start = calendar.keep_or_previous(bound)
    start = calendar.snap_start(shift(calendar, activity_start, lag))
    if duration <= 0:
        return lag_only_at_bound(axis, calendar, start, activity_start, lag)
    return work_from_bound(axis, assignment, duration, start)


def lag_only_at_bound(
    axis: TimeAxis, calendar: TimeAxis, start: pd.Timestamp, at_bound: pd.Timestamp, lag: float
) -> LateAssignment:
    """Place an assignment with no work and a lag that took a bound.

    It finishes where its lag lands, at the activity calendar's last working time at or before it.
    """
    finish = axis.snap_finish(start)
    return LateAssignment(start, finish, min(at_bound, calendar.add(finish, -lag, finish=False)), True, at_bound)


def work_from_bound(axis: TimeAxis, assignment: Assignment, duration: float, start: pd.Timestamp) -> LateAssignment:
    """Run an assignment with work that took a bound forward from its start.

    Its finish takes the activity calendar's last close at or before it, and the assignment then runs
    back from there (probe ZZ-CPP-RDSF B3).
    """
    calendar = assignment.axis
    finish = calendar.add(start, duration, finish=True)
    closed = calendar.snap_finish(axis.snap_finish(finish))
    if closed < finish:
        finish = closed
        start = calendar.add(finish, -duration, finish=False)
    return LateAssignment(start, finish, shift(calendar, start, -assignment.lag_minutes), True)


def common_late_finish(
    axis: TimeAxis, assignments: list[Assignment], durations: dict[str, float], placed: list[LateAssignment]
) -> list[LateAssignment]:
    """Run every assignment back from the common late finish a bound gives two or more of them.

    That finish is the latest any of them reaches, at the activity calendar's last close at or before
    it. One with no work and no lag sits at its last working time at or before it (probe ZZ-CPP-ZRA;
    corpus H24-09 A1260); one with no work and a lag that took the bound sits there too and gives the
    earlier of the bound and its lag back (probe ZZ-CPP-ZLB B4; corpus H25-02 A1460, H25-08 A1220).
    Probes ZZ-CPP-RDSF B1, B2, B5; corpus H9-08 A1050.
    """
    late_finish = axis.snap_finish(max(late.finish for late in placed))
    common = []
    for assignment, late in zip(assignments, placed, strict=True):
        calendar = assignment.axis
        duration = durations[assignment.taskrsrc_id]
        finish = calendar.snap_finish(late_finish)
        if duration > 0:
            start = calendar.add(finish, -duration, finish=False)
            common.append(LateAssignment(start, finish, shift(calendar, start, -assignment.lag_minutes), True))
        elif not assignment.lag_minutes:
            common.append(LateAssignment(finish, finish, finish, late.bound_taken))
        elif late.start_at_bound is not None:
            back = calendar.add(finish, -assignment.lag_minutes, finish=False)
            common.append(LateAssignment(late.start, finish, min(late.start_at_bound, back), True, late.start_at_bound))
        else:
            common.append(late)
    return common


def start_printed_at_bound(axis: TimeAxis, placement: BackwardPlacement) -> pd.Timestamp:
    """Late start shown: the start bound as it binds, or the assignments' late start.

    The bound where no activity working time separates it from the late start the assignments give
    (probes ZZ-CPP-SBNA, -SBNC; corpus H15-10 A1070).
    """
    bound = placement.start_bound
    if bound is not None and placement.start >= bound and axis.between(bound, placement.start) == 0:
        return bound
    return placement.start
