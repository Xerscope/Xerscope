"""One activity: its P6 properties in the update shown, then its history across every update.

Drawn under the Gantt for the activity picked there, and by the Task history page. The
activity is named by its Activity ID (task_code) only; every value shown is read from the
loaded snapshot or store, nothing comes back from the browser but that ID.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from xerscope.analysis.progress import activity_finish_shift
from xerscope.app import ui
from xerscope.config import DATETIME_FMT
from xerscope.viz.charts import build_activity_dates, build_activity_float
from xerscope.xer.model import CONSTRAINT, PCT_COMPLETE_TYPE, RSRC_TYPE, TASK_TYPE

# The panel's yes / no reads model.HARD_CONSTRAINTS, the DCMA-05 set (Start on, Start on or before, Finish
# on, Finish on or before, Mandatory start / finish); P6-02 counts a narrower set. The label says which.
HARD_CONSTRAINT_LABEL = "Hard constraint (DCMA-05 set)"

ROW_PREFIX = "a:"  # Gantt row id of an activity (viz/gantt.py); "w:" is a WBS row
MAX_ID = 200  # characters: longer than any Activity ID P6 stores, shorter than a forged payload

HISTORY_COLUMNS = [
    "data_date",
    "status",
    "start",
    "finish",
    "total_float_d",
    "remaining_d",
    "original_d",
    "pct_complete",
    "is_critical",
]


def task_from_row_id(value: object) -> str | None:
    """The Activity ID of a Gantt row id ("a:C3020" -> "C3020"); None for a WBS row, an empty
    or oversized value or anything but a string. The caller still checks the ID is drawn."""
    if not isinstance(value, str) or not value.startswith(ROW_PREFIX) or len(value) > MAX_ID:
        return None
    return value[len(ROW_PREFIX) :] or None


# --- identity card ----------------------------------------------------------------------


def _text(value) -> str:
    return "–" if value is None or (not isinstance(value, str) and pd.isna(value)) or value == "" else str(value)


def _when(value) -> str:
    return "–" if pd.isna(value) else pd.Timestamp(value).strftime(DATETIME_FMT)


def _days(value) -> str:
    return "–" if pd.isna(value) else f"{value:.1f} wd"


def _yes(value) -> str:
    return "–" if pd.isna(value) else ("Yes" if bool(value) else "No")


def _constraint(kind, date) -> str:
    if pd.isna(kind) or kind == "":
        return "–"
    label = CONSTRAINT.get(kind, kind)
    return label if pd.isna(date) else f"{label} {_when(date)}"


def task_rows(snapshot, task_code: str) -> pd.DataFrame:
    """The activity's rows in ``snapshot`` (one, unless the file repeats the Activity ID)."""
    activities = snapshot.activities
    return activities[activities["task_code"] == task_code]


def card_sections(snapshot, task: pd.Series) -> list[tuple[str, list[tuple[str, str]]]]:
    """The activity's properties as P6 stores them, grouped as in P6's Activity Details, each
    value read from the snapshot's columns (no value is recomputed here)."""
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
                ("Task codes", " · ".join(code_text) or "–"),
            ],
        ),
        (
            "Status",
            [
                ("Status", _text(task["status"])),
                ("% complete", "–" if pd.isna(task["pct_complete"]) else f"{task['pct_complete']:.1f} %"),
                ("Original duration", _days(task["original_d"])),
                ("Remaining duration", _days(task["remaining_d"])),
                ("Total float", _days(task["total_float_d"])),
                ("Free float", _days(task["free_float_d"])),
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
                ("Primary constraint", _constraint(task["cstr_type"], task["cstr_date"])),
                ("Secondary constraint", _constraint(task["cstr_type2"], task["cstr_date2"])),
                (HARD_CONSTRAINT_LABEL, _yes(task["has_hard_constraint"])),
            ],
        ),
    ]


def card_html(sections: list[tuple[str, list[tuple[str, str]]]]) -> str:
    """The card's markup; every label and value is escaped (they come from the XER file)."""
    blocks = []
    for title, items in sections:
        pairs = "".join(f"<dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>" for label, value in items)
        blocks.append(f"<section><h4>{html.escape(title)}</h4><dl>{pairs}</dl></section>")
    return f'<div class="xs-card">{"".join(blocks)}</div>'


def resources(snapshot, task_code: str) -> pd.DataFrame:
    """The activity's resource assignments (TASKRSRC): units budgeted, actual, remaining."""
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


def logic(snapshot, task_code: str) -> pd.DataFrame:
    """Predecessors then successors of the activity: the other Activity ID, link type, lag."""
    links = snapshot.relationships
    names = dict(zip(snapshot.activities["task_code"], snapshot.activities["task_name"], strict=False))
    frames = []
    for side, mine, other in (("Predecessor", "succ_code", "pred_code"), ("Successor", "pred_code", "succ_code")):
        rows = links[links[mine] == task_code]
        frames.append(
            pd.DataFrame(
                {
                    "relationship": side,
                    "task_code": rows[other],
                    "task_name": rows[other].map(names),
                    "link type": rows["type"],
                    "lag_d": rows["lag_d"],
                    "external": rows["is_external"],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def show_card(snapshot, task_code: str) -> None:
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
            ui.table(assigned, key="task_resources")
    with logic_column:
        ui.section("Logic")
        links = logic(snapshot, task_code)
        if links.empty:
            st.caption("No relationship.")
        else:
            ui.table(links, key="task_logic")


# --- history ----------------------------------------------------------------------------


def show_history(store, task_code: str) -> None:
    """KPIs, dates and float charts, and the table of the activity across every update."""
    history = store.history[store.history["task_code"] == task_code].sort_values("data_date")
    if history.empty:
        st.caption("This Task ID is in no loaded update.")
        return
    if len(store) - len(history):
        st.caption(f"Present in {len(history)} of {len(store)} updates (added or deleted along the way).")
    last = history.iloc[-1]
    slip = activity_finish_shift(store, history)
    ui.kpis(
        [
            ("Status", last["status"]),
            (
                "Forecast finish",
                ui.fmt_date(last["finish"], "—"),
                None if slip is None else f"{slip:+.1f} wd since first",
                None,
                "inverse",
            ),
            ("Total float", "–" if pd.isna(last["total_float_d"]) else f"{last['total_float_d']:.1f} wd"),
            ("% complete", "–" if pd.isna(last["pct_complete"]) else f"{last['pct_complete']:.0f} %"),
        ]
    )
    dates_column, float_column = st.columns(2, gap="large")
    with dates_column:
        ui.section("Forecast start and finish")
        ui.chart(build_activity_dates(history))
    with float_column:
        ui.section("Total float (working days)")
        ui.chart(build_activity_float(history))
    ui.section("By update")
    ui.table(history, columns=HISTORY_COLUMNS, key="task_history")
