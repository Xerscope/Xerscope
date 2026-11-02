"""Trend charts: S-curve, performance indices, milestone trend, PPC, metric history.

Colours follow the reference data-viz palette: categorical slots in fixed order (an
entity keeps its colour whatever the filter), one y-axis per chart, 2 px lines, >= 8 px
markers, recessive grid, legend + direct end labels for a few series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

# The app's colours, in one place. ACCENT is the theme's primaryColor
# (app/.streamlit/config.toml). STATUS is reserved for meaning (critical / warning /
# pass / complete, and the check statuses in app/ui.py) and never decorates; SERIES is
# the categorical palette for lines and keeps clear of those hues.
ACCENT = "#1f4e79"
SERIES = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"],
}
STATUS = {
    "light": {"critical": "#c0392b", "warning": "#b26a00", "good": "#2e7d32", "complete": "#9aa5b1"},
    "dark": {"critical": "#d03b3b", "warning": "#fab219", "good": "#0ca30c", "complete": "#898781"},
}
INK = {
    "light": {"primary": "#1f2933", "secondary": "#3e4c59", "muted": "#7b8794", "grid": "#e6e9ee", "axis": "#c9d0d8"},
    "dark": {"primary": "#f0efec", "secondary": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835"},
}


def _mode(dark: bool) -> str:
    return "dark" if dark else "light"


FONT = dict(size=13)
TICK = dict(size=12)
INDEX_ALERT = 0.95  # performance index below this is flagged (SPI, BEI, EV / AC)
PPC_TARGET = 80  # default PPC target, in percent
LABEL_FULL_MAX = 20  # PPC bars up to this many weeks carry "63% (5/8)"
LABEL_SHORT_MAX = 40  # up to this many weeks they carry "63%", beyond none
# Weekly updates are read to the day: no time in hovers, and zooming below one day keeps
# day labels instead of Plotly's hour and minute ticks. For date axes only.
DATE_AXIS = dict(hoverformat="%Y-%m-%d", tickformatstops=[dict(dtickrange=[None, 86_400_000], value="%d %b")])


def _layout(fig: go.Figure, dark: bool, height: int = 380, y_title: str = "", legend: bool = True) -> go.Figure:
    """House style: 13 px text, recessive grid, legend on top, room on the right for end labels."""
    ink = INK[_mode(dark)]
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=110, t=56, b=10),
        showlegend=legend,
        legend=dict(orientation="h", yref="container", y=0.995, yanchor="top", x=0, font=FONT),
        hovermode="x unified",
        font=dict(color=ink["secondary"], **FONT),
        hoverlabel=dict(font=FONT, align="left"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(
        gridcolor=ink["grid"],
        linecolor=ink["axis"],
        showspikes=True,
        spikecolor=ink["muted"],
        spikethickness=1,
        spikedash="dot",
        tickfont=TICK,
        title_font=FONT,
        **DATE_AXIS,
    )
    fig.update_yaxes(
        title=y_title,
        gridcolor=ink["grid"],
        linecolor=ink["axis"],
        zerolinecolor=ink["axis"],
        tickfont=TICK,
        title_font=FONT,
    )
    return fig


def _data_date(fig: go.Figure, when, dark: bool) -> None:
    if when is not None:
        fig.add_vline(x=when, line=dict(color=INK[_mode(dark)]["secondary"], width=1.5, dash="dash"))
        fig.add_annotation(
            x=when,
            y=1,
            yref="paper",
            text=f"Data date {when:%Y-%m-%d}",
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            font=dict(size=12),
        )


def _end_label(fig: go.Figure, x, y, text: str, color: str) -> None:
    fig.add_annotation(x=x, y=y, text=text, showarrow=False, xanchor="left", xshift=6, font=dict(size=12, color=color))


def _as_number(y) -> float:
    return float(pd.Timestamp(y).value) if isinstance(y, pd.Timestamp) else float(y)


def _end_labels(fig: go.Figure, ends: list[tuple], span: float, color: str) -> None:
    """End labels for several lines, ``ends`` = (x, y, text) with y numeric or Timestamp.

    Plotly does not move colliding annotations: labels of lines ending on the same point
    are merged into one, labels closer than 4 % of ``span`` (the y-axis span, same unit as
    y) are stacked 16 px apart upwards.
    """
    merged: dict[tuple, list[str]] = {}
    for x, y, text in ends:
        merged.setdefault((x, y), []).append(text)
    last, shift = None, 0
    for (x, y), texts in sorted(merged.items(), key=lambda item: _as_number(item[0][1])):
        value = _as_number(y)
        shift = shift + 16 if last is not None and value - last < 0.04 * span else 0
        fig.add_annotation(
            x=x,
            y=y,
            text=" · ".join(texts),
            showarrow=False,
            xanchor="left",
            xshift=6,
            yshift=shift,
            font=dict(size=12, color=color),
        )
        last = value


# --- earned value -------------------------------------------------------------------------------


def build_scurve(
    curve: pd.DataFrame,
    series: pd.DataFrame,
    forecast: pd.DataFrame | None,
    data_date=None,
    percent: bool = False,
    dark: bool = False,
) -> go.Figure:
    """PV (baseline), EV and AC per update, forecast of hours to completion."""
    c = SERIES[_mode(dark)]
    bac = float(series["bac_hr"].iloc[0]) if len(series) else 0.0
    k = (100 / bac) if (percent and bac) else 1.0
    unit = "% of BAC" if percent and bac else "labour hours"
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=curve["date"],
            y=curve["pv_cum_hr"] * k,
            mode="lines",
            name="PV (baseline)",
            line=dict(color=c[0], width=2),
        )
    )
    s = series.dropna(subset=["data_date"])
    fig.add_trace(
        go.Scatter(
            x=s["data_date"],
            y=s["ev_hr"] * k,
            mode="lines+markers",
            name="EV (earned)",
            line=dict(color=c[1], width=2),
            marker=dict(size=8),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=s["data_date"],
            y=s["ac_hr"] * k,
            mode="lines+markers",
            name="AC (actual)",
            line=dict(color=c[2], width=2),
            marker=dict(size=8, symbol="square"),
        )
    )
    if forecast is not None and len(forecast) > 1:
        fig.add_trace(
            go.Scatter(
                x=forecast["date"],
                y=forecast["fc_cum_hr"] * k,
                mode="lines",
                name="Forecast (AC + remaining)",
                line=dict(color=c[2], width=2, dash="dash"),
            )
        )
        _end_label(
            fig,
            forecast["date"].iloc[-1],
            forecast["fc_cum_hr"].iloc[-1] * k,
            f"EAC {forecast['fc_cum_hr'].iloc[-1] * k:,.0f}",
            INK[_mode(dark)]["secondary"],
        )
    if len(curve):
        _end_label(
            fig,
            curve["date"].iloc[-1],
            curve["pv_cum_hr"].iloc[-1] * k,
            f"BAC {curve['pv_cum_hr'].iloc[-1] * k:,.0f}",
            INK[_mode(dark)]["secondary"],
        )
    _data_date(fig, data_date, dark)
    fig.update_traces(hovertemplate="%{y:,.1f}")
    return _layout(fig, dark, 500, unit)


def build_index_trend(series: pd.DataFrame, columns: dict[str, str], dark: bool = False) -> go.Figure:
    """Performance indices per update on one ratio axis, 1.0 and the alert threshold marked."""
    c = SERIES[_mode(dark)]
    ink = INK[_mode(dark)]
    fig = go.Figure()
    ends = []
    for i, (col, name) in enumerate(columns.items()):
        s = series.dropna(subset=[col])
        fig.add_trace(
            go.Scatter(
                x=s["data_date"],
                y=s[col],
                mode="lines+markers",
                name=name,
                line=dict(color=c[i], width=2),
                marker=dict(size=8),
                hovertemplate="%{y:.2f}",
            )
        )
        if len(s):
            y = float(s[col].iloc[-1])
            ends.append((s["data_date"].iloc[-1], y, f"{name} {y:.2f}"))
    span = max((float(series[c].max()) for c in columns if series[c].notna().any()), default=1.0) - min(
        (float(series[c].min()) for c in columns if series[c].notna().any()), default=0.0
    )
    _end_labels(fig, ends, max(span, 0.1), ink["secondary"])
    fig.add_hline(y=1.0, line=dict(color=ink["muted"], width=1))
    fig.add_hline(
        y=INDEX_ALERT,
        line=dict(color=STATUS[_mode(dark)]["critical"], width=1, dash="dot"),
        annotation_text=f"{INDEX_ALERT:g}",
        annotation_position="bottom left",
    )
    return _layout(fig, dark, 380, "index")


# --- milestones ---------------------------------------------------------------------------------


def build_mta(trend: pd.DataFrame, colour_order: list[str], dark: bool = False) -> go.Figure:
    """Milestone trend analysis: forecast date (y) per reporting date (x), diagonal = today.

    Colours follow ``colour_order`` among the plotted lines only, so up to len(SERIES)
    lines never share a colour; a line keeps its colour while the lines before it in
    ``colour_order`` stay picked. Lines with the same dates hide each other: the unified
    hover lists every line at a reporting date and their end labels merge.
    """
    c = SERIES[_mode(dark)]
    ink = INK[_mode(dark)]
    fig = go.Figure()
    lo = min(trend["data_date"].min(), trend["forecast"].min())
    hi = max(trend["data_date"].max(), trend["forecast"].max())
    fig.add_trace(
        go.Scatter(
            x=[lo, hi],
            y=[lo, hi],
            mode="lines",
            name="Reporting date = forecast",
            line=dict(color=ink["muted"], width=1, dash="dot"),
            hoverinfo="skip",
        )
    )
    ranked = sorted((code for code in trend["task_code"].unique() if code in colour_order), key=colour_order.index)
    ends = []
    for code, g in trend.groupby("task_code", sort=False):
        color = c[ranked.index(code) % len(c)] if code in ranked else ink["muted"]
        done = g["is_complete"].to_numpy()
        fig.add_trace(
            go.Scatter(
                x=g["data_date"],
                y=g["forecast"],
                mode="lines+markers",
                name=f"{code} {g['task_name'].iloc[-1]}",
                line=dict(color=color, width=2),
                marker=dict(size=9, symbol=["diamond" if d else "circle" for d in done]),
                hovertemplate=f"{code}: " + "%{y|%Y-%m-%d}<extra></extra>",
            )
        )
        ends.append((g["data_date"].iloc[-1], g["forecast"].iloc[-1], code))
    pad = pd.Timedelta(days=10)
    _end_labels(fig, ends, (trend["forecast"].max() - trend["forecast"].min() + 4 * pad).value, ink["secondary"])
    fig = _layout(fig, dark, 540, "Forecast date")
    fig.update_xaxes(
        title="Reporting date (data date)", range=[trend["data_date"].min() - pad, trend["data_date"].max() + 3 * pad]
    )
    fig.update_yaxes(range=[trend["forecast"].min() - 2 * pad, trend["forecast"].max() + 2 * pad], **DATE_AXIS)
    return fig


# --- one activity / project finish across updates ------------------------------------------------


def _line(history: pd.DataFrame, column: str, name: str, colour: str, **options) -> go.Scatter:
    return go.Scatter(
        x=history["data_date"],
        y=history[column],
        name=name,
        mode="lines+markers",
        line=dict(color=colour, width=2),
        marker=dict(size=8),
        **options,
    )


def build_activity_dates(history: pd.DataFrame, dark: bool = False) -> go.Figure:
    """Forecast start and finish of one activity in every update."""
    colours = SERIES[_mode(dark)]
    fig = go.Figure([_line(history, "start", "Start", colours[0]), _line(history, "finish", "Finish", colours[1])])
    fig.update_xaxes(title="Data date")
    fig = _layout(fig, dark, 380, "Forecast date")
    fig.update_yaxes(**DATE_AXIS)
    low, high = history[["start", "finish"]].min().min(), history[["start", "finish"]].max().max()
    if pd.notna(low) and high - low < pd.Timedelta(days=14):
        # dates that never move (a reached milestone): Plotly would zoom the axis down to milliseconds
        fig.update_yaxes(range=[low - pd.Timedelta(days=7), high + pd.Timedelta(days=7)])
    return fig


def build_activity_float(history: pd.DataFrame, dark: bool = False) -> go.Figure:
    """Total float of one activity in every update, zero marked as critical."""
    fig = go.Figure(
        _line(history, "total_float_d", "Total float", SERIES[_mode(dark)][0], hovertemplate="%{y} d<extra></extra>")
    )
    fig.add_hline(
        y=0,
        line=dict(color=STATUS[_mode(dark)]["critical"], width=1, dash="dot"),
        annotation_text="critical",
        annotation_position="bottom left",
    )
    fig.update_xaxes(title="Data date")
    return _layout(fig, dark, 380, "Working days")


def build_finish_trend(summary: pd.DataFrame, dark: bool = False) -> go.Figure:
    """Forecast project finish per weekly update: the single most-watched planning trend."""
    colour = SERIES[_mode(dark)][0]
    updates = summary.dropna(subset=["data_date", "forecast_finish"])
    shift = updates["finish_shift_wd"].map(format_shift)
    fig = go.Figure(
        go.Scatter(
            x=updates["data_date"],
            y=updates["forecast_finish"],
            mode="lines+markers",
            line=dict(color=colour, width=2),
            marker=dict(size=8, color=colour),
            customdata=np.stack([updates["source"], shift], axis=-1) if len(updates) else None,
            hovertemplate="Update %{x|%Y-%m-%d}<br>Forecast finish %{y|%Y-%m-%d}%{customdata[1]}"
            "<br>%{customdata[0]}<extra></extra>",
        )
    )
    fig.update_xaxes(title="Data date")
    fig = _layout(fig, dark, 380, "Forecast finish", legend=False)
    fig.update_yaxes(**DATE_AXIS)
    fig.update_layout(hovermode="closest", margin=dict(l=10, r=20, t=20, b=10))
    return fig


def format_shift(shift_wd: float) -> str:
    return "" if pd.isna(shift_wd) else f" ({shift_wd:+g} wd)"


# --- PPC ---------------------------------------------------------------------------------------


def build_ppc(ppc: pd.DataFrame, target: float = PPC_TARGET, dark: bool = False) -> go.Figure:
    c = SERIES[_mode(dark)]
    p = ppc.copy()
    p["label"] = p["data_date"].dt.strftime("%Y-%m-%d")
    text = [
        f"{v:.0f}% ({d}/{n})" if pd.notna(v) else "no commitment"
        for v, d, n in zip(p["ppc"], p["completed"], p["committed"], strict=True)
    ]
    # bar labels shrink with the number of weeks (full ones overlap past LABEL_FULL_MAX bars;
    # the hover keeps the counts)
    weeks = len(p)
    short = ["" if weeks > LABEL_SHORT_MAX else f"{v:.0f}%" if pd.notna(v) else "-" for v in p["ppc"]]
    fig = go.Figure(
        go.Bar(
            x=p["label"],
            y=p["ppc"].fillna(0),
            text=text if weeks <= LABEL_FULL_MAX else short,
            customdata=text,
            textposition="outside",
            cliponaxis=False,
            marker=dict(color=c[0], cornerradius=4),
            width=0.6,
            name="PPC",
            hovertemplate="Week to %{x}: %{customdata}<extra></extra>",
        )
    )
    critical = STATUS[_mode(dark)]["critical"]
    fig.add_hline(y=target, line=dict(color=critical, width=1, dash="dot"))
    # in the right margin: inside the plot it sits on the last bar
    fig.add_annotation(
        x=1,
        xref="paper",
        y=target,
        text=f"target {target:g}%",
        showarrow=False,
        xanchor="left",
        xshift=6,
        font=dict(size=12, color=critical),
    )
    fig = _layout(fig, dark, 400, "PPC (%)", legend=False)
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(range=[0, 115])
    fig.update_xaxes(title="Week ending (data date)", showspikes=False, type="category")
    return fig


# --- metric history (schedule health) -----------------------------------------------------------


def build_metric_trend(
    h: pd.DataFrame, name: str, threshold: float | None, threshold_label: str, unit: str, dark: bool = False
) -> go.Figure:
    c = SERIES[_mode(dark)]
    fig = go.Figure(
        go.Scatter(
            x=h["data_date"],
            y=h["actual"],
            mode="lines+markers",
            name=name,
            line=dict(color=c[0], width=2),
            marker=dict(size=8),
            customdata=h[["found", "total"]].astype("float").to_numpy(),
            hovertemplate="%{x|%Y-%m-%d}: %{y:.2f} (%{customdata[0]:.0f} / %{customdata[1]:.0f})<extra></extra>",
        )
    )
    if threshold is not None and unit != "pass/fail":
        fig.add_hline(
            y=threshold,
            line=dict(color=STATUS[_mode(dark)]["critical"], width=1, dash="dot"),
            annotation_text=f"target {threshold_label}",
            annotation_position="top left",
        )
    fig = _layout(fig, dark, 360, unit, legend=False)
    fig.update_layout(hovermode="closest")
    return fig
