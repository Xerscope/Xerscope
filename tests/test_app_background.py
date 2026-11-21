"""The two threads of the app: the series read on worker processes, and the Overview scores.
conftest sets XERSCOPE_SYNC_LOAD for every other test; here it is lifted and the thread joined before
the next run, which is what the sidebar's polling fragment does in a browser."""

import threading
import time
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from conftest import file_boxes, files_done, open_files, read_folder
from streamlit.testing.v1 import AppTest

import xerscope
from xerscope.analysis.checks import run_standard
from xerscope.app import cache
from xerscope.app.files_window import most_recent_first

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")


def _ok(at):
    assert not at.exception, [e.value for e in at.exception]


def _joined(at, key: str):
    job = at.session_state[key]
    assert job is not None and job.thread is not None
    job.thread.join(timeout=300)
    assert job.done
    return job


def test_the_pages_wait_for_the_whole_series_then_draw_once(sample_dir, monkeypatch):
    """No page is drawn on a partial series: they redrew on every file read and the default baseline
    moved with them. The pages show the reading, then the complete series, its first update the
    default baseline."""
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_SYNC_LOAD", raising=False)
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "2")  # the worker processes, not the in-thread fallback
    at = read_folder(AppTest.from_file(APP, default_timeout=300).run())
    _ok(at)
    assert at.session_state["store"] is None
    assert any(i.value.startswith("Reading 8 updates") for i in at.info)  # in place of the page
    job = _joined(at, "_load_job")
    assert len(job.results) == len(list(sample_dir.glob("*.xer")))
    at.run()
    _ok(at)
    assert len(at.session_state["store"]) == len(list(sample_dir.glob("*.xer")))
    assert at.session_state["_load_job"] is None and not at.get("progress")
    assert not any(i.value.startswith("Reading") for i in at.info)
    assert at.session_state["bl_choice"] == at.session_state["store"].labels[0]
    files_done(at)  # the window opened on its Baseline section: the pages wait for Done
    # the parse cache keeps the files of this series only
    assert {key[0] for key in at.session_state["_parsed"]} == {p.name for p in sample_dir.glob("*.xer")}
    # the Overview then computes the four scores in a thread and fills the cards as they come
    assert any(c.value.startswith("Computing the scores") for c in at.caption)
    _joined(at, "_score_job")
    at.run()
    _ok(at)
    cards = [m for m in at.metric if m.label.endswith(" score")]
    assert len(cards) == 4 and all(m.value.endswith("%") for m in cards)
    assert not any(c.value.startswith("Computing the scores") for c in at.caption)


def test_a_new_choice_of_files_stops_the_reading_and_forgets_the_previous_series(sample_dir, monkeypatch):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_SYNC_LOAD", raising=False)
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "1")
    at = read_folder(AppTest.from_file(APP, default_timeout=300).run())
    first_job = at.session_state["_load_job"]
    at.session_state["_memo"] = {("stale",): 1}
    open_files(at)  # a new choice while the first one is read: the first three files only
    for box in file_boxes(at)[3:]:
        box.uncheck()
    files_done(at)
    _ok(at)
    assert first_job.cancelled
    assert "_memo" not in at.session_state or ("stale",) not in at.session_state["_memo"]
    job = _joined(at, "_load_job")
    assert len(job.items) == 3


def test_most_recent_first_orders_by_status_date_unreadable_last(sample_dir):
    items = [(p.name, p.read_bytes()) for p in sorted(sample_dir.glob("*.xer"))]
    items.append(("broken.xer", b"not an xer"))
    ordered = [name for name, _ in most_recent_first(items)]
    dates = sorted((p.name for p in sample_dir.glob("*.xer")), reverse=True)
    assert ordered == [*dates, "broken.xer"]
    assert pd.Timestamp(dates[0][-14:-4]) > pd.Timestamp(dates[-1][-14:-4])


def _cards(at):
    return {m.label: (m.value, m.delta) for m in at.metric if m.label.endswith(" score")}


def test_a_standard_finished_while_the_overview_is_shown_fills_its_card_without_an_app_rerun(sample_dir, monkeypatch):
    """The score cards are a fragment that polls the job: a standard finishing between two polls
    fills its card, and the app is never asked to rerun (it was once per standard, each run drawing
    the whole page again). The cards then hold the values the "Compute scores" button gives."""
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "1")
    synchronous = read_folder(AppTest.from_file(APP, default_timeout=300).run())
    expected = _cards(synchronous.button(key="overview_scores").click().run())
    assert len(expected) == 4 and all(value.endswith("%") for value, _ in expected.values())

    monkeypatch.delenv("XERSCOPE_SYNC_LOAD", raising=False)
    gate = threading.Semaphore(0)  # one permit per standard allowed to finish

    def gated(standard, context, **options):
        gate.acquire()
        return run_standard(standard, context, **options)

    monkeypatch.setattr(cache, "run_standard", gated)
    real_score_job = cache.score_job

    def score_job(*args):
        # the page has collected what was in; one more standard finishes before the next poll
        job = real_score_job(*args)
        if len(job.results) < len(job.standards):
            before = len(job.results)
            gate.release()
            deadline = time.monotonic() + 300
            while len(job.results) == before and time.monotonic() < deadline:
                time.sleep(0.01)
        return job

    monkeypatch.setattr(cache, "score_job", score_job)
    at = read_folder(AppTest.from_file(APP, default_timeout=300).run())
    _joined(at, "_load_job")
    files_done(at.run())  # the window opened on its Baseline section once the series was read
    reruns = []
    real_rerun = st.rerun

    def rerun(*args, **kwargs):
        reruns.append(kwargs.get("scope", args[0] if args else "app"))
        real_rerun(*args, **kwargs)

    monkeypatch.setattr(st, "rerun", rerun)
    filled = [sum(value.endswith("%") for value, _ in _cards(at).values())]  # the run Done made: the first poll
    for _ in range(6):
        at.run()
        _ok(at)
        filled.append(sum(value.endswith("%") for value, _ in _cards(at).values()))
        if filled[-1] == 4:
            break
    assert reruns == []
    assert filled == [0, 1, 2, 3, 4]
    assert _cards(at) == expected


