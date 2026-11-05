"""Schedule risk analysis (experimental): the CPM rerun with drawn durations.

A CPM gives one finish date. Durations are estimates, so the finish is a distribution: each
iteration draws a duration for every activity that has a range, reschedules with the engine of
``analysis/cpm.py`` and records the project finish and the longest path. After N iterations the
finish is read as percentiles (P80 = 80 % of the iterations finish on or before that date) and
each activity as its criticality (share of iterations where it is on the longest path).

Method: GAO Schedule Assessment Guide, Best Practice 8 (a sound CPM schedule, a simulation, the
confidence level of the finish). Ranges are three-point factors of the remaining duration
(minimum, most likely, maximum), drawn from the triangular law. Draws are independent: correlated
risks (AACE RP 57R-09, risk drivers) are not modelled yet, so the spread is a lower bound.

Choices, each visible in the result:

- a drawn factor multiplies the remaining duration the plain recalculation uses (the one an
  expected finish set, if any): ``cpm.schedule(..., scale=...)``; the activity loses its expected
  finish in the draw, as the delayed activity of the critical path test does;
- a resource-dependent activity applies the factor to each driving assignment's remaining work,
  still placed on its resource's calendar;
- an open activity with a mandatory constraint keeps its date whatever its duration (``pinned``);
- factors are never negative, so a drawn duration is never below zero; milestones are not drawn.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..xer import Snapshot
from . import cpm

Range = tuple[float, float, float]  # minimum, most likely, maximum, as factors of the remaining duration
NO_RANGE: Range = (1.0, 1.0, 1.0)
PERCENTILES = (10, 50, 80, 90)


def check_range(task_code: str, values: Range) -> Range:
    low, mode, high = (float(value) for value in values)
    if not 0 <= low <= mode <= high:
        raise ValueError(f"{task_code}: a range needs 0 <= minimum <= most likely <= maximum, got {values}")
    return low, mode, high


def read_ranges(path: str | Path) -> dict[str, Range]:
    """A CSV with columns task_code, min, most_likely, max (factors of the remaining duration)."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    missing = {"task_code", "min", "most_likely", "max"} - set(rows[0] if rows else {})
    if missing:
        raise ValueError(f"{path}: missing column(s) {sorted(missing)}")
    return {
        row["task_code"]: check_range(row["task_code"], (row["min"], row["most_likely"], row["max"])) for row in rows
    }


@dataclass
class SraResult:
    finishes: pd.Series  # one project finish per iteration
    deterministic_finish: pd.Timestamp  # the plain recalculation's
    criticality: pd.Series  # task_code -> share of iterations on the longest path
    iterations: int
    seed: int
    varied: list[str] = field(default_factory=list)
    pinned: list[str] = field(default_factory=list)

    def percentile(self, p: float) -> pd.Timestamp:
        """The finish of the iteration at that rank: a date the engine computed, never an interpolation."""
        values = np.sort(self.finishes.to_numpy(dtype="datetime64[ns]"))
        return pd.Timestamp(values[max(0, int(np.ceil(p / 100 * len(values))) - 1)])

    @property
    def deterministic_confidence(self) -> float:
        """Share of iterations finishing on or before the plain recalculation's finish."""
        return float((self.finishes <= self.deterministic_finish).mean())


def simulate(
    snapshot: Snapshot,
    ranges: dict[str, Range] | None = None,
    default: Range = NO_RANGE,
    iterations: int = 1000,
    seed: int = 0,
) -> SraResult:
    """Draw ``iterations`` durations for every open activity with a range, reschedule each time."""
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    ranges = {code: check_range(code, values) for code, values in (ranges or {}).items()}
    default = check_range("default", default)
    base = cpm.schedule(snapshot)
    frame = base.frame
    activities = snapshot.by_code
    unknown = sorted(set(ranges) - set(frame.index))
    if unknown:
        raise ValueError(f"ranges name activities the schedule does not have: {unknown[:10]}")

    open_codes = sorted(
        code
        for code in frame.index
        if frame.at[code, "status_code"] != "TK_Complete"
        and not activities.at[code, "is_loe"]
        and not activities.at[code, "is_milestone"]
    )
    varied = [code for code in open_codes if ranges.get(code, default) != NO_RANGE]
    mandatory = activities["cstr_type"].isin(cpm.MANDATORY) | activities["cstr_type2"].isin(cpm.MANDATORY)
    pinned = sorted(code for code in open_codes if bool(mandatory.get(code, False)))

    rng = np.random.default_rng(seed)
    bounds = np.array([ranges.get(code, default) for code in varied], dtype=float).reshape(-1, 3)
    spread = bounds[:, 2] > bounds[:, 0]
    factors = np.tile(bounds[:, 1], (iterations, 1))  # a degenerate range is its most likely value
    if spread.any():
        factors[:, spread] = rng.triangular(
            bounds[spread, 0], bounds[spread, 1], bounds[spread, 2], size=(iterations, int(spread.sum()))
        )

    finishes, on_path = [], pd.Series(0, index=frame.index, dtype=float)
    for draw in factors:
        scale = {code: float(factor) for code, factor in zip(varied, draw, strict=True) if factor != 1.0}
        result = cpm.schedule(snapshot, scale=scale, base=base) if scale else base
        finishes.append(result.finish)
        on_path = on_path.add(result.frame["longest_path"].astype(float), fill_value=0.0)
    return SraResult(
        finishes=pd.Series(finishes, name="finish"),
        deterministic_finish=base.finish,
        criticality=(on_path / iterations).rename("criticality"),
        iterations=iterations,
        seed=seed,
        varied=varied,
        pinned=pinned,
    )
