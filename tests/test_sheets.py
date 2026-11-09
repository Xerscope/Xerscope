"""The calculation sheets (src/xerscope/sheets/<standard>/<id>.md) against the code and the standard.

A sheet is written by hand, so these checks keep it from drifting: one sheet per metric, the
metric's real target and parameter values, XER fields and codes that the model reads, test
names that exist, links to the documentation sites only.
"""

import re
from pathlib import Path

import pytest

import xerscope
from xerscope.analysis import builtin_standards
from xerscope.analysis.audit import sheet

PACKAGE = Path(xerscope.__file__).parent
MODEL = (PACKAGE / "xer" / "model.py").read_text(encoding="utf-8")
TESTS = "\n".join(path.read_text(encoding="utf-8") for path in Path(__file__).parent.glob("test_*.py"))
WITH_SHEETS = ["P6"]
SOURCES = {"docs.oracle.com", "tensix.com"}
METRICS = [(standard_id, metric) for standard_id in WITH_SHEETS for metric in builtin_standards()[standard_id].metrics]


def test_one_sheet_per_metric_and_no_other():
    for standard_id in WITH_SHEETS:
        written = {path.stem for path in (PACKAGE / "sheets" / standard_id).glob("*.md")}
        assert written == {metric.id for metric in builtin_standards()[standard_id].metrics}


@pytest.mark.parametrize(("standard_id", "metric"), METRICS, ids=[m.id for _s, m in METRICS])
def test_sheet_matches_the_standard_and_the_code(standard_id, metric):
    text = sheet(standard_id, metric)
    assert text is not None
    assert text.startswith(f"# {metric.id} · {metric.name}\n"), "title = id · name of the TOML"
    assert f"`{metric.threshold_label}`" in text, "the target written in the TOML"
    for name, value in metric.params.items():
        written = str(value).lower() if isinstance(value, bool) else f"{value:g}"  # as TOML writes it
        assert f"{name} = {written}" in text, f"parameter {name} with the TOML value"
    for table, column in re.findall(r"`(TASK|TASKPRED|TASKRSRC|PROJECT|PROJCOST)\.(\w+)`", text):
        assert f'"{column}"' in MODEL, f"{table}.{column} is not a field the model reads"
    for code in re.findall(r"`((?:TK|TT|PR|CS)_\w+)`", text):
        assert f'"{code}"' in MODEL, f"{code} is not a code the model knows"
    for test_name in re.findall(r"`(test_\w+)`", text):
        assert f"def {test_name}(" in TESTS, f"{test_name} does not exist"
    hosts = set(re.findall(r"\]\(https://([^/)]+)", text))
    assert hosts <= SOURCES, hosts - SOURCES


def test_no_sheet_for_a_metric_that_is_not_the_built_in_one():
    """An uploaded standard reusing the id P6 with another rule gets no built-in sheet."""
    import dataclasses

    metric = builtin_standards()["P6"]["P6-04"]
    assert sheet("P6", dataclasses.replace(metric, rule="p6_06_large_float")) is None
    assert sheet("CUSTOM", metric) is None


# --- one population, three texts: the rule's steps, the sheet, the standard file, the docstring --------

STEP_LINE = re.compile(r"^\d+\. (.+?): .*\((\S+(?: \S+)?)\)$")
# the words of the docstring population line (explain.EXCLUDE / LINKS_TEXT) for each step label
DOCSTRING_WORDS = {
    "not complete": "completed tasks",
    "not level of effort": "level of effort",
    "not milestone": "milestones",
    "not completed before the status date": "tasks completed before the status date",
}


def _section(text: str, title: str) -> str:
    start = text.index(f"## {title}\n") + len(title) + 4
    end = text.find("\n## ", start)
    return text[start : end if end != -1 else len(text)]


@pytest.fixture(scope="module")
def p6_results(store):
    from xerscope.analysis import AnalysisContext, Baseline, run_standard

    context = AnalysisContext(store.latest, store, Baseline.from_snapshot(store.first))
    return {result.metric.id: result for result in run_standard(builtin_standards()["P6"], context)}


