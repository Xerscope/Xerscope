"""Debug page block 6: the activities behind each load warning of the file."""

import dataclasses
from datetime import date

import pandas as pd
import pytest
from xerkit import active, clndr_data, done, snap, todo

from xerscope.analysis import builtin_standards
from xerscope.app.diagnostic import (
    ABSENT,
    DEFAULTED,
    FROM_FILE,
    check_parameters,
    costs_table,
    diagnostic_frames,
    finish_table,
    leveling_table,
    options_comparison,
    options_table,
)
from xerscope.app.expected_finish_forms import expected_finish_forms
from xerscope.app.recalculation_departures import departure_forms, departure_funnel, departures


def test_options_comparison_puts_the_baseline_next_to_the_update_and_says_what_differs():
    """Two files of one project scheduled with different options give dates that do not compare.
    Update: Progress Override, total float = start float (FT_SS). Baseline file: Retained Logic, no
    float type written, so P6's default (finish float, FT_FF) applies. Two options differ, float_type
    and progressed; the nine others are the same on both sides."""
    update = snap(
        [todo("A")],
        sched={"sched_retained_logic": "N", "sched_progress_override": "Y", "sched_float_type": "FT_SS"},
    )
    baseline = snap([todo("A")], sched={"sched_retained_logic": "Y", "sched_progress_override": "N"})
    table = options_comparison(update, baseline).set_index("option")
    assert list(table.index) == list(options_table(update)["option"])  # one row per option, same order
    assert list(table.index[~table["same"]]) == ["float_type", "progressed"]
    assert table.loc["float_type", ["update", "update_origin", "baseline", "baseline_origin"]].tolist() == [
        "FT_SS",
        FROM_FILE,
        "FT_FF",
        DEFAULTED,
    ]
    assert table.loc["progressed", ["update", "baseline"]].tolist() == ["progress_override", "retained_logic"]
    assert options_comparison(update, update)["same"].all()  # a file against itself: nothing differs


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
    assert any("2 open tasks have a remaining early start" in w for w in s.warnings)
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

    text = xer_text([todo("A"), todo("B")]).replace(
        "%E\n", "%T\tMYSTERY\n%F\tx\ty\tz\n%R\ta\tb\tc\n%R\td\te\tf\n%R\tg\th\ti\n%E\n"
    )
    s = build_snapshot(parse_text(text, source="test.xer"))
    table = diagnostic_frames(s, None, builtin_standards()["P6"])["09_xer_tables"].set_index("table")
    assert table.loc["MYSTERY"].tolist() == [3, 3]
    assert table.loc["TASK", "rows"] == 2 and {"PROJECT", "CALENDAR"} <= set(table.index)
    assert list(table.columns) == ["rows", "columns"]
    assert "a" not in set(
        diagnostic_frames(s, None, builtin_standards()["P6"])["09_xer_tables"].astype(str).to_numpy().ravel()
    )


def test_the_anonymous_diagnostic_lists_user_defined_fields_without_their_label():
    """One text field of TASK, "Location", set on A: the page's table carries the label, the anonymous
    download keeps the field's id, table, type and counts, and writes the label nowhere."""
    from xerkit import xer_text

    from xerscope.xer import build_snapshot, parse_text

    tables = (
        "%T\tUDFTYPE\n%F\tudf_type_id\ttable_name\tudf_type_label\tlogical_data_type\n%R\t7\tTASK\tLocation\tFT_TEXT\n"
        "%T\tUDFVALUE\n%F\tudf_type_id\tfk_id\tproj_id\tudf_text\n%R\t7\t1\t1\tZone 1\n"
    )
    s = build_snapshot(parse_text(xer_text([todo("A")]).replace("%E\n", tables + "%E\n"), source="test.xer"))
    p6 = builtin_standards()["P6"]
    shown = diagnostic_frames(s, None, p6)["09_udf_fields"]
    assert shown.to_numpy().tolist() == [["7", "Location", "TASK", "FT_TEXT", 1, 1, 1]]
    anonymous = diagnostic_frames(s, None, p6, anonymous=True)["09_udf_fields"]
    assert anonymous.to_numpy().tolist() == [["7", "TASK", "FT_TEXT", 1, 1, 1]]
    assert "label" not in anonymous.columns


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


