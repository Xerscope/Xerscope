"""Reading the chosen XER files on several processes, for the Files window's Done.

Parsing and building a Snapshot is pure Python and pandas work: threads share one core (the GIL), so
a series of ten 4 000-activity exports read one file after the other. Here each file goes to a worker
process; the Snapshot comes back pickled. Measured on ten 3.8 MB updates: 3.3 s one after the other,
1.6 s on four processes, process start included; MAX_WORKERS caps them at two.

This module imports no Streamlit: a worker process imports it (``spawn``: a fresh interpreter, never
a fork of the server and its threads) and only needs the XER reader.
"""

from __future__ import annotations

import hashlib
import multiprocessing
import os
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool

from xerscope.store import DuplicateDataDate, SnapshotStore
from xerscope.xer import Snapshot, load_snapshot

MAX_WORKERS = 2  # the most the NAS deployment stays stable with; each process holds a file being read
WORKERS_VARIABLE = "XERSCOPE_LOAD_WORKERS"  # set to 1 to read in the calling thread


def worker_count(files: int) -> int:
    """Processes for ``files`` files: XERSCOPE_LOAD_WORKERS, else one per core, never above
    MAX_WORKERS. A value that is not a whole number of at least 1 is ignored (the default applies)."""
    configured = os.environ.get(WORKERS_VARIABLE, "").strip()
    wanted = int(configured) if configured.isascii() and configured.isdigit() else 0
    if wanted < 1:
        wanted = os.cpu_count() or 1
    return max(1, min(wanted, MAX_WORKERS, files))


def error_text(name: str, exc: Exception) -> str:
    """The sidebar line of a file that could not be read: the message, named by the file once (an
    XerError names it already)."""
    text = str(exc)
    return text if text.startswith(f"{name}:") else f"{name}: {text}"


def read_update(
    name: str, data: bytes, chosen_project: str | None, parse: Callable[..., Snapshot] = load_snapshot
) -> tuple[str, Snapshot | str, dict]:
    """One file as the app reads it, on a worker process or in the script run: the project picked
    for it, else the default one. Returns the name, the Snapshot (or the error text) and the entries
    for the session's parse cache. ``parse``: called as ``load_snapshot(data, name=, project_id=)``;
    the script run passes its session-cached parser."""
    digest = hashlib.sha256(data).hexdigest()
    try:
        snapshot = parse(data, name=name, project_id=None)
        cache = {(name, digest, None): snapshot}
        if chosen_project in set(snapshot.file_projects["proj_id"]) and chosen_project != snapshot.project_id:
            snapshot = parse(data, name=name, project_id=chosen_project)
            cache[(name, digest, chosen_project)] = snapshot
        return name, snapshot, cache
    except Exception as exc:  # noqa: BLE001 - the error is shown for that file, the others load
        return name, error_text(name, exc), {}


def store_of(results: Iterable[tuple[str, Snapshot | str]]) -> tuple[SnapshotStore | None, list[str]]:
    """The series of the files read (``read_update``'s name and result, in the order of the series)
    and the errors met: a file's error text, a file without status date, several files on one."""
    snapshots, errors = [], []
    for name, result in results:
        if isinstance(result, str):
            errors.append(result)
        elif result.data_date is None:
            errors.append(f"{name}: no status date (PROJECT.last_recalc_date); the file is skipped")
        else:
            snapshots.append(result)
    if not snapshots:
        return None, errors
    try:
        return SnapshotStore(snapshots), errors
    except DuplicateDataDate as exc:
        return None, [*errors, f"{exc}. Untick the others."]


def read_updates(
    items: list[tuple[str, bytes]], choices: dict[str, str], stopped: Callable[[], bool] = lambda: False
) -> Iterator[tuple[str, Snapshot | str, dict]]:
    """``read_update`` for every file, as each finishes: on worker processes when there is more than
    one file and more than one worker, else one after the other here. A pool that cannot start or
    breaks (no process allowed, a worker killed for memory) falls back to reading here. Once
    ``stopped()`` (another choice of files replaced this one), the files not started are dropped and
    the reading ends after the files under way."""
    done: set[str] = set()
    workers = worker_count(len(items))
    if workers > 1:
        pool = None
        try:
            pool = ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn"))
            futures = [pool.submit(read_update, name, data, choices.get(name)) for name, data in items]
            for future in as_completed(futures):
                if stopped():
                    return
                result = future.result()
                done.add(result[0])
                yield result
            return
        except (OSError, BrokenProcessPool, RuntimeError):
            pass  # read what is left below
        finally:
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)
    for name, data in items:
        if stopped():
            return
        if name not in done:
            yield read_update(name, data, choices.get(name))
