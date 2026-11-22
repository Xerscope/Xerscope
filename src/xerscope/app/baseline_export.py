"""The P6 XML export of baselines in use: its index, what the resolution reads of it, the baselines read from it."""

from __future__ import annotations

import functools

import streamlit as st

from xerscope.analysis import Baseline
from xerscope.analysis.baseline import DEFAULT_EV_BASIS
from xerscope.analysis.baseline_resolution import UNDECIDED, Export, Resolution, resolutions
from xerscope.app.baseline_file import baseline_items
from xerscope.app.session import _digest, _parse, _pmxml_index
from xerscope.app.xml_baselines import export_of
from xerscope.xer import Snapshot, XerError, is_pmxml
from xerscope.xer.pmxml import DiskFile, PmxmlIndex


def _xml_baseline_id(source: tuple[str, bytes | DiskFile], pointer: str | None) -> str | None:
    """Return ``pointer`` (an update's sum_base_proj_id) when the P6 XML baseline file holds that baseline, else None.

    The file's Project Baseline is read. None for an XER file.
    """
    name, data = source
    if not pointer or not is_pmxml(data):
        return None
    return pointer if pointer in _pmxml_index(name, data).baseline_spans else None


def is_undecided(snapshot: Snapshot) -> bool:
    """Tell whether the resolution left ``snapshot`` undecided: the versions around it hold different baselines."""
    found = _resolution(snapshot)
    return found is not None and found.found_by == UNDECIDED


def candidates(snapshot: Snapshot) -> dict[str, str]:
    """Return the baselines an undecided update can be measured against: baseline id -> the version holding it."""
    found, export = _resolution(snapshot), export_contents()
    if found is None or export is None:
        return {}
    versions = (found.version_before, found.version_after)
    return {export.project_baselines[version]: version for version in versions if version in export.project_baselines}


def _is_named_in_export(source: tuple[str, bytes | DiskFile] | None, pointer: str) -> bool:
    """Return whether the separate baseline file is a P6 XML export that holds the baseline ``pointer`` names.

    An export that cannot be read holds none (the sidebar says so where it is used).
    """
    try:
        return source is not None and _xml_baseline_id(source, pointer) is not None
    except XerError:
        return False


def _resolution(snapshot: Snapshot) -> Resolution | None:
    """Return what ``analysis.baseline_resolution`` finds for an update of the series read; None outside it.

    Found once for the series, its projects and the export in use.
    """
    store = st.session_state.get("store")
    if store is None:
        return None
    export = baseline_export()
    projects = tuple((update.source, update.project_id, update.file_baseline.proj_id) for update in store)
    key = (st.session_state.get("signature"), projects, None if export is None else _digest(export[1]))
    kept = st.session_state.get("_resolutions")
    if kept is None or kept[0] != key:
        found = resolutions(store, export_contents())
        kept = (key, {update.source: one for update, one in zip(store, found, strict=True)})
        st.session_state["_resolutions"] = kept
        st.session_state["_export_read_errors"] = {}  # the baselines of another export, or another series
    return kept[1].get(snapshot.source)


def _export_baseline(export: tuple[str, bytes | DiskFile, PmxmlIndex], object_id: str) -> Baseline:
    """Return one baseline of the export in use, by ObjectId, on the EV basis of the window.

    Built once per file content, baseline and basis (``baseline_for`` asks for it on every page and
    rerun).
    """
    name, data, _ = export
    basis = st.session_state.get("ev_basis", DEFAULT_EV_BASIS)
    cache = st.session_state.setdefault("_xml_baselines", {})
    key = (name, _digest(data), object_id, basis)
    if key not in cache:
        if len(cache) > 64:
            cache.clear()
        cache[key] = Baseline.from_snapshot(_parse(name, data, project_id=object_id), basis)
    return cache[key]


def _read_export_baseline(export: tuple[str, bytes | DiskFile, PmxmlIndex], baseline_id: str) -> Baseline | None:
    """Return one baseline of the export (``_export_baseline``); None, recorded for the sidebar, if unreadable."""
    try:
        return _export_baseline(export, baseline_id)
    except XerError as exc:  # this update has none, the sidebar says why
        st.session_state.setdefault("_export_read_errors", {})[baseline_id] = str(exc)
        return None


def baseline_export() -> tuple[str, bytes | DiskFile, PmxmlIndex] | None:
    """Return the separate baseline file in use when it is a P6 XML export that can be read.

    Its name, its contents and the session's index of it. None for an XER, for no file, and for an export
    that cannot be read (the sidebar says so).
    """
    return _export_in_use()[0]


def export_contents() -> Export | None:
    """Return what the resolution reads of the export in use (``xml_baselines.export_of``); None without one.

    Kept for the session with the content digests found so far, and read through the session's own reader:
    the pages and the Debug page compare and apply the baselines of the export from one read of each.
    """
    export = baseline_export()
    if export is None:
        return None
    name, data, index = export
    key = (name, _digest(data))
    kept = st.session_state.get("_export_contents")
    if kept is None or kept[0] != key:
        kept = (key, export_of(name, data, index, functools.partial(_parse, name, data)))
        st.session_state["_export_contents"] = kept
    return kept[1]


def _export_in_use() -> tuple[tuple[str, bytes | DiskFile, PmxmlIndex] | None, str]:
    """Return ``baseline_export`` and, when the export in use cannot be read, why (blank otherwise)."""
    for name, data in baseline_items(st.session_state):
        if is_pmxml(data):
            try:
                return (name, data, _pmxml_index(name, data)), ""
            except XerError as exc:
                return None, str(exc)
    return None, ""
