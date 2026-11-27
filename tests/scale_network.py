"""A seeded random P6 network of about 4,000 activities, built in code (no real schedule).

Eight WBS branches of chained work with links across branches (FS, SS, FF, SF; lags and
leads), three calendars (Mon-Fri 8 h with holidays, Mon-Fri 10 h with holidays, 7 days 10 h),
primary and secondary constraints, start and finish milestones, Level of Effort, resource
assignments (some activities resource dependent) and expenses, and progress (complete, in
progress, not started, 40 activities started out of sequence) around a data date at 40 % of
the planned span.

Two kinds of value are written to the file:

- what a scheduler reads (durations, logic, calendars, constraints, actual dates, remaining
  durations): xerscope's CPM and MPXJ's scheduler both recalculate from these
  (tests/test_scale_random_network.py compares them);
- what the checks read as stored (forecast dates, total float, planned dates): planted by the
  generator, activity by activity, so the activities each check must find follow from the
  generator's records (tests/test_scale_random_network.py, one function per check). They are not
  a recalculation: INT-01 would flag them, and P6 replaces them at the first F9.

The network avoids the shapes of ``crosscheck.UNRESOLVED`` and the P6_SETTLED link shapes
(``supported_link``), but carries those P6 settled against MPXJ for constraints and period edges
(``crosscheck.settled_activities``, ``edges_written_apart``) and calendars linked both ways, so the
open question ``edge_on_another_calendar`` occurs and its activities are listed for a P6 reading.

    PYTHONPATH=src:tests python tests/scale_network.py OUT.xer [SEED]
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from xerkit import clndr_data, xer_text

SEED = 2026
BRANCHES = 8
ACTIVITIES_PER_BRANCH = 495
PROJECT_START = pd.Timestamp("2026-01-05")  # a Monday
START_HOUR, FINISH_HOUR = 8, 16  # every stored start at 08:00 and finish at 16:00: inside the work of every calendar
LAG_CALENDAR = {"sched_calendar_on_relationship_lag": "rcal_Predecessor"}

# Holidays of the two Mon-Fri calendars written here (P6 day serial = days since 1899-12-30).
HOLIDAYS = [pd.Timestamp(day) for day in (
    "2026-04-03", "2026-05-01", "2026-07-14", "2026-12-25", "2027-01-01", "2027-03-26",
    "2027-05-03", "2027-07-14", "2027-12-24", "2027-12-27", "2028-01-03", "2028-04-14",
)]  # fmt: skip


def _serial(day: pd.Timestamp) -> int:
    return (day - pd.Timestamp("1899-12-30")).days


# Three calendars that do not work at the same times: the 10 h days run past the 8 h day's 17:00, the
# 7-day one over the weekend, the 10 h Mon-Fri one keeps half the 8 h one's holidays.
CALENDARS = {
    "12": (8, clndr_data(range(2, 7), [("08:00", "12:00"), ("13:00", "17:00")], tuple(map(_serial, HOLIDAYS)))),
    "11": (10, clndr_data(range(2, 7), [("07:00", "12:00"), ("13:00", "18:00")], tuple(map(_serial, HOLIDAYS[::2])))),
    "13": (10, clndr_data(range(1, 8), [("07:00", "12:00"), ("13:00", "18:00")])),
}
CALENDAR_NAMES = {"12": "Mon-Fri 8h holidays", "11": "Mon-Fri 10h holidays", "13": "7 days 10h"}
CALENDAR_WEIGHTS = {"12": 5, "11": 3, "13": 2}
RESOURCE_OF_CALENDAR = {"12": "R1", "11": "R3", "13": "R2"}
RESOURCES = [
    {"rsrc_id": "R1", "rsrc_short_name": "FITTER", "rsrc_type": "RT_Labor", "clndr_id": "12"},
    {"rsrc_id": "R2", "rsrc_short_name": "CRANE", "rsrc_type": "RT_Equip", "clndr_id": "13"},
    {"rsrc_id": "R3", "rsrc_short_name": "CREW", "rsrc_type": "RT_Labor", "clndr_id": "11"},
]


def calendar_rows() -> list[dict]:
    return [
        {
            "clndr_id": clndr_id, "clndr_name": CALENDAR_NAMES[clndr_id], "clndr_type": "CA_Project",
            "day_hr_cnt": str(hours), "week_hr_cnt": str(hours * (7 if clndr_id == "13" else 5)), "clndr_data": data,
        }
        for clndr_id, (hours, data) in CALENDARS.items()
    ]  # fmt: skip


START_CONSTRAINTS = {"CS_MSO", "CS_MSOA", "CS_MSOB", "CS_MANDSTART"}
PRIMARY_CONSTRAINTS = [
    "CS_MSO", "CS_MSOA", "CS_MSOB", "CS_MEO", "CS_MEOA", "CS_MEOB", "CS_MANDSTART", "CS_MANDFIN", "CS_ALAP",
]  # fmt: skip
# (primary, secondary): a start constraint with a finish one, as P6 lets them pair
SECONDARY_PAIRS = [("CS_MSOA", "CS_MEOB"), ("CS_MSOB", "CS_MEOA"), ("CS_MSOA", "CS_MEO"), ("CS_MEOA", "CS_MSOB")]


@dataclass
class Activity:
    """One TASK row, with what the generator decided for it."""

    code: str
    wbs_id: str
    clndr_id: str
    task_type: str = "TT_Task"
    duration_wd: int = 0
    status: str = "TK_NotStart"
    plan_start_day: int = 0  # the generator's rough plan, calendar days from PROJECT_START
    plan_finish_day: int = 0
    remain_hr: float = 0.0
    act_start: pd.Timestamp | None = None
    act_end: pd.Timestamp | None = None
    forecast_start: pd.Timestamp | None = None  # restart_date and early_start_date
    forecast_finish: pd.Timestamp | None = None  # reend_date and early_end_date
    target_start: pd.Timestamp | None = None
    target_end: pd.Timestamp | None = None
    planned_finish: pd.Timestamp | None = None  # the finish of the plan, before any date is planted
    total_float_hr: float | None = None
    cstr_type: str = ""
    cstr_date: pd.Timestamp | None = None
    cstr_type2: str = ""
    cstr_date2: pd.Timestamp | None = None
    has_assignment: bool = False
    has_expense: bool = False
    planted: set[str] = field(default_factory=set)  # what the generator planted on it, for the reader

    @property
    def hours_per_day(self) -> int:
        return CALENDARS[self.clndr_id][0]

    @property
    def target_hr(self) -> float:
        return float(self.duration_wd * self.hours_per_day)

    @property
    def is_milestone(self) -> bool:
        return self.task_type in ("TT_Mile", "TT_FinMile")

    @property
    def is_loe(self) -> bool:
        return self.task_type == "TT_LOE"

    @property
    def is_complete(self) -> bool:
        return self.status == "TK_Complete"

    @property
    def is_started(self) -> bool:
        return self.status != "TK_NotStart"


@dataclass
class Link:
    pred: str
    succ: str
    type: str  # FS, SS, FF, SF
    lag_hr: float


@dataclass
class Network:
    activities: dict[str, Activity]
    links: list[Link]
    data_date: pd.Timestamp

    def predecessors(self, code: str) -> list[Link]:
        return self._links_into.get(code, [])

    def successors(self, code: str) -> list[Link]:
        return self._links_from.get(code, [])

    def __post_init__(self):
        self._links_into: dict[str, list[Link]] = {}
        self._links_from: dict[str, list[Link]] = {}
        for link in self.links:
            self._links_into.setdefault(link.succ, []).append(link)
            self._links_from.setdefault(link.pred, []).append(link)

    def text(self, shuffle_seed: int | None = None) -> str:
        """The XER; with ``shuffle_seed``, the TASK and TASKPRED rows in another order (ids unchanged)."""
        text = xer_text(
            [task_row(activity) for activity in self.activities.values()],
            [(link.pred, link.succ, link.type, f"{link.lag_hr:g}") for link in self.links],
            data_date=_stamp(self.data_date),
            project={"plan_start_date": _stamp(PROJECT_START + pd.Timedelta(hours=START_HOUR)), "clndr_id": "12"},
            wbs=wbs_rows(),
            sched=LAG_CALENDAR,
            calendars=calendar_rows(),
            resources=RESOURCES,
            assign=[assignment_row(activity) for activity in self.activities.values() if activity.has_assignment],
            costs=[
                {"task_code": activity.code, "target_cost": "1000"}
                for activity in self.activities.values()
                if activity.has_expense
            ],
        )
        return text if shuffle_seed is None else shuffled_rows(text, ("TASK", "TASKPRED"), shuffle_seed)

    def write(self, path: str | Path, shuffle_seed: int | None = None) -> Path:
        path = Path(path)
        path.write_text(self.text(shuffle_seed), encoding="utf-8")
        return path


# --- the XER rows ----------------------------------------------------------------------------------


def _stamp(moment: pd.Timestamp | None) -> str:
    return "" if moment is None else moment.strftime("%Y-%m-%d %H:%M")


def task_row(activity: Activity) -> dict:
    """The TASK row; its task_id follows from the Activity ID, so a reordered file keeps every id."""
    return {
        "task_id": str(1000 + int(activity.code[1:]) + 10_000 * (ord(activity.code[0]) - ord("A"))),
        "task_code": activity.code,
        "wbs_id": activity.wbs_id,
        "clndr_id": activity.clndr_id,
        "task_type": activity.task_type,
        "status_code": activity.status,
        "target_drtn_hr_cnt": f"{activity.target_hr:g}",
        "remain_drtn_hr_cnt": f"{activity.remain_hr:g}",
        "total_float_hr_cnt": "" if activity.total_float_hr is None else f"{activity.total_float_hr:g}",
        "act_start_date": _stamp(activity.act_start),
        "act_end_date": _stamp(activity.act_end),
        "early_start_date": _stamp(activity.forecast_start),
        "early_end_date": _stamp(activity.forecast_finish),
        "restart_date": _stamp(activity.forecast_start),
        "reend_date": _stamp(activity.forecast_finish),
        "target_start_date": _stamp(activity.target_start),
        "target_end_date": _stamp(activity.target_end),
        "cstr_type": activity.cstr_type,
        "cstr_date": _stamp(activity.cstr_date),
        "cstr_type2": activity.cstr_type2,
        "cstr_date2": _stamp(activity.cstr_date2),
        "phys_complete_pct": "100" if activity.is_complete else "0",
    }


def wbs_rows() -> list[dict]:
    rows = [{"wbs_id": "10", "proj_id": "1", "wbs_short_name": "T", "wbs_name": "T", "proj_node_flag": "Y"}]
    for branch in range(BRANCHES):
        rows.append(_wbs(f"2{branch}", "10", f"B{branch}", f"Branch {branch}"))
        rows += [_wbs(f"3{branch}{part}", f"2{branch}", f"P{part}", f"Part {part}") for part in range(3)]
    return rows


def _wbs(wbs_id: str, parent: str, short_name: str, name: str) -> dict:
    return {
        "wbs_id": wbs_id, "proj_id": "1", "parent_wbs_id": parent, "wbs_short_name": short_name,
        "wbs_name": name, "proj_node_flag": "N", "seq_num": wbs_id,
    }  # fmt: skip


def assignment_row(activity: Activity) -> dict:
    """One driving labour assignment on the activity's own calendar: actual units = the work done."""
    done_hr = activity.target_hr - activity.remain_hr
    return {
        "task_code": activity.code, "rsrc_id": RESOURCE_OF_CALENDAR[activity.clndr_id],
        "target_qty": f"{activity.target_hr:g}", "remain_qty": f"{activity.remain_hr:g}",
        "act_reg_qty": f"{done_hr:g}", "act_ot_qty": "0", "target_qty_per_hr": "1", "remain_qty_per_hr": "1",
        "target_lag_drtn_hr_cnt": "0", "relag_drtn_hr_cnt": "0", "rollup_dates_flag": "Y",
        **({"act_start_date": _stamp(activity.act_start)} if activity.is_started else {}),
    }  # fmt: skip


