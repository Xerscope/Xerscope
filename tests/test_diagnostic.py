"""Debug page block 6: the activities behind each load warning of the file."""

import pandas as pd
import pytest
from xerkit import active, done, snap, todo

from xerscope.analysis import builtin_standards
from xerscope.app.diagnostic import ABSENT, costs_table, diagnostic_frames, finish_table, leveling_table


def test_leveling_table_lists_the_activities_the_warning_counts():
    """Restart apart from early start: A (not started) and B (in progress) are counted, C is
    complete and not counted; D has its restart equal to its early start."""
    s = snap(
        [
            todo("A", early_start_date="2026-03-02 08:00", restart_date="2026-03-09 08:00"),
            active("B", early_start_date="2026-03-02 08:00", restart_date="2026-03-04 08:00"),
            done("C", early_start_date="2026-03-02 08:00", restart_date="2026-03-09 08:00"),
            todo("D", early_start_date="2026-03-02 08:00", restart_date="2026-03-02 08:00"),
        ]
    )
    assert any("2 open activities have a remaining early start" in w for w in s.warnings)
    table = leveling_table(s)
    assert table["task_code"].tolist() == ["A", "B"]
    assert table.columns.tolist() == [
        "task_code",
        "status_code",
        "early_start_date",
        "restart_date",
        "act_start_date",
    ]
    assert table.loc[0, "restart_date"] == pd.Timestamp("2026-03-09 08:00")


def test_finish_table_holds_scd_end_date_and_the_latest_activities():
    """scd_end_date 30 Jul 2027 against activities that end 13 and 20 Mar 2026: the warning,
    and the activities that end last, latest first."""
    s = snap(
        [
            todo("A", early_end_date="2026-03-13 17:00"),
            todo("B", early_end_date="2026-03-20 17:00"),
        ],
        project={"scd_end_date": "2027-07-30 17:00"},
    )
    assert any("PROJECT.scd_end_date 2027-07-30 differs" in w for w in s.warnings)
    project, latest = finish_table(s)
    assert project.to_dict("records") == [
        {"scd_end_date": pd.Timestamp("2027-07-30 17:00"), "latest_activity_finish": pd.Timestamp("2026-03-20 17:00")}
    ]
    assert latest["task_code"].tolist() == ["B", "A"]
    assert latest.columns.tolist() == ["task_code", "task_type", "status_code", "finish"]


def test_costs_table_sums_the_assignment_and_expense_costs():
    """Two assignments (1000.00 at 25 per unit, 250.50 at 10 per unit) and one expense of 300:
    TASKRSRC 2 rows, 2 with a cost, total 1250.50, rate 10 to 25; PROJCOST 1 row, total 300."""
    s = snap(
        [todo("A"), todo("B")],
        assign=[
            {"task_code": "A", "rsrc_id": "900", "target_cost": "1000.00", "cost_per_qty": "25"},
            {"task_code": "B", "rsrc_id": "900", "target_cost": "250.50", "cost_per_qty": "10"},
        ],
        costs=[{"task_code": "A", "target_cost": "300"}],
    )
    table = costs_table(s).set_index("table")
    assert table.loc["TASKRSRC"].to_dict() == {
        "rows": 2,
        "rows_with_cost": 2,
        "target_cost_total": 1250.5,
        "cost_per_qty_min": 10.0,
        "cost_per_qty_max": 25.0,
    }
    assert table.loc["PROJCOST", ["rows", "rows_with_cost", "target_cost_total"]].tolist() == [1, 1, 300.0]
    assert "07_costs" in diagnostic_frames(s, None, builtin_standards()["P6"])


def test_costs_table_says_absent_when_the_file_has_no_cost_column():
    s = snap([todo("A")], rsrc=["A"], costs=["A"])
    table = costs_table(s).set_index("table")
    assert table.loc["TASKRSRC"].to_dict() == {
        "rows": 1,
        "rows_with_cost": ABSENT,
        "target_cost_total": ABSENT,
        "cost_per_qty_min": ABSENT,
        "cost_per_qty_max": ABSENT,
    }
    assert table.loc["PROJCOST", ["rows", "target_cost_total"]].tolist() == [1, ABSENT]


def test_costs_table_of_a_file_without_resources_or_expenses():
    table = costs_table(snap([todo("A")])).set_index("table")
    assert table["rows"].tolist() == [0, 0]
    assert table["target_cost_total"].tolist() == [ABSENT, ABSENT]


