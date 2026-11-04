"""The calculation shown next to each check must restate the result, never contradict it."""

import pytest

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_metric, run_standard
from xerscope.analysis.explain import explain, fmt_value
from xerscope.analysis.rules import RULES
from xerscope.analysis.standards import loads_standard, template_text


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


def test_parameters_show_standard_and_defaults(results, store):
    late = next(r for r in results if r.metric.id == "P6-12")
    assert explain(late).parameters == []  # the P6 checks are explicit functions: nothing to set
    assert any("milestones" in line for line in explain(late).population)
    # a built-in check takes no parameter but its x threshold, shown with its default and its sentence
    with_parameters = {r.metric.id: explain(r) for r in results if explain(r).parameters}
    assert set(with_parameters) == {
        "P6-04", "P6-05", "P6-06", "DCMA-06", "DCMA-08", "DCMA-12",
        "06A211a", "06A401a", "06A504a", "06A504b", "06A506c",
    }  # fmt: skip
    assert with_parameters["P6-04"].parameters == [("limit_hours", "352", "standard")]
    assert "Flagged when remaining duration > 352 hours." in with_parameters["P6-04"].population
    assert with_parameters["06A506c"].parameters == [
        ("status_period_days", "28", "standard"),
        ("riding_window_wd", "3", "standard"),
        ("remaining_tolerance_wd", "2", "standard"),
    ]
    riding = "Rides when the start is within 3 working days of the data date in both updates"
    assert any(line.startswith(riding) for line in with_parameters["06A506c"].population)
    slip = "The first open critical activity is delayed by 600 working days."
    assert slip in with_parameters["DCMA-12"].population

    custom = loads_standard(template_text())  # the parameterised rules live in the custom template
    lines = explain(run_metric(custom["CUS-04"], AnalysisContext(store.latest))).parameters
    assert {origin for _name, _value, origin in lines} == {"standard", "default"}


def test_link_rules_word_exclusions_on_the_successor():
    from xerscope.analysis.explain import _population
    from xerscope.analysis.rules import RULES

    lines = _population(RULES["lag"], {"exclude": ["loe", "milestones"], "links": "succ_incomplete"})
    assert "Relationships whose successor is excluded: level of effort, milestones." in lines


def test_relationship_checks_say_relationships(results):
    lags = next(r for r in results if r.metric.id == "P6-08")
    e = explain(lags)
    assert e.subject == "relationships" and "relationships checked" in e.formula


def test_rules_that_flag_relationships_declare_links(results):
    for r in results:
        if "pred_code" in r.flagged.columns:
            assert RULES[r.metric.rule].links, r.metric.id


def test_explain_tables_match_registry():
    from xerscope.analysis.populations import EXCLUSIONS
    from xerscope.analysis.rules import EXEMPT, RULES

    # the CPLI (ratio) and critical path test (pass/fail) rules have no numerator/denominator/flagged
    # list to word; explain() falls back to defaults for them.
    assert {name for name, rule in RULES.items() if rule.title} == set(RULES) - {
        "dcma_12_critical_path_test",
        "dcma_13_cpli",
        "decm_06a401a_critical_path_test",
    }
    # the vocabularies carry their own labels: every key has one, so explain never falls back to the key
    assert all(exclusion.text for exclusion in EXCLUSIONS.values())
    assert all(EXEMPT.values())


def test_every_exemption_has_a_mask():
    """An EXEMPT key without its mask in _exempt_masks would only fail when a standard uses it."""
    from xerkit import snap, todo

    from xerscope.analysis.rules import EXEMPT, _exempt_masks

    pop = snap([todo("A")]).activities
    assert set(_exempt_masks(pop, set(), set())) == set(EXEMPT)
