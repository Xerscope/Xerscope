"""The CPM against a second, independent engine: MPXJ's PrimaveraScheduler.

No answer here comes from xerscope itself. Three sources, in order of authority:

1. P6: the dates P6 stored in real exports (Hotel, Terminal). xerscope must reproduce
   every one; where MPXJ misses one, xerscope must still be right.
2. MPXJ's PrimaveraScheduler (pinned commit, tests/reference/mpxj_cpm.py), written
   independently and tuned by its authors against P6: random networks of every kind
   (unstarted, progressed in and out of sequence, resource dependent, constrained) must
   give the same dates, total and free float, to the working minute.
3. Where the two differ and no P6 file settles it, the case is named in
   ``crosscheck.UNRESOLVED`` (or MPXJ's own output is self-contradictory,
   ``crosscheck.mpxj_inconsistent``). Where P6's held-out corpus settled it against MPXJ
   (``crosscheck.P6_SETTLED``), xerscope follows P6 and the difference is MPXJ's. Any
   other difference fails. P6 outranks MPXJ: tests/test_p6_heldout.py is the oracle.

Needs Java, the ``crosscheck`` extra and the built scheduler; skipped otherwise.
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import pandas as pd
import pytest
from test_cpm_properties import random_network
from xerkit import active, done, todo, xer_text

REF = Path(__file__).parent / "reference" / "data"
LAG_PRED = {"sched_calendar_on_relationship_lag": "rcal_Predecessor"}


@pytest.fixture(scope="module")
def xc():
    pytest.importorskip("jpype")
    pytest.importorskip("mpxj")
    if shutil.which("java") is None:
        pytest.skip("no Java runtime")
    from xerscope import crosscheck

    if "mpxj-cpm-" not in crosscheck.mpxj_scheduler_source():
        pytest.skip(
            f"MPXJ's scheduler not built, {crosscheck.mpxj_scheduler_source()} loaded: run tests/reference/mpxj_cpm.py"
        )
    return crosscheck


def compare(xc, tmp_path, name, *args, **kw):
    path = tmp_path / f"{name}.xer"
    path.write_text(xer_text(*args, **kw))
    from xerscope.xer import load_snapshot

    snap = load_snapshot(path)
    assert not xc.mpxj_unsupported(snap), xc.mpxj_unsupported(snap)
    return snap, xc.cpm_crosscheck(path)


def unexplained(xc, snap, cmp) -> pd.DataFrame:
    """Differences no UNRESOLVED case or MPXJ inconsistency accounts for."""
    bad = cmp[cmp["comparable"] & ~cmp["xs_mpxj_work"]]
    if bad.empty or xc.unresolved_patterns(snap) or xc.settled_patterns(snap):
        return bad.iloc[0:0]
    bad = bad[[xc.excused_row(snap, c, f) is None for c, f in zip(bad["task_code"], bad["field"], strict=True)]]
    if bad.empty or xc.mpxj_inconsistent(snap, cmp):
        return bad.iloc[0:0]
    return bad


# --- 1. P6 ------------------------------------------------------------------------------------


@pytest.mark.reference
@pytest.mark.parametrize("name", ["p6viewer/Hotel Project.xer", "p6viewer/TERMINAL BUILDING-AIRPORT.xer"])
def test_p6_xerscope_and_mpxj(xc, require_reference, name):
    cmp = xc.cpm_crosscheck(require_reference(name))
    assert len(cmp) > 300 and cmp["xs_p6"].all(), cmp[~cmp["xs_p6"]].head().to_string()
    # MPXJ is a credible second engine (Hotel 99.9 %, Terminal 100 %) ...
    assert cmp["mpxj_p6"].mean() > 0.999
    # ... and every value it gets wrong, xerscope gets right (P6's finish shown 08:00 after a
    # non-working gap, not the previous evening)
    assert cmp.loc[~cmp["mpxj_p6"], "xs_p6"].all()


# --- 2. random networks -----------------------------------------------------------------------

RESOURCES = [
    {"rsrc_id": "R1", "rsrc_short_name": "FITTER", "rsrc_type": "RT_Labor", "clndr_id": "C8"},
    {"rsrc_id": "R2", "rsrc_short_name": "CRANE", "rsrc_type": "RT_Equip", "clndr_id": "C7D"},
    {"rsrc_id": "R3", "rsrc_short_name": "CREW", "rsrc_type": "RT_Labor", "clndr_id": "C10"},
]
CONSTRAINTS = ["CS_MSOA", "CS_MEOB", "CS_MSO", "CS_MEO", "CS_MSOB", "CS_MEOA", "CS_ALAP", "CS_MANDSTART", "CS_MANDFIN"]
ELAPSED_H = {"2026-02-16 08:00": 80, "2026-02-25 13:00": 20}  # actual start -> working hours to the data date


def network(kind: str, seed: int):
    """(tasks, links, extra xer_text kwargs) for one random network of ``kind``."""
    rnd = random.Random(31_000 + seed)
    progress = kind not in ("unstarted", "constraints")
    fs_ss_ff = dict(types=["FS", "FS", "SS", "FF"], lags=(0, 0, 8, 16))
    if kind in ("resources", "resources_cal", "constraints"):
        tasks, links = random_network(seed, progress=progress, in_sequence=True, **fs_ss_ff)
    elif kind == "out_of_sequence_fs_ss_ff":
        tasks, links = random_network(seed, progress=True, **fs_ss_ff)
    else:
        tasks, links = random_network(seed, progress=progress, in_sequence=kind == "in_sequence")
    kw: dict = {"sched": LAG_PRED}
    if kind.startswith("resources"):
        res = RESOURCES if kind == "resources_cal" else [dict(r, clndr_id="C8") for r in RESOURCES]
        assign = []
        for t in tasks:
            if t.get("task_type", "TT_Task") != "TT_Task" or t.get("status_code") == "TK_Complete":
                continue
            if rnd.random() < 0.4:
                t["task_type"] = "TT_Rsrc"
                started = t.get("status_code") == "TK_Active"
                for r in rnd.sample(res, k=rnd.choice([1, 2])):
                    rate = rnd.choice([1, 1, 2, 0.5])
                    rem = rnd.choice([8, 16, 24, 40]) * rate
                    act = ELAPSED_H.get(t.get("act_start_date"), 0) * rate  # actual units = elapsed work
                    assign.append(
                        {
                            "task_code": t["task_code"],
                            "rsrc_id": r["rsrc_id"],
                            "target_qty": str(rem + act),
                            "remain_qty": str(rem),
                            "act_reg_qty": str(act),
                            "act_ot_qty": "0",
                            "target_qty_per_hr": str(rate),
                            "remain_qty_per_hr": str(rate),
                            "target_lag_drtn_hr_cnt": "0",
                            "relag_drtn_hr_cnt": "0",
                            "rollup_dates_flag": "Y",
                            **({"act_start_date": t["act_start_date"]} if started else {}),
                        }
                    )
        kw.update(resources=res, assign=assign)
    if kind == "constraints":
        t = rnd.choice([t for t in tasks if t.get("task_type", "TT_Task") == "TT_Task"])
        t["cstr_type"] = CONSTRAINTS[seed % len(CONSTRAINTS)]
        t["cstr_date"] = rnd.choice(["2026-03-09 08:00", "2026-03-20 17:00", "2026-04-06 08:00", "2026-03-11 13:00"])
    return tasks, links, kw


# kind -> (networks, minimum share of values identical): the share guards the networks a
# named UNRESOLVED case excuses, so a new bug cannot hide behind one
KINDS = {
    "unstarted": (40, 0.999),
    "in_sequence": (40, 0.98),
    "out_of_sequence": (40, 0.93),
    "out_of_sequence_fs_ss_ff": (40, 0.95),
    "resources": (40, 0.98),
    "resources_cal": (30, 0.85),
    "constraints": (45, 0.97),
}


@pytest.mark.parametrize("kind", KINDS)
def test_random_networks_agree_with_mpxj(xc, tmp_path, kind):
    n, floor = KINDS[kind]
    values, agree, failures = 0, 0, []
    for seed in range(n):
        tasks, links, kw = network(kind, seed)
        snap, cmp = compare(xc, tmp_path, f"{kind}{seed}", tasks, links, **kw)
        ok = cmp[cmp["comparable"]]
        values += len(ok)
        agree += int(ok["xs_mpxj_work"].sum())
        bad = unexplained(xc, snap, cmp)
        if not bad.empty:
            failures.append(f"seed {seed}: " + bad[["task_code", "field", "xerscope", "mpxj"]].head(4).to_string())
    assert not failures, "\n".join(failures)
    assert agree / values >= floor, f"{kind}: {agree}/{values} values identical"


# --- 3. the hand cases of test_cpm.py, through MPXJ ---------------------------------------------


def h(x):
    return dict(target_drtn_hr_cnt=str(x), remain_drtn_hr_cnt=str(x))


FM = dict(task_type="TT_FinMile", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0")
SM = dict(task_type="TT_Mile", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0")
ASG = dict(act_reg_qty="0", act_ot_qty="0", target_qty_per_hr="1", remain_qty_per_hr="1", rollup_dates_flag="Y")
HAND = {
    "fs chain": ([todo("A", **h(16)), todo("B", **h(8))], [("A", "B", "FS", 0)]),
    "ss ff sf": (
        [todo("A", **h(40)), todo("B", **h(16)), todo("C", **h(8)), todo("D", **h(8))],
        [("A", "B", "SS", 8), ("A", "C", "FF", 0), ("A", "D", "SF", 16)],
    ),
    "holiday": ([todo("A", cstr_type="CS_MSOA", cstr_date="2026-04-02 08:00", **h(16))], []),
    "milestones": (
        [todo("A", **h(8)), todo("FM", **FM), todo("SM", **SM)],
        [("A", "FM", "FS", 0), ("A", "SM", "FS", 0)],
    ),
    "snlt negative float": (
        [todo("P", **h(16)), todo("A", cstr_type="CS_MSOB", cstr_date="2026-03-02 08:00", **h(8))],
        [("P", "A", "FS", 0)],
    ),
    "fnlt": (
        [todo("A", **h(16)), todo("Z", cstr_type="CS_MEOB", cstr_date="2026-03-02 17:00", **FM)],
        [("A", "Z", "FS", 0)],
    ),
    "alap": (
        [todo("A", cstr_type="CS_ALAP", **h(8)), todo("B", **h(40)), todo("Z", **FM)],
        [("A", "Z", "FS", 0), ("B", "Z", "FS", 0)],
    ),
    "secondary constraint": (
        [
            todo(
                "A",
                cstr_type="CS_MSOA",
                cstr_date="2026-03-03 08:00",
                cstr_type2="CS_MEOB",
                cstr_date2="2026-03-03 12:00",
                **h(8),
            )
        ],
        [],
    ),
    "mixed calendars, 24 h lag": (
        [todo("A", cstr_type="CS_MSOA", cstr_date="2026-03-06 08:00", **h(8)), todo("B", clndr_id="C7D", **h(8))],
        [("A", "B", "FS", 16)],
        {"sched": {"sched_calendar_on_relationship_lag": "rcal_24Hour"}},
    ),
    "retained logic out of sequence": (
        [todo("A", **h(16)), active("B", remain_drtn_hr_cnt="8")],
        [("A", "B", "FS", 0)],
    ),
    "finished predecessor, unexpired lag": (
        [done("A", act_end_date="2026-02-27 17:00"), active("B", remain_drtn_hr_cnt="8")],
        [("A", "B", "FS", 40)],
    ),
    "ss lag from started work": (
        [done("A"), active("B"), todo("C")],
        [("A", "B", "FS", 0), ("B", "C", "SS", 16)],
    ),
    # B started, then held back by A (Retained Logic). MPXJ binds C to nothing past the data
    # date; P6 applies the SF from B's remaining early start (P6_SETTLED "sf_from_started"),
    # so the two differ here by design and the case checks that the difference is reported
    "sf from started work held back": (
        [
            todo("A", **h(40)),
            active("B", act_start_date="2026-02-25 13:00", remain_drtn_hr_cnt="16"),
            todo("C", **h(8)),
        ],
        [("A", "B", "FS", 0), ("B", "C", "SF", 8)],
    ),
    "expected finish": (
        [active("A", remain_drtn_hr_cnt="40", expect_end_date="2026-03-04 17:00")],
        [],
        {"sched": {"sched_use_expect_end_flag": "Y"}},  # MPXJ reads a blank flag as off
    ),
    "must finish by": ([todo("A", **h(16))], [], {"project": {"plan_end_date": "2026-03-06 00:00"}}),
    "level of effort": (
        [todo("A", **h(16)), todo("B", **h(24)), todo("L", task_type="TT_LOE", **h(8))],
        [("A", "B", "FS", 0), ("A", "L", "SS", 0), ("L", "B", "FF", 0)],
    ),
    "resource dependent, two driving assignments": (
        [todo("A", task_type="TT_Rsrc", **h(16)), todo("B", **h(8))],
        [("A", "B", "FS", 0)],
        {
            "resources": [dict(r, clndr_id="C8") for r in RESOURCES],
            "assign": [
                dict(ASG, task_code="A", rsrc_id="R1", target_qty="16", remain_qty="16"),
                dict(
                    ASG,
                    task_code="A",
                    rsrc_id="R2",
                    target_qty="48",
                    remain_qty="48",
                    target_qty_per_hr="2",
                    remain_qty_per_hr="2",
                ),
            ],
        },
    ),
}


@pytest.mark.parametrize("name", HAND)
def test_hand_cases_agree_with_mpxj(xc, tmp_path, name):
    tasks, links, *kw = HAND[name]
    kw = dict(kw[0]) if kw else {}
    kw["sched"] = {**LAG_PRED, **kw.get("sched", {})}
    snap, cmp = compare(xc, tmp_path, "hand", tasks, links, **kw)
    bad = unexplained(xc, snap, cmp)
    assert bad.empty, bad[["task_code", "field", "xerscope", "mpxj"]].to_string()
    assert cmp["comparable"].sum() >= 6
    if name == "sf from started work held back":
        assert xc.settled_patterns(snap) == {"sf_from_started"}
        assert not cmp.loc[cmp["task_code"] == "C", "xs_mpxj_work"].all()  # P6's reading, not MPXJ's


# --- 4. the demo: its stored dates are xerscope's own, so MPXJ checks them --------------------


def test_demo_dates_are_confirmed_by_mpxj(xc, sample_dir):
    """The demo's early / late dates and floats are written by xerscope's CPM (sample.py):
    every one must be MPXJ's too, except where MPXJ contradicts its own logic (a Start On
    or After on the day of the logic start) or a value named in UNRESOLVED."""
    from xerscope.xer import load_snapshot

    for path in sorted(sample_dir.glob("*.xer")):
        snap = load_snapshot(path)
        assert not xc.mpxj_unsupported(snap), (path.name, xc.mpxj_unsupported(snap))
        cmp = xc.cpm_crosscheck(path)
        assert cmp["xs_p6"].all(), path.name  # the file holds what xerscope computes
        bad = cmp[cmp["comparable"] & ~cmp["xs_mpxj_work"]]
        bad = bad[[xc.excused_row(snap, c, f) is None for c, f in zip(bad["task_code"], bad["field"], strict=True)]]
        assert bad.empty or xc.mpxj_inconsistent(snap, cmp), (path.name, bad.head().to_string())
