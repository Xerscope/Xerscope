"""Data loading shared by every page: sidebar inputs -> SnapshotStore in session state."""

from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd
import streamlit as st

from xerscope.analysis import Baseline, Standard, discover_standards
from xerscope.analysis.baseline import DEFAULT_EV_BASIS, EV_BASES
from xerscope.anonymize import Anonymizer, LeakError
from xerscope.app import ui
from xerscope.store import DuplicateDataDate, SnapshotStore
from xerscope.xer import XER_SUFFIXES, FileHeader, Snapshot, XerError, load_header, load_snapshot, xer_files
from xerscope.xer.parser import parse_bytes

# Streamlit wants extensions without the dot.
UPLOAD_TYPES = [suffix.lstrip(".") for suffix in XER_SUFFIXES]


def _parse(name: str, data: bytes, project: str | None = None, project_id: str | None = None) -> Snapshot:
    """Parse once per session, keyed on content. The cache lives in the session's state, never in a
    process-wide cache: when the session ends (server.disconnectedSessionTTL after the tab closes),
    nothing of the files it read stays in the server."""
    cache = st.session_state.setdefault("_parsed", {})
    key = (name, hashlib.sha256(data).hexdigest(), project, project_id)
    if key not in cache:
        if len(cache) > 64:
            cache.clear()
        cache[key] = load_snapshot(data, project_code=project, name=name, project_id=project_id)
    return cache[key]


def _build(items: list[tuple[str, bytes]], project: str | None = None) -> tuple[SnapshotStore | None, list[str]]:
    """``project`` applies to the files that hold it; the others keep their default project
    (the one with the most activities), so a project renamed between updates still loads."""
    snapshots, errors = [], []
    for name, data in items:
        try:
            snapshot = _parse(name, data)
            if project and project != snapshot.project_code and project in snapshot.projects_in_file:
                snapshot = _parse(name, data, project)
        except XerError as exc:
            errors.append(str(exc))
            continue
        if snapshot.data_date is None:
            errors.append(f"{name}: no data date (PROJECT.last_recalc_date); the file is skipped")
            continue
        snapshots.append(snapshot)
    if not snapshots:
        return None, errors
    try:
        return SnapshotStore(snapshots), errors
    except DuplicateDataDate as exc:
        return None, [*errors, f"{exc}. Untick the others."]


def _items_from_uploads(uploads) -> tuple[tuple, list[tuple[str, bytes]] | None]:
    """Signature of the uploaded files, and their contents when they changed since last run."""
    # keyed on content, so a corrected file of the same name and size is read again
    signature = ("upload",) + tuple(
        sorted((upload.name, hashlib.sha256(upload.getvalue()).hexdigest()) for upload in uploads)
    )
    if signature == st.session_state.get("signature"):
        return signature, None
    return signature, [(upload.name, upload.getvalue()) for upload in uploads]


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


def _describe_file(path: Path) -> tuple[str, str]:
    """Tick box label and help for a file not read yet: what build_snapshot would take from it."""
    header = _header(path)
    if isinstance(header, str):
        return f"{path.name} — unreadable", header
    counts = header.project_task_counts
    label = f"{path.name} — {header.project_code} · {ui.fmt_date(header.data_date)}"
    if len(counts) > 1:
        label += f" · {len(counts)} projects"
    details = (
        f"Project: {header.project_code} ({header.selected_by})  \n"
        f"Projects in file (TASK rows): {' · '.join(f'{code} ({n})' for code, n in counts.items())}  \n"
        f"Data date: {ui.fmt_date(header.data_date)} (from {header.data_date_source or 'nothing'})"
    )
    return label, details


