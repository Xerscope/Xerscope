"""Baseline resolution, the parse and result memos, and the exports built from them."""

from __future__ import annotations

import os
from dataclasses import replace

import streamlit as st

from xerscope.analysis import Baseline
from xerscope.analysis.baseline import (
    DEFAULT_EV_BASIS,
    KIND_CHOSEN,
    KIND_EXACT,
    KIND_FALLBACK,
    KIND_IN_FILE,
    KIND_NONE,
    KIND_PLANNED,
    KIND_PROBABLE,
    KIND_SERIES,
    baseline_in_file,
    relinked,
)
from xerscope.analysis.baseline_resolution import (
    IN_EXPORT,
    IN_FILE,
    LOADED_UPDATE,
    SAME_GENERATION,
    UNDECIDED,
)
from xerscope.app import ui
from xerscope.app.baseline_export import (
    _read_export_baseline,
    _resolution,
    _xml_baseline_id,
    baseline_export,
    candidates,
    is_undecided,
)
from xerscope.app.baseline_file import _baseline_file_source, baseline_files_tag
from xerscope.app.session import (
    BL_EACH,
    BL_FILE,
    BL_NONE,
    BL_PLANNED,
    _cache_for,
    _data_locked,
    _digest,
    _parse,
)
from xerscope.store import SnapshotStore
from xerscope.xer import Snapshot, XerError, is_pmxml


def _baseline_from_choice(sidebar, store: SnapshotStore, choice: str, basis: str, env_path: str, exports: list[str]):
    """Return the Baseline (or marker) the window's choice stands for; None when nothing usable.

    ``exports``: the names of the folder's P6 XML exports (``_folder_baseline_names``), listed once per run.
    """
    if choice in (BL_PLANNED, BL_EACH):
        return choice  # resolved per snapshot
    if choice == BL_NONE:
        return None
    if choice != BL_FILE:
        return _series(_update_baseline(store, choice, basis), choice)
    source = _baseline_file_source(env_path, exports)
    if source is not None:
        st.session_state["baseline_digest"] = _digest(source[1])
    if source is None:
        how = "Pick a P6 XML file of the folder" if _data_locked() else "Upload the baseline XER (or P6 XML)"
        sidebar.caption(f"{how}, or pick one of the loaded snapshots.")
        return None
    try:
        # a P6 XML export holds the baselines themselves: the one the latest update names, if it is there
        pointer = _xml_baseline_id(source, store.latest.file_baseline.proj_id)
        snapshot = _parse(*source, project_id=pointer)
    except XerError as exc:
        sidebar.error(f"Baseline not read: {ui.md_text(exc)}")
        return None
    if is_pmxml(source[1]):
        sidebar.caption(f"P6 XML baseline {ui.md_text(snapshot.project_code)}")
    return _series(Baseline.from_snapshot(snapshot, basis), choice)


def _series(baseline: Baseline, choice: str) -> Baseline:
    """Return ``baseline`` as the one baseline of the whole series: ``choice`` is BL_FILE or an update's label."""
    return replace(baseline, kind=KIND_SERIES, found_by=choice, source=baseline.label)


def _update_baseline(store: SnapshotStore, choice: str, basis: str) -> Baseline:
    """Return the loaded update ``choice`` as a Baseline on ``basis``, built once per series.

    The sidebar asks for it on every run, whichever page is open.
    """
    cache = _cache_for("_update_baselines", (*data_identity(baseline=False), basis))
    if choice not in cache:
        cache[choice] = Baseline.from_snapshot(store.by_label(choice), basis)
    return cache[choice]


def _fallback_picker(sidebar, store: SnapshotStore, basis: str, exports: list[str]) -> None:
    """Show what an update whose file has no usable baseline is measured against: chosen, never imposed."""
    choice = st.session_state["bl_fallback"]
    # the separate file: uploaded, else named by XERSCOPE_BASELINE (a locked server has only that one)
    env_path = os.environ.get("XERSCOPE_BASELINE", "")
    st.session_state["fallback"] = _baseline_from_choice(sidebar, store, choice, basis, env_path, exports)


PROBABLE = (
    "probable: "  # opens the ``source`` of a baseline that is not the one the update names (``_resolved_baseline``)
)


UNDECIDED_NONE = "none"  # the window's choice for an undecided update: not measured (the default)
UNDECIDED_FALLBACK = "fallback"  # the window's choice for an undecided update: the fallback
CHOSEN_IN_THE_WINDOW = "chosen in the window"


