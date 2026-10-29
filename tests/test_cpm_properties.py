"""CPM invariants on random schedules (seeded, so a failure always reproduces).

No P6 output exists for these networks, so they check what any P6 recalculation must
satisfy whatever the network. The dates themselves are compared with an independent
engine, MPXJ's PrimaveraScheduler, in tests/test_crosscheck_mpxj.py.

Progress here follows the logic (no started activity with an unfinished predecessor):
out-of-sequence progress legitimately gives negative float and is left to the MPXJ
comparison.

- every relationship holds on the early dates and on the late dates (an SF from started
  work binds nothing past the data date)
- an unstarted task lasts its remaining duration, early and late
- total float = late finish - early finish (P6 default "finish float"); free float >= 0
  (it can exceed total float: late dates stop at the project finish, free float runs to
  the successors, in P6 as in MPXJ)
- unconstrained, one calendar, Retained Logic: no negative float; with FS links only and
  no leads (nothing dangling past the end) the longest path has zero float
- with FS links only, delaying any activity never brings the project finish earlier
"""

from __future__ import annotations

import random

import pandas as pd
import pytest
from xerkit import CALENDAR_IDS, snap

from xerscope.analysis.cpm import _Axes, _date_range, schedule

TYPES = ["FS", "FS", "FS", "SS", "FF", "SF"]
SEEDS = range(60)


def random_network(
    seed: int, n: int = 14, progress: bool = True, types=TYPES, lags=(0, 0, 0, 8, 16, -8), in_sequence: bool = False
):
    rnd = random.Random(seed)
    codes = [f"A{i:02d}" for i in range(n)]
    tasks, links = [], []
    for i, c in enumerate(codes):
        hours = rnd.choice([0, 8, 16, 24, 40, 56, 80])
        t = {"task_code": c, "target_drtn_hr_cnt": str(hours), "remain_drtn_hr_cnt": str(hours)}
        if hours == 0:
            t["task_type"] = rnd.choice(["TT_Mile", "TT_FinMile"])
        r = rnd.random()
        if progress and i < n // 3 and r < 0.35 and hours:
            t.update(
                status_code="TK_Complete",
                remain_drtn_hr_cnt="0",
                act_start_date="2026-02-02 08:00",
                act_end_date="2026-02-20 17:00",
            )
        elif progress and i < n // 2 and r < 0.6 and hours:
            t.update(
                status_code="TK_Active",
                act_start_date=rnd.choice(["2026-02-16 08:00", "2026-02-25 13:00"]),
                remain_drtn_hr_cnt=str(rnd.choice([8, 16, 32])),
            )
        tasks.append(t)
    for j in range(1, n):  # a DAG: links only go forward in the list
        for i in rnd.sample(range(j), k=min(j, rnd.choice([1, 1, 2, 3]))):
            links.append((codes[i], codes[j], rnd.choice(types), rnd.choice(lags)))
    if in_sequence:  # nothing started while one of its predecessors is unfinished
        status = {t["task_code"]: t.get("status_code", "TK_NotStart") for t in tasks}
        preds: dict[str, list[str]] = {}
        for p, s, *_ in links:
            preds.setdefault(s, []).append(p)
        for t in tasks:
            c = t["task_code"]
            if status[c] != "TK_NotStart" and any(status[p] != "TK_Complete" for p in preds.get(c, [])):
                for k in ("status_code", "act_start_date", "act_end_date"):
                    t.pop(k, None)
                t["remain_drtn_hr_cnt"] = t["target_drtn_hr_cnt"]
                status[c] = "TK_NotStart"
    return tasks, links


