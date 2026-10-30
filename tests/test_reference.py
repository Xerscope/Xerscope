"""xerscope against third-party XER files with stated results.

Fetch the pinned files once:  uv run python tests/reference/fetch.py
Without them these tests are skipped (with that instruction), never silently passed.
"""

import json
from pathlib import Path

import pandas as pd
import pytest
from conftest import mpxj_or_skip
from reference import expected as E
from reference.sources import FILES

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_metric
from xerscope.xer import build_snapshot, percent_complete, read_xer

DATA = Path(__file__).parent / "reference" / "data"
pytestmark = [
    pytest.mark.reference,
    pytest.mark.skipif(
        not all((DATA / n).exists() for n in FILES),
        reason="reference files missing: uv run python tests/reference/fetch.py",
    ),
]


def snap(name):
    return build_snapshot(read_xer(DATA / name))


def ts(v):
    return None if v is None or pd.isna(v) else pd.Timestamp(v).strftime("%Y-%m-%d %H:%M")


# --- MPXJ: real P6 exports ---------------------------------------------------------------


@pytest.mark.parametrize("name,setting", E.LAG_CALENDAR.items())
def test_lag_calendar_option(name, setting):
    assert snap(name).options["lag_calendar"] == setting


def test_percent_complete_matches_p6_export():
    t = snap(E.PERCENT_COMPLETE_FILE).activities.set_index("task_name")
    got = {name: t.loc[name, "pct_complete"] for name in E.PERCENT_COMPLETE}
    assert got == E.PERCENT_COMPLETE


def test_stale_scd_end_date_is_not_the_forecast():
    """Real P6 export: scd_end_date says 2020-12-30, the only activity finished 2019-06-12."""
    s = snap("mpxj/PredecessorCalendar.xer")
    assert ts(s.scheduled_finish) == "2020-12-30 08:00"
    assert ts(s.finish_date) == "2019-06-12 17:00"
    assert any("scd_end_date" in w for w in s.warnings)


@pytest.mark.parametrize("name", [n for n in FILES if n.endswith(".xer")])
def test_every_reference_file_loads_cleanly(name):
    s = snap(name)
    assert len(s.activities) > 0 and s.data_date is not None


# --- xerlock rules and sample ----------------------------------------------------------------


@pytest.mark.parametrize("row,pct", E.PERCENT_RULES)
def test_percent_complete_rules(row, pct):
    assert percent_complete(pd.DataFrame([row])).iloc[0] == pct


@pytest.fixture(scope="module")
def xl():
    return snap(E.XERLOCK_FILE), json.loads((DATA / E.XERLOCK_JSON).read_text(encoding="utf-8"))


def test_xerlock_project_totals(xl):
    s, _ = xl
    a = s.activities
    got = {
        "activities": len(a),
        "critical": int(a.is_critical.sum()),
        "longest_path": int(a.on_longest_path.sum()),
        "milestones": int(a.is_milestone.sum()),
        "complete": int(a.is_complete.sum()),
        "in_progress": int((a.is_started & ~a.is_complete).sum()),
        "not_started": int((~a.is_started).sum()),
        "pct_activities_complete": round(100 * a.is_complete.mean(), 1),
        "data_date": ts(s.data_date),
        "finish": ts(s.finish_date),
        "lag_calendar": s.options["lag_calendar"],
    }
    assert got == E.XERLOCK_PROJECT


FIELDS = [  # (xerscope column, xerlock key, kind)
    ("early_start_date", "early_start", "ts"),
    ("early_end_date", "early_end", "ts"),
    ("late_start_date", "late_start", "ts"),
    ("late_end_date", "late_end", "ts"),
    ("act_start_date", "act_start", "ts"),
    ("act_end_date", "act_end", "ts"),
    ("target_drtn_hr_cnt", "duration_hrs", "num"),
    ("remain_drtn_hr_cnt", "remain_duration_hrs", "num"),
    ("pct_complete", "pct_complete", "num"),
    ("is_critical", "is_critical", "bool"),
    ("on_longest_path", "is_longest_path", "bool"),
    ("status_code", "status", "str"),
]


def test_xerlock_every_activity_field(xl):
    s, ref = xl
    t = s.activities.set_index("task_code")
    diffs = []
    for a in ref["activities"]:
        o = t.loc[a["task_code"]]
        for col, key, kind in FIELDS:
            mine, theirs = o[col], a[key]
            if kind == "ts":
                mine, theirs = ts(mine), ts(theirs)
            elif kind == "num":
                mine = None if pd.isna(mine) else round(float(mine), 2)
                theirs = None if theirs is None else round(float(theirs), 2)
            elif kind == "bool":
                mine = bool(mine)
            if mine != theirs:
                diffs.append((a["task_code"], col, mine, theirs))
        tf = None if o.is_complete else round(float(o.total_float_hr_cnt), 2)
        if tf != a["total_float_hrs"]:
            diffs.append((a["task_code"], "total_float_hr", tf, a["total_float_hrs"]))
    assert diffs == []


def test_xerlock_relationships(xl):
    s, ref = xl
    code = {a["task_id"]: a["task_code"] for a in ref["activities"]}
    theirs = {
        (code[p["task_id"]], a["task_code"], p["type"].replace("PR_", ""), p["lag_hrs"])
        for a in ref["activities"]
        for p in a["predecessors"]
    }
    mine = {(r.pred_code, r.succ_code, r.type, r.lag_hr) for r in s.relationships.itertuples()}
    assert mine == theirs


# --- DCMA results stated by xerlock (baseline = planned dates in the file) -------------------


@pytest.mark.parametrize("metric_id", E.DCMA)
def test_dcma_matches_stated_result(metric_id, xl):
    s, _ = xl
    std = builtin_standards()["DCMA"]
    r = run_metric(std[metric_id], AnalysisContext(s, baseline=Baseline.planned(s)))
    want = {k: v for k, v in E.DCMA[metric_id].items() if k != "note"}
    got = {k: getattr(r, k) for k in want}
    if "value" in got and got["value"] is not None:
        got["value"] = round(got["value"], 2)
    assert got == want, E.DCMA[metric_id].get("note", "")


def test_critical_path_test_delays_the_same_activity_as_xerlock(xl):
    """xerlock tests/test_cpm_sample.py: +600 wd on MEP-020 moves the finish by 600 wd."""
    from xerscope.analysis.cpm import critical_path_test

    s, _ = xl
    r = critical_path_test(s, 600)
    assert r.delayed == "MEP-020"
    assert r.passed and r.shift_h == pytest.approx(600 * 8)


def test_cpl_matches_xerlock_hand_calculation(xl):
    """xerlock tests/test_standards.py: CPL = 1080 h (135 working days x 8 h)."""
    s, _ = xl
    assert s.calendar().work_hours(s.data_date, s.finish_date) == 1080


# --- Independent reader: MPXJ (optional: uv sync --extra crosscheck, needs Java) -------------


def test_mpxj_reads_every_reference_file_like_xerscope():
    mpxj_or_skip()
    from xerscope.crosscheck import compare_paths

    df = compare_paths(sorted(DATA.glob("*/*.xer")))
    bad = df[~df["agree"]]
    assert len(df) > 500 and bad.empty, bad.to_string()
