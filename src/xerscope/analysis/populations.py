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


def open_activities(context: AnalysisContext) -> pd.DataFrame:
    """Every activity that is not completed (WBS summaries are never in the snapshot's activities)."""
    activities = context.snapshot.activities
    return activities[~_yes(activities["is_complete"])]


def without_level_of_effort(activities: pd.DataFrame) -> pd.DataFrame:
    return activities[~_yes(activities["is_loe"])]


def without_milestones(activities: pd.DataFrame) -> pd.DataFrame:
    return activities[~_yes(activities["is_milestone"])]


def discrete_tasks(activities: pd.DataFrame) -> pd.DataFrame:
    """Neither level of effort nor milestones: the tasks DCMA PAM 200.1 section 4.0 measures."""
    return without_milestones(without_level_of_effort(activities))


def open_tasks(context: AnalysisContext) -> pd.DataFrame:
    """The DCMA population: incomplete, non-LOE, non-milestone tasks."""
    return discrete_tasks(open_activities(context))


def with_baseline(context: AnalysisContext, activities: pd.DataFrame) -> pd.DataFrame:
    """The activities with their baseline start and finish (empty where the baseline lacks them)."""
    return activities.join(context.baseline.frame[["bl_start", "bl_finish"]], on="task_code")


def finish_driver(context: AnalysisContext) -> pd.Series | None:
    """The open, non-LOE activity with the latest forecast finish; None when no work remains."""
    activities = context.snapshot.activities
    remaining = activities[~activities["is_complete"] & ~activities["is_loe"] & activities["finish"].notna()]
    return None if remaining.empty else remaining.loc[remaining["finish"].idxmax()]


def has_predecessor_in_project(context: AnalysisContext, activities: pd.DataFrame) -> pd.Series:
    """True where the activity is the successor of a relationship inside this project."""
    return activities["task_code"].isin(_relationships_in_project(context)["succ_code"])


def has_successor_in_project(context: AnalysisContext, activities: pd.DataFrame) -> pd.Series:
    """True where the activity is the predecessor of a relationship inside this project."""
    return activities["task_code"].isin(_relationships_in_project(context)["pred_code"])


def _relationships_in_project(context: AnalysisContext) -> pd.DataFrame:
    relationships = context.snapshot.relationships
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


def relationships_into(context: AnalysisContext, successors: pd.DataFrame) -> pd.DataFrame:
    """Relationships whose successor is one of ``successors``, with both activity names added."""
    names = context.snapshot.activities.set_index("task_code")["task_name"]
    relationships = context.snapshot.relationships
    into = relationships[relationships["succ_code"].isin(successors["task_code"])]
    return into.assign(pred_name=into["pred_code"].map(names), succ_name=into["succ_code"].map(names))


# --- flagged rows ------------------------------------------------------------------------


def open_end_reason(missing_predecessor: pd.Series, missing_successor: pd.Series) -> pd.Series:
    """Why an activity is an open end; empty where it has both."""
    reason = np.select(
        [missing_predecessor & missing_successor, missing_predecessor, missing_successor],
        ["no predecessor, no successor", "no predecessor", "no successor"],
        default="",
    )
    return pd.Series(reason, index=missing_predecessor.index)


def flagged_activities(activities: pd.DataFrame, **extra_columns) -> pd.DataFrame:
    """The standard activity columns of the flagged rows, plus any extra column."""
    flagged = activities[[column for column in ACTIVITY_COLS if column in activities.columns]].copy()
    for name, values in extra_columns.items():
        flagged[name] = values
    return flagged


def flagged_relationships(relationships: pd.DataFrame) -> pd.DataFrame:
    """The standard relationship columns of the flagged rows."""
    return relationships[[column for column in LINK_COLS if column in relationships.columns]].copy()
