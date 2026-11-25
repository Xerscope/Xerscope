"""The Gantt Ask field's agent answer: drawn under the grammar's banner when XERSCOPE_AGENT=on.

The agent package is imported only when the agent is on, so an app without it never loads the code
that opens a connection.
"""

from __future__ import annotations

import os

import streamlit as st

from xerscope.app import ui
from xerscope.app.cache import memo

AGENT_VARIABLE = "XERSCOPE_AGENT"


def agent_enabled() -> bool:
    """XERSCOPE_AGENT=on: what the grammar did not read goes to the local model."""
    return os.environ.get(AGENT_VARIABLE, "").strip().lower() == "on"


def show_agent_answer(asked: str, store, snapshot):
    """Ask the local agent once per sentence and update, draw its answer, and return it.

    None when the model could not be asked. A query's activities are what the Gantt then draws.
    """
    from xerscope import agent
    from xerscope.agent import client, tools
    from xerscope.analysis import query

    context = memo(("agent_view", snapshot.source), tools.context_for, store, snapshot, baseline=False, ev_basis=False)
    lang = query.language(asked)
    try:
        said = memo(
            ("agent", snapshot.source, asked), agent.answer, asked, context, lang, baseline=False, ev_basis=False
        )
    except client.ModelError as error:
        st.warning(f"Local agent unavailable: {error}")
        return None
    with st.container(border=True, key="ask_agent"):
        st.markdown(ui.md_text(said.sentence if not said.refused else f"Agent: no answer, {said.refused}."))
        if said.command == "simulate_delay" and not said.refused:
            st.caption(ui.md_text(said.values["note"]))
        argument = f" · {said.choice.argument}" if said.choice.argument else ""
        st.caption(f"local agent · {said.command} · {said.field}{argument} · {said.seconds:.1f} s")
    return said