def shuffled_rows(text: str, tables: tuple[str, ...], seed: int) -> str:
    """``text`` with the %R rows of each of ``tables`` in a random order; nothing else moves."""
    lines = text.splitlines()
    rnd = random.Random(seed)
    for table in tables:
        first = lines.index(f"%T\t{table}") + 2
        last = first
        while last < len(lines) and lines[last].startswith("%R"):
            last += 1
        rows = lines[first:last]
        rnd.shuffle(rows)
        lines[first:last] = rows
    return "\n".join(lines) + "\n"


# --- the network -----------------------------------------------------------------------------------


def generate(seed: int = SEED) -> Network:
    """The network of ``seed``: logic, rough plan, progress, then every planted value."""
    rnd = random.Random(seed)
    activities, links = _logic(rnd)
    _plan(activities, links)
    data_date = _data_date(activities)
    _progress(rnd, activities, links, data_date)
    links = [supported_link(link, activities) for link in links]
    for activity in activities.values():
        _dates(rnd, activity, data_date)
    _plant_progress_errors(rnd, activities, data_date)
    _plant_targets(rnd, activities, data_date)
    _plant_floats(rnd, activities)
    _plant_constraints(rnd, activities, data_date)
    _plant_resources(rnd, activities)
    return Network(activities, links, data_date)


