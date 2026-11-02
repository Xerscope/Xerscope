import pandas as pd
import streamlit as st

from xerscope.analysis.wbs import ROOT, children, path, rollup, subtree_ids, visible_tree
from xerscope.app import ui
from xerscope.app.state import baseline_for, compare_picker, is_dark, memo, require_store, snapshot_picker
from xerscope.viz import build_gantt, categorise, level_rows
from xerscope.viz.gantt import CATEGORY_ORDER
from xerscope.xer.model import STATUS

WBS_TABLE_MAX_HEIGHT = 420
MAX_ROWS_DEFAULT = 150  # Gantt rows drawn before the figure gets too tall to read
NODE_KEY = "gantt_node"  # the WBS node the page shows, kept across reruns
INDENT = "\u2003"  # em space: the outline indentation survives in the table cell

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
        lead="Bars are coloured by float; the outline behind each bar is the same activity in the "
        "comparison you pick, so slippage shows as the bar leaving its outline.",
    )

nodes = memo(
    ("rollup", snapshot.source, st.session_state.get("bl_choice"), baseline.label if baseline else None),
    rollup,
    snapshot,
    baseline,
)
if st.session_state.get(NODE_KEY) not in set(nodes["wbs_id"]):
    st.session_state[NODE_KEY] = ROOT  # first visit, or a node the picked update does not have
current = st.session_state[NODE_KEY]
labels = nodes.set_index("wbs_id")["label"]


def open_node(wbs_id: str) -> None:
    st.session_state[NODE_KEY] = wbs_id


def open_picked(key: str) -> None:
    if st.session_state.get(key):
        open_node(st.session_state[key])
        st.session_state[key] = None  # back on this level later, the same pill opens it again


kpis = st.container()  # filled once the WBS selection is known

wbs_column, filter_column = st.columns([1.5, 1], gap="large")
with wbs_column:
    st.markdown("**WBS** · select a node to open it")
    expand_all = st.toggle("Expand all", key="gantt_expand_all")
    outline = visible_tree(nodes, set(nodes["wbs_id"]) if expand_all else set(path(nodes, current)))
    marker = [
        "▾ " if is_open else "▸ " if has_children else "\u2003 "
        for is_open, has_children in zip(outline["open"], outline["has_children"], strict=True)
    ]
    outline["node"] = [
        INDENT * depth + mark + ("● " if wbs_id == current else "") + label
        for depth, mark, wbs_id, label in zip(
            outline["depth"], marker, outline["wbs_id"], outline["label"], strict=True
        )
    ]
    event = st.dataframe(
        outline[["node", "pct_complete", "finish_variance_wd"]],
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        # rows move when the outline opens or closes: a fresh table each time, no stale selection
        key=f"wbs_tree:{snapshot.source}:{current}:{expand_all}",
        width="stretch",
        height=ui.table_height(len(outline), WBS_TABLE_MAX_HEIGHT),
        column_config={
            "node": st.column_config.TextColumn("WBS", width="large"),
            "pct_complete": st.column_config.ProgressColumn(
                "% complete", min_value=0, max_value=100, format="%.0f %%", width="small"
            ),
            "finish_variance_wd": st.column_config.NumberColumn(
                "Δ BL (wd)", format="%+.0f", help="Finish shift against the baseline, working days", width="small"
            ),
        },
    )
    rows = event.selection.rows
    if rows and rows[0] < len(outline) and outline["wbs_id"].iloc[rows[0]] != current:
        open_node(outline["wbs_id"].iloc[rows[0]])
        st.rerun()
node = nodes[nodes["wbs_id"] == current].iloc[0]

with filter_column:
    st.markdown("**Filters**")
    status = st.multiselect("Status", list(STATUS.values()), placeholder="All")
    categories = st.multiselect("Float", CATEGORY_ORDER, placeholder="All")
    search = st.text_input("Search", placeholder="Activity ID or name")
    left_options, right_options = st.columns(2)
    show_links = left_options.toggle("Logic links", value=False)
    hide_loe = right_options.toggle("Hide LOE", value=True)
    max_rows = right_options.number_input("Max rows", 20, 1000, MAX_ROWS_DEFAULT, step=10)
    timescale = st.segmented_control(
        "Timescale", ["Month", "Week"], default="Month", help="Week shows the 12 weeks around the data date"
    )

# breadcrumb up, one button per sub-WBS down
crumbs = st.container(horizontal=True, gap="small", vertical_alignment="center")
for i, wbs_id in enumerate(path(nodes, current)):
    if i:
        crumbs.markdown("›")
    crumbs.button(labels[wbs_id], key=f"crumb:{wbs_id}", disabled=wbs_id == current, on_click=open_node, args=(wbs_id,))
sub_nodes = children(nodes, current)
if sub_nodes:
    pick_key = f"open_child:{current}"
    st.pills("Open a sub-WBS", sub_nodes, format_func=labels.get, key=pick_key, on_change=open_picked, args=(pick_key,))

tasks = snapshot.activities.copy()
if search:
    # a search looks through the whole branch, listed flat
    if current != ROOT:
        tasks = tasks[tasks["wbs_id"].isin(subtree_ids(nodes, current))]
    tasks = tasks[ui.search_mask(tasks, ["task_code", "task_name"], search)]  # accent-insensitive
    sub_nodes = []
elif current == ROOT:
    tasks = tasks[~tasks["wbs_id"].isin(set(nodes["wbs_id"]))]  # assigned to the project node itself
else:
    tasks = tasks[tasks["wbs_id"] == current]
tasks["category"] = categorise(tasks)

with kpis:
    percent_complete = node["pct_complete"]
    ui.kpis(
        [
            ("Focus", node["wbs_code"] if node["wbs_id"] != ROOT else "Whole project", None, node["wbs_name"]),
            (
                "% complete",
                "–" if pd.isna(percent_complete) else f"{percent_complete:.1f} %",
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
            ("Labour hours", f"{node['actual_hr']:,.0f} / {node['budget_hr']:,.0f}", None, "Actual / budgeted"),
            ("Open critical", int(node["critical"])),
        ]
    )

if status:
    tasks = tasks[tasks["status"].isin(status)]
if categories:
    tasks = tasks[tasks["category"].isin(categories)]
if hide_loe:
    tasks = tasks[~tasks["is_loe"]]
tasks = tasks.sort_values(["wbs_sort", "start"], na_position="last")
if len(tasks) > max_rows:
    st.caption(f"Showing the first {max_rows} of {len(tasks)} activities: filter or open a sub-WBS.")
    tasks = tasks.head(int(max_rows))
if tasks.empty and not sub_nodes:
    st.info("No activity matches the filters.")
    st.stop()

order, summaries = level_rows(tasks, nodes[nodes["wbs_id"].isin(sub_nodes)])

st.plotly_chart(
    build_gantt(
        tasks,
        data_date=snapshot.data_date,
        compare=compare,
        compare_label=compare_label or "comparison",
        relationships=snapshot.relationships,
        show_links=show_links,
        dark=is_dark(),
        summaries=summaries,
        snapshot=snapshot,
        row_order=order,
        timescale="week" if timescale == "Week" else "month",
        span=tuple(nodes.loc[nodes["wbs_id"] == ROOT, ["start", "finish"]].iloc[0]),
    ),
    width="stretch",
    config={"displayModeBar": False, "scrollZoom": False},
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
    ui.csv_button(tasks[table_columns], f"gantt_{ui.stamp(snapshot.data_date)}.csv")
