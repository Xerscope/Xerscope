"""The activity panel under the Gantt (app/task_panel.py): only an Activity ID crosses from the
browser, every value is read from the loaded schedule, schedule text never becomes markup."""

import dataclasses

import pandas as pd
import pytest

from xerscope.app import activity_details, task_panel


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
    task = activity_details.task_rows(snapshot, code).iloc[0]
    return snapshot, task, dict(item for _, items in activity_details.card_sections(snapshot, task) for item in items)


def test_card_shows_the_snapshot_values_and_changes_nothing(store):
    snapshot = store.latest
    code = snapshot.activities["task_code"].iloc[0]
    tasks_before, links_before = snapshot.tasks.copy(), snapshot.relationships.copy()
    _, task, values = _values(store, code)
    row = snapshot.activities.set_index("task_code").loc[code]
    assert values["Task ID"] == code and values["Task name"] == row["task_name"]
    assert values["Total float"] == ("–" if pd.isna(row["total_float_d"]) else f"{row['total_float_d']:.1f} wd")
    assert values["Remaining duration"] == ("–" if pd.isna(row["remaining_d"]) else f"{row['remaining_d']:.1f} wd")
    activity_details.resources(snapshot, code)
    activity_details.logic(snapshot, code)
    pd.testing.assert_frame_equal(snapshot.tasks, tasks_before)  # cached frames are read, never written
    pd.testing.assert_frame_equal(snapshot.relationships, links_before)


def test_logic_lists_both_sides_of_each_link(store):
    snapshot = store.latest
    link = snapshot.relationships.iloc[0]
    as_successor = activity_details.logic(snapshot, link["succ_code"])
    as_predecessor = activity_details.logic(snapshot, link["pred_code"])
    assert link["pred_code"] in set(as_successor.loc[as_successor["relationship"] == "Predecessor", "task_code"])
    assert link["succ_code"] in set(as_predecessor.loc[as_predecessor["relationship"] == "Successor", "task_code"])
    expected = (snapshot.relationships["succ_code"] == link["succ_code"]).sum()
    assert (as_successor["relationship"] == "Predecessor").sum() == expected


def test_resources_are_the_activity_assignments(store):
    snapshot = store.latest
    assigned = snapshot.assignments
    code = assigned["task_code"].iloc[0]
    rows = activity_details.resources(snapshot, code)
    assert len(rows) == (assigned["task_code"] == code).sum()
    assert rows["budgeted units"].sum() == pytest.approx(
        assigned.loc[assigned["task_code"] == code, "target_qty"].sum()
    )


def test_schedule_text_is_escaped_in_the_card(store):
    snapshot = store.latest
    task = activity_details.task_rows(snapshot, snapshot.activities["task_code"].iloc[0]).iloc[0].copy()
    task["task_name"] = '<img src=x onerror="alert(1)">'
    markup = activity_details.card_html(activity_details.card_sections(snapshot, task))
    assert "<img" not in markup and "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in markup


def test_a_repeated_activity_id_draws_no_card(store):
    snapshot = store.latest
    code = snapshot.activities["task_code"].iloc[0]
    doubled = pd.concat([snapshot.tasks, snapshot.tasks[snapshot.tasks["task_code"] == code]])
    copy = dataclasses.replace(snapshot, tasks=doubled)
    assert len(activity_details.task_rows(copy, code)) == 2  # show_card warns instead of picking one


def test_hard_constraint_row_names_the_dcma_set_it_reads():
    """model.HARD_CONSTRAINTS (DCMA-05) holds Start on or before; P6-02 (113176: Mandatory Start, Start On,
    Mandatory Finish, Finish On) does not. A task constrained Start on or before reads Yes, under a label
    that names the DCMA set, and P6-02 does not count it."""
    from rulekit import STANDARDS, counts, run
    from xerkit import snap, todo

    s = snap([todo("A", cstr_type="CS_MSOB", cstr_date="2026-03-10 08:00")])
    task = activity_details.task_rows(s, "A").iloc[0]
    values = dict(item for _, items in activity_details.card_sections(s, task) for item in items)
    assert values["Hard constraint (DCMA-05 set)"] == "Yes"
    assert "Hard constraint" not in values
    assert counts(run(STANDARDS["P6"], "P6-02", s)) == (0, 1)