def _items_from_folder(sidebar, folder: str) -> tuple[tuple, list[tuple[str, bytes]] | None, bool]:
    """Signature of the folder's XER files, their contents when changed, and whether the folder is usable."""
    root = Path(folder).expanduser()
    files = xer_files(root) if root.is_dir() else []
    if not files:
        sidebar.error("Folder not found" if not root.is_dir() else "No .xer file in that folder")
        st.session_state.update(store=None, signature=(), errors=[])
        return (), None, False
    # Widget keys name the folder by a hash: a key shows in the page as a CSS class, and the
    # folder path is the server's.
    folder_id = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    # nothing ticked by default: a file is read (up to ~1 GB for a 40 MB export) only once asked for
    keys = {path.name: f"read:{folder_id}:{path.name}" for path in files}

    def tick_all(value: bool) -> None:
        st.session_state.update(dict.fromkeys(keys.values(), value))

    ticked = sum(bool(st.session_state.get(key)) for key in keys.values())
    picked = []
    # a fixed key keeps the expander open while files are ticked: without it Streamlit keys it on
    # its label, which holds the count, and redraws it closed at every tick
    with sidebar.expander(
        f"Files to read · {ticked} of {len(files)} ticked", expanded=not ticked, key=f"files:{folder_id}"
    ):
        select, clear = st.columns(2)
        select.button("Select all", key=f"all:{folder_id}", on_click=tick_all, args=(True,), width="stretch")
        clear.button("Clear", key=f"none:{folder_id}", on_click=tick_all, args=(False,), width="stretch")
        for path in files:
            label, details = _describe_file(path)
            if st.checkbox(label, value=False, key=keys[path.name], help=details):
                picked.append(path.name)
    if not picked:
        sidebar.info("Tick at least one file to read")
        st.session_state.update(store=None, signature=(), errors=[])
        return (), None, False
    files = [path for path in files if path.name in picked]
    signature = ("folder", str(root)) + tuple((path.name, path.stat().st_mtime_ns) for path in files)
    if signature == st.session_state.get("signature"):
        return signature, None, True
    return signature, [(path.name, path.read_bytes()) for path in files], True


def _project_picker(sidebar, store: SnapshotStore) -> SnapshotStore:
    """A file exported with several projects: the one with the most activities was taken;
    let the user pick another and read the files again for it."""
    codes = sorted({code for snapshot in store for code in snapshot.projects_in_file})
    if len(codes) <= 1:
        return store
    current = store.latest.project_code
    index = codes.index(current) if current in codes else 0
    choice = sidebar.selectbox("Project", codes, index=index, key="project")
    if choice == current:
        return store
    with st.spinner(f"Reading {choice}…"):
        store, errors = _build(st.session_state["items"], project=choice)
    st.session_state.update(store=store, errors=errors)
    return store


def _data_locked() -> bool:
    """Remote deployment: the visitor reads the server's exports folder and nothing else. No path
    field (the app cannot be pointed elsewhere) and no upload (one parsed export of 40 MB takes
    about 1 GB, so a few uploads would push the app past its memory cap, docs/deploy.md §7)."""
    return os.environ.get("XERSCOPE_DATA_LOCKED", "").lower() in ("1", "true", "yes")


