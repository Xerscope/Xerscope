"""The two widgets that pick a P6 activity code: its type, then its values.

Drawn on a page that filters tasks by activity code (the Gantt). The values come from the
snapshot shown; nothing but the picked labels and typed texts comes back from the browser.
"""

from __future__ import annotations

import streamlit as st

from xerscope.analysis.task_filters import matching_code_ids
from xerscope.xer.model import Snapshot


def pick_activity_code(snapshot: Snapshot, key_prefix: str) -> tuple[str | None, set[str] | None]:
    """Draw the two widgets; return the code type picked and the ``code_id`` of the values it keeps.

    A value picked from the suggestions is that value exactly ("equals"); a text typed keeps every
    value containing it ("contains"). Returns ``(None, None)`` when the file has no activity code,
    and ``code_ids`` None when no value is picked: no filter on the code. ``key_prefix`` names the
    page, so that each page keeps its own picks.
    """
    code_type, code_ids = None, None
    if not snapshot.code_values.empty:  # the file's P6 activity codes, if it has any
        type_column, value_column = st.columns([1, 2])
        code_type = type_column.selectbox(
            "Task code (P6 activity code)",
            list(dict.fromkeys(snapshot.code_values["code_type"])),
            index=None,
            placeholder="None",
        )
        values = snapshot.code_values[snapshot.code_values["code_type"] == code_type]
        paths = snapshot.code_paths(code_type) if code_type else {}
        description = dict(zip(values["code_id"], values["name"], strict=True))
        by_label = {f"{path} · {description[code_id]}": code_id for code_id, path in paths.items()}
        picks = value_column.multiselect(
            "Code values",
            list(by_label),
            placeholder="Type to search; pick a value, or press Enter to keep every value containing the text"
            if code_type
            else "Pick a task code first",
            accept_new_options=True,
            filter_mode="contains",
            disabled=code_type is None,
            key=f"{key_prefix}_code_values:{code_type}",  # another code type starts with nothing picked
        )
        if picks:  # nothing picked: no filter on the code
            code_ids = matching_code_ids(values, by_label, picks)
    return code_type, code_ids
