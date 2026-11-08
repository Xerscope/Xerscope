"""Tasks absent from the baseline: one definition (``Baseline.unbaselined``), the same count on every
surface that shows it (Health caption, Earned value caption and KPI, sidebar match rate, Debug block 5)
and in DECM 06A501a while every baseline task has its dates."""

import ast
from pathlib import Path

import pytest
from conftest import baseline_box, read_folder
from rulekit import run
from streamlit.testing.v1 import AppTest
from xerkit import snap, todo

import xerscope
from xerscope.analysis import Baseline, builtin_standards
from xerscope.analysis.evm import ev_point
from xerscope.app.diagnostic import baseline_table

DECM = builtin_standards()["DECM"]
APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")


def test_one_definition_for_every_surface():
    """Baseline A, B, C; the update A, B, D, E: D and E are not in the baseline."""
    baseline = Baseline.from_snapshot(snap([todo("A"), todo("B"), todo("C")]))
    update = snap([todo("A"), todo("B"), todo("D"), todo("E")])
    assert baseline.unbaselined(update) == ["D", "E"]
    assert ev_point(update, baseline).unbaselined == ["D", "E"]
    assert baseline_table(update, baseline)[["matched", "activities"]].iloc[0].tolist() == [2, 4]
    assert run(DECM, "06A501a", update, baseline).numerator == 2


def test_06a501a_also_counts_a_baseline_task_without_dates():
    """DECM 06A501a is "missing a baseline start or finish": B is in the baseline without dates, so
    it counts there and not among the tasks absent from the baseline."""
    baseline = Baseline.from_snapshot(snap([todo("A"), todo("B", early_start_date="", early_end_date="")]))
    update = snap([todo("A"), todo("B"), todo("D")])
    assert baseline.unbaselined(update) == ["D"]
    assert run(DECM, "06A501a", update, baseline).numerator == 2


def test_no_surface_recomputes_the_set():
    """The set difference with ``baseline.frame.index`` is written once, in Baseline.unbaselined."""
    src = Path(xerscope.__file__).parent
    found = []
    for path in sorted([*src.joinpath("app").rglob("*.py"), src / "analysis" / "evm.py"]):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and ast.unparse(node).startswith("set(")
                and "frame.index" in ast.unparse(node)
            ):
                found.append(f"{path.name}:{node.lineno}")
            if (
                isinstance(node, ast.Call)
                and ast.unparse(node.func).endswith(".isin")
                and any(ast.unparse(arg) == "baseline.frame.index" for arg in node.args)
            ):
                found.append(f"{path.name}:{node.lineno}")
    # evm.compare_p6_export flags each row of the union of both sides: a per-row flag, not the count
    assert found == ["evm.py:398"], found


@pytest.fixture(scope="module")
def app(sample_dir):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("XERSCOPE_DATA", str(sample_dir))
        patch.delenv("XERSCOPE_BASELINE", raising=False)
        patch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
        yield read_folder(AppTest.from_file(APP, default_timeout=180).run())


def _captions(at) -> list[str]:
    return [caption.value for caption in at.caption]


def test_health_and_earned_value_name_the_same_tasks(app, store):
    """The demo series adds C3045 in week 4: against the first update, the latest update has it alone
    outside the baseline, and both pages say so."""
    baseline = Baseline.from_snapshot(store.first)
    expected = baseline.unbaselined(store.latest)
    assert expected == ["C3045"]
    baseline_box(app).set_value(store.labels[0])
    app.switch_page("views/health.py").run()
    assert not app.exception
    assert f"{len(expected)} tasks are not in the baseline: {', '.join(expected)}" in _captions(app)
    app.switch_page("views/earned_value.py").run()
    assert not app.exception
    shown = [text for text in _captions(app) if text.startswith("Not in the baseline")]
    assert shown and shown[0].endswith(", ".join(expected))
