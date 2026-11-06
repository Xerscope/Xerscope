"""Audit of the xer/ layer on hostile and edge inputs (parser, model, calendar / TimeAxis).

Each test records the real behaviour of the code. A test marked ``xfail(strict=True)`` proves a
defect listed in the audit findings (AUDIT-XER-nn): it asserts the expected behaviour and fails
today. The others pass and document behaviour that held up. Nothing here judges P6 semantics.
"""

from __future__ import annotations

import contextlib
import gc
import signal
import tracemalloc
from datetime import date

import numpy as np
import pandas as pd
import pytest
from xerkit import MON_FRI_8H, clndr_data, snap, todo, with_second_project, xer_text

from xerscope.xer import XerError, build_snapshot, parse_bytes, parse_text
from xerscope.xer.calendar import (
    EXCEPTION_FIRST_DATE,
    EXCEPTION_LAST_DATE,
    TimeAxis,
    WorkCalendar,
    hours_to_days,
    parse_clndr_data,
)
from xerscope.xer.model import HEADER_TABLES, projects_text, to_datetime, to_number

T = pd.Timestamp
HEAD = "ERMHDR\t23.12\t2026-03-02\n"


@contextlib.contextmanager
def time_limit(seconds: int):
    """Fail the test instead of hanging when a suspect loop does not end (SIGALRM, Linux)."""
    if not hasattr(signal, "SIGALRM"):
        pytest.skip("no SIGALRM on this platform")

    def on_alarm(signum, frame):
        raise TimeoutError(f"did not finish within {seconds} s")

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def calendar(blob: str, hpd: str = "8", **extra) -> WorkCalendar:
    return WorkCalendar.from_row(
        pd.Series({"clndr_id": "X", "clndr_name": "X", "day_hr_cnt": hpd, "clndr_data": blob, **extra})
    )


def peak_memory(fn):
    """(result, peak bytes allocated by Python while running ``fn``)."""
    gc.collect()
    tracemalloc.start()
    try:
        result = fn()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, peak


def big_xer(target_bytes: int) -> bytes:
    """A TASK table of ~target_bytes, 30 columns, built in memory (no real schedule)."""
    cols = ["task_id", "proj_id", "task_code", "task_name", "status_code", "task_type", "clndr_id"]
    cols += [f"c{i}" for i in range(23)]
    head = HEAD + "%T\tPROJECT\n%F\tproj_id\tproj_short_name\tlast_recalc_date\n%R\t1\tT\t2026-03-02 08:00\n"
    head += "%T\tTASK\n%F\t" + "\t".join(cols) + "\n"
    row = "%R\t{i}\t1\tA{i}\tActivity name number {i} with some text\tTK_NotStart\tTT_Task\t8\t"
    row += "\t".join(f"val{k}" for k in range(23)) + "\n"
    n = target_bytes // len(row.format(i=1_000_000))
    return (head + "".join(row.format(i=i) for i in range(n)) + "%E\n").encode("utf-8")


def wbs_row(wbs_id: str, name: str, seq: str) -> dict:
    return {"wbs_id": wbs_id, "proj_id": "1", "parent_wbs_id": "", "wbs_short_name": name, "wbs_name": name,
            "proj_node_flag": "N", "seq_num": seq}  # fmt: skip


# --- parser -----------------------------------------------------------------------------------


def test_empty_file_raises_xer_error():
    with pytest.raises(XerError, match="not an XER file"):
        parse_bytes(b"")


def test_missing_end_marker_is_tolerated():
    assert list(parse_text(HEAD + "%T\tA\n%F\tx\n%R\t1\n").tables) == ["A"]


def test_table_without_field_line_is_skipped_with_a_warning():
    raw = parse_text(HEAD + "%T\tA\n%R\t1\n%E\n")
    assert raw.tables == {}
    assert raw.warnings == ["table A has rows but no %F field line; skipped"]


def test_second_field_line_in_a_table_keeps_the_first_columns_and_ignores_the_rows_under_it():
    """AUDIT-XER-01: the rows read under the first %F line kept their columns; the rows under a
    contradicting %F line are left out, and the warning names the table."""
    raw = parse_text(HEAD + "%T\tA\n%F\tx\ty\n%R\t1\t2\n%F\tp\tq\tr\n%R\t3\t4\t5\n%E\n")
    assert raw.table("A").to_dict("records") == [{"x": "1", "y": "2"}]
    assert raw.warnings == ["table A: a %F line with other columns than its first one; the rows under it are ignored"]


def test_table_written_twice_is_refused():
    """AUDIT-XER-01, closed by the load contract (#133): P6 writes each table once; a second block,
    with other columns or the same, is refused rather than merged."""
    with pytest.raises(XerError, match="table TASK appears twice"):
        parse_text(HEAD + "%T\tTASK\n%F\tx\ty\n%R\t1\t2\n%T\tTASK\n%F\tp\n%R\t3\n%E\n")
    with pytest.raises(XerError, match="table TASK appears twice"):
        parse_text(HEAD + "%T\tTASK\n%F\tx\n%R\t1\n%T\tOTHER\n%F\ty\n%R\t2\n%T\tTASK\n%F\tx\n%R\t3\n%E\n")


