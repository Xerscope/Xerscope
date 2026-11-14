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

from .config import DATE_FMT, DATETIME_FMT

HOURS_PER_DAY = 8
PROJECT_ID = "4501"
PROJECT_CODE = "PRJ-ALPHA"
CREATED = "2026-08-24 09:00"  # create / add date of everything in the demo
RSRC_CREW = "5001"
RSRC_VENDOR = "5002"
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


def _links_by_end(links) -> tuple[dict[str, list], dict[str, list]]:
    """The links of each activity: those arriving at it, those leaving it."""
    predecessors_of, successors_of = defaultdict(list), defaultdict(list)
    for predecessor, successor, link_type, lag in links:
        predecessors_of[successor].append((predecessor, link_type, lag))
        successors_of[predecessor].append((successor, link_type, lag))
    return predecessors_of, successors_of


def _remaining_days(activity: Activity) -> int:
    return 0 if activity.act_finish is not None else math.ceil(activity.remaining)


def _cpm(activities: dict[str, Activity], links, data_day: int) -> dict[str, dict]:
    """Forward/backward pass in whole days from the data day ``data_day``."""
    order = _topo(activities, links)
    predecessors_of, successors_of = _links_by_end(links)
    scheduled = [code for code in order if activities[code].kind != "TT_LOE"]  # a level of effort follows the rest

    early: dict[str, tuple[int, int]] = {}  # code -> (early start, early finish)
    for code in scheduled:
        early[code] = _early_days(activities[code], predecessors_of[code], activities, early, data_day)
    finish = max(early_finish for _, early_finish in early.values())

    late_finish: dict[str, int] = {}
    for code in reversed(scheduled):
        late_finish[code] = _late_finish_day(activities[code], successors_of[code], activities, late_finish, finish)

    out: dict[str, dict[str, int | None]] = {}
    for code in order:
        activity = activities[code]
        if activity.kind == "TT_LOE":
            loe_start = activity.act_start if activity.act_start is not None else data_day
            out[code] = {"es": loe_start, "ef": finish, "lf": finish, "tf": 0}
        else:
            early_start, early_finish = early[code]
            total_float = None if activity.act_finish is not None else late_finish[code] - early_finish
            out[code] = {"es": early_start, "ef": early_finish, "lf": late_finish[code], "tf": total_float}
    return out


def _early_days(
    activity: Activity,
    predecessor_links: list,
    activities: dict[str, Activity],
    early: dict[str, tuple[int, int]],
    data_day: int,
) -> tuple[int, int]:
    """Early start and finish of one activity: its actual dates, else what its predecessors allow."""
    if activity.act_start is not None and activity.act_finish is not None:  # finished, so started
        return activity.act_start, activity.act_finish
    remaining = _remaining_days(activity)
    if activity.act_start is not None:
        return activity.act_start, data_day + remaining
    start = data_day
    for predecessor, link_type, lag in predecessor_links:
        if activities[predecessor].kind != "TT_LOE":
            start = max(start, _start_a_link_allows(link_type, lag, early[predecessor], remaining))
    if activity.constraint == "CS_MSOA" and activity.constraint_day is not None:
        start = max(start, activity.constraint_day)
    return start, start + remaining


def _start_a_link_allows(link_type: str, lag: int, predecessor_early: tuple[int, int], remaining: int) -> int:
    """The earliest start one link leaves to its successor, which has ``remaining`` days to do."""
    predecessor_start, predecessor_finish = predecessor_early
    return {
        "FS": predecessor_finish + lag,
        "SS": predecessor_start + lag,
        "FF": predecessor_finish + lag - remaining,
        "SF": predecessor_start + lag - remaining,
    }[link_type]


