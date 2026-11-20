"""Baseline resolution, the parse and result memos, and the exports built from them."""

from __future__ import annotations

import functools
import os
import threading
from collections.abc import MutableMapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import streamlit as st

from xerscope.analysis import AnalysisContext, Baseline, Standard
from xerscope.analysis.baseline import (
    DEFAULT_EV_BASIS,
    EV_BASES,
    absent_project_baselines,
    baseline_in_file,
    other_project_baselines,
    project_codes,
    relinked,
    renumbered,
    uses_project_baseline,
)
from xerscope.analysis.baseline_resolution import (
    IN_EXPORT,
    LOADED_UPDATE,
    SAME_GENERATION,
    UNDECIDED,
    Export,
    Resolution,
    resolutions,
)
from xerscope.analysis.checks import CheckResult, run_metric, run_standard
from xerscope.analysis.standards import Metric
from xerscope.app import ui
from xerscope.app.session import (
    BASELINE_ALONE,
    BASELINE_ASKED,
    BASELINE_SET,
    BL_EACH,
    BL_FILE,
    BL_NONE,
    BL_PLANNED,
    DRAFTS,
    EV_BASIS_LABEL,
    UPLOAD_TYPES,
    _data_locked,
    _digest,
    _open_window,
    _section_title,
    counted,
)
from xerscope.app.xml_baselines import export_of
from xerscope.store import SnapshotStore
from xerscope.xer import Snapshot, XerError, baseline_copies, is_pmxml, load_snapshot, pmxml_files
from xerscope.xer.pmxml import DiskFile, PmxmlIndex, index_pmxml


def _parse(name: str, data: bytes | DiskFile, project_id: str | None = None) -> Snapshot:
    """Parse once per session, keyed on content.

    The cache lives in the session's state, never in a process-wide cache: when the session ends
    (server.disconnectedSessionTTL after the tab closes), nothing of the files it read stays in the
    server.
    """
    cache = st.session_state.setdefault("_parsed", {})
    key = (name, _digest(data), project_id)
    if key not in cache:
        if len(cache) > 64:
            cache.clear()
        index = _pmxml_index(name, data) if is_pmxml(data) else None
        cache[key] = load_snapshot(data, name=name, project_id=project_id, pmxml_index=index)
    return cache[key]


def _ask_for_the_baseline() -> None:
    """Open the window on its Baseline section, once per choice of files, until Done sets the baseline."""
    if not st.session_state.get(BASELINE_SET) and not st.session_state.get(BASELINE_ASKED):
        st.session_state[BASELINE_ASKED] = True
        _open_window(BASELINE_ALONE)


def _project_labels(snapshot: Snapshot) -> dict[str, str]:
    """Return the projects of ``snapshot``'s file that own activities, by proj_id, in file order.

    Code, data date, activities and, for a baseline copy, the project it is the baseline of.
    """
    table = snapshot.file_projects
    codes = dict(zip(table["proj_id"], table["proj_short_name"], strict=True))
    copies = baseline_copies(table)
    labels = {}
    for _, row in table[table["tasks"] > 0].iterrows():
        label = f"{row['proj_short_name']} · {ui.fmt_date(row['data_date'])} · {row['tasks']} tasks"
        if row["proj_id"] in copies:
            label += f" · baseline of {codes[copies[row['proj_id']]]}"
        labels[row["proj_id"]] = label
    return labels


def _baseline_from_choice(sidebar, store: SnapshotStore, choice: str, basis: str, env_path: str, exports: list[str]):
    """Return the Baseline (or marker) the window's choice stands for; None when nothing usable.

    ``exports``: the names of the folder's P6 XML exports (``_folder_baseline_names``), listed once per run.
    """
    if choice in (BL_PLANNED, BL_EACH):
        return choice  # resolved per snapshot
    if choice == BL_NONE:
        return None
    if choice != BL_FILE:
        return _update_baseline(store, choice, basis)
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
    return Baseline.from_snapshot(snapshot, basis)


def _cache_for(slot: str, identity: tuple) -> dict:
    """Return the session's cache ``slot`` for ``identity``, emptied when the identity moved since the last call."""
    held_for, cache = st.session_state.get(slot, (None, {}))
    if held_for != identity:
        cache = {}
    st.session_state[slot] = (identity, cache)
    return cache


def _update_baseline(store: SnapshotStore, choice: str, basis: str) -> Baseline:
    """Return the loaded update ``choice`` as a Baseline on ``basis``, built once per series.

    The sidebar asks for it on every run, whichever page is open.
    """
    cache = _cache_for("_update_baselines", (*data_identity(baseline=False), basis))
    if choice not in cache:
        cache[choice] = Baseline.from_snapshot(store.by_label(choice), basis)
    return cache[choice]


