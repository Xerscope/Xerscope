"""Critical path method, as Primavera P6 (Professional 23.12 / 24) schedules a project.

Every date is computed on the activity's own calendar to the minute (``TimeAxis``), with
P6's conventions: a start is the beginning of a working period, a finish the end of one,
so a 1-day task starting Monday 08:00 finishes Monday 17:00 and its FS successor starts
Tuesday 08:00.

Forward pass (early dates), in topological order, for each open activity:

- start  >= data date; suspended work: start >= resume date
- FS: start  >= pred finish + lag        SS: start  >= pred start + lag
- FF: finish >= pred finish + lag        SF: finish >= pred start + lag
- lag counted on the calendar the project names (successor by default, predecessor, 24 h,
  project default)
- SS / SF lag of a started predecessor, option "Calculate start-to-start lag from": Early
  Start (default) = the predecessor's remaining early start + the lag not yet expired
  (expired = working time from its actual start to the data date); Actual Start = its
  actual start + the full lag (a finished predecessor's too)
- constraints: start on / on or after -> start >= date; finish on / on or after -> finish
  >= date; mandatory start / finish pin the date whatever the logic, except that the early
  dates never fall before the data date; a constraint of the wrong kind on a milestone
  (finish constraint on a start milestone) is ignored
- in progress: actual start kept; the remaining duration starts at the data date, after
  open predecessors too under Retained Logic (P6 default) and Actual Dates; under Progress
  Override its start is an actual, so FS / SS predecessors no longer bound it while FF / SF
  predecessors still bound its finish
- expected finish (option on): the early finish, or the early start when it falls before
  it (remaining 0); an FF / SF bound later than that wins; ALAP ignores it (``expected_finish``)
- finished, under Retained Logic: logic passes through it (out-of-sequence progress, see
  ``pred_bounds``)
- finish = start + remaining duration (minutes of the activity's calendar)
- resource dependent: the bound is taken on the activity's calendar, each driving
  assignment is placed from it on its resource's calendar (+ assignment lag, duration =
  remaining units / units per hour), the activity starts at the earliest assignment
  start on its own calendar and the assignments run forward from there (``rsrc_early``)

Backward pass (late dates), in reverse order: the same relationships mirrored (an SS/SF
lag that has partly expired in the forward pass is shortened the same way), started
from the project's "must finish by" date when it has one (else the latest early
finish), open ends there too (or at their own early finish if the project makes open
ends critical), and no late finish after it; a finished successor passes back the late
date its own successors give it, less the full FS / FF lag or the unexpired SS / SF lag
(nothing between two finished activities); under Progress Override FS / SS links into a
started successor bind nothing (its start is an actual), FF / SF links still do; start on
/ on or before -> late start <= date; finish on / on or before -> late finish <= date;
mandatory dates pinned. Under Actual Dates, a started successor bounds its predecessors
by its actual dates (out-of-sequence progress gives negative float, as Oracle warns).

Float, in working hours of the activity's calendar: total = late - early finish (P6
option "finish float", default), or start, or the smaller of the two (``FLOAT_TYPE``);
free = time to the earliest successor constraint (under Progress Override, work under way
runs past its own SS / SF links and past finished successors). As-late-as-possible
activities then move right by their free float. Level-of-effort activities run from the
earliest date their start-type links give (SS / FS predecessors, SS / SF successors) to
the latest their finish-type links give (FF / SF predecessors, FF / FS successors), their
late dates the same way from their links' late dates; they drive nothing.

Validated against P6's own output: the P6 Professional 23.12.1 held-out corpus
(tests/test_p6_heldout.py, which names the corpus activity each rule above was taken from)
and four real exports whose every stored date the engine reproduces (tests/test_cpm.py).
MPXJ's PrimaveraScheduler is a second opinion only (crosscheck.P6_SETTLED, UNRESOLVED).
See docs/cpm.md.

Not modelled (reported in ``warnings``): leveling, multiple float paths, relationships to
projects not in the file.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field

import pandas as pd

from ..xer import Snapshot
from ..xer.calendar import TimeAxis, WorkCalendar

START_LIKE = {"CS_MSO": "start", "CS_MSOA": "start", "CS_MEO": "finish", "CS_MEOA": "finish"}  # forward
LATE_LIKE = {"CS_MSO": "start", "CS_MSOB": "start", "CS_MEO": "finish", "CS_MEOB": "finish"}  # backward
MANDATORY = {"CS_MANDSTART": "start", "CS_MANDFIN": "finish"}
PROGRESSED = ("retained_logic", "progress_override", "actual_dates")
H24 = WorkCalendar("__24h__", "24 hours", 24.0, (((0, 1440),),) * 7, {}, from_data=False)


class CycleError(ValueError):
    """The logic has a loop; ``members`` are the activities on a loop (not the ones downstream of it)."""

    def __init__(self, message: str, members: tuple[str, ...] = ()):
        super().__init__(message)
        self.members = members


def _loop_members(candidates: set[str], successors: dict[str, list]) -> list[str]:
    """Activities of ``candidates`` that lie on a loop: strongly connected components of more than
    one activity, or an activity linked to itself (Tarjan, iterative)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    members: list[str] = []
    for root in sorted(candidates):
        if root in index:
            continue
        index[root] = low[root] = len(index)
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(successors[root]))]
        while work:
            code, remaining = work[-1]
            for successor, _, _ in remaining:
                if successor not in candidates:
                    continue
                if successor not in index:
                    index[successor] = low[successor] = len(index)
                    stack.append(successor)
                    on_stack.add(successor)
                    work.append((successor, iter(successors[successor])))
                    break
                if successor in on_stack:
                    low[code] = min(low[code], index[successor])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[code])
                if low[code] == index[code]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == code:
                            break
                    if len(component) > 1 or any(succ == code for succ, _, _ in successors[code]):
                        members.extend(component)
    return sorted(members)


# SCHEDOPTIONS.sched_float_type -> which float "Compute Total Float as" reports, on the
# activity's calendar. P6's dialog writes FT_FF (Finish Float = LF - EF), FT_SS (Start
# Float = LS - ES) and FT_Min (the smaller). FT_Start and FT_Total only come from imported
# files: P6 keeps the code and reports the finish float. Only resource-dependent work
# tells the two floats apart; on task-dependent work the late dates are placed by
# duration on the same calendar, so they are equal (test_float_type_codes_read_as_p6_does).
FLOAT_TYPE = {"FT_FF": "finish", "FT_SS": "start", "FT_Min": "min", "FT_Start": "finish", "FT_Total": "finish"}


# First ERMHDR major version whose files keep the stored remaining when the expected finish is
# earlier than the early start. Evidence: P6 23.12 corpus, 94 of 94 cases collapse to remaining 0;
# P6 26.5 / 26.8 project exports (Project Management Cloud), 112 cases over 14 updates, none
# collapses. Versions 24 and 25 are unverified; an absent or unreadable version keeps the corpus rule.
KEEP_EARLY_EXPECTED_FINISH_FROM = 26


def collapses_early_expected_finish(version: str) -> bool:
    match = re.match(r"\s*(\d+)", version or "")
    return match is None or int(match.group(1)) < KEEP_EARLY_EXPECTED_FINISH_FROM


@dataclass(frozen=True)
class Options:
    """P6 scheduling options (SCHEDOPTIONS / PROJECT) the computation depends on."""

    progressed: str = "retained_logic"  # "When scheduling progressed activities use"
    float_type: str = "FT_FF"  # "Compute Total Float as": see FLOAT_TYPE
    lag_calendar: str = "rcal_Successor"  # Oracle: the successor's when none is selected
    open_critical: bool = False
    lag_from_early_start: bool = True  # SS lag of a started predecessor: "Early Start"
    use_expected_finish: bool = True
    must_finish_by: pd.Timestamp | None = None
    # "Ignore relationships to and from other projects" unchecked (SD_Both): the external
    # early start / late finish P6 stored for lost links to other projects bound the dates
    honor_external: bool = True
    # An expected finish earlier than the early start brings the remaining duration to 0
    # (False: the stored remaining is kept and the expected finish is ignored for that activity)
    collapse_early_expected_finish: bool = True

    def __post_init__(self):
        if self.progressed not in PROGRESSED:
            raise ValueError(f"progressed must be one of {PROGRESSED}")

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot) -> Options:
        export_version = (snapshot.options.get("export", {}) or {}).get("version", "")
        sched_options = snapshot.options.get("sched", {}) or {}

        def flag(key, default):
            value = sched_options.get(key, "")
            return default if value in ("", None) else value == "Y"

        return cls(
            progressed=snapshot.options.get("progressed", "retained_logic"),
            float_type=sched_options.get("sched_float_type") or "FT_FF",
            lag_calendar=snapshot.options.get("lag_calendar", "rcal_Successor"),
            open_critical=flag("sched_open_critical_flag", False),
            lag_from_early_start=flag("sched_lag_early_start_flag", True),
            use_expected_finish=flag("sched_use_expect_end_flag", True),
            must_finish_by=snapshot.options.get("must_finish_by"),
            honor_external=(sched_options.get("sched_outer_depend_type") or "SD_Both") == "SD_Both",
            collapse_early_expected_finish=collapses_early_expected_finish(export_version),
        )


@dataclass
class Schedule:
    frame: pd.DataFrame  # index task_code: es, ef, ls, lf, tf_hr, ff_hr, rem_override_hr, ...
    finish: pd.Timestamp | None
    options: Options
    warnings: list[str] = field(default_factory=list)
    assignments: pd.DataFrame = field(default_factory=pd.DataFrame)  # one row per open assignment
    assignment_minutes: dict[str, float] = field(default_factory=dict)  # taskrsrc_id -> remaining minutes as placed


class _Axes:
    """One TimeAxis per calendar, built once over the schedule's date range."""

    def __init__(self, snapshot: Snapshot, first, last):
        self.snapshot, self.first, self.last = snapshot, first, last
        self._axes: dict[str, TimeAxis] = {}

    def __getitem__(self, calendar: WorkCalendar) -> TimeAxis:
        key = calendar.clndr_id or "__default__"
        if key not in self._axes:
            self._axes[key] = TimeAxis(calendar, self.first, self.last)
        return self._axes[key]

    def of(self, clndr_id: str) -> TimeAxis:
        return self[self.snapshot.calendar(clndr_id)]


