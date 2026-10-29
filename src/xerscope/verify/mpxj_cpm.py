"""MPXJ's PrimaveraScheduler as a second CPM engine, and the comparison of both with P6.

What P6's held-out corpus settled against MPXJ is in ``P6_SETTLED``; what no P6 output
settles yet is in ``UNRESOLVED``. xerscope follows P6; MPXJ is a hint.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..xer import build_snapshot, read_xer
from .mpxj_reader import _read_project, _start_jvm

# --- second CPM engine: MPXJ's PrimaveraScheduler ----------------------------------------------
#
# MPXJ (16.x) ships a CPM scheduler for P6 projects, written independently of xerscope and
# tuned by its authors against P6 output. It honours a subset of P6's scheduling options;
# a file using another one cannot be compared, and ``mpxj_unsupported`` says why. Known
# MPXJ's self-contradictions are detected by ``mpxj_inconsistent`` so a disagreement is never
# silently blamed on either engine.

CPM_FIELDS = ("es", "ef", "ls", "lf", "tf_hr", "ff_hr")

# Where xerscope and MPXJ were seen to differ (thousands of random networks, see
# tests/test_crosscheck_mpxj.py) and no P6 output is at hand to say which is right. Each
# needs a P6 recalculation of a file that contains it; until then neither engine is
# trusted there, and a comparison that meets one of them is reported, not failed.
UNRESOLVED = {
    "ff_sf_lag_from_finished": "FF / SF lag from a finished activity: MPXJ counts the lag from the data date "
    "(twice, for FF); xerscope lets it expire from the actual dates, as for FS",
    "sf_progressed": "SF into progressed work, or from a finished activity: MPXJ's case table differs by "
    "status in ways not derived from a rule",
    "lead_from_progressed": "a lead (negative lag) from finished work, or an FS / FF lead from started work "
    "(SS / SF leads from started work agree)",
    "finished_into_started": "an FF / SS / SF link from a finished activity into started work",
    "rsrc_calendar": "resource-dependent activity whose resources work another calendar: MPXJ starts it "
    "on the activity calendar, xerscope on each resource's",
    "assignment_lag": "assignment lag on a resource-dependent activity: MPXJ leaves it out of the activity dates",
    "free_float_lead": "free float of an activity with a lead to a successor",
    "free_float_mandatory": "free float of an activity with a mandatory constraint",
}


# Where the two engines differ and P6's output settled it against MPXJ (the P6 23.12 held-out
# corpus, tests/test_p6_heldout.py). xerscope follows P6; a comparison that meets one of these
# reports the difference as MPXJ's. MPXJ stays a hint everywhere else.
P6_SETTLED = {
    "sf_from_started": "SF from a started predecessor into unstarted work: MPXJ binds nothing past the data "
    "date; P6 applies the link from the predecessor's remaining early start (corpus H1-08 A1240, +85 values "
    "on H1-H7 when applied)",
    "lag_to_finished_successor": "lag on a link into a finished successor under Retained Logic: MPXJ drops an FS lag "
    "in the backward pass; P6 passes the full FS / FF lag back, the unexpired SS / SF lag, and nothing between "
    "two finished activities (corpus, +121 values)",
    "expected_finish_edge": "an expected finish before the early start or on work with an FF / SF predecessor: "
    "MPXJ ignores it; P6 sets the remaining duration to zero, or lets a later FF / SF bound win (corpus, "
    "300 activities with an expected finish)",
}


def settled_patterns(snap) -> set[str]:
    """Keys of P6_SETTLED present in ``snap``: MPXJ is known to differ from P6 there."""
    t = snap.activities.drop_duplicates("task_code").set_index("task_code")
    st, r = t["status_code"], snap.relationships
    p, s = r["pred_code"].map(st), r["succ_code"].map(st)
    out = set()
    if ((r["type"] == "SF") & (p == "TK_Active") & (s == "TK_NotStart")).any():
        out.add("sf_from_started")
    retained = snap.options.get("progressed", "retained_logic") == "retained_logic"
    if retained and ((s == "TK_Complete") & (p != "TK_Complete") & (r["lag_hr"] != 0)).any():
        out.add("lag_to_finished_successor")
    if (snap.options.get("sched") or {}).get("sched_use_expect_end_flag", "Y") != "N" and "expect_end_date" in t:
        exp = t["expect_end_date"]
        has = exp.notna() & (t["task_type"] == "TT_Task") & (t["status_code"] != "TK_Complete")
        linked = t.index.isin(r.loc[r["type"].isin(["FF", "SF"]), "succ_code"])
        before_dd = (exp < snap.data_date) if snap.data_date is not None else False
        if (has & (linked | before_dd)).any():
            out.add("expected_finish_edge")
    return out


def unresolved_patterns(snap) -> set[str]:
    """Keys of UNRESOLVED present in ``snap`` (network-wide: a difference propagates)."""
    t = snap.activities.drop_duplicates("task_code").set_index("task_code")
    st, r = t["status_code"], snap.relationships
    p, s = r["pred_code"].map(st), r["succ_code"].map(st)
    out = set()
    if ((r["type"].isin(["FF", "SF"])) & (r["lag_hr"] != 0) & (p == "TK_Complete")).any():
        out.add("ff_sf_lag_from_finished")
    if ((r["type"] == "SF") & ((s != "TK_NotStart") | (p == "TK_Complete"))).any():
        out.add("sf_progressed")
    lead = r["lag_hr"] < 0
    if (lead & ((p == "TK_Complete") | ((p == "TK_Active") & r["type"].isin(["FS", "FF"])))).any():
        out.add("lead_from_progressed")
    if ((r["type"] != "FS") & (p == "TK_Complete") & (s == "TK_Active")).any():
        out.add("finished_into_started")
    a = snap.assignments
    if not a.empty:
        rsrc = a[a["task_code"].map(t["task_type"]).eq("TT_Rsrc") & a["driving"].astype(bool)]
        own = rsrc["task_code"].map(t["clndr_id"]).astype(str)
        cal = rsrc["rsrc_clndr_id"].astype(str)
        if ((cal != "") & (cal != own)).any():
            out.add("rsrc_calendar")
        if (rsrc["relag_drtn_hr_cnt"].fillna(0) != 0).any():
            out.add("assignment_lag")
    return out


def excused_row(snap, task_code: str, field: str) -> str | None:
    """UNRESOLVED key for a single value that differs for a known reason, else None."""
    if field != "ff_hr":
        return None
    r = snap.relationships
    if ((r["pred_code"] == task_code) & (r["lag_hr"] < 0)).any():
        return "free_float_lead"
    t = snap.activities.set_index("task_code")
    if task_code in t.index and {t.at[task_code, "cstr_type"], t.at[task_code, "cstr_type2"]} & {
        "CS_MANDSTART",
        "CS_MANDFIN",
    }:
        return "free_float_mandatory"
    return None


def mpxj_inconsistent(snap, cmp: pd.DataFrame) -> set[str]:
    """Unstarted tasks where MPXJ's dates contradict themselves or the logic.

    Seen in MPXJ 16.10 / master 8c4f646 with constraints: the early finish is not
    recomputed when a Start On / Start On or After / Mandatory Start replaces the start
    (finish before start), the late start is not recomputed under a Start On or Before /
    Mandatory Finish (late start after late finish), and a Start On or After on the same
    day as the logic start moves the start before what the logic allows. Checked here:
    early and late spans equal the remaining duration; FS / SS successors start, FF / SF
    successors finish, no earlier than the relationship allows.
    """
    from ..analysis.cpm import Options, _Run

    run = _Run(snap, {}, Options.from_snapshot(snap))
    t = snap.activities.drop_duplicates("task_code").set_index("task_code")
    m = cmp.pivot_table(index="task_code", columns="field", values="mpxj", aggfunc="first")
    out: set[str] = set()
    todo = [c for c in m.index if t.at[c, "task_type"] == "TT_Task" and t.at[c, "status_code"] == "TK_NotStart"]
    for c in todo:
        ax = run.cal_ax[c]
        d = float(t.at[c, "remain_drtn_hr_cnt"] or 0) * 60
        es, ef, ls, lf = (pd.Timestamp(m.at[c, k]) for k in ("es", "ef", "ls", "lf"))
        if ax.work(ef) - ax.work(es) != d or ax.work(lf) - ax.work(ls) != d:
            out.add(c)
    links = [(p, succ, typ, lag) for succ in todo for p, typ, lag in run.preds[succ] if p in m.index and p in todo]
    for p, s, typ, lag_m in links:
        lx = run.lag_axis(p, s)
        frm = pd.Timestamp(m.at[p, "ef" if typ in ("FS", "FF") else "es"])
        to = pd.Timestamp(m.at[s, "es" if typ in ("FS", "SS") else "ef"])
        if lx.work(to) < lx.work(frm) + lag_m:
            out.add(s)
    return out


def mpxj_scheduler_source() -> str:
    """Where the PrimaveraScheduler class was loaded from (the released jar or a newer build)."""
    _start_jvm()
    from org.mpxj.cpm import PrimaveraScheduler

    return str(PrimaveraScheduler.class_.getProtectionDomain().getCodeSource().getLocation())


def mpxj_unsupported(snap) -> list[str]:
    """Scheduling options of ``snap`` that MPXJ's PrimaveraScheduler does not model."""
    o = snap.options
    s = o.get("sched", {}) or {}
    out = []
    if o.get("progressed") != "retained_logic":
        out.append(f"progressed activities scheduled with {o.get('progressed')} (MPXJ: retained logic only)")
    if s.get("sched_lag_early_start_flag", "Y") not in ("Y", ""):
        out.append("SS lag from actual start (MPXJ: early start only)")
    if s.get("sched_open_critical_flag", "N") == "Y":
        out.append("open ends critical")
    if not s.get("sched_calendar_on_relationship_lag"):
        out.append("no lag calendar stated (P6 uses the successor's, MPXJ the predecessor's)")
    if (s.get("sched_outer_depend_type") or "SD_Both") != "SD_Both":
        out.append("relationships to other projects ignored")
    a, t = snap.assignments, snap.activities
    rsrc_dep = set(t.loc[(t["task_type"] == "TT_Rsrc") & ~t["is_complete"], "task_code"])
    if not a.empty and (~a["driving"].astype(bool) & a["task_code"].isin(rsrc_dep)).any():
        out.append("resource-dependent activity with a non-driving assignment (MPXJ lets every assignment drive)")
    return out


