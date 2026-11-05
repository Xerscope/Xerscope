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
from .rules import RULES, AnalysisContext
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
    baseline: str = ""  # the baseline the result was computed on ("none" when it needs one and has none)

    @property
    def note_with_baseline(self) -> str:
        """``note`` followed by the baseline, for the exports."""
        if not self.baseline:
            return self.note
        return f"{self.note} · baseline: {self.baseline}" if self.note else f"baseline: {self.baseline}"


# Rules that read the baseline without needing one (they fall back on the planned dates), by name
BASELINE_READERS = {"decm_06a204b_dangling_logic", "dcma_08_high_duration"}


def uses_baseline(metric: Metric) -> bool:
    """Whether the baseline changes this metric's result."""
    effective = {**RULES[metric.rule].params, **metric.params}
    return metric.needs_baseline or metric.rule in BASELINE_READERS or effective.get("field") == "baseline"


def run_metric(metric: Metric, context: AnalysisContext) -> CheckResult:
    used = context.baseline
    baseline = ("none" if used is None else used.source or used.label) if uses_baseline(metric) else ""
    if metric.needs_baseline and context.baseline is None:
        return CheckResult(metric, "n/a", note="needs a baseline", baseline=baseline)
    try:
        out = RULES[metric.rule].fn(context, **metric.params)
    except Exception as exc:  # noqa: BLE001 - reported in the result
        return CheckResult(metric, "error", note=f"{type(exc).__name__}: {exc}", baseline=baseline)
    value = out.value
    if metric.unit == "count":
        value = None if out.numerator is None else float(out.numerator)
    elif value is None and metric.unit == "%" and out.numerator is not None:
        value = 100.0 * out.numerator / out.denominator if out.denominator else None
    status = out.status or metric.evaluate(value)
    if value is None and out.denominator == 0:
        status, note = "n/a", out.note or "nothing to check"
    else:
        note = out.note
    return CheckResult(
        metric,
        status,
        value,
        out.numerator,
        out.denominator,
        out.flagged,
        note,
        out.checked,
        out.counted,
        out.funnel,
        baseline,
    )


def run_standard(standard: Standard, context: AnalysisContext) -> list[CheckResult]:
    return [run_metric(metric, context) for metric in standard.metrics]


@dataclass(frozen=True)
class StandardScore:
    """Checks in pass over checks evaluated (pass + fail); info, n/a and error are not evaluated."""

    passed: int
    evaluated: int
    failed_ids: tuple[str, ...]

    @property
    def share(self) -> float | None:
        """passed / evaluated, None when no check was evaluated (the score is n/a)."""
        return self.passed / self.evaluated if self.evaluated else None

    @property
    def value(self) -> str:
        return "–" if self.share is None else f"{100 * self.share:.0f} %"

    @property
    def detail(self) -> str:
        if not self.evaluated:
            return "0 evaluated"
        failed = f": {', '.join(self.failed_ids)}" if self.failed_ids else ""
        return f"{self.evaluated} evaluated · {len(self.failed_ids)} fail{failed}"


def standard_score(results: list[CheckResult]) -> StandardScore:
    """The score of one standard from its results (xerscope convention, docs/formulas.md §1.6)."""
    failed = tuple(result.metric.id for result in results if result.status == "fail")
    passed = sum(result.status == "pass" for result in results)
    return StandardScore(passed, passed + len(failed), failed)


def fmt_value(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    if unit == "%":
        return f"{value:.1f} %"
    if unit == "ratio":
        return f"{value:.2f}"
    if unit == "pass/fail":
        return "pass" if value >= 1 else "fail"
    return f"{value:g}"


def _result_text(result: CheckResult) -> str:
    return "–" if result.status in ("n/a", "error") else fmt_value(result.value, result.metric.unit)


def _count_text(result: CheckResult) -> str:
    if result.numerator is not None and result.denominator is not None:
        return f"{result.numerator} / {result.denominator}"
    return "" if result.numerator is None else str(result.numerator)


def results_frame(results: list[CheckResult]) -> pd.DataFrame:
    """One row per result: the numbers (``actual``, ``found``, ``total``) and the text shown for them
    (``target``, ``result``, ``count``)."""
    frame = pd.DataFrame(
        [
            {
                "id": result.metric.id,
                "group": result.metric.group,
                "check": result.metric.name,
                "description": result.metric.description,
                "target": result.metric.threshold_label,
                "result": _result_text(result),
                "count": _count_text(result),
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
    store: SnapshotStore,
    standard: Standard,
    baseline: Baseline | Callable[[Snapshot], Baseline | None] | None = None,
    result_of: Callable[[Metric, Snapshot], CheckResult] | None = None,
) -> pd.DataFrame:
    """Every metric on every snapshot: the week-over-week health trend (long format).

    ``baseline`` is one Baseline for all snapshots, or a function giving each its own
    (e.g. ``Baseline.planned``). ``result_of(metric, update)``, when given, supplies each result
    instead (the app's per-session cache); ``baseline`` is then not read.
    """
    rows = []
    for index, update in enumerate(store):
        if result_of is not None:
            results = [result_of(metric, update) for metric in standard.metrics]
        else:
            update_baseline = baseline(update) if callable(baseline) else baseline
            results = run_standard(standard, AnalysisContext(update, store, update_baseline))
        for result in results:
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
