"""One activity across every weekly update: how its dates, float and progress moved."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from xerscope.app import ui
from xerscope.app.state import is_dark, require_store
from xerscope.viz.charts import FONT, INK, SERIES, STATUS, TICK

store = require_store()
ui.header(
    "Activity history",
    store,
    store.latest,
    lead="Follow one activity through every loaded update: forecast dates, float and progress.",
)

hist = store.history
names = hist.drop_duplicates("task_code", keep="last").set_index("task_code")["task_name"]
choice = st.selectbox("Activity", names.index, format_func=lambda c: f"{c} · {names[c]}")
h = hist[hist["task_code"] == choice].sort_values("data_date")
if len(store) - len(h):
    st.caption(f"Present in {len(h)} of {len(store)} updates (added or deleted along the way).")

first, last = h.iloc[0], h.iloc[-1]
cal = store.latest.calendar(last["clndr_id"] if isinstance(last["clndr_id"], str) else None)
slip = cal.working_days(first["finish"], last["finish"]) if len(h) > 1 and h["finish"].notna().all() else None
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

mode = "dark" if is_dark() else "light"
ink, c = INK[mode], SERIES[mode]


def style(fig: go.Figure, y_title: str) -> go.Figure:
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


c1, c2 = st.columns(2, gap="large")
with c1:
    ui.section("Forecast start and finish")
    fig = go.Figure()
    fig.add_scatter(
        x=h["data_date"],
        y=h["start"],
        name="Start",
        mode="lines+markers",
        line=dict(color=c[0], width=2),
        marker=dict(size=8),
    )
    fig.add_scatter(
        x=h["data_date"],
        y=h["finish"],
        name="Finish",
        mode="lines+markers",
        line=dict(color=c[1], width=2),
        marker=dict(size=8),
    )
    st.plotly_chart(style(fig, "Forecast date"), width="stretch")
with c2:
    ui.section("Total float (working days)")
    fig = go.Figure(
        go.Scatter(
            x=h["data_date"],
            y=h["total_float_d"],
            mode="lines+markers",
            name="Total float",
            line=dict(color=c[0], width=2),
            marker=dict(size=8),
            hovertemplate="%{y} d<extra></extra>",
        )
    )
    fig.add_hline(
        y=0,
        line=dict(color=STATUS[mode]["critical"], width=1, dash="dot"),
        annotation_text="critical",
        annotation_position="bottom left",
    )
    st.plotly_chart(style(fig, "Working days"), width="stretch")

ui.section("By update")
ui.table(
    h,
    columns=[
        "data_date",
        "status",
        "start",
        "finish",
        "total_float_d",
        "remaining_d",
        "original_d",
        "pct_complete",
        "is_critical",
    ],
)
