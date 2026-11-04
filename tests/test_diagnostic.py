"""Debug page block 6: the activities behind each load warning of the file."""

import pandas as pd
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
