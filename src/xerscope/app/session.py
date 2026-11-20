"""Session-state keys and the window and lock helpers every other app module shares."""

from __future__ import annotations

import hashlib
import html
import os
from pathlib import Path

import streamlit as st

from xerscope.app import ui
from xerscope.store import SnapshotStore
from xerscope.xer import XER_SUFFIXES
from xerscope.xer.pmxml import DiskFile

# Streamlit wants extensions without the dot.
UPLOAD_TYPES = [suffix.lstrip(".") for suffix in XER_SUFFIXES]


NBSP = "\u00a0"  # thousands separator that does not break a label across lines


def _file_choices() -> dict[str, str]:
    """Return the project picked for a file in the window's Files section: proj_id by file name."""
    return st.session_state.setdefault("file_projects", {})


def _digest(data: bytes | DiskFile) -> str:
    """Return the sha256 of a file's contents.

    Of a file read from the disk where asked, the one computed from the file itself and kept until the
    file changes (``_file_digest``). Of the uploaded baseline, the one computed when it was held
    (``_apply_drafts``): the memo asks for it on every call.
    """
    if isinstance(data, DiskFile):
        return _file_digest(data.path)
    held, held_digest = st.session_state.get("bl_file_digest", (None, ""))
    return held_digest if data is held else hashlib.sha256(data).hexdigest()


# The window's baseline selectors write to drafts, filled with the values in force when it opens;
# Done copies them to the keys the app reads, closing it otherwise (Esc, ✕, a click outside) drops them.
DRAFTS = {
    "bl_choice": "draft_bl_choice",
    "ev_basis": "draft_ev_basis",
    "bl_fallback": "draft_bl_fallback",
    "bl_folder_file": "draft_bl_folder_file",
    "guid_link": "draft_guid_link",
}


def _project_draft(source: str) -> str:
    """Return the draft key of the project picked for file ``source`` in the window (its proj_id)."""
    return f"draft_file_project:{source}"


def _open_window(section: str) -> None:
    st.session_state.update(files_open=True, window_section=section)
    # The folder field shows the folder of the last validated choice, else XERSCOPE_DATA. Set here,
    # not as a default of the widget: when the window closes without Done, the browser leaves the
    # field's key in the session state with an empty value, which a default would not fill.
    source = st.session_state.get("files_source") or ("none",)
    st.session_state["files_folder"] = source[1] if source[0] == "folder" else os.environ.get("XERSCOPE_DATA", "")
    for key, draft in DRAFTS.items():
        if key in st.session_state:
            st.session_state[draft] = st.session_state[key]
    for snapshot in st.session_state.get("store") or ():
        st.session_state[_project_draft(snapshot.source)] = snapshot.project_id


def _apply_drafts() -> None:
    """On Done, make the window's baseline choice the one in force, its uploaded file held.

    A project picked for a file other than the one read is recorded, and the next run reads that file
    again.
    """
    for key, draft in DRAFTS.items():
        if draft in st.session_state:
            st.session_state[key] = st.session_state[draft]
    for snapshot in st.session_state.get("store") or ():
        chosen = st.session_state.get(_project_draft(snapshot.source))
        if chosen is not None and chosen != snapshot.project_id:
            _file_choices()[snapshot.source] = chosen
    upload = st.session_state.get("bl_upload")
    if upload is not None:
        contents = upload.getvalue()
        st.session_state["bl_file"] = (upload.name, contents)
        st.session_state["bl_file_digest"] = (contents, hashlib.sha256(contents).hexdigest())


def _close_window() -> None:
    st.session_state["files_open"] = False


def _section_title(text: str, note: str = "") -> None:
    """Show a section's title in the window, ``note`` aligned right (a count, a state)."""
    st.html(f'<div class="xd-title"><span>{html.escape(text)}</span><span>{html.escape(note)}</span></div>')


def _file_digest(path: Path) -> str:
    """Return the sha256 of a folder's file, keyed on content as an upload.

    Read and digested again only when its inode, size, modification or change time moved: a file replaced
    under the same name and modification time (os.utime) still gets a new change time. Kept in the
    session's state.
    """
    cache = st.session_state.setdefault("_file_digests", {})
    stat = path.stat()
    stamp = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    kept = cache.get(str(path))
    if kept is None or kept[0] != stamp:
        with path.open("rb") as file:  # in pieces: a P6 XML export runs to gigabytes
            kept = (stamp, hashlib.file_digest(file, "sha256").hexdigest())
        cache[str(path)] = kept
    return kept[1]


