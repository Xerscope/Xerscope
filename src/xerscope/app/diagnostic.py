"""The tables of the Debug page: what xerscope read from the file and what it decided.

Reads only: ``Snapshot``, ``analysis.cpm.Options`` and ``schedule``, the integrity comparisons,
the P6 standard. Nothing here computes a date or a count; the page shows these frames and
``Anonymizer.zip_frames`` hands them out.
"""

from __future__ import annotations

import codecs
import csv
import io
import math
import re
import warnings
from collections.abc import Iterable

import pandas as pd

from xerscope.analysis.baseline import RENUMBERED_COLUMNS, Baseline, renumbered
from xerscope.analysis.cpm import ASSIGNMENT_FIELDS, FIELDS, Options, compare_assignments, compare_with_stored, schedule
from xerscope.analysis.evm import (
    PV_P6_OPTIONAL,
    PV_P6_REQUIRED,
    PV_P6_TOLERANCE_HR,
    PvComparison,
    etc_settings,
    etc_technique_counts,
    pv_labor_check,
    pv_p6_comparison,
)
from xerscope.analysis.rules import RULES
from xerscope.analysis.standards import Standard
from xerscope.app.ui import as_dates
from xerscope.config import DEFAULT_SETTINGS
from xerscope.xer.calendar import Intervals
from xerscope.xer.model import (
    FILE_PROJECT_COLUMNS,
    PCT_TYPE_COUNT_COLUMNS,
    PROJECT_SETTING_COLUMNS,
    Snapshot,
    leveled,
    to_number,
)

FROM_FILE, DEFAULTED, BLANK = "file", "default (blank in file)", "blank in file (no default)"

# Activity inputs the CPM reads (analysis/cpm.py, _Run.__init__): shown next to every difference.
INPUT_COLS = [
    "task_type",
    "status_code",
    "cstr_type",
    "cstr_date",
    "cstr_type2",
    "cstr_date2",
    "clndr_id",
    "remain_drtn_hr_cnt",
    "expect_end_date",
    "is_loe",
    "is_milestone",
]
ASSIGNMENT_INPUT_COLS = ["rsrc_id", "rsrc_clndr_id", "driving", "remain_qty", "remain_qty_per_hr", "relag_drtn_hr_cnt"]

# Fixed readings of the P6 Check Schedule dialog options (analysis/p6/check_schedule.py docstrings).
P6_DIALOG_OPTIONS = [
    ("Dangling Start", "Ignore in-progress activities", "applied (started tasks excluded)"),
    ("Dangling Finish", "Ignore activities with soft constraints", "not read (unchecked in P6 by default)"),
    ("Dangling Finish", "Ignore activities with hard constraints", "not read (unchecked in P6 by default)"),
]
# The dialog's three tabs, as the P6 Professional 26 help names them (client_help 101248):
# Relationships and Assignments (113174 lists logic, lags, relationship types, out of sequence,
# resource / cost, dangling), Dates and Durations, Constraints. Only the first tab's content is
# given by that help; the other two are read from the checks' names.
RELATIONSHIPS, DATES, CONSTRAINTS = "Relationships and Assignments", "Dates and Durations", "Constraints"
P6_TABS = {
    "P6-01": RELATIONSHIPS,
    "P6-02": CONSTRAINTS,
    "P6-03": CONSTRAINTS,
    "P6-04": DATES,
    "P6-05": RELATIONSHIPS,
    "P6-06": DATES,
    "P6-07": RELATIONSHIPS,
    "P6-08": RELATIONSHIPS,
    "P6-09": RELATIONSHIPS,
    "P6-10a": DATES,
    "P6-10b": DATES,
    "P6-11": RELATIONSHIPS,
    "P6-12": DATES,
    "P6-13": DATES,
    "P6-14": DATES,
    "P6-15": RELATIONSHIPS,
    "P6-16": RELATIONSHIPS,
    "P6-17": RELATIONSHIPS,
}


def _row(option: str, source: str, raw: object, applied: object, default: object) -> dict:
    blank = raw is None or raw == "" or (isinstance(raw, float) and pd.isna(raw))
    return {
        "option": option,
        "xer_field": source,
        "raw": "" if blank else str(raw),
        "applied": str(applied),
        "origin": (BLANK if default is None else DEFAULTED) if blank else FROM_FILE,
        "default": "" if default is None else str(default),
    }


