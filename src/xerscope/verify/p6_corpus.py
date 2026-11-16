"""P6 itself: the held-out corpus of cpp-cpm-engine, scored against the engine.

30 sets of 12 synthetic schedules, each frozen before P6 saw it, imported into P6
Professional 23.12.1 and scheduled with F9, with P6's early/late dates and floats read
back from its database (tests/reference/fetch_p6_heldout.py; the protocol is in the
corpus). That is P6 output on progressed, constrained, multi-calendar and (from H8)
resource-dependent work, which no public export covers. P6's import re-sizes
resource-dependent work: the corpus records what P6 held after import
(p6-imported/*.json) and ``p6_heldout_score`` lays it over the case before scheduling,
as the corpus' own scorer does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .mpxj_cpm import same_value

# The corpus' name for each of verify.mpxj_cpm's CPM_FIELDS.
P6_FIELD = {
    "es": "early_start",
    "ef": "early_finish",
    "ls": "late_start",
    "lf": "late_finish",
    "tf_hr": "total_float_hr",
    "ff_hr": "free_float_hr",
}


SCORE_COLUMNS = [
    "set",
    "case",
    "task_code",
    "status",
    "field",
    "p6",
    "xerscope",
    "agree",
    "resource_dependent",
    "options",
]


def _apply_p6_import(raw, path: Path) -> list[str]:
    """Apply P6's post-import sizing (p6-imported/<case>.json) to the raw tables. Returns
    the task codes P6 re-sized (their dates are compared on P6's input, not the file's)."""
    if not path.exists():
        return []
    resource_dependent = json.loads(path.read_text(encoding="utf-8")).get("resource_dependent", {})
    tasks = raw.tables.get("TASK")
    resized: list[str] = []
    for task_code, columns in resource_dependent.get("tasks", {}).items():
        _write_as_xer_text(tasks, tasks["task_code"] == task_code, columns)
        resized.append(task_code)
    assignments = raw.tables.get("TASKRSRC")
    resources = raw.tables.get("RSRC")
    if assignments is not None and resources is not None and resource_dependent.get("assignments"):
        # the corpus names an assignment by activity code and resource short name, the XER by ids
        task_code_of_assignment = assignments["task_id"].map(tasks.set_index("task_id")["task_code"])
        resource_name_of_assignment = assignments["rsrc_id"].map(resources.set_index("rsrc_id")["rsrc_short_name"])
        for assignment in resource_dependent["assignments"]:
            is_this_assignment = (task_code_of_assignment == assignment["task_code"]) & (
                resource_name_of_assignment == assignment["rsrc_short_name"]
            )
            columns = {
                name: value for name, value in assignment.items() if name not in ("task_code", "rsrc_short_name")
            }
            _write_as_xer_text(assignments, is_this_assignment, columns)
            resized.append(assignment["task_code"])
    return sorted(set(resized))


def _write_as_xer_text(table: pd.DataFrame, rows: pd.Series, columns: dict[str, Any]) -> None:
    """Write P6's values into the chosen rows of a raw table, as the XER holds them: text, and
    nothing for a value P6 left empty. A column the table does not have is skipped."""
    for name, value in columns.items():
        if name in table.columns:
            table.loc[rows, name] = "" if value is None else str(value)


def p6_heldout_score(set_dir: str | Path, overlay: bool = True) -> pd.DataFrame:
    """One row per (case, unfinished activity, field): P6's value, xerscope's, ``agree``.

    ``early_start`` of work under way is P6's remaining early start (xerscope's
    ``remaining_start``). Dates agree on the same clock time, floats within 0.01 h.
    ``resource_dependent`` marks activities P6's import re-sized.
    """
    set_dir = Path(set_dir)
    p6_results = pd.read_csv(set_dir / "p6-results.csv")
    for date_column in ("early_start", "early_finish", "late_start", "late_finish"):
        p6_results[date_column] = pd.to_datetime(p6_results[date_column])
    rows: list[dict[str, Any]] = []
    for case, p6_activities in p6_results.groupby("case", sort=True):
        if (set_dir / "cases" / f"{case}.xer").exists():
            rows += _case_rows(set_dir, case, p6_activities, overlay)
    return pd.DataFrame(rows, columns=SCORE_COLUMNS)


def _case_rows(set_dir: Path, case: str, p6_activities: pd.DataFrame, overlay: bool) -> list[dict[str, Any]]:
    """One case scheduled by xerscope and compared with what P6 gave for it; a single "error"
    row when the case cannot be scheduled."""
    from ..analysis.cpm import CycleError, schedule
    from ..xer import build_snapshot, read_xer

    raw = read_xer(set_dir / "cases" / f"{case}.xer")
    resized = _apply_p6_import(raw, set_dir / "p6-imported" / f"{case}.json") if overlay else []
    snapshot = build_snapshot(raw)
    case_columns = {"set": set_dir.name, "case": case, "options": _scheduling_options_label(snapshot)}
    try:
        computed = schedule(snapshot).frame
    except (CycleError, ValueError) as error:
        cannot_schedule = dict(
            task_code="*", status="", field="error", p6=None, xerscope=str(error), agree=False, resource_dependent=False
        )
        return [case_columns | cannot_schedule]
    resource_dependent = set(resized) | set(snapshot.by_code.index[snapshot.by_code["task_type"] == "TT_Rsrc"])
    rows = []
    for p6_activity in p6_activities.itertuples(index=False):
        if p6_activity.task_code not in computed.index:
            continue
        activity_columns = dict(
            task_code=p6_activity.task_code,
            status=p6_activity.status[3:],
            resource_dependent=p6_activity.task_code in resource_dependent,
        )
        for field_columns in _compared_fields(p6_activity, computed.loc[p6_activity.task_code]):
            rows.append(case_columns | activity_columns | field_columns)
    return rows


def _scheduling_options_label(snapshot) -> str:
    """Name the scheduling options of a case in a few words, to group differences by option,
    as in ``retained_logic FT_FF predecessor ssES expfin openCrit``."""
    sched_options = snapshot.options.get("sched", {}) or {}
    return (
        f"{snapshot.options['progressed']} {sched_options.get('sched_float_type') or 'FT_FF'} "
        f"{snapshot.options['lag_calendar']} "
        f"{'ssES' if sched_options.get('sched_lag_early_start_flag', 'Y') != 'N' else 'ssAS'} "
        f"{'expfin' if sched_options.get('sched_use_expect_end_flag', 'Y') != 'N' else 'noexp'}"
        f"{' openCrit' if sched_options.get('sched_open_critical_flag') == 'Y' else ''}"
    )


def _compared_fields(p6_activity, computed_activity: pd.Series) -> list[dict[str, Any]]:
    """P6's value and xerscope's for each CPM field of one activity."""
    compared = []
    for cpm_field, p6_field in P6_FIELD.items():
        # work under way: P6's early start is the remaining early start
        is_remaining_start = cpm_field == "es" and p6_activity.status == "TK_Active"
        xerscope_value = computed_activity["remaining_start" if is_remaining_start else cpm_field]
        p6_value = getattr(p6_activity, p6_field)
        compared.append(
            dict(field=p6_field, p6=p6_value, xerscope=xerscope_value, agree=same_value(xerscope_value, p6_value))
        )
    return compared