def test_ev_settings_block_lists_each_wbs_and_counts_the_techniques():
    wbs = [
        {
            "wbs_id": code,
            "proj_id": "1",
            "wbs_short_name": code,
            "wbs_name": code,
            "proj_node_flag": "N",
            "parent_wbs_id": "",
            "seq_num": "1",
            "ev_compute_type": "EC_Cmp_pct",
            "ev_etc_compute_type": etc,
            "ev_etc_user_value": "1",
        }
        for code, etc in (("W1", "EE_Rem_hr"), ("W2", "EE_PF_1"))
    ]
    s = snap([todo("A", wbs_id="W1"), todo("B", wbs_id="W2"), todo("C", wbs_id="W2")], wbs=wbs)
    frames = diagnostic_frames(s, None, builtin_standards()["P6"])
    assert frames["08_ev_settings"][["wbs_code", "ev_etc_compute_type", "etc_technique", "activities"]].to_dict(
        "records"
    ) == [
        {"wbs_code": "W1", "ev_etc_compute_type": "EE_Rem_hr", "etc_technique": "remaining units", "activities": 1},
        {"wbs_code": "W2", "ev_etc_compute_type": "EE_PF_1", "etc_technique": "PF = 1", "activities": 2},
    ]
    counts = frames["08_etc_techniques"].set_index("etc_technique")
    assert counts["wbs"].to_dict() == {"remaining units": 1, "PF = 1": 1}


# --- block 09: XER tables and planned value labour units ----------------------------------------

MON, FRI = "2026-03-02 08:00", "2026-03-06 17:00"
WED = "2026-03-04 08:00"  # two of the five working days of the week MON-FRI are elapsed: 0.4
WEEK = dict(early_start_date=MON, early_end_date=FRI, target_drtn_hr_cnt="40", remain_drtn_hr_cnt="40")


def _labor(code, qty, start=None, end=None, **kw):
    dates = {"target_start_date": start, "target_end_date": end} if start else {}
    return dict(task_code=code, rsrc_id="R1", rsrc_type="RT_Labor", target_qty=str(qty), **dates, **kw)


def test_xer_tables_lists_every_table_of_the_file_with_rows_and_columns():
    """An unknown table added to the file is listed with its own counts; no cell value is written."""
    from xerkit import xer_text

    from xerscope.xer import build_snapshot, parse_text

    text = xer_text([todo("A"), todo("B")]) + "%T\tMYSTERY\n%F\tx\ty\tz\n%R\ta\tb\tc\n%R\td\te\tf\n%R\tg\th\ti\n"
    s = build_snapshot(parse_text(text, source="test.xer"))
    table = diagnostic_frames(s, None, builtin_standards()["P6"])["09_xer_tables"].set_index("table")
    assert table.loc["MYSTERY"].tolist() == [3, 3]
    assert table.loc["TASK", "rows"] == 2 and {"PROJECT", "CALENDAR"} <= set(table.index)
    assert list(table.columns) == ["rows", "columns"]
    assert "a" not in set(
        diagnostic_frames(s, None, builtin_standards()["P6"])["09_xer_tables"].astype(str).to_numpy().ravel()
    )


def test_pv_labor_check_by_assignment_against_by_activity():
    """Data date Wednesday 08:00 (2 of 5 working days of the baseline week = 0.4).
    A, 160 h: 100 h Mon-Fri -> 100 x 0.4 = 40; 60 h Tue-Fri (8 of 32 h elapsed = 0.25) -> 15.
      By assignment 55, by activity 160 x 0.4 = 64, gap -9. In progress.
    B, 40 h, no assignment: 40 x 0.4 = 16 both ways. In progress.
    C, 80 h, one assignment naming a curve, on the activity's dates: 80 x 0.4 = 32 both ways.
    D, 40 h next week: 0 both ways. Not started.
    E, 40 h the week before, one assignment Wed 02-25 to Fri 03-06 (24 + 16 = 40 of 64 h elapsed = 0.625
      -> 25) against the activity's 40 (complete by its dates): gap -15."""
    from xerscope.analysis import Baseline
    from xerscope.analysis.evm import pv_labor_check

    week_before = dict(early_start_date="2026-02-23 08:00", early_end_date="2026-02-27 17:00")
    next_week = dict(early_start_date="2026-03-09 08:00", early_end_date="2026-03-13 17:00")
    tasks = [
        todo("A", **WEEK, target_work_qty="160"),
        todo("B", **WEEK, target_work_qty="40"),
        todo("C", **WEEK, target_work_qty="80"),
        todo("D", **{**WEEK, **next_week}, target_work_qty="40"),
        todo("E", **{**WEEK, **week_before}, target_work_qty="40"),
    ]
    assign = [
        _labor("A", 100, MON, FRI),
        _labor("A", 60, "2026-03-03 08:00", FRI),
        _labor("C", 80, curv_id="7"),
        _labor("E", 40, "2026-02-25 08:00", FRI),
    ]
    baseline = Baseline.from_snapshot(snap(tasks, assign=assign))
    update = snap(tasks, assign=assign, data_date=WED)
    totals, by_status = pv_labor_check(update, baseline)
    row = totals.iloc[0]
    assert (row["activities"], row["assignments"], row["labor_assignments"]) == (5, 4, 4)
    assert (row["labor_assignments_with_curve"], row["bl_hr_with_curve"]) == (1, 80)
    assert (row["bac_activity_hr"], row["bac_assignment_hr"]) == (360, 360)
    assert (row["pv_activity_hr"], row["pv_assignment_hr"], row["gap_hr"]) == pytest.approx(
        (64 + 16 + 32 + 40, 55 + 16 + 32 + 25, -9 - 15)
    )
    by_status = by_status.set_index("status")
    assert by_status["activities"].to_dict() == {"not started": 1, "in progress": 3, "complete": 1}
    assert by_status["gap_hr"].to_dict() == pytest.approx({"not started": 0, "in progress": -9, "complete": -15})
    assert by_status["pv_assignment_hr"].sum() == pytest.approx(row["pv_assignment_hr"])


