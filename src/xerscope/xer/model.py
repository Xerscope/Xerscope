"""Typed, analysis-ready view of one project in one XER export (= one snapshot).

Key decisions
- Activities are identified by ``task_code`` (the P6 Activity ID). ``task_id`` is an
  internal database key that can change when a project is re-imported, so it is only
  used to resolve relationships *inside* a single file.
- The snapshot date is ``PROJECT.last_recalc_date``: that is where P6 stores the data
  date in an XER. If it is blank, P6 schedules from the planned start, so we do too.
- Durations and float are converted from hours to working days with the task's own
  calendar (``CALENDAR.day_hr_cnt``), which is what every standard threshold is
  expressed in (e.g. DCMA's 44 working days).
- P6's own scheduling options are honoured where the file has them: the critical
  definition (``PROJECT.critical_path_type`` / ``critical_drtn_hr_cnt``) and the
  calendar used for relationship lags (``SCHEDOPTIONS.sched_calendar_on_relationship_lag``).
- Percent complete follows the activity's percent-complete type (duration, physical or
  units), as P6 displays it.
- The forecast finish is the latest activity finish. ``PROJECT.scd_end_date`` is kept as
  ``scheduled_finish`` only: real P6 exports can carry a stale value there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import DEFAULT_SETTINGS, Settings
from .calendar import TimeAxis, WorkCalendar
from .parser import RawXer, XerError

TASK_DATE_COLS = [
    "act_start_date",
    "act_end_date",
    "early_start_date",
    "early_end_date",
    "late_start_date",
    "late_end_date",
    "target_start_date",
    "target_end_date",
    "restart_date",
    "reend_date",
    "expect_end_date",
    "cstr_date",
    "cstr_date2",
    "external_early_start_date",
    "external_late_end_date",
    "suspend_date",
    "resume_date",
]
TASK_NUM_COLS = [
    "total_float_hr_cnt",
    "free_float_hr_cnt",
    "remain_drtn_hr_cnt",
    "target_drtn_hr_cnt",
    "phys_complete_pct",
    "target_work_qty",
    "act_work_qty",
    "remain_work_qty",
    "target_equip_qty",
    "act_equip_qty",
    "remain_equip_qty",
]
ASSIGNMENT_DATE_COLS = [
    "restart_date",
    "reend_date",
    "rem_late_start_date",
    "rem_late_end_date",
    "act_start_date",
    "act_end_date",
    "target_start_date",
    "target_end_date",
]
ASSIGNMENT_NUM_COLS = [
    "target_qty",
    "act_reg_qty",
    "act_ot_qty",
    "remain_qty",
    "remain_qty_per_hr",
    "target_qty_per_hr",
    "relag_drtn_hr_cnt",
    "target_lag_drtn_hr_cnt",
]

# Labour hours and nonlabour units per activity (Budgeted / Actual / Remaining, as P6 names them)
LABOR_COLS = [
    "labor_budget_hr",
    "labor_actual_hr",
    "labor_remaining_hr",
    "nonlabor_budget_qty",
    "nonlabor_actual_qty",
    "nonlabor_remaining_qty",
]

STATUS = {"TK_NotStart": "Not started", "TK_Active": "In progress", "TK_Complete": "Complete"}
TASK_TYPE = {
    "TT_Task": "Task dependent",
    "TT_Rsrc": "Resource dependent",
    "TT_LOE": "Level of effort",
    "TT_Mile": "Start milestone",
    "TT_StartMile": "Start milestone",  # non-standard alias seen in third-party exports
    "TT_FinMile": "Finish milestone",
    "TT_WBS": "WBS summary",
}
START_MILESTONES = frozenset({"TT_Mile", "TT_StartMile"})
LAG_CALENDARS = {"rcal_Predecessor", "rcal_Successor", "rcal_24Hour", "rcal_ProjDefault"}
REL_TYPE = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}
# DCMA "hard" constraints = they can stop the network from moving (MSO, MFO, SNLT, FNLT).
HARD_CONSTRAINTS = frozenset({"CS_MSO", "CS_MSOB", "CS_MEO", "CS_MEOB", "CS_MANDSTART", "CS_MANDFIN"})
START_CONSTRAINTS = frozenset({"CS_MSO", "CS_MSOA", "CS_MSOB", "CS_MANDSTART"})
CONSTRAINT = {
    "CS_MSO": "Start on",
    "CS_MSOA": "Start on or after",
    "CS_MSOB": "Start on or before",
    "CS_MEO": "Finish on",
    "CS_MEOA": "Finish on or after",
    "CS_MEOB": "Finish on or before",
    "CS_MANDSTART": "Mandatory start",
    "CS_MANDFIN": "Mandatory finish",
    "CS_ALAP": "As late as possible",
}


def _blank_to_na(s: pd.Series) -> pd.Series:
    return s.where(s.astype(str).str.strip() != "", None)


def forecast_dates(t: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """P6's current forecast dates of a TASK frame: the remaining early dates (restart /
    reend, what P6 shows and what leveling moves), the early dates when an exporter left
    them blank. The one reading of "when is this scheduled" for the model and the checks."""
    return (
        t["restart_date"].combine_first(t["early_start_date"]),
        t["reend_date"].combine_first(t["early_end_date"]),
    )


def to_datetime(s: pd.Series) -> pd.Series:
    # XER dates are "YYYY-MM-DD HH:MM"; ISO8601 also tolerates exporters adding seconds.
    return pd.to_datetime(_blank_to_na(s), format="ISO8601", errors="coerce")


def to_number(s: pd.Series) -> pd.Series:
    return pd.to_numeric(_blank_to_na(s), errors="coerce")


def _parse_date(value: object) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and np.isnan(value)) or str(value).strip() == "":
        return None
    ts = pd.to_datetime(str(value), format="ISO8601", errors="coerce")
    return None if pd.isna(ts) else ts


def percent_complete(t: pd.DataFrame) -> pd.Series:
    """Activity % complete as P6 displays it, chosen by ``complete_pct_type``.

    - CP_Phys:  phys_complete_pct (entered by the planner)
    - CP_Drtn:  (original - remaining) / original; 100 once the activity is complete
    - CP_Units: actual units / (actual + remaining units), labour + non-labour
    Where the chosen basis cannot be computed (no duration, no units) the stored
    physical % is used, then the status. Checked against MPXJ's P6 8.4 test export
    and xerlock's rules (tests/test_reference.py).
    """

    def num(c: str) -> pd.Series:
        return pd.to_numeric(t[c], errors="coerce") if c in t else pd.Series(np.nan, index=t.index)

    kind = t["complete_pct_type"] if "complete_pct_type" in t else pd.Series("", index=t.index)
    complete = t["status_code"] == "TK_Complete"
    phys = num("phys_complete_pct")
    orig, rem = num("target_drtn_hr_cnt"), num("remain_drtn_hr_cnt")
    pct_dur = ((orig - rem) / orig * 100).where(orig > 0).clip(lower=0)
    pct_dur = pct_dur.mask(complete, 100.0)
    act_u = num("act_work_qty").fillna(0) + num("act_equip_qty").fillna(0)
    tot_u = act_u + num("remain_work_qty").fillna(0) + num("remain_equip_qty").fillna(0)
    pct_units = (act_u / tot_u * 100).where(tot_u > 0)
    pct = pd.Series(
        np.select([kind == "CP_Drtn", kind == "CP_Units"], [pct_dur, pct_units], default=phys),
        index=t.index,
        dtype=float,
    )
    pct = pct.fillna(phys).fillna(complete.map({True: 100.0, False: 0.0}))
    return pct.clip(0, 100).round(2)


def _ensure_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df


@dataclass
class Snapshot:
    source: str
    project_id: str
    project_code: str
    project_name: str
    data_date: pd.Timestamp | None
    finish_date: pd.Timestamp | None  # latest activity finish = forecast finish
    planned_start: pd.Timestamp | None
    export_date: str | None
    tasks: pd.DataFrame
    relationships: pd.DataFrame
    wbs: pd.DataFrame
    calendars: pd.DataFrame
    assignments: pd.DataFrame  # TASKRSRC rows, may be empty
    projects_in_file: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scheduled_finish: pd.Timestamp | None = None  # PROJECT.scd_end_date, as stored
    options: dict = field(default_factory=dict)  # P6 scheduling options that affect results
    work_calendars: dict[str, WorkCalendar] = field(default_factory=dict)
    project_clndr_id: str = ""
    expenses: pd.DataFrame = field(default_factory=pd.DataFrame)  # PROJCOST rows, may be empty
    external_tasks: pd.DataFrame = field(default_factory=pd.DataFrame)  # other projects' linked tasks
    external_links: pd.DataFrame = field(default_factory=pd.DataFrame)  # links to/from them

    def calendar(self, clndr_id: str | None = None) -> WorkCalendar:
        """Calendar by id; the project's default calendar when id is blank or unknown."""
        for cid in (clndr_id, self.project_clndr_id):
            if cid and cid in self.work_calendars:
                return self.work_calendars[cid]
        default = next((c for c in self.work_calendars.values()), None)
        return default or WorkCalendar.standard()

    def work_hours(self, clndr: pd.Series, a: pd.Series, b: pd.Series) -> pd.Series:
        """Working hours from ``a`` to ``b``, row by row, on each row's calendar.

        Exact to the minute (the CPM's TimeAxis); a blank or unknown calendar id falls back
        to the project calendar; NaN where a date is missing; negative when ``b < a``.
        """
        out = pd.Series(np.nan, index=a.index, dtype=float)
        ok = a.notna() & b.notna()
        if not ok.any():
            return out
        lo = min(a[ok].min(), b[ok].min()).date()
        hi = max(a[ok].max(), b[ok].max()).date()
        cal_id = clndr[ok].map(lambda c: self.calendar(c if isinstance(c, str) else None).clndr_id)
        for cid, idx in cal_id.groupby(cal_id).groups.items():
            ax = TimeAxis(self.calendar(cid or None), lo, hi)
            out[idx] = (ax.work_many(b[idx]) - ax.work_many(a[idx])) / 60
        return out

    def working_days(self, clndr: pd.Series, a: pd.Series, b: pd.Series) -> pd.Series:
        """``work_hours`` in days of each row's calendar (its hours per day)."""
        hpd = clndr.map(lambda c: self.calendar(c if isinstance(c, str) else None).hours_per_day)
        return self.work_hours(clndr, a, b) / hpd.astype(float)

    @property
    def label(self) -> str:
        dd = self.data_date.strftime("%Y-%m-%d") if self.data_date is not None else "no data date"
        return f"{dd} · {self.source}"

    @property
    def activities(self) -> pd.DataFrame:
        """Tasks without WBS-summary rows: what every count and chart should use."""
        return self.tasks[~self.tasks["is_wbs_summary"]]


