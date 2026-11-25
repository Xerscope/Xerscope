import pandas as pd
import streamlit as st

from xerscope.analysis import standard_score
from xerscope.analysis.explain import KPI_FORMULAS, critical_definition
from xerscope.analysis.progress import finish_shift_since_first
from xerscope.app import ui
from xerscope.app.cache import (
    score_errors,
    score_job,
    standard_results,
    standard_results_held,
)
from xerscope.app.loading import (
    background_jobs,
)
from xerscope.app.state import (
    page_header,
    require_store,
    standards,
)
from xerscope.config import DEFAULT_SETTINGS
from xerscope.viz import build_finish_trend
from xerscope.xer.calendar import LIMIT_MARK

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
            None if pd.isna(shift) else f"{ui.SHIFT_WD_FORMAT.format(shift)} vs previous update",
            "Latest early finish of the project, against the previous update, on the project calendar. "
            f"{ui.SHIFT_WD_SENTENCE}",
        ),
        (
            "Shift since first update",
            ui.fmt_number(total, ui.SHIFT_WD_FORMAT),
            None,
            f"Forecast finish against the first loaded update, on the project calendar. {ui.SHIFT_WD_SENTENCE}",
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
            critical_definition(latest, DEFAULT_SETTINGS.critical_float_days),
            "inverse",
        ),
    ],
    formulas=KPI_FORMULAS,
)

ui.section(
    "Score by standard",
    "Criteria in pass over criteria evaluated, on the latest update and the baseline picked in the sidebar. "
    "Shown once Schedule health or the button has computed them: the standards take several seconds "
    "on a large file.",
)
available = standards()  # the built-in ones, the XERSCOPE_STANDARDS folder and this session's uploads
loading = st.session_state.get("_load_job") is not None  # the series is still being read


def score_section(polling: bool) -> None:
    """The score cards. ``polling``: the scores are computed in a thread (``score_job``); this runs
    as a fragment every second and fills each card as its standard finishes, the rest of the page
    not drawn again (``poll_scores``)."""
    held = {key: standard_results_held(standard, latest) for key, standard in available.items()}
    missing = [key for key, results in held.items() if results is None]
    for message in score_errors(latest, available).values():
        st.error(message, icon=":material/error:")
    if missing and polling:
        job = score_job(latest, store, available)
        held = {key: standard_results_held(standard, latest) for key, standard in available.items()}
        if not job.done:
            st.caption(f"Computing the scores · {len(job.held)}/{len(available)} standards")
    elif (
        missing
        and not loading
        and st.button(
            "Compute scores",
            icon=":material/calculate:",
            key="overview_scores",
            help="Runs every built-in standard on the latest update and fills the score cards; Schedule health "
            'reuses the results. Use it when the cards read "not computed yet"; it takes several seconds on a '
            "large file.",
        )
    ):
        held = {key: standard_results(standard, latest, store) for key, standard in available.items()}
    ui.score_cards(
        {available[key].name: None if results is None else standard_score(results) for key, results in held.items()}
    )


def is_a_score_missing() -> bool:
    """Whether a listed standard has a check that is not computed yet.

    A standard the score job settled in error is not missing: nothing more will come for it.
    """
    settled = score_errors(latest, available)
    return any(
        key not in settled and standard_results_held(standard, latest) is None for key, standard in available.items()
    )


def poll_scores() -> None:
    """Draw the score cards, as the fragment does every second, or end the polling. The timer of a
    fragment only goes with a full run of the page: a poll that finds every score asks for one, and
    the page then draws the cards without a fragment. Left to its timer, it read every check again
    each second for as long as the page stayed open."""
    if not is_a_score_missing():
        st.rerun(scope="app")
    score_section(polling=True)


if background_jobs() and not loading and is_a_score_missing():
    st.fragment(poll_scores, run_every=1.0)()
else:
    score_section(polling=False)

ui.section(
    "Forecast finish by update",
    "Each point is one weekly XER: where its schedule puts the project finish. "
    "A rising line means the end date is slipping.",
)
ui.chart(build_finish_trend(summary))

ui.section("Updates loaded")
ui.table(summary.drop(columns=["snapshot_idx", "project"]), key="overview_updates", reading="overview_updates")

limits = [warning for warning in store.warnings if LIMIT_MARK in warning]
for warning in store.warnings:
    if warning not in limits:
        st.warning(warning, icon=":material/warning:")
if limits:
    ui.section("Limits", "What these files hold that xerscope reads differently from P6, and where.")
    for warning in limits:
        st.warning(warning, icon=":material/rule:")