def _folder_baseline_names(session: MutableMapping | None = None) -> list[str]:
    """Return the P6 XML exports next to the updates read from a folder, by name; none when the updates were uploaded.

    A P6 XML export holds a project's baselines, which its XER does not.
    """
    session = st.session_state if session is None else session
    source: tuple = session.get("files_source") or ("none",)
    root = Path(source[1]).expanduser() if source[0] == "folder" else None
    return [path.name for path in pmxml_files(root)] if root is not None and root.is_dir() else []


def _picked_folder_baseline(session: MutableMapping | None = None, exports: list[str] | None = None) -> Path | None:
    """Return the folder's P6 XML export picked in the window as the separate baseline file; None when none is picked.

    Only a name of the folder's own list (``exports``, listed here when not given) is taken: the name never
    builds a path elsewhere.
    """
    session = st.session_state if session is None else session
    name = session.get("bl_folder_file") or ""
    exports = _folder_baseline_names(session) if exports is None else exports
    if name not in exports:
        return None
    return Path(session["files_source"][1]).expanduser() / name


def _is_baseline_file_offered(env_path: str, exports: list[str]) -> bool:
    """Return whether a separate baseline file can be had.

    Uploaded, picked in the folder, or named by XERSCOPE_BASELINE (a locked server takes no upload).
    """
    return not _data_locked() or Path(env_path).is_file() or bool(exports)


def _disk_baseline_file(path: Path) -> tuple[str, bytes | DiskFile]:
    """Return a baseline file of the disk as (name, contents).

    A P6 XML export is handed out to be read where asked, never whole: it runs to gigabytes, and a rerun
    reads none of it once its baselines are built. An XER, a few megabytes, is read as it always was.
    """
    export = DiskFile(path)
    return path.name, export if is_pmxml(export) else path.read_bytes()


def _baseline_file_source(env_path: str | None, exports: list[str]) -> tuple[str, bytes | DiskFile] | None:
    """Return the separate baseline file.

    The one picked in the folder (among ``exports``), else the one uploaded in the window, else
    XERSCOPE_BASELINE's.
    """
    picked = _picked_folder_baseline(exports=exports)
    if picked is not None:
        return _disk_baseline_file(picked)
    source = None if _data_locked() else st.session_state.get("bl_file")
    env_path = os.environ.get("XERSCOPE_BASELINE", "") if env_path is None else env_path
    if source is None and env_path and Path(env_path).is_file():
        source = _disk_baseline_file(Path(env_path))
    return source


def _xml_baseline_id(source: tuple[str, bytes | DiskFile], pointer: str | None) -> str | None:
    """Return ``pointer`` (an update's sum_base_proj_id) when the P6 XML baseline file holds that baseline, else None.

    The file's Project Baseline is read. None for an XER file.
    """
    name, data = source
    if not pointer or not is_pmxml(data):
        return None
    return pointer if pointer in _pmxml_index(name, data).baseline_spans else None


def _pmxml_index(name: str, data: bytes | DiskFile) -> PmxmlIndex:
    """Return the index of a P6 XML file, made once per content.

    The sidebar asks which baselines the file holds on every rerun, and each baseline read from it starts
    from the index. Keyed on the bytes it was made from, since its positions are theirs alone.
    """
    cache = st.session_state.setdefault("_pmxml_index", {})
    key = (name, _digest(data))
    if key not in cache:
        cache.clear()  # one baseline file at a time
        cache[key] = index_pmxml(data, name)
    return cache[key]


def _describe_baseline(sidebar, store: SnapshotStore, baseline: Baseline) -> None:
    sidebar.caption(f"{ui.md_text(baseline.label)} · {len(baseline.frame)} tasks · {baseline.bac_hours:,.0f} labor h")
    baseline_date, first_date = baseline.snapshot.data_date, store.first.data_date
    if baseline_date is not None and first_date is not None and baseline_date > first_date:
        sidebar.warning(
            f"The baseline's status date ({ui.fmt_date(baseline_date)}) is after the first update's "
            f"({ui.fmt_date(first_date)}): "
            "BEI, missed tasks and PV before that date compare against a plan that did not exist yet.",
            icon=":material/warning:",
        )


def _fallback_options(store: SnapshotStore, exports: list[str]) -> list[str]:
    """Return what an update whose file has no usable baseline can be measured against.

    A separate file on a locked server only when its folder holds a P6 XML export or XERSCOPE_BASELINE
    names a file (nothing can be uploaded there).
    """
    file_choice = _is_baseline_file_offered(os.environ.get("XERSCOPE_BASELINE", ""), exports)
    return ([BL_FILE] if file_choice else []) + store.labels + [BL_PLANNED, BL_NONE]