# --- Debug block 09: date and baseline columns of TASK -----------------------------------------


@pytest.mark.oracle("standard")
def test_task_date_columns_lists_a_baseline_column_the_data_map_does_not_have():
    """Source: XER Import/Export Data Map Guide (Project) v26, G57491-01, table TASK: target_end_date is
    "Planned Finish", update_user "Last Modified By"; no column base_start_date / base_end_date.
    A holds both base_* dates, B only base_end_date, C none; A and B carry a Last Modified By, B's a name
    that reads like a date, which must not come out as one.
    By hand: base_end_date 2 activities, earliest 2026-01-09 17:00, latest 2026-02-20 17:00;
    base_start_date 1 activity, 2026-01-05 08:00; update_user 2 activities, no date."""
    from xerscope.app.xer_columns import NOT_IN_DATA_MAP, task_date_columns_table

    tasks = [
        todo("A", base_start_date="2026-01-05 08:00", base_end_date="2026-01-09 17:00", update_user="U1"),
        todo("B", base_end_date="2026-02-20 17:00", update_user="2026-03-01 08:00"),
        todo("C"),
    ]
    rows = task_date_columns_table(snap(tasks)).set_index("column")
    assert rows.loc["base_end_date"].to_dict() == {
        "label": NOT_IN_DATA_MAP,
        "tasks": 2,
        "earliest": pd.Timestamp("2026-01-09 17:00"),
        "latest": pd.Timestamp("2026-02-20 17:00"),
    }
    assert rows.loc["base_start_date", "tasks"] == 1
    assert rows.loc["base_start_date", "earliest"] == pd.Timestamp("2026-01-05 08:00")
    assert rows.loc["target_end_date", "label"] == "Planned Finish"
    assert rows.loc["update_user", "label"] == "Last Modified By"
    assert rows.loc["update_user", "tasks"] == 2
    assert pd.isna(rows.loc["update_user", "earliest"])  # a user name, never shown nor read as a date


@pytest.mark.oracle("characterization")
def test_xer_columns_lists_every_column_of_the_file_with_the_rows_holding_a_value():
    """By hand: TASK has 3 rows; base_end_date is written on A only, blank on B and C, so 1 row holds a
    value; task_code is on all 3. PROJECT has 1 row with last_recalc_date. A column of the file that
    xerscope never reads is listed all the same."""
    from xerscope.app.xer_columns import xer_columns_table

    tasks = [todo("A", base_end_date="2026-01-09 17:00", zz_unread="x"), todo("B"), todo("C")]
    rows = xer_columns_table(snap(tasks)).set_index(["table", "column"])["rows_with_value"]
    assert rows[("TASK", "base_end_date")] == 1
    assert rows[("TASK", "zz_unread")] == 1
    assert rows[("TASK", "task_code")] == 3
    assert rows[("PROJECT", "last_recalc_date")] == 1


@pytest.mark.oracle("characterization")
def test_file_fields_lists_every_field_of_the_raw_file_in_its_order_without_the_model():
    """Read by the parser alone: a TASK of 3 rows whose %F line carries base_start_date and base_end_date,
    filled on A only, and a table the model never reads (ZZTABLE). By hand: TASK base_end_date is at its
    place in the %F line, 3 rows, 1 with a value; ZZTABLE zz_field 1 row, 0 with a value."""
    from xerkit import xer_text

    from xerscope.app.xer_columns import file_fields_table
    from xerscope.xer import parse_text

    tasks = [todo("A", base_start_date="2026-01-05 08:00", base_end_date="2026-01-09 17:00"), todo("B"), todo("C")]
    text = xer_text(tasks).replace("%E", "%T\tZZTABLE\n%F\tzz_field\n%R\t \n%E")
    fields = file_fields_table(parse_text(text, source="x.xer"))
    task = fields[fields["table"] == "TASK"].reset_index(drop=True)
    header = next(line for line in text.splitlines() if line.startswith("%F") and "task_code" in line).split("\t")[1:]
    assert task["column"].tolist() == header
    row = task[task["column"] == "base_end_date"].iloc[0]
    assert (row["position"], row["rows"], row["rows_with_value"]) == (header.index("base_end_date") + 1, 3, 1)
    extra = fields[fields["table"] == "ZZTABLE"].iloc[0]
    assert (extra["column"], extra["rows"], extra["rows_with_value"]) == ("zz_field", 1, 0)


