"""Trend charts: S-curve, performance indices, milestone trend, PPC, metric history.

Colours follow the reference data-viz palette: categorical slots in fixed order (an
entity keeps its colour whatever the filter), one y-axis per chart, 1.5 px lines, >= 8 px
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
# browser applies live (app/style.css only fades the grid). STATUS is reserved for
# meaning (critical / warning / pass / complete / info, and the check statuses in app/ui.py)
# and never decorates; SERIES is the categorical palette for lines and keeps clear of those
# hues: azure, copper, teal, brass, orchid, violet. Order checked with the data-viz palette
# validator, light (#ffffff) and dark (#070b14) surfaces: adjacent pairs >= 8 CVD delta E
# (worst 12.6) and >= 15 normal-vision delta E (worst 16.0); the first three also all-pairs.
SERIES = ["#3478e6", "#d0652a", "#2f9e8f", "#a27f1f", "#c0509a", "#7c5ce6"]
STATUS = {"critical": "#c0392b", "warning": "#a15c00", "good": "#2e7d32", "complete": "#818e9f", "info": "#1d6a73"}
NEUTRAL = "#7b8794"  # reference lines: data date, reporting line, index 1.0
# Decoration (app/style.css, through CSS light-dark()), one per theme: the theme's linkColor.
ACCENT = {"light": "#1d6a73", "dark": "#6cc0c9"}
# The theme's textColor, for the hover text (app/ui.py: chart): Streamlit's Plotly theme fades it.
TEXT = {"light": "#1c1917", "dark": "#ece9e4"}
MIN_DATE_SPAN = pd.Timedelta(days=14)  # a date axis narrower than this is widened by DATE_PAD each side
DATE_PAD = pd.Timedelta(days=7)
LINE = 1.5  # data line width, px
# The theme's body font (app/.streamlit/config.toml, served from app/static/): the charts are
# drawn in the page, so the font the theme loads applies to them.
FONT_FAMILY = "Onest, sans-serif"
FONT = dict(size=13)
TICK = dict(size=12)
INDEX_ALERT = 0.95  # performance index below this is flagged (SPI, BEI, EV / AC)
PPC_TARGET = 80  # default PPC target, in percent
# Weekly updates are read to the day: no time in hovers, and zooming below one day keeps
# day labels instead of Plotly's hour and minute ticks. For date axes only.
DATE_AXIS = dict(hoverformat="%Y-%m-%d", tickformatstops=[dict(dtickrange=[None, 86_400_000], value="%d %b")])


def _with_house_style(figure: go.Figure, height: int = 380, y_title: str = "", legend: bool = True) -> go.Figure:
    """House style: 13 px text, legend on top, room on the right for end labels. Text, grid and
    axis colours come from the theme (st.plotly_chart's default theme="streamlit")."""
    figure.update_layout(
        height=height,
        margin=dict(l=10, r=110, t=56, b=10),
        showlegend=legend,
        legend=dict(orientation="h", yref="container", y=0.995, yanchor="top", x=0, font=FONT),
        hovermode="x unified",
        font=dict(family=FONT_FAMILY, **FONT),
        hoverlabel=dict(font=FONT, align="left"),
    )
    figure.update_xaxes(
        showspikes=True,
        spikethickness=1,
        spikedash="dot",
        tickfont=TICK,
        title_font=FONT,
        **DATE_AXIS,
    )
    figure.update_yaxes(title=y_title, tickfont=TICK, title_font=FONT)
    return figure


def _mark_data_date(figure: go.Figure, data_date) -> None:
    """A dashed vertical line at the status date, with its date above the plot."""
    if data_date is not None:
        figure.add_vline(x=data_date, line=dict(color=NEUTRAL, width=1.5, dash="dash"))
        figure.add_annotation(
            x=data_date,
            y=1,
            yref="paper",
            text=f"Status date {data_date:%Y-%m-%d}",
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            font=dict(size=12),
        )


def _add_end_label(figure: go.Figure, x, y, text: str) -> None:
    """A label right of the point (x, y), where a line ends. Text in the theme's colour (none
    given), so it follows a theme switch."""
    figure.add_annotation(x=x, y=y, text=text, showarrow=False, xanchor="left", xshift=6, font=dict(size=12))


def _as_number(value) -> float:
    """A number or a date as a number, to order and space labels along the y axis."""
    return float(pd.Timestamp(value).value) if isinstance(value, pd.Timestamp) else float(value)


def _add_end_labels(figure: go.Figure, ends: list[tuple], span: float) -> None:
    """End labels for several lines, ``ends`` = (x, y, text) with y numeric or Timestamp.

    Plotly does not move colliding annotations: labels of lines ending on the same point
    are merged into one, labels closer than 4 % of ``span`` (the y-axis span, same unit as
    y) are stacked 16 px apart upwards.
    """
    merged: dict[tuple, list[str]] = {}
    for x, y, text in ends:
        merged.setdefault((x, y), []).append(text)
    previous_value, shift_px = None, 0
    for (x, y), texts in sorted(merged.items(), key=lambda item: _as_number(item[0][1])):
        value = _as_number(y)
        too_close = previous_value is not None and value - previous_value < 0.04 * span
        shift_px = shift_px + 16 if too_close else 0
        figure.add_annotation(
            x=x,
            y=y,
            text=" · ".join(texts),
            showarrow=False,
            xanchor="left",
            xshift=6,
            yshift=shift_px,
            font=dict(size=12),
        )
        previous_value = value


# --- earned value -------------------------------------------------------------------------------


def build_scurve(
    curve: pd.DataFrame,
    series: pd.DataFrame,
    forecast: pd.DataFrame | None,
    data_date=None,
    percent: bool = False,
) -> go.Figure:
    """PV (baseline), EV and AC per update, forecast of hours to completion.

    At ``data_date`` a vertical mark joins that update's PV and EV, labelled SV = EV − PV in
    the chart's unit: green when EV >= PV (ahead), red when behind. PV there is the update's
    own (``series.pv_hr``, as in the KPIs). ``curve`` and ``forecast`` hold the value at each
    instant (``pv_curve``, ``forecast_curve``): the PV curve passes through that mark.

    ``percent``: each update's EV, AC and SV over its own BAC (``series.bac_hr``, as the KPIs'
    ``ev_pct``); the PV and forecast curves over the BAC of the update at ``data_date`` (else the
    last), the update they are drawn for.
    """
    updates = series.dropna(subset=["data_date"])
    at_data_date = updates[updates["data_date"] == data_date] if data_date is not None else updates.iloc[0:0]
    bac_hr = float((at_data_date if len(at_data_date) else updates)["bac_hr"].iloc[-1]) if len(updates) else 0.0
    percent = bool(percent and bac_hr)
    # hours as they are, or as a share of the BAC: of the update drawn for the curves, of its own for each point
    curve_scale = (100 / bac_hr) if percent else 1.0
    update_scale = 100 / updates["bac_hr"].where(updates["bac_hr"] > 0) if percent else 1.0
    unit = "% of BAC" if percent else "labor hours"
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=curve["date"],
            y=curve["pv_cum_hr"] * curve_scale,
            mode="lines",
            name="PV (baseline)",
            line=dict(color=SERIES[0], width=LINE),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=updates["data_date"],
            y=updates["ev_hr"] * update_scale,
            mode="lines+markers",
            name="EV (earned)",
            line=dict(color=SERIES[1], width=LINE),
            marker=dict(size=8),
            customdata=(updates["sv_hr"] * update_scale).to_frame().to_numpy(),
            hovertemplate="%{y:,.1f}  (SV %{customdata[0]:+,.1f})",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=updates["data_date"],
            y=updates["ac_hr"] * update_scale,
            mode="lines+markers",
            name="AC (actual)",
            line=dict(color=SERIES[2], width=LINE),
            marker=dict(size=8, symbol="square"),
        )
    )
    if forecast is not None and len(forecast) > 1:
        figure.add_trace(
            go.Scatter(
                x=forecast["date"],
                y=forecast["fc_cum_hr"] * curve_scale,
                mode="lines",
                name="Forecast (AC + remaining)",
                line=dict(color=SERIES[2], width=LINE, dash="dash"),
            )
        )
        estimate_at_completion = forecast["fc_cum_hr"].iloc[-1] * curve_scale
        _add_end_label(figure, forecast["date"].iloc[-1], estimate_at_completion, f"EAC {estimate_at_completion:,.0f}")
    if len(curve):
        budget_at_completion = curve["pv_cum_hr"].iloc[-1] * curve_scale
        label = f"BAC {budget_at_completion:,.0f} · baseline tasks of this update"
        _add_end_label(figure, curve["date"].iloc[-1], budget_at_completion, label)
    if len(at_data_date):
        # drawn last, over the AC marker and the data-date line it shares x with
        _add_schedule_variance(figure, at_data_date, curve_scale, data_date, percent)
    _mark_data_date(figure, data_date)
    figure.update_traces(hovertemplate="%{y:,.1f}", selector=lambda trace: trace.name != "EV (earned)")
    return _with_house_style(figure, 500, unit)