def _fallback_picker(sidebar, store: SnapshotStore, basis: str, exports: list[str]) -> None:
    """Show what an update whose file has no usable baseline is measured against: chosen, never imposed."""
    choice = st.session_state["bl_fallback"]
    st.session_state["fallback_choice"] = choice
    # the separate file: uploaded, else named by XERSCOPE_BASELINE (a locked server has only that one)
    env_path = os.environ.get("XERSCOPE_BASELINE", "")
    st.session_state["fallback"] = _baseline_from_choice(sidebar, store, choice, basis, env_path, exports)


PROBABLE = (
    "probable: "  # opens the ``source`` of a baseline that is not the one the update names (``_resolved_baseline``)
)


IN_ITS_FILE, FROM_THE_EXPORT, A_PROBABLE_BASELINE, THE_FALLBACK = (
    "the baseline of its file",
    "the baseline it names, from the export",
    "a probable baseline",
    "the fallback",
)


def _source_kind(snapshot: Snapshot) -> str:
    """Return where the baseline of an update comes from in the per-file mode.

    Its file, the export under the id it names, a probable baseline (``_resolved_baseline``), the
    fallback, nothing.
    """
    if snapshot.file_baseline.usable:
        return IN_ITS_FILE
    found = _resolution(snapshot)
    if found is not None and found.found_by == IN_EXPORT:
        return FROM_THE_EXPORT
    if found is not None and found.found_by in (LOADED_UPDATE, SAME_GENERATION):
        return A_PROBABLE_BASELINE
    return THE_FALLBACK if st.session_state.get("fallback") is not None else "no baseline"


def _which_updates(snapshots: list[Snapshot]) -> str:
    """Return the updates a sidebar line is about, short.

    The file of a single one, else a count and the dates (a list of long file names made the lines
    unreadable on a long series).
    """
    if len(snapshots) == 1:
        return ui.md_text(snapshots[0].source)
    count = counted(len(snapshots), "update")
    span = _date_span(snapshots)
    if span:
        return f"{count}, {span}"
    return count


def _dates_or_file(snapshots: list[Snapshot]) -> str:
    """Return the file of a single update, else the first and last data dates of the updates."""
    if len(snapshots) == 1:
        return ui.md_text(snapshots[0].source)
    return _date_span(snapshots)


def _date_span(snapshots: list[Snapshot]) -> str:
    """Return the ``first → last`` data date of the updates; empty when none has a data date."""
    dates = sorted(snapshot.data_date for snapshot in snapshots if snapshot.data_date is not None)
    if not dates:
        return ""
    return f"{ui.fmt_date(dates[0])} → {ui.fmt_date(dates[-1])}"


def _files_name(snapshots: list[Snapshot]) -> str:
    """Return the subject and verb of a sentence on one update ("its file names") or several."""
    return "its file names" if len(snapshots) == 1 else "their files name"


def _resolution_warnings(sidebar, store: SnapshotStore, instead: str) -> list[Snapshot]:
    """Show, in the per-file mode, the export that cannot be read.

    The updates measured against a probable baseline, those left undecided (``instead``: what applies to
    them). Returns the updates no baseline was found for.
    """
    export_error = _export_in_use()[1]
    if export_error:
        sidebar.error(f"Baselines export not read: {ui.md_text(export_error)}")
    kinds = {snapshot.source: _source_kind(snapshot) for snapshot in store}
    probable = [snapshot for snapshot in store if kinds[snapshot.source] == A_PROBABLE_BASELINE]
    if probable:
        sidebar.warning(
            f"{_which_updates(probable)}: measured against a probable baseline, not the one "
            f"{_files_name(probable)}. Which one and why: under the title of each page, and Debug, block 5.",
            icon=":material/warning:",
        )
    found = (IN_ITS_FILE, FROM_THE_EXPORT, A_PROBABLE_BASELINE)
    unusable = [snapshot for snapshot in store if kinds[snapshot.source] not in found]
    undecided = [snapshot for snapshot in unusable if getattr(_resolution(snapshot), "found_by", "") == UNDECIDED]
    if undecided:
        sidebar.warning(
            f"{_which_updates(undecided)}: the baseline {_files_name(undecided)} is not in the export, and the "
            f"versions around it do not hold one same baseline; {instead}. Debug, block 5.",
            icon=":material/warning:",
        )
    return unusable


