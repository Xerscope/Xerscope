"""Chart readability: labels that would print on top of each other, colours that would collide."""

import pandas as pd

from xerscope.viz.charts import build_activity_dates, build_mta, build_ppc


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
