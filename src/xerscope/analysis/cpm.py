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
  >= date; a primary mandatory start / finish pins the date whatever the logic, except that
  the early dates never fall before the data date; in the second slot it bounds as a start
  on / finish on (``second_constraint_type``); a constraint of the wrong kind on a milestone
  (finish constraint on a start milestone) is ignored
- in progress: actual start kept; the remaining duration starts at the data date, after
  open predecessors too under Retained Logic (P6 default) and Actual Dates; under Progress
  Override its start is an actual, so FS / SS predecessors no longer bound it while FF / SF
  predecessors still bound its finish
- expected finish (option on): the early finish, or the early start when it falls before
  it (remaining 0); an FF / SF bound later than that wins; ALAP ignores it (``expected_finish``);
  an unstarted milestone sits at the later of its logic and it, its remaining staying 0
  (``milestone_expected_finish``)
- finished, under Retained Logic: logic passes through it (out-of-sequence progress, see
  ``pred_bounds``)
- finish = start + remaining duration (minutes of the activity's calendar)
- resource dependent: the bound is taken on the activity's calendar, each driving
  assignment is placed from it on its resource's calendar (+ assignment lag, duration =
  remaining units / units per hour, or its remaining window without a rate), the activity
  starts at the earliest assignment start on its own calendar and the assignments run
  forward from there (``rsrc_early``)

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

import math
import re
from collections import defaultdict, deque
from collections.abc import Iterator
from dataclasses import dataclass, field, replace

import pandas as pd
from pandas.errors import OutOfBoundsDatetime

from ..xer import Snapshot
from ..xer.calendar import TimeAxis, WorkCalendar

START_LIKE = {"CS_MSO": "start", "CS_MSOA": "start", "CS_MEO": "finish", "CS_MEOA": "finish"}  # forward
LATE_LIKE = {"CS_MSO": "start", "CS_MSOB": "start", "CS_MEO": "finish", "CS_MEOB": "finish"}  # backward
MANDATORY = {"CS_MANDSTART": "start", "CS_MANDFIN": "finish"}
# What a mandatory date in the second slot is scheduled as: it bounds both passes and pins nothing
AS_SECOND_CONSTRAINT = {"CS_MANDSTART": "CS_MSO", "CS_MANDFIN": "CS_MEO"}
# On work under way, one of these in either slot removes both constraints from the backward pass
DROPS_LATE_SIDE_UNDER_WAY = ("CS_MSOB", "CS_MANDSTART", "CS_MANDFIN")
PROGRESSED = ("retained_logic", "progress_override", "actual_dates")
H24 = WorkCalendar("__24h__", "24 hours", 24.0, (((0, 1440),),) * 7, {}, from_data=False)
LINK_TYPES = ("FS", "SS", "FF", "SF")
# The end of a level of effort each relationship ties: its start through these, its finish through the others
# (Boyle, "constructing LOE activities in P6").
LOE_START_FROM_PREDECESSOR = ("SS", "FS")
LOE_START_FROM_SUCCESSOR = ("SS", "SF")
# Longest remaining duration, lag, assignment duration or asked delay the engine schedules, in hours
# (114 years of 24 h days). Beyond it, or non-finite, the value is refused as a ScheduleError before the passes
# run; a bounded value that still lands past year 2262 (pandas' limit) on a sparse calendar is
# translated to the same error in _schedule. The model clamps such values on load with a warning.
MAX_HOURS = 1e6


class ScheduleError(ValueError):
    """The snapshot cannot be scheduled; ``members`` name the activities (or links) at fault."""

    def __init__(self, message: str, members: tuple[str, ...] = ()):
        super().__init__(message)
        self.members = members


class CycleError(ScheduleError):
    """The logic has a loop; ``members`` are the activities on a loop (not the ones downstream of it)."""


class _Components:
    """Strongly connected components of ``candidates``: the groups of activities that all reach each
    other through the links (Tarjan's algorithm, with its own stack instead of recursion).

    Each activity gets a number in the order it is first met (``index``) and the smallest number it
    can reach back to (``low``). An activity whose two numbers are equal closes a component: the
    activities met since it, still on ``stack``, all reach each other.
    """

    def __init__(self, candidates: set[str], successors: dict[str, list]):
        self.candidates, self.successors = candidates, successors
        self.index: dict[str, int] = {}
        self.low: dict[str, int] = {}
        self.stack: list[str] = []
        self.on_stack: set[str] = set()
        self.components: list[list[str]] = []
        for root in sorted(candidates):
            if root not in self.index:
                self._walk_from(root)

    def _open(self, code: str) -> tuple[str, Iterator]:
        """Number the activity, put it on the stack; what the walk keeps: the code and its links left to follow."""
        self.index[code] = self.low[code] = len(self.index)
        self.stack.append(code)
        self.on_stack.add(code)
        return code, iter(self.successors[code])

    def _next_unmet(self, code: str, remaining: Iterator) -> str | None:
        """First successor not met yet among the links left; one met and still on the stack is a way back."""
        for successor, _, _ in remaining:
            if successor not in self.candidates:
                continue
            if successor not in self.index:
                return successor
            if successor in self.on_stack:
                self.low[code] = min(self.low[code], self.index[successor])
        return None

    def _walk_from(self, root: str) -> None:
        """Follow the links depth first from ``root``, closing each component as its first activity is left."""
        work = [self._open(root)]
        while work:
            code, remaining = work[-1]
            successor = self._next_unmet(code, remaining)
            if successor is not None:
                work.append(self._open(successor))
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                self.low[parent] = min(self.low[parent], self.low[code])
            if self.low[code] == self.index[code]:
                self.components.append(self._closed_by(code))

    def _closed_by(self, code: str) -> list[str]:
        """Activities taken off the stack down to ``code``: one component."""
        component = []
        while True:
            member = self.stack.pop()
            self.on_stack.discard(member)
            component.append(member)
            if member == code:
                return component


def _loop_members(candidates: set[str], successors: dict[str, list]) -> list[str]:
    """Activities of ``candidates`` that lie on a loop: strongly connected components of more than
    one activity, or an activity linked to itself."""
    members: list[str] = []
    for component in _Components(candidates, successors).components:
        code = component[-1]
        if len(component) > 1 or any(successor == code for successor, _, _ in successors[code]):
            members.extend(component)
    return sorted(members)


def loop_members(snapshot: Snapshot) -> list[str]:
    """Activities on a logic loop, read from the links alone: no date, duration or lag is needed.

    The network is the one the passes schedule (`_Run._network`): the activities that are not level
    of effort, and the relationships of a known type between two of them. The engine names the
    same activities when it refuses a loop (``CycleError.members``).
    """
    activities = snapshot.by_code
    nodes = {code for code, is_loe in activities["is_loe"].items() if not is_loe}
    links = snapshot.relationships
    links = links[links["type"].isin(LINK_TYPES) & links["pred_code"].isin(nodes) & links["succ_code"].isin(nodes)]
    successors: dict[str, list] = defaultdict(list)
    for predecessor, successor in zip(links["pred_code"], links["succ_code"], strict=True):
        successors[predecessor].append((successor, None, None))  # the shape of `_Run.succs`: type and lag unread here
    return _loop_members(nodes, successors)


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


@dataclass(frozen=True)
class Schedule:
    """One recalculation. ``schedule`` hands every caller its own copy of the frames, the warnings
    and the minutes, so an edit by one caller never reaches another or the cached result."""

    frame: pd.DataFrame  # index task_code: RESULT_COLS (es, ef, ls, lf, tf_hr, ff_hr, rem_override_hr, ...)
    finish: pd.Timestamp | None
    options: Options
    warnings: list[str] = field(default_factory=list)
    assignments: pd.DataFrame = field(default_factory=pd.DataFrame)  # one row per open assignment
    assignment_minutes: dict[str, float] = field(default_factory=dict)  # taskrsrc_id -> remaining minutes as placed
    # the plain recalculation (file options, no delay), the one cached on the snapshot: its
    # comparison with the stored dates is cached too (compare_with_stored)
    plain: bool = False

    def copy(self) -> Schedule:
        return replace(
            self,
            frame=self.frame.copy(),
            warnings=list(self.warnings),
            assignments=self.assignments.copy(),
            assignment_minutes=dict(self.assignment_minutes),
        )


