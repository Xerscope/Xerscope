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

from ..xer import build_snapshot, read_xer

_LAG = {
    "rcal_Predecessor": "PREDECESSOR",
    "rcal_Successor": "SUCCESSOR",
    "rcal_24Hour": "TWENTY_FOUR_HOUR",
    "rcal_ProjDefault": "PROJECT_DEFAULT",
}
_PCT = {
    "CP_Drtn": "getPercentageComplete",
    "CP_Phys": "getPhysicalPercentComplete",
    "CP_Units": "getPercentageWorkComplete",
}
_STANDARD_TYPES = {"TT_Task", "TT_Rsrc", "TT_LOE", "TT_Mile", "TT_FinMile"}


def _start_jvm():
    try:
        import jpype
    except ImportError as exc:
        raise RuntimeError("crosscheck needs the optional extra: uv sync --extra crosscheck") from exc
    try:
        import mpxj  # noqa: F401  (registers the MPXJ jars with jpype)
    except ImportError as exc:
        raise RuntimeError("crosscheck needs the optional extra: uv sync --extra crosscheck") from exc
    if not jpype.isJVMStarted():
        # A newer org.mpxj.cpm build (tests/reference/mpxj_cpm.py) goes first on the classpath,
        # so its scheduler replaces the released one's, whatever was imported before.
        extra = os.environ.get("XERSCOPE_MPXJ_CPM_JAR")
        jars = [p for p in jpype.getClassPath().split(os.pathsep) if p]
        jpype.startJVM(classpath=([extra] if extra else []) + jars)
    from org.mpxj.primavera import PrimaveraXERFileReader

    return PrimaveraXERFileReader


def _read_project(reader_cls, path: Path, project_code: str):
    """The project xerscope analyses: files can hold several, MPXJ reads the first by default."""
    projects = list(reader_cls().readAll(str(path)))
    for proj in projects:
        if str(proj.getProjectProperties().getProjectID()) == project_code:
            return proj
    return projects[0]


def _ts(v) -> str | None:
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d %H:%M")
    return str(v).replace("T", " ")[:16]


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else round(f, 2)


def _hours(duration) -> float | None:
    """MPXJ Duration -> hours, only when MPXJ reports it in hours (no calendar guessing)."""
    if duration is None or str(duration.getUnits()) != "h":
        return None
    return round(float(duration.getDuration()), 2)


def compare_file(path: str | Path) -> pd.DataFrame:
    reader = _start_jvm()
    path = Path(path)
    snap = build_snapshot(read_xer(path))
    ours = snap.activities.set_index("task_code")
    proj = _read_project(reader, path, snap.project_code)
    rows: list[dict] = []

    def add(code, field, a, b):
        rows.append(dict(file=path.name, code=code, field=field, xerscope=a, mpxj=b, agree=a == b))

    props = proj.getProjectProperties()
    add("PROJECT", "data_date", _ts(snap.data_date), _ts(props.getStatusDate()))
    if snap.options.get("sched", {}).get("sched_calendar_on_relationship_lag"):
        # only when the file states it: with no option, Oracle says the successor's
        # calendar is used, MPXJ assumes the predecessor's
        add("PROJECT", "lag_calendar", _LAG[snap.options["lag_calendar"]], str(props.getRelationshipLagCalendar()))

    theirs = {
        str(t.getActivityID()): t
        for t in proj.getTasks()
        if t.getActivityID() is not None and str(t.getActivityID()) in ours.index
    }
    add("PROJECT", "activities", len(ours), len(theirs))

    for code, t in theirs.items():
        o = ours.loc[code]
        add(code, "name", o["task_name"], str(t.getName()))
        if o["task_type"] in _STANDARD_TYPES:
            add(code, "milestone", bool(o["is_milestone"]), bool(t.getMilestone()))
        for col, getter in [
            ("early_start_date", "getEarlyStart"),
            ("early_end_date", "getEarlyFinish"),
            ("late_start_date", "getLateStart"),
            ("late_end_date", "getLateFinish"),
            ("act_start_date", "getActualStart"),
            ("act_end_date", "getActualFinish"),
        ]:
            add(code, col, _ts(o[col]), _ts(getattr(t, getter)()))
        add(code, "remaining_hr", _num(o["remain_drtn_hr_cnt"]), _hours(t.getRemainingDuration()))
        tf = _hours(t.getTotalSlack())
        if not o["is_complete"] and tf is not None and pd.notna(o["total_float_hr_cnt"]):
            add(code, "total_float_hr", _num(o["total_float_hr_cnt"]), tf)
        getter = _PCT.get(o["complete_pct_type"], "getPhysicalPercentComplete")
        add(
            code,
            f"pct_complete[{o['complete_pct_type'] or 'none'}]",
            _num(o["pct_complete"]),
            _num(getattr(t, getter)()),
        )
        add(code, "critical", bool(o["is_critical"]), bool(t.getCritical()))
        rel = snap.relationships[snap.relationships["succ_code"] == code]
        mine = sorted((r.pred_code, r.type, _num(r.lag_hr)) for r in rel.itertuples())
        ref = sorted(
            (str(r.getPredecessorTask().getActivityID()), str(r.getType()), _hours(r.getLag()) or 0.0)
            for r in t.getPredecessors()
        )
        add(code, "predecessors", mine, ref)
    return pd.DataFrame(rows)


def compare_paths(paths) -> pd.DataFrame:
    frames = [compare_file(p) for p in paths]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
