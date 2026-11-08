"""The activity panel under the Gantt (app/task_panel.py): only an Activity ID crosses from the
browser, every value is read from the loaded schedule, schedule text never becomes markup."""

import dataclasses

import pandas as pd
import pytest

from xerscope.app import task_panel


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a:C3020", "C3020"),
        ("w:7003", None),  # a WBS row opens or closes, it picks nothing
        ("a:", None),
        ("C3020", None),  # no row prefix
        (None, None),
        (42, None),
        (["a:C3020"], None),
        ("a:" + "x" * 300, None),  # longer than any Activity ID: a forged value
    ],
)
def test_only_an_activity_row_id_gives_an_activity_id(value, expected):
    assert task_panel.task_from_row_id(value) == expected


def _values(store, code):
    snapshot = store.latest
    task = task_panel.task_rows(snapshot, code).iloc[0]
    return snapshot, task, dict(item for _, items in task_panel.card_sections(snapshot, task) for item in items)


def test_card_shows_the_snapshot_values_and_changes_nothing(store):
    snapshot = store.latest
    code = snapshot.activities["task_code"].iloc[0]
    tasks_before, links_before = snapshot.tasks.copy(), snapshot.relationships.copy()
    _, task, values = _values(store, code)
    row = snapshot.activities.set_index("task_code").loc[code]
    assert values["Task ID"] == code and values["Task name"] == row["task_name"]
    assert values["Total float"] == ("–" if pd.isna(row["total_float_d"]) else f"{row['total_float_d']:.1f} wd")
    assert values["Remaining duration"] == ("–" if pd.isna(row["remaining_d"]) else f"{row['remaining_d']:.1f} wd")
    task_panel.resources(snapshot, code)
    task_panel.logic(snapshot, code)
    pd.testing.assert_frame_equal(snapshot.tasks, tasks_before)  # cached frames are read, never written
    pd.testing.assert_frame_equal(snapshot.relationships, links_before)


def test_logic_lists_both_sides_of_each_link(store):
    snapshot = store.latest
    link = snapshot.relationships.iloc[0]
    as_successor = task_panel.logic(snapshot, link["succ_code"])
    as_predecessor = task_panel.logic(snapshot, link["pred_code"])
    assert link["pred_code"] in set(as_successor.loc[as_successor["relationship"] == "Predecessor", "task_code"])
    assert link["succ_code"] in set(as_predecessor.loc[as_predecessor["relationship"] == "Successor", "task_code"])
    expected = (snapshot.relationships["succ_code"] == link["succ_code"]).sum()
    assert (as_successor["relationship"] == "Predecessor").sum() == expected


def test_resources_are_the_activity_assignments(store):
    snapshot = store.latest
    assigned = snapshot.assignments
    code = assigned["task_code"].iloc[0]
    rows = task_panel.resources(snapshot, code)
    assert len(rows) == (assigned["task_code"] == code).sum()
    assert rows["budgeted units"].sum() == pytest.approx(
        assigned.loc[assigned["task_code"] == code, "target_qty"].sum()
    )


def test_schedule_text_is_escaped_in_the_card(store):
    snapshot = store.latest
    task = task_panel.task_rows(snapshot, snapshot.activities["task_code"].iloc[0]).iloc[0].copy()
    task["task_name"] = '<img src=x onerror="alert(1)">'
    markup = task_panel.card_html(task_panel.card_sections(snapshot, task))
    assert "<img" not in markup and "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in markup


def test_a_repeated_activity_id_draws_no_card(store):
    snapshot = store.latest
    code = snapshot.activities["task_code"].iloc[0]
    doubled = pd.concat([snapshot.tasks, snapshot.tasks[snapshot.tasks["task_code"] == code]])
    copy = dataclasses.replace(snapshot, tasks=doubled)
    assert len(task_panel.task_rows(copy, code)) == 2  # show_card warns instead of picking one


def test_hard_constraint_row_names_the_dcma_set_it_reads():
    """model.HARD_CONSTRAINTS (DCMA-05) holds Start on or before; P6-02 (113176: Mandatory Start, Start On,
    Mandatory Finish, Finish On) does not. A task constrained Start on or before reads Yes, under a label
    that names the DCMA set, and P6-02 does not count it."""
    from rulekit import STANDARDS, counts, run
    from xerkit import snap, todo

    s = snap([todo("A", cstr_type="CS_MSOB", cstr_date="2026-03-10 08:00")])
    task = task_panel.task_rows(s, "A").iloc[0]
    values = dict(item for _, items in task_panel.card_sections(s, task) for item in items)
    assert values["Hard constraint (DCMA-05 set)"] == "Yes"
    assert "Hard constraint" not in values
    assert counts(run(STANDARDS["P6"], "P6-02", s)) == (0, 1)