def sidebar_loader() -> None:
    sidebar = st.sidebar
    sidebar.subheader("Weekly XER exports")
    if _data_locked():
        uploads = None
        folder = os.environ.get("XERSCOPE_DATA", "")
        sidebar.caption("The exports folder of this server")
    else:
        uploads = sidebar.file_uploader("Upload .xer files", type=UPLOAD_TYPES, accept_multiple_files=True)
        folder = sidebar.text_input(
            "…or read a folder", value=os.environ.get("XERSCOPE_DATA", ""), placeholder="/path/to/exports"
        )

    items: list[tuple[str, bytes]] | None = None
    signature: tuple = ()
    if uploads:
        signature, items = _items_from_uploads(uploads)
    elif folder:
        signature, items, usable = _items_from_folder(sidebar, folder)
        if not usable:
            return

    if items is not None:
        with st.spinner(f"Parsing {len(items)} file(s)…"):
            store, errors = _build(items)
        st.session_state.update(store=store, signature=signature, errors=errors, items=items)
    elif not uploads and not folder:
        st.session_state.update(store=None, signature=(), errors=[], items=None)

    store: SnapshotStore | None = st.session_state.get("store")
    if store is not None:
        store = _project_picker(sidebar, store)
        sidebar.caption(
            f"{store.latest.project_code} · {len(store)} snapshot(s) · "
            f"{ui.fmt_date(store.first.data_date)} → {ui.fmt_date(store.latest.data_date)}"
        )
    if store is not None:
        _selection_panel(sidebar, store)
    for error in st.session_state.get("errors", []):
        sidebar.error(error)
    if store is not None:
        _baseline_picker(store)
        sidebar.toggle(
            "Anonymous exports",
            value=True,
            key="anon_exports",
            help="Downloads (CSV, Power BI, Debug) carry new Activity IDs and names, other text emptied, "
            "as in the anonymised XER extract. The pages always show the files' own data.",
        )
        sidebar.checkbox(
            "Costs",
            value=False,
            key="costs",
            help="The costs in the file come from the resource prices. On: the cost SPI is the main SPI "
            "on Earned value, as P6's Schedule Performance Index.",
        )


def _selection_panel(sidebar, store: SnapshotStore) -> None:
    """What was taken from each file and why: the project, the rule that picked it, and the
    data date. Open by default when a file holds several projects."""
    table = store.selection()
    attention = any(len(snapshot.project_task_counts) > 1 for snapshot in store)
    with sidebar.expander(f"Selection · {len(store)} file(s) in series", expanded=attention):
        st.caption(
            "One project per file: the one picked in Project when the file holds it, otherwise the one "
            "with the most TASK rows. Data date: PROJECT.last_recalc_date, else plan_start_date. "
            "One file per data date."
        )
        st.dataframe(
            table.assign(data_date=table["data_date"].map(ui.fmt_date)),
            hide_index=True,
            column_config={
                "file": "File",
                "project": "Project",
                "selected_by": "Picked by",
                "projects_in_file": "Projects in file (TASK rows)",
                "data_date": "Data date",
                "data_date_from": "Data date from",
                "baseline": "Baseline (P6 Project Baseline)",
                "activities": "Activities",
            },
        )


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
    """The Baseline (or marker) the sidebar choice stands for; None when nothing usable."""
    if choice in (BL_PLANNED, BL_EACH):
        return choice  # resolved per snapshot
    if choice == BL_NONE:
        return None
    if choice != BL_FILE:
        return Baseline.from_snapshot(store.by_label(choice), basis)
    upload = None if _data_locked() else sidebar.file_uploader("Baseline .xer", type=UPLOAD_TYPES, key="bl_upload")
    source = (upload.name, upload.getvalue()) if upload is not None else None
    if source is None and env_path and Path(env_path).is_file():
        source = (Path(env_path).name, Path(env_path).read_bytes())
    if source is not None:
        st.session_state["baseline_digest"] = hashlib.sha256(source[1]).hexdigest()
    if source is None:
        if _data_locked():
            sidebar.caption("No baseline file on this server: pick one of the loaded snapshots.")
        else:
            sidebar.caption("Upload the baseline XER, or pick one of the loaded snapshots.")
        return None
    try:
        return Baseline.from_snapshot(_parse(*source), basis)
    except XerError as exc:
        sidebar.error(f"Baseline not read: {exc}")
        return None


def _describe_baseline(sidebar, store: SnapshotStore, baseline: Baseline) -> None:
    sidebar.caption(f"{baseline.label} · {len(baseline.frame)} activities · {baseline.bac_hours:,.0f} labour h")
    baseline_date, first_date = baseline.snapshot.data_date, store.first.data_date
    if baseline_date is not None and first_date is not None and baseline_date > first_date:
        sidebar.warning(
            f"The baseline's data date ({ui.fmt_date(baseline_date)}) is after the first update's "
            f"({ui.fmt_date(first_date)}): "
            "BEI, missed tasks and PV before that date compare against a plan that did not exist yet.",
            icon=":material/warning:",
        )