# --- Debug block 11: project settings ----------------------------------------------------------

COUNTS = ["tasks_CP_Phys", "tasks_CP_Drtn", "tasks_CP_Units", "tasks_pct_blank", "tasks_pct_other"]
SETTINGS = {
    "use_project_baseline_flag": "Y",
    "sum_base_proj_id": "2",
    "baselines_to_export": "2",
    "baseline_names_to_export": "SECRETBL1,SECRETBL2",
    "def_complete_pct_type": "CP_Units",
    "add_act_remain_flag": "N",
    "act_this_per_link_flag": "Y",
    "act_pct_link_flag": "N",
    "rem_target_link_flag": "Y",
    "reset_planned_flag": "N",
    "def_task_type": "TT_Task",
    "def_duration_type": "DT_FixedDrtn",
    "next_data_date": "",
}


def _two_projects_text():
    from xerkit import DD, with_second_project, xer_text

    tasks = [
        todo("A"),
        todo("B", complete_pct_type="CP_Phys"),
        todo("C", complete_pct_type="CP_Units"),
        todo("D", complete_pct_type=""),
        todo("E", complete_pct_type="CP_Scope"),
    ]
    main = xer_text(tasks, project={**SETTINGS, "proj_short_name": "SECRETPRJ"})
    return with_second_project(main, "SECRETBASE", ["A"], DD)


def _settings(text):
    from xerscope.app.diagnostic import project_settings_table
    from xerscope.xer import build_snapshot, parse_text

    return project_settings_table(build_snapshot(parse_text(text, source="x.xer"))).set_index("proj_id")


def test_project_settings_show_y_n_as_stored_and_count_tasks_by_pct_type():
    """Project 1: the settings above and 5 tasks, one per kind (Phys, Drtn, Units, blank, other: CP_Scope).
    Project 2 (a second PROJECT row without these values) owns 1 Drtn task. Y / N stay as stored, the
    two baseline names count 2, a blank next_data_date stays blank (the column is there)."""
    table = _settings(_two_projects_text())
    first, second = table.loc["1"], table.loc["2"]
    flags = ["use_project_baseline_flag", "add_act_remain_flag", "act_this_per_link_flag", "act_pct_link_flag"]
    assert first[flags].tolist() == ["Y", "N", "Y", "N"]
    assert first[["rem_target_link_flag", "reset_planned_flag"]].tolist() == ["Y", "N"]
    assert first[["def_complete_pct_type", "def_task_type", "def_duration_type"]].tolist() == [
        "CP_Units",
        "TT_Task",
        "DT_FixedDrtn",
    ]
    assert first[["sum_base_proj_id", "baselines_to_export", "baseline_names_to_export"]].tolist() == ["2", "2", 2]
    assert first["next_data_date"] == "" and first["last_recalc_date"] == "2026-03-02 08:00"
    assert first[COUNTS].tolist() == [1, 1, 1, 1, 1]
    assert second[COUNTS].tolist() == [0, 1, 0, 0, 0]
    assert second[["use_project_baseline_flag", "baseline_names_to_export"]].tolist() == ["", 0]


