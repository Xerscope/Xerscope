"""Reading the series into the session: background jobs, the lexicon and the sidebar loader."""

from __future__ import annotations

import functools
import hashlib
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from xerscope.analysis import query
from xerscope.analysis.ask import suggested
from xerscope.app import ui
from xerscope.app.baselines import _ask_for_the_baseline, _baseline_picker, _files_count, _parse
from xerscope.app.files_window import _window, most_recent_first
from xerscope.app.reading import read_update, read_updates, store_of
from xerscope.app.session import _digest, _file_choices, _file_digest, _open_window, _period
from xerscope.store import DuplicateDataDate, SnapshotStore
from xerscope.xer import Snapshot, xer_files


def _parse_cached(data: bytes, name: str, project_id: str | None = None) -> Snapshot:
    """Run ``_parse`` with ``load_snapshot``'s signature, for ``reading.read_update``."""
    return _parse(name, data, project_id)


def _read(name: str, data: bytes) -> Snapshot:
    """Return the snapshot of one file.

    The project picked for it in the window, else the file's default project (``_default_project`` in the
    model).
    """
    snapshot = _parse(name, data)
    chosen = _file_choices().get(name)
    if chosen in set(snapshot.file_projects["proj_id"]):
        return snapshot if chosen == snapshot.project_id else _parse(name, data, project_id=chosen)
    return snapshot


def _build(
    items: list[tuple[str, bytes]], on_file: Callable[[int, str], None] | None = None
) -> tuple[SnapshotStore | None, list[str]]:
    """Read each file for the project picked for it, else its default project.

    So a project renamed between updates still loads. ``on_file(index, name)`` is called before each file
    is read (the sidebar's progress line). The file is read and its error worded as on a worker process
    (``reading.read_update``), the series built as there (``reading.store_of``).
    """
    choices, results = _file_choices(), []
    for index, (name, data) in enumerate(items):
        if on_file is not None:
            on_file(index, name)
        _, result, _ = read_update(name, data, choices.get(name), parse=_parse_cached)
        results.append((name, result))
    return store_of(results)


def background_jobs() -> bool:
    """Return whether the files after the first and the Overview scores are read in a thread while the pages draw.

    XERSCOPE_SYNC_LOAD=1 (the tests: AppTest returns when the script ends) does everything in the script
    run.
    """
    return os.environ.get("XERSCOPE_SYNC_LOAD", "").lower() not in ("1", "true", "yes")


def _lexicon_dirs(name: str) -> list[Path]:
    """Return the folder ``name`` (generated, curated, suggested) of XERSCOPE_LEXICON; none when unset."""
    root = os.environ.get("XERSCOPE_LEXICON", "")
    return [Path(root) / name] if root else []


@functools.cache
def lexicon_and_errors() -> tuple[query.Lexicon, tuple[str, ...]]:
    """Return the Ask field's trade words.

    The *.toml of XERSCOPE_LEXICON's curated/ folder (a company's own words, kept outside the repository;
    none ships with the app), and the files and refusals skipped with why. Read once for the process: it
    holds no session's data. The errors show on the Debug page, never to a visitor of another page.
    """
    found, errors = query.load_lexicon(*_lexicon_dirs(query.CURATED))
    return found, tuple(errors + query.load_refusals(*_lexicon_dirs(query.CURATED))[1])


def lexicon() -> query.Lexicon:
    """Return the Ask field's trade words, without the errors met reading them."""
    return lexicon_and_errors()[0]


@functools.cache
def refusals() -> list[tuple[str, frozenset[str]]]:
    """Return the generated groups curated/ refuses.

    They win over generated/ and over the variants derived in memory.
    """
    return query.load_refusals(*_lexicon_dirs(query.CURATED))[0]


@functools.cache
def file_variants() -> dict[str, list[list[str]]]:
    """Return the variant groups that name their source column.

    Generated/ (``xerscope lexicon build``) less the curated refusals, and curated/'s own; merged with
    those derived in memory.
    """
    generated = query.refuse(query.load_variants(*_lexicon_dirs(query.GENERATED)), refusals())
    curated = query.load_variants(*_lexicon_dirs(query.CURATED))
    return {c: generated.get(c, []) + curated.get(c, []) for c in sorted({*generated, *curated})}


def session_lexicon() -> query.Lexicon:
    """Return the app's lexicon plus the words taught this session (``teach``): what the Ask field reads."""
    found = lexicon()
    for word, label in st.session_state.get("taught", []):
        found = query.learn(found, word, label)
    return found


