"""Data loading shared by every page: sidebar inputs -> SnapshotStore in session state."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from xerscope.analysis import Baseline, Standard, discover_standards
from xerscope.analysis.baseline import DEFAULT_EV_BASIS, EV_BASES
from xerscope.store import SnapshotStore
from xerscope.xer import XER_SUFFIXES, Snapshot, XerError, load_snapshot, xer_files

# Streamlit wants extensions without the dot.
UPLOAD_TYPES = [suffix.lstrip(".") for suffix in XER_SUFFIXES]


def _parse(name: str, data: bytes, project: str | None = None) -> Snapshot:
    """Parse once per session, keyed on content. The cache lives in the session's state, never in a
    process-wide cache: when the session ends (server.disconnectedSessionTTL after the tab closes),
    nothing of the files it read stays in the server."""
    cache = st.session_state.setdefault("_parsed", {})
    key = (name, hashlib.sha256(data).hexdigest(), project)
    if key not in cache:
        if len(cache) > 64:
            cache.clear()
        cache[key] = load_snapshot(data, project_code=project, name=name)
    return cache[key]


def _build(items: list[tuple[str, bytes]], project: str | None = None) -> tuple[SnapshotStore | None, list[str]]:
    snapshots, errors = [], []
    for name, data in items:
        try:
            snapshot = _parse(name, data, project)
        except XerError as exc:
            errors.append(str(exc))
            continue
        if snapshot.data_date is None:
            errors.append(f"{name}: no data date (PROJECT.last_recalc_date); the file is skipped")
            continue
        snapshots.append(snapshot)
    return (SnapshotStore(snapshots) if snapshots else None), errors


def _items_from_uploads(uploads) -> tuple[tuple, list[tuple[str, bytes]] | None]:
    """Signature of the uploaded files, and their contents when they changed since last run."""
    # keyed on content, so a corrected file of the same name and size is read again
    signature = ("upload",) + tuple(
        sorted((upload.name, hashlib.sha256(upload.getvalue()).hexdigest()) for upload in uploads)
    )
    if signature == st.session_state.get("signature"):
        return signature, None
    return signature, [(upload.name, upload.getvalue()) for upload in uploads]


def _items_from_folder(sidebar, folder: str) -> tuple[tuple, list[tuple[str, bytes]] | None, bool]:
    """Signature of the folder's XER files, their contents when changed, and whether the folder is usable."""
    root = Path(folder).expanduser()
    files = xer_files(root) if root.is_dir() else []
    if not files:
        sidebar.error("Folder not found" if not root.is_dir() else "No .xer file in that folder")
        st.session_state.update(store=None, signature=(), errors=[])
        return (), None, False
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


def sidebar_loader() -> None:
    sidebar = st.sidebar
    sidebar.subheader("Weekly XER exports")
    uploads = sidebar.file_uploader("Upload .xer files", type=UPLOAD_TYPES, accept_multiple_files=True)
    if os.environ.get("XERSCOPE_DATA_LOCKED", "").lower() in ("1", "true", "yes"):
        # Remote deployment: the folder is the server's, a visitor cannot point the app elsewhere.
        folder = os.environ.get("XERSCOPE_DATA", "")
        sidebar.caption("…or the exports folder of this server")
    else:
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
            f"{store.first.data_date:%d %b %Y} → {store.latest.data_date:%d %b %Y}"
        )
    for error in st.session_state.get("errors", []):
        sidebar.error(error)
    if store is not None:
        _baseline_picker(store)


BL_NONE = "None"
BL_PLANNED = "Planned dates in each file (target_*)"
BL_FILE = "Separate baseline file"


EV_BASIS_LABEL = {
    "budgeted_planned": "Budgeted · planned dates",
    "budgeted_current": "Budgeted · current dates",
    "at_completion_current": "At completion · current dates",
}


def _baseline_from_choice(sidebar, store: SnapshotStore, choice: str, basis: str, env_path: str):
    """The Baseline (or marker) the sidebar choice stands for; None when nothing usable."""
    if choice == BL_PLANNED:
        return BL_PLANNED  # resolved per snapshot
    if choice == BL_NONE:
        return None
    if choice != BL_FILE:
        return Baseline.from_snapshot(store.by_label(choice), basis)
    upload = sidebar.file_uploader("Baseline .xer", type=UPLOAD_TYPES, key="bl_upload")
    source = (upload.name, upload.getvalue()) if upload is not None else None
    if source is None and env_path and Path(env_path).is_file():
        source = (Path(env_path).name, Path(env_path).read_bytes())
    if source is None:
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
            f"The baseline's data date ({baseline_date:%d %b %Y}) is after the first update's ({first_date:%d %b %Y}): "
            "BEI, missed tasks and PV before that date compare against a plan that did not exist yet.",
            icon=":material/warning:",
        )


def _baseline_picker(store: SnapshotStore) -> None:
    sidebar = st.sidebar
    sidebar.subheader("Baseline")
    env_path = os.environ.get("XERSCOPE_BASELINE", "")
    options = [BL_FILE] + store.labels + [BL_PLANNED, BL_NONE]
    choice = sidebar.selectbox(
        "Baseline (BL)",
        options,
        index=0 if env_path else 1,
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
    baseline: Baseline | None | str = _baseline_from_choice(sidebar, store, choice, basis, env_path)
    st.session_state["baseline"] = baseline
    if isinstance(baseline, Baseline):
        _describe_baseline(sidebar, store, baseline)


def baseline_for(snapshot: Snapshot) -> Baseline | None:
    """The sidebar's baseline, as it applies to ``snapshot``."""
    baseline = st.session_state.get("baseline")
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


def is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


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
    return chosen.activities, f"{chosen.data_date:%Y-%m-%d}"


def memo(key: tuple, function, *arguments):
    """Per-session cache keyed on the loaded files: heavy analyses run once per data set.

    ``function(*arguments)`` runs only on a cache miss.
    """
    cache = st.session_state.setdefault("_memo", {})
    full_key = (st.session_state.get("signature"),) + key
    if full_key not in cache:
        if len(cache) > 64:
            cache.clear()
        cache[full_key] = function(*arguments)
    return cache[full_key]
