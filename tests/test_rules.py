"""Each rule on a hand-made schedule small enough to count by eye.

The cases target where P6 and DCMA disagree, since that is where a wrong population
or exemption would silently shift a result.
"""

import pandas as pd
import pytest
from rulekit import STANDARDS, codes, counts, links, run
from xerkit import FM, SM, active, done, hours, snap, todo, with_second_project, xer_text

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_metric
from xerscope.xer import build_snapshot, parse_text

P6 = STANDARDS["P6"]
DCMA = STANDARDS["DCMA"]


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
    """101248: "Started activities and start milestones are not required by this analysis to have predecessors."
    And: "Completed activities and WBS summary activities are not included in this analysis."
    The P6 Professional reports exempt only the started ones: a 26.8 report lists a not-started start
    milestone without predecessor (test_p6_checksched.py), and the r22.12 report analysed by Ten Six
    (tensix.com/using-the-p6-check-schedule-tool/) notes "The W1000 Notice to Proceed task
    has no predecessor and the W1030 Project Complete task has no successor."
    """
    # S1: started, no predecessor -> passes; M0: start milestone, not started -> flagged; C has no
    # successor; F: finish milestone with no successor -> flagged; A only drives B via SS (not an open end).
    r = run(P6, "P6-01", LOGIC)
    assert codes(r) == ["C", "F", "M0"]
    assert dict(zip(r.flagged["task_code"], r.flagged["reason"], strict=True))["M0"] == "no predecessor"
    assert dict(zip(r.flagged["task_code"], r.flagged["reason"], strict=True))["F"] == "no successor"
    assert r.denominator == 6  # D0 removed (actual finish)


def test_p6_logic_flags_the_finish_milestone_without_successor():
    """Ten Six: "the schedule would have passed if not for the Project Complete milestone with no successor." """
    s = snap(
        [
            todo("Start", task_type="TT_Mile", target_drtn_hr_cnt="0"),
            todo("A"),
            todo("B"),
            todo("Finish", task_type="TT_FinMile", target_drtn_hr_cnt="0"),
        ],
        [("Start", "A", "FS", 0), ("A", "B", "FS", 0), ("B", "Finish", "FS", 0)],
    )
    r = run(P6, "P6-01", s)
    # Finish has no successor; Start, not started, has no predecessor (test_p6_logic_exemptions)
    assert codes(r) == ["Finish", "Start"]
    assert (r.numerator, r.denominator) == (2, 4)


def test_dcma_01_follows_pam_200_1():
    """DCMA-EA PAM 200.1 (Oct 2012) 4.1: "Any incomplete task that is missing a predecessor and/or a
    successor is included in this metric."

    4.0 excludes completed tasks, LOE, subprojects and milestones; 4.1 has no project start/finish
    exemption and no "dangling" (an SS-only finish) case: only a missing predecessor or successor counts.
    """
    r = run(DCMA, "DCMA-01", LOGIC)
    # Population: D0 (complete), M0 and F (milestones) are out; S1, A, B, C remain -> 4.
    # S1: started, no predecessor (no exemption for the project start). C: no successor.
    # A drives B by SS only: it has a successor, so it is not flagged (no "dangling").
    assert dict(zip(r.flagged["task_code"], r.flagged["reason"], strict=True)) == {
        "S1": "no predecessor",
        "C": "no successor",
    }
    assert (r.numerator, r.denominator) == (2, 4)


def test_missing_logic_keeps_exemptions_and_dangling_for_custom_standards():
    """The parameters DCMA-01 no longer uses stay available (custom-template.toml CUS-01)."""
    from xerscope.analysis.rules import RULES

    r = RULES["missing_logic"].fn(
        AnalysisContext(LOGIC),
        exclude=["complete", "loe"],
        pred_exempt=["project_start"],
        succ_exempt=["project_finish"],
        dangling=True,
    )
    # The pre-PAM 200.1 DCMA-01 result on LOGIC, unchanged: D0 (complete) out -> 6 checked;
    # A drives B by SS only, so it is a dangling finish.
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


def test_external_link_counts_only_when_the_option_says_so():
    from xerscope.analysis.rules import RULES

    s = snap([todo("A"), todo("B")], [("A", "B", "FS", 0), ("X9", "A", "FS", 0, "2")])
    r = RULES["missing_logic"].fn(AnalysisContext(s), exclude=[], external_passes=False)
    assert sorted(r.flagged["task_code"]) == ["A", "B"]  # A: the external link no longer counts


def test_link_to_an_activity_not_in_the_file_is_dropped():
    # TASKPRED names a predecessor id no TASK row has (an export of one project out of a
    # linked set): the link is not logic P6 can schedule, so it counts for no check.
    s = snap([todo("A"), todo("B")], [("A", "B", "FS", 0), ("999", "A", "FS", 8)])
    assert len(s.relationships) == 1
    assert any("not in the file" in w for w in s.warnings)
    assert codes(run(P6, "P6-01", s)) == ["A", "B"]  # A has no predecessor after all; B no successor
    assert run(P6, "P6-08", s).denominator == 1  # the lagged ghost link is not in the population


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


