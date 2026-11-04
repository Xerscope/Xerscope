"""Trend charts: S-curve, performance indices, milestone trend, PPC, metric history.

Colours follow the reference data-viz palette: categorical slots in fixed order (an
entity keeps its colour whatever the filter), one y-axis per chart, 2 px lines, >= 8 px
markers, recessive grid, legend + direct end labels for a few series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

# The app's colours, in one place. One set for both themes: every mark in SERIES and STATUS
# (except "info", used as a label background only) and NEUTRAL reaches 3:1 against the light
# and the dark page backgrounds (WCAG 2.2 SC 1.4.11), so a chart need not be redrawn when the
# viewer switches theme. Text, grid and axes are left to Streamlit's Plotly theme, which the
# browser applies live. STATUS is reserved for meaning (critical / warning / pass / complete /
# info, and the check statuses in app/ui.py) and never decorates; SERIES is the categorical
# palette for lines and keeps clear of those hues.
SERIES = ["#2a78d6", "#ea632e", "#19a070", "#be8100", "#e36092", "#6554d7"]
STATUS = {"critical": "#c0392b", "warning": "#a15c00", "good": "#2e7d32", "complete": "#818e9f", "info": "#1f4e79"}
NEUTRAL = "#7b8794"  # reference lines: data date, reporting line, index 1.0
ACCENT = "#0b7fa0"  # decoration (app/style.css)
# The theme's body font (app/.streamlit/config.toml, served from app/static/): the charts are
# drawn in the page, so the font the theme loads applies to them.
FONT_FAMILY = "IBM Plex Sans, sans-serif"
FONT = dict(size=13)
TICK = dict(size=12)
INDEX_ALERT = 0.95  # performance index below this is flagged (SPI, BEI, EV / AC)
PPC_TARGET = 80  # default PPC target, in percent
LABEL_FULL_MAX = 20  # PPC bars up to this many weeks carry "63% (5/8)"
LABEL_SHORT_MAX = 40  # up to this many weeks they carry "63%", beyond none
# Weekly updates are read to the day: no time in hovers, and zooming below one day keeps
# day labels instead of Plotly's hour and minute ticks. For date axes only.
DATE_AXIS = dict(hoverformat="%Y-%m-%d", tickformatstops=[dict(dtickrange=[None, 86_400_000], value="%d %b")])


def _layout(fig: go.Figure, height: int = 380, y_title: str = "", legend: bool = True) -> go.Figure:
    """House style: 13 px text, legend on top, room on the right for end labels. Text, grid and
    axis colours come from the theme (st.plotly_chart's default theme="streamlit")."""
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=110, t=56, b=10),
        showlegend=legend,
        legend=dict(orientation="h", yref="container", y=0.995, yanchor="top", x=0, font=FONT),
        hovermode="x unified",
        font=dict(family=FONT_FAMILY, **FONT),
        hoverlabel=dict(font=FONT, align="left"),
    )
    fig.update_xaxes(
        showspikes=True,
        spikethickness=1,
        spikedash="dot",
        tickfont=TICK,
        title_font=FONT,
        **DATE_AXIS,
    )
    fig.update_yaxes(title=y_title, tickfont=TICK, title_font=FONT)
    return fig


def _data_date(fig: go.Figure, when) -> None:
    if when is not None:
        fig.add_vline(x=when, line=dict(color=NEUTRAL, width=1.5, dash="dash"))
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


def _end_label(fig: go.Figure, x, y, text: str) -> None:
    """Text in the theme's colour (none given), so it follows a theme switch."""
    fig.add_annotation(x=x, y=y, text=text, showarrow=False, xanchor="left", xshift=6, font=dict(size=12))


def _as_number(y) -> float:
    return float(pd.Timestamp(y).value) if isinstance(y, pd.Timestamp) else float(y)


def _end_labels(fig: go.Figure, ends: list[tuple], span: float) -> None:
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
            font=dict(size=12),
        )
        last = value


# --- earned value -------------------------------------------------------------------------------


def build_scurve(
    curve: pd.DataFrame,
    series: pd.DataFrame,
    forecast: pd.DataFrame | None,
    data_date=None,
    percent: bool = False,
) -> go.Figure:
    """PV (baseline), EV and AC per update, forecast of hours to completion."""
    c = SERIES
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
        )
    if len(curve):
        _end_label(
            fig,
            curve["date"].iloc[-1],
            curve["pv_cum_hr"].iloc[-1] * k,
            f"BAC {curve['pv_cum_hr'].iloc[-1] * k:,.0f}",
        )
    _data_date(fig, data_date)
    fig.update_traces(hovertemplate="%{y:,.1f}")
    return _layout(fig, 500, unit)


