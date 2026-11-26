"""One activity and the activities around it, as the Gantt's task panel shows them.

- ``linked_chain``: the activities reached from one activity through its relationships, upstream,
  downstream or both, a number of links deep; through every relationship or the driving ones only
  (``analysis.cpm.Schedule.links``: P6's Driving column, recalculated because the XER does not
  export it).
- ``trail_by_update``: total float, free float and constraints of a list of activities in each
  update, as P6 stored them.
- ``constraint_history``: every change of an activity's constraints from one update to the next,
  the rows of the changelog (``analysis.changelog.constraint_changes``).
- ``logic_by_update``: in each update, the activity and its direct predecessors and successors as
  that update links them, with floats, constraints and whether each link drives.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import pandas as pd

from ..store import SnapshotStore
from ..xer.model import CONSTRAINT
from .changelog import constraint_changes
from .cpm import ScheduleError, schedule

UPSTREAM = "upstream"
DOWNSTREAM = "downstream"
BOTH = "both"
TRAIL_COLS = ["task_code", "data_date", "update", "total_float_d", "free_float_d", "primary", "secondary"]
TASK = "task"
PREDECESSOR = "predecessor"
SUCCESSOR = "successor"
LOGIC_COLS = [
    "data_date",
    "update",
    "role",
    "level",
    "task_code",
    "task_name",
    "link_type",
    "driving_link",
    "total_float_d",
    "free_float_d",
    "primary",
    "secondary",
]


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


def logic_by_update(store: SnapshotStore, task_code: str, depth: int = 1, driving_only: bool = False) -> pd.DataFrame:
    """Return, for each update holding ``task_code``, the activity and the activities linked to it (LOGIC_COLS).

    ``role`` is TASK, PREDECESSOR (upstream) or SUCCESSOR (downstream), read from that update's
    relationships, so a link added or deleted shows as a neighbour present in some updates only.
    ``level`` is the number of links between the activity and the task (0 for the task, 1 for a direct
    neighbour), ``depth`` links at most, each activity at the level it is first reached; with
    ``driving_only`` only driving links are followed. ``link_type`` and ``driving_link`` are those of the
    link it is reached by, toward the task. Floats and constraints are P6's; ``driving_link`` is the
    recalculated flag (P6 does not export it), None when the update cannot be scheduled and on the
    task's own row.
    """
    rows = []
    for snapshot in store:
        if task_code not in snapshot.by_code.index:
            continue
        driving = driving_flags(snapshot)
        followed = _followed_links(snapshot.relationships, driving, driving_only)
        rows.append(_logic_row(snapshot, task_code, TASK, 0, None, None))
        for role, toward, away in ((PREDECESSOR, "succ_code", "pred_code"), (SUCCESSOR, "pred_code", "succ_code")):
            for level, link in _reached_links(followed, task_code, toward, away, depth):
                flag = driving.get((link.pred_code, link.succ_code, link.type))
                rows.append(_logic_row(snapshot, getattr(link, away), role, level, link.type, flag))
    return pd.DataFrame(rows, columns=LOGIC_COLS)


def _followed_links(links: pd.DataFrame, driving: dict, driving_only: bool) -> list[Any]:
    """Return the relationships a walk may take: all of them, or the driving ones only."""
    if not driving_only:
        return list(links.itertuples())
    return [link for link in links.itertuples() if driving.get((link.pred_code, link.succ_code, link.type))]


def _reached_links(links: list[Any], task_code: str, toward: str, away: str, depth: int) -> list[tuple[int, Any]]:
    """Return (level, link) for each activity reached from ``task_code`` within ``depth`` links.

    Breadth first: the link by which it is first reached, whose ``toward`` end is nearer the task and
    whose ``away`` end is the activity.
    """
    by_near_end: dict[str, list] = {}
    for link in links:
        by_near_end.setdefault(getattr(link, toward), []).append(link)
    seen, frontier = {task_code}, [task_code]
    reached: list[tuple[int, Any]] = []
    for level in range(1, depth + 1):
        frontier = _next_frontier(by_near_end, frontier, away, seen, reached, level)
    return reached


def _next_frontier(by_near_end: dict, frontier: list, away: str, seen: set, reached: list, level: int) -> list:
    """Return the activities one link further than ``frontier``, not seen before; each is added to ``reached``."""
    found = []
    for code in frontier:
        for link in by_near_end.get(code, []):
            other = getattr(link, away)
            if other in seen:
                continue
            seen.add(other)
            reached.append((level, link))
            found.append(other)
    return found


def driving_flags(snapshot) -> dict[tuple[str, str, str], bool]:
    """Return the recalculated driving flag of each relationship (predecessor, successor, type).

    Empty when the update cannot be scheduled. P6 does not export its own (TASKPRED has no such field).
    """
    try:
        links = schedule(snapshot).links
    except ScheduleError:
        return {}
    keys = zip(links["pred_code"], links["succ_code"], links["type"], strict=True)
    return dict(zip(keys, links["driving"], strict=True))


def _logic_row(snapshot, code: str, role: str, level: int, link_type: str | None, driving: bool | None) -> dict:
    """One activity of one update; an activity of another project (``[ext]``) has no values."""
    tasks = snapshot.by_code
    known = code in tasks.index
    task = tasks.loc[code] if known else pd.Series(dtype=object)
    return {
        "data_date": snapshot.data_date,
        "update": snapshot.label,
        "role": role,
        "level": level,
        "task_code": code,
        "task_name": task.get("task_name"),
        "link_type": link_type,
        "driving_link": driving,
        "total_float_d": task.get("total_float_d"),
        "free_float_d": task.get("free_float_d"),
        "primary": _constraint_text(task.get("cstr_type"), task.get("cstr_date")),
        "secondary": _constraint_text(task.get("cstr_type2"), task.get("cstr_date2")),
    }