def _logic(rnd: random.Random) -> tuple[dict[str, Activity], list[Link]]:
    """Activities and links; every activity linked on both sides except the open ends planted."""
    activities = {"A0000": Activity("A0000", "10", "12", "TT_Mile", planted={"project start"})}
    links: list[Link] = []
    no_successor: set[str] = set()
    for branch in range(BRANCHES):
        codes = _branch(rnd, branch, activities, links, no_successor)
        _loe(rnd, branch, codes, activities, links, no_successor)
    activities["Z9999"] = Activity("Z9999", "10", "13", "TT_FinMile", planted={"project finish"})
    _close_open_ends(activities, links, no_successor)
    return activities, links


def _branch(rnd, branch, activities, links, no_successor) -> list[str]:
    letter = "ABCDEFGH"[branch]
    codes: list[str] = []
    for number in range(1, ACTIVITIES_PER_BRANCH + 1):
        code = f"{letter}{number:04d}"
        activities[code] = _new_activity(rnd, code, branch, number)
        candidates = [candidate for candidate in codes[-60:] if candidate not in no_successor]
        is_without_predecessor = number > 1 and rnd.random() < 0.006
        if is_without_predecessor:
            activities[code].planted.add("no predecessor")
        elif candidates:
            for pred in rnd.sample(candidates, k=min(len(candidates), rnd.choice([1, 1, 2, 3]))):
                links.append(_random_link(rnd, pred, code))
        if branch > 0 and number > 60 and not is_without_predecessor and rnd.random() < 0.08:
            others = [f"{'ABCDEFGH'[other]}{number - shift:04d}" for other in range(branch) for shift in range(20, 60)]
            other = rnd.choice(others)
            if other not in no_successor:
                links.append(_random_link(rnd, other, code))
        if rnd.random() < 0.006:
            no_successor.add(code)
            activities[code].planted.add("no successor")
        codes.append(code)
    return codes


