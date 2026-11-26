"""The commands the local model may choose, each computed by xerscope's own engines.

``query`` filters, sorts, counts and groups the activities of the update shown through
``analysis.activity_view`` (one condition per funnel step). The others read one activity or the
project between that update and the one before (``activity_forensics``, ``forensics.half_step``,
``longest_path.path_churn``, ``store.history``) or delay one activity in the engine
(``cpm.delay_impact``). A command returns a few named values (``FIELDS``); the model picks one
command and one of its values, and computes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..analysis import activity_view as views
from ..analysis.activity_forensics import activity_half_step
from ..analysis.cpm import ScheduleError, delay_impact
from ..analysis.forensics import half_step
from ..analysis.longest_path import path_churn
from ..store import SnapshotStore
from ..xer import Snapshot

FIRST = 10  # Activity IDs a list holds at most
MAX_CONDITIONS = 6
MAX_DELAY_DAYS = 500

# command -> the values it returns, the first one the default
FIELDS: dict[str, tuple[str, ...]] = {
    "query": ("count", "list", "groups"),
    "activity_slip": ("total_shift_wd", "finish_after", "driving_predecessors"),
    "activity_history": ("finish", "first_finish", "updates"),
    "project_slip": ("finish", "slip_wd", "replanning_wd"),
    "path_changes": ("on_path", "entered", "left_open"),
    "simulate_delay": ("finish_move_wd", "finish_after", "float_after_d"),
    "none": ("none",),
}
COMMANDS: dict[str, str] = {
    "query": "count, list or group the activities of this update that meet conditions on the columns",
    "activity_slip": "how far one activity's finish moved since the update before, and what drives it",
    "activity_history": "one activity's finish in the updates of the series",
    "project_slip": "the project finish, and how far progress and replanning moved it since the update before",
    "path_changes": "the open activities on the longest path, those that entered it, those that left it",
    "simulate_delay": "what a delay of some working days on one open activity would do to the project finish",
    "none": "a question these commands cannot answer (a fact the schedule does not hold, an advice)",
}
ACTIVITY_COMMANDS = ("activity_slip", "activity_history", "simulate_delay")


def day(value) -> str | None:
    """Write a date as YYYY-MM-DD (ISO 8601), None for none."""
    return pd.Timestamp(value).date().isoformat() if pd.notna(value) else None


@dataclass(frozen=True)
class Context:
    """What the page holds: the series, the update shown and its view (``activity_view``)."""

    store: SnapshotStore
    snapshot: Snapshot
    view: views.View

    @property
    def previous(self) -> Snapshot | None:
        """The update before the one shown, None for the first."""
        return self.store.previous(self.snapshot)

    def has_activity(self, task_code: str) -> bool:
        """Tell whether the update shown holds that Activity ID."""
        return task_code in self.view.frame.index


def context_for(store: SnapshotStore, snapshot: Snapshot) -> Context:
    """Build the context of ``snapshot``, its view read against the update before it."""
    return Context(store, snapshot, views.activity_view(snapshot, store.previous(snapshot)))


@dataclass(frozen=True)
class Choice:
    """The model's choice, read from its JSON object: the command, the value, and what each needs."""

    command: str
    field: str
    argument: str = ""
    days: float = 0.0
    query: views.Query = views.Query()


def run(context: Context, choice: Choice) -> dict:
    """Run the chosen command on the page's context; ``{"error": ...}`` when it cannot be read."""
    if choice.command == "query":
        return run_query(context, choice.query)
    if choice.command == "activity_slip":
        return activity_slip(context, choice.argument)
    if choice.command == "activity_history":
        return activity_history(context, choice.argument)
    if choice.command == "project_slip":
        return project_slip(context)
    if choice.command == "path_changes":
        return path_changes(context)
    if choice.command == "simulate_delay":
        return simulate_delay(context, choice.argument, choice.days)
    return {}


def run_query(context: Context, query: views.Query) -> dict:
    """Count, list and group the activities of the view that the query keeps."""
    try:
        result = views.run(context.view, query, context.snapshot.data_date)
    except views.QueryError as error:
        return {"error": str(error)}
    codes = [str(code) for code in result.funnel.rows.index]
    return {
        "start": len(context.view.frame),
        "steps": [(step.label, step.left) for step in result.funnel.steps],
        "count": result.count,
        "list": [str(code) for code in result.first.index][:FIRST],
        "groups": result.groups,
        "conditions": [views.describe(condition) for condition in query.conditions],
        "codes": codes,
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


def simulate_delay(context: Context, task_code: str, days: float) -> dict:
    """Delay ``task_code`` by ``days`` working days in the engine and read the project finish and its float."""
    if not 0 < days <= MAX_DELAY_DAYS:
        return {"error": f"a delay is a number of working days between 1 and {MAX_DELAY_DAYS}"}
    try:
        impact = delay_impact(context.snapshot, task_code, days)
    except (ValueError, ScheduleError) as error:
        return {"error": str(error)}
    return {
        "finish_move_wd": impact.finish_move_wd,
        "finish_before": day(impact.finish_before),
        "finish_after": day(impact.finish_after),
        "float_before_d": impact.float_before_d,
        "float_after_d": impact.float_after_d,
        "note": impact.note,
        "blocking": ", ".join(impact.blocking),
    }
