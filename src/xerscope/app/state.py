"""Data loading shared by every page: sidebar inputs -> SnapshotStore in session state."""

from __future__ import annotations

import hashlib
import html
import os
import secrets
import threading
from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import pandas as pd
import streamlit as st

from xerscope.analysis import AnalysisContext, Baseline, Standard, discover_standards
from xerscope.analysis.baseline import DEFAULT_EV_BASIS, EV_BASES, relinked, renumbered
from xerscope.analysis.checks import CheckResult, run_metric, run_standard
from xerscope.analysis.standards import Metric
from xerscope.analysis.wbs import ROOT
from xerscope.anonymize import Anonymizer, LeakError
from xerscope.app import ui
from xerscope.store import DuplicateDataDate, SnapshotStore
from xerscope.xer import (
    XER_SUFFIXES,
    FileHeader,
    Snapshot,
    XerError,
    baseline_copies,
    load_header,
    load_snapshot,
    xer_files,
)
from xerscope.xer.model import HEADER_TABLES, read_header
from xerscope.xer.parser import parse_bytes

# Streamlit wants extensions without the dot.
UPLOAD_TYPES = [suffix.lstrip(".") for suffix in XER_SUFFIXES]
NBSP = "\u00a0"  # pads a label without collapsing, so a list in a monospaced face reads in columns


def _parse(name: str, data: bytes, project_id: str | None = None) -> Snapshot:
    """Parse once per session, keyed on content. The cache lives in the session's state, never in a
    process-wide cache: when the session ends (server.disconnectedSessionTTL after the tab closes),
    nothing of the files it read stays in the server."""
    cache = st.session_state.setdefault("_parsed", {})
    key = (name, hashlib.sha256(data).hexdigest(), project_id)
    if key not in cache:
        if len(cache) > 64:
            cache.clear()
        cache[key] = load_snapshot(data, name=name, project_id=project_id)
    return cache[key]


def _file_choices() -> dict[str, str]:
    """The project picked for a file in the window's Files section: proj_id by file name."""
    return st.session_state.setdefault("file_projects", {})


def _read(name: str, data: bytes) -> Snapshot:
    """The snapshot of one file: the project picked for it in the window, else the file's default
    project (``_default_project`` in the model)."""
    snapshot = _parse(name, data)
    chosen = _file_choices().get(name)
    if chosen in set(snapshot.file_projects["proj_id"]):
        return snapshot if chosen == snapshot.project_id else _parse(name, data, project_id=chosen)
    return snapshot


def _build(
    items: list[tuple[str, bytes]], on_file: Callable[[int, str], None] | None = None
) -> tuple[SnapshotStore | None, list[str]]:
    """Each file read for the project picked for it, else its default project, so a project renamed
    between updates still loads. ``on_file(index, name)`` is called before each file is read (the
    sidebar's progress line)."""
    snapshots, errors = [], []
    for index, (name, data) in enumerate(items):
        if on_file is not None:
            on_file(index, name)
        try:
            snapshot = _read(name, data)
        except XerError as exc:
            errors.append(str(exc))
            continue
        if snapshot.data_date is None:
            errors.append(f"{name}: no status date (PROJECT.last_recalc_date); the file is skipped")
            continue
        snapshots.append(snapshot)
    if not snapshots:
        return None, errors
    try:
        return SnapshotStore(snapshots), errors
    except DuplicateDataDate as exc:
        return None, [*errors, f"{exc}. Untick the others."]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def background_jobs() -> bool:
    """Whether the files after the first and the Overview scores are read in a thread while the
    pages draw. XERSCOPE_SYNC_LOAD=1 (the tests: AppTest returns when the script ends) does
    everything in the script run."""
    return os.environ.get("XERSCOPE_SYNC_LOAD", "").lower() not in ("1", "true", "yes")


def _header_date(name: str, data: bytes) -> pd.Timestamp | None:
    """The file's status date from its PROJECT rows only, for the reading order; None when unreadable."""
    try:
        return read_header(parse_bytes(data, source=name, keep=HEADER_TABLES)).data_date
    except XerError:
        return None


