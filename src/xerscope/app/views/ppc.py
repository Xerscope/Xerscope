import pandas as pd
import streamlit as st

from xerscope.analysis.progress import committed, ppc_series, progress_delta, rollup_delta
from xerscope.app import ui
from xerscope.app.state import baseline_for, csv_download, is_dark, memo, require_store
from xerscope.viz.charts import PPC_TARGET, build_ppc

COMMITMENT_COLUMNS = [
    "task_code",
    "task_name",
    "completed",
    "planned_finish",
    "actual_finish",
    "forecast_finish_now",
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


def show_kpis(commitments: pd.DataFrame, project_progress: pd.Series) -> tuple[int, int]:
    """KPI row; returns (finished as committed, committed) for the formula caption."""
    has_commitments = not commitments.empty
    done = int(commitments.loc[commitments["in_update"], "completed"].sum()) if has_commitments else 0
    due = int(commitments["in_update"].sum()) if has_commitments else 0
    ui.kpis(
        [
            (
                "PPC this week",
                f"{100 * done / due:.0f} %" if due else "–",
                None,
                "Committed activities finished / committed",
            ),
            ("Committed", due, None, "Forecast at W−1 to finish before this data date"),
            ("Finished as committed", done),
            (
                "Project progress",
                "–" if pd.isna(project_progress["progress_pts"]) else f"{project_progress['progress_pts']:+.2f} pts",
                None,
                "Earned labour hours this week / budget hours (baseline hours and EV technique when a baseline is set)",
            ),
        ]
    )
    return done, due


def show_commitments_and_wbs(commitments: pd.DataFrame, wbs_progress: pd.DataFrame, done: int, due: int) -> None:
    left, right = st.columns(2, gap="large")
    with left:
        formula = f"Formula: {done} finished / {due} committed" + (f" = {100 * done / due:.0f} %" if due else "")
        ui.section("Commitments", formula)
        if commitments.empty:
            st.caption("Nothing was forecast to finish this week.")
        else:
            ui.table(commitments.sort_values("completed"), columns=COMMITMENT_COLUMNS)
    with right:
        ui.section("Progress by WBS", "Points of % complete gained this week, weighted by labour hours.")
        ui.table(wbs_progress.rename(columns={"wbs_l1": "wbs_code"}), columns=WBS_COLUMNS)


def show_progress_by_activity(progress: pd.DataFrame, current) -> None:
    ui.section("Progress by activity", "Activities whose % complete, earned or actual hours moved this week.")
    moved_mask = (progress["pct_delta"] != 0) | (progress["earned_hr_week"] != 0) | (progress["actual_hr_week"] != 0)
    moved = progress[moved_mask].sort_values("earned_hr_week", ascending=False)
    ui.table(moved, max_height=640, columns=ACTIVITY_COLUMNS)
    csv_download(progress, f"progress_{ui.stamp(current.data_date)}.csv")


store = require_store()
top = st.container()
if len(store) < 2:
    with top:
        ui.header("PPC & weekly progress", store)
    st.info("PPC compares consecutive updates: load at least two.")
    st.stop()

target_column, milestones_column, week_column = st.columns([1, 1, 2], vertical_alignment="bottom")
target = target_column.number_input("PPC target (%)", 0, 100, PPC_TARGET, step=5)
with_ms = milestones_column.toggle("Include milestones", value=True)
week_labels = store.labels[1:]
week = week_column.selectbox("Week ending", week_labels, index=len(week_labels) - 1, key="ppc_week")
week_index = store.labels.index(week)
previous, current = store[week_index - 1], store[week_index]
with top:
    ui.header(
        "PPC & weekly progress",
        store,
        current,
        lead="PPC (Last Planner) = of the activities update W−1 forecast to finish before W's data date, "
        "the share that update W shows complete. Weekly progress = actual in W minus actual in W−1.",
    )

ppc = memo(("ppc", with_ms), ppc_series, store, with_ms)
ui.section("Percent plan complete by week")
st.plotly_chart(build_ppc(ppc, target, is_dark()), width="stretch")

commitments = committed(previous, current, with_ms)
baseline = baseline_for(current)
progress = progress_delta(previous, current, baseline if baseline is not None and baseline.bac_hours > 0 else None)
wbs_progress = rollup_delta(progress)
project_progress = wbs_progress[wbs_progress["wbs_l1"] == "Project"].iloc[0]
done, due = show_kpis(commitments, project_progress)
show_commitments_and_wbs(commitments, wbs_progress, done, due)
show_progress_by_activity(progress, current)