def test_project_settings_columns_the_file_lacks_read_absent():
    """The default test PROJECT row has none of the settings but last_recalc_date; sum_base_proj_id and
    use_project_baseline_flag read blank (as the baseline resolution reads them), the others absent."""
    from xerkit import xer_text

    row = _settings(xer_text([todo(c) for c in "ABC"])).loc["1"]
    others = [c for c in SETTINGS if c not in ("sum_base_proj_id", "use_project_baseline_flag")]
    assert row[others].tolist() == [ABSENT] * len(others)
    assert row[["sum_base_proj_id", "use_project_baseline_flag"]].tolist() == ["", ""]
    assert row["last_recalc_date"] == "2026-03-02 08:00"
    assert row[COUNTS].tolist() == [0, 3, 0, 0, 0]


def test_project_settings_counts_read_absent_when_task_has_no_complete_pct_type():
    from xerkit import xer_text

    lines = xer_text([todo("A")]).splitlines()
    at = lines.index("%T\tTASK")
    drop = lines[at + 1].split("\t").index("complete_pct_type")
    for i in (at + 1, at + 2):
        cells = lines[i].split("\t")
        del cells[drop]
        lines[i] = "\t".join(cells)
    assert _settings("\n".join(lines) + "\n").loc["1", COUNTS].tolist() == [ABSENT] * len(COUNTS)


def test_project_settings_zip_renames_project_codes_and_holds_no_baseline_name():
    import io
    import zipfile

    from xerscope.anonymize import Anonymizer
    from xerscope.xer import build_snapshot, parse_text

    raw = parse_text(_two_projects_text(), source="x.xer")
    frames = diagnostic_frames(build_snapshot(raw), None, builtin_standards()["P6"], anonymous=True)
    block = {name: frame for name, frame in frames.items() if name.startswith("11_")}
    assert sorted(block) == ["11_project_settings"]
    with zipfile.ZipFile(io.BytesIO(Anonymizer.from_raws([raw]).zip_frames(block))) as archive:
        text = "".join(archive.read(name).decode("utf-8-sig") for name in archive.namelist())
        shown = pd.read_csv(
            io.StringIO(archive.read("11_project_settings.csv").decode("utf-8-sig")), dtype=str, keep_default_na=False
        )
    assert "SECRET" not in text
    assert shown["proj_short_name"].str.startswith("XP").all() and shown["proj_short_name"].nunique() == 2
    assert shown["baseline_names_to_export"].tolist() == ["2", "0"]


def test_project_settings_meaning_covers_every_setting_and_marks_the_unverified():
    from xerscope.app.diagnostic import project_settings_meaning_table
    from xerscope.xer.model import PROJECT_SETTING_COLUMNS

    meaning = project_settings_meaning_table().set_index("field")
    settings = [field.removeprefix("PROJECT.") for field in meaning.index if field.startswith("PROJECT.")]
    assert settings == PROJECT_SETTING_COLUMNS
    assert meaning.loc["PROJECT.next_data_date", "reading"] == "meaning unverified"
    assert meaning.loc["PROJECT.sum_base_proj_id", "xer_label"] == "Project Baseline"
    assert meaning.filter(like="PROJWBS", axis=0)["reading"].tolist() == [ABSENT]


# --- block 13: calendar detail ------------------------------------------------------------------------
# xerkit's C8 is Monday to Friday 08:00-12:00 / 13:00-17:00 with one holiday, Friday 2026-04-03 (serial
# 46115); its CALENDAR row stores 8 h per day and 40 h per week. A calendar of uneven days is added:
# Monday 07:00-11:30 (4.5 h), Tuesday 00:00-00:00 (a 24 h day), a working Saturday 2026-03-07 and a
# shortened Monday 2026-03-02, with 8 h per day and 40 h per week stored.
UNEVEN_DAYS = clndr_data(range(2, 4), [("07:00", "11:30")], ())
UNEVEN_DAYS = UNEVEN_DAYS.replace("(0||3()((0||0(s|07:00|f|11:30)())))", "(0||3()((0||0(s|00:00|f|00:00)())))")
UNEVEN_DAYS = UNEVEN_DAYS.replace(
    "(0||Exceptions()())",
    "(0||Exceptions()((0||0(d|46088)((0||0(s|08:00|f|12:00)())))(0||1(d|46083)((0||0(s|07:00|f|09:00)())))))",
)
UNEVEN_CALENDAR = {
    "clndr_id": "U1",
    "clndr_name": "Uneven",
    "day_hr_cnt": "8",
    "week_hr_cnt": "40",
    "clndr_data": UNEVEN_DAYS,
}