def kind_of(baseline: Baseline | None) -> str:
    """Return how ``baseline`` relates to its update (``analysis.baseline.KIND_*``), "none" without one."""
    return KIND_NONE if baseline is None else baseline.kind


def _fallback_baseline(snapshot: Snapshot) -> Baseline | None:
    """Return the fallback chosen in the window, as it applies to ``snapshot`` (a file with no usable baseline)."""
    fallback, choice = st.session_state.get("fallback"), st.session_state.get("bl_fallback", BL_NONE)
    if fallback == BL_PLANNED:
        built = _planned(snapshot)
        return replace(built, kind=KIND_FALLBACK, found_by=choice, source=f"fallback ({BL_PLANNED})")
    if isinstance(fallback, Baseline):
        what = "separate baseline file" if choice == BL_FILE else "loaded update"
        return replace(fallback, kind=KIND_FALLBACK, found_by=choice, source=f"fallback ({what}): {fallback.label}")
    return None


def _planned(snapshot: Snapshot) -> Baseline:
    """Return the planned dates (target_*) of ``snapshot`` as its baseline, on the EV basis of the window."""
    built = Baseline.planned(snapshot, st.session_state.get("ev_basis", DEFAULT_EV_BASIS))
    return replace(built, kind=KIND_PLANNED, found_by=BL_PLANNED, source=built.label)


def _loaded_update_baseline(snapshot: Snapshot, project_id: str) -> Baseline:
    """Return the last update read from ``project_id``, the project ``snapshot`` names as its baseline.

    As a probable baseline: the same P6 object, in the state it was exported in, not the one it was made a
    baseline in.
    """
    update = [other for other in st.session_state["store"] if other.project_id == project_id][-1]
    built = Baseline.from_snapshot(update, st.session_state.get("ev_basis", DEFAULT_EV_BASIS))
    source = (
        f"{PROBABLE}the project of {update.source}, as exported on {ui.stamp(update.data_date)}, "
        f"which the update names as its baseline ({snapshot.file_baseline.proj_id})"
    )
    return replace(built, kind=KIND_PROBABLE, found_by=LOADED_UPDATE, source=source)


def _resolved_baseline(snapshot: Snapshot) -> Baseline | None:
    """Return the baseline found for an update whose file holds none (``analysis.baseline_resolution``).

    The one the export holds under the id the update names is what P6 measured against. The two others
    are not, and their ``source`` opens with ``PROBABLE`` so that every page, warning and download says
    it: the loaded update whose project the update names as its baseline, and the baseline the versions
    of the export hold before and after the update's project.
    """
    found = _resolution(snapshot)
    if found is None:
        return None
    if found.found_by == LOADED_UPDATE:
        return _loaded_update_baseline(snapshot, found.baseline_id)
    if found.found_by == UNDECIDED:
        return _chosen_baseline(snapshot)
    export = baseline_export()
    if export is None or found.found_by not in (IN_EXPORT, SAME_GENERATION):
        return None
    built = _read_export_baseline(export, found.baseline_id)
    if built is None:
        return None
    code = built.snapshot.project_code
    if found.found_by == IN_EXPORT:
        source = f"P6 Project Baseline {code} from {export[0]}"
        return replace(built, kind=KIND_EXACT, found_by=IN_EXPORT, source=source)
    source = (
        f"{PROBABLE}baseline {code} of {export[0]}, held by the versions created before and after the "
        f"update's project ({found.version_before} and {found.version_after}); the one its file names "
        f"({snapshot.file_baseline.proj_id}) is not in the export"
    )
    return replace(built, kind=KIND_PROBABLE, found_by=SAME_GENERATION, source=source)


def _chosen_baseline(snapshot: Snapshot) -> Baseline | None:
    """Return the baseline the window chose for an undecided update: a candidate, the fallback, or None (the default).

    The versions created around the update's project hold different baselines, so nothing is applied
    until the user picks one of them, or the fallback, in the window's Baseline section.
    """
    choice = st.session_state.get("bl_undecided", {}).get(snapshot.source, UNDECIDED_NONE)
    if choice == UNDECIDED_FALLBACK:
        return _fallback_baseline(snapshot)
    held_by, export = candidates(snapshot), baseline_export()
    if choice not in held_by or export is None:
        return None
    built = _read_export_baseline(export, choice)
    if built is None:
        return None
    source = (
        f"{CHOSEN_IN_THE_WINDOW}: baseline {built.snapshot.project_code} of {export[0]}, held by version "
        f"{held_by[choice]}; the versions around the update's project hold different baselines and the one "
        f"its file names ({snapshot.file_baseline.proj_id}) is not in the export"
    )
    return replace(built, kind=KIND_CHOSEN, found_by=CHOSEN_IN_THE_WINDOW, source=source)


