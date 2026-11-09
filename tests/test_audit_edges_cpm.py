"""Software audit of the CPM engine (analysis/cpm.py): robustness, termination, determinism,
complexity, caching. Not P6 semantics.

Every case is a schedule built with xerkit. A test that documents a defect is marked
``xfail(strict=True, reason="AUDIT-CPM-nn: ...")``; the others pin behaviour that is correct.
Findings: see the audit report (findings_cpm.md) for the table these IDs refer to.
"""

from __future__ import annotations

import dataclasses
import random
import signal
import sys
import time
from contextlib import contextmanager

import pandas as pd
import pytest
from rulekit import STANDARDS, codes, run
from xerkit import SM, active, done, hours, snap, todo, with_second_project, xer_text

from xerscope.analysis.cpm import (
    RESULT_COLS,
    CycleError,
    Schedule,
    ScheduleError,
    compare_with_stored,
    critical_path_test,
    schedule,
)
from xerscope.xer import Snapshot, XerError, build_snapshot, parse_text

T = pd.Timestamp
DD = T("2026-03-02 08:00")


@contextmanager
def deadline(seconds: int):
    """Fail instead of hanging: a suspected infinite loop is cut by SIGALRM."""

    def _timeout(signum, frame):
        raise TimeoutError(f"no answer within {seconds} s")

    previous = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def chain(n: int, extra_links: int = 0, seed: int = 0, duration_hr: str = "1"):
    """An FS chain of ``n`` one-hour activities plus ``extra_links`` random forward links (a DAG)."""
    rnd = random.Random(seed)
    tasks = [todo(f"T{i:06d}", target_drtn_hr_cnt=duration_hr, remain_drtn_hr_cnt=duration_hr) for i in range(n)]
    links = [(f"T{i:06d}", f"T{i + 1:06d}", "FS", 0) for i in range(n - 1)]
    for _ in range(extra_links):
        j = rnd.randrange(1, n)
        i = rnd.randrange(0, j)
        links.append((f"T{i:06d}", f"T{j:06d}", rnd.choice(["FS", "SS", "FF", "SF"]), rnd.choice([0, 1, 2, -1])))
    return tasks, links


# --- cycles ----------------------------------------------------------------------------------------


def test_self_loop_raises_cycle_error_naming_the_activity():
    s = snap([todo("A"), todo("B")], [("A", "A", "FS", 0), ("A", "B", "FS", 0)])
    with deadline(10), pytest.raises(CycleError) as info:
        schedule(s)
    assert info.value.members == ("A",)  # B is downstream of the loop, not on it


def test_two_cycle_with_negative_lags_raises_not_hangs():
    s = snap([todo("A"), todo("B")], [("A", "B", "FS", -8), ("B", "A", "FS", -8)])
    with deadline(10), pytest.raises(CycleError) as info:
        schedule(s)
    assert info.value.members == ("A", "B")


def test_cycle_of_20000_activities_is_found_iteratively_and_quickly():
    """Tarjan is iterative: no RecursionError on a loop as long as the whole network."""
    n = 20_000
    tasks = [todo(f"A{i:05d}", **hours(1)) for i in range(n)]
    links = [(f"A{i:05d}", f"A{(i + 1) % n:05d}", "FS", 0) for i in range(n)]
    s = snap(tasks, links)
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(1000)
    try:
        start = time.perf_counter()
        with deadline(60), pytest.raises(CycleError) as info:
            schedule(s)
    finally:
        sys.setrecursionlimit(limit)
    assert len(info.value.members) == n
    assert time.perf_counter() - start < 30
    assert str(info.value).endswith("…")  # the message is truncated, the members are complete


def test_loop_entirely_among_finished_activities_still_blocks_the_whole_recalculation():
    """P6 refuses to schedule a loop whatever the status; the engine does the same. The open
    activity C downstream is left without dates (see 'Questions au métier')."""
    s = snap([done("A"), done("B"), todo("C")], [("A", "B", "FS", 0), ("B", "A", "FS", 0), ("B", "C", "FS", 0)])
    with deadline(10), pytest.raises(CycleError) as info:
        schedule(s)
    assert info.value.members == ("A", "B")


