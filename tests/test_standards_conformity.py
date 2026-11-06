"""Every built-in metric says the same thing in four places: its TOML entry, its rule's docstring, the funnel
its rule builds on the demo series, and docs/standards.md. A change in one must be made in the others."""

import re
from pathlib import Path

import pytest

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_standard
from xerscope.analysis.populations import EXCLUSIONS
from xerscope.analysis.rules import RULES

DOCS = Path(__file__).parents[1] / "docs" / "standards.md"
NO_POPULATION = {"DCMA-12", "DCMA-13", "INT-03"}  # pass/fail, ratio and assignment checks: no activity funnel
# Exclusions a docstring states that the rule applies inside its predicate (or the CPM does), not as a funnel step
NARRATIVE = {
    "INT-04": {"tasks downstream of a loop", "level of effort (its links are not part of the network)"},
    "INT-07": {"start constraints of started tasks"},
}
LABEL_TO_KEY = {exclusion.label: key for key, exclusion in EXCLUSIONS.items()}


def _results(store):
    baseline = Baseline.from_snapshot(store.first)
    context = AnalysisContext(store[-1], store, baseline=baseline)
    standards = builtin_standards()
    return [result for sid in ("P6", "DCMA", "INTEGRITY") for result in run_standard(standards[sid], context)]


def _docs_row(docs: str, metric_id: str) -> str:
    key = metric_id if not metric_id.startswith("DCMA-") else str(int(metric_id.split("-")[1]))
    return next((line for line in docs.splitlines() if line.startswith(f"| {key} |")), "")


@pytest.fixture(scope="module")
def results(store):
    return _results(store)


def test_every_metric_runs_and_has_a_row_in_the_docs(results):
    docs = DOCS.read_text(encoding="utf-8")
    assert [result.metric.id for result in results if result.status == "error"] == []
    assert [result.metric.id for result in results if not _docs_row(docs, result.metric.id)] == []


def test_docstring_exclusions_are_the_funnel_steps(results):
    """The "Excludes:" line of a rule names exactly the EXCLUSIONS its funnel applies (same words)."""
    for result in results:
        metric_id = result.metric.id
        if result.funnel is None:
            assert metric_id in NO_POPULATION or result.status in ("n/a", "info"), metric_id
            continue
        # a link funnel labels its steps "successor not complete": the activity exclusion, applied to the successor
        step_labels = [step.label.removeprefix("successor ") for step in result.funnel.steps]
        exclusion_keys = [LABEL_TO_KEY[label] for label in step_labels if label in LABEL_TO_KEY]
        population_lines = RULES[result.metric.rule].population
        excludes_line = next(
            (line for line in population_lines if line.startswith("Excludes:") or "successor is excluded:" in line), ""
        )
        if not exclusion_keys and not excludes_line:
            continue
        assert excludes_line, (
            f"{metric_id}: the funnel excludes {exclusion_keys} but the docstring has no Excludes line"
        )
        docstring_excludes = {part.strip().rstrip(".") for part in excludes_line.split(":", 1)[1].split(",")}
        funnel_excludes = {EXCLUSIONS[key].text for key in exclusion_keys}
        assert funnel_excludes <= docstring_excludes, (
            f"{metric_id}: docstring {sorted(docstring_excludes)} vs funnel {sorted(funnel_excludes)}"
        )
        # items stated in the rule's own words ("no lead", "successor end not an actual date") have a step each
        unmatched_in_docstring = docstring_excludes - funnel_excludes - NARRATIVE.get(metric_id, set())
        rule_worded_steps = [label for label in step_labels if label not in LABEL_TO_KEY and label != "into a task"]
        assert len(unmatched_in_docstring) <= len(rule_worded_steps), (
            f"{metric_id}: docstring says more than the funnel: {unmatched_in_docstring} vs {rule_worded_steps}"
        )


def test_docs_targets_match_the_toml(results):
    """The target column of the docs tables carries the TOML target (0 and <= 0 read the same)."""
    docs = DOCS.read_text(encoding="utf-8")

    def norm(text: str) -> str:
        text = re.sub(r"\s+", "", text.replace("≤", "<=").replace("≥", ">="))
        return text.replace("<=0%", "0%").replace("<=0|", "0|").replace("<=0", "0") if "<=0" in text else text

    for result in results:
        toml_target, docs_row = result.metric.threshold_label, _docs_row(docs, result.metric.id)
        if (
            not toml_target or "`p6.toml`" in docs_row
        ):  # checks the P6 dialog has no default for: the TOML is the source
            continue
        assert norm(toml_target) in norm(docs_row), (
            f"{result.metric.id}: TOML target {toml_target!r} not in docs row {docs_row!r}"
        )
