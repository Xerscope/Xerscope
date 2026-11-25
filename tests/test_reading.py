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


@pytest.mark.parametrize(("asked", "expected"), [("3", 3), ("4", 4), ("16", 8)])
def test_a_number_asked_is_taken_up_to_the_cores(monkeypatch, asked, expected):
    # the NAS asks for 1 in its compose file (docs/deploy.md section 7); a machine of 8 cores runs at most 8
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", asked)
    monkeypatch.setattr(reading, "usable_cores", lambda: 8)
    assert worker_count(10) == expected


GB, MB = 1_000_000_000, 1_000_000


@pytest.mark.parametrize(
    ("cores", "memory", "largest", "files", "expected"),
    [
        (24, 16 * GB, 4 * MB, 10, 10),  # room (16 - 0.5) GB // 252 MB = 61: the 10 files decide
        (24, 16 * GB, 4 * MB, 30, 24),  # the 24 cores decide
        (24, 4 * GB, 40 * MB, 10, 2),  # 3.5 GB // 1.332 GB = 2
        (24, 2 * GB, 40 * MB, 10, 1),  # the NAS cap: 1.5 GB // 1.332 GB = 1
        (2, 64 * GB, 4 * MB, 10, 2),
    ],
)
def test_auto_takes_what_the_cores_and_the_memory_allow(monkeypatch, cores, memory, largest, files, expected):
    """One worker may hold 1.2 x (110 MB + 25 x the largest file): 252 MB for 4 MB, 1.332 GB for 40 MB;
    0.5 GB stays for the app."""
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "Auto")
    monkeypatch.setattr(reading, "usable_cores", lambda: cores)
    monkeypatch.setattr(reading, "memory_bytes", lambda: memory)
    assert reading.worker_bytes(4 * MB) == 252_000_000 and reading.worker_bytes(40 * MB) == 1_332_000_000
    assert worker_count(files, largest) == expected


def test_a_number_asked_stays_within_the_memory(monkeypatch):
    # 4 asked on a 2 GB cap reading 40 MB exports: room for one, one it is
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "4")
    monkeypatch.setattr(reading, "usable_cores", lambda: 8)
    monkeypatch.setattr(reading, "memory_bytes", lambda: 2 * GB)
    assert worker_count(10, 40 * MB) == 1 and worker_count(10, 4 * MB) == 4


def test_the_container_quota_bounds_the_cores(monkeypatch):
    values = {"cpu.max": ["400000", "100000"], "memory.max": ["2147483648"]}
    monkeypatch.setattr(reading, "_cgroup_value", lambda name: values[name])
    monkeypatch.setattr("os.process_cpu_count", lambda: 24, raising=False)
    monkeypatch.setattr("os.cpu_count", lambda: 24)
    assert reading.usable_cores() == 4 and reading.memory_bytes() == 2147483648
    values["cpu.max"] = ["max", "100000"]
    assert reading.usable_cores() == 24


@pytest.mark.parametrize("asked", ["", "0", "-1", "two", "\u00b2", "1.5"])
def test_an_unusable_variable_falls_back_to_the_default(monkeypatch, asked):
    # "\u00b2".isdigit() is True but int() refuses it: the reading thread died on it, the series half read
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", asked)
    monkeypatch.setattr(reading, "usable_cores", lambda: 4)
    assert worker_count(10) == 2
    monkeypatch.setattr(reading, "usable_cores", lambda: 1)
    assert worker_count(10) == 1


@pytest.mark.parametrize("workers", ["1", "2"])
def test_every_file_is_read_as_one_after_the_other(items, monkeypatch, workers):
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", workers)
    results = {name: snapshot for name, snapshot, _ in read_updates(items, {})}
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


def test_a_stop_drops_the_files_not_started(items, monkeypatch):
    monkeypatch.setenv("XERSCOPE_LOAD_WORKERS", "1")
    read = []
    for name, _, _ in read_updates(items, {}, stopped=lambda: len(read) >= 1):
        read.append(name)
    assert len(read) == 1


def test_the_parse_cache_entries_name_the_file_and_its_content(items):
    name, snapshot, cache = read_update(*items[0], None)
    ((key, cached),) = cache.items()
    assert key[0] == name and len(key[1]) == 64 and key[2] is None and cached is snapshot


def test_a_worker_does_not_run_the_app_script(items, monkeypatch, capfd):
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
    assert "ScriptRunContext" not in capfd.readouterr().err


def test_an_error_names_its_file_once():
    from xerscope.app.reading import error_text
    from xerscope.xer import XerError

    assert error_text("a.xer", XerError("a.xer: PROJECT or TASK table missing")) == (
        "a.xer: PROJECT or TASK table missing"
    )
    assert error_text("a.xer", KeyError("task_id")) == "a.xer: 'task_id'"