@pytest.fixture(scope="module")
def calendar_frames():
    from xerscope.app.diagnostic import calendar_detail_frames

    snapshot = snap([todo("A"), todo("B", clndr_id="U1")], calendars=[UNEVEN_CALENDAR])
    return calendar_detail_frames(snapshot)


def test_calendar_summary_sets_the_stored_hours_beside_the_periods(calendar_frames):
    summary = calendar_frames["13_calendar_summary"].set_index("clndr_id")
    standard = summary.loc["8"]  # xerkit writes C8 as clndr_id 8
    assert standard["week_hours_from_periods"] == 40 and standard["day_lengths_from_periods"] == "8"
    assert standard["day_hr_cnt_matches_periods"] and standard["week_hr_cnt_matches_periods"]
    assert standard["exceptions_non-working_day"] == 1 and standard["activities"] == 1
    uneven = summary.loc["U1"]
    assert uneven["working_days_per_week"] == 2 and uneven["week_hours_from_periods"] == 28.5  # 4.5 + 24
    assert uneven["day_lengths_from_periods"] == "4.5, 24"
    assert not uneven["day_hr_cnt_matches_periods"] and not uneven["week_hr_cnt_matches_periods"]
    assert uneven["hours_per_day_used_for_days"] == 8  # days still divide by the stored day_hr_cnt
    assert uneven["exceptions_working_day_on_a_non-working_weekday"] == 1
    assert uneven["exceptions_other_working_hours"] == 1


def test_calendar_week_writes_each_weekday_as_p6_shows_it(calendar_frames):
    week = calendar_frames["13_calendar_week"]
    uneven = week[week["clndr_id"] == "U1"].set_index("weekday")
    assert uneven.loc["Monday", "working_periods"] == "07:00-11:30" and uneven.loc["Monday", "working_hours"] == 4.5
    assert uneven.loc["Tuesday", "working_periods"] == "00:00-24:00" and uneven.loc["Tuesday", "working_hours"] == 24
    assert uneven.loc["Sunday", "working_periods"] == "" and uneven.loc["Sunday", "working_hours"] == 0
    standard = week[week["clndr_id"] == "8"].set_index("weekday")
    assert standard.loc["Friday", "working_periods"] == "08:00-12:00, 13:00-17:00"


def test_calendar_exceptions_say_what_they_do_to_the_weekday(calendar_frames):
    exceptions = calendar_frames["13_calendar_exceptions"].set_index(["clndr_id", "date"])
    holiday = exceptions.loc[("8", date(2026, 4, 3))]
    assert holiday["kind"] == "non-working day" and holiday["weekday_working_hours"] == 8
    saturday = exceptions.loc[("U1", date(2026, 3, 7))]
    assert saturday["kind"] == "working day on a non-working weekday" and saturday["working_hours"] == 4
    monday = exceptions.loc[("U1", date(2026, 3, 2))]
    assert monday["kind"] == "other working hours" and monday["working_periods"] == "07:00-09:00"
    assert monday["weekday_working_periods"] == "07:00-11:30" and monday["weekday_working_hours"] == 4.5


def test_calendar_detail_is_in_the_diagnostic_zip_without_names_when_anonymous():
    from xerscope.app.diagnostic import calendar_summary_table

    snapshot = snap([todo("A")], calendars=[UNEVEN_CALENDAR])
    assert "clndr_name" in calendar_summary_table(snapshot).columns
    assert "clndr_name" not in calendar_summary_table(snapshot, anonymous=True).columns
    frames = diagnostic_frames(snapshot, None, builtin_standards()["P6"], anonymous=True)
    assert {"13_calendar_summary", "13_calendar_week", "13_calendar_exceptions"} <= set(frames)