def _jdt(v) -> pd.Timestamp | None:
    return None if v is None else pd.Timestamp(str(v))


def mpxj_schedule(path: str | Path, project_code: str | None = None) -> pd.DataFrame:
    """Recalculate ``path`` with MPXJ's PrimaveraScheduler: one row per activity (index task_code).

    Columns ``es`` (remaining early start for started work, as P6 stores it), ``ef``,
    ``ls``, ``lf``, ``tf_hr``, ``ff_hr``. Input normalisation, neutral on a real P6 export:
    the at-completion duration is set to actual + remaining (MPXJ otherwise derives it
    from the stored dates), and the non-standard TT_StartMile is read as a start milestone.
    """
    _start_jvm()
    from org.mpxj import ActivityType, Duration, TimeUnit
    from org.mpxj.cpm import PrimaveraScheduler

    path = Path(path)
    if project_code is None:
        project_code = build_snapshot(read_xer(path)).project_code
    proj = _read_project(_start_jvm(), path, project_code)
    props = proj.getProjectProperties()

    def hours(d) -> float:
        return 0.0 if d is None else float(d.convertUnits(TimeUnit.HOURS, props).getDuration())

    status = props.getStatusDate()
    for t in proj.getTasks():
        if t.getActivityID() is None:
            continue
        if t.getActivityType() is None and not t.getSummary():
            t.setActivityType(ActivityType.START_MILESTONE)
        a_s, a_f = t.getActualStart(), t.getActualFinish()
        if a_s is not None and a_f is None and status is not None and t.getSuspendDate() is None:
            # P6's actual duration: working time from the actual start to the data date (what
            # MPXJ's own reader computes first, before deriving it again from stored dates)
            end = status if status.isAfter(a_s) else a_s
            t.setActualDuration(t.getEffectiveCalendar().getWork(a_s, end, TimeUnit.HOURS))
        if t.getRemainingDuration() is not None:
            total = hours(t.getActualDuration()) + hours(t.getRemainingDuration())
            t.setDuration(Duration.getInstance(total, TimeUnit.HOURS))
    PrimaveraScheduler().schedule(proj, props.getStartDate())
    rows = {}
    for t in proj.getTasks():
        if t.getActivityID() is None or str(t.getActivityType()) == "WBS_SUMMARY":
            continue
        tf, ff = t.getTotalSlack(), t.getFreeSlack()
        rows[str(t.getActivityID())] = {
            "es": _jdt(t.getEarlyStart()),
            "ef": _jdt(t.getEarlyFinish()),
            "ls": _jdt(t.getLateStart()),
            "lf": _jdt(t.getLateFinish()),
            "tf_hr": None if tf is None else round(hours(tf), 2),
            "ff_hr": None if ff is None else round(hours(ff), 2),
            "complete": t.getActualFinish() is not None,
        }
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("task_code")


