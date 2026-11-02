"""Building blocks shared by the one-function-per-check modules (``p6/``, ``dcma/``).

Each helper answers one question in the words a schedule reader uses: which activities
are open, which have a predecessor, which links lead into open work. A check reads as a
few of these combined with ``&``, ``|`` and ``~``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ..xer.model import START_CONSTRAINTS

if TYPE_CHECKING:
    from .checks import AnalysisContext

ACTIVITY_COLS = [
    "task_code",
    "task_name",
    "wbs_code",
    "type",
    "status",
    "start",
    "finish",
    "total_float_d",
    "total_float_hr_cnt",
    "remaining_d",
    "original_d",
    "constraint",
]
LINK_COLS = ["pred_code", "pred_name", "succ_code", "succ_name", "type", "lag_hr", "lag_d"]


# --- activities --------------------------------------------------------------------------


def _yes(column: pd.Series) -> pd.Series:
    return column.fillna(False).astype(bool)


def open_activities(ctx: AnalysisContext) -> pd.DataFrame:
    """Every activity that is not completed (WBS summaries are never in the snapshot's activities)."""
    activities = ctx.snapshot.activities
    return activities[~_yes(activities["is_complete"])]


def without_level_of_effort(activities: pd.DataFrame) -> pd.DataFrame:
    return activities[~_yes(activities["is_loe"])]


def without_milestones(activities: pd.DataFrame) -> pd.DataFrame:
    return activities[~_yes(activities["is_milestone"])]


def has_predecessor_in_project(ctx: AnalysisContext, activities: pd.DataFrame) -> pd.Series:
    """True where the activity is the successor of a relationship inside this project."""
    return activities["task_code"].isin(_relationships_in_project(ctx)["succ_code"])


def has_successor_in_project(ctx: AnalysisContext, activities: pd.DataFrame) -> pd.Series:
    """True where the activity is the predecessor of a relationship inside this project."""
    return activities["task_code"].isin(_relationships_in_project(ctx)["pred_code"])


def _relationships_in_project(ctx: AnalysisContext) -> pd.DataFrame:
    relationships = ctx.snapshot.relationships
    return relationships[~relationships["is_external"].astype(bool)]


def constrained_by(activities: pd.DataFrame, constraint_types: list[str], ignore_started_starts: bool) -> pd.Series:
    """True where the primary or the secondary constraint is one of ``constraint_types``.

    With ``ignore_started_starts`` a start constraint on an activity that has started is
    not counted (it can no longer hold the start).
    """
    constrained = pd.Series(False, index=activities.index)
    for column in ("cstr_type", "cstr_type2"):
        counts = activities[column].isin(constraint_types)
        if ignore_started_starts:
            counts &= ~(activities[column].isin(START_CONSTRAINTS) & activities["is_started"])
        constrained |= counts
    return constrained


# --- relationships -----------------------------------------------------------------------


def relationships_into(ctx: AnalysisContext, successors: pd.DataFrame) -> pd.DataFrame:
    """Relationships whose successor is one of ``successors``, with both activity names added."""
    names = ctx.snapshot.activities.set_index("task_code")["task_name"]
    relationships = ctx.snapshot.relationships
    into = relationships[relationships["succ_code"].isin(successors["task_code"])]
    return into.assign(pred_name=into["pred_code"].map(names), succ_name=into["succ_code"].map(names))


# --- flagged rows ------------------------------------------------------------------------


def open_end_reason(missing_predecessor: pd.Series, missing_successor: pd.Series) -> pd.Series:
    """Why an activity is an open end; empty where it has both."""
    reason = np.where(
        missing_predecessor & missing_successor,
        "no predecessor, no successor",
        np.where(missing_predecessor, "no predecessor", np.where(missing_successor, "no successor", "")),
    )
    return pd.Series(reason, index=missing_predecessor.index)


def flagged_activities(activities: pd.DataFrame, **extra_columns) -> pd.DataFrame:
    """The standard activity columns of the flagged rows, plus any extra column."""
    flagged = activities[[c for c in ACTIVITY_COLS if c in activities.columns]].copy()
    for name, values in extra_columns.items():
        flagged[name] = values
    return flagged


def flagged_relationships(relationships: pd.DataFrame) -> pd.DataFrame:
    """The standard relationship columns of the flagged rows."""
    return relationships[[c for c in LINK_COLS if c in relationships.columns]].copy()
