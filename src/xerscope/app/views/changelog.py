from functools import partial

import pandas as pd
import streamlit as st

from xerscope.analysis.changelog import (
    category_totals,
    changelog,
    forecast_finish,
    headline_counts,
    summary,
    weekly_change_counts,
    weekly_change_matrix,
)
from xerscope.app import ui
from xerscope.app.cache import memo
from xerscope.app.downloads import csv_download, sources_of
from xerscope.app.state import open_in_gantt, page_header, require_store

SEARCH_COLUMNS = ["task_code", "task_name", "wbs_code", "field"]


def show_kpis(log: pd.DataFrame, counts: pd.DataFrame) -> None:
    finish, shift_wd = forecast_finish(log)
    headline = headline_counts(counts)
    ui.kpis(
        [
            (
                "Forecast finish",
                ui.fmt_date(finish),
                None if shift_wd is None else ui.SHIFT_WD_FORMAT.format(shift_wd),
                f"Forecast finish between the two updates, on the project calendar. {ui.SHIFT_WD_SENTENCE}",
            ),
            ("Added / deleted", f"{headline['added']} / {headline['deleted']}", None, "Tasks"),
            ("Logic changes", headline["logic"]),
            ("Durations changed", headline["durations"]),
            (
                "Retroactive actuals",
                headline["retroactive_actuals"],
                None,
                "Actual dates edited or removed after being reported: should not happen",
            ),
            ("Became critical", headline["became_critical"]),
        ]
    )


def show_categories(counts: pd.DataFrame, old, new) -> None:
    ui.section("Changes by category")
    ui.table(
        category_totals(counts),
        key="changelog_categories",
        reading="changelog_categories",
        empty=f"No change between {old.label} and {new.label}: no task, link, duration, date, resource or budget "
        "differs, the tasks being matched by Task ID.",
    )


def show_all_changes(log: pd.DataFrame, counts: pd.DataFrame, old, new) -> None:
    ui.section("All changes")
    category_column, change_column, search_column = st.columns([2, 3, 2])
    categories = category_column.multiselect(
        "Category",
        [name for name in log["category"].cat.categories if name != "Project"],
        placeholder="All",
        help="Keeps the changes of the picked categories (Scope, Dates, Logic, Durations, Resources, "
        "Constraints…; the Project rows are never listed here). Empty keeps all.",
    )
    kinds = change_column.multiselect(
        "Change",
        sorted(counts["change"].unique()),
        placeholder="All",
        help="Keeps the picked kinds of change within the categories. "
        "Use it to list one kind, such as durations changed, on its own.",
    )
    search = search_column.text_input(
        "Search",
        placeholder="ID, name or WBS",
        help="Keeps the rows whose Task ID, name, WBS or field contains the text, ignoring case and accents. "
        "Use it to follow one task or one WBS branch.",
    )
    view = log[log["category"] != "Project"]
    if categories:
        view = view[view["category"].isin(categories)]
    if kinds:
        view = view[view["change"].isin(kinds)]
    if search:
        view = view[ui.search_mask(view, SEARCH_COLUMNS, search)]
    st.caption(
        f"{len(view):,} change(s) shown. Δ of a start or a finish: working days gained (+) or lost (−), a later "
        "date reads negative. Δ of the other rows: after minus before."
    )
    ui.table(
        view,
        max_height=ui.TABLE_LONG,
        key="changelog_all",
        reading="changelog_all",
        open_task=partial(open_in_gantt, snapshot=new),
        empty=f"No change to list between {old.label} and {new.label}: the Category, Change and Search filters above "
        "keep none of the log (the log itself is empty only when the two files hold the same tasks, links, dates "
        "and resources).",
    )
    csv_download(
        log,
        f"changelog_{ui.stamp(old.data_date)}_{ui.stamp(new.data_date)}.csv",
        "Download changelog (CSV)",
        sources=sources_of(old, new),
    )


def show_weekly(store) -> None:
    with st.expander("Every week, side by side"):
        weekly = memo(("changelog_weekly",), weekly_change_counts, store, baseline=False)
        wide = weekly_change_matrix(weekly)
        ui.table(
            wide,
            max_height=ui.TABLE_LONG,
            key="changelog_weekly",
            reading="changelog_weekly",
            empty="No change was recorded between any two consecutive updates of the series.",
        )


store = require_store()
top = st.container()
if len(store) < 2:
    with top:
        page_header("Changelog", store)
    st.info("Load at least two XER files to compare them.")
    st.stop()

labels = store.labels
old_column, new_column = st.columns(2)
# From is always older than To: a log read backwards shows a slip as a gain and actuals as removed
new_label = new_column.selectbox(
    "To (newer)",
    labels[1:],
    index=len(labels) - 2,
    key="cl_new",
    help="The later of the two updates compared; the changes are read as To minus From. "
    "Use it with From to compare any two weeks, not only consecutive ones.",
)
new_index = labels.index(new_label)
older_labels = labels[:new_index]
if st.session_state.get("cl_old") not in older_labels:
    st.session_state["cl_old"] = older_labels[-1]  # To moved before From: From follows, one update back
old_label = old_column.selectbox(
    "From (older)",
    older_labels,
    key="cl_old",
    help="The earlier of the two updates compared: only the updates before To are listed. The buttons below "
    "set it one, four updates back or to the first loaded.",
)


def _from(back: int | None) -> None:
    """From = ``back`` updates before To (None: the first loaded)."""
    index = labels.index(st.session_state["cl_new"])
    st.session_state["cl_old"] = labels[0 if back is None else max(index - back, 0)]


with old_column, st.container(horizontal=True, gap="small"):
    for text, back in (("Previous", 1), ("4 back", 4), ("First", None)):
        st.button(
            text,
            key=f"cl_from_{text}",
            type="secondary",
            on_click=_from,
            args=(back,),
            help="Sets From to the update before To, four updates before it, or the first loaded. "
            'Use "4 back" for a monthly reading.',
        )
old, new = store.by_label(old_label), store.by_label(new_label)
with top:
    page_header(
        "Changelog",
        store,
        new,
        lead="Everything that changed between two XER files: tasks, durations, relationships, progress, "
        "dates, float, constraints, budgets and resource assignments. Tasks are matched by Task ID.",
    )
log = memo(("changelog", old_label, new_label), changelog, old, new, baseline=False)
counts = summary(log)
show_kpis(log, counts)
show_categories(counts, old, new)
show_all_changes(log, counts, old, new)
show_weekly(store)
