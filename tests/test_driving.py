"""Driving relationships: the links that set their successor's early date.

Oracle, P6 EPPM web services, Relationship field Driving: "The flag indicating if this
relationship determines the early dates for the successor activity". P6 computes it when it
schedules and does not export it (XER data map, TASKPRED: no driving field), so no P6 output
names the driving links one by one. Two checks stand in for it:

- hand cases on calendar C8 (tests/xerkit.py: Mon-Fri 08:00-12:00 / 13:00-17:00), the
  working time between the date a link allows and the successor's date written out;
- on P6's own exports, the rule applied to the dates P6 stored gives the same links as on
  the recalculated dates: the recalculation adds no difference of its own.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from conftest import P6_CORPUS_HINT, REFERENCE_HINT, missing
from xerkit import FM, done, hours, snap, todo

from xerscope.analysis import cpm
from xerscope.xer import build_snapshot, load_snapshot
from xerscope.xer.parser import read_xer

REF = Path(__file__).parent / "reference" / "data"
HELD_OUT = REF / "p6-heldout" / "validation" / "held-out"
REFERENCE = ["p6viewer/Hotel Project.xer", "p6viewer/TERMINAL BUILDING-AIRPORT.xer", "pv/20-kW-residential-pv-p6.xer"]
HELD_OUT_SETS = [f"H{number}" for number in range(1, 31)]


def driving(tasks, preds, **kw) -> dict[tuple[str, str], bool]:
    links = cpm.schedule(snap(tasks, preds, **kw)).links
    return dict(zip(zip(links["pred_code"], links["succ_code"], strict=True), links["driving"], strict=True))


# --- hand cases --------------------------------------------------------------------------


@pytest.mark.oracle("standard")
def test_fs_over_a_weekend_drives():
    """A (40 h) from Mon 2026-03-02 08:00 finishes Fri 03-06 17:00; B FS 0 starts Mon 03-09 08:00.
    Working time between Fri 17:00 and Mon 08:00 on C8: 0 -> A->B drives."""
    links = driving([todo("A", **hours(40)), todo("B", **hours(8))], [("A", "B", "FS", 0)])
    assert links == {("A", "B"): True}


@pytest.mark.oracle("standard")
def test_only_the_latest_of_two_predecessors_drives():
    """A1 (40 h) finishes Fri 03-06 17:00, A2 (8 h) Mon 03-02 17:00; both FS 0 into B.
    B starts Mon 03-09 08:00: A1's bound reaches it, A2's is 4 working days short."""
    links = driving(
        [todo("A1", **hours(40)), todo("A2", **hours(8)), todo("B", **hours(8))],
        [("A1", "B", "FS", 0), ("A2", "B", "FS", 0)],
    )
    assert links == {("A1", "B"): True, ("A2", "B"): False}


@pytest.mark.oracle("standard")
def test_two_predecessors_finishing_together_both_drive():
    """A1 and A2 (16 h each) both finish Tue 03-03 17:00; B FS 0 starts Wed 08:00. Either
    link alone sets that date: both determine it, both drive."""
    links = driving(
        [todo("A1", **hours(16)), todo("A2", **hours(16)), todo("B", **hours(8))],
        [("A1", "B", "FS", 0), ("A2", "B", "FS", 0)],
    )
    assert links == {("A1", "B"): True, ("A2", "B"): True}


@pytest.mark.oracle("standard")
def test_one_working_hour_short_does_not_drive():
    """A finishes Fri 03-06 17:00; B held by Start On or After Mon 03-09 09:00 starts there.
    Working time between: Mon 08:00-09:00 = 1 h -> the constraint sets B, A->B does not drive."""
    links = driving(
        [todo("A", **hours(40)), todo("B", cstr_type="CS_MSOA", cstr_date="2026-03-09 09:00", **hours(8))],
        [("A", "B", "FS", 0)],
    )
    assert links == {("A", "B"): False}


@pytest.mark.oracle("standard")
def test_ff_link_drives_the_successor_finish():
    """A (40 h) finishes Fri 03-06 17:00; B (8 h) FF 0 cannot finish before: B finishes Fri 17:00
    (starts Fri 08:00), its finish is set by the link -> A->B drives."""
    links = driving([todo("A", **hours(40)), todo("B", **hours(8))], [("A", "B", "FF", 0)])
    assert links == {("A", "B"): True}


@pytest.mark.oracle("standard")
def test_a_link_a_mandatory_finish_overrides_does_not_drive():
    """A (40 h) finishes Fri 03-06 17:00; B (8 h) FF 0 under Mandatory Finish Tue 03-03 17:00
    finishes there, before the link allows: the constraint sets B's finish, A->B does not drive."""
    links = driving(
        [todo("A", **hours(40)), todo("B", cstr_type="CS_MANDFIN", cstr_date="2026-03-03 17:00", **hours(8))],
        [("A", "B", "FF", 0)],
    )
    assert links == {("A", "B"): False}