def _wbs_frame(raw: RawXer, proj_id: str) -> tuple[pd.DataFrame, str | None]:
    wbs = raw.table("PROJWBS")
    if wbs.empty:
        return pd.DataFrame(
            columns=["wbs_id", "wbs_code", "wbs_name", "wbs_l1", "wbs_sort", "ev_compute_type", "ev_user_pct"]
        ), None
    wbs = _ensure_cols(
        wbs[wbs["proj_id"] == proj_id].copy(),
        ["parent_wbs_id", "proj_node_flag", "seq_num", "wbs_short_name", "wbs_name", "ev_compute_type", "ev_user_pct"],
    )
    by_id = wbs.set_index("wbs_id")
    proj_node = wbs.loc[wbs["proj_node_flag"] == "Y"]
    project_name = proj_node["wbs_name"].iloc[0] if not proj_node.empty else None

    def lineage(wid: str) -> list[str]:
        chain: list[str] = []
        seen: set[str] = set()
        while wid in by_id.index and wid not in seen:
            seen.add(wid)
            row = by_id.loc[wid]
            if row["proj_node_flag"] == "Y":
                break
            chain.append(wid)
            wid = row["parent_wbs_id"]
        return chain[::-1]

    seq = pd.to_numeric(by_id["seq_num"], errors="coerce").fillna(0).astype(int)
    codes, l1, sort = [], [], []
    for wid in wbs["wbs_id"]:
        chain = lineage(wid)
        codes.append(".".join(by_id.loc[c, "wbs_short_name"] for c in chain))
        # P6 orders WBS siblings by seq_num, not alphabetically
        sort.append(".".join(f"{seq[c]:06d}" for c in chain))
        top = chain[0] if chain else None
        l1.append(f"{by_id.loc[top, 'wbs_short_name']} · {by_id.loc[top, 'wbs_name']}" if top else "")
    wbs["wbs_code"] = codes
    wbs["wbs_l1"] = l1
    wbs["wbs_sort"] = sort
    return wbs, project_name


