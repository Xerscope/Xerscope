"""Gantt grouped by WBS, as in P6's Activities view: a tree grid on the left, the
timeline on the right, one row each, WBS rows folding open and closed in the browser.

Python builds the rows (``gantt_rows``) and the page (``gantt_html``); ``gantt.js`` and
``gantt.css`` draw them. Encoding:
- Bar colour = float category (critical / near critical / normal / complete), legend shown.
- Hollow outline behind a bar = the same activity in the comparison snapshot (previous
  update or baseline), so slippage reads as the bar leaving its outline.
- Diamonds = milestones. Dark thin bar = WBS summary. Dashed vertical line = data date.

The page is built from schedule text (activity and WBS names come from the XER file):
values reach the browser only as JSON data, the script writes them with ``textContent``,
and a Content-Security-Policy forbids any network request or external resource.
"""

from __future__ import annotations

import json
import math
from importlib.resources import files

import numpy as np
import pandas as pd

from ..analysis.wbs import ROOT
from ..config import DEFAULT_SETTINGS, Settings
from .charts import INK, SERIES, STATUS

PALETTE = {
    mode: {
        "Critical": STATUS[mode]["critical"],
        "Near critical": STATUS[mode]["warning"],
        "Normal": SERIES[mode][0],
        "Complete": STATUS[mode]["complete"],
        "ink": INK[mode]["primary"],
        "secondary": INK[mode]["secondary"],
        "muted": INK[mode]["muted"],
        "grid": INK[mode]["grid"],
        "axis": INK[mode]["axis"],
        "background": "#0e1117" if mode == "dark" else "#ffffff",
        "band": "#1a1d24" if mode == "dark" else "#f3f5f8",
    }
    for mode in ("light", "dark")
}
CATEGORY_ORDER = ["Critical", "Near critical", "Normal", "Complete"]
WEEK_WINDOW = (pd.Timedelta(weeks=2), pd.Timedelta(weeks=10))  # week timescale: before / after the data date
SPAN_PAD = pd.Timedelta(days=7)  # month timescale: margin around the schedule
CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'"


def categorise(tasks: pd.DataFrame, settings: Settings = DEFAULT_SETTINGS) -> pd.Series:
    tf = tasks["total_float_d"]
    cat = np.select(
        [tasks["is_complete"], tasks["is_critical"], tf <= settings.near_critical_float_days],
        ["Complete", "Critical", "Near critical"],
        default="Normal",
    )
    return pd.Series(cat, index=tasks.index)


def _iso(value) -> str | None:
    return None if value is None or pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%dT%H:%M")


def _number(value, digits: int = 1) -> float | None:
    return None if value is None or pd.isna(value) or not math.isfinite(float(value)) else round(float(value), digits)


def _compare_columns(t: pd.DataFrame, compare: pd.DataFrame | None, snapshot) -> pd.DataFrame:
    """Comparison start / finish and the finish shift (working days of each activity's calendar)."""
    if compare is None or compare.empty:
        return t.assign(cmp_start=pd.NaT, cmp_finish=pd.NaT, shift_wd=np.nan)
    cmp = compare.drop_duplicates("task_code").set_index("task_code")[["start", "finish"]]
    t = t.assign(cmp_start=t["task_code"].map(cmp["start"]), cmp_finish=t["task_code"].map(cmp["finish"]))
    shift = np.nan if snapshot is None else snapshot.working_days(t["clndr_id"], t["cmp_finish"], t["finish"])
    return t.assign(shift_wd=shift)


def _wbs_row(n, top: str, top_depth: int, shown: set[str]) -> dict:
    parent = None if n.wbs_id == top else (n.parent if n.depth > 1 else ROOT)
    return {
        "id": f"w:{n.wbs_id}",
        "parent": f"w:{parent}" if parent in shown else None,
        "depth": int(n.depth) - top_depth,
        "kind": "wbs",
        "code": "" if n.wbs_id == ROOT else str(n.wbs_code),
        "name": str(n.label if n.wbs_id == ROOT else n.wbs_name),
        "start": _iso(n.start),
        "finish": _iso(n.finish),
        "pct": _number(n.pct_complete, 0),
        "float_d": _number(n.min_float_d),
        "shift_wd": _number(n.finish_variance_wd),
        "activities": int(n.activities),
    }


def _iso_column(dates: pd.Series) -> list[str | None]:
    text = dates.dt.strftime("%Y-%m-%dT%H:%M").tolist()
    return [value if isinstance(value, str) else None for value in text]  # NaT -> None


def _number_column(values: pd.Series, digits: int = 1) -> list[float | None]:
    rounded = pd.to_numeric(values, errors="coerce").astype(float).round(digits).tolist()
    return [value if math.isfinite(value) else None for value in rounded]  # NaN, inf -> None


