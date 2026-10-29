import pandas as pd
import streamlit as st

from xerscope.analysis.progress import committed, ppc_series, progress_delta, rollup_delta
from xerscope.app import ui
from xerscope.app.state import baseline_for, is_dark, require_store
from xerscope.viz.charts import build_ppc

store = require_store()
top = st.container()
if len(store) < 2:
    with top:
        ui.header("PPC & weekly progress", store)
    st.info("PPC compares consecutive updates: load at least two.")
    st.stop()

c1, c2, c3 = st.columns([1, 1, 2], vertical_alignment="bottom")
target = c1.number_input("PPC target (%)", 0, 100, 80, step=5)
with_ms = c2.toggle("Include milestones", value=True)
labels = store.labels[1:]
week = c3.selectbox("Week ending", labels, index=len(labels) - 1, key="ppc_week")
i = store.labels.index(week)
prev, cur = store[i - 1], store[i]
with top:
    ui.header(
        "PPC & weekly progress",
        store,
        cur,
        lead="PPC (Last Planner) = of the activities update W−1 forecast to finish before W's data date, "
        "the share that update W shows complete. Weekly progress = actual in W minus actual in W−1.",
    )

ppc = ppc_series(store, with_ms)
ui.section("Percent plan complete by week")
st.plotly_chart(build_ppc(ppc, target, is_dark()), width="stretch")

c = committed(prev, cur, with_ms)
bl = baseline_for(cur)
d = progress_delta(prev, cur, bl if bl is not None and bl.bac_hours > 0 else None)
r = rollup_delta(d)
total = r[r["wbs_l1"] == "Project"].iloc[0]
done = int(c.loc[c["in_update"], "completed"].sum()) if not c.empty else 0
n = int(c["in_update"].sum()) if not c.empty else 0
ui.kpis(
    [
        ("PPC this week", f"{100 * done / n:.0f} %" if n else "–", None, "Committed activities finished / committed"),
        ("Committed", n, None, "Forecast at W−1 to finish before this data date"),
        ("Finished as committed", done),
        (
            "Project progress",
            "–" if pd.isna(total["progress_pts"]) else f"{total['progress_pts']:+.2f} pts",
            None,
            "Earned labour hours this week / budget hours (baseline hours and EV technique when a baseline is set)",
        ),
    ]
)

left, right = st.columns(2, gap="large")
with left:
    ui.section("Commitments", f"Formula: {done} finished / {n} committed" + (f" = {100 * done / n:.0f} %" if n else ""))
    if c.empty:
        st.caption("Nothing was forecast to finish this week.")
    else:
        ui.table(
            c.sort_values("completed"),
            columns=[
                "task_code",
                "task_name",
                "completed",
                "planned_finish",
                "actual_finish",
                "forecast_finish_now",
                "status_now",
                "wbs_code",
                "in_update",
            ],
        )
with right:
    ui.section("Progress by WBS", "Points of % complete gained this week, weighted by labour hours.")
    ui.table(
        r.rename(columns={"wbs_l1": "wbs_code"}),
        columns=["wbs_code", "progress_pts", "earned_hr_week", "actual_hr_week", "budget_hr", "activities_progressed"],
    )

ui.section("Progress by activity", "Activities whose % complete, earned or actual hours moved this week.")
moved = d[(d["pct_delta"] != 0) | (d["earned_hr_week"] != 0) | (d["actual_hr_week"] != 0)].sort_values(
    "earned_hr_week", ascending=False
)
ui.table(
    moved,
    max_height=640,
    columns=[
        "task_code",
        "task_name",
        "pct_prev",
        "pct_now",
        "pct_delta",
        "earned_hr_week",
        "actual_hr_week",
        "labor_budget_hr",
        "labor_actual_hr",
        "status",
        "wbs_l1",
        "new",
        "deleted",
    ],
)
ui.csv_button(d, f"progress_{cur.data_date:%Y-%m-%d}.csv")