def _new_activity(rnd: random.Random, code: str, branch: int, number: int) -> Activity:
    calendar = rnd.choices(list(CALENDAR_WEIGHTS), weights=list(CALENDAR_WEIGHTS.values()))[0]
    wbs_id = f"3{branch}{min(2, 3 * number // ACTIVITIES_PER_BRANCH)}"
    roll = rnd.random()
    if roll < 0.03:
        return Activity(code, wbs_id, calendar, rnd.choice(["TT_Mile", "TT_FinMile"]))
    if roll < 0.05:
        return Activity(code, wbs_id, calendar, duration_wd=rnd.randint(46, 70), planted={"long"})
    if roll < 0.06 and calendar == "11":  # 36 to 44 days of 10 h: over 352 h, not over 44 days
        return Activity(code, wbs_id, calendar, duration_wd=rnd.randint(36, 44), planted={"long in hours"})
    return Activity(code, wbs_id, calendar, duration_wd=rnd.randint(2, 15))


def _random_link(rnd: random.Random, pred: str, succ: str) -> Link:
    link_type = rnd.choices(["FS", "SS", "FF", "SF"], weights=[75, 12, 10, 3])[0]
    roll = rnd.random()
    if roll < 0.12:
        lag_hr = float(rnd.choice([4, 8, 16, 24, 40, 80]))
    elif roll < 0.15:
        lag_hr = float(-rnd.choice([4, 8, 16]))
    elif roll < 0.155:
        lag_hr = float(rnd.choice([352, 400, 480]))  # at and over P6's long-lag limit
    else:
        lag_hr = 0.0
    return Link(pred, succ, link_type, lag_hr)


