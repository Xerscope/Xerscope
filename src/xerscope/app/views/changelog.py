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
from xerscope.app.state import csv_download, memo, open_in_gantt, page_header, require_store, sources_of

SEARCH_COLUMNS = ["task_code", "task_name", "wbs_code", "field"]


def show_kpis(log: pd.DataFrame, counts: pd.DataFrame) -> None:
    finish, shift_wd = forecast_finish(log)
    headline = headline_counts(counts)
    ui.kpis(
        [
            (
                "Forecast finish",
                ui.fmt_date(finish),
                None if shift_wd is None else f"{shift_wd:+.1f} wd",
                "Working days gained (+) or lost (−) on the forecast finish between the two updates "
                "(project calendar): a later finish reads negative",
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


def show_categories(counts: pd.DataFrame) -> None:
    ui.section("Changes by category")
    ui.table(
        category_totals(counts),
        key="changelog_categories",
        overrides={
            **ui.count_columns(total="Changes"),
            "kinds": st.column_config.TextColumn("Kinds of change", width="large"),
        },
    )


def show_all_changes(log: pd.DataFrame, counts: pd.DataFrame, old, new) -> None:
    ui.section("All changes")
    category_column, change_column, search_column = st.columns([2, 3, 2])
    categories = category_column.multiselect(
        "Category", [name for name in log["category"].cat.categories if name != "Project"], placeholder="All"
    )
    kinds = change_column.multiselect("Change", sorted(counts["change"].unique()), placeholder="All")
    search = search_column.text_input("Search", placeholder="ID, name or WBS")
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
    ui.table(view, max_height=640, key="changelog_all", open_task=partial(open_in_gantt, snapshot=new))
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
        ui.table(wide, max_height=640, key="changelog_weekly")


store = require_store()
top = st.container()
if len(store) < 2:
    with top:
        page_header("Changelog", store)
    st.info("Load at least two XER files to compare them.")
    st.stop()

labels = store.labels
old_column, new_column = st.columns(2)
new_label = new_column.selectbox("To (newer)", labels, index=len(labels) - 1, key="cl_new")
new_index = labels.index(new_label)
old_label = old_column.selectbox("From (older)", labels, index=max(new_index - 1, 0), key="cl_old")


def _from(back: int | None) -> None:
    """From = ``back`` updates before To (None: the first loaded)."""
    index = labels.index(st.session_state["cl_new"])
    st.session_state["cl_old"] = labels[0 if back is None else max(index - back, 0)]


with old_column, st.container(horizontal=True, gap="small"):
    for text, back in (("Previous", 1), ("4 back", 4), ("First", None)):
        st.button(text, key=f"cl_from_{text}", type="secondary", on_click=_from, args=(back,))
old, new = store.by_label(old_label), store.by_label(new_label)
with top:
    page_header(
        "Changelog",
        store,
        new,
        lead="Everything that changed between two XER files: tasks, durations, relationships, progress, "
        "dates, float, constraints, budgets and resource assignments. Tasks are matched by Task ID.",
    )
if old is new:
    st.warning("Pick two different files.")
    st.stop()

log = memo(("changelog", old_label, new_label), changelog, old, new, baseline=False)
counts = summary(log)
show_kpis(log, counts)
show_categories(counts)
show_all_changes(log, counts, old, new)
show_weekly(store)