def options_table(snapshot: Snapshot) -> pd.DataFrame:
    """One row per scheduling option ``Options.from_snapshot`` reads: raw XER value, value applied, origin."""
    options = Options.from_snapshot(snapshot)
    sched = snapshot.options.get("sched", {}) or {}
    project = snapshot.options.get("project", {})
    read = snapshot.options
    retained, override = sched.get("sched_retained_logic", ""), sched.get("sched_progress_override", "")
    critical_hr = read.get("critical_float_hr")
    export = read.get("export", {}) or {}
    export_raw = " / ".join(part for part in (export.get("version"), export.get("product")) if part)
    rows = [
        _row("use_expected_finish", "SCHEDOPTIONS.sched_use_expect_end_flag", sched.get("sched_use_expect_end_flag"),
             options.use_expected_finish, True),
        _row("float_type", "SCHEDOPTIONS.sched_float_type", sched.get("sched_float_type"), options.float_type, "FT_FF"),
        _row("open_critical", "SCHEDOPTIONS.sched_open_critical_flag", sched.get("sched_open_critical_flag"),
             options.open_critical, False),
        _row("lag_from_early_start", "SCHEDOPTIONS.sched_lag_early_start_flag",
             sched.get("sched_lag_early_start_flag"), options.lag_from_early_start, True),
        _row("honor_external", "SCHEDOPTIONS.sched_outer_depend_type", sched.get("sched_outer_depend_type"),
             options.honor_external, "SD_Both"),
        _row("export_version", "ERMHDR.version + product", export_raw,
             f"collapse_early_expected_finish={options.collapse_early_expected_finish}", None),
        _row("progressed", "SCHEDOPTIONS.sched_retained_logic + sched_progress_override",
             f"{retained}+{override}" if retained or override else "", options.progressed, "retained_logic"),
        _row("lag_calendar", "SCHEDOPTIONS.sched_calendar_on_relationship_lag",
             sched.get("sched_calendar_on_relationship_lag"), options.lag_calendar, "rcal_Successor"),
        _row("critical_path_type", "PROJECT.critical_path_type", project.get("critical_path_type"),
             read.get("critical_path_type"), "CT_TotFloat"),
        _row("critical_float_hr", "PROJECT.critical_drtn_hr_cnt", project.get("critical_drtn_hr_cnt"),
             critical_hr if critical_hr is not None else f"{DEFAULT_SETTINGS.critical_float_days} d (Settings)",
             f"{DEFAULT_SETTINGS.critical_float_days} d (Settings)"),
        _row("must_finish_by", "PROJECT.plan_end_date", project.get("plan_end_date"), options.must_finish_by, None),
    ]  # fmt: skip
    return pd.DataFrame(rows)


ANALYSED, BASELINE_OF_ANALYSED = "analysed project", "baseline of the analysed project"


def projects_table(snapshot: Snapshot) -> pd.DataFrame:
    """Every PROJECT row of the file: TASK rows, the baseline pointers, and the role in this analysis.

    The baseline of the analysed project is the project its ``sum_base_proj_id`` names (P6's
    "Project Baseline"); ``orig_proj_id`` ("Original Project") of a baseline copy names the project
    it was copied from.
    """
    table = snapshot.file_projects[FILE_PROJECT_COLUMNS].copy()
    analysed = table["proj_id"] == snapshot.project_id
    pointer = table.loc[analysed, "sum_base_proj_id"]
    pointed = pointer.iloc[0] if len(pointer) else ""
    table["role"] = ""
    table.loc[(table["proj_id"] == pointed) & (pointed != "") & ~analysed, "role"] = BASELINE_OF_ANALYSED
    table.loc[analysed, "role"] = ANALYSED
    return table


BASELINE_POINTER_COLUMNS = [
    "file", "data_date", "proj_id", "add_date", "sum_base_proj_id", "baseline_in_file", "use_project_baseline_flag",
]  # fmt: skip


def baseline_pointers(snapshots: Iterable[Snapshot]) -> pd.DataFrame:
    """One row per update, in the order given (a SnapshotStore: data date order): the analysed
    project's proj_id, add_date and use_project_baseline_flag as stored, the Project Baseline it
    names (sum_base_proj_id) and whether the same file holds that project."""
    rows = []
    for snapshot in snapshots:
        projects = snapshot.file_projects.set_index("proj_id")
        project = projects.loc[snapshot.project_id]
        pointer = str(project["sum_base_proj_id"])
        rows.append(
            {
                "file": snapshot.source,
                "data_date": snapshot.data_date,
                "proj_id": snapshot.project_id,
                "add_date": project["add_date"],
                "sum_base_proj_id": pointer,
                "baseline_in_file": bool(pointer) and pointer in projects.index,
                "use_project_baseline_flag": project["use_project_baseline_flag"],
            }
        )
    return pd.DataFrame(rows, columns=BASELINE_POINTER_COLUMNS)


def renumbered_table(snapshot: Snapshot, baseline: Baseline | None, previous: Snapshot | None) -> pd.DataFrame:
    """Tasks of ``snapshot`` that carry the GUID of a task of the baseline file, or of the previous
    update, under a new Activity ID (``baseline.renumbered``). ``baseline`` as chosen, not linked."""
    frames = [
        renumbered(other, snapshot).assign(against=against)
        for against, other in (("baseline", baseline.snapshot if baseline else None), ("previous update", previous))
        if other is not None and other is not snapshot
    ]
    columns = ["against", *RENUMBERED_COLUMNS]
    return pd.concat(frames)[columns].reset_index(drop=True) if frames else pd.DataFrame(columns=columns)


GUID_MATCH_COLUMNS = [
    "against", "tasks", "tasks_against", "guids_blank", "guids_repeated", "guids_shared",
    "ids_in_both", "ids_gone", "ids_new", "renumbered", "gone_guid_in_update", "gone_guid_absent",
]  # fmt: skip


def _usable_guids(snapshot: Snapshot) -> pd.Series:
    """task_code -> GUID of ``snapshot``, blank and repeated GUIDs left out (as ``renumbered`` reads them)."""
    tasks = snapshot.activities
    if "guid" not in tasks:
        return pd.Series(dtype=str)
    guids = pd.Series(tasks["guid"].fillna("").astype(str).str.strip().to_numpy(), index=tasks["task_code"])
    guids = guids[guids != ""]
    return guids[~guids.duplicated(keep=False)]


