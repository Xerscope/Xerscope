"""Chart readability: labels that would print on top of each other, colours that would collide."""

import pandas as pd

from xerscope.viz import build_finish_trend, build_gantt
from xerscope.viz.charts import INK, build_activity_dates, build_mta, build_ppc


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
    fig = build_mta(_mta_frame({"M1": same, "K2": same}), ["M1", "K2"])
    labels = [a.text for a in fig.layout.annotations]
    assert labels == ["M1 · K2"]  # two labels on one point would print on top of each other
    assert fig.layout.hovermode == "x unified"  # hover lists both hidden lines


def test_mta_close_end_labels_are_pushed_apart():
    fig = build_mta(
        _mta_frame({"M1": ["2026-06-01"] * 3, "M2": ["2026-06-02"] * 3, "M3": ["2026-12-01"] * 3}), ["M1", "M2", "M3"]
    )
    shift = {a.text: a.yshift or 0 for a in fig.layout.annotations}
    assert shift["M1"] != shift["M2"]  # one day apart on a 6-month axis: same pixel row
    assert shift["M3"] == 0


def test_mta_picked_lines_never_share_a_colour():
    order = [f"A{i}" for i in range(12)]
    fig = build_mta(_mta_frame({"A0": ["2026-06-01"] * 3, "A6": ["2026-07-01"] * 3}), order)
    colours = [t.line.color for t in fig.data if t.name and t.name[0] == "A"]
    assert len(set(colours)) == 2  # slot 0 and slot 6 of a 6-colour palette would collide


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


def test_charts_show_dates_to_the_day(store):
    """Weekly reporting reads dates, not times: no hour in hovers or tick labels."""
    s = store.latest
    gantt = build_gantt(s.activities, data_date=s.data_date)
    starts = [row[3] for trace in gantt.data if trace.customdata is not None for row in trace.customdata]
    assert starts and all(len(start) == 10 for start in starts)  # 2026-11-16, no 08:00
    trend = build_finish_trend(store.summary)
    for fig in (gantt, trend):
        for axis in (fig.layout.xaxis, fig.layout.yaxis):
            if axis.type == "date" or fig is trend:
                assert axis.hoverformat == "%Y-%m-%d"
                assert all(stop.value != "%H:%M" for stop in axis.tickformatstops)
    assert gantt.layout.xaxis.tickformatstops[0].dtickrange[1] == 86_400_000  # below a day: day labels


def test_gantt_week_and_month_timescales(store):
    s = store.latest
    month = build_gantt(s.activities, data_date=s.data_date, timescale="month")
    assert month.layout.xaxis.dtick == "M1" and month.layout.xaxis.range is None  # whole project
    week = build_gantt(s.activities, data_date=s.data_date, timescale="week")
    assert week.layout.xaxis.dtick == 7 * 86_400_000
    low, high = (pd.Timestamp(x) for x in week.layout.xaxis.range)
    assert low <= s.data_date <= high and high - low == pd.Timedelta(weeks=12)


def test_gantt_logic_links_are_darker_than_the_grid(store):
    s = store.latest
    fig = build_gantt(s.activities, data_date=s.data_date, relationships=s.relationships, show_links=True)
    link = next(t for t in fig.data if t.name == "Logic")
    assert link.line.color == INK["light"]["muted"]  # the axis grey vanished on white