def _file_baseline_warnings(sidebar, store: SnapshotStore) -> None:
    """Show, in the per-file mode, what the export gave (``_resolution_warnings``).

    The updates with no baseline (and what applies instead), each reason a pointer is not used with the
    updates it concerns, a series that mixes sources.
    """
    choice = st.session_state.get("fallback_choice", BL_NONE)
    instead = "their baseline checks are n/a" if choice == BL_NONE else f"fallback: {choice}"
    unusable = _resolution_warnings(sidebar, store, instead)
    if unusable:
        sidebar.warning(
            f"No usable P6 Project Baseline in the file of {_which_updates(unusable)}: {instead}.",
            icon=":material/warning:",
        )
    reasons: dict[str, list[Snapshot]] = {}
    for snapshot in unusable:
        if snapshot.file_baseline.note:
            reasons.setdefault(snapshot.file_baseline.text, []).append(snapshot)
    for reason, snapshots in reasons.items():
        sidebar.warning(f"{_which_updates(snapshots)}: {ui.md_text(reason)}. Not used.", icon=":material/warning:")
    groups: dict[str, list[Snapshot]] = {}
    for snapshot in store:
        groups.setdefault(_source_kind(snapshot), []).append(snapshot)
    if len(groups) > 1:
        parts = [f"{len(snapshots)} on {kind} ({_dates_or_file(snapshots)})" for kind, snapshots in groups.items()]
        sidebar.warning(
            "The series mixes baseline sources, so its updates are not measured against the same plan: "
            + "; ".join(parts)
            + ".",
            icon=":material/warning:",
        )


def _updates_without_the_baseline_they_name(store: SnapshotStore) -> list[Snapshot]:
    """Return the updates ``_absent_baseline_help`` looks at.

    All of them, less, in the per-file mode, those measured against the baseline they name, read from the
    export.
    """
    if st.session_state.get("baseline") != BL_EACH:
        return list(store)
    return [snapshot for snapshot in store if _source_kind(snapshot) != FROM_THE_EXPORT]


def _absent_baseline_help(sidebar, store: SnapshotStore) -> None:
    """Show the updates whose P6 Project Baseline (sum_base_proj_id) names a project their file does not hold.

    The updates whose earned value uses it (use_project_baseline_flag not N): the baseline named by its
    code when any loaded file holds that project, why it is needed, and what to load. Counts and dates
    only, no file name (a long series of long names made the line unreadable). No P6 steps: restoring or
    converting a baseline changes the project. Which file names which: Debug, block 5.
    """
    absent = absent_project_baselines(_updates_without_the_baseline_they_name(store))
    if not absent:
        return
    codes = project_codes(store)
    updates = sum(len(snapshots) for snapshots in absent.values())

    def one(proj_id: str, snapshots: list[Snapshot]) -> str:
        dates = sorted(snapshot.data_date for snapshot in snapshots if snapshot.data_date is not None)
        when = ui.fmt_date(dates[0]) if len(dates) == 1 else _date_span(snapshots)
        name = codes.get(proj_id, "a project no loaded file holds (its code is unknown)")
        without_flag = sum(uses_project_baseline(snapshot) is None for snapshot in snapshots)
        flag = f", {counted(without_flag, 'update')} without use_project_baseline_flag" if without_flag else ""
        return f"{name}, named by {counted(len(snapshots), 'update')} ({when}{flag})"

    shown = sorted(absent.items(), key=lambda item: -len(item[1]))[:ABSENT_BASELINES_SHOWN]
    named = "; ".join(one(proj_id, snapshots) for proj_id, snapshots in shown)
    if len(absent) > ABSENT_BASELINES_SHOWN:
        named += f"; {len(absent) - ABSENT_BASELINES_SHOWN} more"
    sidebar.error(
        f"P6 Project Baseline missing for {counted(updates, 'update')} of {len(store)}: {named}. "
        "P6 measures planned value, BEI, Late Activities and Missed tasks against it "
        "(Project Details > Settings, use project baseline). Export that project from P6 and load its XER "
        f"under Baseline (BL) > {BL_FILE}. Which file names which: Debug, block 5.",
        icon=":material/error:",
    )


def _other_baseline_warning(sidebar, store: SnapshotStore, choice: str, baseline) -> None:
    """Show the warning on a separate baseline file or a loaded update in force.

    For every update or as the fallback of those without a usable baseline in their file, whose project is
    not the Project Baseline those updates name.
    """
    if choice not in (BL_EACH, BL_PLANNED, BL_NONE):  # the separate file or a loaded update
        separate, updates, kind = baseline, list(store), choice
    elif choice == BL_EACH and st.session_state.get("fallback_choice") not in (None, BL_PLANNED, BL_NONE):
        separate = st.session_state.get("fallback")
        # the other updates found their own baseline
        updates = [snapshot for snapshot in store if _source_kind(snapshot) == THE_FALLBACK]
        kind = st.session_state.get("fallback_choice")
    else:
        return
    if not isinstance(separate, Baseline):
        return
    others = other_project_baselines(separate.snapshot, updates)
    if not others:
        return
    codes = project_codes([*store, separate.snapshot])
    loaded = separate.snapshot
    named = "; ".join(
        f"{codes.get(proj_id, 'a project no loaded file holds')} ({counted(len(snapshots), 'update')})"
        for proj_id, snapshots in sorted(others.items(), key=lambda item: -len(item[1]))
    )
    what = "separate baseline file" if kind == BL_FILE else "baseline (a loaded update)"
    sidebar.warning(
        f"The {what} is {loaded.project_code}, status date {ui.fmt_date(loaded.data_date)}, but the updates "
        "name another P6 Project "
        f"Baseline: {named}. Their planned value, BEI and late tasks will not match P6's. (Compared by P6's "
        "internal project id, which holds within one P6 database only.) Ask for the export of the project they "
        "name: Debug, block 5, lists the pointers.",
        icon=":material/warning:",
    )


