"""load_series (app/loading.py) without AppTest: the session is a dict standing in for st.session_state,
the files are two of the demo series, read in the call (XERSCOPE_SYNC_LOAD, set by conftest)."""

import pytest
import streamlit as st

from xerscope.app.loading import load_series
from xerscope.store import SnapshotStore


@pytest.fixture
def upload(sample_dir, monkeypatch):
    """Return the session holding an upload of two demo files, and the files."""
    files = [(path.name, path.read_bytes()) for path in sorted(sample_dir.glob("*.xer"))[:2]]
    session = {"files_source": ("upload", files)}
    monkeypatch.setattr(st, "session_state", session)
    return session, files


@pytest.mark.oracle("characterization")
def test_load_series_reads_the_upload_and_fills_the_session(upload):
    session, files = upload
    store = load_series(lambda index, count, name: None)
    assert isinstance(store, SnapshotStore) and len(store) == 2
    assert session["store"] is store
    assert session["items"] == files
    assert session["errors"] == []
    assert session["signature"][0] == "upload" and len(session["signature"]) == 3
    assert session["_load_job"] is None


@pytest.mark.oracle("characterization")
def test_load_series_tells_the_count_then_each_file(upload):
    _, files = upload
    told = []
    load_series(lambda index, count, name: told.append((index, count, name)))
    assert told == [(0, 2, None), (0, 2, files[0][0]), (1, 2, files[1][0])]


@pytest.mark.oracle("characterization")
def test_load_series_does_not_read_the_same_source_again(upload):
    session, _ = upload
    store = load_series(lambda index, count, name: None)
    parsed_keys = set(session["_parsed"])
    told = []
    again = load_series(lambda index, count, name: told.append(name))
    assert again is store
    assert told == []
    assert set(session["_parsed"]) == parsed_keys


@pytest.mark.oracle("characterization")
def test_load_series_without_a_source_returns_no_store(monkeypatch):
    session = {}
    monkeypatch.setattr(st, "session_state", session)
    assert load_series(lambda index, count, name: None) is None
    assert session["store"] is None and session["signature"] == () and session["_load_job"] is None
