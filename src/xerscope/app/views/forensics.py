"""Delay analysis page: the half-step reading of one week and its series (analysis/forensics.py)."""

from functools import partial

import streamlit as st

from xerscope.analysis.cpm import ScheduleError
from xerscope.analysis.explain import KPI_FORMULAS
from xerscope.analysis.forensics import (
    LAST_ACTIVITY,
    MANDATORY_FINISH,
    MUST_FINISH_BY,
    finish_case,
    half_step,
    half_step_series,
    longest_path_float_d,
    revisions_by_horizon,
)
from xerscope.analysis.longest_path import (
    SWITCHED,
    change_counts,
    longest_path,
    longest_path_funnel,
    path_changes,
    path_churn,
    path_commitments,
)
from xerscope.analysis.progress import kept_count
from xerscope.app import ui
from xerscope.app.cache import (
    memo,
)
from xerscope.app.downloads import (
    csv_download,
    sources_of,
)
from xerscope.app.sets import show_steps as show_funnel_steps
from xerscope.app.state import (
    open_in_gantt,
    page_header,
    require_store,
    snapshot_picker,
)
from xerscope.config import DEFAULT_SETTINGS
from xerscope.viz.charts import build_half_step, build_slip_trend

CASE_TEXT = {
    LAST_ACTIVITY: "the finish is the latest early finish of the project and moves freely",
    MUST_FINISH_BY: "a Must Finish By bounds the late dates only: the finish still moves, and the float of "
    "the longest path turns negative past the date",
    MANDATORY_FINISH: "a Mandatory Finish holds the last task's date: the delay shows in the float of "
    "the longest path, not in the finish",
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
    ui.caveat(
        "xerscope does not recalculate the finish P6 stored in the file (" + "; ".join(gaps) + "). The shifts "
        "below may come from the recalculation and not from the schedule: read them as indications only. "
        "The Schedule health page, Integrity standard, lists the dates that differ; the Debug page, block 3, "
        "the tasks where the difference starts and their form."
    )


def show_kpis(read, new) -> None:
    """Readout of the week; the formulas are those of analysis/explain.py."""
    float_d = longest_path_float_d(new)
    ui.kpis(
        [
            (
                "Finish before replanning",
                ui.fmt_date(read.finish_before_replanning),
                ui.SHIFT_WD_FORMAT.format(read.slip_wd),
            ),
            (
                "Finish shown",
                ui.fmt_date(read.new_finish),
                f"{ui.SHIFT_WD_FORMAT.format(read.replanning_wd)} by replanning",
            ),
            ("Longest path float", ui.fmt_number(float_d, "{:.1f} wd")),
            ("Tasks matched", f"{read.matched}", f"{read.added} added, {read.deleted} deleted"),
        ],
        formulas=KPI_FORMULAS,
    )


def show_steps(read, old, new) -> None:
    """Chart and table of the steps, the residual warning, the CSV."""
    ui.section(
        "Step by step",
        "The earlier update rescheduled with this update's changes applied one kind at a time, in this order; "
        "each bar is what that kind did to the finish.",
    )
    ui.chart(build_half_step(read.steps))
    ui.table(read.steps, key="forensics_steps", reading="forensics_steps")
    if read.is_slip_beyond_period:
        ui.caveat(
            f"The progress step lost {abs(read.slip_wd):.1f} wd in a period of {read.period_wd:.1f} wd. "
            "AACE 29R-03 3.4.K.4.g: a revision may sit in the half-step, or the lack of progress pushed work "
            "into a non-working stretch of a calendar."
        )
    if abs(read.residual_wd) > 0.005:
        ui.caveat(
            f"Residual {read.residual_wd:+.1f} wd: the steps do not account for every change between the two "
            "files. A change the changelog does not list moved the finish."
        )
    csv_download(
        read.steps,
        f"half_step_{ui.stamp(old.data_date)}_{ui.stamp(new.data_date)}.csv",
        "Download steps (CSV)",
        sources=sources_of(old, new),
    )


def show_horizon(old, new) -> None:
    """Where the week's revisions fall: within the lookahead, where work is made ready, or beyond it."""
    weeks = DEFAULT_SETTINGS.lookahead_weeks
    horizon = memo(
        ("forensics_horizon", old.label, new.label, weeks),
        revisions_by_horizon, old, new, weeks, baseline=False, ev_basis=False,
    )  # fmt: skip
    st.caption(
        f"Where the revisions fall: on tasks starting within {weeks:g} weeks of the status date (work under "
        "way included), where a Last Planner team makes work ready, or beyond. Revisions that fall mostly "
        "beyond reshape the far plan."
    )
    ui.table(horizon, key="forensics_horizon", reading="forensics_horizon")


def show_path_commitments(old, new) -> None:
    """Show the week's commitments made on the previous update's longest path, kept or not."""
    commitments = path_commitments(old, new)
    st.caption(
        f"Commitments of the week on the previous update's longest path: {kept_count(commitments)} kept of "
        f"{len(commitments)}. PPC counts every commitment alike; a miss here moves the finish."
    )
    if not commitments.empty:
        ui.table(
            commitments.sort_values(["kept", "planned_date"]),
            key="forensics_path_commitments",
            reading="forensics_path_commitments",
            max_height=ui.TABLE_SHORT,
            open_task=partial(open_in_gantt, snapshot=new),
        )


def show_longest_path(old, new) -> None:
    """Tasks that entered or left the longest path since the previous update, then the table."""
    changes = path_changes(old, new)
    counts = change_counts(changes)
    ui.section(
        "Longest path",
        f"Open tasks on the longest path of this update ({longest_path(new)[1]}) against the previous one "
        f"({longest_path(old)[1]}). {counts[SWITCHED]} still open left the path: it switched away from them. "
        "AACE RP 29R-03 3.4.E.9 and SVP 2.3.B.6.",
    )
    show_funnel_steps(longest_path_funnel(new)[0], key="forensics_path_funnel")
    ui.table(
        changes,
        key="forensics_path",
        reading="forensics_path",
        max_height=ui.TABLE_SHORT,
        open_task=partial(open_in_gantt, snapshot=new),
        empty="No open task is on the longest path of either update: nothing entered, stayed on or left it.",
    )


def show_path_series(store) -> None:
    """Longest path of every update against the one before it: table, CSV."""
    churn = memo(("forensics_path_churn",), path_churn, store, baseline=False, ev_basis=False)
    ui.table(churn, key="forensics_path_churn", reading="forensics_path_churn", max_height=ui.TABLE_SHORT)
    csv_download(churn, "longest_path_churn.csv", "Download longest path (CSV)", sources=sources_of(*list(store)))


def show_series(store) -> None:
    """Every update read against the one before it: chart, table, CSV."""
    ui.section(
        "Every update",
        "Each update read against the one before it. A finish shown that holds still while the finish before "
        "replanning keeps slipping is a delay absorbed by replanning.",
    )
    series = memo(("forensics_series",), half_step_series, store, baseline=False, ev_basis=False)
    ui.chart(build_slip_trend(series))
    ui.table(series, key="forensics_series", reading="forensics_series", max_height=ui.TABLE_SHORT)
    csv_download(series, "half_step_series.csv", "Download series (CSV)", sources=sources_of(*list(store)))


store = require_store()
top = st.container()
if len(store) < 2:
    with top:
        page_header("Delay analysis", store)
    st.info("The half-step reading compares consecutive updates: load at least two.")
    st.stop()

new = snapshot_picker(store, "Update", key="forensics_snap")
new_index = store.labels.index(new.label)
if new_index == 0:
    st.info("Pick an update after the first: the reading needs the one before it.")
    st.stop()
old = store[new_index - 1]
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
    read = memo(("forensics", old.label, new.label), half_step, old, new, baseline=False, ev_basis=False)
except ScheduleError as error:
    st.error(f"These two updates cannot be read: {ui.without_addresses(str(error))}", icon=":material/block:")
    st.stop()
show_case(new)
show_engine_gap(read, old, new)
show_kpis(read, new)
show_steps(read, old, new)
show_horizon(old, new)
show_longest_path(old, new)
show_path_commitments(old, new)
show_series(store)
show_path_series(store)