RESULT_COLS = [
    "task_code",
    "status_code",
    "es",
    "ef",
    "remaining_start",
    "ls",
    "lf",
    "tf_hr",
    "ff_hr",
    "resource_dependent",
    "longest_path",
    "rem_override_hr",
]


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

    The plain recalculation (no extra delay, file options) is cached on the snapshot: the
    integrity check, the critical path test and the weekly history share it. Each call returns
    its own copy (0.1 ms on Hotel against 1 s of scheduling), so a caller may edit what it gets
    without reaching the cache. The snapshot is immutable; an edited one is a new snapshot
    (``dataclasses.replace``) with an empty cache.

    Raises ``CycleError`` on a logic loop and ``ScheduleError`` (its base) when a remaining
    duration, a lag, an assignment duration or a delay of ``extra_hours`` is not finite or exceeds
    ``MAX_HOURS``, or when the file holds no date to schedule from. The dates and the lags are
    checked before the loops are looked for, the durations after.

    ``base``: the plain recalculation, given with ``extra_hours``. A delayed activity then drops
    its expected finish, which would absorb the delay, and runs its remaining duration in
    ``base`` (the one the expected finish set, if any) plus the delay.
    """
    if not extra_hours and options is None:
        cached = getattr(snapshot, "_xs_schedule", None)
        if cached is None:
            cached = replace(_schedule(snapshot, None, None), plain=True)
            object.__setattr__(snapshot, "_xs_schedule", cached)
        return cached.copy()
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


def _number_or_zero(value) -> float:
    """A number of the assignment table as a float, 0 when the file gives none."""
    return float(value) if pd.notna(value) else 0.0


def _refuse_unbounded_assignments(unbounded: list[str]) -> None:
    """Refuse the assignments, listed as "Activity ID/assignment id", whose lag or duration is not finite
    or beyond ``MAX_HOURS``, naming their activities."""
    if unbounded:
        raise ScheduleError(
            f"{len(unbounded)} assignments carry a lag or a duration (units / units per hour) that is not "
            f"finite or beyond {MAX_HOURS:g} h: {unbounded[:8]}",
            tuple(sorted({entry.split("/")[0] for entry in unbounded})),
        )


def _refuse_unbounded_delays(extra_hours: dict[str, float]) -> None:
    """Refuse a delay that is not finite or beyond ``MAX_HOURS``, naming the activities to delay: the
    rule of a remaining duration and of a lag, for the one value that does not come from the file."""
    unbounded = sorted(task_code for task_code, delay_hr in extra_hours.items() if not _bounded(delay_hr))
    if unbounded:
        raise ScheduleError(
            f"{len(unbounded)} activities are asked a delay that is not finite or beyond {MAX_HOURS:g} h: "
            f"{unbounded[:8]}",
            tuple(unbounded),
        )


def _schedule(
    snapshot: Snapshot, extra_hours: dict[str, float] | None, options: Options | None, base: Schedule | None = None
) -> Schedule:
    _refuse_unbounded_delays(extra_hours or {})
    try:
        return _Run(snapshot, extra_hours or {}, options or Options.from_snapshot(snapshot), base).result()
    except ScheduleError:
        raise
    except (OverflowError, OutOfBoundsDatetime) as exc:  # a date past year 2262 the time axis cannot hold
        raise ScheduleError(f"a date falls outside the schedulable range: {exc}") from exc
    except ValueError as exc:  # the time axis refuses a date outside its range before growing to it
        if "date out of range" not in str(exc):
            raise
        raise ScheduleError(f"a date falls outside the schedulable range: {exc}") from exc


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
                raise ScheduleError("no status date, no planned start and no task date: nothing to schedule from")
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
        self._durations()
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
        self.preds: dict[str, list] = defaultdict(list)
        self.succs: dict[str, list] = defaultdict(list)
        self.loe_preds: dict[str, list] = defaultdict(list)
        self.loe_succs: dict[str, list] = defaultdict(list)
        links = self.snapshot.relationships[["pred_code", "succ_code", "type", "lag_hr"]]
        self.linked_on = set(links["pred_code"])  # has a successor of any kind (LOE, WBS summary included)
        links = self._readable_links(links)
        self._file_links(links)
        self._warn_of_loe_to_loe(links)
        self.order = self._topological_order()

    def _readable_links(self, links: pd.DataFrame) -> pd.DataFrame:
        """Links the passes have a rule for.

        Defensive reading of the link table (the model validates it too): a type the passes have
        no rule for is left out with a warning rather than read as SF by the FS/SS "else" branches;
        a lag the time axis cannot place is a typed error, never an OverflowError.
        """
        unknown = links[~links["type"].isin(LINK_TYPES)]
        if not unknown.empty:
            shown = unknown[["pred_code", "succ_code", "type"]].head(5).itertuples(index=False)
            self.warnings.append(
                f"{len(unknown)} relationships of a type not in {LINK_TYPES} ignored: "
                f"{[f'{p}->{s} {t}' for p, s, t in shown]}"
            )
            links = links[links["type"].isin(LINK_TYPES)]
        lags = pd.to_numeric(links["lag_hr"], errors="coerce").fillna(0.0)
        unbounded = links[~_bounded(lags)]
        if not unbounded.empty:
            raise ScheduleError(
                f"{len(unbounded)} relationships carry a lag that is not finite or beyond {MAX_HOURS:g} h: "
                f"{[f'{p}->{s}' for p, s in unbounded[['pred_code', 'succ_code']].head(8).itertuples(index=False)]}",
                tuple(sorted(set(unbounded["pred_code"]) | set(unbounded["succ_code"]))),
            )
        return links

    def _file_links(self, links: pd.DataFrame) -> None:
        """Each link under its two ends, lag in minutes: between two scheduled activities (``preds``,
        ``succs``), or between a level of effort and a scheduled activity (``loe_preds``, ``loe_succs``)."""
        node_set = set(self.nodes)
        loe_set = set(self.loe_codes)
        for predecessor, successor, link_type, lag in links.itertuples(index=False):
            lag_minutes = float(lag or 0) * 60
            if predecessor in node_set and successor in node_set:
                self.preds[successor].append((predecessor, link_type, lag_minutes))
                self.succs[predecessor].append((successor, link_type, lag_minutes))
            elif successor in loe_set and predecessor in node_set:
                self.loe_preds[successor].append((predecessor, link_type, lag_minutes))
            elif predecessor in loe_set and successor in node_set:
                self.loe_succs[predecessor].append((successor, link_type, lag_minutes))

    def _warn_of_loe_to_loe(self, links: pd.DataFrame) -> None:
        """An LOE takes its dates from the work it spans; a link between two LOEs gives neither a
        date here. Whether P6 schedules one LOE from another is not documented: counted, not lost."""
        loe_to_loe = [
            (predecessor, successor)
            for predecessor, successor in zip(links["pred_code"], links["succ_code"], strict=True)
            if self.is_loe.get(predecessor, False) and self.is_loe.get(successor, False)
        ]
        if loe_to_loe:
            self.warnings.append(
                f"{len(loe_to_loe)} relationship(s) between two level-of-effort activities, ignored: {loe_to_loe[:5]}"
            )

    def _topological_order(self) -> list[str]:
        """Scheduled activities, each after all its predecessors; a logic loop is refused (``CycleError``).

        The network is a directed graph: activities are nodes, relationships are edges
        (predecessor -> successor). We need an order in which every activity comes after all
        its predecessors (a topological sort, Kahn's algorithm): the forward pass can then
        compute an activity from predecessors already computed, and the backward pass walks
        the same order reversed, so successors are computed first.
        in_degree[x] = number of predecessors of x not placed yet; x is ready at 0.
        Example, A -> B -> D and A -> C -> D:
          start  A=0 B=1 C=1 D=2  -> place A
                 B=0 C=0 D=2      -> place B, then C
                 D=0              -> place D        order = [A, B, C, D]
        """
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
        return order

    def _durations(self) -> None:
        """Remaining durations of the open activities the passes will place: finite and bounded (else a
        typed error), never negative (read as 0, warned). The model clamps the same values on load with
        its own warning; this keeps the engine safe on a snapshot built another way."""
        remaining = {
            code: self.inputs[code].get("remain_drtn_hr_cnt")
            for code in self.nodes
            if self.status[code] != "TK_Complete"
        }
        remaining = {code: float(value) for code, value in remaining.items() if pd.notna(value)}
        unbounded = sorted(code for code, value in remaining.items() if not _bounded(value))
        if unbounded:
            raise ScheduleError(
                f"{len(unbounded)} activities carry a remaining duration that is not finite or beyond "
                f"{MAX_HOURS:g} h: {unbounded[:8]}",
                tuple(unbounded),
            )
        negative = sorted(code for code, value in remaining.items() if value < 0)
        if negative:
            self.warnings.append(
                f"{len(negative)} activities with a negative remaining duration, read as 0: {negative[:5]}"
            )

    def _assignments(self) -> None:
        """Open assignments. Resource-dependent activities are scheduled from their driving
        assignments, each on its resource's calendar; the others use the activity calendar."""
        self.assignments_by_task: dict[str, list[_Asg]] = defaultdict(list)
        assignment_table = self.snapshot.assignments
        unbounded: list[str] = []
        for row in assignment_table.itertuples(index=False) if not assignment_table.empty else []:
            code = row.task_code
            if code not in self.inputs or self.status[code] == "TK_Complete" or self.is_loe[code]:
                continue
            assignment = self._assignment_from_row(code, row)
            if assignment is None:
                unbounded.append(f"{code}/{row.taskrsrc_id}")
                continue
            self.assignments_by_task[code].append(assignment)
        _refuse_unbounded_assignments(unbounded)
        self._record_resource_dependent()

    def _assignment_from_row(self, code: str, row) -> _Asg | None:
        """One row of the assignment table as the engine schedules it: on the resource calendar when the
        activity is of type Resource Dependent and the row names one, else on the activity calendar; its
        duration is remaining units / units per hour. None when its lag or its duration is not finite or
        beyond ``MAX_HOURS``.

        Without a rate above 0, an assignment on a resource calendar lasts the working time between its
        own remaining start and finish, and its lag runs as the lag of a link out of the activity does
        (``unexpired``). P6 23.12.1: 181 such assignments of the held-out corpus after P6's import, e.g.
        H25-09 A1480; probes zero-units. 26.8 not measured. Not measured either, and left without a
        duration: no remaining dates, or a resource without a calendar.
        """
        remaining_units = _number_or_zero(row.remain_qty)
        units_per_hour = _number_or_zero(row.remain_qty_per_hr)
        is_on_resource_calendar = self.inputs[code].get("task_type") == "TT_Rsrc" and bool(row.rsrc_clndr_id)
        axis = self.axes.of(row.rsrc_clndr_id) if is_on_resource_calendar else self.cal_ax[code]
        lag_hours = _number_or_zero(row.relag_drtn_hr_cnt)
        lag_minutes, remaining_minutes = lag_hours * 60, None
        if units_per_hour > 0:
            remaining_minutes = remaining_units / units_per_hour * 60
        elif is_on_resource_calendar:
            remaining_minutes = _window_minutes(row, axis)
            lag_minutes = self.unexpired(code, axis, lag_minutes)
        if not _bounded(lag_hours) or (remaining_minutes is not None and not _bounded(remaining_minutes / 60)):
            return None
        resource_name = str(row.rsrc_short_name or row.rsrc_name or row.rsrc_id or "")
        return _Asg(str(row.taskrsrc_id), resource_name, axis, lag_minutes, remaining_minutes, bool(row.driving))

    def _record_resource_dependent(self) -> None:
        """Keep the activities scheduled from their resources (``rsrc_dep``): unfinished, of type Resource
        Dependent, with a driving assignment that has a duration. Warn of those of that type without one."""
        of_resource_type = {
            code
            for code in self.nodes
            if self.inputs[code].get("task_type") == "TT_Rsrc" and self.status[code] != "TK_Complete"
        }
        self.rsrc_dep = {code for code in of_resource_type if self.driving(code)}
        lacking = [code for code in self.nodes if code in of_resource_type and code not in self.rsrc_dep]
        if lacking:
            self.warnings.append(
                f"{len(lacking)} resource-dependent tasks without a driving assignment that has a "
                f"duration, scheduled on their task calendar: {lacking[:5]}"
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
        remaining = 0.0 if pd.isna(remaining_hr) else max(0.0, float(remaining_hr)) * 60  # negative: 0 (_durations)
        return remaining + self.extra_hours.get(code, 0.0) * 60

    def driving(self, code) -> list[_Asg]:
        return [
            assignment
            for assignment in self.assignments_by_task[code]
            if assignment.driving and assignment.duration_minutes is not None
        ]

    def constraints(self, code) -> list[tuple[str, pd.Timestamp]]:
        """Dated constraints of ``c`` P6 schedules with. A finish constraint on a start
        milestone, or a start constraint on a finish milestone (P6's own dialog refuses
        them; an import keeps them), is ignored (P6 23.12 corpus, H6-03 A1130).

        Only the primary constraint pins: the second one is given as it is scheduled
        (``second_constraint_type``).
        """
        dated = []
        activity_kind = self.kind(code)
        written = self.inputs[code]
        slots = (
            (written.get("cstr_type"), written.get("cstr_date")),
            (self.second_constraint_type(code), written.get("cstr_date2")),
        )
        for constraint_type, date in slots:
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

    def second_constraint_type(self, code):
        """The type of the second constraint as P6 schedules it.

        On work not started, a Mandatory Start / Finish in the second slot is a Start On / Finish On
        and pins nothing. P6 23.12.1, 26.8 not measured. Late side: probes xf-mandatory (Q9,
        Q10: it caps as an "On or Before" does). Early side: the same probes for a Mandatory Finish
        (the early finish of Q9 and Q10 is the date); for a Mandatory Start, held-out corpus H29-01
        A1300 and H24-05 A1350 (the early start is the date). Work under way keeps the type as
        written: no mandatory date bounds its late dates (``late_constraints``; H28-03 A1410).
        """
        written = self.inputs[code].get("cstr_type2")
        if self.status[code] == "TK_NotStart":
            return AS_SECOND_CONSTRAINT.get(written, written)
        return written

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
            if self.is_binding(predecessor, link_type, started, finish_only):
                out.append((bounded_end, self.pred_bound(code, predecessor, link_type, lag)))
        return out

    def is_binding(self, predecessor: str, link_type: str, started: bool, finish_only: bool) -> bool:
        """False for the two links Progress Override releases: from a finished predecessor to the start
        of work under way, and an SF link from a predecessor under way."""
        predecessor_status = self.status[predecessor]
        if predecessor_status == "TK_Complete" and not self.retain and started and not finish_only:
            return False  # Progress Override: a finished FF / SF predecessor still bounds
        # Progress Override: the predecessor's start is an actual, an SF from it
        # binds nothing (H10-02 A1250); an SS still does, through its unexpired lag
        is_sf_from_work_under_way = link_type == "SF" and predecessor_status == "TK_Active"
        return not (is_sf_from_work_under_way and self.options.progressed == "progress_override")

    def pred_bound(self, code: str, predecessor: str, link_type: str, lag: float) -> pd.Timestamp:
        """Earliest instant one binding link allows: the predecessor's date the link reads, plus the lag."""
        link_axis = self.lag_axis(predecessor, code)
        if self.status[predecessor] == "TK_Complete" and self.retain:
            return self.retained_bound(code, predecessor, link_type, lag, link_axis)
        if link_type in ("FS", "FF"):
            return self.shift(link_axis, self.early_finish[predecessor], lag)
        predecessor_start, predecessor_lag = self.start_link(predecessor, link_axis, lag)
        return self.shift(link_axis, predecessor_start, predecessor_lag)

    def retained_bound(
        self, code: str, predecessor: str, link_type: str, lag: float, link_axis: TimeAxis
    ) -> pd.Timestamp:
        """Bound a finished predecessor gives under Retained Logic: the date it carries, plus the part of
        a positive lag not yet expired since its actual finish (FS, FF) or start (SS, SF)."""
        if self.status[code] == "TK_Complete":
            return self.carry[predecessor]
        measured_from = self.inputs[predecessor].get("act_end_date" if link_type in ("FS", "FF") else "act_start_date")
        has_actual = measured_from is not None and pd.notna(measured_from)
        unexpired_lag = lag
        if lag <= 0:
            unexpired_lag = 0.0
        elif has_actual:
            unexpired_lag = max(0.0, lag - max(0, link_axis.between(measured_from, self.data_date)))
        if link_type == "SS" and not self.options.lag_from_early_start and has_actual:
            # "Calculate start-to-start lag from Actual Start": from the finished
            # predecessor's actual start, whatever it still carries (H6-07 A1190)
            return self.shift(link_axis, measured_from, lag)
        return self.shift(link_axis, self.carry[predecessor], unexpired_lag)

    def unexpired(self, predecessor: str, link_axis: TimeAxis, lag: float) -> float:
        """Minutes of a lag counted from the start of ``predecessor`` still to run after the data date:
        the lag of an SS / SF link out of it, or of one of its assignments without a rate. The whole
        lag when the activity is not under way; a lead is left as it is."""
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
        for code in self.order:
            if self.status[code] == "TK_Complete":
                self.forward_finished(code)
            else:
                self.forward_open(code)
        self.open_ = [code for code in self.order if self.status[code] != "TK_Complete"]
        # Under Retained Logic a finished activity ends, for its successors, at its carried
        # date: an actual finish after the data date (invalid progress) no longer sets the end.
        self.finish = max(
            (
                self.carry.get(code, self.early_finish[code])
                if self.status[code] == "TK_Complete"
                else self.early_finish[code]
                for code in self.nodes
            ),
            default=None,
        )

    def forward_open(self, code) -> None:
        """Early dates of one open activity: its bounds, its constraints, the placement, then what a
        Mandatory Finish and an expected finish change."""
        axis = self.cal_ax[code]
        started = self.status[code] == "TK_Active"
        activity_kind, duration = self.kind(code), self.dur_min(code)
        start_bounds, finish_bounds = self.early_bounds(code, started)
        milestone_expected = self.milestone_expected_finish(code)
        pinned, constraint_start_bounds, constraint_finish_bounds = self.forward_constraints(code, started)
        # Mandatory Start / Finish: the date, whatever the logic, in both passes; except
        # that unstarted work never starts before the data date (H3-04 A1100, H2-06
        # A1130: the early dates move to the data date, the late dates stay). A milestone's
        # expected finish still counts: it sits at the later of that date and the Mandatory Start
        # (P6 23.12.1 on the held-out corpus: 17 milestones; tests/test_cpm_milestone_mandatory_start.py).
        # So does the second constraint: the early dates take the later of the pin and its date
        # (H24-05 A1350, H24-04 A1210, H23-02 A1230; tests/test_cpm_second_constraint.py)
        if pinned and pinned[0] == "start":
            start_bounds, finish_bounds = [max(pinned[1], self.data_date)], []
        start_bounds += constraint_start_bounds
        finish_bounds += constraint_finish_bounds
        if milestone_expected is not None:
            finish_bounds.append(milestone_expected)
        if pinned and pinned[0] == "finish" and not self.has_expected_finish(code):
            start, finish_time = self.mandatory_finish_dates(code, axis, activity_kind, duration, pinned[1])
        elif code in self.rsrc_dep and activity_kind == "task":
            start, finish_time = self.rsrc_early(
                code,
                start_bounds,
                finish_bounds,
                self.extra_hours.get(code, 0.0) * 60,
                self.resource_expected_finish(code),
            )
        else:
            start, finish_time = _early(axis, activity_kind, duration, start_bounds, finish_bounds)
        if self.has_task_expected_finish(code, activity_kind):
            start, finish_time = self.expected_finish(
                code,
                axis,
                pd.Timestamp(self.inputs[code].get("expect_end_date", pd.NaT)),
                start_bounds,
                finish_bounds,
                start,
                finish_time,
                self.is_start_bound_by_logic(started),
                any(link_type in ("FF", "SF") for _, link_type, _ in self.preds[code]),
                self.options.collapse_early_expected_finish,
            )
        self.record_early(code, started, activity_kind, start, finish_time)

    def is_start_bound_by_logic(self, started: bool) -> bool:
        """False for work under way under Progress Override: its start is an actual, so FS / SS
        predecessors no longer bound it; FF / SF predecessors still bound its finish (H1-11 A1040).
        Mirrored in successor_limits."""
        return not (started and self.options.progressed == "progress_override")

    def early_bounds(self, code, started: bool) -> tuple[list, list]:
        """Earliest dates the start and the finish may take ("not before" bounds), constraints apart: the
        data date, a resume date, the predecessors and the early date a link to another project gives."""
        finish_bounds: list[pd.Timestamp]
        start_bounds, finish_bounds = [self.data_date], []
        resume = self.inputs[code].get("resume_date") if started else None
        if resume is not None and pd.notna(resume):
            # suspended work resumes on its resume date (H8-07 A1020)
            start_bounds.append(max(self.data_date, pd.Timestamp(resume)))
        for bounded_end, bound in self.pred_bounds(
            code, started, finish_only=not self.is_start_bound_by_logic(started)
        ):
            (start_bounds if bounded_end == "start" else finish_bounds).append(bound)
        external_date = self.inputs[code].get("external_early_start_date")
        if self.options.honor_external and external_date is not None and pd.notna(external_date):
            # a lost link to a project not in the database: not a link of this project, so Progress
            # Override does not release work under way from it (H8-08 A1020, H10-12 A1130, H15-09 A1110)
            start_bounds.append(pd.Timestamp(external_date))
            self.external.add(code)
        return start_bounds, finish_bounds

    def resource_expected_finish(self, code) -> pd.Timestamp | None:
        """Expected finish a resource-dependent activity is placed with: none when the option is off,
        the activity is delayed or as late as possible, or the date is before the data date."""
        use_expected = self.options.use_expected_finish and not self.delayed(code)
        expected_date = self.inputs[code].get("expect_end_date", pd.NaT) if use_expected else pd.NaT
        if pd.notna(expected_date) and not self.is_as_late_as_possible(code) and expected_date >= self.data_date:
            return pd.Timestamp(expected_date)
        return None

    def has_expected_finish(self, code) -> bool:
        """True when the activity has an expected finish the option applies to: it is on, the activity
        is not delayed and not as late as possible."""
        if not self.options.use_expected_finish or self.delayed(code):
            return False
        return pd.notna(self.inputs[code].get("expect_end_date", pd.NaT)) and not self.is_as_late_as_possible(code)

    def has_task_expected_finish(self, code, activity_kind: str) -> bool:
        """True when an expected finish sets the remaining duration of task-dependent work."""
        return activity_kind == "task" and self.has_expected_finish(code) and code not in self.rsrc_dep

    def milestone_expected_finish(self, code) -> pd.Timestamp | None:
        """The expected finish an unstarted milestone is placed at, or None.

        A bound on its early date: the milestone sits at the later of its logic and the expected finish.
        The date is passed as entered and written like any milestone date (``_early``): a finish
        milestone keeps a working instant and moves to the next opening otherwise, a start milestone
        takes the next opening. P6 23.12.1 (26.8 not measured): held-out corpus H23-09 A1200, H26-08
        A1390, H28-11 A1330, H26-11 A1370; probes h3-situations X8, X9 (Sunday 17:00 -> Monday 08:00),
        X11 (08:00 kept).
        """
        is_unstarted_milestone = self.status[code] == "TK_NotStart" and self.kind(code) != "task"
        if not is_unstarted_milestone or not self.has_expected_finish(code):
            return None
        return pd.Timestamp(self.inputs[code]["expect_end_date"])

    def mandatory_finish_dates(
        self, code, axis: TimeAxis, activity_kind: str, duration: float, date: pd.Timestamp
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Early dates under a Mandatory Finish: the finish at the date and the start a duration before;
        from the data date instead when that start would fall before it.

        Resource-dependent work takes that start only: its driving assignments run on from it on their
        own calendars and the early finish is theirs, before or after the date (P6 23.12.1: probe
        xf-mandatory Q2, early finish a day after the date; held-out corpus H28-04 A1100, a day
        before; 26.8 not measured).
        """
        has_duration = activity_kind == "task" and duration
        finish_time = axis.keep_or_previous(date)
        start = axis.add(finish_time, -duration, finish=False) if has_duration else finish_time
        if start < self.data_date:
            start = axis.snap_start(self.data_date)
            finish_time = axis.add(start, duration, finish=True) if has_duration else start
        if code in self.rsrc_dep and activity_kind == "task":
            return self.rsrc_early(code, [start], [], self.extra_hours.get(code, 0.0) * 60)
        return start, finish_time

    def record_early(self, code, started: bool, activity_kind: str, start, finish_time) -> None:
        """Keep the early dates: work under way shows its actual start, its remaining start apart."""
        actual_start = self.inputs[code].get("act_start_date") if started else None
        if started and (actual_start is None or pd.isna(actual_start)):
            # the mirror of "complete without actual dates": the early start is the remaining start
            self.warnings.append(f"{code}: in progress without an actual start")
            actual_start = None
        self.early_start[code] = actual_start if actual_start is not None and activity_kind == "task" else start
        self.early_finish[code] = finish_time
        self.remaining_start[code] = start

    def forward_finished(self, code) -> None:
        """A finished activity keeps its actuals; under Retained Logic it also passes on a date."""
        self.early_start[code], self.early_finish[code] = self.finished_dates(code)
        actual_start = self.inputs[code].get("act_start_date")
        # An SS or SF link from a level of effort, or from a task not yet started under Progress Override
        # or Actual Dates, reads this start; without an actual start it is the data date. A task under
        # Retained Logic reads the carried date below instead (retained_bound). No Oracle page describes
        # the case; not measured in P6.
        self.remaining_start[code] = actual_start if pd.notna(actual_start) else self.data_date
        if self.retain:
            self.carry[code] = max([self.data_date] + [bound for _, bound in self.pred_bounds(code, started=False)])

    def finished_dates(self, code) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Start and finish a finished activity is placed at: its actual dates. With one of them missing
        it takes the other, with both missing the data date, and a warning says so: a status without its
        dates, met in files other tools produce; no Oracle page describes it."""
        actual_start = self.inputs[code].get("act_start_date")
        actual_finish = self.inputs[code].get("act_end_date")
        if pd.notna(actual_start) and pd.notna(actual_finish):
            return actual_start, actual_finish
        self.warnings.append(f"{code}: complete without actual dates")
        if pd.notna(actual_start):
            return actual_start, actual_start
        if pd.notna(actual_finish):
            return actual_finish, actual_finish
        return self.data_date, self.data_date

    def forward_constraints(self, code, started: bool) -> tuple[tuple[str, pd.Timestamp] | None, list, list]:
        """The mandatory date of the activity if any (its end, the date), and the bounds its other
        constraints give to its early start and to its early finish.

        Work under way keeps its actual start, so its constraints are not applied here, only reported.

        An expected finish in force on work not started drops the early side of a Finish On and a
        Finish On or After: the work finishes at its expected finish (P6 23.12.1: probes oc-edges-xc
        N5, N7, xf-mandatory M7; 26.8 not measured). Their late side stays in the backward pass.
        """
        pinned = None
        start_bounds: list[pd.Timestamp] = []
        finish_bounds: list[pd.Timestamp] = []
        if started and self.constraints(code):
            self.unapplied.append(code)
        for constraint_type, date in [] if started else self.constraints(code):
            if constraint_type in MANDATORY:
                pinned = (MANDATORY[constraint_type], date)
            elif START_LIKE.get(constraint_type) == "start":
                start_bounds.append(date)
            elif START_LIKE.get(constraint_type) == "finish" and not self.has_expected_finish(code):
                finish_bounds.append(date)
        return pinned, start_bounds, finish_bounds

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
        the early dates (``duration_override``).

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
            duration_minutes = self.base_minutes(code, assignment) + extra_minutes
            assignment_start = self.lagged_start(assignment, lower_start)
            if self.is_expected_finish_applied(expected_date, assignment_start, finish_bound):
                # the expected finish sets the remaining work, measured on the resource
                # calendar from this placement (H26-11 A1090: 35.5 h from Tue 06:00, then
                # run from the activity's Tue 07:00 to Fri 06:30); an expected finish before
                # the placement keeps the file's remaining duration (H14-05 A1040), and an
                # FF / SF bound later than it wins, as for task-dependent work
                duration_minutes = float(assignment.axis.between(assignment_start, expected_date))
                expected_applies = True
            durations[assignment.taskrsrc_id] = duration_minutes
            self.assignment_minutes[assignment.taskrsrc_id] = duration_minutes
            starts.append(self.activity_start_given_by(assignment, assignment_start, duration_minutes, finish_bound))
        start = axis.snap_start(min(starts))
        finishes = []
        for assignment in self.driving(code):
            assignment_start = self.lagged_start(assignment, start)
            assignment_finish = self.finish_run_from(assignment, assignment_start, durations[assignment.taskrsrc_id])
            self.assignment_early[assignment.taskrsrc_id] = (assignment_start, assignment_finish)
            finishes.append(assignment_finish)
        if expected_applies:
            self.duration_override[code] = float(axis.between(start, max(finishes)))  # the backward pass follows
        return start, max(finishes)

    def lagged_start(self, assignment: _Asg, measured_from: pd.Timestamp) -> pd.Timestamp:
        """Start of an assignment placed from an instant: shifted by its lag, on its calendar."""
        return assignment.axis.snap_start(self.shift(assignment.axis, measured_from, assignment.lag_minutes))

    @staticmethod
    def finish_run_from(assignment: _Asg, assignment_start: pd.Timestamp, duration_minutes: float) -> pd.Timestamp:
        """Finish of an assignment that works its duration from a start, on its calendar; the start itself
        when no work is left."""
        if not duration_minutes:
            return assignment_start
        return assignment.axis.add(assignment_start, duration_minutes, finish=True)

    @staticmethod
    def is_expected_finish_applied(
        expected_date: pd.Timestamp | None, assignment_start: pd.Timestamp, finish_bound: pd.Timestamp | None
    ) -> bool:
        """True when the expected finish sets the remaining work of an assignment: there is one, after
        the assignment's start and not before the finish bound."""
        return (
            expected_date is not None
            and expected_date > assignment_start
            and (finish_bound is None or expected_date >= finish_bound)
        )

    def activity_start_given_by(
        self,
        assignment: _Asg,
        assignment_start: pd.Timestamp,
        duration_minutes: float,
        finish_bound: pd.Timestamp | None,
    ) -> pd.Timestamp:
        """Start one driving assignment gives the activity: the assignment's start less its lag. An
        assignment that would finish before the finish bound is first moved to finish at the bound, or
        at the next working time of its calendar, and starts its duration before; with no work left, it
        starts at that finish."""
        assignment_finish = self.finish_run_from(assignment, assignment_start, duration_minutes)
        if finish_bound is not None and assignment_finish < finish_bound:
            assignment_finish = assignment.axis.keep_or_next(finish_bound)
            assignment_start = assignment_finish
            if duration_minutes:
                assignment_start = assignment.axis.add(assignment_finish, -duration_minutes, finish=False)
        return self.shift(assignment.axis, assignment_start, -assignment.lag_minutes)

    # --- backward pass -------------------------------------------------------------------------
    def successor_limits(self, code, late: bool) -> tuple[list, list]:
        """Latest start / finish ``c`` may have against its successors' late (or early) dates."""
        late_start_bounds: list[pd.Timestamp] = []
        late_finish_bounds: list[pd.Timestamp] = []
        for successor, link_type, lag in self.succs[code]:
            if self.is_binding_successor(code, successor, link_type, late):
                bound = self.successor_limit(code, successor, link_type, lag, late)
                (late_finish_bounds if link_type in ("FS", "FF") else late_start_bounds).append(bound)
        return late_start_bounds, late_finish_bounds

    def is_binding_successor(self, code, successor, link_type: str, late: bool) -> bool:
        """False for the links that give ``code`` no latest date: the ones Progress Override releases,
        and a finished successor outside Retained Logic, unless its actual dates are read."""
        status = self.status
        progress_override = self.options.progressed == "progress_override"
        if progress_override and status[successor] == "TK_Active" and link_type in ("FS", "SS"):
            # Progress Override: a started successor's start is an actual, so a link to it
            # binds no late date; links to its finish (FF, SF) still do (H5-06 A1030
            # against H3-03 A1030)
            return False
        is_start_link_or_done = link_type in ("SS", "SF") or status[successor] == "TK_Complete"
        if not late and progress_override and status[code] == "TK_Active" and is_start_link_or_done:
            # Progress Override again: the free float of work under way runs past its own
            # start-type links (its start is an actual too) and past finished successors,
            # to whatever is left (H2-05 A1030, H2-04 A1110; counter-examples H4-08
            # A1010, H12-07 A1120 are open, see docs/backlog.md)
            return False
        if status[successor] == "TK_Complete" and not self.retain:
            return self.reads_actual_dates(successor, late)
        return True

    def reads_actual_dates(self, successor, late: bool) -> bool:
        """Actual Dates: the backward pass uses the actual dates of a successor that has started."""
        return (
            late
            and self.options.progressed == "actual_dates"
            and self.status[successor] != "TK_NotStart"
            and pd.notna(self.inputs[successor].get("act_start_date"))
        )

    def successor_limit(self, code, successor, link_type: str, lag: float, late: bool) -> pd.Timestamp:
        """Latest date one binding link allows: the successor's date the link reads, less the lag."""
        if late and self.retain and self.status[successor] == "TK_Complete":
            return self.carried_late_limit(code, successor, link_type, lag)
        successor_start, successor_finish = self.successor_dates(successor, late)
        link_axis = self.lag_axis(code, successor)
        read_date = successor_start if link_type in ("FS", "SS") else successor_finish
        return self.shift(link_axis, read_date, -self.lag_to_take_back(code, link_type, lag, link_axis))

    def carried_late_limit(self, code, successor, link_type: str, lag: float) -> pd.Timestamp:
        """Late date a finished successor passes back under Retained Logic.

        The late date its own successors give it, less this link's lag: in full for FS / FF (it
        runs from a finish still to come: H1-08 A1020), the part not yet expired since the actual
        start for SS / SF (H6-07 A1030), a lead from started work not at all; between two finished
        activities only the carried date passes (H1-08 A1050). MPXJ drops the FS lag; P6 does not.
        """
        carried_late = self.lcarry[successor]
        if self.status[code] == "TK_Complete":
            return carried_late
        link_axis = self.lag_axis(code, successor)
        return self.shift(link_axis, carried_late, -self.lag_to_take_back(code, link_type, lag, link_axis))

    def successor_dates(self, successor, late: bool) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Start and finish of a successor a link is measured from: its late dates in the backward
        pass, its early ones for the free float."""
        if self.reads_actual_dates(successor, late):
            # the finish of a finished successor as finished_dates placed it: its actual finish, or its
            # actual start when the file gives no finish
            successor_finish = (
                self.early_finish[successor] if self.status[successor] == "TK_Complete" else self.late_finish[successor]
            )
            return self.inputs[successor].get("act_start_date"), successor_finish
        if self.status[successor] == "TK_Complete" and not late and self.retain:
            # free float against a finished successor: it sits at its carried date
            return self.carry[successor], self.carry[successor]
        if late:
            return self.late_start[successor], self.late_finish[successor]
        return self.remaining_start[successor], self.early_finish[successor]

    def lag_to_take_back(self, code, link_type: str, lag: float, link_axis: TimeAxis) -> float:
        """Lag of a link out of ``code`` that still separates it from its successor."""
        if self.status[code] == "TK_Complete":
            # finished (Retained Logic, see lcarry): only the lag not yet expired since its
            # actual finish (FS, FF) or start (SS, SF) still counts; a lead is dropped (MPXJ)
            measured_from = self.inputs[code].get("act_end_date" if link_type in ("FS", "FF") else "act_start_date")
            done_lag = (
                max(0, link_axis.between(measured_from, self.data_date))
                if measured_from is not None and pd.notna(measured_from)
                else 0
            )
            return max(0.0, lag - done_lag) if lag > 0 else 0.0
        if link_type in ("FS", "FF"):
            return lag
        if lag < 0 and self.status[code] == "TK_Active":
            return 0.0  # a lead from work already started no longer pulls it earlier (MPXJ)
        # SS / SF from a started activity: the forward pass only waits for the lag not
        # yet expired, so the backward pass mirrors that, or a driving link would leave
        # negative float on an unconstrained network.
        return self.unexpired(code, link_axis, lag)

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
            assignment_start, assignment_finish, is_driven = self.assignment_late_dates(
                code, assignment, upper_start, upper_finish
            )
            driven = driven or is_driven
            self.assignment_late[assignment.taskrsrc_id] = (assignment_start, assignment_finish)
            starts.append(self.shift(assignment.axis, assignment_start, -assignment.lag_minutes))
            finishes.append(assignment_finish)
        start = min(starts)
        if driven and start == upper_start and not alap:
            # written at the bound's instant, as a late date from an SS bound is on
            # task-dependent work (H26-04 A1440: late start Wed 16:00, not Thu 08:00)
            start = axis.keep_or_previous(min(late_start_bounds))
        return start, max(finishes)

    def assignment_late_dates(
        self, code, assignment: _Asg, upper_start: pd.Timestamp | None, upper_finish: pd.Timestamp | None
    ) -> tuple[pd.Timestamp | None, pd.Timestamp | None, bool]:
        """Latest start and finish of one driving assignment on its resource calendar, and whether the
        start bound placed it with no assignment lag (the activity's late start is then that bound).

        The assignment runs back from the finish bound; the start bound, moved by the assignment
        lag, takes over when it is earlier or when there is no finish bound.
        """
        duration = self.assignment_minutes.get(
            assignment.taskrsrc_id, self.base_minutes(code, assignment) + self.extra_hours.get(code, 0.0) * 60
        )
        start = finish = None
        if upper_finish is not None:
            finish = assignment.axis.snap_finish(upper_finish)
            start = assignment.axis.add(finish, -duration, finish=False) if duration else finish
        if upper_start is None:
            return start, finish, False
        candidate = assignment.axis.snap_start(self.shift(assignment.axis, upper_start, assignment.lag_minutes))
        if start is None or candidate < start:
            finish = assignment.axis.add(candidate, duration, finish=True) if duration else candidate
            return candidate, finish, assignment.lag_minutes == 0
        return start, finish, False

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
        end_anchor = self.options.must_finish_by if self.options.must_finish_by is not None else self.finish
        for code in reversed(self.order):
            if self.status[code] == "TK_Complete":
                if self.retain:
                    late_start_bounds, late_finish_bounds = self.successor_limits(code, late=True)
                    self.lcarry[code] = min(late_start_bounds + late_finish_bounds + [end_anchor])
                continue
            late_start_bounds, late_finish_bounds = self.late_bounds(code, end_anchor)
            self.late_start[code], self.late_finish[code] = self.place_late(
                code, self.cal_ax[code], self.kind(code), self.dur_min(code), late_start_bounds, late_finish_bounds
            )

    def late_bounds(self, code, end_anchor: pd.Timestamp) -> tuple[list, list]:
        """Latest dates an open activity may start at and finish at ("not after" bounds): what follows
        it and the project end, then its constraints; a mandatory date replaces them, except under a
        Mandatory Finish with an expected finish in force: the late finish is then the lesser of the
        successors' bound and the date."""
        following_start_bounds, following_finish_bounds = self.bounds_of_what_follows(code, end_anchor)
        pinned, constraint_start_bounds, constraint_finish_bounds = self.late_constraints(code)
        if pinned is None:
            return (
                following_start_bounds + constraint_start_bounds,
                following_finish_bounds + constraint_finish_bounds,
            )
        end, date = pinned
        # a second constraint of the same end tighter than the mandatory date still
        # holds (H23-08 A1220: Finish On or Before four days before the Mandatory
        # Finish is the late finish); under a Mandatory Start, so does a finish date in the
        # second slot (H26-08 A1280: the late finish is the second date, the late start follows).
        # Not measured: a start date in the second slot under a primary Mandatory Finish (no corpus
        # or probe activity has it); it bounds nothing here, as before
        if end == "start":
            return [min([date] + constraint_start_bounds)], constraint_finish_bounds
        if self.has_expected_finish(code):
            # With an expected finish in force the Mandatory Finish date no longer pins work not
            # started, whether or not the expected finish sets the duration: the late finish is
            # the lesser of what the successors allow and the date. P6 23.12.1 (26.8 not
            # measured): probes xf-mandatory M1, M3, M9, M11, F3; held-out corpus H29-02 A1160,
            # H29-05 A1110, H29-11 A1230, H25-05 A1150 (resource-dependent), H23-07 A1250 (finish
            # milestone), H25-02 A1240 (an FF bound later than the expected finish). Not
            # measured: an expected finish after the date for a milestone, a start milestone, a
            # secondary constraint. Work under way never gets here (late_constraints)
            return following_start_bounds, following_finish_bounds + [date]
        return [], [min([date] + constraint_finish_bounds)]

    def bounds_of_what_follows(self, code, end_anchor: pd.Timestamp) -> tuple[list, list]:
        """Bounds the successors give, the project end and the late date a link to another project gives."""
        late_start_bounds, late_finish_bounds = self.successor_limits(code, late=True)
        if not late_start_bounds and not late_finish_bounds:
            # "Make open-ended activities critical": the late finish of an activity
            # without any successor link is its early finish, never past the project's
            # Must Finish By (H25-05 A1380); one whose successors bind nothing (finished,
            # a WBS summary) is not open-ended and ends at the project's end (H27-04 A1390)
            open_end = code not in self.linked_on
            late_finish_bounds.append(
                min(self.early_finish[code], end_anchor) if self.options.open_critical and open_end else end_anchor
            )
        else:
            # No late finish after the project's: an activity whose successors only bound
            # its start (SS, SF) would otherwise float past the end, and so would its
            # predecessors. MPXJ's PrimaveraScheduler caps it the same way; no P6 file at
            # hand covers the case (tests/test_crosscheck_mpxj.py).
            late_finish_bounds.append(end_anchor)
        external_date = self.inputs[code].get("external_late_end_date")
        if self.options.honor_external and external_date is not None and pd.notna(external_date):
            late_finish_bounds.append(pd.Timestamp(external_date))
            self.external.add(code)
        return late_start_bounds, late_finish_bounds

    def late_constraints(self, code) -> tuple[tuple[str, pd.Timestamp] | None, list, list]:
        """The mandatory date of the activity if any (its end, the date), and the bounds its other
        constraints give to its late start and to its late finish.

        Work under way has no mandatory date in the backward pass: P6 23.12.1 gives it the late dates
        of the network (probes oc-edges-xc U3, U6; held-out corpus H3-02 A1050, H8-06 A1010). 26.8
        not measured.
        """
        pinned = None
        start_bounds: list[pd.Timestamp] = []
        finish_bounds: list[pd.Timestamp] = []
        started = self.status[code] == "TK_Active"
        if started and self.is_late_side_dropped(code):
            return pinned, start_bounds, finish_bounds
        for constraint_type, date in self.constraints(code):
            if constraint_type in MANDATORY and not started:
                pinned = (MANDATORY[constraint_type], date)
            elif LATE_LIKE.get(constraint_type) == "start" and not started:
                start_bounds.append(date)
            elif LATE_LIKE.get(constraint_type) == "finish":
                finish_bounds.append(date)
        return pinned, start_bounds, finish_bounds

    def is_late_side_dropped(self, code) -> bool:
        """Whether work under way loses both its constraints on the late side: a Start On or Before, a
        Mandatory Start or a Mandatory Finish in either slot. P6 23.12.1 on the probes h1-situations
        (P7, P10, P14, K10: a Finish On or Before beside one of them is dropped too; beside a Start On or
        After or a Start On it holds, P8, P9) and h27-causes (KB1-KB5: a Finish On or Before and a
        Mandatory Finish in either order; KB6, KB7 each alone). 26.8 not measured. Not measured: a
        Finish On beside a Mandatory Finish; it is dropped here as the rule is stated."""
        return any(constraint_type in DROPS_LATE_SIDE_UNDER_WAY for constraint_type, _ in self.constraints(code))

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
        for code in reversed(self.open_):
            axis = self.cal_ax[code]
            start_limits, finish_limits = self.successor_limits(code, late=False)
            if self.is_as_late_as_possible(code):
                if not start_limits and not finish_limits:
                    finish_limits = [self.finish]
                self.move_to_late_dates(code, axis, start_limits, finish_limits)
            self.free_float_hr[code] = self.free_float(code, axis, start_limits, finish_limits)
            self.total_float_hr[code] = self.total_float(code, axis)

    def is_as_late_as_possible(self, code) -> bool:
        """As Late As Possible moves the remaining work of started activities too
        (H27-05 A1170: in progress, remaining 3 h, placed at its late dates)."""
        return "CS_ALAP" in (self.inputs[code].get("cstr_type"), self.inputs[code].get("cstr_type2"))

    def move_to_late_dates(self, code, axis, start_limits: list, finish_limits: list) -> None:
        """Early dates of an "as late as possible" activity, moved to the latest its successors' early
        dates allow, when that is later; its driving assignments follow. The late dates of the backward
        pass are left as they were."""
        keep = dict(self.assignment_late)
        placed_start, placed_finish = self.place_late(
            code, axis, self.kind(code), self.dur_min(code), start_limits, finish_limits, alap=True
        )
        if placed_finish > self.early_finish[code]:
            self.early_finish[code], self.remaining_start[code] = placed_finish, placed_start
            if self.status[code] == "TK_NotStart":
                self.early_start[code] = placed_start
            for assignment in self.driving(code) if code in self.rsrc_dep else []:
                self.assignment_early[assignment.taskrsrc_id] = self.assignment_late[assignment.taskrsrc_id]
        self.assignment_late.clear()
        self.assignment_late.update(keep)

    def free_float(self, code, axis, start_limits: list, finish_limits: list) -> float:
        """Hours the activity can slip before the first successor moves, on the activity's calendar."""
        gaps = [axis.between(self.early_finish[code], limit) / 60 for limit in finish_limits] + [
            axis.between(self.remaining_start[code], limit) / 60 for limit in start_limits
        ]
        # open end: free float runs to the project's early finish, not to "must finish by"
        free_float_hr = (
            max(0.0, min(gaps)) if gaps else max(0.0, axis.between(self.early_finish[code], self.finish) / 60)
        )
        if self.has_expected_finish(code) or self.is_unstarted_under_mandatory(code):
            # P6 23.12.1 gives no free float to an activity with an expected finish in force,
            # whether or not it sets the duration (held-out corpus: 707 of 707; H1-08 A1090,
            # H5-01 A1120), nor to unstarted work under a primary Mandatory Start / Finish
            # (508 of 508; probes: 76 of 76, e.g. oc-edges-xc E14). Observed, not explained;
            # 26.8 not measured.
            return 0.0
        return free_float_hr

    def is_unstarted_under_mandatory(self, code) -> bool:
        """True for work not started whose primary constraint is a dated Mandatory Start / Finish."""
        primary_type, primary_date = self.inputs[code].get("cstr_type"), self.inputs[code].get("cstr_date")
        return self.status[code] == "TK_NotStart" and primary_type in MANDATORY and pd.notna(primary_date)

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
        for code in self.loe_codes:
            if self.status[code] == "TK_Complete":
                self.early_start[code], self.early_finish[code] = self.finished_dates(code)
                continue
            self.record_loe_early_dates(code)
            self.record_loe_late_dates(code)

    def record_loe_early_dates(self, code) -> None:
        """Keep the early dates of an unfinished LOE: from the earliest start it is tied to, never before
        the data date, to the latest finish it is tied to; under way, it shows its actual start, when the
        file gives one, and its remaining start is the data date."""
        axis = self.cal_ax[code]
        tied_starts, tied_finishes = self.early_dates_tied_to(code)
        is_active = self.status[code] == "TK_Active"
        actual_start = self.inputs[code].get("act_start_date") if is_active else None
        if is_active and pd.isna(actual_start):
            # as a task under way without an actual start (record_early): it starts with what it is tied to
            self.warnings.append(f"{code}: in progress without an actual start")
        if pd.notna(actual_start):
            loe_start = actual_start
        elif tied_starts:
            loe_start = axis.snap_start(max(self.data_date, min(tied_starts)))
        else:
            loe_start = axis.snap_start(self.data_date)
        loe_finish = self.loe_early_finish(axis, tied_finishes, loe_start)
        earliest_finish = axis.snap_start(max(loe_start, self.data_date))
        self.early_start[code], self.early_finish[code] = loe_start, max(loe_finish, earliest_finish)
        self.remaining_start[code] = axis.snap_start(self.data_date) if is_active else loe_start

    def loe_early_finish(
        self, axis: TimeAxis, tied_finishes: list[pd.Timestamp], loe_start: pd.Timestamp
    ) -> pd.Timestamp:
        """Early finish of an LOE before the data date is applied: the latest finish it is tied to; tied
        to none, the project finish; and its own start when the project has no finish."""
        if tied_finishes:
            return axis.snap_finish(max(tied_finishes))
        if self.finish is not None:
            return axis.snap_finish(self.finish)
        return loe_start

    def early_dates_tied_to(self, code) -> tuple[list[pd.Timestamp], list[pd.Timestamp]]:
        """Early dates the relationships of an LOE give to its start, and those they give to its finish."""
        tied_starts: list[pd.Timestamp] = []
        tied_finishes: list[pd.Timestamp] = []
        for predecessor, link_type, lag in self.loe_preds[code]:
            tied_date = self.early_date_through_predecessor(predecessor, code, link_type, lag)
            (tied_starts if link_type in LOE_START_FROM_PREDECESSOR else tied_finishes).append(tied_date)
        for successor, link_type, lag in self.loe_succs[code]:
            tied_date = self.early_date_through_successor(code, successor, link_type, lag)
            (tied_starts if link_type in LOE_START_FROM_SUCCESSOR else tied_finishes).append(tied_date)
        return tied_starts, tied_finishes

    def early_date_through_predecessor(self, predecessor: str, code: str, link_type: str, lag: float) -> pd.Timestamp:
        """Early date a predecessor gives to the LOE ``code``: its remaining start (SS, SF) or its early
        finish (FS, FF) plus the lag; from work under way, an SS or SF link runs from the data date."""
        link_axis = self.lag_axis(predecessor, code)
        if link_type in ("SS", "SF") and self.status[predecessor] == "TK_Active":
            # from the data date plus the unexpired lag (H10-01 A1300, H12-08 A1290)
            return self.shift(link_axis, self.data_date, self.unexpired(predecessor, link_axis, lag))
        measured_from = (
            self.remaining_start[predecessor] if link_type in ("SS", "SF") else self.early_finish[predecessor]
        )
        return self.shift(link_axis, measured_from, lag)

    def early_date_through_successor(self, code: str, successor: str, link_type: str, lag: float) -> pd.Timestamp:
        """Early date a successor gives to the LOE ``code``: its remaining start (SS, FS) or its early
        finish (FF, SF), less the lag."""
        measured_to = self.remaining_start[successor] if link_type in ("SS", "FS") else self.early_finish[successor]
        return self.shift(self.lag_axis(code, successor), measured_to, -lag)

    def record_loe_late_dates(self, code) -> None:
        """Keep the late dates and the floats of an unfinished LOE: to the latest late finish it is tied
        to, or the project finish; from the earliest late start it is tied to, or its late finish."""
        axis = self.cal_ax[code]
        tied_late_starts, tied_late_finishes = self.late_dates_tied_to(code)
        open_end = axis.snap_finish(self.finish) if self.finish is not None else self.early_finish[code]
        late_finish = axis.snap_finish(max(tied_late_finishes)) if tied_late_finishes else open_end
        late_start = late_finish
        if tied_late_starts:
            # never after the late finish (H10-01 A1300)
            late_start = min(axis.snap_start(min(tied_late_starts)), late_finish)
        self.late_start[code], self.late_finish[code] = late_start, late_finish
        self.total_float_hr[code] = self.total_float(code, axis)
        self.free_float_hr[code] = 0.0

    def late_dates_tied_to(self, code) -> tuple[list[pd.Timestamp], list[pd.Timestamp]]:
        """Late dates the relationships of an LOE give to its start, and those they give to its finish.
        A finished successor gives none."""
        tied_late_starts: list[pd.Timestamp] = []
        tied_late_finishes: list[pd.Timestamp] = []
        for predecessor, link_type, lag in self.loe_preds[code]:
            if self.status[predecessor] == "TK_Complete":
                tied_late_starts.extend(
                    self.late_starts_through_finished_predecessor(predecessor, code, link_type, lag)
                )
                continue
            measured_from = self.late_start[predecessor] if link_type in ("SS", "SF") else self.late_finish[predecessor]
            tied_date = self.shift(self.lag_axis(predecessor, code), measured_from, lag)
            (tied_late_starts if link_type in LOE_START_FROM_PREDECESSOR else tied_late_finishes).append(tied_date)
        for successor, link_type, lag in self.loe_succs[code]:
            if self.status[successor] == "TK_Complete":
                continue
            measured_to = self.late_start[successor] if link_type in ("SS", "FS") else self.late_finish[successor]
            tied_date = self.shift(self.lag_axis(code, successor), measured_to, -lag)
            (tied_late_starts if link_type in LOE_START_FROM_SUCCESSOR else tied_late_finishes).append(tied_date)
        return tied_late_starts, tied_late_finishes

    def late_starts_through_finished_predecessor(
        self, predecessor: str, code: str, link_type: str, lag: float
    ) -> list[pd.Timestamp]:
        """Late start a finished predecessor gives to the LOE ``code``, in a list, empty when it gives
        none: through an SS link, the late date it passes back (``lcarry``) plus the lag; through an FS
        link from a task, its actual finish plus the lag."""
        if link_type == "SS" and predecessor in self.lcarry:
            return [self.shift(self.lag_axis(predecessor, code), self.lcarry[predecessor], lag)]
        if link_type == "FS" and self.kind(predecessor) == "task":
            actual_finish = self.inputs[predecessor].get("act_end_date")
            if actual_finish is not None and not pd.isna(actual_finish):
                return [self.shift(self.lag_axis(predecessor, code), actual_finish, lag)]
        return []

    # --- longest path ------------------------------------------------------------------------
    def _ends_project(self, code, enders: list[str]) -> bool:
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
        pending = self.longest_path_ends()
        while pending:
            code = pending.pop()
            if code in longest:
                continue
            longest.add(code)
            pending.extend(self.driving_predecessors(code))
        # A level-of-effort activity is on the path when one of its links into a longest-path
        # activity drives that activity's date (P6 20.12 export: LOE spanning two activities
        # of the path, SS from the first, FF into the second, flagged). Its own dates come from
        # its links, so the trace stops there.
        for loe in self.loe_codes:
            if self.is_loe_driving_one_of(loe, longest):
                longest.add(loe)
        return longest

    def longest_path_ends(self) -> list[str]:
        """Unfinished activities that finish at the project finish: where the trace starts."""
        # the activities whose early finish is the project finish, found once per trace
        enders = [code for code in self.nodes if self.early_finish[code] == self.finish]
        return [code for code in self.open_ if self._ends_project(code, enders)]

    def driving_predecessors(self, code) -> list[str]:
        """Unfinished predecessors whose link drives a date of ``code``. Work under way has none under
        Progress Override: its logic is ignored."""
        if self.status[code] == "TK_Active" and self.options.progressed == "progress_override":
            return []
        driving = []
        for predecessor, link_type, lag in self.preds[code]:
            if self.status[predecessor] == "TK_Complete":
                continue
            bound = self.early_bound_through(predecessor, code, link_type, lag)
            if self.is_driven_by(code, link_type, bound):
                driving.append(predecessor)
        return driving

    def early_bound_through(self, predecessor: str, code: str, link_type: str, lag: float) -> pd.Timestamp:
        """Earliest date a link from an unfinished predecessor allows ``code``: the predecessor's early
        finish (FS, FF) or the start an SS or SF link is measured from, plus the lag."""
        link_axis = self.lag_axis(predecessor, code)
        if link_type in ("FS", "FF"):
            return self.shift(link_axis, self.early_finish[predecessor], lag)
        predecessor_start, predecessor_lag = self.start_link(predecessor, link_axis, lag)
        return self.shift(link_axis, predecessor_start, predecessor_lag)

    def is_driven_by(self, code, link_type: str, bound: pd.Timestamp) -> bool:
        """True when the date a link allows is not before the date of ``code`` it bounds, its remaining
        start (FS, SS) or its early finish (FF, SF), in working time of its calendar."""
        own_instant = self.remaining_start[code] if link_type in ("FS", "SS") else self.early_finish[code]
        axis = self.cal_ax[code]
        return axis.work(bound) >= axis.work(own_instant)

    def is_loe_driving_one_of(self, loe, longest: set[str]) -> bool:
        """True when a link from the unfinished LOE drives a date of one of the ``longest`` activities."""
        if self.status[loe] == "TK_Complete" or loe not in self.early_finish:
            return False
        for successor, link_type, lag in self.loe_succs[loe]:
            if successor not in longest:
                continue
            link_axis = self.lag_axis(loe, successor)
            measured_from = self.early_finish[loe] if link_type in ("FS", "FF") else self.remaining_start[loe]
            bound = self.shift(link_axis, measured_from, lag)
            if self.is_driven_by(successor, link_type, bound):
                return True
        return False

    # --- assignment dates --------------------------------------------------------------------
    def assignment_dates(self) -> pd.DataFrame:
        """Task dependent: the activity's remaining dates + assignment lag, for the assignment's
        own duration (units / units per hour) on the activity calendar. Checked against every
        assignment P6 stored in Hotel and Terminal (tests/test_cpm.py)."""
        rows = []
        for code, assignments in self.assignments_by_task.items():
            if code not in self.remaining_start or code not in self.late_start:
                continue
            for assignment in assignments:
                dates = self.early_and_late_dates(code, assignment)
                rows.append([assignment.taskrsrc_id, code, assignment.rsrc, assignment.driving, *dates])
        return pd.DataFrame(rows, columns=ASSIGNMENT_COLS)

    def early_and_late_dates(
        self, code: str, assignment: _Asg
    ) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp | None, pd.Timestamp | None]:
        """Remaining early start and finish, late start and finish of an assignment: those the forward
        pass placed for a driving assignment of resource-dependent work, with the late dates of the
        backward pass (none when it placed none), else those it takes from the activity."""
        if assignment.taskrsrc_id not in self.assignment_early:
            return self.dates_from_activity(code, assignment)
        assignment_start, assignment_finish = self.assignment_early[assignment.taskrsrc_id]
        late_assignment_start, late_assignment_finish = self.assignment_late.get(assignment.taskrsrc_id, (None, None))
        return assignment_start, assignment_finish, late_assignment_start, late_assignment_finish

    def dates_from_activity(
        self, code: str, assignment: _Asg
    ) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp | None, pd.Timestamp | None]:
        """Remaining early start and finish, late start and finish of an assignment the passes did not
        place: from the activity's remaining start and late start plus its lag, for its own duration, or
        the activity's when it has none."""
        duration_minutes = (
            assignment.duration_minutes if assignment.duration_minutes is not None else self.dur_min(code)
        )
        assignment_start = self.lagged_start(assignment, self.remaining_start[code])
        assignment_finish = self.finish_run_from(assignment, assignment_start, duration_minutes)
        late_start_after_lag = self.shift(assignment.axis, self.late_start[code], assignment.lag_minutes)
        # no work left: the late dates stay at the period end, as the task's (_late)
        late_assignment_start = (
            late_start_after_lag if not duration_minutes else assignment.axis.snap_start(late_start_after_lag)
        )
        late_assignment_finish = self.finish_run_from(assignment, late_assignment_start, duration_minutes)
        return assignment_start, assignment_finish, late_assignment_start, late_assignment_finish

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
                "tf_hr": self.total_float_hr.get(code, float("nan")),  # NaN: finished, no float
                "ff_hr": self.free_float_hr.get(code, float("nan")),
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
        frame = pd.DataFrame(rows, columns=RESULT_COLS).set_index("task_code")  # no row: an empty Schedule
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


def _bounded(hours) -> bool:
    """Finite and within ``MAX_HOURS`` in absolute value; element-wise on a Series."""
    if isinstance(hours, pd.Series):
        return hours.map(_bounded).astype(bool)
    return math.isfinite(hours) and abs(hours) <= MAX_HOURS


def _window_minutes(row, axis: TimeAxis) -> float | None:
    """Working minutes, on the assignment's calendar, from its remaining start to its remaining
    finish; None when a date is missing or the finish is not after the start."""
    start, finish = row.restart_date, row.reend_date
    if pd.isna(start) or pd.isna(finish) or finish <= start:
        return None
    return float(axis.between(start, finish))


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

    Against the plain recalculation (``recomputed`` None or ``schedule(snapshot)``, ``plain``) the
    table is cached on the snapshot, as ``schedule`` is: INT-01 and the Debug page share it. Each
    call returns its own copy.
    """
    plain = schedule(snapshot) if recomputed is None else recomputed
    if not plain.plain:
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


def _schedule_failure(error: ScheduleError, delayed: str | None = None) -> CptResult:
    return CptResult(False, str(error), delayed)


@dataclass
class _DelayOutcome:
    """What a delay on ``code`` did to the project's finish: the measures the verdict and its note read."""

    code: str
    delay_days: float
    hours_per_day: float  # of the delayed activity's calendar
    base_finish: pd.Timestamp  # latest early finish of the end points, plain schedule
    delayed_finish: pd.Timestamp  # the same, delayed schedule
    shift_hr: float  # from one finish to the other, working hours of the delayed activity's calendar
    own_move: pd.Timedelta  # how far the delayed activity's own finish moved
    end_move: pd.Timedelta  # how far the project's finish moved
    is_reached: bool  # the end points that finish the plain schedule moved
    shortened_hr: pd.Series  # task_code -> remaining hours an expected finish gave up (the delayed activity apart)

    @property
    def delay_hr(self) -> float:
        return self.delay_days * self.hours_per_day

    @property
    def is_whole(self) -> bool:
        """The finish moved by the whole delay.

        Measured on the delayed activity's calendar. It can move further when the path crosses
        calendars with other non-working days; it can also read less for the same reason (the
        window of the move holds non-working days of that calendar the downstream path does not
        observe), so the proportion is also read in calendar days: the finish must move at least
        as much as the delayed activity's own finish did.
        """
        return self.shift_hr >= self.delay_hr - 1e-6 or self.end_move >= self.own_move

    @property
    def passed(self) -> bool:
        """The whole delay arrived, or part of it did and nothing stopped the rest.

        Less than the whole on both readings is not a failure by itself: PAM 200.1 §4.12 reads its
        proportion "assuming zero float", and the delayed activity may have float on its own finish
        (it can be on the longest path by its start alone), or the path may cross calendars. A
        delay that stops on the way is: the end points that finish the plain schedule do not move,
        or an expected finish downstream gives up remaining duration (to 0 once pushed past that
        date: the shortening is the absorption).
        """
        return self.is_whole or (self.is_reached and self.shortened_hr.empty)


def _first_open_on_longest_path(activities: pd.DataFrame, frame: pd.DataFrame) -> pd.Series | None:
    """Open activity of the longest path that starts first (the lowest Activity ID among equals), or None.

    The critical path = the longest path of the recalculated schedule (with negative float,
    "total float <= 0" would also take in less critical paths). Milestones and level of effort
    are not delayed.
    """
    open_ = activities[
        ~activities["is_complete"] & ~activities["is_loe"] & ~activities["is_milestone"]
    ].drop_duplicates("task_code")
    critical_path = open_[open_["task_code"].map(frame["longest_path"]).fillna(False).astype(bool)]
    if critical_path.empty:
        return None
    critical_path = critical_path.assign(_rs=critical_path["task_code"].map(frame["remaining_start"]))
    return critical_path.sort_values(["_rs", "task_code"]).iloc[0]


def _end_points(snapshot: Snapshot, frame: pd.DataFrame) -> list[str]:
    """Activities no work follows.

    A level of effort is never one (P6 computes its dates from the activities it is linked to, it
    drives nothing), and a level-of-effort successor does not make its predecessor something
    other than an end.
    """
    activities, links = snapshot.activities, snapshot.relationships
    loe = set(activities.loc[activities["is_loe"].astype(bool), "task_code"])
    # built once: per activity it took 33 s on Hotel
    has_successor = set(links.loc[~links["succ_code"].isin(loe), "pred_code"])
    return [code for code in frame.index if code not in has_successor and code not in loe]


def _delay_outcome(
    snapshot: Snapshot, target: pd.Series, delay_days: float, base: Schedule, late: Schedule
) -> _DelayOutcome:
    """Measures of the move from ``base`` (plain schedule) to ``late`` (``target`` delayed)."""
    code = target["task_code"]
    end_points = _end_points(snapshot, base.frame)
    base_finish = base.frame.loc[end_points, "ef"].max()
    delayed_finish = late.frame.loc[end_points, "ef"].max()
    axis = TimeAxis(
        snapshot.calendar(target["clndr_id"]), base_finish.date(), (delayed_finish + pd.Timedelta(days=1)).date()
    )
    ends = base.frame.loc[end_points, "ef"]
    shortened = (base.frame["rem_override_hr"] - late.frame["rem_override_hr"].reindex(base.frame.index)).fillna(0)
    return _DelayOutcome(
        code=code,
        delay_days=delay_days,
        hours_per_day=float(target["hours_per_day"]),
        base_finish=base_finish,
        delayed_finish=delayed_finish,
        shift_hr=axis.between(base_finish, delayed_finish) / 60,
        own_move=late.frame.at[code, "ef"] - base.frame.at[code, "ef"],
        end_move=delayed_finish - base_finish,
        is_reached=late.frame.loc[ends.index[ends == base_finish], "ef"].max() > base_finish,
        shortened_hr=shortened[(shortened > 1e-6) & (shortened.index != code)],
    )


def _move_note(outcome: _DelayOutcome) -> str:
    """The delay asked, the finish before and after, and the move in working days."""
    return (
        f"+{outcome.delay_days:g} wd on {outcome.code}: forecast finish {outcome.base_finish:%Y-%m-%d} -> "
        f"{outcome.delayed_finish:%Y-%m-%d}, moved {outcome.shift_hr / outcome.hours_per_day:+.1f} wd"
        + ("" if outcome.passed else f" instead of {outcome.delay_days:+g}")
        + (
            " (more: the path crosses other calendars' non-working days)"
            if outcome.shift_hr > outcome.delay_hr + 1e-6
            else ""
        )
    )


def _calendar_reading(snapshot: Snapshot, outcome: _DelayOutcome) -> str:
    """What the project calendar and the calendar days read, when the finish moved fewer working days
    than the delay on the delayed activity's calendar: a calendar effect is told from an absorbed delay."""
    if not outcome.shift_hr < outcome.delay_hr - 1e-6:
        return ""
    project = snapshot.calendar()
    project_axis = TimeAxis(project, outcome.base_finish.date(), (outcome.delayed_finish + pd.Timedelta(days=1)).date())
    project_shift_wd = (
        project_axis.between(outcome.base_finish, outcome.delayed_finish)
        / 60
        / (project.hours_per_day or outcome.hours_per_day)
    )
    reading = ""
    if outcome.is_whole:
        reading = ": a calendar effect, the whole delay reached the finish"
    elif outcome.passed:
        reading = f": the delay reaches the finish, less float on {outcome.code}'s own finish or a calendar effect"
    return (
        f" ({project_shift_wd:+.1f} wd on the project calendar; {outcome.end_move.days:+d} calendar days against "
        f"{outcome.own_move.days:+d} for {outcome.code}'s own finish{reading})"
    )


def _pinned_by_a_mandatory_date(activities: pd.DataFrame) -> list[dict]:
    """Open activities with a mandatory date: only open work can absorb a delay, a finished
    activity's mandatory date is history."""
    mandatory = activities["cstr_type"].isin(MANDATORY) | activities["cstr_type2"].isin(MANDATORY)
    pinned = activities[mandatory & ~activities["is_complete"].astype(bool)]
    return [
        {**row, "reason": "mandatory date", "absorbed_wd": None}
        for row in pinned[["task_code", "task_name", "cstr_type", "cstr_type2"]].to_dict("records")
    ]


def _absorbing_expected_finishes(activities: pd.DataFrame, outcome: _DelayOutcome) -> list[dict]:
    """Activities whose expected finish gave up remaining duration, the largest cut first, in working days."""
    if outcome.shortened_hr.empty:
        return []
    names = activities.set_index("task_code")["task_name"]
    hours = activities.set_index("task_code")["hours_per_day"].astype(float)
    return [
        {
            "task_code": task, "task_name": names.get(task, ""), "cstr_type": "", "cstr_type2": "",
            "reason": "expected finish",
            "absorbed_wd": round(float(cut / hours.get(task, outcome.hours_per_day)), 1),
        }
        for task, cut in outcome.shortened_hr.sort_values(ascending=False).items()
    ]  # fmt: skip


def _what_stops_the_delay(snapshot: Snapshot, outcome: _DelayOutcome) -> tuple[list[dict], str]:
    """The activities that may hold a failed delay back, and what the note says of them."""
    links, code, note = snapshot.relationships, outcome.code, ""
    follows_the_finish = links[(links["pred_code"] == code) & links["type"].isin(["FS", "FF"])]
    if not outcome.is_reached and follows_the_finish.empty:
        note += f"; {code} has no FS or FF successor: nothing follows its finish"
    pinned = _pinned_by_a_mandatory_date(snapshot.activities)
    if pinned:
        note += f"; mandatory constraints may absorb it: {', '.join(pin['task_code'] for pin in pinned[:5])}"
    absorbing = _absorbing_expected_finishes(snapshot.activities, outcome)
    if absorbing:
        listed = ", ".join(f"{item['task_code']} ({item['absorbed_wd']:g} wd)" for item in absorbing[:5])
        note += f"; expected finish dates absorb it (remaining duration cut when pushed past them): {listed}"
    return pinned + absorbing, note


def critical_path_test(snapshot: Snapshot, delay_days: float) -> CptResult:
    """Add ``delay_days`` to the first open activity of the critical path; the delay must reach the finish.

    The finish is measured on the project's end points (activities that no activity other than a
    level of effort follows, level of effort left out), in working time of the delayed activity's
    calendar. Pass = the whole delay reached it (further is a calendar effect), or part of it did
    and nothing stopped the rest: the end points that finish the plain schedule moved and no
    expected finish downstream gave up remaining duration. The part that did not arrive is float
    on the delayed activity's own finish (it may be on the longest path by its start alone) or
    calendars on the way; the note gives the amount. Fail = those end points do not move (nothing
    follows the delayed finish, or a mandatory date or a link that binds nothing stops the delay),
    or an expected finish absorbs part of it (its activity loses its remaining duration when the
    delay pushes it past that date); the note names what it can.
    """
    try:
        base = schedule(snapshot)
    except ScheduleError as exc:  # a loop, or a duration / lag the engine cannot place
        return _schedule_failure(exc)
    target = _first_open_on_longest_path(snapshot.activities, base.frame)
    if target is None:
        return CptResult(False, "no open task on the longest path: the critical path is not defined")
    code = target["task_code"]
    delay_hours = delay_days * float(target["hours_per_day"])
    try:
        late = schedule(snapshot, {code: delay_hours}, base=base)
    except ScheduleError as exc:
        return _schedule_failure(exc, code)
    outcome = _delay_outcome(snapshot, target, delay_days, base, late)
    note = _move_note(outcome) + _calendar_reading(snapshot, outcome)
    blocking: list[dict] = []
    if not outcome.passed:
        blocking, reasons = _what_stops_the_delay(snapshot, outcome)
        note += reasons
    return CptResult(outcome.passed, note, code, outcome.shift_hr, blocking)