def _loe(rnd, branch, codes, activities, links, no_successor) -> None:
    """Two Level of Effort activities per branch: SS from early work, FF into later work or none."""
    for index in range(2):
        code = f"L{branch}{index:03d}"
        activities[code] = Activity(code, f"2{branch}", "12", "TT_LOE", duration_wd=1)
        start = rnd.choice(
            [
                candidate
                for candidate in codes[:60]
                if candidate not in no_successor and activities[candidate].clndr_id == "12"
            ]
        )
        finish = rnd.choice(
            [candidate for candidate in codes[200:400] if "no predecessor" not in activities[candidate].planted]
        )
        links.append(Link(start, code, "SS", 0.0))
        if index == 0:
            links.append(Link(code, finish, "FF", 0.0))  # a Level of Effort driving discrete work


def _close_open_ends(activities, links, no_successor) -> None:
    """The project start precedes every activity left without a predecessor, the project finish
    follows every one left without a successor; the open ends planted stay open."""
    has_predecessor = {link.succ for link in links}
    has_successor = {link.pred for link in links}
    for code, activity in activities.items():
        if code in ("A0000", "Z9999") or activity.is_loe:
            continue
        if code not in has_predecessor and "no predecessor" not in activity.planted:
            links.append(Link("A0000", code, "FS", 0.0))
        if code not in has_successor and code not in no_successor:
            links.append(Link(code, "Z9999", "FS", 0.0))


def _plan(activities: dict[str, Activity], links: list[Link]) -> None:
    """A rough forward pass in calendar days (5 working days = 7 days), to place progress and
    planted dates plausibly. No check or comparison reads it."""
    into: dict[str, list[Link]] = {}
    for link in links:
        into.setdefault(link.succ, []).append(link)
    for code in _in_link_order(activities, links):
        activity = activities[code]
        length = _calendar_days(activity, activity.duration_wd)
        start = 0
        for link in into.get(code, []):
            pred = activities[link.pred]
            lag = _calendar_days(pred, link.lag_hr / pred.hours_per_day)
            bound = {
                "FS": pred.plan_finish_day + lag + 1,
                "SS": pred.plan_start_day + lag,
                "FF": pred.plan_finish_day + lag - length,
                "SF": pred.plan_start_day + lag - length,
            }[link.type]
            start = max(start, bound)
        activity.plan_start_day, activity.plan_finish_day = start, start + length


def _in_link_order(activities, links) -> list[str]:
    """Activities in an order where every predecessor comes first (Kahn's algorithm)."""
    waiting_on = dict.fromkeys(activities, 0)
    successors: dict[str, list[str]] = {}
    for link in links:
        waiting_on[link.succ] += 1
        successors.setdefault(link.pred, []).append(link.succ)
    ready = [code for code, count in waiting_on.items() if count == 0]
    order = []
    while ready:
        code = ready.pop()
        order.append(code)
        for succ in successors.get(code, []):
            waiting_on[succ] -= 1
            if waiting_on[succ] == 0:
                ready.append(succ)
    assert len(order) == len(activities), "the generator made a loop"
    return order


def _calendar_days(activity: Activity, working_days: float) -> int:
    return round(working_days if activity.clndr_id == "13" else working_days * 7 / 5)


def _data_date(activities: dict[str, Activity]) -> pd.Timestamp:
    """The Monday nearest 40 % of the planned span, 08:00."""
    span = max(activity.plan_finish_day for activity in activities.values())
    day = PROJECT_START + pd.Timedelta(days=round(0.4 * span))
    return day - pd.Timedelta(days=day.weekday()) + pd.Timedelta(hours=START_HOUR)


def _day_of(day: int) -> pd.Timestamp:
    """Calendar day ``day`` of the plan, moved to the next Monday-Friday that is no holiday."""
    moment = PROJECT_START + pd.Timedelta(days=day)
    while moment.weekday() >= 5 or moment in HOLIDAYS:
        moment += pd.Timedelta(days=1)
    return moment