def test_second_field_line_inside_one_table_ignores_the_rows_under_it():
    """AUDIT-XER-01: a second %F line in the same block never relabels the rows read under the first."""
    raw = parse_text(HEAD + "%T\tTASK\n%F\tx\ty\n%R\t1\t2\n%F\tp\n%R\t3\n%E\n")
    assert raw.table("TASK").to_dict("records") == [{"x": "1", "y": "2"}]
    assert raw.warnings == [
        "table TASK: a %F line with other columns than its first one; the rows under it are ignored"
    ]


def test_row_longer_than_its_fields_is_truncated_and_reported_only_when_non_blank():
    raw = parse_text(HEAD + "%T\tA\n%F\tx\ty\n%R\t1\t2\t3\n%R\t1\t2\t\n%E\n")
    assert raw.table("A").to_dict("records") == [{"x": "1", "y": "2"}, {"x": "1", "y": "2"}]
    assert raw.warnings == ["table A: 1 row(s) with more fields than its %F line; extra fields dropped"]


def test_utf8_bom_is_stripped_from_the_header_tag():
    raw = parse_bytes(("﻿" + HEAD + "%T\tA\n%F\tx\n%R\t1\n%E\n").encode("utf-8"))
    assert (raw.encoding, raw.version, list(raw.tables)) == ("utf-8-sig", "23.12", ["A"])


def test_cp1252_undefined_bytes_are_replaced_with_a_warning():
    raw = parse_bytes(HEAD.encode() + b"%T\tA\n%F\tx\n%R\ta\x81b\x8dc\n%E\n")
    assert raw.encoding == "cp1252 (lossy)"
    assert raw.table("A").iloc[0, 0] == "a�b�c"
    assert any("undecodable" in w for w in raw.warnings)


def test_utf16_file_is_decoded_or_rejected_naming_the_encoding():
    """AUDIT-XER-02: a UTF-16 / UTF-32 byte order mark is honoured instead of reading the bytes as cp1252."""
    raw = parse_bytes((HEAD + "%T\tA\n%F\tx\n%R\t1\n%E\n").encode("utf-16"))  # BOM FF FE
    assert (raw.encoding, raw.version, raw.table("A")["x"].tolist()) == ("utf-16", "23.12", ["1"])
    assert parse_bytes((HEAD + "%T\tA\n%F\tx\n%R\t1\n%E\n").encode("utf-32")).encoding == "utf-32"
    with pytest.raises(XerError, match="UTF-16 byte order mark"):
        parse_bytes(b"\xff\xfe\x00\xd8")  # a lone high surrogate: not UTF-16 text


def test_lone_carriage_return_inside_a_value_is_kept():
    raw = parse_text(HEAD + "%T\tCALENDAR\n%F\tclndr_id\tclndr_data\n%R\t1\t(0||a()\r(0||b()))\n%E\n")
    assert raw.table("CALENDAR").loc[0, "clndr_data"] == "(0||a()\r(0||b()))"


def test_cr_only_line_endings_give_no_tables_and_a_clear_model_error():
    raw = parse_text("ERMHDR\t1\r%T\tTASK\r%F\tx\r%R\t1\r%E\r", source="mac.xer")
    assert raw.tables == {}  # the parser accepts the header line, so no XerError at this level
    with pytest.raises(XerError, match="incomplete file, no %E end line"):
        build_snapshot(raw)  # "%E\r" is not the %E line: the file reads as cut short


def test_lines_with_an_unknown_tag_are_dropped_without_a_count():
    raw = parse_text(HEAD + "%T\tA\n%F\tx\n %R\t1\n%R \t2\n%X\t3\n%E\n")
    assert raw.table("A").empty
    assert raw.warnings == []  # only %R rows before any %T are counted (orphans)


def test_empty_table_name_followed_by_rows_counts_them_as_outside_any_table():
    """AUDIT-XER-03: a blank %T name opens no table (as a %T line without a name); its rows are reported."""
    raw = parse_text(HEAD + "%T\t\n%F\tx\n%R\t9\n%E\n")
    assert raw.tables == {}
    assert raw.warnings == ["1 %R row(s) outside any named %T table; skipped"]


def test_table_name_with_a_tab_keeps_the_first_field_and_tag_like_names_are_plain_names():
    assert list(parse_text(HEAD + "%T\tTA\tBLE\n%F\tx\n%R\t1\n%E\n").tables) == ["TA"]
    raw = parse_text(HEAD + "%T\t%T\n%F\t%R\t%T\tx\n%R\t1\t2\t3\n%E\n")
    assert raw.table("%T").to_dict("records") == [{"%R": "1", "%T": "2", "x": "3"}]


def test_table_with_zero_rows_keeps_its_columns():
    raw = parse_text(HEAD + "%T\tA\n%F\tx\ty\n%T\tB\n%F\tz\n%R\t1\n%E\n")
    assert raw.table("A").shape == (0, 2)
    assert list(raw.table("A").columns) == ["x", "y"]