@pytest.mark.parametrize("metric_id", [m.id for m in builtin_standards()["P6"].metrics])
def test_the_rule_the_sheet_and_the_standard_name_the_same_steps(p6_results, metric_id):
    """Each population step of the rule is listed in the sheet in the same order with the same
    source; the source is named in the metric's `source` in p6.toml and linked from the sheet."""
    from xerscope.analysis.populations import STEP_SOURCES

    result = p6_results[metric_id]
    metric = result.metric
    steps = [(step.label, step.source) for step in result.funnel.steps]
    text = sheet("P6", metric)
    written = [
        match.groups()
        for line in _section(text, "Population (denominator)").splitlines()
        if (match := STEP_LINE.match(line))
    ]
    assert written == steps, "sheet steps differ from the rule's"
    for _label, source in steps:
        if source == "model":
            continue
        assert source in metric.source, f"p6.toml source of {metric_id} does not name {source}"
        if STEP_SOURCES[source].startswith("http"):
            assert STEP_SOURCES[source] in text, f"the sheet does not link {source}"


@pytest.mark.parametrize("metric_id", [m.id for m in builtin_standards()["P6"].metrics])
def test_the_rule_docstring_excludes_what_its_steps_remove(p6_results, metric_id):
    """The 'Excludes:' line Schedule health shows lists exactly the activity steps (any order);
    a link rule says which relationships it counts; a rule without step says nothing is excluded."""
    from xerscope.analysis.explain import LINKS_TEXT

    result = p6_results[metric_id]
    lines = RULES_POPULATION(result.metric.rule)
    labels = [step.label for step in result.funnel.steps]
    excludes = [line for line in lines if line.startswith("Excludes: ")]
    activity_steps = {DOCSTRING_WORDS[label] for label in labels if label in DOCSTRING_WORDS}
    if activity_steps:
        assert len(excludes) == 1, lines
        assert set(excludes[0].removeprefix("Excludes: ").rstrip(".").split(", ")) == activity_steps
    else:
        assert not excludes, lines
    if "not both ends complete" in labels:
        assert f"Relationships counted: {LINKS_TEXT['not_both_complete']}." in lines


def RULES_POPULATION(rule_name: str) -> tuple[str, ...]:
    from xerscope.analysis.rules import RULES

    return RULES[rule_name].population


# No row population to cut: ratios, pass/fail tests, and the one check counting recalculated assignments
# (TASKRSRC rows are neither activities nor relationships, the two things the Audit page lists as removed).
NO_FUNNEL = {"int_03_assignments_recalculated"}


@pytest.mark.parametrize("standard_id", sorted(builtin_standards()))
def test_funnel_ends_on_the_denominator_and_removes_the_excluded(store, standard_id):
    """start - every step's removals = denominator, for every metric of the four standards; for P6 the rows
    removed are the Audit page's Excluded tab."""
    from xerscope.analysis import AnalysisContext, Baseline, run_standard
    from xerscope.analysis.audit import split

    for snapshot in store:
        context = AnalysisContext(snapshot, store, Baseline.from_snapshot(store.first))
        for result in run_standard(builtin_standards()[standard_id], context):
            metric_id = result.metric.id
            if result.funnel is None:
                assert result.denominator is None or result.metric.rule in NO_FUNNEL, metric_id
                continue
            funnel = result.funnel
            left = funnel.start - sum(len(step.removed) for step in funnel.steps)
            assert left == result.denominator == (funnel.steps[-1].left if funnel.steps else funnel.start), metric_id
            assert len(funnel.rows) == left, metric_id
            if standard_id != "P6":
                continue
            sets = split(result, snapshot)
            if sets.excluded is not None and metric_id != "P6-13":
                assert sum(len(step.removed) for step in funnel.steps) == len(sets.excluded), metric_id