def _add_schedule_variance(
    figure: go.Figure, at_data_date: pd.DataFrame, scale: float, data_date, percent: bool
) -> None:
    """A vertical mark from PV to EV at the data date, labelled SV = EV − PV: green when EV >= PV
    (ahead), red when behind. ``scale``: the update's values in the chart's unit."""
    planned, earned, variance = (float(at_data_date[column].iloc[-1]) * scale for column in ("pv_hr", "ev_hr", "sv_hr"))
    colour = STATUS["good"] if variance >= 0 else STATUS["critical"]
    figure.add_trace(
        go.Scatter(
            x=[data_date, data_date],
            y=[planned, earned],
            mode="lines+markers",
            name="SV (EV − PV)",
            line=dict(color=colour, width=3),
            marker=dict(symbol="line-ew-open", size=12, color=colour),
            showlegend=False,
            hoverinfo="skip",
        )
    )
    # above the mark's top end, left of the data date: clear of the curves, which rise to the right
    figure.add_annotation(
        x=data_date,
        y=max(planned, earned),
        text=f"SV {variance:+,.1f} % of BAC" if percent else f"SV {variance:+,.0f} h",
        showarrow=False,
        xanchor="right",
        yanchor="bottom",
        xshift=-6,
        yshift=4,
    )


