"""Gantt grouped by WBS, as in P6's Activities view: a tree grid on the left, the
timeline on the right, one row each, WBS rows folding open and closed in the browser.

Python builds the rows (``gantt_rows``) and the data (``gantt_data``); ``gantt.js`` and
``gantt.css`` draw them as a Streamlit component (app/ui.py: GANTT). Encoding:
- Bar colour = float category (critical / near critical / normal / complete), legend shown.
- Hollow outline behind a bar = the same activity in the comparison snapshot (previous
  update or baseline), so slippage reads as the bar leaving its outline.
- Diamonds = milestones. Dark thin bar = WBS summary. Dashed vertical line = data date.

Schedule text (activity and WBS names come from the XER file) reaches the browser only as
the component's data, never in its markup, and the script writes it with the DOM property textContent.
Page colours and font follow the theme in the browser (gantt.css, --st-* variables).
"""

from __future__ import annotations

import math
from importlib.resources import files

import numpy as np
import pandas as pd

from ..analysis.wbs import ROOT
from ..config import DEFAULT_SETTINGS, Settings
from .charts import SERIES, STATUS

# Bar colours, the same on both themes (viz/charts.py: >= 3:1 on either background).
PALETTE = {
    "Critical": STATUS["critical"],
    "Near critical": STATUS["warning"],
    "Normal": SERIES[0],
    "Complete": STATUS["complete"],
}
CATEGORY_ORDER = ["Critical", "Near critical", "Normal", "Complete"]
ROW_PX = 26  # px per row; sent to the browser as rowPx, which gantt.js writes to --row for gantt.css
CHROME_PX = 96  # px of toolbar, legend, header (52) and borders around the rows; sent as chromePx
MIN_ROWS = 4  # rows the component is sized for at least: the "no activity" notice needs the room
WEEK_WINDOW = (pd.Timedelta(weeks=2), pd.Timedelta(weeks=10))  # week timescale: before / after the data date
SPAN_PAD = pd.Timedelta(days=7)  # month timescale: margin around the schedule
ISO_MINUTE = "%Y-%m-%dT%H:%M"  # the date text gantt.js reads: date and time to the minute

# The tree grid's columns after the name: (row key, header, kind). "number" is right-aligned as sent,
# "date" shows the day of the row's ISO_MINUTE text. A WBS row has no original or remaining duration.
GRID_COLUMNS = [("pct", "% complete", "number"), ("float_d", "Float (wd)", "number")]
ACTIVITIES_COLUMNS = [
    ("original_d", "Original (wd)", "number"),
    ("remaining_d", "Remaining (wd)", "number"),
    ("pct", "% complete", "number"),
    ("start", "Start", "date"),
    ("finish", "Finish", "date"),
    ("float_d", "Total float (wd)", "number"),
]


def categorise(tasks: pd.DataFrame, settings: Settings = DEFAULT_SETTINGS) -> pd.Series:
    """The category of each task, one of ``CATEGORY_ORDER``: complete first, then critical, then
    near critical (total float within ``settings.near_critical_float_days``), else normal."""
    total_float_d = tasks["total_float_d"]
    categories = np.select(
        [tasks["is_complete"], tasks["is_critical"], total_float_d <= settings.near_critical_float_days],
        ["Complete", "Critical", "Near critical"],
        default="Normal",
    )
    return pd.Series(categories, index=tasks.index)


def open_row_ids(
    rows: list[dict],
    nodes: pd.DataFrame,
    branch_ids: set[str],
    focus: str,
    picked_wbs_id: str | None = None,
    filtering: bool = False,
) -> set[str]:
    """The WBS rows drawn open (``"w:<wbs_id>"``): every WBS row of ``rows`` when a filter is on,
    so each match shows; otherwise the node in ``focus`` alone. With a picked activity, also the
    nodes from its own (``picked_wbs_id``) up to the top, those of the branch drawn: its row shows
    and is scrolled to."""
    open_ids = {row["id"] for row in rows if row["kind"] == "wbs"} if filtering else {f"w:{focus}"}
    if picked_wbs_id is not None:
        chain = nodes.loc[nodes["wbs_id"] == picked_wbs_id, "ancestors"]
        ancestors = chain.iloc[0] if len(chain) else []
        open_ids |= {f"w:{ancestor}" for ancestor in ancestors if ancestor in branch_ids}
    return open_ids


def _iso_text(value) -> str | None:
    """One date as ``ISO_MINUTE`` text, None when it is missing."""
    return None if value is None or pd.isna(value) else pd.Timestamp(value).strftime(ISO_MINUTE)


def _rounded_number(value, digits: int = 1) -> float | None:
    """One number rounded to ``digits`` decimals, None when it is missing or not finite."""
    return None if value is None or pd.isna(value) or not math.isfinite(float(value)) else round(float(value), digits)


# The column forms below are not ``_iso_text`` and ``_rounded_number`` mapped over a column:
# the pandas methods are faster on thousands of activities, and numpy rounds half-way values
# (2.675 to 2 decimals) differently from ``round``, so the rows would change.


