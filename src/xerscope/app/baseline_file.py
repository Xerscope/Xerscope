"""The separate baseline file: picked in the folder, uploaded in the window, or named by XERSCOPE_BASELINE.

In the folder: the P6 XML exports next to the updates, its .xer files not ticked as updates (which one is
a baseline is often known only once the series is read), and every .xer and P6 XML file of its
``baselines`` subfolder (``BASELINES_FOLDER``), which the updates are never read from. A baseline exported
as its own XER can sit there under the name of an update.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

import streamlit as st

from xerscope.app.session import BL_EACH, BL_FILE, _data_locked, _digest
from xerscope.xer import is_pmxml, pmxml_files, xer_files
from xerscope.xer.pmxml import DiskFile

BASELINES_FOLDER = "baselines"  # the subfolder of the updates' folder that holds baseline files only


def _folder_baseline_names(session: MutableMapping | None = None) -> list[str]:
    """Return the baseline files of the folder the updates were read from; none when the updates were uploaded.

    The P6 XML exports next to the updates, by name (a P6 XML export holds a project's baselines, which its
    XER does not), then the folder's .xer files left unticked, by name (a ticked one is an update of the
    series), then the .xer and P6 XML files of the ``baselines`` subfolder, as "baselines/<name>": the
    folder of the updates is read for .xer files only, not its subfolders.
    """
    session = st.session_state if session is None else session
    source: tuple = session.get("files_source") or ("none",)
    root = Path(source[1]).expanduser() if source[0] == "folder" else None
    if root is None or not root.is_dir():
        return []
    ticked = set(source[2]) if len(source) > 2 else set()
    names = [path.name for path in pmxml_files(root)]
    names += [path.name for path in xer_files(root) if path.name not in ticked]
    held = root / BASELINES_FOLDER
    if held.is_dir():
        names += [f"{BASELINES_FOLDER}/{path.name}" for path in sorted([*xer_files(held), *pmxml_files(held)])]
    return names


def is_xml_name(name: str) -> bool:
    """Tell whether a name of ``_folder_baseline_names`` is a P6 XML file: one the updates can be looked for in."""
    return name.lower().endswith(".xml")


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


def _disk_baseline_file(path: Path, name: str = "") -> tuple[str, bytes | DiskFile]:
    """Return a baseline file of the disk as (name, contents).

    ``name``: the one it is listed under in the folder ("baselines/<name>" in the subfolder, so that it never
    takes the name of an update), else the file's own. A P6 XML export is handed out to be read where asked,
    never whole: it runs to gigabytes, and a rerun reads none of it once its baselines are built. An XER, a
    few megabytes, is read as it always was.
    """
    export = DiskFile(path)
    return name or path.name, export if is_pmxml(export) else path.read_bytes()


def _picked_folder_file(session: MutableMapping | None = None, exports: list[str] | None = None):
    """Return the baseline file picked in the folder as (name, contents), None when none is picked."""
    picked = _picked_folder_baseline(session, exports)
    if picked is None:
        return None
    session = st.session_state if session is None else session
    return _disk_baseline_file(picked, session.get("bl_folder_file") or "")


def _baseline_file_source(env_path: str | None, exports: list[str]) -> tuple[str, bytes | DiskFile] | None:
    """Return the separate baseline file.

    The one picked in the folder (among ``exports``), else the one uploaded in the window, else
    XERSCOPE_BASELINE's.
    """
    picked = _picked_folder_file(exports=exports)
    if picked is not None:
        return picked
    source = None if _data_locked() else st.session_state.get("bl_file")
    env_path = os.environ.get("XERSCOPE_BASELINE", "") if env_path is None else env_path
    if source is None and env_path and Path(env_path).is_file():
        source = _disk_baseline_file(Path(env_path))
    return source


def baseline_items(session: MutableMapping) -> list[tuple[str, bytes | DiskFile]]:
    """Return the separate baseline file as (name, contents), when one is in use.

    Picked in the folder, uploaded or XERSCOPE_BASELINE: the baseline or the fallback of the window, or,
    in the per-file mode, the P6 XML export the updates are looked for in (an XER is no such export).
    """
    is_the_baseline = session.get("bl_choice") == BL_FILE or session.get("bl_fallback") == BL_FILE
    if not is_the_baseline and session.get("bl_choice") != BL_EACH:
        return []
    held = _picked_folder_file(session)
    if held is None and not _data_locked():
        held = session.get("bl_file")
    env_path = os.environ.get("XERSCOPE_BASELINE", "")
    if held is None and env_path and Path(env_path).is_file():
        held = _disk_baseline_file(Path(env_path))
    if held is None or not (is_the_baseline or is_pmxml(held[1])):
        return []
    return [held]


def baseline_files_tag(session: MutableMapping) -> tuple[tuple[str, str], ...]:
    """Return the (name, digest) of each ``baseline_items`` file.

    With the signature, which files an anonymizer or an extract was built from.
    """
    return tuple((name, _digest(data)) for name, data in baseline_items(session))


def drafted_baseline_file(exports: list[str]) -> tuple[str, bytes | DiskFile] | None:
    """Return the separate baseline file the window's drafts point at, before Done applies them.

    The one drafted in the folder's list, else the one uploaded now, else the one in force (held or named
    by XERSCOPE_BASELINE).
    """
    session = st.session_state
    name = session.get("draft_bl_folder_file") or ""
    if name and name in exports:  # "" is the window's "(none)"
        return _picked_folder_file({"files_source": session.get("files_source"), "bl_folder_file": name}, exports)
    upload = None if _data_locked() else session.get("bl_upload")
    if upload is not None:
        return upload.name, upload.getvalue()
    return _baseline_file_source(None, [])
