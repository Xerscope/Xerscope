"""The Files window of the sidebar: file listing, uploads and the project fields."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import streamlit as st

from xerscope.app import ui
from xerscope.app.baseline_window import _baseline_fields
from xerscope.app.session import (
    BASELINE_ALONE,
    BASELINE_ASKED,
    BASELINE_SET,
    FILES_SCOPE,
    FILES_UPLOAD_SCOPE,
    KEPT_UPLOADS_SCOPE,
    NBSP,
    UPLOAD_TYPES,
    _apply_drafts,
    _close_window,
    _data_locked,
    _digest,
    _project_draft,
    _section_title,
    folder_root,
    folder_under_root,
)
from xerscope.store import SnapshotStore
from xerscope.xer import FileHeader, Snapshot, XerError, baseline_copies, load_header, xer_files
from xerscope.xer.model import HEADER_TABLES, project_counts_text, read_header
from xerscope.xer.parser import parse_bytes


def _header_date(name: str, data: bytes) -> pd.Timestamp | None:
    """Return the file's status date from its PROJECT rows only, for the reading order; None when unreadable."""
    try:
        return read_header(parse_bytes(data, source=name, keep=HEADER_TABLES)).data_date
    except XerError:
        return None


def most_recent_first(items: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Return the files by status date, latest first (unreadable last).

    The pages open on the latest update, so it is read first and the others follow in the background.
    """
    dates = {name: _header_date(name, data) for name, data in items}
    return sorted(items, key=lambda item: (dates[item[0]] is None, -(dates[item[0]] or pd.Timestamp(0)).value))


def _header(path: Path) -> FileHeader | str:
    """Return the file's header (PROJECT and TASK only), or why it cannot be read.

    Kept in the session's state like the parsed files, keyed on name, size and modification time.
    """
    cache = st.session_state.setdefault("_headers", {})
    try:
        stat = path.stat()
    except OSError:  # removed since the folder was listed
        return "no longer in the folder"
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in cache:
        if len(cache) > 256:
            cache.clear()
        try:
            cache[key] = load_header(path)
        except XerError as exc:
            cache[key] = str(exc)
    return cache[key]


def _describe_file(path: Path, same_date_as: str | None = None) -> tuple[str, str]:
    """Return the tick box label and help for a file not read yet.

    What build_snapshot would take from it, the project, its status date and its number of tasks on the
    label itself. ``same_date_as``: the file of the folder that comes first with the same status date (the
    series holds one update per date, so the two cannot be read together).
    """
    header = _header(path)
    name = ui.md_text(path.name)  # a widget label and its help are Markdown
    if isinstance(header, str):
        return f"{name} — unreadable", ui.md_text(header)
    counts = header.project_task_counts  # keyed by proj_id
    ids = [proj_id for proj_id, code in header.project_codes.items() if code == header.project_code]
    tasks = counts.get(ids[0]) if len(ids) == 1 else None  # two projects with one code: no count
    code = ui.md_text(header.project_code)
    codes = {proj_id: ui.md_text(value) for proj_id, value in header.project_codes.items()}
    label = f"{name} — {code} · {ui.fmt_date(header.data_date)}"
    if tasks is not None:
        label += f" · {int(tasks):,} tasks".replace(",", NBSP)
    if len(counts) > 1:
        label += f" · {len(counts)} projects"
    if same_date_as:
        label += f" — same date as {same_date_as}"
    details = (
        f"Project: {code} ({header.selected_by})  \n"
        f"Projects in file (TASK rows): {project_counts_text(counts, codes)}  \n"
        f"Status date: {ui.fmt_date(header.data_date)} (from {header.data_date_source or 'nothing'})"
    )
    return label, details


def _doubles_by_date(headers: dict[str, FileHeader | str]) -> dict[str, str]:
    """Return each file that shares its status date with an earlier one by name, with that earlier file.

    The series holds one update per status date: of the files sharing one, the first by name is the one
    Select all ticks, the others say which file they double. A file unreadable or without status date
    doubles none.
    """
    first_by_date: dict[pd.Timestamp, str] = {}
    doubles: dict[str, str] = {}
    for name, header in headers.items():
        if isinstance(header, str) or header.data_date is None:
            continue
        kept = first_by_date.setdefault(header.data_date, name)
        if kept != name:
            doubles[name] = kept
    return doubles


def _select_all_line(keys: dict[str, str], readable: list[str], folder_id: str, chosen: tuple[str, ...]) -> None:
    """Show the count of ticked files with the Select all and Clear buttons.

    ``keys``: the widget key of each file's box, by file name; ``readable``: the names Select all ticks;
    ``chosen``: the names ticked before a box is drawn (its widget holds the value once drawn).
    """

    def tick_all(value: bool) -> None:
        """Select all ticks every readable file but the doubles of a status date; Clear unticks all."""
        names = readable if value else list(keys)
        st.session_state.update({keys[name]: value for name in names})

    ticked = sum(bool(st.session_state.get(key, name in chosen)) for name, key in keys.items())
    count, select, clear = st.columns([2, 1, 1], vertical_alignment="center")
    count.caption(f"{ticked} of {len(keys)} ticked")
    select.button(
        "Select all",
        key=f"all:{folder_id}",
        on_click=tick_all,
        args=(True,),
        width="stretch",
        help="Ticks every readable file of the folder except the doubles of one status date. "
        "Use it to load a whole folder in one go.",
    )
    clear.button(
        "Clear",
        key=f"none:{folder_id}",
        on_click=tick_all,
        args=(False,),
        width="stretch",
        help="Unticks every file of the folder. Use it to start the choice again.",
    )


def _folder_boxes(folder: str, chosen: tuple[str, ...]) -> tuple[str, ...]:
    """Show one tick box per XER file of ``folder`` and return the names ticked.

    ``chosen``: the names of the last validated choice, ticked when the window opens: the boxes start
    from it under keys new to this opening, so what the browser shows is what the server counts.
    """
    root = folder_under_root(folder)
    if root is None:
        st.error(f"Folder outside {folder_root()}: set XERSCOPE_FOLDER_ROOT to read another tree")
        return ()
    files = xer_files(root) if root.is_dir() else []
    if not files:
        st.error("Folder not found" if not root.is_dir() else "No .xer file in that folder")
        return ()
    # Widget keys name the folder by a hash: a key shows in the page as a CSS class, and the
    # folder path is the server's.
    folder_id = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    # nothing ticked by default: a file is read (up to ~1 GB for a 40 MB export) only once asked for
    keys = {path.name: ui.fresh_key(FILES_SCOPE, f"{folder_id}:{path.name}") for path in files}

    headers = {path.name: _header(path) for path in files}
    same_date_as = _doubles_by_date(headers)
    readable = [name for name, header in headers.items() if not isinstance(header, str) and name not in same_date_as]
    _select_all_line(keys, readable, folder_id, chosen)
    picked = []
    with st.container(key="files_list_folder"):
        for path in files:
            label, details = _describe_file(path, same_date_as.get(path.name))
            if st.checkbox(label, value=path.name in chosen, key=keys[path.name], help=details):
                picked.append(path.name)
    if not picked:
        st.info("Tick at least one file to read")
    return tuple(picked)


def _upload_boxes(uploads, kept: tuple[tuple[str, bytes], ...]) -> tuple[tuple[str, bytes], ...]:
    """Show one tick box per uploaded file, ticked by default, and return the files left ticked.

    ``kept``: the files of the last validated choice (an upload widget starts empty each time the window
    opens).
    """
    files = {(name, _digest(data)): data for name, data in kept}
    for upload in uploads or []:
        files.setdefault((upload.name, _digest(upload.getvalue())), upload.getvalue())
    picked = []
    with st.container(key="files_list_upload"):
        for (name, digest), data in files.items():
            if st.checkbox(
                ui.md_text(name),
                value=True,
                key=ui.fresh_key(KEPT_UPLOADS_SCOPE, f"{digest[:12]}:{name}"),
                help=f"{len(data) / 1e6:.1f} MB",
            ):
                picked.append((name, data))
    for name, count in _same_names(picked).items():
        st.error(f"{count} files named {ui.md_text(name)}: untick all but one")
    return tuple(picked)


def _same_names(files: Iterable[tuple[str, bytes]]) -> dict[str, int]:
    """Return the names held by more than one file, with their count.

    The series is read by file name, so two files of one name would overwrite each other's results.
    """
    names = [name for name, _ in files]
    return {name: names.count(name) for name in sorted(set(names)) if names.count(name) > 1}


def _files_section(source: tuple, store: SnapshotStore | None) -> tuple | None:
    """Show the upload, folder and the list of files with a box to leave one out.

    Then the project read from each file of the series; the choice Done would validate.
    """
    if _data_locked():
        folder, uploads = os.environ.get("XERSCOPE_DATA", ""), None
        _section_title("Files", "server folder")
    else:
        _section_title("Files")
        uploads = st.file_uploader(
            "Upload .xer files",
            type=UPLOAD_TYPES,
            accept_multiple_files=True,
            key=ui.fresh_key(FILES_UPLOAD_SCOPE, "files"),
            help="Reads P6 exports (.xer) kept in this session's memory only; nothing is written to disk. "
            "Use it for files on this computer; a folder path below reads from the server instead.",
        )
        folder = st.text_input(
            "…or read a folder",
            key="files_folder",
            placeholder="/path/to/exports",
            help="A folder of the server whose .xer files are listed below for ticking. "
            "Use it for a weekly series kept on the server; uploads above take precedence.",
        )
    kept = _upload_boxes(uploads, source[1] if source[0] == "upload" else ())
    picked = () if kept else _folder_boxes(folder, source[2] if source[0] == "folder" else ()) if folder else ()
    if store is not None:
        _projects_fields(store)
    if kept:
        return ("upload", kept)
    return ("folder", folder, picked) if picked else None


def _projects_fields(store: SnapshotStore) -> None:
    """Show one row per file of the series.

    The project read from it and the rule that picked it, and a list of its projects when more than one
    can be analysed once its baseline copies are set aside, on a draft that Done applies
    (``_apply_drafts``); otherwise the row says it holds a baseline copy.
    """
    st.caption("Project read from each file · why")
    with st.container(key="files_projects"):
        for snapshot in sorted(store, key=lambda snapshot: snapshot.source):
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
                help="The project of this file the pages analyse, when the file holds several (its P6 Project "
                "Baselines are listed aside). Use it when the analysed project is not the one picked by default.",
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


def _window_sections(has_series: bool) -> list[str]:
    """Return the sections the window draws, the one its opener names first.

    Opened by itself for the baseline of a series just read (``BASELINE_ALONE``), the Baseline section
    alone: the boxes of the Files section came back unticked in a browser, and Done then read no file.
    """
    opened_on = st.session_state.get("window_section")
    if opened_on == BASELINE_ALONE:
        return ["baseline"]
    if not has_series:
        return ["files"]
    return ["baseline", "files"] if opened_on == "baseline" else ["files", "baseline"]


def _draw_sections(sections: list[str], source: tuple, store: SnapshotStore | None) -> tuple | None:
    """Show the window's sections, a rule between them, and return the files choice Done would validate.

    Without the Files section the choice is the files already read.
    """
    choice = None if "files" in sections else st.session_state.get("files_source")
    for index, section in enumerate(sections):
        if index:
            st.html('<hr class="xd-rule">')
        if section == "files":
            choice = _files_section(source, store)
        else:
            _baseline_fields(store)
    return choice


def _on_done(choice: tuple | None, store: SnapshotStore | None) -> None:
    """Apply the drafts and the files ``choice``, close the window and rerun the page."""
    _apply_drafts()
    if choice != st.session_state.get("files_source"):  # other files: their baseline is asked once read
        st.session_state.update({BASELINE_ASKED: False, BASELINE_SET: False})
    elif store is not None:  # the Baseline section was shown
        st.session_state[BASELINE_SET] = True
    st.session_state.update(files_source=choice, files_open=False)
    st.rerun()


@st.dialog("Files and baseline", width="large", on_dismiss=_close_window)
def _window(store: SnapshotStore | None) -> None:
    """Show the window of the sidebar's Files and Baseline lines.

    A widget inside it reruns this function only (st.dialog is a fragment): nothing applies before Done,
    which reads the files and sets the baseline choice; closing it otherwise changes nothing. The section
    the line names comes first; without the Files section (``_window_sections``) Done keeps the files
    already read.
    """
    source = st.session_state.get("files_source") or ("none",)
    with st.container(key="files_sheet"):
        choice = _draw_sections(_window_sections(has_series=store is not None), source, store)
        with st.container(key="xd_foot", horizontal=True, vertical_alignment="center"):
            clash = choice is not None and choice[0] == "upload" and bool(_same_names(choice[1]))
            unloads = choice is None and store is not None  # Done would unload the series
            st.caption(
                "Tick a file: Done with none would unload the series" if unloads else "Done applies · Esc cancels"
            )
            is_done = st.button(
                "Done",
                type="primary",
                key="files_done",
                shortcut="Ctrl+Enter",
                disabled=clash or unloads,
                help="Reads the ticked files, then the pages draw once the whole series is loaded; another choice "
                "of files asks for its baseline once. Use Ctrl+Enter; Esc cancels. Disabled while two uploads "
                "share a name, or while no file is ticked and a series is loaded.",
            )
        if is_done:
            _on_done(choice, store)


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
