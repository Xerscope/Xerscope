"""One task in one update: its card, resources and logic, as P6's Activity Details shows them.

Shared by the Gantt's task panel. Every value is read from the snapshot; card text is escaped. The driving
flag of a relationship is recalculated by the CPM: P6 does not export it (TASKPRED has no such field).
"""

from __future__ import annotations

import html
from collections.abc import Callable

import pandas as pd
import streamlit as st

from xerscope.analysis.activity_trail import constraint_text, driving_flags
from xerscope.analysis.cpm import ScheduleError, schedule
from xerscope.app import ui
from xerscope.config import DATETIME_FMT
from xerscope.xer.model import PCT_COMPLETE_TYPE, RSRC_TYPE, TASK_TYPE

# The panel's yes / no reads model.HARD_CONSTRAINTS, the DCMA-05 set (Start on, Start on or before, Finish
# on, Finish on or before, Mandatory start / finish); P6-02 counts a narrower set. The label says which.
HARD_CONSTRAINT_LABEL = "Hard constraint (DCMA-05 set)"


# --- identity card ----------------------------------------------------------------------


def _text(value) -> str:
    return ui.MISSING if value is None or (not isinstance(value, str) and pd.isna(value)) or value == "" else str(value)


def _when(value) -> str:
    if pd.isna(value):
        return ui.MISSING
    return pd.Timestamp(value).strftime(DATETIME_FMT)


def _yes(value) -> str:
    if pd.isna(value):
        return ui.MISSING
    return "Yes" if bool(value) else "No"


def _constraint_cell(kind, date) -> str:
    """Return a constraint as the card writes it: P6's name and its date, a dash without one."""
    return constraint_text(kind, date) or "–"


def task_rows(snapshot, task_code: str) -> pd.DataFrame:
    """Return the activity's rows in ``snapshot`` (one, unless the file repeats the Activity ID)."""
    activities = snapshot.activities
    return activities[activities["task_code"] == task_code]


def card_sections(snapshot, task: pd.Series) -> list[tuple[str, list[tuple[str, str]]]]:
    """Return the activity's properties as P6 stores them, grouped as in P6's Activity Details.

    Each value is read from the snapshot's columns (no value is recomputed here).
    """
    calendars = snapshot.calendars.set_index("clndr_id") if not snapshot.calendars.empty else pd.DataFrame()
    calendar = "–"
    if task["clndr_id"] in calendars.index:
        row = calendars.loc[task["clndr_id"]]
        hours = "" if pd.isna(task["hours_per_day"]) else f" · {task['hours_per_day']:g} h/day"
        calendar = f"{_text(row.get('clndr_name'))}{hours}"
    wbs = snapshot.wbs
    wbs_names = dict(zip(wbs["wbs_id"], wbs["wbs_name"], strict=True)) if "wbs_name" in wbs else {}
    codes = snapshot.task_codes[snapshot.task_codes["task_code"] == task["task_code"]]
    code_text = []
    for code_type, code_id in zip(codes["code_type"], codes["code_id"], strict=True):
        code_text.append(f"{code_type}: {snapshot.code_paths(code_type).get(code_id, code_id)}")
    return [
        (
            "Identity",
            [
                ("Task ID", _text(task["task_code"])),
                ("Task name", _text(task["task_name"])),
                ("WBS", f"{_text(task['wbs_code'])} · {_text(wbs_names.get(task['wbs_id']))}"),
                ("Task type", TASK_TYPE.get(task["task_type"], _text(task["task_type"]))),
                ("% complete type", PCT_COMPLETE_TYPE.get(task["complete_pct_type"], _text(task["complete_pct_type"]))),
                ("Calendar", calendar),
                ("Activity codes", " · ".join(code_text) or "–"),
            ],
        ),
        (
            "Status",
            [
                ("Status", _text(task["status"])),
                ("% complete", ui.fmt_number(task["pct_complete"], "{:.1f} %")),
                ("Original duration", ui.fmt_number(task["original_d"], "{:.1f} wd")),
                ("Remaining duration", ui.fmt_number(task["remaining_d"], "{:.1f} wd")),
                ("Total float", ui.fmt_number(task["total_float_d"], "{:.1f} wd")),
                ("Free float", ui.fmt_number(task["free_float_d"], "{:.1f} wd")),
                ("Critical", _yes(task["is_critical"])),
                ("Longest path", _yes(task["on_longest_path"])),
            ],
        ),
        (
            "Dates",
            [
                ("Start", _when(task["start"])),
                ("Finish", _when(task["finish"])),
                ("Actual start", _when(task["act_start_date"])),
                ("Actual finish", _when(task["act_end_date"])),
                ("Early start", _when(task["early_start_date"])),
                ("Early finish", _when(task["early_end_date"])),
                ("Late start", _when(task["late_start_date"])),
                ("Late finish", _when(task["late_end_date"])),
                ("Planned start", _when(task["target_start_date"])),
                ("Planned finish", _when(task["target_end_date"])),
            ],
        ),
        (
            "Constraints",
            [
                ("Primary constraint", _constraint_cell(task["cstr_type"], task["cstr_date"])),
                ("Secondary constraint", _constraint_cell(task["cstr_type2"], task["cstr_date2"])),
                (HARD_CONSTRAINT_LABEL, _yes(task["has_hard_constraint"])),
            ],
        ),
    ]


