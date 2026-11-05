"""The app's per-session caches: one computation per set of inputs, a new one when any input
changes, and values that no page alters (the next reader gets what a fresh calculation gives)."""

import dataclasses
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest
from conftest import baseline_box, read_folder
from streamlit.testing.v1 import AppTest

import xerscope
from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, health_history
from xerscope.analysis.checks import run_metric
from xerscope.app import state
from xerscope.app.state import BL_EACH, BL_PLANNED
from xerscope.store import SnapshotStore

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
BEI = builtin_standards()["P6"]["P6-13"]  # reads the baseline
HIGH_DURATION = builtin_standards()["DCMA"]["DCMA-08"]  # reads the baseline, has a parameter


@pytest.fixture
def runs(monkeypatch):
    """Every metric the app computes: (standard, metric id, file)."""
    calls = []
    original = state.run_metric

    def counting(metric, context):
        calls.append((metric.standard, metric.id, context.snapshot.source))
        return original(metric, context)

    monkeypatch.setattr(state, "run_metric", counting)
    return calls


def same_result(cached, fresh) -> None:
    for name in ("metric", "status", "value", "numerator", "denominator", "note", "baseline"):
        assert getattr(cached, name) == getattr(fresh, name), name
    for name in ("flagged", "checked", "counted"):
        got, expected = getattr(cached, name), getattr(fresh, name)
        assert (got is None) == (expected is None), name
        if got is not None:
            pd.testing.assert_frame_equal(got, expected, obj=name)
    assert (cached.funnel is None) == (fresh.funnel is None)
    if cached.funnel is not None:
        pd.testing.assert_frame_equal(cached.funnel.rows, fresh.funnel.rows)
        assert [(s.label, s.source, s.left) for s in cached.funnel.steps] == [
            (s.label, s.source, s.left) for s in fresh.funnel.steps
        ]
        for got, expected in zip(cached.funnel.steps, fresh.funnel.steps, strict=True):
            pd.testing.assert_frame_equal(got.removed, expected.removed)


# --- metric_result: the key, input by input ----------------------------------------------------


def _metric_script():
    import streamlit as st

    from xerscope.app.state import metric_result

    store = st.session_state["store"]
    metric_result(st.session_state["metric"], store.by_label(st.session_state["update"]), store)


def _metric_app(store, baseline, basis="budgeted_planned"):
    at = AppTest.from_function(_metric_script, default_timeout=120)
    at.session_state["store"] = store
    at.session_state["signature"] = ("folder", "probe")
    at.session_state["metric"] = BEI
    at.session_state["update"] = store.labels[-1]
    at.session_state["ev_basis"] = basis
    at.session_state["baseline"] = baseline
    return at


def _change(at, store, change):
    first, second = store.labels[:2]
    session = at.session_state
    if change == "files":
        session["signature"] = ("folder", "other")
    elif change == "project":
        latest = store.latest
        session["store"] = SnapshotStore([*list(store)[:-1], dataclasses.replace(latest, project_id="other")])
    elif change == "baseline_update":
        session["baseline"] = Baseline.from_snapshot(store.by_label(second), "budgeted_planned")
    elif change == "baseline_digest":  # same name, other bytes
        session["baseline_digest"] = "b" * 64
    elif change == "baseline_none":
        session["baseline"] = None
    elif change == "baseline_planned":
        session["baseline"] = BL_PLANNED
    elif change == "threshold":
        session["metric"] = dataclasses.replace(BEI, threshold=0.5)
    elif change == "params":
        session["metric"] = dataclasses.replace(HIGH_DURATION, params={"limit_days": 20})
    elif change == "standard":
        session["metric"] = dataclasses.replace(BEI, standard="CUSTOM")
    elif change == "update":
        session["update"] = first


INPUTS = [
    "files",
    "project",
    "baseline_update",
    "baseline_digest",
    "baseline_none",
    "baseline_planned",
    "threshold",
    "params",
    "standard",
    "update",
]


@pytest.mark.parametrize("change", INPUTS)
def test_metric_result_runs_once_then_again_for_any_other_input(store, runs, change):
    at = _metric_app(store, Baseline.from_snapshot(store.first, "budgeted_planned"))
    at.session_state["baseline_digest"] = "a" * 64
    if change == "params":
        at.session_state["metric"] = HIGH_DURATION
    at.run()
    at.run()
    assert not at.exception and len(runs) == 1  # two reads, one calculation
    _change(at, store, change)
    at.run()
    assert not at.exception and len(runs) == 2


def test_metric_result_runs_again_for_another_fallback(store, runs):
    at = _metric_app(store, BL_EACH)
    at.session_state["fallback_choice"] = BL_PLANNED
    at.run()
    at.run()
    assert len(runs) == 1
    at.session_state["fallback_choice"] = store.labels[0]
    at.run()
    assert not at.exception and len(runs) == 2


def test_metric_result_runs_again_for_another_ev_basis(store, runs):
    at = _metric_app(store, Baseline.from_snapshot(store.first, "budgeted_planned"))
    at.run()
    at.session_state["ev_basis"] = "at_completion_current"
    at.session_state["baseline"] = Baseline.from_snapshot(store.first, "at_completion_current")
    at.run()
    assert not at.exception and len(runs) == 2