def test_dcma_02_03_04_follow_pam_200_1():
    """DCMA-EA PAM 200.1 (Oct 2012) 4.2: "the number of logic links with a lead (negative lag) in
    predecessor relationships for incomplete tasks"; 4.3: "the number of lags in predecessor logic
    relationships for incomplete tasks"; 4.4: "a count of incomplete tasks containing each type of
    logic link".

    4.0 excludes completed tasks, LOE, subprojects and milestones, so a link counts when its
    successor is a retained task. A link whose predecessor is a milestone still counts (M->C).
    """
    s = snap(
        [done("D1"), done("D2"), todo("A"), todo("B"), todo("C"), todo("M", task_type="TT_FinMile")],
        [
            ("D1", "D2", "FS", 16),  # out: successor complete
            ("D2", "A", "FS", 400),  # in: lag
            ("A", "D1", "SS", 8),  # out: successor complete
            ("A", "B", "FS", -8),  # in: lead
            ("D1", "B", "FF", 352),  # in: lag, not FS
            ("B", "M", "FS", 8),  # out: successor is a milestone
            ("M", "C", "FS", 8),  # in: predecessor milestone still counts
        ],
    )
    leads = run(DCMA, "DCMA-02", s)
    assert links(leads) == [("A", "B")]
    assert counts(leads) == (1, 4)
    lags = run(DCMA, "DCMA-03", s)
    assert links(lags) == [("D1", "B"), ("D2", "A"), ("M", "C")]
    assert counts(lags) == (3, 4)
    fs = run(DCMA, "DCMA-04", s)
    assert links(fs) == [("D1", "B")]  # the only link that is not FS
    assert counts(fs) == (3, 4)


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
    # P6 Professional: Start On / Finish On are hard; secondary counts; ST: start constraint ignored once started
    assert codes(run(P6, "P6-02", s)) == ["MF", "MS", "SEC"]
    assert codes(run(P6, "P6-03", s)) == ["LB"]
    assert codes(run(DCMA, "DCMA-05", s)) == ["LB", "MF", "MS", "SEC"]


def test_dcma_05_follows_pam_200_1():
    """DCMA-EA PAM 200.1 (Oct 2012) 4.5: "Divide the total number of hard constraints by the number of
    incomplete tasks."

    Hard constraints are MFO, MSO, SNLT and FNLT (a secondary constraint counts, a started task is
    not exempt); soft ones (SNET, FNET, ASAP) are not. 4.0 excludes completed tasks, LOE,
    subprojects and milestones: MSF, a finish milestone with FNLT, is out of numerator and population.
    """
    s = snap(
        [
            todo("MS", cstr_type="CS_MSO", cstr_date="2026-04-01 08:00"),
            todo("MF", cstr_type="CS_MANDFIN", cstr_date="2026-04-01 17:00"),
            todo("LB", cstr_type="CS_MEOB", cstr_date="2026-04-01 17:00"),
            todo("SEC", cstr_type2="CS_MANDSTART", cstr_date2="2026-04-01 08:00"),
            active("STB", cstr_type="CS_MSOB", cstr_date="2026-03-09 08:00"),
            active("ST", cstr_type="CS_MSOA", cstr_date="2026-02-23 08:00"),
            todo(
                "MSF",
                task_type="TT_FinMile",
                target_drtn_hr_cnt="0",
                cstr_type="CS_MEOB",
                cstr_date="2026-04-01 17:00",
            ),
        ]
    )
    r = run(DCMA, "DCMA-05", s)
    assert codes(r) == ["LB", "MF", "MS", "SEC", "STB"]
    assert (r.numerator, r.denominator) == (5, 6)


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


def test_the_x_threshold_of_the_built_in_checks_is_a_parameter():
    """The dialog's x (P6, hours) and DCMA's 44 days are parameters: the default is the standard's
    value, another value moves the count. Float 400 h (C10 = 40 d), 353 h (44.1 d), 352 h, 160 h (20 d)."""
    import dataclasses

    s = snap(
        [
            todo("A", clndr_id="C10", total_float_hr_cnt="400"),
            todo("B", total_float_hr_cnt="353"),
            todo("C", total_float_hr_cnt="352"),
            todo("D", total_float_hr_cnt="160"),
        ]
    )

    def with_limit(std, metric_id, **params):
        metric = dataclasses.replace(std[metric_id], params=params)
        return run_metric(metric, AnalysisContext(s))

    assert codes(run(P6, "P6-06", s)) == ["A", "B"]  # default x = 352 h
    assert codes(with_limit(P6, "P6-06", limit_hours=200)) == ["A", "B", "C"]
    assert codes(with_limit(P6, "P6-06", limit_hours=400)) == []
    assert codes(run(DCMA, "DCMA-06", s)) == ["B"]  # default 44 d
    assert codes(with_limit(DCMA, "DCMA-06", limit_days=20)) == ["A", "B", "C"]  # 40, 44.1, 44 > 20; D = 20 is not


def test_dcma_06_07_follow_pam_200_1():
    """DCMA-EA PAM 200.1 (Oct 2012) 4.6: "An incomplete task with total float greater than 44 working
    days (2 months) is counted in this metric." 4.7: "An incomplete task with total float less than 0
    working days is included in this metric."

    4.0 excludes completed tasks, LOE, subprojects and milestones: the milestones MH (high float) and
    MN (negative float) are out of numerator and population. Float is in the task's calendar days.
    """
    s = snap(
        [
            todo("A", clndr_id="C10", total_float_hr_cnt="400"),  # 40 d
            todo("B", total_float_hr_cnt="353"),  # 44.1 d
            todo("C", total_float_hr_cnt="352"),  # 44 d
            todo("N", total_float_hr_cnt="-8"),
            todo("MH", task_type="TT_FinMile", target_drtn_hr_cnt="0", total_float_hr_cnt="400"),
            todo("MN", task_type="TT_FinMile", target_drtn_hr_cnt="0", total_float_hr_cnt="-8"),
        ]
    )
    high = run(DCMA, "DCMA-06", s)
    assert (codes(high), high.denominator) == (["B"], 4)
    neg = run(DCMA, "DCMA-07", s)
    assert (codes(neg), neg.denominator) == (["N"], 4)


