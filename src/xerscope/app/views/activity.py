"""One activity across every weekly update: how its dates, float and progress moved."""

from functools import partial

import pandas as pd
import streamlit as st

from xerscope.analysis.progress import activity_finish_shift
from xerscope.app import ui
from xerscope.app.state import require_store
from xerscope.viz.charts import build_activity_dates, build_activity_float

LIST_COLUMNS = [
    "data_date",
    "status",
    "start",
    "finish",
    "total_float_d",
    "remaining_d",
    "original_d",
    "pct_complete",
    "is_critical",
]


def show_kpis(store, history: pd.DataFrame) -> None:
    last = history.iloc[-1]
    slip = activity_finish_shift(store, history)
    ui.kpis(
        [
            ("Status", last["status"]),
            (
                "Forecast finish",
                ui.fmt_date(last["finish"], "—"),
                None if slip is None else f"{slip:+.1f} wd since first",
                None,
                "inverse",
            ),
            ("Total float", "–" if pd.isna(last["total_float_d"]) else f"{last['total_float_d']:.1f} wd"),
            ("% complete", "–" if pd.isna(last["pct_complete"]) else f"{last['pct_complete']:.0f} %"),
        ]
    )


def show_charts(history: pd.DataFrame) -> None:
    dates_column, float_column = st.columns(2, gap="large")
    with dates_column:
        ui.section("Forecast start and finish")
        st.plotly_chart(build_activity_dates(history), width="stretch")
    with float_column:
        ui.section("Total float (working days)")
        st.plotly_chart(build_activity_float(history), width="stretch")


store = require_store()
ui.header(
    "Task history",
    store,
    store.latest,
    lead="Follow one task through every loaded update: forecast dates, float and progress.",
)

all_history = store.history
names = ui.latest_names(store)
choice = st.selectbox("Task", names.index, format_func=partial(ui.code_label, names))
history = all_history[all_history["task_code"] == choice].sort_values("data_date")
if len(store) - len(history):
    st.caption(f"Present in {len(history)} of {len(store)} updates (added or deleted along the way).")

show_kpis(store, history)
show_charts(history)

ui.section("By update")
ui.table(history, columns=LIST_COLUMNS)
