"""The tables of the Debug page: what xerscope read from the file and what it decided.

Reads only: ``Snapshot``, ``analysis.cpm.Options`` and ``schedule``, the integrity comparisons,
the P6 standard. Nothing here computes a date or a count; the page shows these frames and
``Anonymizer.zip_frames`` hands them out.
"""

from __future__ import annotations

import pandas as pd

from xerscope.analysis.baseline import Baseline
from xerscope.analysis.cpm import ASSIGNMENT_FIELDS, FIELDS, Options, compare_assignments, compare_with_stored, schedule
from xerscope.analysis.populations import LARGE_HOURS
from xerscope.analysis.standards import Standard
from xerscope.config import DEFAULT_SETTINGS
from xerscope.xer.model import Snapshot, leveled

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
    ("Dangling Start", "Ignore in-progress activities", "applied (started activities excluded)"),
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
    "P6-10": DATES,
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
            "x_hours": LARGE_HOURS if metric.id in ("P6-04", "P6-05", "P6-06") else None,
        }
        for metric in standard.metrics
    ]
    rows += [
        {"tab": RELATIONSHIPS, "check": f"{check} · {option}", "target": reading, "x_hours": None}
        for check, option, reading in P6_DIALOG_OPTIONS
    ]
    return pd.DataFrame(rows)


def baseline_table(snapshot: Snapshot, baseline: Baseline | None) -> pd.DataFrame:
    """The baseline in use: label, kind, activities of the update it covers."""
    if baseline is None:
        return pd.DataFrame([{"baseline": "none", "kind": "", "matched": 0, "activities": len(snapshot.by_code)}])
    codes = snapshot.by_code.index
    return pd.DataFrame(
        [
            {
                "baseline": baseline.label,
                "kind": "planned dates (target_*)" if baseline.snapshot is snapshot else "separate file",
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


def diagnostic_frames(snapshot: Snapshot, baseline: Baseline | None, standard: Standard) -> dict[str, pd.DataFrame]:
    """The six blocks, named as the files of the diagnostic zip."""
    project_finish, latest_finishes = finish_table(snapshot)
    return {
        "01_options": options_table(snapshot),
        "02_expected_finish": expected_finish_table(snapshot),
        "03_int01_recalculation": recalculation_table(snapshot),
        "03_int03_assignments": assignments_table(snapshot),
        "04_check_parameters": check_parameters(standard),
        "05_baseline": baseline_table(snapshot, baseline),
        "05_calendars": calendars_table(snapshot),
        "06_leveling": leveling_table(snapshot),
        "06_project_finish": project_finish,
        "06_latest_finishes": latest_finishes,
    }
