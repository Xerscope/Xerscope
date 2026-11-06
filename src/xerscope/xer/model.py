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
- Values P6 would never write (a repeated key, a time-zoned date, an infinite or negative
  remaining duration, an unknown link type) are repaired by ``validate.py``, one rule and one
  warning line each, so the file still loads and says what was done to it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from operator import attrgetter

import numpy as np
import pandas as pd

from ..config import DATE_FMT, DEFAULT_SETTINGS, Settings
from . import validate
from .calendar import TimeAxis, WorkCalendar, hours_to_days
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
    "target_cost",
    "cost_per_qty",
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
# TASK.complete_pct_type, P6's "% Complete Type"
PCT_COMPLETE_TYPE = {"CP_Phys": "Physical", "CP_Drtn": "Duration", "CP_Units": "Units"}
# TASKRSRC / RSRC rsrc_type, P6's "Resource Type"; "role" and "" are role assignments (_assignments)
RSRC_TYPE = {"RT_Labor": "Labor", "RT_Equip": "Nonlabor", "RT_Mat": "Material", "role": "Role", "": "Role"}
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
    try:
        return pd.to_datetime(_blank_to_na(values), format="ISO8601", errors="coerce")
    except ValueError:
        # one cell with a time-zone offset among naive ones: pandas refuses the column even with
        # errors="coerce" ("Mixed timezones"); such a cell reads as NaT (validate.blank_timezones
        # does the same on the model's tables, with a warning)
        return pd.to_datetime(
            _blank_to_na(values.mask(validate.timezone_cells(values))), format="ISO8601", errors="coerce"
        )


def to_number(values: pd.Series) -> pd.Series:
    return pd.to_numeric(_blank_to_na(values), errors="coerce")


def _parse_date(value: object) -> pd.Timestamp | None:
    timestamp = to_datetime(pd.Series([value])).iloc[0]
    return None if pd.isna(timestamp) else timestamp


