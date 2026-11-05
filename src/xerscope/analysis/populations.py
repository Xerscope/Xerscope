"""Building blocks shared by the one-function-per-check modules (``p6/``, ``dcma/``, ``decm/``).

Each helper answers one question in the words a schedule reader uses: which tasks
are open, which have a predecessor, which links lead into open work. A check reads as a
few of these combined with ``&``, ``|`` and ``~``.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..xer import Snapshot
from ..xer.model import START_CONSTRAINTS, forecast_dates
from .baseline import Baseline

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
    "model": (
        "docs/formulas.md 1.1: a relationship counts when its successor is a task of the file"
        " (the predecessor may be a task of another project of the file)"
    ),
    "PAM 200.1": "https://mail.mosaicprojects.com.au/PDF-Gen/DCMA-PAM-200-1.pdf",
    "DECM 8.0": "https://ssitools.com/helpandsuport/DECM/help/ssi_decm_schedule_tests.htm",
    "xerscope": "docs/standards.md: INTEGRITY, xerscope's own checks (not a published standard)",
}


@dataclass(frozen=True)
class Exclusion:
    """One named way to leave tasks out of a population; the single vocabulary of the checks."""

    label: str  # the funnel step, e.g. "not complete"
    text: str  # the words of the "Excludes:" line, e.g. "completed activities"
    removes: Callable[[pd.DataFrame, pd.Timestamp | None], pd.Series]  # (rows, data date) -> rows it takes out


EXCLUSIONS: dict[str, Exclusion] = {
    "complete": Exclusion("not complete", "completed tasks", lambda rows, _dd: rows["is_complete"]),
    "complete_before_data_date": Exclusion(
        "not completed before the status date",
        "tasks completed before the status date",
        lambda rows, data_date: rows["is_complete"] if data_date is None else rows["act_end_date"] < data_date,
    ),
    "started": Exclusion("not started", "started tasks", lambda rows, _dd: rows["is_started"]),
    "loe": Exclusion("not level of effort", "level of effort", lambda rows, _dd: rows["is_loe"]),
    "milestones": Exclusion("not milestone", "milestones", lambda rows, _dd: rows["is_milestone"]),
    "no_duration": Exclusion(
        "original duration above 0",
        "tasks with no original duration",
        lambda rows, _dd: ~(rows["target_drtn_hr_cnt"].fillna(0) > 0),
    ),
}


def without(rows: pd.DataFrame, data_date, exclude: Sequence[str]) -> pd.DataFrame:
    """``rows`` less the tasks any of the ``exclude`` keys (EXCLUSIONS) removes."""
    removed = pd.Series(False, index=rows.index)
    for key in exclude:
        removed |= as_flag(EXCLUSIONS[key].removes(rows, data_date))
    return rows[~removed]


@dataclass
class Step:
    label: str  # what the step keeps, e.g. "not complete"
    source: str  # a key of STEP_SOURCES
    removed: pd.DataFrame  # the rows this step took out
    left: int  # rows kept after it


@dataclass
class Funnel:
    """A population built one named, sourced filter at a time, so a reviewer sees what each removed.

    funnel = activity_funnel(context.snapshot).exclude("complete", "101248")
    funnel.rows   # the population;  funnel.steps  # [Step("not complete", "101248", ..., 790)]
    """

    rows: pd.DataFrame
    data_date: pd.Timestamp | None = None
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

    def exclude(self, key: str, source: str) -> Funnel:
        """Leave out what EXCLUSIONS[key] removes."""
        exclusion = EXCLUSIONS[key]
        return self.keep(exclusion.label, source, lambda rows: ~as_flag(exclusion.removes(rows, self.data_date)))


def activity_funnel(snapshot: Snapshot) -> Funnel:
    """Every task of the file (WBS summaries are never tasks)."""
    return Funnel(snapshot.activities, snapshot.data_date)


# --- activities --------------------------------------------------------------------------


def as_flag(column: pd.Series) -> pd.Series:
    """A boolean column with the blanks read as False."""
    return column.fillna(False).astype(bool)


def joined_sorted(values: pd.Series) -> str:
    """The values as one sorted, comma-separated string (a groupby aggregation)."""
    return ", ".join(sorted(values))


def with_baseline(baseline: Baseline, activities: pd.DataFrame) -> pd.DataFrame:
    """The tasks with their baseline start and finish (empty where the baseline lacks them)."""
    return activities.join(baseline.frame[["bl_start", "bl_finish"]], on="task_code")


def finish_driver(snapshot: Snapshot) -> pd.Series | None:
    """The open, non-LOE task with the latest forecast finish; None when no work remains."""
    activities = snapshot.activities
    remaining = activities[~activities["is_complete"] & ~activities["is_loe"] & activities["finish"].notna()]
    return None if remaining.empty else remaining.loc[remaining["finish"].idxmax()]


def has_predecessor_in_project(snapshot: Snapshot, activities: pd.DataFrame) -> pd.Series:
    """True where the task is the successor of a relationship inside this project."""
    return activities["task_code"].isin(_relationships_in_project(snapshot)["succ_code"])


def has_successor_in_project(snapshot: Snapshot, activities: pd.DataFrame) -> pd.Series:
    """True where the task is the predecessor of a relationship inside this project."""
    return activities["task_code"].isin(_relationships_in_project(snapshot)["pred_code"])


def _relationships_in_project(snapshot: Snapshot) -> pd.DataFrame:
    relationships = snapshot.relationships
    return relationships[~relationships["is_external"].astype(bool)]


def constrained_by(
    activities: pd.DataFrame, constraint_types: Collection[str], ignore_started_starts: bool
) -> pd.Series:
    """True where the primary or the secondary constraint is one of ``constraint_types``.

    With ``ignore_started_starts`` a start constraint on a task that has started is
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
    """True where the task is the successor of an FS or SS relationship."""
    driving = relationships["type"].isin(START_DRIVING_TYPES)
    return codes.isin(relationships.loc[driving, "succ_code"])