def _date_range(snapshot: Snapshot):
    activities = snapshot.activities
    date_columns = [
        "early_start_date",
        "early_end_date",
        "late_start_date",
        "late_end_date",
        "act_start_date",
        "act_end_date",
        "cstr_date",
        "cstr_date2",
        "target_end_date",
    ]
    stamps = pd.concat([activities[column] for column in date_columns if column in activities]).dropna()
    first, last = snapshot.data_date, snapshot.data_date
    if len(stamps):
        known_data_date = [] if snapshot.data_date is None else [snapshot.data_date]
        first = min([stamps.min()] + known_data_date)
        last = max([stamps.max()] + known_data_date)
    # margins: before the earliest stored date (negative lags, constraints) and far past the
    # last one, so the time axis covers everything the passes can reach
    return (first - pd.Timedelta(days=60)).date(), (last + pd.Timedelta(days=400)).date()


def schedule(
    snapshot: Snapshot,
    extra_hours: dict[str, float] | None = None,
    options: Options | None = None,
    base: Schedule | None = None,
) -> Schedule:
    """Recompute early/late dates and float of every activity of ``snap``.

    The plain recalculation (no extra delay, file options) is cached on the snapshot:
    the integrity check, the critical path test and the weekly history share it.

    ``base``: the plain recalculation, given with ``extra_hours``. A delayed activity then drops
    its expected finish, which would absorb the delay, and runs its remaining duration in
    ``base`` (the one the expected finish set, if any) plus the delay.
    """
    if not extra_hours and options is None:
        cached = getattr(snapshot, "_xs_schedule", None)
        if cached is None:
            cached = _schedule(snapshot, None, None)
            object.__setattr__(snapshot, "_xs_schedule", cached)
        return cached
    return _schedule(snapshot, extra_hours, options, base)


@dataclass
class _Asg:
    """One open assignment as the CPM schedules it."""

    taskrsrc_id: str
    rsrc: str
    axis: TimeAxis
    lag_minutes: float  # remaining assignment lag, minutes
    duration_minutes: float  # remaining duration, minutes (None = the activity's)
    driving: bool


def _schedule(
    snapshot: Snapshot, extra_hours: dict[str, float] | None, options: Options | None, base: Schedule | None = None
) -> Schedule:
    return _Run(snapshot, extra_hours or {}, options or Options.from_snapshot(snapshot), base).result()


