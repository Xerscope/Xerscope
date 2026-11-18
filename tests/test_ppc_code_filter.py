"""PPC restricted to an activity code (CodeFilter), checked by hand on tiny XER series.

Definition (docstring of ``progress.committed``, docs/formulas.md section 4): W-1's commitments
for the week to W's data date are a start (not started in W-1, planned start on or before W's
data date) and a finish (not complete in W-1, planned finish on or before it); kept: the actual
start (finish) on or before W's data date. PPC Start = starts kept / starts committed, PPC Finish
= finishes kept / finishes committed, PPC W/W-1 = kept / committed.

The filter keeps the commitments of the tasks assigned, IN W-1'S FILE, to the chosen values of the
code type named ``type_name`` (the P6 name, not the label the file gives it). The rule is a design
decision, not a source: the expected values are counted by hand from the definition above.
Markers: ``characterization`` for the counts (no kind fits "hand count of a design decision"),
``property`` for the partition (holds on any series).

Data dates: update 0 Mon 2026-03-02 08:00, update 1 Mon 03-09, update 2 Mon 03-16. Calendar C8.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest
from xerkit import _table, active, done, snap, todo, xer_text

from xerscope.analysis import progress
from xerscope.analysis.task_filters import CodeFilter
from xerscope.store import SnapshotStore
from xerscope.xer import Snapshot, build_snapshot, parse_text

DD0, DD1, DD2 = "2026-03-02 08:00", "2026-03-09 08:00", "2026-03-16 08:00"
CIV = "CIV · Discipline CIV"  # the label of the value CIV: "<path> · <description>"
MEC = "MEC · Discipline MEC"
COUNTS = ("starts_committed", "starts_kept", "finishes_committed", "finishes_kept", "committed", "kept")
PPC = ("ppc_start", "ppc_finish", "ppc_week")


def plan(start: str, end: str) -> dict:
    """Planned dates in March 2026: start at 08:00 on day ``start``, finish at 17:00 on ``end``."""
    return dict(early_start_date=f"2026-03-{start} 08:00", early_end_date=f"2026-03-{end} 17:00")


def actual(start: str, end: str) -> dict:
    return dict(act_start_date=f"2026-03-{start} 08:00", act_end_date=f"2026-03-{end} 17:00")


def discipline_snap(tasks: list[dict], assigned: dict[str, str], data_date: str) -> Snapshot:
    """``tasks`` with one code type "Discipline", each task of ``assigned`` given its value."""
    codes = [(task, "Discipline", value) for task, value in assigned.items()]
    return snap(tasks, codes=codes, data_date=data_date)


def two_types_snap(
    tasks: list[dict], global_values: dict[str, str], project_values: dict[str, str], dd: str
) -> Snapshot:
    """A file with two code types both named "Discipline": a global one and a project one.

    Each of ``global_values`` / ``project_values`` gives its tasks a value (short name); the value
    description is "Global <value>" / "Project <value>". The labels are the file's: P6 does not
    make a type name unique, so xerscope tells the two apart ("Discipline (global)", ...).
    """
    ids = {t["task_code"]: str(i) for i, t in enumerate(tasks, start=1)}
    types, values, links = [], [], []
    for type_id, scope, assigned in (("701", "Global", global_values), ("702", "Project", project_values)):
        types.append(
            {
                "actv_code_type_id": type_id,
                "seq_num": str(len(types) + 1),
                "actv_code_type": "Discipline",
                "proj_id": "1" if scope == "Project" else "",
                "actv_code_type_scope": f"AS_{scope}",
            }
        )
        value_ids = {}
        for short in sorted(set(assigned.values())):
            value_ids[short] = str(7000 + len(values) + 1)
            values.append(
                {
                    "actv_code_id": value_ids[short],
                    "parent_actv_code_id": "",
                    "actv_code_type_id": type_id,
                    "actv_code_name": f"{scope} {short}",
                    "short_name": short,
                    "seq_num": str(len(values) + 1),
                }
            )
        for task, short in assigned.items():
            links.append(
                {"task_id": ids[task], "actv_code_type_id": type_id, "actv_code_id": value_ids[short], "proj_id": "1"}
            )
    text = xer_text(tasks, data_date=dd)
    tables = _table("ACTVTYPE", types) + _table("ACTVCODE", values) + _table("TASKACTV", links)
    assert text.endswith("%E\n")
    return build_snapshot(parse_text(text[: -len("%E\n")] + "\n".join(tables) + "\n%E\n", source="test.xer"))


def row(table: pd.DataFrame, update: int) -> pd.Series:
    """The ppc_series row of the week that ends at update ``update``."""
    return table.loc[table["snapshot_idx"] == update].iloc[0]


def counts(week: pd.Series) -> tuple[int, ...]:
    return tuple(int(week[column]) for column in COUNTS)


def series(store: SnapshotStore, code_filter: CodeFilter | None) -> pd.DataFrame:
    return progress.ppc_series(store, code_filter=code_filter)


def discipline_store() -> SnapshotStore:
    """Four tasks, Discipline CIV (A, B) and MEC (C, D), three updates (DD 03-02, 03-09, 03-16).

    Update 0: A not started 03-03 -> 03-06; B 03-04 -> 03-20; C 03-05 -> 03-06; D 03-12 -> 03-13.
    Update 1: A complete 03-03 / 03-06; B started 03-04, finish 03-13; C not started 03-10 -> 03-13;
    D not started 03-12 -> 03-13. Update 2: A complete; B complete 03-04 / 03-13; C complete
    03-10 / 03-13; D started 03-12, finish 03-20.
    """
    assigned = {"A": "CIV", "B": "CIV", "C": "MEC", "D": "MEC"}
    update0 = [todo("A", **plan("03", "06")), todo("B", **plan("04", "20")), todo("C", **plan("05", "06"))]
    update0.append(todo("D", **plan("12", "13")))
    update1 = [
        done("A", **actual("03", "06")),
        active("B", act_start_date="2026-03-04 08:00", early_end_date="2026-03-13 17:00"),
        todo("C", **plan("10", "13")),
        todo("D", **plan("12", "13")),
    ]
    update2 = [
        done("A", **actual("03", "06")),
        done("B", **actual("04", "13")),
        done("C", **actual("10", "13")),
        active("D", act_start_date="2026-03-12 08:00", early_end_date="2026-03-20 17:00"),
    ]
    return SnapshotStore(
        [
            discipline_snap(update0, assigned, DD0),
            discipline_snap(update1, assigned, DD1),
            discipline_snap(update2, assigned, DD2),
        ]
    )


# (1) no filter: nothing changes


@pytest.mark.oracle("characterization")
def test_no_code_filter_is_the_unfiltered_series():
    """Without a filter, all four tasks count (counts by hand, order: starts committed / kept,
    finishes committed / kept, committed, kept).

    Week 1 (commitments of update 0, due by 03-09): A start, A finish; B start (finish 03-20 is
    later); C start, C finish; D start 03-12 is later. Committed 3 starts, 2 finishes. Kept: A
    start, A finish, B start. Counts (3, 2, 2, 1, 5, 3), PPC Start 2/3, Finish 1/2, W/W-1 3/5 = 60 %.
    Week 2 (update 1, due by 03-16): B finish; C start, C finish; D start, D finish. Kept: B finish,
    C start, C finish, D start. Counts (2, 2, 3, 2, 5, 4), PPC Finish 2/3, W/W-1 4/5 = 80 %.
    """
    store = discipline_store()
    unfiltered = progress.ppc_series(store)
    pd.testing.assert_frame_equal(unfiltered, series(store, None))
    assert counts(row(unfiltered, 1)) == (3, 2, 2, 1, 5, 3)
    assert counts(row(unfiltered, 2)) == (2, 2, 3, 2, 5, 4)
    assert row(unfiltered, 1)["ppc_week"] == pytest.approx(60.0)
    assert row(unfiltered, 2)["ppc_week"] == pytest.approx(80.0)


# (2) one discipline chosen, and the partition


@pytest.mark.oracle("characterization")
def test_one_discipline_counts_its_own_commitments_only():
    """Same series, the filter keeps one discipline. W-1's commitments listed in the previous test.
    CIV (A, B): week 1 A start, A finish, B start, all kept: (2, 2, 1, 1, 3, 3), 100 %, 100 %, 100 %.
    Week 2 B finish, kept: (0, 0, 1, 1, 1, 1), PPC Start none (0 starts committed), Finish 100 %.
    MEC (C, D): week 1 C start, C finish, both missed: (1, 0, 1, 0, 2, 0), 0 %.
    Week 2 C start, C finish, D start, D finish; kept C start, C finish, D start: (2, 2, 2, 1, 4, 3),
    PPC Start 100 %, Finish 1/2 = 50 %, W/W-1 3/4 = 75 %."""
    store = discipline_store()
    civ = series(store, CodeFilter("Discipline", (CIV,)))
    mec = series(store, CodeFilter("Discipline", (MEC,)))
    assert counts(row(civ, 1)) == (2, 2, 1, 1, 3, 3)
    assert counts(row(civ, 2)) == (0, 0, 1, 1, 1, 1)
    assert [row(civ, 1)[c] for c in PPC] == [100.0, 100.0, 100.0]
    assert pd.isna(row(civ, 2)["ppc_start"])
    assert row(civ, 2)["ppc_finish"] == pytest.approx(100.0)
    assert counts(row(mec, 1)) == (1, 0, 1, 0, 2, 0)
    assert counts(row(mec, 2)) == (2, 2, 2, 1, 4, 3)
    assert [row(mec, 1)[c] for c in PPC] == [0.0, 0.0, 0.0]
    assert [row(mec, 2)[c] for c in PPC] == [pytest.approx(100.0), pytest.approx(50.0), pytest.approx(75.0)]


@pytest.mark.oracle("property")
def test_two_disciplines_that_partition_the_tasks_add_up_to_the_unfiltered_counts():
    """Every task is CIV or MEC, so each count of CIV plus the same count of MEC is the unfiltered
    one. Week 1: (2, 2, 1, 1, 3, 3) + (1, 0, 1, 0, 2, 0) = (3, 2, 2, 1, 5, 3); week 2:
    (0, 0, 1, 1, 1, 1) + (2, 2, 2, 1, 4, 3) = (2, 2, 3, 2, 5, 4)."""
    store = discipline_store()
    unfiltered = progress.ppc_series(store)
    civ = series(store, CodeFilter("Discipline", (CIV,)))
    mec = series(store, CodeFilter("Discipline", (MEC,)))
    for update in (1, 2):
        for column in COUNTS:
            assert row(civ, update)[column] + row(mec, update)[column] == row(unfiltered, update)[column], column


# (3) a task that changes discipline


@pytest.mark.oracle("characterization")
def test_a_task_counts_for_the_discipline_it_had_in_the_previous_update():
    """T is CIV in update 0 and MEC in update 1, U the other way round.
    Update 0 (DD 03-02): T not started 03-03 -> 03-06, U 03-04 -> 03-05. Update 1 (DD 03-09):
    T complete 03-03 / 03-06, U not started 03-10 -> 03-12. Commitments of update 0: T start,
    T finish, U start, U finish. Kept: T start, T finish; missed: U's two.
    CIV in W-1 holds T only: (1, 1, 1, 1, 2, 2), 100 %. MEC in W-1 holds U only: (1, 0, 1, 0, 2, 0),
    0 %. (By the discipline of W, CIV would hold U and read 0 %, MEC T and read 100 %.)"""
    update0 = [todo("T", **plan("03", "06")), todo("U", **plan("04", "05"))]
    update1 = [done("T", **actual("03", "06")), todo("U", **plan("10", "12"))]
    store = SnapshotStore(
        [
            discipline_snap(update0, {"T": "CIV", "U": "MEC"}, DD0),
            discipline_snap(update1, {"T": "MEC", "U": "CIV"}, DD1),
        ]
    )
    civ = row(series(store, CodeFilter("Discipline", (CIV,))), 1)
    mec = row(series(store, CodeFilter("Discipline", (MEC,))), 1)
    assert counts(civ) == (1, 1, 1, 1, 2, 2)
    assert counts(mec) == (1, 0, 1, 0, 2, 0)
    assert civ["ppc_week"] == pytest.approx(100.0)
    assert mec["ppc_week"] == pytest.approx(0.0)


# (4) the type is found by its P6 name, whatever label a file gives it


@pytest.mark.oracle("characterization")
def test_the_type_is_found_by_its_name_when_a_file_labels_it_otherwise():
    """Update 0 has one type "Discipline" (label "Discipline"); updates 1 and 2 have two types of
    that name, labelled "Discipline (global)" and "Discipline (project)". A is CIV in the global
    one, B CIV in the project one (updates 1, 2); both CIV in update 0. The text "CIV" is in
    every value of the type, in both files (the values' labels differ, a text still matches).
    Update 0 (DD 03-02): A not started 03-03 -> 03-13, B 03-04 -> 03-06. Update 1 (DD 03-09): A
    started 03-03 (finish 03-13), B started 03-04 (finish 03-12). Update 2: A, B complete.
    Week 1: A start, B start, B finish (A finish 03-13 is later); kept A start, B start:
    (2, 2, 1, 0, 3, 2), PPC W/W-1 2/3. Week 2 (types labelled otherwise): A finish 03-13, B finish
    03-12, both kept: (0, 0, 2, 2, 2, 2), PPC Start none, PPC W/W-1 100 %."""
    code_filter = CodeFilter("Discipline", ("CIV",))
    update0 = [todo("A", **plan("03", "13")), todo("B", **plan("04", "06"))]
    update1 = [
        active("A", act_start_date="2026-03-03 08:00", early_end_date="2026-03-13 17:00"),
        active("B", act_start_date="2026-03-04 08:00", early_end_date="2026-03-12 17:00"),
    ]
    update2 = [done("A", **actual("03", "13")), done("B", **actual("04", "12"))]
    store = SnapshotStore(
        [
            discipline_snap(update0, {"A": "CIV", "B": "CIV"}, DD0),
            two_types_snap(update1, {"A": "CIV"}, {"B": "CIV"}, DD1),
            two_types_snap(update2, {"A": "CIV"}, {"B": "CIV"}, DD2),
        ]
    )
    table = series(store, code_filter)
    assert counts(row(table, 1)) == (2, 2, 1, 0, 3, 2)
    assert row(table, 1)["ppc_week"] == pytest.approx(200 / 3)
    assert counts(row(table, 2)) == (0, 0, 2, 2, 2, 2)
    assert pd.isna(row(table, 2)["ppc_start"])
    assert row(table, 2)["ppc_week"] == pytest.approx(100.0)


# (5) a value, or a type, that a file does not have


@pytest.mark.oracle("characterization")
def test_a_value_absent_from_the_previous_file_gives_no_commitment_and_no_ppc():
    """Update 0 (DD 03-02): A (CIV) not started 03-03 -> 03-06; no MEC value assigned. Update 1
    (DD 03-09): A complete; M (MEC) not started 03-10 -> 03-13. Update 2 (DD 03-16): M complete
    03-10 / 03-13. Filter MEC. Week 1: update 0 has no MEC task, so no commitment: counts all 0,
    the three PPC none (never 100 %). Week 2: M start, M finish, both kept: (1, 1, 1, 1, 2, 2), 100 %."""
    update0 = [todo("A", **plan("03", "06"))]
    update1 = [done("A", **actual("03", "06")), todo("M", **plan("10", "13"))]
    update2 = [done("A", **actual("03", "06")), done("M", **actual("10", "13"))]
    assigned = {"A": "CIV", "M": "MEC"}
    store = SnapshotStore(
        [
            discipline_snap(update0, {"A": "CIV"}, DD0),
            discipline_snap(update1, assigned, DD1),
            discipline_snap(update2, assigned, DD2),
        ]
    )
    table = series(store, CodeFilter("Discipline", ("MEC",)))
    assert counts(row(table, 1)) == (0, 0, 0, 0, 0, 0)
    assert all(pd.isna(row(table, 1)[column]) for column in PPC)
    assert counts(row(table, 2)) == (1, 1, 1, 1, 2, 2)
    assert row(table, 2)["ppc_week"] == pytest.approx(100.0)


@pytest.mark.oracle("characterization")
def test_a_type_the_file_does_not_have_selects_nothing():
    """Files with the code type "Discipline" only. The filter names "Phase": no task is selected
    (empty set), and the series has no commitment in either week (counts 0, PPC none)."""
    store = discipline_store()
    code_filter = CodeFilter("Phase", ("CIV",))
    first = discipline_snap([todo("A", **plan("03", "06"))], {"A": "CIV"}, DD0)
    assert code_filter.tasks(first) == set()
    table = series(store, code_filter)
    for update in (1, 2):
        assert counts(row(table, update)) == (0, 0, 0, 0, 0, 0)
        assert all(pd.isna(row(table, update)[column]) for column in PPC)


# (6) two types of the same name in one file: union


@pytest.mark.oracle("characterization")
def test_two_types_of_the_same_name_in_a_file_are_a_union():
    """Global "Discipline": A is CIV, C is MEC. Project "Discipline": B is CIV. The name
    "Discipline" is both types. Text "CIV": A (global) and B (project) = {A, B}. The exact label
    of the global value "CIV · Global CIV": A only. Text "MEC": C only. Text "civ" and "mec" together:
    all three."""
    tasks = [todo("A"), todo("B"), todo("C")]
    s = two_types_snap(tasks, {"A": "CIV", "C": "MEC"}, {"B": "CIV"}, DD0)
    assert CodeFilter("Discipline", ("CIV",)).tasks(s) == {"A", "B"}
    assert CodeFilter("Discipline", ("CIV · Global CIV",)).tasks(s) == {"A"}
    assert CodeFilter("Discipline", ("MEC",)).tasks(s) == {"C"}
    assert CodeFilter("Discipline", ("civ", "mec")).tasks(s) == {"A", "B", "C"}


# (7) an exact value against a contained text


@pytest.mark.oracle("characterization")
@pytest.mark.parametrize(
    ("picks", "expected"),
    [
        ((CIV,), {"A"}),  # the label of CIV is exactly that value, not CIVIL
        (("CIV",), {"A", "B"}),  # not a label: a text, contained in CIV and in CIVIL
        (("civ",), {"A", "B"}),  # case ignored
        (("CIVIL",), {"B"}),
        (("elec",), {"D"}),  # accents and case ignored: value "Élec"
        (("zzz",), set()),
        ((CIV, "mec"), {"A", "C"}),  # an exact value and a text, together
    ],
)
def test_a_label_picks_its_value_exactly_and_any_other_pick_is_a_contained_text(picks, expected):
    """A is CIV, B CIVIL, C MEC, D Élec, E has no discipline. The expected set is read from the
    values' codes: "civ" is in "CIV" and "CIVIL"; "elec" is in "Élec"; the label of CIV is not in
    any code, so it only designates the value CIV."""
    tasks = [todo(code) for code in "ABCDE"]
    s = discipline_snap(tasks, {"A": "CIV", "B": "CIVIL", "C": "MEC", "D": "Élec"}, DD0)
    assert CodeFilter("Discipline", picks).tasks(s) == expected


# (8) keep


@pytest.mark.oracle("characterization")
def test_keep_returns_the_rows_of_the_selected_tasks_in_order_with_their_index():
    """A, C are CIV, B is MEC, D has none. Rows C, B, A, D, Z (Z is not in the file), indexed
    10..14. Filter CIV: rows C (index 10) and A (index 12), in that order, other columns kept.
    Filter on a type the file lacks: no rows, same columns."""
    s = discipline_snap([todo(c) for c in "ABCD"], {"A": "CIV", "B": "MEC", "C": "CIV"}, DD0)
    rows = pd.DataFrame({"task_code": ["C", "B", "A", "D", "Z"], "note": list("vwxyz")}, index=[10, 11, 12, 13, 14])
    kept = CodeFilter("Discipline", (CIV,)).keep(rows, s)
    pd.testing.assert_frame_equal(kept, rows.loc[[10, 12]])
    none = CodeFilter("Phase", ("CIV",)).keep(rows, s)
    assert none.empty
    assert list(none.columns) == ["task_code", "note"]


@pytest.mark.oracle("characterization")
def test_a_code_filter_is_immutable():
    """CodeFilter is a frozen dataclass: its fields cannot be reassigned."""
    code_filter = CodeFilter("Discipline", ("CIV",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        code_filter.type_name = "Phase"  # type: ignore[misc]


# (9) progress_of_code: the weekly progress (progress_delta) restricted to a code
#
# Rule (design decision of the project, not a source): a live task counts with the code it has in W's
# file, a task deleted since W-1 with the code it had in W-1's file (it has none in W). Unlike the
# commitments above, which use W-1's file for every task. Values counted by hand from progress_delta:
# pct_delta = pct_now - pct_prev; a task absent from W has pct_now 0 and ``deleted`` true; a task absent
# from W-1 has pct_prev 0 and ``new`` true. % complete is by duration (default of xerkit, 80 h original):
# todo = 0 %, active with 40 h remaining = 50 %, done = 100 %.


def week_pair(
    previous_tasks: list[dict], previous_codes: dict[str, str], current_tasks: list[dict], current_codes: dict[str, str]
) -> tuple[Snapshot, Snapshot, pd.DataFrame]:
    """W-1 (DD 03-02) and W (DD 03-09), each with its disciplines, and ``progress_delta`` of the pair."""
    previous = discipline_snap(previous_tasks, previous_codes, DD0)
    current = discipline_snap(current_tasks, current_codes, DD1)
    return previous, current, progress.progress_delta(previous, current)


def of_code(delta: pd.DataFrame, previous: Snapshot, current: Snapshot, value: str) -> pd.DataFrame:
    return progress.progress_of_code(delta, CodeFilter("Discipline", (value,)), previous, current)


def changes(frame: pd.DataFrame) -> dict[str, float]:
    """pct_delta of each row, by task_code."""
    return dict(zip(frame["task_code"], frame["pct_delta"], strict=True))


@pytest.mark.oracle("characterization")
def test_a_live_task_that_changes_discipline_counts_with_the_discipline_of_w():
    """T is CIV in W-1 and MEC in W; S is CIV in both. W-1: S, T not started (0 %). W: S complete
    (100 %), T started with 40 h left (50 %). Delta: S 0 -> 100 = +100, T 0 -> 50 = +50.
    CIV in W holds S only: {S: 100}. MEC in W holds T only: {T: 50} (CIV in W-1 would hold both, and
    MEC none)."""
    previous, current, delta = week_pair(
        [todo("S"), todo("T")],
        {"S": "CIV", "T": "CIV"},
        [done("S", **actual("03", "06")), active("T")],
        {"S": "CIV", "T": "MEC"},
    )
    assert changes(of_code(delta, previous, current, "CIV")) == {"S": 100.0}
    assert changes(of_code(delta, previous, current, "MEC")) == {"T": 50.0}


@pytest.mark.oracle("characterization")
def test_a_deleted_task_counts_with_the_discipline_it_had_in_w_minus_1():
    """D is CIV in W-1, active (50 %), and is not in W. S is MEC in both: not started in W-1 (0 %),
    complete in W (100 %). N is new in W, MEC, started (50 %). N is listed first in W, so it takes
    the task_id D had in W-1 (xerkit numbers tasks by position): D must not be read through N.
    Delta: D 50 -> 0 (deleted) = -50; S 0 -> 100 = +100; N 0 -> 50 (new) = +50.
    CIV: {D: -50}. MEC: {S: 100, N: 50}."""
    previous, current, delta = week_pair(
        [active("D"), todo("S")],
        {"D": "CIV", "S": "MEC"},
        [active("N"), done("S", **actual("03", "06"))],
        {"N": "MEC", "S": "MEC"},
    )
    assert bool(delta.set_index("task_code").loc["D", "deleted"])
    assert changes(of_code(delta, previous, current, "CIV")) == {"D": -50.0}
    assert changes(of_code(delta, previous, current, "MEC")) == {"S": 100.0, "N": 50.0}


@pytest.mark.oracle("characterization")
def test_a_new_task_counts_with_the_discipline_it_has_in_w():
    """N is not in W-1 and is CIV in W, started (40 h left, 50 %); S is MEC in both, not started
    in both (0 %). Delta: N 0 -> 50 (new) = +50, S 0. CIV: {N: 50}. MEC: {S: 0}."""
    previous, current, delta = week_pair([todo("S")], {"S": "MEC"}, [todo("S"), active("N")], {"S": "MEC", "N": "CIV"})
    assert bool(delta.set_index("task_code").loc["N", "new"])
    assert changes(of_code(delta, previous, current, "CIV")) == {"N": 50.0}
    assert changes(of_code(delta, previous, current, "MEC")) == {"S": 0.0}


def mixed_week() -> tuple[Snapshot, Snapshot, pd.DataFrame]:
    """A deleted, a changed, a new and two unchanged tasks, in W-1's file D, S, T, R and W's N, S, T, R.

    W-1: D CIV 50 %; S CIV 0 %; T CIV 0 %; R MEC 50 %. W: N MEC 50 % (new); S CIV 100 %;
    T MEC 50 % (CIV in W-1); R MEC 100 %. D is deleted.
    Delta pct_delta: D -50, S +100, T +50, R +50, N +50: sum 200.
    """
    return week_pair(
        [active("D"), todo("S"), todo("T"), active("R")],
        {"D": "CIV", "S": "CIV", "T": "CIV", "R": "MEC"},
        [active("N"), done("S", **actual("03", "06")), active("T"), done("R", **actual("03", "06"))],
        {"N": "MEC", "S": "CIV", "T": "MEC", "R": "MEC"},
    )


@pytest.mark.oracle("property")
def test_two_disciplines_that_partition_the_tasks_add_up_to_the_weekly_progress():
    """CIV, by the rule: D (deleted, CIV in W-1) and S (CIV in W) = -50 + 100 = +50.
    MEC: T, R, N = 50 + 50 + 50 = +150. Together the five tasks of delta, +200, once each."""
    previous, current, delta = mixed_week()
    civ = of_code(delta, previous, current, "CIV")
    mec = of_code(delta, previous, current, "MEC")
    assert changes(civ) == {"D": -50.0, "S": 100.0}
    assert changes(mec) == {"T": 50.0, "R": 50.0, "N": 50.0}
    assert sorted([*civ["task_code"], *mec["task_code"]]) == sorted(delta["task_code"])
    assert civ["pct_delta"].sum() + mec["pct_delta"].sum() == pytest.approx(delta["pct_delta"].sum())
    assert civ["pct_delta"].sum() + mec["pct_delta"].sum() == pytest.approx(200.0)


@pytest.mark.oracle("characterization")
def test_the_rows_kept_are_those_of_delta_in_the_same_order_with_the_same_columns():
    """MEC in the week of ``mixed_week`` holds N, T, R. The result is delta's rows of those
    three, in delta's order, every column unchanged (compared whatever the index)."""
    previous, current, delta = mixed_week()
    kept = of_code(delta, previous, current, "MEC")
    expected = delta[delta["task_code"].isin(["N", "T", "R"])]
    assert list(kept.columns) == list(delta.columns)
    pd.testing.assert_frame_equal(kept.reset_index(drop=True), expected.reset_index(drop=True))


@pytest.mark.oracle("characterization")
@pytest.mark.parametrize(
    ("type_name", "value"),
    [("Phase", "CIV"), ("Discipline", "ELE")],  # a type no file has; a value no task holds
)
def test_no_task_held_gives_no_row_and_the_same_columns(type_name, value):
    """In ``mixed_week`` every task is CIV or MEC, and no file has a type "Phase" or a value
    "ELE": the filter holds no task in W or in W-1, so no row is kept, the columns are delta's."""
    previous, current, delta = mixed_week()
    kept = progress.progress_of_code(delta, CodeFilter(type_name, (value,)), previous, current)
    assert kept.empty
    assert list(kept.columns) == list(delta.columns)