def _check(seed: int, progress: bool, fs_only: bool = False):
    # FS only and no lead: no dangling end, no successor allowed before its predecessor's end
    tasks, links = (
        random_network(seed, progress=progress, types=["FS"], lags=(0, 0, 8, 16), in_sequence=True)
        if fs_only
        else random_network(seed, progress=progress, in_sequence=True)
    )
    s = snap(tasks, links)
    sch = schedule(s)
    f = sch.frame
    ax = _Axes(s, *_date_range(s)).of(CALENDAR_IDS["C8"])
    w = ax.work
    st = f["status_code"]
    open_ = f[st != "TK_Complete"]
    dd = s.data_date
    act = s.activities.set_index("task_code")

    # durations and float
    for c, r in open_.iterrows():
        assert r["lf"] >= r["ls"] and r["ef"] >= r["remaining_start"], c
        assert r["remaining_start"] >= dd, c
        d = float(act.at[c, "remain_drtn_hr_cnt"]) * 60
        if act.at[c, "task_type"] == "TT_Task":
            assert w(r["ef"]) - w(r["remaining_start"]) == pytest.approx(d), (seed, c, "early duration")
            assert w(r["lf"]) - w(r["ls"]) == pytest.approx(d), (seed, c, "late duration")
        assert r["tf_hr"] == pytest.approx((w(r["lf"]) - w(r["ef"])) / 60), (seed, c, "total float")
        assert r["tf_hr"] >= 0, (seed, c, "negative float without constraints")
        assert r["ff_hr"] >= 0, (seed, c, "free float")
    lp = open_[open_["longest_path"]]
    assert len(lp), (seed, "no longest path")
    if fs_only:  # an SS/SF-only successor leaves the finish dangling: float past the end, as P6
        assert (lp["tf_hr"] == 0).all(), (seed, "longest path float")

    # every relationship holds, early and late (lags of started predecessors partly expired)
    for p, c, typ, lag in links:
        if st[c] == "TK_Complete" or st[p] == "TK_Complete" and st[c] == "TK_Active":
            continue
        if st[c] == "TK_Active" and typ in ("FS", "SS"):
            continue  # started: its start is its actual start
        if typ == "SF" and st[p] == "TK_Active" and st[c] == "TK_NotStart":
            continue  # tied to the predecessor's actual start, in the past
        lag_m = lag * 60
        if st[p] == "TK_Active" and typ in ("SS", "SF") and lag_m > 0:
            lag_m = max(0, lag_m - ax.between(act.at[p, "act_start_date"], dd))
        P, C = f.loc[p], f.loc[c]
        frm = {"FS": "ef", "FF": "ef", "SS": "remaining_start", "SF": "remaining_start"}[typ]
        to = {"FS": "remaining_start", "SS": "remaining_start", "FF": "ef", "SF": "ef"}[typ]
        assert w(C[to]) >= w(P[frm]) + lag_m - 1e-6, (seed, p, c, typ, lag, "early")
        if st[p] != "TK_Complete":
            lfrm = {"ef": "lf", "remaining_start": "ls"}[frm]
            lto = {"ef": "lf", "remaining_start": "ls"}[to]
            assert w(C[lto]) >= w(P[lfrm]) + lag_m - 1e-6, (seed, p, c, typ, lag, "late")

    # delaying any open activity never brings the finish earlier, with FS links: with FF a
    # longer activity whose finish is fixed starts earlier and pulls its SS successors
    # along (the classic CPM "reverse logic" effect, in P6 too)
    for c in open_.index[:: max(1, len(open_) // 4)] if fs_only else []:
        assert schedule(s, extra_hours={c: 24}).finish >= sch.finish, (seed, c)
    return sch


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_not_started(seed):
    _check(seed, progress=False)


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_progressed(seed):
    _check(seed, progress=True)


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_fs_only(seed):
    _check(seed, progress=seed % 2 == 0, fs_only=True)


def test_ss_lag_from_started_predecessor_leaves_no_negative_float():
    """B started 5 days ago, SS +2 d to C: the lag has expired, C starts at the data date
    and drives the finish, so B and C are both critical with zero float (not -16 h)."""
    from xerkit import active, done, todo

    s = snap([done("A"), active("B"), todo("C")], [("A", "B", "FS", 0), ("B", "C", "SS", 16)])
    f = schedule(s).frame
    assert f.at["C", "es"] == pd.Timestamp("2026-03-02 08:00")
    assert f.at["B", "tf_hr"] == 0 and f.at["C", "tf_hr"] == 0
    assert f.at["B", "longest_path"]


CONSTRAINTS = ["CS_MSOA", "CS_MEOB", "CS_MSO", "CS_MEO", "CS_MSOB", "CS_MEOA", "CS_ALAP", "CS_MANDSTART", "CS_MANDFIN"]
OPTIONS = [
    {},
    {"sched_retained_logic": "N", "sched_progress_override": "Y"},
    {"sched_retained_logic": "N", "sched_progress_override": "N"},
    {"sched_lag_early_start_flag": "N"},
    {"sched_float_type": "FT_SF"},
    {"sched_float_type": "FT_SmallestFloat", "sched_open_critical_flag": "Y"},
    {"sched_calendar_on_relationship_lag": "rcal_Predecessor"},
    {"sched_calendar_on_relationship_lag": "rcal_24Hour"},
]


@pytest.mark.parametrize("seed", range(80))
def test_options_constraints_calendars(seed):
    """Every option, constraint type and calendar mix: no crash, and the constraints hold."""
    rnd = random.Random(1000 + seed)
    tasks, links = random_network(seed)
    for t in tasks:
        t["clndr_id"] = rnd.choice(["C8", "C8", "C10", "C7D"])
        if rnd.random() < 0.2 and t.get("status_code", "TK_NotStart") == "TK_NotStart":
            t["cstr_type"] = rnd.choice(CONSTRAINTS)
            t["cstr_date"] = rnd.choice(["2026-03-09 08:00", "2026-03-20 17:00", "2026-04-06 08:00"])
        if rnd.random() < 0.08 and t.get("status_code", "TK_NotStart") == "TK_NotStart":
            t["task_type"] = "TT_LOE"
    s = snap(tasks, links, sched=OPTIONS[seed % len(OPTIONS)])
    sch = schedule(s)
    f = sch.frame
    act = s.activities.set_index("task_code")
    assert sch.finish is not None
    axes = _Axes(s, *_date_range(s))
    for c, r in f[f["status_code"] == "TK_NotStart"].iterrows():
        typ, date = act.at[c, "cstr_type"], act.at[c, "cstr_date"]
        if act.at[c, "task_type"] == "TT_LOE" or not isinstance(typ, str) or not typ:
            continue
        # compared in working time: a start "on" Friday 17:00 shows as Monday 08:00, as in P6
        w = axes.of(act.at[c, "clndr_id"]).work
        d, start, fin, ls, lf = (w(x) for x in (pd.Timestamp(date), r["remaining_start"], r["ef"], r["ls"], r["lf"]))
        if typ == "CS_MANDSTART":
            assert start == d and ls == d, (seed, c, typ)
        elif typ == "CS_MANDFIN":
            assert fin == d and lf == d, (seed, c, typ)
        elif typ in ("CS_MSOA", "CS_MSO"):
            assert start >= d, (seed, c, typ)
        elif typ in ("CS_MEOA", "CS_MEO"):
            assert fin >= d, (seed, c, typ)
        if typ in ("CS_MSOB", "CS_MSO"):
            assert ls <= d, (seed, c, typ)
        if typ in ("CS_MEOB", "CS_MEO"):
            assert lf <= d, (seed, c, typ)
