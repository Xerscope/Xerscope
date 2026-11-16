"""MPXJ as an independent reader: read the same XER with xerscope and with MPXJ, compare field by field.

MPXJ (https://www.mpxj.org) is an independent, widely used Java reader for P6 files.
Agreement between two independent readers is strong evidence both read the file the way
P6 wrote it. Run it on your own weekly exports:

    uv sync --extra crosscheck          # needs a Java runtime (JDK 11+)
    uv run xerscope crosscheck ~/exports/project-x --out crosscheck.csv

Only fields with the *same meaning* in both readers are compared. Deliberately skipped:
- MPXJ "Start"/"Finish" fall back to planned dates when P6's remaining early dates are
  blank, while xerscope prefers early dates; the raw early/late/actual dates are compared
  instead.
- MPXJ "Duration" is the at-completion duration, not P6's Original Duration.
- ``TT_StartMile`` (a non-standard code) is a milestone for xerscope and not for MPXJ.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pandas as pd

from ..config import DATETIME_FMT
from ..xer import build_snapshot, read_xer

_MPXJ_LAG_CALENDAR = {
    "rcal_Predecessor": "PREDECESSOR",
    "rcal_Successor": "SUCCESSOR",
    "rcal_24Hour": "TWENTY_FOUR_HOUR",
    "rcal_ProjDefault": "PROJECT_DEFAULT",
}
_MPXJ_PERCENT_GETTER = {
    "CP_Drtn": "getPercentageComplete",
    "CP_Phys": "getPhysicalPercentComplete",
    "CP_Units": "getPercentageWorkComplete",
}
_MPXJ_DATE_GETTER = {
    "early_start_date": "getEarlyStart",
    "early_end_date": "getEarlyFinish",
    "late_start_date": "getLateStart",
    "late_end_date": "getLateFinish",
    "act_start_date": "getActualStart",
    "act_end_date": "getActualFinish",
}
_STANDARD_TYPES = {"TT_Task", "TT_Rsrc", "TT_LOE", "TT_Mile", "TT_FinMile"}


def start_jvm():
    """MPXJ's XER reader class, the Java virtual machine started if it was not."""
    try:
        import jpype
        import mpxj  # noqa: F401  (registers the MPXJ jars with jpype)
    except ImportError as error:
        raise RuntimeError("crosscheck needs the optional extra: uv sync --extra crosscheck") from error
    if not jpype.isJVMStarted():
        # A newer org.mpxj.cpm build (tests/reference/mpxj_cpm.py) goes first on the classpath,
        # so its scheduler replaces the released one's, whatever was imported before.
        scheduler_jar = os.environ.get("XERSCOPE_MPXJ_CPM_JAR")
        released_jars = [jar for jar in jpype.getClassPath().split(os.pathsep) if jar]
        jpype.startJVM(classpath=([scheduler_jar] if scheduler_jar else []) + released_jars)
    from org.mpxj.primavera import PrimaveraXERFileReader

    return PrimaveraXERFileReader


def read_project(reader_class, path: Path, project_code: str):
    """The project xerscope analyses: files can hold several, MPXJ reads the first by default."""
    mpxj_projects = list(reader_class().readAll(str(path)))
    for mpxj_project in mpxj_projects:
        if str(mpxj_project.getProjectProperties().getProjectID()) == project_code:
            return mpxj_project
    return mpxj_projects[0]


def _date_text(date) -> str | None:
    """A date of either reader as text to the minute, None when blank."""
    if date is None or date is pd.NaT:
        return None
    if isinstance(date, pd.Timestamp):
        return date.strftime(DATETIME_FMT)
    return str(date).replace("T", " ")[:16]


def _rounded(value) -> float | None:
    """A number of either reader to two decimals, None when blank or not a number."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else round(number, 2)


def _duration_hours(duration) -> float | None:
    """MPXJ Duration -> hours, only when MPXJ reports it in hours (no calendar guessing)."""
    if duration is None or str(duration.getUnits()) != "h":
        return None
    return round(float(duration.getDuration()), 2)


def _project_values(snapshot, mpxj_properties) -> list[tuple]:
    """(code, field, xerscope, mpxj) for what the two readers say of the project itself."""
    values = [("PROJECT", "data_date", _date_text(snapshot.data_date), _date_text(mpxj_properties.getStatusDate()))]
    if snapshot.options.get("sched", {}).get("sched_calendar_on_relationship_lag"):
        # only when the file states it: with no option, Oracle says the successor's
        # calendar is used, MPXJ assumes the predecessor's
        lag_calendar = _MPXJ_LAG_CALENDAR[snapshot.options["lag_calendar"]]
        values.append(("PROJECT", "lag_calendar", lag_calendar, str(mpxj_properties.getRelationshipLagCalendar())))
    return values


def _mpxj_tasks_by_code(mpxj_project, task_codes: pd.Index) -> dict:
    """{Activity ID: MPXJ task} for the tasks of MPXJ's project that xerscope reads as activities."""
    mpxj_tasks = {}
    for mpxj_task in mpxj_project.getTasks():
        if mpxj_task.getActivityID() is not None and str(mpxj_task.getActivityID()) in task_codes:
            mpxj_tasks[str(mpxj_task.getActivityID())] = mpxj_task
    return mpxj_tasks


