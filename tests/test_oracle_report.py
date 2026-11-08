"""The ``oracle`` marker: kinds checked at collection (conftest.py), counted by scripts/oracle_report.py."""

import importlib.util
import subprocess
import sys
from collections import Counter
from pathlib import Path

import conftest
import pytest

SCRIPTS = Path(__file__).parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location("oracle_report", SCRIPTS / "oracle_report.py")
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


class Item:
    def __init__(self, nodeid, *marks):
        self.nodeid, self.marks = nodeid, [m.mark for m in marks]

    def iter_markers(self, name):
        return (m for m in self.marks if m.name == name)


def test_known_kinds_and_unmarked_tests_pass_collection():
    items = [Item(f"t{k}", pytest.mark.oracle(k)) for k in conftest.ORACLE_KINDS] + [Item("plain")]
    conftest.pytest_collection_modifyitems(None, items)


@pytest.mark.parametrize(
    "mark",
    [pytest.mark.oracle("P6"), pytest.mark.oracle("golden"), pytest.mark.oracle(), pytest.mark.oracle(kind="p6")],
)
def test_an_unknown_or_malformed_kind_stops_collection(mark):
    with pytest.raises(pytest.UsageError, match="tests/x.py::t"):
        conftest.pytest_collection_modifyitems(None, [Item("tests/x.py::t", mark)])


def test_tally_counts_unmarked_tests_apart():
    assert report.tally(["p6", "p6", None, "mpxj"]) == Counter({"p6": 2, "mpxj": 1, report.UNMARKED: 1})


def test_render_lists_kinds_then_unmarked_then_total():
    assert report.render(Counter({"p6": 3, report.UNMARKED: 1})).splitlines() == [
        "| oracle | tests | share |",
        "|---|---:|---:|",
        "| p6 | 3 | 75% |",
        "| (none) | 1 | 25% |",
        "| total | 4 | |",
    ]


def test_render_of_nothing_collected():
    assert report.render(Counter()).splitlines()[-2:] == ["| (none) | 0 | - |", "| total | 0 | |"]


def test_collect_reads_the_marker_of_each_collected_test(tmp_path):
    (tmp_path / "test_a.py").write_text(
        "import pytest\n\n@pytest.mark.oracle('mpxj')\ndef test_x():\n    pass\n\ndef test_y():\n    pass\n"
    )
    code = (
        f"import sys, pathlib; sys.path.insert(0, {str(SCRIPTS)!r}); import oracle_report; "
        f"print(sorted(map(str, oracle_report.collect(pathlib.Path({str(tmp_path)!r})))))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "['None', 'mpxj']"
