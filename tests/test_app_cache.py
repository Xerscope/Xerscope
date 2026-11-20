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
from xerscope.analysis import baseline as analysis_baseline
from xerscope.analysis.checks import run_metric
from xerscope.app import baselines, diagnostic, loading, session, state
from xerscope.app.state import BL_EACH, BL_PLANNED
from xerscope.store import SnapshotStore

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
BEI = builtin_standards()["P6"]["P6-13"]  # reads the baseline
HIGH_DURATION = builtin_standards()["DCMA"]["DCMA-08"]  # reads the baseline, has a parameter


@pytest.fixture
def runs(monkeypatch):
    """Every metric the app computes: (standard, metric id, file)."""
    calls = []
    original = baselines.run_metric

    def counting(metric, context):
        calls.append((metric.standard, metric.id, context.snapshot.source))
        return original(metric, context)

    monkeypatch.setattr(baselines, "run_metric", counting)
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
# not the EV basis: test_metric_result_is_not_run_again_for_another_ev_basis


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


def test_metric_result_is_not_run_again_for_another_ev_basis(store, runs):
    """No check reads what the EV basis sets (see the test below): the key leaves it out."""
    at = _metric_app(store, Baseline.from_snapshot(store.first, "budgeted_planned"))
    at.run()
    at.session_state["ev_basis"] = "at_completion_current"
    at.session_state["baseline"] = Baseline.from_snapshot(store.first, "at_completion_current")
    at.run()
    assert not at.exception and len(runs) == 1


BEI_FROM_BASELINE = dataclasses.replace(BEI, rule="bei", params={"due_from": "baseline"}, standard="CUSTOM")


@pytest.mark.parametrize("planned", [False, True])
def test_every_check_gives_the_same_result_whatever_the_ev_basis(store, planned):
    """What lets metric_result's key leave the EV basis out: every metric of every built-in standard,
    and the BEI counted in the baseline (its checked rows came from the baseline's frame), gives the
    same result, rows included, on the three bases."""
    metrics = [m for standard in builtin_standards().values() for m in standard.metrics] + [BEI_FROM_BASELINE]
    snapshot = store.latest

    def results(basis):
        baseline = Baseline.planned(snapshot, basis) if planned else Baseline.from_snapshot(store.first, basis)
        return [run_metric(metric, AnalysisContext(snapshot, store, baseline)) for metric in metrics]

    reference = results("budgeted_planned")
    assert any(r.metric is BEI_FROM_BASELINE and r.checked is not None and len(r.checked) for r in reference)
    for basis in ("budgeted_current", "at_completion_current"):
        for got, expected in zip(results(basis), reference, strict=True):
            same_result(got, expected)


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


def test_audit_computes_a_check_with_other_settings_once(app, store, monkeypatch):
    """P6-04 audited with the target < 3% instead of < 5%: computed when the target is typed, not
    again when the page is redrawn for the rows a step removed. What is kept is what a fresh
    calculation gives."""
    from xerscope.analysis import checks

    audited_runs = []
    original = checks.run_metric

    def counting(metric, context):
        if (metric.id, metric.threshold_label) == ("P6-04", "< 3%"):
            audited_runs.append(context.snapshot.source)
        return original(metric, context)

    monkeypatch.setattr(checks, "run_metric", counting)  # the name the Audit page imports
    monkeypatch.setattr(baselines, "run_metric", counting)  # the name the session's cache calls
    app.switch_page("views/audit.py").run()
    app.get("button_group")[0].set_value("P6").run()
    app.selectbox(key="audit_check:P6").set_value("P6-04").run()
    app.text_input(key="audit:P6:P6-04:target").set_value("< 3%").run()
    app.selectbox(key="funnel_step:P6-04").set_value("not milestone").run()
    assert not app.exception
    assert audited_runs == [store.latest.source]
    kept = [result for result in _cached_metrics(app).values() if result.metric.threshold_label == "< 3%"]
    assert len(kept) == 1
    same_result(kept[0], _fresh(app, store, kept[0].metric, store.latest.source))


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


# --- what the EV basis and the baseline change on the pages ------------------------------------------


