"""Entry point: ``uv run xerscope app`` (or ``streamlit run`` this file)."""

import sys
from pathlib import Path

import streamlit as st

# Allow `streamlit run src/xerscope/app/streamlit_app.py` without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from xerscope.app.state import sidebar_loader  # noqa: E402

st.set_page_config(page_title="xerscope", page_icon=":material/calendar_month:", layout="wide")

VIEWS = Path(__file__).parent / "views"
pages = st.navigation(
    {
        "Schedule": [
            st.Page(VIEWS / "overview.py", title="Overview", icon=":material/dashboard:", default=True),
            st.Page(VIEWS / "gantt.py", title="Gantt & WBS", icon=":material/view_timeline:"),
            st.Page(VIEWS / "activity.py", title="Activity history", icon=":material/history:"),
        ],
        "Analysis": [
            st.Page(VIEWS / "health.py", title="Schedule health", icon=":material/fact_check:"),
            st.Page(VIEWS / "changelog.py", title="Changelog", icon=":material/difference:"),
            st.Page(VIEWS / "earned_value.py", title="Earned value", icon=":material/stacked_line_chart:"),
            st.Page(VIEWS / "milestones.py", title="Milestone trend", icon=":material/flag:"),
            st.Page(VIEWS / "ppc.py", title="PPC & progress", icon=":material/task_alt:"),
        ],
        "Data": [
            st.Page(VIEWS / "export.py", title="Export for Power BI", icon=":material/download:"),
        ],
    }
)

sidebar_loader()
pages.run()
