"""Chart readability: labels that would print on top of each other, colours that would collide."""

import json
import time
from pathlib import Path

import pandas as pd
import pytest
from xerkit import snap, todo

from xerscope.analysis.wbs import rollup
from xerscope.viz import build_finish_trend, categorise, gantt_assets, gantt_data, gantt_rows
from xerscope.viz import gantt as gantt_module
from xerscope.viz.charts import SERIES, STATUS, build_activity_dates, build_mta, build_ppc


def _mta_frame(lines: dict[str, list[str]]) -> pd.DataFrame:
    """MTA rows: one forecast per weekly data date for each milestone."""
    dates = pd.date_range("2026-03-02", periods=3, freq="7D")
    rows = [
        {"data_date": d, "task_code": code, "task_name": code, "forecast": pd.Timestamp(f), "is_complete": False}
        for code, forecasts in lines.items()
        for d, f in zip(dates, forecasts, strict=True)
    ]
    return pd.DataFrame(rows)


def test_mta_identical_lines_share_one_end_label():
    same = ["2026-06-01", "2026-06-05", "2026-06-10"]
    fig = build_mta(_mta_frame({"M1": same, "K2": same}), {})
    labels = [a.text for a in fig.layout.annotations]
    assert labels == ["M1 · K2"]  # two labels on one point would print on top of each other
    assert fig.layout.hovermode == "x unified"  # hover lists both hidden lines


def test_mta_close_end_labels_are_pushed_apart():
    fig = build_mta(_mta_frame({"M1": ["2026-06-01"] * 3, "M2": ["2026-06-02"] * 3, "M3": ["2026-12-01"] * 3}), {})
    shift = {a.text: a.yshift or 0 for a in fig.layout.annotations}
    assert shift["M1"] != shift["M2"]  # one day apart on a 6-month axis: same pixel row
    assert shift["M3"] == 0


def test_mta_x_axis_runs_over_the_updates_from_the_first_data_date():
    """The reporting dates fill the page width, from the first update: no 1:1 scale (the
    reporting line is still forecast = data date, at whatever slope), every forecast in view."""
    # updates on 2026-03-02..16, milestones forecast 5 and 9 months later
    trend = _mta_frame({"M1": ["2026-08-03"] * 3, "M2": ["2026-12-01"] * 3})
    fig = build_mta(trend, {})
    x_lo, x_hi = (pd.Timestamp(v) for v in fig.layout.xaxis.range)
    y_lo, y_hi = (pd.Timestamp(v) for v in fig.layout.yaxis.range)
    assert x_lo == trend["data_date"].min() and x_hi > trend["data_date"].max()
    assert x_hi - x_lo < pd.Timedelta(weeks=4)  # the update period, not the forecast span
    assert fig.layout.yaxis.scaleanchor is None
    assert y_lo <= x_lo and y_hi > pd.Timestamp("2026-12-01")  # the line's start and every forecast in view
    line = next(t for t in fig.data if t.name and t.name.startswith("Reporting line"))
    assert list(line.x) == list(line.y) and pd.Timestamp(line.x[0]) == x_lo and pd.Timestamp(line.x[-1]) == x_hi


def test_mta_lines_keep_their_own_colour_and_the_last_point_shows_the_move():
    lines = {"LATE": ["2026-06-01"] * 3, "EARLY": ["2026-07-01"] * 3, "SAME": ["2026-08-01"] * 3}
    fig = build_mta(_mta_frame(lines), {"LATE": 2.0, "EARLY": -1.5, "SAME": 0.0})
    traces = {t.name.split()[0]: t for t in fig.data if t.name and t.name.split()[0] in lines}
    red, green = STATUS["critical"], STATUS["good"]
    # one series colour per milestone, in order, so lines stay distinguishable
    assert [traces[code].line.color for code in lines] == SERIES[:3]
    # earlier points in the line colour, the last one red (later) / green (earlier) / unchanged
    assert list(traces["LATE"].marker.color) == [SERIES[0]] * 2 + [red]
    assert list(traces["EARLY"].marker.color) == [SERIES[1]] * 2 + [green]
    assert list(traces["SAME"].marker.color) == [SERIES[2]] * 3
    assert list(traces["LATE"].marker.size) == [9, 9, 13] and list(traces["SAME"].marker.size) == [9, 9, 9]
    texts = sorted(a.text for a in fig.layout.annotations)
    # the arrow carries the colour; the text keeps the theme's, so it follows a theme switch
    assert texts == sorted(
        [
            "SAME",
            f'<span style="color:{red}">▲</span> LATE (+2 wd)',
            f'<span style="color:{green}">▼</span> EARLY (-1.5 wd)',
        ]
    )