def teach(word: str, label: str, kind: str) -> bool:
    """Read ``word`` as ``label`` (a ``kind`` of query.suggestions) from now on in this session.

    Append the correction to XERSCOPE_LEXICON's suggested/ for review (``ask.suggested``: the word, the
    label, its column, the filter and the date, never the sentence). The Ask field reads it from a file
    only once copied into curated/. False when a guard refused to record it.
    """
    taught = st.session_state.setdefault("taught", [])
    if (word, label) in taught:
        return True
    taught.append((word, label))
    folders = _lexicon_dirs(query.SUGGESTED)
    return not folders or suggested.record(folders[0], word, label, kind, datetime.now(UTC), lexicon())


@dataclass
class LoadJob:
    """Hold the files being read in a thread, which hands them to worker processes (``reading``).

    ``results`` fills as each file is read (name -> Snapshot, or the error text), ``done`` once every file
    was tried. Nothing of a partial series is shown: the pages wait for ``done``.
    """

    items: list[tuple[str, bytes]]
    choices: dict[str, str]
    results: dict[str, Snapshot | str] = field(default_factory=dict)
    cache: dict[tuple, Snapshot] = field(default_factory=dict)  # _parse's keys, merged once collected
    done: bool = False
    cancelled: bool = False  # set when another choice of files replaces this one: stop reading
    thread: threading.Thread | None = None

    def run(self) -> None:
        """Read each file in turn into ``results``, then set ``done``."""
        try:
            for name, result, cache in read_updates(self.items, self.choices, lambda: self.cancelled):
                self.cache.update(cache)
                self.results[name] = result
        finally:
            self.done = True


def _start_load(items: list[tuple[str, bytes]]) -> LoadJob:
    """Read every chosen file in a daemon thread (the session's choice of project per file taken as it stands).

    The pages show the progress and draw once the series is complete.
    """
    job = LoadJob(most_recent_first(items), dict(_file_choices()))
    job.thread = threading.Thread(target=job.run, name="xerscope-load", daemon=True)
    job.thread.start()
    return job


def _collect(job: LoadJob) -> tuple[SnapshotStore | None, list[str]]:
    """Return the store of the files read so far, in the order of the series, and the errors met."""
    st.session_state.setdefault("_parsed", {}).update(job.cache)
    return store_of((name, job.results[name]) for name, _ in job.items if name in job.results)


@st.fragment(run_every=1.0)
def _poll_load() -> None:
    """Show the reading progress, redrawn alone every second (the page is not).

    One rerun of the app once every file is read, which draws the pages on the complete series.
    """
    job: LoadJob | None = st.session_state.get("_load_job")
    if job is None:
        return
    if job.done:
        st.rerun(scope="app")
    read, total = len(job.results), len(job.items)
    st.progress(read / total, text=f"Reading the updates · {read}/{total}")


def _chosen_items() -> tuple[tuple, list[tuple[str, bytes]] | None, list[str]]:
    """Return the signature of the files validated in the window.

    Their contents when they changed since the last run (None: unchanged, or nothing chosen when the
    signature is empty), and a message per file ticked that is no longer in the folder (moved or replaced
    on the share between two runs).
    """
    source = st.session_state.get("files_source")
    if source is None:
        return (), None, []
    if source[0] == "upload":
        # keyed on content, so a corrected file of the same name and size is read again
        signature = ("upload",) + tuple(sorted((name, _digest(data)) for name, data in source[1]))
        if signature == st.session_state.get("signature"):
            return signature, None, []
        return signature, list(source[1]), []
    _, folder, names = source
    root = Path(folder).expanduser()
    listed = {path.name: path for path in xer_files(root)} if root.is_dir() else {}
    previous = st.session_state.get("signature") or ()
    # the bytes of a file whose digest did not change are those already held: not read again
    held = dict(st.session_state.get("items") or []) if previous[:2] == ("folder", str(root)) else {}
    digests, items, gone = _read_ticked(names, listed, held, previous[2:])
    if not digests and not gone:
        return (), None, []
    signature = ("folder", str(root), *digests)
    if signature == previous:
        return signature, None, gone
    return signature, items, gone


def _read_ticked(
    names, listed: dict[str, Path], held: dict[str, bytes], previous: tuple
) -> tuple[list[tuple[str, str]], list[tuple[str, bytes]], list[str]]:
    """Return the digest and contents of each ticked file, in name order.

    And a message per file no longer in the folder. A file whose digest is in ``previous`` keeps the bytes
    already held.
    """
    digests, items, gone = [], [], []
    for name in sorted(names):
        try:
            path = listed[name]
            digest = _file_digest(path)
            data = held[name] if name in held and (name, digest) in previous else path.read_bytes()
        except (KeyError, OSError):
            gone.append(f"{name}: no longer in the folder; the file is skipped")
            continue
        digests.append((name, digest))
        items.append((name, data))
    return digests, items, gone


