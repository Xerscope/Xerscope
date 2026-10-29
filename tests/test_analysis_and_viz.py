"""Standards on the demo series: each deliberate finding of the generator must be found.

sample.py documents what it plants; these tests check the analysis finds exactly that,
independently of how the rules are written.
"""

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, health_history, run_metric
from xerscope.viz import build_finish_trend, build_gantt

STD = builtin_standards()


def run(store, i, metric_id, baseline=True):
    std = STD[metric_id.split("-")[0]]
    bl = Baseline.from_snapshot(store.first) if baseline else None
    return run_metric(std[metric_id], AnalysisContext(store[i], store, bl))


def flagged(r):
    return set(r.flagged["task_code"])


def test_planted_lead_open_end_and_missing_resources(store):
    assert run(store, 0, "DCMA-02").numerator == 1  # E1040 -> E1050 is FS -3 d
    assert "K5040" in flagged(run(store, 0, "DCMA-01"))  # no successor
    assert flagged(run(store, 0, "P6-11")) == {"E1050", "K5040"}


def test_planted_constraints(store):
    assert flagged(run(store, 0, "DCMA-05")) == {"X4050"}  # finish on or before: hard for DCMA
    assert flagged(run(store, 0, "P6-02")) == set()  # P6: only mandatory dates are hard
    assert flagged(run(store, 0, "P6-03")) == {"P2040", "X4050"}


def test_planted_high_duration(store):
    assert "P2030" in flagged(run(store, 0, "DCMA-08"))  # 60 days


def test_negative_float_appears_after_vendor_delay(store):
    before = run(store, 4, "DCMA-07")
    after = run(store, 5, "DCMA-07")
    assert before.numerator == 0 and after.numerator > 0 and after.status == "fail"


def test_invalid_actual_date_from_week_6(store):
    assert flagged(run(store, 5, "P6-10")) == set()
    assert flagged(run(store, 6, "P6-10")) == {"C3010"}


def test_baseline_execution(store):
    first = run(store, 0, "DCMA-14")
    assert first.status == "n/a"  # nothing due at the baseline date
    late = run(store, len(store) - 1, "DCMA-14")
    assert 0 < late.value < 1  # the slow activities finish after their baseline


def test_health_history_is_long_format(store):
    h = health_history(store, STD["DCMA"], Baseline.from_snapshot(store.first))
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


def test_finish_trend(store):
    fig = build_finish_trend(store.summary)
    assert len(fig.data[0].x) == len(store)