ABSENT_BASELINES_SHOWN = 3  # baselines named in the sidebar line; the rest counted


MATCH_WARN_BELOW = 0.9  # share of the update's activities the baseline must find


def _files_count(store: SnapshotStore) -> str:
    """Return ``N files · K projects``: K is the projects read, in the alert colour when the series mixes several."""
    count = len({snapshot.project_code for snapshot in store})
    projects = counted(count, "project")
    if count > 1:
        projects = f":orange[{projects}]"
    return f"{counted(len(store), 'file')} · {projects}"


def _baseline_kind(baseline: Baseline | None) -> str:
    """Return where ``baseline`` (``baseline_for`` an update) comes from.

    Its file's P6 Project Baseline, the fallback (``_fallback_baseline`` names it so), planned dates, a
    loaded update, a separate file, none.
    """
    if baseline is None:
        return "none"
    if st.session_state.get("baseline") == BL_EACH:
        if baseline.source.startswith("fallback"):
            return f"fallback, {_baseline_short(st.session_state.get('fallback_choice', BL_NONE))}"
        if baseline.source.startswith(PROBABLE):
            return "probable"
        return "in file"
    return _baseline_short(st.session_state.get("bl_choice", BL_NONE))


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
    export_at_hand = (source is not None and is_pmxml(source[1])) or bool(exports)
    file_choice = _is_baseline_file_offered(env_path, exports)
    options = ([BL_EACH] if in_files or export_at_hand else []) + ([BL_FILE] if file_choice else []) + store.labels
    options += [BL_PLANNED, BL_NONE]
    # BL_EACH leads the list and is the default, unless a baseline file is named by XERSCOPE_BASELINE
    if in_files and not env_path:
        return options, BL_EACH
    return options, BL_FILE if env_path and file_choice else store.labels[0]


def _is_named_in_export(source: tuple[str, bytes | DiskFile] | None, pointer: str) -> bool:
    """Return whether the separate baseline file is a P6 XML export that holds the baseline ``pointer`` names.

    An export that cannot be read holds none (the sidebar says so where it is used).
    """
    try:
        return source is not None and _xml_baseline_id(source, pointer) is not None
    except XerError:
        return False


def _baseline_short(choice: str) -> str:
    """Return the sidebar line's name for the baseline in use."""
    if choice == BL_FILE:
        picked = _picked_folder_baseline()
        if picked is not None:
            return picked.name
        held = None if _data_locked() else st.session_state.get("bl_file")
        env_path = os.environ.get("XERSCOPE_BASELINE", "")
        return held[0] if held else Path(env_path).name if Path(env_path).is_file() else "file missing"
    names = {BL_EACH: "in each file", BL_PLANNED: "planned dates", BL_NONE: "none"}
    # a loaded update: its label starts with its data date
    return names.get(choice, f"update {choice.split(' · ')[0]}")


def _baseline_picker(store: SnapshotStore) -> None:
    """Apply the window's baseline choice: the sidebar line names it, the warnings follow it."""
    sidebar = st.sidebar
    line = sidebar.container()
    env_path = os.environ.get("XERSCOPE_BASELINE", "")
    # the window's values, checked against this store: a choice that names a file no longer loaded
    # goes back to the default
    exports = _folder_baseline_names()
    if st.session_state.get("bl_folder_file") not in ["", *exports]:
        # never picked, or a file no longer in the folder: the folder's only export, unless the server
        # names its own baseline file (XERSCOPE_BASELINE)
        st.session_state["bl_folder_file"] = exports[0] if len(exports) == 1 and not env_path else ""
    options, default = _baseline_options(store, env_path, exports)
    if st.session_state.get("bl_choice") not in options:
        st.session_state["bl_choice"] = default
    if st.session_state.get("ev_basis") not in EV_BASES:
        st.session_state["ev_basis"] = DEFAULT_EV_BASIS
    if st.session_state.get("bl_fallback") not in _fallback_options(store, exports):
        st.session_state["bl_fallback"] = BL_NONE
    if not isinstance(st.session_state.get("guid_link"), bool):
        st.session_state["guid_link"] = False
    choice, basis = st.session_state["bl_choice"], st.session_state["ev_basis"]
    st.session_state["baseline_digest"] = None  # set again when the choice is a baseline file
    st.session_state["fallback"], st.session_state["fallback_choice"] = None, BL_NONE
    _baseline_line(line, choice)
    if not st.session_state.get(BASELINE_SET):
        st.session_state["baseline"] = None  # no file read for it, no warning: the pages wait (require_store)
        return
    baseline: Baseline | None | str = _baseline_from_choice(sidebar, store, choice, basis, env_path, exports)
    st.session_state["baseline"] = baseline
    if baseline == BL_EACH:
        _fallback_picker(sidebar, store, basis, exports)
    if isinstance(baseline, Baseline):
        _describe_baseline(sidebar, store, baseline)
    if baseline == BL_EACH:
        _file_baseline_warnings(sidebar, store)
    _absent_baseline_help(sidebar, store)
    _other_baseline_warning(sidebar, store, choice, baseline)
    _renumbered_notice(sidebar, store)


