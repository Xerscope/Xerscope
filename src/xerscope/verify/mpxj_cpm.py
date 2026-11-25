"""MPXJ's PrimaveraScheduler as a second CPM engine, and the comparison of both with P6.

What P6's held-out corpus settled against MPXJ is in ``P6_SETTLED``; what no P6 output
settles yet is in ``UNRESOLVED``. xerscope follows P6; MPXJ is a hint.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..xer import build_snapshot, read_xer
from .mpxj_reader import read_project, start_jvm

# --- second CPM engine: MPXJ's PrimaveraScheduler ----------------------------------------------
#
# MPXJ (16.x) ships a CPM scheduler for P6 projects, written independently of xerscope and
# tuned by its authors against P6 output. It honours a subset of P6's scheduling options;
# a file using another one cannot be compared, and ``mpxj_unsupported`` says why. Known
# self-contradictions of MPXJ are detected by ``mpxj_inconsistent`` so a disagreement is never
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
    # Driving relationships (tests/test_driving.py). P6 does not export its Driving flag, so
    # only P6 Professional's Relationships tab settles these: read the Driving column of the
    # predecessors of corpus H1-01 A1130 (first) and of an As Late As Possible successor (second).
    "driving_held_by_data_date": "a successor whose date no link reaches (the data date or its progress "
    "sets it): MPXJ marks its latest predecessor driving, xerscope none",
    "driving_alap": "a link into an As Late As Possible activity: xerscope reads it on the early dates "
    "and may call it driving, MPXJ never does",
}


# Where the two engines differ and P6's output settled it against MPXJ (the P6 23.12 held-out
# corpus, tests/test_p6_heldout.py). xerscope follows P6; a comparison that meets one of these
# reports the difference as MPXJ's. MPXJ stays a hint everywhere else.
P6_SETTLED = {
    "sf_from_started": "SF from a started predecessor into unstarted work: MPXJ binds nothing past the data "
    "date; P6 applies the link from the predecessor's remaining early start (corpus H1-08 A1240)",
    "lag_to_finished_successor": "lag on a link into a finished successor under Retained Logic: MPXJ drops an FS lag "
    "in the backward pass; P6 passes the full FS / FF lag back, the unexpired SS / SF lag, and nothing between "
    "two finished activities (corpus H1-08 A1020, A1050)",
    "expected_finish_edge": "an expected finish before the early start or on work with an FF / SF predecessor: "
    "MPXJ ignores it; P6 sets the remaining duration to zero, or lets a later FF / SF bound win "
    "(corpus H1-02 A1170, H4-10 A1040)",
}


def settled_patterns(snapshot) -> set[str]:
    """Keys of P6_SETTLED present in ``snapshot``: MPXJ is known to differ from P6 there."""
    tasks = snapshot.by_code
    task_status = tasks["status_code"]
    links = snapshot.relationships
    predecessor_status = links["pred_code"].map(task_status)
    successor_status = links["succ_code"].map(task_status)
    patterns = set()
    if ((links["type"] == "SF") & (predecessor_status == "TK_Active") & (successor_status == "TK_NotStart")).any():
        patterns.add("sf_from_started")
    is_retained_logic = snapshot.options.get("progressed", "retained_logic") == "retained_logic"
    if (
        is_retained_logic
        and ((successor_status == "TK_Complete") & (predecessor_status != "TK_Complete") & (links["lag_hr"] != 0)).any()
    ):
        patterns.add("lag_to_finished_successor")
    uses_expected_end = (snapshot.options.get("sched") or {}).get("sched_use_expect_end_flag", "Y") != "N"
    if uses_expected_end and "expect_end_date" in tasks:
        expected_end = tasks["expect_end_date"]
        has_expected_end = (
            expected_end.notna() & (tasks["task_type"] == "TT_Task") & (tasks["status_code"] != "TK_Complete")
        )
        is_ff_sf_successor = tasks.index.isin(links.loc[links["type"].isin(["FF", "SF"]), "succ_code"])
        ends_before_data_date = (expected_end < snapshot.data_date) if snapshot.data_date is not None else False
        if (has_expected_end & (is_ff_sf_successor | ends_before_data_date)).any():
            patterns.add("expected_finish_edge")
    return patterns


def unresolved_patterns(snapshot) -> set[str]:
    """Keys of UNRESOLVED present in ``snapshot`` (network-wide: a difference propagates)."""
    tasks = snapshot.by_code
    task_status = tasks["status_code"]
    links = snapshot.relationships
    predecessor_status = links["pred_code"].map(task_status)
    successor_status = links["succ_code"].map(task_status)
    patterns = set()
    if ((links["type"].isin(["FF", "SF"])) & (links["lag_hr"] != 0) & (predecessor_status == "TK_Complete")).any():
        patterns.add("ff_sf_lag_from_finished")
    if ((links["type"] == "SF") & ((successor_status != "TK_NotStart") | (predecessor_status == "TK_Complete"))).any():
        patterns.add("sf_progressed")
    is_lead = links["lag_hr"] < 0
    if (
        is_lead
        & (
            (predecessor_status == "TK_Complete")
            | ((predecessor_status == "TK_Active") & links["type"].isin(["FS", "FF"]))
        )
    ).any():
        patterns.add("lead_from_progressed")
    if ((links["type"] != "FS") & (predecessor_status == "TK_Complete") & (successor_status == "TK_Active")).any():
        patterns.add("finished_into_started")
    assignments = snapshot.assignments
    if not assignments.empty:
        is_resource_dependent = assignments["task_code"].map(tasks["task_type"]).eq("TT_Rsrc")
        resource_dependent = assignments[is_resource_dependent & assignments["driving"].astype(bool)]
        activity_calendar_id = resource_dependent["task_code"].map(tasks["clndr_id"]).astype(str)
        resource_calendar_id = resource_dependent["rsrc_clndr_id"].astype(str)
        if ((resource_calendar_id != "") & (resource_calendar_id != activity_calendar_id)).any():
            patterns.add("rsrc_calendar")
        if (resource_dependent["relag_drtn_hr_cnt"].fillna(0) != 0).any():
            patterns.add("assignment_lag")
    return patterns


def excused_row(snapshot, task_code: str, field: str) -> str | None:
    """UNRESOLVED key for a single value that differs for a known reason, else None."""
    if field != "ff_hr":
        return None
    links = snapshot.relationships
    if ((links["pred_code"] == task_code) & (links["lag_hr"] < 0)).any():
        return "free_float_lead"
    activities = snapshot.activities.set_index("task_code")
    if task_code in activities.index and {
        activities.at[task_code, "cstr_type"],
        activities.at[task_code, "cstr_type2"],
    } & {"CS_MANDSTART", "CS_MANDFIN"}:
        return "free_float_mandatory"
    return None


def mpxj_inconsistent(snapshot, comparison: pd.DataFrame) -> set[str]:
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

    cpm_run = _Run(snapshot, {}, Options.from_snapshot(snapshot))
    tasks = snapshot.by_code
    mpxj_by_task = comparison.pivot_table(index="task_code", columns="field", values="mpxj", aggfunc="first")
    unstarted_codes = [
        code
        for code in mpxj_by_task.index
        if tasks.at[code, "task_type"] == "TT_Task" and tasks.at[code, "status_code"] == "TK_NotStart"
    ]
    wrong_span_codes = _tasks_with_wrong_span(cpm_run, tasks, mpxj_by_task, unstarted_codes)
    links = _links_between_unstarted(cpm_run, mpxj_by_task, unstarted_codes)
    return wrong_span_codes | _successors_of_violated_links(cpm_run, mpxj_by_task, links)


def _tasks_with_wrong_span(cpm_run, tasks, mpxj_by_task, unstarted_codes) -> set[str]:
    """Tasks whose MPXJ early or late span, in working minutes, is not the remaining duration."""
    wrong_span_codes: set[str] = set()
    for code in unstarted_codes:
        axis = cpm_run.cal_ax[code]
        # whole minutes, as TimeAxis.at rounds them: 8.2 h * 60 is 491.99999999999994, not 492
        remaining_minutes = round(float(tasks.at[code, "remain_drtn_hr_cnt"] or 0) * 60)
        early_start, early_finish, late_start, late_finish = (
            pd.Timestamp(mpxj_by_task.at[code, field]) for field in ("es", "ef", "ls", "lf")
        )
        if (
            axis.work(early_finish) - axis.work(early_start) != remaining_minutes
            or axis.work(late_finish) - axis.work(late_start) != remaining_minutes
        ):
            wrong_span_codes.add(code)
    return wrong_span_codes


def _links_between_unstarted(cpm_run, mpxj_by_task, unstarted_codes) -> list[tuple]:
    """(predecessor, successor, link type, lag in minutes) of the links joining two compared unstarted tasks."""
    links = []
    for successor in unstarted_codes:
        links += [
            (predecessor, successor, link_type, lag_minutes)
            for predecessor, link_type, lag_minutes in cpm_run.preds[successor]
            if predecessor in mpxj_by_task.index and predecessor in unstarted_codes
        ]
    return links


def _successors_of_violated_links(cpm_run, mpxj_by_task, links) -> set[str]:
    """Successors whose MPXJ date is earlier than the link and its lag allow."""
    violated_successors: set[str] = set()
    for predecessor, successor, link_type, lag_minutes in links:
        lag_axis = cpm_run.lag_axis(predecessor, successor)
        from_date = pd.Timestamp(mpxj_by_task.at[predecessor, "ef" if link_type in ("FS", "FF") else "es"])
        to_date = pd.Timestamp(mpxj_by_task.at[successor, "es" if link_type in ("FS", "SS") else "ef"])
        if lag_axis.work(to_date) < lag_axis.work(from_date) + round(lag_minutes):
            violated_successors.add(successor)
    return violated_successors


def mpxj_scheduler_source() -> str:
    """Where the PrimaveraScheduler class was loaded from (the released jar or a newer build)."""
    start_jvm()
    from org.mpxj.cpm import PrimaveraScheduler

    return str(PrimaveraScheduler.class_.getProtectionDomain().getCodeSource().getLocation())


def mpxj_unsupported(snapshot) -> list[str]:
    """Scheduling options of ``snapshot`` that MPXJ's PrimaveraScheduler does not model."""
    options = snapshot.options
    sched_options = options.get("sched", {}) or {}
    reasons = []
    if options.get("progressed") != "retained_logic":
        reasons.append(f"progressed activities scheduled with {options.get('progressed')} (MPXJ: retained logic only)")
    if sched_options.get("sched_lag_early_start_flag", "Y") not in ("Y", ""):
        reasons.append("SS lag from actual start (MPXJ: early start only)")
    if sched_options.get("sched_open_critical_flag", "N") == "Y":
        reasons.append("open ends critical")
    if not sched_options.get("sched_calendar_on_relationship_lag"):
        reasons.append("no lag calendar stated (P6 uses the successor's, MPXJ the predecessor's)")
    if (sched_options.get("sched_outer_depend_type") or "SD_Both") != "SD_Both":
        reasons.append("relationships to other projects ignored")
    assignments, activities = snapshot.assignments, snapshot.activities
    resource_dependent_codes = set(
        activities.loc[(activities["task_type"] == "TT_Rsrc") & ~activities["is_complete"], "task_code"]
    )
    if (
        not assignments.empty
        and (~assignments["driving"].astype(bool) & assignments["task_code"].isin(resource_dependent_codes)).any()
    ):
        reasons.append("resource-dependent activity with a non-driving assignment (MPXJ lets every assignment drive)")
    return reasons


