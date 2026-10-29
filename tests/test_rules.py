"""Each rule on a hand-made schedule small enough to count by eye.

The cases target where P6 and DCMA disagree, since that is where a wrong population
or exemption would silently shift a result.
"""

import pandas as pd
import pytest
from xerkit import active, done, snap, todo

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_metric

P6 = builtin_standards()["P6"]
DCMA = builtin_standards()["DCMA"]


def run(std, metric_id, s, baseline=None):
    return run_metric(std[metric_id], AnalysisContext(s, baseline=baseline))


def codes(r):
    return sorted(r.flagged["task_code"]) if "task_code" in r.flagged else []


# --- logic --------------------------------------------------------------------------------

LOGIC = snap(
    [
        done("D0"),
        active("S1"),
        todo("M0", task_type="TT_Mile", target_drtn_hr_cnt="0"),
        todo("A"),
        todo("B"),
        todo("C"),
        todo("F", task_type="TT_FinMile", target_drtn_hr_cnt="0", early_end_date="2026-04-30 17:00"),
    ],
    [("D0", "A", "FS", 0), ("A", "B", "SS", 8), ("B", "F", "FS", 0), ("M0", "C", "FS", 0), ("S1", "B", "FS", 0)],
)


def test_p6_logic_exemptions():
    # S1: started, no predecessor -> passes; M0: start milestone -> passes; F: finish milestone
    # -> passes; C has no successor; A only drives B via SS (dangling finish, not an open end).
    r = run(P6, "P6-01", LOGIC)
    assert codes(r) == ["C"]
    assert r.denominator == 6  # D0 removed (actual finish)


def test_dcma_logic_counts_dangling_and_exempts_only_project_ends():
    # The project start is D0 (no predecessor, earliest start), so S1 and M0 are open
    # starts for DCMA even though P6 lets them pass. F is the project finish: exempt.
    r = run(DCMA, "DCMA-01", LOGIC)
    assert dict(zip(r.flagged["task_code"], r.flagged["reason"], strict=True)) == {
        "S1": "no predecessor",
        "M0": "no predecessor",
        "C": "no successor",
        "A": "dangling finish (no FS/FF successor)",
    }
    assert r.denominator == 6


def test_dangling_start_and_finish_rule():
    # Not a P6 Professional 24 check (EPPM only): kept as a rule for your own standard.
    from xerscope.analysis.rules import RULES

    def dangling(s, end):
        return sorted(RULES["dangling"].fn(AnalysisContext(s), end=end).flagged["task_code"])

    assert dangling(LOGIC, "finish") == ["A"]  # A -> B is SS only
    assert dangling(snap([todo("A"), todo("B")], [("A", "B", "FF", 0)]), "start") == ["B"]


def test_external_successor_passes_p6_logic():
    text_tasks = [todo("A"), todo("B")]
    s = snap(text_tasks, [("A", "B", "FS", 0), ("X9", "A", "FS", 0, "2")])  # A has an external predecessor
    r = run(P6, "P6-01", s)
    assert codes(r) == ["B"]  # A passes thanks to the external link; B has no successor


# --- relationships -------------------------------------------------------------------------

LINKS = snap(
    [done("D1"), done("D2"), todo("A"), todo("B")],
    [
        ("D1", "D2", "FS", 16),
        ("D2", "A", "FS", 400),
        ("A", "D1", "SS", 8),
        ("A", "B", "FS", -8),
        ("D1", "B", "FF", 352),
    ],
)


def test_link_populations_differ():
    # P6 drops only links between two finished activities (D1->D2); DCMA drops every link
    # into finished work (D1->D2 and the out-of-sequence A->D1).
    assert run(P6, "P6-08", LINKS).denominator == 4
    assert run(DCMA, "DCMA-03", LINKS).denominator == 3


