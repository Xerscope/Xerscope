"""P6 Check Schedule, written from Oracle's help text (each docstring quotes its source).

Sources: P6 Professional 24 "Check Schedule dialog box" (pro24 101248, the authority) and
the P6 EPPM 25 dialog help (G18294_01 / 91574) for the default targets.

Overlaps tests/test_rules.py on purpose: here each test is one sentence of the source.
"""

import pytest
from rulekit import STANDARDS, codes, counts, links, run
from xerkit import DD, FM, SM, active, done, snap, todo, with_second_project, xer_text

from xerscope.analysis import Baseline
from xerscope.xer import build_snapshot, parse_text

P6 = STANDARDS["P6"]
DCMA = STANDARDS["DCMA"]

BL_BEFORE_DD = "2026-02-20 17:00"  # a baseline finish ten days before the data date (2026-03-02)
LARGE_H = 44 * 8  # P6 "x" threshold: 44 working days on the 8 h calendar (p6.toml)


def chain(link_types, lags=None):
    """not-started activities T01..Tn linked in a row (n = links + 1); ``link_types``/``lags`` per link."""
    n = len(link_types) + 1
    if lags is None:
        lags = [0] * (n - 1)
    tasks = [todo(f"T{i:02d}") for i in range(1, n + 1)]
    links = [(f"T{i:02d}", f"T{i + 1:02d}", link_types[i - 1], lags[i - 1]) for i in range(1, n)]
    return snap(tasks, links)


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


