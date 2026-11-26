"""The sidebar's Baseline line and what the sidebar says about the baseline in use."""

from __future__ import annotations

import os

import streamlit as st

from xerscope.analysis import Baseline
from xerscope.analysis.baseline import (
    DEFAULT_EV_BASIS,
    EV_BASES,
    KIND_CHOSEN,
    KIND_EXACT,
    KIND_FALLBACK,
    KIND_IN_FILE,
    KIND_NONE,
    KIND_PLANNED,
    KIND_PROBABLE,
    KIND_SERIES,
    absent_project_baselines,
    other_project_baselines,
    project_codes,
    renumbered,
    uses_project_baseline,
)
from xerscope.app import ui
from xerscope.app.baseline_export import _export_in_use, is_undecided
from xerscope.app.baseline_file import _folder_baseline_names, is_xml_name
from xerscope.app.baseline_window import _baseline_options, _baseline_short, _fallback_options
from xerscope.app.baselines import _baseline_from_choice, _fallback_picker, baseline_for, kind_of
from xerscope.app.cache import memo
from xerscope.app.session import BASELINE_SET, BL_EACH, BL_FILE, BL_NONE, BL_PLANNED, _open_window, counted
from xerscope.store import SnapshotStore
from xerscope.xer import Snapshot


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


KIND_TEXT = {  # how the sidebar names each kind of baseline (``analysis.baseline.KIND_*``)
    KIND_IN_FILE: "the baseline of its file",
    KIND_EXACT: "the baseline it names, from the export",
    KIND_PROBABLE: "a probable baseline",
    KIND_CHOSEN: "a baseline chosen in the window",
    KIND_FALLBACK: "the fallback",
    KIND_PLANNED: "its planned dates",
    KIND_SERIES: "the baseline of the series",
    KIND_NONE: "no baseline",
}


def _kinds(store: SnapshotStore) -> dict[str, str]:
    """Return the kind of baseline each update of the series is measured against, by file name."""
    return {snapshot.source: kind_of(baseline_for(snapshot, link=False)) for snapshot in store}


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


def _resolution_warnings(sidebar, store: SnapshotStore, kinds: dict[str, str]) -> list[Snapshot]:
    """Show, in the per-file mode, the export that cannot be read.

    The updates measured against a probable baseline, those left undecided (``instead``: what applies to
    them). Returns the updates no baseline was found for.
    """
    export_error = _export_in_use()[1]
    if export_error:
        sidebar.error(f"Baselines export not read: {ui.md_text(export_error)}")
    for baseline_id, error in sorted(st.session_state.get("_export_read_errors", {}).items()):
        sidebar.error(f"Baseline {baseline_id} of the export not read: {ui.md_text(error)}")
    probable = [snapshot for snapshot in store if kinds[snapshot.source] in (KIND_PROBABLE, KIND_CHOSEN)]
    if probable:
        sidebar.warning(
            f"{_which_updates(probable)}: measured against a probable baseline, not the one "
            f"{_files_name(probable)}. Which one and why: under the title of each page, and Debug, block 5.",
            icon=":material/warning:",
        )
    undecided = [snapshot for snapshot in store if kinds[snapshot.source] == KIND_NONE and is_undecided(snapshot)]
    if undecided:
        sidebar.warning(
            f"{_which_updates(undecided)}: the baseline {_files_name(undecided)} is not in the export, and the "
            "versions around it hold different baselines: not measured until one is chosen in the Baseline "
            "window. Debug, block 5.",
            icon=":material/warning:",
        )
    return [s for s in store if kinds[s.source] in (KIND_FALLBACK, KIND_NONE) and s not in undecided]


def _file_baseline_warnings(sidebar, store: SnapshotStore) -> None:
    """Show, in the per-file mode, what the export gave (``_resolution_warnings``).

    The updates with no baseline (and what applies instead), each reason a pointer is not used with the
    updates it concerns, a series that mixes sources.
    """
    choice = st.session_state.get("bl_fallback", BL_NONE)
    instead = "their baseline checks are n/a" if choice == BL_NONE else f"fallback: {choice}"
    kinds = _kinds(store)
    unusable = _resolution_warnings(sidebar, store, kinds)
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
        groups.setdefault(KIND_TEXT[kinds[snapshot.source]], []).append(snapshot)
    if len(groups) > 1:
        parts = [f"{len(snapshots)} on {kind} ({_dates_or_file(snapshots)})" for kind, snapshots in groups.items()]
        sidebar.warning(
            "The series mixes baseline sources, so its updates are not measured against the same plan: "
            + "; ".join(parts)
            + ".",
            icon=":material/warning:",
        )


