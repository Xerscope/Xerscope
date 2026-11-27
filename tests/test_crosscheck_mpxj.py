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
from pathlib import Path

import pandas as pd
import pytest
from conftest import missing, mpxj_or_skip
from test_cpm_properties import random_network
from xerkit import CONSTRAINT_TYPES, FM, SECONDARY_CONSTRAINTS, SM, active, clndr_data, done, hours, todo, xer_text

REF = Path(__file__).parent / "reference" / "data"
LAG_PRED = {"sched_calendar_on_relationship_lag": "rcal_Predecessor"}


@pytest.fixture(scope="module")
def xc():
    mpxj_or_skip()
    from xerscope import crosscheck

    if "mpxj-cpm-" not in crosscheck.mpxj_scheduler_source():
        loaded = crosscheck.mpxj_scheduler_source()
        missing("mpxj", f"scheduler not built ({loaded} loaded): uv run python tests/reference/mpxj_cpm.py")
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


@pytest.mark.oracle("p6")  # P6's stored dates decide; MPXJ is measured against them
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
        t["cstr_type"] = CONSTRAINT_TYPES[seed % len(CONSTRAINT_TYPES)]
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


@pytest.mark.oracle("mpxj")
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


ASG = dict(act_reg_qty="0", act_ot_qty="0", target_qty_per_hr="1", remain_qty_per_hr="1", rollup_dates_flag="Y")
HAND = {
    "fs chain": ([todo("A", **hours(16)), todo("B", **hours(8))], [("A", "B", "FS", 0)]),
    "ss ff sf": (
        [todo("A", **hours(40)), todo("B", **hours(16)), todo("C", **hours(8)), todo("D", **hours(8))],
        [("A", "B", "SS", 8), ("A", "C", "FF", 0), ("A", "D", "SF", 16)],
    ),
    "holiday": ([todo("A", cstr_type="CS_MSOA", cstr_date="2026-04-02 08:00", **hours(16))], []),
    # a project calendar without exceptions of its own, built on C8 (Good Friday off): MPXJ
    # reads the base's holiday into it (ProjectCalendar.getException), A finishes Mon 17:00
    "holiday of the base calendar": (
        [todo("A", clndr_id="20", cstr_type="CS_MSOA", cstr_date="2026-04-02 08:00", **hours(16))],
        [],
        {
            "calendars": [
                {
                    "clndr_id": "20",
                    "clndr_name": "Derived",
                    "clndr_type": "CA_Project",
                    "base_clndr_id": "8",
                    "day_hr_cnt": "8",
                    "week_hr_cnt": "40",
                    "clndr_data": clndr_data(range(2, 7), [("08:00", "12:00"), ("13:00", "17:00")]),
                }
            ]
        },
    ),
    "milestones": (
        [todo("A", **hours(8)), todo("FM", **FM), todo("SM", **SM)],
        [("A", "FM", "FS", 0), ("A", "SM", "FS", 0)],
    ),
    "snlt negative float": (
        [todo("P", **hours(16)), todo("A", cstr_type="CS_MSOB", cstr_date="2026-03-02 08:00", **hours(8))],
        [("P", "A", "FS", 0)],
    ),
    "fnlt": (
        [todo("A", **hours(16)), todo("Z", cstr_type="CS_MEOB", cstr_date="2026-03-02 17:00", **FM)],
        [("A", "Z", "FS", 0)],
    ),
    "alap": (
        [todo("A", cstr_type="CS_ALAP", **hours(8)), todo("B", **hours(40)), todo("Z", **FM)],
        [("A", "Z", "FS", 0), ("B", "Z", "FS", 0)],
    ),
    "secondary constraint": ([todo("A", **SECONDARY_CONSTRAINTS)], []),
    "mixed calendars, 24 h lag": (
        [
            todo("A", cstr_type="CS_MSOA", cstr_date="2026-03-06 08:00", **hours(8)),
            todo("B", clndr_id="C7D", **hours(8)),
        ],
        [("A", "B", "FS", 16)],
        {"sched": {"sched_calendar_on_relationship_lag": "rcal_24Hour"}},
    ),
    "retained logic out of sequence": (
        [todo("A", **hours(16)), active("B", remain_drtn_hr_cnt="8")],
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
            todo("A", **hours(40)),
            active("B", act_start_date="2026-02-25 13:00", remain_drtn_hr_cnt="16"),
            todo("C", **hours(8)),
        ],
        [("A", "B", "FS", 0), ("B", "C", "SF", 8)],
    ),
    "expected finish": (
        [active("A", remain_drtn_hr_cnt="40", expect_end_date="2026-03-04 17:00")],
        [],
        {"sched": {"sched_use_expect_end_flag": "Y"}},  # MPXJ reads a blank flag as off
    ),
    "must finish by": ([todo("A", **hours(16))], [], {"project": {"plan_end_date": "2026-03-06 00:00"}}),
    "level of effort": (
        [todo("A", **hours(16)), todo("B", **hours(24)), todo("L", task_type="TT_LOE", **hours(8))],
        [("A", "B", "FS", 0), ("A", "L", "SS", 0), ("L", "B", "FF", 0)],
    ),
    "resource dependent, two driving assignments": (
        [todo("A", task_type="TT_Rsrc", **hours(16)), todo("B", **hours(8))],
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


@pytest.mark.oracle("mpxj")
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
    if name == "holiday of the base calendar":  # read alone, MPXJ's dates look inconsistent and are dropped
        assert cmp["xs_mpxj_work"].all() and not xc.mpxj_inconsistent(snap, cmp)


# --- 4. the demo: its stored dates are xerscope's own, so MPXJ checks them --------------------


@pytest.mark.oracle("mpxj")
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


# --- 4b. the command on a file where nothing is open ---------------------------------------------


@pytest.mark.oracle("mpxj")
def test_the_command_says_so_when_a_file_has_nothing_to_compare(xc, tmp_path, capsys):
    """Every activity complete: neither engine places anything, the comparison has no row. The
    command names the file, says there is nothing to compare and counts no difference; a file with
    open work after it is still compared."""
    from xerscope.cli import main

    finished = tmp_path / "finished.xer"
    finished.write_text(xer_text([done("A"), done("B")], [("A", "B", "FS", 0)]))
    assert xc.cpm_crosscheck(finished).empty
    open_work = tmp_path / "open.xer"
    open_work.write_text(xer_text([todo("A", **hours(40)), todo("B", **hours(40))], [("A", "B", "FS", 0)]))
    assert main(["crosscheck", "--cpm", str(finished), str(open_work)]) == 0
    printed = capsys.readouterr().out
    assert "finished.xer · nothing to compare" in printed
    assert "open.xer · 2 open activities" in printed
    assert "0 difference(s) no listed cause explains" in printed


# --- 5. the self-consistency check, without Java ------------------------------------------------


@pytest.mark.parametrize(
    "duration, lag",
    [("8.2", "0"), ("0.3333", "0"), ("13.3333", "0"), ("8", "8.3")],  # lag: guard only, see below
)
def test_dates_that_hold_together_are_not_called_inconsistent(duration, lag):
    """MPXJ dates equal to xerscope's own pass ``mpxj_inconsistent``. A duration or a lag in
    decimal hours is a whole number of minutes once rounded as ``TimeAxis.at`` rounds it
    (8.2 h = 492 min, 8.3 h = 498 min), but 8.2 * 60 = 491.99999999999994 and
    8.3 * 60 = 498.00000000000006 in floating point:
    compared raw, the file read as MPXJ contradicting itself and every difference in it was
    excused. A lag's noise is lost once added to a date's working minutes (21138 + 6e-14 is
    21138.0), so the lag case cannot fail today; it guards the same rounding."""
    from xerkit import snap as build

    from xerscope.analysis.cpm import schedule
    from xerscope.crosscheck import mpxj_inconsistent

    snap = build(
        [todo("A", target_drtn_hr_cnt=duration, remain_drtn_hr_cnt=duration), todo("B", **hours(8))],
        [("A", "B", "FS", lag)],
    )
    ours = schedule(snap).frame
    cmp = pd.DataFrame(
        [
            {"task_code": code, "field": field, "mpxj": ours.at[code, "remaining_start" if field == "es" else field]}
            for code in ("A", "B")
            for field in ("es", "ef", "ls", "lf")
        ]
    )
    assert mpxj_inconsistent(snap, cmp) == set()


# --- 6. driving relationships --------------------------------------------------------------------

HELD_OUT = REF / "p6-heldout" / "validation" / "held-out"
# Corpus cases MPXJ's scheduler (pinned commit) stops on with a NullPointerException, measured
# 2026-11-25: left out by name, so any other failure of either engine fails the test.
MPXJ_STOPS = {
    "H25-11", "H26-06", "H27-06", "H28-02", "H28-03", "H28-11",
    "H28-12", "H29-05", "H30-01", "H30-04", "H30-10", "H30-12",
}  # fmt: skip
DRIVING_FILES = [
    "p6viewer/Hotel Project.xer",
    "p6viewer/TERMINAL BUILDING-AIRPORT.xer",
    "pv/20-kW-residential-pv-p6.xer",
]


def _driving_unexplained(xc, path: Path) -> tuple[int, pd.DataFrame]:
    """Links compared, and the differences neither an MPXJ date nor an UNRESOLVED case explains."""
    compared = xc.driving_crosscheck(path)
    unexplained = compared[compared["reason"].isna()]
    assert set(compared["reason"].dropna()) <= {"", "mpxj_dates", *xc.UNRESOLVED, *xc.P6_SETTLED}
    return len(compared), unexplained


@pytest.mark.oracle("mpxj")
@pytest.mark.parametrize("name", DRIVING_FILES)
def test_driving_links_agree_with_mpxj_on_reference_files(xc, require_reference, name):
    """Measured 2026-11-25: Hotel 7,586 open links, 7 differences, each an As Late As Possible
    successor, where P6's aref sides with xerscope (P6_SETTLED driving_alap); Terminal and PV none."""
    compared, unexplained = _driving_unexplained(xc, require_reference(name))
    assert compared > 0
    assert unexplained.empty, unexplained.head(10).to_string()


@pytest.mark.oracle("mpxj")
@pytest.mark.parametrize("name", [f"H{number}" for number in range(1, 31)])
def test_driving_links_agree_with_mpxj_on_the_p6_corpus(xc, name):
    """P6 23.12 held-out corpus, every case MPXJ supports: no difference left once MPXJ's own date
    differences and the UNRESOLVED cases are set aside (measured 2026-11-25 on the 30 sets: 2,399 open
    links, 159 differences: 115 MPXJ dates, 40 driving_held_by_data_date, 4 driving_alap (P6_SETTLED); MPXJ's
    scheduler stops on the 12 cases of MPXJ_STOPS, left out by name)."""
    from xerscope.xer import load_snapshot

    if not HELD_OUT.is_dir():
        missing("p6-corpus", "uv run python tests/reference/fetch_p6_heldout.py")
    for path in sorted((HELD_OUT / name / "cases").glob("*.xer")):
        if xc.mpxj_unsupported(load_snapshot(path)):
            continue
        if path.stem in MPXJ_STOPS:
            continue
        compared, unexplained = _driving_unexplained(xc, path)
        assert compared > 0 and unexplained.empty, (path.name, unexplained.head(10).to_string())


# --- 6. the pattern detectors, without Java -------------------------------------------------------
# unexplained() above drops every difference of a network that carries a pattern, so a detector that
# fires everywhere would silence the whole comparison. The detectors are pinned alone, on networks
# whose patterns follow by hand from the rules written in verify/mpxj_cpm.py.


def _patterns(tasks, links, **kw) -> tuple[set[str], set[str]]:
    from xerkit import snap

    from xerscope.verify import mpxj_cpm

    snapshot = snap(tasks, links, **kw)
    return mpxj_cpm.unresolved_patterns(snapshot), mpxj_cpm.settled_patterns(snapshot)


@pytest.mark.oracle("property")
@pytest.mark.parametrize("seed", range(40))
def test_a_network_with_no_started_work_and_no_assignment_has_no_pattern(seed):
    """Every pattern needs a started or finished task, or an assignment (UNRESOLVED and P6_SETTLED
    rules); the "unstarted" kind has none, whatever its links."""
    tasks, links, kw = network("unstarted", seed)
    assert all(task.get("status_code", "TK_NotStart") == "TK_NotStart" for task in tasks)
    assert _patterns(tasks, links, **kw) == (set(), set())


@pytest.mark.oracle("property")
@pytest.mark.parametrize(
    ("tasks", "links", "unresolved", "settled"),
    [
        ([done("A"), todo("B")], [("A", "B", "FF", 8)], {"ff_sf_lag_from_finished"}, set()),
        ([todo("A"), active("B")], [("A", "B", "SF", 0)], {"sf_progressed"}, set()),
        ([done("A"), todo("B")], [("A", "B", "FS", -8)], {"lead_from_progressed"}, set()),
        ([done("A"), active("B")], [("A", "B", "SS", 0)], {"finished_into_started"}, set()),
        ([active("A"), todo("B")], [("A", "B", "SF", 0)], set(), {"sf_from_started"}),
        ([todo("A"), done("B")], [("A", "B", "FS", 8)], set(), {"lag_to_finished_successor"}),
        ([todo("A"), todo("B")], [("A", "B", "FS", 0)], set(), set()),
    ],
    ids=["ff lag", "sf progressed", "lead", "finished into started", "sf from started", "lag to finished", "none"],
)
def test_each_pattern_is_found_on_the_two_task_network_that_shows_it(tasks, links, unresolved, settled):
    assert _patterns(tasks, links) == (unresolved, settled)


@pytest.mark.oracle("property")
def test_a_resource_dependent_task_on_another_calendar_or_with_a_lag_is_flagged():
    """A driving assignment of a resource-dependent task: the resource's calendar (R2: C7D) differs from
    the task's (C8) -> rsrc_calendar; a relag_drtn_hr_cnt of 8 -> assignment_lag."""
    from xerkit import labour_assignment

    def case(resource_id: str, **assignment):
        row = {**labour_assignment("A", resource_id, 8), **assignment}
        return _patterns([todo("A", task_type="TT_Rsrc")], [], resources=RESOURCES, assign=[row])[0]

    assert case("R2") == {"rsrc_calendar"}
    assert case("R1") == set()  # same calendar (C8), no lag
    assert case("R1", relag_drtn_hr_cnt="8") == {"assignment_lag"}


# --- 6b. the shapes P6 settled per activity, without Java ----------------------------------------
# settled_activities names the activities a P6_SETTLED constraint rule applies to; the comparison of
# tests/test_scale_random_network.py excuses only what follows from them. Each case pins one shape and
# its nearest neighbours that must not be named. Data date: Mon 2 March 2026 08:00, calendar C8.


def _settled(task) -> dict[str, set[str]]:
    from xerkit import snap

    from xerscope.verify import mpxj_cpm

    found = mpxj_cpm.settled_activities(snap([task, todo("Z", **FM)], [("A", "Z", "FS", 0)]))
    return {key: codes for key, codes in found.items() if codes}


@pytest.mark.oracle("property")
@pytest.mark.parametrize(
    ("task", "expected"),
    [
        # docs/cpm.md forward and backward passes: a second constraint is scheduled in both passes
        (todo("A", cstr_type="CS_MSOA", cstr_date="2026-03-03 08:00", cstr_type2="CS_MEO",
              cstr_date2="2026-03-06 17:00", **hours(16)), {"second_constraint": {"A"}}),
        (todo("A", cstr_type="CS_MSOB", cstr_date="2026-03-03 08:00", cstr_type2="CS_MEOA",
              cstr_date2="2026-03-06 17:00", **hours(16)), {"second_constraint": {"A"}}),
        # Finish On or Before in the second slot: MPXJ applies it as P6 does, nothing named
        (todo("A", **SECONDARY_CONSTRAINTS), {}),
        (done("A", cstr_type="CS_MSOA", cstr_date="2026-02-02 08:00", cstr_type2="CS_MEO",
              cstr_date2="2026-02-13 17:00"), {}),
        # work under way: a Start On or Before or a mandatory date in either slot leaves the backward pass
        (active("A", cstr_type="CS_MSOB", cstr_date="2026-03-04 08:00"), {"constraint_under_way": {"A"}}),
        (active("A", cstr_type="CS_MANDFIN", cstr_date="2026-02-27 17:00"), {"constraint_under_way": {"A"}}),
        (active("A", cstr_type="CS_MEOB", cstr_date="2026-03-05 17:00"), {}),
        (todo("A", cstr_type="CS_MSOB", cstr_date="2026-03-04 08:00", **hours(16)), {}),
        # mandatory dates never put early dates before the data date
        (todo("A", cstr_type="CS_MANDSTART", cstr_date="2026-02-27 08:00", **hours(16)),
         {"mandatory_before_data_date": {"A"}}),
        (todo("A", cstr_type="CS_MANDSTART", cstr_date="2026-03-02 08:00", **hours(16)), {}),
        (todo("A", cstr_type="CS_MANDFIN", cstr_date="2026-03-03 12:00", **hours(16)),
         {"mandatory_before_data_date": {"A"}}),  # 11 working hours after the data date, 16 needed
        (todo("A", cstr_type="CS_MANDFIN", cstr_date="2026-03-03 17:00", **hours(16)), {}),  # exactly 16
    ],
    ids=["finish on second", "finish on or after second", "finish on or before second", "complete",
         "under way start on or before", "under way mandatory finish", "under way finish on or before",
         "not started start on or before", "mandatory start before", "mandatory start on the data date",
         "mandatory finish too early", "mandatory finish just fits"],
)  # fmt: skip
def test_each_settled_shape_names_its_activity_and_no_neighbour(task, expected):
    assert _settled(task) == expected


def _comparison_row(task_code, field, xerscope, mpxj, same_work) -> dict:
    return {
        "task_code": task_code, "field": field, "xerscope": pd.Timestamp(xerscope), "mpxj": pd.Timestamp(mpxj),
        "xs_mpxj": xerscope == mpxj, "xs_mpxj_work": same_work,
    }  # fmt: skip


@pytest.mark.oracle("property")
@pytest.mark.parametrize(
    ("calendar", "link_type", "expected"),
    [("C10", "FS", {"A"}), ("C7D", "FS", {"A"}), ("C8", "FS", set()), ("C10", "FF", set())],
    ids=["10 h predecessor", "7-day predecessor", "same calendar", "link the late start does not bind"],
)
def test_edge_on_another_calendar_names_the_predecessor_working_in_the_gap(calendar, link_type, expected):
    """B (C8) has its late start written Fri 6 March 17:00 by xerscope, Mon 9 March 08:00 by MPXJ: the
    same working minute of C8 (period_edge). Its predecessor A then differs (Fri 17:00 against Fri
    18:00 or Sun 16:00). Named only when A's calendar works between the two instants (C10 to 18:00,
    C7D on the weekend; not C8) and the link binds A to B's late start (FS, not FF)."""
    from xerkit import snap

    from xerscope.verify import mpxj_cpm

    snapshot = snap([todo("A", clndr_id=calendar, **hours(8)), todo("B", **hours(40))], [("A", "B", link_type, 0)])
    comparison = pd.DataFrame(
        [
            _comparison_row("B", "ls", "2026-03-06 17:00", "2026-03-09 08:00", True),
            _comparison_row("A", "lf", "2026-03-06 17:00", "2026-03-06 18:00", False),
        ]
    )
    assert list(mpxj_cpm.edges_written_apart(comparison)["task_code"]) == ["B"]
    assert mpxj_cpm.edge_on_another_calendar(snapshot, comparison) == expected


# --- 7. the command's exit code, without Java ---------------------------------------------------
# MPXJ's answer is replaced by hand-written dates: the command, the detectors and the comparison
# around it are the real code. The two activities are 40 working hours each on the 8 h calendar C8
# (Monday to Friday, 08:00 to 17:00), A -> B Finish to Start, no lag: A runs Mon 2 to Fri 6 March
# 2026, B Mon 9 to Fri 13 March, both with no float.


def _dates(early_start, early_finish, late_start, late_finish) -> dict:
    return {"es": pd.Timestamp(early_start), "ef": pd.Timestamp(early_finish),
            "ls": pd.Timestamp(late_start), "lf": pd.Timestamp(late_finish)}  # fmt: skip


HAND_DATES = {
    "A": _dates("2026-03-02 08:00", "2026-03-06 17:00", "2026-03-02 08:00", "2026-03-06 17:00"),
    "B": _dates("2026-03-09 08:00", "2026-03-13 17:00", "2026-03-09 08:00", "2026-03-13 17:00"),
}
# B one working day late (Tue 10 to Mon 16 March): still 40 h long, still after A, so MPXJ does not
# contradict itself and nothing excuses the four dates that differ.
B_A_DAY_LATE = _dates("2026-03-10 08:00", "2026-03-16 17:00", "2026-03-10 08:00", "2026-03-16 17:00")


def _fake_mpxj(monkeypatch, dates_of_b):
    from xerscope import crosscheck
    from xerscope.verify import mpxj_cpm

    rows = {"A": {**HAND_DATES["A"], "tf_hr": 0, "ff_hr": 0}, "B": {**dates_of_b, "tf_hr": 0, "ff_hr": 0}}
    frame = pd.DataFrame.from_dict(rows, orient="index").rename_axis("task_code")
    monkeypatch.setattr(mpxj_cpm, "mpxj_schedule", lambda path, project_code=None: frame)
    monkeypatch.setattr(crosscheck, "mpxj_scheduler_source", lambda: "file:/mpxj-cpm-test.jar")


def _two_activity_file(tmp_path, **kw):
    path = tmp_path / "two.xer"
    path.write_text(xer_text([todo("A", **hours(40)), todo("B", **hours(40))], [("A", "B", "FS", 0)], **kw))
    return path


@pytest.mark.oracle("property")
def test_the_command_exits_1_and_counts_a_difference_no_cause_explains(tmp_path, capsys, monkeypatch):
    from xerscope.cli import main

    _fake_mpxj(monkeypatch, B_A_DAY_LATE)
    path = _two_activity_file(tmp_path, sched=LAG_PRED)
    assert main(["crosscheck", "--cpm", str(path)]) == 1
    printed = capsys.readouterr().out
    assert "4 difference(s) no listed cause explains" in printed


@pytest.mark.oracle("property")
def test_the_command_exits_0_when_a_listed_cause_explains_the_file(tmp_path, capsys, monkeypatch):
    """The same four differences on a file whose scheduling options MPXJ does not model (no lag
    calendar stated): the cause is listed, the count is 0."""
    from xerscope.cli import main

    _fake_mpxj(monkeypatch, B_A_DAY_LATE)
    path = _two_activity_file(tmp_path)
    assert main(["crosscheck", "--cpm", str(path)]) == 0
    printed = capsys.readouterr().out
    assert "option MPXJ does not model: no lag calendar stated" in printed
    assert "0 difference(s) no listed cause explains" in printed


@pytest.mark.oracle("property")
def test_the_command_exits_0_when_mpxj_agrees(tmp_path, capsys, monkeypatch):
    from xerscope.cli import main

    _fake_mpxj(monkeypatch, HAND_DATES["B"])
    path = _two_activity_file(tmp_path, sched=LAG_PRED)
    assert main(["crosscheck", "--cpm", str(path)]) == 0
    assert "0 difference(s) no listed cause explains" in capsys.readouterr().out


@pytest.mark.oracle("property")
@pytest.mark.parametrize(("agrees", "exit_code"), [([True, True], 0), ([True, False], 1)])
def test_the_reader_comparison_exits_1_on_a_disagreement(tmp_path, monkeypatch, capsys, agrees, exit_code):
    from xerscope import crosscheck
    from xerscope.cli import main

    path = _two_activity_file(tmp_path)
    checks = pd.DataFrame({"file": path.name, "field": ["tasks", "links"], "agree": agrees})
    monkeypatch.setattr(crosscheck, "compare_paths", lambda paths: checks)
    assert main(["crosscheck", str(path)]) == exit_code
    assert f"{agrees.count(False)} disagreement(s) out of 2 checks" in capsys.readouterr().out


@pytest.mark.oracle("property")
@pytest.mark.parametrize(("agrees", "exit_code"), [([True, True], 0), ([True, False], 1)])
def test_the_p6_comparison_exits_1_on_a_disagreement(tmp_path, monkeypatch, capsys, agrees, exit_code):
    from xerscope import crosscheck
    from xerscope.cli import main

    scores = pd.DataFrame(
        {
            "set": "H1", "case": "c1", "task_code": ["A", "B"], "status": "TK_NotStart",
            "field": "early_start", "p6": "x", "xerscope": "x", "agree": agrees, "resource_dependent": False,
        }
    )  # fmt: skip
    monkeypatch.setattr(crosscheck, "p6_heldout_score", lambda folder: scores)
    assert main(["crosscheck", "--p6", str(tmp_path)]) == exit_code