def _progress(rnd, activities, links, data_date) -> None:
    """Complete before the data date, started across it, not started after it, following the
    logic (every predecessor of a completed activity complete; an FS predecessor of a started one
    complete, an SS one started), plus 40 activities started out of sequence."""
    data_day = (data_date.normalize() - PROJECT_START).days
    into: dict[str, list[Link]] = {}
    for link in links:
        into.setdefault(link.succ, []).append(link)
    for code in _in_link_order(activities, links):
        activity = activities[code]
        if activity.is_loe:
            continue
        predecessors = [(activities[link.pred], link.type) for link in into.get(code, [])]
        if activity.plan_finish_day < data_day - 30 and all(pred.is_complete for pred, _ in predecessors):
            activity.status = "TK_Complete"
        elif activity.plan_start_day < data_day - 3 and _is_in_sequence(predecessors) and not activity.is_milestone:
            activity.status = "TK_Active"

    def is_waiting(activity):
        """A task not started, due to start within two months, whose predecessors hold it back."""
        predecessors = [(activities[link.pred], link.type) for link in into.get(activity.code, [])]
        is_soon = activity.plan_start_day < data_day + 60
        is_task = activity.status == "TK_NotStart" and activity.task_type == "TT_Task"
        return is_task and is_soon and not _is_in_sequence(predecessors)

    waiting = [activity for activity in activities.values() if is_waiting(activity)]
    for activity in rnd.sample(waiting, k=min(40, len(waiting))):
        activity.status = "TK_Active"
        activity.plan_start_day = min(activity.plan_start_day, data_day - 10)
        activity.planted.add("out of sequence")
    for activity in activities.values():
        if activity.is_loe:
            activity.status = "TK_Active" if activities[into[activity.code][0].pred].is_started else "TK_NotStart"


def _is_in_sequence(predecessors) -> bool:
    """No FS predecessor still open and no SS predecessor not started (P6-15's reading of progress)."""
    for pred, link_type in predecessors:
        if link_type == "FS" and not pred.is_complete:
            return False
        if link_type == "SS" and not pred.is_started:
            return False
    return True


def supported_link(link: Link, activities: dict[str, Activity]) -> Link:
    """The link with its type or lag changed where it would meet a shape MPXJ and xerscope read
    differently and no P6 reading settles (crosscheck.UNRESOLVED, P6_SETTLED):

    - an SF link only between two activities not started (``sf_progressed``, ``sf_from_started``);
    - no FF, SS or SF link from a completed activity into a started one (``finished_into_started``);
    - no FF / SF lag from a completed activity (``ff_sf_lag_from_finished``);
    - a lead only from work not started (``lead_from_progressed``; an SS lead from started work held
      past the data date also differs, C0459 of this network before the rule, reported 2026-11-27).
    """
    pred, succ = activities[link.pred], activities[link.succ]
    link_type, lag_hr = link.type, link.lag_hr
    if link_type == "SF" and (pred.is_started or succ.is_started):
        link_type = "FS" if pred.is_complete else "SS"
    if link_type != "FS" and pred.is_complete and succ.is_started:
        link_type = "FS"
    if link_type in ("FF", "SF") and pred.is_complete:
        lag_hr = 0.0
    if lag_hr < 0 and pred.is_started:
        lag_hr = 0.0
    return Link(link.pred, link.succ, link_type, lag_hr)


# --- stored values ---------------------------------------------------------------------------------


def _at(day: pd.Timestamp, hour: int) -> pd.Timestamp:
    return day.normalize() + pd.Timedelta(hours=hour)