def _assignments(raw: RawXer, pid: str, t: pd.DataFrame) -> pd.DataFrame:
    """TASKRSRC rows of the project, typed, with each resource's type, name and calendar.

    ``rsrc_type``: RT_Labor / RT_Equip (nonlabor) / RT_Mat, from TASKRSRC (P6 8+) else RSRC;
    "role" for a role assigned without a resource. ``driving`` = "Drive activity dates"
    (rollup_dates_flag). ``rsrc_clndr_id`` is the calendar a resource-dependent activity's
    assignment is scheduled on.
    """
    asg = raw.table("TASKRSRC")
    cols = (
        [
            "taskrsrc_id",
            "task_id",
            "task_code",
            "rsrc_id",
            "role_id",
            "rsrc_type",
            "rsrc_name",
            "rsrc_short_name",
            "rsrc_clndr_id",
            "driving",
            "act_qty",
        ]
        + ASSIGNMENT_NUM_COLS
        + ASSIGNMENT_DATE_COLS
    )
    if asg.empty:
        return pd.DataFrame(columns=cols)
    asg = _ensure_cols(
        asg[asg["proj_id"] == pid].copy() if "proj_id" in asg.columns else asg.copy(),
        ["taskrsrc_id", "rsrc_id", "role_id", "rsrc_type", "rollup_dates_flag"]
        + ASSIGNMENT_NUM_COLS
        + ASSIGNMENT_DATE_COLS,
    )
    asg = asg[asg["task_id"].isin(t["task_id"])]
    asg["task_code"] = asg["task_id"].map(t.set_index("task_id")["task_code"])
    for c in ASSIGNMENT_NUM_COLS:
        asg[c] = to_number(asg[c])
    for c in ASSIGNMENT_DATE_COLS:
        asg[c] = to_datetime(asg[c])
    asg["act_qty"] = asg["act_reg_qty"].fillna(0) + asg["act_ot_qty"].fillna(0)
    rsrc = _ensure_cols(
        raw.table("RSRC").copy(), ["rsrc_id", "rsrc_type", "rsrc_name", "rsrc_short_name", "clndr_id"]
    ).set_index("rsrc_id")
    rsrc = rsrc[~rsrc.index.duplicated()]
    own_type = asg["rsrc_type"].astype(object)
    mapped = asg["rsrc_id"].map(rsrc["rsrc_type"]).astype(object)
    asg["rsrc_type"] = own_type.where(own_type.astype(str).str.strip() != "", mapped).fillna("").astype(str)
    role_only = (asg["rsrc_id"].astype(str).str.strip() == "") & (asg["role_id"].astype(str).str.strip() != "")
    asg.loc[role_only, "rsrc_type"] = "role"
    asg["rsrc_name"] = asg["rsrc_id"].map(rsrc["rsrc_name"]).astype(object)
    asg["rsrc_short_name"] = asg["rsrc_id"].map(rsrc["rsrc_short_name"]).astype(object)
    roles = raw.table("ROLES")
    if not roles.empty and {"role_id", "role_name"} <= set(roles.columns):
        asg.loc[role_only, "rsrc_name"] = asg.loc[role_only, "role_id"].map(roles.set_index("role_id")["role_name"])
    asg["rsrc_clndr_id"] = asg["rsrc_id"].map(rsrc["clndr_id"]).astype(object).fillna("").astype(str)
    asg["driving"] = asg["rollup_dates_flag"] != "N"  # P6's default: assignments drive dates
    return asg[cols].reset_index(drop=True)