def mpxj_schedule(path: str | Path, project_code: str | None = None) -> pd.DataFrame:
    """Recalculate ``path`` with MPXJ's PrimaveraScheduler: one row per activity (index task_code).

    Columns ``es`` (remaining early start for started work, as P6 stores it), ``ef``,
    ``ls``, ``lf``, ``tf_hr``, ``ff_hr``. Input normalisation, neutral on a real P6 export:
    the at-completion duration is set to actual + remaining (MPXJ otherwise derives it
    from the stored dates), and the non-standard TT_StartMile is read as a start milestone.
    """
    mpxj_project = _scheduled_project(path, project_code)
    rows = _schedule_rows(mpxj_project, mpxj_project.getProjectProperties())
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("task_code")


def _scheduled_project(path: str | Path, project_code: str | None):
    """Return the MPXJ project of ``path``, normalised (see ``mpxj_schedule``) and scheduled."""
    reader = start_jvm()  # first: the org.mpxj imports below need the JVM running
    from org.mpxj.cpm import PrimaveraScheduler

    path = Path(path)
    if project_code is None:
        project_code = build_snapshot(read_xer(path)).project_code
    mpxj_project = read_project(reader, path, project_code)
    mpxj_properties = mpxj_project.getProjectProperties()
    _normalise_tasks(mpxj_project, mpxj_properties)
    PrimaveraScheduler().schedule(mpxj_project, mpxj_properties.getStartDate())
    return mpxj_project


