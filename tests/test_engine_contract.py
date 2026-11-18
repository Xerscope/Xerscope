"""The engine's error contract on damaged random networks (seeded, so a failure reproduces).

A file that loads is rescheduled or refused by name: ``schedule`` returns a result, or raises
``ScheduleError`` (``CycleError`` for a logic loop), and nothing else. The load itself returns a
snapshot or raises ``XerError``. Each network is a valid random one damaged in one way: a logic
loop, a link of an activity to itself, a duration or a lag that is not finite or out of any
schedule's range, a date no calendar holds or that is not a date, a link type, a calendar or a
status P6 does not write, a status date out of range. Three more reach the engine's own guards,
past the repairs of the load: a delay asked of ``schedule`` that is out of range, and a snapshot
edited after loading with such a lag or remaining duration.
A refusal names the activities at fault, except a date beyond the time axis (year 2262), which a
chain of long durations reaches together: that one names the calendar.
A delay that is not a number (NaN) is not drawn here: its own test below holds that it is refused
like a delay out of range.
The dates of a valid network are held by tests/test_cpm_properties.py; here only the outcome is.
"""

from __future__ import annotations

import dataclasses
import random
import re

import pytest
from rulekit import STANDARDS, codes, run
from test_cpm_properties import random_network
from xerkit import CONSTRAINT_TYPES, active, done, hours, snap, todo, xer_text

from xerscope.analysis.cpm import MAX_HOURS, CycleError, ScheduleError, critical_path_test, schedule
from xerscope.xer import XerError, build_snapshot, parse_text

pytestmark = pytest.mark.oracle("property")

SEEDS = range(25)
NUMBERS = ["1e7", "1e30", "inf", "-inf", "nan", "-40", "1e6", "999999"]
DATES = [
    "2500-01-01 08:00",
    "1700-01-01 08:00",
    "2262-04-11 08:00",
    "0001-01-01 00:00",
    "9999-12-31 23:59",
    "2026-02-30 08:00",
    "not a date",
    "",
]
LAGS = [1e7, 1e30, float("inf"), float("-inf"), float("nan"), -1e7]
LINK_TYPES = ["FS", "SS", "FF", "SF"]
IN_THE_FILE = ["loop", "self link", "duration", "lag", "date", "link type", "calendar", "status", "status date"]
PAST_THE_LOAD = ["delay", "edited lag", "edited duration"]
OUT_OF_RANGE = [1e7, 1e30, float("inf"), -1e7]  # hours