def _dates(rnd: random.Random, activity: Activity, data_date: pd.Timestamp) -> None:
    """Actual and forecast dates of the activity's status, every forecast start the data date or
    later and every forecast finish at least a day after the data date."""
    start = _day_of(activity.plan_start_day)
    finish = _day_of(max(activity.plan_finish_day, activity.plan_start_day + 1))
    if activity.is_milestone:
        finish = start
    if activity.is_complete:
        activity.act_start = _at(start, START_HOUR)
        activity.act_end = _at(finish, START_HOUR if activity.is_milestone else FINISH_HOUR)
        activity.remain_hr = 0.0
        activity.planned_finish = activity.act_end
        return
    if activity.is_started:
        activity.act_start = _at(start, START_HOUR)
        done = rnd.uniform(0.2, 0.8)
        activity.remain_hr = max(2 * activity.hours_per_day, round(activity.target_hr * (1 - done)))
        if activity.is_loe:
            activity.remain_hr = activity.target_hr
        activity.forecast_start = data_date
        activity.forecast_finish = _at(
            _day_of(
                (data_date.normalize() - PROJECT_START).days
                + _calendar_days(activity, activity.remain_hr / activity.hours_per_day)
                + 1
            ),
            FINISH_HOUR,
        )
        activity.planned_finish = activity.forecast_finish
        return
    activity.remain_hr = activity.target_hr
    first = max(start, data_date.normalize())
    activity.forecast_start = data_date if first == data_date.normalize() else _at(first, START_HOUR)
    length = _calendar_days(activity, activity.duration_wd)
    if activity.is_milestone:
        activity.forecast_finish = activity.forecast_start
    else:
        activity.forecast_finish = _at(_day_of((first - PROJECT_START).days + max(1, length)), FINISH_HOUR)
    activity.planned_finish = activity.forecast_finish


def _plant_progress_errors(rnd, activities, data_date) -> None:
    """Dates on the wrong side of the data date, a handful of each kind, never on the same activity."""
    tasks = [activity for activity in activities.values() if activity.task_type == "TT_Task" and not activity.planted]
    not_started = [activity for activity in tasks if not activity.is_started]
    started = [activity for activity in tasks if activity.status == "TK_Active"]
    completed = [activity for activity in tasks if activity.is_complete]
    picks = rnd.sample(not_started, 30)
    for activity in picks[:18]:  # forecast start days before the data date
        activity.forecast_start = _at(data_date - pd.Timedelta(days=rnd.randint(2, 20)), START_HOUR)
        activity.planted.add("forecast start before the data date")
    for activity in picks[18:]:  # an hour before the data date, on its day
        activity.forecast_start = data_date - pd.Timedelta(hours=1)
        activity.planted.add("forecast start an hour before the data date")
    picks = rnd.sample(started, 24)
    for activity in picks[:8]:
        activity.forecast_start = _at(data_date - pd.Timedelta(days=rnd.randint(2, 9)), START_HOUR)
        activity.planted.add("remaining start before the data date")
    for activity in picks[8:16]:
        activity.forecast_finish = _at(data_date - pd.Timedelta(days=rnd.randint(2, 9)), FINISH_HOUR)
        activity.planted.add("forecast finish before the data date")
    for activity in picks[16:]:
        activity.act_start = _at(data_date + pd.Timedelta(days=rnd.randint(2, 9)), START_HOUR)
        activity.forecast_start = activity.act_start
        activity.planted.add("actual start after the data date")
    for activity in rnd.sample(completed, 8):
        activity.act_end = _at(data_date + pd.Timedelta(days=rnd.randint(2, 9)), FINISH_HOUR)
        activity.planted.add("actual finish after the data date")


def _plant_targets(rnd, activities, data_date) -> None:
    """Planned dates (the baseline the checks read): the plan, a week or more before the current
    finish for one activity in six (late); see ``_baseline_finish``. Six open milestones and Level of
    Effort activities have none."""
    for activity in activities.values():
        activity.target_start = _at(_day_of(activity.plan_start_day), START_HOUR)
        current = activity.act_end if activity.is_complete else activity.forecast_finish
        is_planted_late = not activity.is_milestone and rnd.random() < 1 / 6
        late_by = pd.Timedelta(days=rnd.randint(7, 25)) if is_planted_late else None
        activity.target_end = _baseline_finish(activity.planned_finish, current, data_date, late_by)
    start_milestone, finish_milestone = activities["A0000"], activities["Z9999"]
    start_milestone.target_start = min(activity.target_start for activity in activities.values()) - pd.Timedelta(days=1)
    finish_milestone.target_end = max(activity.target_end for activity in activities.values()) + pd.Timedelta(days=1)
    without = [
        activity
        for activity in activities.values()
        if (activity.is_milestone or activity.is_loe) and not activity.is_complete and activity.code != "Z9999"
    ]
    for activity in rnd.sample(without, 6):
        activity.target_start = activity.target_end = None
        activity.planted.add("no planned dates")


