import pandas as pd
import streamlit as st

from xerscope.analysis.wbs import ROOT, rollup, subtree_ids
from xerscope.app import ui
from xerscope.app.state import (
    baseline_for,
    compare_picker,
    csv_download,
    memo,
    require_store,
    snapshot_picker,
    sources_of,
)
from xerscope.viz import categorise, gantt_data, gantt_rows
from xerscope.viz.gantt import CATEGORY_ORDER
from xerscope.xer.model import STATUS

NODE_KEY = "gantt_node"  # the WBS node the page opens on, kept across reruns
GANTT_HEIGHT = 680  # px; the chart scrolls inside


store = require_store()
top = st.container()

snapshot_column, compare_column = st.columns(2)
with snapshot_column:
    snapshot = snapshot_picker(store, "Update", key="gantt_snap")
with compare_column:
    compare, compare_label = compare_picker(store, snapshot, key="gantt_cmp")
baseline = baseline_for(snapshot)
with top:
    ui.header(
        "Gantt & WBS",
        store,
        snapshot,
        baseline,
        lead="Bars are coloured by float; the outline behind each bar is the same task in the "
        "comparison you pick, so slippage shows as the bar leaving its outline.",
    )

nodes = memo(
    ("rollup", snapshot.source),
    rollup,
    snapshot,
    baseline,
    ev_basis=False,  # reads bl_finish only
)
if st.session_state.get(NODE_KEY) not in set(nodes["wbs_id"]):
    st.session_state[NODE_KEY] = ROOT  # first visit, or a node the picked update does not have
labels = dict(zip(nodes["wbs_id"], nodes["label"], strict=True))


# "CIV · Civil works › ZA · Zone A": each node and the nodes above it, built once (the list
# formats every node on each rerun)
path_labels = {
    wbs_id: " › ".join(labels[a] for a in reversed(ancestors) if a != ROOT) or labels[ROOT]
    for wbs_id, ancestors in zip(nodes["wbs_id"], nodes["ancestors"], strict=True)
}

current = st.selectbox("WBS", nodes["wbs_id"].tolist(), format_func=path_labels.get, key=NODE_KEY)
node = nodes[nodes["wbs_id"] == current].iloc[0]
ui.kpis(
    [
        ("Focus", node["wbs_code"] if current != ROOT else "Whole project", None, node["wbs_name"]),
        (
            "% complete",
            "–" if pd.isna(node["pct_complete"]) else f"{node['pct_complete']:.1f} %",
            None,
            f"Weighted by {node['weight']}",
        ),
        (
            "Forecast finish",
            ui.fmt_date(node["finish"]),
            None if pd.isna(node["finish_variance_wd"]) else f"{node['finish_variance_wd']:+.1f} wd vs BL",
            None,
            "inverse",
        ),
        ("Labor hours", f"{node['actual_hr']:,.0f} / {node['budget_hr']:,.0f}", None, "Actual / budgeted"),
        ("Open critical", int(node["critical"])),
    ]
)

status_column, float_column, search_column = st.columns(3)
status = status_column.multiselect("Status", list(STATUS.values()), placeholder="All")
categories = float_column.multiselect("Float", CATEGORY_ORDER, placeholder="All")
search = search_column.text_input("Search", placeholder="Task ID or name")
code_type, code_ids, picks = None, set(), []
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
        key=f"gantt_code_values:{code_type}",  # another code type starts with nothing picked
    )
    # a suggestion picked = that value exactly (P6 "equals"); text kept = every value whose code
    # contains it, case and accents ignored (P6 "contains")
    short = dict(zip(values["code_id"], values["value"], strict=True))
    for pick in picks:
        if pick in by_label:
            code_ids.add(by_label[pick])
        else:
            code_ids |= {code_id for code_id, value in short.items() if ui.fold(pick) in ui.fold(value)}
options = st.container(horizontal=True, vertical_alignment="bottom", gap="large")
show_links = options.toggle("Logic links", value=False)
hide_loe = options.toggle("Hide LOE", value=True)
timescale = options.segmented_control(
    "Timescale", ["Month", "Week"], default="Month", help="Week shows the 12 weeks around the status date"
)

branch_ids = set(nodes["wbs_id"]) if current == ROOT else subtree_ids(nodes, current)
branch = nodes[nodes["wbs_id"].isin(branch_ids)]
tasks = snapshot.activities
if current != ROOT:
    tasks = tasks[tasks["wbs_id"].isin(branch_ids)]
tasks = tasks.assign(category=categorise(tasks))
if hide_loe:
    tasks = tasks[~tasks["is_loe"]]
unfiltered = len(tasks)
if status:
    tasks = tasks[tasks["status"].isin(status)]
if categories:
    tasks = tasks[tasks["category"].isin(categories)]
if search:
    tasks = tasks[ui.search_mask(tasks, ["task_code", "task_name"], search)]  # accent-insensitive
if code_type and picks:
    tasks = tasks[tasks["task_code"].isin(snapshot.tasks_with_codes(code_type, code_ids))]
filtering = len(tasks) < unfiltered  # every status ticked filters nothing: the outline stays closed

rows = gantt_rows(tasks, branch, compare=compare, snapshot=snapshot, keep_empty=not filtering)
root_row = nodes[nodes["wbs_id"] == ROOT].iloc[0]
ui.GANTT(
    data=gantt_data(
        rows,
        relationships=snapshot.relationships,
        data_date=snapshot.data_date,
        span=(root_row["start"], root_row["finish"]),
        timescale="week" if timescale == "Week" else "month",
        # a filter opens every branch so each match shows; otherwise the chosen node opens
        open_ids={r["id"] for r in rows if r["kind"] == "wbs"} if filtering else {f"w:{current}"},
        selected=f"w:{current}",
        compare_label=compare_label or "",
        links=show_links,
        height=GANTT_HEIGHT,
    ),
    key="gantt_chart",
)

with st.expander("Table view"):
    table_columns = [
        "task_code",
        "task_name",
        "wbs_code",
        "status",
        "category",
        "start",
        "finish",
        "total_float_d",
        "remaining_d",
        "pct_complete",
        "labor_budget_hr",
        "constraint",
    ]
    ui.table(tasks, columns=table_columns)
    csv_download(tasks[table_columns], f"gantt_{ui.stamp(snapshot.data_date)}.csv", sources=sources_of(snapshot))