# --- the memo's bound ---------------------------------------------------------------------------


def _fill_script():
    import streamlit as st

    from xerscope.app.state import MEMO_SIZE, memo

    runs = st.session_state.setdefault("runs", [])
    memo(("entry", 0), lambda: runs.append(0))
    for index in range(1, MEMO_SIZE + 1):
        memo(("entry", index), lambda index=index: runs.append(index))
        memo(("entry", 0), lambda: runs.append(0))  # read again: kept as recently used


def test_memo_drops_the_least_recently_used_entry_past_its_size():
    at = AppTest.from_function(_fill_script, default_timeout=120).run()
    assert not at.exception
    cache = at.session_state["_memo"]
    assert len(cache) == state.MEMO_SIZE
    kept = {key[-1] for key in cache}
    assert 0 in kept and 1 not in kept  # entry 1 was the oldest unread one
    assert at.session_state["runs"].count(0) == 1


# --- one result for Health, Audit and Earned value ----------------------------------------------


@pytest.fixture
def app(sample_dir, store, monkeypatch):
    """The sample series against its first update as baseline (a fresh calculation can rebuild it)."""
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = read_folder(AppTest.from_file(APP, default_timeout=300).run())
    baseline_box(at).set_value(store.labels[0])
    at.button(key="files_done").click().run()
    assert not at.exception
    return at


def _fresh(at, store, metric, source):
    snapshot = next(s for s in store if s.source == source)
    baseline = Baseline.from_snapshot(store.first, at.session_state["ev_basis"])
    return run_metric(metric, AnalysisContext(snapshot, store, baseline))


def _cached_metrics(at):
    return {key[-3:]: value for key, value in at.session_state["_memo"].items() if "metric" in key}


def test_health_audit_and_earned_value_compute_each_result_once(app, store, runs):
    app.switch_page("views/health.py").run()
    app.toggle(key="health_expand").set_value(True).run()
    app.switch_page("views/audit.py").run()
    app.get("button_group")[0].set_value("P6").run()
    app.selectbox(key="audit_check:P6").set_value("P6-13").run()
    app.switch_page("views/earned_value.py").run()
    app.switch_page("views/health.py").run()
    assert not app.exception
    assert runs and max(Counter(runs).values()) == 1
    p6 = builtin_standards()["P6"]
    assert {(m.id, store.latest.source) for m in p6.metrics} <= {(i, f) for _, i, f in runs}
    # Earned value reads the BEI of every update but keeps only what Health or Audit computed
    kept_files = {source for _, source, _ in _cached_metrics(app)}
    assert kept_files == {store.latest.source}


def test_cached_results_are_left_as_a_fresh_calculation_gives_them(app, store):
    """Pages read the cached results (lists, sets, exports, explanations): none may alter them."""
    app.switch_page("views/health.py").run()
    app.toggle(key="health_expand").set_value(True).run()
    sets = next(s for s in app.selectbox if s.key and s.key.startswith("health_sets_check:"))
    for metric_id in sets.options:
        app.selectbox(key=sets.key).set_value(metric_id).run()
    app.button(key="sets_build").click().run()
    app.switch_page("views/audit.py").run()
    app.get("button_group")[0].set_value("P6").run()
    for metric_id in ("P6-13", "P6-01"):
        app.selectbox(key="audit_check:P6").set_value(metric_id).run()
    app.switch_page("views/earned_value.py").run()
    assert not app.exception
    cached = _cached_metrics(app)
    assert len(cached) >= len(builtin_standards()["P6"].metrics)
    for (metric_repr, source, _), result in cached.items():
        assert repr(result.metric) == metric_repr
        same_result(result, _fresh(app, store, result.metric, source))


# --- the Health trend -----------------------------------------------------------------------------


def _history_keys(at):
    return [key for key in at.session_state["_memo"] if "health_history" in key]


def test_health_trend_is_computed_on_request_once_and_keeps_numbers_only(app, store, runs):
    app.switch_page("views/health.py").run()
    assert not _history_keys(app) and app.button(key="health_trend_btn")
    before = len(runs)
    app.button(key="health_trend_btn").click().run()
    assert not app.exception and len(_history_keys(app)) == 1
    standard = builtin_standards()["P6"]
    # the latest update's results came from the cache; the others were computed, not kept
    assert len(runs) - before == len(standard.metrics) * (len(store) - 1)
    assert {source for _, source, _ in _cached_metrics(app)} == {store.latest.source}
    app.selectbox(key="health_trend_metric").select_index(1).run()
    assert not app.exception and len(runs) - before == len(standard.metrics) * (len(store) - 1)
    assert not [b for b in app.button if b.key == "health_trend_btn"]
    history = app.session_state["_memo"][_history_keys(app)[0]]
    baseline = Baseline.from_snapshot(store.first, app.session_state["ev_basis"])
    pd.testing.assert_frame_equal(history, health_history(store, standard, baseline))
