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


def activity_start_given_by(
    assignment: Assignment,
    assignment_start: pd.Timestamp,
    duration_minutes: float,
    finish_bound: pd.Timestamp | None,
) -> pd.Timestamp:
    """Start one driving assignment gives the activity: the assignment's start less its lag.

    An assignment that would finish before the finish bound is first moved to finish at the bound, or
    at the next working time of its calendar, and starts its duration before; with no work left, it
    starts at that finish.
    """
    assignment_finish = finish_run_from(assignment, assignment_start, duration_minutes)
    if finish_bound is not None and assignment_finish < finish_bound:
        assignment_finish = assignment.axis.keep_or_next(finish_bound)
        assignment_start = assignment_finish
        if duration_minutes:
            assignment_start = assignment.axis.add(assignment_finish, -duration_minutes, finish=False)
    return shift(assignment.axis, assignment_start, -assignment.lag_minutes)


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


def assignment_late_dates(
    assignment: Assignment,
    duration: float,
    upper_start: pd.Timestamp | None,
    upper_finish: pd.Timestamp | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None, bool]:
    """Latest start and finish of one driving assignment on its resource calendar.

    The third value says whether the start bound placed it with no assignment lag (the activity's late
    start is then that bound). The assignment runs back from the finish bound; the start bound, moved
    by the assignment lag, takes over when it is earlier or when there is no finish bound.
    """
    start = finish = None
    if upper_finish is not None:
        finish = assignment.axis.snap_finish(upper_finish)
        start = assignment.axis.add(finish, -duration, finish=False) if duration else finish
    if upper_start is None:
        return start, finish, False
    candidate = assignment.axis.snap_start(shift(assignment.axis, upper_start, assignment.lag_minutes))
    if start is None or candidate < start:
        finish = assignment.axis.add(candidate, duration, finish=True) if duration else candidate
        return candidate, finish, assignment.lag_minutes == 0
    return start, finish, False


def place_backward(
    axis: TimeAxis,
    assignments: list[Assignment],
    durations: dict[str, float],
    upper_start: pd.Timestamp | None,
    upper_finish: pd.Timestamp | None,
    late_start_bound: pd.Timestamp | None,
    alap: bool,
) -> BackwardPlacement:
    """Late dates of a resource-dependent activity from its bounds taken on its calendar.

    ``durations`` gives the remaining minutes each driving assignment works. Each assignment is placed
    by ``assignment_late_dates``; the activity starts at the earliest assignment start less its lag. A
    start the start bound placed with no lag is written at the bound's own instant
    (``late_start_bound``), except when placing early dates (``alap``).
    """
    starts, finishes, driven, dates = [], [], False, {}
    for assignment in assignments:
        assignment_start, assignment_finish, is_driven = assignment_late_dates(
            assignment, durations[assignment.taskrsrc_id], upper_start, upper_finish
        )
        driven = driven or is_driven
        dates[assignment.taskrsrc_id] = (assignment_start, assignment_finish)
        starts.append(shift(assignment.axis, assignment_start, -assignment.lag_minutes))
        finishes.append(assignment_finish)
    start = min(starts)
    if driven and start == upper_start and not alap:
        # written at the bound's instant, as a late date from an SS bound is on
        # task-dependent work (H26-04 A1440: late start Wed 16:00, not Thu 08:00)
        start = axis.keep_or_previous(late_start_bound)
    return BackwardPlacement(start, max(finishes), dates)
