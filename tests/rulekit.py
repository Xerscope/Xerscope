"""Shared helpers for rule tests: the built-in standards (loaded once), ``run``, ``run_on_store``, ``codes``."""

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_metric

STANDARDS = builtin_standards()


def run(std, metric_id, s, baseline=None):
    return run_metric(std[metric_id], AnalysisContext(s, baseline=baseline))


def run_on_store(store, index, metric_id, baseline=True):
    """One metric on ``store[index]`` with the store's first update as baseline (or none)."""
    first_as_baseline = Baseline.from_snapshot(store.first) if baseline else None
    context = AnalysisContext(store[index], store, first_as_baseline)
    return run_metric(STANDARDS[metric_id.split("-")[0]][metric_id], context)


def codes(r):
    return sorted(r.flagged["task_code"]) if "task_code" in r.flagged else []


def links(r):
    """Flagged relationships of a link rule as sorted (pred_code, succ_code) pairs."""
    if "pred_code" not in r.flagged:
        return []
    return sorted(zip(r.flagged["pred_code"], r.flagged["succ_code"], strict=True))


def counts(r):
    return (r.numerator, r.denominator)
