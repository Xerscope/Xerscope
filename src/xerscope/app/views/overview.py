import pandas as pd
import streamlit as st

from xerscope.analysis import builtin_standards, standard_score
from xerscope.analysis.explain import KPI_FORMULAS
from xerscope.analysis.progress import finish_shift_since_first
from xerscope.app import ui
from xerscope.app.state import (
    background_jobs,
    page_header,
    poll_scores,
    require_store,
    score_job,
    standard_results,
    standard_results_held,
    standards,
)
from xerscope.viz import build_finish_trend

store = require_store()
latest = store.latest
summary = store.summary
last = summary.iloc[-1]
before = summary.iloc[-2] if len(summary) > 1 else None

page_header(
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
            None if pd.isna(shift) else f"{round(shift, 1):+g} wd vs previous update",
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
            "Tasks complete",
            f"{int(last['complete'])} / {int(last['activities'])}",
            None if before is None else f"{int(last['complete'] - before['complete']):+d} this week",
        ),
        (
            "Critical tasks",
            int(last["critical"]),
            None if before is None else f"{int(last['critical'] - before['critical']):+d} this week",
            "Open tasks with total float ≤ 0",
            "inverse",
        ),
    ],
    formulas=KPI_FORMULAS,
)

ui.section(
    "Score by standard",
    "Checks in pass over checks evaluated, on the latest update and the baseline picked in the sidebar. "
    "Shown once Schedule health or the button has computed them: the four standards take several seconds "
    "on a large file.",
)
built_in = {key: standard for key, standard in standards().items() if key in builtin_standards()}
held = {key: standard_results_held(standard, latest) for key, standard in built_in.items()}
missing = [key for key, results in held.items() if results is None]
loading = st.session_state.get("_load_job") is not None  # the series is still being read
if missing and background_jobs() and not loading:
    # computed in a thread once the series is read; the cards fill as each standard finishes
    job = score_job(latest, store, built_in)
    held = {key: standard_results_held(standard, latest) for key, standard in built_in.items()}
    failed = [str(job.results[key]) for key in missing if isinstance(job.results.get(key), str)]
    for message in failed:
        st.error(message, icon=":material/error:")
    if not job.done:
        st.caption(f"Computing the scores · {len(job.held)}/{len(built_in)} standards")
        poll_scores()
elif missing and not loading and st.button("Compute scores", icon=":material/calculate:", key="overview_scores"):
    held = {key: standard_results(standard, latest, store) for key, standard in built_in.items()}
ui.score_cards(
    {built_in[key].name: None if results is None else standard_score(results) for key, results in held.items()}
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
