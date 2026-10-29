import pytest

from xerscope.xer import XerError, parse_bytes, parse_text, read_xer

MINI = (
    "ERMHDR\t23.12\t2026-10-20\tProject\r\n"
    "%T\tPROJECT\r\n%F\tproj_id\tproj_short_name\tlast_recalc_date\r\n"
    "%R\t1\tDEMO\t2026-10-19 08:00\r\n"
    "%T\tTASK\r\n%F\ttask_id\tproj_id\ttask_code\ttask_name\ttotal_float_hr_cnt\r\n"
    "%R\t10\t1\tA100\tCoulage béton\t16\r\n"
    "%R\t11\t1\tA200\tShort row\r\n"  # trailing field dropped by the exporter
    "%E\r\n"
)


def test_tables_and_header():
    raw = parse_text(MINI, source="mini.xer")
    assert raw.version == "23.12"
    assert raw.export_date == "2026-10-20"
    assert set(raw.tables) == {"PROJECT", "TASK"}
    assert raw.table("TASK").shape == (2, 5)


def test_short_rows_are_padded_not_shifted():
    task = parse_text(MINI).table("TASK")
    assert task.loc[1, "task_name"] == "Short row"
    assert task.loc[1, "total_float_hr_cnt"] == ""


def test_cp1252_fallback():
    raw = parse_bytes(MINI.encode("cp1252"), source="ansi.xer")
    assert raw.encoding == "cp1252"
    assert raw.table("TASK").loc[0, "task_name"] == "Coulage béton"


def test_utf8_is_preferred():
    raw = parse_bytes(MINI.encode("utf-8"))
    assert raw.encoding == "utf-8-sig"
    assert raw.table("TASK").loc[0, "task_name"] == "Coulage béton"


def test_missing_table_is_empty():
    assert parse_text(MINI).table("TASKPRED").empty


def test_rejects_non_xer():
    with pytest.raises(XerError):
        parse_text("hello\nworld")


def test_reads_generated_file(sample_dir):
    raw = read_xer(next(sample_dir.glob("*.xer")))
    for name in ("PROJECT", "CALENDAR", "PROJWBS", "TASK", "TASKPRED", "TASKRSRC"):
        assert not raw.table(name).empty, name
