import pandas as pd
import streamlit as st

from xerscope.analysis.changelog import category_totals, changelog, summary, weekly_change_counts, weekly_change_matrix
from xerscope.app import ui
from xerscope.app.state import csv_download, memo, require_store, sources_of

RETROACTIVE_ACTUALS = (
    "actual start changed (retroactive)",
    "actual finish changed (retroactive)",
    "actual start removed",
    "actual finish removed",
)
SEARCH_COLUMNS = ["task_code", "task_name", "wbs_code", "field"]


def count_changes(counts: pd.DataFrame, category: str, *changes: str) -> int:
    """Number of changes in a category, optionally only of the given kinds."""
    in_category = counts["category"] == category
    wanted = counts["change"].isin(changes) if changes else True
    return int(counts[in_category & wanted]["count"].sum())


def show_kpis(log: pd.DataFrame, counts: pd.DataFrame) -> None:
    project = log[log["category"] == "Project"].set_index("change")
    has_finish = "forecast finish" in project.index and bool(project.loc["forecast finish", "after"])
    shift = project.loc["forecast finish", "delta"] if "forecast finish" in project.index else None
    finish_text = ui.fmt_date(pd.Timestamp(project.loc["forecast finish", "after"])) if has_finish else "–"
    ui.kpis(
        [
            (
                "Forecast finish",
                finish_text,
                None if shift is None or pd.isna(shift) else f"{shift:+.1f} wd",
                None,
                "inverse",
            ),
            (
                "Added / deleted",
                f"{count_changes(counts, 'Scope', 'added')} / {count_changes(counts, 'Scope', 'deleted')}",
                None,
                "Tasks",
            ),
            ("Logic changes", count_changes(counts, "Relationships")),
            ("Durations changed", count_changes(counts, "Durations")),
            (
                "Retroactive actuals",
                count_changes(counts, "Progress", *RETROACTIVE_ACTUALS),
                None,
                "Actual dates edited or removed after being reported: should not happen",
            ),
            ("Became critical", count_changes(counts, "Float", "became critical")),
        ]
    )


def show_categories(counts: pd.DataFrame) -> None:
    ui.section("Changes by category")
    ui.table(
        category_totals(counts),
        overrides={
            "total": st.column_config.NumberColumn("Changes", format="%d"),
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
    st.caption(f"{len(view):,} change(s) shown")
    ui.table(view, max_height=640)
    csv_download(
        log,
        f"changelog_{ui.stamp(old.data_date)}_{ui.stamp(new.data_date)}.csv",
        "Download changelog (CSV)",
        sources=sources_of(old, new),
    )


def show_weekly(store) -> None:
    with st.expander("Every week, side by side"):
        weekly = memo(("changelog_weekly",), weekly_change_counts, store)
        wide = weekly_change_matrix(weekly)
        ui.table(wide, max_height=640)


store = require_store()
top = st.container()
if len(store) < 2:
    with top:
        ui.header("Changelog", store)
    st.info("Load at least two XER files to compare them.")
    st.stop()

labels = store.labels
old_column, new_column = st.columns(2)
new_label = new_column.selectbox("To (newer)", labels, index=len(labels) - 1, key="cl_new")
new_index = labels.index(new_label)
old_label = old_column.selectbox("From (older)", labels, index=max(new_index - 1, 0), key="cl_old")
old, new = store.by_label(old_label), store.by_label(new_label)
with top:
    ui.header(
        "Changelog",
        store,
        new,
        lead="Everything that changed between two XER files: tasks, durations, relationships, progress, "
        "dates, float, constraints, budgets and resource assignments. Tasks are matched by Task ID.",
    )
if old is new:
    st.warning("Pick two different files.")
    st.stop()

log = memo(("changelog", old_label, new_label), changelog, old, new)
counts = summary(log)
show_kpis(log, counts)
show_categories(counts)
show_all_changes(log, counts, old, new)
show_weekly(store)