def test_lead_long_lag_and_fs_share():
    assert run(DCMA, "DCMA-02", LINKS).numerator == 1  # A->B -8 h
    long = run(P6, "P6-05", LINKS)  # > 352 h: 400 yes, 352 no
    assert [(r.pred_code, r.succ_code) for r in long.flagged.itertuples()] == [("D2", "A")]
    fs = run(DCMA, "DCMA-04", LINKS)  # D2->A FS, A->B FS, D1->B FF
    assert (fs.numerator, fs.denominator) == (2, 3)
    assert fs.value == pytest.approx(200 / 3)


# --- constraints, float, durations ------------------------------------------------------------


def test_constraint_sets_differ_between_p6_and_dcma():
    s = snap(
        [
            todo("MS", cstr_type="CS_MSO", cstr_date="2026-04-01 08:00"),
            todo("MF", cstr_type="CS_MANDFIN", cstr_date="2026-04-01 17:00"),
            todo("LB", cstr_type="CS_MEOB", cstr_date="2026-04-01 17:00"),
            active("ST", cstr_type="CS_MSOA", cstr_date="2026-02-23 08:00"),
            todo("SEC", cstr_type2="CS_MANDSTART", cstr_date2="2026-04-01 08:00"),
        ]
    )
    assert codes(run(P6, "P6-02", s)) == ["MF", "SEC"]  # mandatory only, secondary counts
    assert codes(run(P6, "P6-03", s)) == ["LB", "MS"]  # ST: start constraint ignored once started
    assert codes(run(DCMA, "DCMA-05", s)) == ["LB", "MF", "MS", "SEC"]


def test_float_threshold_in_hours_vs_working_days():
    # 10 h/day calendar: 400 h = 40 working days. P6 (> 352 h) flags it, DCMA (> 44 d) does not.
    s = snap(
        [
            todo("A", clndr_id="C10", total_float_hr_cnt="400"),
            todo("B", total_float_hr_cnt="353"),
            todo("C", total_float_hr_cnt="352"),
            todo("N", total_float_hr_cnt="-8"),
        ]
    )
    assert codes(run(P6, "P6-06", s)) == ["A", "B"]
    assert codes(run(DCMA, "DCMA-06", s)) == ["B"]  # 353 / 8 = 44.1 d
    assert codes(run(P6, "P6-14", s)) == ["N"]