def _iso_text_column(dates: pd.Series) -> list[str | None]:
    """A column of dates as ``ISO_MINUTE`` text, None where a date is missing."""
    text = dates.dt.strftime(ISO_MINUTE).tolist()
    return [value if isinstance(value, str) else None for value in text]  # NaT is not a string


def _rounded_number_column(values: pd.Series, digits: int = 1) -> list[float | None]:
    """A column of numbers rounded to ``digits`` decimals, None where one is missing or not finite."""
    rounded = pd.to_numeric(values, errors="coerce").astype(float).round(digits).tolist()
    return [value if math.isfinite(value) else None for value in rounded]  # NaN and inf are not JSON


def _compare_columns(activities: pd.DataFrame, compare: pd.DataFrame | None, snapshot) -> pd.DataFrame:
    """Comparison start / finish and the finish shift (working days of each activity's calendar):
    comparison finish minus finish, so an activity finishing later than the comparison reads negative."""
    if compare is None or compare.empty:
        return activities.assign(cmp_start=pd.NaT, cmp_finish=pd.NaT, shift_wd=np.nan)
    comparison = compare.drop_duplicates("task_code").set_index("task_code")[["start", "finish"]]
    activities = activities.assign(
        cmp_start=activities["task_code"].map(comparison["start"]),
        cmp_finish=activities["task_code"].map(comparison["finish"]),
    )
    if snapshot is None:
        return activities.assign(shift_wd=np.nan)
    # 0.0 - x, not -x: an activity that did not move stays 0.0 and never reads -0.0
    working_days = snapshot.working_days(activities["clndr_id"], activities["cmp_finish"], activities["finish"])
    return activities.assign(shift_wd=0.0 - working_days)


def _wbs_row(node, top: str, top_depth: int, shown: set[str]) -> dict:
    """The row of one WBS node (a roll-up row of ``analysis.wbs.rollup``) for the component."""
    parent = None if node.wbs_id == top else (node.parent if node.depth > 1 else ROOT)
    return {
        "id": f"w:{node.wbs_id}",
        "parent": f"w:{parent}" if parent in shown else None,
        "depth": int(node.depth) - top_depth,
        "kind": "wbs",
        "code": "" if node.wbs_id == ROOT else str(node.wbs_code),
        "name": str(node.label if node.wbs_id == ROOT else node.wbs_name),
        "start": _iso_text(node.start),
        "finish": _iso_text(node.finish),
        "pct": _rounded_number(node.pct_complete, 0),
        "float_d": _rounded_number(node.min_float_d),
        "shift_wd": _rounded_number(node.finish_variance_wd),
        "activities": int(node.activities),
    }


def _task_rows(activities: pd.DataFrame) -> list[dict]:
    """Activity rows, built column by column (one pass, not one pandas lookup per cell)."""
    milestone = [
        ("start" if start else "finish") if is_milestone else None
        for start, is_milestone in zip(activities["is_start_milestone"], activities["is_milestone"], strict=True)
    ]
    columns = {
        "id": ("a:" + activities["task_code"].astype(str)).tolist(),
        "parent": ("w:" + activities["node"].astype(str)).tolist(),
        "kind": ["task"] * len(activities),
        "code": activities["task_code"].astype(str).tolist(),
        "name": activities["task_name"].astype(str).tolist(),
        "start": _iso_text_column(activities["start"]),
        "finish": _iso_text_column(activities["finish"]),
        "cmp_start": _iso_text_column(activities["cmp_start"]),
        "cmp_finish": _iso_text_column(activities["cmp_finish"]),
        "category": activities["category"].tolist(),
        "milestone": milestone,
        "status": activities["status"].astype(str).tolist(),
        "pct": _rounded_number_column(activities["pct_complete"], 0),
        "float_d": _rounded_number_column(activities["total_float_d"]),
        "original_d": _rounded_number_column(activities["original_d"]),
        "remaining_d": _rounded_number_column(activities["remaining_d"]),
        "shift_wd": _rounded_number_column(activities["shift_wd"]),
    }
    return [dict(zip(columns, values, strict=True)) for values in zip(*columns.values(), strict=True)]


def _used_wbs_ids(wbs_ids, ancestors: pd.Series, shown: set[str]) -> set[str]:
    """The WBS nodes with an activity below them: each of ``wbs_ids`` and its ancestors in ``shown``."""
    used: set[str] = set()
    for wbs_id in wbs_ids:
        used |= {ancestor for ancestor in ancestors.get(wbs_id, [wbs_id]) if ancestor in shown}
    return used


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
    drawn = tasks.assign(node=tasks["wbs_id"].where(tasks["wbs_id"].isin(shown), top))
    drawn = _compare_columns(drawn, compare, snapshot).sort_values(["start", "task_code"], na_position="last")
    ancestors = nodes.set_index("wbs_id")["ancestors"]
    used = _used_wbs_ids(drawn["node"].unique(), ancestors, shown)
    by_node: dict[str, list[dict]] = {}
    for row, wbs_id in zip(_task_rows(drawn), drawn["node"], strict=True):
        by_node.setdefault(wbs_id, []).append(row)
    rows = []
    for node in nodes.itertuples():
        if not keep_empty and node.wbs_id not in used:
            continue
        rows.append(_wbs_row(node, top, top_depth, shown))
        depth = int(node.depth) - top_depth + 1
        for row in by_node.get(node.wbs_id, []):
            row["depth"] = depth
            rows.append(row)
    return rows