def _apply_file_choices(store: SnapshotStore) -> SnapshotStore:
    """Read again, for the project picked in the window, the files read for another one.

    The other files keep their snapshot.
    """
    data = dict(st.session_state.get("items") or [])
    snapshots = list(store)
    for i, snapshot in enumerate(snapshots):
        chosen = _file_choices().get(snapshot.source)
        if chosen and chosen != snapshot.project_id and snapshot.source in data:
            snapshots[i] = _read(snapshot.source, data[snapshot.source])
    if all(new is old for new, old in zip(snapshots, store, strict=True)):
        return store
    try:
        store = SnapshotStore(snapshots)
    except DuplicateDataDate as exc:
        for new, old in zip(snapshots, store, strict=True):
            if new is not old:
                _file_choices().pop(new.source, None)
        st.session_state["errors"] = [*st.session_state.get("errors", []), f"{exc}. Pick another project."]
        return store
    st.session_state["store"] = store
    return store


def _forget_previous_series() -> None:
    """Stop the reading and the score computation still running for the previous choice of files.

    Another choice of files was validated: drop what was cached for it (analysis results, baselines read
    from the files). The parsed files are pruned once the new series is read (``_keep_parsed``): an
    unchanged file is not read twice.
    """
    for slot in ("_load_job", "_score_job"):
        job = st.session_state.get(slot)
        if job is not None and not job.done:
            job.cancelled = True
    st.session_state.update(_load_job=None, _score_job=None)
    for cache in ("_memo", "_file_baselines"):
        st.session_state.pop(cache, None)


def _keep_parsed(items: list[tuple[str, bytes]]) -> None:
    """Keep in the parse cache only the files of the series just read.

    A snapshot of a 4 000-activity export holds about 30 MB, and the files of earlier choices are not read
    back.
    """
    current = {(name, hashlib.sha256(data).hexdigest()) for name, data in items}
    cache = st.session_state.get("_parsed", {})
    for key in [key for key in cache if key[:2] not in current]:
        del cache[key]


def sidebar_loader() -> None:
    """Read the files chosen in the window and show their lines in the sidebar."""
    sidebar = st.sidebar
    files_line = sidebar.container()

    signature, items, gone = _chosen_items()
    if items is not None:
        _forget_previous_series()
    if items is not None and background_jobs() and len(items) > 1:
        # every file read in a thread on worker processes; the pages wait and draw once, on the
        # complete series (a partial one redrew every page and moved the default baseline per file)
        job = _start_load(items)
        st.session_state.update(store=None, signature=signature, items=items, errors=gone, _load_job=job)
    elif items is not None:
        # one line per file read, in the sidebar: a series of large exports takes a while
        line = sidebar.empty()
        count = len(items)
        line.progress(0.0, text=f"Reading {count} file(s)…")
        store, errors = _build(
            items,
            on_file=lambda index, name: line.progress(
                index / count, text=f"Reading {ui.md_text(name)} · {index + 1}/{count}"
            ),
        )
        line.empty()
        st.session_state.update(store=store, signature=signature, errors=[*gone, *errors], items=items, _load_job=None)
        _keep_parsed(items)
    elif not signature:
        st.session_state.update(store=None, signature=(), errors=[], items=None, _load_job=None)
    job: LoadJob | None = st.session_state.get("_load_job")
    if job is not None:
        if job.done:
            store, errors = _collect(job)
            st.session_state.update(store=store, errors=[*st.session_state.get("errors", []), *errors], _load_job=None)
            _keep_parsed(job.items)
        else:
            with sidebar:
                _poll_load()

    store: SnapshotStore | None = st.session_state.get("store")
    if store is not None:
        store = _apply_file_choices(store)
    # written once the projects are read: the count and dates are theirs
    files_line.button(
        f"Files · {_files_count(store)}" if store is not None else "Files · none read",
        key="files_button",
        help=f"Projects read: {', '.join(sorted({ui.md_text(snapshot.project_code) for snapshot in store}))}; "
        f"{len(store)} snapshot(s), {_period(store)}. Open to change the files or the project read from each."
        if store is not None
        else "Open to upload files or read a folder.",
        type="tertiary",
        width="stretch",
        shortcut="F",
        on_click=_open_window,
        args=("files",),
    )
    for error in st.session_state.get("errors", []):
        sidebar.error(ui.md_text(error))  # the file's text: a table or column name
    if store is not None:
        _baseline_picker(store)
        _ask_for_the_baseline()
    if st.session_state.get("files_open"):
        _window(store)
    if store is not None:
        sidebar.toggle(
            "Anonymous exports",
            value=True,
            key="anon_exports",
            help="Downloads (CSV, Power BI, Debug) carry new Task IDs and names, other text emptied, "
            "as in the anonymized XER extract. The pages always show the files' own data.",
        )
        sidebar.checkbox(
            "Costs",
            value=False,
            key="costs",
            help="The costs in the file come from the resource prices. On: the cost SPI is the main SPI "
            "on Earned value, as P6's Schedule Performance Index.",
        )
