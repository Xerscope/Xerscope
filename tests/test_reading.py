"""The files read on worker processes (app/reading.py): same snapshots as one after the other, an
unreadable file reported without stopping the others, and a stop that drops the files not started."""

import sys
import types
from pathlib import Path

import pytest

import xerscope
from xerscope.app import reading
from xerscope.app.reading import read_update, read_updates, worker_count
from xerscope.xer import load_snapshot


@pytest.fixture(scope="module")
def items(sample_dir):
    return [(p.name, p.read_bytes()) for p in sorted(sample_dir.glob("*.xer"))[:4]]


def test_worker_count_follows_the_variable_and_never_exceeds_the_files(monkeypatch):
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "2")
    assert worker_count(10) == 2 and worker_count(1) == 1
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "1")
    assert worker_count(10) == 1


@pytest.mark.parametrize("asked", ["3", "4", "16"])
def test_worker_count_never_exceeds_two(monkeypatch, asked):
    # two processes is the most the NAS deployment stays stable with (docs/deploy.md section 7)
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", asked)
    assert worker_count(10) == 2


@pytest.mark.parametrize("asked", ["", "0", "-1", "two", "\u00b2", "1.5"])
def test_an_unusable_variable_falls_back_to_the_default(monkeypatch, asked):
    # "\u00b2".isdigit() is True but int() refuses it: the reading thread died on it, the series half read
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", asked)
    monkeypatch.setattr("os.cpu_count", lambda: 4)
    assert worker_count(10) == 2
    monkeypatch.setattr("os.cpu_count", lambda: 1)
    assert worker_count(10) == 1


@pytest.fixture
def on_workers(monkeypatch):
    """The names ``_read_on_workers`` yielded: the files that went through a worker process. The serial
    loop of ``read_updates`` reads the others in the calling process and is not counted."""
    names = []
    real = reading._read_on_workers

    def counting(*args):
        for result in real(*args):
            names.append(result[0])
            yield result

    monkeypatch.setattr(reading, "_read_on_workers", counting)
    return names


@pytest.mark.parametrize("workers", ["1", "2"])
def test_every_file_is_read_as_one_after_the_other(items, monkeypatch, workers, on_workers):
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", workers)
    results = {name: snapshot for name, snapshot, _ in read_updates(items, {})}
    # one worker reads here; two workers read every file in a worker process, not the serial fallback
    assert sorted(on_workers) == (sorted(name for name, _ in items) if workers == "2" else [])
    assert set(results) == {name for name, _ in items}
    for name, data in items:
        expected = load_snapshot(data, name=name)
        assert results[name].data_date == expected.data_date
        assert results[name].activities["task_code"].tolist() == expected.activities["task_code"].tolist()


def test_an_unreadable_file_is_named_and_the_others_load(items, monkeypatch):
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "2")
    results = {name: snapshot for name, snapshot, _ in read_updates([*items, ("broken.xer", b"not an xer")], {})}
    assert isinstance(results["broken.xer"], str) and results["broken.xer"].startswith("broken.xer: ")
    assert all(not isinstance(results[name], str) for name, _ in items)


@pytest.mark.parametrize("workers", ["1", "2"])
def test_a_stop_drops_the_files_not_started(items, monkeypatch, workers, on_workers):
    """The first file is read, then stopped() is true before each next one: by hand, exactly 1 of the 4
    files is yielded, on the serial loop with one worker and on the pool (which stops its own loop) with two."""
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", workers)
    read = []
    for name, _, _ in read_updates(items, {}, stopped=lambda: len(read) >= 1):
        read.append(name)
    assert len(read) == 1
    assert len(on_workers) == (1 if workers == "2" else 0)  # the pool path ran, and stopped after one


def test_the_parse_cache_entries_name_the_file_and_its_content(items):
    name, snapshot, cache = read_update(*items[0], None)
    ((key, cached),) = cache.items()
    assert key[0] == name and len(key[1]) == 64 and key[2] is None and cached is snapshot


def test_a_worker_does_not_run_the_app_script(items, monkeypatch, capfd, on_workers):
    """Streamlit installs the app script as ``__main__`` (a module with no spec, ``__file__`` the
    script); a ``spawn`` worker runs that file again as ``__mp_main__`` before its first task. The
    script must draw nothing there: it ran the whole app with no session, one "missing
    ScriptRunContext" warning per Streamlit call, in every worker."""
    app = types.ModuleType("__main__")
    app.__file__ = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
    monkeypatch.setitem(sys.modules, "__main__", app)
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "2")
    results = {name: snapshot for name, snapshot, _ in read_updates(items, {})}
    assert all(not isinstance(snapshot, str) for snapshot in results.values()) and len(results) == len(items)
    assert len(on_workers) == len(items)  # every file really went through a worker, so the check below means something
    assert "ScriptRunContext" not in capfd.readouterr().err


def test_an_error_names_its_file_once():
    from xerscope.app.reading import error_text
    from xerscope.xer import XerError

    assert error_text("a.xer", XerError("a.xer: PROJECT or TASK table missing")) == (
        "a.xer: PROJECT or TASK table missing"
    )
    assert error_text("a.xer", KeyError("task_id")) == "a.xer: 'task_id'"