def test_keep_projection_tolerates_a_wanted_column_the_file_lacks():
    raw = parse_text(HEAD + "%T\tTASK\n%F\ttask_id\n%R\t1\n%E\n", keep={"TASK": ("task_id", "task_code")})
    assert list(raw.table("TASK").columns) == ["task_id"]  # the model's _require then names the missing one
    raw = parse_text(HEAD + "%T\tTASK\n%F\ta\n%R\t1\n%E\n", keep=HEADER_TABLES)
    assert "TASK" not in raw.tables and any("no %F" in w for w in raw.warnings)


def test_duplicate_column_name_is_refused_by_the_parser():
    """AUDIT-XER-04, closed by the load contract (#133): a column named twice is a XerError."""
    text = xer_text([todo("A")])
    header = next(line for line in text.splitlines() if line.startswith("%F\ttask_id"))
    text = text.replace(header, header.replace("\ttask_name\t", "\ttask_code\t"), 1)  # two task_code columns
    with pytest.raises(XerError, match="table TASK names column task_code twice"):
        parse_text(text, source="t.xer")


def test_a_single_50mb_line_parses_fast_in_bounded_memory():
    data = (HEAD + "%T\tA\n%F\tx\n%R\t" + "y" * 50_000_000 + "\n%E\n").encode()
    with time_limit(30):
        raw, peak = peak_memory(lambda: parse_bytes(data))
    assert len(raw.table("A").iloc[0, 0]) == 50_000_000
    assert peak < 6 * len(data)  # measured: about 3x (str decode + split copies)


def test_ten_million_tabs_on_one_row_are_dropped_with_no_warning_for_blank_extras():
    data = (HEAD + "%T\tA\n%F\tx\n%R\t" + "\t" * 10_000_000 + "\n%E\n").encode()
    with time_limit(30):
        raw = parse_bytes(data)
    assert raw.table("A").shape == (1, 1) and raw.warnings == []


def test_peak_memory_of_parse_bytes_is_a_small_multiple_of_the_file_size():
    """AUDIT-XER-05: the text (1x), the cell array and the distinct cell strings; measured 3.2x."""
    data = big_xer(10_000_000)
    with time_limit(120):
        raw, peak = peak_memory(lambda: parse_bytes(data))
    assert len(raw.table("TASK")) > 40_000
    assert peak <= 4 * len(data), (
        f"peak {peak / 1e6:.0f} MB for a {len(data) / 1e6:.0f} MB file ({peak / len(data):.1f}x)"
    )


# --- model: identity ------------------------------------------------------------------------


def test_repeated_activity_id_keeps_the_first_row_with_a_warning():
    """#135: the first row of a repeated Activity ID is kept, the others leave the snapshot."""
    s = snap([todo("A", task_name="first"), todo("A", task_name="second")])
    assert len(s.tasks) == 1 and s.by_code.loc["A", "task_name"] == "first"
    assert any("Activity ID repeated in the project ['A']" in w for w in s.warnings)


def test_empty_task_code_is_accepted_as_an_identity_without_a_warning():
    s = snap([{"task_code": ""}, todo("B")], [("", "B", "FS", 0)])
    assert s.tasks["task_code"].tolist() == ["", "B"]
    assert s.relationships[["pred_code", "succ_code"]].to_dict("records") == [{"pred_code": "", "succ_code": "B"}]
    assert not [w for w in s.warnings if "task_code" in w or "Activity ID" in w]


def test_task_codes_differing_by_case_or_trailing_space_are_distinct_identities():
    s = snap([todo("A"), todo("a"), todo("A ")])
    assert s.tasks["task_code"].tolist() == ["A", "a", "A "]
    assert len(s.by_code) == 3 and not any("duplicate" in w for w in s.warnings)


def test_repeated_task_id_is_refused():
    """AUDIT-XER-06, closed by the load contract (#133): every other table points at task_id."""
    with pytest.raises(XerError, match=r"table TASK has duplicate task_id \['1'\]"):
        snap([todo("A", task_id="1"), todo("B", task_id="1")], [("A", "B", "FS", 0)])


def test_repeated_wbs_id_is_refused():
    """AUDIT-XER-07, closed by the load contract (#133)."""
    wbs = [
        wbs_row("10", "A", "1"),
        wbs_row("10", "B", "2"),
    ]  # fmt: skip
    with pytest.raises(XerError, match=r"table PROJWBS has duplicate wbs_id \['10'\]"):
        snap([todo("A", wbs_id="10")], wbs=wbs)


def test_duplicate_project_row_keeps_the_first_and_file_baseline_readable():
    """AUDIT-XER-08: a duplicated PROJECT row is dropped with a warning; the baseline note stays text."""
    lines = xer_text([todo("A")]).splitlines()
    row = lines.index("%T\tPROJECT") + 2
    lines.insert(row + 1, lines[row])
    s = build_snapshot(parse_text("\n".join(lines), source="t.xer"))
    assert len(s.file_projects) == 1
    assert "t.xer: 1 PROJECT row(s) repeat a proj_id ['1']; the first row is kept" in s.warnings
    assert "dtype" not in s.file_baseline.note and "dtype" not in s.file_baseline.proj_id


