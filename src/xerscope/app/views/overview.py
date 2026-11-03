import pandas as pd
import streamlit as st

from xerscope.analysis.progress import finish_shift_since_first
from xerscope.app import ui
from xerscope.app.state import require_store
from xerscope.viz import build_finish_trend

store = require_store()
latest = store.latest
summary = store.summary
last = summary.iloc[-1]
before = summary.iloc[-2] if len(summary) > 1 else None

ui.header(
    "Overview",
    store,
    latest,
    lead=f"{len(store)} weekly update(s) loaded, "
    f"{ui.fmt_date(store.first.data_date)} → {ui.fmt_date(latest.data_date)}.",
)

shift = last["finish_shift_wd"]
total = finish_shift_since_first(store)
ui.kpis(
    [
        (
            "Forecast finish",
            ui.fmt_date(latest.finish_date),
            None if pd.isna(shift) else f"{shift:+g} wd vs previous update",
            "Latest early finish of the project",
            "inverse",
        ),
        (
            "Shift since first update",
            "–" if total is None else f"{total:+.1f} wd",
            None,
            "Forecast finish now minus the forecast in the first loaded update (working days, project calendar)",
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
st.plotly_chart(build_finish_trend(summary), width="stretch")

ui.section("Updates loaded")
ui.table(summary.drop(columns=["snapshot_idx", "project"]))

for w in store.warnings:
    st.warning(w, icon=":material/warning:")
