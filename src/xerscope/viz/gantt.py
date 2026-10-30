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

from ..config import DEFAULT_SETTINGS, Settings
from .charts import FONT, INK, SERIES, STATUS, TICK

PALETTE = {
    mode: {
        "Critical": STATUS[mode]["critical"],
        "Near critical": STATUS[mode]["warning"],
        "Normal": SERIES[mode][0],
        "Complete": STATUS[mode]["complete"],
        "ghost": INK[mode]["secondary"],
        "ink": INK[mode]["secondary"],
        "grid": INK[mode]["grid"],
        "link": INK[mode]["axis"],
    }
    for mode in ("light", "dark")
}
CATEGORY_ORDER = ["Critical", "Near critical", "Normal", "Complete"]
MIN_BAR_MS = 4 * 3600 * 1000  # keep 1-hour tasks visible


def categorise(tasks: pd.DataFrame, settings: Settings = DEFAULT_SETTINGS) -> pd.Series:
    tf = tasks["total_float_d"]
    cat = np.select(
        [tasks["is_complete"], tasks["is_critical"], tf <= settings.near_critical_float_days],
        ["Complete", "Critical", "Near critical"],
        default="Normal",
    )
    return pd.Series(cat, index=tasks.index)


def _fmt(ts: pd.Series) -> pd.Series:
    return ts.dt.strftime("%Y-%m-%d %H:%M").fillna("-")


def row_label(tasks: pd.DataFrame, width: int = 42) -> pd.Series:
    name = tasks["task_name"].astype(str)
    name = name.where(name.str.len() <= width, name.str.slice(0, width - 1) + "…")
    return tasks["task_code"].astype(str) + "  " + name


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
) -> go.Figure:
    """Rows are drawn top to bottom in the order of ``tasks`` (sort before calling).

    ``summaries`` (columns row, start, finish, pct_complete, activities) adds WBS summary
    bars; ``row_order`` then interleaves them with the activity rows (see wbs_rows).
    ``snapshot`` (the Snapshot ``tasks`` come from) gives the finish shift in working days
    of each activity's calendar; without it the hover says calendar days.
    """
    pal = PALETTE["dark" if dark else "light"]
    t = tasks.copy()
    t["row"] = row_label(t)
    t["category"] = categorise(t, settings)
    rows = row_order or t["row"].tolist()

    # Finish shift vs comparison, for the hover text.
    shift_txt = pd.Series("", index=t.index)
    cmp = None
    if compare is not None and not compare.empty:
        cmp = compare.set_index("task_code")[["start", "finish"]]
        cf = t["task_code"].map(cmp["finish"])
        if snapshot is not None:
            shift, unit = snapshot.working_days(t["clndr_id"], cf, t["finish"]), "wd"
        else:
            shift, unit = (t["finish"] - cf).dt.total_seconds() / 86400, "cal. d"
        shift_txt = np.where(
            shift.notna(),
            "<br>Finish vs "
            + compare_label
            + ": "
            + shift.round(1).map(("{:+g} " + unit).format, na_action="ignore").astype(object),
            np.where(cf.isna(), "<br>Not in " + compare_label, ""),
        )
        shift_txt = pd.Series(shift_txt, index=t.index)

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
            dur = ((c["finish"] - c["start"]).dt.total_seconds() * 1000).clip(lower=MIN_BAR_MS)
            fig.add_trace(
                go.Bar(
                    y=c["row"],
                    base=c["start"],
                    x=dur,
                    orientation="h",
                    width=0.8,
                    name=compare_label,
                    legendrank=10,
                    marker=dict(color="rgba(0,0,0,0)", line=dict(color=pal["ghost"], width=1)),
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
        dur = ((b["finish"] - b["start"]).dt.total_seconds() * 1000).clip(lower=MIN_BAR_MS)
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
        dur = ((sm["finish"] - sm["start"]).dt.total_seconds() * 1000).clip(lower=MIN_BAR_MS)
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
        height=min(max(360, 26 * len(rows) + 150), 4000),  # past ~150 rows: filter, or zoom
        margin=dict(l=10, r=20, t=90, b=10),
        # legend pinned to the figure's top edge; the date axis sits between it and the bars
        legend=dict(orientation="h", yref="container", y=0.995, yanchor="top", x=0, xanchor="left", font=FONT),
        font=dict(color=pal["ink"], **FONT),
        hoverlabel=dict(align="left", font=FONT),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        bargap=0.2,
    )
    fig.update_xaxes(type="date", showgrid=True, gridcolor=pal["grid"], side="top", tickfont=TICK)
    fig.update_yaxes(
        categoryorder="array", categoryarray=rows, autorange="reversed", showgrid=False, tickfont=dict(size=13)
    )
    return fig


def build_finish_trend(summary: pd.DataFrame, dark: bool = False) -> go.Figure:
    """Forecast project finish per weekly update: the single most-watched planning trend."""
    pal = PALETTE["dark" if dark else "light"]
    s = summary.dropna(subset=["data_date", "forecast_finish"])
    shift = s["finish_shift_wd"].map(lambda v: "" if pd.isna(v) else f" ({v:+g} wd)")
    fig = go.Figure(
        go.Scatter(
            x=s["data_date"],
            y=s["forecast_finish"],
            mode="lines+markers",
            line=dict(color=pal["Normal"], width=2),
            marker=dict(size=8, color=pal["Normal"]),
            customdata=np.stack([s["source"], shift], axis=-1) if len(s) else None,
            hovertemplate="Update %{x|%Y-%m-%d}<br>Forecast finish %{y|%Y-%m-%d}%{customdata[1]}"
            "<br>%{customdata[0]}<extra></extra>",
        )
    )
    fig.update_layout(
        height=380,
        margin=dict(l=10, r=20, t=20, b=10),
        showlegend=False,
        font=dict(color=pal["ink"], **FONT),
        hoverlabel=dict(font=FONT),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(title="Data date", gridcolor=pal["grid"], tickfont=TICK)
    fig.update_yaxes(title="Forecast finish", gridcolor=pal["grid"], tickfont=TICK)
    return fig


def wbs_rows(tasks: pd.DataFrame, nodes: pd.DataFrame) -> tuple[list[str], pd.DataFrame]:
    """Row order grouping activities under their WBS node, plus the summary rows.

    ``nodes`` is analysis.wbs.rollup output restricted to the nodes to show (in order);
    each activity goes under the node it is assigned to.
    """
    t = tasks.copy()
    t["row"] = row_label(t)
    order: list[str] = []
    summary_rows = []
    by_node = {k: g.sort_values(["start", "task_code"])["row"].tolist() for k, g in t.groupby("wbs_id")}
    shown = set()
    for n in nodes.itertuples():
        # non-breaking spaces: Plotly keeps them, so the tree indentation survives
        label = "\u00a0" * 3 * max(n.depth - 1, 0) + "▾ " + n.label.strip()
        order.append(label)
        summary_rows.append(
            {
                "row": label,
                "start": n.start,
                "finish": n.finish,
                "pct_complete": n.pct_complete,
                "activities": n.activities,
            }
        )
        for r in by_node.get(n.wbs_id, []):
            order.append(r)
            shown.add(r)
    rest = [r for r in t.sort_values(["start", "task_code"])["row"] if r not in shown]
    return order + rest, pd.DataFrame(summary_rows)
