"""The calculation shown next to each check must restate the result, never contradict it."""

import pytest

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_standard
from xerscope.analysis.explain import explain, fmt_value


@pytest.fixture(scope="module")
def results(store):
    bl = Baseline.from_snapshot(store.first)
    out = []
    for std in builtin_standards().values():
        out += run_standard(std, AnalysisContext(store.latest, store, bl))
    return out


def test_formula_restates_the_numbers(results):
    for r in results:
        e = explain(r)
        if r.metric.unit in ("%", "ratio") and r.numerator is not None and r.denominator:
            assert f"{r.numerator} " in e.formula and f"/ {r.denominator} " in e.formula, (r.metric.id, e.formula)
            assert e.formula.endswith(fmt_value(r.value, r.metric.unit)), (r.metric.id, e.formula)
        if r.metric.unit == "count" and r.status in ("pass", "fail"):
            assert e.formula.startswith(f"{r.numerator or 0} "), (r.metric.id, e.formula)


def test_verdict_follows_status(results):
    for r in results:
        v = explain(r).verdict
        if r.metric.unit == "pass/fail":
            continue
        expected = {
            "pass": "meets the target",
            "fail": "misses the target",
            "info": "no pass/fail target",
            "n/a": "Not applicable",
            "error": "error",
        }[r.status]
        assert expected in v, (r.metric.id, r.status, v)


def test_parameters_show_standard_and_defaults(results):
    late = next(r for r in results if r.metric.id == "P6-12")
    params = {name: (value, origin) for name, value, origin in explain(late).parameters}
    assert params["exclude"] == ("complete, milestones, loe", "standard")
    assert params["tolerance_hours"][1] == "default"
    assert any("Excludes: completed activities" in line for line in explain(late).population)


def test_relationship_checks_say_relationships(results):
    lags = next(r for r in results if r.metric.id == "P6-08")
    e = explain(lags)
    assert e.subject == "relationships" and "relationships checked" in e.formula
