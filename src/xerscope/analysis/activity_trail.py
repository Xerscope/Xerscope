"""One activity and the activities around it, as the Gantt's task panel shows them.

- ``linked_chain``: the activities reached from one activity through its relationships, upstream,
  downstream or both, a number of links deep; through every relationship or the driving ones only
  (``analysis.cpm.Schedule.links``: P6's Driving column, recalculated because the XER does not
  export it).
- ``trail_by_update``: total float, free float and constraints of a list of activities in each
  update, as P6 stored them.
- ``constraint_history``: every change of an activity's constraints from one update to the next,
  the rows of the changelog (``analysis.changelog.constraint_changes``).
"""

from __future__ import annotations

from collections import deque

import pandas as pd

from ..store import SnapshotStore
from ..xer.model import CONSTRAINT
from .changelog import constraint_changes

UPSTREAM = "upstream"
DOWNSTREAM = "downstream"
BOTH = "both"
TRAIL_COLS = ["task_code", "data_date", "update", "total_float_d", "free_float_d", "primary", "secondary"]


def linked_chain(links: pd.DataFrame, task_code: str, direction: str, depth: int, driving_only: bool) -> list[str]:
    """Activity IDs reached from ``task_code`` (first) within ``depth`` links, nearest first.

    ``links``: one row per relationship, ``pred_code``, ``succ_code`` and, with ``driving_only``,
    ``driving``. ``direction``: UPSTREAM follows predecessors, DOWNSTREAM successors, BOTH each
    side on its own (a predecessor's other successors are not reached).
    """
    if driving_only:
        links = links[links["driving"].astype(bool)]
    reached = [task_code]
    if direction in (UPSTREAM, BOTH):
        reached += _walk(_neighbours(links, "succ_code", "pred_code"), task_code, depth, set(reached))
    if direction in (DOWNSTREAM, BOTH):
        reached += _walk(_neighbours(links, "pred_code", "succ_code"), task_code, depth, set(reached))
    return reached


def _neighbours(links: pd.DataFrame, from_column: str, to_column: str) -> dict[str, list[str]]:
    neighbours: dict[str, list[str]] = {}
    for start, end in zip(links[from_column], links[to_column], strict=True):
        neighbours.setdefault(start, []).append(end)
    return neighbours


def _walk(neighbours: dict[str, list[str]], task_code: str, depth: int, seen: set[str]) -> list[str]:
    """Breadth first from ``task_code``, ``depth`` steps at most, skipping ``seen`` (updated)."""
    found = []
    pending = deque([(task_code, 0)])
    while pending:
        code, distance = pending.popleft()
        if distance == depth:
            continue
        for neighbour in neighbours.get(code, []):
            if neighbour in seen:
                continue
            seen.add(neighbour)
            found.append(neighbour)
            pending.append((neighbour, distance + 1))
    return found


def _constraint_text(kind, date) -> str | None:
    """P6's name of a constraint and its date, None without one."""
    if pd.isna(kind) or kind == "":
        return None
    label = CONSTRAINT.get(kind, kind)
    return label if pd.isna(date) else f"{label} {pd.Timestamp(date):%Y-%m-%d %H:%M}"


def trail_by_update(store: SnapshotStore, task_codes: list[str]) -> pd.DataFrame:
    """Return one row per activity of ``task_codes`` and update holding it (TRAIL_COLS).

    P6's total and free float in working days, its primary and secondary constraint with their dates.
    """
    rows = []
    for snapshot in store:
        tasks = snapshot.by_code
        for code in task_codes:
            if code not in tasks.index:
                continue
            task = tasks.loc[code]
            rows.append(
                {
                    "task_code": code,
                    "data_date": snapshot.data_date,
                    "update": snapshot.label,
                    "total_float_d": task["total_float_d"],
                    "free_float_d": task["free_float_d"],
                    "primary": _constraint_text(task["cstr_type"], task["cstr_date"]),
                    "secondary": _constraint_text(task["cstr_type2"], task["cstr_date2"]),
                }
            )
    return pd.DataFrame(rows, columns=TRAIL_COLS)


def constraint_history(store: SnapshotStore, task_code: str) -> pd.DataFrame:
    """Return each change of the activity's constraints between two consecutive updates.

    The changelog's rows (``field``, ``change``, ``before``, ``after``) with the ``data_date`` of
    the later update.
    """
    frames = []
    for previous, current in zip(list(store)[:-1], list(store)[1:], strict=True):
        changes = constraint_changes(previous, current, [task_code])
        frames.append(changes.assign(data_date=current.data_date)[["data_date", "field", "change", "before", "after"]])
    columns = ["data_date", "field", "change", "before", "after"]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
