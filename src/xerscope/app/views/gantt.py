import pandas as pd
import streamlit as st

from xerscope.analysis.wbs import ROOT, rollup, subtree_ids
from xerscope.app import ui
from xerscope.app.state import baseline_for, compare_picker, is_dark, memo, require_store, snapshot_picker
from xerscope.viz import build_gantt, categorise, wbs_rows

store = require_store()
top = st.container()

c1, c2 = st.columns(2)
with c1:
    snap = snapshot_picker(store, "Update", key="gantt_snap")
with c2:
    cmp, cmp_label = compare_picker(store, snap, key="gantt_cmp")
bl = baseline_for(snap)
with top:
    ui.header(
        "Gantt & WBS",
        store,
        snap,
        bl,
        lead="Bars are coloured by float; the outline behind each bar is the same activity in the "
        "comparison you pick, so slippage shows as the bar leaving its outline.",
    )

nodes = memo(
    ("rollup", snap.source, st.session_state.get("bl_choice"), bl.label if bl else None), lambda: rollup(snap, bl)
)
kpis = st.container()  # filled once the WBS selection is known

left, right = st.columns([1.5, 1], gap="large")
with left:
    st.markdown("**WBS** · select a row to focus the Gantt")
    event = st.dataframe(
        nodes[["label", "pct_complete", "finish_var_wd"]],
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"wbs_table:{snap.source}",  # a new update gets a fresh selection: row positions differ
        width="stretch",
        height=min(33 * len(nodes) + 38, 420),
        column_config={
            "label": st.column_config.TextColumn("WBS", width="medium"),
            "pct_complete": st.column_config.ProgressColumn("% complete", min_value=0, max_value=100, format="%.0f %%"),
            "finish_var_wd": st.column_config.NumberColumn(
                "Δ BL (wd)", format="%+.0f", help="Finish shift against the baseline, working days"
            ),
        },
    )
    rows = event.selection.rows if event is not None and hasattr(event, "selection") else []
    node = nodes.iloc[rows[0]] if rows and rows[0] < len(nodes) else nodes.iloc[0]

with right:
    st.markdown("**Filters**")
    status = st.multiselect("Status", ["Not started", "In progress", "Complete"], placeholder="All")
    cats = st.multiselect("Float", ["Critical", "Near critical", "Normal", "Complete"], placeholder="All")
    search = st.text_input("Search", placeholder="Activity ID or name")
    o1, o2 = st.columns(2)
    group = o1.toggle("Group by WBS", value=True)
    show_links = o2.toggle("Logic links", value=False)
    hide_loe = o1.toggle("Hide LOE", value=True)
    max_rows = o2.number_input("Max rows", 20, 1000, 150, step=10)

keep = subtree_ids(nodes, node["wbs_id"])
tasks = snap.activities.copy()
if node["wbs_id"] != ROOT:
    tasks = tasks[tasks["wbs_id"].isin(keep)]
tasks["category"] = categorise(tasks)

with kpis:
    pct = node["pct_complete"]
    ui.kpis(
        [
            ("Focus", node["wbs_code"] if node["wbs_id"] != ROOT else "Whole project", None, node["wbs_name"]),
            ("% complete", "–" if pd.isna(pct) else f"{pct:.1f} %", None, f"Weighted by {node['weight']}"),
            (
                "Forecast finish",
                f"{node['finish']:%d %b %Y}" if pd.notna(node["finish"]) else "–",
                None if pd.isna(node["finish_var_wd"]) else f"{node['finish_var_wd']:+.1f} wd vs BL",
                None,
                "inverse",
            ),
            ("Labour hours", f"{node['actual_hr']:,.0f} / {node['budget_hr']:,.0f}", None, "Actual / budgeted"),
            ("Open critical", int(node["critical"])),
        ]
    )

if status:
    tasks = tasks[tasks["status"].isin(status)]
if cats:
    tasks = tasks[tasks["category"].isin(cats)]
if hide_loe:
    tasks = tasks[~tasks["is_loe"]]
if search:
    # accent-insensitive: "beton" finds "Béton"
    s = ui.fold(search)
    hit = tasks[["task_code", "task_name"]].apply(lambda col: col.map(ui.fold).str.contains(s, regex=False))
    tasks = tasks[hit.any(axis=1)]
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
    anc = nodes.set_index("wbs_id")["ancestors"]
    used = set().union(*(set(anc[w]) for w in tasks["wbs_id"].unique() if w in anc.index))
    shown = nodes[nodes["wbs_id"].isin(used & keep) & (nodes["wbs_id"] != ROOT)]
    order, summaries = wbs_rows(tasks, shown)

st.plotly_chart(
    build_gantt(
        tasks,
        data_date=snap.data_date,
        compare=cmp,
        compare_label=cmp_label or "comparison",
        relationships=snap.relationships,
        show_links=show_links,
        dark=is_dark(),
        summaries=summaries,
        snapshot=snap,
        row_order=order,
    ),
    width="stretch",
)

with st.expander("Table view"):
    cols = [
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
    ui.table(tasks, columns=cols)
    ui.csv_button(tasks[cols], f"gantt_{snap.data_date:%Y-%m-%d}.csv")
