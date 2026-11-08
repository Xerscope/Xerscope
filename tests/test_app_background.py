"""The two threads of the app: the series read on worker processes, and the Overview scores.
conftest sets XERSCOPE_SYNC_LOAD for every other test; here it is lifted and the thread joined before
the next run, which is what the sidebar's polling fragment does in a browser."""

from pathlib import Path

import pandas as pd
import pytest
from conftest import file_boxes, files_done, open_files, read_folder
from streamlit.testing.v1 import AppTest

import xerscope
from xerscope.app.state import most_recent_first

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