def build_index_trend(series: pd.DataFrame, columns: dict[str, str]) -> go.Figure:
    """Performance indices per update on one ratio axis, 1.0 and the alert threshold marked."""
    figure = go.Figure()
    ends = []
    for i, (column, name) in enumerate(columns.items()):
        updates = series.dropna(subset=[column])
        digits = 3 if column in ("spi", "spi_cost") else 2  # SPI: 1.002 ahead of plan would read 1.00
        figure.add_trace(
            go.Scatter(
                x=updates["data_date"],
                y=updates[column],
                mode="lines+markers",
                name=name,
                line=dict(color=SERIES[i], width=LINE),
                marker=dict(size=8),
                hovertemplate=f"%{{y:.{digits}f}}",
            )
        )
        if len(updates):
            last_index = float(updates[column].iloc[-1])
            ends.append((updates["data_date"].iloc[-1], last_index, f"{name} {last_index:.{digits}f}"))
    drawn = [column for column in columns if series[column].notna().any()]
    highest = max((float(series[column].max()) for column in drawn), default=1.0)
    lowest = min((float(series[column].min()) for column in drawn), default=0.0)
    _add_end_labels(figure, ends, max(highest - lowest, 0.1))
    figure.add_hline(y=1.0, line=dict(color=NEUTRAL, width=1))
    figure.add_hline(
        y=INDEX_ALERT,
        line=dict(color=STATUS["critical"], width=1, dash="dot"),
        annotation_text=f"{INDEX_ALERT:g}",
        annotation_position="bottom left",
    )
    return _with_house_style(figure, 380, "index")


# --- milestones ---------------------------------------------------------------------------------