def test_check_parameters_show_the_dangling_options_the_standard_sets():
    """Block 04 reads the Dangling options (113174) from the standard in use, not fixed text."""
    p6 = builtin_standards()["P6"]

    def options(standard):
        table = check_parameters(standard).set_index("check")
        return {check: table.loc[check, "target"] for check in table.index if "Ignore" in check}

    assert options(p6) == {
        "P6-16 · Ignore in-progress activities": "checked",
        "P6-17 · Ignore activities with soft constraints": "unchecked",
        "P6-17 · Ignore activities with hard constraints": "unchecked",
    }
    metrics = [
        dataclasses.replace(metric, params={**metric.params, "ignore_in_progress": False})
        if metric.id == "P6-16"
        else dataclasses.replace(metric, params={**metric.params, "ignore_hard_constraints": True})
        if metric.id == "P6-17"
        else metric
        for metric in p6.metrics
    ]
    assert options(dataclasses.replace(p6, metrics=metrics)) == {
        "P6-16 · Ignore in-progress activities": "unchecked",
        "P6-17 · Ignore activities with soft constraints": "unchecked",
        "P6-17 · Ignore activities with hard constraints": "checked",
    }


def test_baseline_block_names_the_kind_basis_and_link_of_the_baseline_in_use():
    """Block 5: a loaded update used as baseline is not a "separate file"; a P6 XML baseline and a
    fallback say so; the EV basis and the GUID link option are written, the source unless anonymous."""
    import dataclasses

    from xerscope.analysis import Baseline
    from xerscope.app.diagnostic import baseline_table

    first = dataclasses.replace(snap([todo("A")], data_date="2026-03-02 08:00"), source="a.xer")
    update = dataclasses.replace(snap([todo("A")], data_date="2026-03-09 08:00"), source="b.xer")
    loaded = Baseline.from_snapshot(first, "budgeted_current")
    row = baseline_table(update, loaded, updates=["a.xer", "b.xer"], guid_link=True).iloc[0]
    assert (row["kind"], row["ev_basis"], row["guid_link"]) == ("loaded update", "budgeted_current", True)
    xml = dataclasses.replace(
        Baseline.from_snapshot(dataclasses.replace(first, source="export.xml")),
        source="P6 Project Baseline 370 from export.xml",
    )
    row = baseline_table(update, xml, updates=["b.xer"]).iloc[0]
    assert (row["kind"], row["source"]) == ("P6 XML baseline file", "P6 Project Baseline 370 from export.xml")
    assert baseline_table(update, xml, anonymous=True, updates=["b.xer"]).loc[0, "source"] == ""
    # the app marks a fallback by its kind (analysis.baseline.KIND_FALLBACK), as baselines.py sets it
    fallback = dataclasses.replace(Baseline.planned(update), source="fallback (planned dates)", kind="fallback")
    assert baseline_table(update, fallback).loc[0, "kind"] == "fallback, planned dates (target_*)"


def test_pv_labor_check_states_its_basis_and_population():
    """Block 9: baseline B and D (40 h each), the update holds B only: PV over 1 of 2 baseline activities,
    1 deleted, on the default EV basis."""
    from xerscope.analysis import Baseline
    from xerscope.analysis.evm import pv_labor_check

    baseline = Baseline.from_snapshot(snap([todo("B", **WEEK, target_work_qty="40"), todo("D", **WEEK)]))
    totals, _ = pv_labor_check(snap([todo("B", **WEEK)], data_date=WED), baseline)
    row = totals.iloc[0]
    assert (row["ev_basis"], row["baseline_activities"], row["activities"], row["deleted_activities"]) == (
        "budgeted_planned",
        2,
        1,
        1,
    )