def _task_rows(t: pd.DataFrame) -> list[dict]:
    """Activity rows, built column by column (one pass, not one pandas lookup per cell)."""
    milestone = [
        ("start" if start else "finish") if is_milestone else None
        for start, is_milestone in zip(t["is_start_milestone"], t["is_milestone"], strict=True)
    ]
    columns = {
        "id": ("a:" + t["task_code"].astype(str)).tolist(),
        "parent": ("w:" + t["node"].astype(str)).tolist(),
        "kind": ["task"] * len(t),
        "code": t["task_code"].astype(str).tolist(),
        "name": t["task_name"].astype(str).tolist(),
        "start": _iso_column(t["start"]),
        "finish": _iso_column(t["finish"]),
        "cmp_start": _iso_column(t["cmp_start"]),
        "cmp_finish": _iso_column(t["cmp_finish"]),
        "category": t["category"].tolist(),
        "milestone": milestone,
        "status": t["status"].astype(str).tolist(),
        "pct": _number_column(t["pct_complete"], 0),
        "float_d": _number_column(t["total_float_d"]),
        "shift_wd": _number_column(t["shift_wd"]),
    }
    return [dict(zip(columns, values, strict=True)) for values in zip(*columns.values(), strict=True)]


def gantt_rows(
    tasks: pd.DataFrame,
    nodes: pd.DataFrame,
    *,
    compare: pd.DataFrame | None = None,
    snapshot=None,
    keep_empty: bool = True,
) -> list[dict]:
    """One row per WBS node, each followed by its own activities, in P6 order.

    ``nodes`` is analysis.wbs.rollup output for the branch to draw, its first row the
    branch's top node; ``tasks`` the activities to draw, with a ``category`` column.
    Activities on a node outside ``nodes`` go under the top node. ``keep_empty`` False
    drops WBS rows with no activity below them (a filter is on). WBS rows carry the
    roll-up of every activity below them, filtered or not, and the finish variance
    against the baseline; activity rows the finish shift against ``compare``.
    """
    shown = set(nodes["wbs_id"])
    top, top_depth = nodes["wbs_id"].iloc[0], int(nodes["depth"].iloc[0])
    t = tasks.assign(node=tasks["wbs_id"].where(tasks["wbs_id"].isin(shown), top))
    t = _compare_columns(t, compare, snapshot).sort_values(["start", "task_code"], na_position="last")
    ancestors = nodes.set_index("wbs_id")["ancestors"]
    used = {a for node in t["node"].unique() for a in ancestors.get(node, [node]) if a in shown}
    by_node: dict[str, list[dict]] = {}
    for row, node in zip(_task_rows(t), t["node"], strict=True):
        by_node.setdefault(node, []).append(row)
    rows = []
    for n in nodes.itertuples():
        if not keep_empty and n.wbs_id not in used:
            continue
        rows.append(_wbs_row(n, top, top_depth, shown))
        depth = int(n.depth) - top_depth + 1
        for row in by_node.get(n.wbs_id, []):
            row["depth"] = depth
            rows.append(row)
    return rows


def _safe_json(payload) -> str:
    """JSON that cannot close the <script> element it sits in."""
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    for raw, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), (" ", "\\u2028"), (" ", "\\u2029")):
        text = text.replace(raw, escaped)
    return text


def _window(rows: list[dict], timescale: str, data_date, span) -> tuple[pd.Timestamp, pd.Timestamp]:
    if timescale == "week" and data_date is not None:
        return data_date - WEEK_WINDOW[0], data_date + WEEK_WINDOW[1]
    if span is not None and not pd.isna(span[0]):
        return span[0] - SPAN_PAD, span[1] + SPAN_PAD
    dates = pd.to_datetime([d for r in rows for d in (r["start"], r["finish"]) if d])
    return (dates.min() - SPAN_PAD, dates.max() + SPAN_PAD) if len(dates) else (pd.Timestamp.now(),) * 2


def gantt_html(
    rows: list[dict],
    *,
    relationships: pd.DataFrame | None = None,
    data_date: pd.Timestamp | None = None,
    span: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    timescale: str = "month",
    dark: bool = False,
    open_ids: set[str] | None = None,
    selected: str | None = None,
    compare_label: str = "",
    links: bool = False,
    height: int = 640,
) -> str:
    """The component page: ``gantt.css``, ``gantt.js`` and the rows as JSON.

    ``open_ids`` are the row ids drawn open (default: the top row). ``span`` (start,
    finish) sets the month timescale; "week" shows WEEK_WINDOW around the data date.
    Logic links join the activities drawn, from the predecessor's driving end to the
    successor's driven end.
    """
    ids = {r["id"] for r in rows}
    link_rows = []
    if links and relationships is not None and not relationships.empty:
        pairs = relationships[["pred_code", "succ_code", "type"]].itertuples(index=False)
        link_rows = [[f"a:{p}", f"a:{s}", str(k)] for p, s, k in pairs if f"a:{p}" in ids and f"a:{s}" in ids]
    window = _window(rows, timescale, data_date, span)
    payload = {
        "rows": rows,
        "links": link_rows,
        "dataDate": _iso(data_date),
        "window": [_iso(window[0]), _iso(window[1])],
        "timescale": timescale,
        "palette": PALETTE["dark" if dark else "light"],
        "categories": CATEGORY_ORDER,
        "open": sorted(open_ids if open_ids is not None else {r["id"] for r in rows[:1]}),
        "selected": selected,
        "compareLabel": compare_label,
        "height": height,
    }
    assets = files(__package__)
    css = assets.joinpath("gantt.css").read_text(encoding="utf-8")
    js = assets.joinpath("gantt.js").read_text(encoding="utf-8")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
        f"<style>{css}</style></head><body><div id='gantt'></div>"
        f"<script>const DATA = {_safe_json(payload)};</script>"
        f"<script>{js}</script></body></html>"
    )