def test_another_ev_basis_reruns_no_check_and_the_sets_stay_those_of_a_fresh_calculation(app, store, runs, downloads):
    from xerscope.analysis.audit import sets_long
    from xerscope.export import csv_bytes

    app.sidebar.toggle(key="anon_exports").set_value(False).run()
    app.switch_page("views/health.py").run()
    app.button(key="sets_build").click().run()
    computed = len(runs)
    baseline_box(app, "ev_basis").set_value("at_completion_current")
    app.button(key="files_done").click().run()
    app.switch_page("views/health.py").run()
    assert not app.exception and len(runs) == computed
    # the sets built before the change are still offered: they are those of the new basis
    p6 = builtin_standards()["P6"]
    baseline = Baseline.from_snapshot(store.first, "at_completion_current")
    fresh = [run_metric(metric, AnalysisContext(store.latest, store, baseline)) for metric in p6.metrics]
    expected = csv_bytes(sets_long(fresh, store.latest))
    assert _download(app, downloads, "All sets (CSV)") == expected


def test_another_baseline_withdraws_the_sets_and_the_diagnostic_built_before(app, store):
    app.sidebar.toggle(key="anon_exports").set_value(False).run()
    app.switch_page("views/health.py").run()
    app.button(key="sets_build").click().run()
    app.switch_page("views/debug.py").run()
    app.button(key="debug_build").click().run()
    assert _offered(app, "Download diagnostic (.zip)")
    baseline_box(app).set_value(store.labels[1])
    app.button(key="files_done").click().run()
    assert not _offered(app, "Download diagnostic (.zip)")
    app.switch_page("views/health.py").run()
    assert not app.exception and not _offered(app, "All sets (CSV)")


def test_another_ev_basis_withdraws_the_diagnostic_built_before(app):
    """The diagnostic's planned value check (block 9) follows the EV basis."""
    app.switch_page("views/debug.py").run()
    app.sidebar.toggle(key="anon_exports").set_value(False).run()
    app.button(key="debug_build").click().run()
    assert _offered(app, "Download diagnostic (.zip)")
    baseline_box(app, "ev_basis").set_value("at_completion_current")
    app.button(key="files_done").click().run()
    assert not app.exception and not _offered(app, "Download diagnostic (.zip)")


@pytest.mark.parametrize("page", ["ppc", "changelog", "export"])
def test_pages_that_read_no_baseline_are_not_recomputed_for_another(app, store, page):
    app.switch_page(f"views/{page}.py").run()

    def entries():
        # the sidebar's renumbered notice follows the baseline on every page; so does the progress of the
        # activities, which Percent plan complete measures against it
        return {key for key in app.session_state["_memo"] if key[-1] != "renumbered" and "ppc_progress" not in key}

    before = entries()
    assert before
    baseline_box(app).set_value(store.labels[1])
    app.button(key="files_done").click().run()
    app.switch_page(f"views/{page}.py").run()
    assert not app.exception and entries() == before


def test_ppc_reads_the_week_once_and_again_for_the_other_reading_of_late_commitments(app, store, monkeypatch):
    """The week's milestone commitments and unplanned work are computed once however often the page
    is drawn; unticking "Include commitments late at W-1" recomputes the commitments, which read
    it, and not the unplanned work, which does not. What is kept is what a fresh calculation gives."""
    from xerscope.analysis import progress

    calls = Counter()

    def counting(name):
        original = getattr(progress, name)

        def counted(*arguments):
            calls[name] += 1
            return original(*arguments)

        monkeypatch.setattr(progress, name, counted)
        return original

    milestones_of, unplanned_of = counting("committed_milestones"), counting("unplanned_work")
    app.switch_page("views/ppc.py").run()
    app.number_input[0].set_value(70).run()
    assert not app.exception
    assert calls == {"committed_milestones": 1, "unplanned_work": 1}
    app.checkbox(key="ppc_overdue").set_value(False).run()
    assert not app.exception
    assert calls == {"committed_milestones": 2, "unplanned_work": 1}
    previous, current = store[len(store) - 2], store[len(store) - 1]
    kept = {key[-3:]: value for key, value in app.session_state["_memo"].items() if key[-3] == "ppc_milestones"}
    assert sorted(key[-1] for key in kept) == [False, True]
    for (_, _, include_overdue), value in kept.items():
        pd.testing.assert_frame_equal(value, milestones_of(previous, current, include_overdue))
    unplanned = [value for key, value in app.session_state["_memo"].items() if key[-2] == "ppc_unplanned"]
    assert len(unplanned) == 1
    pd.testing.assert_frame_equal(unplanned[0], unplanned_of(previous, current))


def _offered(at, label: str) -> bool:
    return any(b.proto.label == label for b in at.get("download_button"))


