import pandas as pd
import streamlit as st

from xerscope.analysis.progress import committed, ppc_series, progress_delta, rollup_delta
from xerscope.app import ui
from xerscope.app.state import baseline_for, csv_download, memo, require_store, sources_of
from xerscope.viz.charts import PPC_TARGET, build_ppc

COMMITMENT_COLUMNS = [
    "task_code",
    "task_name",
    "commitment",
    "kept",
    "planned_date",
    "actual_date",
    "forecast_now",
    "status_now",
    "wbs_code",
    "in_update",
]
WBS_COLUMNS = ["wbs_code", "progress_pts", "earned_hr_week", "actual_hr_week", "budget_hr", "activities_progressed"]
ACTIVITY_COLUMNS = [
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
]


def show_kpis(week: pd.Series, project_progress: pd.Series) -> None:
    ui.kpis(
        [
            (
                "PPC this week",
                "–" if pd.isna(week["ppc"]) else f"{week['ppc']:.0f} %",
                None,
                "Commitments kept / commitments: finishes and starts, milestones left out",
            ),
            (
                "Finishes kept",
                f"{week['finishes_kept']} / {week['finishes_committed']}",
                None,
                "Forecast at W−1 to finish before this status date, complete now (Last Planner PPC)",
            ),
            (
                "Starts kept",
                f"{week['starts_kept']} / {week['starts_committed']}",
                None,
                "Not started at W−1, forecast to start before this status date, started now",
            ),
            (
                "Project progress",
                "–" if pd.isna(project_progress["progress_pts"]) else f"{project_progress['progress_pts']:+.2f} pts",
                None,
                "Earned labor hours this week / budget hours (baseline hours and EV technique when a baseline is set)",
            ),
        ]
    )


def show_commitments_and_wbs(commitments: pd.DataFrame, wbs_progress: pd.DataFrame, week: pd.Series) -> None:
    left, right = st.columns(2, gap="large")
    with left:
        formula = (
            f"Formula: ({week['finishes_kept']} finishes + {week['starts_kept']} starts kept) / "
            f"({week['finishes_committed']} + {week['starts_committed']} committed)"
        ) + ("" if pd.isna(week["ppc"]) else f" = {week['ppc']:.0f} %")
        ui.section("Commitments", formula)
        if commitments.empty:
            st.caption("Nothing was forecast to start or finish this week.")
        else:
            ui.table(commitments.sort_values(["kept", "commitment"]), columns=COMMITMENT_COLUMNS)
    with right:
        ui.section("Progress by WBS", "Points of % complete gained this week, weighted by labor hours.")
        ui.table(wbs_progress.rename(columns={"wbs_l1": "wbs_code"}), columns=WBS_COLUMNS)


def show_progress_by_activity(progress: pd.DataFrame, previous, current) -> None:
    ui.section("Progress by task", "Tasks whose % complete, earned or actual hours moved this week.")
    moved_mask = (progress["pct_delta"] != 0) | (progress["earned_hr_week"] != 0) | (progress["actual_hr_week"] != 0)
    moved = progress[moved_mask].sort_values("earned_hr_week", ascending=False)
    ui.table(moved, max_height=640, columns=ACTIVITY_COLUMNS)
    csv_download(progress, f"progress_{ui.stamp(current.data_date)}.csv", sources=sources_of(previous, current))


store = require_store()
top = st.container()
if len(store) < 2:
    with top:
        ui.header("PPC & weekly progress", store)
    st.info("PPC compares consecutive updates: load at least two.")
    st.stop()

target_column, week_column = st.columns([1, 3], vertical_alignment="bottom")
target = target_column.number_input("PPC target (%)", 0, 100, PPC_TARGET, step=5)
week_labels = store.labels[1:]
week = week_column.selectbox("Week ending", week_labels, index=len(week_labels) - 1, key="ppc_week")
week_index = store.labels.index(week)
previous, current = store[week_index - 1], store[week_index]
with top:
    ui.header(
        "PPC & weekly progress",
        store,
        current,
        lead="PPC = of the finishes and starts update W−1 forecast before W's status date, the share "
        "that update W shows done; milestones left out. Weekly progress = actual in W minus actual in W−1.",
    )

ppc = memo(("ppc",), ppc_series, store, baseline=False)
ui.section("Percent plan complete by week")
st.plotly_chart(build_ppc(ppc, target), width="stretch")

commitments = committed(previous, current)
baseline = baseline_for(current)
progress = progress_delta(previous, current, baseline if baseline is not None and baseline.bac_hours > 0 else None)
wbs_progress = rollup_delta(progress)
project_progress = wbs_progress[wbs_progress["wbs_l1"] == "Project"].iloc[0]
week_ppc = ppc.set_index("snapshot_idx").loc[week_index]
show_kpis(week_ppc, project_progress)
show_commitments_and_wbs(commitments, wbs_progress, week_ppc)
show_progress_by_activity(progress, previous, current)