def build_mta(
    trend: pd.DataFrame,
    last_shift_wd: dict[str, float],
    order: list[str] | None = None,
    bounds: tuple[pd.Timestamp | None, pd.Timestamp | None] = (None, None),
) -> go.Figure:
    """Milestone trend analysis: forecast date (y) per reporting date (x), diagonal = today.

    Both axes run over the same dates on a 1:1 scale, so the reporting line (forecast = data
    date) is the 45° diagonal; below it is the past. The span is ``bounds`` (project start,
    project finish), widened to any update or forecast outside it so no point is cut; a
    missing bound comes from the points.

    Each line keeps its own series colour so milestones stay distinguishable: the colour of
    its position in ``order`` (the user's pick order, so the picker's tags can match), else
    of its position in ``trend``. The move in
    the last update (``last_shift_wd``, working days, `milestone_slips.last_week_wd`: negative =
    later) marks the last point and the end label: red later, green earlier, line colour unchanged.
    Lines with the same dates hide each other: the unified hover lists every line at a
    reporting date and their end labels merge.
    """
    figure = go.Figure()
    first_date, last_date = _mta_axis_span(trend, bounds)
    figure.add_trace(
        go.Scatter(
            x=[first_date, last_date, last_date],
            y=[first_date, last_date, first_date],
            fill="toself",
            fillcolor="rgba(123, 135, 148, 0.12)",  # NEUTRAL, faint: the past, below the reporting line
            line=dict(width=0),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[first_date, last_date],
            y=[first_date, last_date],
            mode="lines",
            name="Reporting line (forecast = status date)",
            line=dict(color=NEUTRAL, width=3),
            hoverinfo="skip",
        )
    )
    ends = []
    order = order or list(dict.fromkeys(trend["task_code"]))
    for code, rows in trend.groupby("task_code", sort=False):
        if rows["forecast"].isna().all():
            continue
        line_colour = SERIES[order.index(code) % len(SERIES)]
        shift_wd = last_shift_wd.get(code, 0.0)
        # the colour of the last move: later is red, earlier green, none when the date did not move
        move_colour = STATUS["critical"] if shift_wd < 0 else STATUS["good"] if shift_wd > 0 else None
        drawn = rows.loc[: rows["forecast"].last_valid_index()]  # blank forecast = hidden update: the line breaks
        earlier_points = len(drawn) - 1
        figure.add_trace(
            go.Scatter(
                x=drawn["data_date"],
                y=drawn["forecast"].astype(object).where(drawn["forecast"].notna(), None),
                mode="lines+markers",
                name=f"{code} {drawn['task_name'].iloc[-1]}",
                line=dict(color=line_colour, width=LINE),
                marker=dict(
                    # the last point bigger when it moved: red / orange series stay apart
                    size=[9] * earlier_points + [13 if move_colour else 9],
                    symbol=["diamond" if is_complete else "circle" for is_complete in drawn["is_complete"].to_numpy()],
                    color=[line_colour] * earlier_points + [move_colour or line_colour],
                ),
                hovertemplate=f"{code}: " + "%{y|%Y-%m-%d}<extra></extra>",
                cliponaxis=False,  # the first update's points sit on the left edge: drawn whole
            )
        )
        label = _mta_end_label(code, shift_wd, move_colour)
        ends.append((drawn["data_date"].iloc[-1], drawn["forecast"].iloc[-1], label))
    _add_end_labels(figure, ends, (last_date - first_date).value)
    figure = _with_house_style(figure, 760, "Forecast date")
    # same range and scale on both axes: the diagonal is at 45°, the plot square
    axis_range = [first_date, last_date]
    figure.update_xaxes(title="Reporting date (status date)", range=axis_range, constrain="domain")
    figure.update_yaxes(range=axis_range, scaleanchor="x", scaleratio=1, constrain="domain", **DATE_AXIS)
    return figure