def cpm_crosscheck(path: str | Path, project_code: str | None = None) -> pd.DataFrame:
    """Three-way comparison per open activity and field: P6 (stored), xerscope, MPXJ.

    ``p6`` is what the file stores: the truth when P6 scheduled the file, otherwise
    placeholders (synthetic files), so judge ``xs_mpxj`` there. Dates agree only on the
    same clock time; float on the same number of hours.
    """
    from ..analysis.cpm import _Axes, _date_range, schedule

    path = Path(path)
    snap = build_snapshot(read_xer(path), project_code)
    axes = _Axes(snap, *_date_range(snap))
    ours = schedule(snap).frame
    theirs = mpxj_schedule(path, snap.project_code)
    t = snap.activities.drop_duplicates("task_code").set_index("task_code")
    stored = {
        "es": "early_start_date",
        "ef": "early_end_date",
        "ls": "late_start_date",
        "lf": "late_end_date",
        "tf_hr": "total_float_hr_cnt",
        "ff_hr": "free_float_hr_cnt",
    }
    rows = []
    for code in ours.index:
        if t.at[code, "is_complete"] or t.at[code, "is_loe"] or code not in theirs.index:
            continue
        ax = axes.of(t.at[code, "clndr_id"])
        for f in CPM_FIELDS:
            xs = ours.at[code, "remaining_start" if f == "es" else f]
            mp = theirs.at[code, f]
            p6 = t.at[code, stored[f]]
            rows.append(
                {
                    "task_code": code,
                    "status": t.at[code, "status"],
                    "field": f,
                    "p6": p6,
                    "xerscope": xs,
                    "mpxj": mp,
                    # MPXJ leaves some values empty (no total float on an ALAP activity)
                    "comparable": mp is not None and not pd.isna(mp),
                    "xs_mpxj": _same(xs, mp),
                    # same instant of work written differently (Friday 17:00 / Monday 08:00)
                    "xs_mpxj_work": _same(xs, mp) or _same_work(ax, xs, mp),
                    "xs_p6": _same(xs, p6),
                    "mpxj_p6": _same(mp, p6),
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "task_code",
            "status",
            "field",
            "p6",
            "xerscope",
            "mpxj",
            "comparable",
            "xs_mpxj",
            "xs_mpxj_work",
            "xs_p6",
            "mpxj_p6",
        ],  # fmt: skip
    )


def _same_work(ax, a, b) -> bool:
    if not isinstance(a, pd.Timestamp) or not isinstance(b, pd.Timestamp) or pd.isna(a) or pd.isna(b):
        return False
    return ax.work(a) == ax.work(b)


def _same(a, b) -> bool:
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return False
    if isinstance(a, pd.Timestamp) or isinstance(b, pd.Timestamp):
        return pd.Timestamp(a) == pd.Timestamp(b)
    return abs(float(a) - float(b)) < 0.01


# --- P6 itself: the held-out corpus of cpp-cpm-engine ------------------------------------------
#
# 30 sets of 12 synthetic schedules, each frozen before P6 saw it, imported into P6
# Professional 23.12.1 and scheduled with F9, with P6's early/late dates and floats read
# back from its database (tests/reference/fetch_p6_heldout.py; the protocol is in the
# corpus). That is P6 output on progressed, constrained, multi-calendar and (from H8)
# resource-dependent work, which no public export covers. P6's import re-sizes resource
