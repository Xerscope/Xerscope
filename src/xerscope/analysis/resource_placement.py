"""Dates of a resource-dependent activity, placed from its driving assignments as P6 23.12 does.

The duration of such an activity comes from its resources. Each driving resource assignment
has remaining hours of work and a rate (hours per hour); its duration is work / rate, counted
on the resource's own calendar, not the activity's. The activity spans its assignments.

Example: 40 h of work at 0.5 h per hour (a half-time person) lasts 80 working hours of that
person's calendar; if the person works Monday to Thursday, the activity stretches over the
Fridays they are off.

Early dates (``place_early``), as P6 23.12 places them (corpus H8-H30):

1. the lower bound is taken on the activity's own calendar (H8-03 A1240: data date 00:00,
   activity Mon-Thu from 07:00, resource every day from 06:00: starts 07:00);
2. each driving assignment is placed from there on its resource calendar, with its lag, and
   pushed back behind a finish bound if one is later;
3. the activity starts at the earliest assignment start, on its own calendar, and each
   assignment then runs forward from that start: a finish bound is met, not tight (H10-02
   A1360: an FF bound at Fri 18:00 on a Mon-Sat 08-16 resource, placed Fri 08:00-16:00).

Late dates (``place_late``): the mirror, from the upper bounds.

Nothing here reads or writes the state of a recalculation: ``cpm.py`` gives the bounds, the
remaining minutes of each assignment and the expected finish, and records the dates it gets.
Task-dependent work, whose duration is counted on the activity calendar alone, is placed by
``_early`` and ``_late`` of ``cpm.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from ..xer.calendar import TimeAxis


@dataclass
class Assignment:
    """One open assignment as the CPM schedules it."""

    taskrsrc_id: str
    rsrc: str
    axis: TimeAxis
    lag_minutes: float  # remaining assignment lag, minutes
    duration_minutes: float  # remaining duration, minutes (None = the activity's)
    driving: bool


@dataclass
class EarlyPlacement:
    """Early dates of a resource-dependent activity and of its driving assignments."""

    start: pd.Timestamp
    finish: pd.Timestamp
    assignment_dates: dict[str, tuple[pd.Timestamp, pd.Timestamp]]  # taskrsrc_id -> start, finish
    assignment_minutes: dict[str, float]  # taskrsrc_id -> remaining minutes as placed (expected finish)
    is_sized_by_expected_finish: bool  # the expected finish set the remaining work of an assignment


@dataclass
class LatePlacement:
    """Late dates of a resource-dependent activity and of its driving assignments."""

    start: pd.Timestamp
    finish: pd.Timestamp
    assignment_dates: dict[str, tuple[pd.Timestamp | None, pd.Timestamp | None]]  # taskrsrc_id -> start, finish


def place_early(
    driving: Sequence[Assignment],
    activity_axis: TimeAxis,
    remaining_minutes: Sequence[float],
    lower_start: pd.Timestamp,
    finish_bound: pd.Timestamp | None,
    expected_date: pd.Timestamp | None,
) -> EarlyPlacement:
    """Place a resource-dependent activity and its driving assignments at their early dates.

    The start comes out on the activity calendar; the dates of each assignment, and the finish,
    the latest of theirs, on the resource calendars (steps 2 and 3 of the module docstring).
    ``lower_start`` is the earliest start, taken on the activity calendar; ``finish_bound`` the
    latest of the dates the finish may not come before, if any. ``remaining_minutes`` holds the
    work left of each assignment of ``driving``, in the same order, in minutes of its calendar.

    ``expected_date``: the expected finish when the option applies. It sets the remaining work
    of the assignments it applies to (``is_expected_finish_applied``).
    """
    starts: list[pd.Timestamp] = []
    assignment_minutes: dict[str, float] = {}
    is_sized_by_expected_finish = False
    for assignment, given_minutes in zip(driving, remaining_minutes, strict=True):
        duration_minutes = given_minutes
        assignment_start = lagged_start(assignment, lower_start)
        if is_expected_finish_applied(expected_date, assignment_start, finish_bound):
            # the expected finish sets the remaining work, measured on the resource
            # calendar from this placement (H26-11 A1090: 35.5 h from Tue 06:00, then
            # run from the activity's Tue 07:00 to Fri 06:30); an expected finish before
            # the placement keeps the file's remaining duration (H14-05 A1040), and an
            # FF / SF bound later than it wins, as for task-dependent work
            duration_minutes = float(assignment.axis.between(assignment_start, expected_date))
            is_sized_by_expected_finish = True
        assignment_minutes[assignment.taskrsrc_id] = duration_minutes
        starts.append(activity_start_given_by(assignment, assignment_start, duration_minutes, finish_bound))
    start = activity_axis.snap_start(min(starts))
    finishes: list[pd.Timestamp] = []
    assignment_dates: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for assignment in driving:
        assignment_start = lagged_start(assignment, start)
        assignment_finish = finish_run_from(assignment, assignment_start, assignment_minutes[assignment.taskrsrc_id])
        assignment_dates[assignment.taskrsrc_id] = (assignment_start, assignment_finish)
        finishes.append(assignment_finish)
    return EarlyPlacement(start, max(finishes), assignment_dates, assignment_minutes, is_sized_by_expected_finish)


def lagged_start(assignment: Assignment, measured_from: pd.Timestamp) -> pd.Timestamp:
    """Return the start of an assignment placed from an instant: shifted by its lag, on its calendar."""
    return assignment.axis.snap_start(assignment.axis.shift(measured_from, assignment.lag_minutes))


def finish_run_from(assignment: Assignment, assignment_start: pd.Timestamp, duration_minutes: float) -> pd.Timestamp:
    """Return the finish of an assignment that works its duration from a start, on its calendar.

    The start itself when no work is left.
    """
    if not duration_minutes:
        return assignment_start
    return assignment.axis.add(assignment_start, duration_minutes, finish=True)


def is_expected_finish_applied(
    expected_date: pd.Timestamp | None, assignment_start: pd.Timestamp, finish_bound: pd.Timestamp | None
) -> bool:
    """Tell whether the expected finish sets the remaining work of an assignment.

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
    """Return the start one driving assignment gives the activity: the assignment's start less its lag.

    An assignment that would finish before the finish bound is first moved to finish at the
    bound, or at the next working time of its calendar, and starts its duration before; with no
    work left, it starts at that finish.
    """
    assignment_finish = finish_run_from(assignment, assignment_start, duration_minutes)
    if finish_bound is not None and assignment_finish < finish_bound:
        assignment_finish = assignment.axis.keep_or_next(finish_bound)
        assignment_start = assignment_finish
        if duration_minutes:
            assignment_start = assignment.axis.add(assignment_finish, -duration_minutes, finish=False)
    return assignment.axis.shift(assignment_start, -assignment.lag_minutes)


