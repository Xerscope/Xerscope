"""The window's Baseline section: the choices it offers, their names, the per-file table, the undecided updates."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from xerscope.analysis import Baseline
from xerscope.analysis.baseline import EV_BASES, KIND_FALLBACK, KIND_IN_FILE, KIND_NONE
from xerscope.analysis.baseline_resolution import NOT_FOUND
from xerscope.app import ui
from xerscope.app.baseline_export import _is_named_in_export, _resolution, baseline_export, candidates, is_undecided
from xerscope.app.baseline_file import (
    BASELINES_FOLDER,
    _baseline_file_source,
    _folder_baseline_names,
    _is_baseline_file_offered,
    _picked_folder_baseline,
    drafted_baseline_file,
    is_xml_name,
)
from xerscope.app.baselines import UNDECIDED_FALLBACK, UNDECIDED_NONE
from xerscope.app.session import (
    BASELINE_SET,
    BL_EACH,
    BL_FILE,
    BL_NONE,
    BL_PLANNED,
    DRAFTS,
    EV_BASIS_LABEL,
    UPLOAD_TYPES,
    _baseline_upload_key,
    _data_locked,
    _parse,
    _section_title,
)
from xerscope.app.xml_baselines import baseline_per_file
from xerscope.store import SnapshotStore
from xerscope.xer import Snapshot, XerError, is_pmxml


def _fallback_options(store: SnapshotStore, exports: list[str]) -> list[str]:
    """Return what an update whose file has no usable baseline can be measured against.

    A separate file on a locked server only when its folder holds a P6 XML export or XERSCOPE_BASELINE
    names a file (nothing can be uploaded there).
    """
    file_choice = _is_baseline_file_offered(os.environ.get("XERSCOPE_BASELINE", ""), exports)
    return ([BL_FILE] if file_choice else []) + store.labels + [BL_PLANNED, BL_NONE]


def banner_kind(baseline: Baseline | None) -> str:
    """Return where ``baseline`` (``baseline_for`` an update) comes from.

    Its file's P6 Project Baseline, the fallback (``_fallback_baseline`` names it so), planned dates, a
    loaded update, a separate file, none.
    """
    if baseline is None:
        return KIND_NONE
    if baseline.kind == KIND_IN_FILE:  # the checks read the file's own baseline whatever the window chose
        return baseline.kind
    if st.session_state.get("baseline") != BL_EACH:  # one baseline for the series, or the planned dates
        return _baseline_short(st.session_state.get("bl_choice", BL_NONE))
    if baseline.kind == KIND_FALLBACK:
        return f"fallback, {_baseline_short(st.session_state.get('bl_fallback', BL_NONE))}"
    return baseline.kind


def _baseline_options(store: SnapshotStore, env_path: str, exports: list[str]) -> tuple[list[str], str]:
    """Return the choices of "Baseline (BL)" and the default one.

    A separate file is offered when it can be had: uploaded, picked in the folder, or named by
    XERSCOPE_BASELINE on a locked server.
    """
    # an update's own baseline: in its file, or in a P6 XML baseline file holding the one its file names
    source = _baseline_file_source(env_path, exports)
    in_files = any(
        snapshot.file_baseline.usable or _is_named_in_export(source, snapshot.file_baseline.proj_id)
        for snapshot in store
    )
    # an export the updates can be looked for in: the separate file, or one of the folder still to pick
    export_at_hand = (source is not None and is_pmxml(source[1])) or any(map(is_xml_name, exports))
    file_choice = _is_baseline_file_offered(env_path, exports)
    options = ([BL_EACH] if in_files or export_at_hand else []) + ([BL_FILE] if file_choice else []) + store.labels
    options += [BL_PLANNED, BL_NONE]
    # BL_EACH leads the list and is the default, unless a baseline file is named by XERSCOPE_BASELINE
    if in_files and not env_path:
        return options, BL_EACH
    return options, BL_FILE if env_path and file_choice else store.labels[0]


def _baseline_short(choice: str) -> str:
    """Return the sidebar line's name for the baseline in use."""
    if choice == BL_FILE:
        if _picked_folder_baseline() is not None:
            return st.session_state["bl_folder_file"]  # as listed: "baselines/<name>" in the subfolder
        held = None if _data_locked() else st.session_state.get("bl_file")
        env_path = os.environ.get("XERSCOPE_BASELINE", "")
        return held[0] if held else Path(env_path).name if Path(env_path).is_file() else "file missing"
    names = {BL_EACH: "in each file", BL_PLANNED: "planned dates", BL_NONE: "none"}
    # a loaded update: its label starts with its data date
    return names.get(choice, f"update {choice.split(' · ')[0]}")


