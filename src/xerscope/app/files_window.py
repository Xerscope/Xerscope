"""The Files window of the sidebar: file listing, uploads and the project fields."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import streamlit as st

from xerscope.app import ui
from xerscope.app.baselines import _baseline_fields, _project_labels
from xerscope.app.session import (
    BASELINE_ALONE,
    BASELINE_ASKED,
    BASELINE_SET,
    NBSP,
    UPLOAD_TYPES,
    _apply_drafts,
    _close_window,
    _data_locked,
    _digest,
    _project_draft,
    _section_title,
)
from xerscope.store import SnapshotStore
from xerscope.xer import FileHeader, XerError, baseline_copies, load_header, xer_files
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


def _folder_boxes(folder: str, chosen: tuple[str, ...]) -> tuple[str, ...]:
    """Show one tick box per XER file of ``folder`` and return the names ticked.

    ``chosen``: the names of the last validated choice, ticked again when the window reopens (its boxes
    are gone once closed).
    """
    root = Path(folder).expanduser()
    files = xer_files(root) if root.is_dir() else []
    if not files:
        st.error("Folder not found" if not root.is_dir() else "No .xer file in that folder")
        return ()
    # Widget keys name the folder by a hash: a key shows in the page as a CSS class, and the
    # folder path is the server's.
    folder_id = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    # nothing ticked by default: a file is read (up to ~1 GB for a 40 MB export) only once asked for
    keys = {path.name: f"read:{folder_id}:{path.name}" for path in files}
    for name, key in keys.items():
        st.session_state.setdefault(key, name in chosen)

    headers = {path.name: _header(path) for path in files}
    # the series holds one update per status date: of the files sharing one, the first by name is
    # the one Select all ticks, the others say which file they double
    first_by_date: dict[pd.Timestamp, str] = {}
    same_date_as: dict[str, str] = {}
    for name, header in headers.items():
        if isinstance(header, str) or header.data_date is None:
            continue
        kept = first_by_date.setdefault(header.data_date, name)
        if kept != name:
            same_date_as[name] = kept
    readable = [name for name, header in headers.items() if not isinstance(header, str) and name not in same_date_as]

    def tick_all(value: bool) -> None:
        """Select all ticks every readable file but the doubles of a status date; Clear unticks all."""
        names = readable if value else list(keys)
        st.session_state.update({keys[name]: value for name in names})

    ticked = sum(bool(st.session_state[key]) for key in keys.values())
    count, select, clear = st.columns([2, 1, 1], vertical_alignment="center")
    count.caption(f"{ticked} of {len(files)} ticked")
    select.button("Select all", key=f"all:{folder_id}", on_click=tick_all, args=(True,), width="stretch")
    clear.button("Clear", key=f"none:{folder_id}", on_click=tick_all, args=(False,), width="stretch")
    picked = []
    with st.container(key="files_list_folder"):
        for path in files:
            label, details = _describe_file(path, same_date_as.get(path.name))
            if st.checkbox(label, key=keys[path.name], help=details):
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
                ui.md_text(name), value=True, key=f"keep:{digest[:12]}:{name}", help=f"{len(data) / 1e6:.1f} MB"
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
            "Upload .xer files", type=UPLOAD_TYPES, accept_multiple_files=True, key="files_upload"
        )
        folder = st.text_input("…or read a folder", key="files_folder", placeholder="/path/to/exports")
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
        sections = _window_sections(has_series=store is not None)
        choice = None if "files" in sections else st.session_state.get("files_source")
        for index, section in enumerate(sections):
            if index:
                st.html('<hr class="xd-rule">')
            if section == "files":
                choice = _files_section(source, store)
            else:
                _baseline_fields(store)
        with st.container(key="xd_foot", horizontal=True, vertical_alignment="center"):
            st.caption("Done applies · Esc cancels")
            clash = choice is not None and choice[0] == "upload" and bool(_same_names(choice[1]))
            if st.button("Done", type="primary", key="files_done", shortcut="Ctrl+Enter", disabled=clash):
                _apply_drafts()
                if choice != st.session_state.get("files_source"):  # other files: their baseline is asked once read
                    st.session_state.update({BASELINE_ASKED: False, BASELINE_SET: False})
                elif store is not None:  # the Baseline section was shown
                    st.session_state[BASELINE_SET] = True
                st.session_state.update(files_source=choice, files_open=False)
                st.rerun()