def _some(rnd: random.Random, tasks: list[dict]) -> list[dict]:
    return rnd.sample(tasks, k=max(1, len(tasks) // 4))


def damaged_network(seed: int, damage: str):
    """``random_network(seed)`` with one kind of damage; returns (tasks, links, snap keywords)."""
    rnd = random.Random(9000 + seed)
    tasks, links = random_network(seed, n=rnd.randint(2, 14))
    codes = [task["task_code"] for task in tasks]
    if damage == "loop":
        for _ in range(rnd.randint(1, 3)):
            a, b = rnd.sample(codes, 2)
            links += [(a, b, rnd.choice(LINK_TYPES), 0), (b, a, rnd.choice(LINK_TYPES), 0)]
    elif damage == "self link":
        links.append((codes[0], codes[0], "FS", 0))
    elif damage == "duration":
        for task in _some(rnd, tasks):
            task[rnd.choice(["remain_drtn_hr_cnt", "target_drtn_hr_cnt"])] = rnd.choice(NUMBERS)
    elif damage == "lag":
        links[:] = [(p, s, kind, rnd.choice(LAGS) if rnd.random() < 0.3 else lag) for p, s, kind, lag in links]
        links.append((codes[0], codes[-1], "FS", 1e30))
    elif damage == "date":
        for task in _some(rnd, tasks):
            column = rnd.choice(
                ["act_start_date", "act_end_date", "cstr_date", "early_start_date", "target_start_date"]
            )
            task[column] = rnd.choice(DATES)
            task.setdefault("cstr_type", rnd.choice(CONSTRAINT_TYPES))
    elif damage == "link type":
        links[:] = [
            (p, s, rnd.choice(["XX", "", "PR_FS", "fs"]) if rnd.random() < 0.3 else kind, lag)
            for p, s, kind, lag in links
        ]
    elif damage == "calendar":
        for task in _some(rnd, tasks):
            task["clndr_id"] = rnd.choice(["NOPE", ""])
    elif damage == "status":
        for task in _some(rnd, tasks):
            task["status_code"] = rnd.choice(["TK_Complete", "TK_Active", "TK_Weird", ""])
            task["act_start_date"] = rnd.choice(["", "2026-05-01 08:00"])
            task["act_end_date"] = rnd.choice(["", "2026-01-05 17:00"])
    elif damage == "status date":
        return tasks, links, {"data_date": rnd.choice(DATES)}
    return tasks, links, {}


def _past_the_load(snapshot, rnd: random.Random, damage: str):
    """``snapshot`` edited as ``damage`` says, and the delay to ask of ``schedule``."""
    if damage == "delay":
        return snapshot, {rnd.choice(list(snapshot.activities["task_code"])): rnd.choice(OUT_OF_RANGE)}
    if damage == "edited lag" and len(snapshot.relationships):
        links = snapshot.relationships.astype({"lag_hr": float})
        links.loc[links.index[0], "lag_hr"] = rnd.choice(OUT_OF_RANGE)
        return dataclasses.replace(snapshot, relationships=links), None
    if damage == "edited duration":
        tasks = snapshot.tasks.astype({"remain_drtn_hr_cnt": float})
        tasks.loc[tasks.index[0], "remain_drtn_hr_cnt"] = rnd.choice(OUT_OF_RANGE)
        return dataclasses.replace(snapshot, tasks=tasks), None
    return snapshot, None


@pytest.mark.parametrize("damage", IN_THE_FILE + PAST_THE_LOAD)
@pytest.mark.parametrize("seed", SEEDS)
def test_a_damaged_network_is_scheduled_or_refused_by_name(seed, damage):
    tasks, links, keywords = damaged_network(seed, damage)
    try:
        snapshot = snap(tasks, links, **keywords)
    except XerError:
        return
    snapshot, delay = _past_the_load(snapshot, random.Random(seed), damage)
    try:
        result = schedule(snapshot, extra_hours=delay)
    except ScheduleError as refused:
        # a date the time axis cannot hold comes from a whole chain: that refusal names the calendar only
        named = refused.members or "schedulable range" in str(refused)
        assert named, (seed, damage, "refused without naming an activity")
        if damage in ("edited lag", "edited duration"):  # one value out of range: its activities are named
            assert refused.members, (seed, damage, str(refused))
        assert isinstance(refused, CycleError) == (damage in ("loop", "self link")), (seed, damage, str(refused))
        return
    assert damage not in ("loop", "self link"), (seed, damage, "a logic loop was scheduled")
    assert len(result.frame) and result.frame["ef"].notna().all(), (seed, damage, "an activity without a date")


PROGRESS_OPTIONS = {
    "retained logic": {},
    "progress override": {"sched_retained_logic": "N", "sched_progress_override": "Y"},
    "actual dates": {"sched_retained_logic": "N", "sched_progress_override": "N"},
}
WITHOUT_ACTUAL_DATES = {
    "finished without actual start": done("X", act_start_date=""),
    "finished without actual finish": done("X", act_end_date=""),
    "finished without actual dates": done("X", act_start_date="", act_end_date=""),
    "under way without actual start": active("X", act_start_date=""),
}


def _assert_scheduled_or_refused_by_name(snapshot, case: tuple) -> None:
    """The contract of this file on one snapshot: every activity dated, or a refusal that names activities."""
    try:
        result = schedule(snapshot)
    except ScheduleError as refused:
        assert refused.members, (case, "refused without naming an activity")
        return
    assert result.frame[["es", "ef"]].notna().all().all(), (case, "an activity without a date")


@pytest.mark.parametrize("is_predecessor", [True, False])
@pytest.mark.parametrize("lag_hr", [0, 8])
@pytest.mark.parametrize("link_type", LINK_TYPES)
@pytest.mark.parametrize("damage", WITHOUT_ACTUAL_DATES)
@pytest.mark.parametrize("progress", PROGRESS_OPTIONS)
def test_an_activity_without_its_actual_dates_is_scheduled_or_refused_by_name(
    progress, damage, link_type, lag_hr, is_predecessor
):
    """A status without the actual dates P6 writes with it, under each progress option: the random
    networks above run under Retained Logic only, where a finished activity is not read through its
    remaining start."""
    link = ("X", "B", link_type, lag_hr) if is_predecessor else ("B", "X", link_type, lag_hr)
    tasks = [dict(WITHOUT_ACTUAL_DATES[damage]), todo("B", **hours(8))]
    snapshot = snap(tasks, [link], sched=PROGRESS_OPTIONS[progress])
    _assert_scheduled_or_refused_by_name(snapshot, (progress, damage, link))


@pytest.mark.parametrize("lag_hr", [0, 8])
@pytest.mark.parametrize("link_type", LINK_TYPES)
@pytest.mark.parametrize("damage", WITHOUT_ACTUAL_DATES)
@pytest.mark.parametrize("progress", PROGRESS_OPTIONS)
def test_a_level_of_effort_is_dated_whatever_actual_date_is_missing(progress, damage, link_type, lag_hr):
    """The level of effort itself without its actual dates, then tied on each side to an activity
    without them: its dates are read from the dates of what it is tied to."""
    level_of_effort = dict(WITHOUT_ACTUAL_DATES[damage], task_code="L", task_type="TT_LOE")
    tasks = [todo("A", **hours(8)), level_of_effort, todo("B", **hours(8))]
    snapshot = snap(tasks, [("A", "L", "SS", 0), ("L", "B", "FF", 0)], sched=PROGRESS_OPTIONS[progress])
    _assert_scheduled_or_refused_by_name(snapshot, (progress, damage, "the level of effort itself"))
    for link in (("X", "L", link_type, lag_hr), ("L", "X", link_type, lag_hr)):
        tasks = [dict(WITHOUT_ACTUAL_DATES[damage]), todo("L", task_type="TT_LOE"), todo("B", **hours(8))]
        snapshot = snap(tasks, [link, ("L", "B", "FF", 0)], sched=PROGRESS_OPTIONS[progress])
        _assert_scheduled_or_refused_by_name(snapshot, (progress, damage, link))


@pytest.mark.parametrize("delay_hr", [MAX_HOURS + 1, 1e30, float("inf"), float("-inf"), float("nan"), -MAX_HOURS - 1])
def test_a_delay_out_of_range_is_refused_by_naming_the_delayed_activity(delay_hr):
    """A delay asked of ``schedule`` follows the rule of a remaining duration or a lag: not finite,
    or beyond ``MAX_HOURS``, it is refused before the passes run and the refusal names the
    activity that was to be delayed, and only that one."""
    snapshot = snap([todo("A", **hours(40)), todo("B", **hours(40))], [("A", "B", "FS", 0)])
    with pytest.raises(ScheduleError, match="delay") as refused:
        schedule(snapshot, extra_hours={"A": 8.0, "B": delay_hr})
    assert refused.value.members == ("B",)


def test_a_delay_at_the_limit_is_not_refused_as_a_delay():
    """``MAX_HOURS`` itself passes the guard, as it does for a duration: what stops the run then is
    the date, past the year the time axis holds, and that refusal names no activity."""
    snapshot = snap([todo("A", **hours(40)), todo("B", **hours(40))], [("A", "B", "FS", 0)])
    with pytest.raises(ScheduleError, match="schedulable range") as refused:
        schedule(snapshot, extra_hours={"B": MAX_HOURS})
    assert refused.value.members == ()
    delayed = schedule(snapshot, extra_hours={"B": 8.0})
    assert delayed.frame.at["B", "ef"] > schedule(snapshot).frame.at["B", "ef"]


def _without_any_date(tasks, links):
    """The file of ``tasks`` and ``links`` with every date left blank: P6 writes none, the load warns."""
    text = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", "", xer_text(tasks, links))
    return build_snapshot(parse_text(text, source="test.xer"))


def test_a_file_without_any_date_is_refused_as_a_schedule_error():
    """No status date, no planned start and no activity date: nothing to schedule from. The refusal
    is a ``ScheduleError`` like the others; it names no activity, the file is at fault. The critical
    path test then answers a failure with that message, it does not raise."""
    snapshot = _without_any_date([todo("A", **hours(40)), todo("B", **hours(40))], [("A", "B", "FS", 0)])
    assert snapshot.data_date is None and snapshot.planned_start is None
    with pytest.raises(ScheduleError, match="nothing to schedule from") as refused:
        schedule(snapshot)
    assert refused.value.members == ()
    assert not isinstance(refused.value, CycleError)
    test = critical_path_test(snapshot, 600)
    assert not test.passed and "nothing to schedule from" in test.note


@pytest.mark.parametrize("metric_id", ["INT-01", "INT-03", "INT-07", "INT-08"])
@pytest.mark.parametrize(
    "links", [[("A", "B", "FS", 0)], [("A", "B", "FS", 0), ("B", "A", "FS", 0)]], ids=["chain", "loop"]
)
def test_an_integrity_check_on_a_file_without_any_date_says_it_cannot_schedule(metric_id, links):
    """Each integrity check that needs the recalculation answers "cannot schedule" and no verdict,
    with or without a loop in the logic. INT-04 needs the links only: see the tests below."""
    snapshot = _without_any_date([todo("A", **hours(40)), todo("B", **hours(40))], links)
    result = run(STANDARDS["INTEGRITY"], metric_id, snapshot)
    assert result.status == "n/a", (result.status, result.note)
    assert result.note.startswith("cannot schedule: ") and "nothing to schedule from" in result.note


def test_a_loop_is_counted_beside_another_refusal():
    """INT-04 counts the activities on a loop from the links alone. When the engine refuses the file
    for another reason first (a lag beyond ``MAX_HOURS`` on a snapshot edited after the load), the
    loop A <-> B is still there and still counted."""
    looped = snap([todo("A", **hours(40)), todo("B", **hours(40))], [("A", "B", "FS", 0), ("B", "A", "FS", 0)])
    found = run(STANDARDS["INTEGRITY"], "INT-04", looped)
    assert found.status == "fail" and codes(found) == ["A", "B"]
    links = looped.relationships.astype({"lag_hr": float})
    links.loc[links.index[0], "lag_hr"] = MAX_HOURS + 1
    unschedulable = dataclasses.replace(looped, relationships=links)
    with pytest.raises(ScheduleError, match="lag") as refused:
        schedule(unschedulable)
    assert not isinstance(refused.value, CycleError)
    still_found = run(STANDARDS["INTEGRITY"], "INT-04", unschedulable)
    assert still_found.status == "fail" and codes(still_found) == ["A", "B"] and still_found.numerator == 2


@pytest.mark.parametrize(
    ("links", "status", "on_a_loop"),
    [([("A", "B", "FS", 0)], "pass", []), ([("A", "B", "FS", 0), ("B", "A", "FS", 0)], "fail", ["A", "B"])],
    ids=["chain", "loop"],
)
def test_int_04_reads_the_loops_of_a_file_without_any_date(links, status, on_a_loop):
    """A file the engine cannot schedule (no date at all) has its loops counted all the same: a
    loop is in the links. Without a loop the check passes with 0 of 2 tasks."""
    snapshot = _without_any_date([todo("A", **hours(40)), todo("B", **hours(40))], links)
    result = run(STANDARDS["INTEGRITY"], "INT-04", snapshot)
    assert result.status == status and codes(result) == on_a_loop
    assert (result.numerator, result.denominator) == (len(on_a_loop), 2)


def test_loop_members_are_those_the_engine_names_and_none_when_it_schedules():
    """A -> B -> C -> A with D after C and a level of effort L spanning A to B: the loop is A, B, C,
    as the engine's refusal names it; D is downstream, L is not part of the network. A link of an
    activity to itself is a loop of one. A chain has none."""
    from xerscope.analysis.cpm import loop_members

    tasks = [todo(code, **hours(8)) for code in "ABCD"] + [todo("L", task_type="TT_LOE")]
    links = [("A", "B", "FS", 0), ("B", "C", "FS", 0), ("C", "A", "FS", 0), ("C", "D", "FS", 0)]
    looped = snap(tasks, [*links, ("A", "L", "SS", 0), ("L", "B", "FF", 0), ("L", "A", "FS", 0)])
    assert loop_members(looped) == ["A", "B", "C"]
    with pytest.raises(CycleError) as refused:
        schedule(looped)
    assert list(refused.value.members) == ["A", "B", "C"]
    assert loop_members(snap([todo("A", **hours(8))], [("A", "A", "FS", 0)])) == ["A"]
    chain = snap([todo("A", **hours(8)), todo("B", **hours(8))], [("A", "B", "FS", 0)])
    assert loop_members(chain) == [] and schedule(chain) is not None
