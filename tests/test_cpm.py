"""The CPM engine against P6: real exports to the minute, then each rule by hand.

Sources of the expected values, strongest first:
- P6 itself: the dates P6 stored in Hotel and Terminal (both unstarted, task dependent);
- xerlock's sample: synthetic, its dates come from xerlock's own engine (another tool,
  the only one here using Progress Override);
- the hand cases: worked out from Oracle's documentation. Every one that MPXJ's
  scheduler models is run through it in tests/test_crosscheck_mpxj.py; the others
  (Actual Dates, Progress Override, SS lag from actual start, open ends critical) have
  no independent check and say so.

Hand cases use xerkit's calendars: C8 = Mon-Fri 08-12 / 13-17 with Good Friday
(2026-04-03) off, C7D = 7 days 08-16. Data date Monday 2026-03-02 08:00.
"""

from pathlib import Path

import pandas as pd
import pytest
from xerkit import active, done, snap, todo

from xerscope.analysis.cpm import (
    FIELDS,
    CycleError,
    compare_assignments,
    compare_with_stored,
    critical_path_test,
    schedule,
)
from xerscope.xer import load_snapshot

T = pd.Timestamp
REF = Path(__file__).parent / "reference" / "data"
FM = dict(task_type="TT_FinMile", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0")
SM = dict(task_type="TT_Mile", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0")


def hours(h):
    return dict(target_drtn_hr_cnt=str(h), remain_drtn_hr_cnt=str(h))


def dates(s, code):
    r = schedule(s).frame.loc[code]
    return r["remaining_start"], r["ef"], r["ls"], r["lf"], r["tf_hr"], r["ff_hr"]


# --- real P6 exports: every stored early/late date and float, exactly --------------------------

REFERENCE = {  # file -> minimum number of stored values compared
    "p6viewer/Hotel Project.xer": 25_000,  # P6 6.0
    "p6viewer/TERMINAL BUILDING-AIRPORT.xer": 390,  # P6 5.0
    "pv/20-kW-residential-pv-p6.xer": 150,  # P6 25.12
    "xereditor/sample.xer": 250,  # P6 20.12 (plus 10 LOE, below)
    "xerlock/sample-schedule.xer": 120,  # not P6: synthetic, xerlock's engine (Progress Override)
}

# Stored values another engine wrote and P6 23.12 contradicts (tests/test_p6_heldout.py):
# xerscope follows P6, so these, and only these, may differ. xerlock binds the late dates of
# EW-030 (under way) to its started FS successor; P6 does not (register R9b, H5-06 A1030).
NOT_P6 = {
    "xerlock/sample-schedule.xer": {
        ("EW-030", "late_start_date"),
        ("EW-030", "late_end_date"),
        ("EW-030", "total_float_hr_cnt"),
    }
}


@pytest.mark.reference
@pytest.mark.parametrize("name", REFERENCE)
def test_recalculation_reproduces_the_stored_dates_to_the_minute(name):
    if not (REF / name).exists():
        pytest.skip("reference files missing: uv run python tests/reference/fetch.py")
    s = load_snapshot(REF / name)
    cmp = compare_with_stored(s)
    cmp = cmp[cmp["stored"].notna()]
    bad = cmp[~cmp["agree"]]
    assert len(cmp) >= REFERENCE[name]
    assert set(zip(bad["task_code"], bad["field"], strict=True)) == NOT_P6.get(name, set()), bad.head(20).to_string()


@pytest.mark.reference
@pytest.mark.parametrize(
    "name",
    [
        pytest.param(
            n,
            marks=pytest.mark.xfail(
                strict=True,
                reason="P6 20.12 flags level-of-effort activities on the longest path; xerscope leaves LOE out "
                "(open: see docs/cpm.md, Validation)",
            ),
        )
        if n == "xereditor/sample.xer"
        else n
        for n in REFERENCE
    ],
)
def test_longest_path_matches_p6s_flag(name):
    """Every open activity's computed longest-path membership = P6's driving_path_flag."""
    if not (REF / name).exists():
        pytest.skip("reference files missing: uv run python tests/reference/fetch.py")
    s = load_snapshot(REF / name)
    t = s.activities.set_index("task_code")
    open_ = t[~t["is_complete"]]
    mine = schedule(s).frame.loc[open_.index, "longest_path"]
    assert open_["on_longest_path"].sum() > 0
    assert (mine == open_["on_longest_path"]).all()


@pytest.mark.reference
def test_level_of_effort_dates_reproduce_p6(require_reference):
    """P6 20.12 stored the dates of 10 LOE activities (SS from a task, FF into the next):
    start, finish, late dates and float all reproduced, the only P6 output with LOE at hand."""
    s = load_snapshot(require_reference("xereditor/sample.xer"))
    t = s.activities.set_index("task_code")
    loe = t[t["is_loe"]]
    assert len(loe) == 10
    f = schedule(s).frame.loc[loe.index]
    for mine, theirs in FIELDS:
        got = f.get(mine)
        assert (got.to_numpy() == loe[theirs].to_numpy()).all(), (mine, got.head(3), loe[theirs].head(3))


ASSIGNMENTS = {"p6viewer/Hotel Project.xer": 2278, "p6viewer/TERMINAL BUILDING-AIRPORT.xer": 62}


@pytest.mark.reference
@pytest.mark.parametrize("name", ASSIGNMENTS)
def test_assignment_dates_reproduce_p6(name):
    """TASKRSRC remaining early/late start and finish of every assignment, to the minute:
    activity dates + assignment lag, duration = remaining units / units per hour."""
    if not (REF / name).exists():
        pytest.skip("reference files missing: uv run python tests/reference/fetch.py")
    cmp = compare_assignments(load_snapshot(REF / name))
    assert cmp["taskrsrc_id"].nunique() == ASSIGNMENTS[name]
    bad = cmp[~cmp["agree"]]
    assert bad.empty, bad.head(20).to_string()


@pytest.mark.reference
def test_critical_path_test_lands_on_xerlocks_date():
    """xerlock tests/test_cpm_sample.py: +600 wd on MEP-020 moves MS-030 2026-09-08 -> 2028-12-27."""
    name = "xerlock/sample-schedule.xer"
    if not (REF / name).exists():
        pytest.skip("reference files missing")
    r = critical_path_test(load_snapshot(REF / name), 600)
    assert r.delayed == "MEP-020" and r.passed
    assert "2026-09-08 -> 2028-12-27" in r.note


# --- relationships and lags -------------------------------------------------------------------


def test_fs_chain_starts_next_morning():
    s = snap([todo("A", **hours(16)), todo("B", **hours(8))], [("A", "B", "FS", 0)])
    assert dates(s, "A")[:2] == (T("2026-03-02 08:00"), T("2026-03-03 17:00"))
    assert dates(s, "B") == (
        T("2026-03-04 08:00"),
        T("2026-03-04 17:00"),
        T("2026-03-04 08:00"),
        T("2026-03-04 17:00"),
        0,
        0,
    )
    assert dates(s, "A")[2:4] == (T("2026-03-02 08:00"), T("2026-03-03 17:00"))  # LF = previous evening


@pytest.mark.parametrize(
    "option,start",
    [
        ("rcal_Predecessor", "2026-03-11 08:00"),  # Fri 17:00 + 16 h on C8 = Tue 17:00 -> Wed
        ("rcal_ProjDefault", "2026-03-11 08:00"),  # project calendar is C8 too
        ("rcal_Successor", "2026-03-09 08:00"),  # + 16 h on C7D = Sat + Sun -> Monday
        ("rcal_24Hour", "2026-03-07 09:00"),  # + 16 elapsed hours = Saturday 09:00, a C7D working hour
    ],
)
def test_lag_counted_on_the_calendar_the_project_names(option, start):
    s = snap(
        [
            todo("A", cstr_type="CS_MSOA", cstr_date="2026-03-06 08:00", **hours(8)),
            todo("B", clndr_id="C7D", **hours(8)),
        ],
        [("A", "B", "FS", 16)],
        sched={"sched_calendar_on_relationship_lag": option},
    )
    assert dates(s, "A")[1] == T("2026-03-06 17:00")
    assert dates(s, "B")[0] == T(start)


def test_ss_ff_sf():
    s = snap(
        [todo("A", **hours(40)), todo("B", **hours(16)), todo("C", **hours(8)), todo("D", **hours(8))],
        [("A", "B", "SS", 8), ("A", "C", "FF", 0), ("A", "D", "SF", 16)],
    )
    assert dates(s, "B")[:2] == (T("2026-03-03 08:00"), T("2026-03-04 17:00"))  # Mon 17:00 -> Tue
    assert dates(s, "C")[:2] == (T("2026-03-06 08:00"), T("2026-03-06 17:00"))  # finishes with A
    assert dates(s, "D")[:2] == (T("2026-03-03 08:00"), T("2026-03-03 17:00"))  # finish >= A start + 16 h


def test_holiday_is_skipped():
    s = snap([todo("A", cstr_type="CS_MSOA", cstr_date="2026-04-02 08:00", **hours(16))])
    assert dates(s, "A")[:2] == (T("2026-04-02 08:00"), T("2026-04-06 17:00"))  # Thu, (Good Fri), Mon


def test_milestone_conventions():
    s = snap([todo("A", **hours(8)), todo("FM", **FM), todo("SM", **SM)], [("A", "FM", "FS", 0), ("A", "SM", "FS", 0)])
    assert dates(s, "FM")[:2] == (T("2026-03-02 17:00"),) * 2  # finish milestone: the same evening
    assert dates(s, "SM")[:2] == (T("2026-03-03 08:00"),) * 2  # start milestone: the next morning


# --- constraints ----------------------------------------------------------------------------


def test_start_no_earlier_than():
    s = snap([todo("A", cstr_type="CS_MSOA", cstr_date="2026-03-04 08:00", **hours(8))])
    assert dates(s, "A")[:2] == (T("2026-03-04 08:00"), T("2026-03-04 17:00"))


def test_start_no_later_than_gives_negative_float_to_the_path():
    s = snap(
        [todo("P", **hours(16)), todo("A", cstr_type="CS_MSOB", cstr_date="2026-03-02 08:00", **hours(8))],
        [("P", "A", "FS", 0)],
    )
    a = dates(s, "A")
    assert a[2:5] == (T("2026-03-02 08:00"), T("2026-03-02 17:00"), -16)
    assert dates(s, "P")[3:5] == (T("2026-02-27 17:00"), -16)  # the Friday before the data date


def test_finish_no_later_than():
    s = snap(
        [todo("A", **hours(16)), todo("Z", cstr_type="CS_MEOB", cstr_date="2026-03-02 17:00", **FM)],
        [("A", "Z", "FS", 0)],
    )
    assert dates(s, "Z")[4] == -8 and dates(s, "A")[4] == -8


def test_start_on_is_both_bounds():
    s = snap([todo("A", cstr_type="CS_MSO", cstr_date="2026-03-05 08:00", **hours(8)), todo("B", **hours(40))])
    a = dates(s, "A")
    assert a[0] == T("2026-03-05 08:00") and a[2] == T("2026-03-05 08:00") and a[4] == 0


def test_mandatory_dates_override_logic():
    s = snap(
        [
            todo("P", **hours(16)),
            todo("A", cstr_type="CS_MANDSTART", cstr_date="2026-03-02 08:00", **hours(8)),
            todo("Z", cstr_type="CS_MANDFIN", cstr_date="2026-03-02 17:00", **FM),
        ],
        [("P", "A", "FS", 0), ("P", "Z", "FS", 0)],
    )
    assert dates(s, "A")[:2] == (T("2026-03-02 08:00"), T("2026-03-02 17:00"))  # before P finishes
    assert dates(s, "Z")[1] == T("2026-03-02 17:00")


def test_finish_on_and_finish_on_or_after_delay_the_early_finish():
    for typ in ("CS_MEO", "CS_MEOA"):
        s = snap([todo("A", cstr_type=typ, cstr_date="2026-03-04 17:00", **hours(8)), todo("B", **hours(40))])
        assert dates(s, "A")[:2] == (T("2026-03-04 08:00"), T("2026-03-04 17:00")), typ
    # Finish On also caps the late finish; Finish On or After does not
    assert dates(
        snap([todo("A", cstr_type="CS_MEO", cstr_date="2026-03-04 17:00", **hours(8)), todo("B", **hours(40))]), "A"
    )[3:5] == (T("2026-03-04 17:00"), 0)
    assert dates(
        snap([todo("A", cstr_type="CS_MEOA", cstr_date="2026-03-04 17:00", **hours(8)), todo("B", **hours(40))]), "A"
    )[3:5] == (T("2026-03-06 17:00"), 16)


# --- external dates (relationships to projects not in the database) ---------------------------


def test_external_early_start_bounds_the_start():
    tasks = [todo("A", external_early_start_date="2026-03-04 08:00", **hours(8))]
    s = snap(tasks)
    assert dates(s, "A")[:2] == (T("2026-03-04 08:00"), T("2026-03-04 17:00"))
    assert any("external early start" in w for w in schedule(s).warnings)
    ignored = snap(tasks, sched={"sched_outer_depend_type": "SD_None"})  # "Ignore relationships…"
    assert dates(ignored, "A")[0] == T("2026-03-02 08:00")


def test_external_late_finish_bounds_the_late_dates():
    s = snap([todo("A", external_late_end_date="2026-03-02 17:00", **hours(8)), todo("B", **hours(40))])
    assert dates(s, "A")[3:5] == (T("2026-03-02 17:00"), 0)  # not the project finish (Fri 17:00)


def test_multiple_float_paths_are_reported_not_computed():
    s = snap([todo("A", **hours(8))], sched={"enable_multiple_longest_path_calc": "Y"})
    assert any("multiple float paths" in w for w in schedule(s).warnings)
    assert not any("multiple float paths" in w for w in schedule(snap([todo("A", **hours(8))])).warnings)


def test_constraint_on_an_in_progress_activity_is_reported():
    s = snap([active("A", cstr_type="CS_MEOA", cstr_date="2026-03-20 17:00", remain_drtn_hr_cnt="8")])
    assert dates(s, "A")[1] == T("2026-03-02 17:00")  # actual start kept, remaining from the data date
    assert any("in-progress activities carry a constraint" in w for w in schedule(s).warnings)


def test_secondary_constraint_counts():
    s = snap(
        [
            todo(
                "A",
                cstr_type="CS_MSOA",
                cstr_date="2026-03-03 08:00",
                cstr_type2="CS_MEOB",
                cstr_date2="2026-03-03 12:00",
                **hours(8),
            )
        ]
    )
    # finishes Tue 17:00 but must finish by Tue 12:00: 13:00-17:00 = 4 working hours late
    assert dates(s, "A")[3:5] == (T("2026-03-03 12:00"), -4)


# --- as late as possible, project finish, open ends -----------------------------------------------


def test_alap_uses_its_free_float():
    links = [("A", "Z", "FS", 0), ("B", "Z", "FS", 0)]
    base = [todo("A", **hours(8)), todo("B", **hours(40)), todo("Z", **FM)]
    s = snap(base, links)
    assert dates(s, "A")[4:] == (32, 32)
    s = snap([dict(base[0], cstr_type="CS_ALAP")] + base[1:], links)
    assert dates(s, "A") == (
        T("2026-03-06 08:00"),
        T("2026-03-06 17:00"),
        T("2026-03-06 08:00"),
        T("2026-03-06 17:00"),
        0,
        0,
    )


def test_must_finish_by_sets_the_late_dates():
    s = snap([todo("A", **hours(16))], project={"plan_end_date": "2026-03-06 00:00"})
    a = dates(s, "A")
    assert a[3] == T("2026-03-05 17:00") and a[4] == 16  # Thu evening: 2 days of float
    assert a[5] == 0  # free float runs to the project's own finish


@pytest.mark.parametrize("flag,tf", [("N", 32), ("Y", 0)])
def test_open_ends_critical_option(flag, tf):
    s = snap([todo("A", **hours(8)), todo("B", **hours(40))], sched={"sched_open_critical_flag": flag})
    assert dates(s, "A")[4] == tf


# --- progress ---------------------------------------------------------------------------------

OOS = [todo("A", **hours(16)), active("B", remain_drtn_hr_cnt="8")]  # B started before A


@pytest.mark.parametrize(
    "retained,override,start",
    [
        ("Y", "N", "2026-03-04 08:00"),  # retained logic: remaining work waits for A
        ("N", "Y", "2026-03-02 08:00"),  # progress override: runs from the data date
    ],
)
def test_out_of_sequence_progress(retained, override, start):
    s = snap(OOS, [("A", "B", "FS", 0)], sched={"sched_retained_logic": retained, "sched_progress_override": override})
    assert dates(s, "B")[0] == T(start)


def _ss(flag, lag, links=()):
    # A started Mon 23 Feb 08:00: one working week (40 h) before the data date
    tasks = [todo("P", **hours(16)), active("A", remain_drtn_hr_cnt="40"), todo("B", **hours(8))]
    return dates(snap(tasks, [("A", "B", "SS", lag), *links], sched={"sched_lag_early_start_flag": flag}), "B")[0]


def test_ss_lag_early_start_subtracts_the_expired_lag():
    """Oracle, Schedule Options > "Calculate start-to-start lag from" > Early Start: "The
    expired lag is calculated as the number of workperiods between the actual start and the
    data date. The successor's start date is the predecessor's internal early start plus
    any remaining lag." 80 h lag - 40 h expired = 40 h after the data date."""
    assert _ss("Y", 8) == T("2026-03-02 08:00")  # lag fully expired
    assert _ss("Y", 80) == T("2026-03-09 08:00")  # Mon 2 + 40 h


def test_ss_lag_options_differ_when_the_predecessor_is_held_back():
    """A started out of sequence and waits for P (retained logic): its internal early start
    is Wed 4 08:00. Early Start: + 40 h remaining lag; Actual Start: actual start + 80 h."""
    held = [("P", "A", "FS", 0)]
    assert _ss("Y", 80, held) == T("2026-03-11 08:00")  # Wed 4 08:00 + 40 h = Tue 10 17:00
    assert _ss("N", 80, held) == T("2026-03-09 08:00")  # Mon 23 Feb 08:00 + 80 h = Fri 6 17:00


def test_expected_finish_sets_remaining_work():
    t = [active("A", remain_drtn_hr_cnt="40", expect_end_date="2026-03-04 17:00")]
    assert dates(snap(t, sched={"sched_use_expect_end_flag": "Y"}), "A")[1] == T("2026-03-04 17:00")
    assert dates(snap(t, sched={"sched_use_expect_end_flag": "N"}), "A")[1] == T("2026-03-06 17:00")


@pytest.mark.parametrize(
    "sched,start",
    [
        # Retained Logic: a finished activity passes on only what open work still imposes, so
        # an actual finish after the data date (invalid progress) drives nothing. Same as
        # MPXJ's PrimaveraScheduler (tests/test_crosscheck_mpxj.py).
        ({}, "2026-03-02 08:00"),
        # Actual Dates: the actual dates themselves drive. No independent engine models
        # this option: xerscope's reading of Oracle's description, unconfirmed.
        ({"sched_retained_logic": "N", "sched_progress_override": "N"}, "2026-03-04 08:00"),
    ],
)
def test_actual_finish_after_the_data_date(sched, start):
    s = snap([done("A", act_end_date="2026-03-03 17:00"), todo("B", **hours(8))], [("A", "B", "FS", 0)], sched=sched)
    assert dates(s, "B")[0] == T(start)


def test_level_of_effort_spans_its_drivers():
    s = snap(
        [todo("A", **hours(16)), todo("B", **hours(24)), todo("L", task_type="TT_LOE", **hours(8))],
        [("A", "B", "FS", 0), ("A", "L", "SS", 0), ("L", "B", "FF", 0)],
    )
    r = schedule(s).frame.loc["L"]
    assert (r["es"], r["ef"]) == (T("2026-03-02 08:00"), T("2026-03-06 17:00"))


# --- errors and the critical path test -----------------------------------------------------------


def test_logic_loop_is_reported():
    s = snap([todo("A"), todo("B")], [("A", "B", "FS", 0), ("B", "A", "FS", 0)])
    with pytest.raises(CycleError, match="A"):
        schedule(s)


def test_critical_path_test_shift_in_working_days():
    s = snap(
        [todo("A", **hours(8)), todo("B", **hours(8)), todo("Z", **FM)], [("A", "B", "FS", 0), ("B", "Z", "FS", 0)]
    )
    r = critical_path_test(s, 10)
    assert r.passed and r.shift_h == 80
    assert "2026-03-03 -> 2026-03-17" in r.note  # Tue + 10 working days, weekends skipped


# --- conventions no reference file settles (documented in docs/cpm.md) ----------------------------


def test_late_start_bound_in_non_working_time_shows_the_previous_period_end():
    # Project must finish by Tue 10 00:00 -> B late Mon 09 08:00-17:00; A (SS+8 elapsed h)
    # must start by Mon 09 00:00, a Saturday-night-to-Monday gap: P6 writes the bound's own
    # instant, here the previous period end Fri 06 17:00, the same working minute as Mon
    # 08:00 (P6 23.12 held-out corpus, H3-02 A1240 and 93 other values; register R4).
    s = snap(
        [todo("A", **hours(8)), todo("B", **hours(8))],
        [("A", "B", "SS", 8)],
        project={"plan_end_date": "2026-03-10 00:00"},
        sched={"sched_calendar_on_relationship_lag": "rcal_24Hour"},
    )
    assert dates(s, "B")[2] == T("2026-03-09 08:00")
    a = dates(s, "A")
    assert a[2] == T("2026-03-06 17:00") and a[4] == 40  # one working week of float


@pytest.mark.parametrize("lag,start", [(40, "2026-03-09 08:00"), (8, "2026-03-03 08:00")])
def test_out_of_sequence_work_waits_for_the_unexpired_lag(lag, start):
    """B started before A finished + lag: under Retained Logic its remaining work waits for
    the lag still to run after A's actual finish (Fri 17:00 -> data date Mon 08:00: none
    expired). MPXJ's PrimaveraScheduler gives the same dates (case2 of the MPXJ crosscheck)."""
    s = snap([done("A", act_end_date="2026-02-27 17:00"), active("B", remain_drtn_hr_cnt="8")], [("A", "B", "FS", lag)])
    assert dates(s, "B")[0] == T(start)


# --- P6 Professional 24 options -------------------------------------------------------------------


def test_lag_calendar_defaults_to_the_successor_when_none_is_selected():
    """Oracle: "If you do not select a calendar, Successor Activity Calendar is used"."""
    s = snap(
        [
            todo("A", cstr_type="CS_MSOA", cstr_date="2026-03-06 08:00", **hours(8)),
            todo("B", clndr_id="C7D", **hours(8)),
        ],
        [("A", "B", "FS", 16)],
        sched={"sched_float_type": "FT_FF"},
    )
    assert s.options["lag_calendar"] == "rcal_Successor"
    assert dates(s, "B")[0] == T("2026-03-09 08:00")  # + 16 h on C7D (Sat, Sun)


def test_actual_dates_option_gives_negative_float_to_the_predecessor():
    """Ten Six's illustration of "Actual Dates": B started out of sequence, so the backward
    pass ties A's late finish to B's actual start (Mon 23 Feb): A's float goes negative
    and grows each period it stays open. Retained logic keeps it positive."""
    tasks = [todo("A", **hours(16)), active("B", remain_drtn_hr_cnt="8"), todo("Z", **hours(80))]
    links = [("A", "B", "FS", 0)]
    flags = {
        "actual": {"sched_retained_logic": "N", "sched_progress_override": "N"},
        "retained": {"sched_retained_logic": "Y", "sched_progress_override": "N"},
    }
    actual = snap(tasks, links, sched=flags["actual"])
    assert actual.options["progressed"] == "actual_dates"
    a = dates(actual, "A")
    assert a[3] == T("2026-02-20 17:00") and a[4] == -56  # LF = Fri before B's actual start
    assert dates(actual, "B")[0] == T("2026-03-04 08:00")  # forward pass as retained logic
    assert dates(snap(tasks, links, sched=flags["retained"]), "A")[4] == 56  # to B late start Fri 13


# --- resource-dependent activities -------------------------------------------------------------------

RSRCS = [
    {"rsrc_id": "R7", "rsrc_short_name": "CRANE", "rsrc_type": "RT_Equip", "clndr_id": "C7D"},
    {"rsrc_id": "R8", "rsrc_short_name": "FITTER", "rsrc_type": "RT_Labor", "clndr_id": "C8"},
]


def _asg(code, rsrc, qty, lag=0, driving="Y"):
    """An unstarted assignment with every field P6 exports for one (budgeted = remaining,
    1 unit per hour, lag both planned and remaining), so any reader sees the same thing."""
    return {
        "task_code": code,
        "rsrc_id": rsrc,
        "target_qty": str(qty),
        "remain_qty": str(qty),
        "act_reg_qty": "0",
        "act_ot_qty": "0",
        "target_qty_per_hr": "1",
        "remain_qty_per_hr": "1",
        "target_lag_drtn_hr_cnt": str(lag),
        "relag_drtn_hr_cnt": str(lag),
        "rollup_dates_flag": driving,
    }


def test_resource_dependent_activity_runs_on_its_resources_calendars():
    """Oracle: "Resource dependent activities are scheduled according to the calendars for
    the resources. If multiple resources are assigned [...], the latest finish date of all
    driving resources is used for the early finish date of the activity." The crane works
    7 days (C7D 08-16): 56 h end Sun 8 16:00. The fitter (C8) starts after an 8 h lag."""
    tasks = [todo("A", task_type="TT_Rsrc", **hours(56)), todo("B", **hours(8))]
    s = snap(
        tasks,
        [("A", "B", "FS", 0)],
        resources=RSRCS,
        assign=[_asg("A", "R7", 56), _asg("A", "R8", 16, lag=8), _asg("A", "R8", 400, driving="N")],
    )
    sch = schedule(s)
    a = sch.frame.loc["A"]
    assert a["resource_dependent"]
    assert (a["es"], a["ef"]) == (T("2026-03-02 08:00"), T("2026-03-08 16:00"))  # not Tue 10 (C8)
    assert dates(s, "B")[0] == T("2026-03-09 08:00")
    fitter = sch.assignments[sch.assignments["rsrc"] == "FITTER"].iloc[0]
    assert (fitter["restart"], fitter["reend"]) == (T("2026-03-03 08:00"), T("2026-03-04 17:00"))


def test_task_dependent_activity_keeps_its_own_calendar():
    tasks = [todo("A", **hours(56))]
    s = snap(tasks, resources=RSRCS, assign=[_asg("A", "R7", 56)])
    assert dates(s, "A")[1] == T("2026-03-10 17:00")  # 7 days of C8
    assert not schedule(s).frame.loc["A", "resource_dependent"]


def test_resource_dependent_late_dates_use_the_resource_calendar():
    s = snap(
        [todo("A", task_type="TT_Rsrc", **hours(56))],
        resources=RSRCS,
        assign=[_asg("A", "R7", 56)],
        project={"plan_end_date": "2026-03-15 16:00"},
    )  # Sunday 16:00: a crane working hour
    a = dates(s, "A")
    assert (a[2], a[3]) == (T("2026-03-09 08:00"), T("2026-03-15 16:00"))


def test_task_dependent_assignment_lag_and_own_duration():
    """Assignment lag (relag) after the activity's start; its duration = units / units per hour."""
    s = snap([todo("A", **hours(24))], resources=RSRCS, assign=[_asg("A", "R8", 8, lag=8)])
    a = schedule(s).assignments.iloc[0]
    assert (a["restart"], a["reend"]) == (T("2026-03-03 08:00"), T("2026-03-03 17:00"))
    assert (a["rem_late_start"], a["rem_late_end"]) == (T("2026-03-03 08:00"), T("2026-03-03 17:00"))


@pytest.mark.parametrize("finish_link", ["pred", "succ"])
def test_loe_spans_from_its_start_driver_to_its_finish_driver(finish_link):
    """LOE tied SS to A and FF to C (as a predecessor or a successor): it runs from A's
    start to C's finish, not to the project finish (D runs a week longer)."""
    tasks = [
        todo("A"),
        todo("C"),
        todo("D", target_drtn_hr_cnt="120", remain_drtn_hr_cnt="120"),
        todo("L", task_type="TT_LOE", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0"),
    ]
    links = [("A", "C", "FS", 0), ("A", "D", "FS", 0), ("A", "L", "SS", 0)]
    links.append(("C", "L", "FF", 0) if finish_link == "pred" else ("L", "C", "FF", 0))
    f = schedule(snap(tasks, links)).frame
    assert f.at["L", "es"] == f.at["A", "es"] == pd.Timestamp("2026-03-02 08:00")
    assert f.at["L", "ef"] == f.at["C", "ef"] == pd.Timestamp("2026-03-27 17:00")
    assert schedule(snap(tasks, links)).finish == f.at["D", "ef"] > f.at["L", "ef"]
