import pandas as pd
import streamlit as st

from xerscope.app import ui
from xerscope.app.state import is_dark, require_store
from xerscope.viz import build_finish_trend

store = require_store()
latest = store.latest
prev = store.previous(latest)
summary = store.summary
last = summary.iloc[-1]
before = summary.iloc[-2] if len(summary) > 1 else None

ui.header(
    "Overview",
    store,
    latest,
    lead=f"{len(store)} weekly update(s) loaded, {store.first.data_date:%d %b %Y} → {latest.data_date:%d %b %Y}.",
)

shift = last["finish_shift_d"]
total = (latest.finish_date - store.first.finish_date).total_seconds() / 86400 if len(store) > 1 else None
ui.kpis(
    [
        (
            "Forecast finish",
            f"{latest.finish_date:%d %b %Y}" if latest.finish_date is not None else "–",
            None if pd.isna(shift) else f"{shift:+g} d vs previous update",
            "Latest early finish of the project",
            "inverse",
        ),
        (
            "Shift since first update",
            "–" if total is None else f"{total:+.0f} d",
            None,
            "Forecast finish now minus the forecast in the first loaded update (calendar days)",
        ),
        (
            "Activities complete",
            f"{int(last['complete'])} / {int(last['activities'])}",
            None if before is None else f"{int(last['complete'] - before['complete']):+d} this week",
        ),
        (
            "Critical activities",
            int(last["critical"]),
            None if before is None else f"{int(last['critical'] - before['critical']):+d} this week",
            "Open activities with total float ≤ 0",
            "inverse",
        ),
    ]
)

ui.section(
    "Forecast finish by update",
    "Each point is one weekly XER: where its schedule puts the project finish. "
    "A rising line means the end date is slipping.",
)
st.plotly_chart(build_finish_trend(summary, dark=is_dark()), width="stretch")

ui.section("Updates loaded")
ui.table(summary.drop(columns=["snapshot_idx", "project"]))

for w in store.warnings:
    st.warning(w, icon=":material/warning:")
