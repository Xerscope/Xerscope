"""A .xer is the trust boundary: build_snapshot returns a Snapshot or raises XerError, nothing else.

Each case below is a damaged or hostile export a user can plausibly hand the app: a copy still
being written to a NAS share, a file edited by hand, a crafted upload. Left unchecked, each one
either crashes with a library exception (on the app's synchronous load path every page then
fails and the file picker is no longer drawn) or yields numbers from a partial schedule without
a word.

Refusing rather than repairing rests on what P6 writes. The 394 P6 exports under
tests/reference/data (12 third-party files, 30 held-out sets of 12) all end with %E, hold one
table per name and one column per name in each %F line, have unique TASK.task_id,
PROJWBS.wbs_id and CALENDAR.clndr_id, and date nothing outside 2000-2027.
"""

from __future__ import annotations

import pandas as pd
import pytest
from xerkit import active, done, hours, todo, xer_text

from xerscope.xer import XerError, build_snapshot, parse_text

WBS = [
    {
        "wbs_id": wbs_id,
        "proj_id": "1",
        "wbs_short_name": code,
        "wbs_name": code,
        "proj_node_flag": "N",
        "parent_wbs_id": parent,
        "seq_num": seq,
    }
    for wbs_id, code, parent, seq in (("10", "CIV", "", "1"), ("11", "FDN", "10", "2"))
]
RESOURCES = [{"rsrc_id": "R8", "rsrc_short_name": "FITTER", "rsrc_type": "RT_Labor", "clndr_id": "C8"}]
ASSIGNMENT = {
    "task_code": "B",
    "rsrc_id": "R8",
    "target_qty": "40",
    "remain_qty": "40",
    "act_reg_qty": "0",
    "act_ot_qty": "0",
    "target_qty_per_hr": "1",
    "remain_qty_per_hr": "1",
    "rollup_dates_flag": "Y",
}


def full_file() -> str:
    """One file with every table the model reads: calendars, WBS, a done, an active and an open
    task, logic, a labour assignment, an activity code and an expense."""
    return xer_text(
        [
            done("A", wbs_id="11", **hours(16)),
            active("B", wbs_id="11", **hours(40)),
            todo("C", wbs_id="10", **hours(8)),
        ],
        [("A", "B", "FS", 0), ("B", "C", "SS", 8)],
        wbs=WBS,
        sched={"sched_float_type": "FT_Total"},
        resources=RESOURCES,
        assign=[ASSIGNMENT],
        codes=[("C", "Area", "North/Room 1")],
        costs=["C"],
    )


def build(text: str):
    return build_snapshot(parse_text(text, source="t.xer"))


def lines_of(text: str) -> list[str]:
    return text.rstrip("\n").split("\n")