def _updates_without_a_baseline(store: SnapshotStore) -> list[Snapshot]:
    """Return the updates ``_absent_baseline_help`` looks at.

    All of them, less, in the per-file mode, those measured against a baseline: the one they name, a
    probable one (said by ``_resolution_warnings``), and those left undecided, which the window offers
    candidates for. Counting a probable baseline as missing told a user with 6 exact and 14 probable
    baselines that 14 were missing.
    """
    if st.session_state.get("baseline") != BL_EACH:
        return list(store)
    return [
        snapshot
        for snapshot in store
        if kind_of(baseline_for(snapshot, link=False)) in (KIND_FALLBACK, KIND_NONE) and not is_undecided(snapshot)
    ]


def _absent_baseline_help(sidebar, store: SnapshotStore) -> None:
    """Show the updates whose P6 Project Baseline (sum_base_proj_id) names a project their file does not hold.

    The updates whose earned value uses it (use_project_baseline_flag not N): the baseline named by its
    code when any loaded file holds that project, why it is needed, and what to load. Counts and dates
    only, no file name (a long series of long names made the line unreadable). No P6 steps: restoring or
    converting a baseline changes the project. Which file names which: Debug, block 5.
    """
    absent = absent_project_baselines(_updates_without_a_baseline(store))
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
    sidebar.warning(
        f"No baseline in {counted(updates, 'update')} of {len(store)}: {named}. P6 measures planned value, BEI, "
        "Late Activities and Missed tasks against it. P6 writes no baseline in an XER: put the P6 XML export of "
        "the baselines (Export > Primavera P6 XML, Baselines to Export) next to the files. Which file names "
        "which: the Files and baseline window.",
        icon=":material/warning:",
    )


def _primary_baseline_notice(sidebar, store: SnapshotStore) -> None:
    """Show one line when updates measure earned value against each user's primary baseline in P6.

    P6 Project Details > Settings, "Baseline for earned value calculation": the project baseline or your
    primary baseline (Oracle P6 Professional help). A primary baseline is a user's choice the file does not
    carry, so xerscope reads the project baseline and says so rather than guess. The flag read
    (use_project_baseline_flag = N for the primary baseline) is unverified (``uses_project_baseline``).
    """
    primary = sum(uses_project_baseline(snapshot) is False for snapshot in store)
    if not primary:
        return
    verb = "uses" if primary == 1 else "use"
    sidebar.warning(
        f"{counted(primary, 'update')} {verb} a user's primary baseline in P6: xerscope reads the project baseline.",
        icon=":material/warning:",
    )


def _other_baseline_warning(sidebar, store: SnapshotStore, choice: str, baseline) -> None:
    """Show the warning on a separate baseline file or a loaded update in force.

    For every update or as the fallback of those without a usable baseline in their file, whose project is
    not the Project Baseline those updates name.
    """
    if choice not in (BL_EACH, BL_PLANNED, BL_NONE):  # the separate file or a loaded update
        separate, updates, kind = baseline, list(store), choice
    elif choice == BL_EACH and st.session_state.get("bl_fallback") not in (None, BL_PLANNED, BL_NONE):
        separate = st.session_state.get("fallback")
        # the other updates found their own baseline
        updates = [snapshot for snapshot in store if kind_of(baseline_for(snapshot, link=False)) == KIND_FALLBACK]
        kind = st.session_state.get("bl_fallback", "")
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
        # P6 XML: an XER of the baselines subfolder is a baseline the user picks, not an export to look in
        xml = [name for name in exports if is_xml_name(name)]
        st.session_state["bl_folder_file"] = xml[0] if len(xml) == 1 and not env_path else ""
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
    st.session_state["fallback"] = None
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
    _primary_baseline_notice(sidebar, store)
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
    """Show one line on the tasks of the updates that carry a baseline task's GUID under a new Activity ID.

    A warning while they count as deleted and new, a caption once the option links them, nothing when
    there are none. A baseline read from a P6 XML export gets no line: the XML reader writes its GUID
    blank (``xer/pmxml.py``, the XML and the XER encode it differently), so no task can be told renumbered
    against it, and nothing is said rather than a renumbering invented.
    """
    found = memo(("renumbered",), _renumbered_counts, store)
    if not found:
        return
    tasks = counted(sum(found.values()), "task")
    files = ui.md_text(", ".join(f"{name} ({count})" for name, count in found.items()))
    if st.session_state.get("guid_link"):
        sidebar.caption(f"{tasks} renumbered since the baseline, matched by GUID.", help=f"Per update: {files}.")
        return
    sidebar.warning(
        f"{tasks} renumbered since the baseline: turn on Link by GUID in the Baseline window. Until then each "
        f"counts as deleted and new ({files}).",
        icon=":material/warning:",
    )


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