def _fallback_picker(sidebar, store: SnapshotStore, basis: str) -> None:
    """What an update whose file has no usable baseline is measured against: chosen, never imposed."""
    options = [BL_FILE] + store.labels + [BL_PLANNED, BL_NONE]
    choice = sidebar.selectbox(
        "When a file has no baseline",
        options,
        index=len(options) - 1,
        key="bl_fallback",
        help="Applies update by update: an update uses the baseline of its own file when it has a usable one, "
        "otherwise this. None: the checks that need a baseline are n/a for that update.",
    )
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


MATCH_WARN_BELOW = 0.9  # share of the update's activities the baseline must find


def show_baseline_used(snapshot: Snapshot, baseline: Baseline | None, series: bool = False) -> None:
    """Under a page header: the baseline an update is measured against, and what is wrong with it.
    ``series``: the page measures every update against this baseline (the PV / EV / SPI curves)."""
    stamp = ui.stamp(snapshot.data_date)
    name = ui.md_text(snapshot.source)
    if baseline is None:
        st.markdown(f"**Baseline used for {stamp}**: none")
        return
    st.markdown(f"**Baseline used for {stamp}**: {ui.md_text(baseline.source or baseline.label)}")
    if series and st.session_state.get("baseline") == BL_EACH and len(st.session_state["store"]) > 1:
        st.caption(
            "The PV, EV and SPI curves measure every update against this baseline; the BEI uses each update's own."
        )
    baseline_date = baseline.snapshot.data_date
    if baseline_date is not None and snapshot.data_date is not None and baseline_date > snapshot.data_date:
        st.warning(
            f"{name}: the baseline's data date ({ui.fmt_date(baseline_date)}) is after the update's "
            f"({ui.fmt_date(snapshot.data_date)}): it compares against a plan that did not exist yet.",
            icon=":material/warning:",
        )
    codes = set(snapshot.activities["task_code"])
    matched = len(codes & set(baseline.frame.index))
    if codes and matched / len(codes) < MATCH_WARN_BELOW:
        st.warning(
            f"{name}: the baseline finds {matched} of {len(codes)} activities of the update "
            f"({100 * matched / len(codes):.0f} %, below {MATCH_WARN_BELOW:.0%}). Late activities, BEI and "
            "earned value count the others as not baselined.",
            icon=":material/warning:",
        )


def _baseline_picker(store: SnapshotStore) -> None:
    sidebar = st.sidebar
    sidebar.subheader("Baseline")
    env_path = os.environ.get("XERSCOPE_BASELINE", "")
    in_files = any(snapshot.file_baseline.usable for snapshot in store)
    options = [BL_FILE] + store.labels + [BL_PLANNED, BL_NONE]
    if in_files:
        options.insert(0, BL_EACH)
    # BL_EACH leads the list and is the default, unless a baseline file is named by XERSCOPE_BASELINE
    file_at = 1 if in_files else 0
    choice = sidebar.selectbox(
        "Baseline (BL)",
        options,
        index=0 if in_files and not env_path else file_at + (0 if env_path else 1),
        key="bl_choice",
        help="PV, BEI, missed tasks and late activities are measured against it. "
        "Usually the contract baseline, exported from P6 as its own XER.",
    )
    basis = sidebar.selectbox(
        "Earned value basis",
        list(EV_BASES),
        key="ev_basis",
        index=list(EV_BASES).index(DEFAULT_EV_BASIS),
        format_func=EV_BASIS_LABEL.get,
        help="P6 Admin Preferences > Earned Value > 'When calculating earned value from a baseline use' "
        "(P6 default: budgeted values with planned dates). Set it as in your P6 so PV, EV and BAC match.",
    )
    st.session_state["baseline_digest"] = None  # set again when the choice is a baseline file
    baseline: Baseline | None | str = _baseline_from_choice(sidebar, store, choice, basis, env_path)
    st.session_state["baseline"] = baseline
    st.session_state["fallback"], st.session_state["fallback_choice"] = None, BL_NONE
    if baseline == BL_EACH:
        _fallback_picker(sidebar, store, basis)
    if isinstance(baseline, Baseline):
        _describe_baseline(sidebar, store, baseline)
    if baseline == BL_EACH:
        _file_baseline_warnings(sidebar, store)