def percent_complete(tasks: pd.DataFrame) -> pd.Series:
    """Activity % complete as P6 computes it, chosen by ``complete_pct_type``.

    - CP_Phys:  phys_complete_pct (entered by the planner)
    - CP_Drtn:  (original - remaining) / original; 100 once the activity is complete
    - CP_Units: actual units / (actual + remaining units), labour + non-labour
    Where the chosen basis cannot be computed (no duration, no units) the stored
    physical % is used, then the status. Checked against MPXJ's P6 8.4 test export
    and xerlock's rules (tests/test_reference.py).

    Not rounded: Oracle's formulas (Percent Complete and Earned Value Columns of the
    Activity Table) carry no rounding, and EV and DECM 06A505b use this value. P6 shows
    two decimals; the pages round for display only.
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
    return percent.clip(0, 100)


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
    tasks = validate.unique_rows(tasks, "task_id", "TASK", raw.source, warnings)
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


def _project_table(raw: RawXer, warnings: list[str]) -> pd.DataFrame:
    """PROJECT with ``proj_id`` checked and unique (the first of two rows with one id is kept)."""
    projects = raw.table("PROJECT")
    if projects.empty or raw.table("TASK").empty:
        raise XerError(f"{raw.source}: PROJECT or TASK table missing")
    _require(projects, raw.source, "PROJECT", ["proj_id"])
    return validate.unique_rows(projects, "proj_id", "PROJECT", raw.source, warnings)


def _typed_dates(frame: pd.DataFrame, columns: list[str], table: str, inputs: _BuildInputs) -> None:
    """Type the date ``columns`` of ``frame`` in place; a time-zoned cell reads as NaT, with a warning."""
    validate.blank_timezones(frame, columns, table, inputs.source, inputs.warnings)
    for column in columns:
        frame[column] = to_datetime(frame[column])


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
            warnings.append(f"{raw.source}: TASKPRED.{column} missing: taken from the {what} task")
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


# Every PROJECT row of the file: TASK rows, and the baseline pointers P6 writes (EPPM XER data map,
# table PROJECT, v23: sum_base_proj_id "Project Baseline", orig_proj_id "Original Project",
# last_baseline_update_date "Last Update Date", add_date "Date Added"; same XER format on 26, unverified).
# use_project_baseline_flag has no label in the data map; its name matches the Project Details >
# Settings choice of the baseline earned value uses (the project baseline or each user's primary
# baseline, P6 Professional help, Earned Value tab of Admin Preferences), unverified. Both as stored.
# data_date: the project's data date, read as for the analysed project (_data_date).
FILE_PROJECT_COLUMNS = [
    "proj_id", "proj_short_name", "tasks", "sum_base_proj_id", "orig_proj_id", "last_baseline_update_date",
    "data_date", "add_date", "use_project_baseline_flag",
]  # fmt: skip
# Project settings carried along with the rows above, as stored, None when the file has no such
# column, except the two FILE_PROJECT_COLUMNS among them, blank as the baseline resolution reads
# them (Debug block 11; no KPI reads the others). What each one is: app/diagnostic.py, SETTINGS_MEANING.
PROJECT_SETTING_COLUMNS = [
    "use_project_baseline_flag", "sum_base_proj_id", "baselines_to_export", "baseline_names_to_export",
    "def_complete_pct_type", "add_act_remain_flag", "act_this_per_link_flag", "act_pct_link_flag",
    "rem_target_link_flag", "reset_planned_flag", "def_task_type", "def_duration_type", "next_data_date",
    "last_recalc_date",
]  # fmt: skip
# TASK rows of the project by complete_pct_type (PCT_COMPLETE_TYPE, then blank, then any other code);
# None when TASK has no complete_pct_type column.
PCT_TYPE_COUNT_COLUMNS = [*(f"tasks_{kind}" for kind in PCT_COMPLETE_TYPE), "tasks_pct_blank", "tasks_pct_other"]


@dataclass(frozen=True)
class FileBaseline:
    """The P6 Project Baseline of the analysed project (``sum_base_proj_id``) as the same file holds it.

    ``usable``: the pointer names another project of the file that owns activities and, when it
    records its ``orig_proj_id``, was copied from the analysed project. Otherwise ``note`` says why not.
    """

    proj_id: str
    code: str
    usable: bool
    note: str
    updated: str = ""  # last_baseline_update_date of the baseline project, as stored

    @property
    def text(self) -> str:
        if self.usable:
            return f"Baseline: {self.code} (from the file)"
        return f"Baseline: none in file ({self.note})" if self.note else "Baseline: none in file"


def file_baseline(file_projects: pd.DataFrame, project_id: str) -> FileBaseline:
    """Resolve ``sum_base_proj_id`` of ``project_id`` among the PROJECT rows of the file."""
    rows = file_projects.set_index("proj_id")
    pointer = str(rows.loc[project_id, "sum_base_proj_id"]) if project_id in rows.index else ""
    if not pointer:
        return FileBaseline("", "", False, "")
    if pointer == project_id:
        return FileBaseline(pointer, "", False, "the pointer names the analysed project itself")
    if pointer not in rows.index:
        return FileBaseline(pointer, "", False, f"project {pointer} absent")
    target = rows.loc[pointer]
    if target["tasks"] == 0:
        return FileBaseline(pointer, target["proj_short_name"], False, f"project {pointer} has no tasks")
    origin = str(target["orig_proj_id"])
    if origin and origin != project_id:
        note = f"project {pointer} was copied from project {origin}, not from the analysed project {project_id}"
        return FileBaseline(pointer, target["proj_short_name"], False, note)
    return FileBaseline(pointer, target["proj_short_name"], True, "", str(target["last_baseline_update_date"]))


CODE_VALUE_COLUMNS = ["code_type", "code_id", "parent_id", "value", "name", "seq"]
TASK_CODE_COLUMNS = ["task_code", "code_type", "code_id"]


@dataclass(frozen=True)
class Snapshot:
    """One parsed file, read-only once built. Analyses cache their results on it (``by_code``,
    the CPM's ``_xs_schedule`` / ``_xs_comparison``, written with ``object.__setattr__``), so a
    changed snapshot is a new one: ``dataclasses.replace(snapshot, tasks=...)`` starts with an
    empty cache, an in-place edit of a table would not (docs/cpm.md, Performance)."""

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
    project_task_counts: dict[str, int] = field(default_factory=dict)  # TASK rows by proj_id
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
    # P6 activity codes: the values of each code type the project's activities use, and which
    # value each activity is assigned (_activity_codes)
    code_values: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=CODE_VALUE_COLUMNS))
    task_codes: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=TASK_CODE_COLUMNS))
    file_projects: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=FILE_PROJECT_COLUMNS))
    xer_tables: dict[str, tuple[int, int]] = field(default_factory=dict)  # every %T table: (rows, columns)

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
        return hours_to_days(self.work_hours(clndr, start, end), hours_per_day.astype(float))

    def project_working_days(self, start: pd.Timestamp, end: pd.Timestamp) -> float:
        """Working days from ``start`` to ``end`` on the project calendar: for project-level dates
        (data date, forecast finish, a WBS node's finish)."""
        return self.calendar().working_days(start, end)

    def activity_working_days(self, clndr_id: str | None, start: pd.Timestamp, end: pd.Timestamp) -> float:
        """Working days from ``start`` to ``end`` on one activity's calendar (project calendar when
        the id is blank or unknown): for one activity's dates. ``working_days`` does it row by row."""
        return self.calendar(clndr_id).working_days(start, end)

    @property
    def file_baseline(self) -> FileBaseline:
        return file_baseline(self.file_projects, self.project_id)

    @property
    def label(self) -> str:
        date_text = self.data_date.strftime(DATE_FMT) if self.data_date is not None else "no status date"
        return f"{date_text} · {self.source}"

    @property
    def activities(self) -> pd.DataFrame:
        """Tasks without WBS-summary rows: what every count and chart should use."""
        return self.tasks[~self.tasks["is_wbs_summary"]]

    def code_paths(self, code_type: str) -> dict[str, str]:
        """Values of one activity code type, by id, each labelled with its path in the code's
        hierarchy ("B1 / L1"), sorted by that path."""
        values = self.code_values[self.code_values["code_type"] == code_type]
        parent = dict(zip(values["code_id"], values["parent_id"], strict=True))
        short = dict(zip(values["code_id"], values["value"], strict=True))
        paths = {code_id: " / ".join(short[c] for c in reversed(_chain(code_id, parent))) for code_id in short}
        return dict(sorted(paths.items(), key=lambda item: item[1]))

    def tasks_with_codes(self, code_type: str, code_ids: Iterable[str]) -> set[str]:
        """Activity IDs assigned one of ``code_ids`` of ``code_type``, exactly, as P6's filter
        "Activity code equals": a parent value does not take its sub-values' activities."""
        assigned = self.task_codes[self.task_codes["code_type"] == code_type]
        return set(assigned.loc[assigned["code_id"].isin(set(code_ids)), "task_code"])

    @cached_property
    def by_code(self) -> pd.DataFrame:
        """Activities indexed by task_code (first row wins); treat as read-only, it is cached."""
        return self.activities.drop_duplicates("task_code").set_index("task_code")


def _activity_codes(raw: RawXer, tasks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """P6 activity codes of the project's activities. Oracle, "P6 EPPM XER Import/Export Data
    Map Guide (Project)", v23: ACTVTYPE (Activity Codes: ``actv_code_type`` is the code's name),
    ACTVCODE (Activity Code Values: ``short_name`` the value, ``actv_code_name`` its
    description, ``parent_actv_code_id`` its parent value, ``seq_num`` the sort order),
    TASKACTV (Activity Code Assignments: ``task_id``, ``actv_code_id``).

    ``task_codes``: one row per activity and value (TASKACTV rows of the project's TASK
    rows; the type is the value's own). ``code_values``: every value of the types those rows
    use, parents included, ordered as in P6 (type, then ``seq_num``). Rows naming an unknown
    task, value or type are left out.
    """
    types, values, links = raw.table("ACTVTYPE"), raw.table("ACTVCODE"), raw.table("TASKACTV")
    empty = (pd.DataFrame(columns=CODE_VALUE_COLUMNS), pd.DataFrame(columns=TASK_CODE_COLUMNS))
    needed = {
        "ACTVTYPE": (types, ["actv_code_type_id", "actv_code_type"]),
        "ACTVCODE": (values, ["actv_code_id", "actv_code_type_id", "short_name"]),
        "TASKACTV": (links, ["task_id", "actv_code_id"]),
    }
    if any(frame.empty or not set(columns) <= set(frame.columns) for frame, columns in needed.values()):
        return empty
    type_name = types.drop_duplicates("actv_code_type_id").set_index("actv_code_type_id")["actv_code_type"]
    values = values.assign(code_type=values["actv_code_type_id"].map(type_name)).dropna(subset=["code_type"])
    code_of_task = tasks.drop_duplicates("task_id").set_index("task_id")["task_code"]
    type_of_value = values.drop_duplicates("actv_code_id").set_index("actv_code_id")["code_type"]
    task_codes = pd.DataFrame(
        {
            "task_code": links["task_id"].map(code_of_task),
            "code_type": links["actv_code_id"].map(type_of_value),
            "code_id": links["actv_code_id"],
        }
    ).dropna()
    task_codes = task_codes.drop_duplicates().reset_index(drop=True)
    used = values[values["code_type"].isin(set(task_codes["code_type"]))]
    code_values = pd.DataFrame(
        {
            "code_type": used["code_type"],
            "code_id": used["actv_code_id"],
            "parent_id": used.get("parent_actv_code_id", pd.Series("", index=used.index)).fillna(""),
            "value": used["short_name"],
            "name": used.get("actv_code_name", used["short_name"]),
            "seq": pd.to_numeric(used.get("seq_num", pd.Series(0, index=used.index)), errors="coerce").fillna(0),
        }
    )
    code_values = code_values.drop_duplicates("code_id").sort_values(["code_type", "seq", "value"])
    return code_values.reset_index(drop=True), task_codes


def _chain(code_id: str, parent: dict[str, str]) -> list[str]:
    """``code_id`` then its parents up to the top value; a cycle in a broken file ends it."""
    chain, current = [], code_id
    while current in parent and current not in chain:
        chain.append(current)
        current = parent[current]
    return chain


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


def _wbs_frame(raw: RawXer, project_id: str, warnings: list[str]) -> tuple[pd.DataFrame, str | None]:
    wbs = raw.table("PROJWBS")
    if wbs.empty:
        return pd.DataFrame(
            columns=[
                "wbs_id",
                "wbs_code",
                "wbs_name",
                "wbs_l1",
                "wbs_sort",
                "ev_compute_type",
                "ev_user_pct",
                "ev_etc_compute_type",
                "ev_etc_user_value",
            ]
        ), None
    _require(wbs, raw.source, "PROJWBS", ["proj_id", "wbs_id"])
    wbs = validate.unique_rows(wbs[wbs["proj_id"] == project_id], "wbs_id", "PROJWBS", raw.source, warnings)
    wbs = _ensure_cols(
        wbs.copy(),
        [
            "parent_wbs_id",
            "proj_node_flag",
            "seq_num",
            "wbs_short_name",
            "wbs_name",
            "ev_compute_type",
            "ev_user_pct",
            "ev_etc_compute_type",
            "ev_etc_user_value",
        ],
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

    sequence = validate.bounded_sequence(by_id["seq_num"], "PROJWBS", raw.source, warnings)
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
            "curv_id",
            "act_qty",
        ]
        + ASSIGNMENT_NUM_COLS
        + ASSIGNMENT_DATE_COLS
    )
    if raw_assignments.empty:
        return pd.DataFrame(columns=columns)
    _require(raw_assignments, inputs.raw.source, "TASKRSRC", ["task_id"])
    if "proj_id" in raw_assignments.columns:
        raw_assignments = raw_assignments[raw_assignments["proj_id"] == inputs.project_id]
    assignments = _ensure_cols(
        raw_assignments.copy(),
        ["taskrsrc_id", "rsrc_id", "role_id", "rsrc_type", "rollup_dates_flag", "curv_id"]
        + ASSIGNMENT_NUM_COLS
        + ASSIGNMENT_DATE_COLS,
    )
    assignments = assignments[assignments["task_id"].isin(tasks["task_id"])]
    assignments["task_code"] = assignments["task_id"].map(tasks.set_index("task_id")["task_code"])
    for column in ASSIGNMENT_NUM_COLS:
        assignments[column] = to_number(assignments[column])
    _typed_dates(assignments, ASSIGNMENT_DATE_COLS, "TASKRSRC", inputs)
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


def baseline_copies(projects: pd.DataFrame) -> dict[str, str]:
    """The PROJECT rows (``proj_id``, ``sum_base_proj_id``, ``orig_proj_id``) that are baseline copies of
    another project of the file, each with the project it is the baseline of: named as that project's
    Project Baseline (``sum_base_proj_id``), else copied from it (``orig_proj_id``)."""
    ids = set(projects["proj_id"])
    copies = {
        own: origin
        for own, origin in zip(projects["proj_id"], projects["orig_proj_id"], strict=True)
        if origin and origin != own and origin in ids
    }
    copies.update(
        (pointer, own)
        for own, pointer in zip(projects["proj_id"], projects["sum_base_proj_id"], strict=True)
        if pointer and pointer != own and pointer in ids
    )
    return copies


def _default_project(projects: pd.DataFrame, copies: set[str]) -> tuple[pd.Series, str]:
    """The PROJECT row a file is read for when none is asked for, and the rule that picked it.

    Baseline copies (``copies``) are set aside; of the others, the most TASK rows (``_n``), then the
    latest data date (``_data_date``), then the first in the file. When every project is a baseline
    copy, the most TASK rows, then the first in the file. TASK rows come first: a file exported with
    other projects of a portfolio can hold a small project recalculated later than the main one."""
    rows = [row for _, row in projects.iterrows()]  # file order
    if len(rows) == 1:
        return rows[0], "only project"
    pool = [row for row in rows if row["proj_id"] not in copies]
    if pool:
        keys = [(row["_n"], _data_date(row)[0] or pd.Timestamp.min) for row in pool]
        names = ["most TASK rows", "latest data date"]
    else:
        pool = rows
        keys = [(row["_n"],) for row in pool]
        names = ["most TASK rows"]
    # sorted is stable, reverse included: projects with the same keys keep their file order
    order = sorted(range(len(pool)), key=keys.__getitem__, reverse=True)
    best = order[0]
    if len(pool) == 1:
        return pool[best], "only project not a baseline copy"
    differs = [n for n, a, b in zip(names, keys[best], keys[order[1]], strict=True) if a != b]
    rule = differs[0] if differs else "first in file"
    set_aside = len(rows) - len(pool)
    if pool is rows and copies:
        rule += ", every project a baseline copy"
    elif set_aside:
        rule += f", {set_aside} baseline cop{'y' if set_aside == 1 else 'ies'} set aside"
    return pool[best], rule


def _select_project(
    source: str,
    projects: pd.DataFrame,
    all_tasks: pd.DataFrame,
    project_code: str | None,
    warnings: list[str],
    project_id: str | None = None,
) -> tuple[pd.Series, dict[str, int], dict[str, str], str]:
    """The PROJECT row to build the snapshot for, the TASK row count and the code of every project
    that owns activities (both by ``proj_id``, in file order: two projects may share one code), and
    how the row was selected (``_default_project``, or ``chosen``). ``project_id`` names a project
    exactly; ``project_code`` names the projects of that code, of which ``_default_project`` takes
    one: a baseline copy can carry the code of the project it was copied from."""
    task_counts = all_tasks["proj_id"].value_counts()
    projects = _ensure_cols(projects.copy(), ["sum_base_proj_id", "orig_proj_id"])
    copies = set(baseline_copies(projects))
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
        raise XerError(f"{source}: no project owns any task")
    projects["_n"] = projects["proj_id"].map(task_counts)
    counts = {str(pid): int(n) for pid, n in zip(projects["proj_id"], projects["_n"], strict=True)}
    codes = {str(pid): str(code) for pid, code in zip(projects["proj_id"], projects["proj_short_name"], strict=True)}
    if project_id:
        selected = projects[projects["proj_id"] == project_id]
        if selected.empty:
            raise XerError(f"{source}: project {project_id!r} not found (has {list(counts)})")
        return selected.iloc[0], counts, codes, "chosen"
    if project_code:
        selected = projects[projects["proj_short_name"] == project_code]
        if selected.empty:
            raise XerError(f"{source}: project {project_code!r} not found (has {list(codes.values())})")
        return _default_project(selected, copies)[0], counts, codes, "chosen"
    project_row, rule = _default_project(projects, copies)
    if len(projects) > 1:
        warnings.append(f"{source}: {len(projects)} projects in file, using {project_row['proj_short_name']}")
    return project_row, counts, codes, rule


def project_counts_text(counts: Mapping[str, int], codes: Mapping[str, str]) -> str:
    """The "Projects in file" line: TASK rows by project, each named by its code ("UPD (3) · BL (2)").
    ``counts`` and ``codes`` are keyed by ``proj_id``, so two projects with one code both appear."""
    return " · ".join(f"{codes.get(proj_id, proj_id)} ({n})" for proj_id, n in counts.items())


def projects_text(snapshot: Snapshot) -> str:
    """``project_counts_text`` of a snapshot, the codes read from its ``file_projects``."""
    projects = snapshot.file_projects
    return project_counts_text(
        snapshot.project_task_counts, dict(zip(projects["proj_id"], projects["proj_short_name"], strict=True))
    )


def _file_projects(projects: pd.DataFrame, all_tasks: pd.DataFrame) -> pd.DataFrame:
    """One row per PROJECT row of the file, in file order: ``FILE_PROJECT_COLUMNS``, then the
    ``PROJECT_SETTING_COLUMNS`` not among them and the ``PCT_TYPE_COUNT_COLUMNS``."""
    absent = [c for c in PROJECT_SETTING_COLUMNS if c not in projects.columns and c not in FILE_PROJECT_COLUMNS]
    table = _ensure_cols(projects.copy(), FILE_PROJECT_COLUMNS + PROJECT_SETTING_COLUMNS + ["plan_start_date"])
    table["tasks"] = table["proj_id"].map(all_tasks["proj_id"].value_counts()).fillna(0).astype(int)
    table["data_date"] = pd.to_datetime([_data_date(row)[0] for _, row in table.iterrows()])
    table[absent] = None
    if "complete_pct_type" in all_tasks.columns:
        kind = all_tasks["complete_pct_type"].fillna("")
        kind = kind.where(kind.isin([*PCT_COMPLETE_TYPE, ""]), "other").replace("", "blank")
        kind = kind.map(lambda value: f"tasks_{value}" if value in PCT_COMPLETE_TYPE else f"tasks_pct_{value}")
        counts = all_tasks.groupby(["proj_id", kind]).size().unstack(fill_value=0)
        counts = counts.reindex(columns=PCT_TYPE_COUNT_COLUMNS, fill_value=0)
        table = table.join(counts, on="proj_id")
        table[PCT_TYPE_COUNT_COLUMNS] = table[PCT_TYPE_COUNT_COLUMNS].fillna(0).astype(int)
    else:
        table[PCT_TYPE_COUNT_COLUMNS] = None
    extra = [column for column in PROJECT_SETTING_COLUMNS if column not in FILE_PROJECT_COLUMNS]
    return table[FILE_PROJECT_COLUMNS + extra + PCT_TYPE_COUNT_COLUMNS].reset_index(drop=True)


def _calendars(
    raw: RawXer, settings: Settings, warnings: list[str]
) -> tuple[pd.DataFrame, pd.Series, dict[str, WorkCalendar]]:
    """CALENDAR table, hours per working day by calendar id, and the parsed work calendars; what
    ``WorkCalendar.from_row`` had to repair in a row (an unreadable blob, an exception out of range,
    a day under a minute) is one warning per calendar."""
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
    for calendar in work_calendars.values():
        if calendar.notes:
            warnings.append(
                f"{raw.source}: calendar {calendar.clndr_id} ({calendar.name}): {'; '.join(calendar.notes)}"
            )
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
            "guid",  # TASK.guid, the activity's GUID ("globally unique ID generated by the system")
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
    _typed_dates(tasks, TASK_DATE_COLS, "TASK", inputs)
    for column in TASK_NUM_COLS:
        tasks[column] = to_number(tasks[column])
    # The remaining duration drives the CPM and the % complete: unusable values read as 0, said once.
    remaining = validate.usable_hours(
        tasks["remain_drtn_hr_cnt"], "activity remaining duration", tasks["task_code"], source, inputs.warnings
    )
    tasks["remain_drtn_hr_cnt"] = validate.nonnegative_remaining(remaining, source, inputs.warnings)

    default_hours = inputs.fallback_hours_per_day
    task_hours_per_day = tasks["clndr_id"].map(inputs.hours_per_day).astype(float)
    unknown_calendars = sorted(set(tasks.loc[task_hours_per_day.isna(), "clndr_id"].astype(str)))
    if unknown_calendars:
        inputs.warnings.append(
            f"{source}: task calendars not in the file {unknown_calendars[:5]}; "
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
    tasks["total_float_d"] = hours_to_days(tasks["total_float_hr_cnt"], tasks["hours_per_day"]).where(
        ~tasks["is_complete"]
    )
    tasks["free_float_d"] = hours_to_days(tasks["free_float_hr_cnt"], tasks["hours_per_day"]).where(
        ~tasks["is_complete"]
    )
    tasks["remaining_d"] = hours_to_days(tasks["remain_drtn_hr_cnt"], tasks["hours_per_day"])
    tasks["original_d"] = hours_to_days(tasks["target_drtn_hr_cnt"], tasks["hours_per_day"])

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
        inputs.warnings.append(f"{source}: duplicate task IDs {list(duplicates)[:5]}; history joins may be wrong")
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
    relationships = validate.known_relationship_types(relationships, inputs.source, inputs.warnings).copy()
    all_tasks = _ensure_cols(inputs.all_tasks.copy(), ["clndr_id"])
    code_by_id = all_tasks.set_index("task_id")["task_code"]
    hours_per_day_by_id = (
        all_tasks.set_index("task_id")["clndr_id"].map(inputs.hours_per_day).astype(float).fillna(default_hours)
    )
    relationships["succ_code"] = relationships["task_id"].map(code_by_id)
    relationships["pred_code"] = relationships["pred_task_id"].map(code_by_id)
    relationships["type"] = relationships["pred_type"].map(REL_TYPE).fillna(relationships["pred_type"])
    lag_names = relationships["pred_code"].astype(str) + "->" + relationships["succ_code"].astype(str)
    lag_hours = to_number(relationships["lag_hr_cnt"]).fillna(0.0)
    relationships["lag_hr"] = validate.usable_hours(
        lag_hours, "relationship lag", lag_names, inputs.source, inputs.warnings
    )
    # Lag hours -> days. Oracle: "Lag entered in a unit other than hours is converted
    # to hours based on the predecessor activity's calendar", whatever calendar the lag
    # is then scheduled on (that one is the CPM's business, analysis/cpm.py).
    lag_hours_per_day = relationships["pred_task_id"].map(hours_per_day_by_id)
    relationships["lag_d"] = hours_to_days(
        relationships["lag_hr"], lag_hours_per_day.astype(float).fillna(default_hours)
    )
    relationships["is_external"] = relationships["pred_proj_id"].ne(project_id) & relationships["pred_proj_id"].ne("")
    # A predecessor in another project of the same file is named as in external_links:
    # its own Activity ID may also exist here, and would read as a link from that one.
    external_in_file = relationships["is_external"] & relationships["pred_code"].notna()
    external_names = "[ext]" + relationships.loc[external_in_file, "pred_task_id"].astype(str)
    relationships.loc[external_in_file, "pred_code"] = external_names
    local_codes = all_tasks.loc[all_tasks["proj_id"] == project_id, "task_code"]
    validate.placeholder_clashes(local_codes, external_names, inputs.source, inputs.warnings)
    # Counted before the unschedulable links go: those still have an external predecessor.
    external_predecessors = set(relationships.loc[relationships["is_external"], "task_id"])

    # A predecessor with no TASK row is a link to another project (P6 exports the link, not
    # the other project's activities) or a corrupt link. Either way it is not logic that can
    # be scheduled; only the corrupt ones are reported.
    lost = relationships["succ_code"].isna() | relationships["pred_code"].isna()
    corrupt = lost & ~relationships["is_external"]
    if corrupt.any():
        inputs.warnings.append(
            f"{inputs.source}: {int(corrupt.sum())} relationship(s) to a task "
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
    _typed_dates(external_tasks, TASK_DATE_COLS, "TASK", inputs)
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
            f"{inputs.source}: {count} open tasks have a remaining early start "
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
            f"latest task finish {finish:%Y-%m-%d}; using the tasks"
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
    project_task_counts: dict[str, int]  # TASK rows by proj_id
    data_date: pd.Timestamp | None
    data_date_source: str
    project_codes: dict[str, str] = field(default_factory=dict)  # proj_id -> project code


def read_header(raw: RawXer) -> FileHeader:
    """The default project and data date of a file, by the rules of build_snapshot, from
    PROJECT and TASK alone (a RawXer parsed with ``keep=HEADER_TABLES`` is enough)."""
    warnings: list[str] = []
    projects = _project_table(raw, warnings)
    all_tasks = _task_table(raw, projects, warnings)
    project_row, task_counts, codes, selected_by = _select_project(raw.source, projects, all_tasks, None, warnings)
    data_date, data_date_source = _data_date(project_row)
    return FileHeader(
        raw.source, project_row["proj_short_name"], selected_by, task_counts, data_date, data_date_source, codes
    )


def build_snapshot(
    raw: RawXer,
    project_code: str | None = None,
    settings: Settings = DEFAULT_SETTINGS,
    project_id: str | None = None,
) -> Snapshot:
    """Turn a parsed XER into a typed Snapshot for one project.

    If the file contains several projects, ``project_code`` selects one; otherwise the
    project with the most activities is used and a warning is recorded. ``project_id``
    (PROJECT.proj_id) selects one exactly, over ``project_code``.
    """
    warnings = list(raw.warnings)  # appended to in the order the steps run: that order is observable
    projects = _project_table(raw, warnings)
    all_tasks = _task_table(raw, projects, warnings)
    all_relationships = _taskpred_table(raw, all_tasks, warnings)

    # The project, its data date and its calendars
    project_row, task_counts, _codes, selected_by = _select_project(
        raw.source, projects, all_tasks, project_code, warnings, project_id
    )
    planned_start = _parse_date(project_row["plan_start_date"])
    data_date, data_date_source = _data_date(project_row)
    if data_date is None:
        warnings.append(f"{raw.source}: no status date (last_recalc_date / plan_start_date blank)")
    calendars, hours_per_day, work_calendars = _calendars(raw, settings, warnings)
    inputs = _BuildInputs(raw, all_tasks, all_relationships, project_row, hours_per_day, settings, warnings)
    wbs, project_name = _wbs_frame(raw, inputs.project_id, warnings)
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
    code_values, task_codes = _activity_codes(raw, tasks)

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
        code_values=code_values,
        task_codes=task_codes,
        file_projects=_file_projects(projects, all_tasks),
        xer_tables={name: (len(table), len(table.columns)) for name, table in raw.tables.items()},
    )
    _check_snapshot_columns(snapshot)
    return snapshot
