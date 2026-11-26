"""One activity: its P6 properties in the update shown, then its history across every update.

Drawn under the Gantt for the activity picked there. The activity is named by its Activity ID
(task_code) only; every value shown is read from the loaded snapshot or store, nothing comes
back from the browser but that ID.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import streamlit as st

from xerscope.analysis.activity_trail import (
    BOTH,
    DOWNSTREAM,
    PREDECESSOR,
    SUCCESSOR,
    TASK,
    UPSTREAM,
    constraint_history,
    trail_by_update,
)
from xerscope.analysis.progress import activity_finish_shift
from xerscope.app import ui
from xerscope.viz.charts import build_activity_history, link_text

ROW_PREFIX = "a:"  # Gantt row id of an activity (viz/gantt.py); "w:" is a WBS row
MAX_ID = 200  # characters: longer than any Activity ID P6 stores, shorter than a forged payload

OPENED = "opened"  # a breadcrumb row: a task opened in the panel, before its neighbours
ROLE_LABEL = {PREDECESSOR: "predecessor", SUCCESSOR: "successor"}
CHAIN_DIRECTIONS = {UPSTREAM: "Predecessors", DOWNSTREAM: "Successors", BOTH: "Both"}
CHAIN_DEPTH = 3  # links followed by default: a reader's usual look around a task, a few dozen tasks at most
CHAIN_MAX_DEPTH = 10

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


def chain_request(task_code: str) -> tuple[str, int, bool] | None:
    """The chain of linked tasks the viewer asks to see in the Gantt: (direction, depth, driving only),
    None until the button is pressed."""
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        direction = st.segmented_control(
            "Chain",
            list(CHAIN_DIRECTIONS),
            default=BOTH,
            format_func=CHAIN_DIRECTIONS.__getitem__,
            key="task_chain_direction",
            help="Which side of the task to follow: its predecessors, its successors, or each side.",
        )
        depth = st.number_input(
            "Links deep",
            min_value=1,
            max_value=CHAIN_MAX_DEPTH,
            value=CHAIN_DEPTH,
            key="task_chain_depth",
            help="How many relationships to follow from the task.",
        )
        driving_only = st.toggle(
            "Driving links only",
            key="task_chain_driving",
            help="Follow only the links that set their successor's date (P6's Driving checkbox, recalculated "
            "by the CPM because the XER does not export it).",
        )
        asked = st.button(
            "Show the chain in the Gantt",
            icon=":material/account_tree:",
            key="task_chain_show",
            help=f"Draws only {ui.md_text(task_code)} and the tasks linked to it; Show all draws everything again.",
        )
    return (direction or BOTH, int(depth), driving_only) if asked else None


def show_trail(store, trail: list[str], logic: pd.DataFrame, open_task: Callable[[str], None]) -> None:
    """The breadcrumb, one row per task and a column per status date: the tasks opened (the one shown
    last), then the predecessors and successors of the one shown, as each update links them (link type,
    driving), with P6's total and free float and the constraints. A blank cell: not in that update, or
    not linked to the task there. Selecting a row opens its task."""
    opened = trail_by_update(store, trail).assign(role=OPENED, link_type=None, driving_link=None)
    neighbours = logic[logic["role"] != TASK]
    rows = pd.concat([opened, neighbours], ignore_index=True)
    if rows.empty:
        return
    # one column per status date (a store holds one update per data date): short headers, in date order
    cells = rows.assign(
        cell=[_logic_cell(row) for row in rows.itertuples()],
        status_date=rows["data_date"].map(ui.fmt_date),
    )
    matrix = cells.pivot_table(index=["role", "task_code"], columns="status_date", values="cell", aggfunc="first")
    date_of = dict(zip(cells["status_date"], cells["data_date"], strict=True))
    order = sorted(date_of, key=date_of.__getitem__)
    matrix = matrix.reindex(index=pd.MultiIndex.from_tuples(_trail_rows(trail, opened, neighbours)), columns=order)
    shown = matrix.reset_index(names=["role", "task_code"])
    # how many links away, the nearest any update has it; blank on a task opened
    nearest = neighbours.groupby(["role", "task_code"])["level"].min()
    levels = [nearest.get((role, code)) for role, code in zip(shown["role"], shown["task_code"], strict=True)]
    shown.insert(1, "level", pd.array(levels, dtype="Int64"))
    ui.table(shown, key="task_trail", reading="task_trail", open_task=open_task)


def _trail_rows(trail: list[str], opened: pd.DataFrame, neighbours: pd.DataFrame) -> list[tuple[str, str]]:
    """The breadcrumb's rows in order: the tasks opened as they were opened, then predecessors, then
    successors, nearest first."""
    present = set(opened["task_code"])
    rows = [(OPENED, code) for code in trail if code in present]
    for role in (PREDECESSOR, SUCCESSOR):
        side = neighbours[neighbours["role"] == role].sort_values("level", kind="stable")
        rows += [(role, code) for code in side["task_code"].drop_duplicates()]
    return rows


def pick_neighbours(logic: pd.DataFrame, task_code: str) -> list[str]:
    """The predecessors and successors, of any update, the viewer picks to draw beside the task's float."""
    neighbours = logic[logic["role"] != TASK].sort_values("level", kind="stable").drop_duplicates("task_code")
    labels = {
        code: ROLE_LABEL[role] + (f" · level {level}" if level > 1 else "")
        for code, role, level in zip(neighbours["task_code"], neighbours["role"], neighbours["level"], strict=True)
    }
    return st.multiselect(
        "Show on the chart",
        list(labels),
        format_func=lambda code: f"{code} · {labels[code]}",
        key=f"task_float_shown:{task_code}",
        placeholder="Predecessors and successors to draw",
        help="Hover a point of the task for that update's predecessors and successors; pick one here to draw "
        "its total float too (dotted: predecessor, dashed: successor; faded where the link does not drive).",
    )


def _logic_cell(row) -> str:
    link = link_text(row.link_type, row.driving_link)
    return f"{link} · {_trail_cell(row)}" if link else _trail_cell(row)


def _trail_cell(row) -> str:
    total = ui.fmt_number(row.total_float_d, "{:.1f}")
    free = ui.fmt_number(row.free_float_d, "{:.1f}")
    constraints = " / ".join(text for text in (row.primary, row.secondary) if isinstance(text, str)) or "–"
    return f"TF {total} · FF {free} · {constraints}"


# --- history ----------------------------------------------------------------------------


def show_history(store, task_code: str, logic: pd.DataFrame) -> None:
    """KPIs, dates and float charts, and the table of the activity across every update. ``logic``: its
    neighbours in each update (``activity_trail.logic_by_update``), for the float chart."""
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
                None if slip is None else f"{ui.SHIFT_WD_FORMAT.format(slip)} since first",
                f"Forecast finish against the first forecast of this task, on its own calendar. {ui.SHIFT_WD_SENTENCE}",
            ),
            ("Total float", ui.fmt_number(last["total_float_d"], "{:.1f} wd")),
            ("% complete", ui.fmt_number(last["pct_complete"], "{:.0f} %")),
        ]
    )
    ui.section("Forecast dates and total float")
    shown = pick_neighbours(logic, task_code)
    ui.chart(build_activity_history(history, logic, shown))
    ui.section("By update")
    ui.table(history, columns=HISTORY_COLUMNS, key="task_history", reading="task_history")
    ui.section("Constraint changes")
    ui.table(
        constraint_history(store, task_code),
        key="task_constraints",
        reading="task_constraints",
        empty="No constraint added, removed or changed on this task from one update to the next.",
    )