def test_two_projects_with_the_same_code_are_both_counted():
    """AUDIT-XER-09: project_task_counts / projects_in_file are keyed by proj_id; the text names each by code."""
    text = with_second_project(xer_text([todo("A")]), "T", ["X", "Y"], "2026-03-09 08:00")
    s = build_snapshot(parse_text(text, source="t.xer"))
    assert len(s.file_projects) == 2  # the file does hold two projects
    assert s.project_task_counts == {"1": 1, "2": 2} and s.projects_in_file == ["1", "2"]
    assert projects_text(s) == "T (1) · T (2)"


def test_local_activity_named_like_an_external_placeholder_is_warned_about():
    """AUDIT-XER-10: the placeholder name is kept (documented and tested); the collision is reported."""
    # project 2 owns task_id 100 and links it into B; this project also has an activity literally called "[ext]100"
    main = xer_text([todo("[ext]100"), todo("B")], [("[ext]100", "B", "FS", 0), ("100", "B", "FS", 8, "2")])
    s = build_snapshot(parse_text(with_second_project(main, "P2", ["X"], "2026-03-02 08:00"), source="t.xer"))
    preds = s.relationships[s.relationships["succ_code"] == "B"]
    assert preds["is_external"].tolist() == [False, True]
    assert preds["pred_code"].tolist() == ["[ext]100", "[ext]100"]
    assert any("activity ID(s) ['[ext]100'] are also the placeholder names" in w for w in s.warnings)


def test_same_activity_id_in_two_projects_with_an_external_link_is_named_by_task_id():
    main = xer_text([todo("A"), todo("B")], [("A", "B", "FS", 0), ("100", "B", "FS", 0, "2")])
    s = build_snapshot(parse_text(with_second_project(main, "P2", ["A"], "2026-03-02 08:00"), source="t.xer"))
    assert s.relationships[["pred_code", "is_external"]].to_dict("records") == [
        {"pred_code": "A", "is_external": False},
        {"pred_code": "[ext]100", "is_external": True},
    ]
    assert s.external_tasks["task_code"].tolist() == ["[ext]100"]


# --- model: typing of cells ---------------------------------------------------------------------


def test_columns_present_but_all_blank_give_nat_nan_and_no_crash():
    s = snap(
        [
            todo(
                "A",
                early_start_date="",
                early_end_date="",
                target_drtn_hr_cnt="",
                remain_drtn_hr_cnt="",
                total_float_hr_cnt="",
            )
        ]
    )
    t = s.tasks.iloc[0]
    assert pd.isna(t["start"]) and pd.isna(t["finish"]) and s.finish_date is None
    assert np.isnan(t["original_d"]) and np.isnan(t["remaining_d"]) and np.isnan(t["total_float_d"])
    assert not t["is_critical"]  # NaN float never reads as critical


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", "NaT"),
        ("0000-00-00", "NaT"),
        ("03/02/2026", "NaT"),  # a US date is not guessed (pyproject turns the guess warning into an error)
        ("2026-03-02 24:00", "NaT"),  # 24:00 is not read as the next midnight (question for the business)
        ("2026-13-01 08:00", "NaT"),
        ("2026-03-02 08:00:30", "2026-03-02 08:00:30"),  # seconds kept
        ("2026-03-02 08:00:30.123456", "2026-03-02 08:00:30.123456"),
        ("2026-03-02T08:00", "2026-03-02 08:00:00"),
        ("  2026-03-02 08:00  ", "2026-03-02 08:00:00"),
        ("20260302", "2026-03-02 00:00:00"),
        ("9999-12-31 23:59", "NaT"),  # outside 1900-2199: read as blank (#133)
    ],
)
def test_date_cells(text, expected):
    s = snap([todo("A", early_start_date=text)])
    assert str(s.tasks.iloc[0]["early_start_date"]) == expected


def test_a_timezone_suffixed_date_cell_reads_as_blank_with_a_warning():
    """AUDIT-XER-11: one time-zoned cell among naive ones is blanked before pandas sees the column."""
    s = snap([todo("A", early_start_date="2026-03-02 08:00+02:00"), todo("B", early_end_date="2026-03-13 17:00Z")])
    assert len(s.tasks) == 2
    assert pd.isna(s.tasks.iloc[0]["early_start_date"]) and pd.isna(s.tasks.iloc[1]["early_end_date"])
    assert s.tasks.iloc[1]["early_start_date"] == T("2026-03-02 08:00")
    assert "test.xer: 2 TASK date cell(s) carry a time zone; read as blank" in s.warnings
    assert to_datetime(pd.Series(["2026-03-02 08:00+02:00", "2026-03-02 08:00"])).isna().tolist() == [True, False]


def test_invalid_data_date_cells_fall_through_to_no_status_date():
    for text in ("03/02/2026", "2026-03-02 24:00", "0000-00-00"):
        s = snap([todo("A")], data_date=text)
        assert s.data_date is None and s.data_date_source == ""
        assert any("no status date" in w for w in s.warnings)


