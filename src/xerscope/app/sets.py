"""The sets behind a check, as the Audit page and Schedule health show them.

Cut by ``analysis.audit.split`` from what the rule returned, never rebuilt here. ``prefix`` keeps
the widget keys apart when several checks are shown on one page.
"""

import pandas as pd
import streamlit as st

from xerscope.analysis.audit import (
    counted_count,
    funnel_table,
    removed_set,
    removing_steps,
    split,
    step_rows,
    step_sources,
)
from xerscope.analysis.explain import noun
from xerscope.analysis.populations import STEP_SOURCES
from xerscope.app import ui
from xerscope.app.state import csv_download


def source_text(key: str, own_source: str = "") -> str:
    """A step's source as the caption shows it: its key alone for a web page, with its text otherwise.

    An "xerscope" step (an exclusion a standard of your own sets) names that standard's ``source``.
    The app shows no external link: the address of a web page is in docs/standards.md, Sources.
    """
    if key == "xerscope" and own_source:
        return f"{key}: {own_source}"
    source = STEP_SOURCES[key]
    return key if source.startswith("http") else f"{key}: {source}"


def source_caption(funnel, own_source: str = "") -> str:
    """The sources a funnel's steps follow, on one line; ``own_source`` is the standard's own text."""
    return " · ".join(source_text(key, own_source) for key in step_sources(funnel))


def show_set(frame: pd.DataFrame, title: str, filename: str, key: str, sources: list[str]) -> None:
    if frame.empty:
        st.caption(f"No {title.lower()}.")
        return
    ui.table(frame, max_height=480, key=f"table_{key}")
    # anonymised or raw as the sidebar switch says; only the files behind this result are read
    csv_download(frame, filename, "Download CSV", key=f"dl_{key}", sources=sources)


def show_steps(funnel) -> None:
    """A funnel's steps as a table, each step with the text it follows (the Gantt Ask field)."""
    ui.table(
        pd.DataFrame(step_rows(funnel)),
        raw_labels=True,
        key="ask_funnel",
        overrides={name: st.column_config.NumberColumn(name, format="%d") for name in ("removed", "left")},
    )
    st.caption(source_caption(funnel))


def show_removed(result, snapshot, sources: list[str]) -> None:
    """The rows one step took out of the population, the step picked among those that removed any."""
    removing = removing_steps(result.funnel)
    if not removing:
        return
    label = st.selectbox(
        "Rows removed by", [step.label for step in removing], index=None, key=f"funnel_step:{result.metric.id}"
    )
    if label is None:
        return
    subject, frame = removed_set(next(step for step in removing if step.label == label))
    show_set(
        frame,
        f"{subject} removed",
        f"{result.metric.id}_{ui.stamp(snapshot.data_date)}_removed.csv",
        "removed",
        sources,
    )


def show_funnel(result, snapshot, sources: list[str]) -> None:
    """How the denominator was cut from the file, step by step, each step with the text it follows."""
    if result.funnel is None:
        return
    st.markdown("**Population, step by step**")
    ui.table(
        funnel_table(result.funnel, result.numerator),
        raw_labels=True,
        key="funnel",
        overrides={name: st.column_config.NumberColumn(name, format="%d") for name in ("removed", "left")},
    )
    if result.funnel.steps:
        st.caption(source_caption(result.funnel, result.metric.source))
    show_removed(result, snapshot, sources)


def show_sets(result, snapshot, sources: list[str], prefix: str = "") -> None:
    """Counted / Checked, not counted / Excluded tabs; for a check with no population, its note."""
    sets = split(result, snapshot)
    if sets is None:
        st.caption("This check has no population to list (a ratio or a pass/fail test).")
        if result.note:
            st.markdown(f"**Note** · {ui.md_text(result.note)}")
        return
    stamp = f"{result.metric.id}_{ui.stamp(snapshot.data_date)}"
    labels = [
        f"Counted ({counted_count(result, sets)})",
        f"Checked, not counted ({len(sets.not_counted)})",
    ]
    if sets.excluded is not None:
        labels.append(f"Excluded ({len(sets.excluded)})")
    tabs = st.tabs(labels)
    with tabs[0]:
        if sets.counted_outside:
            st.caption(
                f"{sets.counted_outside} {noun(sets.subject, sets.counted_outside)} counted here are not in the "
                "checked set (the numerator is not a part of the denominator for this check)."
            )
        show_set(sets.counted, "Counted items", f"{stamp}_counted.csv", f"{prefix}counted", sources)
    with tabs[1]:
        show_set(
            sets.not_counted, "Checked items not counted", f"{stamp}_not_counted.csv", f"{prefix}not_counted", sources
        )
    if sets.excluded is not None:
        with tabs[2]:
            st.caption(f"The file's {sets.subject} outside the checked set; their status and type say why.")
            show_set(sets.excluded, "Excluded items", f"{stamp}_excluded.csv", f"{prefix}excluded", sources)
