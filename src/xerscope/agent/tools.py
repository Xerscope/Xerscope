"""The commands the local model may choose, each computed by xerscope's own engines.

A command reads the update the page shows (``snapshot``) and, for a move, the update before it in the
series; it returns a few named values (``FIELDS``), never the schedule itself. The model picks one
command and one of its fields; it computes nothing and never reads the activities.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..analysis import query
from ..analysis.activity_forensics import activity_half_step
from ..analysis.forensics import half_step
from ..analysis.longest_path import path_churn
from ..store import SnapshotStore
from ..xer import Snapshot

FIRST = 10  # Activity IDs a list holds at most

# command -> the values it returns, the first one the default
FIELDS: dict[str, tuple[str, ...]] = {
    "find_activity": ("task_code", "count", "task_codes"),
    "filter": ("count", "task_codes"),
    "activity_slip": ("total_shift_wd", "finish_after", "driving_predecessors"),
    "activity_history": ("finish", "first_finish", "updates"),
    "project_slip": ("finish", "slip_wd", "replanning_wd"),
    "path_changes": ("on_path", "entered", "left_open"),
    "none": ("none",),
}
# what the model reads of each command, and the argument it takes ("" when none)
COMMANDS: dict[str, tuple[str, str]] = {
    "find_activity": ("the Activity IDs whose name holds some words", "the words of the name"),
    "filter": ("how many activities, and which, match a filter of the page (status, float, WBS, resource...)", ""),
    "activity_slip": (
        "how far an activity's finish moved since the update before, and what drives it",
        "an Activity ID",
    ),
    "activity_history": ("an activity's finish in every update of the series", "an Activity ID"),
    "project_slip": ("the project finish, and how far progress and replanning moved it since the update before", ""),
    "path_changes": ("the open activities on the longest path, those that entered it, those that left it", ""),
    "none": ("the question cannot be answered by these commands (a what-if, a fact not in the schedule)", ""),
}
ACTIVITY_COMMANDS = ("activity_slip", "activity_history")


def day(value) -> str | None:
    """Write a date as YYYY-MM-DD (ISO 8601), None for none."""
    return pd.Timestamp(value).date().isoformat() if pd.notna(value) else None


@dataclass(frozen=True)
class Context:
    """What the page holds.

    The series, the update shown, its activities as the Gantt filters them (with their ``category``
    column), the WBS tree and the Ask lexicon.
    """

    store: SnapshotStore
    snapshot: Snapshot
    tasks: pd.DataFrame
    nodes: pd.DataFrame
    vocab: query.Vocabulary

    @property
    def previous(self) -> Snapshot | None:
        """The update before the one shown, None for the first."""
        return self.store.previous(self.snapshot)

    def has_activity(self, task_code: str) -> bool:
        """Tell whether the update shown holds that Activity ID."""
        return task_code in set(self.snapshot.activities["task_code"].astype(str))


def find_activity(context: Context, text: str) -> dict:
    """Find the activities whose name holds every word of ``text`` (3 letters or more, accents folded)."""
    words = [word for word in query.fold(text).split() if len(word) > 2]
    names = context.snapshot.activities["task_name"].astype(str).map(query.fold)
    hits = context.snapshot.activities[names.map(lambda name: bool(words) and all(w in name for w in words))]
    codes = hits["task_code"].astype(str).tolist()
    return {"count": len(codes), "task_code": codes[0] if len(codes) == 1 else None, "task_codes": codes[:FIRST]}


def filter_tasks(context: Context, sentence: str) -> dict:
    """Count and list the page's activities that the Ask grammar's reading of ``sentence`` keeps."""
    ask = query.parse_keywords(sentence, context.vocab)
    funnel = query.apply(ask, context.tasks, context.snapshot, context.nodes, None)
    codes = funnel.rows["task_code"].astype(str).tolist()
    return {
        "count": len(codes),
        "task_codes": codes[:FIRST],
        "understood": query.funnel_line(funnel) if funnel.steps else "",
        "left_out": list(ask.ignored),
    }


def activity_slip(context: Context, task_code: str) -> dict:
    """Read how far ``task_code``'s finish moved since the update before, and its driving predecessors."""
    previous = context.previous
    if previous is None:
        return {"error": "no earlier update in the series"}
    read = activity_half_step(previous, context.snapshot, task_code)
    if read.missing_from:
        return {"error": f"{task_code} is missing from {read.missing_from}"}
    return {
        "total_shift_wd": round(read.total_shift_wd, 2),
        "finish_after": day(read.new_finish),
        "driving_predecessors": ", ".join(read.driving_after) or "none",
        "since": day(previous.data_date),
    }


def activity_history(context: Context, task_code: str) -> dict:
    """Read ``task_code``'s finish in the update shown and in the first update that holds it."""
    history = context.store.history
    rows = history.loc[
        (history["task_code"] == task_code) & (history["data_date"] <= context.snapshot.data_date), "finish"
    ]
    if rows.empty:
        return {"error": f"{task_code} is in no update up to this one"}
    return {"finish": day(rows.iloc[-1]), "first_finish": day(rows.iloc[0]), "updates": len(rows)}


def project_slip(context: Context) -> dict:
    """Read the project finish and its move by progress and by replanning since the update before."""
    previous = context.previous
    if previous is None:
        return {"error": "no earlier update in the series"}
    read = half_step(previous, context.snapshot)
    return {
        "finish": day(read.new_finish),
        "slip_wd": round(read.slip_wd, 2),
        "replanning_wd": round(read.replanning_wd, 2),
        "since": day(previous.data_date),
    }


def path_changes(context: Context) -> dict:
    """Count the open activities on the longest path, and those that entered or left it."""
    churn = path_churn(context.store)
    rows = churn[churn["data_date"] == context.snapshot.data_date]
    if rows.empty:
        return {"error": "no earlier update in the series"}
    row = rows.iloc[0]
    return {"on_path": int(row["on_path"]), "entered": int(row["entered"]), "left_open": int(row["left_open"])}


def run(context: Context, command: str, argument: str) -> dict:
    """Run ``command`` on the page's context, ``argument`` read as that command takes it."""
    if command == "find_activity":
        return find_activity(context, argument)
    if command == "filter":
        return filter_tasks(context, argument)
    if command == "activity_slip":
        return activity_slip(context, argument)
    if command == "activity_history":
        return activity_history(context, argument)
    if command == "project_slip":
        return project_slip(context)
    if command == "path_changes":
        return path_changes(context)
    return {}
