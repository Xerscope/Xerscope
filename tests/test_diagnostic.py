"""Debug page block 6: the activities behind each load warning of the file."""

import pandas as pd
from xerkit import active, done, snap, todo

from xerscope.app.diagnostic import finish_table, leveling_table


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