def _reset_stale_drafts(options: list[str], fallback_options: list[str], folder_files: list[str]) -> None:
    """Start again from the value in force each draft the store no longer offers.

    ``options``: the baselines offered; ``fallback_options``: what a file with no baseline can be measured
    against; ``folder_files``: the names of the baseline files of the folder.
    """
    offered = {
        "draft_bl_choice": options,
        "draft_ev_basis": list(EV_BASES),
        "draft_bl_fallback": fallback_options,
        "draft_bl_folder_file": folder_files,
        "draft_guid_link": [True, False],
    }
    for key, draft in DRAFTS.items():
        # the project of a baseline XER is checked against that file's projects by its own picker
        if draft in offered and st.session_state.get(draft) not in offered[draft]:
            st.session_state[draft] = st.session_state[key]


def _baseline_file_fields(choice: str, folder_files: list[str]) -> None:
    """Show the pickers of a baseline file: the one in the folder, and the upload of a .xer or P6 XML.

    ``choice``: the draft baseline choice. The folder picker serves the separate baseline file and each
    file's own baseline (the file looked for in it); the upload only the separate file.
    """
    wants_file = choice == BL_FILE or (choice == BL_EACH and st.session_state["draft_bl_fallback"] == BL_FILE)
    if (wants_file or choice == BL_EACH) and len(folder_files) > 1:
        st.selectbox(
            "Baseline file in the folder",
            folder_files,
            key="draft_bl_folder_file",
            format_func=lambda name: name or "(none)",
            help="The P6 XML exports placed next to the .xer files (Export > Primavera P6 XML, Baselines to "
            f"Export), and the .xer and P6 XML files of the '{BASELINES_FOLDER}' subfolder, which can carry the "
            "name of an update. The one picked is the separate baseline file; it is never read as an update. With "
            f"'{BL_EACH}', each update is looked for in a P6 XML one: the baseline its file names, else a copy of "
            "it (Debug, block 5).",
        )
    if wants_file and not _data_locked():
        st.file_uploader(
            "Baseline .xer, or a P6 XML export with its baselines",
            type=[*UPLOAD_TYPES, "xml"],
            key=_baseline_upload_key(),
            help="P6 Professional exports a project's baselines in XML only (Export > Primavera P6 XML, "
            "Baselines to Export). Each update is then measured against the baseline its file names.",
        )
        held = st.session_state.get("bl_file")
        if held:
            st.caption(f"Held: {ui.md_text(held[0])}")
    if wants_file:
        _baseline_file_project(folder_files)


def _baseline_file_project(folder_files: list[str]) -> None:
    """Show the project to read from a separate baseline XER that holds several, its default first picked.

    A P6 XML file is read by the baseline the updates name, an XER of one project has nothing to pick.
    """
    source = drafted_baseline_file(folder_files)
    if source is None or is_pmxml(source[1]):
        return
    try:
        snapshot = _parse(*source)
    except XerError:
        return  # the sidebar says why it is not read
    projects = snapshot.file_projects
    if len(projects) < 2:
        return
    codes = dict(zip(projects["proj_id"], projects["proj_short_name"], strict=True))
    if st.session_state.get("draft_bl_file_project") not in codes:
        st.session_state["draft_bl_file_project"] = snapshot.project_id
    st.selectbox(
        "Project read from the baseline file",
        list(codes),
        key="draft_bl_file_project",
        format_func=lambda proj_id: codes[proj_id] or proj_id,
        help="The baseline XER holds several projects (a project and the baselines exported with it): the one "
        "picked is the baseline. By default, the project the file is read for when no choice is made.",
    )


def _baseline_fields(store: SnapshotStore) -> None:
    """Show the window's Baseline section.

    The selectors the sidebar held, same choices, on drafts (DRAFTS) that Done applies.
    """
    exports = _folder_baseline_names()
    options, _ = _baseline_options(store, os.environ.get("XERSCOPE_BASELINE", ""), exports)
    fallback_options = _fallback_options(store, exports)
    folder_files = ["", *exports]  # "": none picked
    _reset_stale_drafts(options, fallback_options, folder_files)
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
        "(P6 default: budgeted values with planned dates). Set it as in your P6 so PV, EV and BAC match. "
        "It also sets the dates of a separate baseline (P6's BL Project Start / Finish): its planned dates, "
        "or its current dates with the two 'current dates' options.",
    )
    st.checkbox(
        "Link renumbered tasks by GUID",
        key="draft_guid_link",
        help="A task of an update that carries a baseline task's GUID (TASK.guid) under a new Task ID is "
        "measured against that baseline task, as P6 does when the renumbering was carried to the baseline "
        "(Renumber Activity IDs > Renumber Selected Activities in Baselines). Off: it counts as deleted and "
        "new, as P6 does otherwise.",
    )
    choice = st.session_state["draft_bl_choice"]
    if choice == BL_EACH:
        _fallback_fields(store, fallback_options)
    if st.session_state.get(BASELINE_SET):  # before the first Done nothing is read for the baseline
        _baseline_per_file(store)
    _baseline_file_fields(choice, folder_files)


