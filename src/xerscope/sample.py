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

HOURS_PER_DAY = 8
PROJECT_ID = "4501"
PROJECT_CODE = "PRJ-ALPHA"
PROJECT_NAME = "Usine de traitement – Phase 1"  # en dash + accent: exercises cp1252
CALENDAR_ID = "601"
# every day 08:00-16:00, written in full (P6 exports always carry the blob; without it each
# reader would guess the working week its own way)
CALENDAR_DATA = (
    "(0||CalendarData()((0||DaysOfWeek()("
    + "".join(f"(0||{d}()((0||0(s|08:00|f|16:00)())))" for d in range(1, 8))
    + "))(0||Exceptions()())))"
)
START = date(2026, 8, 31)

WBS = [  # wbs_id, short name, name, parent, proj_node_flag
    ("7000", PROJECT_CODE, PROJECT_NAME, "", "Y"),
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
class Activity:
    code: str
    name: str
    wbs: str
    duration: int
    kind: str = "TT_Task"
    constraint: str = ""
    constraint_offset: int = 0  # constraint date = first-schedule date + offset
    productivity: float = 1.0
    has_resource: bool = True
    since: int = 0  # first snapshot index the activity exists in
    # runtime
    remaining: float = 0.0
    act_start: int | None = None
    act_finish: int | None = None  # exclusive day index
    target: tuple[int, int] | None = None
    constraint_day: int | None = None


def _activities() -> list[Activity]:
    return [
        Activity("M1000", "Notice to proceed", "PM", 0, "TT_Mile"),
        Activity("E1010", "Basic design", "ENG", 15),
        Activity("E1020", "Detailed design – civil", "ENG", 20),
        Activity("E1030", "Detailed design – mechanical", "ENG", 25, productivity=0.7),
        Activity("E1040", "Detailed design – electrical", "ENG", 20),
        Activity("E1050", "IFC drawings issued", "ENG", 5, has_resource=False),
        Activity("P2010", "Long-lead equipment RFQ", "PRC", 10),
        Activity("P2020", "Bid evaluation & award", "PRC", 10),
        Activity("P2030", "Equipment fabrication", "PRC", 60, productivity=0.8),
        Activity("P2040", "Equipment delivery", "PRC", 10, constraint="CS_MSOA"),
        Activity("P2050", "Bulk materials procurement", "PRC", 30),
        Activity("C3010", "Site mobilisation", "CIV", 5),
        Activity("C3020", "Earthworks", "CIV", 15),
        Activity("C3030", "Foundations", "CIV", 20, productivity=0.85),
        Activity("C3040", "Underground utilities", "CIV", 15),
        Activity("C3045", "Additional drainage works", "CIV", 10, since=4),
        Activity("C3050", "Structural steel erection", "CIV", 25),
        Activity("C3060", "Roads & paving", "CIV", 10),
        Activity("M3099", "Civil works complete", "CIV", 0, "TT_FinMile"),
        Activity("X4010", "Equipment setting", "MEC", 15),
        Activity("X4020", "Piping installation", "MEC", 30),
        Activity("X4030", "Electrical installation", "MEC", 30),
        Activity("X4040", "Instrumentation", "MEC", 20),
        Activity("X4050", "Mechanical completion", "MEC", 0, "TT_FinMile", constraint="CS_MEOB", constraint_offset=3),
        Activity("K5010", "Pre-commissioning", "COM", 15),
        Activity("K5020", "Commissioning", "COM", 15),
        Activity("K5030", "Performance test", "COM", 10),
        Activity("K5040", "Handover documentation", "COM", 20, has_resource=False),
        Activity("L0001", "Project management & controls", "PM", 0, "TT_LOE"),
        Activity("M9999", "Project completion", "PM", 0, "TT_FinMile"),
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


def _links(snapshot_index: int, activities: dict[str, Activity]):
    return [
        (predecessor, successor, link_type, lag)
        for predecessor, successor, link_type, lag, (first_snapshot, last_snapshot) in LINKS
        if first_snapshot <= snapshot_index <= last_snapshot and predecessor in activities and successor in activities
    ]


def _topo(activities: dict[str, Activity], links) -> list[str]:
    in_degree = dict.fromkeys(activities, 0)
    successors_of = defaultdict(list)
    for predecessor, successor, *_ in links:
        successors_of[predecessor].append(successor)
        in_degree[successor] += 1
    queue = deque(code for code in activities if in_degree[code] == 0)
    order = []
    while queue:
        code = queue.popleft()
        order.append(code)
        for successor in successors_of[code]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)
    if len(order) != len(activities):
        raise ValueError("cycle in sample network")
    return order


def _cpm(activities: dict[str, Activity], links, data_day: int) -> dict[str, dict]:
    """Forward/backward pass in whole days from the data day ``data_day``."""
    order = _topo(activities, links)
    preds, succs = defaultdict(list), defaultdict(list)
    for predecessor, successor, link_type, lag in links:
        preds[successor].append((predecessor, link_type, lag))
        succs[predecessor].append((successor, link_type, lag))

    def remaining_days(activity: Activity) -> int:
        return 0 if activity.act_finish is not None else math.ceil(activity.remaining)

    early_start, early_finish = {}, {}
    for code in order:
        activity = activities[code]
        if activity.kind == "TT_LOE":
            continue
        if activity.act_finish is not None:
            early_start[code], early_finish[code] = activity.act_start, activity.act_finish
            continue
        remaining = remaining_days(activity)
        if activity.act_start is not None:
            early_start[code], early_finish[code] = activity.act_start, data_day + remaining
            continue
        start = data_day
        for predecessor, link_type, lag in preds[code]:
            if activities[predecessor].kind == "TT_LOE":
                continue
            start = max(
                start,
                {
                    "FS": early_finish[predecessor] + lag,
                    "SS": early_start[predecessor] + lag,
                    "FF": early_finish[predecessor] + lag - remaining,
                    "SF": early_start[predecessor] + lag - remaining,
                }[link_type],
            )
        if activity.constraint == "CS_MSOA" and activity.constraint_day is not None:
            start = max(start, activity.constraint_day)
        early_start[code], early_finish[code] = start, start + remaining

    finish = max(early_finish.values())
    late_finish: dict[str, int] = {}
    for code in reversed(order):
        activity = activities[code]
        if activity.kind == "TT_LOE":
            continue
        if activity.act_finish is not None:
            late_finish[code] = activity.act_finish
            continue
        remaining = remaining_days(activity)
        late = finish
        for successor, link_type, lag in succs[code]:
            successor_activity = activities[successor]
            if successor_activity.kind == "TT_LOE" or successor_activity.act_finish is not None:
                continue
            successor_late_start = late_finish[successor] - remaining_days(successor_activity)
            late = min(
                late,
                {
                    "FS": successor_late_start - lag,
                    "SS": successor_late_start - lag + remaining,
                    "FF": late_finish[successor] - lag,
                    "SF": late_finish[successor] - lag + remaining,
                }[link_type],
            )
        if activity.constraint == "CS_MEOB" and activity.constraint_day is not None:
            late = min(late, activity.constraint_day)
        late_finish[code] = late

    out = {}
    for code in order:
        activity = activities[code]
        if activity.kind == "TT_LOE":
            loe_start = activity.act_start if activity.act_start is not None else data_day
            out[code] = {"es": loe_start, "ef": finish, "lf": finish, "tf": 0}
        else:
            out[code] = {
                "es": early_start[code],
                "ef": early_finish[code],
                "lf": late_finish[code],
                "tf": None if activity.act_finish is not None else late_finish[code] - early_finish[code],
            }
    return out


STALLS = {4: {"E1040": 3}, 6: {"E1020": 7}}  # snapshot -> {activity: working days lost}


def _progress(
    activities: dict[str, Activity],
    links,
    previous_data_day: int,
    data_day: int,
    rng: random.Random,
    lost: dict[str, int] | None = None,
) -> None:
    """Advance work from previous_data_day to data_day, respecting FS/SS logic with actual dates."""
    order = _topo(activities, links)
    preds = defaultdict(list)
    for predecessor, successor, link_type, lag in links:
        preds[successor].append((predecessor, link_type, lag))
    for code in order:
        activity = activities[code]
        if activity.kind == "TT_LOE":
            if activity.act_start is None and activities["M1000"].act_start is not None:
                activity.act_start = activities["M1000"].act_start
            continue
        if activity.act_finish is not None:
            continue
        if activity.act_start is None:
            allowed = previous_data_day
            for predecessor, link_type, lag in preds[code]:
                predecessor_activity = activities[predecessor]
                if predecessor_activity.kind == "TT_LOE" or link_type in ("FF", "SF"):
                    continue
                if link_type == "FS":
                    allowed = (
                        max(allowed, predecessor_activity.act_finish + lag)
                        if predecessor_activity.act_finish is not None
                        else math.inf
                    )
                else:  # SS
                    allowed = (
                        max(allowed, predecessor_activity.act_start + lag)
                        if predecessor_activity.act_start is not None
                        else math.inf
                    )
            if activity.constraint == "CS_MSOA" and activity.constraint_day is not None:
                allowed = max(allowed, activity.constraint_day)
            if allowed >= data_day:
                continue
            allowed = int(allowed)
            if activity.duration == 0:
                activity.act_start = activity.act_finish = allowed
                continue
            activity.act_start = allowed
        else:
            allowed = previous_data_day
        productivity_today = activity.productivity * rng.uniform(0.9, 1.1)
        work = max(0, data_day - allowed - (lost or {}).get(code, 0)) * productivity_today
        if work >= activity.remaining:
            activity.act_finish = min(
                data_day, allowed + (lost or {}).get(code, 0) + math.ceil(activity.remaining / productivity_today)
            )
            activity.remaining = 0
        else:
            activity.remaining -= work


def _day(day_index: int) -> date:
    return START + timedelta(days=day_index)


def _start_text(day_index: int | None) -> str:  # start-of-day timestamp
    return "" if day_index is None else f"{_day(day_index):%Y-%m-%d} 08:00"


def _constraint_text(activity: Activity) -> str:
    """Constraint date as P6 writes it: an "on or after" constraint is a start, the others a finish."""
    if not activity.constraint:
        return ""
    if activity.constraint == "CS_MSOA":
        return _start_text(activity.constraint_day)
    return _finish_text(activity.constraint_day)


def _finish_text(day_index: int | None) -> str:  # end of the day before the exclusive day index
    return "" if day_index is None else f"{_day(day_index - 1):%Y-%m-%d} 16:00"


def _finish(early_finish: int, duration: int, kind: str) -> str:
    if kind == "TT_Mile" or (duration == 0 and kind != "TT_FinMile"):
        return _start_text(early_finish)
    return _finish_text(early_finish)


def _write(path: Path, tables: dict[str, tuple[list[str], list[list]]], export: date) -> None:
    lines = [f"ERMHDR\t23.12\t{export:%Y-%m-%d}\tProject\tadmin\tPlanner\tdbxDatabaseNoName\tProject Management\tEUR"]
    for name, (columns, rows) in tables.items():
        lines.append(f"%T\t{name}")
        lines.append("%F\t" + "\t".join(columns))
        lines.extend(
            "%R\t" + "\t".join("" if value is None else str(value) for value in row_values) for row_values in rows
        )
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

    recomputed = schedule(load_snapshot(path))
    frame = recomputed.frame
    assignment_column = {code: column_index for column_index, code in enumerate(ASSIGNMENT_COLS)}
    assignment_dates = recomputed.assignments.set_index("taskrsrc_id")
    task_column = {code: day_index for day_index, code in enumerate(TASK_COLS)}

    def format_timestamp(timestamp) -> str:
        return "" if timestamp is None or pd.isna(timestamp) else f"{timestamp:%Y-%m-%d %H:%M}"

    for row in tables["TASK"][1]:
        code, status = row[task_column["task_code"]], row[task_column["status_code"]]
        if code not in frame.index or status == "TK_Complete":
            continue
        dates = frame.loc[code]
        row[task_column["early_start_date"]] = format_timestamp(
            dates["remaining_start"]
        )  # P6 stores the remaining start
        row[task_column["early_end_date"]] = format_timestamp(dates["ef"])
        row[task_column["late_start_date"]] = format_timestamp(dates["ls"])
        row[task_column["late_end_date"]] = format_timestamp(dates["lf"])
        row[task_column["total_float_hr_cnt"]] = f"{dates['tf_hr']:g}"
        row[task_column["free_float_hr_cnt"]] = f"{dates['ff_hr']:g}"
        if status == "TK_Active":
            row[task_column["restart_date"]], row[task_column["reend_date"]] = (
                format_timestamp(dates["remaining_start"]),
                format_timestamp(dates["ef"]),
            )
        row[task_column["driving_path_flag"]] = "Y" if dates["longest_path"] else "N"
    for row in tables["TASKRSRC"][1]:  # assignment remaining dates, as P6 stores them
        taskrsrc_id = str(row[assignment_column["taskrsrc_id"]])
        if taskrsrc_id in assignment_dates.index:
            dates = assignment_dates.loc[taskrsrc_id]
            for computed_name, stored_name in (
                ("restart", "restart_date"),
                ("reend", "reend_date"),
                ("rem_late_start", "rem_late_start_date"),
                ("rem_late_end", "rem_late_end_date"),
            ):
                row[assignment_column[stored_name]] = format_timestamp(dates[computed_name])
    project_columns, project_rows = tables["PROJECT"]
    project_rows[0][project_columns.index("scd_end_date")] = format_timestamp(frame["ef"].max())
    _write(path, tables, export)


def generate(out_dir: str | Path, weeks: int = 8, seed: int = 7) -> list[Path]:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    pool = {activity.code: activity for activity in _activities()}
    for activity in pool.values():
        activity.remaining = activity.duration
    paths: list[Path] = []
    previous_data_day = 0

    for snapshot_index in range(weeks):
        data_day = 7 * snapshot_index
        activities = {code: activity for code, activity in pool.items() if activity.since <= snapshot_index}
        links = _links(snapshot_index, activities)
        if snapshot_index > 0:
            _progress(activities, links, previous_data_day, data_day, rng, STALLS.get(snapshot_index))
        if snapshot_index == 5 and activities["P2030"].act_finish is None:
            activities["P2030"].remaining += 10  # vendor delay
        day_schedule = _cpm(activities, links, data_day)

        for code, activity in activities.items():  # planned dates + constraint dates fixed on first schedule
            if activity.target is None:
                activity.target = (day_schedule[code]["es"], day_schedule[code]["ef"])
                if activity.constraint:
                    anchor = activity.target[1] if activity.constraint == "CS_MEOB" else activity.target[0]
                    activity.constraint_day = anchor + activity.constraint_offset

        data_date = _day(data_day)
        task_rows = []
        hours: dict[str, tuple[int, int, int]] = {}
        for row_index, (code, activity) in enumerate(activities.items()):
            dates = day_schedule[code]
            done = activity.act_finish is not None
            started = activity.act_start is not None
            if done:
                status, remaining_days, percent = "TK_Complete", 0, 100
            else:
                status = "TK_Active" if started else "TK_NotStart"
                remaining_days = (
                    max(0, dates["ef"] - data_day) if activity.kind == "TT_LOE" else math.ceil(activity.remaining)
                )
                percent = (
                    min(99, max(0, round(100 * (activity.duration - activity.remaining) / activity.duration)))
                    if started and activity.duration
                    else 0
                )
            constraint_text = _constraint_text(activity)
            duration_for_dates = dates["ef"] - dates["es"]
            if done:
                early_start_text, early_finish_text = (
                    _start_text(activity.act_start),
                    _finish(activity.act_finish, activity.duration, activity.kind),
                )
            elif started:
                early_start_text, early_finish_text = (
                    _start_text(data_day),
                    _finish(dates["ef"], duration_for_dates, activity.kind),
                )
            else:
                early_start_text, early_finish_text = (
                    _start_text(dates["es"]),
                    _finish(dates["ef"], activity.duration, activity.kind),
                )
            if activity.kind == "TT_FinMile" and not done:
                early_start_text = early_finish_text
            actual_end_text = _finish(activity.act_finish, activity.duration, activity.kind) if done else ""
            if snapshot_index >= 6 and code == "C3010" and done:  # injected data-quality issue
                actual_end_text = f"{data_date + timedelta(days=2):%Y-%m-%d} 16:00"
            total_float = dates["tf"]
            crew = CREW[activity.wbs] if activity.has_resource and activity.duration > 0 else 0
            worked = (
                0 if not started else (min(data_day, activity.act_finish if done else data_day) - activity.act_start)
            )
            budget_hours, actual_hours, remaining_hours = (
                activity.duration * HOURS_PER_DAY * crew,
                worked * HOURS_PER_DAY * crew,
                remaining_days * HOURS_PER_DAY * crew,
            )
            hours[code] = (budget_hours, actual_hours, remaining_hours)
            task_rows.append(
                [
                    100000 + snapshot_index * 1000 + row_index,
                    PROJECT_ID,
                    WBS_ID[activity.wbs],
                    CALENDAR_ID,
                    percent,
                    "CP_Phys",
                    activity.kind,
                    "DT_FixedDUR2",
                    status,
                    code,
                    activity.name,
                    "" if total_float is None else total_float * HOURS_PER_DAY,
                    "",
                    remaining_days * HOURS_PER_DAY,
                    activity.duration * HOURS_PER_DAY,
                    constraint_text,
                    _start_text(activity.act_start) if started else "",
                    actual_end_text,
                    "" if done else _start_text(dates["lf"] - remaining_days),
                    "" if done else _finish(dates["lf"], remaining_days, activity.kind),
                    "",
                    early_start_text,
                    early_finish_text,
                    _start_text(data_day) if started and not done else "",
                    early_finish_text if started and not done else "",
                    _start_text(activity.target[0]),
                    _finish(activity.target[1], activity.duration, activity.kind),
                    activity.constraint,
                    "Y" if (total_float is not None and total_float <= 0 and activity.kind != "TT_LOE") else "N",
                    "",
                    "2026-08-24 09:00",
                    f"{data_date:%Y-%m-%d} 08:00",
                    budget_hours,
                    actual_hours,
                    remaining_hours,
                ]
            )
        task_ids = {task_row[9]: task_row[0] for task_row in task_rows}
        pred_rows = [
            [
                900000 + snapshot_index * 1000 + index,
                task_ids[successor],
                task_ids[predecessor],
                PROJECT_ID,
                PROJECT_ID,
                f"PR_{link_type}",
                lag * HOURS_PER_DAY,
            ]
            for index, (predecessor, successor, link_type, lag) in enumerate(links)
        ]
        # units per hour = crew size, so remaining units / rate = the activity's remaining hours
        assignment_rows = [
            [
                800000 + snapshot_index * 1000 + index,
                task_ids[code],
                PROJECT_ID,
                "5001",
                *hours[code],
                CREW[activity.wbs],
                CREW[activity.wbs],
                "Y",
                "",
                "",
                "",
                "",
            ]
            for index, (code, activity) in enumerate(activities.items())
            if activity.has_resource and activity.duration > 0
        ]
        assignment_rows += [
            [
                890000 + snapshot_index * 1000 + index,
                task_ids[code],
                PROJECT_ID,
                "5002",
                1,
                0,
                1,
                0,
                0,
                "N",
                "",
                "",
                "",
                "",
            ]
            for index, code in enumerate(("P2030", "P2040"))
            if code in task_ids
        ]  # vendor supply, no hours
        finish_day = max(activity["ef"] for activity in day_schedule.values())

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
                [
                    [
                        PROJECT_ID,
                        PROJECT_CODE,
                        CALENDAR_ID,
                        _start_text(0),
                        "",
                        _finish_text(finish_day),
                        _start_text(data_day),
                        "2026-08-24 09:00",
                    ]
                ],
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
                    "clndr_data",
                ],
                [
                    [
                        CALENDAR_ID,
                        "Y",
                        "7 jours / 8 h",
                        "",
                        "",
                        "CA_Base",
                        HOURS_PER_DAY,
                        HOURS_PER_DAY * 7,
                        HOURS_PER_DAY * 30,
                        HOURS_PER_DAY * 365,
                        CALENDAR_DATA,
                    ]
                ],
            ),
            # P6's default scheduling options, written out so every reader applies the same
            "SCHEDOPTIONS": (
                [
                    "schedoptions_id",
                    "proj_id",
                    "sched_retained_logic",
                    "sched_progress_override",
                    "sched_lag_early_start_flag",
                    "sched_open_critical_flag",
                    "sched_float_type",
                    "sched_calendar_on_relationship_lag",
                    "sched_use_expect_end_flag",
                    "sched_outer_depend_type",
                ],
                [["1", PROJECT_ID, "Y", "N", "Y", "N", "FT_FF", "rcal_Predecessor", "Y", "SD_Both"]],
            ),
            "PROJWBS": (
                ["wbs_id", "proj_id", "seq_num", "proj_node_flag", "wbs_short_name", "wbs_name", "parent_wbs_id"],
                [
                    [wid, PROJECT_ID, n, flag, short, name, parent]
                    for n, (wid, short, name, parent, flag) in enumerate(WBS)
                ],
            ),
            "RSRC": (
                ["rsrc_id", "rsrc_short_name", "rsrc_name", "rsrc_type", "clndr_id"],
                [
                    ["5001", "CREW", "Site crew", "RT_Labor", CALENDAR_ID],
                    ["5002", "VENDOR", "Vendor", "RT_Mat", CALENDAR_ID],
                ],
            ),
            "TASK": (TASK_COLS, task_rows),
            "TASKPRED": (
                ["task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_proj_id", "pred_type", "lag_hr_cnt"],
                pred_rows,
            ),
            "TASKRSRC": (ASSIGNMENT_COLS, assignment_rows),
        }
        path = output_dir / f"{PROJECT_CODE}_{data_date:%Y-%m-%d}.xer"
        _write(path, tables, data_date + timedelta(days=1))
        _store_p6_dates(path, tables, data_date + timedelta(days=1))
        paths.append(path)
        previous_data_day = data_day
    return paths


if __name__ == "__main__":
    import sys

    for written in generate(sys.argv[1] if len(sys.argv) > 1 else "data/sample"):
        print(written)