MPXJ_LINK_TYPES = {"FINISH_START": "FS", "START_START": "SS", "FINISH_FINISH": "FF", "START_FINISH": "SF"}


def mpxj_driving_links(path: str | Path, project_code: str | None = None) -> pd.DataFrame:
    """Return every relationship between two activities of ``path``, MPXJ's driving flag on each.

    ``Relation.getDriving`` is set by PrimaveraScheduler on its forward pass.
    """
    rows = []
    for mpxj_task in _scheduled_project(path, project_code).getTasks():
        for relation in mpxj_task.getPredecessors():
            predecessor, successor = relation.getPredecessorTask(), relation.getSuccessorTask()
            if predecessor.getActivityID() is None or successor.getActivityID() is None:
                continue
            link_type = str(relation.getType())
            rows.append(
                {
                    "pred_code": str(predecessor.getActivityID()),
                    "succ_code": str(successor.getActivityID()),
                    "type": MPXJ_LINK_TYPES.get(link_type, link_type),
                    "driving": bool(relation.getDriving()),
                }
            )
    return pd.DataFrame(rows, columns=["pred_code", "succ_code", "type", "driving"])


def _normalise_tasks(mpxj_project, mpxj_properties) -> None:
    """Prepare every activity of ``mpxj_project`` for scheduling, in place."""
    mpxj_status_date = mpxj_properties.getStatusDate()
    for mpxj_task in mpxj_project.getTasks():
        if mpxj_task.getActivityID() is None:
            continue
        _set_start_milestone_type(mpxj_task)
        _set_actual_duration(mpxj_task, mpxj_status_date)
        _set_total_duration(mpxj_task, mpxj_properties)


