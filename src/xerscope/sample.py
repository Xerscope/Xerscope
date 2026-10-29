"""Generate a realistic series of weekly XER updates for demos and tests.

The project is progressed week by week and rescheduled with a small CPM engine, so
dates, float and logic are internally consistent. Deliberate events give the analysis
step something to find:

- week 0: baseline (no progress). P2030 is a 60-day activity (DCMA high duration).
- week 2+: E1030 and P2030 progress slowly -> slippage, float erosion.
- week 4: activity C3045 is added (scope change).
- week 5: P2030 remaining duration +10 d (vendor delay) -> X4050's hard constraint
          (finish on or before) produces negative float.
- week 6: X4030's SS+10 link from C3050 becomes FS (logic change);
          C3010's actual finish is pushed after the data date (invalid date).
- week 4: E1040 loses 3 days, week 6: E1020 loses 7 days -> both miss the finish the
          previous update forecast (PPC below 100 %).
- always: E1040 -> E1050 has a 3-day lead, K5040 has no successor (open end),
          K5040 and E1050 have no resources.
- task_id changes in every file (as after a re-import); task_code stays stable.
- labour hours: each resourced activity has a crew (1-4 people, 8 h/day). Budget = duration
  x crew; actual = days worked x crew, so slow activities burn more hours than they earn.

Dates use a 7-day, 8 h/day calendar to keep the scheduling arithmetic simple.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HPD = 8
PROJ_ID = "4501"
PROJ_CODE = "PRJ-ALPHA"
PROJ_NAME = "Usine de traitement – Phase 1"  # en dash + accent: exercises cp1252
CLNDR_ID = "601"
START = date(2026, 8, 31)

WBS = [  # wbs_id, short name, name, parent, proj_node_flag
    ("7000", PROJ_CODE, PROJ_NAME, "", "Y"),
    ("7001", "ENG", "Ingénierie", "7000", "N"),
    ("7002", "PRC", "Procurement", "7000", "N"),
    ("7003", "CIV", "Civil works", "7000", "N"),
    ("7004", "MEC", "Mechanical & electrical", "7000", "N"),
    ("7005", "COM", "Commissioning", "7000", "N"),
    ("7006", "PM", "Project management", "7000", "N"),
]
WBS_ID = {short: wid for wid, short, *_ in WBS}
CREW = {"ENG": 2, "PRC": 1, "CIV": 4, "MEC": 3, "COM": 2, "PM": 1}


@dataclass
class Act:
    code: str
    name: str
    wbs: str
    dur: int
    kind: str = "TT_Task"
    cstr: str = ""
    cstr_offset: int = 0  # constraint date = first-schedule date + offset
    productivity: float = 1.0
    has_rsrc: bool = True
    since: int = 0  # first snapshot index the activity exists in
    # runtime
    remaining: float = 0.0
    act_start: int | None = None
    act_finish: int | None = None  # exclusive day index
    target: tuple[int, int] | None = None
    cstr_day: int | None = None


def _activities() -> list[Act]:
    return [
        Act("M1000", "Notice to proceed", "PM", 0, "TT_Mile"),
        Act("E1010", "Basic design", "ENG", 15),
        Act("E1020", "Detailed design – civil", "ENG", 20),
        Act("E1030", "Detailed design – mechanical", "ENG", 25, productivity=0.7),
        Act("E1040", "Detailed design – electrical", "ENG", 20),
        Act("E1050", "IFC drawings issued", "ENG", 5, has_rsrc=False),
        Act("P2010", "Long-lead equipment RFQ", "PRC", 10),
        Act("P2020", "Bid evaluation & award", "PRC", 10),
        Act("P2030", "Equipment fabrication", "PRC", 60, productivity=0.8),
        Act("P2040", "Equipment delivery", "PRC", 10, cstr="CS_MSOA"),
        Act("P2050", "Bulk materials procurement", "PRC", 30),
        Act("C3010", "Site mobilisation", "CIV", 5),
        Act("C3020", "Earthworks", "CIV", 15),
        Act("C3030", "Foundations", "CIV", 20, productivity=0.85),
        Act("C3040", "Underground utilities", "CIV", 15),
        Act("C3045", "Additional drainage works", "CIV", 10, since=4),
        Act("C3050", "Structural steel erection", "CIV", 25),
        Act("C3060", "Roads & paving", "CIV", 10),
        Act("M3099", "Civil works complete", "CIV", 0, "TT_FinMile"),
        Act("X4010", "Equipment setting", "MEC", 15),
        Act("X4020", "Piping installation", "MEC", 30),
        Act("X4030", "Electrical installation", "MEC", 30),
        Act("X4040", "Instrumentation", "MEC", 20),
        Act("X4050", "Mechanical completion", "MEC", 0, "TT_FinMile", cstr="CS_MEOB", cstr_offset=3),
        Act("K5010", "Pre-commissioning", "COM", 15),
        Act("K5020", "Commissioning", "COM", 15),
        Act("K5030", "Performance test", "COM", 10),
        Act("K5040", "Handover documentation", "COM", 20, has_rsrc=False),
        Act("L0001", "Project management & controls", "PM", 0, "TT_LOE"),
        Act("M9999", "Project completion", "PM", 0, "TT_FinMile"),
    ]


# pred, succ, type, lag (days), (first snapshot, last snapshot) the link exists in
LINKS: list[tuple[str, str, str, int, tuple[int, int]]] = [
    ("M1000", "E1010", "FS", 0, (0, 99)),
    ("M1000", "C3010", "FS", 0, (0, 99)),
    ("E1010", "E1020", "FS", 0, (0, 99)),
    ("E1010", "E1030", "FS", 0, (0, 99)),
    ("E1010", "E1040", "SS", 5, (0, 99)),
    ("E1010", "P2010", "FS", 0, (0, 99)),
    ("E1020", "E1050", "FS", 0, (0, 99)),
    ("E1030", "E1050", "FS", 0, (0, 99)),
    ("E1040", "E1050", "FS", -3, (0, 99)),  # lead
    ("P2010", "P2020", "FS", 0, (0, 99)),
    ("P2020", "P2030", "FS", 0, (0, 99)),
    ("P2030", "P2040", "FS", 0, (0, 99)),
    ("E1050", "P2050", "FS", 0, (0, 99)),
    ("C3010", "C3020", "FS", 0, (0, 99)),
    ("E1020", "C3020", "FS", 0, (0, 99)),
    ("C3020", "C3030", "FS", 0, (0, 99)),
    ("C3020", "C3040", "SS", 5, (0, 99)),
    ("C3030", "C3050", "FS", 0, (0, 99)),
    ("P2050", "C3050", "FS", 0, (0, 99)),
    ("C3040", "C3060", "FS", 0, (0, 3)),
    ("C3040", "C3045", "FS", 0, (4, 99)),
    ("C3045", "C3060", "FS", 0, (4, 99)),
    ("C3050", "M3099", "FS", 0, (0, 99)),
    ("C3060", "M3099", "FS", 0, (0, 99)),
    ("C3030", "X4010", "FS", 0, (0, 99)),
    ("P2040", "X4010", "FS", 0, (0, 99)),
    ("X4010", "X4020", "FS", 0, (0, 99)),
    ("P2050", "X4020", "FS", 0, (0, 99)),
    ("C3050", "X4030", "SS", 10, (0, 5)),
    ("C3050", "X4030", "FS", 0, (6, 99)),
    ("X4030", "X4040", "FS", 0, (0, 99)),
    ("X4020", "X4050", "FS", 0, (0, 99)),
    ("X4040", "X4050", "FS", 0, (0, 99)),
    ("M3099", "X4050", "FS", 0, (0, 99)),
    ("X4050", "K5010", "FS", 0, (0, 99)),
    ("K5010", "K5020", "FS", 0, (0, 99)),
    ("K5020", "K5030", "FS", 0, (0, 99)),
    ("K5030", "M9999", "FS", 0, (0, 99)),
    ("K5010", "K5040", "SS", 5, (0, 99)),  # K5040 has no successor: open end
    ("M1000", "L0001", "SS", 0, (0, 99)),
    ("L0001", "M9999", "FF", 0, (0, 99)),
]


def _links(snap: int, acts: dict[str, Act]):
    return [(p, s, t, lag) for p, s, t, lag, (a, b) in LINKS if a <= snap <= b and p in acts and s in acts]


def _topo(acts: dict[str, Act], links) -> list[str]:
    indeg = dict.fromkeys(acts, 0)
    out = defaultdict(list)
    for p, s, *_ in links:
        out[p].append(s)
        indeg[s] += 1
    q = deque(c for c in acts if indeg[c] == 0)
    order = []
    while q:
        c = q.popleft()
        order.append(c)
        for s in out[c]:
            indeg[s] -= 1
            if indeg[s] == 0:
                q.append(s)
    if len(order) != len(acts):
        raise ValueError("cycle in sample network")
    return order


def _cpm(acts: dict[str, Act], links, dd: int) -> dict[str, dict]:
    """Forward/backward pass in whole days from data date ``dd``."""
    order = _topo(acts, links)
    preds, succs = defaultdict(list), defaultdict(list)
    for p, s, typ, lag in links:
        preds[s].append((p, typ, lag))
        succs[p].append((s, typ, lag))

    def rem(a: Act) -> int:
        return 0 if a.act_finish is not None else math.ceil(a.remaining)

    es, ef = {}, {}
    for c in order:
        a = acts[c]
        if a.kind == "TT_LOE":
            continue
        if a.act_finish is not None:
            es[c], ef[c] = a.act_start, a.act_finish
            continue
        d = rem(a)
        if a.act_start is not None:
            es[c], ef[c] = a.act_start, dd + d
            continue
        start = dd
        for p, typ, lag in preds[c]:
            if acts[p].kind == "TT_LOE":
                continue
            start = max(
                start,
                {
                    "FS": ef[p] + lag,
                    "SS": es[p] + lag,
                    "FF": ef[p] + lag - d,
                    "SF": es[p] + lag - d,
                }[typ],
            )
        if a.cstr == "CS_MSOA" and a.cstr_day is not None:
            start = max(start, a.cstr_day)
        es[c], ef[c] = start, start + d

    finish = max(ef.values())
    lf: dict[str, int] = {}
    for c in reversed(order):
        a = acts[c]
        if a.kind == "TT_LOE":
            continue
        if a.act_finish is not None:
            lf[c] = a.act_finish
            continue
        d = rem(a)
        late = finish
        for s, typ, lag in succs[c]:
            sa = acts[s]
            if sa.kind == "TT_LOE" or sa.act_finish is not None:
                continue
            ls_s = lf[s] - rem(sa)
            late = min(
                late,
                {
                    "FS": ls_s - lag,
                    "SS": ls_s - lag + d,
                    "FF": lf[s] - lag,
                    "SF": lf[s] - lag + d,
                }[typ],
            )
        if a.cstr == "CS_MEOB" and a.cstr_day is not None:
            late = min(late, a.cstr_day)
        lf[c] = late

    out = {}
    for c in order:
        a = acts[c]
        if a.kind == "TT_LOE":
            s0 = a.act_start if a.act_start is not None else dd
            out[c] = dict(es=s0, ef=finish, lf=finish, tf=0)
        else:
            out[c] = dict(es=es[c], ef=ef[c], lf=lf[c], tf=None if a.act_finish is not None else lf[c] - ef[c])
    return out


STALLS = {4: {"E1040": 3}, 6: {"E1020": 7}}  # snapshot -> {activity: working days lost}


def _progress(
    acts: dict[str, Act], links, prev_dd: int, dd: int, rng: random.Random, lost: dict[str, int] | None = None
) -> None:
    """Advance work from prev_dd to dd, respecting FS/SS logic with actual dates."""
    order = _topo(acts, links)
    preds = defaultdict(list)
    for p, s, typ, lag in links:
        preds[s].append((p, typ, lag))
    for c in order:
        a = acts[c]
        if a.kind == "TT_LOE":
            if a.act_start is None and acts["M1000"].act_start is not None:
                a.act_start = acts["M1000"].act_start
            continue
        if a.act_finish is not None:
            continue
        if a.act_start is None:
            allowed = prev_dd
            for p, typ, lag in preds[c]:
                pa = acts[p]
                if pa.kind == "TT_LOE" or typ in ("FF", "SF"):
                    continue
                if typ == "FS":
                    allowed = max(allowed, pa.act_finish + lag) if pa.act_finish is not None else math.inf
                else:  # SS
                    allowed = max(allowed, pa.act_start + lag) if pa.act_start is not None else math.inf
            if a.cstr == "CS_MSOA" and a.cstr_day is not None:
                allowed = max(allowed, a.cstr_day)
            if allowed >= dd:
                continue
            allowed = int(allowed)
            if a.dur == 0:
                a.act_start = a.act_finish = allowed
                continue
            a.act_start = allowed
        else:
            allowed = prev_dd
        prod = a.productivity * rng.uniform(0.9, 1.1)
        work = max(0, dd - allowed - (lost or {}).get(c, 0)) * prod
        if work >= a.remaining:
            a.act_finish = min(dd, allowed + (lost or {}).get(c, 0) + math.ceil(a.remaining / prod))
            a.remaining = 0
        else:
            a.remaining -= work


def _day(i: int) -> date:
    return START + timedelta(days=i)


def _s(i: int | None) -> str:  # start-of-day timestamp
    return "" if i is None else f"{_day(i):%Y-%m-%d} 08:00"


def _f(i: int | None) -> str:  # end of the day before exclusive index i
    return "" if i is None else f"{_day(i - 1):%Y-%m-%d} 16:00"


def _finish(ef: int, dur: int, kind: str) -> str:
    if kind == "TT_Mile" or (dur == 0 and kind != "TT_FinMile"):
        return _s(ef)
    return _f(ef)


def _write(path: Path, tables: dict[str, tuple[list[str], list[list]]], export: date) -> None:
    lines = [f"ERMHDR\t23.12\t{export:%Y-%m-%d}\tProject\tadmin\tPlanner\tdbxDatabaseNoName\tProject Management\tEUR"]
    for name, (cols, rows) in tables.items():
        lines.append(f"%T\t{name}")
        lines.append("%F\t" + "\t".join(cols))
        lines.extend("%R\t" + "\t".join("" if v is None else str(v) for v in r) for r in rows)
    lines.append("%E")
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252"))


TASK_COLS = [
    "task_id",
    "proj_id",
    "wbs_id",
    "clndr_id",
    "phys_complete_pct",
    "complete_pct_type",
    "task_type",
    "duration_type",
    "status_code",
    "task_code",
    "task_name",
    "total_float_hr_cnt",
    "free_float_hr_cnt",
    "remain_drtn_hr_cnt",
    "target_drtn_hr_cnt",
    "cstr_date",
    "act_start_date",
    "act_end_date",
    "late_start_date",
    "late_end_date",
    "expect_end_date",
    "early_start_date",
    "early_end_date",
    "restart_date",
    "reend_date",
    "target_start_date",
    "target_end_date",
    "cstr_type",
    "driving_path_flag",
    "float_path",
    "create_date",
    "update_date",
    "target_work_qty",
    "act_work_qty",
    "remain_work_qty",
]


ASSIGNMENT_COLS = [
    "taskrsrc_id",
    "task_id",
    "proj_id",
    "rsrc_id",
    "target_qty",
    "act_reg_qty",
    "remain_qty",
    "target_qty_per_hr",
    "remain_qty_per_hr",
    "rollup_dates_flag",
    "restart_date",
    "reend_date",
    "rem_late_start_date",
    "rem_late_end_date",
]


def _store_p6_dates(path: Path, tables: dict, export: date) -> None:
    """Replace the simulation's dates by the validated P6-style CPM, as P6 would store them.

    The simple day-based CPM above drives the week-by-week progress; what the files carry
    (early/late dates, float, remaining dates) is recalculated with analysis.cpm, so the
    demo passes the same integrity check a real P6 export does.
    """
    from .analysis.cpm import schedule
    from .xer import load_snapshot

    sched = schedule(load_snapshot(path))
    f = sched.frame
    a_col = {c: i for i, c in enumerate(ASSIGNMENT_COLS)}
    a_dates = sched.assignments.set_index("taskrsrc_id")
    col = {c: i for i, c in enumerate(TASK_COLS)}

    def fmt(ts) -> str:
        return "" if ts is None or pd.isna(ts) else f"{ts:%Y-%m-%d %H:%M}"

    for row in tables["TASK"][1]:
        code, status = row[col["task_code"]], row[col["status_code"]]
        if code not in f.index or status == "TK_Complete":
            continue
        r = f.loc[code]
        row[col["early_start_date"]] = fmt(r["remaining_start"])  # P6 stores the remaining start
        row[col["early_end_date"]] = fmt(r["ef"])
        row[col["late_start_date"]] = fmt(r["ls"])
        row[col["late_end_date"]] = fmt(r["lf"])
        row[col["total_float_hr_cnt"]] = f"{r['tf_hr']:g}"
        row[col["free_float_hr_cnt"]] = f"{r['ff_hr']:g}"
        if status == "TK_Active":
            row[col["restart_date"]], row[col["reend_date"]] = fmt(r["remaining_start"]), fmt(r["ef"])
        row[col["driving_path_flag"]] = "Y" if r["longest_path"] else "N"
    for row in tables["TASKRSRC"][1]:  # assignment remaining dates, as P6 stores them
        k = str(row[a_col["taskrsrc_id"]])
        if k in a_dates.index:
            r = a_dates.loc[k]
            for mine, theirs in (
                ("restart", "restart_date"),
                ("reend", "reend_date"),
                ("rem_late_start", "rem_late_start_date"),
                ("rem_late_end", "rem_late_end_date"),
            ):
                row[a_col[theirs]] = fmt(r[mine])
    proj_cols, proj_rows = tables["PROJECT"]
    proj_rows[0][proj_cols.index("scd_end_date")] = fmt(f["ef"].max())
    _write(path, tables, export)


def generate(out_dir: str | Path, weeks: int = 8, seed: int = 7) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    pool = {a.code: a for a in _activities()}
    for a in pool.values():
        a.remaining = a.dur
    paths: list[Path] = []
    prev_dd = 0

    for snap in range(weeks):
        dd = 7 * snap
        acts = {c: a for c, a in pool.items() if a.since <= snap}
        links = _links(snap, acts)
        if snap > 0:
            _progress(acts, links, prev_dd, dd, rng, STALLS.get(snap))
        if snap == 5 and acts["P2030"].act_finish is None:
            acts["P2030"].remaining += 10  # vendor delay
        sched = _cpm(acts, links, dd)

        for c, a in acts.items():  # planned dates + constraint dates fixed on first schedule
            if a.target is None:
                a.target = (sched[c]["es"], sched[c]["ef"])
                if a.cstr:
                    anchor = a.target[1] if a.cstr == "CS_MEOB" else a.target[0]
                    a.cstr_day = anchor + a.cstr_offset

        data_date = _day(dd)
        task_rows = []
        hours: dict[str, tuple[int, int, int]] = {}
        for i, (c, a) in enumerate(acts.items()):
            s = sched[c]
            done = a.act_finish is not None
            started = a.act_start is not None
            status = "TK_Complete" if done else ("TK_Active" if started else "TK_NotStart")
            rem = 0 if done else (max(0, s["ef"] - dd) if a.kind == "TT_LOE" else math.ceil(a.remaining))
            pct = (
                100
                if done
                else (min(99, max(0, round(100 * (a.dur - a.remaining) / a.dur))) if started and a.dur else 0)
            )
            dur_for_dates = s["ef"] - s["es"]
            if done:
                es_txt, ef_txt = _s(a.act_start), _finish(a.act_finish, a.dur, a.kind)
            elif started:
                es_txt, ef_txt = _s(dd), _finish(s["ef"], dur_for_dates, a.kind)
            else:
                es_txt, ef_txt = _s(s["es"]), _finish(s["ef"], a.dur, a.kind)
            if a.kind == "TT_FinMile" and not done:
                es_txt = ef_txt
            act_end = _finish(a.act_finish, a.dur, a.kind) if done else ""
            if snap >= 6 and c == "C3010" and done:  # injected data-quality issue
                act_end = f"{data_date + timedelta(days=2):%Y-%m-%d} 16:00"
            tf = s["tf"]
            crew = CREW[a.wbs] if a.has_rsrc and a.dur > 0 else 0
            worked = 0 if not started else (min(dd, a.act_finish if done else dd) - a.act_start)
            budget_h, actual_h, remain_h = a.dur * HPD * crew, worked * HPD * crew, rem * HPD * crew
            hours[c] = (budget_h, actual_h, remain_h)
            task_rows.append(
                [
                    100000 + snap * 1000 + i,
                    PROJ_ID,
                    WBS_ID[a.wbs],
                    CLNDR_ID,
                    pct,
                    "CP_Phys",
                    a.kind,
                    "DT_FixedDUR2",
                    status,
                    c,
                    a.name,
                    "" if tf is None else tf * HPD,
                    "",
                    rem * HPD,
                    a.dur * HPD,
                    _s(a.cstr_day) if a.cstr == "CS_MSOA" else (_f(a.cstr_day) if a.cstr else ""),
                    _s(a.act_start) if started else "",
                    act_end,
                    "" if done else _s(s["lf"] - rem),
                    "" if done else _finish(s["lf"], rem, a.kind),
                    "",
                    es_txt,
                    ef_txt,
                    _s(dd) if started and not done else "",
                    ef_txt if started and not done else "",
                    _s(a.target[0]),
                    _finish(a.target[1], a.dur, a.kind),
                    a.cstr,
                    "Y" if (tf is not None and tf <= 0 and a.kind != "TT_LOE") else "N",
                    "",
                    "2026-08-24 09:00",
                    f"{data_date:%Y-%m-%d} 08:00",
                    budget_h,
                    actual_h,
                    remain_h,
                ]
            )
        ids = {r[9]: r[0] for r in task_rows}
        pred_rows = [
            [900000 + snap * 1000 + k, ids[s], ids[p], PROJ_ID, PROJ_ID, f"PR_{t}", lag * HPD]
            for k, (p, s, t, lag) in enumerate(links)
        ]
        # units per hour = crew size, so remaining units / rate = the activity's remaining hours
        rsrc_rows = [
            [
                800000 + snap * 1000 + k,
                ids[c],
                PROJ_ID,
                "5001",
                *hours[c],
                CREW[a.wbs],
                CREW[a.wbs],
                "Y",
                "",
                "",
                "",
                "",
            ]
            for k, (c, a) in enumerate(acts.items())
            if a.has_rsrc and a.dur > 0
        ]
        rsrc_rows += [
            [890000 + snap * 1000 + k, ids[c], PROJ_ID, "5002", 1, 0, 1, 0, 0, "N", "", "", "", ""]
            for k, c in enumerate(("P2030", "P2040"))
            if c in ids
        ]  # vendor supply, no hours
        finish_day = max(v["ef"] for v in sched.values())

        tables = {
            "PROJECT": (
                [
                    "proj_id",
                    "proj_short_name",
                    "clndr_id",
                    "plan_start_date",
                    "plan_end_date",
                    "scd_end_date",
                    "last_recalc_date",
                    "add_date",
                ],
                [[PROJ_ID, PROJ_CODE, CLNDR_ID, _s(0), "", _f(finish_day), _s(dd), "2026-08-24 09:00"]],
            ),
            "CALENDAR": (
                [
                    "clndr_id",
                    "default_flag",
                    "clndr_name",
                    "proj_id",
                    "base_clndr_id",
                    "clndr_type",
                    "day_hr_cnt",
                    "week_hr_cnt",
                    "month_hr_cnt",
                    "year_hr_cnt",
                ],
                [[CLNDR_ID, "Y", "7 jours / 8 h", "", "", "CA_Base", HPD, HPD * 7, HPD * 30, HPD * 365]],
            ),
            "PROJWBS": (
                ["wbs_id", "proj_id", "seq_num", "proj_node_flag", "wbs_short_name", "wbs_name", "parent_wbs_id"],
                [
                    [wid, PROJ_ID, n, flag, short, name, parent]
                    for n, (wid, short, name, parent, flag) in enumerate(WBS)
                ],
            ),
            "RSRC": (
                ["rsrc_id", "rsrc_short_name", "rsrc_name", "rsrc_type", "clndr_id"],
                [["5001", "CREW", "Site crew", "RT_Labor", CLNDR_ID], ["5002", "VENDOR", "Vendor", "RT_Mat", CLNDR_ID]],
            ),
            "TASK": (TASK_COLS, task_rows),
            "TASKPRED": (
                ["task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_proj_id", "pred_type", "lag_hr_cnt"],
                pred_rows,
            ),
            "TASKRSRC": (ASSIGNMENT_COLS, rsrc_rows),
        }
        path = out / f"{PROJ_CODE}_{data_date:%Y-%m-%d}.xer"
        _write(path, tables, data_date + timedelta(days=1))
        _store_p6_dates(path, tables, data_date + timedelta(days=1))
        paths.append(path)
        prev_dd = dd
    return paths


if __name__ == "__main__":
    import sys

    for p in generate(sys.argv[1] if len(sys.argv) > 1 else "data/sample"):
        print(p)
