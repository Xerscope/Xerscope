"""The tables of the Debug page: what xerscope read from the file and what it decided.

Reads only: ``Snapshot``, ``analysis.cpm.Options`` and ``schedule``, the integrity comparisons,
the P6 standard. Nothing here computes a date or a count; the page shows these frames and
``Anonymizer.zip_frames`` hands them out.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from xerscope.analysis.baseline import Baseline
from xerscope.analysis.cpm import ASSIGNMENT_FIELDS, FIELDS, Options, compare_assignments, compare_with_stored, schedule
from xerscope.analysis.evm import etc_settings, etc_technique_counts, pv_labor_check
from xerscope.analysis.rules import RULES
from xerscope.analysis.standards import Standard
from xerscope.config import DEFAULT_SETTINGS
from xerscope.xer.model import Snapshot, leveled, to_number

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
    table = snapshot.file_projects.copy()
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
                "matched": int(codes.isin(baseline.frame.index).sum()),
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
        return (
            pd.to_datetime(frame[column], errors="coerce") if column in frame else pd.Series(pd.NaT, index=frame.index)
        )

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


def diagnostic_frames(
    snapshot: Snapshot, baseline: Baseline | None, standard: Standard, anonymous: bool = False
) -> dict[str, pd.DataFrame]:
    """The nine blocks, named as the files of the diagnostic zip. ``anonymous``: no file name in them."""
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
    }