def _set_start_milestone_type(mpxj_task) -> None:
    """Read an activity with no activity type (the non-standard TT_StartMile) as a start milestone.

    A WBS node has no activity type either and keeps none: MPXJ reads it as a summary task.
    """
    from org.mpxj import ActivityType

    if mpxj_task.getActivityType() is None and not mpxj_task.getSummary():
        mpxj_task.setActivityType(ActivityType.START_MILESTONE)


def _set_actual_duration(mpxj_task, mpxj_status_date) -> None:
    """Set P6's actual duration on started, unfinished, not suspended work: working time from actual start to data date.

    MPXJ's own reader computes it first, then derives it again from the stored dates.
    """
    from org.mpxj import TimeUnit

    mpxj_actual_start = mpxj_task.getActualStart()
    if (
        mpxj_actual_start is not None
        and mpxj_task.getActualFinish() is None
        and mpxj_status_date is not None
        and mpxj_task.getSuspendDate() is None
    ):
        work_end = mpxj_status_date if mpxj_status_date.isAfter(mpxj_actual_start) else mpxj_actual_start
        mpxj_task.setActualDuration(
            mpxj_task.getEffectiveCalendar().getWork(mpxj_actual_start, work_end, TimeUnit.HOURS)
        )


def _set_total_duration(mpxj_task, mpxj_properties) -> None:
    """Set the at-completion duration to actual + remaining, when a remaining duration exists."""
    from org.mpxj import Duration, TimeUnit

    if mpxj_task.getRemainingDuration() is not None:
        actual_hr = _duration_hr(mpxj_task.getActualDuration(), mpxj_properties)
        remaining_hr = _duration_hr(mpxj_task.getRemainingDuration(), mpxj_properties)
        mpxj_task.setDuration(Duration.getInstance(actual_hr + remaining_hr, TimeUnit.HOURS))


def _duration_hr(mpxj_duration, mpxj_properties) -> float:
    """``mpxj_duration`` in hours, converted with the project's calendar settings; 0 when absent."""
    from org.mpxj import TimeUnit

    return (
        0.0
        if mpxj_duration is None
        else float(mpxj_duration.convertUnits(TimeUnit.HOURS, mpxj_properties).getDuration())
    )


