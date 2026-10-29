"""Run a standard's metrics on a snapshot.

    std = builtin_standards()["P6"]
    ctx = AnalysisContext(snapshot, baseline=Baseline.from_snapshot(bl))
    results_frame(run_standard(std, ctx))

A failing rule never takes the others down: its result has status "error" and the
exception text as note.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from ..config import DEFAULT_SETTINGS, Settings
from ..store import SnapshotStore
from ..xer import Snapshot
from .baseline import Baseline
from .rules import RULES
from .standards import Metric, Standard

Status = Literal["pass", "fail", "info", "n/a", "error"]


@dataclass
class CheckResult:
    metric: Metric
    status: Status
    value: float | None = None
    numerator: int | None = None
    denominator: int | None = None
    flagged: pd.DataFrame = field(default_factory=pd.DataFrame)
    note: str = ""


@dataclass
class AnalysisContext:
    snapshot: Snapshot
    store: SnapshotStore | None = None
    baseline: Baseline | None = None
    settings: Settings = DEFAULT_SETTINGS

    @property
    def previous(self) -> Snapshot | None:
        return self.store.previous(self.snapshot) if self.store else None


def run_metric(metric: Metric, ctx: AnalysisContext) -> CheckResult:
    if metric.needs_baseline and ctx.baseline is None:
        return CheckResult(metric, "n/a", note="needs a baseline")
    try:
        out = RULES[metric.rule].fn(ctx, **metric.params)
    except Exception as exc:  # noqa: BLE001 - reported in the result
        return CheckResult(metric, "error", note=f"{type(exc).__name__}: {exc}")
    value = out.value
    if metric.unit == "count":
        value = None if out.numerator is None else float(out.numerator)
    elif value is None and metric.unit == "%" and out.numerator is not None:
        value = 100.0 * out.numerator / out.denominator if out.denominator else None
    status = metric.evaluate(value)
    if value is None and out.denominator == 0:
        status, note = "n/a", out.note or "nothing to check"
    else:
        note = out.note
    return CheckResult(metric, status, value, out.numerator, out.denominator, out.flagged, note)


def run_standard(standard: Standard, ctx: AnalysisContext) -> list[CheckResult]:
    return [run_metric(m, ctx) for m in standard.metrics]


def results_frame(results: list[CheckResult]) -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {
                "id": r.metric.id,
                "group": r.metric.group,
                "check": r.metric.name,
                "description": r.metric.description,
                "target": r.metric.threshold_label,
                "actual": r.value,
                "found": r.numerator,
                "total": r.denominator,
                "status": r.status,
                "note": r.note,
            }
            for r in results
        ]
    )
    df[["found", "total"]] = df[["found", "total"]].astype("Int64")
    return df


def health_history(
    store: SnapshotStore, standard: Standard, baseline: Baseline | Callable[[Snapshot], Baseline | None] | None = None
) -> pd.DataFrame:
    """Every metric on every snapshot: the week-over-week health trend (long format).

    ``baseline`` is one Baseline for all snapshots, or a function giving each its own
    (e.g. ``Baseline.planned``).
    """
    rows = []
    for i, snap in enumerate(store):
        bl = baseline(snap) if callable(baseline) else baseline
        ctx = AnalysisContext(snap, store, bl)
        for r in run_standard(standard, ctx):
            rows.append(
                {
                    "snapshot_idx": i,
                    "data_date": snap.data_date,
                    "id": r.metric.id,
                    "check": r.metric.name,
                    "actual": r.value,
                    "found": r.numerator,
                    "total": r.denominator,
                    "status": r.status,
                }
            )
    df = pd.DataFrame(rows)
    df[["found", "total"]] = df[["found", "total"]].astype("Int64")
    return df