@pytest.mark.parametrize(
    ("text", "hours", "days", "critical"),
    [
        ("1e5", 100000.0, 12500.0, False),
        ("-0", 0.0, 0.0, True),
        ("NaN", np.nan, np.nan, False),
        ("1,5", np.nan, np.nan, False),  # decimal comma is not a number
        ("inf", np.nan, np.nan, False),  # an infinite number reads as blank (#133)
        ("-inf", np.nan, np.nan, False),
        ("-40", 0.0, 0.0, True),  # a negative remaining duration reads as 0 (with a warning)
        (" 80 ", 80.0, 10.0, False),
        ("+80", 80.0, 10.0, False),
        ("0x10", np.nan, np.nan, False),
        ("1_000", np.nan, np.nan, False),
        ("80h", np.nan, np.nan, False),
    ],
)
def test_number_cells(text, hours, days, critical):
    s = snap([todo("A", remain_drtn_hr_cnt=text, total_float_hr_cnt=text, target_drtn_hr_cnt=text)])
    t = s.tasks.iloc[0]
    assert (pd.isna(t["remain_drtn_hr_cnt"]) and pd.isna(hours)) or t["remain_drtn_hr_cnt"] == hours
    assert (pd.isna(t["remaining_d"]) and pd.isna(days)) or t["remaining_d"] == days
    assert bool(t["is_critical"]) is critical


def test_infinite_huge_and_negative_remaining_durations():
    """An infinite number reads as blank (#133); a finite one above 1e6 h and a negative one read as
    0, each with one warning."""
    tasks = [
        todo("A", remain_drtn_hr_cnt="inf"),
        todo("B", remain_drtn_hr_cnt="1e9"),
        todo("C", remain_drtn_hr_cnt="-40"),
    ]
    s = snap(tasks + [todo("D", remain_drtn_hr_cnt="")])
    remaining = s.tasks["remain_drtn_hr_cnt"].tolist()
    assert np.isnan(remaining[0]) and remaining[1:3] == [0.0, 0.0] and np.isnan(remaining[3])
    assert "test.xer: 1 activity remaining duration(s) not finite or above 1e+06 h ['B']; read as 0" in s.warnings
    assert "test.xer: 1 activities with a negative remaining duration, read as 0" in s.warnings


def test_unusable_lag_reads_as_zero_and_an_unknown_link_type_is_kept_and_named():
    """An unknown link type keeps its code in ``relationships`` (#128) and is named once; the
    recalculation ignores it (AUDIT-CPM-06, tests/test_audit_edges_cpm.py)."""
    links = [("A", "B", "FS", "inf"), ("B", "C", "XX", 0), ("A", "C", "SS", "2e6"), ("B", "C", "FF", 8)]
    s = snap([todo("A"), todo("B"), todo("C")], links)
    assert s.relationships[["pred_code", "succ_code", "type", "lag_hr"]].to_dict("records") == [
        {"pred_code": "A", "succ_code": "B", "type": "FS", "lag_hr": 0.0},
        {"pred_code": "B", "succ_code": "C", "type": "PR_XX", "lag_hr": 0.0},
        {"pred_code": "A", "succ_code": "C", "type": "SS", "lag_hr": 0.0},
        {"pred_code": "B", "succ_code": "C", "type": "FF", "lag_hr": 8.0},
    ]
    assert [w for w in s.warnings if "pred_type" in w] == [
        "test.xer: TASKPRED.pred_type 'PR_XX' is not a P6 code (1 row): "
        "kept with its code, ignored by the recalculation"
    ]
    assert "test.xer: 1 relationship lag(s) not finite or above 1e+06 h ['A->C']; read as 0" in s.warnings  # inf: blank


def test_negative_remaining_duration_reads_as_100_percent_complete():
    s = snap([todo("A", status_code="TK_Active", target_drtn_hr_cnt="80", remain_drtn_hr_cnt="-40")])
    assert s.tasks.iloc[0]["pct_complete"] == 100.0  # (80 - -40) / 80 = 150 %, clipped


def test_text_in_critical_duration_threshold_falls_back_to_the_settings_default():
    s = snap([todo("A", total_float_hr_cnt="0")], project={"critical_drtn_hr_cnt": "abc"})
    assert s.options["critical_float_hr"] is None and bool(s.tasks.iloc[0]["is_critical"])


def test_to_number_and_to_datetime_accept_plain_strings_only():
    assert to_number(pd.Series(["1.5", "1 000", "１２", " "])).isna().tolist() == [False, True, True, True]
    assert to_number(pd.Series(["1.5"])).iloc[0] == 1.5
    assert to_datetime(pd.Series(["2026-W10", "x"])).isna().all()


# --- model: calendars ------------------------------------------------------------------------


@pytest.mark.parametrize("hpd", ["0", "", "-8", "abc"])
def test_day_hr_cnt_zero_blank_or_invalid_falls_back_to_the_default_hours(hpd):
    cal = [{"clndr_id": "Z", "clndr_name": "z", "day_hr_cnt": hpd, "week_hr_cnt": "40", "clndr_data": MON_FRI_8H}]
    s = snap([todo("A", clndr_id="Z")], calendars=cal)
    assert s.calendar("Z").hours_per_day == 8.0
    assert s.tasks.iloc[0]["remaining_d"] == 10.0


