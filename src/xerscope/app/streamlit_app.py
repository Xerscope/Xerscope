"""Entry point: ``uv run xerscope app``.

``xerscope app`` runs Streamlit from this folder so ``.streamlit/config.toml`` (theme,
localhost binding) applies whatever the Streamlit version (1.66 also reads it next to the
script). Debug, block 12, shows what was read.

Streamlit installs this script as the ``__main__`` module of each run. A file-reading worker
(``app/reading.py``, start method ``spawn``) runs the parent's ``__main__`` file again, as
``__mp_main__``, before its first task; the guard at the bottom keeps the app, and Streamlit, out of
the workers (Python documentation, multiprocessing, "Safe importing of main module").
"""

import sys
from pathlib import Path

VIEWS = Path(__file__).parent / "views"


def main() -> None:
    import streamlit as st

    # Allow `streamlit run src/xerscope/app/streamlit_app.py` without installing the package.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from xerscope.app import ui
    from xerscope.app.state import debug_page, sidebar_loader

    st.set_page_config(page_title="xerscope", page_icon=":material/calendar_month:", layout="wide")

    pages = st.navigation(
        {
            "Schedule": [
                st.Page(VIEWS / "overview.py", title="Overview", icon=":material/dashboard:", default=True),
                st.Page(VIEWS / "gantt.py", title="Gantt & WBS", icon=":material/view_timeline:"),
                st.Page(VIEWS / "activity.py", title="Task history (to be removed)", icon=":material/history:"),
            ],
            "Analysis": [
                st.Page(VIEWS / "health.py", title="Schedule health", icon=":material/fact_check:"),
                st.Page(VIEWS / "audit.py", title="Audit", icon=":material/manage_search:"),
                st.Page(VIEWS / "changelog.py", title="Changelog", icon=":material/difference:"),
                st.Page(VIEWS / "earned_value.py", title="Earned value", icon=":material/stacked_line_chart:"),
                st.Page(VIEWS / "milestones.py", title="Milestone trend", icon=":material/flag:"),
                st.Page(VIEWS / "ppc.py", title="PPC & progress", icon=":material/task_alt:"),
            ],
            "Data": [
                st.Page(VIEWS / "export.py", title="Export for Power BI", icon=":material/download:"),
                # the Debug page lists what the app read and decided, file by file: not on a deployed
                # instance (XERSCOPE_DATA_LOCKED) unless asked for with XERSCOPE_DEBUG_PAGE=1
                *([st.Page(VIEWS / "debug.py", title="Debug", icon=":material/bug_report:")] if debug_page() else []),
            ],
        }
    )

    ui.apply_style()
    sidebar_loader()
    ui.glossary()
    pages.run()


if __name__ == "__main__":  # a Streamlit run; "__mp_main__" in a file-reading worker
    main()
