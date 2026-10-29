"""Data loading shared by every page: sidebar inputs -> SnapshotStore in session state."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from xerscope.analysis import Baseline, Standard, discover_standards
from xerscope.analysis.baseline import DEFAULT_EV_BASIS, EV_BASES
from xerscope.store import SnapshotStore
from xerscope.xer import Snapshot, XerError, build_snapshot, parse_bytes


@st.cache_data(show_spinner=False, max_entries=512)
def _parse(name: str, data: bytes) -> Snapshot:
    # Cached on file content: re-opening the same week's export is free.
    return build_snapshot(parse_bytes(data, source=name))


def _build(items: list[tuple[str, bytes]]) -> tuple[SnapshotStore | None, list[str]]:
    snaps, errors = [], []
    for name, data in items:
        try:
            snaps.append(_parse(name, data))
        except XerError as exc:
            errors.append(str(exc))
    return (SnapshotStore(snaps) if snaps else None), errors


def sidebar_loader() -> None:
    sb = st.sidebar
    sb.subheader("Weekly XER exports")
    uploads = sb.file_uploader("Upload .xer files", type=["xer"], accept_multiple_files=True)
    folder = sb.text_input(
        "…or read a folder", value=os.environ.get("XERSCOPE_DATA", ""), placeholder="/path/to/exports"
    )

    items: list[tuple[str, bytes]] | None = None
    signature: tuple = ()
    if uploads:
        signature = ("upload",) + tuple(sorted((f.name, f.size) for f in uploads))
        if signature != st.session_state.get("signature"):
            items = [(f.name, f.getvalue()) for f in uploads]
    elif folder:
        root = Path(folder).expanduser()
        if not root.is_dir():
            sb.error("Folder not found")
            return
        files = sorted(root.glob("*.xer"))
        signature = ("folder", str(root)) + tuple((p.name, p.stat().st_mtime_ns) for p in files)
        if signature != st.session_state.get("signature"):
            items = [(p.name, p.read_bytes()) for p in files]

    if items is not None:
        with st.spinner(f"Parsing {len(items)} file(s)…"):
            store, errors = _build(items)
        st.session_state.update(store=store, signature=signature, errors=errors)
    elif not uploads and not folder:
        st.session_state.update(store=None, signature=(), errors=[])

    store: SnapshotStore | None = st.session_state.get("store")
    if store is not None:
        sb.caption(
            f"{store.latest.project_code} · {len(store)} snapshot(s) · "
            f"{store.first.data_date:%d %b %Y} → {store.latest.data_date:%d %b %Y}"
        )
    for err in st.session_state.get("errors", []):
        sb.error(err)
    if store is not None:
        _baseline_picker(store)


BL_NONE = "None"
BL_PLANNED = "Planned dates in each file (target_*)"
BL_FILE = "Separate baseline file"


def _baseline_picker(store: SnapshotStore) -> None:
    sb = st.sidebar
    sb.subheader("Baseline")
    env_path = os.environ.get("XERSCOPE_BASELINE", "")
    options = [BL_FILE] + store.labels + [BL_PLANNED, BL_NONE]
    default = 0 if env_path else 1
    choice = sb.selectbox(
        "Baseline (BL)",
        options,
        index=default,
        key="bl_choice",
        help="PV, BEI, missed tasks and late activities are measured against it. "
        "Usually the contract baseline, exported from P6 as its own XER.",
    )
    short = {
        "budgeted_planned": "Budgeted · planned dates",
        "budgeted_current": "Budgeted · current dates",
        "at_completion_current": "At completion · current dates",
    }
    basis = sb.selectbox(
        "Earned value basis",
        list(EV_BASES),
        key="ev_basis",
        index=list(EV_BASES).index(DEFAULT_EV_BASIS),
        format_func=short.get,
        help="P6 Admin Preferences > Earned Value > 'When calculating earned value from a baseline use' "
        "(P6 default: budgeted values with planned dates). Set it as in your P6 so PV, EV and BAC match.",
    )
    bl: Baseline | None | str = None
    if choice == BL_FILE:
        up = sb.file_uploader("Baseline .xer", type=["xer"], key="bl_upload")
        if up is not None:
            bl = Baseline.from_snapshot(_parse(up.name, up.getvalue()), basis)
        elif env_path and Path(env_path).is_file():
            p = Path(env_path)
            bl = Baseline.from_snapshot(_parse(p.name, p.read_bytes()), basis)
        else:
            sb.caption("Upload the baseline XER, or pick one of the loaded snapshots.")
    elif choice == BL_PLANNED:
        bl = BL_PLANNED  # resolved per snapshot
    elif choice != BL_NONE:
        bl = Baseline.from_snapshot(store.by_label(choice), basis)
    st.session_state["baseline"] = bl
    if isinstance(bl, Baseline):
        sb.caption(f"{bl.label} · {len(bl.frame)} activities · {bl.bac_hours:,.0f} labour h")


def baseline_for(snap: Snapshot) -> Baseline | None:
    """The sidebar's baseline, as it applies to ``snap``."""
    bl = st.session_state.get("baseline")
    if bl == BL_PLANNED:
        return Baseline.planned(snap, st.session_state.get("ev_basis", DEFAULT_EV_BASIS))
    return bl if isinstance(bl, Baseline) else None


def standards() -> dict[str, Standard]:
    """Built-in standards, files in XERSCOPE_STANDARDS and any uploaded this session."""
    found, errors = discover_standards(*[d for d in [os.environ.get("XERSCOPE_STANDARDS", "")] if d])
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
        prev = store.previous(current)
        return (prev.activities if prev is not None else None), "previous update"
    if choice == COMPARE_BL:
        bl = baseline_for(current)
        if bl is None:
            return None, ""
        f = bl.frame.rename(columns={"bl_start": "start", "bl_finish": "finish"}).reset_index()
        return f, "baseline"
    if choice == COMPARE_FIRST:
        return (store.first.activities if store.first is not current else None), "first snapshot"
    snap = store.by_label(choice)
    return snap.activities, f"{snap.data_date:%Y-%m-%d}"


def memo(key: tuple, fn):
    """Per-session cache keyed on the loaded files: heavy analyses run once per data set."""
    cache = st.session_state.setdefault("_memo", {})
    full = (st.session_state.get("signature"),) + key
    if full not in cache:
        if len(cache) > 64:
            cache.clear()
        cache[full] = fn()
    return cache[full]
