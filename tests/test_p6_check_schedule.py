"""P6 Check Schedule, written from Oracle's help text (each docstring quotes its source).

Sources: P6 Professional 24 "Check Schedule dialog box" (pro24 101248, the authority) and
the P6 EPPM 25 dialog help (G18294_01 / 91574) for the default targets.
"""

import pytest
from xerkit import active, done, snap, todo

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_metric

P6 = builtin_standards()["P6"]
DCMA = builtin_standards()["DCMA"]


def run(std, metric_id, s, baseline=None):
    return run_metric(std[metric_id], AnalysisContext(s, baseline=baseline))


def codes(r):
    return sorted(r.flagged["task_code"]) if "task_code" in r.flagged else []


def chain(link_types, lags=None, n=21):
    """n not-started activities T01..Tn linked in a row; ``link_types``/``lags`` per link."""
    lags = lags or [0] * (n - 1)
    tasks = [todo(f"T{i:02d}") for i in range(1, n + 1)]
    links = [(f"T{i:02d}", f"T{i + 1:02d}", link_types[i - 1], lags[i - 1]) for i in range(1, n)]
    return snap(tasks, links)


def counts(r):
    return (r.numerator, r.denominator)


# --- 1. target strictness ---------------------------------------------------------------------


def test_p6_08_lags_exactly_5_percent_fails_the_strict_target_dcma_03_passes():
    """'The default target is less than 5 percent.' (Lags option, G18294_01)"""
    s = chain(["FS"] * 20, lags=[8] + [0] * 19)  # 1 lagged link of 20 = 5%
    p6 = run(P6, "P6-08", s)
    assert counts(p6) == (1, 20)
    assert p6.status == "fail"
    dcma = run(DCMA, "DCMA-03", s)
    assert counts(dcma) == (1, 20)
    assert dcma.status == "pass"  # DCMA allows <= 5%


def test_p6_07_fs_exactly_90_percent_fails_the_strict_target_dcma_04_passes():
    """'The default target is greater than 90 percent.' (Relationship Types option, G18294_01)"""
    s = chain(["SS", "SS"] + ["FS"] * 18)  # 18 FS of 20 = 90%
    p6 = run(P6, "P6-07", s)
    assert counts(p6) == (18, 20)
    assert p6.status == "fail"
    dcma = run(DCMA, "DCMA-04", s)
    assert counts(dcma) == (18, 20)
    assert dcma.status == "pass"  # DCMA allows >= 90%


# --- 2. large duration boundary ---------------------------------------------------------------


def test_p6_04_remaining_352h_is_not_large_353h_is():
    """'Activities that have a remaining duration greater than' the value (101248); default 352h."""
    s = snap([todo("AT", remain_drtn_hr_cnt="352"), todo("OVER", remain_drtn_hr_cnt="353")])
    r = run(P6, "P6-04", s)
    assert counts(r) == (1, 2)
    assert codes(r) == ["OVER"]


def test_dcma_08_original_44_days_is_not_high_45_days_is():
    """DCMA 08 (original duration above 44 working days): 352 h = 44 d on C8, 360 h = 45 d."""
    s = snap([todo("AT", target_drtn_hr_cnt="352"), todo("OVER", target_drtn_hr_cnt="360")])
    r = run(DCMA, "DCMA-08", s)
    assert counts(r) == (1, 2)
    assert codes(r) == ["OVER"]


# --- 3. exclusions ----------------------------------------------------------------------------

OFFENCES = {
    "P6-14": {"total_float_hr_cnt": "-8"},  # negative float
    "P6-06": {"total_float_hr_cnt": "400"},  # above 352 h
    "P6-04": {"remain_drtn_hr_cnt": "400"},  # above 352 h
    "P6-02": {"cstr_type": "CS_MANDSTART", "cstr_date": "2026-03-09 08:00"},  # hard constraint
}


def four_with_offence(offence):
    """The same offence on a not-started activity, a LOE, a WBS summary and a completed one."""
    return snap(
        [
            todo("TODO", **offence),
            todo("LOE", task_type="TT_LOE", **offence),
            todo("WBS", task_type="TT_WBS", **offence),
            done("DONE", **offence),
        ]
    )