def guid_match_table(snapshot: Snapshot, baseline: Baseline | None, previous: Snapshot | None) -> pd.DataFrame:
    """Counts only (no code, no GUID): how the tasks of ``snapshot`` match those of the baseline file and
    of the previous update, by Activity ID and by GUID (TASK.guid). ``renumbered`` is what the option
    "Link renumbered tasks by GUID" links. Of the other tasks gone, ``gone_guid_absent`` counts those
    whose GUID the update does not carry at all (deleted, or a copy of the project with new GUIDs) and
    ``gone_guid_in_update`` those whose GUID it carries under an ID the option cannot take (an ID the
    other file holds too); gone tasks without a usable GUID are in neither."""
    rows = []
    for against, other in (("baseline", baseline.snapshot if baseline else None), ("previous update", previous)):
        if other is None or other is snapshot:
            continue
        mine, theirs = _usable_guids(snapshot), _usable_guids(other)
        codes, other_codes = set(snapshot.activities["task_code"]), set(other.activities["task_code"])
        raw = snapshot.activities.get("guid", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
        pairs = renumbered(other, snapshot)
        gone = other_codes - codes - set(pairs["old_code"])
        gone_guids = theirs[theirs.index.isin(gone)]
        rows.append(
            {
                "against": against,
                "tasks": len(codes),
                "tasks_against": len(other_codes),
                "guids_blank": int((raw == "").sum()),
                "guids_repeated": int(raw[raw != ""].duplicated(keep=False).sum()),
                "guids_shared": len(set(mine) & set(theirs)),
                "ids_in_both": len(codes & other_codes),
                "ids_gone": len(other_codes - codes),
                "ids_new": len(codes - other_codes),
                "renumbered": len(pairs),
                "gone_guid_in_update": int(gone_guids.isin(set(mine)).sum()),
                "gone_guid_absent": int((~gone_guids.isin(set(mine))).sum()),
            }
        )
    return pd.DataFrame(rows, columns=GUID_MATCH_COLUMNS)


def expected_finish_table(snapshot: Snapshot) -> pd.DataFrame:
    """Activities with an expected finish: stored dates and remaining, recalculated early dates,
    and whether the expected finish set the remaining duration (``rem_override_hr``, 0 = brought to 0)."""
    tasks = snapshot.by_code
    with_expected = tasks[tasks["expect_end_date"].notna()] if "expect_end_date" in tasks else tasks.iloc[0:0]
    frame = schedule(snapshot).frame
    columns = ["status_code", "early_start_date", "early_end_date", "remain_drtn_hr_cnt", "expect_end_date"]
    out = with_expected[[column for column in columns if column in with_expected]].copy()
    out["es_recalc"] = frame["es"].reindex(out.index)
    out["remaining_start_recalc"] = frame["remaining_start"].reindex(out.index)
    out["ef_recalc"] = frame["ef"].reindex(out.index)
    out["rem_override_hr"] = frame["rem_override_hr"].reindex(out.index)
    out["remaining_set_to_0"] = out["rem_override_hr"] == 0
    return out.reset_index()


def _inputs(snapshot: Snapshot, codes: pd.Index) -> pd.DataFrame:
    tasks = snapshot.by_code
    inputs = tasks.loc[codes, [column for column in INPUT_COLS if column in tasks]].copy()
    inputs["calendar_hours_per_day"] = [snapshot.calendar(clndr).hours_per_day for clndr in inputs["clndr_id"]]
    frame = schedule(snapshot).frame
    for column in ("resource_dependent", "longest_path", "rem_override_hr"):
        inputs[column] = frame[column].reindex(codes)
    return inputs


def recalculation_table(snapshot: Snapshot) -> pd.DataFrame:
    """INT-01: one row per activity with a stored date or float that differs from the recalculation,
    stored and recalculated values side by side, then the inputs the CPM read for it."""
    empty = pd.DataFrame(columns=["task_code", "differs"])
    comparison = compare_with_stored(snapshot)
    if comparison.empty:
        return empty
    comparison = comparison[comparison["stored"].notna()]
    differing = comparison[~comparison["agree"]]["task_code"].unique()
    if not len(differing):
        return empty
    wide = comparison[comparison["task_code"].isin(differing)]
    stored = wide.pivot(index="task_code", columns="field", values="stored")
    computed = wide.pivot(index="task_code", columns="field", values="computed")
    out = pd.DataFrame(index=pd.Index(sorted(differing), name="task_code"))
    for _, stored_name in FIELDS:
        if stored_name in stored:
            out[stored_name] = stored[stored_name]
            out[f"{stored_name}_recalc"] = computed[stored_name]
    out["differs"] = wide[~wide["agree"]].groupby("task_code")["field"].agg(", ".join)
    return out.join(_inputs(snapshot, out.index)).reset_index()


def assignments_table(snapshot: Snapshot) -> pd.DataFrame:
    """INT-03: one row per open assignment whose stored remaining dates differ, with TASKRSRC inputs."""
    empty = pd.DataFrame(columns=["taskrsrc_id", "task_code", "differs"])
    comparison = compare_assignments(snapshot)
    if comparison.empty:
        return empty
    comparison = comparison[comparison["stored"].notna()]
    differing = comparison[~comparison["agree"]]["taskrsrc_id"].unique()
    if not len(differing):
        return empty
    wide = comparison[comparison["taskrsrc_id"].isin(differing)]
    stored = wide.pivot(index="taskrsrc_id", columns="field", values="stored")
    computed = wide.pivot(index="taskrsrc_id", columns="field", values="computed")
    out = pd.DataFrame(index=pd.Index(sorted(differing), name="taskrsrc_id"))
    out["task_code"] = wide.groupby("taskrsrc_id")["task_code"].first()
    for _, stored_name in ASSIGNMENT_FIELDS:
        if stored_name in stored:
            out[stored_name] = stored[stored_name]
            out[f"{stored_name}_recalc"] = computed[stored_name]
    out["differs"] = wide[~wide["agree"]].groupby("taskrsrc_id")["field"].agg(", ".join)
    assignments = snapshot.assignments.astype({"taskrsrc_id": str}).set_index("taskrsrc_id")
    inputs = assignments.loc[out.index, [column for column in ASSIGNMENT_INPUT_COLS if column in assignments]]
    return out.join(inputs).reset_index()


def check_parameters(standard: Standard) -> pd.DataFrame:
    """Targets and the x threshold of the P6 standard, each check on its dialog tab."""
    rows = [
        {
            "tab": P6_TABS.get(metric.id, ""),
            "check": f"{metric.id} · {metric.name}",
            "target": metric.threshold_label,
            "x_hours": {**RULES[metric.rule].params, **metric.params}.get("limit_hours"),
        }
        for metric in standard.metrics
    ]
    rows += [
        {"tab": RELATIONSHIPS, "check": f"{check} · {option}", "target": reading, "x_hours": None}
        for check, option, reading in P6_DIALOG_OPTIONS
    ]
    return pd.DataFrame(rows)


def baseline_table(snapshot: Snapshot, baseline: Baseline | None, anonymous: bool = False) -> pd.DataFrame:
    """The baseline in use: label, kind, activities of the update it covers. ``anonymous``: the label
    names no file (the file name carries the project code), only the kind of baseline."""
    if baseline is None:
        return pd.DataFrame([{"baseline": "none", "kind": "", "matched": 0, "activities": len(snapshot.by_code)}])
    codes = snapshot.by_code.index
    planned = baseline.snapshot is snapshot
    in_file = not planned and baseline.snapshot.source == snapshot.source
    label = baseline.label
    if anonymous:
        label = "planned dates of the update" if planned else "baseline file"
        label = "project baseline in the file" if in_file else label
    return pd.DataFrame(
        [
            {
                "baseline": label,
                "kind": "planned dates (target_*)"
                if planned
                else "project baseline in the file"
                if in_file
                else "separate file",
                "matched": len(codes) - len(baseline.unbaselined(snapshot)),
                "activities": len(codes),
            }
        ]
    )


def calendars_table(snapshot: Snapshot) -> pd.DataFrame:
    """Each calendar of the file: hours per day and how many activities use it."""
    used = snapshot.activities["clndr_id"].value_counts()
    calendars = snapshot.calendars[["clndr_id", "day_hr_cnt"]].copy() if "clndr_id" in snapshot.calendars else None
    if calendars is None or calendars.empty:
        calendars = pd.DataFrame({"clndr_id": used.index, "day_hr_cnt": None})
    calendars["hours_per_day"] = [snapshot.calendar(clndr).hours_per_day for clndr in calendars["clndr_id"]]
    calendars["activities"] = calendars["clndr_id"].map(used).fillna(0).astype(int)
    calendars["project_default"] = calendars["clndr_id"] == snapshot.project_clndr_id
    return calendars.reset_index(drop=True)


WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)  # WorkCalendar.week order
HOUR_COUNT_COLUMNS = ["day_hr_cnt", "week_hr_cnt", "month_hr_cnt", "year_hr_cnt"]  # P6 "Hours per Time Period"
CALENDAR_TEXT_COLUMNS = ["clndr_type", "default_flag", "base_clndr_id"]