def test_mta_colour_follows_pick_order_even_with_a_line_missing():
    # picked C, A, B; A has no trend to plot: B and C keep the colours of their picker tags
    lines = {"B": ["2026-06-01"] * 3, "C": ["2026-07-01"] * 3}
    fig = build_mta(_mta_frame(lines), {}, order=["C", "A", "B"])
    colour = {t.name.split()[0]: t.line.color for t in fig.data if t.name and t.name.split()[0] in lines}
    assert colour == {"C": SERIES[0], "B": SERIES[2]}


@pytest.mark.parametrize(
    "fig",
    [
        build_mta(_mta_frame({"M1": ["2026-08-03"] * 3}), {"M1": 1.0}),
        build_ppc(pd.DataFrame({"data_date": pd.date_range("2026-03-02", periods=2, freq="7D"),
                                "ppc": [100.0, 50], "completed": [1, 1], "committed": [1, 2]}), 80),
    ],
)  # fmt: skip
def test_charts_leave_text_grid_and_axes_to_the_theme(fig):
    """Streamlit's Plotly theme colours text, grid and axes in the browser, live on a theme
    switch; a colour set here would stay the one of the theme the page was drawn with."""
    assert fig.layout.font.color is None and fig.layout.paper_bgcolor is None
    for axis in (fig.layout.xaxis, fig.layout.yaxis):
        assert axis.gridcolor is None and axis.linecolor is None and axis.zerolinecolor is None
    assert all(a.font.color is None for a in fig.layout.annotations)


def test_ppc_target_label_sits_outside_the_bars():
    ppc = pd.DataFrame(
        {
            "data_date": pd.date_range("2026-03-02", periods=3, freq="7D"),
            "ppc": [100.0, 50, 100],
            "completed": [1, 1, 1],
            "committed": [1, 2, 1],
        }
    )
    label = build_ppc(ppc, 80).layout.annotations[0]
    assert label.xref == "paper" and label.x >= 1  # in the right margin, not over the last bar


def test_activity_dates_axis_keeps_days_when_dates_never_move():
    day = pd.Timestamp("2026-08-31 08:00")
    history = pd.DataFrame(
        {"data_date": pd.date_range("2026-08-31", periods=3, freq="7D"), "start": day, "finish": day}
    )
    low, high = (pd.Timestamp(x) for x in build_activity_dates(history).layout.yaxis.range)
    assert (low, high) == (day - pd.Timedelta(days=7), day + pd.Timedelta(days=7))


def test_finish_trend_shows_dates_to_the_day(store):
    """Weekly reporting reads dates, not times: no hour in hovers or tick labels."""
    trend = build_finish_trend(store.summary)
    assert len(trend.data[0].x) == len(store)  # one point per update
    for axis in (trend.layout.xaxis, trend.layout.yaxis):
        assert axis.hoverformat == "%Y-%m-%d"
        assert axis.tickformatstops[0].dtickrange[1] == 86_400_000  # below a day: day labels


# --- WBS Gantt -------------------------------------------------------------------------------

WBS = [  # project W0 > E (W1) > D (W11), project > C (W2)
    {
        "wbs_id": "W0",
        "proj_id": "1",
        "parent_wbs_id": "",
        "proj_node_flag": "Y",
        "wbs_short_name": "T",
        "wbs_name": "Project",
        "seq_num": "0",
    },
    {
        "wbs_id": "W1",
        "proj_id": "1",
        "parent_wbs_id": "W0",
        "proj_node_flag": "N",
        "wbs_short_name": "E",
        "wbs_name": "Engineering",
        "seq_num": "1",
    },
    {
        "wbs_id": "W11",
        "proj_id": "1",
        "parent_wbs_id": "W1",
        "proj_node_flag": "N",
        "wbs_short_name": "D",
        "wbs_name": "Design",
        "seq_num": "1",
    },
    {
        "wbs_id": "W2",
        "proj_id": "1",
        "parent_wbs_id": "W0",
        "proj_node_flag": "N",
        "wbs_short_name": "C",
        "wbs_name": "Civil",
        "seq_num": "2",
    },
]