def debug_page() -> bool:
    """Return whether the Debug page is in the navigation.

    Always on a workstation; on a deployed instance (``_data_locked``) only with XERSCOPE_DEBUG_PAGE=1,
    since the page describes the server's reading of every file to whoever holds the URL.
    """
    asked = os.environ.get("XERSCOPE_DEBUG_PAGE", "").lower() in ("1", "true", "yes")
    return not _data_locked() or asked


def data_locked() -> bool:
    """Return whether this is a remote deployment (``_data_locked``).

    Pages show nothing about the server (Debug block 12).
    """
    return _data_locked()


def folder_root() -> Path:
    """Return the folder a typed folder must lie under.

    XERSCOPE_FOLDER_ROOT when set, else the folder of XERSCOPE_DATA, else the home directory. The
    field of the Files window reads nothing outside it, so a path typed in the page cannot walk the
    server's file system (CodeQL path injection).
    """
    root = os.environ.get("XERSCOPE_FOLDER_ROOT") or os.environ.get("XERSCOPE_DATA") or str(Path.home())
    return Path(os.path.realpath(os.path.expanduser(root)))


def folder_under_root(folder: str) -> Path | None:
    """Return the resolved ``folder`` when it lies under ``folder_root()``, else None."""
    root = str(folder_root())
    resolved = os.path.realpath(os.path.expanduser(folder))
    if resolved == root:
        return Path(root)
    if resolved.startswith(root + os.sep):
        return Path(resolved)
    return None


def _data_locked() -> bool:
    """Return whether this is a remote deployment: the visitor reads the server's exports folder and nothing else.

    No path field (the app cannot be pointed elsewhere) and no upload (one parsed export of 40 MB takes
    about 1 GB, so a few uploads would push the app past its memory cap, docs/deploy.md §7).
    """
    return os.environ.get("XERSCOPE_DATA_LOCKED", "").lower() in ("1", "true", "yes")


def _period(store: SnapshotStore) -> str:
    """Return the first and last data dates, the year written once when both share it: one sidebar row."""
    first, last = store.first.data_date, store.latest.data_date
    start = ui.fmt_date(first)
    if first is not None and last is not None and first.year == last.year:
        start = start.rsplit(" ", 1)[0]
    return f"{start} → {ui.fmt_date(last)}"


# A series just read waits for its baseline: the window opens once on its Baseline section
# (BASELINE_ASKED), and nothing is computed against a baseline before Done there (BASELINE_SET).
BASELINE_ASKED = "baseline_asked"


BASELINE_SET = "baseline_set"


BASELINE_ALONE = "baseline alone"  # the window's section when it opens by itself: no Files section


BL_NONE = "None"


BL_EACH = "Baseline in each file (P6 Project Baseline)"


BL_PLANNED = "Planned dates in each file (target_*)"


BL_FILE = "Separate baseline file"


EV_BASIS_LABEL = {
    "budgeted_planned": "Budgeted · planned dates",
    "budgeted_current": "Budgeted · current dates",
    "at_completion_current": "At completion · current dates",
}


def counted(number: int, word: str, plural: str | None = None) -> str:
    """Return ``3 files`` or ``1 file``: the number and its word, in the plural unless the number is 1.

    ``plural`` gives the irregular plural of a word (``copy``, ``copies``).
    """
    if number == 1:
        return f"{number} {word}"
    if plural is None:
        plural = f"{word}s"
    return f"{number} {plural}"


SNAP_CHOICE = "snap_choice"  # the update picked on any page: every page's picker follows it


COMPARE_NONE = "None"


COMPARE_PREV = "Previous update"


COMPARE_BL = "Baseline (BL)"


COMPARE_FIRST = "First snapshot"


ANONYMISED = " · anonymized"  # suffix of an anonymized download's label


PREPARE_LABEL = "Prepare anonymized downloads"
