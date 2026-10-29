import streamlit as st

from xerscope.analysis.progress import milestone_codes, milestone_slips, milestone_trend
from xerscope.app import ui
from xerscope.app.state import is_dark, require_store
from xerscope.viz.charts import SERIES, build_mta

store = require_store()
ui.header(
    "Milestone trend analysis",
    store,
    store.latest,
    lead="Each line is one milestone's forecast date in every update. Flat = stable, rising = slipping. "
    "A completed milestone (◆) meets the dotted diagonal, where forecast = reporting date.",
)

all_ms = milestone_codes(store)
names = store.history.drop_duplicates("task_code", keep="last").set_index("task_code")["task_name"]
others = sorted(set(store.history["task_code"]) - set(all_ms))
cap = len(SERIES["light"])
picked = st.multiselect(
    f"Milestones and key activities (up to {cap})",
    all_ms + others,
    default=all_ms[:cap],
    max_selections=cap,
    format_func=lambda c: f"{c} · {names.get(c, '')}",
    key="mta_pick",
)
if not picked:
    st.info("Pick at least one milestone or activity.")
    st.stop()
if len(store) < 2:
    st.info("The trend needs at least two updates.")

trend = milestone_trend(store, picked)
st.plotly_chart(build_mta(trend, all_ms + others, is_dark()), width="stretch")

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