@pytest.mark.oracle("standard")
def test_ff_link_short_of_the_successor_finish_does_not_drive():
    """A (8 h) finishes Mon 03-02 17:00; B (40 h) FF 0 finishes Fri 03-06 17:00 on its own duration.
    The link allows a finish 4 working days earlier: it bounds B's finish, not its start, and
    does not drive (compared with B's start, Mon 08:00, it would)."""
    links = driving([todo("A", **hours(8)), todo("B", **hours(40))], [("A", "B", "FF", 0)])
    assert links == {("A", "B"): False}


@pytest.mark.oracle("standard")
def test_a_predecessor_finished_at_the_data_date_drives_nothing():
    """A finished Fri 02-13 17:00; data date Mon 02-16 08:00, the same working instant on C8.
    B starts at the data date, which A's link reaches, yet A is finished: Oracle (P6 help,
    Activity Network: a driving relationship's activity "does not have an Actual Finish date")."""
    links = driving([done("A"), todo("B", **hours(8))], [("A", "B", "FS", 0)], data_date="2026-02-16 08:00")
    assert links == {("A", "B"): False}


@pytest.mark.oracle("standard")
def test_a_finished_predecessor_drives_nothing():
    """A finished Fri 02-13 17:00, before the data date (Mon 03-02 08:00): B starts at the data
    date, which A's link does not reach; a finished activity's link is never driving."""
    links = driving([done("A"), todo("B", **hours(8)), todo("Z", **FM)], [("A", "B", "FS", 0), ("B", "Z", "FS", 0)])
    assert links == {("A", "B"): False, ("B", "Z"): True}


# --- P6's exports: stored dates and recalculated dates give the same links ----------------


def _links_on_stored_dates(snapshot) -> pd.Series:
    """The rule of cpm._Run.is_driving_link applied to the remaining start and early finish P6
    stored (restart / reend, else early start / finish) in place of the recalculated ones."""
    run = cpm._Run(snapshot, {}, cpm.Options.from_snapshot(snapshot), None)
    run.forward()
    run.backward()
    run.floats()
    run.level_of_effort()
    stored = snapshot.by_code
    for code in list(run.early_finish):
        if code not in stored.index or stored.at[code, "status_code"] == "TK_Complete":
            continue
        start = stored.at[code, "restart_date"]
        start = stored.at[code, "early_start_date"] if pd.isna(start) else start
        finish = stored.at[code, "reend_date"]
        finish = stored.at[code, "early_end_date"] if pd.isna(finish) else finish
        if pd.notna(start):
            run.remaining_start[code] = start
        if pd.notna(finish):
            run.early_finish[code] = finish
    return run.driving_links().set_index(["pred_code", "succ_code", "type"])["driving"]


def _assert_same_links(path: Path) -> int:
    snapshot = load_snapshot(path)
    recalculated = cpm.schedule(snapshot).links.set_index(["pred_code", "succ_code", "type"])["driving"]
    on_stored = _links_on_stored_dates(snapshot)
    different = recalculated[recalculated != on_stored]
    assert different.empty, f"{path.name}: {different.head(10).to_dict()}"
    return int(recalculated.sum())