class _Run:
    """One recalculation: the network, then one method per pass, in the order P6 runs them.

    State is kept in plain dicts keyed by activity code (es, ef, rs, ls, lf, tf, ff): they
    are 10x faster than DataFrame lookups in the passes' inner loops.
    """

    def __init__(
        self, snapshot: Snapshot, extra_hours: dict[str, float], options: Options, base: Schedule | None = None
    ):
        self.snapshot, self.extra_hours, self.options, self.base = snapshot, extra_hours, options, base
        # Nothing is scheduled before the data date, nor before the project's planned start
        # (P6 keeps the later of the two as the earliest start of remaining work).
        self.warnings: list[str] = []
        known = [date for date in (snapshot.data_date, snapshot.planned_start) if date is not None]
        if not known:  # never scheduled: start from the earliest date any activity carries
            all_activities = snapshot.activities
            date_columns = [
                column
                for column in ("act_start_date", "early_start_date", "target_start_date")
                if column in all_activities
            ]
            stamps = (
                pd.concat([all_activities[column] for column in date_columns]).dropna()
                if date_columns
                else pd.Series(dtype="datetime64[ns]")
            )
            if stamps.empty:
                raise ValueError("no status date, no planned start and no task date: nothing to schedule from")
            known = [stamps.min()]
            self.warnings.append(
                f"no status date or planned start: scheduled from the earliest task date {known[0]:%Y-%m-%d %H:%M}"
            )
        self.data_date = max(known)
        self.activities = snapshot.by_code
        self.axes = _Axes(snapshot, *_date_range(snapshot))
        self.project_calendar = snapshot.calendar()
        self._network()
        input_columns = [
            "task_type", "status_code", "clndr_id", "remain_drtn_hr_cnt", "act_start_date", "act_end_date",
            "cstr_type", "cstr_date", "cstr_type2", "cstr_date2", "expect_end_date",
            "external_early_start_date", "external_late_end_date", "resume_date",
        ]  # fmt: skip
        self.inputs = self.activities[[column for column in input_columns if column in self.activities]].to_dict(
            "index"
        )
        self.cal_ax = {code: self.axes.of(self.inputs[code]["clndr_id"]) for code in self.activities.index}
        self.status = self.activities["status_code"].to_dict()
        self._assignments()
        self.early_start: dict[str, pd.Timestamp] = {}
        self.early_finish: dict[str, pd.Timestamp] = {}
        self.remaining_start: dict[str, pd.Timestamp] = {}  # start used by SS/SF successors (remaining start)
        self.late_start: dict[str, pd.Timestamp] = {}
        self.late_finish: dict[str, pd.Timestamp] = {}
        self.total_float_hr: dict[str, float] = {}
        self.free_float_hr: dict[str, float] = {}
        self.assignment_early: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}  # taskrsrc_id -> start, finish
        self.assignment_minutes: dict[str, float] = {}  # taskrsrc_id -> remaining minutes as placed (expected finish)
        self.assignment_late: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
        # Retained Logic: finished activities pass logic through (see pred_bounds)
        self.retain = options.progressed == "retained_logic"
        self.duration_override: dict[str, float] = {}  # remaining minutes set by an expected finish
        self.carry: dict[str, pd.Timestamp] = {}  # finished activity -> early date it passes on
        self.lcarry: dict[str, pd.Timestamp] = {}  # finished activity -> late date it passes back
        self.external: set[str] = set()  # activities bounded by an external date
        self.unapplied: list[str] = []  # in-progress activities whose constraints the forward pass skips

    # --- network ---------------------------------------------------------------------------
    def _network(self) -> None:
        """Relationships between scheduled activities, LOE links apart, topological order."""
        activities = self.activities
        self.is_loe = activities["is_loe"].to_dict()
        self.nodes = [code for code in activities.index if not self.is_loe[code]]
        self.loe_codes = [code for code in activities.index if self.is_loe[code]]
        node_set = set(self.nodes)
        self.preds: dict[str, list] = defaultdict(list)
        self.succs: dict[str, list] = defaultdict(list)
        self.loe_preds: dict[str, list] = defaultdict(list)
        self.loe_succs: dict[str, list] = defaultdict(list)
        links = self.snapshot.relationships[["pred_code", "succ_code", "type", "lag_hr"]]
        self.linked_on = set(links["pred_code"])  # has a successor of any kind (LOE, WBS summary included)
        for predecessor, successor, link_type, lag in links.itertuples(index=False):
            lag_minutes = float(lag or 0) * 60
            if predecessor in node_set and successor in node_set:
                self.preds[successor].append((predecessor, link_type, lag_minutes))
                self.succs[predecessor].append((successor, link_type, lag_minutes))
            elif successor in activities.index and self.is_loe.get(successor, False) and predecessor in node_set:
                self.loe_preds[successor].append((predecessor, link_type, lag_minutes))
            elif predecessor in activities.index and self.is_loe.get(predecessor, False) and successor in node_set:
                self.loe_succs[predecessor].append((successor, link_type, lag_minutes))
        # An LOE takes its dates from the work it spans; a link between two LOEs gives neither a
        # date here. Whether P6 schedules one LOE from another is not documented: counted, not lost.
        loe_to_loe = [
            (p, s)
            for p, s in zip(links["pred_code"], links["succ_code"], strict=True)
            if self.is_loe.get(p, False) and self.is_loe.get(s, False)
        ]
        if loe_to_loe:
            self.warnings.append(
                f"{len(loe_to_loe)} relationship(s) between two level-of-effort activities, ignored: {loe_to_loe[:5]}"
            )
        # The network is a directed graph: activities are nodes, relationships are edges
        # (predecessor -> successor). We need an order in which every activity comes after all
        # its predecessors (a topological sort, Kahn's algorithm): the forward pass can then
        # compute an activity from predecessors already computed, and the backward pass walks
        # the same order reversed, so successors are computed first.
        # in_degree[x] = number of predecessors of x not placed yet; x is ready at 0.
        # Example, A -> B -> D and A -> C -> D:
        #   start  A=0 B=1 C=1 D=2  -> place A
        #          B=0 C=0 D=2      -> place B, then C
        #          D=0              -> place D        order = [A, B, C, D]
        in_degree = dict.fromkeys(self.nodes, 0)
        for successor, links in self.preds.items():
            in_degree[successor] = len(links)
        queue = deque(code for code in self.nodes if in_degree[code] == 0)
        order: list[str] = []
        while queue:
            code = queue.popleft()
            order.append(code)
            for successor, _, _ in self.succs[code]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)
        # nodes left out never reached 0: they wait on each other, a cycle (A -> B -> A).
        # P6 refuses to schedule a loop too.
        if len(order) != len(self.nodes):
            loop = _loop_members(set(self.nodes) - set(order), self.succs)
            raise CycleError(f"logic loop among {loop[:8]}{'…' if len(loop) > 8 else ''}", tuple(loop))
        self.order = order

    def _assignments(self) -> None:
        """Open assignments. Resource-dependent activities are scheduled from their driving
        assignments, each on its resource's calendar; the others use the activity calendar."""
        inputs, status = self.inputs, self.status
        self.assignments_by_task: dict[str, list[_Asg]] = defaultdict(list)
        assignment_table = self.snapshot.assignments
        for row in assignment_table.itertuples(index=False) if not assignment_table.empty else []:
            code = row.task_code
            if code not in inputs or status[code] == "TK_Complete" or self.is_loe[code]:
                continue
            remaining_units = float(row.remain_qty) if pd.notna(row.remain_qty) else 0.0
            rate = float(row.remain_qty_per_hr) if pd.notna(row.remain_qty_per_hr) else 0.0
            on_rsrc_cal = inputs[code].get("task_type") == "TT_Rsrc" and bool(row.rsrc_clndr_id)
            axis = self.axes.of(row.rsrc_clndr_id) if on_rsrc_cal else self.cal_ax[code]
            remaining_minutes = remaining_units / rate * 60 if rate > 0 else None
            lag = float(row.relag_drtn_hr_cnt) * 60 if pd.notna(row.relag_drtn_hr_cnt) else 0.0
            name = str(row.rsrc_short_name or row.rsrc_name or row.rsrc_id or "")
            self.assignments_by_task[code].append(
                _Asg(str(row.taskrsrc_id), name, axis, lag, remaining_minutes, bool(row.driving))
            )
        rsrc_type = {
            code for code in self.nodes if inputs[code].get("task_type") == "TT_Rsrc" and status[code] != "TK_Complete"
        }
        self.rsrc_dep = {code for code in rsrc_type if self.driving(code)}
        lacking = [code for code in self.nodes if code in rsrc_type and code not in self.rsrc_dep]
        if lacking:
            self.warnings.append(
                f"{len(lacking)} resource-dependent tasks without a driving assignment with "
                f"units per hour, scheduled on their task calendar: {lacking[:5]}"
            )

    # --- helpers -----------------------------------------------------------------------------
    def lag_axis(self, predecessor: str, successor: str) -> TimeAxis:
        calendar = self.options.lag_calendar
        if calendar == "rcal_Predecessor":
            return self.cal_ax[predecessor]
        if calendar == "rcal_24Hour":
            return self.axes[H24]
        if calendar == "rcal_ProjDefault":
            return self.axes[self.project_calendar]
        return self.cal_ax[successor]

    @staticmethod
    def shift(axis: TimeAxis, ts: pd.Timestamp, lag_minutes: float) -> pd.Timestamp:
        return ts if lag_minutes == 0 else axis.add(ts, lag_minutes, finish=lag_minutes > 0)

    def kind(self, code) -> str:
        task_type = self.inputs[code].get("task_type")
        if task_type in ("TT_Mile", "TT_StartMile"):
            return "start_ms"
        if task_type == "TT_FinMile":
            return "finish_ms"
        return "task"

    def delayed(self, code) -> bool:
        """True for an activity delayed against ``base``: its expected finish no longer applies."""
        return self.base is not None and code in self.extra_hours

    def base_minutes(self, code, assignment: _Asg) -> float:
        """Remaining minutes of an assignment before the delay (``base``'s when the activity is delayed)."""
        if self.delayed(code):
            return self.base.assignment_minutes.get(assignment.taskrsrc_id, assignment.duration_minutes)
        return assignment.duration_minutes

    def dur_min(self, code) -> float:
        if self.delayed(code):
            held = self.base.frame.at[code, "rem_override_hr"]
            if pd.notna(held):
                return float(held) * 60 + self.extra_hours[code] * 60
        elif code in self.duration_override:  # remaining duration recomputed from an expected finish
            return self.duration_override[code] + self.extra_hours.get(code, 0.0) * 60
        remaining_hr = self.inputs[code].get("remain_drtn_hr_cnt")
        return (0.0 if pd.isna(remaining_hr) else float(remaining_hr) * 60) + self.extra_hours.get(code, 0.0) * 60

    def driving(self, code) -> list[_Asg]:
        return [
            assignment
            for assignment in self.assignments_by_task[code]
            if assignment.driving and assignment.duration_minutes is not None
        ]

    def constraints(self, code) -> list[tuple[str, pd.Timestamp]]:
        """Dated constraints of ``c`` P6 schedules with. A finish constraint on a start
        milestone, or a start constraint on a finish milestone (P6's own dialog refuses
        them; an import keeps them), is ignored (P6 23.12 corpus, H6-03 A1130)."""
        dated = []
        activity_kind = self.kind(code)
        for type_field, date_field in (("cstr_type", "cstr_date"), ("cstr_type2", "cstr_date2")):
            constraint_type, date = self.inputs[code].get(type_field), self.inputs[code].get(date_field)
            if constraint_type and isinstance(constraint_type, str) and constraint_type != "CS_ALAP" and pd.notna(date):
                side = (
                    START_LIKE.get(constraint_type) or LATE_LIKE.get(constraint_type) or MANDATORY.get(constraint_type)
                )
                if (activity_kind == "start_ms" and side == "finish") or (
                    activity_kind == "finish_ms" and side == "start"
                ):
                    continue
                dated.append((constraint_type, pd.Timestamp(date)))
        return dated

    def pred_bounds(self, code: str, started: bool, finish_only: bool = False) -> list[tuple[str, pd.Timestamp]]:
        """Lower bounds the predecessors of ``c`` put on its start or its finish.

        Returns ("start" | "finish", instant) pairs; ``finish_only`` keeps the FF / SF ones.
        A finished predecessor, under Retained Logic, passes on what its own unfinished
        predecessors still impose (``carry``: the data date when nothing does), plus the
        part of a positive lag not yet expired since
        its actual finish (FS, FF) or start (SS, SF); a lead is dropped, and between two
        finished activities only the carried date passes. Without Retained Logic a finished
        predecessor bounds unstarted work by its actual dates + lag, and started work not at
        all. An SS or SF link from a started predecessor is measured from its remaining early
        start (or its actual start, under the option) plus the unexpired lag; SF included
        (P6 23.12 corpus, H1-08 A1240). Out-of-sequence progress otherwise follows MPXJ's
        PrimaveraScheduler (its issue #972, checked there against real P6 schedules).
        """
        out = []
        for predecessor, link_type, lag in self.preds[code]:
            bounded_end = "start" if link_type in ("FS", "SS") else "finish"
            if finish_only and bounded_end == "start":
                continue
            link_axis = self.lag_axis(predecessor, code)
            if self.status[predecessor] == "TK_Complete":
                if self.retain:
                    if self.status[code] == "TK_Complete":
                        out.append((bounded_end, self.carry[predecessor]))
                        continue
                    measured_from = self.inputs[predecessor].get(
                        "act_end_date" if link_type in ("FS", "FF") else "act_start_date"
                    )
                    unexpired_lag = lag
                    if lag <= 0:
                        unexpired_lag = 0.0
                    elif measured_from is not None and pd.notna(measured_from):
                        unexpired_lag = max(0.0, lag - max(0, link_axis.between(measured_from, self.data_date)))
                    if (
                        link_type == "SS"
                        and not self.options.lag_from_early_start
                        and measured_from is not None
                        and pd.notna(measured_from)
                    ):
                        # "Calculate start-to-start lag from Actual Start": from the finished
                        # predecessor's actual start, whatever it still carries (H6-07 A1190)
                        out.append((bounded_end, self.shift(link_axis, measured_from, lag)))
                        continue
                    out.append((bounded_end, self.shift(link_axis, self.carry[predecessor], unexpired_lag)))
                    continue
                if started and not finish_only:
                    continue  # Progress Override: a finished FF / SF predecessor still bounds
            if link_type in ("FS", "FF"):
                out.append((bounded_end, self.shift(link_axis, self.early_finish[predecessor], lag)))
            else:
                if (
                    link_type == "SF"
                    and self.status[predecessor] == "TK_Active"
                    and self.options.progressed == "progress_override"
                ):
                    # Progress Override: the predecessor's start is an actual, an SF from it
                    # binds nothing (H10-02 A1250); an SS still does, through its unexpired lag
                    continue
                predecessor_start, predecessor_lag = self.start_link(predecessor, link_axis, lag)
                out.append((bounded_end, self.shift(link_axis, predecessor_start, predecessor_lag)))
        return out

    def unexpired(self, predecessor: str, link_axis: TimeAxis, lag: float) -> float:
        """Lag of an SS/SF link from ``p`` still to run after the data date (whole lag if not started)."""
        actual_start = self.inputs[predecessor].get("act_start_date")
        if self.status[predecessor] != "TK_Active" or lag <= 0 or actual_start is None or pd.isna(actual_start):
            return lag
        return max(0.0, lag - max(0, link_axis.between(actual_start, self.data_date)))

    def start_link(self, predecessor: str, link_axis: TimeAxis, lag: float) -> tuple[pd.Timestamp, float]:
        """Instant an SS/SF link from ``p`` is measured from, and the lag to add.

        Oracle (Schedule Options, "Calculate start-to-start lag from"): Early Start =
        the predecessor's internal early start plus the lag not yet expired, expired =
        working time from its actual start to the data date; Actual Start = from its
        actual start (successor >= data date + remaining lag). Under Actual Dates the
        option is disabled: actual start.
        """
        actual_start = self.inputs[predecessor].get("act_start_date")
        if self.status[predecessor] == "TK_NotStart" or actual_start is None or pd.isna(actual_start):
            return self.remaining_start[predecessor], lag
        if (
            self.status[predecessor] == "TK_Active"
            and self.options.lag_from_early_start
            and self.options.progressed != "actual_dates"
        ):
            # Progress Override: the remaining work of a started predecessor begins at the
            # data date, and that is where the link is measured from, not from its remaining
            # start on its own calendar (H17-10 A1270: a successor at the data date while
            # the predecessor's remaining start is the next working day)
            measured_from = (
                self.data_date if self.options.progressed == "progress_override" else self.remaining_start[predecessor]
            )
            return measured_from, self.unexpired(predecessor, link_axis, lag)
        return actual_start, lag

    # --- forward pass --------------------------------------------------------------------------
    def forward(self) -> None:
        """Early dates: the soonest each activity can start and finish.

        Walks the topological order, so every predecessor is already dated. For an open
        activity it collects "not before" dates (lower bounds) and keeps the latest one:

        - start bounds: the data date (nothing remaining happens before "today"), a resume
          date, each finish-to-start predecessor's finish + lag (B starts after A finishes),
          each start-to-start predecessor's start + lag, links to other projects, start
          constraints set by the planner
        - finish bounds: each finish-to-finish predecessor's finish + lag, each
          start-to-finish predecessor's start + lag, finish constraints
        - a mandatory constraint overrides all of them

        (P6 and the code write these four relationship types FS, SS, FF and SF.)

        Then finish = start + remaining duration, counted in working minutes of the
        activity's calendar (``_early``); a later finish bound pushes both. Resource-dependent
        activities (dated by their resources' calendars) and an expected finish adjust the
        result. A finished activity keeps its actual dates (``forward_finished``).

        Example: A ends Monday 17:00; B follows A finish-to-start with no lag, lasts 2 days,
        on a Monday-to-Friday 08:00-17:00 calendar: B starts Tuesday 08:00 and finishes
        Wednesday 17:00.
        """
        inputs, options, status, data_date = self.inputs, self.options, self.status, self.data_date
        early_start, early_finish, remaining_start = self.early_start, self.early_finish, self.remaining_start
        for code in self.order:
            if status[code] == "TK_Complete":
                self.forward_finished(code)
                continue
            axis = self.cal_ax[code]
            started = status[code] == "TK_Active"
            activity_kind, duration = self.kind(code), self.dur_min(code)
            start_bounds, finish_bounds = [data_date], []
            resume = inputs[code].get("resume_date") if started else None
            if resume is not None and pd.notna(resume):
                # suspended work resumes on its resume date (H8-07 A1020)
                start_bounds.append(max(data_date, pd.Timestamp(resume)))
            # Progress Override: the start of work under way is an actual, so FS / SS
            # predecessors no longer bound it; FF / SF predecessors still bound its finish
            # (H1-11 A1040). Mirrored in successor_limits.
            use_logic = not (started and options.progressed == "progress_override")
            for bounded_end, bound in self.pred_bounds(code, started, finish_only=not use_logic):
                (start_bounds if bounded_end == "start" else finish_bounds).append(bound)
            external_date = inputs[code].get("external_early_start_date")
            if options.honor_external and external_date is not None and pd.notna(external_date):
                # a lost link to a project not in the database: not a link of this project, so Progress
                # Override does not release work under way from it (H8-08 A1020, H10-12 A1130, H15-09 A1110)
                start_bounds.append(pd.Timestamp(external_date))
                self.external.add(code)
            pinned = self.forward_constraints(code, started, start_bounds, finish_bounds)
            # Mandatory Start / Finish: the date, whatever the logic, in both passes; except
            # that unstarted work never starts before the data date (H3-04 A1100, H2-06
            # A1130: the early dates move to the data date, the late dates stay)
            if pinned and pinned[0] == "start":
                start_bounds, finish_bounds = [max(pinned[1], data_date)], []
            if code in self.rsrc_dep and activity_kind == "task":
                use_expected = options.use_expected_finish and not self.delayed(code)
                expected_date = inputs[code].get("expect_end_date", pd.NaT) if use_expected else pd.NaT
                alap = "CS_ALAP" in (inputs[code].get("cstr_type"), inputs[code].get("cstr_type2"))
                expected_date = (
                    pd.Timestamp(expected_date)
                    if pd.notna(expected_date) and not alap and expected_date >= data_date
                    else None
                )
                start, finish_time = self.rsrc_early(
                    code, start_bounds, finish_bounds, self.extra_hours.get(code, 0.0) * 60, expected_date
                )
            else:
                start, finish_time = _early(axis, activity_kind, duration, start_bounds, finish_bounds)
            if pinned and pinned[0] == "finish" and code not in self.duration_override:
                finish_time = axis.keep_or_previous(pinned[1])
                start = (
                    axis.add(finish_time, -duration, finish=False)
                    if (activity_kind == "task" and duration)
                    else finish_time
                )
                if start < data_date:
                    start = axis.snap_start(data_date)
                    finish_time = (
                        axis.add(start, duration, finish=True) if (activity_kind == "task" and duration) else start
                    )
            if activity_kind == "task" and options.use_expected_finish and not self.delayed(code):
                expected_date = inputs[code].get("expect_end_date", pd.NaT)
                alap = "CS_ALAP" in (inputs[code].get("cstr_type"), inputs[code].get("cstr_type2"))
                finish_linked = any(link_type in ("FF", "SF") for _, link_type, _ in self.preds[code])
                if pd.notna(expected_date) and not alap and code not in self.rsrc_dep:
                    start, finish_time = self.expected_finish(
                        code,
                        axis,
                        pd.Timestamp(expected_date),
                        start_bounds,
                        finish_bounds,
                        start,
                        finish_time,
                        use_logic,
                        finish_linked,
                        options.collapse_early_expected_finish,
                    )
            early_start[code], early_finish[code], remaining_start[code] = (
                (inputs[code].get("act_start_date") if started and activity_kind == "task" else start),
                finish_time,
                start,
            )
        self.open_ = [code for code in self.order if status[code] != "TK_Complete"]
        # Under Retained Logic a finished activity ends, for its successors, at its carried
        # date: an actual finish after the data date (invalid progress) no longer sets the end.
        self.finish = max(
            (
                self.carry.get(code, early_finish[code]) if status[code] == "TK_Complete" else early_finish[code]
                for code in self.nodes
            ),
            default=None,
        )

    def forward_finished(self, code) -> None:
        """A finished activity keeps its actuals; under Retained Logic it also passes on a date."""
        early_start, early_finish = self.early_start, self.early_finish
        early_start[code], early_finish[code] = (
            self.inputs[code].get("act_start_date"),
            self.inputs[code].get("act_end_date"),
        )
        self.remaining_start[code] = early_start[code]
        if pd.isna(early_start[code]) or pd.isna(early_finish[code]):
            self.warnings.append(f"{code}: complete without actual dates")
            if pd.notna(early_start[code]):
                early_finish[code] = early_start[code]
            elif pd.notna(early_finish[code]):
                early_start[code] = early_finish[code]
            else:
                early_start[code] = early_finish[code] = self.data_date
        if self.retain:
            self.carry[code] = max([self.data_date] + [bound for _, bound in self.pred_bounds(code, started=False)])

    def forward_constraints(self, code, started: bool, start_bounds: list, finish_bounds: list):
        """Add the activity's dated constraints to the start / finish bounds (in place).

        Returns the Mandatory Start / Finish as (side, date), else None. Work under way keeps
        its actual start, so its constraints are not applied here, only reported.
        """
        pinned = None
        if started and self.constraints(code):
            self.unapplied.append(code)
        for constraint_type, date in [] if started else self.constraints(code):
            if constraint_type in MANDATORY:
                pinned = (MANDATORY[constraint_type], date)
            elif START_LIKE.get(constraint_type) == "start":
                start_bounds.append(date)
            elif START_LIKE.get(constraint_type) == "finish":
                finish_bounds.append(date)
        return pinned

    def expected_finish(
        self,
        code,
        axis,
        expected_date,
        start_bounds,
        finish_bounds,
        start,
        finish_time,
        use_logic,
        finish_linked,
        collapse_early=True,
    ):
        """Early dates of task-dependent work with an expected finish, as P6 23.12 places them
        (corpus witnesses: H1-02 A1170, H4-10 A1040, H24-07 A1210).

        The expected finish stands in for "early start + remaining duration": the early
        finish is the expected finish, or the early start when the expected finish falls
        before it (remaining duration 0), on whatever date the data date, the predecessors
        or a constraint give the start. An FF / SF bound later than that finish wins
        instead, with the file's remaining duration and the start placed back from it, as
        without an expected finish. The remaining duration the backward pass uses follows
        the early dates (``dur_override``).

        Observed, not explained: work under way under Progress Override with an FF / SF
        predecessor keeps its remaining duration when the expected finish falls before its
        early start, even when that predecessor's bound no longer binds.
        """
        early_start_time = axis.snap_start(max(start_bounds)) if start_bounds else start
        if not use_logic and finish_linked and expected_date < early_start_time:
            return start, finish_time
        if not collapse_early and expected_date < early_start_time:  # P6 26.x: expected finish ignored
            return start, finish_time
        # an expected finish off the calendar or on a period start ends the previous working
        # period (P6 26.x exports: 31 Dec in a break -> 24 Dec 17:00, 08:00 -> 17:00 the day before)
        exp_fin = max(axis.snap_finish(expected_date), early_start_time)
        finish_bound = axis.keep_or_next(max(finish_bounds)) if finish_bounds else None
        # compared in working time: 17:00 and the next 08:00 are the same instant of work
        if finish_bound is not None and axis.work(exp_fin) < axis.work(finish_bound):
            return start, finish_time
        self.duration_override[code] = float(axis.between(early_start_time, exp_fin))
        return early_start_time, exp_fin

    def rsrc_early(
        self, code, start_bounds, finish_bounds, extra_minutes, expected_date=None
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Dates of a resource-dependent activity: its duration comes from its resources.

        In plain terms: each driving resource assignment has remaining hours of work and a
        rate (hours per hour); its duration is work / rate, counted on the resource's own
        calendar, not the activity's. The activity spans its assignments.

        Example: 40 h of work at 0.5 h per hour (a half-time person) lasts 80 working hours
        of that person's calendar; if the person works Monday to Thursday, the activity
        stretches over the Fridays they are off.

        Detail, as P6 23.12 places it (corpus H8-H30):

        1. the lower bound is taken on the activity's own calendar (H8-03 A1240: data date
           00:00, activity Mon-Thu from 07:00, resource every day from 06:00: starts 07:00);
        2. each driving assignment is placed from there on its resource calendar, with its
           lag, and pushed back behind a finish bound if one is later;
        3. the activity starts at the earliest assignment start, on its own calendar, and
           each assignment then runs forward from that start: a finish bound is met, not
           tight (H10-02 A1360: an FF bound at Fri 18:00 on a Mon-Sat 08-16 resource,
           placed Fri 08:00-16:00).

        ``expected_date``: the expected finish when the option applies (see below).
        """
        axis = self.cal_ax[code]
        lower_start = axis.snap_start(max(start_bounds))
        finish_bound = max(finish_bounds) if finish_bounds else None
        starts, durations, expected_applies = [], {}, False
        for assignment in self.driving(code):
            duration = self.base_minutes(code, assignment) + extra_minutes
            assignment_start = assignment.axis.snap_start(
                self.shift(assignment.axis, lower_start, assignment.lag_minutes)
            )
            if (
                expected_date is not None
                and expected_date > assignment_start
                and (finish_bound is None or expected_date >= finish_bound)
            ):
                # the expected finish sets the remaining work, measured on the resource
                # calendar from this placement (H26-11 A1090: 35.5 h from Tue 06:00, then
                # run from the activity's Tue 07:00 to Fri 06:30); an expected finish before
                # the placement keeps the file's remaining duration (H14-05 A1040), and an
                # FF / SF bound later than it wins, as for task-dependent work
                duration = float(assignment.axis.between(assignment_start, expected_date))
                expected_applies = True
            durations[assignment.taskrsrc_id] = self.assignment_minutes[assignment.taskrsrc_id] = duration
            assignment_finish = (
                assignment.axis.add(assignment_start, duration, finish=True) if duration else assignment_start
            )
            if finish_bound is not None and assignment_finish < finish_bound:
                assignment_finish = assignment.axis.keep_or_next(finish_bound)
                assignment_start = (
                    assignment.axis.add(assignment_finish, -duration, finish=False) if duration else assignment_finish
                )
            starts.append(self.shift(assignment.axis, assignment_start, -assignment.lag_minutes))
        start = axis.snap_start(min(starts))
        finishes = []
        for assignment in self.driving(code):
            duration = durations[assignment.taskrsrc_id]
            assignment_start = assignment.axis.snap_start(self.shift(assignment.axis, start, assignment.lag_minutes))
            assignment_finish = (
                assignment.axis.add(assignment_start, duration, finish=True) if duration else assignment_start
            )
            self.assignment_early[assignment.taskrsrc_id] = (assignment_start, assignment_finish)
            finishes.append(assignment_finish)
        if expected_applies:
            self.duration_override[code] = float(axis.between(start, max(finishes)))  # the backward pass follows
        return start, max(finishes)

    # --- backward pass -------------------------------------------------------------------------
    def successor_limits(self, code, late: bool) -> tuple[list, list]:
        """Latest start / finish ``c`` may have against its successors' late (or early) dates."""
        inputs, status = self.inputs, self.status
        late_start_bounds, late_finish_bounds = [], []
        progress_override = self.options.progressed == "progress_override"
        for successor, link_type, link_lag in self.succs[code]:
            lag = link_lag
            if progress_override and status[successor] == "TK_Active" and link_type in ("FS", "SS"):
                # Progress Override: a started successor's start is an actual, so a link to it
                # binds no late date; links to its finish (FF, SF) still do (H5-06 A1030
                # against H3-03 A1030)
                continue
            if (
                not late
                and progress_override
                and status[code] == "TK_Active"
                and (link_type in ("SS", "SF") or status[successor] == "TK_Complete")
            ):
                # Progress Override again: the free float of work under way runs past its own
                # start-type links (its start is an actual too) and past finished successors,
                # to whatever is left (H2-05 A1030, H2-04 A1110; counter-examples H4-08
                # A1010, H12-07 A1120 are open, see docs/backlog.md)
                continue
            if (
                late
                and self.options.progressed == "actual_dates"
                and status[successor] != "TK_NotStart"
                and pd.notna(inputs[successor].get("act_start_date"))
            ):
                # Actual Dates: the backward pass uses the successor's actual dates
                successor_start = inputs[successor].get("act_start_date")
                successor_finish = (
                    inputs[successor].get("act_end_date")
                    if status[successor] == "TK_Complete"
                    else self.late_finish[successor]
                )
            elif status[successor] == "TK_Complete" and not late and self.retain:
                # free float against a finished successor: it sits at its carried date
                successor_start = successor_finish = self.carry[successor]
            elif status[successor] == "TK_Complete":
                if late and self.retain:
                    # Retained Logic: a finished successor passes back the late date its own
                    # successors give it, less this link's lag: in full for FS / FF (it runs
                    # from a finish still to come: H1-08 A1020), the part not yet expired
                    # since the actual start for SS / SF (H6-07 A1030), a lead from started
                    # work not at all; between two finished activities only the carried date
                    # passes (H1-08 A1050). MPXJ drops the FS lag; P6 does not.
                    carried_late = self.lcarry[successor]
                    if status[code] == "TK_Complete":
                        bound = carried_late
                    else:
                        link_axis = self.lag_axis(code, successor)
                        lag_used = self.unexpired(code, link_axis, lag) if link_type in ("SS", "SF") else lag
                        if link_type in ("SS", "SF") and lag < 0 and status[code] == "TK_Active":
                            lag_used = 0.0
                        bound = self.shift(link_axis, carried_late, -lag_used)
                    (late_finish_bounds if link_type in ("FS", "FF") else late_start_bounds).append(bound)
                continue
            else:
                successor_start, successor_finish = (
                    (self.late_start[successor], self.late_finish[successor])
                    if late
                    else (self.remaining_start[successor], self.early_finish[successor])
                )
            link_axis = self.lag_axis(code, successor)
            # SS / SF from a started activity: the forward pass only waits for the lag not
            # yet expired, so the backward pass mirrors that, or a driving link would leave
            # negative float on an unconstrained network.
            successor_lag = self.unexpired(code, link_axis, lag) if link_type in ("SS", "SF") else lag
            if link_type in ("SS", "SF") and lag < 0 and status[code] == "TK_Active":
                successor_lag = 0.0  # a lead from work already started no longer pulls it earlier (MPXJ)
            if status[code] == "TK_Complete":
                # finished (Retained Logic, see lcarry): only the lag not yet expired since its
                # actual finish (FS, FF) or start (SS, SF) still counts; a lead is dropped (MPXJ)
                measured_from = inputs[code].get("act_end_date" if link_type in ("FS", "FF") else "act_start_date")
                done_lag = (
                    max(0, link_axis.between(measured_from, self.data_date))
                    if measured_from is not None and pd.notna(measured_from)
                    else 0
                )
                lag = successor_lag = max(0.0, lag - done_lag) if lag > 0 else 0.0
            if link_type == "FS":
                late_finish_bounds.append(self.shift(link_axis, successor_start, -lag))
            elif link_type == "SS":
                late_start_bounds.append(self.shift(link_axis, successor_start, -successor_lag))
            elif link_type == "FF":
                late_finish_bounds.append(self.shift(link_axis, successor_finish, -lag))
            elif link_type == "SF":
                late_start_bounds.append(self.shift(link_axis, successor_finish, -successor_lag))
        return late_start_bounds, late_finish_bounds

    def place_late(
        self, code, axis, activity_kind, duration, late_start_bounds, late_finish_bounds, alap: bool = False
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Latest start and finish within the bounds; ``alap`` when placing early dates."""
        if code not in self.rsrc_dep or activity_kind != "task":
            return _late(axis, activity_kind, duration, late_start_bounds, late_finish_bounds)
        # Mirror of rsrc_early: the bounds are taken on the activity calendar first (H10-04
        # A1220: a successor's late start Tue 08:00 is Mon 16:00 on a Mon-Sat 08-16 activity,
        # the 24 h resource then runs back from there), then each driving assignment is
        # placed on its resource calendar (H9-08 A1230: the resource's holiday moves it)
        upper_finish = axis.snap_finish(min(late_finish_bounds)) if late_finish_bounds else None
        upper_start = axis.snap_start(min(late_start_bounds)) if late_start_bounds else None
        starts, finishes, driven = [], [], False
        for assignment in self.driving(code):
            assignment_duration = self.assignment_minutes.get(
                assignment.taskrsrc_id, self.base_minutes(code, assignment) + self.extra_hours.get(code, 0.0) * 60
            )
            assignment_finish = assignment.axis.snap_finish(upper_finish) if upper_finish is not None else None
            assignment_start = (
                (
                    assignment.axis.add(assignment_finish, -assignment_duration, finish=False)
                    if assignment_duration
                    else assignment_finish
                )
                if assignment_finish is not None
                else None
            )
            if upper_start is not None:
                candidate = assignment.axis.snap_start(self.shift(assignment.axis, upper_start, assignment.lag_minutes))
                if assignment_start is None or candidate < assignment_start:
                    assignment_start, assignment_finish = (
                        candidate,
                        assignment.axis.add(candidate, assignment_duration, finish=True)
                        if assignment_duration
                        else candidate,
                    )
                    driven = driven or assignment.lag_minutes == 0
            self.assignment_late[assignment.taskrsrc_id] = (assignment_start, assignment_finish)
            starts.append(self.shift(assignment.axis, assignment_start, -assignment.lag_minutes))
            finishes.append(assignment_finish)
        start = min(starts)
        if driven and start == upper_start and not alap:
            # written at the bound's instant, as a late date from an SS bound is on
            # task-dependent work (H26-04 A1440: late start Wed 16:00, not Thu 08:00)
            start = axis.keep_or_previous(min(late_start_bounds))
        return start, max(finishes)

    def backward(self) -> None:
        """Late dates: the latest each activity can start and finish without delaying the
        project end.

        Walks the topological order backwards, so every successor is already dated. For an
        open activity it collects "not after" dates (upper bounds) and keeps the earliest:
        the project end (the "must finish by" date the planner may set, else the latest
        early finish), each successor's late date less the lag, read through the same
        relationship types in the other direction (``successor_limits``), links to other
        projects and constraints. Late start = late finish -
        remaining duration on the activity's calendar (``place_late``).

        Total float (computed later, ``floats``) is late finish - early finish: how much the
        activity can slip before the project end moves. 0 = critical: any delay moves the end.

        Example: B (2 days) must finish by Friday 17:00 for its successor: late finish
        Friday 17:00, late start Thursday 08:00; with B's early finish on Wednesday 17:00 its
        float is 2 days.
        """
        options, status = self.options, self.status
        end_anchor = options.must_finish_by if options.must_finish_by is not None else self.finish
        for code in reversed(self.order):
            if status[code] == "TK_Complete":
                if self.retain:
                    late_start_bounds, late_finish_bounds = self.successor_limits(code, late=True)
                    self.lcarry[code] = min(late_start_bounds + late_finish_bounds + [end_anchor])
                continue
            axis = self.cal_ax[code]
            activity_kind, duration = self.kind(code), self.dur_min(code)
            late_start_bounds, late_finish_bounds = self.successor_limits(code, late=True)
            if not late_start_bounds and not late_finish_bounds:
                # "Make open-ended activities critical": the late finish of an activity
                # without any successor link is its early finish, never past the project's
                # Must Finish By (H25-05 A1380); one whose successors bind nothing (finished,
                # a WBS summary) is not open-ended and ends at the project's end (H27-04 A1390)
                open_end = code not in self.linked_on
                late_finish_bounds.append(
                    min(self.early_finish[code], end_anchor) if options.open_critical and open_end else end_anchor
                )
            else:
                # No late finish after the project's: an activity whose successors only bound
                # its start (SS, SF) would otherwise float past the end, and so would its
                # predecessors. MPXJ's PrimaveraScheduler caps it the same way; no P6 file at
                # hand covers the case (tests/test_crosscheck_mpxj.py).
                late_finish_bounds.append(end_anchor)
            external_date = self.inputs[code].get("external_late_end_date")
            if options.honor_external and external_date is not None and pd.notna(external_date):
                late_finish_bounds.append(pd.Timestamp(external_date))
                self.external.add(code)
            pinned = None
            constraint_start_bounds, constraint_finish_bounds = [], []  # bounds the constraints themselves give
            for constraint_type, date in self.constraints(code):
                if constraint_type in MANDATORY:
                    pinned = (MANDATORY[constraint_type], date)
                elif LATE_LIKE.get(constraint_type) == "start" and status[code] != "TK_Active":
                    constraint_start_bounds.append(date)
                elif LATE_LIKE.get(constraint_type) == "finish":
                    constraint_finish_bounds.append(date)
            successor_start_bounds, successor_finish_bounds = (
                list(late_start_bounds),
                list(late_finish_bounds),
            )  # the successors' bounds alone
            late_start_bounds, late_finish_bounds = (
                late_start_bounds + constraint_start_bounds,
                late_finish_bounds + constraint_finish_bounds,
            )
            if pinned:
                # a second constraint of the same end tighter than the mandatory date still
                # holds (H23-08 A1220: Finish On or Before four days before the Mandatory
                # Finish is the late finish)
                if pinned[0] == "start":
                    late_start_bounds, late_finish_bounds = [min([pinned[1]] + constraint_start_bounds)], []
                else:
                    late_start_bounds, late_finish_bounds = [], [min([pinned[1]] + constraint_finish_bounds)]
                if pinned[0] == "finish" and code in self.duration_override:
                    # With an expected finish earlier than the Mandatory Finish the date no
                    # longer pins: the successors' bounds drive the late dates, capped by the
                    # expected finish on task-dependent work (H22-06 A1120, H23-03 A1210,
                    # H23-07 A1110) and by the mandatory date itself on resource-dependent
                    # work (H25-05 A1150; observed, not explained)
                    cap = pinned[1] if code in self.rsrc_dep else min(pinned[1], self.early_finish[code])
                    late_start_bounds, late_finish_bounds = successor_start_bounds, successor_finish_bounds + [cap]
            self.late_start[code], self.late_finish[code] = self.place_late(
                code, axis, activity_kind, duration, late_start_bounds, late_finish_bounds
            )

    # --- float, as late as possible ------------------------------------------------------------
    def floats(self) -> None:
        """Float of each open activity: how much it can slip.

        - total float: late finish - early finish (or the start, per the project's option),
          in working hours of the activity's calendar: slip before the project end moves
        - free float: slip before the first successor moves (the gap to the earliest date a
          successor imposes)

        Example: B finishes Wednesday 17:00, its only successor C (finish-to-start, no lag)
        starts Friday 08:00 at the earliest because of another predecessor: B's free float is
        Thursday, 8 h; its total float may be larger if C itself has float.

        An "as late as possible" activity is moved right by its free float here. The walk is
        in reverse order, so such an activity sees its successors already moved, and free
        float is measured against the dates P6 finally shows."""
        inputs, early_start, early_finish, remaining_start = (
            self.inputs,
            self.early_start,
            self.early_finish,
            self.remaining_start,
        )
        for code in reversed(self.open_):
            axis = self.cal_ax[code]
            activity_kind, duration = self.kind(code), self.dur_min(code)
            # As Late As Possible moves the remaining work of started activities too
            # (H27-05 A1170: in progress, remaining 3 h, placed at its late dates)
            alap = "CS_ALAP" in (inputs[code].get("cstr_type"), inputs[code].get("cstr_type2"))
            start_limits, finish_limits = self.successor_limits(code, late=False)
            if alap:
                if not start_limits and not finish_limits:
                    finish_limits = [self.finish]
                keep = dict(self.assignment_late)
                placed_start, placed_finish = self.place_late(
                    code, axis, activity_kind, duration, start_limits, finish_limits, alap=True
                )
                if placed_finish > early_finish[code]:
                    early_finish[code], remaining_start[code] = placed_finish, placed_start
                    if self.status[code] == "TK_NotStart":
                        early_start[code] = placed_start
                    for assignment in self.driving(code) if code in self.rsrc_dep else []:
                        self.assignment_early[assignment.taskrsrc_id] = self.assignment_late[assignment.taskrsrc_id]
                self.assignment_late.clear()
                self.assignment_late.update(keep)
            gaps = [axis.between(early_finish[code], limit) / 60 for limit in finish_limits] + [
                axis.between(remaining_start[code], limit) / 60 for limit in start_limits
            ]
            # open end: free float runs to the project's early finish, not to "must finish by"
            self.free_float_hr[code] = (
                max(0.0, min(gaps)) if gaps else max(0.0, axis.between(early_finish[code], self.finish) / 60)
            )
            if code in self.duration_override:
                # an activity whose expected finish applies has no free float in P6, whatever
                # its successors' early dates (corpus: 265 of 265 such values; H1-08 A1090,
                # H5-01 A1120). Observed, not explained.
                self.free_float_hr[code] = 0.0
            self.total_float_hr[code] = self.total_float(code, axis)

    def total_float(self, code, axis) -> float:
        """Total float in hours of the activity's calendar, read the way the project's float option says."""
        finish_float = axis.between(self.early_finish[code], self.late_finish[code]) / 60
        start_float = axis.between(self.remaining_start[code], self.late_start[code]) / 60
        which = FLOAT_TYPE.get(self.options.float_type, "finish")  # unknown code: P6's default
        if which == "finish":
            return finish_float
        if which == "start":
            return start_float
        return min(finish_float, start_float)

    # --- level of effort: spans what drives it ------------------------------------------------
    def level_of_effort(self) -> None:
        """Dates of level-of-effort activities (LOE): bars that span other work and drive
        nothing, for example site management for the length of a phase. An LOE has no
        duration of its own: it starts with the earliest work it is tied to and finishes
        with the latest.

        Example: "Supervision" tied to the start of A (Monday) and to the finish of D
        (Friday the week after) runs Monday to that Friday, and stretches if D slips.

        Detail: each relationship ties the end of the LOE it names: start-type ends (SS, FS
        predecessors; SS, SF successors) give its start, finish-type ends (FF, SF
        predecessors; FF, FS successors) its finish. An FF predecessor and an FF successor to
        the same activity give the same finish (Boyle, "constructing LOE activities in P6").
        It runs from the earliest start to the latest finish. Its late dates come the same
        way from the late dates of the activities it is tied to; a finished task contributes
        through an FS link by its actual finish plus the lag, and through an SS link by the
        late date it passes back (``lcarry``) plus the lag; with no start-type link
        left, or one later than the late finish, the late start is the late finish. Float as
        for any activity, free float 0 (H8-01 A1160, H10-11 A1210).
        """
        inputs, data_date, early_start, early_finish, remaining_start = (
            self.inputs,
            self.data_date,
            self.early_start,
            self.early_finish,
            self.remaining_start,
        )
        for code in self.loe_codes:
            if self.status[code] == "TK_Complete":
                early_start[code], early_finish[code] = (
                    inputs[code].get("act_start_date"),
                    inputs[code].get("act_end_date"),
                )
                continue
            axis = self.cal_ax[code]
            starts, end_points = [], []
            for predecessor, link_type, lag in self.loe_preds[code]:
                link_axis = self.lag_axis(predecessor, code)
                if link_type in ("SS", "SF") and self.status[predecessor] == "TK_Active":
                    # from the data date plus the unexpired lag (H10-01 A1300, H12-08 A1290)
                    measured_from, run = data_date, self.unexpired(predecessor, link_axis, lag)
                else:
                    measured_from, run = (
                        (remaining_start[predecessor] if link_type in ("SS", "SF") else early_finish[predecessor]),
                        lag,
                    )
                (starts if link_type in ("SS", "FS") else end_points).append(self.shift(link_axis, measured_from, run))
            for successor, link_type, lag in self.loe_succs[code]:
                to = remaining_start[successor] if link_type in ("SS", "FS") else early_finish[successor]
                (starts if link_type in ("SS", "SF") else end_points).append(
                    self.shift(self.lag_axis(code, successor), to, -lag)
                )
            active = self.status[code] == "TK_Active"
            loe_start = (
                inputs[code].get("act_start_date")
                if active
                else axis.snap_start(max([data_date, min(starts)] if starts else [data_date]))
            )
            loe_finish = (
                axis.snap_finish(max(end_points))
                if end_points
                else (axis.snap_finish(self.finish) if self.finish is not None else loe_start)
            )
            early_start[code], early_finish[code] = (
                loe_start,
                max(loe_finish, axis.snap_start(max(loe_start, data_date))),
            )
            remaining_start[code] = axis.snap_start(data_date) if active else loe_start
            lstarts, lends = [], []
            for predecessor, link_type, lag in self.loe_preds[code]:
                if self.status[predecessor] == "TK_Complete":
                    if link_type == "SS" and predecessor in self.lcarry:  # the late date it passes back
                        lstarts.append(self.shift(self.lag_axis(predecessor, code), self.lcarry[predecessor], lag))
                    if link_type == "FS" and self.kind(predecessor) == "task":  # finished task: its actual finish holds
                        actual_finish = inputs[predecessor].get("act_end_date")
                        if actual_finish is not None and not pd.isna(actual_finish):
                            lstarts.append(self.shift(self.lag_axis(predecessor, code), actual_finish, lag))
                else:
                    measured_from = (
                        self.late_start[predecessor] if link_type in ("SS", "SF") else self.late_finish[predecessor]
                    )
                    (lstarts if link_type in ("SS", "FS") else lends).append(
                        self.shift(self.lag_axis(predecessor, code), measured_from, lag)
                    )
            for successor, link_type, lag in self.loe_succs[code]:
                if self.status[successor] != "TK_Complete":
                    to = self.late_start[successor] if link_type in ("SS", "FS") else self.late_finish[successor]
                    (lstarts if link_type in ("SS", "SF") else lends).append(
                        self.shift(self.lag_axis(code, successor), to, -lag)
                    )
            open_end = axis.snap_finish(self.finish) if self.finish is not None else early_finish[code]
            late_finish = axis.snap_finish(max(lends)) if lends else open_end
            late_start = (
                min(axis.snap_start(min(lstarts)), late_finish) if lstarts else late_finish
            )  # never after the late finish (H10-01 A1300)
            self.late_start[code], self.late_finish[code] = late_start, late_finish
            self.total_float_hr[code] = self.total_float(code, axis)
            self.free_float_hr[code] = 0.0

    # --- longest path ------------------------------------------------------------------------
    def _ends_project(self, code) -> bool:
        """``code`` finishes at the project finish. Equal to the minute; or, when only milestones
        set the project finish, no working minute of ``code``'s calendar between its finish and
        the project finish (Fri 17:00 before a finish milestone written Mon 08:00).
        To test in P6 (plan, P6 measurement 6.5): Oracle states "equal" without saying whether
        working time counts; this reading is the maintainer's until then. When the milestone is
        on another calendar, the gap is still read as 0 on ``code``'s calendar, with a warning."""
        finish = self.early_finish[code]
        if finish == self.finish:
            return True
        if pd.isna(finish) or pd.isna(self.finish):
            return False
        enders = [c for c in self.nodes if self.early_finish[c] == self.finish]
        if not enders or any(self.kind(c) == "task" for c in enders):
            return False
        if self.cal_ax[code].between(finish, self.finish) != 0:
            return False
        own = self.inputs[code]["clndr_id"]
        for ender in enders:
            other = self.inputs[ender]["clndr_id"]
            if other != own:
                gap = self.cal_ax[ender].between(finish, self.finish)
                warning = (
                    f"{code}: on the longest path, finishing {finish} before the finish milestone {ender} at "
                    f"{self.finish}; 0 working minutes on its calendar {own}, {gap} on {ender}'s calendar {other} "
                    "(read as 0, to test in P6)"
                )
                if warning not in self.warnings:
                    self.warnings.append(warning)
        return True

    def longest_path(self) -> set[str]:
        """From the activities that finish last, back through driving links (Oracle:
        "activities that have an early finish equal to the latest calculated early finish
        for the project", then "all driving relationships for those activities")."""
        longest: set[str] = set()
        pending = [code for code in self.open_ if self._ends_project(code)]
        while pending:
            code = pending.pop()
            if code in longest:
                continue
            longest.add(code)
            axis = self.cal_ax[code]
            for predecessor, link_type, lag in self.preds[code]:
                if self.status[predecessor] == "TK_Complete" or (
                    self.status[code] == "TK_Active" and self.options.progressed == "progress_override"
                ):
                    continue
                link_axis = self.lag_axis(predecessor, code)
                if link_type in ("FS", "FF"):
                    bound = self.shift(link_axis, self.early_finish[predecessor], lag)
                else:
                    predecessor_start, predecessor_lag = self.start_link(predecessor, link_axis, lag)
                    bound = self.shift(link_axis, predecessor_start, predecessor_lag)
                own_instant = self.remaining_start[code] if link_type in ("FS", "SS") else self.early_finish[code]
                if axis.work(bound) >= axis.work(own_instant):
                    pending.append(predecessor)
        # A level-of-effort activity is on the path when one of its links into a longest-path
        # activity drives that activity's date (P6 20.12 export: LOE spanning two activities
        # of the path, SS from the first, FF into the second, flagged). Its own dates come from
        # its links, so the trace stops there.
        for loe in self.loe_codes:
            if self.status[loe] == "TK_Complete" or loe not in self.early_finish:
                continue
            for successor, link_type, lag in self.loe_succs[loe]:
                if successor not in longest:
                    continue
                link_axis = self.lag_axis(loe, successor)
                measured_from = self.early_finish[loe] if link_type in ("FS", "FF") else self.remaining_start[loe]
                bound = self.shift(link_axis, measured_from, lag)
                own_instant = (
                    self.remaining_start[successor] if link_type in ("FS", "SS") else self.early_finish[successor]
                )
                if self.cal_ax[successor].work(bound) >= self.cal_ax[successor].work(own_instant):
                    longest.add(loe)
                    break
        return longest

    # --- assignment dates --------------------------------------------------------------------
    def assignment_dates(self) -> pd.DataFrame:
        """Task dependent: the activity's remaining dates + assignment lag, for the assignment's
        own duration (units / units per hour) on the activity calendar. Checked against every
        assignment P6 stored in Hotel and Terminal (tests/test_cpm.py)."""
        rows = []
        for code, items in self.assignments_by_task.items():
            if code not in self.remaining_start or code not in self.late_start:
                continue
            for assignment in items:
                if assignment.taskrsrc_id in self.assignment_early:
                    (assignment_start, assignment_finish), (late_assignment_start, late_assignment_finish) = (
                        self.assignment_early[assignment.taskrsrc_id],
                        self.assignment_late.get(assignment.taskrsrc_id, (None, None)),
                    )
                else:
                    duration = (
                        assignment.duration_minutes if assignment.duration_minutes is not None else self.dur_min(code)
                    )
                    assignment_start = assignment.axis.snap_start(
                        self.shift(assignment.axis, self.remaining_start[code], assignment.lag_minutes)
                    )
                    assignment_finish = (
                        assignment.axis.add(assignment_start, duration, finish=True) if duration else assignment_start
                    )
                    late_shifted = self.shift(assignment.axis, self.late_start[code], assignment.lag_minutes)
                    # no work left: the late dates stay at the period end, as the task's (_late)
                    late_assignment_start = late_shifted if not duration else assignment.axis.snap_start(late_shifted)
                    late_assignment_finish = (
                        assignment.axis.add(late_assignment_start, duration, finish=True)
                        if duration
                        else late_assignment_start
                    )
                rows.append(
                    [
                        assignment.taskrsrc_id,
                        code,
                        assignment.rsrc,
                        assignment.driving,
                        assignment_start,
                        assignment_finish,
                        late_assignment_start,
                        late_assignment_finish,
                    ]
                )
        return pd.DataFrame(rows, columns=ASSIGNMENT_COLS)

    # --- result ------------------------------------------------------------------------------
    def result(self) -> Schedule:
        self.forward()
        self.backward()
        self.floats()
        self.level_of_effort()
        longest = self.longest_path()
        self._report()
        rows = [
            {
                "task_code": code,
                "status_code": self.status[code],
                "es": self.early_start[code],
                "ef": self.early_finish[code],
                "remaining_start": self.remaining_start.get(code),
                "ls": self.late_start.get(code),
                "lf": self.late_finish.get(code),
                "tf_hr": self.total_float_hr.get(code),
                "ff_hr": self.free_float_hr.get(code),
                "resource_dependent": code in self.rsrc_dep,
                "longest_path": code in longest,
                # remaining hours an expected finish set in place of the file's (0 = finish before the start)
                "rem_override_hr": self.duration_override[code] / 60
                if code in self.duration_override
                else float("nan"),
            }
            for code in self.activities.index
            if code in self.early_start
        ]
        frame = pd.DataFrame(rows).set_index("task_code")
        return Schedule(
            frame, self.finish, self.options, self.warnings, self.assignment_dates(), self.assignment_minutes
        )

    def _report(self) -> None:
        if (self.snapshot.options.get("sched", {}) or {}).get("enable_multiple_longest_path_calc") == "Y":
            self.warnings.append(
                "the project asks for multiple float paths: dates and float are unaffected, but the float "
                "path numbers (float_path, float_path_order) are not computed"
            )
        if self.external:
            self.warnings.append(
                f"{len(self.external)} tasks bounded by P6's external early start / late finish "
                f"(relationships to projects not in the file): {sorted(self.external)[:5]}"
            )
        if self.unapplied:
            self.warnings.append(
                f"{len(self.unapplied)} in-progress tasks carry a constraint: the forward pass keeps their "
                f"actual start, the backward pass applies finish and mandatory constraints. No reference file "
                f"covers this case, compare with P6: {self.unapplied[:5]}"
            )


ASSIGNMENT_COLS = ["taskrsrc_id", "task_code", "rsrc", "driving", "restart", "reend", "rem_late_start", "rem_late_end"]


def _early(
    axis: TimeAxis, kind: str, duration: float, start_bounds: list, finish_bounds: list
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Early start / finish from lower bounds, in clock time, snapped the way P6 shows them.

    Each rule is pinned by a reference file (tests/test_cpm.py):

    - task: starts at a period start (a predecessor ending 16:00 -> next morning 08:00),
      ends at a period end; a finish bound in non-working time moves to the next working
      time (Hotel HCSWB3Z2190: shown 08:00 after a holiday, not 16:00 before it)
    - start milestone: like a task start (xerlock MS-020: 08:00 the next morning)
    - finish milestone: the bound as it is when it is working time or a period edge
      (16:00 right after its predecessor), else the next working time
    """
    if kind == "finish_ms":
        value = axis.keep_or_next(max(start_bounds + finish_bounds))
        return value, value
    if kind == "start_ms" or duration == 0:
        value = axis.snap_start(max(start_bounds + finish_bounds))
        return value, value
    start = axis.snap_start(max(start_bounds))
    finish_time = axis.add(start, duration, finish=True)
    if finish_bounds:
        finish_bound = axis.keep_or_next(max(finish_bounds))
        if finish_bound > finish_time:
            finish_time, start = finish_bound, axis.add(finish_bound, -duration, finish=False)
    return start, finish_time


def _late(
    axis: TimeAxis, kind: str, duration: float, late_start_bounds: list, late_finish_bounds: list
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Late start / finish from upper bounds, snapped the way P6 shows them.

    - task: finishes at a period end (a successor starting 08:00 -> previous evening);
      a start bound (SS / SF successor, start constraint) is written at its own instant,
      the previous period end when it falls in non-working time (H3-02 A1240: Fri 17:00,
      not Mon 07:00; the same working minute)
    - start milestone: the bound as it is when working time or a period edge, else the
      previous working time (Hotel HCMEB4000: 16:00; xerlock MS-020: 08:00)
    - finish milestone: a period end
    - task with no remaining duration: a period end, like a finish milestone, although its
      early dates sit at a period start (P6 Professional 24 export: an open activity with
      remaining 0 and an FS successor starting 08:00 shows late start = late finish at the
      previous 17:00)
    """
    if kind == "start_ms":
        value = axis.keep_or_previous(min(late_start_bounds + late_finish_bounds))
        return value, value
    if kind == "finish_ms" or (kind == "task" and duration == 0):
        value = axis.snap_finish(min(late_start_bounds + late_finish_bounds))
        return value, value
    finish_time = axis.snap_finish(min(late_finish_bounds)) if late_finish_bounds else None
    start = axis.add(finish_time, -duration, finish=False) if finish_time is not None else None
    if late_start_bounds:
        latest_start = axis.keep_or_previous(min(late_start_bounds))
        if start is None or latest_start < start:
            start, finish_time = latest_start, axis.add(latest_start, duration, finish=True)
    return start, finish_time


# --- comparison with the dates P6 stored ---------------------------------------------------

FIELDS = [
    ("es", "early_start_date"),
    ("ef", "early_end_date"),
    ("ls", "late_start_date"),
    ("lf", "late_end_date"),
    ("tf_hr", "total_float_hr_cnt"),
    ("ff_hr", "free_float_hr_cnt"),
]
ASSIGNMENT_FIELDS = [
    ("restart", "restart_date"),
    ("reend", "reend_date"),
    ("rem_late_start", "rem_late_start_date"),
    ("rem_late_end", "rem_late_end_date"),
]


def compare_with_stored(snapshot: Snapshot, recomputed: Schedule | None = None) -> pd.DataFrame:
    """One row per (open activity, field): what P6 stored, what the CPM gives, the gap.

    For in-progress activities P6 stores the remaining early start as early start.
    ``agree`` needs the exact clock time; ``gap_hr`` is the difference in working hours
    of the activity's calendar (0 with agree False = same instant shown differently,
    e.g. Wednesday 17:00 vs the next working morning).

    Against the plain recalculation (``recomputed`` None or ``schedule(snapshot)``) the table is
    cached on the snapshot, as ``schedule`` is: INT-01 and the Debug page share it. Each call
    returns its own copy.
    """
    plain = schedule(snapshot) if recomputed is None else recomputed
    if plain is not getattr(snapshot, "_xs_schedule", None):
        return _comparison(snapshot, plain)
    cached = getattr(snapshot, "_xs_comparison", None)
    if cached is None:
        cached = _comparison(snapshot, plain)
        object.__setattr__(snapshot, "_xs_comparison", cached)
    return cached.copy()


def _comparison(snapshot: Snapshot, recomputed: Schedule) -> pd.DataFrame:
    activities = snapshot.by_code
    frame = recomputed.frame
    rows = []
    axes = _Axes(snapshot, *_date_range(snapshot))
    for code in frame.index:
        if activities.at[code, "status_code"] == "TK_Complete" or activities.at[code, "is_loe"]:
            continue
        axis = axes.of(activities.at[code, "clndr_id"])
        for computed_name, stored_name in FIELDS:
            value = (
                frame.at[code, "remaining_start"]
                if computed_name == "es" and activities.at[code, "status_code"] == "TK_Active"
                else frame.at[code, computed_name]
            )
            stored = activities.at[code, stored_name] if stored_name in activities else None
            rows.append(_cmp_row(axis, code, stored_name, stored, value, hours=computed_name.endswith("_hr")))
    return pd.DataFrame(rows, columns=["task_code", "field", "stored", "computed", "gap_hr", "agree"])


def _cmp_row(axis: TimeAxis, code, field_name, stored, value, hours: bool) -> dict:
    if stored is None or pd.isna(stored) or value is None or pd.isna(value):
        gap = None
    elif hours:
        gap = round(float(value) - float(stored), 2)
    else:
        gap = axis.between(stored, value) / 60
    if hours:
        agree = gap == 0 if gap is not None else False
    else:  # dates: the same clock time, not just the same working minute
        agree = gap is not None and pd.Timestamp(stored) == pd.Timestamp(value)
    return {"task_code": code, "field": field_name, "stored": stored, "computed": value, "gap_hr": gap, "agree": agree}


def compare_assignments(snapshot: Snapshot, recomputed: Schedule | None = None) -> pd.DataFrame:
    """One row per (open assignment, date): TASKRSRC remaining early / late dates vs the CPM."""
    recomputed = recomputed or schedule(snapshot)
    assignments = snapshot.assignments
    output_columns = ["taskrsrc_id", "task_code", "rsrc", "field", "stored", "computed", "gap_hr", "agree"]
    if assignments.empty or recomputed.assignments.empty:
        return pd.DataFrame(columns=output_columns)
    stored = (
        assignments.assign(taskrsrc_id=assignments["taskrsrc_id"].astype(str))
        .drop_duplicates("taskrsrc_id")
        .set_index("taskrsrc_id")
    )
    activities = snapshot.by_code
    axes = _Axes(snapshot, *_date_range(snapshot))
    rows = []
    for computed_row in recomputed.assignments.itertuples(index=False):
        axis = axes.of(activities.at[computed_row.task_code, "clndr_id"])
        for computed_name, stored_name in ASSIGNMENT_FIELDS:
            row = _cmp_row(
                axis,
                computed_row.task_code,
                stored_name,
                stored.at[computed_row.taskrsrc_id, stored_name],
                getattr(computed_row, computed_name),
                False,
            )
            rows.append({"taskrsrc_id": computed_row.taskrsrc_id, "rsrc": computed_row.rsrc, **row})
    return pd.DataFrame(rows, columns=output_columns)


# --- DCMA critical path test ----------------------------------------------------------------


@dataclass
class CptResult:
    passed: bool
    note: str
    delayed: str | None = None
    shift_h: float = 0.0
    blocking: list[dict] = field(default_factory=list)


def _cycle_failure(error: CycleError, delayed: str | None = None) -> CptResult:
    return CptResult(False, str(error), delayed)


def critical_path_test(snapshot: Snapshot, delay_days: float) -> CptResult:
    """Add ``delay_days`` to the first open activity of the critical path; the finish must move as much.

    The finish is measured on the project's end points (activities without successors),
    in working time of the delayed activity's calendar. Pass = it moved by at least the
    delay (further is a calendar effect, less means something absorbed the delay: a mandatory
    date, or an expected finish downstream, whose activity loses its remaining duration when the
    delay pushes it past that date; both are named with what they absorbed).
    """
    activities = snapshot.activities
    try:
        base = schedule(snapshot)
    except CycleError as exc:
        return _cycle_failure(exc)
    # The critical path = the longest path of the recalculated schedule (with negative
    # float, "total float <= 0" would also take in less critical paths).
    frame = base.frame
    open_ = activities[
        ~activities["is_complete"] & ~activities["is_loe"] & ~activities["is_milestone"]
    ].drop_duplicates("task_code")
    critical_path = open_[open_["task_code"].map(frame["longest_path"]).fillna(False).astype(bool)]
    if critical_path.empty:
        return CptResult(False, "no open task on the longest path: the critical path is not defined")
    critical_path = critical_path.assign(_rs=critical_path["task_code"].map(frame["remaining_start"]))
    target = critical_path.sort_values(["_rs", "task_code"]).iloc[0]
    code = target["task_code"]
    hours_per_day = float(target["hours_per_day"])
    delay_hours = delay_days * hours_per_day
    try:
        late = schedule(snapshot, {code: delay_hours}, base=base)
    except CycleError as exc:
        return _cycle_failure(exc, code)
    has_successor = set(snapshot.relationships["pred_code"])  # built once: per activity it took 33 s on Hotel
    end_points = [code for code in base.frame.index if code not in has_successor]
    base_finish = base.frame.loc[end_points, "ef"].max()
    delayed_finish = late.frame.loc[end_points, "ef"].max()
    axis = TimeAxis(
        snapshot.calendar(target["clndr_id"]), base_finish.date(), (delayed_finish + pd.Timedelta(days=1)).date()
    )
    shift = axis.between(base_finish, delayed_finish) / 60
    # The finish must move by the whole delay, measured on the delayed activity's calendar. It
    # can move further when the path crosses calendars with other non-working days; it can also
    # read less for the same reason (the window of the move holds non-working days of that
    # calendar the downstream path does not observe), so the proportion is also read in calendar
    # days: the finish must move at least as much as the delayed activity's own finish did.
    # Less on both readings means a constraint, an expected finish or broken logic absorbed it.
    own_move = late.frame.at[code, "ef"] - base.frame.at[code, "ef"]
    end_move = delayed_finish - base_finish
    passed = shift >= delay_hours - 1e-6 or end_move >= own_move
    note = (
        f"+{delay_days:g} wd on {code}: forecast finish {base_finish:%Y-%m-%d} -> {delayed_finish:%Y-%m-%d}, "
        f"moved {shift / hours_per_day:+.1f} wd"
        + ("" if passed else f" instead of {delay_days:+g}")
        + (" (more: the path crosses other calendars' non-working days)" if shift > delay_hours + 1e-6 else "")
    )
    if shift < delay_hours - 1e-6:
        # fewer working days than the delay on the delayed activity's calendar: say what the project
        # calendar and the calendar days read, so a calendar effect is told from an absorbed delay
        project = snapshot.calendar()
        project_axis = TimeAxis(project, base_finish.date(), (delayed_finish + pd.Timedelta(days=1)).date())
        project_shift_wd = (
            project_axis.between(base_finish, delayed_finish) / 60 / (project.hours_per_day or hours_per_day)
        )
        note += (
            f" ({project_shift_wd:+.1f} wd on the project calendar; {end_move.days:+d} calendar days against "
            f"{own_move.days:+d} for {code}'s own finish"
            + (": a calendar effect, the whole delay reached the finish)" if passed else ")")
        )
    blocking = []
    if not passed:
        # only open work can absorb a delay: a finished activity's mandatory date is history
        mandatory = activities["cstr_type"].isin(MANDATORY) | activities["cstr_type2"].isin(MANDATORY)
        pinned = activities[mandatory & ~activities["is_complete"].astype(bool)]
        blocking = [
            {**row, "reason": "mandatory date", "absorbed_wd": None}
            for row in pinned[["task_code", "task_name", "cstr_type", "cstr_type2"]].to_dict("records")
        ]
        if blocking:
            note += f"; mandatory constraints may absorb it: {', '.join(pin['task_code'] for pin in blocking[:5])}"
        # an expected finish downstream shortens the remaining duration of its activity when the
        # delay pushes its start past that date (to 0 beyond it): the shortening is the absorption
        shortened = (base.frame["rem_override_hr"] - late.frame["rem_override_hr"].reindex(base.frame.index)).fillna(0)
        shortened = shortened[(shortened > 1e-6) & (shortened.index != code)]
        if not shortened.empty:
            names = activities.set_index("task_code")["task_name"]
            hours = activities.set_index("task_code")["hours_per_day"].astype(float)
            absorbing = [
                {
                    "task_code": task, "task_name": names.get(task, ""), "cstr_type": "", "cstr_type2": "",
                    "reason": "expected finish", "absorbed_wd": round(float(cut / hours.get(task, hours_per_day)), 1),
                }
                for task, cut in shortened.sort_values(ascending=False).items()
            ]  # fmt: skip
            blocking += absorbing
            listed = ", ".join(f"{item['task_code']} ({item['absorbed_wd']:g} wd)" for item in absorbing[:5])
            note += f"; expected finish dates absorb it (remaining duration cut when pushed past them): {listed}"
    return CptResult(passed, note, code, shift, blocking)