def most_recent_first(items: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """The files by status date, latest first (unreadable last): the pages open on the latest
    update, so it is read first and the others follow in the background."""
    dates = {name: _header_date(name, data) for name, data in items}
    return sorted(items, key=lambda item: (dates[item[0]] is None, -(dates[item[0]] or pd.Timestamp(0)).value))


@dataclass
class LoadJob:
    """The files being read in a thread: ``results`` fills in reading order (name -> Snapshot, or
    the error text), ``done`` once every file was tried. ``seen`` is how many the page last drew."""

    items: list[tuple[str, bytes]]
    choices: dict[str, str]
    results: dict[str, Snapshot | str] = field(default_factory=dict)
    cache: dict[tuple, Snapshot] = field(default_factory=dict)  # _parse's keys, merged once collected
    done: bool = False
    seen: int = 0
    thread: threading.Thread | None = None

    def read(self, name: str, data: bytes) -> None:
        """One file, as ``_read`` would read it: the project picked for it, else the default."""
        digest = hashlib.sha256(data).hexdigest()
        snapshot = load_snapshot(data, name=name)
        self.cache[(name, digest, None)] = snapshot
        chosen = self.choices.get(name)
        if chosen in set(snapshot.file_projects["proj_id"]) and chosen != snapshot.project_id:
            snapshot = load_snapshot(data, name=name, project_id=chosen)
            self.cache[(name, digest, chosen)] = snapshot
        self.results[name] = snapshot

    def run(self) -> None:
        for name, data in self.items:
            if name in self.results:
                continue
            try:
                self.read(name, data)
            except Exception as exc:  # noqa: BLE001 - an error of a thread would otherwise be lost
                self.results[name] = f"{name}: {exc}"
        self.done = True


def _start_load(items: list[tuple[str, bytes]]) -> LoadJob:
    """The most recent file read now, the others in a daemon thread (the session's choice of
    project per file taken as it stands)."""
    job = LoadJob(most_recent_first(items), dict(_file_choices()))
    first = job.items[0]
    try:
        job.read(*first)
    except Exception as exc:  # noqa: BLE001
        job.results[first[0]] = f"{first[0]}: {exc}"
    if len(job.items) == 1:
        job.done = True
    else:
        job.thread = threading.Thread(target=job.run, name="xerscope-load", daemon=True)
        job.thread.start()
    return job


def _collect(job: LoadJob) -> tuple[SnapshotStore | None, list[str]]:
    """The store of the files read so far, in the order of the series, and the errors met."""
    snapshots, errors = [], []
    for name, _ in job.items:
        result = job.results.get(name)
        if result is None:
            continue
        if isinstance(result, str):
            errors.append(result)
        elif result.data_date is None:
            errors.append(f"{name}: no status date (PROJECT.last_recalc_date); the file is skipped")
        else:
            snapshots.append(result)
    job.seen = len(job.results)
    st.session_state.setdefault("_parsed", {}).update(job.cache)
    if not snapshots:
        return None, errors
    try:
        return SnapshotStore(snapshots), errors
    except DuplicateDataDate as exc:
        return None, [*errors, f"{exc}. Untick the others."]


@st.fragment(run_every=1.0)
def _poll_load() -> None:
    """Draws nothing; reruns the app when the thread read another file, or finished."""
    job = st.session_state.get("_load_job")
    if job is None or job.done or len(job.results) != job.seen:
        st.rerun(scope="app")


def _header(path: Path) -> FileHeader | str:
    """The file's header (PROJECT and TASK only), or why it cannot be read. Kept in the session's
    state like the parsed files, keyed on name, size and modification time."""
    cache = st.session_state.setdefault("_headers", {})
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in cache:
        if len(cache) > 256:
            cache.clear()
        try:
            cache[key] = load_header(path)
        except XerError as exc:
            cache[key] = str(exc)
    return cache[key]


def _describe_file(path: Path, widths: tuple[int, int] = (0, 0)) -> tuple[str, str]:
    """Tick box label and help for a file not read yet: what build_snapshot would take from it.
    ``widths``: name and project code padded to these lengths, so the list reads in columns."""
    header = _header(path)
    name = path.name.ljust(widths[0], NBSP)
    if isinstance(header, str):
        return f"{name} — unreadable", header
    counts = header.project_task_counts
    label = f"{name} — {header.project_code.ljust(widths[1], NBSP)} · {ui.fmt_date(header.data_date)}"
    if len(counts) > 1:
        label += f" · {len(counts)} projects"
    details = (
        f"Project: {header.project_code} ({header.selected_by})  \n"
        f"Projects in file (TASK rows): {' · '.join(f'{code} ({n})' for code, n in counts.items())}  \n"
        f"Status date: {ui.fmt_date(header.data_date)} (from {header.data_date_source or 'nothing'})"
    )
    return label, details


def _folder_boxes(folder: str, chosen: tuple[str, ...]) -> tuple[str, ...]:
    """One tick box per XER file of ``folder``; the names ticked. ``chosen``: the names of the
    last validated choice, ticked again when the window reopens (its boxes are gone once closed)."""
    root = Path(folder).expanduser()
    files = xer_files(root) if root.is_dir() else []
    if not files:
        st.error("Folder not found" if not root.is_dir() else "No .xer file in that folder")
        return ()
    # Widget keys name the folder by a hash: a key shows in the page as a CSS class, and the
    # folder path is the server's.
    folder_id = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    # nothing ticked by default: a file is read (up to ~1 GB for a 40 MB export) only once asked for
    keys = {path.name: f"read:{folder_id}:{path.name}" for path in files}
    for name, key in keys.items():
        st.session_state.setdefault(key, name in chosen)

    def tick_all(value: bool) -> None:
        st.session_state.update(dict.fromkeys(keys.values(), value))

    ticked = sum(bool(st.session_state[key]) for key in keys.values())
    count, select, clear = st.columns([2, 1, 1], vertical_alignment="center")
    count.caption(f"{ticked} of {len(files)} ticked")
    select.button("Select all", key=f"all:{folder_id}", on_click=tick_all, args=(True,), width="stretch")
    clear.button("Clear", key=f"none:{folder_id}", on_click=tick_all, args=(False,), width="stretch")
    picked = []
    headers = [_header(path) for path in files]
    widths = (
        max(len(path.name) for path in files),
        max((len(header.project_code) for header in headers if not isinstance(header, str)), default=0),
    )
    with st.container(key="files_list_folder"):
        for path in files:
            label, details = _describe_file(path, widths)
            if st.checkbox(label, key=keys[path.name], help=details):
                picked.append(path.name)
    if not picked:
        st.info("Tick at least one file to read")
    return tuple(picked)


def _upload_boxes(uploads, kept: tuple[tuple[str, bytes], ...]) -> tuple[tuple[str, bytes], ...]:
    """One tick box per uploaded file, ticked by default; the files left ticked. ``kept``: the files
    of the last validated choice (an upload widget starts empty each time the window opens)."""
    files = {(name, _digest(data)): data for name, data in kept}
    for upload in uploads or []:
        files.setdefault((upload.name, _digest(upload.getvalue())), upload.getvalue())
    picked = []
    with st.container(key="files_list_upload"):
        for (name, digest), data in files.items():
            if st.checkbox(name, value=True, key=f"keep:{digest[:12]}:{name}", help=f"{len(data) / 1e6:.1f} MB"):
                picked.append((name, data))
    return tuple(picked)


# The window's baseline selectors write to drafts, filled with the values in force when it opens;
# Done copies them to the keys the app reads, closing it otherwise (Esc, ✕, a click outside) drops them.
DRAFTS = {
    "bl_choice": "draft_bl_choice",
    "ev_basis": "draft_ev_basis",
    "bl_fallback": "draft_bl_fallback",
    "guid_link": "draft_guid_link",
}


def _project_draft(source: str) -> str:
    """The draft key of the project picked for file ``source`` in the window (its proj_id)."""
    return f"draft_file_project:{source}"


def _open_window(section: str) -> None:
    st.session_state.update(files_open=True, window_section=section)
    for key, draft in DRAFTS.items():
        if key in st.session_state:
            st.session_state[draft] = st.session_state[key]
    for snapshot in st.session_state.get("store") or ():
        st.session_state[_project_draft(snapshot.source)] = snapshot.project_id


def _apply_drafts() -> None:
    """Done: the window's baseline choice becomes the one in force, its uploaded file held; a project
    picked for a file other than the one read is recorded, and the next run reads that file again."""
    for key, draft in DRAFTS.items():
        if draft in st.session_state:
            st.session_state[key] = st.session_state[draft]
    st.session_state["bl_defaulted"] = False
    for snapshot in st.session_state.get("store") or ():
        chosen = st.session_state.get(_project_draft(snapshot.source))
        if chosen is not None and chosen != snapshot.project_id:
            _file_choices()[snapshot.source] = chosen
    upload = st.session_state.get("bl_upload")
    if upload is not None:
        st.session_state["bl_file"] = (upload.name, upload.getvalue())


def _close_window() -> None:
    st.session_state["files_open"] = False


def _section_title(text: str, note: str = "") -> None:
    """A section's title in the window, ``note`` aligned right (a count, a state)."""
    st.html(f'<div class="xd-title"><span>{html.escape(text)}</span><span>{html.escape(note)}</span></div>')


def _files_section(source: tuple, store: SnapshotStore | None) -> tuple | None:
    """Upload, folder and the list of files with a box to leave one out, then the project read from
    each file of the series; the choice Done would validate."""
    if _data_locked():
        folder, uploads = os.environ.get("XERSCOPE_DATA", ""), None
        _section_title("Files", "server folder")
    else:
        _section_title("Files")
        uploads = st.file_uploader(
            "Upload .xer files", type=UPLOAD_TYPES, accept_multiple_files=True, key="files_upload"
        )
        st.session_state.setdefault(
            "files_folder", source[1] if source[0] == "folder" else os.environ.get("XERSCOPE_DATA", "")
        )
        folder = st.text_input("…or read a folder", key="files_folder", placeholder="/path/to/exports")
    kept = _upload_boxes(uploads, source[1] if source[0] == "upload" else ())
    picked = () if kept else _folder_boxes(folder, source[2] if source[0] == "folder" else ()) if folder else ()
    if store is not None:
        _projects_fields(store)
    if kept:
        return ("upload", kept)
    return ("folder", folder, picked) if picked else None


def _projects_fields(store: SnapshotStore) -> None:
    """One row per file of the series: the project read from it and the rule that picked it, and a
    list of its projects when more than one can be analysed once its baseline copies are set aside, on
    a draft that Done applies (``_apply_drafts``); otherwise the row says it holds a baseline copy."""
    st.caption("Project read from each file · why")
    with st.container(key="files_projects"):
        for snapshot in sorted(store, key=lambda s: s.source):
            labels = _project_labels(snapshot)
            copies = set(baseline_copies(snapshot.file_projects)) & set(labels)
            # the projects one could analyse: the baseline copies set aside, unless one is the project read
            choices = (set(labels) - copies) | {snapshot.project_id}
            row = f"{ui.md_text(snapshot.source)} — **{ui.md_text(snapshot.project_code)}** · " + ui.md_text(
                snapshot.selected_by
            )
            aside = len(copies - choices)
            if len(choices) < 2 and aside:
                row += " · + baseline copy" if aside == 1 else f" · + {aside} baseline copies"
            st.markdown(row)
            if len(choices) < 2:
                continue
            key = _project_draft(snapshot.source)
            if st.session_state.get(key) not in labels:
                st.session_state[key] = snapshot.project_id
            st.selectbox(
                f"Project of {snapshot.source}",
                list(labels),
                format_func=labels.get,
                key=key,
                label_visibility="collapsed",
            )
    with st.expander("Selection details"):
        st.caption(
            "One project per file: the one picked in its list, otherwise baseline copies (sum_base_proj_id, "
            "orig_proj_id) set aside, the most TASK rows, then the latest status date, then the first in the "
            "file. Picked by says which rule decided. "
            "Status date: PROJECT.last_recalc_date, else plan_start_date. "
            "One file per status date."
        )
        table = store.selection()
        st.dataframe(
            table.assign(data_date=table["data_date"].map(ui.fmt_date)),
            hide_index=True,
            key="files_selection",
            column_config={
                "file": "File",
                "project": "Project",
                "selected_by": "Picked by",
                "projects_in_file": "Projects in file (TASK rows)",
                "data_date": "Status date",
                "data_date_from": "Status date from",
                "baseline": "Baseline (P6 Project Baseline)",
                "activities": "Tasks",
            },
        )


@st.dialog("Files and baseline", width="medium", on_dismiss=_close_window)
def _window(store: SnapshotStore | None) -> None:
    """The window of the sidebar's Files and Baseline lines. A widget inside it reruns this function
    only (st.dialog is a fragment): nothing applies before Done, which reads the files and sets the
    baseline choice; closing it otherwise changes nothing. The section the line names comes first."""
    source = st.session_state.get("files_source") or ("none",)
    with st.container(key="files_sheet"):
        sections = ["files", "baseline"] if store is not None else ["files"]
        if st.session_state.get("window_section") == "baseline":
            sections.reverse()
        choice = None
        for index, section in enumerate(sections):
            if index:
                st.html('<hr class="xd-rule">')
            if section == "files":
                choice = _files_section(source, store)
            else:
                _baseline_fields(store)
        with st.container(key="xd_foot", horizontal=True, vertical_alignment="center"):
            st.caption("Done applies · Esc cancels")
            if st.button("Done", type="primary", key="files_done", shortcut="Ctrl+Enter"):
                _apply_drafts()
                st.session_state.update(files_source=choice, files_open=False)
                st.rerun()


def _chosen_items() -> tuple[tuple, list[tuple[str, bytes]] | None]:
    """Signature of the files validated in the window, and their contents when they changed since
    the last run (None: unchanged, or nothing chosen when the signature is empty)."""
    source = st.session_state.get("files_source")
    if source is None:
        return (), None
    if source[0] == "upload":
        # keyed on content, so a corrected file of the same name and size is read again
        signature = ("upload",) + tuple(sorted((name, _digest(data)) for name, data in source[1]))
        if signature == st.session_state.get("signature"):
            return signature, None
        return signature, list(source[1])
    _, folder, names = source
    root = Path(folder).expanduser()
    files = [path for path in xer_files(root) if path.name in names] if root.is_dir() else []
    if not files:
        return (), None
    signature = ("folder", str(root)) + tuple((path.name, _file_digest(path)) for path in files)
    previous = st.session_state.get("signature") or ()
    if signature == previous:
        return signature, None
    # the bytes of a file whose digest did not change are those already held: not read again
    held = dict(st.session_state.get("items") or []) if previous[:2] == signature[:2] else {}
    unchanged = {name for name, _ in set(signature[2:]) & set(previous[2:]) if name in held}
    return signature, [(path.name, held[path.name] if path.name in unchanged else path.read_bytes()) for path in files]


def _file_digest(path: Path) -> str:
    """sha256 of a folder's file, keyed on content as an upload. Read and digested again only when
    its inode, size, modification or change time moved: a file replaced under the same name and
    modification time (os.utime) still gets a new change time. Kept in the session's state."""
    cache = st.session_state.setdefault("_file_digests", {})
    stat = path.stat()
    stamp = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    kept = cache.get(str(path))
    if kept is None or kept[0] != stamp:
        kept = (stamp, _digest(path.read_bytes()))
        cache[str(path)] = kept
    return kept[1]


def _apply_file_choices(store: SnapshotStore) -> SnapshotStore:
    """Read again, for the project picked in the window, the files read for another one;
    the other files keep their snapshot."""
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


def debug_page() -> bool:
    """Whether the Debug page is in the navigation: always on a workstation; on a deployed
    instance (``_data_locked``) only with XERSCOPE_DEBUG_PAGE=1, since the page describes the
    server's reading of every file to whoever holds the URL."""
    asked = os.environ.get("XERSCOPE_DEBUG_PAGE", "").lower() in ("1", "true", "yes")
    return not _data_locked() or asked


def data_locked() -> bool:
    """Remote deployment (``_data_locked``): pages show nothing about the server (Debug block 12)."""
    return _data_locked()


def _data_locked() -> bool:
    """Remote deployment: the visitor reads the server's exports folder and nothing else. No path
    field (the app cannot be pointed elsewhere) and no upload (one parsed export of 40 MB takes
    about 1 GB, so a few uploads would push the app past its memory cap, docs/deploy.md §7)."""
    return os.environ.get("XERSCOPE_DATA_LOCKED", "").lower() in ("1", "true", "yes")


def _period(store: SnapshotStore) -> str:
    """First and last data dates, the year written once when both share it: one sidebar row."""
    first, last = store.first.data_date, store.latest.data_date
    start = ui.fmt_date(first)
    if first is not None and last is not None and first.year == last.year:
        start = start.rsplit(" ", 1)[0]
    return f"{start} → {ui.fmt_date(last)}"


def sidebar_loader() -> None:
    sidebar = st.sidebar
    files_line = sidebar.container()

    signature, items = _chosen_items()
    if items is not None and background_jobs() and len(items) > 1:
        # the most recent update now, the pages open on it; the rest in a thread, the store
        # growing as they come (the memo keys follow the files in the store, so nothing computed
        # on a partial series is read back for the full one)
        job = _start_load(items)
        st.session_state.update(signature=signature, items=items, _load_job=job)
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
        st.session_state.update(store=store, signature=signature, errors=errors, items=items, _load_job=None)
    elif not signature:
        st.session_state.update(store=None, signature=(), errors=[], items=None, _load_job=None)
    job: LoadJob | None = st.session_state.get("_load_job")
    if job is not None:
        store, errors = _collect(job)
        st.session_state.update(store=store, errors=errors)
        if job.done:
            st.session_state["_load_job"] = None
            # the default baseline (the first update) was taken on the partial series: taken again
            if st.session_state.get("bl_defaulted"):
                st.session_state.pop("bl_choice", None)
        else:
            read, total = len(job.results), len(job.items)
            sidebar.progress(read / total, text=f"Reading the updates · {read}/{total}")
            with sidebar:
                _poll_load()

    store: SnapshotStore | None = st.session_state.get("store")
    if store is not None:
        store = _apply_file_choices(store)
    # written once the projects are read: the count and dates are theirs
    files_line.button(
        f"Files · {_files_count(store)}" if store is not None else "Files · none read",
        key="files_button",
        help=f"Projects read: {', '.join(sorted({ui.md_text(s.project_code) for s in store}))}; "
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
        sidebar.error(error)
    if store is not None:
        _baseline_picker(store)
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


def _project_labels(snapshot: Snapshot) -> dict[str, str]:
    """The projects of ``snapshot``'s file that own activities, by proj_id, in file order: code, data
    date, activities and, for a baseline copy, the project it is the baseline of."""
    table = snapshot.file_projects
    codes = dict(zip(table["proj_id"], table["proj_short_name"], strict=True))
    copies = baseline_copies(table)
    labels = {}
    for _, row in table[table["tasks"] > 0].iterrows():
        label = f"{row['proj_short_name']} · {ui.fmt_date(row['data_date'])} · {row['tasks']} activities"
        if row["proj_id"] in copies:
            label += f" · baseline of {codes[copies[row['proj_id']]]}"
        labels[row["proj_id"]] = label
    return labels


BL_NONE = "None"
BL_EACH = "Baseline in each file (P6 Project Baseline)"
BL_PLANNED = "Planned dates in each file (target_*)"
BL_FILE = "Separate baseline file"


EV_BASIS_LABEL = {
    "budgeted_planned": "Budgeted · planned dates",
    "budgeted_current": "Budgeted · current dates",
    "at_completion_current": "At completion · current dates",
}


def _baseline_from_choice(sidebar, store: SnapshotStore, choice: str, basis: str, env_path: str):
    """The Baseline (or marker) the window's choice stands for; None when nothing usable."""
    if choice in (BL_PLANNED, BL_EACH):
        return choice  # resolved per snapshot
    if choice == BL_NONE:
        return None
    if choice != BL_FILE:
        return Baseline.from_snapshot(store.by_label(choice), basis)
    source = None if _data_locked() else st.session_state.get("bl_file")
    if source is None and env_path and Path(env_path).is_file():
        source = (Path(env_path).name, Path(env_path).read_bytes())
    if source is not None:
        st.session_state["baseline_digest"] = hashlib.sha256(source[1]).hexdigest()
    if source is None:
        sidebar.caption("Upload the baseline XER, or pick one of the loaded snapshots.")
        return None
    try:
        return Baseline.from_snapshot(_parse(*source), basis)
    except XerError as exc:
        sidebar.error(f"Baseline not read: {exc}")
        return None


def _describe_baseline(sidebar, store: SnapshotStore, baseline: Baseline) -> None:
    sidebar.caption(f"{baseline.label} · {len(baseline.frame)} tasks · {baseline.bac_hours:,.0f} labor h")
    baseline_date, first_date = baseline.snapshot.data_date, store.first.data_date
    if baseline_date is not None and first_date is not None and baseline_date > first_date:
        sidebar.warning(
            f"The baseline's status date ({ui.fmt_date(baseline_date)}) is after the first update's "
            f"({ui.fmt_date(first_date)}): "
            "BEI, missed tasks and PV before that date compare against a plan that did not exist yet.",
            icon=":material/warning:",
        )


def _fallback_options(store: SnapshotStore) -> list[str]:
    """What an update whose file has no usable baseline can be measured against. No separate file on
    a locked server: it could only be uploaded."""
    return ([] if _data_locked() else [BL_FILE]) + store.labels + [BL_PLANNED, BL_NONE]


def _fallback_picker(sidebar, store: SnapshotStore, basis: str) -> None:
    """What an update whose file has no usable baseline is measured against: chosen, never imposed."""
    choice = st.session_state["bl_fallback"]
    st.session_state["fallback_choice"] = choice
    st.session_state["fallback"] = _baseline_from_choice(sidebar, store, choice, basis, "")


def _source_kind(snapshot: Snapshot) -> str:
    """Where the baseline of an update comes from in the per-file mode: its file, the fallback, nothing."""
    if snapshot.file_baseline.usable:
        return "the baseline of its file"
    return "the fallback" if st.session_state.get("fallback") is not None else "no baseline"


def _file_baseline_warnings(sidebar, store: SnapshotStore) -> None:
    """The per-file mode, file by file: no usable baseline (and what applies instead), a pointer that is
    not used and why, a series that mixes sources."""
    unusable = [snapshot for snapshot in store if not snapshot.file_baseline.usable]
    if unusable:
        choice = st.session_state.get("fallback_choice", BL_NONE)
        instead = "their baseline checks are n/a" if choice == BL_NONE else f"fallback: {choice}"
        sidebar.warning(
            f"No usable P6 Project Baseline in the file of {ui.md_text(', '.join(s.source for s in unusable))}: "
            f"{instead}.",
            icon=":material/warning:",
        )
    for snapshot in unusable:
        if snapshot.file_baseline.note:
            sidebar.warning(
                f"{ui.md_text(snapshot.source)}: {ui.md_text(snapshot.file_baseline.text)}. Not used.",
                icon=":material/warning:",
            )
    groups: dict[str, list[str]] = {}
    for snapshot in store:
        groups.setdefault(_source_kind(snapshot), []).append(snapshot.source)
    if len(groups) > 1:
        parts = [f"{len(files)} on {kind} ({ui.md_text(', '.join(files))})" for kind, files in groups.items()]
        sidebar.warning(
            "The series mixes baseline sources, so its updates are not measured against the same plan: "
            + "; ".join(parts)
            + ".",
            icon=":material/warning:",
        )


def _absent_baseline_help(sidebar, store: SnapshotStore) -> None:
    """Files whose P6 Project Baseline (sum_base_proj_id) names a project the file does not hold: ask
    for that baseline's XER. No P6 steps: restoring or converting a baseline changes the project."""
    absent: dict[str, list[str]] = {}
    for snapshot in store:
        pointer = snapshot.file_baseline.proj_id
        if pointer and pointer not in set(snapshot.file_projects["proj_id"]):
            absent.setdefault(pointer, []).append(snapshot.source)
    if not absent:
        return
    named = "; ".join(f"project {proj_id} ({', '.join(files)})" for proj_id, files in absent.items())
    sidebar.info(
        f"P6 Project Baseline not exported with the file: {ui.md_text(named)}. "
        f"Load that baseline's XER under Baseline (BL) > {BL_FILE}.",
        icon=":material/info:",
    )


MATCH_WARN_BELOW = 0.9  # share of the update's activities the baseline must find


def _count(number: int, word: str) -> str:
    return f"{number} {word}{'' if number == 1 else 's'}"


def _files_count(store: SnapshotStore) -> str:
    """``N files · K projects``: K is the projects read, in the alert colour when the series mixes several."""
    count = len({snapshot.project_code for snapshot in store})
    projects = _count(count, "project")
    if count > 1:
        projects = f":orange[{projects}]"
    return f"{_count(len(store), 'file')} · {projects}"


def _baseline_kind(baseline: Baseline | None) -> str:
    """Where ``baseline`` (``baseline_for`` an update) comes from: its file's P6 Project Baseline, the
    fallback (``_fallback_baseline`` names it so), planned dates, a loaded update, a separate file, none."""
    if baseline is None:
        return "none"
    if st.session_state.get("baseline") == BL_EACH:
        if baseline.source.startswith("fallback"):
            return f"fallback, {_baseline_short(st.session_state.get('fallback_choice', BL_NONE))}"
        return "in file"
    return _baseline_short(st.session_state.get("bl_choice", BL_NONE))


def context_banner(store: SnapshotStore, snapshot: Snapshot) -> None:
    """One line under a page title: what the page is computed from (projects read, data date of the update
    shown, the baseline ``baseline_for`` gives it, EV basis, costs, files), the baseline's source in full in
    the help. Pressing it opens the Files and baseline window."""
    codes = list(dict.fromkeys(s.project_code for s in store))
    projects = " + ".join(ui.md_text(code) for code in codes[:3]) + (f" +{len(codes) - 3}" if len(codes) > 3 else "")
    baseline = baseline_for(snapshot)
    kind = _baseline_kind(baseline)
    basis = EV_BASIS_LABEL[st.session_state.get("ev_basis", DEFAULT_EV_BASIS)]
    costs = "on" if costs_shown() else "off"
    label = (
        f"{projects} · data date {ui.fmt_date(snapshot.data_date)} · BL {ui.md_text(kind)} · "
        f"EV {basis.lower().replace(' · ', ', ')} · costs {costs} · {_files_count(store)}"
    )
    used = ui.md_text(baseline.source or baseline.label) if baseline is not None else ui.md_text(kind)
    details = [
        f"Project(s) read: {', '.join(ui.md_text(code) for code in codes)}",
        f"Data date of the update shown: {ui.fmt_date(snapshot.data_date)} ({ui.md_text(snapshot.source)})",
        f"Baseline used for {ui.stamp(snapshot.data_date)}: {used}",
        f"Earned value basis: {basis}",
        f"Costs: {costs} (sidebar)",
        "Open to change the files, the project read from each file and the baseline.",
    ]
    st.button(
        label,
        key="context_banner",
        help="  \n".join(details),
        type="tertiary",
        width="stretch",
        on_click=_open_window,
        args=("files",),
    )


def page_header(title: str, store: SnapshotStore, snapshot: Snapshot | None = None, lead: str = "") -> None:
    """Page title, the context banner for ``snapshot`` (default: the latest update), then an optional lead."""
    st.title(title)
    context_banner(store, snapshot or store.latest)
    job: LoadJob | None = st.session_state.get("_load_job")
    if job is not None and not job.done:
        st.warning(
            f"Reading the updates · {len(job.results)}/{len(job.items)}: the series is incomplete and the "
            "figures change until every file is read.",
            icon=":material/hourglass_top:",
        )
    if lead:
        st.caption(lead)


def baseline_warnings(snapshot: Snapshot, baseline: Baseline | None, series: bool = False) -> None:
    """Under a page header: what is wrong with the baseline an update is measured against.
    ``series``: the page measures every update against this baseline (the PV / EV / SPI curves)."""
    name = ui.md_text(snapshot.source)
    if baseline is None:
        if st.session_state.get("baseline") == BL_EACH:
            todo = (
                "upload the baseline XER under 'When a file has no baseline'"
                if st.session_state.get("fallback_choice") == BL_FILE
                else "pick what applies instead under 'When a file has no baseline' (the sidebar's Baseline line)"
            )
            st.info(f"{name}: {ui.md_text(snapshot.file_baseline.text)}. To measure this update, {todo}.")
        return
    if series and st.session_state.get("baseline") == BL_EACH and len(st.session_state["store"]) > 1:
        st.caption(
            "The PV, EV and SPI curves measure every update against this baseline; the BEI uses each update's own."
        )
    baseline_date = baseline.snapshot.data_date
    if baseline_date is not None and snapshot.data_date is not None and baseline_date > snapshot.data_date:
        st.warning(
            f"{name}: the baseline's status date ({ui.fmt_date(baseline_date)}) is after the update's "
            f"({ui.fmt_date(snapshot.data_date)}): it compares against a plan that did not exist yet.",
            icon=":material/warning:",
        )
    codes = set(snapshot.activities["task_code"])
    matched = len(codes & set(baseline.frame.index))
    if codes and matched / len(codes) < MATCH_WARN_BELOW:
        st.warning(
            f"{name}: the baseline finds {matched} of {len(codes)} tasks of the update "
            f"({100 * matched / len(codes):.0f} %, below {MATCH_WARN_BELOW:.0%}). Late tasks, BEI and "
            "earned value count the others as not baselined.",
            icon=":material/warning:",
        )


def _baseline_options(store: SnapshotStore, env_path: str) -> tuple[list[str], str]:
    """The choices of "Baseline (BL)" and the default one. A separate file is offered when it can be
    had: uploaded, or named by XERSCOPE_BASELINE on a locked server."""
    in_files = any(snapshot.file_baseline.usable for snapshot in store)
    file_choice = not _data_locked() or Path(env_path).is_file()
    options = ([BL_EACH] if in_files else []) + ([BL_FILE] if file_choice else []) + store.labels
    options += [BL_PLANNED, BL_NONE]
    # BL_EACH leads the list and is the default, unless a baseline file is named by XERSCOPE_BASELINE
    if in_files and not env_path:
        return options, BL_EACH
    return options, BL_FILE if env_path and file_choice else store.labels[0]


def _baseline_short(choice: str) -> str:
    """The sidebar line's name for the baseline in use."""
    if choice == BL_FILE:
        held = None if _data_locked() else st.session_state.get("bl_file")
        env_path = os.environ.get("XERSCOPE_BASELINE", "")
        return held[0] if held else Path(env_path).name if Path(env_path).is_file() else "file missing"
    names = {BL_EACH: "in each file", BL_PLANNED: "planned dates", BL_NONE: "none"}
    # a loaded update: its label starts with its data date
    return names.get(choice, f"update {choice.split(' · ')[0]}")


def _baseline_picker(store: SnapshotStore) -> None:
    """The window's baseline choice, applied: the sidebar line names it, the warnings follow it."""
    sidebar = st.sidebar
    line = sidebar.container()
    env_path = os.environ.get("XERSCOPE_BASELINE", "")
    # the window's values, checked against this store: a choice that names a file no longer loaded
    # goes back to the default
    options, default = _baseline_options(store, env_path)
    if st.session_state.get("bl_choice") not in options:
        st.session_state["bl_choice"] = default
        st.session_state["bl_defaulted"] = True  # not the viewer's choice: set again when the series is complete
    if st.session_state.get("ev_basis") not in EV_BASES:
        st.session_state["ev_basis"] = DEFAULT_EV_BASIS
    if st.session_state.get("bl_fallback") not in _fallback_options(store):
        st.session_state["bl_fallback"] = BL_NONE
    if not isinstance(st.session_state.get("guid_link"), bool):
        st.session_state["guid_link"] = False
    choice, basis = st.session_state["bl_choice"], st.session_state["ev_basis"]
    st.session_state["baseline_digest"] = None  # set again when the choice is a baseline file
    baseline: Baseline | None | str = _baseline_from_choice(sidebar, store, choice, basis, env_path)
    st.session_state["baseline"] = baseline
    st.session_state["fallback"], st.session_state["fallback_choice"] = None, BL_NONE
    if baseline == BL_EACH:
        _fallback_picker(sidebar, store, basis)
    line.button(
        f"Baseline · {_baseline_short(choice)}",
        key="baseline_button",
        help="Open to change the baseline, the earned value basis and the fallback.",
        type="tertiary",
        width="stretch",
        shortcut="B",
        on_click=_open_window,
        args=("baseline",),
    )
    if isinstance(baseline, Baseline):
        _describe_baseline(sidebar, store, baseline)
    if baseline == BL_EACH:
        _file_baseline_warnings(sidebar, store)
    _absent_baseline_help(sidebar, store)
    _renumbered_notice(sidebar, store)


def _renumbered_notice(sidebar, store: SnapshotStore) -> None:
    """Tasks of the updates that carry a baseline task's GUID under a new Activity ID (``renumbered``):
    a warning while they count as deleted and new, a caption once the option links them, nothing
    when there are none."""
    found = memo(("renumbered",), _renumbered_counts, store, ev_basis=False)
    if not found:
        return
    total = sum(found.values())
    files = ui.md_text(", ".join(f"{name} ({count})" for name, count in found.items()))
    tasks = f"{total} task" if total == 1 else f"{total} tasks"
    if st.session_state.get("guid_link"):
        sidebar.caption(f"{tasks} renumbered since the baseline, linked to the baseline by GUID: {files}.")
        return
    sidebar.warning(
        f"{tasks} {'carries' if total == 1 else 'carry'} a baseline task's GUID under a new Activity ID "
        f"({files}): against the baseline {'it counts' if total == 1 else 'they count'} as deleted and new. "
        "Option in the Baseline window: Link renumbered tasks by GUID.",
        icon=":material/warning:",
    )


def _renumbered_counts(store: SnapshotStore) -> dict[str, int]:
    """Renumbered tasks per update (file -> count), once per data set and baseline: the sidebar
    draws the notice on every rerun of every page, and the GUID match reads every update."""
    found = {}
    for snapshot in store:
        baseline = baseline_for(snapshot, link=False)
        if baseline is None or baseline.snapshot is snapshot:
            continue
        count = len(renumbered(baseline.snapshot, snapshot))
        if count:
            found[snapshot.source] = count
    return found


def _baseline_fields(store: SnapshotStore) -> None:
    """The window's Baseline section: the selectors the sidebar held, same choices, on drafts
    (DRAFTS) that Done applies. A draft the store no longer offers starts again from the value in force."""
    options, _ = _baseline_options(store, os.environ.get("XERSCOPE_BASELINE", ""))
    offered = {
        "draft_bl_choice": options,
        "draft_ev_basis": list(EV_BASES),
        "draft_bl_fallback": _fallback_options(store),
        "draft_guid_link": [True, False],
    }
    for key, draft in DRAFTS.items():
        if st.session_state.get(draft) not in offered[draft]:
            st.session_state[draft] = st.session_state[key]
    _section_title("Baseline", _baseline_short(st.session_state["draft_bl_choice"]))
    st.selectbox(
        "Baseline (BL)",
        options,
        key="draft_bl_choice",
        help="PV, BEI, missed tasks and late tasks are measured against it. "
        "Usually the contract baseline, exported from P6 as its own XER.",
    )
    st.selectbox(
        "Earned value basis",
        list(EV_BASES),
        key="draft_ev_basis",
        format_func=EV_BASIS_LABEL.get,
        help="P6 Admin Preferences > Earned Value > 'When calculating earned value from a baseline use' "
        "(P6 default: budgeted values with planned dates). Set it as in your P6 so PV, EV and BAC match.",
    )
    st.checkbox(
        "Link renumbered tasks by GUID",
        key="draft_guid_link",
        help="A task of an update that carries a baseline task's GUID (TASK.guid) under a new Activity ID is "
        "measured against that baseline task, as P6 does when the renumbering was carried to the baseline "
        "(Renumber Activity IDs > Renumber Selected Activities in Baselines). Off: it counts as deleted and "
        "new, as P6 does otherwise.",
    )
    choice = st.session_state["draft_bl_choice"]
    if choice == BL_EACH:
        st.selectbox(
            "When a file has no baseline",
            _fallback_options(store),
            key="draft_bl_fallback",
            help="Applies update by update: an update uses the baseline of its own file when it has a usable "
            "one, otherwise this. None: the checks that need a baseline are n/a for that update.",
        )
    wants_file = choice == BL_FILE or (choice == BL_EACH and st.session_state["draft_bl_fallback"] == BL_FILE)
    if wants_file and not _data_locked():
        st.file_uploader("Baseline .xer", type=UPLOAD_TYPES, key="bl_upload")
        held = st.session_state.get("bl_file")
        if held:
            st.caption(f"Held: {held[0]}")


def _fallback_baseline(snapshot: Snapshot) -> Baseline | None:
    """The fallback chosen in the window, as it applies to ``snapshot`` (a file with no usable baseline)."""
    fallback, choice = st.session_state.get("fallback"), st.session_state.get("fallback_choice", BL_NONE)
    if fallback == BL_PLANNED:
        built = Baseline.planned(snapshot, st.session_state.get("ev_basis", DEFAULT_EV_BASIS))
        return replace(built, source=f"fallback ({BL_PLANNED})")
    if isinstance(fallback, Baseline):
        kind = "separate baseline file" if choice == BL_FILE else "loaded update"
        return replace(fallback, source=f"fallback ({kind}): {fallback.label}")
    return None


def _file_baseline(snapshot: Snapshot) -> Baseline | None:
    """The Baseline built from the project ``snapshot``'s file names as its P6 Project Baseline, or
    None when the file names none that can be used (``Snapshot.file_baseline``). Kept for the files
    and EV basis loaded."""
    pointer = snapshot.file_baseline
    data = dict(st.session_state.get("items") or []).get(snapshot.source)
    if not pointer.usable or data is None:
        return None
    basis = st.session_state.get("ev_basis", DEFAULT_EV_BASIS)
    signature = st.session_state.get("signature")
    held_for, cache = st.session_state.get("_file_baselines", (None, {}))
    if held_for != signature:
        cache = {}
    key = (snapshot.source, snapshot.project_id, pointer.proj_id, basis)
    if key not in cache:
        try:
            source = _parse(snapshot.source, data, project_id=pointer.proj_id)
        except XerError:
            return None
        built = Baseline.from_snapshot(source, basis)
        updated = pointer.updated[:10] or "not recorded"
        cache[key] = replace(
            built,
            label=f"{pointer.code} (P6 Project Baseline in {snapshot.source})",
            source=f"P6 Project Baseline in the file (proj_id {pointer.proj_id}, last update {updated})",
        )
    st.session_state["_file_baselines"] = (signature, cache)
    return cache[key]


def baseline_for(snapshot: Snapshot, link: bool | None = None) -> Baseline | None:
    """The sidebar's baseline, as it applies to ``snapshot``. ``link`` (default: the window's option
    "Link renumbered tasks by GUID"): with the tasks ``snapshot`` renumbered under their new IDs."""
    choice = st.session_state.get("baseline")
    if choice == BL_EACH:
        baseline = _file_baseline(snapshot) or _fallback_baseline(snapshot)
    elif choice == BL_PLANNED:
        baseline = Baseline.planned(snapshot, st.session_state.get("ev_basis", DEFAULT_EV_BASIS))
    else:
        baseline = choice if isinstance(choice, Baseline) else None
    link = st.session_state.get("guid_link", False) if link is None else link
    return relinked(baseline, snapshot) if link and baseline is not None else baseline


def standards() -> dict[str, Standard]:
    """Built-in standards, files in XERSCOPE_STANDARDS and any uploaded this session."""
    extra_folder = os.environ.get("XERSCOPE_STANDARDS", "")
    found, errors = discover_standards(*([extra_folder] if extra_folder else []))
    found.update(st.session_state.get("uploaded_standards", {}))
    st.session_state["standard_errors"] = errors
    return found


def require_store() -> SnapshotStore:
    store = st.session_state.get("store")
    if store is None:
        st.info(
            "Load your weekly XER exports from the sidebar's Files line (upload or folder path).\n\n"
            "No files yet? Generate a demo set with `uv run xerscope sample --out data/sample`, "
            "then read the folder `data/sample`."
        )
        st.stop()
    return store


SNAP_CHOICE = "snap_choice"  # the update picked on any page: every page's picker follows it


def _follow_snapshot(key: str) -> None:
    st.session_state[SNAP_CHOICE] = st.session_state[key]


def snapshot_picker(store: SnapshotStore, label: str = "Snapshot", key: str = "snap") -> Snapshot:
    """The update a page works on. One choice for the whole session (``SNAP_CHOICE``): picked on
    Schedule health, the Gantt opens on the same update; the latest update until one is picked."""
    labels = store.labels
    wanted = st.session_state.get(SNAP_CHOICE)
    st.session_state[key] = wanted if wanted in labels else labels[-1]
    choice = st.selectbox(label, labels, key=key, on_change=_follow_snapshot, args=(key,))
    return store.by_label(choice)


def go_to(page: str, **state) -> None:
    """Open another page with ``state`` written to the session first: the page's widgets read
    it (``views/gantt.py``, ``gantt_task=...``). Pages are named by their path under app/."""
    st.session_state.update(state)
    st.switch_page(f"views/{page}.py")


def open_in_gantt(task_code: str, snapshot: Snapshot | None = None) -> None:
    """The Gantt on ``task_code`` (its card and history under the chart), on ``snapshot``'s update
    when given, the whole project in view and no filter. Passed to ``ui.table(open_task=...)``."""
    state = {"gantt_task": task_code, "gantt_node": ROOT, "gantt_focus": None}
    if snapshot is not None:
        state[SNAP_CHOICE] = snapshot.label
    go_to("gantt", **state)


COMPARE_NONE = "None"
COMPARE_PREV = "Previous update"
COMPARE_BL = "Baseline (BL)"
COMPARE_FIRST = "First snapshot"


def compare_picker(store: SnapshotStore, current: Snapshot, key: str = "cmp") -> tuple[pd.DataFrame | None, str]:
    """Activities (task_code, start, finish, …) to outline the current bars against."""
    options = [COMPARE_PREV, COMPARE_BL, COMPARE_FIRST, COMPARE_NONE] + [
        label for label in store.labels if label != current.label
    ]
    choice = st.selectbox("Compare with", options, key=key)
    if choice == COMPARE_NONE:
        return None, ""
    if choice == COMPARE_PREV:
        previous = store.previous(current)
        return (previous.activities if previous is not None else None), "previous update"
    if choice == COMPARE_BL:
        baseline = baseline_for(current)
        if baseline is None:
            return None, ""
        activities = baseline.frame.rename(columns={"bl_start": "start", "bl_finish": "finish"}).reset_index()
        return activities, "baseline"
    if choice == COMPARE_FIRST:
        return (store.first.activities if store.first is not current else None), "first snapshot"
    chosen = store.by_label(choice)
    return chosen.activities, ui.stamp(chosen.data_date)


def _baseline_identity(ev_basis: bool = True) -> tuple:
    """What the sidebar's baseline is: the choice, the EV basis (None when ``ev_basis`` is False)
    with the GUID link option, and, for an uploaded file, its bytes."""
    baseline = st.session_state.get("baseline")
    basis = (st.session_state.get("ev_basis"), st.session_state.get("guid_link", False)) if ev_basis else None
    if isinstance(baseline, Baseline):
        return baseline.label, basis, st.session_state.get("baseline_digest")
    if baseline == BL_EACH:  # resolved per snapshot: which project each file names
        store = st.session_state.get("store")
        pointers = tuple((s.source, s.file_baseline.proj_id, s.file_baseline.usable) for s in store or ())
        fallback = (st.session_state.get("fallback_choice"), st.session_state.get("baseline_digest"))
        return baseline, basis, pointers, fallback
    return baseline, basis  # None, or BL_PLANNED (resolved per snapshot)


def data_identity(baseline: bool = True, ev_basis: bool = True) -> tuple:
    """What a result computed now was computed from: the files (``signature``: names and content
    digests), the project read from each and, unless
    ``baseline`` is False, the baseline in use with (unless ``ev_basis`` is False) the EV basis.
    The memo's key and the tag of a built download start with it."""
    # the project pickers re-read the same files for another project: same signature, other data
    store = st.session_state.get("store")
    projects = tuple((snapshot.source, snapshot.project_id) for snapshot in store) if store is not None else ()
    identity = _baseline_identity(ev_basis) if baseline else ()
    return st.session_state.get("signature"), projects, identity


MEMO_SIZE = 128  # entries per session; a standard holds at most 18 metrics, each its own entry


def memo(key: tuple, function, *arguments, keep: bool = True, baseline: bool = True, ev_basis: bool = True):
    """Per-session cache keyed on the loaded files and the baseline: heavy analyses run once per data set.

    The full key: ``data_identity`` (files, projects, and the baseline and EV basis unless the
    analysis reads neither: ``baseline`` / ``ev_basis`` False), then ``key``, which names the
    analysis and everything else it reads. ``function(*arguments)`` runs only on a cache miss;
    ``keep=False`` then returns the value without storing it (a series over every update that
    should not hold each update's frames). The cache lives in the session's state, never
    process-wide; past MEMO_SIZE entries the least recently used goes. Callers do not modify what
    it returns: the next reader gets the same object.
    """
    cache = st.session_state.setdefault("_memo", {})
    full_key = data_identity(baseline, ev_basis) + key
    if full_key in cache:
        cache[full_key] = cache.pop(full_key)  # most recently used last
        return cache[full_key]
    value = function(*arguments)
    if keep:
        while len(cache) >= MEMO_SIZE:
            cache.pop(next(iter(cache)))
        cache[full_key] = value
    return value


def metric_result(metric: Metric, snapshot: Snapshot, store: SnapshotStore, keep: bool = True) -> CheckResult:
    """``metric`` on ``snapshot`` against the sidebar's baseline for it, once per session: Health,
    Audit and the BEI of Earned value read the same entry. Key (with ``memo``'s): the metric as
    written (rule, parameters, target, standard: its repr) and the update (file, data date). Not
    the EV basis: no rule reads what it sets (the ev_* columns, the assignment costs)."""
    return memo(
        _metric_key(metric, snapshot),
        run_metric,
        metric,
        AnalysisContext(snapshot, store, baseline_for(snapshot)),
        keep=keep,
        ev_basis=False,
    )


def _metric_key(metric: Metric, snapshot: Snapshot) -> tuple:
    return ("metric", repr(metric), snapshot.source, str(snapshot.data_date))


def standard_results(standard: Standard, snapshot: Snapshot, store: SnapshotStore) -> list[CheckResult]:
    """Every check of ``standard`` on ``snapshot``, each through :func:`metric_result`."""
    return [metric_result(metric, snapshot, store) for metric in standard.metrics]


def hold_standard_results(standard: Standard, snapshot: Snapshot, results: list[CheckResult]) -> None:
    """Results computed outside the script run (ScoreJob) stored where ``metric_result`` reads."""
    for metric, result in zip(standard.metrics, results, strict=True):
        memo(_metric_key(metric, snapshot), lambda result=result: result, ev_basis=False)


@dataclass
class ScoreJob:
    """The standards' checks on one update, computed in a thread for the Overview's score cards:
    ``results`` fills per standard id as each finishes."""

    identity: tuple
    snapshot: Snapshot
    store: SnapshotStore
    baseline: Baseline | None
    standards: dict[str, Standard]
    results: dict[str, list[CheckResult]] = field(default_factory=dict)
    held: set[str] = field(default_factory=set)  # standard ids already written to the memo
    done: bool = False
    thread: threading.Thread | None = None

    def run(self) -> None:
        context = AnalysisContext(self.snapshot, self.store, self.baseline)
        for key, standard in self.standards.items():
            try:
                self.results[key] = run_standard(standard, context)
            except Exception as exc:  # noqa: BLE001 - shown as an error on the Overview, not lost
                self.results[key] = str(exc)  # type: ignore[assignment]
        self.done = True


def score_job(snapshot: Snapshot, store: SnapshotStore, standards_: dict[str, Standard]) -> ScoreJob:
    """The job computing ``standards_`` on ``snapshot`` for the current data set, started on the
    first call; a new data set or baseline starts another. The results already in are written to
    the memo, so Schedule health reads them."""
    identity = (*data_identity(ev_basis=False), snapshot.source, str(snapshot.data_date), tuple(standards_))
    job: ScoreJob | None = st.session_state.get("_score_job")
    if job is None or job.identity != identity:
        job = ScoreJob(identity, snapshot, store, baseline_for(snapshot), dict(standards_))
        job.thread = threading.Thread(target=job.run, name="xerscope-scores", daemon=True)
        job.thread.start()
        st.session_state["_score_job"] = job
    for key, results in list(job.results.items()):
        if key not in job.held and not isinstance(results, str):
            hold_standard_results(job.standards[key], snapshot, results)
            job.held.add(key)
    return job


@st.fragment(run_every=1.0)
def poll_scores() -> None:
    """Draws nothing; reruns the app when a standard's results came in, or all did."""
    job: ScoreJob | None = st.session_state.get("_score_job")
    if job is None or job.done or len(job.results) != len(job.held):
        st.rerun(scope="app")


def standard_results_held(standard: Standard, snapshot: Snapshot) -> list[CheckResult] | None:
    """The results :func:`standard_results` would return, if every one is already cached, else None.
    Computes nothing."""
    results = [
        memo(_metric_key(metric, snapshot), lambda: None, keep=False, ev_basis=False) for metric in standard.metrics
    ]
    return None if any(result is None for result in results) else results


ANONYMISED = " · anonymized"  # suffix of an anonymized download's label
PREPARE_LABEL = "Prepare anonymized downloads"


def anonymous_exports(session: MutableMapping | None = None) -> bool:
    """The sidebar switch: downloads anonymized (default) or in the files' own names."""
    session = st.session_state if session is None else session
    return session.get("anon_exports", True)


def costs_shown(session: MutableMapping | None = None) -> bool:
    """The sidebar checkbox: cost figures on Earned value (default off, the schedules are sourced in hours)."""
    session = st.session_state if session is None else session
    return bool(session.get("costs", False))


def sources_of(*snapshots: Snapshot | None, baseline: Baseline | None = None) -> list[str]:
    """The files a download is made from: the updates shown and the baseline's file."""
    found = [snapshot.source for snapshot in snapshots if snapshot is not None]
    return found + ([baseline.snapshot.source] if baseline is not None else [])


def anonymizers_built(session: MutableMapping | None = None) -> dict[frozenset[str], Anonymizer]:
    """The anonymizers of the session, by the set of file names each one read."""
    session = st.session_state if session is None else session
    built_anonymizers = session.get("_anonymizers")
    return (
        built_anonymizers[1]
        if built_anonymizers is not None and built_anonymizers[0] == session.get("signature")
        else {}
    )


def anonymizer(
    prepare: bool = False, sources: Iterable[str] | None = None, session: MutableMapping | None = None
) -> Anonymizer | None:
    """New codes for ``sources`` (file names; None = every loaded file), kept in the session only.

    Built on request, from those files only: it reads them again. The codes come from one key per
    session (HMAC), so an anonymizer of one update and one of the whole series name an activity
    the same way. One built from more files also serves a download of fewer."""
    session = st.session_state if session is None else session
    signature = session.get("signature")
    items = session.get("items") or []
    wanted = frozenset(name for name, _ in items if sources is None or name in set(sources))
    built_anonymizers = session.get("_anonymizers")
    if built_anonymizers is None or built_anonymizers[0] != signature:
        built_anonymizers = (signature, {})
        session["_anonymizers"] = built_anonymizers
    built = built_anonymizers[1]
    for names, anonymous in built.items():
        if wanted <= names:
            return anonymous
    if not prepare:
        return None
    key = session.setdefault("_anon_key", secrets.token_bytes(32))
    with st.spinner(f"Reading {len(wanted)} file(s) for the anonymized downloads…"):
        anonymous = Anonymizer.from_raws(
            (parse_bytes(data, source=name) for name, data in items if name in wanted), key=key
        )
    if len(built) >= 4:  # a few sets per session: each holds the text values of its files
        built.pop(next(iter(built)))
    built[wanted] = anonymous
    return anonymous


def downloads_ready(sources: Iterable[str] | None = None, session: MutableMapping | None = None) -> bool:
    """Whether a download of ``sources`` can be offered now: the switch is off, or its anonymizer is built."""
    session = st.session_state if session is None else session
    return not anonymous_exports(session) or anonymizer(sources=sources, session=session) is not None


@dataclass(frozen=True)
class Fetched:
    """The bytes of a download, or why it was refused (a leak of original values)."""

    data: bytes | None
    refused: str
    anonymised: bool


def fetch(
    session: MutableMapping,
    plain: Callable[[], bytes] | None,
    anonymised: Callable[[Anonymizer], bytes],
    sources: Iterable[str] | None = None,
    *,
    prepare: bool = False,
    anonymous: bool | None = None,
) -> Fetched | None:
    """The bytes of one download under the sidebar switch (``anonymous`` overrides it).

    Switch off: ``plain()``. On: ``anonymised(anonymizer)`` only, never ``plain``; None while the
    anonymizer for ``sources`` is not built and ``prepare`` is false. A ``LeakError`` is a refusal."""
    if anonymous is None:
        anonymous = anonymous_exports(session)
    if not anonymous:
        return Fetched(plain(), "", False)
    try:
        built = anonymizer(prepare=prepare, sources=sources, session=session)
        if built is None:
            return None
        return Fetched(anonymised(built), "", True)
    except LeakError as exc:
        return Fetched(None, str(exc), True)


def hold(session: MutableMapping, slot: str, tag: object, fetched: Fetched) -> None:
    """Keep a built download in the session for the loaded files and ``tag`` (what it was built for)."""
    session[slot] = (session.get("signature"), tag, fetched)


def held(session: MutableMapping, slot: str, tag: object) -> Fetched | None:
    """The download kept by ``hold`` if it is for the loaded files and this ``tag``."""
    kept = session.get(slot)
    return kept[2] if kept is not None and kept[:2] == (session.get("signature"), tag) else None


def show_download(
    fetched: Fetched,
    label: str,
    file_name: str,
    mime: str,
    *,
    suffix: bool = True,
    key: str | None = None,
    **button,
) -> None:
    """The download button of ``fetched`` (labelled anonymized when it is), or the refusal."""
    if fetched.refused:
        st.error(fetched.refused, icon=":material/block:")
        return
    st.download_button(
        label + (ANONYMISED if fetched.anonymised and suffix else ""),
        fetched.data,
        file_name,
        mime,
        icon=":material/download:",
        key=key,
        **button,
    )


def download(
    label: str,
    file_name: str,
    mime: str,
    plain: Callable[[], bytes],
    anonymised: Callable[[Anonymizer], bytes],
    *,
    key: str | None = None,
    prepare_key: str | None = None,
    sources: Iterable[str] | None = None,
    anon_file_name: str | None = None,
    **button,
) -> None:
    """A download under the sidebar switch. On, a button prepares the anonymizer of ``sources``
    (file names; None = every loaded file) and the download shows from then on."""
    fetched = fetch(st.session_state, plain, anonymised, sources)
    if fetched is None and st.button(
        PREPARE_LABEL,
        icon=":material/visibility_off:",
        key=f"prepare:{prepare_key or key or file_name}",
        help="Reads the file(s) of this download again to give them new codes. The codes are the same "
        "in every download of the session.",
    ):
        fetched = fetch(st.session_state, plain, anonymised, sources, prepare=True)
    if fetched is not None:
        name = anon_file_name if fetched.anonymised and anon_file_name else file_name
        show_download(fetched, label, name, mime, key=key, **button)


def csv_download(
    frame: pd.DataFrame,
    filename: str,
    label: str = "Download CSV",
    key: str | None = None,
    sources: Iterable[str] | None = None,
    sensitive: bool = True,
) -> None:
    """A table as CSV, anonymized or not as the sidebar switch says; ``sources`` are the files the
    table comes from, the only ones read to anonymise it. ``sensitive=False``: a table with no
    schedule data, always as is."""
    if not sensitive:
        data = frame.to_csv(index=False).encode("utf-8-sig")
        show_download(Fetched(data, "", False), label, filename, "text/csv", key=key)
        return
    download(
        label,
        filename,
        "text/csv",
        lambda: frame.to_csv(index=False).encode("utf-8-sig"),
        lambda anonymous: anonymous.csv(frame),
        key=key,
        sources=sources,
    )