def place_late(
    driving: Sequence[Assignment],
    activity_axis: TimeAxis,
    remaining_minutes: Sequence[float],
    late_start_bounds: list,
    late_finish_bounds: list,
    is_slide: bool,
) -> LatePlacement:
    """Place a resource-dependent activity and its driving assignments at the latest dates within the bounds.

    The mirror of ``place_early``: the bounds are taken on the activity calendar, each
    assignment then runs back on its resource calendar. ``remaining_minutes`` holds the work
    left of each assignment of ``driving``, in the same order, in minutes of its calendar, as
    the early placement left it. ``is_slide``: the dates placed are the early dates of an
    as-late-as-possible activity, moved to the latest its successors allow, not late dates.
    """
    # Mirror of place_early: the bounds are taken on the activity calendar first (H10-04
    # A1220: a successor's late start Tue 08:00 is Mon 16:00 on a Mon-Sat 08-16 activity,
    # the 24 h resource then runs back from there), then each driving assignment is
    # placed on its resource calendar (H9-08 A1230: the resource's holiday moves it)
    upper_finish = activity_axis.snap_finish(min(late_finish_bounds)) if late_finish_bounds else None
    upper_start = activity_axis.snap_start(min(late_start_bounds)) if late_start_bounds else None
    starts, finishes, driven = [], [], False
    assignment_dates: dict[str, tuple[pd.Timestamp | None, pd.Timestamp | None]] = {}
    for assignment, duration_minutes in zip(driving, remaining_minutes, strict=True):
        assignment_start, assignment_finish, is_driven = assignment_late_dates(
            assignment, duration_minutes, upper_start, upper_finish
        )
        driven = driven or is_driven
        assignment_dates[assignment.taskrsrc_id] = (assignment_start, assignment_finish)
        starts.append(assignment.axis.shift(assignment_start, -assignment.lag_minutes))
        finishes.append(assignment_finish)
    start = min(starts)
    if driven and start == upper_start and not is_slide:
        # written at the bound's instant, as a late date from an SS bound is on
        # task-dependent work (H26-04 A1440: late start Wed 16:00, not Thu 08:00)
        start = activity_axis.keep_or_previous(min(late_start_bounds))
    return LatePlacement(start, max(finishes), assignment_dates)


def assignment_late_dates(
    assignment: Assignment,
    duration_minutes: float,
    upper_start: pd.Timestamp | None,
    upper_finish: pd.Timestamp | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None, bool]:
    """Return the latest start and finish of one driving assignment on its resource calendar.

    The third value tells whether the start bound placed it with no assignment lag: the
    activity's late start is then that bound.

    The assignment runs back from the finish bound; the start bound, moved by the assignment
    lag, takes over when it is earlier or when there is no finish bound.
    """
    start = finish = None
    if upper_finish is not None:
        finish = assignment.axis.snap_finish(upper_finish)
        start = assignment.axis.add(finish, -duration_minutes, finish=False) if duration_minutes else finish
    if upper_start is None:
        return start, finish, False
    candidate = assignment.axis.snap_start(assignment.axis.shift(upper_start, assignment.lag_minutes))
    if start is None or candidate <= start:
        finish = assignment.axis.add(candidate, duration_minutes, finish=True) if duration_minutes else candidate
        return candidate, finish, assignment.lag_minutes == 0
    return start, finish, False
