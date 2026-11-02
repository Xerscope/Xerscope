"""Plotly Gantt for one snapshot, optionally overlaid on a comparison snapshot.

Encoding
- Bar colour = schedule status (critical / near critical / normal / complete), from the
  reserved status palette, always paired with a legend label.
- Hollow outline behind each bar = the same activity in the comparison snapshot
  (previous update or baseline), so slippage reads as the bar leaving its outline.
- Diamonds = milestones. Dashed vertical line = data date. Optional grey elbows = logic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ..config import DATE_FMT, DEFAULT_SETTINGS, Settings
from .charts import DATE_AXIS, FONT, INK, SERIES, STATUS, TICK

PALETTE = {
    mode: {
        "Critical": STATUS[mode]["critical"],
        "Near critical": STATUS[mode]["warning"],
        "Normal": SERIES[mode][0],
        "Complete": STATUS[mode]["complete"],
        "ink": INK[mode]["secondary"],
        "grid": INK[mode]["grid"],
        "link": INK[mode]["muted"],
    }
    for mode in ("light", "dark")
}
CATEGORY_ORDER = ["Critical", "Near critical", "Normal", "Complete"]
MIN_BAR_MS = 4 * 3600 * 1000  # keep 1-hour tasks visible
WEEK_MS = 7 * 86_400_000
WEEK_WINDOW = (pd.Timedelta(weeks=2), pd.Timedelta(weeks=10))  # week timescale: before / after the data date


def _bar_ms(frame: pd.DataFrame) -> pd.Series:
    """Bar length in milliseconds (a horizontal Bar on a date axis), never below MIN_BAR_MS."""
    return ((frame["finish"] - frame["start"]).dt.total_seconds() * 1000).clip(lower=MIN_BAR_MS)


def categorise(tasks: pd.DataFrame, settings: Settings = DEFAULT_SETTINGS) -> pd.Series:
    tf = tasks["total_float_d"]
    cat = np.select(
        [tasks["is_complete"], tasks["is_critical"], tf <= settings.near_critical_float_days],
        ["Complete", "Critical", "Near critical"],
        default="Normal",
    )
    return pd.Series(cat, index=tasks.index)


def _fmt(ts: pd.Series) -> pd.Series:
    return ts.dt.strftime(DATE_FMT).fillna("-")


LABEL_WIDTH = 42  # characters of a row's name before it is cut with "…"


def _truncate(text: str, width: int = LABEL_WIDTH) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def row_label(tasks: pd.DataFrame) -> pd.Series:
    return tasks["task_code"].astype(str) + "  " + tasks["task_name"].astype(str).map(_truncate)


def _finish_shift_text(tasks, compare, compare_label, snapshot):
    """Hover text of the finish shift vs the comparison, and the comparison's dates by task code."""
    shift_txt = pd.Series("", index=tasks.index)
    if compare is None or compare.empty:
        return shift_txt, None
    cmp = compare.set_index("task_code")[["start", "finish"]]
    cf = tasks["task_code"].map(cmp["finish"])
    if snapshot is not None:
        shift, unit = snapshot.working_days(tasks["clndr_id"], cf, tasks["finish"]), "wd"
    else:
        shift, unit = (tasks["finish"] - cf).dt.total_seconds() / 86400, "cal. d"
    shift_txt = np.where(
        shift.notna(),
        "<br>Finish vs "
        + compare_label
        + ": "
        + shift.round(1).map(("{:+g} " + unit).format, na_action="ignore").astype(object),
        np.where(cf.isna(), "<br>Not in " + compare_label, ""),
    )
    return pd.Series(shift_txt, index=tasks.index), cmp


