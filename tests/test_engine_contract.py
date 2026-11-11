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
A delay that is not a number (NaN) is not drawn: it leaves ``schedule`` as a plain ValueError.
The dates of a valid network are held by tests/test_cpm_properties.py; here only the outcome is.
"""

from __future__ import annotations

import dataclasses
import random

import pytest
from test_cpm_properties import random_network
from xerkit import CONSTRAINT_TYPES, snap

from xerscope.analysis.cpm import CycleError, ScheduleError, schedule
from xerscope.xer import XerError

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