def test_p6_04_remaining_352h_is_not_large_353h_is_and_milestones_are_out():
    """'Activities that have a remaining duration greater than' the value (Large Durations option, 101248).

    101248 is silent on milestones, but a P6 Professional r22.12 Check Schedule report analysed by Ten Six
    (https://tensix.com/using-the-p6-check-schedule-tool/) says: "The Large Durations tasks assessment
    only considers remaining work. Milestones and LOE tasks are not included." (its other checks count
    the finish milestone in their total). P6 EPPM help 46282: "WBS summary activities, activities with
    an actual finish date, milestones, and Level of Effort activities are removed from the subset"."""
    s = snap(
        [
            todo("AT", remain_drtn_hr_cnt=str(LARGE_H)),
            todo("OVER", remain_drtn_hr_cnt=str(LARGE_H + 1)),
            todo("MS", task_type="TT_FinMile", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0"),
        ]
    )
    r = run(P6, "P6-04", s)
    assert counts(r) == (1, 2)
    assert codes(r) == ["OVER"]


def test_dcma_08_original_44_days_is_not_high_45_days_is():
    """DCMA 08 (baseline duration above 44 working days): 352 h = 44 d on C8, 360 h = 45 d."""
    s = snap([todo("AT", target_drtn_hr_cnt=str(LARGE_H)), todo("OVER", target_drtn_hr_cnt=str(LARGE_H + 8))])
    r = run(DCMA, "DCMA-08", s, Baseline.planned(s))
    assert counts(r) == (1, 2)
    assert codes(r) == ["OVER"]


# --- 3. exclusions ----------------------------------------------------------------------------

OFFENCES = {
    "P6-14": {"total_float_hr_cnt": "-8"},  # negative float
    "P6-06": {"total_float_hr_cnt": "400"},  # above LARGE_H
    "P6-04": {"remain_drtn_hr_cnt": "400"},  # above LARGE_H
    # hard finish; a start constraint would be dropped on DONE by the started exemption anyway
    "P6-02": {"cstr_type": "CS_MANDFIN", "cstr_date": "2026-03-09 08:00"},
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
def test_p6_completed_wbs_summary_and_loe_are_not_included(metric_id):
    """'Completed, WBS Summary, and Level of Effort activities are not included in this analysis.'
    (Large Float wording, 101248, reused here for all four metrics.)"""
    r = run(P6, metric_id, four_with_offence(OFFENCES[metric_id]))
    assert counts(r)[0] == 1
    assert r.denominator == 1  # only TODO is in the population
    assert codes(r) == ["TODO"]


def test_p6_01_wbs_summary_without_links_is_neither_flagged_nor_counted():
    """'Completed activities and WBS summary activities are not included in this analysis.' (Logic, 101248)"""
    s = snap([todo("A"), todo("B"), todo("WBS", task_type="TT_WBS")], [("A", "B", "FS", 0)])
    r = run(P6, "P6-01", s)
    assert "WBS" not in codes(r)
    assert r.denominator == 2  # A and B only


def test_p6_11_milestone_loe_and_wbs_are_excluded_completed_stays_in():
    """'Milestones, WBS Summary activities, and Level of Effort activities are not included in this analysis.'
    (Resource / Cost, 101248)"""
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


def test_p6_12_milestone_loe_wbs_and_completed_are_excluded():
    """'Milestones, WBS Summary activities, and Level of Effort activities are not included in this analysis.'
    (Late Activities, 101248). Report R1 (docs/standards.md) checks as many late activities as large
    durations, the same population: completed activities are out too."""
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
    assert counts(r) == (1, 1)
    assert codes(r) == ["A"]


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
    assert codes(r) == ["A0", "A1", "A2", "A3", "A4"]


# --- 6. link populations ------------------------------------------------------------------------


def test_p6_07_numerator_counts_finish_to_start_links_and_flags_the_others():
    """'Specify the target for the acceptable percentage of relationships that must have a relationship type
    of Finish to Start.' (Relationship Types, 101248)"""
    s = snap(
        [todo("A"), todo("B"), todo("C"), todo("D")],
        [("A", "B", "FS", 0), ("B", "C", "FS", 0), ("C", "D", "SS", 0)],
    )
    r = run(P6, "P6-07", s)
    assert counts(r) == (2, 3)
    assert links(r) == [("C", "D")]


def test_p6_09_negative_lag_counts_done_to_todo_not_done_to_done_and_not_zero():
    """'Relationships between completed activities are not included in this analysis.' (Negative Lags, 101248)"""
    s = snap(
        [done("D1"), done("D2"), todo("T1"), todo("T2")],
        [("D1", "T1", "FS", -8), ("D1", "D2", "FS", -8), ("D2", "T2", "FS", 0)],
    )
    r = run(P6, "P6-09", s)
    assert counts(r) == (1, 2)  # D1->D2 is outside both
    assert links(r) == [("D1", "T1")]


def test_p6_05_done_to_done_link_with_a_long_lag_is_outside_the_denominator():
    """'Relationships between completed activities are not included in this analysis.' (Long Lags, 101248)"""
    s = snap(
        [done("D1"), done("D2"), todo("T1")],
        [("D1", "D2", "FS", LARGE_H + 48), ("D2", "T1", "FS", 0)],  # 400 h lag, over the threshold
    )
    r = run(P6, "P6-05", s)
    assert counts(r) == (0, 1)
    assert links(r) == []


# --- 7. invalid progress dates ------------------------------------------------------------------

AFTER_DD = "2026-03-03 08:00"  # the day after the data date (DD is Monday 2026-03-02)
BEFORE_DD = "2026-02-27 08:00"  # the working day before the data date (Friday)


def test_p6_10b_actual_start_after_the_data_date_on_an_in_progress_activity_is_invalid():
    """'Invalid dates for in progress activities are remaining early start dates earlier than the data date
    or actual start dates later than the data date.' (Invalid Progress Dates, 101248)"""
    s = snap([active("A", act_start_date=AFTER_DD, early_start_date="2026-03-02 08:00"), active("B")])
    r = run(P6, "P6-10b", s)
    assert counts(r) == (1, 2)
    assert codes(r) == ["A"]


def test_p6_10b_completed_with_actual_finish_exactly_on_the_data_date_stays_in_and_is_not_invalid():
    """'Invalid dates for completed activities are actual finish dates later than the data date.' and
    'Completed activities with an actual finish earlier than the data date' are not included in this analysis.
    (Invalid Progress Dates, 101248)"""
    s = snap([done("ON", act_end_date=DD), done("BEFORE"), done("AFTER", act_end_date=AFTER_DD)])
    r = run(P6, "P6-10b", s)
    assert counts(r) == (1, 2)  # BEFORE is excluded; ON stays in
    assert codes(r) == ["AFTER"]


def test_p6_10a_not_started_start_before_the_data_date_is_invalid_loe_and_wbs_are_excluded():
    """'Invalid dates for not started activities are start dates earlier than the data date.' and
    'WBS summary activities, and Level of Effort activities are not included in this analysis.'
    (Invalid Progress Dates, 101248)"""
    s = snap(
        [
            todo("ON", early_start_date=DD),
            todo("EARLY", early_start_date=BEFORE_DD),
            todo("LOE", task_type="TT_LOE", early_start_date=BEFORE_DD),
            todo("WBS", task_type="TT_WBS", early_start_date=BEFORE_DD),
        ]
    )
    r = run(P6, "P6-10a", s)
    assert counts(r) == (1, 2)
    assert codes(r) == ["EARLY"]


# --- 8. resource / cost -------------------------------------------------------------------------


def test_p6_11_a_role_only_or_an_expense_only_activity_passes_and_nothing_assigned_is_flagged():
    """'An activity will be considered to pass this test if at least one resource, role, or expense has been
    assigned, regardless of whether any costs have been assigned to the resources or expenses.'
    (Resource / Cost, 101248)"""
    s = snap(
        [todo("ROLE"), todo("EXP"), todo("RES"), done("NONE"), todo("WBS", task_type="TT_WBS")],
        assign=[{"task_code": "ROLE", "role_id": "5", "rsrc_id": ""}],  # a role, no resource
        costs=["EXP"],
        rsrc=["RES"],
    )
    r = run(P6, "P6-11", s)
    assert counts(r) == (1, 4)
    assert codes(r) == ["NONE"]


# --- 9. BEI -------------------------------------------------------------------------------------


def test_p6_13_bei_is_completed_over_all_baseline_activities():
    """101248 says 'baseline activities calculated to finish before the open project's data date', but a
    P6 Professional report (R1) divides the completed activities by every baseline activity, whatever its
    finish date. The report wins."""
    # A finishes before the data date; B keeps xerkit's default early end (2026-03-13), after it
    baseline = Baseline.from_snapshot(snap([todo("A", early_end_date=BL_BEFORE_DD), todo("B")]))
    current = snap([done("A"), done("B")])
    r = run(P6, "P6-13", current, baseline)
    assert counts(r) == (2, 2)
    assert r.value == 1.0
    assert r.status == "pass"
    assert r.note == "2 completed / 2 baseline tasks"


def test_p6_13_a_baseline_milestone_is_not_counted():
    """'In the project baseline, milestones, WBS Summary activities, Level of Effort activities, and activities
    with a finish date later than the open project's data date are not included in this analysis.'
    (BEI, 101248)"""
    baseline = Baseline.from_snapshot(
        snap(
            [
                todo("A", early_end_date=BL_BEFORE_DD),
                todo("MS", task_type="TT_FinMile", target_drtn_hr_cnt="0", early_end_date=BL_BEFORE_DD),
            ]
        )
    )
    current = snap([done("A"), todo("MS", task_type="TT_FinMile", target_drtn_hr_cnt="0")])
    r = run(P6, "P6-13", current, baseline)
    assert counts(r) == (1, 1)
    assert r.value == 1.0
    assert codes(r) == []


# --- 10. Out of sequence and dangling (P6 Professional report R1) -----------------------------------


def test_p6_15_out_of_sequence_is_progress_while_a_predecessor_is_still_open():
    """'Activities which are completed or in-progress before their predecessors.' A P6 Professional report
    (R1) lists pairs and counts each activity once: in every pair the FS predecessor finishes
    after the data date; pairs whose predecessor finished late but before the data date are not listed."""
    s = snap(
        [done("A"), active("B"), todo("A2"), active("A3"), active("C"), active("D")],
        [("A", "B", "FS", 0), ("A2", "C", "FS", 0), ("A3", "C", "FS", 0), ("A2", "D", "SS", 0)],
    )
    r = run(P6, "P6-15", s)
    assert counts(r) == (2, 6)  # C (two open FS predecessors) and D (SS predecessor not started)
    assert codes(r) == ["C", "C", "D"]  # one row per activity and predecessor, as the report lists them


def test_p6_16_dangling_start_ignores_in_progress_and_activities_without_predecessor():
    """'Activities with start dates that are not driven by predecessors', 'Ignore In Progress Activities'
    checked. The report's Logic check lists the activity with no predecessor; the dangling check does not."""
    s = snap(
        [todo("P"), todo("X"), active("Y"), todo("Z")],
        [("P", "X", "FF", 0), ("P", "Y", "FF", 0), ("X", "Z", "FS", 0)],
    )
    r = run(P6, "P6-16", s)
    assert counts(r) == (1, 4)
    assert codes(r) == ["X"]


def test_p6_17_dangling_finish_needs_a_successor_that_is_not_driven():
    """'Activities with finish dates that do not drive successors.' An activity with no successor at all is
    the Logic check's (the report lists it there, not here)."""
    s = snap([todo("X"), todo("S"), todo("K")], [("X", "S", "SS", 0)])
    r = run(P6, "P6-17", s)
    assert counts(r) == (1, 3)
    assert codes(r) == ["X"]


def test_p6_16_and_17_leave_milestones_out():
    """A milestone has a single date. On report R1, start and finish milestones with only FF or SS logic
    (Start on or after constraints) are not dangling: none found by either check."""
    s = snap(
        [todo("P"), todo("FM", **FM), todo("SM", **SM), todo("S")],
        [("P", "FM", "FF", 0), ("SM", "S", "SS", 0)],
    )
    assert counts(run(P6, "P6-16", s)) == (0, 4)
    assert counts(run(P6, "P6-17", s)) == (0, 4)


def _with_link_to_second_project(text: str, pred_task_id: str, succ_task_id: str, link_type: str) -> str:
    """``text`` plus a TASKPRED row of project 2 whose predecessor is ``pred_task_id`` of project 1."""
    lines = text.splitlines()
    at = lines.index("%T\tTASKPRED")
    header = lines[at + 1].split("\t")[1:]
    row = dict.fromkeys(header, "")
    row.update(task_pred_id="99", task_id=succ_task_id, pred_task_id=pred_task_id, proj_id="2", pred_proj_id="1")
    row.update(pred_type=f"PR_{link_type}", lag_hr_cnt="0")
    lines.insert(at + 2, "%R\t" + "\t".join(row[column] for column in header))
    return "\n".join(lines) + "\n"


def test_p6_16_and_17_do_not_read_links_to_other_projects():
    """UNRESOLVED (docs/standards.md): the Dangling help (113174) does not say how P6 treats a link to an
    activity of another project. Pinned reading: P6-16 / P6-17 see only the links inside the project,
    where P6-01 lets an external link pass (46291)."""
    # B: FF from A and FS from X9 of project 2 (not in the file). Only the FF is read: B is listed.
    s = snap([todo("A"), todo("B"), todo("C")], [("A", "B", "FF", 0), ("X9", "B", "FS", 0, "2"), ("B", "C", "FS", 0)])
    r = run(P6, "P6-16", s)
    assert (counts(r), codes(r)) == ((1, 3), ["B"])
    # A: its only predecessor is an FF from project 2. No predecessor read: not listed, P6-01 passes it.
    s = snap([todo("A"), todo("B")], [("X9", "A", "FF", 0, "2"), ("A", "B", "FS", 0)])
    assert counts(run(P6, "P6-16", s)) == (0, 2)
    assert codes(run(P6, "P6-01", s)) == ["B"]
    # A: SS to B, FS to Z of project 2 (in the file). Only the SS is read: A is listed.
    text = with_second_project(xer_text([todo("A"), todo("B")], [("A", "B", "SS", 0)]), "P2", ["Z"], DD)
    s = build_snapshot(parse_text(_with_link_to_second_project(text, "1", "100", "FS"), source="t.xer"), "T")
    assert s.activities.set_index("task_code").loc["A", "has_external_succ"]
    r = run(P6, "P6-17", s)
    assert (counts(r), codes(r)) == ((1, 2), ["A"])


def test_p6_12_and_13_with_the_planned_dates_baseline_reproduce_p6():
    """Report R1 (docs/standards.md) is reproduced exactly with the "planned dates in each file" baseline:
    the same late activities with the same finish variance to the hour, and the same BEI. P6 moves a
    not-started activity's planned dates with the schedule (variance 0) and freezes them at its actual
    start, so only an activity in progress drifts from them."""
    current = snap(
        [
            # in progress: planned finish frozen two weeks before the forecast finish -> late, 10 wd
            active("RUN", target_end_date="2026-02-27 17:00", early_end_date="2026-03-13 17:00"),
            # not started: planned dates follow the schedule -> on time
            todo("WAIT", target_end_date="2026-03-13 17:00", early_end_date="2026-03-13 17:00"),
            done("DONE", target_end_date="2026-02-13 17:00"),
        ]
    )
    baseline = Baseline.planned(current)
    late = run(P6, "P6-12", current, baseline)
    assert counts(late) == (1, 2)  # completed activities are not checked
    assert codes(late) == ["RUN"]
    assert late.flagged.iloc[0]["finish_variance_wd"] == pytest.approx(10)  # P6: -80 h on an 8 h day
    bei = run(P6, "P6-13", current, baseline)
    assert counts(bei) == (1, 3)  # completed / every activity of the baseline (the file itself)