def working_periods_text(periods: Intervals) -> str:
    """One day's working periods as written in P6, "08:00-12:00, 13:00-17:00"; "" for a non-working day."""

    def clock(minute_of_day: int) -> str:
        return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"  # the end of a 24 h day reads 24:00

    return ", ".join(f"{clock(start)}-{clock(end)}" for start, end in periods)


def working_hours_of(periods: Intervals) -> float:
    """Working hours of one day's periods."""
    return sum(end - start for start, end in periods) / 60


EXCEPTION_KINDS = (
    "non-working day",
    "working day on a non-working weekday",
    "other working hours",
    "same hours as the weekday",
)


def exception_kind(exception_periods: Intervals, normal_periods: Intervals) -> str:
    """What a calendar exception does to the day it replaces."""
    if not exception_periods:
        return "non-working day"
    if not normal_periods:
        return "working day on a non-working weekday"
    if exception_periods != normal_periods:
        return "other working hours"
    return "same hours as the weekday"


def calendar_summary_table(snapshot: Snapshot, anonymous: bool = False) -> pd.DataFrame:
    """One row per calendar of the file: the hours per time period P6 stores (CALENDAR.*_hr_cnt), the
    working time its periods (clndr_data) add up to, whether the two agree, and its exceptions by kind.
    ``anonymous``: without the calendar name."""
    activities_per_calendar = snapshot.activities["clndr_id"].value_counts()
    calendar_rows = snapshot.calendars
    stored = (
        calendar_rows.drop_duplicates("clndr_id").set_index("clndr_id")
        if "clndr_id" in calendar_rows
        else pd.DataFrame()
    )
    rows = []
    for clndr_id, calendar in snapshot.work_calendars.items():
        stored_row = stored.loc[clndr_id] if clndr_id in stored.index else pd.Series(dtype=object)
        stored_hours = {column: pd.to_numeric(stored_row.get(column), errors="coerce") for column in HOUR_COUNT_COLUMNS}
        day_lengths = sorted({working_hours_of(periods) for periods in calendar.week if periods})
        week_hours = sum(working_hours_of(periods) for periods in calendar.week)
        kinds = pd.Series(
            [exception_kind(periods, calendar.week[day.weekday()]) for day, periods in calendar.exceptions.items()],
            dtype=object,
        ).value_counts()
        rows.append(
            {
                "clndr_id": clndr_id,
                **({} if anonymous else {"clndr_name": calendar.name}),
                **{column: stored_row.get(column, "") for column in CALENDAR_TEXT_COLUMNS},
                **stored_hours,
                "periods_read_from": "clndr_data" if calendar.from_data else "guessed from day/week hours",
                "working_days_per_week": sum(1 for periods in calendar.week if periods),
                "week_hours_from_periods": week_hours,
                "day_lengths_from_periods": ", ".join(f"{hours:g}" for hours in day_lengths),
                "day_hr_cnt_matches_periods": len(day_lengths) == 1 and stored_hours["day_hr_cnt"] == day_lengths[0],
                "week_hr_cnt_matches_periods": stored_hours["week_hr_cnt"] == week_hours,
                "hours_per_day_used_for_days": calendar.hours_per_day,
                "exceptions": len(calendar.exceptions),
                **{f"exceptions_{kind.replace(' ', '_')}": int(kinds.get(kind, 0)) for kind in EXCEPTION_KINDS},
                "first_exception": min(calendar.exceptions, default=None),
                "last_exception": max(calendar.exceptions, default=None),
                "activities": int(activities_per_calendar.get(clndr_id, 0)),
                "project_default": clndr_id == snapshot.project_clndr_id,
            }
        )
    return pd.DataFrame(rows)


