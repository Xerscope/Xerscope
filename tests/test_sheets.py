"""The calculation sheets (src/xerscope/sheets/<standard>/<id>.md) against the code and the standard.

A sheet is written by hand, so these checks keep it from drifting: one sheet per metric, the
metric's real target and parameter values, XER fields and codes that the model reads, test
names that exist, links to the documentation sites only.
"""

import re
from pathlib import Path

import pytest

import xerscope
from xerscope.analysis import builtin_standards
from xerscope.analysis.audit import sheet

PACKAGE = Path(xerscope.__file__).parent
MODEL = (PACKAGE / "xer" / "model.py").read_text(encoding="utf-8")
TESTS = "\n".join(path.read_text(encoding="utf-8") for path in Path(__file__).parent.glob("test_*.py"))
WITH_SHEETS = ["P6"]
SOURCES = {"docs.oracle.com", "tensix.com"}
METRICS = [(standard_id, metric) for standard_id in WITH_SHEETS for metric in builtin_standards()[standard_id].metrics]


def test_one_sheet_per_metric_and_no_other():
    for standard_id in WITH_SHEETS:
        written = {path.stem for path in (PACKAGE / "sheets" / standard_id).glob("*.md")}
        assert written == {metric.id for metric in builtin_standards()[standard_id].metrics}


@pytest.mark.parametrize(("standard_id", "metric"), METRICS, ids=[m.id for _s, m in METRICS])
def test_sheet_matches_the_standard_and_the_code(standard_id, metric):
    text = sheet(standard_id, metric)
    assert text is not None
    assert text.startswith(f"# {metric.id} · {metric.name}\n"), "title = id · name of the TOML"
    assert f"`{metric.threshold_label}`" in text, "the target written in the TOML"
    for name, value in metric.params.items():
        assert f"{name} = {value:g}" in text, f"parameter {name} with the TOML value"
    for table, column in re.findall(r"`(TASK|TASKPRED|TASKRSRC|PROJECT|PROJCOST)\.(\w+)`", text):
        assert f'"{column}"' in MODEL, f"{table}.{column} is not a field the model reads"
    for code in re.findall(r"`((?:TK|TT|PR|CS)_\w+)`", text):
        assert f'"{code}"' in MODEL, f"{code} is not a code the model knows"
    for test_name in re.findall(r"`(test_\w+)`", text):
        assert f"def {test_name}(" in TESTS, f"{test_name} does not exist"
    hosts = set(re.findall(r"\]\(https://([^/)]+)", text))
    assert hosts <= SOURCES, hosts - SOURCES


def test_no_sheet_for_a_metric_that_is_not_the_built_in_one():
    """An uploaded standard reusing the id P6 with another rule gets no built-in sheet."""
    import dataclasses

    metric = builtin_standards()["P6"]["P6-04"]
    assert sheet("P6", dataclasses.replace(metric, rule="p6_06_large_float")) is None
    assert sheet("CUSTOM", metric) is None
