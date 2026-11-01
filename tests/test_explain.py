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
    assert params["exclude"] == ("milestones, loe", "standard")
    assert params["no_baseline"] == ("planned", "standard")
    assert params["tolerance_hours"][1] == "default"
    assert any("Excludes: milestones" in line for line in explain(late).population)


def test_link_rules_word_exclusions_on_the_successor():
    from xerscope.analysis.explain import _population

    lines = _population("lag", {"exclude": ["loe", "milestones"], "links": "succ_incomplete"})
    assert "Relationships whose successor is excluded: level of effort, milestones." in lines


def test_relationship_checks_say_relationships(results):
    lags = next(r for r in results if r.metric.id == "P6-08")
    e = explain(lags)
    assert e.subject == "relationships" and "relationships checked" in e.formula


def test_explain_tables_match_registry():
    from xerscope.analysis.explain import EXCLUDE_TEXT, EXEMPT_TEXT, WORDING
    from xerscope.analysis.rules import EXCLUDE, EXEMPT, RULES

    # cpli (ratio) and critical_path_test (pass/fail) have no numerator/denominator/flagged
    # list to word; explain() falls back to WORDING.get(..., defaults) for them.
    assert set(WORDING) == set(RULES) - {"cpli", "critical_path_test"}
    assert set(EXCLUDE_TEXT) == set(EXCLUDE)
    assert set(EXEMPT_TEXT) == set(EXEMPT)