def _mta_axis_span(
    trend: pd.DataFrame, bounds: tuple[pd.Timestamp | None, pd.Timestamp | None]
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last date of both axes: every update and forecast drawn, widened to the
    project's start and finish (``bounds``) when they are known."""
    dates = pd.concat([trend["data_date"], trend["forecast"]]).dropna()
    project_start, project_finish = bounds
    first_date = min(dates.min(), project_start) if project_start is not None else dates.min()
    last_date = max(dates.max(), project_finish) if project_finish is not None else dates.max()
    if last_date <= first_date:  # one date only: a day either side so the axes have a span
        return first_date - pd.Timedelta(days=1), last_date + pd.Timedelta(days=1)
    return first_date, last_date


def _mta_end_label(code: str, shift_wd: float, move_colour: str | None) -> str:
    """The milestone's code and its last move in working days, behind an arrow when it moved: up
    for later, down for earlier. The arrow carries the colour (a mark, 3:1 on both themes); the
    text keeps the theme's."""
    label = code + (format_shift(shift_wd) if shift_wd else "")
    if not move_colour:
        return label
    return f'<span style="color:{move_colour}">{"▲" if shift_wd < 0 else "▼"}</span> {label}'


# --- one activity / project finish across updates ------------------------------------------------


def _line(history: pd.DataFrame, column: str, name: str, colour: str, **options) -> go.Scatter:
    return go.Scatter(
        x=history["data_date"],
        y=history[column],
        name=name,
        mode="lines+markers",
        line=dict(color=colour, width=LINE),
        marker=dict(size=8),
        **options,
    )


def build_activity_dates(history: pd.DataFrame) -> go.Figure:
    """Forecast start and finish of one activity in every update."""
    figure = go.Figure([_line(history, "start", "Start", SERIES[0]), _line(history, "finish", "Finish", SERIES[1])])
    figure.update_xaxes(title="Status date")
    figure = _with_house_style(figure, 380, "Forecast date")
    figure.update_yaxes(**DATE_AXIS)
    low, high = history[["start", "finish"]].min().min(), history[["start", "finish"]].max().max()
    # dates that never move (a reached milestone): Plotly would zoom the axis down to milliseconds
    _widen_dates(figure.update_yaxes, low, high)
    return figure


def _widen_dates(update_axis, low, high) -> None:
    """A date axis of less than MIN_DATE_SPAN (one update, a date that never moves) gets DATE_PAD
    each side: zoomed to the hour, Plotly would repeat the same day label on every tick."""
    if pd.notna(low) and pd.notna(high) and high - low < MIN_DATE_SPAN:
        update_axis(range=[low - DATE_PAD, high + DATE_PAD])


def build_activity_float(history: pd.DataFrame) -> go.Figure:
    """Total float of one activity in every update, zero marked as critical."""
    figure = go.Figure(_line(history, "total_float_d", "Total float", SERIES[0], hovertemplate="%{y} d<extra></extra>"))
    figure.add_hline(
        y=0,
        line=dict(color=STATUS["critical"], width=1, dash="dot"),
        annotation_text="critical",
        annotation_position="bottom left",
    )
    figure.update_xaxes(title="Status date")
    return _with_house_style(figure, 380, "Working days")


def build_finish_trend(summary: pd.DataFrame) -> go.Figure:
    """Forecast project finish per weekly update: the single most-watched planning trend."""
    colour = SERIES[0]
    updates = summary.dropna(subset=["data_date", "forecast_finish"])
    shift_texts = updates["finish_shift_wd"].map(format_shift)
    figure = go.Figure(
        go.Scatter(
            x=updates["data_date"],
            y=updates["forecast_finish"],
            mode="lines+markers",
            line=dict(color=colour, width=LINE),
            marker=dict(size=8, color=colour),
            customdata=np.stack([updates["source"], shift_texts], axis=-1) if len(updates) else None,
            hovertemplate="Update %{x|%Y-%m-%d}<br>Forecast finish %{y|%Y-%m-%d}%{customdata[1]}"
            "<br>%{customdata[0]}<extra></extra>",
        )
    )
    figure.update_xaxes(title="Status date")
    figure = _with_house_style(figure, 380, "Forecast finish", legend=False)
    figure.update_yaxes(**DATE_AXIS)
    figure.update_layout(hovermode="closest", margin=dict(l=10, r=20, t=20, b=10))
    if len(updates):  # one update: both axes would zoom on a point
        _widen_dates(figure.update_xaxes, updates["data_date"].min(), updates["data_date"].max())
        _widen_dates(figure.update_yaxes, updates["forecast_finish"].min(), updates["forecast_finish"].max())
    return figure


def format_shift(shift_wd: float) -> str:
    """A move in working days as it follows a date or a code: " (+2.5 wd)"; nothing when unknown."""
    return "" if pd.isna(shift_wd) else f" ({round(shift_wd, 1):+g} wd)"


# --- PPC ---------------------------------------------------------------------------------------


def _ppc_text(percents, kept, committed) -> list[str]:
    """One text per week: "63% (5/8)", the commitments kept over those made; "no commitment" for a
    week with none."""
    return [
        f"{percent:.0f}% ({kept_count}/{committed_count})" if pd.notna(percent) else "no commitment"
        for percent, kept_count, committed_count in zip(percents, kept, committed, strict=True)
    ]


def _with_note(texts: list[str], notes: pd.Series) -> list[str]:
    """Each text followed, on a new line, by the note of its week when it has one."""
    return [text if not isinstance(note, str) else f"{text}<br>{note}" for text, note in zip(texts, notes, strict=True)]


def build_ppc(ppc: pd.DataFrame, target: float = PPC_TARGET) -> go.Figure:
    """Three lines: PPC Finish (finishes kept / committed, Last Planner), PPC Start and PPC W/W-1
    (starts and finishes together). The hover of a week gives the three with their counts: equal
    values draw one line over another.

    A week with a ``note`` (`ppc_series`: more than a week since the previous update, or
    Activity IDs changed since it) has open markers and the note at the end of its hover.
    A week with nothing committed has no point, a gap in the line (a point at 0 would read as
    0 % kept); its hover says "no commitment"."""
    weeks = ppc.copy()
    weeks["label"] = weeks["data_date"].dt.strftime("%Y-%m-%d")
    has_note = [isinstance(note, str) for note in weeks["note"]]
    figure = go.Figure()
    for column, kept, committed, name, colour in (
        ("ppc_finish", "finishes_kept", "finishes_committed", "PPC Finish", SERIES[0]),
        ("ppc_start", "starts_kept", "starts_committed", "PPC Start", SERIES[2]),
        ("ppc_week", "kept", "committed", "PPC W/W−1", SERIES[1]),
    ):
        texts = _ppc_text(weeks[column], weeks[kept], weeks[committed])
        figure.add_trace(
            go.Scatter(
                x=weeks["label"],
                y=weeks[column],
                mode="lines+markers",
                name=name,
                line=dict(color=colour, width=2),
                marker=dict(
                    symbol=["circle-open" if noted else "circle" for noted in has_note],
                    size=[11 if noted else 7 for noted in has_note],  # an open marker reads smaller
                    line=dict(width=2, color=colour),
                ),
                connectgaps=False,
                cliponaxis=False,  # a point at 0 % is drawn whole, not cut by the axis
                # the week's hover lists the three lines: the note once, under the last
                customdata=_with_note(texts, weeks["note"]) if column == "ppc_week" else texts,
                hovertemplate=name + " %{customdata}<extra></extra>",
            )
        )
    critical = STATUS["critical"]
    figure.add_hline(y=target, line=dict(color=critical, width=1, dash="dot"))
    # in the right margin: inside the plot it sits on the last point
    figure.add_annotation(
        x=1,
        xref="paper",
        y=target,
        text=f"target {target:g}%",
        showarrow=False,
        xanchor="left",
        xshift=6,
        font=dict(size=12),  # the theme's text colour; the dotted line beside it is red
    )
    figure = _with_house_style(figure, 400, "PPC (%)", legend=True)
    figure.update_yaxes(range=[0, 105])
    figure.update_xaxes(title="Week ending (status date)", showspikes=False, type="category")
    return figure


# --- metric history (schedule health) -----------------------------------------------------------


def build_metric_trend(
    history: pd.DataFrame, name: str, threshold: float | None, threshold_label: str, unit: str
) -> go.Figure:
    """One check of a standard in every update: its value, with what it found over what it
    checked in the hover, and its target as a dotted line."""
    figure = go.Figure(
        go.Scatter(
            x=history["data_date"],
            y=history["actual"],
            mode="lines+markers",
            name=name,
            line=dict(color=SERIES[0], width=LINE),
            marker=dict(size=8),
            customdata=history[["found", "total"]].astype("float").to_numpy(),
            hovertemplate="%{x|%Y-%m-%d}: %{y:.2f} (%{customdata[0]:.0f} / %{customdata[1]:.0f})<extra></extra>",
        )
    )
    if threshold is not None and unit != "pass/fail":
        figure.add_hline(
            y=threshold,
            line=dict(color=STATUS["critical"], width=1, dash="dot"),
            annotation_text=f"target {threshold_label}",
            annotation_position="top left",
        )
    figure = _with_house_style(figure, 360, unit, legend=False)
    figure.update_layout(hovermode="closest")
    return figure


def build_half_step(steps: pd.DataFrame) -> go.Figure:
    """Shift of the project finish at each step of a half-step reading (analysis/forensics.py).

    One bar per step after the as-scheduled row: working days lost (negative, critical colour) or
    gained (positive, good colour), the finish once the step is applied in the hover.
    """
    stepped = steps.iloc[1:]
    colours = [STATUS["critical"] if shift < 0 else STATUS["good"] for shift in stepped["shift_wd"].fillna(0)]
    finishes = stepped["finish"].map(lambda stamp: "–" if pd.isna(stamp) else f"{stamp:%Y-%m-%d}")
    figure = go.Figure(
        go.Bar(
            x=stepped["step"],
            y=stepped["shift_wd"],
            marker_color=colours,
            text=stepped["shift_wd"].map(format_shift),
            textposition="outside",
            customdata=np.stack([finishes, stepped["changes"]], axis=-1) if len(stepped) else None,
            hovertemplate="%{x}<br>Finish once applied %{customdata[0]}<br>%{customdata[1]} change(s)<extra></extra>",
        )
    )
    figure = _with_house_style(figure, 320, "Finish shift (wd)", legend=False)
    figure.add_hline(y=0, line_color=NEUTRAL, line_width=1)
    figure.update_layout(margin=dict(l=10, r=20, t=30, b=10))
    return figure


def build_slip_trend(series: pd.DataFrame) -> go.Figure:
    """Finish shown and finish before replanning per update (analysis/forensics.py ``half_step_series``).

    Two lines: the recalculated finish of each update, and where the previous update's plan lands
    with that update's progress alone. A gap between them, week after week, is the delay the
    replanning absorbs.
    """
    rows = series.dropna(subset=["data_date"])
    figure = go.Figure()
    for column, name, colour in (
        ("finish_before_replanning", "Finish before replanning", SERIES[1]),
        ("finish", "Finish shown", SERIES[0]),
    ):
        figure.add_trace(
            go.Scatter(
                x=rows["data_date"],
                y=rows[column],
                name=name,
                mode="lines+markers",
                line=dict(color=colour, width=LINE),
                marker=dict(size=8, color=colour),
                hovertemplate=f"Update %{{x|%Y-%m-%d}}<br>{name} %{{y|%Y-%m-%d}}<extra></extra>",
            )
        )
    figure.update_xaxes(title="Status date")
    figure = _with_house_style(figure, 380, "Finish")
    figure.update_yaxes(**DATE_AXIS)
    figure.update_layout(hovermode="x unified", margin=dict(l=10, r=20, t=20, b=10))
    if len(rows):
        _widen_dates(figure.update_xaxes, rows["data_date"].min(), rows["data_date"].max())
        both = pd.concat([rows["finish"], rows["finish_before_replanning"]]).dropna()
        if len(both):
            _widen_dates(figure.update_yaxes, both.min(), both.max())
    return figure