def _file_baseline(snapshot: Snapshot) -> Baseline | None:
    """Return the Baseline built from the project ``snapshot``'s file names as its P6 Project Baseline.

    None when the file names none that can be used (``Snapshot.file_baseline``). Kept for the files and EV
    basis loaded.
    """
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
        built = baseline_in_file(snapshot, data, basis, lambda data, name, project_id: _parse(name, data, project_id))
        if built is None:
            return None
        cache[key] = replace(built, kind=KIND_IN_FILE, found_by=IN_FILE)
    st.session_state["_file_baselines"] = (signature, cache)
    return cache[key]


def baseline_for(snapshot: Snapshot, link: bool | None = None) -> Baseline | None:
    """Return the sidebar's baseline, as it applies to ``snapshot``.

    ``link`` (default: the window's option "Link renumbered tasks by GUID"): with the tasks ``snapshot``
    renumbered under their new IDs. Built once per data set: the banner, the page and each check ask
    for it on every run.
    """
    link = st.session_state.get("guid_link", False) if link is None else link
    cache = _cache_for("_baselines_for", data_identity())
    key = (snapshot.source, link)
    if key not in cache:
        cache[key] = _built_baseline(snapshot, link)
    return cache[key]


def _built_baseline(snapshot: Snapshot, link: bool) -> Baseline | None:
    """Return the sidebar's baseline for ``snapshot``, with its renumbered tasks relinked when ``link``."""
    choice = st.session_state.get("baseline")
    if choice == BL_EACH:
        baseline = _per_file_baseline(snapshot)
    elif choice == BL_PLANNED:
        baseline = _planned(snapshot)
    else:
        baseline = choice if isinstance(choice, Baseline) else None
    return relinked(baseline, snapshot) if link and baseline is not None else baseline


def _per_file_baseline(snapshot: Snapshot) -> Baseline | None:
    """Return the baseline of ``snapshot`` in the per-file mode: its file's, else the one found, else the fallback.

    An undecided update takes no fallback: it is measured once its baseline is chosen in the window.
    """
    baseline = _file_baseline(snapshot) or _resolved_baseline(snapshot)
    if baseline is not None or is_undecided(snapshot):
        return baseline
    return _fallback_baseline(snapshot)


def _baseline_identity(ev_basis: bool = True) -> tuple:
    """Return what the sidebar's baseline is.

    The choice, the EV basis (None when ``ev_basis`` is False) with the GUID link option (always:
    ``baseline_for`` relinks the baseline whatever the analysis reads), and, for an uploaded file, its
    bytes.
    """
    baseline = st.session_state.get("baseline")
    basis = (st.session_state.get("ev_basis") if ev_basis else None, st.session_state.get("guid_link", False))
    if isinstance(baseline, Baseline):
        return baseline.label, basis, st.session_state.get("baseline_digest")
    if baseline == BL_EACH:  # resolved per snapshot: which project each file names
        store = st.session_state.get("store")
        pointers = tuple(
            (snapshot.source, snapshot.file_baseline.proj_id, snapshot.file_baseline.usable) for snapshot in store or ()
        )
        fallback = (st.session_state.get("bl_fallback"), st.session_state.get("baseline_digest"))
        chosen = tuple(sorted(st.session_state.get("bl_undecided", {}).items()))
        export = baseline_files_tag(st.session_state)  # the export the updates are looked for in
        return baseline, basis, pointers, fallback, chosen, export
    return baseline, basis  # None, or BL_PLANNED (resolved per snapshot)


def data_identity(baseline: bool = True, ev_basis: bool = True) -> tuple:
    """Return what a result computed now was computed from.

    The files (``signature``: names and content digests), the project read from each and, unless
    ``baseline`` is False, the baseline in use with (unless ``ev_basis`` is False) the EV basis. The
    memo's key and the tag of a built download start with it.
    """
    # the project pickers re-read the same files for another project: same signature, other data
    store = st.session_state.get("store")
    projects = tuple((snapshot.source, snapshot.project_id) for snapshot in store) if store is not None else ()
    identity = _baseline_identity(ev_basis) if baseline else ()
    return st.session_state.get("signature"), projects, identity


def snapshot_identity(snapshot: Snapshot) -> tuple[str, str]:
    """Return the file and the data date that tell one update from another.

    As the memo keys and the tags of built downloads hold them.
    """
    return snapshot.source, str(snapshot.data_date)