def test_tiny_day_hr_cnt_without_blob_falls_back_to_the_default_hours_with_a_warning():
    """AUDIT-XER-12: a day under one minute has no working time on the axis: the default hours apply."""
    cal = [{"clndr_id": "Z", "clndr_name": "zero", "day_hr_cnt": "1e-9", "week_hr_cnt": "40", "clndr_data": ""}]
    s = snap([todo("A", clndr_id="Z")], calendars=cal)
    assert s.calendar("Z").hours_per_day == 8.0 and s.tasks.iloc[0]["remaining_d"] == 10.0
    assert any("calendar Z (zero): day_hr_cnt 1e-09 is under one minute; 8.0 h/day used" in w for w in s.warnings)
    with time_limit(20):
        assert s.calendar("Z").work_hours(T("2026-03-02 08:00"), T("2026-03-09 08:00")) == 40


def test_unknown_clndr_id_with_a_lag_calendar_option_uses_the_project_hours_and_warns():
    s = snap(
        [todo("A", clndr_id="999"), todo("B", clndr_id="998")],
        [("A", "B", "FS", 8)],
        sched={"sched_calendar_on_relationship_lag": "rcal_Predecessor"},
    )
    assert s.options["lag_calendar"] == "rcal_Predecessor"
    assert s.relationships[["lag_hr", "lag_d"]].to_dict("records") == [{"lag_hr": 8, "lag_d": 1.0}]
    assert any("task calendars not in the file ['998', '999']" in w for w in s.warnings)
    assert (
        snap([todo("A")], sched={"sched_calendar_on_relationship_lag": "rcal_Bogus"}).options["lag_calendar"]
        == "rcal_Successor"
    )


def test_a_file_without_calendar_table_uses_the_standard_calendar_and_warns():
    lines = xer_text([todo("A")]).splitlines()
    a, b = lines.index("%T\tCALENDAR"), lines.index("%T\tPROJECT")
    s = build_snapshot(parse_text("\n".join(lines[:a] + lines[b:]), source="t.xer"))
    assert s.calendar().name == "Standard (Mon-Fri)" and s.tasks.iloc[0]["hours_per_day"] == 8.0
    assert any("task calendars not in the file" in w for w in s.warnings)


def test_wbs_seq_num_beyond_int64_keeps_the_order():
    """AUDIT-XER-13: seq_num is clipped to the six digits of the sort key before the integer conversion."""
    wbs = [
        wbs_row("10", "A", "1"),
        wbs_row("11", "B", "1e30"),
    ]  # fmt: skip
    s = snap([todo("A", wbs_id="10"), todo("B", wbs_id="11")], wbs=wbs)
    keys = s.tasks.set_index("task_code")["wbs_sort"]
    assert keys["A"] < keys["B"] == "999999", keys.to_dict()
    assert "test.xer: 1 PROJWBS seq_num value(s) outside 0..999999; clipped" in s.warnings


# --- calendar blob -------------------------------------------------------------------------


def test_blob_with_no_working_day_falls_back_to_an_inferred_week_not_a_loop():
    """A calendar whose DaysOfWeek has no period: from_row discards the blob and infers Mon-Fri.
    No infinite loop, no inf; whether discarding the blob is right is a question for the business."""
    cal = calendar(clndr_data(range(1, 8), []), week_hr_cnt="0")
    assert cal.from_data is False
    assert [len(day) for day in cal.week] == [1, 1, 1, 1, 1, 0, 0]
    with time_limit(10):
        assert cal.work_hours(T("2026-03-02 08:00"), T("2026-03-06 17:00")) == 40


def test_axis_on_a_calendar_without_working_time_fails_fast_with_a_value_error():
    week = tuple(() for _ in range(7))
    cal = WorkCalendar("E", "empty", 8.0, week, {}, from_data=False)
    with time_limit(20), pytest.raises(ValueError, match="no working time"):
        TimeAxis(cal, date(2026, 1, 1), date(2026, 12, 31))


def test_malformed_period_time_in_blob_falls_back_to_the_inferred_week_with_a_warning():
    """AUDIT-XER-14: a period time that is not HH:MM makes the blob unreadable; the workweek is inferred."""
    blob = clndr_data(range(2, 7), [("ab:cd", "09:00"), ("09:00", "17:00")])
    cal = [{"clndr_id": "G", "clndr_name": "g", "day_hr_cnt": "8", "week_hr_cnt": "40", "clndr_data": blob}]
    s = snap([todo("A", clndr_id="G")], calendars=cal)
    assert s.calendar("G").hours_per_day == 8.0 and s.calendar("G").from_data is False
    assert any("calendar G (g): clndr_data unreadable (ValueError:" in w for w in s.warnings)


