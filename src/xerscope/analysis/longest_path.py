"""Longest path of each update and what entered or left it since the update before.

AACE RP 29R-03 (rev. April 25, 2011), MIP 3.3 and 3.4, minimum implementation protocols: "Use
both the longest path and the least float criteria to identify the controlling chain of
activities" (3.4.E.9) and "for each update, identify all changes made that extend, reduce, or
change the longest path" (SVP 2.3.B.6). The SCL Delay and Disruption Protocol, 2nd edition
(February 2017), 11.6(c), reads the same thing as the contemporaneous critical path of each time
slice.

The longest path of an update is the one P6 stored in the file (``TASK.driving_path_flag``, the
Longest Path column of P6), open work only: finished work is no longer driving anything. A file
without one flagged activity (never scheduled, or exported without the field) takes the
recalculated longest path (``analysis.cpm.schedule``), and ``source`` says which was read.

Between two updates an activity of the earlier path either stays, is finished (it left because it
was done), or is still open and no longer on the path: the path switched away from it, which is
what a reader of a delay looks for. An activity deleted since is counted apart.
"""

from __future__ import annotations

import pandas as pd

from ..store import SnapshotStore
from ..xer import Snapshot
from .cpm import ScheduleError, schedule
from .populations import Funnel, activity_funnel, flagged_activities

P6_FLAG = "P6 longest path"
RECALCULATED = "recalculated"
UNKNOWN = "none"

STAYED = "stayed"
ENTERED = "entered"
FINISHED = "left: finished"
SWITCHED = "left: still open"
DELETED = "left: deleted"
# the order a reader wants: what the path switched away from and what it picked up come first
CHANGES = [SWITCHED, ENTERED, FINISHED, DELETED, STAYED]
CHURN_COLUMNS = [
    "data_date",
    "path_source",
    "on_path",
    "stayed",
    "entered",
    "left_finished",
    "left_open",
    "left_deleted",
    "stability",
]


def _path_flags(snapshot: Snapshot) -> tuple[pd.Series, str]:
    """Activity ID -> on the longest path, and where it was read (see the module docstring)."""
    stored = snapshot.by_code["on_longest_path"].astype(bool)
    if stored.any():
        return stored, P6_FLAG
    try:
        frame = schedule(snapshot).frame
    except ScheduleError:
        return stored, UNKNOWN
    return frame["longest_path"].astype(bool).reindex(stored.index, fill_value=False), RECALCULATED


def longest_path_funnel(snapshot: Snapshot) -> tuple[Funnel, str]:
    """Funnel of the longest path of ``snapshot``, step by step, and where the path was read.

    Every activity, less the completed ones, then those on the path: the steps and what each
    removed are the funnel's, as for the checks (``analysis.populations``).
    """
    flags, source = _path_flags(snapshot)
    funnel = activity_funnel(snapshot).exclude("complete", "AACE 29R-03")
    funnel.keep(f"on the longest path ({source})", "AACE 29R-03", lambda rows: rows["task_code"].map(flags))
    return funnel, source


def longest_path(snapshot: Snapshot) -> tuple[list[str], str]:
    """Open activities on the longest path of ``snapshot``, by Activity ID, and where they were read.

    ``P6_FLAG`` when the file flags at least one activity, else ``RECALCULATED``; ``UNKNOWN`` with
    no code when the file flags none and cannot be scheduled.
    """
    funnel, source = longest_path_funnel(snapshot)
    return sorted(set(funnel.rows["task_code"])), source


def _change_of(code: str, before: set[str], after: set[str], new: Snapshot) -> str:
    """Change of ``code``, on the path of one update at least, between the two updates."""
    if code in after:
        return STAYED if code in before else ENTERED
    if code not in new.by_code.index:
        return DELETED
    return FINISHED if bool(new.by_code.loc[code, "is_complete"]) else SWITCHED


def path_changes(old: Snapshot, new: Snapshot) -> pd.DataFrame:
    """One row per activity on the longest path of ``old`` or of ``new``: what happened to it.

    ``change`` (one of ``CHANGES``, the rows in that order), ``float_before_d`` (P6's total float in
    the earlier update), then the standard activity columns (``populations.ACTIVITY_COLS``) as the
    later update has them; a deleted activity shows the earlier update's, without a float after.
    """
    before, after = set(longest_path(old)[0]), set(longest_path(new)[0])
    on_either = before | after
    in_new = new.activities[new.activities["task_code"].isin(on_either)]
    deleted = old.activities[old.activities["task_code"].isin(on_either - set(in_new["task_code"]))]
    rows = pd.concat([in_new, deleted.assign(total_float_d=float("nan"))]).drop_duplicates("task_code")
    change = rows["task_code"].map(lambda code: _change_of(code, before, after, new))
    float_before_d = rows["task_code"].map(old.by_code["total_float_d"])
    changes = flagged_activities(rows, change=change, float_before_d=float_before_d)
    changes["change"] = pd.Categorical(changes["change"], CHANGES, ordered=True)
    leading = ["change", "task_code", "task_name", "wbs_code", "float_before_d", "total_float_d"]
    others = [column for column in changes.columns if column not in leading]
    return changes[leading + others].sort_values(["change", "task_code"], kind="stable").reset_index(drop=True)


def change_counts(changes: pd.DataFrame) -> dict[str, int]:
    """Rows of ``path_changes`` counted per kind of change, every kind present (0 when none)."""
    counted = changes["change"].value_counts()
    return {change: int(counted.get(change, 0)) for change in CHANGES}


def _stability(counts: dict[str, int]) -> float | None:
    """Share of the earlier path's still-open activities that stayed on the path.

    ``stayed / (stayed + switched)``: finished and deleted work is left out, it could not stay.
    None when the earlier path had no activity still open.
    """
    could_stay = counts[STAYED] + counts[SWITCHED]
    return counts[STAYED] / could_stay if could_stay else None


def path_churn(store: SnapshotStore) -> pd.DataFrame:
    """One row per update after the first: its longest path against the one before.

    ``on_path`` the open activities on the path, then how many stayed, entered, were finished,
    are still open but left the path (``left_open``) or were deleted, and ``stability``.
    ``path_source`` is where the later update's path was read; a week between a P6 path and a recalculated one
    compares two definitions and says so (``P6 longest path / recalculated``).
    """
    rows = []
    for index in range(1, len(store)):
        old, new = store[index - 1], store[index]
        counts = change_counts(path_changes(old, new))
        old_source, new_source = longest_path(old)[1], longest_path(new)[1]
        rows.append(
            {
                "data_date": new.data_date,
                "path_source": new_source if old_source == new_source else f"{old_source} / {new_source}",
                "on_path": counts[STAYED] + counts[ENTERED],
                "stayed": counts[STAYED],
                "entered": counts[ENTERED],
                "left_finished": counts[FINISHED],
                "left_open": counts[SWITCHED],
                "left_deleted": counts[DELETED],
                "stability": _stability(counts),
            }
        )
    return pd.DataFrame(rows, columns=CHURN_COLUMNS)