def calendar_week_table(snapshot: Snapshot) -> pd.DataFrame:
    """One row per calendar and weekday: the working periods read from clndr_data (DaysOfWeek)."""
    rows = [
        {
            "clndr_id": clndr_id,
            "weekday": WEEKDAY_NAMES[weekday],
            "working_periods": working_periods_text(periods),
            "working_hours": working_hours_of(periods),
        }
        for clndr_id, calendar in snapshot.work_calendars.items()
        for weekday, periods in enumerate(calendar.week)
    ]
    return pd.DataFrame(rows, columns=["clndr_id", "weekday", "working_periods", "working_hours"])


def calendar_exceptions_table(snapshot: Snapshot) -> pd.DataFrame:
    """One row per calendar exception (clndr_data Exceptions): its date, what it does to the weekday
    it replaces, and the working periods of both."""
    rows = []
    for clndr_id, calendar in snapshot.work_calendars.items():
        for day, periods in sorted(calendar.exceptions.items()):
            normal_periods = calendar.week[day.weekday()]
            rows.append(
                {
                    "clndr_id": clndr_id,
                    "date": day,
                    "weekday": WEEKDAY_NAMES[day.weekday()],
                    "kind": exception_kind(periods, normal_periods),
                    "working_periods": working_periods_text(periods),
                    "working_hours": working_hours_of(periods),
                    "weekday_working_periods": working_periods_text(normal_periods),
                    "weekday_working_hours": working_hours_of(normal_periods),
                }
            )
    columns = [
        "clndr_id",
        "date",
        "weekday",
        "kind",
        "working_periods",
        "working_hours",
        "weekday_working_periods",
        "weekday_working_hours",
    ]
    return pd.DataFrame(rows, columns=columns)


def calendar_detail_frames(snapshot: Snapshot, anonymous: bool = False) -> dict[str, pd.DataFrame]:
    """Block 13: every calendar of the file, its weekly periods and its exceptions, named as in the zip."""
    return {
        "13_calendar_summary": calendar_summary_table(snapshot, anonymous),
        "13_calendar_week": calendar_week_table(snapshot),
        "13_calendar_exceptions": calendar_exceptions_table(snapshot),
    }


def leveling_table(snapshot: Snapshot) -> pd.DataFrame:
    """The activities the leveling load warning counts (``xer.model.leveled``)."""
    tasks = snapshot.tasks
    columns = ["task_code", "status_code", "early_start_date", "restart_date", "act_start_date"]
    return tasks.loc[leveled(tasks), columns].reset_index(drop=True)