def test_out_of_range_exception_serial_is_dropped_with_a_warning():
    """AUDIT-XER-14: an exception the axis cannot hold (serial 99999999 = year 275 760) is left out."""
    blob = (
        "(0||CalendarData()((0||DaysOfWeek()((0||2()((0||0(s|08:00|f|12:00)())))))"
        "(0||Exceptions()((0||0(d|99999999)())))))"
    )
    cal = [{"clndr_id": "G", "clndr_name": "g", "day_hr_cnt": "8", "week_hr_cnt": "40", "clndr_data": blob}]
    s = snap([todo("A", clndr_id="G")], calendars=cal)
    assert s.calendar("G").exceptions == {} and s.calendar("G").from_data is True
    outside = f"{EXCEPTION_FIRST_DATE}..{EXCEPTION_LAST_DATE}"
    dropped = f"calendar G (g): 1 calendar exception(s) dated outside {outside}; dropped"
    assert any(dropped in w for w in s.warnings)


def test_deeply_nested_blob_is_rejected_not_a_recursion_error():
    """AUDIT-XER-15: the tree parser stops past MAX_TREE_DEPTH levels; the blob reads as unreadable."""
    blob = "(0||CalendarData()((0||DaysOfWeek()(" + "(0||2()(" * 3000 + "))" * 3000 + "))))"
    notes: list[str] = []
    with time_limit(20):
        assert parse_clndr_data(blob, notes) is None
    assert len(notes) == 1 and notes[0].startswith("clndr_data unreadable (ValueError: nested deeper than 32 levels")


def test_unbalanced_and_truncated_blobs_return_none():
    assert parse_clndr_data("(0||CalendarData()((0||DaysOfWeek()((0||2()((0||0(s|08:00|f|12:00)())))") is None
    assert parse_clndr_data("") is None and parse_clndr_data(float("nan")) is None  # type: ignore[arg-type]


def test_a_5mb_flat_blob_parses_quickly():
    blob = "(0||CalendarData()((0||DaysOfWeek()(" + "(0||2()((0||0(s|08:00|f|12:00)())))" * 150_000 + "))))"
    with time_limit(30):
        week, _ = parse_clndr_data(blob)
    assert week[0] == ((480, 720),)


def test_same_exception_date_twice_last_one_wins():
    blob = (
        "(0||CalendarData()((0||DaysOfWeek()((0||2()((0||0(s|08:00|f|17:00)())))))"
        "(0||Exceptions()((0||0(d|46083)())(0||1(d|46083)((0||0(s|08:00|f|12:00)())))))))"
    )
    assert parse_clndr_data(blob)[1] == {date(2026, 3, 2): ((480, 720),)}


def test_an_exception_replaces_the_weekday_periods_instead_of_merging():
    blob = (
        "(0||CalendarData()((0||DaysOfWeek()((0||2()((0||0(s|08:00|f|17:00)())))))"
        "(0||Exceptions()((0||0(d|46083)((0||0(s|20:00|f|22:00)())))))))"
    )
    assert calendar(blob).periods(date(2026, 3, 2)) == ((1200, 1320),)


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        (("00:00", "00:00"), (0, 1440)),  # whole day
        (("12:00", "12:00"), (720, 1440)),  # zero-length reads as "until midnight"
        (("22:00", "02:00"), (1320, 1440)),  # a night shift is cut at midnight: 2 h, not 4 (question for the business)
        (("08:60", "09:00"), (540, 1440)),  # 08:60 = 09:00 = f, so "until midnight"
        (("25:00", "26:00"), (1500, 1440)),  # start after midnight: a negative-length period, dropped later by the axis
        (("-1:00", "09:00"), (-60, 540)),  # a start on the previous day is accepted
    ],
)
def test_period_boundaries(period, expected):
    assert parse_clndr_data(clndr_data(range(2, 3), [period]))[0][0] == (expected,)


def test_negative_period_start_counts_minutes_of_the_previous_day():
    cal = calendar(clndr_data(range(2, 7), [("-1:00", "09:00")]))
    assert cal.work_hours(T("2026-03-02 00:00"), T("2026-03-03 00:00")) == 10  # Monday: 23:00 Sunday -> 09:00
    assert cal.work_hours(T("2026-03-02 08:00"), T("2026-03-02 09:00")) == 1


# --- TimeAxis ---------------------------------------------------------------------------------


@pytest.fixture
def axis() -> TimeAxis:
    return calendar(MON_FRI_8H).axis()


def test_dates_before_the_axis_start_and_after_its_end_grow_it(axis):
    first, last = axis.first, axis.last
    assert axis.work(T("1900-01-01 08:00")) < 0 and axis.first < date(1900, 1, 1) < first
    assert axis.work(T("2100-12-31 17:00")) > 0 and axis.last > date(2100, 12, 31) > last
    assert axis.between(T("2099-12-31 08:00"), T("2099-12-31 17:00")) == 480  # a Thursday


def test_leap_days_and_the_non_leap_century(axis):
    assert axis.between(T("2024-02-28 17:00"), T("2024-03-01 08:00")) == 480  # Thu 2024-02-29 works
    assert axis.between(T("2028-02-28 17:00"), T("2028-03-01 08:00")) == 480  # Tue 2028-02-29
    assert axis.between(T("2100-02-28 17:00"), T("2100-03-01 08:00")) == 0  # 2100-02-28 is a Sunday; no 02-29
    assert axis.between(T("1900-01-01 08:00"), T("1900-01-05 17:00")) == 5 * 480  # Mon..Fri 1900