@pytest.fixture
def downloads(monkeypatch):
    """Every file the app hands to a download button, by its media id."""
    from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage

    saved: dict[str, bytes] = {}
    real = MemoryMediaFileStorage.load_and_get_id

    def keep(self, path_or_data, mimetype, kind, filename=None):
        file_id = real(self, path_or_data, mimetype, kind, filename)
        saved[file_id] = self._files_by_id[file_id].content
        return file_id

    monkeypatch.setattr(MemoryMediaFileStorage, "load_and_get_id", keep)
    return saved


def _download(at, downloads: dict[str, bytes], label: str) -> bytes:
    button = next(b for b in at.get("download_button") if b.proto.label == label)
    return downloads[button.proto.url.rsplit("/", 1)[-1].split(".")[0]]


# --- a folder's files, keyed on their content ------------------------------------------------------


def test_a_folder_file_replaced_under_the_same_name_and_time_is_read_again(sample_dir, tmp_path, monkeypatch):
    """A rerun with nothing changed reads no file; one replaced under the same name and modification
    time (its change time moves) is read, digested and parsed again, and only it."""
    import os
    import shutil

    week1, week2, week3 = sorted(sample_dir.glob("*.xer"))[:3]
    folder = tmp_path / "files"
    folder.mkdir()
    shutil.copy2(week1, folder / "a.xer")
    shutil.copy2(week2, folder / "b.xer")
    parsed = []
    original = baselines.load_snapshot

    def counting(data, *args, name=None, **kwargs):
        parsed.append(name)
        return original(data, *args, name=name, **kwargs)

    monkeypatch.setattr(baselines, "load_snapshot", counting)
    monkeypatch.setenv("XERSCOPE_DATA", str(folder))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = read_folder(AppTest.from_file(APP, default_timeout=300).run())
    at.switch_page("views/health.py").run()
    assert not at.exception
    before = {s.source: s.data_date for s in at.session_state["store"]}
    reads = []
    real_read = Path.read_bytes

    def counting_read(path):
        reads.append(path.name)
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", counting_read)
    at.run()
    assert sorted(parsed) == ["a.xer", "b.xer"]  # a rerun parses nothing
    assert reads == []  # nor reads or digests a file whose stat did not change

    stat = (folder / "b.xer").stat()
    (folder / "b.xer").write_bytes(week3.read_bytes())
    os.utime(folder / "b.xer", ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert (folder / "b.xer").stat().st_mtime_ns == stat.st_mtime_ns
    at.run()
    assert not at.exception
    assert sorted(parsed) == ["a.xer", "b.xer", "b.xer"]  # only the replaced file
    assert "a.xer" not in reads and "b.xer" in reads
    after = {s.source: s.data_date for s in at.session_state["store"]}
    assert after["a.xer"] == before["a.xer"] and after["b.xer"] != before["b.xer"]
    # Health's results now are those of the new content (its status date), from a fresh calculation
    computed = {(source, date) for _, source, date in _cached_metrics(at)}
    assert ("b.xer", str(after["b.xer"])) in computed


# --- the scores of Overview ------------------------------------------------------------------------


def _score_cards(at) -> dict[str, tuple[str, str]]:
    return {metric.label: (metric.value, metric.delta) for metric in at.metric if metric.label.endswith(" score")}


def _expected_scores(at, store) -> dict[str, tuple[str, str]]:
    from xerscope.analysis import standard_score

    baseline = Baseline.from_snapshot(store.first, at.session_state["ev_basis"])
    context = AnalysisContext(store.latest, store, baseline)
    scores = {
        sid: standard_score([run_metric(m, context) for m in s.metrics]) for sid, s in builtin_standards().items()
    }
    names = {sid: s.name for sid, s in builtin_standards().items()}
    return {f"{names[sid]} score": (score.value, score.detail) for sid, score in scores.items()}


def _health_score(at, standard_id: str) -> tuple[str, str]:
    at.get("button_group")[0].set_value(standard_id).run()
    assert not at.exception
    name = builtin_standards()[standard_id].name
    (card,) = [(m.value, m.delta) for m in at.metric if m.label == f"{name} score"]
    return card


def test_overview_scores_wait_for_the_button_then_schedule_health_reads_them(app, store, runs):
    """Opening Overview runs no check; the button runs each metric of the four built-in standards
    once on the latest update; the cards equal the score of a fresh calculation and Schedule health's
    card, which computes nothing more."""
    app.switch_page("views/overview.py").run()
    assert not app.exception and runs == []
    assert _score_cards(app) == {f"{s.name} score": ("–", "not computed yet") for s in builtin_standards().values()}

    app.button(key="overview_scores").click().run()
    assert not app.exception
    expected_runs = [(m.standard, m.id, store.latest.source) for s in builtin_standards().values() for m in s.metrics]
    assert Counter(runs) == Counter(expected_runs)  # each metric once
    shown = _score_cards(app)
    assert shown == _expected_scores(app, store)
    app.run()  # the next rerun: nothing left to compute
    assert not [b for b in app.button if b.key == "overview_scores"] and _score_cards(app) == shown

    app.switch_page("views/health.py").run()
    for standard_id in builtin_standards():
        name = builtin_standards()[standard_id].name
        assert _health_score(app, standard_id) == shown[f"{name} score"], standard_id
    assert Counter(runs) == Counter(expected_runs)  # Schedule health computed nothing more


def test_overview_shows_the_scores_schedule_health_computed_without_running_a_check(app, store, runs):
    app.switch_page("views/health.py").run()
    health = {f"{s.name} score": _health_score(app, sid) for sid, s in builtin_standards().items()}
    computed = len(runs)
    app.switch_page("views/overview.py").run()
    assert not app.exception and len(runs) == computed
    assert not [b for b in app.button if b.key == "overview_scores"]
    assert _score_cards(app) == health == _expected_scores(app, store)


# --- the GUID link option -------------------------------------------------------------------------


def _missed_tasks_script():
    import streamlit as st

    from xerscope.app.state import data_identity, metric_result

    store = st.session_state["store"]
    st.session_state["identity"] = data_identity(ev_basis=False)  # the score job's identity starts with it
    st.session_state["denominator"] = metric_result(st.session_state["metric"], store.latest, store).denominator


def test_ticking_the_guid_link_gives_the_checks_of_the_linked_baseline():
    """Baseline A (done by 03-06) and B; the update renumbers A as A2 (same GUID). DCMA-11 counts the
    tasks due in the baseline that are in the update: unlinked, A is deleted (1: B); linked, A2 takes
    A's baseline row (2). The cached result follows the option, as a fresh calculation does."""
    from xerkit import snap, todo

    from xerscope.analysis.baseline import relinked

    week = {"target_start_date": "2026-03-02 08:00", "target_end_date": "2026-03-06 17:00"}
    finished = {**week, "act_start_date": "2026-03-02 08:00", "act_end_date": "2026-03-06 17:00"}
    finished["status_code"] = "TK_Complete"
    first = snap([todo("A", guid="g1", **finished), todo("B", guid="g2", **week)], data_date="2026-03-02 08:00")
    update = snap([todo("A2", guid="g1", **finished), todo("B", guid="g2", **week)], data_date="2026-03-16 08:00")
    first, update = dataclasses.replace(first, source="a.xer"), dataclasses.replace(update, source="b.xer")
    store = SnapshotStore([first, update])
    missed = builtin_standards()["DCMA"]["DCMA-11"]
    baseline = Baseline.from_snapshot(first)
    at = AppTest.from_function(_missed_tasks_script, default_timeout=120)
    at.session_state["store"] = store
    at.session_state["signature"] = ("folder", "renumbered")
    at.session_state["metric"] = missed
    at.session_state["ev_basis"] = "budgeted_planned"
    at.session_state["baseline"] = baseline
    at.session_state["guid_link"] = False
    at.run()
    unlinked = at.session_state["identity"]
    assert not at.exception and at.session_state["denominator"] == 1
    at.session_state["guid_link"] = True
    at.run()
    fresh = run_metric(missed, AnalysisContext(update, store, relinked(baseline, update)))
    assert not at.exception and at.session_state["denominator"] == fresh.denominator == 2
    assert at.session_state["identity"] != unlinked


# --- no baseline built again by a rerun -----------------------------------------------------------------


@pytest.fixture
def builds(monkeypatch):
    """How often the app builds a baseline, looks tasks up by GUID or lists the baseline folder."""
    counts = Counter()

    def counting(owner, name, label):
        original = getattr(owner, name)

        def counted(*arguments, **keywords):
            counts[label] += 1
            return original(*arguments, **keywords)

        monkeypatch.setattr(owner, name, counted)

    counting(Baseline, "from_snapshot", "Baseline.from_snapshot")
    counting(Baseline, "planned", "Baseline.planned")
    for module in (analysis_baseline, baselines, diagnostic):
        counting(module, "renumbered", "renumbered")
    counting(baselines, "pmxml_files", "folder listings")
    return counts


def _rebuilt_by_a_rerun(at, builds, page: str) -> dict[str, int]:
    at.switch_page(f"views/{page}.py").run()
    builds.clear()
    at.run()
    assert not at.exception
    return dict(builds)


@pytest.mark.parametrize("page", ["overview", "gantt", "health", "debug", "ppc", "earned_value"])
@pytest.mark.parametrize("choice", ["loaded update", "planned dates, renumbered tasks linked"])
def test_a_rerun_with_nothing_changed_builds_no_baseline_and_lists_the_folder_once(app, builds, page, choice):
    if choice != "loaded update":
        app.session_state["bl_choice"] = BL_PLANNED
        app.session_state["guid_link"] = True
        app.run()
    assert _rebuilt_by_a_rerun(app, builds, page) == {"folder listings": 1}


def test_a_check_asks_for_the_baseline_only_when_it_is_computed(app, builds):
    """Health reads twenty cached results: none builds the context they were computed from."""
    app.session_state["bl_choice"] = BL_PLANNED
    app.session_state["guid_link"] = True
    app.run()
    app.switch_page("views/health.py").run()
    builds.clear()
    app.toggle(key="health_expand").set_value(True).run()
    assert not app.exception
    assert "Baseline.planned" not in builds and "renumbered" not in builds


def test_another_baseline_is_built_once_and_the_pages_follow_it(app, builds, store):
    app.switch_page("views/health.py").run()
    before = app.session_state["_baselines_for"]
    builds.clear()
    app.session_state["bl_choice"] = store.labels[2]
    app.run()
    app.run()
    assert not app.exception
    assert builds["Baseline.from_snapshot"] == 1  # the sidebar's, shared by the two runs
    assert app.session_state["_baselines_for"] != before
    (baseline,) = {value.label for key, value in app.session_state["_baselines_for"][1].items() if key[1] is False}
    assert baseline == Baseline.from_snapshot(store.by_label(store.labels[2]), "budgeted_planned").label


def _upload_script():
    import types

    import streamlit as st

    from xerscope.app.session import _apply_drafts, _digest

    data = st.session_state["contents"]
    st.session_state["bl_upload"] = types.SimpleNamespace(name="bl.xer", getvalue=lambda: data)
    _apply_drafts()
    st.session_state["held"] = _digest(st.session_state["bl_file"][1])
    st.session_state["held_again"] = _digest(st.session_state["bl_file"][1])
    st.session_state["other"] = _digest(b"another file")


def test_the_digest_of_the_uploaded_baseline_is_computed_once_when_it_is_held(monkeypatch):
    import hashlib

    hashed = []
    real = hashlib.sha256
    monkeypatch.setattr(session.hashlib, "sha256", lambda data=b"": hashed.append(data) or real(data))
    at = AppTest.from_function(_upload_script, default_timeout=120)
    at.session_state["contents"] = b"the baseline"
    at.run()
    assert not at.exception
    assert at.session_state["held"] == at.session_state["held_again"] == real(b"the baseline").hexdigest()
    assert at.session_state["other"] == real(b"another file").hexdigest()
    assert hashed == [b"the baseline", b"another file"]  # the baseline once, not again for each call


# --- the files a series change leaves as they were are not read again -----------------------------------


def test_a_series_change_reads_only_the_files_the_session_has_not_parsed(sample_dir, monkeypatch):
    from conftest import file_boxes, files_done, open_files

    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_SYNC_LOAD", raising=False)
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "1")
    asked = []
    original = loading.read_updates

    def recording(items, *arguments, **keywords):
        asked.append([name for name, _ in items])
        return original(items, *arguments, **keywords)

    monkeypatch.setattr(loading, "read_updates", recording)

    def join_and_collect(at):
        job = at.session_state["_load_job"]  # None when the run already collected a job with nothing to read
        if job is not None:
            job.thread.join(timeout=300)
        return at.run()

    at = join_and_collect(read_folder(AppTest.from_file(APP, default_timeout=300).run()))
    names = sorted(path.name for path in sample_dir.glob("*.xer"))
    assert sorted(asked[0]) == names and len(at.session_state["store"]) == len(names)
    open_files(at)
    file_boxes(at)[-1].uncheck()  # the files left are all parsed
    at = join_and_collect(files_done(at))
    assert asked[1] == [] and len(at.session_state["store"]) == len(names) - 1
    open_files(at)
    file_boxes(at)[-1].check()  # the one dropped from the cache when the series was read again
    at = join_and_collect(files_done(at))
    assert [sorted(read) for read in asked[2:]] == [[names[-1]]]
    assert not at.exception and len(at.session_state["store"]) == len(names)
