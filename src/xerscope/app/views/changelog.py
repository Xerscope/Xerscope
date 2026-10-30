import pandas as pd
import streamlit as st

from xerscope.analysis.changelog import changelog, summary
from xerscope.app import ui
from xerscope.app.state import memo, require_store

store = require_store()
top = st.container()
if len(store) < 2:
    with top:
        ui.header("Changelog", store)
    st.info("Load at least two XER files to compare them.")
    st.stop()

labels = store.labels
c1, c2 = st.columns(2)
new_label = c2.selectbox("To (newer)", labels, index=len(labels) - 1, key="cl_new")
new_i = labels.index(new_label)
old_label = c1.selectbox("From (older)", labels, index=max(new_i - 1, 0), key="cl_old")
old, new = store.by_label(old_label), store.by_label(new_label)
with top:
    ui.header(
        "Changelog",
        store,
        new,
        lead="Everything that changed between two XER files: activities, durations, relationships, progress, "
        "dates, float, constraints, budgets and resource assignments. Activities are matched by Activity ID.",
    )
if old is new:
    st.warning("Pick two different files.")
    st.stop()

log = memo(("changelog", old_label, new_label), lambda: changelog(old, new))
counts = summary(log)


def n(category: str, *changes: str) -> int:
    c = counts[(counts["category"] == category) & (counts["change"].isin(changes) if changes else True)]
    return int(c["count"].sum())


proj = log[log["category"] == "Project"].set_index("change")
has_finish = "forecast finish" in proj.index and bool(proj.loc["forecast finish", "after"])
shift = proj.loc["forecast finish", "delta"] if "forecast finish" in proj.index else None
ui.kpis(
    [
        (
            "Forecast finish",
            f"{pd.Timestamp(proj.loc['forecast finish', 'after']):%d %b %Y}" if has_finish else "–",
            None if shift is None or pd.isna(shift) else f"{shift:+.1f} wd",
            None,
            "inverse",
        ),
        ("Added / deleted", f"{n('Scope', 'added')} / {n('Scope', 'deleted')}", None, "Activities"),
        ("Logic changes", n("Relationships")),
        ("Durations changed", n("Durations")),
        (
            "Retroactive actuals",
            n(
                "Progress",
                "actual start changed (retroactive)",
                "actual finish changed (retroactive)",
                "actual start removed",
                "actual finish removed",
            ),
            None,
            "Actual dates edited or removed after being reported: should not happen",
        ),
        ("Became critical", n("Float", "became critical")),
    ]
)

ui.section("Changes by category")
by_cat = counts.groupby("category", observed=True)["count"].sum().rename("total").reset_index()
ui.table(
    by_cat.merge(
        counts.groupby("category", observed=True)["change"]
        .apply(lambda s: ", ".join(sorted(s)))
        .rename("kinds")
        .reset_index(),
        on="category",
    ),
    overrides={
        "total": st.column_config.NumberColumn("Changes", format="%d"),
        "kinds": st.column_config.TextColumn("Kinds of change", width="large"),
    },
)

ui.section("All changes")
f1, f2, f3 = st.columns([2, 3, 2])
cats = f1.multiselect("Category", [c for c in log["category"].cat.categories if c != "Project"], placeholder="All")
kinds = f2.multiselect("Change", sorted(counts["change"].unique()), placeholder="All")
search = f3.text_input("Search", placeholder="ID, name or WBS")
view = log[log["category"] != "Project"]
if cats:
    view = view[view["category"].isin(cats)]
if kinds:
    view = view[view["change"].isin(kinds)]
if search:
    s = ui.fold(search)
    view = view[
        view[["task_code", "task_name", "wbs_code", "field"]]
        .apply(lambda col: col.map(ui.fold).str.contains(s, regex=False))
        .any(axis=1)
    ]
st.caption(f"{len(view):,} change(s) shown")
ui.table(view, max_height=640)
ui.csv_button(log, f"changelog_{old.data_date:%Y-%m-%d}_{new.data_date:%Y-%m-%d}.csv", "Download changelog (CSV)")

with st.expander("Every week, side by side"):

    def weekly():
        frames = []
        for i in range(1, len(store)):
            c = summary(changelog(store[i - 1], store[i]))
            c["week"] = f"{store[i].data_date:%Y-%m-%d}"
            frames.append(c)
        return pd.concat(frames, ignore_index=True)

    w = memo(("changelog_weekly",), weekly)
    wide = (
        w.pivot_table(index=["category", "change"], columns="week", values="count", aggfunc="sum", observed=True)
        .fillna(0)
        .astype(int)
        .reset_index()
    )
    ui.table(wide, max_height=640)