def table_lines(text: str, table: str) -> tuple[int, list[int]]:
    """Index of the %F line of ``table`` and of its %R lines."""
    lines = lines_of(text)
    start = lines.index(f"%T\t{table}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("%T", "%E"))), len(lines))
    return start + 1, [i for i in range(start + 2, end) if lines[i].startswith("%R")]


def test_the_full_file_builds():
    """The base every mutation below starts from is itself a valid export."""
    s = build(full_file())
    assert len(s.tasks) == 3 and len(s.relationships) == 2 and len(s.assignments) == 1


# --- a file cut short --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cut",
    ["inside the last TASK row", "before TASKPRED", "inside TASKRSRC", "just before %E"],
)
def test_a_file_cut_short_is_refused(cut):
    """A copy still being written, or an interrupted download, stops anywhere. The last row is
    then cut (the parser pads it as if the exporter had dropped trailing empty fields) and the
    tables after it are gone: the schedule loses its logic, an activity its ID and its dates.
    Without %E nothing tells a cut file from a complete one, so it is refused, whatever the cut."""
    text = full_file()
    lines = lines_of(text)
    if cut == "inside the last TASK row":
        _, rows = table_lines(text, "TASK")
        row = lines[rows[-1]]
        truncated = "\n".join([*lines[: rows[-1]], row[: len(row) // 2]])
    elif cut == "before TASKPRED":
        truncated = "\n".join(lines[: lines.index("%T\tTASKPRED")])
    elif cut == "inside TASKRSRC":
        fields, _ = table_lines(text, "TASKRSRC")
        truncated = "\n".join(lines[: fields + 1])
    else:
        truncated = "\n".join(lines[:-1])
    with pytest.raises(XerError, match=r"t\.xer: .*no %E end line"):
        build(truncated)


def test_a_cut_file_still_shows_its_header():
    """The file picker reads PROJECT and TASK alone, to name the project and data date: a cut
    file is listed, and refused when it is loaded."""
    text = "\n".join(lines_of(full_file())[:-1])
    raw = parse_text(text, source="t.xer")
    assert not raw.ended and set(raw.tables) >= {"PROJECT", "TASK"}


def test_lines_after_the_end_line_are_ignored():
    """P6 writes nothing after %E; whatever follows it (padding of a copy tool) is not read."""
    s = build(full_file() + "%T\tTASK\n%F\ttask_id\n%R\t99\n")
    assert len(s.tasks) == 3


# --- structure that P6 never writes ------------------------------------------------------------


def test_a_table_written_twice_is_refused():
    """A second %T TASK block replaced the field names of the first, and the first block's rows
    were then read with the second block's columns (task_code and task_id swapped, no warning)."""
    text = full_file().replace("%E\n", "%T\tTASK\n%F\ttask_code\ttask_id\n%R\tZ\t99\n%E\n")
    with pytest.raises(XerError, match="t.xer: table TASK appears twice"):
        build(text)


def test_a_column_named_twice_is_refused():
    """Two TASK columns of the same name made every typed read of that column a frame instead of a
    series (AttributeError deep in the relationships)."""
    text = full_file()
    fields, _ = table_lines(text, "TASK")
    lines = lines_of(text)
    lines[fields] = lines[fields].replace("\ttask_name\t", "\ttask_code\t", 1)
    with pytest.raises(XerError, match="t.xer: table TASK names column task_code twice"):
        build("\n".join(lines) + "\n")


@pytest.mark.parametrize(
    ("table", "column"),
    [  # beside each key, what happened before the check
        ("TASK", "task_id"),  # InvalidIndexError when relationships and assignments look tasks up
        ("PROJWBS", "wbs_id"),  # ValueError (truth value of a Series) when WBS paths are built
        ("CALENDAR", "clndr_id"),  # no error: the last calendar of that id silently replaced the first
    ],
)
def test_a_duplicated_primary_key_is_refused(table, column):
    """task_id, wbs_id and clndr_id are the keys every other table points at: with two rows on one
    key, a lookup either fails or picks one row arbitrarily."""
    text = full_file()
    _, rows = table_lines(text, table)
    lines = lines_of(text)
    fields = lines[table_lines(text, table)[0]].split("\t")[1:]
    first, second = (lines[i].split("\t") for i in rows[:2])
    second[fields.index(column) + 1] = first[fields.index(column) + 1]
    lines[rows[1]] = "\t".join(second)
    with pytest.raises(
        XerError, match=rf"t\.xer: table {table} has duplicate {column} \['{first[fields.index(column) + 1]}'\]"
    ):
        build("\n".join(lines) + "\n")


# --- values out of any schedule's range --------------------------------------------------------


@pytest.mark.parametrize("value", ["-1", "9999-12-31 00:00", "1899-12-31 23:00", "2200-01-01 00:00"])
def test_a_date_outside_1900_2199_reads_as_no_date(value):
    """XER dates are "YYYY-MM-DD HH:MM"; the reference exports span 2000-2027. "-1" parsed as
    year -1 and failed later in strftime; 9999-12-31 was kept and overflowed the working-day
    count (pandas timestamps end in 2262). Outside 1900-2199 a date reads as blank (NaT), like an
    unparseable one: far enough for any schedule and its lags, short of the overflow."""
    s = build(full_file().replace("2026-03-13 17:00", value))  # C's early finish, among others
    assert s.tasks.set_index("task_code").loc["C", "early_end_date"] is pd.NaT
    assert s.finish_date is None or s.finish_date.year < 2200


def test_dates_at_the_edges_of_the_range_are_kept():
    text = full_file()
    _, rows = table_lines(text, "TASK")
    lines = lines_of(text)
    fields = lines[table_lines(text, "TASK")[0]].split("\t")[1:]
    last = lines[rows[-1]].split("\t")
    last[fields.index("cstr_date") + 1] = "2199-12-31 17:00"
    last[fields.index("cstr_type") + 1] = "CS_MEOB"
    lines[rows[-1]] = "\t".join(last)
    s = build("\n".join(lines) + "\n")
    assert s.tasks.set_index("task_code").loc["C", "cstr_date"] == pd.Timestamp("2199-12-31 17:00")


@pytest.mark.parametrize("value", ["1e400", "-1e400", "inf", "nan"])
def test_a_non_finite_number_reads_as_no_number(value):
    """No XER number is infinite. "1e400" became inf, which a later cast to integer refused
    (PROJWBS.seq_num, the WBS sort order); in a duration it would have reached the CPM. A
    non-finite number reads as blank, like an unparseable one."""
    text = full_file()
    _, rows = table_lines(text, "PROJWBS")
    lines = lines_of(text)
    fields = lines[table_lines(text, "PROJWBS")[0]].split("\t")[1:]
    for i in rows:
        parts = lines[i].split("\t")
        parts[fields.index("seq_num") + 1] = value
        lines[i] = "\t".join(parts)
    s = build("\n".join(lines) + "\n")
    assert len(s.wbs) == 2
    s = build(full_file().replace("\t40\t40\t", f"\t{value}\t{value}\t", 1))
    assert s.tasks.set_index("task_code")["remain_drtn_hr_cnt"].abs().max() != float("inf")


# --- the contract over every column and table --------------------------------------------------

# one value per kind of damage: unreadable text, a negative, a non-finite number, a blank, a
# date past the range of timestamps
GARBAGE = ("x", "-1", "1e400", "", "9999-12-31 00:00")


def mutations():
    """Every table dropped, every row duplicated, every column dropped, and every column's values
    replaced by each GARBAGE value: the damage a hand edit or a broken exporter can do."""
    text = full_file()
    lines = lines_of(text)
    tables = [line.split("\t")[1] for line in lines if line.startswith("%T\t")]
    for table in tables:
        fields, rows = table_lines(text, table)
        names = lines[fields].split("\t")[1:]
        block = {fields - 1, fields, *rows}
        yield f"drop {table}", "\n".join(line for i, line in enumerate(lines) if i not in block)
        for row in rows:
            yield f"{table} row {row} twice", "\n".join([*lines[: row + 1], lines[row], *lines[row + 1 :]])
        for position, name in enumerate(names, start=1):
            dropped = list(lines)
            for i in [fields, *rows]:
                parts = dropped[i].split("\t")
                del parts[position]
                dropped[i] = "\t".join(parts)
            yield f"drop {table}.{name}", "\n".join(dropped)
            for bad in GARBAGE:
                garbled = list(lines)
                for i in rows:
                    parts = garbled[i].split("\t")
                    parts[position] = bad
                    garbled[i] = "\t".join(parts)
                yield f"{table}.{name}={bad!r}", "\n".join(garbled)


def test_any_damage_gives_a_snapshot_or_a_xer_error():
    """The contract itself, over every mutation of ``mutations()``: no other exception escapes
    build_snapshot. A failure lists each mutation and the exception it raised."""
    escaped = []
    count = 0
    for label, text in mutations():
        count += 1
        try:
            build(text + "\n")
        except XerError:
            pass
        except Exception as exc:  # noqa: BLE001 - the point of the test is to catch any
            escaped.append(f"{label}: {type(exc).__name__}: {str(exc)[:80]}")
    assert count >= 540  # 547 today: fewer means full_file() lost a table or a column
    assert not escaped, escaped
