"""The scorer of the P6 held-out corpus schedules each case with the float type P6 held.

Source: the corpus' own protocol (validation/held-out/H30/PROTOCOL.md: "p6_imported_overlay.js lays
that float type over the case: the record's sched_float_type, or, in a record made before it, the
difference the record names") and H28/RESULT.md: saving the Schedule Options dialog in P6 stores
FT_SS for an imported FT_Start. P6's values were computed under the stored type, so a case scored
under the file's type compares two different floats.
"""

import json

import pytest
from xerkit import hours, todo, xer_text

from xerscope.verify.p6_corpus import _apply_p6_import, float_type_p6_held
from xerscope.xer import read_xer

pytestmark = pytest.mark.oracle("standard")


def float_type_after_overlay(tmp_path, record: dict | None) -> str:
    """The float type of a case written with FT_Start once the record of what P6 held is laid over it."""
    case = tmp_path / "case.xer"
    case.write_text(xer_text([todo("A", **hours(8))], sched={"sched_float_type": "FT_Start"}), encoding="cp1252")
    raw = read_xer(case)
    record_file = tmp_path / "case.json"
    if record is not None:
        record_file.write_text(json.dumps(record), encoding="utf-8")
    _apply_p6_import(raw, record_file)
    return raw.tables["SCHEDOPTIONS"]["sched_float_type"].iloc[0]


def test_the_recorded_float_type_is_laid_over_the_case(tmp_path):
    """From H30 the record holds the stored code itself."""
    assert float_type_after_overlay(tmp_path, {"sched_float_type": "FT_SS"}) == "FT_SS"


def test_an_older_record_names_the_float_type_among_its_differences(tmp_path):
    """H28 and H29: the record lists what differs between the file and P6, the float type among it."""
    differences = [
        "TASK A1040 remain_drtn_hr_cnt: xer '40' p6 3.0",
        "SCHEDOPTIONS sched_float_type: xer 'FT_Start' p6 'FT_SS'",
    ]
    assert float_type_after_overlay(tmp_path, {"differences": differences, "sched_float_type": None}) == "FT_SS"


def test_the_recorded_code_wins_over_a_difference_line(tmp_path):
    record = {"sched_float_type": "FT_Min", "differences": ["SCHEDOPTIONS sched_float_type: xer 'FT_Start' p6 'FT_SS'"]}
    assert float_type_after_overlay(tmp_path, record) == "FT_Min"


@pytest.mark.parametrize("record", [{}, {"differences": ["TASK A1040 remain_drtn_hr_cnt: xer '40' p6 3.0"]}, None])
def test_a_case_keeps_its_float_type_when_the_record_names_none(tmp_path, record):
    """No code and no difference line, or no record at all: the file's float type stands."""
    assert float_type_after_overlay(tmp_path, record) == "FT_Start"


def test_float_type_p6_held_reads_nothing_into_other_differences():
    assert float_type_p6_held({"differences": ["CALENDAR H30-1 Mon-Sat 08:00-16:00: xer 'x' p6 'y'"]}) is None
