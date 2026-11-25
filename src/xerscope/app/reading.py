"""Reading the chosen XER files on several processes, for the Files window's Done.

Parsing and building a Snapshot is pure Python and pandas work: threads share one core (the GIL), so
a series of ten 4 000-activity exports read one file after the other. Here each file goes to a worker
process; the Snapshot comes back pickled. Measured on ten 3.8 MB updates: 3.3 s one after the other,
1.6 s on four processes, process start included. By default MAX_WORKERS caps them at two (the NAS);
XERSCOPE_LOAD_WORKERS=auto sizes them to the machine (its cores, and the memory each worker needs for
the largest file), a number asks for that many within the same bounds.

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

MAX_WORKERS = 2  # the default cap: the most the NAS deployment stays stable with
WORKERS_VARIABLE = "XERSCOPE_LOAD_WORKERS"  # 1: read in the calling thread; auto: sized to the machine
AUTO = "auto"
# A worker's peak while it reads one export: a fixed part (the interpreter, pandas and xerscope
# imported) plus a part that grows with the file. Measured: 113-115 MB for a 14 KB export and
# 125 MB for a 0.73 MB one of 3,000 activities (one process each, ru_maxrss), about 1.1 GB for a
# 40 MB export on the NAS (docs/deploy.md §7), hence 25 bytes held per byte read; 20 % on top.
WORKER_FIXED_BYTES = 110_000_000
WORKER_BYTES_PER_FILE_BYTE = 25
WORKER_MARGIN = 1.2
APP_BYTES = 500_000_000  # kept for the app itself and the series already read


def worker_bytes(largest_file: int) -> int:
    """What one worker may hold at its peak when the largest file to read is ``largest_file`` bytes."""
    return int(WORKER_MARGIN * (WORKER_FIXED_BYTES + WORKER_BYTES_PER_FILE_BYTE * largest_file))


def worker_count(files: int, largest_file: int = 0) -> int:
    """Processes for ``files`` files, never more than the files, the usable cores, nor the workers
    the memory holds (the container's cap, else the machine's) when each may read the largest file
    (``largest_file`` bytes).

    XERSCOPE_LOAD_WORKERS: ``auto`` takes as many as the cores and the memory allow; a whole number
    of at least 1 asks for that many, within the same bounds; anything else, or unset, MAX_WORKERS."""
    configured = os.environ.get(WORKERS_VARIABLE, "").strip().lower()
    room = max(1, (memory_bytes() - APP_BYTES) // worker_bytes(largest_file))
    if configured == AUTO:
        wanted = room
    elif configured.isascii() and configured.isdigit() and int(configured) >= 1:
        wanted = min(int(configured), room)
    else:
        wanted = min(MAX_WORKERS, room)
    return max(1, min(wanted, usable_cores(), files))


def usable_cores() -> int:
    """The cores this process may run on: its affinity (a container's cpuset), within the
    container's CPU quota (cgroup v2 ``cpu.max``) when it sets one."""
    counted = getattr(os, "process_cpu_count", os.cpu_count)() or 1
    quota = _cgroup_value("cpu.max")
    if quota and quota[0] != "max" and len(quota) == 2:
        counted = min(counted, max(1, int(quota[0]) // int(quota[1])))
    return counted


def memory_bytes() -> int:
    """The memory this process may use: the container's cap (cgroup v2 ``memory.max``), else the
    machine's physical memory; where neither is known (Windows), room for MAX_WORKERS."""
    cap = _cgroup_value("memory.max")
    if cap and cap[0].isdigit():
        return int(cap[0])
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        return APP_BYTES + MAX_WORKERS * worker_bytes(0)


def _cgroup_value(name: str) -> list[str]:
    """The words of /sys/fs/cgroup/<name>, empty when there is no cgroup v2 file to read."""
    try:
        with open(f"/sys/fs/cgroup/{name}", encoding="ascii") as file:
            return file.read().split()
    except OSError:
        return []


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
        cache: dict[tuple[str, str, str | None], Snapshot] = {(name, digest, None): snapshot}
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


def _read_on_workers(
    items: list[tuple[str, bytes]], choices: dict[str, str], workers: int, stopped: Callable[[], bool]
) -> Iterator[tuple[str, Snapshot | str, dict]]:
    """``read_update`` for every file on ``workers`` processes, as each finishes.

    Ends early, with files unread, when ``stopped()`` or when the pool cannot start or breaks (no process
    allowed, a worker killed for memory): ``read_updates`` then reads here the files not yielded.
    """
    pool = None
    try:
        pool = ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn"))
        futures = [pool.submit(read_update, name, data, choices.get(name)) for name, data in items]
        for future in as_completed(futures):
            if stopped():
                return
            yield future.result()
    except (OSError, BrokenProcessPool, RuntimeError):
        pass  # the caller reads what is left
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)


def read_updates(
    items: list[tuple[str, bytes]], choices: dict[str, str], stopped: Callable[[], bool] = lambda: False
) -> Iterator[tuple[str, Snapshot | str, dict]]:
    """``read_update`` for every file, as each finishes: on worker processes when there is more than
    one file and more than one worker, else one after the other here. A pool that cannot start or
    breaks (no process allowed, a worker killed for memory) falls back to reading here. Once
    ``stopped()`` (another choice of files replaced this one), the files not started are dropped and
    the reading ends after the files under way."""
    done: set[str] = set()
    workers = worker_count(len(items), max((len(data) for _, data in items), default=0))
    if workers > 1:
        for result in _read_on_workers(items, choices, workers, stopped):
            done.add(result[0])
            yield result
    for name, data in items:
        if stopped():
            return
        if name not in done:
            yield read_update(name, data, choices.get(name))
