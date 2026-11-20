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

    ``base_minutes`` gives the remaining minutes each driving assignment would work. Each assignment
    gives a start (``activity_start_given_by``); the activity starts at the earliest on its own
    calendar, and each assignment then runs forward from that start. An expected finish that applies
    sets an assignment's remaining work, measured on its calendar from its placement.
    """
    starts, durations, expected_applies = [], {}, False
    for assignment in assignments:
        duration_minutes = base_minutes[assignment.taskrsrc_id]
        assignment_start = lagged_start(assignment, lower_start)
        if is_expected_finish_applied(expected_date, assignment_start, finish_bound):
            duration_minutes = float(assignment.axis.between(assignment_start, expected_date))
            expected_applies = True
        durations[assignment.taskrsrc_id] = duration_minutes
        starts.append(activity_start_given_by(assignment, assignment_start, duration_minutes, finish_bound))
    start = axis.snap_start(min(starts))
    finishes, dates = [], {}
    for assignment in assignments:
        assignment_start = lagged_start(assignment, start)
        assignment_finish = finish_run_from(assignment, assignment_start, durations[assignment.taskrsrc_id])
        dates[assignment.taskrsrc_id] = (assignment_start, assignment_finish)
        finishes.append(assignment_finish)
    return ForwardPlacement(start, max(finishes), durations, dates, expected_applies)


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
