"""Half-step reading of one activity: why it moved between two updates, and across the series.

The reading of ``analysis.forensics`` (AACE RP 29R-03 MIP 3.4, half-stepped update analysis),
taken on one activity's early finish instead of the project's: the earlier update as scheduled,
then after each of ``forensics.STEPS`` (same order, same derivation, the same recalculated
snapshots), then the later update. The shifts are working days of the activity's calendar in the
later update, days lost negative, the convention of ``progress.activity_finish_shift``.

``residual_wd`` is the move the steps do not account for. The engine gaps compare the recalculated
early finish of the activity in each update with the finish P6 stored for it: with a gap the shifts
may be the engine's and not the schedule's (``is_finish_reproduced``).

A driving predecessor is one whose link leaves no slack: the working time on the lag calendar between
the date the link reads on the predecessor and the date it bounds on the activity equals the lag
(Oracle P6 help, Relationship lag, Driving relationships). Links to other projects are not read.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..store import SnapshotStore
from ..xer import Snapshot
from .changelog import changelog
from .cpm import H24, Schedule, ScheduleError, schedule
from .forensics import AS_SCHEDULED, STEP_COLUMNS, STEPS, progress_shift_wd, replanning_shift_wd, step_schedules

# the date a link reads on the predecessor and the date it bounds on the successor, by link type
LINK_DATES = {"FS": ("ef", "es"), "SS": ("es", "es"), "FF": ("ef", "ef"), "SF": ("es", "ef")}
SLACK_TOLERANCE_HR = 0.01

EARLIER_UPDATE = "the earlier update"
LATER_UPDATE = "the later update"

SERIES_COLUMNS = [
    "data_date",
    "finish",
    "total_shift_wd",
    "slip_wd",
    "replanning_wd",
    "residual_wd",
    "engine_gap_wd",
    "driving_predecessors",
    "note",
]


@dataclass(frozen=True)
class ActivityHalfStep:
    """One activity's week read step by step.

    ``steps``: as ``HalfStep.steps`` (``AS_SCHEDULED`` row, then one per step: ``finish`` the
    recalculated early finish of the activity, ``shift_wd`` its move from the row before,
    ``changes`` the changelog rows of the activity in the step's categories). ``missing_from``
    names the update that lacks the activity, empty when both hold it: the figures are then absent.
    ``driving_before`` / ``driving_after``: driving predecessors in each update. ``changes``: the
    changelog rows of the activity and of those predecessors, ``task_code`` telling which.
    """

    task_code: str
    missing_from: str
    steps: pd.DataFrame
    old_finish: pd.Timestamp | None
    new_finish: pd.Timestamp | None
    residual_wd: float
    old_engine_gap_wd: float
    new_engine_gap_wd: float
    driving_before: list[str]
    driving_after: list[str]
    changes: pd.DataFrame

    @property
    def total_shift_wd(self) -> float:
        """Move of the early finish between the two updates: the steps and the residual add up to it."""
        return float(self.steps["shift_wd"].sum() + self.residual_wd)

    @property
    def slip_wd(self) -> float:
        """What the week's progress did to the activity: the shift of the progress step."""
        return progress_shift_wd(self.steps)

    @property
    def replanning_wd(self) -> float:
        """What the replanning did: the shifts of every step after progress, summed."""
        return replanning_shift_wd(self.steps)

    @property
    def is_finish_reproduced(self) -> bool:
        """Both updates recalculate to the finish P6 stored for the activity: the shifts are the schedule's."""
        return self.old_engine_gap_wd == 0.0 and self.new_engine_gap_wd == 0.0


def driving_predecessors(snapshot: Snapshot, recomputed: Schedule, task_code: str) -> list[str]:
    """Activity IDs whose link into ``task_code`` leaves no slack in the recalculated dates, sorted."""
    links = snapshot.relationships
    into_activity = links[(links["succ_code"] == task_code) & ~links["is_external"].astype(bool)]
    return sorted({link.pred_code for link in into_activity.itertuples() if _is_driving(snapshot, recomputed, link)})


def _is_driving(snapshot: Snapshot, recomputed: Schedule, link) -> bool:
    frame = recomputed.frame
    if link.pred_code not in frame.index or link.type not in LINK_DATES:
        return False
    predecessor_date, successor_date = LINK_DATES[link.type]
    calendar = _lag_calendar(snapshot, recomputed, link.pred_code, link.succ_code)
    gap_hr = calendar.work_hours(frame.loc[link.pred_code, predecessor_date], frame.loc[link.succ_code, successor_date])
    lag_hr = 0.0 if pd.isna(link.lag_hr) else float(link.lag_hr)
    return abs(gap_hr - lag_hr) <= SLACK_TOLERANCE_HR


def _lag_calendar(snapshot: Snapshot, recomputed: Schedule, predecessor: str, successor: str):
    """Return the calendar the lag of a link is counted on, per the scheduling option."""
    option = recomputed.options.lag_calendar
    if option == "rcal_24Hour":
        return H24
    if option == "rcal_ProjDefault":
        return snapshot.calendar()
    owner = predecessor if option == "rcal_Predecessor" else successor
    return snapshot.calendar(_calendar_id(snapshot, owner))


def _calendar_id(snapshot: Snapshot, task_code: str) -> str | None:
    clndr_id = snapshot.by_code.loc[task_code, "clndr_id"]
    return clndr_id if isinstance(clndr_id, str) else None


def _activity_shift_wd(new: Snapshot, task_code: str, before, after) -> float:
    """Working days from ``before`` to ``after`` on the activity's calendar in ``new``, days lost negative."""
    if pd.isna(before) or pd.isna(after):
        return float("nan")
    return 0.0 - round(new.activity_working_days(_calendar_id(new, task_code), before, after), 2)


def _engine_gap_wd(snapshot: Snapshot, recomputed: Schedule, task_code: str) -> float:
    """Recalculated early finish of the activity against the finish P6 stored for it, as the shifts read it."""
    stored = snapshot.by_code.loc[task_code, "finish"]
    return _activity_shift_wd(snapshot, task_code, stored, recomputed.frame.loc[task_code, "ef"])


def _missing_from(old: Snapshot, new: Snapshot, task_code: str) -> str:
    absent = [
        name
        for name, snapshot in ((EARLIER_UPDATE, old), (LATER_UPDATE, new))
        if task_code not in snapshot.by_code.index
    ]
    return " and ".join(absent)


def activity_half_step(old: Snapshot, new: Snapshot, task_code: str) -> ActivityHalfStep:
    """Early finish of ``task_code`` in ``old`` rescheduled with ``new``'s changes applied one step at a time.

    An activity missing from one update returns ``missing_from`` set and no figure.
    Raises ``ScheduleError`` when one of the snapshots, or a derived one, cannot be scheduled.
    """
    missing_from = _missing_from(old, new, task_code)
    if missing_from:
        return _absent_activity(task_code, missing_from)
    old_schedule, new_schedule = schedule(old), schedule(new)
    stepped = step_schedules(old, new)
    log = changelog(old, new)
    own_log = log[log["task_code"] == task_code]
    old_finish = old_schedule.frame.loc[task_code, "ef"]
    new_finish = new_schedule.frame.loc[task_code, "ef"]
    rows = [{"step": AS_SCHEDULED, "finish": old_finish, "shift_wd": float("nan"), "changes": 0}]
    finish = old_finish
    for step, recomputed in zip(STEPS, stepped, strict=True):
        step_finish = recomputed.frame.loc[task_code, "ef"]
        rows.append(
            {
                "step": step.name,
                "finish": step_finish,
                "shift_wd": _activity_shift_wd(new, task_code, finish, step_finish),
                "changes": int(step.is_carried(own_log).sum()),
            }
        )
        finish = step_finish
    driving_before = driving_predecessors(old, old_schedule, task_code)
    driving_after = driving_predecessors(new, new_schedule, task_code)
    concerned = {task_code, *driving_before, *driving_after}
    return ActivityHalfStep(
        task_code=task_code,
        missing_from="",
        steps=pd.DataFrame(rows, columns=STEP_COLUMNS),
        old_finish=old_finish,
        new_finish=new_finish,
        residual_wd=_activity_shift_wd(new, task_code, finish, new_finish),
        old_engine_gap_wd=_engine_gap_wd(old, old_schedule, task_code),
        new_engine_gap_wd=_engine_gap_wd(new, new_schedule, task_code),
        driving_before=driving_before,
        driving_after=driving_after,
        changes=log[log["task_code"].isin(concerned)].reset_index(drop=True),
    )


def _absent_activity(task_code: str, missing_from: str) -> ActivityHalfStep:
    nothing = float("nan")
    return ActivityHalfStep(
        task_code=task_code,
        missing_from=missing_from,
        steps=pd.DataFrame(columns=STEP_COLUMNS),
        old_finish=None,
        new_finish=None,
        residual_wd=nothing,
        old_engine_gap_wd=nothing,
        new_engine_gap_wd=nothing,
        driving_before=[],
        driving_after=[],
        changes=pd.DataFrame(),
    )


def activity_half_step_series(store: SnapshotStore, task_code: str) -> pd.DataFrame:
    """One row per update after the first: how ``task_code`` moved against the update before it.

    Its early finish, the move split into slip (progress), replanning and residual, the engine gap
    of the later update and its driving predecessors. A week the activity is missing from, or that
    cannot be scheduled, keeps its row with the reason in ``note`` and no figure.
    """
    rows = []
    for index in range(1, len(store)):
        old, new = store[index - 1], store[index]
        try:
            rows.append(_series_row(activity_half_step(old, new, task_code), new))
        except ScheduleError as error:
            rows.append({"data_date": new.data_date, "note": f"not read: {error}"})
    return pd.DataFrame(rows, columns=SERIES_COLUMNS)


def _series_row(read: ActivityHalfStep, new: Snapshot) -> dict:
    if read.missing_from:
        return {"data_date": new.data_date, "note": f"missing from {read.missing_from}"}
    return {
        "data_date": new.data_date,
        "finish": read.new_finish,
        "total_shift_wd": read.total_shift_wd,
        "slip_wd": read.slip_wd,
        "replanning_wd": read.replanning_wd,
        "residual_wd": read.residual_wd,
        "engine_gap_wd": read.new_engine_gap_wd,
        "driving_predecessors": ", ".join(read.driving_after),
        "note": "",
    }
