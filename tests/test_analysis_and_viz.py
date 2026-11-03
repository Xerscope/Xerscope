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
from xerscope.analysis.wbs import rollup
from xerscope.app import ui
from xerscope.viz import categorise, gantt_html, gantt_rows
from xerscope.viz.charts import ACCENT, build_activity_dates, build_activity_float


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
    assert len(h) == 14 * len(store)  # DCMA 14-Point
    neg = h[h["id"] == "DCMA-07"].set_index("snapshot_idx")["found"]
    assert neg[4] == 0 and neg[5] > 0


def test_gantt_rows_on_the_demo_series(store):
    s = store.latest
    tasks = s.activities.assign(category=categorise(s.activities))
    rows = gantt_rows(tasks, rollup(s), compare=store.first.activities, snapshot=s)
    drawn = [r["code"] for r in rows if r["kind"] == "task"]
    assert sorted(drawn) == sorted(s.activities["task_code"])  # every activity once
    assert rows[0]["id"] == "w:__project__" and rows[0]["depth"] == 0
    assert {r["category"] for r in rows if r["kind"] == "task"} >= {"Critical", "Complete"}
    assert "Critical" in gantt_html(rows, relationships=s.relationships, data_date=s.data_date, links=True)


def test_gantt_compare_with_no_common_tasks(store):
    """Comparison sharing no task code (another project): no outline, no shift, rows still build."""
    s = store.latest
    other = store.first.activities.assign(task_code=lambda f: "ZZ-" + f["task_code"].astype(str))
    tasks = s.activities.assign(category=categorise(s.activities))
    rows = gantt_rows(tasks, rollup(s), compare=other, snapshot=s)
    assert all(r["cmp_finish"] is None and r["shift_wd"] is None for r in rows if r["kind"] == "task")


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
