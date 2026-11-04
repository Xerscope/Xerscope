"""Run a standard's metrics on a snapshot.

    std = builtin_standards()["P6"]
    context = AnalysisContext(snapshot, baseline=Baseline.from_snapshot(bl))
    results_frame(run_standard(std, context))

A failing rule never takes the others down: its result has status "error" and the
exception text as note.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from ..store import SnapshotStore
from ..xer import Snapshot
from .baseline import Baseline
from .populations import Funnel
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
    checked: pd.DataFrame | None = None  # rows behind the denominator (RuleOutput.checked)
    counted: pd.DataFrame | None = None  # rows behind the numerator when they are not ``flagged``
    funnel: Funnel | None = None  # the named steps that cut ``checked`` from the file


@dataclass
class AnalysisContext:
    snapshot: Snapshot
    store: SnapshotStore | None = None
    baseline: Baseline | None = None


def run_metric(metric: Metric, context: AnalysisContext) -> CheckResult:
    if metric.needs_baseline and context.baseline is None:
        return CheckResult(metric, "n/a", note="needs a baseline")
    try:
        out = RULES[metric.rule].fn(context, **metric.params)
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
    return CheckResult(
        metric, status, value, out.numerator, out.denominator, out.flagged, note, out.checked, out.counted, out.funnel
    )


def run_standard(standard: Standard, context: AnalysisContext) -> list[CheckResult]:
    return [run_metric(metric, context) for metric in standard.metrics]


def results_frame(results: list[CheckResult]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "id": result.metric.id,
                "group": result.metric.group,
                "check": result.metric.name,
                "description": result.metric.description,
                "target": result.metric.threshold_label,
                "actual": result.value,
                "found": result.numerator,
                "total": result.denominator,
                "status": result.status,
                "note": result.note,
            }
            for result in results
        ]
    )
    frame[["found", "total"]] = frame[["found", "total"]].astype("Int64")
    return frame


def compare_counts(got: pd.DataFrame, expected: pd.DataFrame, keys: list[str] | None = None) -> pd.DataFrame:
    """found / total typed from a report (P6 Check Schedule summary) against ``results_frame``.

    ``expected`` has ``id``, ``found``, ``total`` (and ``file`` when ``keys`` names it). A line
    with neither count typed is not part of the report and is left out. ``match`` is False
    when either count differs or the check is not in ``got``.
    """
    keys = keys or ["id"]
    typed = expected.dropna(subset=["found", "total"], how="all")
    typed = typed.astype({"found": "Int64", "total": "Int64"})
    merged = typed[keys + ["found", "total"]].merge(
        got[keys + ["check", "found", "total"]], on=keys, how="left", suffixes=("_exp", "")
    )
    same = (merged["found_exp"] == merged["found"]) & (merged["total_exp"] == merged["total"])
    merged["match"] = same.fillna(False).astype(bool)
    return merged[keys + ["check", "found_exp", "found", "total_exp", "total", "match"]]


def health_history(
    store: SnapshotStore, standard: Standard, baseline: Baseline | Callable[[Snapshot], Baseline | None] | None = None
) -> pd.DataFrame:
    """Every metric on every snapshot: the week-over-week health trend (long format).

    ``baseline`` is one Baseline for all snapshots, or a function giving each its own
    (e.g. ``Baseline.planned``).
    """
    rows = []
    for index, update in enumerate(store):
        update_baseline = baseline(update) if callable(baseline) else baseline
        context = AnalysisContext(update, store, update_baseline)
        for result in run_standard(standard, context):
            rows.append(
                {
                    "snapshot_idx": index,
                    "data_date": update.data_date,
                    "id": result.metric.id,
                    "check": result.metric.name,
                    "actual": result.value,
                    "found": result.numerator,
                    "total": result.denominator,
                    "status": result.status,
                }
            )
    frame = pd.DataFrame(rows)
    frame[["found", "total"]] = frame[["found", "total"]].astype("Int64")
    return frame


def health_wide(history: pd.DataFrame, standard: Standard) -> pd.DataFrame:
    """Check results as a table: one row per check, one column per update (``YYYY-MM-DD``).

    ``history`` is the long frame from :func:`health_history`; rows follow the standard's order.
    """
    ids = [metric.id for metric in standard.metrics]
    wide = history.pivot_table(index="id", columns="data_date", values="actual", aggfunc="first").reindex(ids)
    wide.columns = [f"{column:%Y-%m-%d}" for column in wide.columns]
    wide.insert(0, "check", [standard[metric_id].name for metric_id in wide.index])
    return wide.reset_index()