def _wbs_snapshot(**names):
    activities = [
        todo("B", wbs_id="W1", early_start_date="2026-03-09 08:00", early_end_date="2026-03-13 17:00"),
        todo("A", wbs_id="W11", early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00"),
        todo("C", wbs_id="W2", early_start_date="2026-03-02 08:00", early_end_date="2026-03-04 17:00"),
        todo("P", wbs_id="W0", early_start_date="2026-03-02 08:00", early_end_date="2026-03-02 17:00"),
    ]
    for row in activities:
        row["task_name"] = names.get(row["task_code"], row["task_code"])
    return snap(activities, [("A", "B", "FS", 0), ("B", "C", "FS", 0)], wbs=WBS)


def _rows(s, nodes=None, **kw):
    tasks = s.activities.assign(category=categorise(s.activities))
    return gantt_rows(tasks, rollup(s) if nodes is None else nodes, **kw)


def test_gantt_rows_follow_the_wbs_tree_in_p6_order():
    rows = _rows(_wbs_snapshot())
    assert [(r["id"], r["parent"], r["depth"]) for r in rows] == [
        ("w:__project__", None, 0),
        ("a:P", "w:__project__", 1),  # on the project node itself
        ("w:W1", "w:__project__", 1),
        ("a:B", "w:W1", 2),  # a node's own activities come before its child nodes
        ("w:W11", "w:W1", 2),
        ("a:A", "w:W11", 3),
        ("w:W2", "w:__project__", 1),
        ("a:C", "w:W2", 2),
    ]


def test_gantt_rows_of_one_branch_and_filtered():
    s = _wbs_snapshot()
    nodes = rollup(s)
    branch = nodes[nodes["wbs_id"].isin(["W1", "W11"])]
    in_branch = s.activities[s.activities["wbs_id"].isin(["W1", "W11"])]
    rows = gantt_rows(in_branch.assign(category=categorise(in_branch)), branch)
    assert [(r["id"], r["parent"], r["depth"]) for r in rows] == [
        ("w:W1", None, 0),  # the branch's top node is the root of the drawing
        ("a:B", "w:W1", 1),
        ("w:W11", "w:W1", 1),
        ("a:A", "w:W11", 2),
    ]
    only_c = s.activities[s.activities["task_code"] == "C"]
    filtered = gantt_rows(only_c.assign(category=categorise(only_c)), nodes, keep_empty=False)
    assert [r["id"] for r in filtered] == ["w:__project__", "w:W2", "a:C"]  # empty W1, W11 dropped


def test_gantt_rows_compare_dates_and_shift():
    s = _wbs_snapshot()
    earlier = s.activities.assign(finish=s.activities["finish"] - pd.Timedelta(days=1))
    row = next(r for r in _rows(s, compare=earlier, snapshot=s) if r["id"] == "a:B")
    assert row["cmp_finish"] == "2026-03-12T17:00" and row["finish"] == "2026-03-13T17:00"
    assert row["shift_wd"] == 1  # Thu 12 -> Fri 13 March, Mon-Fri calendar


def test_gantt_keeps_schedule_text_out_of_the_markup():
    hostile = "</script><img src=x onerror=alert(1)>"
    s = _wbs_snapshot(B=hostile)
    data = gantt_data(_rows(s), data_date=s.data_date)
    assert not [part for part in gantt_assets().values() if "<img" in part]  # markup, style, script: fixed text
    sent = json.dumps(data, allow_nan=False)  # what the browser receives: data only, written with textContent
    assert json.loads(sent)["rows"][3]["name"] == hostile


def test_gantt_script_never_parses_text_as_html_nor_calls_out():
    script = (Path(gantt_module.__file__).parent / "gantt.js").read_text(encoding="utf-8")
    for unsafe in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "Function(",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "sendBeacon",
        "import(",
    ):
        assert unsafe not in script


def test_gantt_timescales_and_links():
    s = _wbs_snapshot()
    rows = _rows(s)
    span = (pd.Timestamp("2026-03-02"), pd.Timestamp("2026-03-31"))
    month = gantt_data(rows, data_date=s.data_date, span=span)
    assert month["window"] == ["2026-02-23T00:00", "2026-04-07T00:00"]  # the span, 7 days each side
    week = gantt_data(rows, data_date=s.data_date, timescale="week")
    low, high = (pd.Timestamp(w) for w in week["window"])
    assert high - low == pd.Timedelta(weeks=12) and low < s.data_date < high
    assert gantt_data(rows, relationships=s.relationships)["links"] == []  # off unless asked
    linked = gantt_data(rows, relationships=s.relationships, links=True)["links"]
    assert linked == [["a:A", "a:B", "FS"], ["a:B", "a:C", "FS"]]
    no_c = [r for r in rows if r["id"] != "a:C"]
    assert gantt_data(no_c, relationships=s.relationships, links=True)["links"] == [["a:A", "a:B", "FS"]]


def test_gantt_rows_scale_to_a_large_schedule():
    """3,000 activities on 300 WBS nodes: rows are built in one pass, not one pandas lookup per cell
    (per-node sorting and itertuples took about 3 s here, and kept a real schedule loading)."""
    wbs = [WBS[0]] + [
        {
            "wbs_id": f"N{k}",
            "proj_id": "1",
            "parent_wbs_id": "W0",
            "proj_node_flag": "N",
            "wbs_short_name": f"N{k}",
            "wbs_name": f"Node {k}",
            "seq_num": str(k),
        }
        for k in range(300)
    ]
    tasks = [
        todo(f"A{k}", wbs_id=f"N{k % 300}", early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00")
        for k in range(3000)
    ]
    s = snap(tasks, wbs=wbs)
    started = time.perf_counter()
    rows = _rows(s, compare=s.activities, snapshot=s)
    assert time.perf_counter() - started < 2
    assert len(rows) == 1 + 300 + 3000
