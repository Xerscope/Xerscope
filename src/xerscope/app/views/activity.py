"""One activity across every weekly update: how its dates, float and progress moved."""

from functools import partial

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from xerscope.app import ui
from xerscope.app.state import is_dark, require_store
from xerscope.viz.charts import FONT, INK, SERIES, STATUS, TICK

LIST_COLUMNS = [
    "data_date",
    "status",
    "start",
    "finish",
    "total_float_d",
    "remaining_d",
    "original_d",
    "pct_complete",
    "is_critical",
]


def activity_label(names: pd.Series, task_code: str) -> str:
    """Selectbox label for an Activity ID: the code and its latest name."""
    return f"{task_code} · {names[task_code]}"


def show_kpis(store, history: pd.DataFrame) -> None:
    first, last = history.iloc[0], history.iloc[-1]
    calendar = store.latest.calendar(last["clndr_id"] if isinstance(last["clndr_id"], str) else None)
    has_two_finishes = len(history) > 1 and history["finish"].notna().all()
    slip = calendar.working_days(first["finish"], last["finish"]) if has_two_finishes else None
    ui.kpis(
        [
            ("Status", last["status"]),
            (
                "Forecast finish",
                f"{last['finish']:%d %b %Y}" if pd.notna(last["finish"]) else "—",
                None if slip is None else f"{slip:+.1f} wd since first",
                None,
                "inverse",
            ),
            ("Total float", "–" if pd.isna(last["total_float_d"]) else f"{last['total_float_d']:.1f} d"),
            ("% complete", "–" if pd.isna(last["pct_complete"]) else f"{last['pct_complete']:.0f} %"),
        ]
    )


def style_figure(fig: go.Figure, y_title: str, ink: dict) -> go.Figure:
    fig.update_layout(
        height=380,
        margin=dict(l=10, r=20, t=40, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.12, font=FONT),
        font=dict(color=ink["secondary"], **FONT),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(title="Data date", gridcolor=ink["grid"], tickfont=TICK)
    fig.update_yaxes(title=y_title, gridcolor=ink["grid"], tickfont=TICK)
    return fig


def line_trace(history: pd.DataFrame, column: str, name: str, colour: str, **options) -> go.Scatter:
    return go.Scatter(
        x=history["data_date"],
        y=history[column],
        name=name,
        mode="lines+markers",
        line=dict(color=colour, width=2),
        marker=dict(size=8),
        **options,
    )


def show_charts(history: pd.DataFrame) -> None:
    mode = "dark" if is_dark() else "light"
    ink, series_colours = INK[mode], SERIES[mode]
    dates_column, float_column = st.columns(2, gap="large")
    with dates_column:
        ui.section("Forecast start and finish")
        fig = go.Figure()
        fig.add_trace(line_trace(history, "start", "Start", series_colours[0]))
        fig.add_trace(line_trace(history, "finish", "Finish", series_colours[1]))
        st.plotly_chart(style_figure(fig, "Forecast date", ink), width="stretch")
    with float_column:
        ui.section("Total float (working days)")
        fig = go.Figure(
            line_trace(
                history, "total_float_d", "Total float", series_colours[0], hovertemplate="%{y} d<extra></extra>"
            )
        )
        fig.add_hline(
            y=0,
            line=dict(color=STATUS[mode]["critical"], width=1, dash="dot"),
            annotation_text="critical",
            annotation_position="bottom left",
        )
        st.plotly_chart(style_figure(fig, "Working days", ink), width="stretch")


store = require_store()
ui.header(
    "Activity history",
    store,
    store.latest,
    lead="Follow one activity through every loaded update: forecast dates, float and progress.",
)

all_history = store.history
names = all_history.drop_duplicates("task_code", keep="last").set_index("task_code")["task_name"]
choice = st.selectbox("Activity", names.index, format_func=partial(activity_label, names))
history = all_history[all_history["task_code"] == choice].sort_values("data_date")
if len(store) - len(history):
    st.caption(f"Present in {len(history)} of {len(store)} updates (added or deleted along the way).")

show_kpis(store, history)
show_charts(history)

ui.section("By update")
ui.table(history, columns=LIST_COLUMNS)
