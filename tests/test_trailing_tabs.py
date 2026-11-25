"""XER-05 / XER-06: tabs an editor leaves after the end tag or after the last column refused a readable file.

Hand cases: ``%E`` followed by a tab still ends the file, and a ``%F`` line ending in two tabs names the same
columns; both read the same activities as the clean file. What stays refused: a file with no ``%E`` at all
(cut short, or still being copied), and a column named twice before the last one (it would shift them).
"""

import pandas as pd
import pytest
from xerkit import todo, xer_text

from xerscope.xer import load_snapshot
from xerscope.xer.parser import XerError

pytestmark = pytest.mark.oracle("property")

CLEAN = xer_text([todo("A1", target_drtn_hr_cnt="16"), todo("A2", target_drtn_hr_cnt="8")])


def _read(text: str):
    return load_snapshot(text.encode(), name="a.xer")


def _task_fields_line(text: str) -> int:
    lines = text.splitlines()
    return next(index for index, line in enumerate(lines) if line.startswith("%F") and "task_code" in line)


def _with_task_fields(text: str, edit) -> str:
    lines = text.splitlines()
    index = _task_fields_line(text)
    lines[index] = edit(lines[index])
    return "\n".join(lines) + "\n"


def test_a_tab_after_the_end_tag_still_ends_the_file():
    edited = CLEAN.replace("\n%E", "\n%E\t")
    pd.testing.assert_frame_equal(_read(edited).activities, _read(CLEAN).activities)


def test_two_tabs_after_the_last_column_name_no_column():
    edited = _with_task_fields(CLEAN, lambda line: line + "\t\t")
    pd.testing.assert_frame_equal(_read(edited).activities, _read(CLEAN).activities)


def test_a_file_with_no_end_tag_is_still_refused():
    with pytest.raises(XerError, match="no %E end line"):
        _read(CLEAN.replace("\n%E", "\n"))


def test_a_column_named_twice_before_the_last_one_is_still_refused():
    edited = _with_task_fields(CLEAN, lambda line: line.replace("\ttask_code", "\ttask_code\ttask_code", 1))
    with pytest.raises(XerError, match="names column task_code twice"):
        _read(edited)