def _fallback_fields(store: SnapshotStore, fallback_options: list[str]) -> None:
    """Show the per-file mode's own fields: the fallback, then the choice of each undecided update."""
    st.selectbox(
        "When a file has no baseline",
        fallback_options,
        key="draft_bl_fallback",
        help="Applies update by update: an update uses the baseline of its own file when it has a usable "
        "one, otherwise this. None: the checks that need a baseline are n/a for that update.",
    )
    if st.session_state.get(BASELINE_SET):
        _undecided_fields(store)


def _undecided_fields(store: SnapshotStore) -> None:
    """Show, for each undecided update, the choice of its baseline: a candidate of the export, the fallback, none."""
    for snapshot in store:
        held_by = candidates(snapshot)
        if is_undecided(snapshot) and held_by:
            _undecided_box(snapshot, held_by)


def _undecided_box(snapshot: Snapshot, held_by: dict[str, str]) -> None:
    """Show the selector of one undecided update: ``held_by`` is baseline id -> the version of the export holding it."""
    options = [UNDECIDED_NONE, *held_by, UNDECIDED_FALLBACK]
    labels = {UNDECIDED_NONE: "None: not measured", UNDECIDED_FALLBACK: "The fallback above"}
    labels.update({held: f"Baseline {held}, held by version {version}" for held, version in held_by.items()})
    key = f"draft_bl_undecided:{snapshot.source}"
    if st.session_state.get(key) not in options:
        st.session_state[key] = st.session_state.get("bl_undecided", {}).get(snapshot.source, UNDECIDED_NONE)
    st.selectbox(
        f"Baseline of {snapshot.source} (undecided)",
        options,
        key=key,
        format_func=labels.__getitem__,
        help="The baseline this file names is not in the export, and the versions of the export created just "
        "before and just after its project hold different baselines: xerscope does not guess. The one you "
        "pick is applied as a probable baseline, said so on every page and in every download.",
    )


def _fallback_label() -> str:
    """Return the fallback in force as the window's table names it, blank for none."""
    fallback = st.session_state.get("fallback")
    if fallback is None:
        return ""
    return BL_PLANNED if fallback == BL_PLANNED else fallback.label


def _per_file_caption(table: pd.DataFrame) -> str:
    """Return the caption of the window's per-file table.

    The baselines in force in the per-file mode, or what that mode would give beside the single baseline
    in force; and, without an export, why most updates have none.
    """
    choice = st.session_state.get("baseline")
    if choice == BL_EACH:
        caption = "Baseline of each update, as in force now (Done applies the choices above)."
    elif isinstance(choice, Baseline) or choice == BL_PLANNED:
        in_force = BL_PLANNED if choice == BL_PLANNED else choice.label
        caption = (
            f"In force: every update is measured against {in_force}. Below, the baseline each file names and "
            f"what '{BL_EACH}' would give it."
        )
    else:
        caption = f"In force: no baseline. Below, the baseline each file names and what '{BL_EACH}' would give it."
    without = int((table["found_by"] == NOT_FOUND).sum())
    if without and baseline_export() is None:
        caption += (
            f" {without} of {len(table)} have none: P6 writes no baseline in an XER. Put the P6 XML export "
            "of the baselines (Export > Primavera P6 XML, Baselines to Export) next to the files."
        )
    return caption


def _baseline_per_file(store: SnapshotStore) -> None:
    """Show the window's table of the baseline each update names and is, or would be, measured against.

    In the per-file mode (``xml_baselines.baseline_per_file``), with the fallback and the baselines of the
    export that could not be read. Drawn by ``ui.table``, which labels and formats its columns.
    """
    found = {snapshot.source: _resolution(snapshot) for snapshot in store}
    unreadable = frozenset(st.session_state.get("_export_read_errors", {}))
    chosen = {name: pick for name, pick in st.session_state.get("bl_undecided", {}).items() if pick != UNDECIDED_NONE}
    table = baseline_per_file(store, found, _fallback_label(), unreadable, chosen)
    st.caption(_per_file_caption(table))
    labels = {"names": "Names (sum_base_proj_id)", "measured_against": "Measured against", "found_by": "Found"}
    overrides = {name: st.column_config.TextColumn(label) for name, label in labels.items()}
    ui.table(table, key="baseline_per_file", overrides=overrides)