def test_guid_match_counts_ids_guids_and_what_the_option_links():
    """Baseline A, B, C, X, F; update A, B2 (B's GUID), X (C's GUID, X already in the baseline), N, M (no
    GUID). Linked: B -> B2. Gone and not linked: C (its GUID in the update under X, which the option
    cannot take) and F (GUID absent from the update)."""
    from xerkit import snap, todo

    from xerscope.analysis import Baseline
    from xerscope.app.diagnostic import guid_match_table

    baseline = Baseline.from_snapshot(
        snap(
            [
                todo("A", guid="g1"),
                todo("B", guid="g2"),
                todo("C", guid="g3"),
                todo("X", guid="gx"),
                todo("F", guid="gf"),
            ]
        )
    )
    update = snap([todo("A", guid="g1"), todo("B2", guid="g2"), todo("X", guid="g3"), todo("N", guid="g9"), todo("M")])
    (row,) = guid_match_table(update, baseline, None).to_dict("records")
    assert row == {
        "against": "baseline",
        "tasks": 5,
        "tasks_against": 5,
        "guids_blank": 1,
        "guids_repeated": 0,
        "guids_shared": 3,
        "ids_in_both": 2,
        "ids_gone": 3,
        "ids_new": 3,
        "renumbered": 1,
        "gone_guid_in_update": 1,
        "gone_guid_absent": 1,
    }
    previous = snap([todo("A", guid="g1")])
    assert guid_match_table(update, None, previous)["against"].tolist() == ["previous update"]
    assert guid_match_table(update, None, None).empty


def test_expected_finish_forms_count_the_unfinished_activities_by_what_the_rules_key_on():
    """Data date Monday 2 March 2026 08:00, calendar Mon-Fri 8 h. A: Mandatory Finish Fri 6 March 17:00,
    expected finish Tue 10 March 17:00 (after the date), finish-to-finish from P. M: finish milestone,
    expected finish Saturday 7 March 17:00 (off working time). B and C: expected finish Wed 4 March
    17:00, no constraint; B's stored early dates are the recalculated ones (Mon 08:00 to Wed 17:00), C
    keeps another stored finish. D is complete: not counted. E: Mandatory Finish Fri 6 March 17:00 and
    expected finish the same instant (not after the date). F: expected finish Wed 4 March 17:00, start-to-finish
    from P. No Activity ID and no date in the table."""
    expected = {"expect_end_date": "2026-03-04 17:00", "total_float_hr_cnt": ""}
    tasks = [
        todo("P"),
        todo("A", cstr_type="CS_MANDFIN", cstr_date="2026-03-06 17:00", expect_end_date="2026-03-10 17:00"),
        todo("M", task_type="TT_FinMile", expect_end_date="2026-03-07 17:00"),
        todo("B", **expected, early_start_date="2026-03-02 08:00", early_end_date="2026-03-04 17:00"),
        todo("C", **expected),
        done("D", expect_end_date="2026-03-04 17:00"),
        todo("E", cstr_type="CS_MANDFIN", cstr_date="2026-03-06 17:00", expect_end_date="2026-03-06 17:00"),
        todo("F", expect_end_date="2026-03-04 17:00"),
    ]
    s = snap(
        tasks, [("P", "A", "FF", 0), ("P", "M", "FS", 0), ("P", "F", "SF", 0)], sched={"sched_use_expect_end_flag": "Y"}
    )
    forms = expected_finish_forms(s)
    assert list(forms.columns) == [
        "status", "type", "constraint", "after_constraint_date", "off_working_time", "ff_sf_predecessor",
        "tasks", "stored_identical", "stored_different",
    ]  # fmt: skip
    rows = {
        tuple(row[:6]): tuple(row[6:]) for row in forms.astype(object).where(forms.notna(), None).to_numpy().tolist()
    }
    assert rows == {
        ("Not started", "Task dependent", "", None, False, False): (2, 1, 1),
        ("Not started", "Task dependent", "Mandatory finish", True, False, True): (1, 0, 1),
        ("Not started", "Finish milestone", "", None, True, False): (1, 0, 1),
        ("Not started", "Task dependent", "Mandatory finish", False, False, False): (1, 0, 1),
        ("Not started", "Task dependent", "", None, False, True): (1, 0, 1),
    }
    assert forms.iloc[0]["tasks"] == 2
    assert expected_finish_forms(snap([todo("P")])).empty


