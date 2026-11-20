"""Delay analysis page: the half-step reading of one week and its series (analysis/forensics.py)."""

import streamlit as st

from xerscope.analysis.cpm import ScheduleError
from xerscope.analysis.forensics import (
    LAST_ACTIVITY,
    MANDATORY_FINISH,
    MUST_FINISH_BY,
    finish_case,
    half_step,
    half_step_series,
    longest_path_float_d,
)
from xerscope.app import ui
from xerscope.app.state import csv_download, memo, page_header, require_store, sources_of
from xerscope.viz.charts import build_half_step, build_slip_trend

CASE_TEXT = {
    LAST_ACTIVITY: "the finish is the latest early finish of the project and moves freely",
    MUST_FINISH_BY: "a Must Finish By bounds the late dates only: the finish still moves, and the float of "
    "the longest path turns negative past the date",
    MANDATORY_FINISH: "a Mandatory Finish holds the last task's date: the delay shows in the float of "
    "the longest path, not in the finish",
}
STEP_LABELS = {
    "step": "Step",
    "finish": "Finish once applied",
    "shift_wd": "Shift (wd)",
    "changes": "Changes applied",
}
SERIES_LABELS = {
    "data_date": "Status date",
    "finish_case": "Finish held by",
    "held_by": "Date",
    "finish": "Finish shown",
    "finish_before_replanning": "Finish before replanning",
    "slip_wd": "Slip (wd)",
    "replanning_wd": "Replanning (wd)",
    "residual_wd": "Residual (wd)",
    "period_wd": "Period (wd)",
    "engine_gap_wd": "Recalculated vs file (wd)",
    "longest_path_float_d": "Longest path float (d)",
    "matched": "Matched",
    "added": "Added",
    "deleted": "Deleted",
    "note": "Note",
}


def show_case(new) -> None:
    """Say how the finish of the update is held, and what it means for the reading."""
    case, held_by = finish_case(new)
    st.caption(f"Finish held by: **{case}** ({ui.fmt_date(held_by)}). In this case {CASE_TEXT[case]}.")


def show_engine_gap(read, old, new) -> None:
    """Warn when the recalculated finish of either update is not the one P6 stored in its file."""
    if read.is_finish_reproduced:
        return
    gaps = [
        f"{ui.fmt_date(snapshot.data_date)}: recalculated {ui.fmt_date(finish)}, in the file "
        f"{ui.fmt_date(snapshot.finish_date)} ({gap_wd:+.1f} wd)"
        for snapshot, finish, gap_wd in (
            (old, read.old_finish, read.old_engine_gap_wd),
            (new, read.new_finish, read.new_engine_gap_wd),
        )
        if gap_wd != 0.0
    ]
    st.warning(
        "xerscope does not recalculate the finish P6 stored in the file (" + "; ".join(gaps) + "). The shifts "
        "below may come from the recalculation and not from the schedule: read them as indications only. "
        "The Schedule health page, Integrity standard, lists the dates that differ."
    )


def show_kpis(read, new) -> None:
    """Readout of the week: finish before replanning and its slip, finish shown and the replanning, float, matching."""
    float_d = longest_path_float_d(new)
    ui.kpis(
        [
            (
                "Finish before replanning",
                ui.fmt_date(read.finish_before_replanning),
                f"{read.slip_wd:+.1f} wd",
                "Where the previous update's plan lands with this update's status dates and actual dates, "
                "nothing else changed: the delay of the week. Working days gained (+) or lost (−) on the "
                "project calendar, a later finish reads negative.",
            ),
            (
                "Finish shown",
                ui.fmt_date(read.new_finish),
                f"{read.replanning_wd:+.1f} wd by replanning",
                "Recalculated finish of this update. The delta is what the week's replanning (scope, "
                "durations, logic, constraints, calendars and options) did to the finish before replanning.",
            ),
            (
                "Longest path float",
                ui.fmt_number(float_d, "{:.1f} d"),
                None,
                "Lowest total float on the recalculated longest path, days of the project calendar: under a "
                "Must Finish By or a Mandatory Finish, the delay the finish cannot show goes here.",
            ),
            (
                "Tasks matched",
                f"{read.matched}",
                f"{read.added} added, {read.deleted} deleted",
                "Tasks of both updates, by Task ID. Added and deleted ones enter at the scope step.",
            ),
        ]
    )


def show_steps(read, old, new) -> None:
    """Chart and table of the steps, the residual warning, the CSV."""
    ui.section(
        "Step by step",
        "The earlier update rescheduled with this update's changes applied one kind at a time, in this order; "
        "each bar is what that kind did to the finish.",
    )
    ui.chart(build_half_step(read.steps))
    steps = read.steps.rename(columns=STEP_LABELS)
    ui.table(steps, key="forensics_steps")
    if read.is_slip_beyond_period:
        st.warning(
            f"The progress step lost {abs(read.slip_wd):.1f} wd in a period of {read.period_wd:.1f} wd. "
            "AACE 29R-03 3.4.K.4.g: a revision may sit in the half-step, or the lack of progress pushed work "
            "into a non-working stretch of a calendar."
        )
    if abs(read.residual_wd) > 0.005:
        st.warning(
            f"Residual {read.residual_wd:+.1f} wd: the steps do not account for every change between the two "
            "files. A change the changelog does not list moved the finish."
        )
    csv_download(
        read.steps,
        f"half_step_{ui.stamp(old.data_date)}_{ui.stamp(new.data_date)}.csv",
        "Download steps (CSV)",
        sources=sources_of(old, new),
    )


def show_series(store) -> None:
    """Every update read against the one before it: chart, table, CSV."""
    ui.section(
        "Every update",
        "Each update read against the one before it. A finish shown that holds still while the finish before "
        "replanning keeps slipping is a delay absorbed by replanning.",
    )
    series = memo(("forensics_series",), half_step_series, store, baseline=False, ev_basis=False)
    ui.chart(build_slip_trend(series))
    shown = series.rename(columns=SERIES_LABELS)
    ui.table(shown, key="forensics_series", max_height=480)
    csv_download(series, "half_step_series.csv", "Download series (CSV)", sources=sources_of(*list(store)))


store = require_store()
top = st.container()
if len(store) < 2:
    with top:
        page_header("Delay analysis", store)
    st.info("The half-step reading compares consecutive updates: load at least two.")
    st.stop()

labels = store.labels
new_label = st.selectbox("Update", labels, index=len(labels) - 1, key="forensics_new")
new_index = labels.index(new_label)
if new_index == 0:
    st.info("Pick an update after the first: the reading needs the one before it.")
    st.stop()
old, new = store[new_index - 1], store[new_index]
with top:
    page_header(
        "Delay analysis",
        store,
        new,
        lead="What moved the project finish since the previous update, kind of change by kind of change: "
        "the previous plan is rescheduled with this update's progress first (the half-step schedule), then "
        "its revisions. AACE RP 29R-03 MIP 3.4, contemporaneous split (half-stepped update analysis); the "
        "baseline is not read.",
    )

try:
    read = memo(("forensics", labels[new_index - 1], new_label), half_step, old, new, baseline=False, ev_basis=False)
except ScheduleError as error:
    st.warning(f"These two updates cannot be read: {ui.without_addresses(str(error))}")
    st.stop()
show_case(new)
show_engine_gap(read, old, new)
show_kpis(read, new)
show_steps(read, old, new)
show_series(store)