@pytest.mark.oracle("property")
def test_the_score_cards_stop_polling_once_every_score_is_shown(sample_dir, monkeypatch):
    """A fragment's timer only goes with a full run of the page. Once the four scores were shown the
    cards went on polling every second for as long as the Overview stayed open, each poll reading the
    63 checks from the cache. A poll that finds nothing missing asks for that full run, once: the
    page it draws no longer polls."""
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "1")
    monkeypatch.delenv("XERSCOPE_SYNC_LOAD", raising=False)
    at = read_folder(AppTest.from_file(APP, default_timeout=300).run())
    _joined(at, "_load_job")
    files_done(at.run())
    _joined(at, "_score_job")
    at.run()  # the poll that collects the four standards
    shown = _cards(at)
    assert len(shown) == 4 and all(value.endswith("%") for value, _ in shown.values())

    # the next poll, as the browser's timer makes it: the page had found a score missing when it
    # armed the fragment, the fragment now finds them all
    page_saw_one_missing = []
    held = cache.standard_results_held

    def held_after_the_page_looked(standard, snapshot):
        if not page_saw_one_missing:
            page_saw_one_missing.append(standard.name)
            return None
        return held(standard, snapshot)

    monkeypatch.setattr(cache, "standard_results_held", held_after_the_page_looked)
    reruns = []
    real_rerun = st.rerun

    def rerun(*args, **kwargs):
        reruns.append(kwargs.get("scope", args[0] if args else "app"))
        real_rerun(*args, **kwargs)

    monkeypatch.setattr(st, "rerun", rerun)
    at.run()
    _ok(at)
    assert reruns == ["app"]  # one full run, in which the page finds every score and does not poll
    assert _cards(at) == shown


@pytest.mark.parametrize("sync", ["1", "0"])
def test_both_load_paths_give_the_same_errors_for_the_same_bad_files(sample_dir, tmp_path, monkeypatch, sync):
    """One file read in the script run (one ticked, or XERSCOPE_SYNC_LOAD) or several in a thread:
    one reader (reading.read_update) and one series builder (reading.store_of), so the same bad
    files give the same sidebar errors, each naming its file once. The order may differ: the thread
    reads the latest file first."""
    for path in sorted(sample_dir.glob("*.xer"))[:2]:
        (tmp_path / path.name).write_bytes(path.read_bytes())
    data = sorted(sample_dir.glob("*.xer"))[0].read_bytes()
    (tmp_path / "cut.xer").write_bytes(data[: len(data) // 2])
    (tmp_path / "junk.xer").write_bytes(b"not an xer")
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.setenv("XERSCOPE_SYNC_LOAD", sync)
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "1")
    at = read_folder(AppTest.from_file(APP, default_timeout=300).run())
    if sync == "0":
        _joined(at, "_load_job")
        at.run()
    _ok(at)
    assert sorted(at.session_state["errors"]) == [
        "cut.xer: incomplete file, no %E end line (still being copied, or cut short)",
        "junk.xer: not an XER file (no ERMHDR header, no tables)",
    ]
    assert len(at.session_state["store"]) == 2


def test_a_score_job_cancelled_during_a_standard_runs_none_of_its_other_checks(monkeypatch):
    """Another baseline replaced the data set while a standard's checks run: the job stops after the check
    under way, keeps no result of that standard and starts no other."""
    from xerkit import snap

    from xerscope.analysis import builtin_standards
    from xerscope.app import cache
    from xerscope.store import SnapshotStore

    snapshot = snap([{"task_code": "A1"}])
    standards = {key: builtin_standards()[key] for key in ("P6", "DCMA")}
    job = cache.ScoreJob((), snapshot, SnapshotStore([snapshot]), None, standards)
    checks_run = []

    def run_metric(metric, context):
        checks_run.append(metric)
        job.cancelled = True  # replaced while this check runs

    monkeypatch.setattr("xerscope.analysis.checks.run_metric", run_metric)
    job.run()
    assert len(checks_run) == 1
    assert job.results == {}
    assert job.done