@pytest.mark.parametrize("metric_id", sorted(OFFENCES))
def test_completed_wbs_summary_and_loe_are_not_included(metric_id):
    """'Completed, WBS Summary, and Level of Effort activities are not included in this analysis.'"""
    r = run(P6, metric_id, four_with_offence(OFFENCES[metric_id]))
    assert r.numerator == 1
    assert codes(r) == ["TODO"]


def test_p6_01_wbs_summary_without_links_is_neither_flagged_nor_counted():
    """'Completed activities and WBS summary activities are not included in this analysis.'"""
    s = snap([todo("A"), todo("B"), todo("WBS", task_type="TT_WBS")], [("A", "B", "FS", 0)])
    r = run(P6, "P6-01", s)
    assert "WBS" not in codes(r)
    assert r.denominator == 2  # A and B only


def test_p6_11_milestone_loe_and_wbs_are_excluded_completed_stays_in():
    """'Milestones, WBS Summary activities, and Level of Effort activities are not included in this analysis.'"""
    s = snap(
        [
            todo("A"),
            todo("MS", task_type="TT_Mile", target_drtn_hr_cnt="0"),
            todo("LOE", task_type="TT_LOE"),
            todo("WBS", task_type="TT_WBS"),
            done("DONE"),
        ]
    )
    r = run(P6, "P6-11", s)
    assert counts(r) == (2, 2)
    assert codes(r) == ["A", "DONE"]


def test_p6_12_milestone_loe_and_wbs_are_excluded_completed_stays_in():
    """'Milestones, WBS Summary activities, and Level of Effort activities are not included in this analysis.'"""
    base_end = "2026-02-13 17:00"  # baseline finish; a forecast finish later than it is late
    bl_tasks = [
        todo("A", early_end_date=base_end),
        todo("MS", task_type="TT_Mile", target_drtn_hr_cnt="0", early_end_date=base_end),
        todo("LOE", task_type="TT_LOE", early_end_date=base_end),
        todo("WBS", task_type="TT_WBS", early_end_date=base_end),
        todo("DONE", early_end_date=base_end),
    ]
    late_tasks = [
        todo("A"),  # default early finish 2026-03-13: late
        todo("MS", task_type="TT_Mile", target_drtn_hr_cnt="0"),
        todo("LOE", task_type="TT_LOE"),
        todo("WBS", task_type="TT_WBS"),
        done("DONE", act_end_date="2026-02-20 17:00"),  # a week after its baseline finish
    ]
    r = run(P6, "P6-12", snap(late_tasks), Baseline.from_snapshot(snap(bl_tasks)))
    assert counts(r) == (2, 2)
    assert codes(r) == ["A", "DONE"]


# --- 4. started exemption ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metric_id", "cstr_type", "expected"),
    [
        ("P6-02", "CS_MSO", 0),  # start constraint on a started activity
        ("P6-02", "CS_MEO", 1),  # finish constraint still counts
        ("P6-03", "CS_MSOB", 0),
        ("P6-03", "CS_MEOA", 1),
    ],
)
def test_start_constraints_on_started_activities_are_not_included(metric_id, cstr_type, expected):
    """'...and start constraints applied to started activities are not included in this analysis.'"""
    s = snap([active("A", cstr_type=cstr_type, cstr_date="2026-03-09 08:00")])
    assert run(P6, metric_id, s).numerator == expected


def test_dcma_05_counts_a_start_constraint_on_a_started_activity():
    """Contrast: DCMA 05 has no started exemption (ignore_start_when_started = false)."""
    s = snap([active("A", cstr_type="CS_MSO", cstr_date="2026-03-09 08:00")])
    assert run(DCMA, "DCMA-05", s).numerator == 1


# --- 5. soft constraint set -------------------------------------------------------------------


def test_p6_03_counts_each_soft_constraint_type():
    """'Soft constraints are Start On or Before, Start On or After, Finish On or Before,
    Finish On or After, and As Late As Possible.'"""
    soft = ["CS_MSOB", "CS_MSOA", "CS_MEOB", "CS_MEOA", "CS_ALAP"]
    s = snap([todo(f"A{i}", cstr_type=t, cstr_date="2026-03-09 08:00") for i, t in enumerate(soft)])
    r = run(P6, "P6-03", s)
    assert counts(r) == (5, 5)
    assert len(codes(r)) == len(soft)
