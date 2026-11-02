import pandas as pd
import streamlit as st

from xerscope.analysis.wbs import ROOT, rollup, subtree_ids
from xerscope.app import ui
from xerscope.app.state import baseline_for, compare_picker, is_dark, memo, require_store, snapshot_picker
from xerscope.viz import build_gantt, categorise, wbs_rows
from xerscope.viz.gantt import CATEGORY_ORDER
from xerscope.xer.model import STATUS

WBS_TABLE_MAX_HEIGHT = 420
MAX_ROWS_DEFAULT = 150  # Gantt rows drawn before the figure gets too tall to read

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
kpis = st.container()  # filled once the WBS selection is known

wbs_column, filter_column = st.columns([1.5, 1], gap="large")
with wbs_column:
    st.markdown("**WBS** · select a row to focus the Gantt")
    event = st.dataframe(
        nodes[["label", "pct_complete", "finish_variance_wd"]],
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"wbs_table:{snapshot.source}",  # a new update gets a fresh selection: row positions differ
        width="stretch",
        height=ui.table_height(len(nodes), WBS_TABLE_MAX_HEIGHT),
        column_config={
            "label": st.column_config.TextColumn("WBS", width="medium"),
            "pct_complete": st.column_config.ProgressColumn("% complete", min_value=0, max_value=100, format="%.0f %%"),
            "finish_variance_wd": st.column_config.NumberColumn(
                "Δ BL (wd)", format="%+.0f", help="Finish shift against the baseline, working days"
            ),
        },
    )
    rows = event.selection.rows
    node = nodes.iloc[rows[0]] if rows and rows[0] < len(nodes) else nodes.iloc[0]

with filter_column:
    st.markdown("**Filters**")
    status = st.multiselect("Status", list(STATUS.values()), placeholder="All")
    categories = st.multiselect("Float", CATEGORY_ORDER, placeholder="All")
    search = st.text_input("Search", placeholder="Activity ID or name")
    left_options, right_options = st.columns(2)
    group = left_options.toggle("Group by WBS", value=True)
    show_links = right_options.toggle("Logic links", value=False)
    hide_loe = left_options.toggle("Hide LOE", value=True)
    max_rows = right_options.number_input("Max rows", 20, 1000, MAX_ROWS_DEFAULT, step=10)

focus_ids = subtree_ids(nodes, node["wbs_id"])
tasks = snapshot.activities.copy()
if node["wbs_id"] != ROOT:
    tasks = tasks[tasks["wbs_id"].isin(focus_ids)]
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
if search:
    # accent-insensitive: "beton" finds "Béton"
    tasks = tasks[ui.search_mask(tasks, ["task_code", "task_name"], search)]
tasks = tasks.sort_values(["wbs_sort", "start"], na_position="last")
if len(tasks) > max_rows:
    st.caption(f"Showing the first {max_rows} of {len(tasks)} activities: filter or pick a WBS node.")
    tasks = tasks.head(int(max_rows))
if tasks.empty:
    st.info("No activity matches the filters.")
    st.stop()

summaries = order = None
if group and len(nodes) > 1:
    # summary rows for the focused subtree's nodes that still hold a filtered activity
    ancestors = nodes.set_index("wbs_id")["ancestors"]
    used = set().union(*(set(ancestors[wbs_id]) for wbs_id in tasks["wbs_id"].unique() if wbs_id in ancestors.index))
    shown = nodes[nodes["wbs_id"].isin(used & focus_ids) & (nodes["wbs_id"] != ROOT)]
    order, summaries = wbs_rows(tasks, shown)

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
    ),
    width="stretch",
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