def _late_finish_day(
    activity: Activity,
    successor_links: list,
    activities: dict[str, Activity],
    late_finish: dict[str, int],
    finish: int,
) -> int:
    """Late finish of one activity: its actual finish, else what its open successors allow."""
    if activity.act_finish is not None:
        return activity.act_finish
    remaining = _remaining_days(activity)
    late = finish
    for successor, link_type, lag in successor_links:
        successor_activity = activities[successor]
        if successor_activity.kind == "TT_LOE" or successor_activity.act_finish is not None:
            continue
        successor_late_start = late_finish[successor] - _remaining_days(successor_activity)
        allowed = _finish_a_link_allows(link_type, lag, successor_late_start, late_finish[successor], remaining)
        late = min(late, allowed)
    if activity.constraint == "CS_MEOB" and activity.constraint_day is not None:
        late = min(late, activity.constraint_day)
    return late


def _finish_a_link_allows(
    link_type: str, lag: int, successor_late_start: int, successor_late_finish: int, remaining: int
) -> int:
    """The latest finish one link leaves to its predecessor, which has ``remaining`` days to do."""
    return {
        "FS": successor_late_start - lag,
        "SS": successor_late_start - lag + remaining,
        "FF": successor_late_finish - lag,
        "SF": successor_late_finish - lag + remaining,
    }[link_type]


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
    predecessors_of, _ = _links_by_end(links)
    for code in _topo(activities, links):
        activity = activities[code]
        if activity.kind == "TT_LOE":
            if activity.act_start is None:
                activity.act_start = activities["M1000"].act_start  # starts with the project, once it has
            continue
        if activity.act_finish is not None:
            continue
        work_from = _start_when_allowed(activity, predecessors_of[code], activities, previous_data_day, data_day)
        if work_from is not None:
            _work(activity, work_from, data_day, (lost or {}).get(code, 0), rng)


def _start_when_allowed(
    activity: Activity,
    predecessor_links: list,
    activities: dict[str, Activity],
    previous_data_day: int,
    data_day: int,
) -> int | None:
    """The day ``activity`` works from in this period; None when it has no work to do.

    One already started works from the previous data day. One not started starts on the day its
    logic allows, when that day is in the period. No work: it cannot start yet, or it is a
    milestone, reached at once.
    """
    if activity.act_start is not None:
        return previous_data_day
    allowed = _day_logic_allows(activity, predecessor_links, activities, previous_data_day)
    if allowed >= data_day:
        return None
    activity.act_start = int(allowed)
    if activity.duration == 0:
        activity.act_finish = activity.act_start
        return None
    return activity.act_start


def _day_logic_allows(
    activity: Activity, predecessor_links: list, activities: dict[str, Activity], previous_data_day: int
) -> float:
    """The first day ``activity`` may start, infinite while a predecessor holds it back.

    An FS link holds it until its predecessor finishes, an SS link until it starts; FF and SF
    links hold no start back.
    """
    allowed: float = previous_data_day
    for predecessor, link_type, lag in predecessor_links:
        predecessor_activity = activities[predecessor]
        if predecessor_activity.kind == "TT_LOE" or link_type in ("FF", "SF"):
            continue
        reached = predecessor_activity.act_finish if link_type == "FS" else predecessor_activity.act_start
        allowed = max(allowed, reached + lag) if reached is not None else math.inf
    if activity.constraint == "CS_MSOA" and activity.constraint_day is not None:
        allowed = max(allowed, activity.constraint_day)
    return allowed


def _work(activity: Activity, work_from: int, data_day: int, days_lost: int, rng: random.Random) -> None:
    """The work of one period taken off what remains; the activity finishes when nothing remains."""
    productivity_today = activity.productivity * rng.uniform(0.9, 1.1)
    work = max(0, data_day - work_from - days_lost) * productivity_today
    if work >= activity.remaining:
        days_needed = math.ceil(activity.remaining / productivity_today)
        activity.act_finish = min(data_day, work_from + days_lost + days_needed)
        activity.remaining = 0
    else:
        activity.remaining -= work


def _day(day_index: int) -> date:
    return START + timedelta(days=day_index)


def _start_text(day_index: int | None) -> str:  # start-of-day timestamp
    return "" if day_index is None else f"{_day(day_index):{DATE_FMT}} 08:00"


def _constraint_text(activity: Activity) -> str:
    """Constraint date as P6 writes it: an "on or after" constraint is a start, the others a finish."""
    if not activity.constraint:
        return ""
    if activity.constraint == "CS_MSOA":
        return _start_text(activity.constraint_day)
    return _finish_text(activity.constraint_day)


