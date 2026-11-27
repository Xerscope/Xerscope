"""Longest path of each update and what entered or left it (analysis/longest_path.py): hand cases.

Source: AACE RP 29R-03 (rev. April 25, 2011) 3.4.E.9 (the longest path identifies the controlling
chain) and SVP 2.3.B.6 (the changes that change the longest path, update by update).
"""

import pandas as pd
import pytest
from xerkit import active, done, snap, todo

from xerscope.analysis.longest_path import (
    DELETED,
    ENTERED,
    FINISHED,
    P6_FLAG,
    RECALCULATED,
    STAYED,
    SWITCHED,
    UNKNOWN,
    change_counts,
    longest_path,
    longest_path_funnel,
    path_changes,
    path_churn,
    path_commitments,
)
from xerscope.store import SnapshotStore

ON_PATH = {"driving_path_flag": "Y"}
WEEK_LATER = "2026-03-09 08:00"


@pytest.mark.oracle("p6")
def test_the_longest_path_is_the_one_p6_flagged_open_work_only():
    """P6's Longest Path column (TASK.driving_path_flag): A, B and D carry it; D is complete and no
    longer drives anything, so the path of the update is A and B."""
    snapshot = snap([todo("A", **ON_PATH), todo("B", **ON_PATH), todo("C"), done("D", **ON_PATH)])
    assert longest_path(snapshot) == (["A", "B"], P6_FLAG)


@pytest.mark.oracle("standard")
def test_a_file_without_a_flagged_activity_takes_the_recalculated_path():
    """No activity flagged: A (80 h) then B (80 h) is the recalculated longest path, C (80 h, alone)
    ends before it and is not on it."""
    snapshot = snap([todo("A"), todo("B"), todo("C")], [("A", "B", "FS", 0)])
    assert longest_path(snapshot) == (["A", "B"], RECALCULATED)


@pytest.mark.oracle("standard")
def test_each_activity_of_either_path_gets_one_change_the_switches_first():
    """Earlier path: A, B, C, GONE. Later: A stays; B is finished; C is still open and off the path
    (the path switched away from it); GONE is deleted; N entered. Rows in the order a reader wants:
    still open first, then entered, finished, deleted, stayed."""
    earlier = snap([todo(code, **ON_PATH) for code in ("A", "B", "C", "GONE")] + [todo("N")])
    later = snap(
        [todo("A", **ON_PATH), done("B", **ON_PATH), todo("C", total_float_hr_cnt="40"), todo("N", **ON_PATH)],
        data_date=WEEK_LATER,
    )
    changes = path_changes(earlier, later)
    assert changes[["change", "task_code"]].astype(str).to_numpy().tolist() == [
        [SWITCHED, "C"],
        [ENTERED, "N"],
        [FINISHED, "B"],
        [DELETED, "GONE"],
        [STAYED, "A"],
    ]
    switched = changes.set_index("task_code").loc["C"]
    assert (switched["float_before_d"], switched["total_float_d"]) == (0.0, 5.0)  # 40 h on 8 h days
    assert pd.isna(changes.set_index("task_code").loc["GONE", "total_float_d"])  # deleted: no float after
    assert {"type", "status", "start", "finish"} <= set(changes.columns)  # the standard activity columns
    assert change_counts(changes) == {SWITCHED: 1, ENTERED: 1, FINISHED: 1, DELETED: 1, STAYED: 1}


@pytest.mark.oracle("standard")
def test_path_churn_counts_each_update_against_the_one_before():
    """Three updates. Second: of A, B, C on the first path, A stays, B is finished, C left while open, N
    entered: 2 on the path, stability 1 / (1 + 1) = 0.5 (finished work could not stay). Third: unchanged,
    A and N stay: stability 1.0."""
    first = snap([todo(code, **ON_PATH) for code in ("A", "B", "C")] + [todo("N")])
    second_tasks = [todo("A", **ON_PATH), done("B", **ON_PATH), todo("C"), todo("N", **ON_PATH)]
    second = snap(second_tasks, data_date=WEEK_LATER)
    third = snap(second_tasks, data_date="2026-03-16 08:00")
    churn = path_churn(SnapshotStore([first, second, third]))
    assert churn["data_date"].tolist() == [pd.Timestamp(WEEK_LATER), pd.Timestamp("2026-03-16 08:00")]
    row = churn.iloc[0]
    assert (row["on_path"], row["stayed"], row["entered"], row["left_finished"], row["left_open"]) == (2, 1, 1, 1, 1)
    assert churn["stability"].tolist() == [0.5, 1.0]
    assert churn["path_source"].tolist() == [P6_FLAG, P6_FLAG]