def finish_table(snapshot: Snapshot, latest: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """PROJECT.scd_end_date against the latest activity finish, and the activities that end last."""
    project = pd.DataFrame(
        [{"scd_end_date": snapshot.scheduled_finish, "latest_activity_finish": snapshot.finish_date}]
    )
    activities = snapshot.activities[["task_code", "task_type", "status_code", "finish"]]
    return project, activities.nlargest(latest, "finish").reset_index(drop=True)


ABSENT = "absent"


def costs_table(snapshot: Snapshot) -> pd.DataFrame:
    """Whether the file carries costs (P6 computes its cost SPI from them): TASKRSRC and PROJCOST.

    Per table: rows, rows whose ``target_cost`` is above 0, ``target_cost`` total, and for
    TASKRSRC the smallest and largest ``cost_per_qty``. "absent": the column is missing or blank
    on every row.
    """
    assignments, expenses = snapshot.assignments, snapshot.expenses

    def values(frame: pd.DataFrame, column: str) -> pd.Series:
        return to_number(frame[column]).dropna() if column in frame.columns else pd.Series(dtype=float)

    def figures(frame: pd.DataFrame, rate: bool) -> dict:
        cost, per_qty = values(frame, "target_cost"), values(frame, "cost_per_qty")
        return {
            "rows": len(frame),
            "rows_with_cost": int((cost > 0).sum()) if len(cost) else ABSENT,
            "target_cost_total": float(cost.sum()) if len(cost) else ABSENT,
            "cost_per_qty_min": (float(per_qty.min()) if len(per_qty) else ABSENT) if rate else "",
            "cost_per_qty_max": (float(per_qty.max()) if len(per_qty) else ABSENT) if rate else "",
        }

    return pd.DataFrame(
        [
            {"table": "TASKRSRC", **figures(assignments, rate=True)},
            {"table": "PROJCOST", **figures(expenses, rate=False)},
        ]
    )


def xer_tables_table(snapshot: Snapshot) -> pd.DataFrame:
    """Block 09: one row per %T table of the XER read (name, rows, columns), no cell value."""
    return pd.DataFrame(
        [{"table": name, "rows": rows, "columns": cols} for name, (rows, cols) in snapshot.xer_tables.items()],
        columns=["table", "rows", "columns"],
    )


LABOR_KINDS = ("RT_Labor", "role", "")  # as xer.model._labor_hours


def assignment_dates_table(snapshot: Snapshot) -> pd.DataFrame:
    """Labour assignments (TASKRSRC) against their activity: do they carry their own dates?

    One row of counts, no code. Original Lag is TASKRSRC.target_lag_drtn_hr_cnt and Remaining
    Lag relag_drtn_hr_cnt (Oracle XER data map, TASKRSRC). "Planned start later" / "planned
    finish earlier": the assignment's Planned Start / Finish (target_*) differ from its
    activity's. Task dependent activities with an assignment on a resource calendar other than
    the activity's: P6 schedules those assignments on the activity's calendar (P6 help, "Task
    dependent activity"), while the planned value spreads them on the resource's.
    """
    assignments = snapshot.assignments
    assignments = assignments[assignments["rsrc_type"].isin(LABOR_KINDS)] if not assignments.empty else assignments
    activities = snapshot.by_code

    def number(column: str) -> pd.Series:
        return (
            to_number(assignments[column]).fillna(0.0)
            if column in assignments
            else pd.Series(0.0, index=assignments.index)
        )

    def date(frame: pd.DataFrame, column: str) -> pd.Series:
        return as_dates(frame[column]) if column in frame else pd.Series(pd.NaT, index=frame.index)

    task_start = assignments["task_code"].map(date(activities, "target_start_date"))
    task_finish = assignments["task_code"].map(date(activities, "target_end_date"))
    own_start, own_finish = date(assignments, "target_start_date"), date(assignments, "target_end_date")
    task_type = (
        assignments["task_code"].map(activities["task_type"])
        if "task_type" in activities
        else pd.Series("", index=assignments.index)
    )
    task_calendar = assignments["task_code"].map(activities["clndr_id"]).fillna("").astype(str)
    resource_calendar = (
        assignments["rsrc_clndr_id"].fillna("").astype(str)
        if "rsrc_clndr_id" in assignments
        else pd.Series("", index=assignments.index)
    )
    other_calendar = (resource_calendar != "") & (resource_calendar != task_calendar)
    return pd.DataFrame(
        [
            {
                "labor_assignments": len(assignments),
                "with_original_lag": int((number("target_lag_drtn_hr_cnt") > 0).sum()),
                "with_remaining_lag": int((number("relag_drtn_hr_cnt") > 0).sum()),
                "planned_dates_blank": int((own_start.isna() | own_finish.isna()).sum()),
                "planned_start_later_than_activity": int((own_start > task_start).sum()),
                "planned_finish_earlier_than_activity": int((own_finish < task_finish).sum()),
                "task_dependent_on_other_calendar": int((other_calendar & (task_type == "TT_Task")).sum()),
                "resource_dependent": int((task_type == "TT_Rsrc").sum()),
            }
        ]
    )


def _listed(value: object) -> object:
    """Items of a comma-separated list (the separator is assumed: no reference file fills one)."""
    return value if value is None else sum(1 for item in str(value).split(",") if item.strip())


def project_settings_table(snapshot: Snapshot) -> pd.DataFrame:
    """Block 11: the ``PROJECT_SETTING_COLUMNS`` of every project of the file as stored, ``absent``
    when the file has no such column, and its TASK rows by complete_pct_type. Of
    baseline_names_to_export only the number of names is shown. No KPI reads this."""
    table = snapshot.file_projects[["proj_id", "proj_short_name", *PROJECT_SETTING_COLUMNS, *PCT_TYPE_COUNT_COLUMNS]]
    table = table.copy()
    table["baseline_names_to_export"] = table["baseline_names_to_export"].map(_listed)
    return table.astype(object).where(table.notna(), ABSENT)


# What each setting is in P6. Label: P6 EPPM XER Import/Export Data Map, table PROJECT, version 23
# (docs.oracle.com/cd/F74771_01, xer_import_export_data_map_project.pdf). Help: P6 Professional 26
# help (G57535-02, October 2026), the section named. A Y / N reading taken from the label alone is
# marked unverified: no reference file holds the opposite value with P6's own output.
DATA_MAP = "data map v23"
CALCULATIONS = "help 26, Calculations tab - Project Details"
NEW_ACTIVITIES = "help 26, Project Details, Defaults for New Activities"
NO_LABEL = "not in data map v23"
SETTINGS_MEANING = [
    ("PROJECT.use_project_baseline_flag", "use_project_baseline_flag (no label)",
     "Baseline for earned value calculation: the project baseline or your primary baseline",
     "help 26, Settings tab - Project Details", "Y = project baseline: unverified (matched by name)"),
    ("PROJECT.sum_base_proj_id", "Project Baseline", "Project Baseline (Assign Baselines dialog box)",
     "help 26, Assign Baselines dialog box", "proj_id of the baseline project"),
    ("PROJECT.baselines_to_export", NO_LABEL, "Baselines to Export, per project, for a Primavera XML export",
     "help 26, Baselines to Export dialog box", "how the list is stored: unverified (blank in every reference file)"),
    ("PROJECT.baseline_names_to_export", NO_LABEL, "Baselines to Export: Baseline Name",
     "help 26, Baselines to Export dialog box", "shown as a number of comma-separated names: separator unverified"),
    ("PROJECT.def_complete_pct_type", "Default Percent Complete Type", "Percent complete type of new activities",
     NEW_ACTIVITIES, "CP_Phys / CP_Drtn / CP_Units"),
    ("PROJECT.add_act_remain_flag", "Add Actual To Remain", "When updating Actual Units or Cost: Add Actual to "
     "Remaining, or Subtract Actual from At Completion", CALCULATIONS,
     "Y = Add Actual to Remaining: unverified (from the label)"),
    ("PROJECT.act_this_per_link_flag", "Link actual to date and actual this period units and costs",
     "Link actual to date and actual this period units and costs", CALCULATIONS, "Y = marked (from the label)"),
    ("PROJECT.act_pct_link_flag", "Link Percent Complete With Actual",
     "Recalculate Actual Units and Cost when duration % complete changes", CALCULATIONS,
     "Y = marked: unverified (label matched to the help by name)"),
    ("PROJECT.rem_target_link_flag", "Link Budget and At Completion",
     "Link Planned or Budget and At Completion for not started activities", CALCULATIONS,
     "Y = marked (from the label)"),
    ("PROJECT.reset_planned_flag", "Reset Original to Remaining", "Reset Planned or Original Duration and Units to "
     "Remaining, or Reset Remaining Duration and Units to Planned or Original", CALCULATIONS,
     "Y = Reset Planned to Remaining: unverified (from the label)"),
    ("PROJECT.def_task_type", "Default Activity Type", "Activity type of new activities", NEW_ACTIVITIES,
     "TT_* codes"),
    ("PROJECT.def_duration_type", "Default Duration Type", "Duration type of new activities", NEW_ACTIVITIES,
     "DT_* codes"),
    ("PROJECT.next_data_date", NO_LABEL, "", "", "meaning unverified"),
    ("PROJECT.last_recalc_date", "Last Recalc Date", "", DATA_MAP,
     "xerscope's status date (else plan_start_date)"),
    ("TASK.complete_pct_type", "% Complete Type", "Activity % Complete Type", "xer/model.py PCT_COMPLETE_TYPE",
     "tasks_* counts of the project"),
    ("PROJWBS: Use resource curves \\ future period buckets", "no column in data map v23 nor in the reference files",
     "Earned Value tab of the WBS: curves used for EV with Activity Percent Complete",
     "help 26, Calculating earned value using resource curves or manual future period buckets", ABSENT),
]  # fmt: skip


def project_settings_meaning_table() -> pd.DataFrame:
    """Static text, the same for every file: shown on the page, not in the zip."""
    return pd.DataFrame(SETTINGS_MEANING, columns=["field", "xer_label", "p6_setting", "source", "reading"])


def diagnostic_frames(
    snapshot: Snapshot, baseline: Baseline | None, standard: Standard, anonymous: bool = False
) -> dict[str, pd.DataFrame]:
    """Blocks 1 to 9, 11 and 13, named as the files of the diagnostic zip (block 10 is ``pv_p6_frames``).
    ``anonymous``: no file name in them."""
    project_finish, latest_finishes = finish_table(snapshot)
    ev_settings = etc_settings(snapshot)
    pv_totals, pv_by_status = pv_labor_check(snapshot, baseline)
    return {
        "01_options": options_table(snapshot),
        "01b_projects": projects_table(snapshot),
        "02_expected_finish": expected_finish_table(snapshot),
        "03_int01_recalculation": recalculation_table(snapshot),
        "03_int03_assignments": assignments_table(snapshot),
        "04_check_parameters": check_parameters(standard),
        "05_baseline": baseline_table(snapshot, baseline, anonymous),
        "05_calendars": calendars_table(snapshot),
        "06_leveling": leveling_table(snapshot),
        "06_project_finish": project_finish,
        "06_latest_finishes": latest_finishes,
        "07_costs": costs_table(snapshot),
        "08_ev_settings": ev_settings,
        "08_etc_techniques": etc_technique_counts(ev_settings),
        "09_xer_tables": xer_tables_table(snapshot),
        "09_pv_labor_check": pv_totals,
        "09_pv_labor_by_status": pv_by_status,
        "09_assignment_dates": assignment_dates_table(snapshot),
        "11_project_settings": project_settings_table(snapshot),
        **calendar_detail_frames(snapshot, anonymous),
    }


# Block 10: PV labour units against a P6 Activities export. Field -> header names accepted (matched
# without case or extra spaces), required. The page offers a choice of column for a field not found.
P6_EXPORT_FIELDS = {
    "task_code": (("Activity ID",), True),
    "pv_hr": (("Planned Value Labor Units",), True),
    "ev_hr": (("Earned Value Labor Units",), True),
    "schedule_pct": (("Schedule % Complete",), True),
    "bl_hr": (("BL Project Labor Units", "Budgeted Labor Units"), False),
    "status": (("Activity Status",), False),
    "bl_start": (("BL Project Start",), False),
    "bl_finish": (("BL Project Finish",), False),
    "start": (("Planned Start",), False),
    "finish": (("Planned Finish",), False),
}
assert set(PV_P6_OPTIONAL) | {"task_code", *PV_P6_REQUIRED} == set(P6_EXPORT_FIELDS)
P6_NUMBER_FIELDS = ["pv_hr", "ev_hr", "schedule_pct", "bl_hr"]
P6_EXPORT_SUFFIXES = ["csv"]
_THOUSANDS_COMMA = re.compile(r"-?\d{1,3}(,\d{3})+")
_P6_DATE_FLAG = re.compile(r"\s*[A*]$")  # P6 marks actual dates "A" and constraint dates "*"


def _header(name: object) -> str:
    return " ".join(str(name).split())


def _table(rows: list[list[str]]) -> pd.DataFrame:
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise ValueError("The export has no header row and data row.")
    frame = pd.DataFrame(rows[1:], columns=[_header(name) for name in rows[0]], dtype=str)
    return frame.loc[:, ~frame.columns.duplicated() & (frame.columns != "")]


def read_p6_export(name: str, content: bytes) -> pd.DataFrame:
    """The text cells of a P6 Activities export saved as CSV (comma, semicolon or tab), headers with
    single spaces. XLSX is not read: no Excel reader is among the dependencies.

    Raises ValueError for any file that is not a CSV table: nothing of the content is in the message.
    """
    if not name.lower().endswith(".csv"):
        raise ValueError("Only .csv exports are read: save the P6 view as CSV.")
    try:
        if content[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):  # Excel's "Unicode Text"
            text = content.decode("utf-16")
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("cp1252", errors="replace")
        with warnings.catch_warnings():
            # a row longer than the header: refused, never read with its first fields as the index
            warnings.simplefilter("error", pd.errors.ParserWarning)
            raw = pd.read_csv(
                io.StringIO(text), sep=None, engine="python", dtype=str, keep_default_na=False, index_col=False
            )
        # a row shorter than the header: its missing cells blank
        return _table([list(raw.columns)] + raw.fillna("").to_numpy().tolist())
    except (UnicodeDecodeError, ValueError, csv.Error, pd.errors.ParserError, pd.errors.ParserWarning) as exc:
        raise ValueError("The file cannot be read as a CSV table.") from exc


def p6_export_columns(raw: pd.DataFrame, chosen: dict[str, str] | None = None) -> dict[str, str | None]:
    """Column of ``raw`` for each field of ``P6_EXPORT_FIELDS``: the one ``chosen``, else the first
    accepted header present, else None."""
    present = {_header(column).casefold(): column for column in raw.columns}
    columns: dict[str, str | None] = {}
    for field, (names, _required) in P6_EXPORT_FIELDS.items():
        picked = (chosen or {}).get(field)
        found = [present[name.casefold()] for name in names if name.casefold() in present]
        columns[field] = picked if picked in raw.columns else (found[0] if found else None)
    return columns


def p6_number(text: object) -> float:
    """A P6 number as displayed: thousands separator (1,234.5 or 1.234,5), decimal comma (12,5),
    "%" and "h" suffix, spaces. NaN where blank or unreadable."""
    cleaned = re.sub(r"[\s\u00a0\u202f%]", "", str(text)).removesuffix("h").removesuffix("H")
    if "," in cleaned and "." in cleaned:
        decimal = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        cleaned = cleaned.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", "") if _THOUSANDS_COMMA.fullmatch(cleaned) else cleaned.replace(",", ".")
    try:
        number = float(cleaned)
    except ValueError:
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def p6_export_frame(raw: pd.DataFrame, columns: dict[str, str | None]) -> tuple[pd.DataFrame, dict[str, int]]:
    """The export as ``pv_p6_comparison`` reads it, indexed by Activity ID, and what was set aside:
    ``rows_without_id`` (totals, band rows), ``duplicate_ids`` (the first row is kept) and
    ``unreadable_values`` (cells that are not blank and not a number). ValueError if a required
    column is missing."""
    missing = [field for field, (_names, required) in P6_EXPORT_FIELDS.items() if required and not columns.get(field)]
    if missing:
        raise ValueError(f"Column to choose: {', '.join(missing)}.")
    used = {field: column for field, column in columns.items() if column}
    frame = raw[list(used.values())].set_axis(list(used), axis=1)
    frame = frame.assign(task_code=frame["task_code"].str.strip())
    with_id = frame[frame["task_code"] != ""]
    unique = with_id[~with_id["task_code"].duplicated()]
    unreadable = 0
    for field in P6_NUMBER_FIELDS:
        if field in unique:
            text = unique[field].str.strip()
            number = text.map(p6_number)
            unreadable += int((number.isna() & (text != "")).sum())
            unique = unique.assign(**{field: number})
    for field in ["bl_start", "bl_finish", "start", "finish"]:
        if field in unique:
            unique = unique.assign(**{field: unique[field].str.replace(_P6_DATE_FLAG, "", regex=True)})
    notes = {
        "rows_without_id": len(frame) - len(with_id),
        "duplicate_ids": len(with_id) - len(unique),
        "unreadable_values": unreadable,
    }
    return unique.set_index("task_code"), notes


def pv_p6_frames(comparison: PvComparison) -> dict[str, pd.DataFrame]:
    """Block 10 as the files of the diagnostic zip: counts and hours, no activity code or name."""
    return {
        "10_pv_p6_totals": comparison.totals,
        "10_pv_p6_by_schedule_pct": comparison.cross,
        "10_pv_p6_gap_causes": comparison.causes,
        "10_pv_p6_by_calendar": comparison.by_calendar,
    }


def compare_p6_export(
    snapshot: Snapshot,
    baseline: Baseline,
    raw: pd.DataFrame,
    columns: dict[str, str | None],
    tolerance_hr: float = PV_P6_TOLERANCE_HR,
    p6_total_pv_hr: float | None = None,
) -> tuple[PvComparison, dict[str, int]]:
    p6, notes = p6_export_frame(raw, columns)
    return pv_p6_comparison(snapshot, baseline, p6, tolerance_hr, p6_total_pv_hr), notes
