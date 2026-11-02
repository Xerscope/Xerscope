"""Standards on the demo series: each deliberate finding of the generator must be found.

sample.py documents what it plants; these tests check the analysis finds exactly that,
independently of how the rules are written.
"""

import tomllib
from pathlib import Path

import pandas as pd
from rulekit import STANDARDS, codes, run_on_store

import xerscope
from xerscope.analysis import Baseline, health_history
from xerscope.app import ui
from xerscope.viz import build_finish_trend, build_gantt
from xerscope.viz.charts import ACCENT, build_activity_dates, build_activity_float
from xerscope.viz.gantt import MIN_BAR_MS


def test_planted_lead_open_end_and_missing_resources(store):
    assert run_on_store(store, 0, "DCMA-02").numerator == 1  # E1040 -> E1050 is FS -3 d
    assert "K5040" in codes(run_on_store(store, 0, "DCMA-01"))  # no successor
    assert codes(run_on_store(store, 0, "P6-11")) == ["E1050", "K5040"]


def test_planted_constraints(store):
    # X4050 is a finish milestone with finish-on-or-before: hard for DCMA, but PAM 200.1 4.0
    # excludes milestones from the analysis, so DCMA-05 no longer flags it (P6-03 below still does).
    assert codes(run_on_store(store, 0, "DCMA-05")) == []
    assert codes(run_on_store(store, 0, "P6-02")) == []  # P6: only mandatory dates are hard
    assert codes(run_on_store(store, 0, "P6-03")) == ["P2040", "X4050"]


def test_planted_high_duration(store):
    assert "P2030" in codes(run_on_store(store, 0, "DCMA-08"))  # 60 days


def test_negative_float_appears_after_vendor_delay(store):
    before = run_on_store(store, 4, "DCMA-07")
    after = run_on_store(store, 5, "DCMA-07")
    assert before.numerator == 0 and after.numerator > 0 and after.status == "fail"


def test_invalid_actual_date_from_week_6(store):
    assert codes(run_on_store(store, 5, "P6-10")) == []
    assert codes(run_on_store(store, 6, "P6-10")) == ["C3010"]


def test_baseline_execution(store):
    first = run_on_store(store, 0, "DCMA-14")
    assert first.status == "n/a"  # nothing due at the baseline date
    late = run_on_store(store, len(store) - 1, "DCMA-14")
    assert 0 < late.value < 1  # the slow activities finish after their baseline


def test_health_history_is_long_format(store):
    h = health_history(store, STANDARDS["DCMA"], Baseline.from_snapshot(store.first))
    assert len(h) == 14 * len(store)
    neg = h[h["id"] == "DCMA-07"].set_index("snapshot_idx")["found"]
    assert neg[4] == 0 and neg[5] > 0


def test_gantt_figure(store):
    s = store.latest
    fig = build_gantt(
        s.activities,
        data_date=s.data_date,
        compare=store.first.activities,
        relationships=s.relationships,
        show_links=True,
    )
    names = {t.name for t in fig.data}
    assert {"Critical", "Logic"} <= names
    assert any(n and n.startswith("Data date") for n in names)
    bars = [trace for trace in fig.data if trace.type == "bar"]
    assert bars
    assert all(min(trace.x) >= MIN_BAR_MS for trace in bars)  # one-hour tasks stay visible


def test_finish_trend(store):
    fig = build_finish_trend(store.summary)
    assert len(fig.data[0].x) == len(store)


def test_gantt_compare_with_no_common_tasks(store):
    """Comparison that shares no task code (another project): every finish shift is NaN and
    the hover text must still build (an all-NaN mapped Series is float64; str + float64 raises)."""
    s = store.latest
    other = store.first.activities.copy()
    other["task_code"] = "ZZ-" + other["task_code"].astype(str)
    fig = build_gantt(s.activities, data_date=s.data_date, compare=other, compare_label="other")
    assert fig.data


def test_activity_charts_follow_the_history(store):
    code = store.latest.activities["task_code"].iloc[0]
    history = store.history
    history = history[history["task_code"] == code].sort_values("data_date")
    dates, float_chart = build_activity_dates(history), build_activity_float(history)
    assert [trace.name for trace in dates.data] == ["Start", "Finish"]
    assert [trace.name for trace in float_chart.data] == ["Total float"]
    assert len(float_chart.data[0].x) == len(history)
    assert float_chart.layout.yaxis.title.text == "Working days"


def test_fmt_date_shows_a_dash_for_missing_dates():
    assert ui.fmt_date(pd.Timestamp("2026-11-02")) == "02 Nov 2026"
    assert ui.fmt_date(pd.NaT) == "–"
    assert ui.fmt_date(None, "—") == "—"
    assert ui.stamp(pd.Timestamp("2026-11-02")) == "2026-11-02"


def test_chart_accent_is_the_streamlit_theme_colour():
    config = Path(xerscope.__file__).parent / "app" / ".streamlit" / "config.toml"
    theme = tomllib.loads(config.read_text(encoding="utf-8"))["theme"]
    assert theme["primaryColor"].lower() == ACCENT.lower()
