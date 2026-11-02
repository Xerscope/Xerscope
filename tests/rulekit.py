"""Shared helpers for rule tests: the built-in standards, loaded once, and ``run`` / ``codes`` / ``counts``."""

from xerscope.analysis import AnalysisContext, builtin_standards, run_metric

STANDARDS = builtin_standards()


def run(std, metric_id, s, baseline=None):
    return run_metric(std[metric_id], AnalysisContext(s, baseline=baseline))


def codes(r):
    return sorted(r.flagged["task_code"]) if "task_code" in r.flagged else []


def links(r):
    """Flagged relationships of a link rule as sorted (pred_code, succ_code) pairs."""
    if "pred_code" not in r.flagged:
        return []
    return sorted(zip(r.flagged["pred_code"], r.flagged["succ_code"], strict=True))


def counts(r):
    return (r.numerator, r.denominator)