def _window(rows: list[dict], timescale: str, data_date, span) -> tuple[pd.Timestamp, pd.Timestamp]:
    if timescale == "week" and data_date is not None:
        return data_date - WEEK_WINDOW[0], data_date + WEEK_WINDOW[1]
    if span is not None and not pd.isna(span[0]):
        return span[0] - SPAN_PAD, span[1] + SPAN_PAD
    edges = []
    for row in rows:
        edges += [row["start"], row["finish"]]
    dates = pd.to_datetime([edge for edge in edges if edge])
    return (dates.min() - SPAN_PAD, dates.max() + SPAN_PAD) if len(dates) else (pd.Timestamp.now(),) * 2


def visible_rows(rows: list[dict], open_ids: set[str]) -> int:
    """How many rows the component draws with ``open_ids`` open (gantt.js: visibleRows)."""
    shown: set[str] = set()
    for row in rows:
        if row["parent"] is None or (row["parent"] in shown and row["parent"] in open_ids):
            shown.add(row["id"])
    return len(shown)


def fitted_height(rows: list[dict], open_ids: set[str], height: int) -> int:
    """``height`` at most, less when the rows drawn need less: no blank space under a short tree.
    Branches the viewer opens in the browser scroll inside."""
    return min(height, CHROME_PX + ROW_PX * max(MIN_ROWS, visible_rows(rows, open_ids)))


def _drawn_links(rows: list[dict], relationships: pd.DataFrame | None) -> list[list[str]]:
    """Return the logic links between two activities of ``rows``: [predecessor row id, successor row id, type]."""
    if relationships is None or relationships.empty:
        return []
    ids = {row["id"] for row in rows}
    pairs = relationships[["pred_code", "succ_code", "type"]].itertuples(index=False)
    return [
        [f"a:{predecessor}", f"a:{successor}", str(link_type)]
        for predecessor, successor, link_type in pairs
        if f"a:{predecessor}" in ids and f"a:{successor}" in ids
    ]


def gantt_data(
    rows: list[dict],
    *,
    relationships: pd.DataFrame | None = None,
    data_date: pd.Timestamp | None = None,
    span: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    timescale: str = "month",
    open_ids: set[str] | None = None,
    selected: str | None = None,
    compare_label: str = "",
    links: bool = False,
    height: int = 640,
    open_epoch: int = 0,
    columns: list[tuple[str, str, str]] | None = None,
    timeline: bool = True,
    level_bands: bool = False,
) -> dict:
    """The component's data: rows, links, window and options, all plain JSON values.

    ``height`` is the most the component takes (``maxHeight``); ``height`` itself is the
    first-paint estimate for the rows ``open_ids`` show, and the browser then sizes the
    component to the rows it draws, from ``rowPx`` and ``chromePx``. ``open_epoch`` changes
    when the page recomputes which branches are open: the browser then drops the ones it kept.
    ``open_ids`` are the row ids drawn open (default: the top row). ``span`` (start,
    finish) sets the month timescale; "week" shows WEEK_WINDOW around the data date.
    Logic links join the activities drawn, from the predecessor's driving end to the
    successor's driven end. ``columns`` are the grid's columns after the name (default
    ``GRID_COLUMNS``); ``timeline`` False draws the grid alone, the page's full width (the Tasks page);
    ``level_bands`` shades each WBS row by its level, as P6's Activities view colours its WBS bands.
    """
    link_rows = _drawn_links(rows, relationships) if links else []
    window = _window(rows, timescale, data_date, span)
    open_rows = open_ids if open_ids is not None else {row["id"] for row in rows[:1]}
    payload = {
        "rows": rows,
        "links": link_rows,
        "dataDate": _iso_text(data_date),
        "window": [_iso_text(window[0]), _iso_text(window[1])],
        "timescale": timescale,
        "palette": PALETTE,
        "categories": CATEGORY_ORDER,
        "open": sorted(open_rows),
        "selected": selected,
        "compareLabel": compare_label,
        "height": fitted_height(rows, set(open_rows), height),
        "maxHeight": height,
        "rowPx": ROW_PX,
        "chromePx": CHROME_PX,
        "openEpoch": open_epoch,
        "columns": [{"key": key, "label": label, "kind": kind} for key, label, kind in columns or GRID_COLUMNS],
        "timeline": timeline,
        "levelBands": level_bands,
    }
    return payload


def gantt_assets() -> dict[str, str]:
    """The component's markup, stylesheet and script (app/ui.py registers them once)."""
    assets = files(__package__)
    return {
        "html": '<div id="gantt"></div>',
        "css": assets.joinpath("gantt.css").read_text(encoding="utf-8"),
        "js": assets.joinpath("gantt.js").read_text(encoding="utf-8"),
    }
