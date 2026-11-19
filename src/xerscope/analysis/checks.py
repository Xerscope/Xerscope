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
    """One check of a standard run on a file: the rule's output judged against the metric's target.

    A rule that needs a baseline and has none is "n/a"; a rule that raises is "error", its message
    in the note; a rule with nothing to check (no value, a denominator of 0) is "n/a".
    """
    baseline = _baseline_named(metric, context.baseline)
    if metric.needs_baseline and context.baseline is None:
        return CheckResult(metric, "n/a", note="needs a baseline", baseline=baseline)
    try:
        out = RULES[metric.rule].fn(context, **metric.params)
    except Exception as exc:  # noqa: BLE001 - reported in the result
        return CheckResult(metric, "error", note=f"{type(exc).__name__}: {exc}", baseline=baseline)
    value = _value(metric, out)
    status, note = out.status or metric.evaluate(value), out.note
    if value is None and out.denominator == 0:
        status, note = "n/a", out.note or "nothing to check"
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


def _baseline_named(metric: Metric, baseline) -> str:
    """The baseline a result is computed on, for its note: "" when the metric does not read one,
    "none" when it reads one and the file has none."""
    if not uses_baseline(metric):
        return ""
    return "none" if baseline is None else baseline.source or baseline.label


def _value(metric: Metric, out) -> float | None:
    """The value judged against the target: the rule's own, the count it found (unit "count"), or
    for a "%" the share its numerator is of its denominator."""
    if metric.unit == "count":
        return None if out.numerator is None else float(out.numerator)
    if out.value is None and metric.unit == "%" and out.numerator is not None:
        return 100.0 * out.numerator / out.denominator if out.denominator else None
    return out.value


def run_standard(
    standard: Standard, context: AnalysisContext, stopped: Callable[[], bool] = lambda: False
) -> list[CheckResult]:
    """Every check of ``standard``, in its order; once ``stopped()``, the checks left are not run."""
    results = []
    for metric in standard.metrics:
        if stopped():
            break
        results.append(run_metric(metric, context))
    return results


@dataclass(frozen=True)
class StandardScore:
    """Criteria in pass over criteria evaluated (pass + fail); info, n/a and error are not evaluated.
    A criterion is a metric, or the metrics sharing an ``item`` (one line of the source written as
    several metrics): it fails when one of them fails."""

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
    criteria = _results_by_criterion(results)
    failed = tuple(_failed_label(label, members) for label, members in criteria.items() if _has_status(members, "fail"))
    passed = sum(not _has_status(members, "fail") and _has_status(members, "pass") for members in criteria.values())
    return StandardScore(passed, passed + len(failed), failed)


def _results_by_criterion(results: list[CheckResult]) -> dict[str, list[CheckResult]]:
    """The results grouped by criterion, in the order met: the metric's ``item``, else its id."""
    criteria: dict[str, list[CheckResult]] = {}
    for result in results:
        criteria.setdefault(result.metric.item or result.metric.id, []).append(result)
    return criteria


def _has_status(members: list[CheckResult], status: str) -> bool:
    return any(result.status == status for result in members)


def _failed_label(label: str, members: list[CheckResult]) -> str:
    """The failed criterion as the card names it: an item names the metrics that failed it."""
    if not members[0].metric.item:
        return label
    return f"{label} ({', '.join(result.metric.id for result in members if result.status == 'fail')})"


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


def status_counts(results: list[CheckResult]) -> dict[str, int]:
    """How many results have each status (0 when none), and ``scored``: those with a target,
    pass + fail."""
    counts = dict.fromkeys(("pass", "fail", "info", "n/a", "error"), 0)
    for result in results:
        counts[result.status] += 1
    counts["scored"] = counts["pass"] + counts["fail"]
    return counts


def summary_frame(results: list[CheckResult]) -> pd.DataFrame:
    """`results_frame` for the summary and its export: with ``flagged``, the number of items each
    check lists, and ``note`` naming the baseline the result was computed on."""
    summary = results_frame(results).assign(flagged=[len(result.flagged) for result in results])
    summary["note"] = [result.note_with_baseline for result in results]
    return summary


TRAIL_FRONT = ["check_id", "check", "check_status"]


def flagged_trail(results: list[CheckResult]) -> pd.DataFrame:
    """Every item listed by every check, one after the other in the order of ``results``: the
    audit trail behind the scores. Each row names its check (``TRAIL_FRONT``, first). Empty, without
    columns, when no check lists anything."""
    lists = [
        result.flagged.assign(check_id=result.metric.id, check=result.metric.name, check_status=result.status)
        for result in results
        if not result.flagged.empty
    ]
    if not lists:
        return pd.DataFrame()
    trail = pd.concat(lists, ignore_index=True)
    return trail[TRAIL_FRONT + [column for column in trail.columns if column not in TRAIL_FRONT]]


def flagged_codes(flagged: pd.DataFrame) -> list[str]:
    """The Activity IDs a check's list names, once each: its tasks, or both ends of its links. An
    end outside the file ("[ext]…") is not an activity of this schedule."""
    codes: list[str] = []
    for column in ("task_code", "pred_code", "succ_code"):
        if column in flagged.columns:
            codes += [str(code) for code in flagged[column].dropna() if not str(code).startswith("[ext]")]
    return list(dict.fromkeys(codes))


def shown_by_group(results: list[CheckResult], only_failed: bool = False) -> dict[str, list[CheckResult]]:
    """The results to show (all, or the failed ones), by group: the groups in order of first
    appearance, each check in the order of ``results`` within its group (a standard may
    interleave its groups)."""
    groups: dict[str, list[CheckResult]] = {}
    for result in results:
        if not only_failed or result.status == "fail":
            groups.setdefault(result.metric.group, []).append(result)
    return groups


def report_counts(got: pd.DataFrame, typed: pd.DataFrame | None = None) -> pd.DataFrame:
    """The lines of a report to fill, one per check of ``got`` (`results_frame`): ``found`` and
    ``total`` from ``typed`` (a report's ``id``, ``found``, ``total``) where it names the check,
    blank elsewhere and when there is no report. A check ``typed`` names and ``got`` has not is
    left out."""
    checks = got[["id", "check"]]
    if typed is None:
        return checks.assign(found=pd.NA, total=pd.NA).astype({"found": "Int64", "total": "Int64"})
    return checks.merge(typed[["id", "found", "total"]], on="id", how="left")


def mismatch_count(compared: pd.DataFrame) -> int:
    """How many lines of `compare_counts` differ from the report."""
    return int((~compared["match"]).sum())


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
