"""Critical path method, as Primavera P6 (Professional 24) schedules a project.

Every date is computed on the activity's own calendar to the minute (``TimeAxis``), with
P6's conventions: a start is the beginning of a working period, a finish the end of one,
so a 1-day task starting Monday 08:00 finishes Monday 17:00 and its FS successor starts
Tuesday 08:00.

Forward pass (early dates), in topological order, for each open activity:

- start  >= data date
- FS: start  >= pred finish + lag        SS: start  >= pred start + lag
- FF: finish >= pred finish + lag        SF: finish >= pred start + lag
- lag counted on the calendar the project names (successor by default, predecessor, 24 h,
  project default)
- SS lag of a started predecessor, option "Calculate start-to-start lag from": Early Start
  (default) = the predecessor's remaining early start + the lag not yet expired (expired =
  working time from its actual start to the data date); Actual Start = its actual start +
  the full lag
- constraints: start on / on or after -> start >= date; finish on / on or after -> finish
  >= date; mandatory start / finish pin the date whatever the logic
- in progress: actual start kept; the remaining duration starts at the data date, after
  open predecessors too under Retained Logic (P6 default) and Actual Dates, ignoring them
  under Progress Override; an expected finish (if the project uses them) sets the
  remaining duration
- finished, under Retained Logic: logic passes through it (out-of-sequence progress, see
  pred_bounds); SF from started work binds nothing past the data date
- finish = start + remaining duration (minutes of the activity's calendar)
- resource dependent: each driving assignment is scheduled on its resource's calendar
  (start + assignment lag, duration = remaining units / units per hour); the activity
  runs from the earliest assignment start to the latest assignment finish

Backward pass (late dates), in reverse order: the same relationships mirrored (an SS/SF
lag that has partly expired in the forward pass is shortened the same way), started
from the project's "must finish by" date when it has one (else the latest early
finish), open ends there too (or at their own early finish if the project makes open
ends critical), and no late finish after it; finished activities pass late dates back
under Retained Logic; start on / on or before -> late start <= date; finish on / on or before
-> late finish <= date; mandatory dates pinned (early dates not before the data date).
Under Actual Dates, a started successor
bounds its predecessors by its actual dates (out-of-sequence progress gives negative
float, as Oracle warns).

Float, in working hours of the activity's calendar: total = late - early finish (P6
option "finish float", default), or start, or the smaller of the two; free = time to the
earliest successor constraint. As-late-as-possible activities then move right by their
free float. Level-of-effort activities run from the earliest date their start-type links
give (SS / FS predecessors, SS / SF successors) to the latest their finish-type links give
(FF / SF predecessors, FF / FS successors); they drive nothing.

Validated against P6's own output: recalculating real P6 exports reproduces every stored
early/late date and total/free float to the minute (Hotel, P6 6.0: 4,217 activities,
25,302 values; Terminal, P6 5.0; both unstarted), and every stored assignment date
(2,340 assignments, 9,360 dates). Progressed, resource-dependent and constrained
networks, which no public P6 export covers, are compared with MPXJ's independent
PrimaveraScheduler; the cases where the two differ are named in crosscheck.UNRESOLVED.
See docs/cpm.md, tests/test_cpm.py and tests/test_crosscheck_mpxj.py.

Not modelled (reported in ``warnings``): leveling, multiple float paths, relationships to
projects not in the file.
"""

from __future__ import annotations

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
    pass


# SCHEDOPTIONS.sched_float_type -> which float "Compute Total Float as" reports, measured
# on the activity's calendar. P6's own dialog writes FT_FF (Finish Float = LF - EF), FT_SS
# (Start Float = LS - ES) and FT_Min (the smaller). FT_Start and FT_Total only come from
# imported files: P6 keeps the code and reports a start float it makes equal to the finish
# float. Evidence, P6 23.12 held-out corpus H8-H30 on P6's own dates, resource-dependent
# work (the only place the two floats differ): FT_FF = finish 1125/1125, FT_SS = start
# 40/40, FT_Min = min 282/292, FT_Start = finish 390/461 (start 294). On task-dependent
# work the late dates are placed by duration on the same calendar: both floats are equal.
FLOAT_TYPE = {"FT_FF": "finish", "FT_SS": "start", "FT_Min": "min", "FT_Start": "finish", "FT_Total": "finish"}


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

    def __post_init__(self):
        if self.progressed not in PROGRESSED:
            raise ValueError(f"progressed must be one of {PROGRESSED}")

    @classmethod
    def from_snapshot(cls, snap: Snapshot) -> Options:
        o = snap.options.get("sched", {}) or {}

        def flag(key, default):
            v = o.get(key, "")
            return default if v in ("", None) else v == "Y"

        return cls(
            progressed=snap.options.get("progressed", "retained_logic"),
            float_type=o.get("sched_float_type") or "FT_FF",
            lag_calendar=snap.options.get("lag_calendar", "rcal_Successor"),
            open_critical=flag("sched_open_critical_flag", False),
            lag_from_early_start=flag("sched_lag_early_start_flag", True),
            use_expected_finish=flag("sched_use_expect_end_flag", True),
            must_finish_by=snap.options.get("must_finish_by"),
            honor_external=(o.get("sched_outer_depend_type") or "SD_Both") == "SD_Both",
        )


@dataclass
class Schedule:
    frame: pd.DataFrame  # index task_code: es, ef, ls, lf, tf_hr, ff_hr, ...
    finish: pd.Timestamp | None
    options: Options
    warnings: list[str] = field(default_factory=list)
    assignments: pd.DataFrame = field(default_factory=pd.DataFrame)  # one row per open assignment


class _Axes:
    """One TimeAxis per calendar, built once over the schedule's date range."""

    def __init__(self, snap: Snapshot, first, last):
        self.snap, self.first, self.last = snap, first, last
        self._axes: dict[str, TimeAxis] = {}

    def __getitem__(self, cal: WorkCalendar) -> TimeAxis:
        key = cal.clndr_id or "__default__"
        if key not in self._axes:
            self._axes[key] = TimeAxis(cal, self.first, self.last)
        return self._axes[key]

    def of(self, clndr_id: str) -> TimeAxis:
        return self[self.snap.calendar(clndr_id)]