def card_html(sections: list[tuple[str, list[tuple[str, str]]]]) -> str:
    """Return the card's markup; every label and value is escaped (they come from the XER file)."""
    blocks = []
    for title, items in sections:
        pairs = "".join(f"<dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>" for label, value in items)
        blocks.append(f"<section><h4>{html.escape(title)}</h4><dl>{pairs}</dl></section>")
    return f'<div class="xs-card">{"".join(blocks)}</div>'


def resources(snapshot, task_code: str) -> pd.DataFrame:
    """Return the activity's resource assignments (TASKRSRC): units budgeted, actual, remaining."""
    rows = snapshot.assignments[snapshot.assignments["task_code"] == task_code]
    return pd.DataFrame(
        {
            "resource": rows["rsrc_name"].where(rows["rsrc_name"].astype(str) != "", rows["rsrc_short_name"]),
            "resource type": rows["rsrc_type"].map(lambda kind: RSRC_TYPE.get(kind, kind)),
            "driving": rows["driving"],
            "budgeted units": rows["target_qty"],
            "actual units": rows["act_qty"],
            "remaining units": rows["remain_qty"],
        }
    )


def recalculated_links(snapshot) -> pd.DataFrame | None:
    """Return every relationship with its driving flag as the recalculation gives it (``cpm.Schedule.links``).

    None when the update cannot be scheduled. P6 does not export its own (TASKPRED has no such field).
    """
    try:
        return schedule(snapshot).links
    except ScheduleError:
        return None


def logic(snapshot, task_code: str) -> pd.DataFrame:
    """Return the activity's predecessors, then its successors.

    The other Activity ID, link type, lag, whether the link drives, and the other activity's longest path
    flag, total float and dates as P6 stored them.
    """
    links = snapshot.relationships
    tasks = snapshot.by_code
    driving = driving_flags(snapshot)
    frames = []
    for side, mine, other in (("Predecessor", "succ_code", "pred_code"), ("Successor", "pred_code", "succ_code")):
        rows = links[links[mine] == task_code]
        keys = zip(rows["pred_code"], rows["succ_code"], rows["type"], strict=True)
        others = rows[other]
        frames.append(
            pd.DataFrame(
                {
                    "relationship": side,
                    "task_code": others,
                    "task_name": others.map(tasks["task_name"]),
                    "link type": rows["type"],
                    "lag_d": rows["lag_d"],
                    "driving_link": [driving.get(key) for key in keys],
                    "on_longest_path": others.map(tasks["on_longest_path"]),
                    "total_float_d": others.map(tasks["total_float_d"]),
                    "start": others.map(tasks["start"]),
                    "finish": others.map(tasks["finish"]),
                    "external": rows["is_external"],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def show_card(snapshot, task_code: str, open_task: Callable[[str], None] | None = None) -> None:
    """Show the activity's card, its resources and its logic; ``open_task`` makes a Logic row open its task."""
    rows = task_rows(snapshot, task_code)
    if len(rows) != 1:
        st.warning(
            f"Task ID {ui.md_text(task_code)} is on {len(rows)} rows of this update: no card is drawn, "
            "a Task ID names one task of a project.",
            icon=":material/warning:",
        )
        return
    st.html(card_html(card_sections(snapshot, rows.iloc[0])))
    resource_column, logic_column = st.columns(2, gap="large")
    with resource_column:
        ui.section("Resources")
        assigned = resources(snapshot, task_code)
        if assigned.empty:
            st.caption("No resource assignment.")
        else:
            ui.table(assigned, key="task_resources", reading="task_resources")
    with logic_column:
        ui.section("Logic")
        links = logic(snapshot, task_code)
        if links.empty:
            st.caption("No relationship.")
        else:
            ui.table(links, key=f"task_logic:{task_code}", reading="task_logic", open_task=open_task)