@pytest.mark.oracle("p6")
@pytest.mark.parametrize("name", REFERENCE)
def test_reference_files_drive_the_same_on_stored_and_recalculated_dates(name):
    """Hotel, Terminal, PV: every relationship drives on the recalculated dates exactly when it
    drives on the dates P6 stored (measured 2026-11-25: 7,701 links, all equal)."""
    if not (REF / name).exists():
        missing("reference", REFERENCE_HINT)
    assert _assert_same_links(REF / name) > 0


@pytest.mark.oracle("p6")
@pytest.mark.parametrize("name", HELD_OUT_SETS)
def test_p6_corpus_drives_the_same_on_stored_and_recalculated_dates(name):
    """P6 23.12 held-out corpus: same check on every case of the set (measured 2026-11-25 on the
    30 sets: 12,024 links, all equal)."""
    if not HELD_OUT.is_dir():
        missing("p6-corpus", P6_CORPUS_HINT)
    cases = sorted((HELD_OUT / name / "cases").glob("*.xer"))
    assert cases
    for path in cases:
        _assert_same_links(path)


# --- P6's own relationship date: TASKPRED.aref ------------------------------------------------
#
# P6 Professional writes aref on every relationship of the Hotel, Terminal, PV and xereditor
# exports (the P6 23.12 corpus leaves it blank). Oracle documents it for links to projects
# outside the database only (web services, Relationship.Aref: "Adjusted Relationship Early
# Finish"), yet on these files it holds, for every link, the start the link allows its
# successor, written as P6 writes a finish (16:00 the evening before 08:00). A link drives
# exactly when that start is the successor's remaining start in working time: the one
# relationship-level value P6 exports that the driving rule can be checked against.


def _aref_drives(path: Path) -> tuple[pd.Series, pd.Series]:
    """Per open link (pred_code, succ_code, type): the recalculated driving flag, and whether P6's
    aref reaches the successor's remaining start on the successor's calendar."""
    raw = read_xer(path)
    snapshot = build_snapshot(raw)
    recalculated = cpm.schedule(snapshot)
    tasks, frame = snapshot.by_code, recalculated.frame
    code_of = dict(zip(snapshot.activities["task_id"], snapshot.activities["task_code"], strict=True))
    axes = cpm._Axes(snapshot, *cpm._date_range(snapshot))
    stored = {}
    for row in raw.tables["TASKPRED"].itertuples():
        predecessor, successor = code_of.get(row.pred_task_id), code_of.get(row.task_id)
        if predecessor is None or successor is None or not row.aref:
            continue
        if tasks.at[predecessor, "is_complete"] or tasks.at[successor, "is_complete"]:
            continue
        start = frame.at[successor, "remaining_start"]
        start = frame.at[successor, "es"] if pd.isna(start) else start
        axis = axes.of(tasks.at[successor, "clndr_id"])
        stored[(predecessor, successor, row.pred_type.removeprefix("PR_"))] = axis.work(
            pd.Timestamp(row.aref)
        ) >= axis.work(start)
    p6 = pd.Series(stored, dtype=bool)
    links = recalculated.links.set_index(["pred_code", "succ_code", "type"])["driving"]
    p6 = p6[p6.index.isin(links.index)]  # a level-of-effort's links place it; they are not in Schedule.links
    return links.reindex(p6.index), p6


@pytest.mark.oracle("p6")
@pytest.mark.parametrize("name", [*REFERENCE, "xereditor/sample.xer"])
def test_driving_links_are_those_p6s_aref_says_set_the_successor_start(name):
    """Measured 2026-11-25: 7,742 open links (Hotel 7,586, Terminal 84, PV 31, xereditor 41), 4,929
    driving, every one equal; the 7 links into As Late As Possible work of Hotel included. The links
    of the xereditor sample's level-of-effort activities are not in Schedule.links (they place the
    LOE): P6's aref says each reaches its successor."""
    if not (REF / name).exists():
        missing("reference", REFERENCE_HINT)
    recalculated, p6 = _aref_drives(REF / name)
    assert len(p6) > 0
    different = p6[recalculated != p6]
    assert different.empty, different.head(10).to_dict()