def _date_range(snap: Snapshot):
    t = snap.activities
    cols = [
        c
        for c in [
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
        if c in t
    ]
    stamps = pd.concat([t[c] for c in cols]).dropna()
    lo = min([stamps.min()] + [x for x in [snap.data_date] if x is not None]) if len(stamps) else snap.data_date
    hi = max([stamps.max()] + [x for x in [snap.data_date] if x is not None]) if len(stamps) else snap.data_date
    return (lo - pd.Timedelta(days=60)).date(), (hi + pd.Timedelta(days=400)).date()


def schedule(snap: Snapshot, extra_hours: dict[str, float] | None = None, options: Options | None = None) -> Schedule:
    """Recompute early/late dates and float of every activity of ``snap``.

    The plain recalculation (no extra delay, file options) is cached on the snapshot:
    the integrity check, the critical path test and the weekly history share it.
    """
    if not extra_hours and options is None:
        cached = getattr(snap, "_xs_schedule", None)
        if cached is None:
            cached = _schedule(snap, None, None)
            object.__setattr__(snap, "_xs_schedule", cached)
        return cached
    return _schedule(snap, extra_hours, options)


@dataclass
class _Asg:
    """One open assignment as the CPM schedules it."""

    taskrsrc_id: str
    rsrc: str
    ax: TimeAxis
    lag_m: float  # remaining assignment lag, minutes
    dur_m: float  # remaining duration, minutes (None = the activity's)
    driving: bool


def _schedule(snap: Snapshot, extra_hours: dict[str, float] | None, options: Options | None) -> Schedule:
    return _Run(snap, extra_hours or {}, options or Options.from_snapshot(snap)).result()


class _Run:
    """One recalculation: the network, then one method per pass, in the order P6 runs them.

    State is kept in plain dicts keyed by activity code (es, ef, rs, ls, lf, tf, ff): they
    are 10x faster than DataFrame lookups in the passes' inner loops.
    """

    def __init__(self, snap: Snapshot, extra: dict[str, float], opt: Options):
        self.snap, self.extra, self.opt = snap, extra, opt
        # Nothing is scheduled before the data date, nor before the project's planned start
        # (P6 keeps the later of the two as the earliest start of remaining work).
        self.warnings: list[str] = []
        known = [d for d in (snap.data_date, snap.planned_start) if d is not None]
        if not known:  # never scheduled: start from the earliest date any activity carries
            a = snap.activities
            cols = [c for c in ("act_start_date", "early_start_date", "target_start_date") if c in a]
            stamps = pd.concat([a[c] for c in cols]).dropna() if cols else pd.Series(dtype="datetime64[ns]")
            if stamps.empty:
                raise ValueError("no data date, no planned start and no activity date: nothing to schedule from")
            known = [stamps.min()]
            self.warnings.append(
                f"no data date or planned start: scheduled from the earliest activity date {known[0]:%Y-%m-%d %H:%M}"
            )
        self.dd = max(known)
        self.t = snap.activities.drop_duplicates("task_code").set_index("task_code")
        self.axes = _Axes(snap, *_date_range(snap))
        self.proj_cal = snap.calendar()
        self._network()
        cols = [
            "task_type", "status_code", "clndr_id", "remain_drtn_hr_cnt", "act_start_date", "act_end_date",
            "cstr_type", "cstr_date", "cstr_type2", "cstr_date2", "expect_end_date",
            "external_early_start_date", "external_late_end_date",
        ]  # fmt: skip
        self.R = self.t[[c for c in cols if c in self.t]].to_dict("index")
        self.cal_ax = {c: self.axes.of(self.R[c]["clndr_id"]) for c in self.t.index}
        self.status = self.t["status_code"].to_dict()
        self._assignments()
        self.es: dict[str, pd.Timestamp] = {}
        self.ef: dict[str, pd.Timestamp] = {}
        self.rs: dict[str, pd.Timestamp] = {}  # start used by SS/SF successors (remaining start)
        self.ls: dict[str, pd.Timestamp] = {}
        self.lf: dict[str, pd.Timestamp] = {}
        self.tf: dict[str, float] = {}
        self.ff: dict[str, float] = {}
        self.a_early: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}  # taskrsrc_id -> start, finish
        self.a_late: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
        # Retained Logic: finished activities pass logic through (see pred_bounds)
        self.retain = opt.progressed == "retained_logic"
        self.dur_override: dict[str, float] = {}  # remaining minutes set by an expected finish
        self.carry: dict[str, pd.Timestamp] = {}  # finished activity -> early date it passes on
        self.lcarry: dict[str, pd.Timestamp] = {}  # finished activity -> late date it passes back
        self.external: set[str] = set()  # activities bounded by an external date
        self.unapplied: list[str] = []  # in-progress activities whose constraints the forward pass skips

    # --- network ---------------------------------------------------------------------------
    def _network(self) -> None:
        """Relationships between scheduled activities, LOE links apart, topological order."""
        t = self.t
        self.is_loe = t["is_loe"].to_dict()
        self.nodes = [c for c in t.index if not self.is_loe[c]]
        self.loe_codes = [c for c in t.index if self.is_loe[c]]
        node_set = set(self.nodes)
        self.preds: dict[str, list] = defaultdict(list)
        self.succs: dict[str, list] = defaultdict(list)
        self.loe_preds: dict[str, list] = defaultdict(list)
        self.loe_succs: dict[str, list] = defaultdict(list)
        rel = self.snap.relationships[["pred_code", "succ_code", "type", "lag_hr"]]
        for p, s, typ, lag in rel.itertuples(index=False):
            lag_m = float(lag or 0) * 60
            if p in node_set and s in node_set:
                self.preds[s].append((p, typ, lag_m))
                self.succs[p].append((s, typ, lag_m))
            elif s in t.index and self.is_loe.get(s, False) and p in node_set:
                self.loe_preds[s].append((p, typ, lag_m))
            elif p in t.index and self.is_loe.get(p, False) and s in node_set:
                self.loe_succs[p].append((s, typ, lag_m))
        indeg = dict.fromkeys(self.nodes, 0)
        for s, links in self.preds.items():
            indeg[s] = len(links)
        queue = deque(c for c in self.nodes if indeg[c] == 0)
        order: list[str] = []
        while queue:
            c = queue.popleft()
            order.append(c)
            for s, _, _ in self.succs[c]:
                indeg[s] -= 1
                if indeg[s] == 0:
                    queue.append(s)
        if len(order) != len(self.nodes):
            loop = sorted(set(self.nodes) - set(order))
            raise CycleError(f"logic loop among {loop[:8]}{'…' if len(loop) > 8 else ''}")
        self.order = order

    def _assignments(self) -> None:
        """Open assignments. Resource-dependent activities are scheduled from their driving
        assignments, each on its resource's calendar; the others use the activity calendar."""
        R, status = self.R, self.status
        self.asg: dict[str, list[_Asg]] = defaultdict(list)
        a_tab = self.snap.assignments
        for r in a_tab.itertuples(index=False) if not a_tab.empty else []:
            c = r.task_code
            if c not in R or status[c] == "TK_Complete" or self.is_loe[c]:
                continue
            rem = float(r.remain_qty) if pd.notna(r.remain_qty) else 0.0
            rate = float(r.remain_qty_per_hr) if pd.notna(r.remain_qty_per_hr) else 0.0
            on_rsrc_cal = R[c].get("task_type") == "TT_Rsrc" and bool(r.rsrc_clndr_id)
            ax = self.axes.of(r.rsrc_clndr_id) if on_rsrc_cal else self.cal_ax[c]
            dur = rem / rate * 60 if rate > 0 else None
            lag = float(r.relag_drtn_hr_cnt) * 60 if pd.notna(r.relag_drtn_hr_cnt) else 0.0
            name = str(r.rsrc_short_name or r.rsrc_name or r.rsrc_id or "")
            self.asg[c].append(_Asg(str(r.taskrsrc_id), name, ax, lag, dur, bool(r.driving)))
        rsrc_type = {c for c in self.nodes if R[c].get("task_type") == "TT_Rsrc" and status[c] != "TK_Complete"}
        self.rsrc_dep = {c for c in rsrc_type if self.driving(c)}
        lacking = [c for c in self.nodes if c in rsrc_type and c not in self.rsrc_dep]
        if lacking:
            self.warnings.append(
                f"{len(lacking)} resource-dependent activities without a driving assignment with "
                f"units per hour, scheduled on their activity calendar: {lacking[:5]}"
            )

    # --- helpers -----------------------------------------------------------------------------
    def lag_axis(self, p: str, s: str) -> TimeAxis:
        cal = self.opt.lag_calendar
        if cal == "rcal_Predecessor":
            return self.cal_ax[p]
        if cal == "rcal_24Hour":
            return self.axes[H24]
        if cal == "rcal_ProjDefault":
            return self.axes[self.proj_cal]
        return self.cal_ax[s]

    @staticmethod
    def shift(ax: TimeAxis, ts: pd.Timestamp, lag_m: float) -> pd.Timestamp:
        return ts if lag_m == 0 else ax.add(ts, lag_m, finish=lag_m > 0)

    def kind(self, c) -> str:
        tt = self.R[c].get("task_type")
        return "start_ms" if tt in ("TT_Mile", "TT_StartMile") else "finish_ms" if tt == "TT_FinMile" else "task"

    def dur_min(self, c) -> float:
        if c in self.dur_override:  # remaining duration recomputed from an expected finish
            return self.dur_override[c] + self.extra.get(c, 0.0) * 60
        rd = self.R[c].get("remain_drtn_hr_cnt")
        return (0.0 if pd.isna(rd) else float(rd) * 60) + self.extra.get(c, 0.0) * 60

    def driving(self, c) -> list[_Asg]:
        return [a for a in self.asg[c] if a.driving and a.dur_m is not None]

    def constraints(self, c) -> list[tuple[str, pd.Timestamp]]:
        out = []
        for ct, cd in (("cstr_type", "cstr_date"), ("cstr_type2", "cstr_date2")):
            typ, date = self.R[c].get(ct), self.R[c].get(cd)
            if typ and isinstance(typ, str) and typ != "CS_ALAP" and pd.notna(date):
                out.append((typ, pd.Timestamp(date)))
        return out

    def pred_bounds(self, c: str, started: bool, finish_only: bool = False) -> list[tuple[str, pd.Timestamp]]:
        """Lower bounds the predecessors of ``c`` put on its start or its finish.

        Returns ("start" | "finish", instant) pairs; ``finish_only`` keeps the FF / SF ones.
        A finished predecessor, under Retained Logic, passes on what its own unfinished
        predecessors still impose (``carry``: the data date when nothing does), plus the
        part of a positive lag not yet expired since
        its actual finish (FS, FF) or start (SS, SF); a lead is dropped, and between two
        finished activities only the carried date passes. Without Retained Logic a finished
        predecessor bounds unstarted work by its actual dates + lag, and started work not at
        all. An SS or SF link from a started predecessor is measured from its remaining early
        start (or its actual start, under the option) plus the unexpired lag: P6 23.12 applies
        the SF case too (held-out corpus H1-08 A1240), where MPXJ's scheduler binds nothing.
        Out-of-sequence progress otherwise follows MPXJ's PrimaveraScheduler (its issue #972,
        checked there against real P6 schedules); with no out-of-sequence progress both
        readings give the same dates.
        """
        out = []
        for p, typ, lag in self.preds[c]:
            end = "start" if typ in ("FS", "SS") else "finish"
            if finish_only and end == "start":
                continue
            lx = self.lag_axis(p, c)
            if self.status[p] == "TK_Complete":
                if self.retain:
                    if self.status[c] == "TK_Complete":
                        out.append((end, self.carry[p]))
                        continue
                    frm = self.R[p].get("act_end_date" if typ in ("FS", "FF") else "act_start_date")
                    rem = lag
                    if lag <= 0:
                        rem = 0.0
                    elif frm is not None and pd.notna(frm):
                        rem = max(0.0, lag - max(0, lx.between(frm, self.dd)))
                    out.append((end, self.shift(lx, self.carry[p], rem)))
                    continue
                if started and not finish_only:
                    continue  # Progress Override: a finished FF / SF predecessor still bounds
            if typ in ("FS", "FF"):
                out.append((end, self.shift(lx, self.ef[p], lag)))
            else:
                p_start, p_lag = self.start_link(p, lx, lag)
                out.append((end, self.shift(lx, p_start, p_lag)))
        return out

    def unexpired(self, p: str, lx: TimeAxis, lag: float) -> float:
        """Lag of an SS/SF link from ``p`` still to run after the data date (whole lag if not started)."""
        act = self.R[p].get("act_start_date")
        if self.status[p] != "TK_Active" or lag <= 0 or act is None or pd.isna(act):
            return lag
        return max(0.0, lag - max(0, lx.between(act, self.dd)))

    def start_link(self, p: str, lx: TimeAxis, lag: float) -> tuple[pd.Timestamp, float]:
        """Instant an SS/SF link from ``p`` is measured from, and the lag to add.

        Oracle (Schedule Options, "Calculate start-to-start lag from"): Early Start =
        the predecessor's internal early start plus the lag not yet expired, expired =
        working time from its actual start to the data date; Actual Start = from its
        actual start (successor >= data date + remaining lag). Under Actual Dates the
        option is disabled: actual start.
        """
        act = self.R[p].get("act_start_date")
        if self.status[p] == "TK_NotStart" or act is None or pd.isna(act):
            return self.rs[p], lag
        if self.status[p] == "TK_Active" and self.opt.lag_from_early_start and self.opt.progressed != "actual_dates":
            return self.rs[p], self.unexpired(p, lx, lag)
        return act, lag

    # --- forward pass --------------------------------------------------------------------------
    def forward(self) -> None:
        R, opt, status, dd = self.R, self.opt, self.status, self.dd
        es, ef, rs = self.es, self.ef, self.rs
        for c in self.order:
            ax = self.cal_ax[c]
            st = status[c]
            if st == "TK_Complete":
                es[c], ef[c] = R[c].get("act_start_date"), R[c].get("act_end_date")
                rs[c] = es[c]
                if pd.isna(es[c]) or pd.isna(ef[c]):
                    self.warnings.append(f"{c}: complete without actual dates")
                    es[c] = ef[c] = es[c] if pd.notna(es[c]) else ef[c] if pd.notna(ef[c]) else dd
                if self.retain:
                    self.carry[c] = max([dd] + [b for _, b in self.pred_bounds(c, started=False)])
                continue
            started = st == "TK_Active"
            k, d = self.kind(c), self.dur_min(c)
            s_c, f_c = [dd], []
            # Progress Override: the start of work under way is an actual, so FS / SS
            # predecessors no longer bound it; FF / SF predecessors still bound its finish
            # (P6 23.12, corpus H1-11 A1040: +260 values). Mirrored in successor_limits.
            use_logic = not (started and opt.progressed == "progress_override")
            for end, bound in self.pred_bounds(c, started, finish_only=not use_logic):
                (s_c if end == "start" else f_c).append(bound)
            ext = R[c].get("external_early_start_date")
            if use_logic and opt.honor_external and ext is not None and pd.notna(ext):
                s_c.append(pd.Timestamp(ext))  # a lost link to a project not in the database
                self.external.add(c)
            pinned = None
            if started and self.constraints(c):
                self.unapplied.append(c)
            for typ, date in [] if started else self.constraints(c):
                if typ in MANDATORY:
                    pinned = (MANDATORY[typ], date)
                elif START_LIKE.get(typ) == "start":
                    s_c.append(date)
                elif START_LIKE.get(typ) == "finish":
                    f_c.append(date)
            # Mandatory Start / Finish: the date, whatever the logic, in both passes; except
            # that unstarted work never starts before the data date (P6 23.12, corpus H3-04
            # A1100, H2-06 A1130: the early dates move to the data date, the late dates stay)
            if pinned and pinned[0] == "start":
                s_c, f_c = [max(pinned[1], dd)], []
            if c in self.rsrc_dep and k == "task":
                start, fin = self.rsrc_early(c, s_c, f_c, self.extra.get(c, 0.0) * 60)
            else:
                start, fin = _early(ax, k, d, s_c, f_c)
            if pinned and pinned[0] == "finish":
                fin = ax.keep_or_previous(pinned[1])
                start = ax.add(fin, -d, finish=False) if (k == "task" and d) else fin
                if start < dd:
                    start = ax.snap_start(dd)
                    fin = ax.add(start, d, finish=True) if (k == "task" and d) else start
            if k == "task" and opt.use_expected_finish:
                exp = R[c].get("expect_end_date", pd.NaT)
                alap = "CS_ALAP" in (R[c].get("cstr_type"), R[c].get("cstr_type2"))
                finish_linked = any(typ in ("FF", "SF") for _, typ, _ in self.preds[c])
                if pd.notna(exp) and not alap and c not in self.rsrc_dep:
                    start, fin = self.expected_finish(
                        c, ax, pd.Timestamp(exp), s_c, f_c, start, fin, use_logic, finish_linked
                    )
                elif pd.notna(exp) and not alap and not finish_linked and exp >= start and exp >= dd:
                    # resource-dependent work: MPXJ's reading, the only one measured better
                    # than P6's task rule on the corpus so far (register R7)
                    fin = pd.Timestamp(exp)
                    self.dur_override[c] = float(ax.between(start, fin))
            es[c], ef[c], rs[c] = (R[c].get("act_start_date") if started and k == "task" else start), fin, start
        self.open_ = [c for c in self.order if status[c] != "TK_Complete"]
        # Under Retained Logic a finished activity ends, for its successors, at its carried
        # date: an actual finish after the data date (invalid progress) no longer sets the end.
        self.finish = max(
            (self.carry.get(c, ef[c]) if status[c] == "TK_Complete" else ef[c] for c in self.nodes), default=None
        )

    def expected_finish(self, c, ax, exp, s_c, f_c, start, fin, use_logic, finish_linked):
        """Early dates of task-dependent work with an expected finish, as P6 23.12 places them
        (held-out corpus, 300 activities with an expected finish, every status and option).

        The expected finish stands in for "early start + remaining duration": the early
        finish is the expected finish, or the early start when the expected finish falls
        before it (remaining duration 0), on whatever date the data date, the predecessors
        or a constraint give the start, a Mandatory Finish included (it only pins the late
        dates, register R5). An FF / SF bound later than that finish wins instead, with the
        file's remaining duration and the start placed back from it, as without an expected
        finish. The remaining duration the backward pass uses follows the early dates.

        Measured but not understood: work under way under Progress Override with an FF / SF
        predecessor keeps its remaining duration when the expected finish falls before its
        early start, even when that predecessor's bound no longer binds (35 of 36 corpus
        values; without the rule 35 lost, 2 won).
        """
        s0 = ax.snap_start(max(s_c)) if s_c else start
        if not use_logic and finish_linked and exp < s0:
            return start, fin
        exp_fin = max(exp, s0)
        f_min = ax.keep_or_next(max(f_c)) if f_c else None
        if f_min is not None and exp_fin < f_min:
            return start, fin
        self.dur_override[c] = float(ax.between(s0, exp_fin))
        return s0, exp_fin

    def rsrc_early(self, c, s_c, f_c, d_extra) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Resource dependent: each driving assignment on its resource calendar."""
        lo = max(s_c)
        f_min = max(f_c) if f_c else None
        starts, fins = [], []
        for a in self.driving(c):
            d = a.dur_m + d_extra
            s0 = a.ax.snap_start(self.shift(a.ax, lo, a.lag_m))
            f0 = a.ax.add(s0, d, finish=True) if d else s0
            if f_min is not None and f0 < f_min:
                f0 = a.ax.keep_or_next(f_min)
                s0 = a.ax.add(f0, -d, finish=False) if d else f0
            self.a_early[a.taskrsrc_id] = (s0, f0)
            starts.append(s0)
            fins.append(f0)
        return min(starts), max(fins)

    # --- backward pass -------------------------------------------------------------------------
    def successor_limits(self, c, late: bool) -> tuple[list, list]:
        """Latest start / finish ``c`` may have against its successors' late (or early) dates."""
        R, status = self.R, self.status
        l_s, l_f = [], []
        po = self.opt.progressed == "progress_override"
        for s, typ, link_lag in self.succs[c]:
            lag = link_lag
            if po and status[s] == "TK_Active" and typ in ("FS", "SS"):
                # Progress Override: a started successor's start is an actual, so a link to it
                # binds no late date; links to its finish (FF, SF) still do (corpus H5-06
                # A1030 vs H3-03 A1030: +406 values, 1 lost)
                continue
            if not late and po and status[c] == "TK_Active" and (typ in ("SS", "SF") or status[s] == "TK_Complete"):
                # ... and the free float of work under way runs past its own start-type links
                # (its start is an actual too) and past finished successors, to whatever is
                # left (corpus tally of one-successor activities; +116 values, 28 lost:
                # register R6 keeps the counter-examples, H4-08 A1010, H12-07 A1120)
                continue
            if (
                late
                and self.opt.progressed == "actual_dates"
                and status[s] != "TK_NotStart"
                and pd.notna(R[s].get("act_start_date"))
            ):
                # Actual Dates: the backward pass uses the successor's actual dates
                s_start = R[s].get("act_start_date")
                s_fin = R[s].get("act_end_date") if status[s] == "TK_Complete" else self.lf[s]
            elif status[s] == "TK_Complete" and not late and self.retain:
                # free float against a finished successor: it sits at its carried date
                s_start = s_fin = self.carry[s]
            elif status[s] == "TK_Complete":
                if late and self.retain:
                    # Retained Logic: a finished successor passes back the late date its own
                    # successors give it, less this link's lag: in full for FS / FF (it runs
                    # from a finish still to come: corpus H1-08 A1020, 40 h kept), the part
                    # not yet expired since the actual start for SS / SF (H6-07 A1030), a lead
                    # from started work not at all; between two finished activities only the
                    # carried date passes (H1-08 A1050). MPXJ's case table (FS lag dropped)
                    # differs: P6 settled it, +121 corpus values.
                    lc = self.lcarry[s]
                    if status[c] == "TK_Complete":
                        bound = lc
                    else:
                        lx = self.lag_axis(c, s)
                        use = self.unexpired(c, lx, lag) if typ in ("SS", "SF") else lag
                        if typ in ("SS", "SF") and lag < 0 and status[c] == "TK_Active":
                            use = 0.0
                        bound = self.shift(lx, lc, -use)
                    (l_f if typ in ("FS", "FF") else l_s).append(bound)
                continue
            else:
                s_start, s_fin = (self.ls[s], self.lf[s]) if late else (self.rs[s], self.ef[s])
            lx = self.lag_axis(c, s)
            # SS / SF from a started activity: the forward pass only waits for the lag not
            # yet expired, so the backward pass mirrors that, or a driving link would leave
            # negative float on an unconstrained network.
            s_lag = self.unexpired(c, lx, lag) if typ in ("SS", "SF") else lag
            if typ in ("SS", "SF") and lag < 0 and status[c] == "TK_Active":
                s_lag = 0.0  # a lead from work already started no longer pulls it earlier (MPXJ)
            if status[c] == "TK_Complete":
                # finished (Retained Logic, see lcarry): only the lag not yet expired since its
                # actual finish (FS, FF) or start (SS, SF) still counts; a lead is dropped (MPXJ)
                frm = R[c].get("act_end_date" if typ in ("FS", "FF") else "act_start_date")
                done_lag = max(0, lx.between(frm, self.dd)) if frm is not None and pd.notna(frm) else 0
                lag = s_lag = max(0.0, lag - done_lag) if lag > 0 else 0.0
            if typ == "FS":
                l_f.append(self.shift(lx, s_start, -lag))
            elif typ == "SS":
                l_s.append(self.shift(lx, s_start, -s_lag))
            elif typ == "FF":
                l_f.append(self.shift(lx, s_fin, -lag))
            elif typ == "SF":
                l_s.append(self.shift(lx, s_fin, -s_lag))
        return l_s, l_f

    def place_late(self, c, ax, k, d, l_s, l_f) -> tuple[pd.Timestamp, pd.Timestamp]:
        if c not in self.rsrc_dep or k != "task":
            return _late(ax, k, d, l_s, l_f)
        hi_f = min(l_f) if l_f else None
        hi_s = min(l_s) if l_s else None
        starts, fins = [], []
        for a in self.driving(c):
            dd_ = a.dur_m + self.extra.get(c, 0.0) * 60
            f0 = a.ax.snap_finish(hi_f) if hi_f is not None else None
            s0 = (a.ax.add(f0, -dd_, finish=False) if dd_ else f0) if f0 is not None else None
            if hi_s is not None:
                cand = a.ax.snap_start(self.shift(a.ax, hi_s, a.lag_m))
                if s0 is None or cand < s0:
                    s0, f0 = cand, a.ax.add(cand, dd_, finish=True) if dd_ else cand
            self.a_late[a.taskrsrc_id] = (s0, f0)
            starts.append(self.shift(a.ax, s0, -a.lag_m))
            fins.append(f0)
        return min(starts), max(fins)

    def backward(self) -> None:
        opt, status = self.opt, self.status
        end_anchor = opt.must_finish_by if opt.must_finish_by is not None else self.finish
        for c in reversed(self.order):
            if status[c] == "TK_Complete":
                if self.retain:
                    l_s, l_f = self.successor_limits(c, late=True)
                    self.lcarry[c] = min(l_s + l_f + [end_anchor])
                continue
            ax = self.cal_ax[c]
            k, d = self.kind(c), self.dur_min(c)
            l_s, l_f = self.successor_limits(c, late=True)
            if not l_s and not l_f:
                l_f.append(self.ef[c] if opt.open_critical else end_anchor)
            else:
                # No late finish after the project's: an activity whose successors only bound
                # its start (SS, SF) would otherwise float past the end, and so would its
                # predecessors. MPXJ's PrimaveraScheduler caps it the same way; no P6 file at
                # hand covers the case (tests/test_crosscheck_mpxj.py).
                l_f.append(end_anchor)
            ext = self.R[c].get("external_late_end_date")
            if opt.honor_external and ext is not None and pd.notna(ext):
                l_f.append(pd.Timestamp(ext))
                self.external.add(c)
            pinned = None
            for typ, date in self.constraints(c):
                if typ in MANDATORY:
                    pinned = (MANDATORY[typ], date)
                elif LATE_LIKE.get(typ) == "start" and status[c] != "TK_Active":
                    l_s.append(date)
                elif LATE_LIKE.get(typ) == "finish":
                    l_f.append(date)
            if pinned:
                l_s, l_f = ([pinned[1]], []) if pinned[0] == "start" else ([], [pinned[1]])
                if pinned[0] == "finish" and c in self.dur_override:
                    # an expected finish earlier than the Mandatory Finish is the late finish
                    # too (corpus H22-06 A1120, 18 values; the activity's early finish is then
                    # the expected finish)
                    l_f = [min(pinned[1], self.ef[c])]
            self.ls[c], self.lf[c] = self.place_late(c, ax, k, d, l_s, l_f)

    # --- float, as late as possible ------------------------------------------------------------
    def floats(self) -> None:
        """Reverse order, so an ALAP activity sees its successors already moved, and free float
        is measured against the dates P6 finally shows."""
        R, es, ef, rs, ls, lf = self.R, self.es, self.ef, self.rs, self.ls, self.lf
        for c in reversed(self.open_):
            ax = self.cal_ax[c]
            k, d = self.kind(c), self.dur_min(c)
            alap = "CS_ALAP" in (R[c].get("cstr_type"), R[c].get("cstr_type2")) and self.status[c] == "TK_NotStart"
            e_s, e_f = self.successor_limits(c, late=False)
            if alap:
                if not e_s and not e_f:
                    e_f = [self.finish]
                keep = dict(self.a_late)
                new_s, new_f = self.place_late(c, ax, k, d, e_s, e_f)
                if new_f > ef[c]:
                    es[c], ef[c], rs[c] = new_s, new_f, new_s
                    for a in self.driving(c) if c in self.rsrc_dep else []:
                        self.a_early[a.taskrsrc_id] = self.a_late[a.taskrsrc_id]
                self.a_late.clear()
                self.a_late.update(keep)
            gaps = [ax.between(ef[c], x) / 60 for x in e_f] + [ax.between(rs[c], x) / 60 for x in e_s]
            # open end: free float runs to the project's early finish, not to "must finish by"
            self.ff[c] = max(0.0, min(gaps)) if gaps else max(0.0, ax.between(ef[c], self.finish) / 60)
            fin_f = ax.between(ef[c], lf[c]) / 60
            st_f = ax.between(rs[c], ls[c]) / 60
            which = FLOAT_TYPE.get(self.opt.float_type, "finish")  # unknown code: P6's default
            self.tf[c] = fin_f if which == "finish" else st_f if which == "start" else min(fin_f, st_f)

    # --- level of effort: spans what drives it ------------------------------------------------
    def level_of_effort(self) -> None:
        """Each relationship ties the end of the LOE it names: start-type ends (SS, FS
        predecessors; SS, SF successors) give its start, finish-type ends (FF, SF
        predecessors; FF, FS successors) its finish. An FF predecessor and an FF successor to
        the same activity give the same finish (Boyle, "constructing LOE activities in P6").
        It runs from the earliest start to the latest finish."""
        R, dd, es, ef, rs = self.R, self.dd, self.es, self.ef, self.rs
        for c in self.loe_codes:
            if self.status[c] == "TK_Complete":
                es[c], ef[c] = R[c].get("act_start_date"), R[c].get("act_end_date")
                continue
            ax = self.cal_ax[c]
            starts, ends = [], []
            for p, typ, lag in self.loe_preds[c]:
                frm = rs[p] if typ in ("SS", "SF") else ef[p]
                (starts if typ in ("SS", "FS") else ends).append(self.shift(self.lag_axis(p, c), frm, lag))
            for s_, typ, lag in self.loe_succs[c]:
                to = rs[s_] if typ in ("SS", "FS") else ef[s_]
                (starts if typ in ("SS", "SF") else ends).append(self.shift(self.lag_axis(c, s_), to, -lag))
            active = self.status[c] == "TK_Active"
            s0 = R[c].get("act_start_date") if active else ax.snap_start(max([dd, min(starts)] if starts else [dd]))
            e0 = ax.snap_finish(max(ends)) if ends else (ax.snap_finish(self.finish) if self.finish is not None else s0)
            es[c], ef[c] = s0, max(e0, ax.snap_start(max(s0, dd)))
            rs[c] = ax.snap_start(dd) if active else s0
            self.ls[c], self.lf[c] = rs[c], ef[c]
            self.tf[c] = self.ff[c] = 0.0

    # --- longest path ------------------------------------------------------------------------
    def longest_path(self) -> set[str]:
        """From the activities that finish last, back through driving links (Oracle:
        "activities that have an early finish equal to the latest calculated early finish
        for the project", then "all driving relationships for those activities")."""
        longest: set[str] = set()
        todo_ = [c for c in self.open_ if self.ef[c] == self.finish]
        while todo_:
            c = todo_.pop()
            if c in longest:
                continue
            longest.add(c)
            ax = self.cal_ax[c]
            for p, typ, lag in self.preds[c]:
                if self.status[p] == "TK_Complete" or (
                    self.status[c] == "TK_Active" and self.opt.progressed == "progress_override"
                ):
                    continue
                lx = self.lag_axis(p, c)
                if typ in ("FS", "FF"):
                    bound = self.shift(lx, self.ef[p], lag)
                else:
                    p_start, p_lag = self.start_link(p, lx, lag)
                    bound = self.shift(lx, p_start, p_lag)
                mine = self.rs[c] if typ in ("FS", "SS") else self.ef[c]
                if ax.work(bound) >= ax.work(mine):
                    todo_.append(p)
        return longest

    # --- assignment dates --------------------------------------------------------------------
    def assignment_dates(self) -> pd.DataFrame:
        """Task dependent: the activity's remaining dates + assignment lag, for the assignment's
        own duration (units / units per hour) on the activity calendar. Checked against every
        assignment P6 stored in Hotel and Terminal (tests/test_cpm.py)."""
        rows = []
        for c, items in self.asg.items():
            if c not in self.rs or c not in self.ls:
                continue
            for a in items:
                if a.taskrsrc_id in self.a_early:
                    (s0, f0), (s1, f1) = self.a_early[a.taskrsrc_id], self.a_late.get(a.taskrsrc_id, (None, None))
                else:
                    d = a.dur_m if a.dur_m is not None else self.dur_min(c)
                    s0 = a.ax.snap_start(self.shift(a.ax, self.rs[c], a.lag_m))
                    f0 = a.ax.add(s0, d, finish=True) if d else s0
                    s1 = a.ax.snap_start(self.shift(a.ax, self.ls[c], a.lag_m))
                    f1 = a.ax.add(s1, d, finish=True) if d else s1
                rows.append([a.taskrsrc_id, c, a.rsrc, a.driving, s0, f0, s1, f1])
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
                "task_code": c, "status_code": self.status[c], "es": self.es[c], "ef": self.ef[c],
                "remaining_start": self.rs.get(c), "ls": self.ls.get(c), "lf": self.lf.get(c),
                "tf_hr": self.tf.get(c), "ff_hr": self.ff.get(c), "resource_dependent": c in self.rsrc_dep,
                "longest_path": c in longest,
            }
            for c in self.t.index
            if c in self.es
        ]  # fmt: skip
        frame = pd.DataFrame(rows).set_index("task_code")
        return Schedule(frame, self.finish, self.opt, self.warnings, self.assignment_dates())

    def _report(self) -> None:
        if (self.snap.options.get("sched", {}) or {}).get("enable_multiple_longest_path_calc") == "Y":
            self.warnings.append(
                "the project asks for multiple float paths: dates and float are unaffected, but the float "
                "path numbers (float_path, float_path_order) are not computed"
            )
        if self.external:
            self.warnings.append(
                f"{len(self.external)} activities bounded by P6's external early start / late finish "
                f"(relationships to projects not in the file): {sorted(self.external)[:5]}"
            )
        if self.unapplied:
            self.warnings.append(
                f"{len(self.unapplied)} in-progress activities carry a constraint: the forward pass keeps their "
                f"actual start, the backward pass applies finish and mandatory constraints. No reference file "
                f"covers this case, compare with P6: {self.unapplied[:5]}"
            )


