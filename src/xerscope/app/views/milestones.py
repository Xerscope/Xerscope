from functools import partial

import streamlit as st

from xerscope.analysis.progress import milestone_codes, milestone_slips, milestone_trend, plotted_trend
from xerscope.app import ui
from xerscope.app.state import is_dark, memo, require_store
from xerscope.viz.charts import SERIES, build_mta

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
names = ui.latest_names(store)
others = sorted(set(store.history["task_code"]) - set(all_ms))
cap = len(SERIES["light"])
picked = st.multiselect(
    f"Milestones and key activities (up to {cap})",
    all_ms + others,
    default=open_ms[:cap],
    max_selections=cap,
    format_func=partial(ui.code_label, names),
    key="mta_pick",
)
if not picked:
    st.info("Pick at least one milestone or activity.")
    st.stop()
if len(store) < 2:
    st.info("The trend needs at least two updates.")
    st.stop()

trend = memo(("mta", tuple(picked)), milestone_trend, store, picked)
plotted = plotted_trend(trend)
if hidden := sorted(set(picked) - set(plotted["task_code"])):
    st.caption(f"Complete in the first update, no trend to plot: {', '.join(hidden)}")
slips = milestone_slips(trend, store)
if not plotted.empty:
    last_shift = dict(zip(slips["task_code"], slips["last_week_wd"], strict=True))
    st.plotly_chart(build_mta(plotted, last_shift, is_dark()), width="stretch")
    st.caption("Line colour = move in the last update: red later, green earlier, grey unchanged or complete.")

ui.section("Slippage", "Working days on each milestone's own calendar.")
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