@pytest.mark.oracle("standard")
def test_the_weeks_commitments_on_the_path_are_counted_apart_from_the_ppc():
    """Status dates Mon 2 and Mon 16 March 2026. A, B and C are due to start Mon 2 and finish Fri 13
    March: two commitments each, six in all. A (on the path) and C (off it) are done in time; B (on
    the path) has not started. PPC of the week: 4 kept of 6, 66.7 %. On the path of the earlier
    update, A and B: 2 kept of 4, 50 %. PPC counts every commitment alike (progress.committed); the
    path's are those a miss of which moves the finish."""
    in_time = {"act_start_date": "2026-03-02 08:00", "act_end_date": "2026-03-13 17:00"}
    earlier = snap([todo("A", **ON_PATH), todo("B", **ON_PATH), todo("C")])
    later = snap(
        [done("A", **in_time, **ON_PATH), todo("B", **ON_PATH), done("C", **in_time)], data_date="2026-03-16 08:00"
    )
    on_path = path_commitments(earlier, later)
    assert sorted(zip(on_path["task_code"], on_path["commitment"], on_path["kept"], strict=True)) == [
        ("A", "Finish", True),
        ("A", "Start", True),
        ("B", "Finish", False),
        ("B", "Start", False),
    ]
    row = path_churn(SnapshotStore([earlier, later])).iloc[0]
    assert (row["path_committed"], row["path_kept"], row["ppc_path"]) == (4, 2, 50.0)
    assert round(row["ppc_week"], 1) == 66.7


@pytest.mark.oracle("standard")
def test_a_week_between_a_flagged_and_an_unflagged_file_names_both_sources():
    """The earlier file flags its path, the later one flags nothing: the week compares two definitions
    of the path, and the row says so."""
    flagged = snap([todo("A", **ON_PATH)])
    unflagged = snap([active("A")], data_date=WEEK_LATER)
    churn = path_churn(SnapshotStore([flagged, unflagged]))
    assert churn["path_source"].tolist() == [f"{P6_FLAG} / {RECALCULATED}"]


@pytest.mark.oracle("standard")
def test_the_population_of_the_path_is_a_funnel_whose_steps_can_be_read():
    """Four activities: one complete (removed by "not complete"), one open off the path (removed by
    the path step), two left. The steps are those of analysis.populations, as for a check."""
    snapshot = snap([todo("A", **ON_PATH), todo("B", **ON_PATH), todo("C"), done("D", **ON_PATH)])
    funnel, source = longest_path_funnel(snapshot)
    steps = [(step.label, len(step.removed), step.left) for step in funnel.steps]
    assert steps == [("not complete", 1, 3), (f"on the longest path ({P6_FLAG})", 1, 2)]
    assert funnel.start == 4 and source == P6_FLAG


@pytest.mark.oracle("property")
def test_the_same_file_twice_changes_nothing_on_the_path():
    """Metamorphic: an update against itself, every activity of the path stays."""
    snapshot = snap([todo("A", **ON_PATH), todo("B", **ON_PATH), todo("C")])
    assert change_counts(path_changes(snapshot, snapshot)) == {
        SWITCHED: 0,
        ENTERED: 0,
        FINISHED: 0,
        DELETED: 0,
        STAYED: 2,
    }


@pytest.mark.oracle("standard")
def test_a_file_that_flags_nothing_and_cannot_be_scheduled_has_no_known_path():
    """A -> B -> A is a loop of the logic: the recalculation refuses it (cpm.CycleError), and no
    activity is flagged, so the update has no path and says its source is unknown (docstring of
    longest_path: UNKNOWN with no code)."""
    snapshot = snap([todo("A"), todo("B")], [("A", "B", "FS", 0), ("B", "A", "FS", 0)])
    assert longest_path(snapshot) == ([], UNKNOWN)
    assert UNKNOWN == "none"


@pytest.mark.oracle("standard")
def test_a_deleted_activity_of_the_path_is_neither_a_kept_nor_a_missed_commitment():
    """As the commitments test above, plus D: on the path, due Mon 2 to Fri 13 March, absent from the
    later update. A deleted activity is a scope change, not a miss (longest_path.path_commitments;
    progress.committed): the path's rows are still A and B, 2 kept of 4, and the week's PPC is still
    4 kept of 6; counted, D would make 2 of 6 and 4 of 8."""
    in_time = {"act_start_date": "2026-03-02 08:00", "act_end_date": "2026-03-13 17:00"}
    earlier = snap([todo("A", **ON_PATH), todo("B", **ON_PATH), todo("C"), todo("D", **ON_PATH)])
    later = snap(
        [done("A", **in_time, **ON_PATH), todo("B", **ON_PATH), done("C", **in_time)], data_date="2026-03-16 08:00"
    )
    assert sorted(path_commitments(earlier, later)["task_code"].unique()) == ["A", "B"]
    row = path_churn(SnapshotStore([earlier, later])).iloc[0]
    assert (row["path_committed"], row["path_kept"], row["ppc_path"]) == (4, 2, 50.0)
    assert round(row["ppc_week"], 1) == 66.7