def test_work_is_the_inverse_of_at_on_working_instants_and_monotone(axis):
    stamps = pd.date_range("2026-01-01", "2026-12-31 23:59", freq="7min")
    work = axis.work_many(stamps)
    assert (np.diff(work) >= 0).all()
    for ts, w in zip(stamps[::13], work[::13], strict=True):
        if axis.is_working(ts):
            assert ts in (axis.at(w, finish=False), axis.at(w, finish=True))
        assert axis.work(ts) == w
    minutes = pd.date_range("2026-03-02 00:00", "2026-03-09 00:00", freq="1min")
    steps = np.diff(axis.work_many(minutes))
    assert set(np.unique(steps)) == {0, 1} and steps.sum() == 5 * 480  # strict +1 inside work, flat outside


def test_at_is_strictly_increasing_and_work_reads_it_back(axis):
    values = np.arange(0, 480 * 250, 7)
    finishes = [axis.at(w, finish=True) for w in values]
    starts = [axis.at(w, finish=False) for w in values]
    assert all(a < b for a, b in zip(finishes, finishes[1:], strict=False))
    assert all(a < b for a, b in zip(starts, starts[1:], strict=False))
    assert all(axis.work(f) == w for f, w in zip(finishes, values, strict=True))


def test_no_drift_over_10000_half_hour_steps_on_a_7_hour_calendar():
    axis = calendar(clndr_data(range(2, 7), [("08:00", "15:00")]), hpd="7").axis()
    t = T("2026-03-02 08:00")
    for _ in range(10_000):
        t = axis.add(t, 0.5 * 60, finish=True)
    assert axis.between(T("2026-03-02 08:00"), t) == 10_000 * 30
    assert t == T("2028-11-24 10:00")  # 300 000 min / 420 per day = 714 days + 2 h, exact
    t = T("2026-03-02 08:00")
    for _ in range(10_000):
        t = axis.add(t, 0.1 * 60, finish=True)  # 6 min: 0.1 h is not exact in binary
    assert axis.between(T("2026-03-02 08:00"), t) == 60_000


def test_fractional_minutes_are_rounded_half_to_even(axis):
    """``at`` rounds to the minute with Python's round(): 0.5 and 2.5 minutes go down, 1.5 goes up."""
    t = T("2026-03-02 08:00")
    assert axis.add(t, 0.5, finish=False) == t
    assert axis.add(t, 1.5, finish=False) == T("2026-03-02 08:02")
    assert axis.add(t, 2.5, finish=False) == T("2026-03-02 08:02")
    assert axis.between(T("2026-03-02 08:00:00"), T("2026-03-02 08:00:59")) == 0  # seconds are floored


def test_nan_or_infinite_minutes_raise_immediately(axis):
    t = T("2026-03-02 08:00")
    with pytest.raises(ValueError, match="NaN"):
        axis.add(t, float("nan"))
    with pytest.raises(OverflowError):
        axis.add(t, float("inf"))


def test_work_of_nat_raises_type_error_while_work_hours_returns_nan(axis):
    with pytest.raises(TypeError, match="NaT"):
        axis.work(pd.NaT)
    assert axis.work_many([T("2026-03-02 08:00"), pd.NaT]).tolist()[1] == 0  # documented: NaT -> 0
    assert np.isnan(axis.cal.work_hours(pd.NaT, T("2026-03-02 08:00")))


def test_a_duration_beyond_the_timestamp_range_fails_fast(axis):
    """AUDIT-XER-16: the axis stops at the Timestamp range with a ValueError instead of growing towards it."""

    def add_too_much():
        with pytest.raises(ValueError, match="date out of range"):
            axis.add(T("2026-03-02 08:00"), 1e8)  # 1e8 working minutes: ~800 years
        with pytest.raises(ValueError, match="date out of range"):
            axis.add(T("2026-03-02 08:00"), 1e9)  # more calendar minutes than the range holds: no growth at all
        with pytest.raises(ValueError, match="date out of range"):
            axis.add(T("2026-03-02 08:00"), -1e8)

    with time_limit(10):
        _, peak = peak_memory(add_too_much)
    assert peak < 20_000_000, f"peak {peak / 1e6:.0f} MB"  # before: 67 MB and ~7 s (1e9: 278 MB, ~28 s, year 6129)


def test_timestamps_at_the_nanosecond_bounds(axis):
    assert axis.work(T("2262-04-11")) > 0  # the last representable day is reachable
    assert axis.work(T("1677-09-22")) < 0  # and the first
    with pytest.raises(ValueError, match="date out of range"):
        axis.work(T("1677-09-21"))  # before Timestamp.min


def test_hours_to_days_by_zero_differs_between_scalar_and_series():
    with pytest.raises(ZeroDivisionError):
        hours_to_days(80, 0)
    assert hours_to_days(pd.Series([80.0]), pd.Series([0.0])).tolist() == [np.inf]
    assert np.isnan(hours_to_days(float("nan"), 8))
