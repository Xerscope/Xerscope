"""The Gantt's drill-through: the chain of linked activities, floats and constraints by update.

Expected values are read off the hand-made networks below; no P6 output names a chain.
"""

from __future__ import annotations

import pandas as pd
import pytest
from xerkit import hours, snap, todo

from xerscope.analysis.activity_trail import (
    BOTH,
    DOWNSTREAM,
    UPSTREAM,
    constraint_history,
    linked_chain,
    logic_by_update,
    trail_by_update,
)
from xerscope.store import SnapshotStore

# P1 -> P2 -> X -> S1 -> S2, and Q -> X (not driving), P2 -> R (R is not upstream of X)
LINKS = pd.DataFrame(
    [
        ("P1", "P2", True),
        ("P2", "X", True),
        ("Q", "X", False),
        ("X", "S1", True),
        ("S1", "S2", False),
        ("P2", "R", True),
    ],
    columns=["pred_code", "succ_code", "driving"],
)


@pytest.mark.oracle("property")
@pytest.mark.parametrize(
    ("direction", "depth", "driving_only", "expected"),
    [
        (UPSTREAM, 1, False, ["X", "P2", "Q"]),
        (UPSTREAM, 2, False, ["X", "P2", "Q", "P1"]),  # R, P2's other successor, is not upstream of X
        (UPSTREAM, 9, True, ["X", "P2", "P1"]),  # Q -> X does not drive
        (DOWNSTREAM, 1, False, ["X", "S1"]),
        (DOWNSTREAM, 2, False, ["X", "S1", "S2"]),
        (DOWNSTREAM, 2, True, ["X", "S1"]),  # S1 -> S2 does not drive
        (BOTH, 1, False, ["X", "P2", "Q", "S1"]),
        (BOTH, 0, False, ["X"]),
    ],
)
def test_linked_chain(direction, depth, driving_only, expected):
    assert linked_chain(LINKS, "X", direction, depth, driving_only) == expected


@pytest.mark.oracle("property")
def test_a_loop_is_walked_once():
    """A -> B -> A: each activity once, whatever the depth."""
    loop = pd.DataFrame([("A", "B", True), ("B", "A", True)], columns=["pred_code", "succ_code", "driving"])
    assert linked_chain(loop, "A", BOTH, 5, False) == ["A", "B"]


def _two_updates(second_constraint: dict) -> SnapshotStore:
    """B (8 h) after A (40 h), FS 0; the second update a week later changes B's constraint."""
    preds = [("A", "B", "FS", 0)]
    first = snap([todo("A", **hours(40)), todo("B", **hours(8))], preds, data_date="2026-03-02 08:00")
    second = snap(
        [todo("A", **hours(40)), todo("B", **hours(8), **second_constraint)], preds, data_date="2026-03-09 08:00"
    )
    return SnapshotStore([first, second])


@pytest.mark.oracle("property")
def test_trail_gives_floats_and_constraints_by_update():
    """Two updates, two activities: four rows; B's primary constraint appears in the second only,
    under P6's name and its date."""
    store = _two_updates({"cstr_type": "CS_MSOA", "cstr_date": "2026-03-16 08:00"})
    trail = trail_by_update(store, ["A", "B"])
    assert len(trail) == 4
    by_update = trail[trail["task_code"] == "B"].set_index("data_date")
    assert pd.isna(by_update.loc[pd.Timestamp("2026-03-02 08:00"), "primary"])
    assert by_update.loc[pd.Timestamp("2026-03-09 08:00"), "primary"] == "Start on or after 2026-03-16 08:00"
    assert by_update["secondary"].isna().all()


@pytest.mark.oracle("property")
def test_trail_skips_an_update_without_the_activity():
    store = _two_updates({})
    assert trail_by_update(store, ["A", "missing"])["task_code"].tolist() == ["A", "A"]


@pytest.mark.oracle("property")
def test_constraint_history_lists_the_changelog_change_with_its_data_date():
    """B gains a Start On or After in the second update: one row, "primary constraint added",
    dated by the second update's data date; A has no change."""
    store = _two_updates({"cstr_type": "CS_MSOA", "cstr_date": "2026-03-16 08:00"})
    history = constraint_history(store, "B")
    assert history[["data_date", "field", "change"]].values.tolist() == [
        [pd.Timestamp("2026-03-09 08:00"), "primary constraint", "primary constraint added"]
    ]
    assert history.loc[0, "after"].startswith("CS_MSOA")
    assert constraint_history(store, "A").empty


@pytest.mark.oracle("property")
def test_constraint_history_of_a_single_update_is_empty():
    store = SnapshotStore([snap([todo("A", **hours(8))])])
    assert constraint_history(store, "A").empty


@pytest.mark.oracle("property")
def test_logic_by_update_follows_each_update_s_own_links():
    """Update 1: A -> B. Update 2 adds C -> B and puts a Start On or After on C. B's rows: itself in
    both updates, A in both, C in the second only, with its constraint; A (40 h, finishing Fri 03-06
    17:00 in update 1) drives B, which starts Mon 08:00 (tests/test_driving.py, first case)."""
    first = snap([todo("A", **hours(40)), todo("B", **hours(8))], [("A", "B", "FS", 0)], data_date="2026-03-02 08:00")
    second = snap(
        [
            todo("A", **hours(40)),
            todo("B", **hours(8)),
            todo("C", cstr_type="CS_MSOA", cstr_date="2026-03-16 08:00", **hours(8)),
        ],
        [("A", "B", "FS", 0), ("C", "B", "FS", 0)],
        data_date="2026-03-09 08:00",
    )
    logic = logic_by_update(SnapshotStore([first, second]), "B")
    rows = list(zip(logic["data_date"].dt.day, logic["role"], logic["task_code"], strict=True))
    assert rows == [
        (2, "task", "B"),
        (2, "predecessor", "A"),
        (9, "task", "B"),
        (9, "predecessor", "A"),
        (9, "predecessor", "C"),
    ]
    first_link = logic[(logic["task_code"] == "A") & (logic["data_date"].dt.day == 2)].iloc[0]
    assert first_link["link_type"] == "FS" and first_link["driving_link"] is True
    c_row = logic[logic["task_code"] == "C"].iloc[0]
    assert c_row["primary"] == "Start on or after 2026-03-16 08:00"
    assert pd.isna(logic.loc[logic["role"] == "task", "driving_link"]).all()


@pytest.mark.oracle("property")
def test_logic_by_update_skips_an_update_without_the_task():
    store = SnapshotStore([snap([todo("A", **hours(8))], data_date="2026-03-02 08:00")])
    assert logic_by_update(store, "missing").empty
