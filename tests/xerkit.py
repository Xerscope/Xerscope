"""Build tiny XER files in tests, so every expected number can be checked by hand."""

from __future__ import annotations

from xerscope.xer import Snapshot, build_snapshot, parse_text

DD = "2026-03-02 08:00"  # Monday


def clndr_data(days: range, periods: list[tuple[str, str]], holidays: tuple[int, ...] = ()) -> str:
    """A P6 CALENDAR.clndr_data blob: working ``periods`` on ``days`` (1 = Sunday .. 7 = Saturday)."""
    work = "".join(f"(0||{i}(s|{a}|f|{b})())" for i, (a, b) in enumerate(periods))
    week = "".join(f"(0||{d}()({work if d in days else ''}))" for d in range(1, 8))
    exc = "".join(f"(0||{i}(d|{h})())" for i, h in enumerate(holidays))
    return f"(0||CalendarData()((0||DaysOfWeek()({week}))(0||Exceptions()({exc}))))"


# Written out in full, so any reader (xerscope, MPXJ, P6) sees the same working time.
MON_FRI_8H = clndr_data(range(2, 7), [("08:00", "12:00"), ("13:00", "17:00")], (46115,))  # 46115 = Fri 2026-04-03
MON_FRI_10H = clndr_data(range(2, 7), [("08:00", "18:00")])
SEVEN_DAYS_8H = clndr_data(range(1, 8), [("08:00", "16:00")])

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


# Tests name calendars and resources (C8, C7D, R1...); the file carries numeric ids, as P6
# writes them (MPXJ, like P6's own import, reads these keys as integers).
CALENDAR_IDS = {"C8": "8", "C10": "10", "C7D": "7"}


def _key(col: str, v: object) -> object:
    if col == "clndr_id" and v in CALENDAR_IDS:
        return CALENDAR_IDS[v]
    if col == "rsrc_id" and isinstance(v, str) and v[:1] == "R" and v[1:].isdigit():
        return str(900 + int(v[1:]))
    return v


def _table(name: str, rows: list[dict]) -> list[str]:
    cols = list(dict.fromkeys(k for r in rows for k in r))
    return [f"%T\t{name}", "%F\t" + "\t".join(cols)] + [
        "%R\t" + "\t".join(str(_key(c, r.get(c, ""))) for c in cols) for r in rows
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
            {
                "clndr_id": "C10",
                "clndr_name": "Mon-Fri 10h",
                "day_hr_cnt": "10",
                "week_hr_cnt": "50",
                "clndr_data": MON_FRI_10H,
            },
            {
                "clndr_id": "C7D",
                "clndr_name": "7 days 8h",
                "day_hr_cnt": "8",
                "week_hr_cnt": "56",
                "clndr_data": SEVEN_DAYS_8H,
            },
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
