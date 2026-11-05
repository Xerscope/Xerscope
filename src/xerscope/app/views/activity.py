"""One activity across every weekly update: how its dates, float and progress moved.

The same panel opens under the Gantt for the activity picked there (app/task_panel.py).
"""

from functools import partial

import streamlit as st

from xerscope.app import ui
from xerscope.app.state import page_header, require_store
from xerscope.app.task_panel import show_history

store = require_store()
page_header(
    "Task history",
    store,
    store.latest,
    lead="Follow one task through every loaded update: forecast dates, float and progress.",
)

names = ui.latest_names(store)
choice = st.selectbox("Task", names.index, format_func=partial(ui.code_label, names))
show_history(store, choice)