def has_driving_successor(codes: pd.Series, relationships: pd.DataFrame) -> pd.Series:
    """True where the task is the predecessor of an FS or FF relationship."""
    driving = relationships["type"].isin(FINISH_DRIVING_TYPES)
    return codes.isin(relationships.loc[driving, "pred_code"])


def lag_flagged(relationships: pd.DataFrame, compare: Callable, limit: float, column: str = "lag_hr") -> pd.DataFrame:
    """The relationships whose lag (blank = 0) satisfies ``compare(lag, limit)``."""
    return relationships[compare(relationships[column].fillna(0), limit)]


# --- progress dates ----------------------------------------------------------------------


DATE_GRAINS = ("timestamp", "day")


def at_grain(dates: pd.Series | pd.Timestamp, grain: str):
    """Dates as a check compares them: as stored ("timestamp", P6's reading: 12:00 is after a data date
    at 08:00) or by calendar day ("day", DCMA-EA PAM 200.1, which reasons in dates)."""
    if grain not in DATE_GRAINS:
        raise ValueError(f"date grain {grain!r} not in {DATE_GRAINS}")
    if grain == "timestamp":
        return dates
    return dates.dt.normalize() if isinstance(dates, pd.Series) else dates.normalize()


def forecast_before(tasks: pd.DataFrame, data_date, grain: str = "timestamp") -> pd.Series:
    """Incomplete tasks whose forecast start (not started) or finish is before the status date."""
    early_start, early_finish = forecast_dates(tasks)  # the same reading as the model's Start / Finish
    early_start, early_finish, data_date = (at_grain(d, grain) for d in (early_start, early_finish, data_date))
    not_started_and_late = ~tasks["is_started"] & (early_start < data_date)
    return as_flag(~tasks["is_complete"] & (not_started_and_late | (early_finish < data_date)))


def actual_after(tasks: pd.DataFrame, data_date, grain: str = "timestamp") -> pd.Series:
    """Tasks with an actual start or finish after the status date."""
    data_date = at_grain(data_date, grain)
    start, end = (at_grain(tasks[c], grain) for c in ("act_start_date", "act_end_date"))
    return as_flag((start > data_date) | (end > data_date))


def invalid_date_reason(forecast: pd.Series, actual: pd.Series) -> pd.Series:
    """Why a task has an invalid progress date (read only where one of the two masks is True)."""
    reason = np.select(
        [forecast & actual, forecast],
        ["forecast before and actual after status date", "forecast before status date"],
        default="actual after status date",
    )
    return pd.Series(reason, index=forecast.index)


# --- flagged rows ------------------------------------------------------------------------


def open_end_reason(missing_predecessor: pd.Series, missing_successor: pd.Series) -> pd.Series:
    """Why a task is an open end; empty where it has both."""
    reason = np.select(
        [missing_predecessor & missing_successor, missing_predecessor, missing_successor],
        ["no predecessor, no successor", "no predecessor", "no successor"],
        default="",
    )
    return pd.Series(reason, index=missing_predecessor.index)


def flagged_activities(activities: pd.DataFrame, **extra_columns) -> pd.DataFrame:
    """The standard task columns of the flagged rows, plus any extra column."""
    flagged = activities[[column for column in ACTIVITY_COLS if column in activities.columns]].copy()
    for name, values in extra_columns.items():
        flagged[name] = values
    return flagged


def flagged_relationships(relationships: pd.DataFrame) -> pd.DataFrame:
    """The standard relationship columns of the flagged rows."""
    return relationships[[column for column in LINK_COLS if column in relationships.columns]].copy()


def predecessors_ahead(links: pd.DataFrame, tasks: pd.DataFrame) -> pd.DataFrame:
    """The links into a started successor whose FS predecessor is not complete, or SS predecessor not started,
    at the status date (``tasks`` indexed by task code): P6's out-of-sequence tasks.

    The link-type reading is calibrated on a P6 Check Schedule report: FF and SF links, and an SS
    predecessor that has started, are not listed.
    """
    if links.empty:
        return links
    predecessor_complete = links["pred_code"].map(tasks["is_complete"]).astype(bool)
    predecessor_started = links["pred_code"].map(tasks["is_started"]).astype(bool)
    return links[((links["type"] == "FS") & ~predecessor_complete) | ((links["type"] == "SS") & ~predecessor_started)]