def _schedule_rows(mpxj_project, mpxj_properties) -> dict[str, dict]:
    """Scheduled dates and floats by activity id; activities of type WBS Summary are left out.

    A WBS node has a row too, under its WBS code: MPXJ gives it that code as activity id.
    """
    rows = {}
    for mpxj_task in mpxj_project.getTasks():
        if mpxj_task.getActivityID() is None or str(mpxj_task.getActivityType()) == "WBS_SUMMARY":
            continue
        rows[str(mpxj_task.getActivityID())] = _schedule_row(mpxj_task, mpxj_properties)
    return rows


def _schedule_row(mpxj_task, mpxj_properties) -> dict:
    """Return the CPM_FIELDS of one scheduled task, and whether it is complete."""
    total_slack, free_slack = mpxj_task.getTotalSlack(), mpxj_task.getFreeSlack()
    return {
        "es": _timestamp(mpxj_task.getEarlyStart()),
        "ef": _timestamp(mpxj_task.getEarlyFinish()),
        "ls": _timestamp(mpxj_task.getLateStart()),
        "lf": _timestamp(mpxj_task.getLateFinish()),
        "tf_hr": None if total_slack is None else round(_duration_hr(total_slack, mpxj_properties), 2),
        "ff_hr": None if free_slack is None else round(_duration_hr(free_slack, mpxj_properties), 2),
        "complete": mpxj_task.getActualFinish() is not None,
    }


def _timestamp(mpxj_datetime) -> pd.Timestamp | None:
    return None if mpxj_datetime is None else pd.Timestamp(str(mpxj_datetime))