def _fallback_baseline(snapshot: Snapshot) -> Baseline | None:
    """The fallback chosen in the sidebar, as it applies to ``snapshot`` (a file with no usable baseline)."""
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


def baseline_for(snapshot: Snapshot) -> Baseline | None:
    """The sidebar's baseline, as it applies to ``snapshot``."""
    baseline = st.session_state.get("baseline")
    if baseline == BL_EACH:
        return _file_baseline(snapshot) or _fallback_baseline(snapshot)
    if baseline == BL_PLANNED:
        return Baseline.planned(snapshot, st.session_state.get("ev_basis", DEFAULT_EV_BASIS))
    return baseline if isinstance(baseline, Baseline) else None


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
            "Load your weekly XER exports from the sidebar (upload or folder path).\n\n"
            "No files yet? Generate a demo set with `uv run xerscope sample --out data/sample`, "
            "then read the folder `data/sample`."
        )
        st.stop()
    return store


def snapshot_picker(store: SnapshotStore, label: str = "Snapshot", key: str = "snap") -> Snapshot:
    labels = store.labels
    choice = st.selectbox(label, labels, index=len(labels) - 1, key=key)
    return store.by_label(choice)


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


def _baseline_identity() -> tuple:
    """What the sidebar's baseline is: the choice, the EV basis and, for an uploaded file, its bytes."""
    baseline = st.session_state.get("baseline")
    if isinstance(baseline, Baseline):
        return baseline.label, baseline.ev_basis, st.session_state.get("baseline_digest")
    if baseline == BL_EACH:  # resolved per snapshot: which project each file names
        store = st.session_state.get("store")
        pointers = tuple((s.source, s.file_baseline.proj_id, s.file_baseline.usable) for s in store or ())
        fallback = (st.session_state.get("fallback_choice"), st.session_state.get("baseline_digest"))
        return baseline, st.session_state.get("ev_basis"), pointers, fallback
    return baseline, st.session_state.get("ev_basis")  # None, or BL_PLANNED (resolved per snapshot)


def memo(key: tuple, function, *arguments):
    """Per-session cache keyed on the loaded files and the baseline: heavy analyses run once per data set.

    ``function(*arguments)`` runs only on a cache miss.
    """
    cache = st.session_state.setdefault("_memo", {})
    # the project picker re-reads the same files for another project: same signature, other data
    store = st.session_state.get("store")
    projects = tuple(snapshot.project_code for snapshot in store) if store is not None else ()
    full_key = (st.session_state.get("signature"), projects, _baseline_identity()) + key
    if full_key not in cache:
        if len(cache) > 64:
            cache.clear()
        cache[full_key] = function(*arguments)
    return cache[full_key]


ANONYMISED = " · anonymised"  # suffix of an anonymised download's label
PREPARE_LABEL = "Prepare anonymised downloads"


def anonymous_exports(session: MutableMapping | None = None) -> bool:
    """The sidebar switch: downloads anonymised (default) or in the files' own names."""
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
    with st.spinner(f"Reading {len(wanted)} file(s) for the anonymised downloads…"):
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
    """The download button of ``fetched`` (labelled anonymised when it is), or the refusal."""
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
    """A table as CSV, anonymised or not as the sidebar switch says; ``sources`` are the files the
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