def build_snapshot(
    raw: RawXer,
    project_code: str | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> Snapshot:
    """Turn a parsed XER into a typed Snapshot for one project.

    If the file contains several projects, ``project_code`` selects one; otherwise the
    project with the most activities is used and a warning is recorded.
    """
    proj = raw.table("PROJECT")
    task_all = raw.table("TASK")
    if proj.empty or task_all.empty:
        raise XerError(f"{raw.source}: PROJECT or TASK table missing")

    counts = task_all["proj_id"].value_counts()
    proj = _ensure_cols(
        proj[proj["proj_id"].isin(counts.index)].copy(),
        [
            "proj_short_name",
            "last_recalc_date",
            "plan_start_date",
            "scd_end_date",
            "clndr_id",
            "critical_path_type",
            "critical_drtn_hr_cnt",
            "plan_end_date",
        ],
    )
    if proj.empty:
        raise XerError(f"{raw.source}: no project owns any activity")
    warnings = list(raw.warnings)
    codes = proj["proj_short_name"].tolist()

    if project_code:
        sel = proj[proj["proj_short_name"] == project_code]
        if sel.empty:
            raise XerError(f"{raw.source}: project {project_code!r} not found (has {codes})")
        prow = sel.iloc[0]
    else:
        proj["_n"] = proj["proj_id"].map(counts)
        prow = proj.sort_values("_n", ascending=False).iloc[0]
        if len(proj) > 1:
            warnings.append(f"{raw.source}: {len(proj)} projects in file, using {prow['proj_short_name']}")

    pid = prow["proj_id"]
    planned_start = _parse_date(prow["plan_start_date"])
    data_date = _parse_date(prow["last_recalc_date"]) or planned_start
    if data_date is None:
        warnings.append(f"{raw.source}: no data date (last_recalc_date / plan_start_date blank)")

    # Calendars -> hours per working day
    cal = raw.table("CALENDAR")
    if not cal.empty:
        cal = _ensure_cols(cal.copy(), ["clndr_name", "day_hr_cnt", "week_hr_cnt", "clndr_data"])
        cal["day_hr_cnt"] = to_number(cal["day_hr_cnt"])
        hpd = cal.set_index("clndr_id")["day_hr_cnt"]
        work_cals = {
            str(r["clndr_id"]): WorkCalendar.from_row(r, settings.default_hours_per_day) for _, r in cal.iterrows()
        }
        cal = cal.drop(columns=["clndr_data"])  # parsed above; the blob is large
    else:
        hpd = pd.Series(dtype=float)
        work_cals = {}

    wbs, project_name = _wbs_frame(raw, pid)

    # P6 scheduling options that change how stored numbers must be read
    sched = raw.table("SCHEDOPTIONS")
    # Oracle (P6 Professional 24, Schedule Options > General): "If you do not select a
    # calendar, Successor Activity Calendar is used to calculate lag."
    lag_cal = "rcal_Successor"
    sched_row: dict[str, str] = {}
    if not sched.empty:
        rows = sched[sched["proj_id"] == pid] if "proj_id" in sched.columns else sched
        sched_row = rows.iloc[0].to_dict() if not rows.empty else {}
        if sched_row.get("sched_calendar_on_relationship_lag") in LAG_CALENDARS:
            lag_cal = sched_row["sched_calendar_on_relationship_lag"]
    # Retained logic / progress override / actual dates: SCHEDOPTIONS stores two flags;
    # both "N" is Actual Dates (read the same way by MPXJ's TableProjectReader).
    rl, po = sched_row.get("sched_retained_logic", ""), sched_row.get("sched_progress_override", "")
    progressed = (
        "progress_override"
        if po == "Y" and rl != "Y"
        else "actual_dates"
        if rl == "N" and po == "N"
        else "retained_logic"
    )
    crit_type = prow["critical_path_type"] or "CT_TotFloat"
    crit_hrs = to_number(pd.Series([prow["critical_drtn_hr_cnt"]])).iloc[0]
    options = {
        "lag_calendar": lag_cal,
        "progressed": progressed,
        "critical_path_type": crit_type,
        "critical_float_hr": None if pd.isna(crit_hrs) else float(crit_hrs),
        "has_schedoptions": not sched.empty,
        "sched": sched_row,  # the raw SCHEDOPTIONS row: read by analysis.cpm
        "must_finish_by": _parse_date(prow["plan_end_date"]),
    }

    # --- tasks ---------------------------------------------------------------
    t = _ensure_cols(
        task_all[task_all["proj_id"] == pid].copy(),
        [
            "task_code",
            "task_name",
            "task_type",
            "status_code",
            "wbs_id",
            "clndr_id",
            "cstr_type",
            "cstr_type2",
            "driving_path_flag",
            "complete_pct_type",
        ]
        + TASK_DATE_COLS
        + TASK_NUM_COLS,
    )
    for c in TASK_DATE_COLS:
        t[c] = to_datetime(t[c])
    for c in TASK_NUM_COLS:
        t[c] = to_number(t[c])

    t["hours_per_day"] = t["clndr_id"].map(hpd).astype(float).replace(0, np.nan).fillna(settings.default_hours_per_day)
    t["status"] = t["status_code"].map(STATUS).fillna(t["status_code"])
    t["type"] = t["task_type"].map(TASK_TYPE).fillna(t["task_type"])
    t["is_complete"] = t["status_code"] == "TK_Complete"
    t["is_started"] = t["status_code"] != "TK_NotStart"
    t["is_start_milestone"] = t["task_type"].isin(START_MILESTONES)
    t["is_milestone"] = t["is_start_milestone"] | (t["task_type"] == "TT_FinMile")
    if (t["task_type"] == "TT_StartMile").any():
        warnings.append(f"{raw.source}: non-standard task_type TT_StartMile read as a start milestone")
    t["is_loe"] = t["task_type"] == "TT_LOE"
    t["is_wbs_summary"] = t["task_type"] == "TT_WBS"

    # P6's Start / Finish columns (Oracle, "Dates Columns of the Activity Table"): the actual
    # date once there is one, else the remaining early date once scheduled, else planned.
    fc_start, fc_finish = forecast_dates(t)
    t["start"] = t["act_start_date"].combine_first(fc_start).combine_first(t["target_start_date"])
    t["finish"] = t["act_end_date"].combine_first(fc_finish).combine_first(t["target_end_date"])

    t["total_float_d"] = (t["total_float_hr_cnt"] / t["hours_per_day"]).where(~t["is_complete"])
    t["free_float_d"] = (t["free_float_hr_cnt"] / t["hours_per_day"]).where(~t["is_complete"])
    t["remaining_d"] = t["remain_drtn_hr_cnt"] / t["hours_per_day"]
    t["original_d"] = t["target_drtn_hr_cnt"] / t["hours_per_day"]
    t["on_longest_path"] = t["driving_path_flag"] == "Y"
    # Critical as P6 defines it for this project: longest path, or total float <= threshold.
    if crit_type == "CT_DrivPath":
        crit = t["on_longest_path"]
    elif options["critical_float_hr"] is not None:
        crit = t["total_float_hr_cnt"] <= options["critical_float_hr"]
    else:
        crit = t["total_float_d"] <= settings.critical_float_days
    # LOE is included, as in P6's own Critical flag (DCMA populations exclude LOE separately).
    t["is_critical"] = ~t["is_complete"] & ~t["is_wbs_summary"] & crit.fillna(False)

    t["pct_complete"] = percent_complete(t)
    t["has_hard_constraint"] = t["cstr_type"].isin(HARD_CONSTRAINTS) | t["cstr_type2"].isin(HARD_CONSTRAINTS)

    if not wbs.empty:
        # EV technique: set per WBS element in P6 (Earned Value settings of the WBS)
        t = t.merge(
            wbs[["wbs_id", "wbs_code", "wbs_l1", "wbs_sort", "ev_compute_type", "ev_user_pct"]], on="wbs_id", how="left"
        )
    else:
        t["wbs_code"] = t["wbs_l1"] = t["wbs_sort"] = t["ev_compute_type"] = t["ev_user_pct"] = ""
    cols = ["wbs_code", "wbs_l1", "wbs_sort", "ev_compute_type", "ev_user_pct"]
    t[cols] = t[cols].fillna("")

    dupes = t["task_code"][t["task_code"].duplicated()].unique()
    if len(dupes):
        warnings.append(f"{raw.source}: duplicate activity IDs {list(dupes)[:5]}; history joins may be wrong")

    # --- relationships ---------------------------------------------------------
    rel = raw.table("TASKPRED")
    if not rel.empty:
        rel = _ensure_cols(rel[rel["proj_id"] == pid].copy(), ["pred_proj_id", "pred_type", "lag_hr_cnt"])
        all_tasks = _ensure_cols(task_all.copy(), ["clndr_id"])
        code_by_id = all_tasks.set_index("task_id")["task_code"]
        hpd_by_id = (
            all_tasks.set_index("task_id")["clndr_id"]
            .map(hpd)
            .astype(float)
            .replace(0, np.nan)
            .fillna(settings.default_hours_per_day)
        )
        rel["succ_code"] = rel["task_id"].map(code_by_id)
        rel["pred_code"] = rel["pred_task_id"].map(code_by_id)
        rel["type"] = rel["pred_type"].map(REL_TYPE).fillna(rel["pred_type"])
        rel["lag_hr"] = to_number(rel["lag_hr_cnt"]).fillna(0.0)
        # Lag hours -> days. Oracle: "Lag entered in a unit other than hours is converted
        # to hours based on the predecessor activity's calendar", whatever calendar the lag
        # is then scheduled on (that one is the CPM's business, analysis/cpm.py).
        lag_hpd = rel["pred_task_id"].map(hpd_by_id)
        rel["lag_d"] = rel["lag_hr"] / lag_hpd.astype(float).fillna(settings.default_hours_per_day)
        rel["is_external"] = rel["pred_proj_id"].ne(pid) & rel["pred_proj_id"].ne("")
        # A predecessor in another project of the same file is named as in external_links:
        # its own Activity ID may also exist here, and would read as a link from that one.
        ext_in_file = rel["is_external"] & rel["pred_code"].notna()
        rel.loc[ext_in_file, "pred_code"] = "[ext]" + rel.loc[ext_in_file, "pred_task_id"].astype(str)
        # A predecessor with no TASK row: a link to another project (P6 exports the link,
        # not the other project's activities) or a corrupt link. Either way it is not logic
        # that can be scheduled; the external ones still count as "has a predecessor" below.
        ext_pred = set(rel.loc[rel["is_external"], "task_id"])
        lost = rel["succ_code"].isna() | rel["pred_code"].isna()
        if (lost & ~rel["is_external"]).any():
            warnings.append(
                f"{raw.source}: {int((lost & ~rel['is_external']).sum())} relationship(s) to an activity "
                "not in the file; ignored by the schedule and the checks"
            )
        rel = rel[~lost].copy()
    else:
        rel = pd.DataFrame(
            columns=["task_id", "pred_task_id", "succ_code", "pred_code", "type", "lag_hr", "lag_d", "is_external"]
        )
        ext_pred = set()

    # Links to other projects: P6's logic check lets them pass.
    all_rel = raw.table("TASKPRED")
    ext_succ: set = set()
    if not all_rel.empty and "proj_id" in all_rel.columns:
        ext_succ = set(
            all_rel.loc[(all_rel["proj_id"] != pid) & all_rel["pred_task_id"].isin(t["task_id"]), "pred_task_id"]
        )
    t["has_external_pred"] = t["task_id"].isin(ext_pred)
    t["has_external_succ"] = t["task_id"].isin(ext_succ)
    # Their counterparts in other projects, with the dates P6 stored for them: the CPM
    # uses them as fixed dates, as P6 does when relationships to other projects count.
    ext_links = pd.DataFrame(columns=["pred_code", "succ_code", "type", "lag_hr", "direction"])
    ext_tasks = pd.DataFrame()
    if not all_rel.empty and "proj_id" in all_rel.columns:
        ar = _ensure_cols(all_rel.copy(), ["pred_proj_id", "pred_type", "lag_hr_cnt"])
        out_ = ar[(ar["proj_id"] != pid) & ar["pred_task_id"].isin(t["task_id"])]
        in_ = rel[rel["is_external"].astype(bool)] if not rel.empty else rel
        other_ids = set(out_["task_id"]) | set(in_["pred_task_id"] if not in_.empty else [])
        if other_ids:
            ot = _ensure_cols(
                task_all[task_all["task_id"].isin(other_ids)].copy(),
                ["task_code", "status_code", "clndr_id"] + TASK_DATE_COLS,
            )
            for c in TASK_DATE_COLS:
                ot[c] = to_datetime(ot[c])
            ot["task_code"] = ot["task_id"].map(lambda i: f"[ext]{i}")
            ext_tasks = ot
            ext_code = ot.set_index("task_id")["task_code"]
            own_code = t.set_index("task_id")["task_code"]
            ext_links = pd.concat(
                [
                    pd.DataFrame(
                        {
                            "pred_code": in_["pred_task_id"].map(ext_code),
                            "succ_code": in_["succ_code"],
                            "type": in_["type"],
                            "lag_hr": in_["lag_hr"],
                            "direction": "in",
                        }
                    ),
                    pd.DataFrame(
                        {
                            "pred_code": out_["pred_task_id"].map(own_code),
                            "succ_code": out_["task_id"].map(ext_code),
                            "type": out_["pred_type"].map(REL_TYPE),
                            "lag_hr": to_number(out_["lag_hr_cnt"]).fillna(0.0),
                            "direction": "out",
                        }
                    ),
                ],
                ignore_index=True,
            ).dropna(subset=["pred_code", "succ_code"])

    # --- resource assignments, labour hours, expenses ------------------------------
    asg = _assignments(raw, pid, t)
    t["has_resource"] = t["task_id"].isin(asg["task_id"])

    # Labour hours: P6 keeps the activity totals on TASK (Budgeted / Actual / Remaining
    # Labor Units; nonlabor in *_equip_qty). Older or partial exports only have the
    # assignments: sum them by resource type (roles count as labour, as in P6).
    if t["target_work_qty"].notna().any():
        t["labor_budget_hr"] = t["target_work_qty"].fillna(0.0)
        t["labor_actual_hr"] = t["act_work_qty"].fillna(0.0)
        t["labor_remaining_hr"] = t["remain_work_qty"].fillna(0.0)
        t["nonlabor_budget_qty"] = t["target_equip_qty"].fillna(0.0)
        t["nonlabor_actual_qty"] = t["act_equip_qty"].fillna(0.0)
        t["nonlabor_remaining_qty"] = t["remain_equip_qty"].fillna(0.0)
        labor_source = "TASK"
    elif not asg.empty:
        for prefix, kinds in (("labor", ("RT_Labor", "role", "")), ("nonlabor", ("RT_Equip",))):
            part = asg[asg["rsrc_type"].isin(kinds)]
            g = part.groupby("task_id")
            unit = "hr" if prefix == "labor" else "qty"
            t[f"{prefix}_budget_{unit}"] = t["task_id"].map(g["target_qty"].sum()).fillna(0.0)
            t[f"{prefix}_actual_{unit}"] = t["task_id"].map(g["act_qty"].sum()).fillna(0.0)
            t[f"{prefix}_remaining_{unit}"] = t["task_id"].map(g["remain_qty"].sum()).fillna(0.0)
        labor_source = "TASKRSRC"
    else:
        for c in LABOR_COLS:
            t[c] = 0.0
        labor_source = "none"
    options["labor_source"] = labor_source

    # Leveling with "preserve scheduled early and late dates" leaves the remaining early
    # dates (restart/reend) apart from the early dates; a plain CPM cannot reproduce them.
    open_t = t[t["status_code"] != "TK_Complete"]
    lev = (
        open_t["restart_date"].notna()
        & open_t["early_start_date"].notna()
        & (open_t["restart_date"] != open_t["early_start_date"])
    )
    if lev.any():
        warnings.append(
            f"{raw.source}: {int(lev.sum())} open activities have a remaining early start "
            "different from their early start (resource leveling?)"
        )

    cost = raw.table("PROJCOST")
    if not cost.empty and "task_id" in cost.columns:
        cost = cost[cost["proj_id"] == pid].copy() if "proj_id" in cost.columns else cost.copy()
    else:
        cost = pd.DataFrame(columns=["task_id"])
    t["has_expense"] = t["task_id"].isin(cost["task_id"])
    t["constraint"] = t["cstr_type"].map(CONSTRAINT).fillna(t["cstr_type"])

    acts = t[~t["is_wbs_summary"]]
    finish = acts["finish"].max() if acts["finish"].notna().any() else None
    scheduled_finish = _parse_date(prow["scd_end_date"])
    if finish is not None and scheduled_finish is not None and abs(scheduled_finish - finish) > pd.Timedelta(days=1):
        warnings.append(
            f"{raw.source}: PROJECT.scd_end_date {scheduled_finish:%Y-%m-%d} differs from the "
            f"latest activity finish {finish:%Y-%m-%d}; using the activities"
        )

    return Snapshot(
        source=raw.source,
        project_id=pid,
        project_code=prow["proj_short_name"],
        project_name=project_name or prow["proj_short_name"],
        data_date=data_date,
        finish_date=finish,
        planned_start=planned_start,
        export_date=raw.export_date,
        tasks=t.reset_index(drop=True),
        relationships=rel.reset_index(drop=True),
        wbs=wbs,
        calendars=cal,
        assignments=asg.reset_index(drop=True),
        projects_in_file=codes,
        warnings=warnings,
        scheduled_finish=scheduled_finish,
        options=options,
        work_calendars=work_cals,
        external_tasks=ext_tasks.reset_index(drop=True),
        external_links=ext_links.reset_index(drop=True),
        project_clndr_id=str(prow["clndr_id"] or ""),
        expenses=cost.reset_index(drop=True),
    )