def _predecessors_by_successor(relationships: pd.DataFrame) -> dict[str, list[tuple]]:
    """{successor's Activity ID: [(predecessor's Activity ID, link type, lag in hours)]} as xerscope reads them."""
    predecessors: dict[str, list[tuple]] = {}
    for link in relationships.itertuples():
        predecessors.setdefault(link.succ_code, []).append((link.pred_code, link.type, _rounded(link.lag_hr)))
    return predecessors


def _mpxj_predecessors(mpxj_task) -> list[tuple]:
    """[(predecessor's Activity ID, link type, lag in hours)] as MPXJ reads them; a lag not in hours counts 0."""
    return [
        (str(link.getPredecessorTask().getActivityID()), str(link.getType()), _duration_hours(link.getLag()) or 0.0)
        for link in mpxj_task.getPredecessors()
    ]


def _activity_values(task_code: str, activity: pd.Series, mpxj_task, predecessors: list[tuple]) -> list[tuple]:
    """(code, field, xerscope, mpxj) for each field of one activity that means the same in both readers."""
    values: list[tuple] = [("name", activity["task_name"], str(mpxj_task.getName()))]
    if activity["task_type"] in _STANDARD_TYPES:
        values.append(("milestone", bool(activity["is_milestone"]), bool(mpxj_task.getMilestone())))
    for column, getter in _MPXJ_DATE_GETTER.items():
        values.append((column, _date_text(activity[column]), _date_text(getattr(mpxj_task, getter)())))
    remaining_hr = _rounded(activity["remain_drtn_hr_cnt"])
    values.append(("remaining_hr", remaining_hr, _duration_hours(mpxj_task.getRemainingDuration())))
    total_float_hr = _duration_hours(mpxj_task.getTotalSlack())
    if not activity["is_complete"] and total_float_hr is not None and pd.notna(activity["total_float_hr_cnt"]):
        values.append(("total_float_hr", _rounded(activity["total_float_hr_cnt"]), total_float_hr))
    complete_pct_type = activity["complete_pct_type"]
    mpxj_percent_getter = _MPXJ_PERCENT_GETTER.get(complete_pct_type, "getPhysicalPercentComplete")
    pct_complete_field = f"pct_complete[{complete_pct_type or 'none'}]"
    pct_complete = _rounded(activity["pct_complete"])
    values.append((pct_complete_field, pct_complete, _rounded(getattr(mpxj_task, mpxj_percent_getter)())))
    values.append(("critical", bool(activity["is_critical"]), bool(mpxj_task.getCritical())))
    values.append(("predecessors", sorted(predecessors), sorted(_mpxj_predecessors(mpxj_task))))
    return [(task_code, *field_and_values) for field_and_values in values]


def compare_file(path: str | Path) -> pd.DataFrame:
    """One row per value both readers give for the file: the project's, then each activity's.

    Columns: file, code (Activity ID, or PROJECT), field, xerscope, mpxj, agree.
    """
    reader_class = start_jvm()
    path = Path(path)
    snapshot = build_snapshot(read_xer(path))
    activities = snapshot.activities.set_index("task_code")
    mpxj_project = read_project(reader_class, path, snapshot.project_code)

    values = _project_values(snapshot, mpxj_project.getProjectProperties())
    mpxj_tasks = _mpxj_tasks_by_code(mpxj_project, activities.index)
    values.append(("PROJECT", "activities", len(activities), len(mpxj_tasks)))
    # the links grouped once: looking them up per activity reads the whole table each time
    predecessors = _predecessors_by_successor(snapshot.relationships)
    for task_code, mpxj_task in mpxj_tasks.items():
        values += _activity_values(task_code, activities.loc[task_code], mpxj_task, predecessors.get(task_code, []))
    return pd.DataFrame(
        [
            dict(
                file=path.name,
                code=code,
                field=field,
                xerscope=xerscope_value,
                mpxj=mpxj_value,
                agree=xerscope_value == mpxj_value,
            )
            for code, field, xerscope_value, mpxj_value in values
        ]
    )


def compare_paths(paths) -> pd.DataFrame:
    """The rows of ``compare_file`` for every file, one table; empty when there is no file."""
    tables = [compare_file(path) for path in paths]
    return pd.concat(tables, ignore_index=True) if tables else pd.DataFrame()
