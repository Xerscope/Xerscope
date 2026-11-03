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
from functools import cached_property
from operator import attrgetter

import numpy as np
import pandas as pd

from ..config import DATE_FMT, DEFAULT_SETTINGS, Settings
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


def _blank_to_na(values: pd.Series) -> pd.Series:
    return values.where(values.astype(str).str.strip() != "", None)


def forecast_dates(tasks: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """P6's current forecast dates of a TASK frame: the remaining early dates (restart /
    reend, what P6 shows and what leveling moves), the early dates when an exporter left
    them blank. The one reading of "when is this scheduled" for the model and the checks."""
    return (
        tasks["restart_date"].combine_first(tasks["early_start_date"]),
        tasks["reend_date"].combine_first(tasks["early_end_date"]),
    )


def to_datetime(values: pd.Series) -> pd.Series:
    # XER dates are "YYYY-MM-DD HH:MM"; ISO8601 also tolerates exporters adding seconds.
    return pd.to_datetime(_blank_to_na(values), format="ISO8601", errors="coerce")


def to_number(values: pd.Series) -> pd.Series:
    return pd.to_numeric(_blank_to_na(values), errors="coerce")


def _parse_date(value: object) -> pd.Timestamp | None:
    timestamp = to_datetime(pd.Series([value])).iloc[0]
    return None if pd.isna(timestamp) else timestamp


def percent_complete(tasks: pd.DataFrame) -> pd.Series:
    """Activity % complete as P6 displays it, chosen by ``complete_pct_type``.

    - CP_Phys:  phys_complete_pct (entered by the planner)
    - CP_Drtn:  (original - remaining) / original; 100 once the activity is complete
    - CP_Units: actual units / (actual + remaining units), labour + non-labour
    Where the chosen basis cannot be computed (no duration, no units) the stored
    physical % is used, then the status. Checked against MPXJ's P6 8.4 test export
    and xerlock's rules (tests/test_reference.py).
    """

    def number(column: str) -> pd.Series:
        if column in tasks:
            return pd.to_numeric(tasks[column], errors="coerce")
        return pd.Series(np.nan, index=tasks.index)

    kind = tasks["complete_pct_type"] if "complete_pct_type" in tasks else pd.Series("", index=tasks.index)
    complete = tasks["status_code"] == "TK_Complete"
    physical = number("phys_complete_pct")
    original, remaining = number("target_drtn_hr_cnt"), number("remain_drtn_hr_cnt")
    by_duration = ((original - remaining) / original * 100).where(original > 0).clip(lower=0)
    by_duration = by_duration.mask(complete, 100.0)
    actual_units = number("act_work_qty").fillna(0) + number("act_equip_qty").fillna(0)
    total_units = actual_units + number("remain_work_qty").fillna(0) + number("remain_equip_qty").fillna(0)
    by_units = (actual_units / total_units * 100).where(total_units > 0)
    percent = pd.Series(
        np.select([kind == "CP_Drtn", kind == "CP_Units"], [by_duration, by_units], default=physical),
        index=tasks.index,
        dtype=float,
    )
    percent = percent.fillna(physical).fillna(complete.map({True: 100.0, False: 0.0}))
    return percent.clip(0, 100).round(2)


def _ensure_cols(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    return frame


def _require(frame: pd.DataFrame, source: str, table: str, columns: list[str]) -> None:
    """Raise a XerError for the first of ``columns`` that ``table`` lacks (identity columns: no default)."""
    for column in columns:
        if column not in frame.columns:
            raise XerError(f"{source}: table {table} has no column {column}")


def _task_table(raw: RawXer, projects: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    """TASK with the identity columns checked; a missing proj_id is the file's only project."""
    tasks = raw.table("TASK")
    _require(tasks, raw.source, "TASK", ["task_id", "task_code"])
    if "proj_id" not in tasks.columns:
        _require(projects, raw.source, "PROJECT", ["proj_id"])
        if len(projects) != 1:
            raise XerError(
                f"{raw.source}: table TASK has no column proj_id "
                f"and PROJECT has {len(projects)} projects to choose from"
            )
        tasks = tasks.assign(proj_id=projects["proj_id"].iloc[0])
        warnings.append(f"{raw.source}: TASK.proj_id missing: taken from the only project in the file")
    return tasks


def _taskpred_table(raw: RawXer, all_tasks: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    """TASKPRED with proj_id / pred_proj_id derived from TASK when the export omits them.

    P6 always writes both; minimal files from other tools may not. proj_id is the
    successor's project; pred_proj_id the predecessor's. A predecessor absent from TASK
    gets "" there, so such a link reads as not external (no way to know better).
    """
    relationships = raw.table("TASKPRED")
    if relationships.empty:
        return relationships
    _require(relationships, raw.source, "TASKPRED", ["task_id", "pred_task_id"])
    owner = all_tasks.drop_duplicates("task_id").set_index("task_id")["proj_id"]
    derived = {"proj_id": "task_id", "pred_proj_id": "pred_task_id"}
    for column, via in derived.items():
        if column not in relationships.columns:
            relationships = relationships.assign(**{column: relationships[via].map(owner).fillna("")})
            what = "successor" if column == "proj_id" else "predecessor"
            warnings.append(f"{raw.source}: TASKPRED.{column} missing: taken from the {what} activity")
    return relationships


# Snapshot column contract: the minimum every frame carries (the code reads these by name).
# The frames may hold more (raw XER columns); build_snapshot fails fast if one goes missing.
TASK_COLS = [
    # identity
    "task_id",
    "task_code",
    "task_name",
    "task_type",
    "wbs_id",
    "wbs_code",
    "wbs_l1",
    "wbs_sort",
    "clndr_id",
    "hours_per_day",
    "is_wbs_summary",
    # P6 stored values
    "status_code",
    "complete_pct_type",
    "ev_compute_type",
    "ev_user_pct",
    "cstr_type",
    "cstr_date",
    "cstr_type2",
    "cstr_date2",
    "total_float_hr_cnt",
    "free_float_hr_cnt",
    "target_drtn_hr_cnt",
    "remain_drtn_hr_cnt",
    "early_start_date",
    "early_end_date",
    "late_start_date",
    "late_end_date",
    "act_start_date",
    "act_end_date",
    "target_start_date",
    "target_end_date",
    "restart_date",
    "reend_date",
    # derived flags
    "status",
    "type",
    "is_complete",
    "is_started",
    "is_milestone",
    "is_start_milestone",
    "is_loe",
    "is_critical",
    "on_longest_path",
    "has_hard_constraint",
    "constraint",
    "has_resource",
    "has_expense",
    "has_external_pred",
    "has_external_succ",
    # working days
    "start",
    "finish",
    "total_float_d",
    "free_float_d",
    "remaining_d",
    "original_d",
    "pct_complete",
]
REL_COLS_MODEL = ["pred_code", "succ_code", "type", "lag_hr", "lag_d", "is_external"]
ASSIGNMENT_COLS_MODEL = [
    "taskrsrc_id",
    "task_id",
    "task_code",
    "role_id",
    "rsrc_id",
    "rsrc_short_name",
    "rsrc_name",
    "rsrc_type",
    "driving",
    "target_qty",
    "act_qty",
    "remain_qty",
    "restart_date",
    "reend_date",
    "act_start_date",
    "act_end_date",
]


def _check_snapshot_columns(snap: Snapshot) -> None:
    """Raise XerError when a built frame lacks a declared column (a model change dropped it)."""
    for name, declared, frame in (
        ("tasks", [*TASK_COLS, *LABOR_COLS], snap.tasks),
        ("relationships", REL_COLS_MODEL, snap.relationships),
        ("assignments", ASSIGNMENT_COLS_MODEL, snap.assignments),
    ):
        missing = [column for column in declared if column not in frame.columns]
        if missing:
            raise XerError(f"{snap.source}: snapshot.{name} lacks declared columns {missing}")


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
    project_task_counts: dict[str, int] = field(default_factory=dict)  # TASK rows by project code
    selected_by: str = ""  # why this project of the file: chosen, only project, most TASK rows
    data_date_source: str = ""  # PROJECT column the data date was read from
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
        for candidate in (clndr_id, self.project_clndr_id):
            if candidate and candidate in self.work_calendars:
                return self.work_calendars[candidate]
        default = next(iter(self.work_calendars.values()), None)
        return default or WorkCalendar.standard()

    def _calendar_of(self, clndr_id: object) -> WorkCalendar:
        """``calendar`` for a cell value: anything but a string (NaN, None) means the default."""
        return self.calendar(clndr_id if isinstance(clndr_id, str) else None)

    def work_hours(self, clndr: pd.Series, start: pd.Series, end: pd.Series) -> pd.Series:
        """Working hours from ``start`` to ``end``, row by row, on each row's calendar.

        Exact to the minute (the CPM's TimeAxis); a blank or unknown calendar id falls back
        to the project calendar; NaN where a date is missing; negative when ``end < start``.
        """
        hours = pd.Series(np.nan, index=start.index, dtype=float)
        known = start.notna() & end.notna()
        if not known.any():
            return hours
        first_day = min(start[known].min(), end[known].min()).date()
        last_day = max(start[known].max(), end[known].max()).date()
        calendar_ids = clndr[known].map(self._calendar_of).map(attrgetter("clndr_id"))
        for calendar_id, rows in calendar_ids.groupby(calendar_ids).groups.items():
            axis = TimeAxis(self.calendar(calendar_id or None), first_day, last_day)
            hours[rows] = (axis.work_many(end[rows]) - axis.work_many(start[rows])) / 60
        return hours

    def working_days(self, clndr: pd.Series, start: pd.Series, end: pd.Series) -> pd.Series:
        """``work_hours`` in days of each row's calendar (its hours per day)."""
        hours_per_day = clndr.map(self._calendar_of).map(attrgetter("hours_per_day"))
        return self.work_hours(clndr, start, end) / hours_per_day.astype(float)

    @property
    def label(self) -> str:
        date_text = self.data_date.strftime(DATE_FMT) if self.data_date is not None else "no data date"
        return f"{date_text} · {self.source}"

    @property
    def activities(self) -> pd.DataFrame:
        """Tasks without WBS-summary rows: what every count and chart should use."""
        return self.tasks[~self.tasks["is_wbs_summary"]]

    @cached_property
    def by_code(self) -> pd.DataFrame:
        """Activities indexed by task_code (first row wins); treat as read-only, it is cached."""
        return self.activities.drop_duplicates("task_code").set_index("task_code")


@dataclass(frozen=True)
class _BuildInputs:
    """What the build steps share: the file's tables, the chosen project and the warning list."""

    raw: RawXer
    all_tasks: pd.DataFrame  # TASK of every project in the file
    all_relationships: pd.DataFrame  # TASKPRED of every project in the file
    project_row: pd.Series
    hours_per_day: pd.Series  # by calendar id
    settings: Settings
    warnings: list[str]  # appended to in run order: that order is observable

    @property
    def source(self) -> str:
        return self.raw.source

    @property
    def project_id(self) -> str:
        return self.project_row["proj_id"]

    @property
    def fallback_hours_per_day(self) -> float:
        """Hours per day for an activity whose calendar is not in the file.

        The chain of ``Snapshot.calendar``: the project's calendar, then the file's first
        calendar, then the standard one. MPXJ resolves it the same way
        (``Task.getEffectiveCalendar`` -> ``ProjectFile.getDefaultCalendar`` ->
        ``ProjectCalendarContainer.findOrCreateDefaultCalendar``); no Oracle page states it.
        """
        project_clndr_id = str(self.project_row.get("clndr_id") or "")
        if project_clndr_id in self.hours_per_day.index:
            return float(self.hours_per_day[project_clndr_id])
        if not self.hours_per_day.empty:
            return float(self.hours_per_day.iloc[0])
        return self.settings.default_hours_per_day


def _wbs_frame(raw: RawXer, project_id: str) -> tuple[pd.DataFrame, str | None]:
    wbs = raw.table("PROJWBS")
    if wbs.empty:
        return pd.DataFrame(
            columns=["wbs_id", "wbs_code", "wbs_name", "wbs_l1", "wbs_sort", "ev_compute_type", "ev_user_pct"]
        ), None
    _require(wbs, raw.source, "PROJWBS", ["proj_id", "wbs_id"])
    wbs = _ensure_cols(
        wbs[wbs["proj_id"] == project_id].copy(),
        ["parent_wbs_id", "proj_node_flag", "seq_num", "wbs_short_name", "wbs_name", "ev_compute_type", "ev_user_pct"],
    )
    by_id = wbs.set_index("wbs_id")
    project_node = wbs.loc[wbs["proj_node_flag"] == "Y"]
    project_name = project_node["wbs_name"].iloc[0] if not project_node.empty else None

    def lineage(wbs_id: str) -> list[str]:
        chain: list[str] = []
        seen: set[str] = set()
        while wbs_id in by_id.index and wbs_id not in seen:
            seen.add(wbs_id)
            row = by_id.loc[wbs_id]
            if row["proj_node_flag"] == "Y":
                break
            chain.append(wbs_id)
            wbs_id = row["parent_wbs_id"]
        return chain[::-1]

    sequence = pd.to_numeric(by_id["seq_num"], errors="coerce").fillna(0).astype(int)
    codes, top_levels, sort_keys = [], [], []
    for wbs_id in wbs["wbs_id"]:
        chain = lineage(wbs_id)
        codes.append(".".join(by_id.loc[element, "wbs_short_name"] for element in chain))
        # P6 orders WBS siblings by seq_num, not alphabetically
        sort_keys.append(".".join(f"{sequence[element]:06d}" for element in chain))
        top = chain[0] if chain else None
        top_levels.append(f"{by_id.loc[top, 'wbs_short_name']} · {by_id.loc[top, 'wbs_name']}" if top else "")
    wbs["wbs_code"] = codes
    wbs["wbs_l1"] = top_levels
    wbs["wbs_sort"] = sort_keys
    return wbs, project_name


def _assignments(inputs: _BuildInputs, tasks: pd.DataFrame) -> pd.DataFrame:
    """TASKRSRC rows of the project, typed, with each resource's type, name and calendar.

    ``rsrc_type``: RT_Labor / RT_Equip (nonlabor) / RT_Mat, from TASKRSRC (P6 8+) else RSRC;
    "role" for a role assigned without a resource. ``driving`` = "Drive activity dates"
    (rollup_dates_flag). ``rsrc_clndr_id`` is the calendar a resource-dependent activity's
    assignment is scheduled on.
    """
    raw_assignments = inputs.raw.table("TASKRSRC")
    columns = (
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
    if raw_assignments.empty:
        return pd.DataFrame(columns=columns)
    if "proj_id" in raw_assignments.columns:
        raw_assignments = raw_assignments[raw_assignments["proj_id"] == inputs.project_id]
    assignments = _ensure_cols(
        raw_assignments.copy(),
        ["taskrsrc_id", "rsrc_id", "role_id", "rsrc_type", "rollup_dates_flag"]
        + ASSIGNMENT_NUM_COLS
        + ASSIGNMENT_DATE_COLS,
    )
    assignments = assignments[assignments["task_id"].isin(tasks["task_id"])]
    assignments["task_code"] = assignments["task_id"].map(tasks.set_index("task_id")["task_code"])
    for column in ASSIGNMENT_NUM_COLS:
        assignments[column] = to_number(assignments[column])
    for column in ASSIGNMENT_DATE_COLS:
        assignments[column] = to_datetime(assignments[column])
    assignments["act_qty"] = assignments["act_reg_qty"].fillna(0) + assignments["act_ot_qty"].fillna(0)

    resources = _ensure_cols(
        inputs.raw.table("RSRC").copy(), ["rsrc_id", "rsrc_type", "rsrc_name", "rsrc_short_name", "clndr_id"]
    ).set_index("rsrc_id")
    resources = resources[~resources.index.duplicated()]
    own_type = assignments["rsrc_type"].astype(object)
    resource_type = assignments["rsrc_id"].map(resources["rsrc_type"]).astype(object)
    has_own_type = own_type.astype(str).str.strip() != ""
    assignments["rsrc_type"] = own_type.where(has_own_type, resource_type).fillna("").astype(str)
    has_no_resource = assignments["rsrc_id"].astype(str).str.strip() == ""
    has_role = assignments["role_id"].astype(str).str.strip() != ""
    role_only = has_no_resource & has_role
    assignments.loc[role_only, "rsrc_type"] = "role"
    assignments["rsrc_name"] = assignments["rsrc_id"].map(resources["rsrc_name"]).astype(object)
    assignments["rsrc_short_name"] = assignments["rsrc_id"].map(resources["rsrc_short_name"]).astype(object)
    roles = inputs.raw.table("ROLES")
    if not roles.empty and {"role_id", "role_name"} <= set(roles.columns):
        role_names = roles.set_index("role_id")["role_name"]
        assignments.loc[role_only, "rsrc_name"] = assignments.loc[role_only, "role_id"].map(role_names)
    resource_calendar = assignments["rsrc_id"].map(resources["clndr_id"]).astype(object)
    assignments["rsrc_clndr_id"] = resource_calendar.fillna("").astype(str)
    assignments["driving"] = assignments["rollup_dates_flag"] != "N"  # P6's default: assignments drive dates
    return assignments[columns].reset_index(drop=True)


def _select_project(
    source: str, projects: pd.DataFrame, all_tasks: pd.DataFrame, project_code: str | None, warnings: list[str]
) -> tuple[pd.Series, dict[str, int], str]:
    """The PROJECT row to build the snapshot for, the TASK row count of every project that owns
    activities (by code, in file order), and how the row was selected: ``chosen`` (the
    requested code), ``only project`` or ``most TASK rows``."""
    task_counts = all_tasks["proj_id"].value_counts()
    projects = _ensure_cols(
        projects[projects["proj_id"].isin(task_counts.index)].copy(),
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
    if projects.empty:
        raise XerError(f"{source}: no project owns any activity")
    projects["_n"] = projects["proj_id"].map(task_counts)
    counts = {str(code): int(n) for code, n in zip(projects["proj_short_name"], projects["_n"], strict=True)}
    if project_code:
        selected = projects[projects["proj_short_name"] == project_code]
        if selected.empty:
            raise XerError(f"{source}: project {project_code!r} not found (has {list(counts)})")
        return selected.iloc[0], counts, "chosen"
    project_row = projects.sort_values("_n", ascending=False).iloc[0]
    if len(projects) == 1:
        return project_row, counts, "only project"
    warnings.append(f"{source}: {len(projects)} projects in file, using {project_row['proj_short_name']}")
    return project_row, counts, "most TASK rows"


def _calendars(raw: RawXer, settings: Settings) -> tuple[pd.DataFrame, pd.Series, dict[str, WorkCalendar]]:
    """CALENDAR table, hours per working day by calendar id, and the parsed work calendars."""
    calendars = raw.table("CALENDAR")
    if calendars.empty:
        return calendars, pd.Series(dtype=float), {}
    _require(calendars, raw.source, "CALENDAR", ["clndr_id"])
    calendars = _ensure_cols(calendars.copy(), ["clndr_name", "day_hr_cnt", "week_hr_cnt", "clndr_data"])
    calendars["day_hr_cnt"] = to_number(calendars["day_hr_cnt"])
    work_calendars = {
        str(row["clndr_id"]): WorkCalendar.from_row(row, settings.default_hours_per_day)
        for _, row in calendars.iterrows()
    }
    # one reading of "hours per day": the calendar's own (a missing or zero count is the default)
    hours_per_day = pd.Series(
        {clndr_id: calendar.hours_per_day for clndr_id, calendar in work_calendars.items()}, dtype=float
    )
    return calendars.drop(columns=["clndr_data"]), hours_per_day, work_calendars  # parsed above; the blob is large


def _header_field(header: list[str], index: int) -> str:
    return header[index].strip() if index < len(header) else ""


def _scheduling_options(inputs: _BuildInputs) -> dict:
    """P6 scheduling options that change how stored numbers must be read."""
    schedule_options = inputs.raw.table("SCHEDOPTIONS")
    schedule_row: dict[str, str] = {}
    if not schedule_options.empty:
        rows = schedule_options
        if "proj_id" in schedule_options.columns:
            rows = schedule_options[schedule_options["proj_id"] == inputs.project_id]
        schedule_row = rows.iloc[0].to_dict() if not rows.empty else {}
    # Oracle (P6 Professional 24, Schedule Options > General): "If you do not select a
    # calendar, Successor Activity Calendar is used to calculate lag."
    chosen_lag_calendar = schedule_row.get("sched_calendar_on_relationship_lag")
    lag_calendar = chosen_lag_calendar if chosen_lag_calendar in LAG_CALENDARS else "rcal_Successor"
    # Retained logic / progress override / actual dates: SCHEDOPTIONS stores two flags;
    # both "N" is Actual Dates (read the same way by MPXJ's TableProjectReader).
    retained_logic = schedule_row.get("sched_retained_logic", "")
    progress_override = schedule_row.get("sched_progress_override", "")
    progressed = "retained_logic"
    if progress_override == "Y" and retained_logic != "Y":
        progressed = "progress_override"
    elif retained_logic == "N" and progress_override == "N":
        progressed = "actual_dates"
    project_row = inputs.project_row
    critical_hours = to_number(pd.Series([project_row["critical_drtn_hr_cnt"]])).iloc[0]
    return {
        "lag_calendar": lag_calendar,
        "progressed": progressed,
        "critical_path_type": project_row["critical_path_type"] or "CT_TotFloat",
        "critical_float_hr": None if pd.isna(critical_hours) else float(critical_hours),
        "has_schedoptions": not schedule_options.empty,
        "sched": schedule_row,  # the raw SCHEDOPTIONS row: read by analysis.cpm
        # ERMHDR: P6 version and product that wrote the file ("" when the header leaves them out)
        "export": {"version": _header_field(inputs.raw.header, 0), "product": _header_field(inputs.raw.header, 6)},
        # the raw PROJECT fields the three values above come from: "" when the file leaves them blank
        "project": {key: project_row[key] for key in ("critical_path_type", "critical_drtn_hr_cnt", "plan_end_date")},
        "must_finish_by": _parse_date(project_row["plan_end_date"]),
    }


def _task_frame(inputs: _BuildInputs, wbs: pd.DataFrame, options: dict) -> pd.DataFrame:
    """The project's activities, typed, with the derived columns every analysis reads."""
    all_tasks, source = inputs.all_tasks, inputs.source
    tasks = _ensure_cols(
        all_tasks[all_tasks["proj_id"] == inputs.project_id].copy(),
        [
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
    for column in TASK_DATE_COLS:
        tasks[column] = to_datetime(tasks[column])
    for column in TASK_NUM_COLS:
        tasks[column] = to_number(tasks[column])

    default_hours = inputs.fallback_hours_per_day
    task_hours_per_day = tasks["clndr_id"].map(inputs.hours_per_day).astype(float)
    unknown_calendars = sorted(set(tasks.loc[task_hours_per_day.isna(), "clndr_id"].astype(str)))
    if unknown_calendars:
        inputs.warnings.append(
            f"{source}: activity calendars not in the file {unknown_calendars[:5]}; "
            f"read on the project's calendar ({default_hours} h/day)"
        )
    tasks["hours_per_day"] = task_hours_per_day.fillna(default_hours)
    tasks["status"] = tasks["status_code"].map(STATUS).fillna(tasks["status_code"])
    tasks["type"] = tasks["task_type"].map(TASK_TYPE).fillna(tasks["task_type"])
    tasks["is_complete"] = tasks["status_code"] == "TK_Complete"
    tasks["is_started"] = tasks["status_code"] != "TK_NotStart"
    tasks["is_start_milestone"] = tasks["task_type"].isin(START_MILESTONES)
    tasks["is_milestone"] = tasks["is_start_milestone"] | (tasks["task_type"] == "TT_FinMile")
    if (tasks["task_type"] == "TT_StartMile").any():
        inputs.warnings.append(f"{source}: non-standard task_type TT_StartMile read as a start milestone")
    tasks["is_loe"] = tasks["task_type"] == "TT_LOE"
    tasks["is_wbs_summary"] = tasks["task_type"] == "TT_WBS"

    # P6's Start / Finish columns (Oracle, "Dates Columns of the Activity Table"): the actual
    # date once there is one, else the remaining early date once scheduled, else planned.
    forecast_start, forecast_finish = forecast_dates(tasks)
    tasks["start"] = tasks["act_start_date"].combine_first(forecast_start).combine_first(tasks["target_start_date"])
    tasks["finish"] = tasks["act_end_date"].combine_first(forecast_finish).combine_first(tasks["target_end_date"])
    tasks["total_float_d"] = (tasks["total_float_hr_cnt"] / tasks["hours_per_day"]).where(~tasks["is_complete"])
    tasks["free_float_d"] = (tasks["free_float_hr_cnt"] / tasks["hours_per_day"]).where(~tasks["is_complete"])
    tasks["remaining_d"] = tasks["remain_drtn_hr_cnt"] / tasks["hours_per_day"]
    tasks["original_d"] = tasks["target_drtn_hr_cnt"] / tasks["hours_per_day"]

    tasks["on_longest_path"] = tasks["driving_path_flag"] == "Y"
    # Critical as P6 defines it for this project: longest path, or total float <= threshold.
    if options["critical_path_type"] == "CT_DrivPath":
        meets_definition = tasks["on_longest_path"]
    elif options["critical_float_hr"] is not None:
        meets_definition = tasks["total_float_hr_cnt"] <= options["critical_float_hr"]
    else:
        meets_definition = tasks["total_float_d"] <= inputs.settings.critical_float_days
    # LOE is included, as in P6's own Critical flag (DCMA populations exclude LOE separately).
    open_work = ~tasks["is_complete"] & ~tasks["is_wbs_summary"]
    tasks["is_critical"] = open_work & meets_definition.fillna(False)

    tasks["pct_complete"] = percent_complete(tasks)
    has_hard_first = tasks["cstr_type"].isin(HARD_CONSTRAINTS)
    tasks["has_hard_constraint"] = has_hard_first | tasks["cstr_type2"].isin(HARD_CONSTRAINTS)

    wbs_columns = ["wbs_code", "wbs_l1", "wbs_sort", "ev_compute_type", "ev_user_pct"]
    if wbs.empty:
        tasks[wbs_columns] = ""
    else:
        # EV technique: set per WBS element in P6 (Earned Value settings of the WBS)
        tasks = tasks.merge(wbs[["wbs_id", *wbs_columns]], on="wbs_id", how="left")
    tasks[wbs_columns] = tasks[wbs_columns].fillna("")

    duplicates = tasks["task_code"][tasks["task_code"].duplicated()].unique()
    if len(duplicates):
        inputs.warnings.append(f"{source}: duplicate activity IDs {list(duplicates)[:5]}; history joins may be wrong")
    return tasks


def _relationships(inputs: _BuildInputs) -> tuple[pd.DataFrame, set]:
    """The project's schedulable relationships, and the successors that also have an external predecessor."""
    all_relationships = inputs.all_relationships
    if all_relationships.empty:
        columns = ["task_id", "pred_task_id", "succ_code", "pred_code", "type", "lag_hr", "lag_d", "is_external"]
        return pd.DataFrame(columns=columns), set()
    project_id, default_hours = inputs.project_id, inputs.fallback_hours_per_day
    relationships = _ensure_cols(
        all_relationships[all_relationships["proj_id"] == project_id].copy(),
        ["pred_proj_id", "pred_type", "lag_hr_cnt"],
    )
    all_tasks = _ensure_cols(inputs.all_tasks.copy(), ["clndr_id"])
    code_by_id = all_tasks.set_index("task_id")["task_code"]
    hours_per_day_by_id = (
        all_tasks.set_index("task_id")["clndr_id"].map(inputs.hours_per_day).astype(float).fillna(default_hours)
    )
    relationships["succ_code"] = relationships["task_id"].map(code_by_id)
    relationships["pred_code"] = relationships["pred_task_id"].map(code_by_id)
    relationships["type"] = relationships["pred_type"].map(REL_TYPE).fillna(relationships["pred_type"])
    relationships["lag_hr"] = to_number(relationships["lag_hr_cnt"]).fillna(0.0)
    # Lag hours -> days. Oracle: "Lag entered in a unit other than hours is converted
    # to hours based on the predecessor activity's calendar", whatever calendar the lag
    # is then scheduled on (that one is the CPM's business, analysis/cpm.py).
    lag_hours_per_day = relationships["pred_task_id"].map(hours_per_day_by_id)
    relationships["lag_d"] = relationships["lag_hr"] / lag_hours_per_day.astype(float).fillna(default_hours)
    relationships["is_external"] = relationships["pred_proj_id"].ne(project_id) & relationships["pred_proj_id"].ne("")
    # A predecessor in another project of the same file is named as in external_links:
    # its own Activity ID may also exist here, and would read as a link from that one.
    external_in_file = relationships["is_external"] & relationships["pred_code"].notna()
    external_names = "[ext]" + relationships.loc[external_in_file, "pred_task_id"].astype(str)
    relationships.loc[external_in_file, "pred_code"] = external_names
    # Counted before the unschedulable links go: those still have an external predecessor.
    external_predecessors = set(relationships.loc[relationships["is_external"], "task_id"])

    # A predecessor with no TASK row is a link to another project (P6 exports the link, not
    # the other project's activities) or a corrupt link. Either way it is not logic that can
    # be scheduled; only the corrupt ones are reported.
    lost = relationships["succ_code"].isna() | relationships["pred_code"].isna()
    corrupt = lost & ~relationships["is_external"]
    if corrupt.any():
        inputs.warnings.append(
            f"{inputs.source}: {int(corrupt.sum())} relationship(s) to an activity "
            "not in the file; ignored by the schedule and the checks"
        )
    return relationships[~lost].copy(), external_predecessors


def _external_links(
    inputs: _BuildInputs, relationships: pd.DataFrame, links_out: pd.DataFrame, tasks: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Counterparts in other projects, with the dates P6 stored for them, and the links to them.

    The CPM uses them as fixed dates, as P6 does when relationships to other projects count.
    ``links_out`` are the other projects' relationships whose predecessor is one of ours.
    """
    outbound_links = _ensure_cols(links_out.copy(), ["pred_type", "lag_hr_cnt"])
    inbound_links = relationships[relationships["is_external"].astype(bool)]
    other_ids = set(outbound_links["task_id"]) | set(inbound_links["pred_task_id"])
    if not other_ids:
        return pd.DataFrame(), pd.DataFrame(columns=["pred_code", "succ_code", "type", "lag_hr", "direction"])
    all_tasks = inputs.all_tasks
    external_tasks = _ensure_cols(
        all_tasks[all_tasks["task_id"].isin(other_ids)].copy(),
        ["task_code", "status_code", "clndr_id"] + TASK_DATE_COLS,
    )
    for column in TASK_DATE_COLS:
        external_tasks[column] = to_datetime(external_tasks[column])
    external_tasks["task_code"] = "[ext]" + external_tasks["task_id"].astype(str)
    external_code = external_tasks.set_index("task_id")["task_code"]
    own_code = tasks.set_index("task_id")["task_code"]
    inbound = pd.DataFrame(
        {
            "pred_code": inbound_links["pred_task_id"].map(external_code),
            "succ_code": inbound_links["succ_code"],
            "type": inbound_links["type"],
            "lag_hr": inbound_links["lag_hr"],
            "direction": "in",
        }
    )
    outbound = pd.DataFrame(
        {
            "pred_code": outbound_links["pred_task_id"].map(own_code),
            "succ_code": outbound_links["task_id"].map(external_code),
            "type": outbound_links["pred_type"].map(REL_TYPE),
            "lag_hr": to_number(outbound_links["lag_hr_cnt"]).fillna(0.0),
            "direction": "out",
        }
    )
    links = pd.concat([inbound, outbound], ignore_index=True).dropna(subset=["pred_code", "succ_code"])
    return external_tasks, links


def _labor_hours(tasks: pd.DataFrame, assignments: pd.DataFrame) -> str:
    """Add the labour / nonlabor columns to ``tasks`` in place and say where they came from.

    P6 keeps the activity totals on TASK (Budgeted / Actual / Remaining Labor Units;
    nonlabor in *_equip_qty). Older or partial exports only have the assignments: sum them
    by resource type (roles count as labour, as in P6).
    """
    if tasks["target_work_qty"].notna().any():
        tasks["labor_budget_hr"] = tasks["target_work_qty"].fillna(0.0)
        tasks["labor_actual_hr"] = tasks["act_work_qty"].fillna(0.0)
        tasks["labor_remaining_hr"] = tasks["remain_work_qty"].fillna(0.0)
        tasks["nonlabor_budget_qty"] = tasks["target_equip_qty"].fillna(0.0)
        tasks["nonlabor_actual_qty"] = tasks["act_equip_qty"].fillna(0.0)
        tasks["nonlabor_remaining_qty"] = tasks["remain_equip_qty"].fillna(0.0)
        return "TASK"
    if assignments.empty:
        for column in LABOR_COLS:
            tasks[column] = 0.0
        return "none"
    for prefix, kinds in (("labor", ("RT_Labor", "role", "")), ("nonlabor", ("RT_Equip",))):
        by_task = assignments[assignments["rsrc_type"].isin(kinds)].groupby("task_id")
        unit = "hr" if prefix == "labor" else "qty"
        tasks[f"{prefix}_budget_{unit}"] = tasks["task_id"].map(by_task["target_qty"].sum()).fillna(0.0)
        tasks[f"{prefix}_actual_{unit}"] = tasks["task_id"].map(by_task["act_qty"].sum()).fillna(0.0)
        tasks[f"{prefix}_remaining_{unit}"] = tasks["task_id"].map(by_task["remain_qty"].sum()).fillna(0.0)
    return "TASKRSRC"


def leveled(tasks: pd.DataFrame) -> pd.Series:
    """Open activities whose remaining early start (restart_date) differs from their early start.

    Leveling with "preserve scheduled early and late dates" leaves the remaining early dates
    (restart/reend) apart from the early dates; a plain CPM cannot reproduce them.
    """
    return (
        (tasks["status_code"] != "TK_Complete")
        & tasks["restart_date"].notna()
        & tasks["early_start_date"].notna()
        & (tasks["restart_date"] != tasks["early_start_date"])
    )


def _warn_leveling(tasks: pd.DataFrame, inputs: _BuildInputs) -> None:
    count = int(leveled(tasks).sum())
    if count:
        inputs.warnings.append(
            f"{inputs.source}: {count} open activities have a remaining early start "
            "different from their early start (resource leveling?)"
        )


def _project_finish(tasks: pd.DataFrame, inputs: _BuildInputs) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """(latest activity finish, PROJECT.scd_end_date); the activities win when they disagree."""
    activities = tasks[~tasks["is_wbs_summary"]]
    finish = activities["finish"].max() if activities["finish"].notna().any() else None
    scheduled_finish = _parse_date(inputs.project_row["scd_end_date"])
    if finish is not None and scheduled_finish is not None and abs(scheduled_finish - finish) > pd.Timedelta(days=1):
        inputs.warnings.append(
            f"{inputs.source}: PROJECT.scd_end_date {scheduled_finish:%Y-%m-%d} differs from the "
            f"latest activity finish {finish:%Y-%m-%d}; using the activities"
        )
    return finish, scheduled_finish


def _data_date(project_row: pd.Series) -> tuple[pd.Timestamp | None, str]:
    """The data date and the PROJECT column it comes from: last_recalc_date, else plan_start_date."""
    for column in ("last_recalc_date", "plan_start_date"):
        date = _parse_date(project_row[column])
        if date is not None:
            return date, column
    return None, ""


# What read_header needs from a file: PROJECT (a few rows) whole, the identity columns of TASK.
HEADER_TABLES = {"PROJECT": None, "TASK": ("task_id", "task_code", "proj_id")}


@dataclass(frozen=True)
class FileHeader:
    """What build_snapshot would take from a file, read from PROJECT and TASK only."""

    source: str
    project_code: str  # the project build_snapshot takes by default
    selected_by: str
    project_task_counts: dict[str, int]  # TASK rows by project code
    data_date: pd.Timestamp | None
    data_date_source: str


def read_header(raw: RawXer) -> FileHeader:
    """The default project and data date of a file, by the rules of build_snapshot, from
    PROJECT and TASK alone (a RawXer parsed with ``keep=HEADER_TABLES`` is enough)."""
    projects = raw.table("PROJECT")
    if projects.empty or raw.table("TASK").empty:
        raise XerError(f"{raw.source}: PROJECT or TASK table missing")
    _require(projects, raw.source, "PROJECT", ["proj_id"])
    warnings: list[str] = []
    all_tasks = _task_table(raw, projects, warnings)
    project_row, task_counts, selected_by = _select_project(raw.source, projects, all_tasks, None, warnings)
    data_date, data_date_source = _data_date(project_row)
    return FileHeader(raw.source, project_row["proj_short_name"], selected_by, task_counts, data_date, data_date_source)


def build_snapshot(
    raw: RawXer,
    project_code: str | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> Snapshot:
    """Turn a parsed XER into a typed Snapshot for one project.

    If the file contains several projects, ``project_code`` selects one; otherwise the
    project with the most activities is used and a warning is recorded.
    """
    projects = raw.table("PROJECT")
    if projects.empty or raw.table("TASK").empty:
        raise XerError(f"{raw.source}: PROJECT or TASK table missing")
    _require(projects, raw.source, "PROJECT", ["proj_id"])
    warnings = list(raw.warnings)  # appended to in the order the steps run: that order is observable
    all_tasks = _task_table(raw, projects, warnings)
    all_relationships = _taskpred_table(raw, all_tasks, warnings)

    # The project, its data date and its calendars
    project_row, task_counts, selected_by = _select_project(raw.source, projects, all_tasks, project_code, warnings)
    planned_start = _parse_date(project_row["plan_start_date"])
    data_date, data_date_source = _data_date(project_row)
    if data_date is None:
        warnings.append(f"{raw.source}: no data date (last_recalc_date / plan_start_date blank)")
    calendars, hours_per_day, work_calendars = _calendars(raw, settings)
    inputs = _BuildInputs(raw, all_tasks, all_relationships, project_row, hours_per_day, settings, warnings)
    wbs, project_name = _wbs_frame(raw, inputs.project_id)
    options = _scheduling_options(inputs)

    # Activities, the logic between them, and the links to other projects
    tasks = _task_frame(inputs, wbs, options)
    relationships, external_predecessors = _relationships(inputs)
    links_out = pd.DataFrame(columns=["task_id", "pred_task_id", "pred_type", "lag_hr_cnt"])
    if not all_relationships.empty and "proj_id" in all_relationships.columns:
        from_other_projects = all_relationships["proj_id"] != inputs.project_id
        links_out = all_relationships[from_other_projects & all_relationships["pred_task_id"].isin(tasks["task_id"])]
    tasks["has_external_pred"] = tasks["task_id"].isin(external_predecessors)
    tasks["has_external_succ"] = tasks["task_id"].isin(set(links_out["pred_task_id"]))
    external_tasks, external_links = _external_links(inputs, relationships, links_out, tasks)

    # Resources, labour hours, leveling, expenses
    assignments = _assignments(inputs, tasks)
    tasks["has_resource"] = tasks["task_id"].isin(assignments["task_id"])
    options["labor_source"] = _labor_hours(tasks, assignments)
    _warn_leveling(tasks, inputs)
    expenses = raw.table("PROJCOST")
    if expenses.empty or "task_id" not in expenses.columns:
        expenses = pd.DataFrame(columns=["task_id"])
    elif "proj_id" in expenses.columns:
        expenses = expenses[expenses["proj_id"] == inputs.project_id].copy()
    tasks["has_expense"] = tasks["task_id"].isin(expenses["task_id"])
    tasks["constraint"] = tasks["cstr_type"].map(CONSTRAINT).fillna(tasks["cstr_type"])

    finish, scheduled_finish = _project_finish(tasks, inputs)

    snapshot = Snapshot(
        source=raw.source,
        project_id=inputs.project_id,
        project_code=project_row["proj_short_name"],
        project_name=project_name or project_row["proj_short_name"],
        data_date=data_date,
        data_date_source=data_date_source,
        finish_date=finish,
        planned_start=planned_start,
        export_date=raw.export_date,
        tasks=tasks.reset_index(drop=True),
        relationships=relationships.reset_index(drop=True),
        wbs=wbs,
        calendars=calendars,
        assignments=assignments.reset_index(drop=True),
        projects_in_file=list(task_counts),
        project_task_counts=task_counts,
        selected_by=selected_by,
        warnings=warnings,
        scheduled_finish=scheduled_finish,
        options=options,
        work_calendars=work_calendars,
        external_tasks=external_tasks.reset_index(drop=True),
        external_links=external_links.reset_index(drop=True),
        project_clndr_id=str(project_row["clndr_id"] or ""),
        expenses=expenses.reset_index(drop=True),
    )
    _check_snapshot_columns(snapshot)
    return snapshot