ASSIGNMENT_COLS = ["taskrsrc_id", "task_code", "rsrc", "driving", "restart", "reend", "rem_late_start", "rem_late_end"]


def _early(ax: TimeAxis, kind: str, d: float, s_c: list, f_c: list) -> tuple[pd.Timestamp, pd.Timestamp]:
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
        v = ax.keep_or_next(max(s_c + f_c))
        return v, v
    if kind == "start_ms" or d == 0:
        v = ax.snap_start(max(s_c + f_c))
        return v, v
    start = ax.snap_start(max(s_c))
    fin = ax.add(start, d, finish=True)
    if f_c:
        f_min = ax.keep_or_next(max(f_c))
        if f_min > fin:
            fin, start = f_min, ax.add(f_min, -d, finish=False)
    return start, fin


def _late(ax: TimeAxis, kind: str, d: float, l_s: list, l_f: list) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Late start / finish from upper bounds, snapped the way P6 shows them.

    - task: finishes at a period end (a successor starting 08:00 -> previous evening);
      a start bound (SS / SF successor, start constraint) is written at its own instant,
      the previous period end when it falls in non-working time (P6 23.12, corpus H3-02
      A1240: Fri 17:00, not Mon 07:00; the same working minute, +94 values)
    - start milestone: the bound as it is when working time or a period edge, else the
      previous working time (Hotel HCMEB4000: 16:00; xerlock MS-020: 08:00)
    - finish milestone: a period end
    """
    if kind == "start_ms" or (kind == "task" and d == 0):
        v = ax.keep_or_previous(min(l_s + l_f))
        return v, v
    if kind == "finish_ms":
        v = ax.snap_finish(min(l_s + l_f))
        return v, v
    fin = ax.snap_finish(min(l_f)) if l_f else None
    start = ax.add(fin, -d, finish=False) if fin is not None else None
    if l_s:
        s_max = ax.keep_or_previous(min(l_s))
        if start is None or s_max < start:
            start, fin = s_max, ax.add(s_max, d, finish=True)
    return start, fin


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


def compare_with_stored(snap: Snapshot, sched: Schedule | None = None) -> pd.DataFrame:
    """One row per (open activity, field): what P6 stored, what the CPM gives, the gap.

    For in-progress activities P6 stores the remaining early start as early start.
    ``agree`` needs the exact clock time; ``gap_hr`` is the difference in working hours
    of the activity's calendar (0 with agree False = same instant shown differently,
    e.g. Wednesday 17:00 vs the next working morning).
    """
    sched = sched or schedule(snap)
    t = snap.activities.drop_duplicates("task_code").set_index("task_code")
    f = sched.frame
    rows = []
    axes = _Axes(snap, *_date_range(snap))
    for c in f.index:
        if t.at[c, "status_code"] == "TK_Complete" or t.at[c, "is_loe"]:
            continue
        ax = axes.of(t.at[c, "clndr_id"])
        for mine, theirs in FIELDS:
            v = f.at[c, "remaining_start"] if mine == "es" and t.at[c, "status_code"] == "TK_Active" else f.at[c, mine]
            stored = t.at[c, theirs] if theirs in t else None
            rows.append(_cmp_row(ax, c, theirs, stored, v, hours=mine.endswith("_hr")))
    return pd.DataFrame(rows, columns=["task_code", "field", "stored", "computed", "gap_hr", "agree"])


def _cmp_row(ax: TimeAxis, code, field_, stored, v, hours: bool) -> dict:
    if stored is None or pd.isna(stored) or v is None or pd.isna(v):
        gap = None
    elif hours:
        gap = round(float(v) - float(stored), 2)
    else:
        gap = ax.between(stored, v) / 60
    if hours:
        agree = gap == 0 if gap is not None else False
    else:  # dates: the same clock time, not just the same working minute
        agree = gap is not None and pd.Timestamp(stored) == pd.Timestamp(v)
    return {"task_code": code, "field": field_, "stored": stored, "computed": v, "gap_hr": gap, "agree": agree}


def compare_assignments(snap: Snapshot, sched: Schedule | None = None) -> pd.DataFrame:
    """One row per (open assignment, date): TASKRSRC remaining early / late dates vs the CPM."""
    sched = sched or schedule(snap)
    a = snap.assignments
    out_cols = ["taskrsrc_id", "task_code", "rsrc", "field", "stored", "computed", "gap_hr", "agree"]
    if a.empty or sched.assignments.empty:
        return pd.DataFrame(columns=out_cols)
    stored = a.assign(taskrsrc_id=a["taskrsrc_id"].astype(str)).drop_duplicates("taskrsrc_id").set_index("taskrsrc_id")
    t = snap.activities.drop_duplicates("task_code").set_index("task_code")
    axes = _Axes(snap, *_date_range(snap))
    rows = []
    for r in sched.assignments.itertuples(index=False):
        ax = axes.of(t.at[r.task_code, "clndr_id"])
        for mine, theirs in ASSIGNMENT_FIELDS:
            row = _cmp_row(ax, r.task_code, theirs, stored.at[r.taskrsrc_id, theirs], getattr(r, mine), False)
            rows.append({"taskrsrc_id": r.taskrsrc_id, "rsrc": r.rsrc, **row})
    return pd.DataFrame(rows, columns=out_cols)


# --- DCMA critical path test ----------------------------------------------------------------


@dataclass
class CptResult:
    passed: bool
    note: str
    delayed: str | None = None
    expected_h: float = 0.0
    shift_h: float = 0.0
    blocking: list[dict] = field(default_factory=list)


def critical_path_test(snap: Snapshot, delay_days: float = 600) -> CptResult:
    """Add ``delay_days`` to the first open activity of the critical path; the finish must move as much.

    The finish is measured on the project's end points (activities without successors),
    in working time of the delayed activity's calendar. Pass = it moved by at least the
    delay (further is a calendar effect, less means something absorbed the delay).
    """
    t = snap.activities
    try:
        base = schedule(snap)
    except CycleError as exc:
        return CptResult(False, str(exc))
    # The critical path = the longest path of the recalculated schedule (with negative
    # float, "total float <= 0" would also take in less critical paths).
    f = base.frame
    open_ = t[~t["is_complete"] & ~t["is_loe"] & ~t["is_milestone"]].drop_duplicates("task_code")
    crit = open_[open_["task_code"].map(f["longest_path"]).fillna(False).astype(bool)]
    if crit.empty:
        return CptResult(False, "no open activity on the longest path: the critical path is not defined")
    crit = crit.assign(_rs=crit["task_code"].map(f["remaining_start"]))
    target = crit.sort_values(["_rs", "task_code"]).iloc[0]
    code = target["task_code"]
    hpd = float(target["hours_per_day"])
    delay_h = delay_days * hpd
    try:
        late = schedule(snap, {code: delay_h})
    except CycleError as exc:
        return CptResult(False, str(exc), code)
    has_succ = set(snap.relationships["pred_code"])  # built once: per activity it took 33 s on Hotel
    ends = [c for c in base.frame.index if c not in has_succ]
    b_fin = base.frame.loc[ends, "ef"].max()
    l_fin = late.frame.loc[ends, "ef"].max()
    ax = TimeAxis(snap.calendar(target["clndr_id"]), b_fin.date(), (l_fin + pd.Timedelta(days=1)).date())
    shift = ax.between(b_fin, l_fin) / 60
    # The finish must move by the whole delay. It can move further when the path crosses
    # calendars with other non-working days (measured here on the delayed activity's
    # calendar); moving less means a constraint or broken logic absorbed part of it.
    passed = shift >= delay_h - 1e-6
    note = (
        f"+{delay_days:g} wd on {code}: forecast finish {b_fin:%Y-%m-%d} -> {l_fin:%Y-%m-%d}, "
        f"moved {shift / hpd:+.1f} wd"
        + ("" if passed else f" instead of {delay_days:+g}")
        + (" (more: the path crosses other calendars' non-working days)" if shift > delay_h + 1e-6 else "")
    )
    blocking = []
    if not passed:
        pins = t[t["cstr_type"].isin(MANDATORY) | t["cstr_type2"].isin(MANDATORY)]
        blocking = pins[["task_code", "task_name", "cstr_type", "cstr_type2"]].to_dict("records")
        if blocking:
            note += f"; mandatory constraints may absorb it: {', '.join(p['task_code'] for p in blocking[:5])}"
    return CptResult(passed, note, code, delay_h, shift, blocking)
