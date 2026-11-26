"""Tasks: P6's Activities view.

Above, the WBS tree and the activities under each node in P6 order, drawn by the Gantt's component
without its timeline (viz.gantt_data): a WBS row folds open and closed, its band shaded by its level;
the columns are original and remaining duration, % complete, start, finish, total float. A click on an
activity selects it. Below, for the activity selected, P6's Activity Details tabs (activity_details):
General, Status, Resources, Relationships (predecessors on the left, successors on the right, the driving
flag recalculated by the CPM), Constraints. Every value is read from the update picked.
"""

import pandas as pd
import streamlit as st

from xerscope.analysis.wbs import ROOT, rollup
from xerscope.app import ui
from xerscope.app.activity_details import show_activity_details
from xerscope.app.cache import memo
from xerscope.app.state import page_header, require_store, snapshot_picker
from xerscope.app.task_panel import task_from_row_id
from xerscope.viz import categorise, gantt_rows
from xerscope.viz.gantt import ACTIVITIES_COLUMNS, gantt_data, open_row_ids

PICKED_KEY = "tasks_picked"  # the Activity ID whose details are shown, kept across reruns
TREE_KEY = "tasks_tree"  # the component's state: the row id of the last click
TREE_HEIGHT = 560  # px at most; the tree scrolls inside

store = require_store()
top = st.container()
snapshot = snapshot_picker(store, "Update", key="tasks_snap")
with top:
    page_header(
        "Tasks",
        store,
        snapshot,
        lead="The WBS and its tasks as P6's Activities view lists them. Click a task for its details: "
        "General, Status, Resources, Relationships (predecessors on the left, successors on the right), Constraints.",
    )


def pick(task_code: str) -> None:
    """Show the details of a task picked on the page (tree, relationships, buttons), when it is one of the update."""
    if task_code in set(snapshot.activities["task_code"]):
        st.session_state[PICKED_KEY] = task_code


def _clicked() -> None:
    """Select the activity clicked in the tree: the browser sends its row id ("a:<Activity ID>"), nothing else."""
    pick(task_from_row_id(st.session_state[TREE_KEY].get("picked")) or "")


def tree_rows(snapshot) -> tuple[list[dict], pd.DataFrame]:
    """Return the Gantt's rows for the whole WBS and the WBS roll-up they are drawn from.

    Each node is followed by its activities, in P6 order.
    """
    tasks = snapshot.activities
    nodes = rollup(snapshot)
    return gantt_rows(tasks.assign(category=categorise(tasks)), nodes), nodes


def show_tree(rows: list[dict], nodes: pd.DataFrame, picked: str | None) -> None:
    """Show the WBS tree, the top level open and, with an activity selected, the branch that holds it."""
    tasks = snapshot.activities
    picked_wbs_id = tasks.loc[tasks["task_code"] == picked, "wbs_id"].iloc[0] if picked else None
    ui.GANTT(
        data=gantt_data(
            rows,
            open_ids=open_row_ids(rows, nodes, set(nodes["wbs_id"]), ROOT, picked_wbs_id),
            selected=f"a:{picked}" if picked else None,
            height=TREE_HEIGHT,
            columns=ACTIVITIES_COLUMNS,
            timeline=False,
            level_bands=True,
        ),
        key=TREE_KEY,
        on_picked_change=_clicked,
        on_focus_change=lambda: None,  # a double click on a WBS row: the Gantt page's focus, not used here
    )


def show_details_header(task_codes: list[str], picked: str) -> None:
    """Show P6's details header: the task, by Task ID and name, and buttons to the tasks before and after it.

    ``task_codes``: the tree's tasks, in its order.
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
            help="Shows the task above this one in the tree.",
        )
        st.button(
            "Next task",
            icon=":material/arrow_downward:",
            key="tasks_next",
            type="tertiary",
            disabled=position == len(task_codes) - 1,
            on_click=pick,
            args=(next_code,),
            help="Shows the task below this one in the tree.",
        )
        name = snapshot.by_code.loc[[picked], "task_name"].iloc[0]
        st.markdown(f"**{ui.md_text(picked)}** · {ui.md_text(name)}")


rows, nodes = memo(("tasks", snapshot.source), tree_rows, snapshot)
ui.reading_popover("tasks_table")
picked = st.session_state.get(PICKED_KEY)
task_codes = [row["code"] for row in rows if row["kind"] == "task"]  # the tree's activities, in its order
if picked not in task_codes:
    picked = None
show_tree(rows, nodes, picked)
if picked:
    show_details_header(task_codes, picked)
    show_activity_details(snapshot, picked, pick_task=pick)
elif task_codes:
    st.caption("Select a task in the tree for its details.")
else:
    st.caption(f"{ui.md_text(snapshot.label)} holds no task.")