def test_expected_finish_forms_are_in_the_anonymous_diagnostic_without_codes_or_dates():
    """A finish milestone on a Saturday, Activity ID "ZQ7": the anonymous table counts it and shows neither
    the ID nor a year."""
    tasks = [todo("ZQ7", task_type="TT_FinMile", expect_end_date="2026-03-07 17:00")]
    frames = diagnostic_frames(snap(tasks), None, builtin_standards()["P6"], anonymous=True)
    forms = frames["02b_expected_finish_forms"]
    assert forms["tasks"].tolist() == [1]
    assert "ZQ7" not in forms.to_csv() and "2026" not in forms.to_csv()


def test_departures_keep_the_activities_where_the_recalculation_first_differs():
    """Data date Monday 2 March 2026 08:00, calendar Mon-Fri 8 h, A -> B -> C, 40 h each. Recalculated:
    A Mon 2 to Fri 6, B Mon 9 to Fri 13, C Mon 16 to Fri 20. A's stored dates are those; B stores a finish
    on Thu 12 17:00 (recalculated 8 h later) and C a finish on Thu 19: C differs too but follows B, so B
    alone is where the difference starts."""
    week = {"target_drtn_hr_cnt": "40", "remain_drtn_hr_cnt": "40", "total_float_hr_cnt": ""}
    tasks = [
        todo("A", early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00", **week),
        todo("B", early_start_date="2026-03-09 08:00", early_end_date="2026-03-12 17:00", **week),
        todo("C", early_start_date="2026-03-16 08:00", early_end_date="2026-03-19 17:00", **week),
    ]
    s = snap(tasks, [("A", "B", "FS", 0), ("B", "C", "FS", 0)])
    roots = departures(s)
    assert roots["task_code"].tolist() == ["B"]
    row = roots.iloc[0]
    assert row["early_end_date_recalc"] == pd.Timestamp("2026-03-13 17:00") and row["gap_hr"] == 8
    assert (row["status"], row["type"], row["constraint"]) == ("Not started", "Task dependent", "")
    assert not row["expected_finish"] and not row["resource_dependent"]
    forms = departure_forms(s)
    assert forms["tasks"].tolist() == [1] and "task_code" not in forms.columns
    steps = [(step.label, len(step.removed), step.left) for step in departure_funnel(s).steps]
    assert steps == [
        ("not complete", 0, 3),
        ("not level of effort", 0, 3),
        ("with a stored early date", 0, 3),
        ("a stored early date is not the recalculated one", 1, 2),  # A is reproduced
        ("no predecessor in the same case", 1, 1),  # C follows B
    ]
    reproduced = snap([todo("A", early_start_date="2026-03-02 08:00", early_end_date="2026-03-06 17:00", **week)])
    assert departures(reproduced).empty and departure_forms(reproduced).empty


def test_departure_forms_are_in_the_anonymous_diagnostic_without_codes_or_dates():
    """Activity ID "ZQ7" stores a finish the recalculation does not give: the anonymous forms table
    counts it and shows neither the ID nor a year."""
    tasks = [todo("ZQ7", target_drtn_hr_cnt="40", remain_drtn_hr_cnt="40", early_end_date="2026-03-12 17:00")]
    frames = diagnostic_frames(snap(tasks), None, builtin_standards()["P6"], anonymous=True)
    forms = frames["03c_departure_forms"]
    assert forms["tasks"].tolist() == [1]
    steps = frames["03a_departure_steps"]  # counts are whole numbers: "850", not "850.0"; blank on the start row
    assert str(steps["removed"].dtype) == "Int64" and str(steps["left"].dtype) == "Int64"
    assert steps["left"].tolist() == [1, 1, 1, 1, 1, 1] and pd.isna(steps["removed"].iloc[0])
    assert "ZQ7" not in forms.to_csv() and "2026" not in forms.to_csv()