def build_index_trend(series: pd.DataFrame, columns: dict[str, str]) -> go.Figure:
    """Performance indices per update on one ratio axis, 1.0 and the alert threshold marked."""
    c = SERIES
    fig = go.Figure()
    ends = []
    for i, (col, name) in enumerate(columns.items()):
        s = series.dropna(subset=[col])
        digits = 3 if col == "spi" else 2  # SPI: 1.002 ahead of plan would read 1.00
        fig.add_trace(
            go.Scatter(
                x=s["data_date"],
                y=s[col],
                mode="lines+markers",
                name=name,
                line=dict(color=c[i], width=2),
                marker=dict(size=8),
                hovertemplate=f"%{{y:.{digits}f}}",
            )
        )
        if len(s):
            y = float(s[col].iloc[-1])
            ends.append((s["data_date"].iloc[-1], y, f"{name} {y:.{digits}f}"))
    span = max((float(series[c].max()) for c in columns if series[c].notna().any()), default=1.0) - min(
        (float(series[c].min()) for c in columns if series[c].notna().any()), default=0.0
    )
    _end_labels(fig, ends, max(span, 0.1))
    fig.add_hline(y=1.0, line=dict(color=NEUTRAL, width=1))
    fig.add_hline(
        y=INDEX_ALERT,
        line=dict(color=STATUS["critical"], width=1, dash="dot"),
        annotation_text=f"{INDEX_ALERT:g}",
        annotation_position="bottom left",
    )
    return _layout(fig, 380, "index")


# --- milestones ---------------------------------------------------------------------------------


