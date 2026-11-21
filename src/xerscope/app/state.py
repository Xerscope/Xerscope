"""Data loading shared by every page: sidebar inputs -> SnapshotStore in session state."""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from xerscope.analysis import Baseline, Standard, discover_standards
from xerscope.analysis.baseline import DEFAULT_EV_BASIS, KIND_CHOSEN, KIND_PROBABLE
from xerscope.analysis.wbs import ROOT
from xerscope.app import ui
from xerscope.app.baseline_export import is_undecided
from xerscope.app.baseline_warnings import MATCH_WARN_BELOW
from xerscope.app.baseline_window import banner_kind
from xerscope.app.baselines import baseline_for
from xerscope.app.downloads import (
    costs_shown,
)
from xerscope.app.loading import (
    LoadJob,
    _files_count,
)
from xerscope.app.session import (
    BASELINE_SET,
    BL_EACH,
    BL_FILE,
    COMPARE_BL,
    COMPARE_FIRST,
    COMPARE_NONE,
    COMPARE_PREV,
    EV_BASIS_LABEL,
    SNAP_CHOICE,
    _open_window,
)
from xerscope.store import SnapshotStore
from xerscope.xer import Snapshot


def context_banner(store: SnapshotStore, snapshot: Snapshot) -> None:
    """Show one line under a page title.

    What the page is computed from (projects read, data date of the update shown, the baseline
    ``baseline_for`` gives it, EV basis, costs, files), the baseline's source in full in the help.
    Pressing it opens the Files and baseline window.
    """
    codes = list(dict.fromkeys(update.project_code for update in store))
    projects = " + ".join(ui.md_text(code) for code in codes[:3]) + (f" +{len(codes) - 3}" if len(codes) > 3 else "")
    baseline = baseline_for(snapshot)
    kind = banner_kind(baseline)
    basis = EV_BASIS_LABEL[st.session_state.get("ev_basis", DEFAULT_EV_BASIS)]
    costs = "on" if costs_shown() else "off"
    label = (
        f"{projects} · status date {ui.fmt_date(snapshot.data_date)} · BL {ui.md_text(kind)} · "
        f"EV {basis.lower().replace(' · ', ', ')} · costs {costs} · {_files_count(store)}"
    )
    used = ui.md_text(baseline.source or baseline.label) if baseline is not None else ui.md_text(kind)
    details = [
        f"Project(s) read: {', '.join(ui.md_text(code) for code in codes)}",
        f"Status date of the update shown: {ui.fmt_date(snapshot.data_date)} ({ui.md_text(snapshot.source)})",
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
    if baseline is not None and baseline.kind in (KIND_PROBABLE, KIND_CHOSEN):
        st.warning(f"Baseline of this update: {used}.", icon=":material/warning:")


def page_header(title: str, store: SnapshotStore, snapshot: Snapshot | None = None, lead: str = "") -> None:
    """Show the page title, the context banner for ``snapshot`` (default: the latest update), then an optional lead."""
    st.title(title)
    context_banner(store, snapshot or store.latest)
    if lead:
        st.caption(lead)


def _what_to_do(snapshot: Snapshot) -> str:
    """Return what measures an update of the per-file mode that has no baseline, for the page's note."""
    if is_undecided(snapshot):
        return "choose one of its candidate baselines, or the fallback, in the Baseline window"
    if st.session_state.get("bl_fallback") == BL_FILE:
        return (
            "put the P6 XML export of the baselines next to the files, or upload it, "
            "under 'When a file has no baseline'"
        )
    return "pick what applies instead under 'When a file has no baseline' (the sidebar's Baseline line)"


def baseline_warnings(snapshot: Snapshot, baseline: Baseline | None, series: bool = False) -> None:
    """Show, under a page header, what is wrong with the baseline an update is measured against.

    ``series``: the page measures every update against this baseline (the PV / EV / SPI curves).
    """
    name = ui.md_text(snapshot.source)
    if baseline is None:
        if st.session_state.get("baseline") == BL_EACH:
            st.info(
                f"{name}: {ui.md_text(snapshot.file_baseline.text)}. To measure this update, {_what_to_do(snapshot)}."
            )
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
    matched = len(codes) - len(baseline.unbaselined(snapshot))
    if codes and matched / len(codes) < MATCH_WARN_BELOW:
        st.warning(
            f"{name}: the baseline finds {matched} of {len(codes)} tasks of the update "
            f"({100 * matched / len(codes):.0f} %, below {MATCH_WARN_BELOW:.0%}). Late tasks, BEI and "
            "earned value count the others as not baselined.",
            icon=":material/warning:",
        )


def standards() -> dict[str, Standard]:
    """Return the built-in standards, files in XERSCOPE_STANDARDS and any uploaded this session."""
    extra_folder = os.environ.get("XERSCOPE_STANDARDS", "")
    found, errors = discover_standards(*([extra_folder] if extra_folder else []))
    found.update(st.session_state.get("uploaded_standards", {}))
    st.session_state["standard_errors"] = errors
    return found


def _page_title() -> str:
    """Return the title of the page being drawn (st.navigation's), "" when Streamlit's registry does not give it.

    An internal API, so a change of Streamlit only drops the title of the empty state.
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return ctx.pages_manager.get_pages()[ctx.page_script_hash]["page_name"]
    except (ImportError, AttributeError, KeyError):
        return ""


def require_store() -> SnapshotStore:
    """Return the series read, or show the empty state.

    The page's title, so the viewer knows where they are, and what to do, then the page stops.
    """
    store = st.session_state.get("store")
    job: LoadJob | None = st.session_state.get("_load_job")
    if store is None and job is not None:
        st.info(
            f"Reading {len(job.items)} updates… The page draws once the whole series is read "
            "(progress in the sidebar).",
            icon=":material/hourglass_top:",
        )
        st.stop()
    if store is not None and not st.session_state.get(BASELINE_SET):
        title = _page_title()
        if title:
            st.title(title)
        st.info(
            f"{_files_count(store)} read. Choose the baseline in the window (the sidebar's Baseline line "
            "opens it again), then Done: the pages are computed once, against it.",
            icon=":material/rule:",
        )
        st.stop()
    if store is None:
        title = _page_title()
        if title:
            st.title(title)
        st.info(
            "Load your weekly XER exports from the sidebar's Files line (upload or folder path).\n\n"
            "No files yet? Generate a demo set with `uv run xerscope sample --out data/sample`, "
            "then read the folder `data/sample`."
        )
        st.stop()
    return store


def _follow_snapshot(key: str) -> None:
    st.session_state[SNAP_CHOICE] = st.session_state[key]


def snapshot_picker(store: SnapshotStore, label: str = "Snapshot", key: str = "snap") -> Snapshot:
    """Return the update a page works on.

    One choice for the whole session (``SNAP_CHOICE``): picked on Schedule health, the Gantt opens on the
    same update; the latest update until one is picked.
    """
    labels = store.labels
    wanted = st.session_state.get(SNAP_CHOICE)
    st.session_state[key] = wanted if wanted in labels else labels[-1]
    choice = st.selectbox(label, labels, key=key, on_change=_follow_snapshot, args=(key,))
    return store.by_label(choice)


def go_to(page: str, **state) -> None:
    """Open another page with ``state`` written to the session first.

    The page's widgets read it (``views/gantt.py``, ``gantt_task=...``). Pages are named by their path
    under app/.
    """
    st.session_state.update(state)
    st.switch_page(f"views/{page}.py")


def open_in_gantt(task_code: str, snapshot: Snapshot | None = None) -> None:
    """Open the Gantt on ``task_code`` (its card and history under the chart).

    On ``snapshot``'s update when given, the whole project in view and no filter. Passed to
    ``ui.table(open_task=...)``.
    """
    state = {"gantt_task": task_code, "gantt_node": ROOT, "gantt_focus": None}
    if snapshot is not None:
        state[SNAP_CHOICE] = snapshot.label
    go_to("gantt", **state)


def compare_picker(store: SnapshotStore, current: Snapshot, key: str = "cmp") -> tuple[pd.DataFrame | None, str]:
    """Return the activities (task_code, start, finish, …) to outline the current bars against."""
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
