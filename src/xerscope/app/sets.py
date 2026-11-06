"""The sets behind a check, as the Audit page and Schedule health show them.

Cut by ``analysis.audit.split`` from what the rule returned, never rebuilt here. ``prefix`` keeps
the widget keys apart when several checks are shown on one page.
"""

import pandas as pd
import streamlit as st

from xerscope.analysis.audit import split
from xerscope.analysis.explain import noun
from xerscope.analysis.populations import STEP_SOURCES, flagged_activities, flagged_relationships
from xerscope.app import ui
from xerscope.app.state import csv_download


def show_set(frame: pd.DataFrame, title: str, filename: str, key: str, sources: list[str]) -> None:
    if frame.empty:
        st.caption(f"No {title.lower()}.")
        return
    ui.table(frame, max_height=480, key=f"table_{key}")
    # anonymised or raw as the sidebar switch says; only the files behind this result are read
    csv_download(frame, filename, "Download CSV", key=f"dl_{key}", sources=sources)


def steps_table(funnel) -> list[dict]:
    """Start, then one row per population step (rows removed, rows left)."""
    rows = [{"step": "start", "source": "", "removed": None, "left": funnel.start}]
    rows += [
        {"step": step.label, "source": step.source, "removed": len(step.removed), "left": step.left}
        for step in funnel.steps
    ]
    return rows


def funnel_table(result) -> pd.DataFrame:
    """The steps of a check's population, then the counted items."""
    rows = steps_table(result.funnel)
    rows.append({"step": "counted", "source": "", "removed": None, "left": result.numerator})
    return pd.DataFrame(rows)


def show_steps(funnel) -> None:
    """A funnel's steps as a table, each step with the text it follows (the Gantt Ask field)."""
    ui.table(
        pd.DataFrame(steps_table(funnel)),
        raw_labels=True,
        key="ask_funnel",
        overrides={name: st.column_config.NumberColumn(name, format="%d") for name in ("removed", "left")},
    )
    used = sorted({step.source for step in funnel.steps})
    st.caption(" · ".join(f"{key}: {STEP_SOURCES[key]}" for key in used))


def show_funnel(result, snapshot, sources: list[str]) -> None:
    """How the denominator was cut from the file, step by step, each step with the text it follows."""
    funnel = result.funnel
    if funnel is None:
        return
    st.markdown("**Population, step by step**")
    ui.table(
        funnel_table(result),
        raw_labels=True,
        key="funnel",
        overrides={name: st.column_config.NumberColumn(name, format="%d") for name in ("removed", "left")},
    )
    used = sorted({step.source for step in funnel.steps})
    if used:
        st.caption(
            " · ".join(
                f"[{key}]({STEP_SOURCES[key]})"
                if STEP_SOURCES[key].startswith("http")
                else f"{key}: {STEP_SOURCES[key]}"
                for key in used
            )
        )
    removing = [step for step in funnel.steps if not step.removed.empty]
    if not removing:
        return
    label = st.selectbox(
        "Rows removed by", [step.label for step in removing], index=None, key=f"funnel_step:{result.metric.id}"
    )
    if label is not None:
        step = next(step for step in removing if step.label == label)
        subject = "relationships" if "pred_code" in step.removed.columns else "activities"
        frame = flagged_relationships(step.removed) if subject == "relationships" else flagged_activities(step.removed)
        show_set(
            frame,
            f"{subject} removed",
            f"{result.metric.id}_{ui.stamp(snapshot.data_date)}_removed.csv",
            "removed",
            sources,
        )


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
        f"Counted ({result.numerator if result.numerator is not None else len(sets.counted)})",
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