def _baseline_line(line, choice: str) -> None:
    """Show the sidebar's Baseline line: the choice in force; it opens the window on its Baseline section."""
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


def _renumbered_notice(sidebar, store: SnapshotStore) -> None:
    """Show the tasks of the updates that carry a baseline task's GUID under a new Activity ID (``renumbered``).

    A warning while they count as deleted and new, a caption once the option links them, nothing when
    there are none.
    """
    if st.session_state.get("guid_link"):
        blank = memo(("baselines_without_guid",), _baselines_without_guid, store, ev_basis=False)
        if blank:
            sidebar.warning(
                f"Link renumbered tasks by GUID is on, but the baseline has no GUID to match "
                f"({ui.md_text(', '.join(blank))}): no task is linked. A P6 XML baseline carries none "
                "xerscope compares; export the baseline as XER to link renumbered tasks.",
                icon=":material/warning:",
            )
    found = memo(("renumbered",), _renumbered_counts, store, ev_basis=False)
    if not found:
        return
    total = sum(found.values())
    files = ui.md_text(", ".join(f"{name} ({count})" for name, count in found.items()))
    tasks = counted(total, "task")
    if st.session_state.get("guid_link"):
        sidebar.caption(f"{tasks} renumbered since the baseline, linked to the baseline by GUID: {files}.")
        return
    sidebar.warning(
        f"{tasks} {'carries' if total == 1 else 'carry'} a baseline task's GUID under a new Task ID "
        f"({files}): against the baseline {'it counts' if total == 1 else 'they count'} as deleted and new. "
        "Option in the Baseline window: Link renumbered tasks by GUID.",
        icon=":material/warning:",
    )


def _baselines_without_guid(store: SnapshotStore) -> list[str]:
    """Return the labels of the baselines in use (other than an update itself) none of whose tasks has a TASK.guid.

    The GUID link finds nothing against them (a P6 XML baseline: xer/pmxml.py).
    """
    labels = set()
    for snapshot in store:
        baseline = baseline_for(snapshot, link=False)
        if baseline is None or baseline.snapshot is snapshot:
            continue
        tasks = baseline.snapshot.activities
        if "guid" not in tasks or not (tasks["guid"].fillna("").astype(str).str.strip() != "").any():
            labels.add(baseline.label)
    return sorted(labels)


def _renumbered_counts(store: SnapshotStore) -> dict[str, int]:
    """Return the renumbered tasks per update (file -> count), once per data set and baseline.

    The sidebar draws the notice on every rerun of every page, and the GUID match reads every update.
    """
    found = {}
    for snapshot in store:
        baseline = baseline_for(snapshot, link=False)
        if baseline is None or baseline.snapshot is snapshot:
            continue
        count = len(renumbered(baseline.snapshot, snapshot))
        if count:
            found[snapshot.source] = count
    return found


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
        if st.session_state.get(draft) not in offered[draft]:
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
            "Export). The one picked is the separate baseline file; it is never read as an update. With "
            f"'{BL_EACH}', each update is looked for in it: the baseline its file names, else a copy of it "
            "(Debug, block 5).",
        )
    if wants_file and not _data_locked():
        st.file_uploader(
            "Baseline .xer, or a P6 XML export with its baselines",
            type=[*UPLOAD_TYPES, "xml"],
            key="bl_upload",
            help="P6 Professional exports a project's baselines in XML only (Export > Primavera P6 XML, "
            "Baselines to Export). Each update is then measured against the baseline its file names.",
        )
        held = st.session_state.get("bl_file")
        if held:
            st.caption(f"Held: {ui.md_text(held[0])}")


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
        "(P6 default: budgeted values with planned dates). Set it as in your P6 so PV, EV and BAC match.",
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
        st.selectbox(
            "When a file has no baseline",
            fallback_options,
            key="draft_bl_fallback",
            help="Applies update by update: an update uses the baseline of its own file when it has a usable "
            "one, otherwise this. None: the checks that need a baseline are n/a for that update.",
        )
    _baseline_file_fields(choice, folder_files)