def _finish_text(day_index: int | None) -> str:  # end of the day before the exclusive day index
    return "" if day_index is None else f"{_day(day_index - 1):{DATE_FMT}} 16:00"


def _finish(early_finish: int, duration: int, kind: str) -> str:
    if kind == "TT_Mile" or (duration == 0 and kind != "TT_FinMile"):
        return _start_text(early_finish)
    return _finish_text(early_finish)


def _write(path: Path, tables: dict[str, tuple[list[str], list[list]]], export: date) -> None:
    lines = [f"ERMHDR\t23.12\t{export:{DATE_FMT}}\tProject\tadmin\tPlanner\tdbxDatabaseNoName\tProject Management\tEUR"]
    for name, (columns, rows) in tables.items():
        lines.append(f"%T\t{name}")
        lines.append("%F\t" + "\t".join(columns))
        lines.extend(
            "%R\t" + "\t".join("" if value is None else str(value) for value in row_values) for row_values in rows
        )
    lines.append("%E")
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252"))


XER_TASK_FIELDS = [
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


XER_TASKRSRC_FIELDS = [
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


def _stamp(timestamp) -> str:
    return "" if timestamp is None or pd.isna(timestamp) else f"{timestamp:{DATETIME_FMT}}"


def _store_p6_dates(path: Path, tables: dict, export: date) -> None:
    """Replace the simulation's dates by the validated P6-style CPM, as P6 would store them.

    The simple day-based CPM above drives the week-by-week progress; what the files carry
    (early/late dates, float, remaining dates) is recalculated with analysis.cpm, so the
    demo passes the same integrity check a real P6 export does.
    """
    from .analysis.cpm import schedule
    from .xer import load_snapshot

    recomputed = schedule(load_snapshot(path))
    _store_task_dates(tables["TASK"][1], recomputed.frame)
    _store_assignment_dates(tables["TASKRSRC"][1], recomputed.assignments.set_index("taskrsrc_id"))
    project_columns, project_rows = tables["PROJECT"]
    project_rows[0][project_columns.index("scd_end_date")] = _stamp(recomputed.frame["ef"].max())
    _write(path, tables, export)


def _store_task_dates(task_rows: list[list], recomputed) -> None:
    """Dates, floats and Longest Path flag of every open activity, written in its TASK row."""
    position = {column: index for index, column in enumerate(XER_TASK_FIELDS)}
    for row in task_rows:
        code, status = row[position["task_code"]], row[position["status_code"]]
        if code not in recomputed.index or status == "TK_Complete":
            continue
        dates = recomputed.loc[code]
        row[position["early_start_date"]] = _stamp(dates["remaining_start"])  # P6 stores the remaining start
        row[position["early_end_date"]] = _stamp(dates["ef"])
        row[position["late_start_date"]] = _stamp(dates["ls"])
        row[position["late_end_date"]] = _stamp(dates["lf"])
        row[position["total_float_hr_cnt"]] = f"{dates['tf_hr']:g}"
        row[position["free_float_hr_cnt"]] = f"{dates['ff_hr']:g}"
        if status == "TK_Active":
            row[position["restart_date"]] = _stamp(dates["remaining_start"])
            row[position["reend_date"]] = _stamp(dates["ef"])
        row[position["driving_path_flag"]] = "Y" if dates["longest_path"] else "N"


ASSIGNMENT_DATES = {  # column of the recalculated assignments -> TASKRSRC column P6 stores it in
    "restart": "restart_date",
    "reend": "reend_date",
    "rem_late_start": "rem_late_start_date",
    "rem_late_end": "rem_late_end_date",
}


def _store_assignment_dates(assignment_rows: list[list], recomputed) -> None:
    """Remaining dates of every assignment recalculated, written in its TASKRSRC row."""
    position = {column: index for index, column in enumerate(XER_TASKRSRC_FIELDS)}
    for row in assignment_rows:
        taskrsrc_id = str(row[position["taskrsrc_id"]])
        if taskrsrc_id not in recomputed.index:
            continue
        dates = recomputed.loc[taskrsrc_id]
        for computed_column, stored_column in ASSIGNMENT_DATES.items():
            row[position[stored_column]] = _stamp(dates[computed_column])


def _task_id(snapshot_index: int, row_index: int) -> int:
    return 100000 + snapshot_index * 1000 + row_index


def _set_targets(activities: dict[str, Activity], day_schedule: dict) -> None:
    """Planned dates and constraint dates are fixed the first time an activity is scheduled."""
    for code, activity in activities.items():
        if activity.target is not None:
            continue
        activity.target = (day_schedule[code]["es"], day_schedule[code]["ef"])
        if activity.constraint:
            anchor = activity.target[1] if activity.constraint == "CS_MEOB" else activity.target[0]
            activity.constraint_day = anchor + activity.constraint_offset


def _status(activity: Activity, dates: dict, data_day: int) -> tuple[str, int, int]:
    """P6 status code, remaining days and percent complete of an activity at the data day."""
    if activity.act_finish is not None:
        return "TK_Complete", 0, 100
    started = activity.act_start is not None
    status = "TK_Active" if started else "TK_NotStart"
    remaining_days = max(0, dates["ef"] - data_day) if activity.kind == "TT_LOE" else math.ceil(activity.remaining)
    percent = 0
    if started and activity.duration:
        percent = min(99, max(0, round(100 * (activity.duration - activity.remaining) / activity.duration)))
    return status, remaining_days, percent


def _early_texts(activity: Activity, dates: dict, data_day: int) -> tuple[str, str]:
    """Early start and finish as P6 writes them: actual, then remaining, then planned."""
    done = activity.act_finish is not None
    if activity.act_finish is not None:
        start = _start_text(activity.act_start)
        finish = _finish(activity.act_finish, activity.duration, activity.kind)
    elif activity.act_start is not None:
        start = _start_text(data_day)
        finish = _finish(dates["ef"], dates["ef"] - dates["es"], activity.kind)
    else:
        start = _start_text(dates["es"])
        finish = _finish(dates["ef"], activity.duration, activity.kind)
    if activity.kind == "TT_FinMile" and not done:
        start = finish
    return start, finish


def _actual_finish_text(snapshot_index: int, activity: Activity, data_day: int) -> str:
    """Actual finish as the file writes it; "" while the activity is open."""
    if activity.act_finish is None:
        return ""
    if snapshot_index >= 6 and activity.code == "C3010":  # injected data-quality issue
        return _finish_text(data_day + 3)  # two days after the data date
    return _finish(activity.act_finish, activity.duration, activity.kind)


def _labour_hours(activity: Activity, remaining_days: int, data_day: int) -> tuple[int, int, int]:
    """Budget, actual and remaining labour hours of an activity: its crew, eight hours a day."""
    crew = CREW[activity.wbs] if activity.has_resource and activity.duration > 0 else 0
    days_worked = 0
    if activity.act_start is not None:
        worked_until = data_day if activity.act_finish is None else min(data_day, activity.act_finish)
        days_worked = worked_until - activity.act_start
    return (
        activity.duration * HOURS_PER_DAY * crew,
        days_worked * HOURS_PER_DAY * crew,
        remaining_days * HOURS_PER_DAY * crew,
    )


def _task_row(
    snapshot_index: int, row_index: int, activity: Activity, dates: dict, data_day: int
) -> tuple[list, tuple[int, int, int]]:
    """One TASK row, and the (budget, actual, remaining) labour hours that go with it."""
    done = activity.act_finish is not None
    started = activity.act_start is not None
    status, remaining_days, percent = _status(activity, dates, data_day)
    early_start_text, early_finish_text = _early_texts(activity, dates, data_day)
    actual_end_text = _actual_finish_text(snapshot_index, activity, data_day)
    total_float = dates["tf"]
    hours = _labour_hours(activity, remaining_days, data_day)
    row = [
        _task_id(snapshot_index, row_index),
        PROJECT_ID,
        WBS_ID[activity.wbs],
        CALENDAR_ID,
        percent,
        "CP_Phys",
        activity.kind,
        "DT_FixedDUR2",
        status,
        activity.code,
        activity.name,
        "" if total_float is None else total_float * HOURS_PER_DAY,
        "",
        remaining_days * HOURS_PER_DAY,
        activity.duration * HOURS_PER_DAY,
        _constraint_text(activity),
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
        CREATED,
        _start_text(data_day),
        *hours,
    ]
    return row, hours


def _link_rows(snapshot_index: int, links: list, task_ids: dict[str, int]) -> list[list]:
    return [
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


def _assignment_rows(
    snapshot_index: int, activities: dict[str, Activity], task_ids: dict[str, int], hours: dict[str, tuple]
) -> list[list]:
    # units per hour = crew size, so remaining units / rate = the activity's remaining hours
    rows = [
        [
            800000 + snapshot_index * 1000 + index,
            task_ids[code],
            PROJECT_ID,
            RSRC_CREW,
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
    rows += [
        [
            890000 + snapshot_index * 1000 + index,
            task_ids[code],
            PROJECT_ID,
            RSRC_VENDOR,
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
    return rows


def _project_table(data_day: int, finish_day: int) -> tuple[list[str], list[list]]:
    columns = [
        "proj_id",
        "proj_short_name",
        "clndr_id",
        "plan_start_date",
        "plan_end_date",
        "scd_end_date",
        "last_recalc_date",
        "add_date",
    ]
    row = [
        PROJECT_ID,
        PROJECT_CODE,
        CALENDAR_ID,
        _start_text(0),
        "",
        _finish_text(finish_day),
        _start_text(data_day),
        CREATED,
    ]
    return columns, [row]


def _fixed_tables() -> dict[str, tuple[list[str], list[list]]]:
    """The tables that are the same in every weekly file."""
    return {
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
            [[wid, PROJECT_ID, n, flag, short, name, parent] for n, (wid, short, name, parent, flag) in enumerate(WBS)],
        ),
        "RSRC": (
            ["rsrc_id", "rsrc_short_name", "rsrc_name", "rsrc_type", "clndr_id"],
            [
                [RSRC_CREW, "CREW", "Site crew", "RT_Labor", CALENDAR_ID],
                [RSRC_VENDOR, "VENDOR", "Vendor", "RT_Mat", CALENDAR_ID],
            ],
        ),
    }


def _tables(snapshot_index: int, activities: dict[str, Activity], links, day_schedule: dict, data_day: int) -> dict:
    """The tables of one weekly file, in the order the file writes them."""
    task_rows = []
    hours: dict[str, tuple[int, int, int]] = {}
    for row_index, (code, activity) in enumerate(activities.items()):
        row, hours[code] = _task_row(snapshot_index, row_index, activity, day_schedule[code], data_day)
        task_rows.append(row)
    task_ids = {code: _task_id(snapshot_index, row_index) for row_index, code in enumerate(activities)}
    finish_day = max(dates["ef"] for dates in day_schedule.values())
    return {
        "PROJECT": _project_table(data_day, finish_day),
        **_fixed_tables(),
        "TASK": (XER_TASK_FIELDS, task_rows),
        "TASKPRED": (
            ["task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_proj_id", "pred_type", "lag_hr_cnt"],
            _link_rows(snapshot_index, links, task_ids),
        ),
        "TASKRSRC": (XER_TASKRSRC_FIELDS, _assignment_rows(snapshot_index, activities, task_ids, hours)),
    }


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
        _set_targets(activities, day_schedule)

        tables = _tables(snapshot_index, activities, links, day_schedule, data_day)
        data_date = _day(data_day)
        path = output_dir / f"{PROJECT_CODE}_{data_date:{DATE_FMT}}.xer"
        _write(path, tables, data_date + timedelta(days=1))
        _store_p6_dates(path, tables, data_date + timedelta(days=1))
        paths.append(path)
        previous_data_day = data_day
    return paths


if __name__ == "__main__":
    import sys

    for written in generate(sys.argv[1] if len(sys.argv) > 1 else "data/sample"):
        print(written)