def _baseline_finish(planned, current, data_date, late_by) -> pd.Timestamp:
    """The planned finish, or ``late_by`` before the current finish; moved earlier a day at a time
    until it is not on the data date's day and the current finish is either no later or a week or
    more later, so "late" never hangs on hours of working time or on reading dates by day."""
    target = planned if late_by is None else current - late_by
    while target.normalize() == data_date.normalize() or pd.Timedelta(0) < current - target < pd.Timedelta(days=7):
        target -= pd.Timedelta(days=1)
    return target


def _plant_floats(rnd, activities) -> None:
    """Stored total float of every open activity: mostly 0 to 300 h; then over 44 days, between
    352 h and 44 days (10 h calendar), exactly at each limit, and negative."""
    for activity in activities.values():
        if activity.is_complete:
            continue
        roll = rnd.random()
        limit_wd_hr = 44 * activity.hours_per_day
        if roll < 0.08:
            activity.total_float_hr = float(limit_wd_hr + rnd.randint(1, 1500))
        elif roll < 0.11 and activity.hours_per_day == 10:
            activity.total_float_hr = float(rnd.randint(353, 440))
        elif roll < 0.12:
            activity.total_float_hr = float(rnd.choice([352, 352.5, limit_wd_hr]))
        elif roll < 0.17:
            activity.total_float_hr = float(-rnd.randint(1, 400))
        else:
            activity.total_float_hr = float(rnd.randint(0, 300))


def _plant_constraints(rnd, activities, data_date) -> None:
    """A primary constraint on one activity in fifteen (milestones, started and completed work
    included), a primary and a secondary one on one in fifty; no constraint on Level of Effort."""
    for activity in activities.values():
        if activity.is_loe or activity.code in ("A0000", "Z9999"):
            continue
        roll = rnd.random()
        anchor = activity.target_start if activity.target_start is not None else data_date
        if roll < 1 / 15:
            activity.cstr_type = rnd.choice(_constraints_of(activity))
        elif roll < 1 / 15 + 1 / 50 and not activity.is_milestone:
            activity.cstr_type, activity.cstr_type2 = rnd.choice(SECONDARY_PAIRS)
            activity.cstr_date2 = _at(_day_of((anchor - PROJECT_START).days + rnd.randint(10, 60)), FINISH_HOUR)
        if activity.cstr_type and activity.cstr_type != "CS_ALAP":
            activity.cstr_date = _at(
                _day_of((anchor.normalize() - PROJECT_START).days + rnd.randint(-5, 20)), START_HOUR
            )


def _constraints_of(activity: Activity) -> list[str]:
    """P6 offers a start milestone start constraints only, a finish milestone finish constraints only."""
    if activity.task_type == "TT_Mile":
        return [
            candidate for candidate in PRIMARY_CONSTRAINTS if candidate in START_CONSTRAINTS or candidate == "CS_ALAP"
        ]
    if activity.task_type == "TT_FinMile":
        return [candidate for candidate in PRIMARY_CONSTRAINTS if candidate not in START_CONSTRAINTS]
    return PRIMARY_CONSTRAINTS


def _plant_resources(rnd, activities) -> None:
    """A labour assignment on most tasks, an expense on some of the rest, nothing on one in eight;
    a fifth of the unstarted tasks with an assignment made resource dependent."""
    for activity in activities.values():
        if activity.is_milestone or activity.is_loe:
            continue
        roll = rnd.random()
        if roll < 0.75:
            activity.has_assignment = True
            if not activity.is_started and rnd.random() < 0.2 and not activity.cstr_type:
                activity.task_type = "TT_Rsrc"
        elif roll < 0.875:
            activity.has_expense = True


def main(argv: list[str]) -> int:
    out = Path(argv[0])
    seed = int(argv[1]) if len(argv) > 1 else SEED
    generate(seed).write(out)
    print(f"wrote {out} (seed {seed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