def build_gantt(
    tasks: pd.DataFrame,
    *,
    data_date: pd.Timestamp | None = None,
    compare: pd.DataFrame | None = None,
    compare_label: str = "Comparison",
    relationships: pd.DataFrame | None = None,
    show_links: bool = False,
    dark: bool = False,
    settings: Settings = DEFAULT_SETTINGS,
    summaries: pd.DataFrame | None = None,
    row_order: list[str] | None = None,
    snapshot=None,
    timescale: str = "month",
    span: tuple[pd.Timestamp, pd.Timestamp] | None = None,
) -> go.Figure:
    """Rows are drawn top to bottom in the order of ``tasks`` (sort before calling).

    ``timescale`` "month" shows the whole schedule with one tick per month; "week" ticks
    every Monday and shows the 12 weeks around the data date.
    ``span`` (start, finish) fixes the month timescale to a wider period than the rows
    shown, so the time axis stays put while the WBS is navigated level by level.

    ``summaries`` (columns row, start, finish, pct_complete, activities) adds WBS summary
    bars; ``row_order`` then orders them with the activity rows (see level_rows).
    ``snapshot`` (the Snapshot ``tasks`` come from) gives the finish shift in working days
    of each activity's calendar; without it the hover says calendar days.
    """
    pal = PALETTE["dark" if dark else "light"]
    t = tasks.copy()
    t["row"] = row_label(t)
    if "category" not in t.columns:  # the app page already categorised for its filter
        t["category"] = categorise(t, settings)
    rows = row_order or t["row"].tolist()

    shift_txt, cmp = _finish_shift_text(t, compare, compare_label, snapshot)

    tf = t["total_float_d"].round(1).astype(object).where(t["total_float_d"].notna(), "-")
    pct = t["pct_complete"].round(0).astype(object).where(t["pct_complete"].notna(), "-")
    t["_custom"] = list(
        zip(
            t["task_code"],
            t["task_name"],
            t["wbs_code"],
            _fmt(t["start"]),
            _fmt(t["finish"]),
            tf,
            pct,
            t["status"],
            shift_txt,
            strict=True,
        )
    )
    hover = (
        "<b>%{customdata[0]}</b> %{customdata[1]}<br>"
        "WBS: %{customdata[2]}<br>"
        "Start: %{customdata[3]}<br>Finish: %{customdata[4]}<br>"
        "Total float: %{customdata[5]} d · %{customdata[6]}% complete<br>"
        "Status: %{customdata[7]}%{customdata[8]}<extra></extra>"
    )

    fig = go.Figure()

    # 1) comparison outlines, drawn first so current bars sit on top
    if cmp is not None:
        c = t[["row", "task_code", "is_milestone"]].join(cmp, on="task_code")
        c = c[~c["is_milestone"] & c["start"].notna() & c["finish"].notna()]
        if not c.empty:
            dur = _bar_ms(c)
            fig.add_trace(
                go.Bar(
                    y=c["row"],
                    base=c["start"],
                    x=dur,
                    orientation="h",
                    width=0.8,
                    name=compare_label,
                    legendrank=10,
                    marker=dict(color="rgba(0,0,0,0)", line=dict(color=pal["ink"], width=1)),
                    hoverinfo="skip",
                )
            )

    # 2) current bars, one trace per category so the legend explains the colours
    bars = t[~t["is_milestone"] & t["start"].notna() & t["finish"].notna()]
    in_legend: set[str] = set()
    for i, cat in enumerate(CATEGORY_ORDER):
        b = bars[bars["category"] == cat]
        if b.empty:
            continue
        dur = _bar_ms(b)
        fig.add_trace(
            go.Bar(
                y=b["row"],
                base=b["start"],
                x=dur,
                orientation="h",
                width=0.55,
                name=cat,
                legendgroup=cat,
                legendrank=i,
                marker=dict(color=pal[cat], cornerradius=3),
                customdata=b["_custom"].tolist(),
                hovertemplate=hover,
            )
        )
        in_legend.add(cat)

    # 3) milestones: start milestones sit on start, finish milestones on finish
    ms = t[t["is_milestone"]].copy()
    if not ms.empty:
        ms["x"] = np.where(ms["is_start_milestone"], ms["start"], ms["finish"])
        ms["x"] = pd.to_datetime(ms["x"])
        for cat in CATEGORY_ORDER:
            m = ms[(ms["category"] == cat) & ms["x"].notna()]
            if m.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    y=m["row"],
                    x=m["x"],
                    mode="markers",
                    name=cat,
                    legendgroup=cat,
                    showlegend=cat not in in_legend,
                    legendrank=CATEGORY_ORDER.index(cat),
                    marker=dict(symbol="diamond", size=13, color=pal[cat], line=dict(color=pal["ink"], width=1)),
                    customdata=m["_custom"].tolist(),
                    hovertemplate=hover,
                )
            )
            in_legend.add(cat)

    # 3b) WBS summary bars: thin and dark, like P6's grouping bands
    if summaries is not None and not summaries.empty:
        sm = summaries.dropna(subset=["start", "finish"])
        dur = _bar_ms(sm)
        pct = sm["pct_complete"].round(0).astype(object).where(sm["pct_complete"].notna(), "-")
        fig.add_trace(
            go.Bar(
                y=sm["row"],
                base=sm["start"],
                x=dur,
                orientation="h",
                width=0.28,
                name="WBS summary",
                legendrank=9,
                marker=dict(color=pal["ink"]),
                customdata=list(
                    zip(
                        sm["row"].str.strip(), _fmt(sm["start"]), _fmt(sm["finish"]), pct, sm["activities"], strict=True
                    )
                ),
                hovertemplate="<b>%{customdata[0]}</b><br>Start: %{customdata[1]}<br>Finish: %{customdata[2]}"
                "<br>%{customdata[3]}% complete · %{customdata[4]} activities<extra></extra>",
            )
        )

    # 4) logic links as elbows: from the predecessor's driving end to the successor's driven end
    if show_links and relationships is not None and not relationships.empty:
        pos = t.set_index("task_code")[["row", "start", "finish"]]
        r = relationships[relationships["pred_code"].isin(pos.index) & relationships["succ_code"].isin(pos.index)]
        xs: list = []
        ys: list = []
        for pred, succ, typ in r[["pred_code", "succ_code", "type"]].itertuples(index=False):
            p, s = pos.loc[pred], pos.loc[succ]
            x0 = p["start"] if typ in ("SS", "SF") else p["finish"]
            x1 = s["finish"] if typ in ("FF", "SF") else s["start"]
            if pd.isna(x0) or pd.isna(x1):
                continue
            xs += [x0, x0, x1, None]
            ys += [p["row"], s["row"], s["row"], None]
        if xs:
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    name="Logic",
                    legendrank=11,
                    line=dict(color=pal["link"], width=1),
                    hoverinfo="skip",
                )
            )
            fig.data = (fig.data[-1],) + fig.data[:-1]  # links behind everything

    # 5) data date: a shape, labelled through a legend entry so it never collides with axis ticks
    if data_date is not None:
        dd_line = dict(color=pal["ink"], width=1.5, dash="dash")
        fig.add_shape(type="line", x0=data_date, x1=data_date, y0=0, y1=1, yref="paper", line=dd_line)
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                line=dd_line,
                legendrank=12,
                name=f"Data date {data_date:%Y-%m-%d}",
                hoverinfo="skip",
            )
        )

    fig.update_layout(
        barmode="overlay",
        height=min(max(240, 26 * len(rows) + 150), 4000),  # past ~150 rows: filter, or open a sub-WBS
        margin=dict(l=10, r=20, t=90, b=10),
        # legend pinned to the figure's top edge; the date axis sits between it and the bars
        legend=dict(orientation="h", yref="container", y=0.995, yanchor="top", x=0, xanchor="left", font=FONT),
        font=dict(color=pal["ink"], **FONT),
        hoverlabel=dict(align="left", font=FONT),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        bargap=0.2,
    )
    fig.update_xaxes(type="date", showgrid=True, gridcolor=pal["grid"], side="top", tickfont=TICK, **DATE_AXIS)
    if timescale == "week":
        window = None if data_date is None else [data_date - WEEK_WINDOW[0], data_date + WEEK_WINDOW[1]]
        fig.update_xaxes(dtick=WEEK_MS, tick0="2000-01-03", tickformat="%d %b", range=window)  # 2000-01-03: a Monday
    else:
        pad = pd.Timedelta(days=7)
        window = None if span is None or pd.isna(span[0]) else [span[0] - pad, span[1] + pad]
        fig.update_xaxes(dtick="M1", tickformat="%b %Y", range=window)
    summary_rows = set() if summaries is None or summaries.empty else set(summaries["row"])
    fig.update_yaxes(
        categoryorder="array",
        categoryarray=rows,
        autorange="reversed",
        showgrid=False,
        tickfont=dict(size=13),
        tickvals=rows,
        ticktext=[f"<b>{row}</b>" if row in summary_rows else row for row in rows],
    )
    # the view is navigated through the WBS, not by zooming: a drag must not change the axes
    fig.update_xaxes(fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    return fig


def level_rows(tasks: pd.DataFrame, nodes: pd.DataFrame) -> tuple[list[str], pd.DataFrame]:
    """Rows of one WBS level: the activities given, then one summary row per child node.

    ``nodes`` is analysis.wbs.rollup output restricted to the child nodes, in P6 order.
    """
    order = row_label(tasks.sort_values(["start", "task_code"])).tolist()
    summary_rows = [
        {
            "row": "▸ " + _truncate(n.label),
            "start": n.start,
            "finish": n.finish,
            "pct_complete": n.pct_complete,
            "activities": n.activities,
        }
        for n in nodes.itertuples()
    ]
    return order + [r["row"] for r in summary_rows], pd.DataFrame(summary_rows)
