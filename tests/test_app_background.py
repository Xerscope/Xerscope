"""The two threads of the app: the series read after its most recent update, and the Overview
scores. conftest sets XERSCOPE_SYNC_LOAD for every other test; here it is lifted and the thread
joined before the next run, which is what the page's polling fragment does in a browser."""

from pathlib import Path

import pandas as pd
from conftest import read_folder
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


def test_the_most_recent_update_is_read_first_then_the_rest_in_a_thread(sample_dir, monkeypatch):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_SYNC_LOAD", raising=False)
    at = read_folder(AppTest.from_file(APP, default_timeout=300).run())
    _ok(at)
    # after Done: one update in the store, the latest of the folder, a progress line, no scores yet
    store = at.session_state["store"]
    assert len(store) == 1
    latest_name = max(sample_dir.glob("*.xer"), key=lambda p: p.name).name
    assert store.latest.source == latest_name
    assert any(p.proto.text.startswith("Reading the updates") for p in at.get("progress"))
    job = _joined(at, "_load_job")
    assert [name for name, _ in job.items][0] == latest_name
    at.run()
    _ok(at)
    assert len(at.session_state["store"]) == len(list(sample_dir.glob("*.xer")))
    assert at.session_state["_load_job"] is None and not at.get("progress")
    # the default baseline is the first update of the whole series, not the first file read
    assert at.session_state["bl_choice"] == at.session_state["store"].labels[0]
    # the Overview then computes the four scores in a thread and fills the cards as they come
    assert any(c.value.startswith("Computing the scores") for c in at.caption)
    _joined(at, "_score_job")
    at.run()
    _ok(at)
    cards = [m for m in at.metric if m.label.endswith(" score")]
    assert len(cards) == 4 and all(m.value.endswith("%") for m in cards)
    assert not any(c.value.startswith("Computing the scores") for c in at.caption)


def test_most_recent_first_orders_by_status_date_unreadable_last(sample_dir):
    items = [(p.name, p.read_bytes()) for p in sorted(sample_dir.glob("*.xer"))]
    items.append(("broken.xer", b"not an xer"))
    ordered = [name for name, _ in most_recent_first(items)]
    dates = sorted((p.name for p in sample_dir.glob("*.xer")), reverse=True)
    assert ordered == [*dates, "broken.xer"]
    assert pd.Timestamp(dates[0][-14:-4]) > pd.Timestamp(dates[-1][-14:-4])
