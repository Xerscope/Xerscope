from functools import partial

import streamlit as st

from xerscope.analysis.progress import milestone_codes, milestone_slips, milestone_trend, plotted_trend
from xerscope.app import ui
from xerscope.app.state import memo, open_in_gantt, page_header, require_store
from xerscope.viz.charts import SERIES, build_mta

store = require_store()
page_header(
    "Milestone trend",
    store,
    store.latest,
    lead="Each line is one milestone's forecast date in every update. Flat = stable, rising = slipping. "
    "A milestone complete before an update's status date is not drawn in that update.",
)

all_ms = milestone_codes(store)
names = ui.latest_names(store)
others = sorted(set(store.history["task_code"]) - set(all_ms))
cap = len(SERIES)
SAVED = "mta_saved"  # the picks, kept while other pages are visited (a widget's value is not)


def _finish_milestones(critical_only: bool) -> list[str]:
    """Finish milestones of the latest update, critical first then by forecast finish, at most
    ``cap``: the project's contractual dates are finish milestones."""
    tasks = store.latest.activities
    rows = tasks[tasks["is_milestone"] & ~tasks["is_start_milestone"]]
    if critical_only:
        rows = rows[rows["is_critical"].astype(bool)]
    rows = rows.sort_values(["is_critical", "finish"], ascending=[False, False])
    return rows["task_code"].head(cap).tolist()


def _set_picks(codes: list[str]) -> None:
    st.session_state[SAVED] = st.session_state["mta_pick"] = codes


def _keep_picks() -> None:
    st.session_state[SAVED] = st.session_state["mta_pick"]


st.session_state.setdefault(SAVED, _finish_milestones(critical_only=False))
st.session_state["mta_pick"] = [code for code in st.session_state[SAVED] if code in all_ms or code in others]
with st.container(horizontal=True, gap="small"):
    st.button("Finish milestones", key="mta_finish", on_click=_set_picks, args=(_finish_milestones(False),))
    st.button("Critical milestones", key="mta_critical", on_click=_set_picks, args=(_finish_milestones(True),))
    st.button("Clear", key="mta_clear", on_click=_set_picks, args=([],))
picked = st.multiselect(
    f"Milestones and key tasks (up to {cap})",
    all_ms + others,
    max_selections=cap,
    format_func=partial(ui.code_label, names),
    key="mta_pick",
    on_change=_keep_picks,
)
if not picked:
    st.info("Pick at least one milestone or task.")
    st.stop()
if len(store) < 2:
    st.info("The trend needs at least two updates.")
    st.stop()

trend = memo(("mta", tuple(picked)), milestone_trend, store, picked, baseline=False)
plotted = plotted_trend(trend)
if hidden := sorted(set(picked) - set(plotted.loc[plotted["forecast"].notna(), "task_code"])):
    st.caption(f"Complete before every status date, nothing to plot: {', '.join(hidden)}")
slips = milestone_slips(trend, store)
if plotted["forecast"].notna().any():
    last_shift = dict(zip(slips["task_code"], slips["last_week_wd"], strict=True))
    figure = build_mta(
        plotted,
        last_shift,
        order=picked,
        bounds=(store.latest.planned_start, store.latest.finish_date),  # the latest update's project
    )
    ui.chart(figure)  # the figure's own height: the square plot sits in it (constrain="domain")
    st.caption(
        "One colour per milestone, as on its tag above. Last point and label = move in the last update: "
        "red later, green earlier."
    )

ui.section("Slippage", "Working days on each milestone's own calendar.")
ui.table(
    slips,
    key="mta_slips",
    open_task=partial(open_in_gantt, snapshot=store.latest),
    overrides={
        "first_forecast": st.column_config.DatetimeColumn("First forecast", format="YYYY-MM-DD"),
        "latest_forecast": st.column_config.DatetimeColumn("Latest forecast", format="YYYY-MM-DD"),
        "slip_wd": st.column_config.NumberColumn("Slip since first (wd)", format="%+.1f"),
        "last_week_wd": st.column_config.NumberColumn("Last update (wd)", format="%+.1f"),
    },
)
with st.expander("Data"):
    ui.table(trend, max_height=640)
