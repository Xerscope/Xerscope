"""Build tiny XER files in tests, so every expected number can be checked by hand."""

from __future__ import annotations

from xerscope.xer import Snapshot, build_snapshot, parse_text

DD = "2026-03-02 08:00"  # Monday
MON_FRI_8H = (
    "(0||CalendarData()((0||DaysOfWeek()((0||1()())"
    + "".join(f"(0||{d}()((0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())))" for d in range(2, 7))
    + "(0||7()())))(0||Exceptions()((0||0(d|46115)())))))"
)  # 46115 = Fri 2026-04-03

TASK_DEFAULTS = {
    "proj_id": "1",
    "task_type": "TT_Task",
    "status_code": "TK_NotStart",
    "clndr_id": "C8",
    "target_drtn_hr_cnt": "80",
    "remain_drtn_hr_cnt": "80",
    "total_float_hr_cnt": "0",
    "early_start_date": "2026-03-02 08:00",
    "early_end_date": "2026-03-13 17:00",
    "target_start_date": "",
    "target_end_date": "",
    "act_start_date": "",
    "act_end_date": "",
    "cstr_type": "",
    "cstr_date": "",
    "cstr_type2": "",
    "driving_path_flag": "N",
    "complete_pct_type": "CP_Drtn",
    "phys_complete_pct": "0",
    "wbs_id": "",
    "target_work_qty": "",
    "act_work_qty": "",
    "remain_work_qty": "",
}


def _table(name: str, rows: list[dict]) -> list[str]:
    cols = list(dict.fromkeys(k for r in rows for k in r))
    return [f"%T\t{name}", "%F\t" + "\t".join(cols)] + [
        "%R\t" + "\t".join(str(r.get(c, "")) for c in cols) for r in rows
    ]


def xer_text(
    tasks: list[dict],
    preds=(),
    *,
    data_date: str = DD,
    rsrc=(),
    costs=(),
    project: dict | None = None,
    wbs=(),
    sched: dict | None = None,
    assign=(),
    resources=(),
) -> str:
    """tasks: dicts with at least task_code; preds: (pred, succ, type, lag_hours[, pred_proj]).

    ``rsrc``: activity codes given one plain labour assignment each. ``assign``: full
    TASKRSRC rows (``task_code`` instead of task_id); ``resources``: RSRC rows.
    """
    ids = {}
    task_rows = []
    for i, t in enumerate(tasks, start=1):
        row = {"task_id": str(i), **TASK_DEFAULTS, "task_name": t["task_code"], **t}
        ids[row["task_code"]] = row["task_id"]
        task_rows.append(row)
    proj = {
        "proj_id": "1",
        "proj_short_name": "T",
        "last_recalc_date": data_date,
        "plan_start_date": data_date,
        "clndr_id": "C8",
        **(project or {}),
    }
    lines = ["ERMHDR\t23.12\t2026-03-02"]
    lines += _table(
        "CALENDAR",
        [
            {
                "clndr_id": "C8",
                "clndr_name": "Mon-Fri 8h",
                "day_hr_cnt": "8",
                "week_hr_cnt": "40",
                "clndr_data": MON_FRI_8H,
            },
            {"clndr_id": "C10", "clndr_name": "Mon-Fri 10h", "day_hr_cnt": "10", "week_hr_cnt": "50", "clndr_data": ""},
            {"clndr_id": "C7D", "clndr_name": "7 days 8h", "day_hr_cnt": "8", "week_hr_cnt": "56", "clndr_data": ""},
        ],
    )
    lines += _table("PROJECT", [proj])
    if sched:
        lines += _table("SCHEDOPTIONS", [{"schedoptions_id": "1", "proj_id": "1", **sched}])
    if wbs:
        lines += _table("PROJWBS", list(wbs))
    lines += _table("TASK", task_rows)
    if preds:
        rows = []
        for k, p in enumerate(preds, start=1):
            pred, succ, typ, lag = p[:4]
            pred_proj = p[4] if len(p) > 4 else "1"
            rows.append(
                {
                    "task_pred_id": str(k),
                    "task_id": ids[succ],
                    "pred_task_id": ids.get(pred, pred),
                    "proj_id": "1",
                    "pred_proj_id": pred_proj,
                    "pred_type": f"PR_{typ}",
                    "lag_hr_cnt": str(lag),
                }
            )
        lines += _table("TASKPRED", rows)
    if resources:
        lines += _table("RSRC", list(resources))
    if rsrc or assign:
        rows = [
            {"taskrsrc_id": str(k), "task_id": ids[c], "proj_id": "1", "rsrc_id": "R1", "target_qty": "80"}
            for k, c in enumerate(rsrc, start=1)
        ]
        rows += [
            {
                "taskrsrc_id": str(100 + k),
                "proj_id": "1",
                "task_id": ids[a["task_code"]],
                **{key: v for key, v in a.items() if key != "task_code"},
            }
            for k, a in enumerate(assign, start=1)
        ]
        lines += _table("TASKRSRC", rows)
    if costs:
        lines += _table(
            "PROJCOST",
            [{"cost_item_id": str(k), "task_id": ids[c], "proj_id": "1"} for k, c in enumerate(costs, start=1)],
        )
    return "\n".join(lines) + "\n"


def snap(tasks, preds=(), **kw) -> Snapshot:
    return build_snapshot(parse_text(xer_text(tasks, preds, **kw), source="test.xer"))


def done(code: str, **kw) -> dict:
    return {
        "task_code": code,
        "status_code": "TK_Complete",
        "remain_drtn_hr_cnt": "0",
        "total_float_hr_cnt": "",
        "act_start_date": "2026-02-02 08:00",
        "act_end_date": "2026-02-13 17:00",
        **kw,
    }


def active(code: str, **kw) -> dict:
    return {
        "task_code": code,
        "status_code": "TK_Active",
        "remain_drtn_hr_cnt": "40",
        "act_start_date": "2026-02-23 08:00",
        **kw,
    }


def todo(code: str, **kw) -> dict:
    return {"task_code": code, **kw}
