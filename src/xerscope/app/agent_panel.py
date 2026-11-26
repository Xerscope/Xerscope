"""The Gantt Ask field's agent answer: drawn under the grammar's banner when XERSCOPE_AGENT=on.

The answer, then "How the agent answered": the question, the model's choice, each condition with the
activities it left (the funnel the Gantt draws), the value said, the model and the seconds, and its
reasoning when XERSCOPE_AGENT_THINKING asked for one (a model's own account, which need not be what
led to its choice: the trace above it is). The agent package is imported only when the agent is on,
so an app without it never loads the code that opens a connection.
"""

from __future__ import annotations

import os
import threading

import streamlit as st

from xerscope.app import ui
from xerscope.app.cache import memo

AGENT_VARIABLE = "XERSCOPE_AGENT"
WARMED_KEY = "_agent_warmed"  # the updates whose instructions the model already read


def agent_enabled() -> bool:
    """XERSCOPE_AGENT=on: what the grammar did not read goes to the local model."""
    return os.environ.get(AGENT_VARIABLE, "").strip().lower() == "on"


def warm_agent(store, snapshot) -> None:
    """Have the local model read the instructions of ``snapshot`` once, in the background.

    The first question on an update then reads only itself. Nothing is drawn; a model that does not
    answer is left to the first question to say.
    """
    warmed = st.session_state.setdefault(WARMED_KEY, set())
    if snapshot.source in warmed:
        return
    warmed.add(snapshot.source)
    from xerscope import agent
    from xerscope.agent import client, tools

    context = memo(("agent_view", snapshot.source), tools.context_for, store, snapshot, baseline=False, ev_basis=False)
    instructions = [{"role": "system", "content": agent.system_prompt(context.view)}, {"role": "user", "content": ""}]
    for url in filter(None, (client.fast_url(), client.model_url())):
        threading.Thread(target=client.warm, args=(instructions, url), daemon=True).start()


def show_agent_answer(asked: str, store, snapshot):
    """Ask the local agent once per sentence and update, draw its answer and its trace, and return it.

    None when no model could be asked. A query's activities are what the Gantt then draws.
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
        model = " · fast model" if said.model == "fast" else ""
        st.caption(f"local agent · {said.command} · {said.field}{argument}{model} · {said.seconds:.1f} s")
        with st.expander("How the agent answered", key="ask_agent_trace"):
            st.markdown(ui.md_text("\n".join(trace_lines(asked, said))))
            if said.reasoning:
                st.caption("The model's reasoning: its own account, not a proof; the steps above are what ran.")
                st.text(said.reasoning)
    return said


def trace_lines(asked: str, said) -> list[str]:
    """Write the answer's path, one Markdown line each: question, choice, conditions and funnel, answer."""
    lines = [f"- **Question:** {asked}", f"- **Choice:** {said.command} · {said.field}"]
    if said.choice.argument:
        lines.append(
            f"- **Task:** {said.choice.argument}" + (f" · {said.choice.days:g} days" if said.choice.days else "")
        )
    steps = said.values.get("steps") or []
    if steps:
        path = " → ".join([f"{said.values['start']} activities", *(f"{left} ({label})" for label, left in steps)])
        lines.append(f"- **Funnel:** {path}")
    lines.append(f"- **Answer:** {said.sentence or 'none, ' + said.refused}")
    lines.append(f"- **Model:** {'fast' if said.model == 'fast' else 'main'} · {said.seconds:.1f} s")
    return lines
