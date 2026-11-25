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


def show_agent_answer(asked: str, store, snapshot, tasks, nodes, lexicon) -> None:
    """Ask the local agent once per sentence and update, and draw its answer and how it was reached."""
    from xerscope import agent
    from xerscope.agent import client, tools
    from xerscope.analysis import query

    context = tools.Context(store, snapshot, tasks, nodes, lexicon)
    lang = query.language(asked)
    try:
        said = memo(
            ("agent", snapshot.source, asked), agent.answer, asked, context, lang, baseline=False, ev_basis=False
        )
    except client.ModelError as error:
        st.warning(f"Local agent unavailable: {error}")
        return
    with st.container(border=True, key="ask_agent"):
        if said.refused:
            st.markdown(ui.md_text(f"Agent: no answer, {said.refused}."))
        else:
            st.markdown(ui.md_text(said.sentence))
        argument = f" · {said.argument}" if said.argument and said.command != "filter" else ""
        st.caption(f"local agent · {said.command} · {said.field}{argument} · {said.seconds:.1f} s")