def test_loop_through_a_level_of_effort_is_not_a_loop_for_the_engine():
    """LOE links are outside the network (documented), so A -> L (LOE) -> A schedules."""
    s = snap(
        [todo("A"), todo("L", task_type="TT_LOE")], [("A", "L", "SS", 0), ("L", "A", "FS", 0), ("L", "L", "FS", 0)]
    )
    with deadline(10):
        f = schedule(s).frame
    assert f.at["A", "es"] == DD and f.at["L", "es"] == DD  # the LOE spans A; the self-link is dropped


def test_external_predecessor_is_namespaced_and_cannot_close_a_loop():
    """A predecessor in another project of the file is ``[ext]<task_id>``; a local A -> B -> A loop
    next to it is still reported with the local names only."""
    text = xer_text([todo("A"), todo("B")], [("A", "B", "FS", 0), ("100", "A", "FS", 0, "2")])
    text = with_second_project(text, "P2", ["X"], "2026-03-02 08:00")
    s = build_snapshot(parse_text(text, source="t.xer"))
    assert "[ext]100" in set(s.relationships["pred_code"])
    f = schedule(s).frame
    assert list(f.index) == ["A", "B"] and f.at["B", "es"] == T("2026-03-16 08:00")
    looped = xer_text([todo("A"), todo("B")], [("A", "B", "FS", 0), ("100", "A", "FS", 0, "2"), ("B", "A", "FS", 0)])
    looped = with_second_project(looped, "P2", ["X"], "2026-03-02 08:00")
    with deadline(10), pytest.raises(CycleError) as info:
        schedule(build_snapshot(parse_text(looped, source="t.xer")))
    assert info.value.members == ("A", "B")


def test_cycle_is_reported_not_raised_by_the_critical_path_test_and_int_04():
    s = snap([todo("A"), todo("B"), todo("C")], [("A", "B", "FS", 0), ("B", "A", "FS", 0), ("B", "C", "FS", 0)])
    result = critical_path_test(s, 600)
    assert not result.passed and "logic loop" in result.note
    int_04 = run(STANDARDS["INTEGRITY"], "INT-04", s)
    assert codes(int_04) == ["A", "B"] and int_04.numerator == 2
    with pytest.raises(CycleError):  # the comparison has no typed fallback: its callers catch CycleError
        compare_with_stored(s)


# --- deep chains, complexity ----------------------------------------------------------------------


def test_chain_of_10000_activities_schedules_without_recursion():
    tasks, links = chain(10_000, extra_links=2_500)
    s = snap(tasks, links)
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(1000)
    try:
        start = time.perf_counter()
        with deadline(60):
            sch = schedule(s)
    finally:
        sys.setrecursionlimit(limit)
    elapsed = time.perf_counter() - start
    f = sch.frame
    assert len(f) == 10_000 and f["longest_path"].any()
    assert f.at["T009999", "ef"] >= f.at["T000000", "ef"] + pd.Timedelta(hours=9_999)
    assert elapsed < 40, elapsed