def test_pv_labor_check_equals_the_activity_value_without_assignments():
    from xerscope.analysis import Baseline
    from xerscope.analysis.evm import pv_labor_check

    tasks = [todo("B", **WEEK, target_work_qty="40")]
    totals, _ = pv_labor_check(snap(tasks, data_date=WED), Baseline.from_snapshot(snap(tasks)))
    assert totals.loc[0, ["pv_activity_hr", "pv_assignment_hr", "gap_hr"]].tolist() == pytest.approx([16, 16, 0])


def test_pv_labor_check_is_empty_without_baseline_and_in_the_diagnostic_zip():
    s = snap([todo("A")])
    frames = diagnostic_frames(s, None, builtin_standards()["P6"])
    assert frames["09_pv_labor_check"].empty and frames["09_pv_labor_by_status"].empty


def test_pv_labor_check_variants_calendar_time_and_end_of_the_data_date():
    """B, 40 h, Mon 08:00 to Fri 17:00 (40 working hours, 105 calendar hours), data date Wed 08:00.
    Working time at the data date: 16 of 40 h -> 16. Calendar time: 48 of 105 h -> 40 x 48 / 105.
    End of the data date's day (Thu 00:00), working time: Mon to Wed, 24 of 40 h -> 24; calendar
    time: 64 of 105 h -> 40 x 64 / 105."""
    from xerscope.analysis import Baseline
    from xerscope.analysis.evm import pv_labor_check

    tasks = [todo("B", **WEEK, target_work_qty="40")]
    totals, _ = pv_labor_check(snap(tasks, data_date=WED), Baseline.from_snapshot(snap(tasks)))
    row = totals.iloc[0]
    assert row["pv_activity_hr"] == pytest.approx(16)
    assert row["pv_calendar_time_hr"] == pytest.approx(40 * 48 / 105)
    assert row["pv_end_of_day_hr"] == pytest.approx(24)
    assert row["pv_calendar_time_end_of_day_hr"] == pytest.approx(40 * 64 / 105)


def test_assignment_dates_counts_lags_own_dates_and_calendars():
    """A (task dependent, Mon-Fri): R1 on the activity's dates; R2 with an Original Lag of 8 h,
    planned Tue-Fri, on a resource calendar C10 other than the activity's C8. B (resource
    dependent): one assignment without planned dates. A nonlabor assignment is left out.
    Expected: 3 labour assignments, 1 with an Original Lag, 1 starting later than its activity,
    0 finishing earlier, 1 without planned dates, 1 task dependent on another calendar, 1
    resource dependent."""
    from xerscope.app.diagnostic import assignment_dates_table

    week = dict(target_start_date=MON, target_end_date=FRI)
    tasks = [todo("A", **WEEK, **week), todo("B", **WEEK, **week, task_type="TT_Rsrc")]
    resources = [
        dict(rsrc_id="R1", rsrc_short_name="R1", rsrc_type="RT_Labor", clndr_id="C8"),
        dict(rsrc_id="R2", rsrc_short_name="R2", rsrc_type="RT_Labor", clndr_id="C10"),
        dict(rsrc_id="E1", rsrc_short_name="E1", rsrc_type="RT_Equip", clndr_id="C8"),
    ]
    assign = [
        _labor("A", 100, MON, FRI),
        {**_labor("A", 60, "2026-03-03 08:00", FRI, target_lag_drtn_hr_cnt="8"), "rsrc_id": "R2"},
        _labor("B", 40),
        dict(task_code="A", rsrc_id="E1", rsrc_type="RT_Equip", target_qty="5", target_lag_drtn_hr_cnt="8"),
    ]
    row = assignment_dates_table(snap(tasks, assign=assign, resources=resources)).iloc[0].to_dict()
    assert row == {
        "labor_assignments": 3,
        "with_original_lag": 1,
        "with_remaining_lag": 0,
        "planned_dates_blank": 1,
        "planned_start_later_than_activity": 1,
        "planned_finish_earlier_than_activity": 0,
        "task_dependent_on_other_calendar": 1,
        "resource_dependent": 1,
    }
