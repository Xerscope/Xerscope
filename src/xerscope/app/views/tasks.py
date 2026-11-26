"""Tasks: P6's Activities view.

Above, the WBS and the activities under each node in P6 order, as the Gantt's tree draws them
(viz.gantt_rows): Activity ID, name, type, original and remaining duration, % complete, start, finish,
total float. Below, for the activity picked in it, P6's Activity Details tabs (activity_details): General,
Status, Resources, Relationships (predecessors on the left, successors on the right, the driving flag
recalculated by the CPM), Constraints. Every value is read from the update picked.
"""

import pandas as pd
import streamlit as st

from xerscope.analysis.wbs import rollup
from xerscope.app import ui
from xerscope.app.activity_details import show_activity_details
from xerscope.app.cache import memo
from xerscope.app.state import page_header, require_store, snapshot_picker
from xerscope.viz import categorise, gantt_rows

PICKED_KEY = "tasks_picked"  # the Activity ID whose details are shown, kept across reruns
INDENT = " "  # one em space per WBS level, as P6 indents its rows
TABLE_COLUMNS = [
    "task_code",
    "task_name",
    "type",
    "original_d",
    "remaining_d",
    "pct_complete",
    "start",
    "finish",
    "total_float_d",
]

store = require_store()
top = st.container()
snapshot = snapshot_picker(store, "Update", key="tasks_snap")
with top:
    page_header(
        "Tasks",
        store,
        snapshot,
        lead="The WBS and its tasks as P6's Activities view lists them. Select a task for its details: "
        "General, Status, Resources, Relationships (predecessors on the left, successors on the right), Constraints.",
    )


def table_rows(snapshot) -> pd.DataFrame:
    """Return the WBS nodes and the activities under each, in P6 order (the Gantt's tree), one row each.

    TABLE_COLUMNS, the name indented by its WBS level. A WBS row carries the node's code, its roll-up of %
    complete, dates and lowest total float; an activity row the activity's own values.
    """
    tasks = snapshot.activities
    tree = gantt_rows(tasks.assign(category=categorise(tasks)), rollup(snapshot))
    by_code = snapshot.by_code[~snapshot.by_code.index.duplicated()]
    return pd.DataFrame([_table_row(row, by_code) for row in tree], columns=TABLE_COLUMNS)


def _table_row(row: dict, by_code: pd.DataFrame) -> dict:
    name = INDENT * int(row["depth"]) + row["name"]
    if row["kind"] == "task":
        task = by_code.loc[row["code"]]
        return {column: task.get(column) for column in TABLE_COLUMNS} | {"task_code": row["code"], "task_name": name}
    return {
        "task_code": row["code"] or snapshot.project_code,  # the project row: P6 shows the project's code
        "task_name": name,
        "type": "WBS",
        "pct_complete": row["pct"],
        "start": pd.to_datetime(row["start"]),
        "finish": pd.to_datetime(row["finish"]),
        "total_float_d": row["float_d"],
    }


def pick(task_code: str) -> None:
    """Show the details of a row picked in a table of the page, when it is an activity of the update."""
    if task_code in set(snapshot.activities["task_code"]):
        st.session_state[PICKED_KEY] = task_code


rows = memo(("tasks", snapshot.source), table_rows, snapshot)
ui.table(
    rows,
    key="tasks_table",
    reading="tasks_table",
    pick_task=pick,
    empty=f"{snapshot.label} holds no task.",
)


def show_details_header(task_codes: list[str], picked: str) -> None:
    """Show P6's details header: the task, by Task ID and name, and buttons to the tasks before and after it.

    ``task_codes``: the table's tasks, in table order.
    """
    position = task_codes.index(picked)
    previous_code = task_codes[max(position - 1, 0)]
    next_code = task_codes[min(position + 1, len(task_codes) - 1)]
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.button(
            "Previous task",
            icon=":material/arrow_upward:",
            key="tasks_previous",
            type="tertiary",
            disabled=position == 0,
            on_click=pick,
            args=(previous_code,),
            help="Shows the task above this one in the table.",
        )
        st.button(
            "Next task",
            icon=":material/arrow_downward:",
            key="tasks_next",
            type="tertiary",
            disabled=position == len(task_codes) - 1,
            on_click=pick,
            args=(next_code,),
            help="Shows the task below this one in the table.",
        )
        name = snapshot.by_code.loc[[picked], "task_name"].iloc[0]
        st.markdown(f"**{ui.md_text(picked)}** · {ui.md_text(name)}")


picked = st.session_state.get(PICKED_KEY)
known = set(snapshot.activities["task_code"])
task_codes = [code for code in rows["task_code"] if code in known]  # the table's tasks, WBS rows left out
if picked in task_codes:
    show_details_header(task_codes, picked)
    show_activity_details(snapshot, picked, pick_task=pick)
else:
    st.caption("Select a task in the table for its details.")
