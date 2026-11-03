import contextlib

import pandas as pd
import pytest
from xerkit import active, snap, todo, xer_text

from xerscope.xer import XerError, build_snapshot, parse_text


def test_snapshot_identity(store):
    s = store.first
    assert s.project_code == "PRJ-ALPHA"
    assert s.project_name == "Usine de traitement – Phase 1"  # from the PROJWBS project node
    assert s.data_date == pd.Timestamp("2026-08-31 08:00")
    assert s.finish_date is not None


def test_types_and_units(store):
    t = store.first.tasks
    assert pd.api.types.is_datetime64_any_dtype(t["early_start_date"])
    fab = t.set_index("task_code").loc["P2030"]
    assert fab["original_d"] == 60  # 480 h / 8 h per day
    assert fab["type"] == "Task dependent"


def test_wbs_path(store):
    t = store.first.tasks.set_index("task_code")
    assert t.loc["E1010", "wbs_code"] == "ENG"
    assert t.loc["E1010", "wbs_l1"] == "ENG · Ingénierie"
    # siblings follow P6 seq_num (ENG before PRC before CIV), not the alphabet
    assert t.loc["E1010", "wbs_sort"] < t.loc["P2010", "wbs_sort"] < t.loc["C3010", "wbs_sort"]


def test_relationships_use_codes_and_days(store):
    r = store.first.relationships
    lead = r[(r["pred_code"] == "E1040") & (r["succ_code"] == "E1050")].iloc[0]
    assert lead["type"] == "FS"
    assert lead["lag_d"] == -3


def test_hard_constraint_flag(store):
    t = store.first.tasks.set_index("task_code")
    assert t.loc["X4050", "has_hard_constraint"]  # CS_MEOB = finish on or before
    assert not t.loc["P2040", "has_hard_constraint"]  # CS_MSOA = soft


def test_completed_tasks_have_no_float(store):
    t = store.latest.activities
    assert t.loc[t["is_complete"], "total_float_d"].isna().all()


def test_blank_data_date_falls_back_to_planned_start():
    xer = (
        "ERMHDR\t23.12\t2026-10-20\n"
        "%T\tPROJECT\n%F\tproj_id\tproj_short_name\tlast_recalc_date\tplan_start_date\n"
        "%R\t1\tP\t\t2026-09-01 08:00\n"
        "%T\tTASK\n%F\ttask_id\tproj_id\ttask_code\ttask_name\ttask_type\tstatus_code\n"
        "%R\t1\t1\tA\tA\tTT_Task\tTK_NotStart\n"
    )
    s = build_snapshot(parse_text(xer))
    assert s.data_date == pd.Timestamp("2026-09-01 08:00")
    assert s.data_date_source == "plan_start_date"


def _xer(project_extra: dict, sched: dict | None = None, tasks=None, preds=None):
    """Minimal XER text (see xerkit.xer_text); ``project_extra`` overrides PROJECT columns."""
    return xer_text(tasks or [], preds or (), project=project_extra, sched=sched)


TASKS = [  # A is critical by float and on the driving path, B is 40 h and C 48 h from critical
    {"task_code": "A", "clndr_id": "C8", "total_float_hr_cnt": "0", "driving_path_flag": "Y"},
    {"task_code": "B", "clndr_id": "C10", "total_float_hr_cnt": "40", "driving_path_flag": "N"},
    {"task_code": "C", "clndr_id": "C8", "total_float_hr_cnt": "48", "driving_path_flag": "Y"},
]


def test_critical_uses_project_float_threshold_in_hours():
    s = build_snapshot(
        parse_text(_xer({"critical_path_type": "CT_TotFloat", "critical_drtn_hr_cnt": "40"}, tasks=TASKS))
    )
    crit = s.activities.set_index("task_code")["is_critical"].to_dict()
    assert crit == {"A": True, "B": True, "C": False}  # 0 h, 40 h <= 40 h; 48 h > 40 h


def test_critical_can_be_longest_path():
    s = build_snapshot(
        parse_text(_xer({"critical_path_type": "CT_DrivPath", "critical_drtn_hr_cnt": "0"}, tasks=TASKS))
    )
    crit = s.activities.set_index("task_code")["is_critical"].to_dict()
    assert crit == {"A": True, "B": False, "C": True}  # driving_path_flag, not float


def test_critical_defaults_to_zero_float_when_project_is_silent():
    s = build_snapshot(parse_text(_xer({}, tasks=TASKS)))
    assert s.activities.set_index("task_code")["is_critical"].to_dict() == {"A": True, "B": False, "C": False}


@pytest.mark.parametrize("setting", ["rcal_Predecessor", "rcal_Successor", "rcal_24Hour", "rcal_ProjDefault"])
def test_lag_days_use_the_predecessor_calendar_whatever_the_lag_calendar(setting):
    """Oracle (Schedule Options): "Lag entered in a unit other than hours is converted to
    hours based on the predecessor activity's calendar." The lag calendar option only
    decides where the CPM counts the lag (analysis/cpm.py)."""
    lag_days = 30 / 8  # pred A on C8
    xer = _xer(
        {},
        {"sched_calendar_on_relationship_lag": setting},
        tasks=TASKS,
        preds=[("A", "B", "FS", 30)],
    )
    s = build_snapshot(parse_text(xer))
    assert s.options["lag_calendar"] == setting
    assert s.relationships.loc[0, "lag_d"] == pytest.approx(lag_days)