def test_large_duration_remaining_vs_original():
    s = snap(
        [
            active("A", target_drtn_hr_cnt="800", remain_drtn_hr_cnt="100"),
            todo("B", target_drtn_hr_cnt="360", remain_drtn_hr_cnt="360"),
            todo("M", task_type="TT_FinMile", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0"),
        ]
    )
    assert codes(run(P6, "P6-04", s)) == ["B"]  # remaining > 352 h
    assert run(P6, "P6-04", s).denominator == 2  # milestone out: Ten Six P6 r22.12 report, EPPM 46282 (101248 silent)
    assert codes(run(DCMA, "DCMA-08", s, Baseline.planned(s))) == ["A", "B"]  # baseline > 44 d


BL8 = snap(
    [todo("A", target_drtn_hr_cnt="800"), todo("B", target_drtn_hr_cnt="360"), todo("C", target_drtn_hr_cnt="352")]
)


def test_dcma_08_uses_the_baseline_duration_not_the_re_estimated_one():
    """PAM 200.1 4.8: baseline duration > 44 wd. A was re-estimated to 50 d (still flagged: baseline 100 d);
    B shrank to 10 d (flagged: baseline 45 d); C is 44 d (not above). NEWD (800 h) is not in the baseline: it
    has no baseline duration so it is not flagged, but it stays in the denominator (incomplete, not excluded).
    The milestone is excluded. Without a baseline the check is n/a."""
    s = snap(
        [
            active("A", target_drtn_hr_cnt="400"),
            todo("B", target_drtn_hr_cnt="80"),
            todo("C", target_drtn_hr_cnt="352"),
            todo("M", task_type="TT_FinMile", target_drtn_hr_cnt="0"),
            todo("NEWD", target_drtn_hr_cnt="800"),
        ]
    )
    r = run(DCMA, "DCMA-08", s, Baseline.from_snapshot(BL8))
    assert codes(r) == ["A", "B"]
    assert counts(r) == (2, 4)
    n = run(DCMA, "DCMA-08", s)
    assert (n.status, n.numerator, n.note) == ("n/a", None, "needs a baseline")


# --- progress, resources --------------------------------------------------------------------


def test_invalid_progress_dates():
    s = snap(
        [
            todo("EARLY", early_start_date="2026-02-27 08:00"),
            active("RUN", restart_date="2026-02-26 08:00", reend_date="2026-02-27 17:00"),
            active("LATE", restart_date="2026-02-27 08:00", reend_date="2026-03-05 17:00"),  # not re-scheduled
            done("FUT", act_end_date="2026-03-04 17:00"),
            done("OK"),
            todo("FINE"),
        ]
    )
    # Pro 24 help (101248): in progress = remaining early start before the data date; P6 reports the
    # forecast (P6-10a) and the actual (P6-10b) halves on two lines
    assert codes(run(P6, "P6-10a", s)) == ["EARLY", "LATE", "RUN"]
    assert codes(run(P6, "P6-10b", s)) == ["FUT"]
    assert run(P6, "P6-10a", s).denominator == run(P6, "P6-10b", s).denominator == 5  # OK finished: removed
    assert run(DCMA, "DCMA-09", s).numerator == 3  # DCMA reads the remaining finish: LATE passes


def test_dcma_09_follows_pam_200_1():
    """DCMA-EA PAM 200.1 (Oct 2012) 4.9: "Incomplete tasks that have a forecast start/finish date prior to
    the IMS status date, or has an actual start/finish date beyond the IMS status date are included in
    this metric."

    4.0 excludes LOE, subprojects and milestones. Completed tasks are kept only when they could still
    have an actual date beyond the status date: one finished before it is out of the population.
    """
    s = snap(
        [
            todo("EARLY", early_start_date="2026-02-27 08:00"),  # forecast start before DD: flagged
            active("RUN", restart_date="2026-02-26 08:00", reend_date="2026-02-27 17:00"),  # remaining finish: flagged
            todo("MEARLY", task_type="TT_Mile", target_drtn_hr_cnt="0", early_start_date="2026-02-27 08:00"),
            done("OK"),  # finished 2026-02-13, before DD: out
            done("FUT", act_end_date="2026-03-04 17:00"),  # actual finish beyond DD: flagged
            todo("FINE"),
            todo("LOE", task_type="TT_LOE", early_start_date="2026-02-27 08:00"),
        ]
    )
    r = run(DCMA, "DCMA-09", s)
    # Population: EARLY, RUN, FUT, FINE = 4 (MEARLY milestone, OK done before DD, LOE out).
    assert codes(r) == ["EARLY", "FUT", "RUN"]
    assert (r.numerator, r.denominator) == (3, 4)


def test_resource_or_expense():
    s = snap(
        [todo("R"), todo("E"), todo("NONE"), done("DONE"), todo("M", task_type="TT_Mile", target_drtn_hr_cnt="0")],
        rsrc=["R"],
        costs=["E"],
    )
    assert codes(run(P6, "P6-11", s)) == ["DONE", "NONE"]  # P6 keeps completed activities
    assert codes(run(DCMA, "DCMA-10", s)) == ["NONE"]


def test_dcma_10_is_na_for_a_project_without_resource_assignment():
    """PAM 200.1 §4.10 applies to a resource-loaded schedule. A and B share a file: A has 1 assignment
    (R of R, NONE), B none, and its assignments are not A's: B is n/a, A is 1 of 2."""
    text = with_second_project(
        xer_text([todo("R"), todo("NONE")], rsrc=["R"], project={"proj_short_name": "A"}),
        "B",
        ["X", "Y"],
        "2026-03-02 08:00",
    )
    a = run(DCMA, "DCMA-10", build_snapshot(parse_text(text, source="t.xer"), project_code="A"))
    b = run(DCMA, "DCMA-10", build_snapshot(parse_text(text, source="t.xer"), project_code="B"))
    assert (a.status, counts(a), codes(a)) == ("fail", (1, 2), ["NONE"])
    assert b.status == "n/a" and "resource-loaded" in b.note


def test_dcma_10_resource_loaded_project_flags_the_unassigned_activity():
    s = snap([todo("R"), todo("NONE")], rsrc=["R"])
    r = run(DCMA, "DCMA-10", s)
    assert (r.status, counts(r), codes(r)) == ("fail", (1, 2), ["NONE"])


def test_dcma_10_labour_hours_without_assignment_still_fail_with_a_note():
    """Hours budgeted on the tasks (TASK.target_work_qty) but no TASKRSRC row: the export is suspect, not the
    schedule unloaded. Both tasks are counted: 2 of 2."""
    s = snap([todo("H", target_work_qty="40"), todo("NONE")])
    r = run(DCMA, "DCMA-10", s)
    assert (r.status, counts(r)) == ("fail", (2, 2))
    assert "labour hours on tasks but no resource assignment" in r.note


def test_dcma_10_expenses_alone_do_not_load_the_project():
    s = snap([todo("E"), todo("NONE")], costs=["E"])
    assert run(DCMA, "DCMA-10", s).status == "n/a"


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


def test_bei_p6_counts_due_in_the_baseline_dcma_in_the_schedule():
    bl = Baseline.from_snapshot(BL)
    p6 = run(P6, "P6-13", NOW, bl)
    # P6 Professional report: every baseline activity counts (101248 says those finishing before the
    # data date, but report R1, docs/standards.md, divides by all of them); NEW is not one
    assert (p6.numerator, p6.denominator) == (2, 4)  # A, B done / A, B, C, D
    gone = snap([done("A", act_end_date="2026-02-26 17:00"), todo("D", early_end_date="2026-04-29 17:00")])
    r = run(P6, "P6-13", gone, bl)
    assert (r.numerator, r.denominator) == (1, 4)  # B and C deleted since the baseline: still counted
    assert "2 of them no longer in the schedule" in r.note
    # DCMA-EA PAM 200.1 (Oct 2012) 3.1.2.4: "Tasks missing baseline finish dates are included in the
    # denominator." (step 1: "Filter out Level of Effort (LOE) tasks, summary tasks, and zero duration
    # tasks (milestones)."). NEW has no baseline finish: due, not finished -> A, B done / A, B, C, NEW.
    dcma = run(DCMA, "DCMA-14", NOW, bl)
    assert (dcma.numerator, dcma.denominator) == (2, 4)
    assert dcma.value == pytest.approx(2 / 4)


def test_missed_tasks_and_late_activities():
    bl = Baseline.from_snapshot(BL)
    r = run(DCMA, "DCMA-11", NOW, bl)
    assert codes(r) == ["B", "C"] and "1 without baseline dates" in r.note  # NEW is not in BL
    assert codes(run(P6, "P6-12", NOW, bl)) == ["C"]  # B: Sat 17:00 vs Fri 17:00, no working time
    # P6 Professional report: completed activities are out (Late Activities checks the Large Durations
    # population); no baseline -> against the planned finish
    now = snap(
        [
            done("A", act_end_date="2026-03-02 17:00"),  # a working day after its baseline finish
            todo("NEW", early_end_date="2026-03-10 17:00", target_end_date="2026-03-09 17:00"),
            todo("NEW2", early_end_date="2026-03-10 17:00", target_end_date="2026-03-10 17:00"),
        ]
    )
    r = run(P6, "P6-12", now, bl)
    assert codes(r) == ["NEW"] and r.denominator == 2


def test_dcma_11_follows_pam_200_1():
    """DCMA-EA PAM 200.1 (Oct 2012) 4.11: a task is due when its baseline finish is on or before the status
    date; it is missed when its actual or forecast finish is after the baseline finish. The base is the
    tasks "not missing baseline start or finish dates". 4.0 leaves out completed tasks, LOE, summary tasks and
    milestones; 4.11 counts actual finishes, so completed tasks stay (4.11 overrides 4.0 there).

    UNRESOLVED: the pamphlet's Finish Variance is working time; the calendar date is compared here.
    """
    st = "2026-02-02 08:00"
    s = snap(
        [
            done("A", act_end_date="2026-02-26 17:00", target_start_date=st, target_end_date="2026-02-27 17:00"),
            done("B", act_end_date="2026-02-28 17:00", target_start_date=st, target_end_date="2026-02-27 17:00"),
            todo("C", early_end_date="2026-03-20 17:00", target_start_date=st, target_end_date="2026-02-27 17:00"),
            todo("E", early_end_date="2026-03-02 17:00", target_start_date=st, target_end_date="2026-03-02 08:00"),
            todo("M", task_type="TT_Mile", target_start_date=st, target_end_date="2026-02-27 17:00"),
            todo("NS", early_end_date="2026-03-20 17:00", target_end_date="2026-02-27 17:00"),
        ]
    )
    r = run(DCMA, "DCMA-11", s, Baseline.planned(s))
    # Data date 2026-03-02 08:00. M is a milestone and NS has no baseline start: out of the base.
    # A, B, C, E have both baseline dates and a baseline finish <= data date: 4 due.
    # A 02-26 <= 02-27 on time; B 02-28 > 02-27 missed; C forecast 03-20 > 02-27 missed;
    # E forecast 03-02 17:00 is the same date as its baseline finish 03-02 08:00: not missed.
    assert codes(r) == ["B", "C"]
    assert (r.numerator, r.denominator) == (2, 4)


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


def test_critical_path_test_does_not_blame_a_completed_mandatory_date():
    # a finished activity cannot absorb a delay: its mandatory date is not listed
    chain = CHAIN[:2] + [dict(CHAIN[2], cstr_type="CS_MANDFIN", cstr_date="2026-03-27 17:00")]
    s = snap(
        chain + [done("D", cstr_type="CS_MANDSTART", cstr_date="2026-02-02 08:00")],
        [("A", "B", "FS", 0), ("B", "Z", "FS", 0)],
    )
    r = run(DCMA, "DCMA-12", s)
    assert r.status == "fail" and codes(r) == ["Z"]


def test_critical_path_test_with_must_finish_by_fails_when_a_mandatory_date_absorbs_the_delay():
    """PAM 4.12 also reads "negative total float" on the completion date. The float to the Must Finish By
    date falls by exactly what the finish moves, so it adds no pass to the finish test, and a Mandatory
    Finish keeps the end's float at 0: Z ends Wed 25 whatever the slip, the test still fails."""
    chain = CHAIN[:2] + [dict(CHAIN[2], cstr_type="CS_MANDFIN", cstr_date="2026-03-25 17:00")]
    s = snap(chain, [("A", "B", "FS", 0), ("B", "Z", "FS", 0)], project={"plan_end_date": "2026-03-25 17:00"})
    r = run(DCMA, "DCMA-12", s)
    assert r.status == "fail" and "moved +0.0 wd" in r.note and codes(r) == ["Z"]


MFB = {"project": {"plan_end_date": "2026-03-25 17:00"}}  # Must Finish By: the float's reference


def test_cpli_uses_the_finish_float():
    # Finish 2026-03-27 = 20 working days from Mon 2026-03-02; total float -16 h = -2 d.
    chain = CHAIN[:2] + [dict(CHAIN[2], total_float_hr_cnt="-16")]
    r = run(DCMA, "DCMA-13", snap(chain, [("A", "B", "FS", 0), ("B", "Z", "FS", 0)], **MFB))
    assert r.value == pytest.approx((20 - 2) / 20)
    assert r.status == "fail"


def test_cpli_needs_a_must_finish_by_date():
    """Without one P6 gives the last activity 0 float: 1.0 whatever the schedule, so n/a."""
    chain = CHAIN[:2] + [dict(CHAIN[2], total_float_hr_cnt="0")]
    r = run(DCMA, "DCMA-13", snap(chain, [("A", "B", "FS", 0), ("B", "Z", "FS", 0)]))
    assert r.status == "n/a" and "Must Finish By" in r.note


def test_calendar_holiday_counts_in_cpl():
    # Same, finishing 2026-04-10: 30 weekdays minus Good Friday (calendar exception) = 29.
    chain = CHAIN[:2] + [dict(CHAIN[2], early_end_date="2026-04-10 17:00")]
    r = run(DCMA, "DCMA-13", snap(chain, [("A", "B", "FS", 0), ("B", "Z", "FS", 0)], **MFB))
    assert "CPL 29 wd" in r.note


def test_cpli_counts_in_working_days_of_the_project_calendar():
    """PAM and Acumen give days without naming a calendar: the project's (C8) here, for the length and the
    float. Z runs on C10: its -16 h are -2 d of 8 h (not -1.6 d), CPL 20 wd -> (20 - 2) / 20."""
    chain = CHAIN[:2] + [dict(CHAIN[2], total_float_hr_cnt="-16", clndr_id="C10")]
    r = run(DCMA, "DCMA-13", snap(chain, [("A", "B", "FS", 0), ("B", "Z", "FS", 0)], **MFB))
    assert r.value == pytest.approx(0.9)
    assert "total float -2 wd" in r.note


# Without a Must Finish By the float is measured against the baseline finish of the end milestone.
A160 = dict(todo("A", **hours(160)), early_end_date="2026-03-27 17:00")  # Mon 2 to Fri 27 Mar: 20 wd


def _end(code="Z", finish="2026-03-27 17:00"):
    return dict(todo(code), **FM, early_end_date=finish)


def _cpli(tasks, preds, baseline_finishes):
    """DCMA-13 on ``tasks`` with a baseline whose activities finish at ``baseline_finishes``."""
    bl = snap([dict(todo(code), early_end_date=finish) for code, finish in baseline_finishes.items()])
    return run(DCMA, "DCMA-13", snap(tasks, preds), Baseline.from_snapshot(bl))


def test_cpli_without_must_finish_by_uses_the_margin_to_the_baseline_finish_of_the_end_milestone():
    """Z ends Fri 27 Mar 17:00 (CPL 20 wd); baseline finish Tue 31 Mar 17:00: Mon 30 + Tue 31 = +2 wd,
    (20 + 2) / 20."""
    r = _cpli([A160, _end()], [("A", "Z", "FS", 0)], {"Z": "2026-03-31 17:00"})
    assert r.value == pytest.approx(1.1) and r.status == "pass"
    assert "margin of Z to its BL finish 2026-03-31: 2 wd" in r.note


def test_cpli_without_must_finish_by_is_below_one_when_the_end_is_after_its_baseline():
    """Baseline finish Wed 25 Mar 17:00, forecast Fri 27: -2 wd, (20 - 2) / 20."""
    r = _cpli([A160, _end()], [("A", "Z", "FS", 0)], {"Z": "2026-03-25 17:00"})
    assert r.value == pytest.approx(0.9) and r.status == "fail"


def test_cpli_takes_the_end_milestone_that_finishes_last():
    """Z1 ends Fri 27 Mar, Z2 (after B, 8 h) Mon 30 Mar: CPL 21 wd to Z2, baseline Wed 1 Apr = +2 wd,
    (21 + 2) / 21; Z1 (+2 wd on 20) would give 1.1."""
    b = dict(todo("B", **hours(8)), early_end_date="2026-03-30 17:00")
    tasks = [A160, b, _end("Z1"), _end("Z2", "2026-03-30 17:00")]
    preds = [("A", "Z1", "FS", 0), ("A", "B", "FS", 0), ("B", "Z2", "FS", 0)]
    r = _cpli(tasks, preds, {"Z1": "2026-03-31 17:00", "Z2": "2026-04-01 17:00"})
    assert r.value == pytest.approx(23 / 21) and "margin of Z2" in r.note


def test_cpli_is_na_without_a_baseline():
    r = run(DCMA, "DCMA-13", snap([A160, _end()], [("A", "Z", "FS", 0)]))
    assert r.status == "n/a" and "baseline" in r.note


def test_cpli_is_na_with_the_planned_dates_baseline():
    """Oracle 47222: the planned finish of a not-started milestone follows its early finish, so the margin
    to it is 0 by construction."""
    s = snap([A160, _end()], [("A", "Z", "FS", 0)])
    r = run(DCMA, "DCMA-13", s, Baseline.planned(s))
    assert r.status == "n/a" and "choose a baseline file" in r.note and "47222" in r.note


def test_cpli_is_na_when_the_end_milestone_has_no_baseline_finish():
    r = _cpli([A160, _end()], [("A", "Z", "FS", 0)], {"A": "2026-03-27 17:00"})
    assert r.status == "n/a" and "baseline finish" in r.note


def test_cpli_is_na_without_an_open_end_milestone():
    r = _cpli(
        [A160, dict(todo("Z"), early_end_date="2026-03-27 17:00")], [("A", "Z", "FS", 0)], {"Z": "2026-03-31 17:00"}
    )
    assert r.status == "n/a" and "milestone" in r.note


def test_cpli_with_must_finish_by_ignores_the_baseline():
    chain = CHAIN[:2] + [dict(CHAIN[2], total_float_hr_cnt="-16")]
    s = snap(chain, [("A", "B", "FS", 0), ("B", "Z", "FS", 0)], **MFB)
    bl = Baseline.from_snapshot(snap([dict(todo("Z"), early_end_date="2026-04-30 17:00")]))
    assert run(DCMA, "DCMA-13", s, bl).value == pytest.approx(0.9)


# --- framework -----------------------------------------------------------------------------


def test_broken_rule_reports_error_not_crash(monkeypatch):
    from xerscope.analysis import rules

    def boom(_context, **_):
        raise RuntimeError("kaput")

    monkeypatch.setitem(rules.RULES, "p6_06_large_float", rules.Rule("p6_06_large_float", boom, "%", ""))
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
    # No milestone passes the successor check; a start milestone must drive something, and a
    # not-started one needs a predecessor too (test_p6_logic_exemptions).
    s = snap([todo("S", task_type="TT_Mile", target_drtn_hr_cnt="0"), todo("A")], [("S", "A", "FS", 0)])
    assert codes(run(P6, "P6-01", s)) == ["A", "S"]  # A: no successor; S: no predecessor
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


def test_recalculated_note_gives_the_latest_early_finish_and_external_dates():
    """Scheduling Results 'Latest Early Finish Date': stored (latest activity finish) against recalculated."""
    s = snap(
        [
            todo("A", early_end_date="2026-03-02 17:00", **hours(8)),
            todo("B", early_start_date="2026-03-03 08:00", early_end_date="2026-03-05 17:00", **hours(8)),
            todo("C", external_early_start_date="2026-03-02 08:00", early_end_date="2026-03-02 17:00", **hours(8)),
        ],
        [("A", "B", "FS", 0)],
    )
    note = run(INTEGRITY, "INT-01", s).note
    assert "latest early finish stored 2026-03-05 17:00, recalculated 2026-03-03 17:00" in note
    assert "1 tasks with external dates" in note


def test_out_of_sequence_progress_is_listed():
    s = snap([todo("A"), active("B"), done("C"), active("D")], [("A", "B", "FS", 0), ("C", "D", "FS", 0)])
    r = run(INTEGRITY, "INT-02", s)
    assert codes(r) == ["B"] and r.denominator == 3  # B, C, D started; D follows a finished C
    assert r.flagged.iloc[0]["ahead_of"] == "A (FS)"


def test_out_of_sequence_follows_the_status_at_the_data_date():
    """P6 log 'Out of sequence activities': started before the predecessor has completed.

    Calibrated on a P6 Check Schedule report: FS predecessor not complete, SS predecessor not started;
    FF and SF links, and a predecessor that completed after the successor's start, are not listed.
    """
    s = snap(
        [
            todo("A"),  # not started, FS -> B: listed
            active("B"),
            active("C", act_start_date="2026-02-23 08:00"),  # started, SS -> D: D started earlier, not listed
            active("D", act_start_date="2026-02-20 08:00"),
            todo("E"),  # not started, SS -> F: listed
            active("F"),
            active("G"),  # not complete, FF -> H: not listed
            active("H"),
            done("I", act_end_date="2026-02-25 17:00"),  # completed after J started, FS -> J: not listed
            active("J", act_start_date="2026-02-23 08:00"),
        ],
        [
            ("A", "B", "FS", 0),
            ("C", "D", "SS", 0),
            ("E", "F", "SS", 0),
            ("G", "H", "FF", 0),
            ("I", "J", "FS", 0),
        ],
    )
    r = run(INTEGRITY, "INT-02", s)
    assert codes(r) == ["B", "F"] and counts(r) == (2, 8)
    assert dict(zip(r.flagged["task_code"], r.flagged["ahead_of"], strict=True)) == {"B": "A (FS)", "F": "E (SS)"}


def test_relationship_loop_lists_the_activities_on_the_loop():
    """P6 log error 'Activities that have invalid relationship loops': A -> B -> C -> A, D hangs off C."""
    s = snap(
        [todo("A"), todo("B"), todo("C"), todo("D"), todo("E")],
        [("A", "B", "FS", 0), ("B", "C", "FS", 0), ("C", "A", "FS", 0), ("C", "D", "FS", 0)],
    )
    r = run(INTEGRITY, "INT-04", s)
    assert codes(r) == ["A", "B", "C"] and counts(r) == (3, 5) and r.status == "fail"
    clean = snap([todo("A"), todo("B")], [("A", "B", "FS", 0)])
    assert counts(run(INTEGRITY, "INT-04", clean)) == (0, 2) and run(INTEGRITY, "INT-04", clean).status == "pass"


def test_log_lists_activities_without_predecessors_or_successors_unfiltered():
    """P6 log warnings: the raw list. P6-01 exempts started activities and skips completed ones."""
    s = snap(
        [todo("M", **SM), todo("A"), todo("B"), active("S"), done("D")],
        [("M", "A", "FS", 0), ("A", "B", "FS", 0)],
    )
    r = run(INTEGRITY, "INT-05", s)
    reasons = dict(zip(r.flagged["task_code"], r.flagged["reason"], strict=True))
    assert reasons == {
        "M": "no predecessor",
        "B": "no successor",
        "S": "no predecessor, no successor",
        "D": "no predecessor, no successor",
    }
    assert counts(r) == (4, 5) and r.status == "info"
    assert codes(run(P6, "P6-01", s)) == ["B", "M", "S"]


def test_log_lists_every_actual_date_after_the_data_date():
    """P6 log warning: 'The activities in which the data date is before the actual date'; no exclusion.

    The data date is Mon 2026-03-02 08:00.
    """
    s = snap(
        [
            active("A", act_start_date="2026-03-05 08:00"),  # started after the data date
            done("B", act_end_date="2026-03-04 17:00"),  # finished after it
            done("C"),  # both actuals in February
            active("L", task_type="TT_LOE", act_start_date="2026-03-05 08:00"),  # LOE: P6-10b leaves it out
            todo("N"),
        ]
    )
    r = run(INTEGRITY, "INT-06", s)
    assert codes(r) == ["A", "B", "L"] and counts(r) == (3, 5) and r.status == "fail"
    assert codes(run(P6, "P6-10b", s)) == ["A", "B"]


def test_unsatisfied_constraint_is_a_constraint_the_recalculated_date_misses():
    """B follows A (8 h each, FS), so its early start is Tue 2026-03-03 08:00 and its early finish Tue 17:00."""
    s = snap(
        [
            todo("A", **hours(8)),
            todo("B", cstr_type="CS_MSOB", cstr_date="2026-03-02 08:00", **hours(8)),  # Start on or before Mon: missed
            todo("C", cstr_type="CS_MSOA", cstr_date="2026-03-02 08:00", **hours(8)),  # no earlier than Mon: met
            todo("D", cstr_type="CS_MSOB", cstr_date="2026-03-10 08:00", **hours(8)),  # met
            todo("E", cstr_type="CS_ALAP", **hours(8)),  # no date to meet
        ],
        [("A", "B", "FS", 0)],
    )
    r = run(INTEGRITY, "INT-07", s)
    assert codes(r) == ["B"] and counts(r) == (1, 3) and r.status == "info"
    assert r.flagged.iloc[0]["unsatisfied"].startswith("Start on or before 2026-03-02 08:00: early start 2026-03-03")


def test_unsatisfied_relationship_is_a_link_the_successor_dates_break():
    """B has a Mandatory start on Mon 2026-03-02, while its FS predecessor A (80 h) finishes Fri 2026-03-13 17:00."""
    s = snap(
        [
            todo("A", **hours(80)),
            todo("B", cstr_type="CS_MANDSTART", cstr_date="2026-03-02 08:00", **hours(8)),
            todo("C", **hours(8)),
            todo("D", **hours(8)),
        ],
        [("A", "B", "FS", 0), ("C", "D", "FS", 0)],
    )
    r = run(INTEGRITY, "INT-08", s)
    assert links(r) == [("A", "B")] and counts(r) == (1, 2) and r.status == "info"
    assert (
        r.flagged.iloc[0]["reason"]
        == "successor start 2026-03-02 08:00:00 before predecessor finish 2026-03-13 17:00:00"
    )


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
    assert links(r) == [("A", "B"), ("C", "D")]
    assert r.status == "fail"


def test_decm_out_of_sequence_ignores_a_completed_predecessor():
    # the sheet counts relationships with an incomplete predecessor: a successor started
    # before a predecessor that has since finished is no longer out of sequence
    s = snap(
        [
            done("P1", act_end_date="2026-02-27 17:00"),
            active("S1", act_start_date="2026-02-23 08:00"),
            active("P2", act_start_date="2026-02-23 08:00"),
            active("S2", act_start_date="2026-02-25 08:00"),
        ],
        [("P1", "S1", "FS", 0), ("P2", "S2", "FS", 0)],
    )
    r = run(DECM, "06A212a", s)
    assert links(r) == [("P2", "S2")] and r.denominator == 1


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
    r = run(DECM, "06A501a", now, bl)
    assert codes(r) == ["F", "NEW", "P"] and "2 of 5 tasks" in r.note
    assert codes(run(DECM, "06A505a", now)) == ["P"]
    r = run(DECM, "06A506a", now)
    assert codes(r) == ["F"] and r.denominator == 1  # of the activities with an actual start


def test_decm_100_percent_is_100_percent():
    """06A505b counts tasks showing 100 % complete without an actual finish. Units % Complete is
    actual / at completion units x 100 (Oracle, Percent Complete Columns of the Activity Table):
    19,999 of 20,000 h is 99.995 %, not complete. Rounded to 2 decimals it read 100.0 and was
    counted."""
    s = snap(
        [
            active("U", complete_pct_type="CP_Units", act_work_qty="19999", remain_work_qty="1"),
            active("C", complete_pct_type="CP_Phys", phys_complete_pct="100"),
        ]
    )
    assert s.by_code.at["U", "pct_complete"] == pytest.approx(99.995, abs=1e-9)
    r = run(DECM, "06A505b", s)
    assert codes(r) == ["C"] and r.denominator == 1


def test_decm_actuals_changed_needs_the_previous_update():
    from xerscope.store import SnapshotStore

    # DECM compares status periods: the update 28 days earlier, not last week's
    w1 = snap([active("A"), done("B")])  # data date 2 March
    w2 = snap([active("A", act_start_date="2026-02-24 08:00"), done("B")], data_date="2026-03-30 08:00")
    store = SnapshotStore([w1, w2])
    r = run_metric(DECM["06A504a"], AnalysisContext(store[1], store))
    assert codes(r) == ["A"] and r.denominator == 2
    assert run_metric(DECM["06A504b"], AnalysisContext(store[1], store)).numerator == 0
    assert run_metric(DECM["06A504a"], AnalysisContext(w2)).status == "n/a"
    week = snap([active("A", act_start_date="2026-02-24 08:00"), done("B")], data_date="2026-03-09 08:00")
    assert run_metric(DECM["06A504a"], AnalysisContext(week, SnapshotStore([w1, week]))).status == "n/a"  # 7 days


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


def test_decm_riding_the_status_date_takes_the_status_period_as_a_parameter():
    from xerscope.analysis.audit import with_settings
    from xerscope.store import SnapshotStore

    # Two weekly updates: R's forecast start is the data date in both. The 28-day default has no earlier
    # update to compare with; a 7-day period compares the two and R rides.
    w1 = snap([todo("R", early_start_date="2026-03-02 08:00")])
    w2 = snap([todo("R", early_start_date="2026-03-09 08:00")], data_date="2026-03-09 08:00")
    store = SnapshotStore([w1, w2])
    context = AnalysisContext(store[1], store)
    default = run_metric(DECM["06A506c"], context)
    assert default.status == "n/a" and "28 days older" in default.note
    shorter = run_metric(with_settings(DECM["06A506c"], params={"status_period_days": 7}), context)
    assert codes(shorter) == ["R"] and counts(shorter) == (1, 1)
    assert run_metric(with_settings(DECM["06A506c"], params={"status_period_days": 8}), context).status == "n/a"


def test_decm_riding_the_status_date_started_work():
    from xerscope.store import SnapshotStore

    # Started a month ago in both updates. S keeps 40 h remaining (5 wd) while the data date
    # moved a month: its finish slid with the status date. M went from 40 h to 16 h: progress.
    m1 = snap(
        [
            active("S", act_start_date="2026-02-23 08:00", remain_drtn_hr_cnt="40"),
            active("M", act_start_date="2026-02-23 08:00", remain_drtn_hr_cnt="40"),
        ]
    )
    m2 = snap(
        [
            active("S", act_start_date="2026-02-23 08:00", remain_drtn_hr_cnt="40"),
            active("M", act_start_date="2026-02-23 08:00", remain_drtn_hr_cnt="16"),
        ],
        data_date="2026-04-06 08:00",
    )
    store = SnapshotStore([m1, m2])
    r = run_metric(DECM["06A506c"], AnalysisContext(store[1], store))
    assert codes(r) == ["S"] and r.denominator == 2
    assert r.flagged.set_index("task_code").at["S", "reason"] == "remaining duration unchanged"


def test_decm_open_ends_on_a_progressed_schedule():
    # D finished; S started with an FS predecessor and no successor: open finish (started
    # tasks count); T not started, FF-only predecessor: open start. Z, the baseline's last
    # finish, is exempt. The baseline here is the file's own current dates.
    s = snap(
        [
            done("D"),
            active("S", early_end_date="2026-03-13 17:00"),
            todo("T", early_end_date="2026-03-13 17:00"),
            todo("Z", early_start_date="2026-03-16 08:00", early_end_date="2026-03-20 17:00"),
        ],
        [("D", "S", "FS", 0), ("D", "T", "FF", 0), ("T", "Z", "FS", 0)],
    )
    r = run(DECM, "06A204b", s, Baseline.from_snapshot(s))
    flagged = r.flagged.set_index("task_code")["reason"]
    assert codes(r) == ["S", "T"] and r.denominator == 3  # D is complete: out of the population
    assert flagged["S"].startswith("open finish") and flagged["T"].startswith("open start")


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


def test_decm_project_start_exemption_does_not_move_once_work_is_done():
    # D (finished) is the project's first start in the baseline; B, next in line and
    # without a predecessor, is an open start, not the project start.
    s = snap(
        [
            done("D", target_start_date="2026-02-02 08:00", target_end_date="2026-02-06 17:00"),
            todo("B", target_start_date="2026-02-09 08:00", target_end_date="2026-02-13 17:00"),
            todo("C", target_start_date="2026-02-16 08:00", target_end_date="2026-02-20 17:00"),
        ],
        [("B", "C", "FS", 0)],
    )
    r = run(DECM, "06A204b", s, Baseline.from_snapshot(s))
    assert "B" in codes(r)  # open start
    assert "C" not in codes(r)  # the last finish of the whole baseline: exempt


def test_actuals_changed_counts_a_removed_date_on_both_sides():
    """A loses its actual start, B's moves: 2 of the 2 activities dated in either update
    (the share was 200 % when the denominator counted only today's dates)."""
    from xerkit import active, todo

    from xerscope.analysis import AnalysisContext
    from xerscope.store import SnapshotStore

    a = snap([active("A"), active("B"), todo("C")])
    b = snap([todo("A"), active("B", act_start_date="2026-02-24 08:00"), todo("C")], data_date="2026-03-30 08:00")
    store = SnapshotStore([a, b])
    out = run_metric(DECM["06A504a"], AnalysisContext(store[1], store))
    assert sorted(out.flagged["task_code"]) == ["A", "B"] and (out.numerator, out.denominator) == (2, 2)


# --- no data date ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("std", "metric"), [(P6, "P6-13"), (DCMA, "DCMA-11"), (DCMA, "DCMA-12"), (DCMA, "DCMA-13"), (DCMA, "DCMA-14")]
)
def test_data_date_checks_are_na_without_a_data_date(std, metric):
    s = snap(
        [done("A"), active("B"), todo("C", early_end_date="2026-03-20 17:00")],
        [("A", "B", "FS", 0), ("B", "C", "FS", 0)],
        project={"last_recalc_date": "", "plan_start_date": ""},
    )
    assert s.data_date is None
    r = run(std, metric, s, Baseline.planned(s))
    assert r.status == "n/a" and "status date" in r.note


def test_decm_out_of_sequence_without_incomplete_activity_finds_nothing():
    s = snap([done("A"), done("B")], [("A", "B", "FS", 0)])
    r = run(DECM, "06A212a", s)
    assert r.status != "error" and r.numerator == 0