def _fallback_baseline(snapshot: Snapshot) -> Baseline | None:
    """Return the fallback chosen in the window, as it applies to ``snapshot`` (a file with no usable baseline)."""
    fallback, choice = st.session_state.get("fallback"), st.session_state.get("fallback_choice", BL_NONE)
    if fallback == BL_PLANNED:
        built = Baseline.planned(snapshot, st.session_state.get("ev_basis", DEFAULT_EV_BASIS))
        return replace(built, source=f"fallback ({BL_PLANNED})")
    if isinstance(fallback, Baseline):
        kind = "separate baseline file" if choice == BL_FILE else "loaded update"
        return replace(fallback, source=f"fallback ({kind}): {fallback.label}")
    return None


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


def _loaded_update_baseline(snapshot: Snapshot, project_id: str) -> Baseline:
    """Return the last update read from ``project_id``, the project ``snapshot`` names as its baseline.

    As a probable baseline: the same P6 object, in the state it was exported in, not the one it was made a
    baseline in.
    """
    update = [other for other in st.session_state["store"] if other.project_id == project_id][-1]
    built = Baseline.from_snapshot(update, st.session_state.get("ev_basis", DEFAULT_EV_BASIS))
    return replace(
        built,
        source=f"{PROBABLE}the project of {update.source}, as exported on {ui.stamp(update.data_date)}, "
        f"which the update names as its baseline ({snapshot.file_baseline.proj_id})",
    )


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
    export = baseline_export()
    if export is None or found.found_by not in (IN_EXPORT, SAME_GENERATION):
        return None
    built = _export_baseline(export, found.baseline_id)
    code = built.snapshot.project_code
    if found.found_by == IN_EXPORT:
        return replace(built, source=f"P6 Project Baseline {code} from {export[0]}")
    return replace(
        built,
        source=f"{PROBABLE}baseline {code} of {export[0]}, held by the versions created before and after the "
        f"update's project ({found.version_before} and {found.version_after}); the one its file names "
        f"({snapshot.file_baseline.proj_id}) is not in the export",
    )


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
        cache[key] = built
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
        baseline = _file_baseline(snapshot) or _resolved_baseline(snapshot) or _fallback_baseline(snapshot)
    elif choice == BL_PLANNED:
        baseline = Baseline.planned(snapshot, st.session_state.get("ev_basis", DEFAULT_EV_BASIS))
    else:
        baseline = choice if isinstance(choice, Baseline) else None
    return relinked(baseline, snapshot) if link and baseline is not None else baseline


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
        fallback = (st.session_state.get("fallback_choice"), st.session_state.get("baseline_digest"))
        export = baseline_files_tag(st.session_state)  # the export the updates are looked for in
        return baseline, basis, pointers, fallback, export
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


MEMO_SIZE = 128  # entries per session; a standard holds at most 18 metrics, each its own entry


