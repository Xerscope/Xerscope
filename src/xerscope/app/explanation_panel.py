"""The explanation of a check as the Health and Audit pages show it."""

import pandas as pd
import streamlit as st

from xerscope.app import ui


def show_calculation(result, explanation) -> None:
    """Show the calculation box, the population, the note and the baseline of one check."""
    with st.container(border=True):
        st.caption("Calculation")
        st.markdown(f"**{explanation.formula}**")  # not a heading: each check would enter the outline
        st.markdown(explanation.verdict)
    if explanation.population:
        st.markdown("**Population**")
        st.markdown("\n".join(f"- {line}" for line in explanation.population))
    if result.note and result.note not in explanation.formula:
        st.markdown(f"**Note** · {ui.md_text(result.note)}")
    if explanation.baseline:
        st.markdown(f"**Baseline** · {ui.md_text(explanation.baseline)}")


def metric_panel(result, explanation, reading: str | None = None, detailed: bool = False) -> None:
    """Show the explanation of one check in two columns: the calculation, then the method.

    ``explanation`` is ``explain(result)``, which the page holds already. ``reading``, a READINGS key, puts a
    "How to read" popover above. ``detailed`` (Schedule health) adds what the check measures above the calculation
    and the parameters table under the method; the Audit page, which sets the parameters itself, leaves both out.
    """
    ui.reading_popover(reading)
    left, right = st.columns([3, 2], gap="large")
    with left:
        if detailed:
            st.markdown(f"**What it measures** · {explanation.measured}")
        show_calculation(result, explanation)
    with right:
        show_method(result.metric, explanation, explanation.parameters if detailed else ())


def show_method(metric, explanation, parameters=()) -> None:
    """Show the method of a check, its parameters table when given, and its source."""
    st.markdown("**Method**")
    st.caption(explanation.method.replace("``", "`"))
    if parameters:
        st.markdown("**Parameters**")
        ui.table(
            pd.DataFrame(parameters, columns=["parameter", "value", "set by"]),
            max_height=ui.TABLE_SHORT,
            key=f"params_{metric.id}",  # one table per check: filters keyed per check
            reading="check_parameters",
        )
    source = ui.without_addresses(metric.source)
    if source:
        st.caption(f"Source: {source}")