def test_large_duration_remaining_vs_original():
    s = snap(
        [
            active("A", target_drtn_hr_cnt="800", remain_drtn_hr_cnt="100"),
            todo("B", target_drtn_hr_cnt="360", remain_drtn_hr_cnt="360"),
            todo("M", task_type="TT_FinMile", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0"),
        ]
    )
    assert codes(run(P6, "P6-04", s)) == ["B"]  # remaining > 352 h
    assert codes(run(DCMA, "DCMA-08", s)) == ["A", "B"]  # original > 44 d


# --- progress, resources --------------------------------------------------------------------


def test_invalid_progress_dates():
    s = snap(
        [
            todo("EARLY", early_start_date="2026-02-27 08:00"),
            active("RUN", early_end_date="2026-02-27 17:00"),
            done("FUT", act_end_date="2026-03-04 17:00"),
            done("OK"),
            todo("FINE"),
        ]
    )
    assert codes(run(P6, "P6-10", s)) == ["EARLY", "FUT", "RUN"]  # Pro 24: one check, both sides
    assert run(P6, "P6-10", s).denominator == 4  # OK finished before the data date: removed
    assert run(DCMA, "DCMA-09", s).numerator == 3


def test_resource_or_expense():
    s = snap(
        [todo("R"), todo("E"), todo("NONE"), done("DONE"), todo("M", task_type="TT_Mile", target_drtn_hr_cnt="0")],
        rsrc=["R"],
        costs=["E"],
    )
    assert codes(run(P6, "P6-11", s)) == ["DONE", "NONE"]  # P6 keeps completed activities
    assert codes(run(DCMA, "DCMA-10", s)) == ["NONE"]


# --- baseline -----------------------------------------------------------------------------

BL = snap(
    [
        todo("A", early_end_date="2026-02-27 17:00"),
        todo("B", early_end_date="2026-02-27 17:00"),
        todo("C", early_end_date="2026-02-27 17:00"),
        todo("D", early_end_date="2026-04-30 17:00"),
    ]
)
NOW = snap(
    [
        done("A", act_end_date="2026-02-26 17:00"),
        done("B", act_end_date="2026-02-28 17:00"),  # finished, but after its baseline finish
        todo("C", early_end_date="2026-03-20 17:00"),  # due, not finished, late
        todo("D", early_end_date="2026-04-29 17:00"),
        todo("NEW", early_end_date="2026-03-10 17:00"),
    ]
)  # not in the baseline


def test_bei_p6_counts_unbaselined_as_due_dcma_ignores_them():
    bl = Baseline.from_snapshot(BL)
    p6 = run(P6, "P6-13", NOW, bl)
    assert (p6.numerator, p6.denominator) == (2, 4)  # A, B done / A, B, C + NEW (no baseline)
    dcma = run(DCMA, "DCMA-14", NOW, bl)
    assert (dcma.numerator, dcma.denominator) == (2, 3)
    assert dcma.value == pytest.approx(2 / 3)


def test_missed_tasks_and_late_activities():
    bl = Baseline.from_snapshot(BL)
    assert codes(run(DCMA, "DCMA-11", NOW, bl)) == ["B", "C"]
    assert codes(run(P6, "P6-12", NOW, bl)) == ["C"]  # D finishes earlier; NEW has no baseline


def test_baseline_metrics_are_na_without_baseline():
    assert run(P6, "P6-13", NOW).status == "n/a"


# --- critical path ---------------------------------------------------------------------------

CHAIN = [
    todo("A", total_float_hr_cnt="0"),
    todo("B", total_float_hr_cnt="0"),
    todo(
        "Z",
        task_type="TT_FinMile",
        target_drtn_hr_cnt="0",
        remain_drtn_hr_cnt="0",
        total_float_hr_cnt="0",
        early_end_date="2026-03-27 17:00",
    ),
]


def test_critical_path_test_passes_on_clean_logic():
    s = snap(CHAIN, [("A", "B", "FS", 0), ("B", "Z", "FS", 0)])
    r = run(DCMA, "DCMA-12", s)
    assert r.status == "pass" and "A" in r.note


def test_critical_path_test_fails_when_a_mandatory_date_absorbs_the_delay():
    chain = CHAIN[:2] + [dict(CHAIN[2], cstr_type="CS_MANDFIN", cstr_date="2026-03-27 17:00")]
    s = snap(chain, [("A", "B", "FS", 0), ("B", "Z", "FS", 0)])
    r = run(DCMA, "DCMA-12", s)
    assert r.status == "fail" and "Z" in r.note


def test_cpli_uses_the_finish_float():
    # Finish 2026-03-27 = 20 working days from Mon 2026-03-02; total float -16 h = -2 d.
    chain = CHAIN[:2] + [dict(CHAIN[2], total_float_hr_cnt="-16")]
    r = run(DCMA, "DCMA-13", snap(chain, [("A", "B", "FS", 0), ("B", "Z", "FS", 0)]))
    assert r.value == pytest.approx((20 - 2) / 20)
    assert r.status == "fail"


def test_calendar_holiday_counts_in_cpl():
    # Same, finishing 2026-04-10: 30 weekdays minus Good Friday (calendar exception) = 29.
    chain = CHAIN[:2] + [dict(CHAIN[2], early_end_date="2026-04-10 17:00")]
    r = run(DCMA, "DCMA-13", snap(chain, [("A", "B", "FS", 0), ("B", "Z", "FS", 0)]))
    assert "CPL 29 wd" in r.note


# --- framework -----------------------------------------------------------------------------


def test_broken_rule_reports_error_not_crash(monkeypatch):
    from xerscope.analysis import rules

    def boom(ctx, **_):
        raise RuntimeError("kaput")

    monkeypatch.setitem(rules.RULES, "float", rules.Rule("float", boom, "%", ""))
    r = run(P6, "P6-06", LOGIC)
    assert r.status == "error" and "kaput" in r.note


def test_results_have_no_nan_status():
    s = snap([todo("A")])
    for std in builtin_standards().values():
        for m in std.metrics:
            r = run_metric(m, AnalysisContext(s))
            assert r.status in {"pass", "fail", "info", "n/a"}, (m.id, r.note)
            assert r.value is None or pd.notna(r.value)


def test_start_milestone_without_successor_is_an_open_end_for_p6():
    # Only finish milestones pass the successor check; a start milestone must drive something.
    s = snap([todo("S", task_type="TT_Mile", target_drtn_hr_cnt="0"), todo("A")], [("S", "A", "FS", 0)])
    assert codes(run(P6, "P6-01", s)) == ["A"]
    s = snap([todo("S", task_type="TT_Mile", target_drtn_hr_cnt="0"), todo("A")], [("A", "S", "FS", 0)])
    assert codes(run(P6, "P6-01", s)) == ["A", "S"]  # A: no predecessor; S: no successor


# --- integrity ------------------------------------------------------------------------------

INTEGRITY = builtin_standards()["INTEGRITY"]


def test_recalculated_flags_stale_dates():
    # A's stored dates are what P6 would compute; B's float was not updated after an edit.
    s = snap(
        [
            todo(
                "A",
                early_end_date="2026-03-02 17:00",
                late_start_date="2026-03-02 08:00",
                late_end_date="2026-03-02 17:00",
                target_drtn_hr_cnt="8",
                remain_drtn_hr_cnt="8",
            ),
            todo(
                "B",
                early_start_date="2026-03-03 08:00",
                early_end_date="2026-03-03 17:00",
                late_start_date="2026-03-03 08:00",
                late_end_date="2026-03-03 17:00",
                target_drtn_hr_cnt="8",
                remain_drtn_hr_cnt="8",
                total_float_hr_cnt="40",
            ),
        ],
        [("A", "B", "FS", 0)],
    )
    r = run(INTEGRITY, "INT-01", s)
    assert codes(r) == ["B"] and r.status == "fail"
    assert "total_float_hr_cnt: 40 -> 0.0" in r.flagged.iloc[0]["differences"]


def test_out_of_sequence_progress_is_listed():
    s = snap([todo("A"), active("B"), done("C"), active("D")], [("A", "B", "FS", 0), ("C", "D", "FS", 0)])
    r = run(INTEGRITY, "INT-02", s)
    assert codes(r) == ["B"] and r.denominator == 3  # B, C, D started; D follows a finished C
    assert r.flagged.iloc[0]["ahead_of"] == "A (FS)"


def test_late_activities_use_working_time():
    # Finished Fri 17:00 against a baseline of Mon 08:00: the same working minute, not late.
    bl = Baseline.from_snapshot(snap([todo("A", early_end_date="2026-03-09 08:00")]))
    now = snap([todo("A", early_end_date="2026-03-06 17:00")])
    assert codes(run(P6, "P6-12", now, bl)) == []
    later = snap([todo("A", early_end_date="2026-03-09 09:00")])
    r = run(P6, "P6-12", later, bl)
    assert codes(r) == ["A"] and r.flagged.iloc[0]["finish_variance_wd"] == pytest.approx(1 / 8, abs=0.01)


def test_assignment_dates_integrity():
    stored = dict(
        restart_date="2026-03-02 08:00",
        reend_date="2026-03-03 17:00",
        rem_late_start_date="2026-03-02 08:00",
        rem_late_end_date="2026-03-03 17:00",
    )
    asg = [
        {"task_code": "A", "rsrc_id": "R8", "remain_qty": "16", "remain_qty_per_hr": "1", **stored},
        {"task_code": "B", "rsrc_id": "R8", "remain_qty": "16", "remain_qty_per_hr": "1", **stored},
    ]
    s = snap(
        [
            todo("A", target_drtn_hr_cnt="16", remain_drtn_hr_cnt="16"),
            todo("B", target_drtn_hr_cnt="16", remain_drtn_hr_cnt="16"),
        ],
        [("A", "B", "FS", 0)],
        assign=asg,
        resources=[{"rsrc_id": "R8", "rsrc_short_name": "FITTER", "rsrc_type": "RT_Labor", "clndr_id": "C8"}],
    )
    r = run(INTEGRITY, "INT-03", s)
    assert (r.numerator, r.denominator) == (1, 2)  # B's assignment was not moved after A
    assert r.flagged.iloc[0]["task_code"] == "B" and r.flagged.iloc[0]["resource"] == "FITTER"


# --- DCMA DECM v8.0 ---------------------------------------------------------------------------

DECM = builtin_standards()["DECM"]
D_BL = Baseline.from_snapshot(
    snap(
        [
            todo("A", early_start_date="2026-03-02 08:00"),
            *[todo(c, early_start_date="2026-03-03 08:00") for c in "BDME"],
            todo("Z", early_start_date="2026-03-20 17:00", early_end_date="2026-03-20 17:00"),
        ]
    )
)
D_NOW = snap(
    [
        todo("A"),
        todo("B"),
        todo("M", task_type="TT_FinMile", target_drtn_hr_cnt="0"),
        todo("D"),
        todo("Z", task_type="TT_FinMile", target_drtn_hr_cnt="0"),
        active("E"),
    ],
    [
        ("A", "B", "FF", 0),
        ("A", "M", "FF", 0),
        ("B", "Z", "FS", 0),
        ("M", "Z", "FS", 0),
        ("A", "D", "FS", 0),
        ("D", "Z", "SS", 0),
        ("E", "Z", "FS", 8),
    ],
)


def test_decm_dangling_logic():
    # B: only an FF predecessor (open start); M: a milestone only needs a predecessor;
    # D: only an SS successor (open finish); E: in progress counts too, no predecessor;
    # A (earliest baseline start) and Z (latest baseline finish) are exempt.
    r = run(DECM, "06A204b", D_NOW, D_BL)
    assert dict(zip(r.flagged["task_code"], r.flagged["reason"], strict=True)) == {
        "B": "open start (no FS/SS predecessor)",
        "D": "open finish (no FS/FF successor)",
        "E": "open start (no FS/SS predecessor)",
    }
    assert r.denominator == 6 and r.status == "fail"


def test_decm_lags_summary_logic_and_loe():
    assert codes(run(DECM, "06A205a", D_NOW)) == ["Z"]  # E -> Z has an 8 h lag
    s = snap(
        [todo("W", task_type="TT_WBS"), todo("A"), todo("L", task_type="TT_LOE"), todo("L2", task_type="TT_LOE")],
        [("W", "A", "FS", 0), ("L", "A", "FS", 0), ("L2", "L", "SS", 0)],
    )
    assert run(DECM, "06A208a", s).numerator == 1
    r = run(DECM, "06A210a", s)
    assert codes(r) == ["L"] and r.denominator == 2  # L2 only drives another LOE


def test_decm_out_of_sequence_counts_relationships():
    s = snap(
        [todo("A", early_end_date="2026-03-06 17:00"), active("B"), todo("C"), todo("D")],
        [("A", "B", "FS", 0), ("C", "D", "FS", -8)],
    )
    s.tasks.loc[s.tasks["task_code"] == "D", "start"] = pd.Timestamp("2026-03-13 09:00")  # overlap via the lead
    s.tasks.loc[s.tasks["task_code"] == "C", "finish"] = pd.Timestamp("2026-03-13 17:00")
    r = run(DECM, "06A212a", s)
    assert sorted(zip(r.flagged["pred_code"], r.flagged["succ_code"], strict=True)) == [("A", "B"), ("C", "D")]
    assert r.status == "fail"


def test_decm_baseline_and_actual_dates():
    bl = Baseline.from_snapshot(snap([todo("A"), todo("B")]))
    now = snap(
        [
            todo("A"),
            todo("B"),
            todo("NEW"),
            todo("P", phys_complete_pct="50", complete_pct_type="CP_Phys"),  # progress, no actual start
            done("F", act_end_date="2026-03-04 17:00"),
        ]
    )  # actual after the data date
    assert codes(run(DECM, "06A501a", now, bl)) == ["F", "NEW", "P"]
    assert codes(run(DECM, "06A505a", now)) == ["P"]
    r = run(DECM, "06A506a", now)
    assert codes(r) == ["F"] and r.denominator == 1  # of the activities with an actual start


def test_decm_actuals_changed_needs_the_previous_update():
    from xerscope.store import SnapshotStore

    w1 = snap([active("A"), done("B")])
    w2 = snap([active("A", act_start_date="2026-02-24 08:00"), done("B")], data_date="2026-03-09 08:00")
    store = SnapshotStore([w1, w2])
    r = run_metric(DECM["06A504a"], AnalysisContext(store[1], store))
    assert codes(r) == ["A"] and r.denominator == 2
    assert run_metric(DECM["06A504b"], AnalysisContext(store[1], store)).numerator == 0
    assert run_metric(DECM["06A504a"], AnalysisContext(w2)).status == "n/a"


def test_decm_riding_the_status_date():
    from xerscope.store import SnapshotStore

    # R's forecast start is the data date in both updates, a month apart: it rides.
    m1 = snap([todo("R", early_start_date="2026-03-02 08:00"), todo("OK", early_start_date="2026-03-02 08:00")])
    m2 = snap(
        [
            todo("R", early_start_date="2026-04-06 08:00"),
            active("OK", act_start_date="2026-03-02 08:00", remain_drtn_hr_cnt="16"),
        ],
        data_date="2026-04-06 08:00",
    )
    store = SnapshotStore([m1, m2])
    r = run_metric(DECM["06A506c"], AnalysisContext(store[1], store))
    assert codes(r) == ["R"] and r.denominator == 2


def test_decm_milestone_needs_only_one_link_per_side():
    s = snap(
        [
            todo("A", early_end_date="2026-03-03 17:00"),
            todo("MS", task_type="TT_FinMile", target_drtn_hr_cnt="0", early_end_date="2026-03-03 17:00"),
            todo("T", early_end_date="2026-03-06 17:00"),
            todo("Z", early_end_date="2026-03-20 17:00"),
        ],
        [("A", "MS", "FS", 0), ("A", "T", "FS", 0), ("MS", "Z", "SS", 0), ("T", "Z", "SS", 0)],
    )
    r = run(DECM, "06A204b", s, Baseline.from_snapshot(s))
    assert "T" in codes(r) and "MS" not in codes(r)  # same SS-only successor: open for a task only


def test_actuals_changed_counts_a_removed_date_on_both_sides():
    """A loses its actual start, B's moves: 2 of the 2 activities dated in either update
    (the share was 200 % when the denominator counted only today's dates)."""
    from xerkit import active, todo

    from xerscope.analysis import AnalysisContext
    from xerscope.analysis.rules import RULES
    from xerscope.store import SnapshotStore

    a = snap([active("A"), active("B"), todo("C")])
    b = snap([todo("A"), active("B", act_start_date="2026-02-24 08:00"), todo("C")], data_date="2026-03-09 08:00")
    store = SnapshotStore([a, b])
    out = RULES["actuals_changed"].fn(AnalysisContext(store[1], store), field="start")
    assert sorted(out.flagged["task_code"]) == ["A", "B"] and (out.numerator, out.denominator) == (2, 2)
