import pandas as pd
import streamlit as st

from xerscope.analysis.explain import KPI_FORMULAS
from xerscope.analysis.progress import committed, ppc_series, progress_delta, rollup_delta
from xerscope.app import ui
from xerscope.app.state import baseline_for, csv_download, memo, page_header, require_store, sources_of
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
PPC_COLUMNS = [
    "data_date",
    "starts_kept",
    "starts_committed",
    "ppc_start",
    "finishes_kept",
    "finishes_committed",
    "ppc_finish",
    "kept",
    "committed",
    "ppc_week",
    "note",
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


def _pct(value) -> str:
    return "n/a" if pd.isna(value) else f"{value:.0f} %"


def show_ppc_weeks(ppc: pd.DataFrame) -> None:
    with st.expander("Every week: counts behind the three PPC"):
        count = st.column_config.NumberColumn
        ui.table(
            ppc.sort_values("data_date", ascending=False),
            columns=PPC_COLUMNS,
            overrides={
                "data_date": st.column_config.DateColumn("Week ending", format="YYYY-MM-DD"),
                "kept": count("Kept (starts + finishes)", format="%d"),
                "committed": count("Committed (starts + finishes)", format="%d"),
            },
        )


def show_kpis(week: pd.Series, project_progress: pd.Series) -> None:
    ui.kpis(
        [
            (
                "PPC Start",
                _pct(week["ppc_start"]),
                None,
                "Starts kept / starts committed; n/a when nothing was due to start",
            ),
            (
                "PPC Finish",
                _pct(week["ppc_finish"]),
                None,
                "Finishes kept / finishes committed (Last Planner: complete / planned); n/a when nothing "
                "was due to finish",
            ),
            (
                "PPC W/W−1",
                _pct(week["ppc_week"]),
                None,
                "(Starts + finishes kept) / (starts + finishes committed); n/a when nothing was due",
            ),
            (
                "Starts kept",
                f"{week['starts_kept']} / {week['starts_committed']}",
                None,
                "Not started at W−1, start at W−1 on or before this status date; actual start on or before it now",
            ),
            (
                "Finishes kept",
                f"{week['finishes_kept']} / {week['finishes_committed']}",
                None,
                "Not complete at W−1, finish at W−1 on or before this status date; actual finish on or before it now",
            ),
            (
                "Project progress",
                "–" if pd.isna(project_progress["progress_pts"]) else f"{project_progress['progress_pts']:+.2f} pts",
                None,
                "Earned labor hours this week / budget hours (baseline hours and EV technique when a baseline is set)",
            ),
        ],
        formulas=KPI_FORMULAS,
    )


def show_commitments_and_wbs(commitments: pd.DataFrame, wbs_progress: pd.DataFrame, week: pd.Series) -> None:
    left, right = st.columns(2, gap="large")
    with left:
        formula = (
            f"PPC Start = {week['starts_kept']} / {week['starts_committed']} = {_pct(week['ppc_start'])}; "
            f"PPC Finish = {week['finishes_kept']} / {week['finishes_committed']} = {_pct(week['ppc_finish'])}; "
            f"PPC W/W−1 = {week['kept']} / {week['committed']} = {_pct(week['ppc_week'])}"
        )
        if isinstance(week["note"], str):
            formula += f". {week['note']}"
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
        page_header("PPC & weekly progress", store)
    st.info("PPC compares consecutive updates: load at least two.")
    st.stop()

target_column, week_column = st.columns([1, 3], vertical_alignment="bottom")
target = target_column.number_input("PPC target (%)", 0, 100, PPC_TARGET, step=5)
week_labels = store.labels[1:]
week = week_column.selectbox("Week ending", week_labels, index=len(week_labels) - 1, key="ppc_week")
week_index = store.labels.index(week)
previous, current = store[week_index - 1], store[week_index]
with top:
    page_header(
        "PPC & weekly progress",
        store,
        current,
        lead="PPC Start = of the starts update W−1 planned on or before W's status date, the share W shows "
        "actually started by then; PPC Finish the same for finishes (Last Planner: complete / planned); "
        "PPC W/W−1 = both together. Milestones and LOE left out. Weekly progress = actual in W minus actual in W−1.",
    )

ppc = memo(("ppc",), ppc_series, store, baseline=False)
ui.section("Percent plan complete by week")
st.plotly_chart(build_ppc(ppc, target), width="stretch")
show_ppc_weeks(ppc)

commitments = committed(previous, current)
baseline = baseline_for(current)
progress = progress_delta(previous, current, baseline if baseline is not None and baseline.bac_hours > 0 else None)
wbs_progress = rollup_delta(progress)
project_progress = wbs_progress[wbs_progress["wbs_l1"] == "Project"].iloc[0]
week_ppc = ppc.set_index("snapshot_idx").loc[week_index]
show_kpis(week_ppc, project_progress)
show_commitments_and_wbs(commitments, wbs_progress, week_ppc)
show_progress_by_activity(progress, previous, current)