@pytest.mark.oracle("characterization")
def test_card_reads_each_float_and_date_from_its_own_column(store):
    """E1030 of the demo series has a total float of -9.0 wd and a free float of 0.0 wd, so a card that
    shows one column under the other label reads wrong. Each row is the snapshot column named in the
    P6 Activity Details layout (activity_details.card_sections), formatted by hand."""
    snapshot = store.latest
    _, task, values = _values(store, "E1030")
    assert values["Total float"] == "-9.0 wd"
    assert values["Free float"] == "0.0 wd"
    row = snapshot.activities.set_index("task_code").loc["E1030"]
    assert values["Original duration"] == f"{row['original_d']:.1f} wd" == "25.0 wd"
    assert values["% complete"] == f"{row['pct_complete']:.1f} %" == "92.0 %"
    assert values["Critical"] == "Yes" and values["Longest path"] == "No"
    assert values["Actual start"] == activity_details._when(pd.Timestamp("2026-09-16 08:00"))
    assert values["Early start"] == activity_details._when(pd.Timestamp("2026-10-19 08:00"))
    assert values["Late start"] == activity_details._when(pd.Timestamp("2026-10-10 08:00"))
    assert values["Planned start"] == activity_details._when(pd.Timestamp("2026-09-15 08:00"))
    assert values["Early finish"] == activity_details._when(pd.Timestamp("2026-10-21 16:00"))
    assert values["Late finish"] == activity_details._when(pd.Timestamp("2026-10-12 16:00"))
    assert values["Planned finish"] == activity_details._when(pd.Timestamp("2026-10-09 16:00"))
    assert values["Actual finish"] == "–"  # E1030 is under way


@pytest.mark.oracle("characterization")
def test_logic_gives_the_type_and_lag_of_each_link(store):
    """The sample's TASKPRED links E1010 -> E1040 Start to Start with 5 wd of lag and E1040 -> E1050
    Finish to Start with -3 wd; each side of a link shows its type and lag."""
    snapshot = store.latest
    links = snapshot.relationships.set_index(["pred_code", "succ_code"])
    assert (links.loc[("E1010", "E1040"), "type"], links.loc[("E1010", "E1040"), "lag_d"]) == ("SS", 5.0)
    assert (links.loc[("E1040", "E1050"), "type"], links.loc[("E1040", "E1050"), "lag_d"]) == ("FS", -3.0)
    successors = activity_details.logic(snapshot, "E1010").query("relationship == 'Successor'").set_index("task_code")
    assert successors.loc["E1040", "link type"] == "SS"
    assert successors.loc["E1040", "lag_d"] == pytest.approx(5.0)
    predecessors = (
        activity_details.logic(snapshot, "E1050").query("relationship == 'Predecessor'").set_index("task_code")
    )
    assert predecessors.loc["E1040", "link type"] == "FS"
    assert predecessors.loc["E1040", "lag_d"] == pytest.approx(-3.0)
    assert not predecessors.loc["E1040", "external"]


@pytest.mark.oracle("characterization")
def test_resources_give_actual_and_remaining_units_apart(store):
    """E1010 has one assignment (Site crew, CREW) of the sample: 240 units budgeted, 256 actual,
    0 remaining (TASKRSRC target_qty, act_qty, remain_qty)."""
    rows = activity_details.resources(store.latest, "E1010")
    assert rows["budgeted units"].tolist() == [240]
    assert rows["actual units"].tolist() == [256.0]
    assert rows["remaining units"].tolist() == [0]


@pytest.mark.oracle("property")
def test_a_repeated_activity_id_shows_the_warning_and_no_card(store, monkeypatch):
    """show_card refuses a Task ID on two rows: one warning naming the count, no card, no sections."""
    snapshot = store.latest
    code = snapshot.activities["task_code"].iloc[0]
    doubled = pd.concat([snapshot.tasks, snapshot.tasks[snapshot.tasks["task_code"] == code]])
    copy = dataclasses.replace(snapshot, tasks=doubled)
    warnings, cards, sections = [], [], []
    monkeypatch.setattr(activity_details.st, "warning", lambda text, **_: warnings.append(text))
    monkeypatch.setattr(activity_details.st, "html", lambda markup, **_: cards.append(markup))
    monkeypatch.setattr(activity_details.ui, "section", lambda title, **_: sections.append(title))
    activity_details.show_card(copy, code)
    assert len(warnings) == 1 and "is on 2 rows of this update: no card is drawn" in warnings[0]
    assert cards == [] and sections == []
