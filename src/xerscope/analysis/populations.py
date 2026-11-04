"""Building blocks shared by the one-function-per-check modules (``p6/``, ``dcma/``, ``decm/``).

Each helper answers one question in the words a schedule reader uses: which activities
are open, which have a predecessor, which links lead into open work. A check reads as a
few of these combined with ``&``, ``|`` and ``~``.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ..xer.model import START_CONSTRAINTS, forecast_dates

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

# A link drives the successor's start through FS / SS, and the predecessor's finish through FS / FF.
START_DRIVING_TYPES = ("FS", "SS")
FINISH_DRIVING_TYPES = ("FS", "FF")


# --- funnel ------------------------------------------------------------------------------

# The texts a population step follows, by the token a step cites (docs/standards.md, Sources).
STEP_SOURCES = {
    "101248": "https://docs.oracle.com/cd/G18296_01/client_help/en_US/101248.htm",
    "46278": "https://docs.oracle.com/cd/G18294_01/p6help/en/46278.htm",
    "46282": "https://docs.oracle.com/cd/G18294_01/p6help/en/46282.htm",
    "Ten Six": "https://tensix.com/using-the-p6-check-schedule-tool/",
    "R1": "docs/standards.md: P6 Professional Check Schedule report R1",
    "model": "docs/formulas.md 1.1: a relationship counts when both ends are activities of the file",
}


@dataclass
class Step:
    label: str  # what the step keeps, e.g. "not complete"
    source: str  # a key of STEP_SOURCES
    removed: pd.DataFrame  # the rows this step took out
    left: int  # rows kept after it


@dataclass
class Funnel:
    """A population built one named, sourced filter at a time, so a reviewer sees what each removed.

    funnel = Funnel(context.snapshot.activities).keep("not complete", "101248", not_complete)
    funnel.rows   # the population;  funnel.steps  # [Step("not complete", "101248", ..., 790)]
    """

    rows: pd.DataFrame
    start: int = 0
    steps: list[Step] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.start = len(self.rows)

    def keep(self, label: str, source: str, predicate: Callable[[pd.DataFrame], pd.Series]) -> Funnel:
        if source not in STEP_SOURCES:
            raise ValueError(f"step {label!r}: unknown source {source!r}")
        kept = as_flag(predicate(self.rows))
        self.steps.append(Step(label, source, self.rows[~kept], int(kept.sum())))
        self.rows = self.rows[kept]
        return self


def not_complete(rows: pd.DataFrame) -> pd.Series:
    return ~as_flag(rows["is_complete"])


def not_level_of_effort(rows: pd.DataFrame) -> pd.Series:
    return ~as_flag(rows["is_loe"])


def not_milestone(rows: pd.DataFrame) -> pd.Series:
    return ~as_flag(rows["is_milestone"])


# --- activities --------------------------------------------------------------------------


def as_flag(column: pd.Series) -> pd.Series:
    """A boolean column with the blanks read as False."""
    return column.fillna(False).astype(bool)


def joined_sorted(values: pd.Series) -> str:
    """The values as one sorted, comma-separated string (a groupby aggregation)."""
    return ", ".join(sorted(values))


def open_activities(context: AnalysisContext) -> pd.DataFrame:
    """Every activity that is not completed (WBS summaries are never in the snapshot's activities)."""
    activities = context.snapshot.activities
    return activities[~as_flag(activities["is_complete"])]


def without_level_of_effort(activities: pd.DataFrame) -> pd.DataFrame:
    return activities[~as_flag(activities["is_loe"])]


def without_milestones(activities: pd.DataFrame) -> pd.DataFrame:
    return activities[~as_flag(activities["is_milestone"])]


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


def constrained_by(
    activities: pd.DataFrame, constraint_types: Collection[str], ignore_started_starts: bool
) -> pd.Series:
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


def links_between(relationships: pd.DataFrame, successors: pd.DataFrame, tasks: pd.DataFrame) -> pd.DataFrame:
    """Relationships into one of ``successors`` whose predecessor is in ``tasks`` (both indexed by task code)."""
    return relationships[
        relationships["succ_code"].isin(successors.index) & relationships["pred_code"].isin(tasks.index)
    ]


def has_driving_predecessor(codes: pd.Series, relationships: pd.DataFrame) -> pd.Series:
    """True where the activity is the successor of an FS or SS relationship."""
    driving = relationships["type"].isin(START_DRIVING_TYPES)
    return codes.isin(relationships.loc[driving, "succ_code"])


def has_driving_successor(codes: pd.Series, relationships: pd.DataFrame) -> pd.Series:
    """True where the activity is the predecessor of an FS or FF relationship."""
    driving = relationships["type"].isin(FINISH_DRIVING_TYPES)
    return codes.isin(relationships.loc[driving, "pred_code"])


def lag_flagged(relationships: pd.DataFrame, compare: Callable, limit: float, column: str = "lag_hr") -> pd.DataFrame:
    """The relationships whose lag (blank = 0) satisfies ``compare(lag, limit)``."""
    return relationships[compare(relationships[column].fillna(0), limit)]


# --- progress dates ----------------------------------------------------------------------


def forecast_before(tasks: pd.DataFrame, data_date) -> pd.Series:
    """Incomplete activities whose forecast start (not started) or finish is before the data date."""
    early_start, early_finish = forecast_dates(tasks)  # the same reading as the model's Start / Finish
    not_started_and_late = ~tasks["is_started"] & (early_start < data_date)
    return as_flag(~tasks["is_complete"] & (not_started_and_late | (early_finish < data_date)))


def actual_after(tasks: pd.DataFrame, data_date) -> pd.Series:
    """Activities with an actual start or finish after the data date."""
    return as_flag((tasks["act_start_date"] > data_date) | (tasks["act_end_date"] > data_date))


def invalid_date_reason(forecast: pd.Series, actual: pd.Series) -> pd.Series:
    """Why an activity has an invalid progress date (read only where one of the two masks is True)."""
    reason = np.select(
        [forecast & actual, forecast],
        ["forecast before and actual after data date", "forecast before data date"],
        default="actual after data date",
    )
    return pd.Series(reason, index=forecast.index)


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


def predecessors_ahead(links: pd.DataFrame, tasks: pd.DataFrame) -> pd.DataFrame:
    """The links into a started successor whose FS predecessor is not complete, or SS predecessor not started,
    at the data date (``tasks`` indexed by task code): P6's out-of-sequence activities.

    The link-type reading is calibrated on a P6 Check Schedule report: FF and SF links, and an SS
    predecessor that has started, are not listed.
    """
    if links.empty:
        return links
    predecessor_complete = links["pred_code"].map(tasks["is_complete"]).astype(bool)
    predecessor_started = links["pred_code"].map(tasks["is_started"]).astype(bool)
    return links[((links["type"] == "FS") & ~predecessor_complete) | ((links["type"] == "SS") & ~predecessor_started)]