def build_mta(trend: pd.DataFrame, last_shift_wd: dict[str, float], order: list[str] | None = None) -> go.Figure:
    """Milestone trend analysis: forecast date (y) per reporting date (x), diagonal = today.

    The x axis runs over the updates, from the first data date, so they fill the page width;
    the y axis holds every forecast. The reporting line (forecast = data date) crosses the
    chart at the slope these ranges give; below it is the past.

    Each line keeps its own series colour so milestones stay distinguishable: the colour of
    its position in ``order`` (the user's pick order, so the picker's tags can match), else
    of its position in ``trend``. The move in
    the last update (``last_shift_wd``, working days, `milestone_slips.last_week_wd`) marks
    the last point and the end label: red later, green earlier, line colour unchanged.
    Lines with the same dates hide each other: the unified hover lists every line at a
    reporting date and their end labels merge.
    """
    status = STATUS
    series = SERIES
    fig = go.Figure()
    # x: the reporting dates, from the first update, a little room after the last for the end
    # labels; y: every forecast and the reporting line. No 1:1 scale, so the updates fill the
    # page width; the reporting line is still forecast = data date, at the slope that gives.
    x0, x1 = trend["data_date"].min(), trend["data_date"].max()
    x1 = x1 + max((x1 - x0) * 0.08, pd.Timedelta(days=3))
    lo, hi = min(x0, trend["forecast"].min()), max(x1, trend["forecast"].max())
    pad = max((hi - lo) * 0.05, pd.Timedelta(days=3))
    lo, hi = lo - pad, hi + pad
    fig.add_trace(
        go.Scatter(
            x=[x0, x1, x1, x0],
            y=[x0, x1, lo, lo],
            fill="toself",
            fillcolor="rgba(123, 135, 148, 0.12)",  # NEUTRAL, faint: the past, below the reporting line
            line=dict(width=0),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[x0, x1],
            y=[x0, x1],
            mode="lines",
            name="Reporting line (forecast = data date)",
            line=dict(color=NEUTRAL, width=3),
            hoverinfo="skip",
        )
    )
    ends = []
    order = order or list(dict.fromkeys(trend["task_code"]))
    for code, rows in trend.groupby("task_code", sort=False):
        if rows["forecast"].isna().all():
            continue
        color = series[order.index(code) % len(series)]
        shift = last_shift_wd.get(code, 0.0)
        moved = status["critical"] if shift > 0 else status["good"] if shift < 0 else None
        g = rows.loc[: rows["forecast"].last_valid_index()]  # blank forecast = hidden update: the line breaks
        done = g["is_complete"].to_numpy()
        fig.add_trace(
            go.Scatter(
                x=g["data_date"],
                y=g["forecast"].astype(object).where(g["forecast"].notna(), None),
                mode="lines+markers",
                name=f"{code} {g['task_name'].iloc[-1]}",
                line=dict(color=color, width=2),
                marker=dict(
                    size=[9] * (len(g) - 1) + [13 if moved else 9],  # bigger: red / orange series stay apart
                    symbol=["diamond" if d else "circle" for d in done],
                    color=[color] * (len(g) - 1) + [moved or color],
                ),
                hovertemplate=f"{code}: " + "%{y|%Y-%m-%d}<extra></extra>",
                cliponaxis=False,  # the first update's points sit on the left edge: drawn whole
            )
        )
        label = code + (format_shift(shift) if shift else "")
        if moved:  # the arrow carries the colour (a mark, 3:1 on both themes); the text keeps the theme's
            label = f'<span style="color:{moved}">{"▲" if shift > 0 else "▼"}</span> {label}'
        ends.append((g["data_date"].iloc[-1], g["forecast"].iloc[-1], label))
    _end_labels(fig, ends, (hi - lo).value)
    fig = _layout(fig, 640, "Forecast date")
    # ticks on the update dates, the first at x = 0, thinned to at most 12 labels
    dates = sorted(trend["data_date"].unique())
    fig.update_xaxes(
        title="Reporting date (data date)",
        range=[x0, x1],
        tickmode="array",
        tickvals=dates[:: -(-len(dates) // 12)],
        tickformat="%d %b",
    )
    fig.update_yaxes(range=[lo, hi], **DATE_AXIS)
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


def build_activity_dates(history: pd.DataFrame) -> go.Figure:
    """Forecast start and finish of one activity in every update."""
    colours = SERIES
    fig = go.Figure([_line(history, "start", "Start", colours[0]), _line(history, "finish", "Finish", colours[1])])
    fig.update_xaxes(title="Data date")
    fig = _layout(fig, 380, "Forecast date")
    fig.update_yaxes(**DATE_AXIS)
    low, high = history[["start", "finish"]].min().min(), history[["start", "finish"]].max().max()
    if pd.notna(low) and high - low < pd.Timedelta(days=14):
        # dates that never move (a reached milestone): Plotly would zoom the axis down to milliseconds
        fig.update_yaxes(range=[low - pd.Timedelta(days=7), high + pd.Timedelta(days=7)])
    return fig


def build_activity_float(history: pd.DataFrame) -> go.Figure:
    """Total float of one activity in every update, zero marked as critical."""
    fig = go.Figure(_line(history, "total_float_d", "Total float", SERIES[0], hovertemplate="%{y} d<extra></extra>"))
    fig.add_hline(
        y=0,
        line=dict(color=STATUS["critical"], width=1, dash="dot"),
        annotation_text="critical",
        annotation_position="bottom left",
    )
    fig.update_xaxes(title="Data date")
    return _layout(fig, 380, "Working days")


def build_finish_trend(summary: pd.DataFrame) -> go.Figure:
    """Forecast project finish per weekly update: the single most-watched planning trend."""
    colour = SERIES[0]
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
    fig = _layout(fig, 380, "Forecast finish", legend=False)
    fig.update_yaxes(**DATE_AXIS)
    fig.update_layout(hovermode="closest", margin=dict(l=10, r=20, t=20, b=10))
    return fig


def format_shift(shift_wd: float) -> str:
    return "" if pd.isna(shift_wd) else f" ({shift_wd:+g} wd)"


# --- PPC ---------------------------------------------------------------------------------------


def build_ppc(ppc: pd.DataFrame, target: float = PPC_TARGET) -> go.Figure:
    c = SERIES
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
    critical = STATUS["critical"]
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
        font=dict(size=12),  # the theme's text colour; the dotted line beside it is red
    )
    fig = _layout(fig, 400, "PPC (%)", legend=False)
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(range=[0, 115])
    fig.update_xaxes(title="Week ending (data date)", showspikes=False, type="category")
    return fig


# --- metric history (schedule health) -----------------------------------------------------------


def build_metric_trend(
    h: pd.DataFrame, name: str, threshold: float | None, threshold_label: str, unit: str
) -> go.Figure:
    c = SERIES
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
            line=dict(color=STATUS["critical"], width=1, dash="dot"),
            annotation_text=f"target {threshold_label}",
            annotation_position="top left",
        )
    fig = _layout(fig, 360, unit, legend=False)
    fig.update_layout(hovermode="closest")
    return fig
