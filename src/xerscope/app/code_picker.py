"""The two widgets that pick a P6 activity code: its type, then its values.

Drawn on a page that filters tasks by activity code (the Gantt). The values come from the
snapshot shown; nothing but the picked labels and typed texts comes back from the browser.
"""

from __future__ import annotations

import streamlit as st

from xerscope.analysis.task_filters import CodeFilter, code_value_labels, matching_code_ids
from xerscope.xer.model import Snapshot


def _draw_code_widgets(snapshot: Snapshot, key_prefix: str) -> tuple[str | None, dict[str, str], list[str]]:
    """Draw the two widgets; return the code type picked (the file's label), its value labels and the picks."""
    code_type, by_label, picks = None, {}, []
    if not snapshot.code_values.empty:  # the file's P6 activity codes, if it has any
        type_column, value_column = st.columns([1, 2])
        code_type = type_column.selectbox(
            "Task code (P6 activity code)",
            list(dict.fromkeys(snapshot.code_values["code_type"])),
            index=None,
            placeholder="None",
            help="Picks one activity code type of the file (P6 ACTVTYPE); its values then filter the page's tasks. "
            "Use it to read one trade, area or contract on its own; None keeps every task.",
        )
        by_label = code_value_labels(snapshot, code_type) if code_type else {}
        placeholder = "Pick a task code first"
        if code_type:
            placeholder = "Type to search; pick a value, or press Enter to keep every value containing the text"
        picks = value_column.multiselect(
            "Code values",
            list(by_label),
            placeholder=placeholder,
            accept_new_options=True,
            filter_mode="contains",
            disabled=code_type is None,
            help="The values of the picked code type to keep; a typed text followed by Enter keeps every value "
            "containing it. Use it to narrow to a few values when the type has many.",
            key=f"{key_prefix}_code_values:{code_type}",  # another code type starts with nothing picked
        )
    return code_type, by_label, picks


def pick_activity_code(snapshot: Snapshot, key_prefix: str) -> tuple[str | None, set[str] | None]:
    """Draw the two widgets; return the code type picked and the ``code_id`` of the values it keeps.

    A value picked from the suggestions is that value exactly ("equals"); a text typed keeps every
    value containing it ("contains"). Returns ``(None, None)`` when the file has no activity code,
    and ``code_ids`` None when no value is picked: no filter on the code. ``key_prefix`` names the
    page, so that each page keeps its own picks.
    """
    code_type, by_label, picks = _draw_code_widgets(snapshot, key_prefix)
    if not picks:  # nothing picked: no filter on the code
        return code_type, None
    values = snapshot.code_values[snapshot.code_values["code_type"] == code_type]
    return code_type, matching_code_ids(values, by_label, picks)


def pick_code_filter(snapshot: Snapshot, key_prefix: str) -> CodeFilter | None:
    """Draw the two widgets; return the filter they make, None when no value is picked.

    The filter names the code type by its P6 name, so it holds in every file of the series.
    """
    code_type, _, picks = _draw_code_widgets(snapshot, key_prefix)
    if not picks:
        return None
    values = snapshot.code_values
    return CodeFilter(values.loc[values["code_type"] == code_type, "type_name"].iloc[0], tuple(picks))