def memo(key: tuple, function, *arguments, keep: bool = True, baseline: bool = True, ev_basis: bool = True):
    """Return the value cached per session, keyed on the loaded files and the baseline.

    Heavy analyses run once per data set.

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
    """Return ``metric`` on ``snapshot`` against the sidebar's baseline for it, once per session.

    Health, Audit and the BEI of Earned value read the same entry. Key (with ``memo``'s): the metric as
    written (rule, parameters, target, standard: its repr) and the update (file, data date). Not the EV
    basis: no rule reads what it sets (the ev_* columns, the assignment costs).
    """
    return memo(
        _metric_key(metric, snapshot),
        lambda: run_metric(metric, AnalysisContext(snapshot, store, baseline_for(snapshot))),  # built on a miss only
        keep=keep,
        ev_basis=False,
    )


def snapshot_identity(snapshot: Snapshot) -> tuple[str, str]:
    """Return the file and the data date that tell one update from another.

    As the memo keys and the tags of built downloads hold them.
    """
    return snapshot.source, str(snapshot.data_date)


def _metric_key(metric: Metric, snapshot: Snapshot) -> tuple:
    """Return the memo key of one metric on one update: the metric's definition, the file and its data date."""
    return ("metric", repr(metric), *snapshot_identity(snapshot))


def standard_results(standard: Standard, snapshot: Snapshot, store: SnapshotStore) -> list[CheckResult]:
    """Return every check of ``standard`` on ``snapshot``, each through :func:`metric_result`."""
    return [metric_result(metric, snapshot, store) for metric in standard.metrics]


def hold_standard_results(standard: Standard, snapshot: Snapshot, results: list[CheckResult]) -> None:
    """Store the results computed outside the script run (ScoreJob) where ``metric_result`` reads."""
    for metric, result in zip(standard.metrics, results, strict=True):
        memo(_metric_key(metric, snapshot), lambda result=result: result, ev_basis=False)


@dataclass
class ScoreJob:
    """Hold the standards' checks on one update, computed in a thread for the Overview's score cards.

    ``results`` fills per standard id as each finishes.
    """

    identity: tuple
    snapshot: Snapshot
    store: SnapshotStore
    baseline: Baseline | None
    standards: dict[str, Standard]
    results: dict[str, list[CheckResult] | str] = field(default_factory=dict)
    held: set[str] = field(default_factory=set)  # standard ids already written to the memo
    done: bool = False
    cancelled: bool = False  # set when another data set or baseline replaces this one
    thread: threading.Thread | None = None

    def run(self) -> None:
        """Compute each standard in turn into ``results``, then set ``done``."""
        context = AnalysisContext(self.snapshot, self.store, self.baseline)
        for key, standard in self.standards.items():
            results: list[CheckResult] | str
            try:
                results = run_standard(standard, context, stopped=lambda: self.cancelled)
            except Exception as exc:  # noqa: BLE001 - shown as an error on the Overview, not lost
                results = str(exc)
            if self.cancelled:
                break  # computed for another data set or baseline: not kept
            self.results[key] = results
        self.done = True


def score_job(snapshot: Snapshot, store: SnapshotStore, standards_: dict[str, Standard]) -> ScoreJob:
    """Return the job computing ``standards_`` on ``snapshot`` for the current data set, started on the first call.

    A new data set or baseline starts another. The results already in are written to the memo, so Schedule
    health reads them.
    """
    identity = (*data_identity(ev_basis=False), snapshot.source, str(snapshot.data_date), tuple(standards_))
    job: ScoreJob | None = st.session_state.get("_score_job")
    if job is None or job.identity != identity:
        if job is not None:
            job.cancelled = True  # its results are for another data set or baseline
        job = ScoreJob(identity, snapshot, store, baseline_for(snapshot), dict(standards_))
        job.thread = threading.Thread(target=job.run, name="xerscope-scores", daemon=True)
        job.thread.start()
        st.session_state["_score_job"] = job
    for key, results in list(job.results.items()):
        if key not in job.held and not isinstance(results, str):
            hold_standard_results(job.standards[key], snapshot, results)
            job.held.add(key)
    return job


def standard_results_held(standard: Standard, snapshot: Snapshot) -> list[CheckResult] | None:
    """Return the results :func:`standard_results` would return, if every one is already cached, else None.

    Computes nothing.
    """
    results = [
        memo(_metric_key(metric, snapshot), lambda: None, keep=False, ev_basis=False) for metric in standard.metrics
    ]
    return None if any(result is None for result in results) else results


def anonymous_exports(session: MutableMapping | None = None) -> bool:
    """Return the sidebar switch: downloads anonymized (default) or in the files' own names."""
    session = st.session_state if session is None else session
    return session.get("anon_exports", True)


def costs_shown(session: MutableMapping | None = None) -> bool:
    """Return the sidebar checkbox: cost figures on Earned value (default off, the schedules are sourced in hours)."""
    session = st.session_state if session is None else session
    return bool(session.get("costs", False))


def sources_of(*snapshots: Snapshot | None, baseline: Baseline | None = None) -> list[str]:
    """Return the files a download is made from: the updates shown and the baseline's file."""
    found = [snapshot.source for snapshot in snapshots if snapshot is not None]
    return found + ([baseline.snapshot.source] if baseline is not None else [])


def baseline_items(session: MutableMapping) -> list[tuple[str, bytes | DiskFile]]:
    """Return the separate baseline file as (name, contents), when one is in use.

    Picked in the folder, uploaded or XERSCOPE_BASELINE: the baseline or the fallback of the window, or,
    in the per-file mode, the P6 XML export the updates are looked for in (an XER is no such export).
    """
    is_the_baseline = session.get("bl_choice") == BL_FILE or session.get("bl_fallback") == BL_FILE
    if not is_the_baseline and session.get("bl_choice") != BL_EACH:
        return []
    picked = _picked_folder_baseline(session)
    held = _disk_baseline_file(picked) if picked is not None else None
    if held is None and not _data_locked():
        held = session.get("bl_file")
    env_path = os.environ.get("XERSCOPE_BASELINE", "")
    if held is None and env_path and Path(env_path).is_file():
        held = _disk_baseline_file(Path(env_path))
    if held is None or not (is_the_baseline or is_pmxml(held[1])):
        return []
    return [held]


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


def baseline_files_tag(session: MutableMapping) -> tuple[tuple[str, str], ...]:
    """Return the (name, digest) of each ``baseline_items`` file.

    With the signature, which files an anonymizer or an extract was built from.
    """
    return tuple((name, _digest(data)) for name, data in baseline_items(session))
