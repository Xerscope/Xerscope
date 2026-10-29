"""P6 itself: the held-out corpus of cpp-cpm-engine, scored against the engine."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .mpxj_cpm import _same

# dependent work; the corpus records what P6 held after import (p6-imported/*.json) and
# ``p6_heldout_score`` lays it over the case before scheduling, as the corpus' own scorer does.

P6_FIELDS = {
    "early_start": "early_start",
    "early_finish": "early_finish",
    "late_start": "late_start",
    "late_finish": "late_finish",
    "total_float_hr": "total_float_hr",
    "free_float_hr": "free_float_hr",
}


def _overlay(raw, path: Path) -> list[str]:
    """Apply P6's post-import sizing (p6-imported/<case>.json) to the raw tables. Returns
    the task codes P6 re-sized (their dates are compared on P6's input, not the file's)."""
    import json

    if not path.exists():
        return []
    d = json.loads(path.read_text(encoding="utf-8"))
    rd = d.get("resource_dependent", {})
    task = raw.tables.get("TASK")
    touched: list[str] = []
    for code, vals in rd.get("tasks", {}).items():
        m = task["task_code"] == code
        for k, v in vals.items():
            if k in task.columns:
                task.loc[m, k] = "" if v is None else str(v)
        touched.append(code)
    asg = raw.tables.get("TASKRSRC")
    rsrc = raw.tables.get("RSRC")
    if asg is not None and rsrc is not None and rd.get("assignments"):
        code_of = task.set_index("task_id")["task_code"]
        name_of = rsrc.set_index("rsrc_id")["rsrc_short_name"]
        for a in rd["assignments"]:
            m = (asg["task_id"].map(code_of) == a["task_code"]) & (asg["rsrc_id"].map(name_of) == a["rsrc_short_name"])
            for k, v in a.items():
                if k in asg.columns and k not in ("task_code", "rsrc_short_name"):
                    asg.loc[m, k] = "" if v is None else str(v)
            touched.append(a["task_code"])
    return sorted(set(touched))


def p6_heldout_score(set_dir: str | Path, overlay: bool = True) -> pd.DataFrame:
    """One row per (case, unfinished activity, field): P6's value, xerscope's, ``agree``.

    ``early_start`` of work under way is P6's remaining early start (xerscope's
    ``remaining_start``). Dates agree on the same clock time, floats within 0.01 h.
    ``resource_dependent`` marks activities P6's import re-sized.
    """
    from ..analysis.cpm import CycleError, schedule
    from ..xer import build_snapshot, read_xer

    set_dir = Path(set_dir)
    res = pd.read_csv(set_dir / "p6-results.csv")
    for c in ("early_start", "early_finish", "late_start", "late_finish"):
        res[c] = pd.to_datetime(res[c])
    rows = []
    for case, g in res.groupby("case", sort=True):
        path = set_dir / "cases" / f"{case}.xer"
        if not path.exists():
            continue
        raw = read_xer(path)
        resized = _overlay(raw, set_dir / "p6-imported" / f"{case}.json") if overlay else []
        snap = build_snapshot(raw)
        o = snap.options.get("sched", {}) or {}
        opts = (
            f"{snap.options['progressed']} {o.get('sched_float_type') or 'FT_FF'} {snap.options['lag_calendar']} "
            f"{'ssES' if o.get('sched_lag_early_start_flag', 'Y') != 'N' else 'ssAS'} "
            f"{'expfin' if o.get('sched_use_expect_end_flag', 'Y') != 'N' else 'noexp'}"
            f"{' openCrit' if o.get('sched_open_critical_flag') == 'Y' else ''}"
        )
        try:
            f = schedule(snap).frame
        except (CycleError, ValueError) as exc:
            rows.append(
                dict(
                    set=set_dir.name,
                    case=case,
                    task_code="*",
                    status="",
                    field="error",
                    p6=None,
                    xerscope=str(exc),
                    agree=False,
                    resource_dependent=False,
                    options=opts,
                )
            )
            continue
        t = snap.activities.drop_duplicates("task_code").set_index("task_code")
        for r in g.itertuples(index=False):
            if r.task_code not in f.index:
                continue
            x = f.loc[r.task_code]
            mine = {
                "early_start": x["remaining_start"] if r.status == "TK_Active" else x["es"],
                "early_finish": x["ef"],
                "late_start": x["ls"],
                "late_finish": x["lf"],
                "total_float_hr": x["tf_hr"],
                "free_float_hr": x["ff_hr"],
            }
            for field, v in mine.items():
                p6 = getattr(r, field)
                agree = _same(v, p6)
                rows.append(
                    dict(
                        set=set_dir.name, case=case, task_code=r.task_code, status=r.status[3:], field=field,
                        p6=p6, xerscope=v, agree=agree,
                        resource_dependent=r.task_code in resized or t.at[r.task_code, "task_type"] == "TT_Rsrc",
                        options=opts,
                    )
                )  # fmt: skip
    return pd.DataFrame(
        rows,
        columns=[
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
        ],
    )
