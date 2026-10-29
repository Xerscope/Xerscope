import pandas as pd
import pytest
from xerkit import active, snap, todo

from xerscope.xer import build_snapshot, parse_text


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


def _xer(project_extra: dict, sched: dict | None = None, tasks=None, preds=None):
    """Minimal XER text. Calendars: C8 = 8 h/day, C10 = 10 h/day, C7 = 7.5 h/day."""
    pf = {
        "proj_id": "1",
        "proj_short_name": "P",
        "last_recalc_date": "2026-03-02 08:00",
        "clndr_id": "C7",
        **project_extra,
    }
    lines = [
        "ERMHDR\t23.12\t2026-03-02",
        "%T\tCALENDAR",
        "%F\tclndr_id\tclndr_name\tday_hr_cnt",
        "%R\tC8\tEight\t8",
        "%R\tC10\tTen\t10",
        "%R\tC7\tSeven-half\t7.5",
        "%T\tPROJECT",
        "%F\t" + "\t".join(pf),
        "%R\t" + "\t".join(pf.values()),
    ]
    if sched:
        lines += ["%T\tSCHEDOPTIONS", "%F\tproj_id\t" + "\t".join(sched), "%R\t1\t" + "\t".join(sched.values())]
    cols = [
        "task_id",
        "proj_id",
        "task_code",
        "task_name",
        "task_type",
        "status_code",
        "clndr_id",
        "total_float_hr_cnt",
        "driving_path_flag",
    ]
    lines += ["%T\tTASK", "%F\t" + "\t".join(cols)]
    for r in tasks or []:
        lines.append("%R\t" + "\t".join(r))
    if preds:
        lines += [
            "%T\tTASKPRED",
            "%F\ttask_pred_id\ttask_id\tpred_task_id\tproj_id\tpred_proj_id\tpred_type\tlag_hr_cnt",
        ]
        lines += ["%R\t" + "\t".join(r) for r in preds]
    return "\n".join(lines) + "\n"


TASKS = [  # id, proj, code, name, type, status, calendar, TF hours, driving path
    ["1", "1", "A", "A", "TT_Task", "TK_NotStart", "C8", "0", "Y"],
    ["2", "1", "B", "B", "TT_Task", "TK_NotStart", "C10", "40", "N"],
    ["3", "1", "C", "C", "TT_Task", "TK_NotStart", "C8", "48", "Y"],
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
        preds=[["9", "2", "1", "1", "1", "PR_FS", "30"]],
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