def test_start_finish_follow_p6_columns_after_leveling():
    """Oracle: Start = actual start, else the remaining early start once scheduled; leveling
    moves the remaining early dates away from the early dates."""
    s = snap(
        [
            todo(
                "A",
                early_start_date="2026-03-02 08:00",
                early_end_date="2026-03-13 17:00",
                restart_date="2026-03-09 08:00",
                reend_date="2026-03-20 17:00",
            ),
            active(
                "B", early_start_date="2026-03-02 08:00", restart_date="2026-03-02 08:00", reend_date="2026-03-06 17:00"
            ),
        ]
    )
    a = s.activities.set_index("task_code")
    assert a.at["A", "start"] == pd.Timestamp("2026-03-09 08:00")
    assert a.at["A", "finish"] == pd.Timestamp("2026-03-20 17:00")
    assert a.at["B", "start"] == pd.Timestamp("2026-02-23 08:00")  # actual start
    assert a.at["B", "finish"] == pd.Timestamp("2026-03-06 17:00")


def test_parser_reports_rows_longer_than_their_header():
    raw = parse_text("ERMHDR\t23.12\n%T\tX\n%F\ta\tb\n%R\t1\t2\textra\n%R\t3\n", source="t.xer")
    assert raw.tables["X"].values.tolist() == [["1", "2"], ["3", ""]]
    assert any("more fields" in w for w in raw.warnings)


# --- minimal XERs: columns missing from a table ------------------------------------


def drop_column(text: str, table: str, column: str) -> str:
    """Remove one column from one table of an XER text (its %F field and every %R value)."""
    out, in_table, idx = [], False, -1
    for line in text.split("\n"):
        parts = line.split("\t")
        if parts[0] == "%T":
            in_table = parts[1] == table
        elif in_table and parts[0] == "%F":
            idx = parts.index(column) if column in parts else -1
            if idx >= 0:
                del parts[idx]
        elif in_table and parts[0] == "%R" and idx >= 0:
            del parts[idx]
        out.append("\t".join(parts))
    return "\n".join(out)


def _linked_text() -> str:
    return xer_text([active("A"), active("B"), active("C")], [("A", "B", "FS", 8), ("B", "C", "SS", 16)])


def _rels(s):
    return s.relationships[["pred_code", "succ_code", "type", "lag_hr", "is_external"]].values.tolist()


@pytest.mark.parametrize("column", ["proj_id", "pred_proj_id"])
def test_taskpred_without_project_column_is_derived(column):
    full = build_snapshot(parse_text(_linked_text(), source="t.xer"))
    s = build_snapshot(parse_text(drop_column(_linked_text(), "TASKPRED", column), source="t.xer"))
    assert _rels(s) == _rels(full) and len(s.relationships) == 2
    assert any(f"TASKPRED.{column} missing" in w for w in s.warnings)


def test_task_without_proj_id_takes_the_only_project():
    s = build_snapshot(parse_text(drop_column(_linked_text(), "TASK", "proj_id"), source="t.xer"))
    assert len(s.activities) == 3 and len(s.relationships) == 2
    assert any("TASK.proj_id missing" in w for w in s.warnings)


def test_task_without_proj_id_and_several_projects_raises():
    text = _linked_text().replace("%T\tTASK\n", "%T\tPROJECT\n%F\tproj_id\n%R\t2\n%T\tTASK\n", 1)
    with pytest.raises(XerError, match=r"t\.xer.*TASK.*proj_id"):
        build_snapshot(parse_text(drop_column(text, "TASK", "proj_id"), source="t.xer"))


def test_task_without_task_code_raises_xer_error():
    with pytest.raises(XerError, match="table TASK has no column task_code"):
        build_snapshot(parse_text(drop_column(_linked_text(), "TASK", "task_code"), source="t.xer"))


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("TASK", "task_id"),
        ("TASK", "task_code"),
        ("TASK", "proj_id"),
        ("TASK", "status_code"),
        ("TASKPRED", "task_id"),
        ("TASKPRED", "pred_task_id"),
        ("TASKPRED", "proj_id"),
        ("TASKPRED", "pred_proj_id"),
        ("PROJECT", "proj_id"),
        ("PROJECT", "proj_short_name"),
        ("CALENDAR", "clndr_id"),
        ("PROJWBS", "proj_id"),
    ],
)
def test_missing_column_never_leaks_a_key_error(table, column):
    text = xer_text(
        [active("A"), active("B")],
        [("A", "B", "FS", 0)],
        wbs=[{"wbs_id": "10", "proj_id": "1", "wbs_short_name": "W", "wbs_name": "W", "proj_node_flag": "Y"}],
    )
    with contextlib.suppress(XerError):  # a clear XerError is fine, a KeyError is not
        build_snapshot(parse_text(drop_column(text, table, column), source="t.xer"))