def test_scaling_from_1k_to_4k_is_close_to_linear():
    """Exponent of the wall time between N = 1,000 and 4,000 (chain + N/4 random links); the 16k and
    64k points are in the audit script cpm_scaling.py (measured 0.97 - 1.05)."""
    times = {}
    for n in (1_000, 4_000):
        s = snap(*chain(n, extra_links=n // 4))
        start = time.perf_counter()
        with deadline(60):
            schedule(s)
        times[n] = time.perf_counter() - start
    import math

    exponent = math.log(times[4_000] / times[1_000]) / math.log(4)
    assert exponent < 1.5, times


# --- odd links -----------------------------------------------------------------------------------


def test_duplicate_fs_and_ss_links_keep_the_tighter_bound():
    s = snap([todo("A", **hours(16)), todo("B", **hours(8))], [("A", "B", "FS", 0), ("A", "B", "SS", 0)])
    f = schedule(s).frame
    assert f.at["B", "es"] == T("2026-03-04 08:00") and f.at["A", "tf_hr"] == 0 and f.at["B", "tf_hr"] == 0


def test_identical_duplicate_links_change_nothing():
    one = schedule(snap([todo("A", **hours(16)), todo("B", **hours(8))], [("A", "B", "FS", 0)])).frame
    two = schedule(snap([todo("A", **hours(16)), todo("B", **hours(8))], [("A", "B", "FS", 0)] * 2)).frame
    assert one.equals(two)


def test_lag_longer_than_the_predecessor_duration():
    s = snap([todo("A", **hours(8)), todo("B", **hours(8))], [("A", "B", "SS", 80)])
    f = schedule(s).frame
    assert f.at["B", "es"] == T("2026-03-16 08:00") and f.at["A", "tf_hr"] == 0 and f.at["B", "ff_hr"] == 0


def test_lead_longer_than_the_predecessor_duration_stops_at_the_data_date():
    s = snap([todo("A", **hours(8)), todo("B", **hours(8))], [("A", "B", "FS", -80)])
    f = schedule(s).frame
    assert f.at["B", "es"] == DD and f.at["A", "es"] == DD
    assert f.at["A", "tf_hr"] == 0 and f.at["B", "tf_hr"] == 0
    assert f.at["A", "ff_hr"] == 72  # to the successor bound (UNRESOLVED vs MPXJ's 0, docs/cpm.md)


def test_lag_on_a_zero_duration_milestone():
    s = snap([todo("M", **SM), todo("B", **hours(8))], [("M", "B", "FS", 16)])
    f = schedule(s).frame
    assert (f.at["M", "es"], f.at["M", "ef"]) == (DD, DD) and f.at["B", "es"] == T("2026-03-04 08:00")
    assert f.at["M", "tf_hr"] == 0 and f.at["M", "ff_hr"] == 0


def test_unknown_relationship_type_is_ignored_on_both_passes_and_reported():
    """AUDIT-CPM-06. A ``PR_XX`` type has no rule in either pass: the engine leaves the link out
    (``_network``) instead of letting ``pred_bounds`` read it as SF (which moved B to Tuesday) while
    the backward pass dropped it. Reported by the engine, or by the model when it drops the row first."""
    tasks = [todo("A", cstr_type="CS_MSOA", cstr_date="2026-03-03 08:00", **hours(16)), todo("B", **hours(8))]
    s = snap(tasks, [("A", "B", "XX", 8)])
    sch = schedule(s)
    unlinked = schedule(snap(tasks)).frame
    assert sch.frame.at["B", "es"] == DD  # not the SF reading
    assert sch.frame.equals(unlinked)
    assert any("XX" in w for w in sch.warnings + s.warnings)


# --- trivial networks ----------------------------------------------------------------------------


def test_no_relationships_every_activity_starts_at_the_data_date():
    f = schedule(snap([todo("A"), todo("B", **hours(8))])).frame
    assert (f["es"] == DD).all() and f.at["A", "tf_hr"] == 0 and f.at["B", "tf_hr"] == 72
    assert f["longest_path"].tolist() == [True, False]


def test_single_activity():
    sch = schedule(snap([todo("A", **hours(8))]))
    assert sch.finish == T("2026-03-02 17:00") and sch.frame.at["A", "longest_path"]


def test_all_activities_finished_empty_forward_pass():
    """AUDIT-CPM-09: no open activity, so no float: NaN in a float column, not None in an object one."""
    sch = schedule(snap([done("A"), done("B")], [("A", "B", "FS", 0)]))
    assert sch.frame["tf_hr"].isna().all() and sch.frame["tf_hr"].dtype == float
    assert sch.frame["ff_hr"].isna().all() and not sch.frame["longest_path"].any()
    assert sch.finish == DD  # the carried date, not the last actual finish (see 'Questions au métier')
    assert critical_path_test(snap([done("A")]), 600).passed is False  # "critical path is not defined"


def test_only_wbs_summary_rows_gives_an_empty_schedule_not_a_key_error():
    """AUDIT-CPM-03: explicit result columns, so a snapshot without a schedulable activity is an empty Schedule."""
    s = snap([todo("W", task_type="TT_WBS")])
    assert s.activities.empty
    sch = schedule(s)
    assert sch.frame.empty and sch.finish is None and sch.assignments.empty
    assert list(sch.frame.columns) == RESULT_COLS[1:] and sch.frame.index.name == "task_code"
    assert not critical_path_test(s, 600).passed
    assert run(STANDARDS["INTEGRITY"], "INT-01", s).numerator == 0


def test_empty_task_table_is_a_typed_parse_error():
    with pytest.raises(XerError):
        snap([])


def test_only_level_of_effort():
    sch = schedule(snap([todo("L", task_type="TT_LOE")]))
    assert sch.finish is None and sch.frame.at["L", "es"] == DD and sch.frame.at["L", "tf_hr"] == 0


# --- constraints against logic -----------------------------------------------------------------


def test_mandatory_start_violating_logic_gives_negative_float_no_exception():
    s = snap(
        [todo("A", **hours(40)), todo("B", cstr_type="CS_MANDSTART", cstr_date="2026-03-03 08:00", **hours(8))],
        [("A", "B", "FS", 0)],
    )
    f = schedule(s).frame
    assert f.at["A", "tf_hr"] == -32 and f.at["A", "lf"] == T("2026-03-02 17:00")
    assert f.at["B", "es"] == T("2026-03-03 08:00") and f.at["B", "tf_hr"] == 0


# --- determinism -------------------------------------------------------------------------------


def _network(seed: int):
    from test_cpm_properties import random_network

    return random_network(seed, n=40)


@pytest.mark.parametrize("seed", range(6))
def test_same_snapshot_twice_and_two_parses_are_bit_for_bit_equal(seed):
    tasks, links = _network(seed)
    s1, s2 = snap(tasks, links), snap(tasks, links)
    a, b, c = schedule(s1), schedule(s2), schedule(s1)
    assert a is not c and a.frame.equals(c.frame)  # the plain recalculation is cached, handed out as copies
    for x, y in ((a.frame, b.frame), (a.assignments, b.assignments)):
        assert list(x.columns) == list(y.columns) and list(x.index) == list(y.index) and x.equals(y)
    assert a.finish == b.finish and a.warnings == b.warnings


@pytest.mark.parametrize("seed", range(6))
def test_relationship_row_order_does_not_change_the_result(seed):
    tasks, links = _network(seed)
    shuffled = list(links)
    random.Random(seed).shuffle(shuffled)
    a = schedule(snap(tasks, links)).frame
    b = schedule(snap(tasks, shuffled)).frame
    c = schedule(snap(tasks, list(reversed(links)))).frame
    assert a.equals(b) and a.equals(c)


def test_result_rows_follow_the_task_table_order_not_the_topological_order():
    s = snap([todo("C"), todo("B"), todo("A")], [("A", "B", "FS", 0), ("B", "C", "FS", 0)])
    assert list(schedule(s).frame.index) == ["C", "B", "A"]


# --- caching ------------------------------------------------------------------------------------


def test_cache_hands_out_copies_of_one_plain_recalculation():
    """The plain recalculation is computed once and cached on the snapshot (``plain``); every caller
    gets its own copy of it. A delayed run is neither cached nor marked plain."""
    s = snap([todo("A"), todo("B")], [("A", "B", "FS", 0)])
    plain = schedule(s)
    again = schedule(s, extra_hours={})
    assert again is not plain and again.frame is not plain.frame and again.frame.equals(plain.frame)
    cached = s._xs_schedule
    assert plain.plain and again.plain and cached.plain
    assert plain.frame is not cached.frame and plain.warnings is not cached.warnings
    assert not schedule(s, extra_hours={"A": 8}).plain and s._xs_schedule is cached
    assert compare_with_stored(s) is not compare_with_stored(s)  # each caller gets a copy
    assert Snapshot.__dataclass_params__.frozen and Schedule.__dataclass_params__.frozen


def test_mutating_the_returned_frame_does_not_change_the_cached_result():
    """AUDIT-CPM-04: ``schedule`` returns a copy of the cached Schedule, and the Schedule is frozen."""
    s = snap([todo("A"), todo("B")], [("A", "B", "FS", 0)])
    first = schedule(s)
    first.frame.loc["A", "tf_hr"] = 999.0
    first.warnings.append("edited by a caller")
    first.assignment_minutes["x"] = 1.0
    again = schedule(s)
    assert again.frame.at["A", "tf_hr"] == 0 and again.warnings == [] and again.assignment_minutes == {}
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.finish = DD


def test_a_changed_snapshot_is_a_new_snapshot_with_its_own_recalculation():
    """AUDIT-CPM-05: the Snapshot is frozen, so a table cannot be swapped under a cached run; a change
    goes through ``dataclasses.replace``, which starts with an empty cache and sees the new durations.
    (An in-place edit of a table is outside the contract: docs/cpm.md, Performance.)"""
    s = snap([todo("A", **hours(8)), todo("B", **hours(8))], [("A", "B", "FS", 0)])
    assert schedule(s).frame.at["A", "ef"] == T("2026-03-02 17:00")
    longer = s.tasks.copy()
    longer.loc[longer["task_code"] == "A", "remain_drtn_hr_cnt"] = 80.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.tasks = longer
    edited = dataclasses.replace(s, tasks=longer)
    assert schedule(edited).frame.at["A", "ef"] == T("2026-03-13 17:00")
    assert schedule(s).frame.at["A", "ef"] == T("2026-03-02 17:00")  # the original keeps its own result


def test_a_replaced_snapshot_starts_with_an_empty_cache():
    s = snap([todo("A", **hours(8))])
    schedule(s)
    fresh = dataclasses.replace(s)
    assert "_xs_schedule" not in fresh.__dict__ and "by_code" not in fresh.__dict__


# --- degenerate inputs ---------------------------------------------------------------------------


def test_negative_remaining_duration_is_read_as_zero_and_reported():
    """AUDIT-CPM-02: remaining -16 h is read as 0 (A is a zero-duration task at the data date, B follows
    at once) and reported, by the engine or by the model when it clamps the value first."""
    s = snap([todo("A", remain_drtn_hr_cnt="-16"), todo("B")], [("A", "B", "FS", 0)])
    sch = schedule(s)
    assert sch.frame.at["A", "es"] == DD and sch.frame.at["A", "ef"] == DD and sch.frame.at["B", "es"] == DD
    assert sch.finish >= DD and sch.frame.at["A", "tf_hr"] == 0
    assert any("negative remaining" in w for w in sch.warnings + s.warnings)


def test_blank_remaining_duration_reads_as_zero():
    f = schedule(snap([todo("A", remain_drtn_hr_cnt=""), todo("B")], [("A", "B", "FS", 0)])).frame
    assert f.at["A", "ef"] == DD and f.at["B", "es"] == DD


def _schedules_or_typed_error(s: Snapshot, members: tuple[str, ...]) -> None:
    """AUDIT-CPM-01: a value the time axis cannot place never escapes as OverflowError. Either the
    engine refuses it (``ScheduleError``, a ``ValueError`` naming the activities) and every caller
    reports instead of crashing, or the model clamped it on load, with a warning, and the run
    completes with finite dates."""
    try:
        sch = schedule(s)
    except ScheduleError as exc:
        assert isinstance(exc, ValueError) and exc.members == members and not isinstance(exc, CycleError)
        for rule in ("INT-01", "INT-03", "INT-04", "INT-07", "INT-08"):  # they report, they do not crash
            checked = run(STANDARDS["INTEGRITY"], rule, s)
            assert not checked.numerator and (rule == "INT-04" or str(exc) in checked.note)
        result = critical_path_test(s, 600)
        assert not result.passed and str(exc) in result.note
        return
    assert s.warnings and sch.frame["ef"].notna().all()


def test_infinite_remaining_duration_reads_as_blank_and_schedules():
    """AUDIT-CPM-01: an infinite number reads as blank on load (#133), so the engine never sees it."""
    s = snap([todo("A", remain_drtn_hr_cnt="inf"), todo("B")], [("A", "B", "FS", 0)])
    assert pd.isna(s.tasks.set_index("task_code").at["A", "remain_drtn_hr_cnt"])
    assert schedule(s).frame["ef"].notna().all()


def test_huge_remaining_duration_is_a_typed_error():
    _schedules_or_typed_error(snap([todo("A", remain_drtn_hr_cnt="1e9")]), ("A",))


def test_infinite_lag_reads_as_zero_and_schedules():
    """AUDIT-CPM-01: an infinite lag reads as blank on load (#133), then 0."""
    s = snap([todo("A"), todo("B")], [("A", "B", "FS", "inf")])
    assert s.relationships["lag_hr"].tolist() == [0.0]
    assert schedule(s).frame["ef"].notna().all()


def test_huge_assignment_duration_is_a_typed_error():
    """Remaining units 1e6 at 1e-6 units per hour: 1e12 h of work on a driving assignment."""
    assignment = {
        "task_code": "A",
        "rsrc_id": "R1",
        "remain_qty": "1e6",
        "remain_qty_per_hr": "1e-6",
        "relag_drtn_hr_cnt": "0",
        "rollup_dates_flag": "Y",
    }
    s = snap([todo("A", task_type="TT_Rsrc"), todo("B")], [("A", "B", "FS", 0)], assign=[assignment])
    _schedules_or_typed_error(s, ("A",))


def test_a_long_remaining_duration_schedules_or_fails_typed():
    """Within the bound, a date the time axis can hold is placed (4e5 h on an 8 h, 7-day calendar: 137
    years); one it cannot (1e6 h: 342 years, past pandas' year 2262) is the same typed error, translated
    from the time axis, not an OutOfBoundsDatetime or OverflowError out of the engine."""
    sch = schedule(snap([todo("A", remain_drtn_hr_cnt="4e5", clndr_id="C7D")]))
    assert sch.frame.at["A", "ef"] > T("2160-01-01") and sch.frame.at["A", "tf_hr"] == 0
    s = snap([todo("A", remain_drtn_hr_cnt="1e6", clndr_id="C7D")])
    with pytest.raises(ScheduleError, match="schedulable range"):
        schedule(s)
    assert "cannot schedule" in run(STANDARDS["INTEGRITY"], "INT-01", s).note
    assert not critical_path_test(s, 600).passed


def test_blank_lag_reads_as_zero():
    f = schedule(snap([todo("A"), todo("B")], [("A", "B", "FS", "")])).frame
    assert f.at["B", "es"] == T("2026-03-16 08:00")


def test_stored_early_dates_missing_do_not_matter():
    f = schedule(snap([todo("A", early_start_date="", early_end_date=""), todo("B")], [("A", "B", "FS", 0)])).frame
    assert f.at["B", "es"] == T("2026-03-16 08:00")


def test_unknown_calendar_falls_back_and_is_flagged_on_the_snapshot():
    s = snap([todo("A", clndr_id="999"), todo("B")], [("A", "B", "FS", 0)])
    assert any("999" in w for w in s.warnings)
    f = schedule(s).frame
    assert f.at["A", "ef"] == T("2026-03-13 17:00")


def test_finished_without_actual_dates_is_warned_and_placed_at_the_data_date():
    sch = schedule(snap([done("A", act_start_date="", act_end_date=""), todo("B")], [("A", "B", "FS", 0)]))
    assert sch.warnings == ["A: complete without actual dates"]
    assert sch.frame.at["A", "es"] == DD and sch.frame.at["B", "es"] == DD


def test_started_without_actual_start_is_warned_and_dated_at_its_remaining_start():
    """AUDIT-CPM-07: the mirror of "complete without actual dates"."""
    sch = schedule(snap([active("A", act_start_date=""), todo("B")], [("A", "B", "FS", 0)]))
    assert sch.warnings == ["A: in progress without an actual start"]
    assert sch.frame.at["A", "es"] == DD == sch.frame.at["A", "remaining_start"]
    assert sch.frame.at["A", "ef"] == T("2026-03-06 17:00") and sch.frame.at["B", "es"] == T("2026-03-09 08:00")


def test_duplicate_activity_id_first_row_wins():
    f = schedule(snap([todo("A"), todo("A", **hours(8)), todo("B")], [("A", "B", "FS", 0)])).frame
    assert list(f.index) == ["A", "B"] and f.at["A", "ef"] == T("2026-03-13 17:00")


# --- float arithmetic -------------------------------------------------------------------------


def test_total_float_is_exact_minutes_divided_by_sixty():
    s = snap(
        [todo("A", **hours(8)), todo("B", cstr_type="CS_MSOA", cstr_date="2026-03-03 08:10", **hours(8))],
        [("A", "B", "FS", 0)],
    )
    f = schedule(s).frame
    # B starts Tue 08:10 (constraint): A may finish up to Tue 08:10, 10 working minutes after its
    # early finish Mon 17:00. The float is 10 min = 1/6 h, not rounded to a tenth or a quarter.
    assert f.at["B", "es"] == T("2026-03-03 08:10") and f.at["A", "lf"] == T("2026-03-03 08:10")
    assert f.at["A", "tf_hr"] * 60 == 10 and f.at["A", "ff_hr"] * 60 == 10
    # Must Finish By 10 working minutes after the early finish (Wed 08:10; a 17:10 would be off the
    # calendar and snap back to 17:00): 10 minutes of float, carried as 1/6 h, not 0.17
    s2 = snap(
        [todo("A", **hours(8)), todo("B", **hours(8))],
        [("A", "B", "FS", 0)],
        project={"plan_end_date": "2026-03-04 08:10"},
    )
    f2 = schedule(s2).frame
    assert f2.at["B", "lf"] == T("2026-03-04 08:10") and f2.at["B", "tf_hr"] * 60 == 10
    gap = compare_with_stored(s2)
    assert gap.loc[(gap["task_code"] == "B") & (gap["field"] == "total_float_hr_cnt"), "gap_hr"].item() == 0.17


@pytest.mark.parametrize(
    "lag_hr,minutes",
    [("0.00816", 0), ("0.008333", 0), ("0.025", 2), ("0.05", 3)],  # 0.49, 0.5 (half to even), 1.5 -> 2, 3
)
def test_sub_minute_lags_round_to_the_minute(lag_hr, minutes):
    f = schedule(snap([todo("A", **hours(8)), todo("B", **hours(8))], [("A", "B", "FS", lag_hr)])).frame
    assert f.at["B", "es"] == T("2026-03-03 08:00") + pd.Timedelta(minutes=minutes)


def test_total_float_equals_late_minus_early_finish_on_the_activity_calendar():
    s = snap([todo("A", clndr_id="C7D", **hours(8)), todo("B", **hours(8))], [("A", "B", "FS", 0)])
    f = schedule(s).frame
    # A ends Mon 16:00 (7-day 08-16); B needs Tue 08:00 at the latest, so A's late finish is Mon 16:00: 0 h
    assert f.at["A", "ef"] == T("2026-03-02 16:00") and f.at["A", "tf_hr"] == 0
    assert f.at["B", "tf_hr"] == 0 and f["ff_hr"].ge(0).all()
