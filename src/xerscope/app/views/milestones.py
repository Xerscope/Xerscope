from functools import partial

import pandas as pd
import streamlit as st

from xerscope.analysis.progress import milestone_codes, milestone_slips, milestone_trend, plotted_trend
from xerscope.app import ui
from xerscope.app.state import is_dark, memo, require_store
from xerscope.viz.charts import SERIES, build_mta


def milestone_label(names: pd.Series, task_code: str) -> str:
    """Multiselect label for an Activity ID: the code and its latest name."""
    return f"{task_code} · {names.get(task_code, '')}"


store = require_store()
ui.header(
    "Milestone trend analysis",
    store,
    store.latest,
    lead="Each line is one milestone's forecast date in every update. Flat = stable, rising = slipping. "
    "A completed milestone (◆) meets the dotted diagonal, where forecast = reporting date, and its line "
    "ends there.",
)

all_ms = milestone_codes(store)
open_ms = milestone_codes(store, open_only=True)
names = store.history.drop_duplicates("task_code", keep="last").set_index("task_code")["task_name"]
others = sorted(set(store.history["task_code"]) - set(all_ms))
cap = len(SERIES["light"])
picked = st.multiselect(
    f"Milestones and key activities (up to {cap})",
    all_ms + others,
    default=open_ms[:cap],
    max_selections=cap,
    format_func=partial(milestone_label, names),
    key="mta_pick",
)
if not picked:
    st.info("Pick at least one milestone or activity.")
    st.stop()
if len(store) < 2:
    st.info("The trend needs at least two updates.")

trend = memo(("mta", tuple(picked)), milestone_trend, store, picked)
plotted = plotted_trend(trend)
if hidden := sorted(set(picked) - set(plotted["task_code"])):
    st.caption(f"Complete in the first update, no trend to plot: {', '.join(hidden)}")
if not plotted.empty:
    st.plotly_chart(build_mta(plotted, all_ms + others, is_dark()), width="stretch")

ui.section("Slippage", "Working days on each milestone's own calendar.")
slips = milestone_slips(trend, store)
ui.table(
    slips,
    overrides={
        "first_forecast": st.column_config.DatetimeColumn("First forecast", format="YYYY-MM-DD"),
        "latest_forecast": st.column_config.DatetimeColumn("Latest forecast", format="YYYY-MM-DD"),
        "slip_wd": st.column_config.NumberColumn("Slip since first (wd)", format="%+.1f"),
        "last_week_wd": st.column_config.NumberColumn("Last update (wd)", format="%+.1f"),
    },
)
with st.expander("Data"):
    ui.table(trend, max_height=640)