def cpm_crosscheck(path: str | Path, project_code: str | None = None) -> pd.DataFrame:
    """Three-way comparison per open activity and field: P6 (stored), xerscope, MPXJ.

    ``p6`` is what the file stores: the truth when P6 scheduled the file, otherwise
    placeholders (synthetic files), so judge ``xs_mpxj`` there. Dates agree only on the
    same clock time; float on the same number of hours.
    """
    from ..analysis.cpm import _Axes, _date_range, schedule

    path = Path(path)
    snapshot = build_snapshot(read_xer(path), project_code)
    axes = _Axes(snapshot, *_date_range(snapshot))
    xerscope_schedule = schedule(snapshot).frame
    mpxj_results = mpxj_schedule(path, snapshot.project_code)
    tasks = snapshot.by_code
    stored_columns = {
        "es": "early_start_date",
        "ef": "early_end_date",
        "ls": "late_start_date",
        "lf": "late_end_date",
        "tf_hr": "total_float_hr_cnt",
        "ff_hr": "free_float_hr_cnt",
    }
    rows = []
    for task_code in xerscope_schedule.index:
        if tasks.at[task_code, "is_complete"] or tasks.at[task_code, "is_loe"] or task_code not in mpxj_results.index:
            continue
        axis = axes.of(tasks.at[task_code, "clndr_id"])
        for field in CPM_FIELDS:
            xerscope_value = xerscope_schedule.at[task_code, "remaining_start" if field == "es" else field]
            mpxj_value = mpxj_results.at[task_code, field]
            p6_value = tasks.at[task_code, stored_columns[field]]
            rows.append(
                {
                    "task_code": task_code,
                    "status": tasks.at[task_code, "status"],
                    "field": field,
                    "p6": p6_value,
                    "xerscope": xerscope_value,
                    "mpxj": mpxj_value,
                    # MPXJ leaves some values empty (no total float on an ALAP activity)
                    "comparable": mpxj_value is not None and not pd.isna(mpxj_value),
                    "xs_mpxj": same_value(xerscope_value, mpxj_value),
                    # same instant of work written differently (Friday 17:00 / Monday 08:00)
                    "xs_mpxj_work": same_value(xerscope_value, mpxj_value)
                    or _is_same_work(axis, xerscope_value, mpxj_value),
                    "xs_p6": same_value(xerscope_value, p6_value),
                    "mpxj_p6": same_value(mpxj_value, p6_value),
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


def _is_same_work(axis, value, other) -> bool:
    """Return whether both are timestamps on the same instant of working time of ``axis``."""
    if not isinstance(value, pd.Timestamp) or not isinstance(other, pd.Timestamp) or pd.isna(value) or pd.isna(other):
        return False
    return axis.work(value) == axis.work(other)


def same_value(value, other) -> bool:
    """Return whether both are present and equal: timestamps to the instant, numbers within 0.01.

    The tolerance is the two decimals to which float hours are kept.
    """
    if value is None or other is None or pd.isna(value) or pd.isna(other):
        return False
    if isinstance(value, pd.Timestamp) or isinstance(other, pd.Timestamp):
        return pd.Timestamp(value) == pd.Timestamp(other)
    return abs(float(value) - float(other)) < 0.01


# --- driving relationships ---------------------------------------------------------------------


def driving_crosscheck(path: str | Path, project_code: str | None = None) -> pd.DataFrame:
    """Compare xerscope's and MPXJ's driving flag on each link between two unfinished activities.

    A finished activity drives nothing (Oracle P6 help, Activity Network); MPXJ reads links of
    finished work on their actual dates, so they are left out. Where the flags differ, ``reason``
    says why: ``mpxj_dates`` when MPXJ placed the predecessor or the
    successor elsewhere (a date difference, judged by ``cpm_crosscheck``), else an ``UNRESOLVED``
    key, else None: a difference no known case explains.
    """
    from ..analysis.cpm import _Axes, _date_range, schedule

    path = Path(path)
    snapshot = build_snapshot(read_xer(path), project_code)
    recalculated = schedule(snapshot)
    keys = ["pred_code", "succ_code", "type"]
    both = recalculated.links.merge(
        mpxj_driving_links(path, snapshot.project_code), on=keys, suffixes=("_xerscope", "_mpxj")
    ).rename(columns={"driving_xerscope": "xerscope", "driving_mpxj": "mpxj"})
    finished = set(snapshot.activities.loc[snapshot.activities["is_complete"], "task_code"])
    both = both[~both["pred_code"].isin(finished) & ~both["succ_code"].isin(finished)].reset_index(drop=True)
    moved = _codes_mpxj_places_elsewhere(
        snapshot,
        recalculated.frame,
        mpxj_schedule(path, snapshot.project_code),
        _Axes(snapshot, *_date_range(snapshot)),
    )
    driven = set(recalculated.links.loc[recalculated.links["driving"], "succ_code"])
    as_late_as_possible = _as_late_as_possible(snapshot)
    reasons = []
    for row in both.itertuples():
        reasons.append(_driving_reason(row, moved, driven, as_late_as_possible))
    return both.assign(reason=reasons)


def _driving_reason(row, moved: set[str], driven: set[str], as_late_as_possible: set[str]) -> str | None:
    """Return why the two engines' driving flags differ on ``row``.

    "" when they agree, None when no known case explains it.
    """
    if row.xerscope == row.mpxj:
        return ""
    if row.pred_code in moved or row.succ_code in moved:
        return "mpxj_dates"
    if row.succ_code in as_late_as_possible:
        return "driving_alap"
    if row.mpxj and row.succ_code not in driven:
        return "driving_held_by_data_date"
    return None


def _codes_mpxj_places_elsewhere(snapshot, frame: pd.DataFrame, mpxj_results: pd.DataFrame, axes) -> set[str]:
    """Activities whose remaining start or early finish MPXJ puts on another instant of working time."""
    tasks = snapshot.by_code
    moved = set()
    for task_code in frame.index:
        if task_code not in mpxj_results.index:
            moved.add(task_code)
            continue
        axis = axes.of(tasks.at[task_code, "clndr_id"])
        start = frame.at[task_code, "remaining_start"]
        start = frame.at[task_code, "es"] if pd.isna(start) else start
        for mine, theirs in (
            (start, mpxj_results.at[task_code, "es"]),
            (frame.at[task_code, "ef"], mpxj_results.at[task_code, "ef"]),
        ):
            if not (same_value(mine, theirs) or _is_same_work(axis, mine, theirs)):
                moved.add(task_code)
    return moved


def _as_late_as_possible(snapshot) -> set[str]:
    tasks = snapshot.activities
    alap = (tasks["cstr_type"] == "CS_ALAP") | (tasks["cstr_type2"] == "CS_ALAP")
    return set(tasks.loc[alap, "task_code"])
