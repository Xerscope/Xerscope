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
    # a built-in check takes no parameter but its x threshold or its dialog options, shown with their values
    with_parameters = {r.metric.id: explain(r) for r in results if explain(r).parameters}
    assert set(with_parameters) == {
        "P6-04", "P6-05", "P6-06", "P6-16", "P6-17", "DCMA-06", "DCMA-08", "DCMA-09", "DCMA-11", "DCMA-12",
        "DCMA-14", "06A211a", "06A401a", "06A504a", "06A504b", "06A506c",
    }  # fmt: skip
    assert with_parameters["P6-16"].parameters == [("ignore_in_progress", "yes", "standard")]
    assert with_parameters["P6-17"].parameters == [
        ("ignore_soft_constraints", "no", "standard"),
        ("ignore_hard_constraints", "no", "standard"),
    ]
    assert with_parameters["DCMA-09"].parameters == [("date_grain", "day", "standard")]
    assert any("by calendar day" in line for line in with_parameters["DCMA-09"].population)
    assert with_parameters["P6-04"].parameters == [("limit_hours", "352", "standard")]
    assert "Flagged when remaining duration > 352 hours." in with_parameters["P6-04"].population
    assert with_parameters["06A506c"].parameters == [
        ("status_period_days", "28", "standard"),
        ("riding_window_wd", "3", "standard"),
        ("remaining_tolerance_wd", "2", "standard"),
    ]
    riding = "Rides when the start is within 3 working days of the status date in both updates"
    assert any(line.startswith(riding) for line in with_parameters["06A506c"].population)
    slip = "The first open critical task is delayed by 600 working days."
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


@pytest.mark.parametrize(
    "project, text",
    [
        ({"critical_path_type": "CT_DrivPath"}, "on the longest path (P6 Longest Path flag)"),
        ({"critical_path_type": "CT_TotFloat", "critical_drtn_hr_cnt": "16"}, "total float ≤ 16 h"),
        ({"critical_path_type": "CT_TotFloat", "critical_drtn_hr_cnt": ""}, "total float ≤ 0 d"),
    ],
)
def test_critical_definition_says_the_critical_path_type_the_counts_use(project, text):
    """The Overview's "Critical tasks" help: the rule model.py applies to is_critical."""
    from xerkit import snap, todo

    from xerscope.analysis.explain import critical_definition

    said = critical_definition(snap([todo("A")], project=project), default_days=0.0)
    assert said == f"Open tasks (LOE and milestones included) {text}"


def test_the_recency_example_of_the_spi_window_help_is_right():
    """Weeks planned 400 h each. Earned 120, 260, 228, 560: 1 168 / 1 600 = 0.73; with the weights 1-2-3-4,
    (120 + 520 + 684 + 2 240) / 4 000 = 0.89. One week later (260, 228, 560, 168): 1 216 / 1 600 = 0.76;
    weighted, (260 + 456 + 1 680 + 672) / 4 000 = 0.77. The plain figure moves by 0.03, the weighted by 0.12."""
    from xerscope.analysis.explain import SPI_WINDOW_READING

    def plain(earned: list[int]) -> float:
        return sum(earned) / (400 * len(earned))

    def by_recency(earned: list[int]) -> float:
        weights = range(1, len(earned) + 1)
        return sum(weight * hours for weight, hours in zip(weights, earned, strict=True)) / (400 * sum(weights))

    first, second = [120, 260, 228, 560], [260, 228, 560, 168]
    figures = [plain(first), by_recency(first), plain(second), by_recency(second)]
    assert [f"{figure:.2f}" for figure in figures] == ["0.73", "0.89", "0.76", "0.77"]
    assert "give 0.73 here and 0.89 with the weights 1-2-3-4" in SPI_WINDOW_READING
    assert "gives 0.76 here and 0.77 with the weights" in SPI_WINDOW_READING
    assert f"{abs(figures[2] - figures[0]):.2f}" == "0.03" and f"{abs(figures[3] - figures[1]):.2f}" == "0.12"
    assert "moves by 0.03 here, by 0.12 with the weights" in SPI_WINDOW_READING
