"""The PPC page filtered on a P6 activity code: what its counts and its tables show.

Week 1 of the series below (W-1 = 03-02, W = 03-09), Discipline of each task in each file:

    task   in W-1    in W     what happens
    A      CIV       CIV      starts and finishes in the week, as planned (kept)
    B      CIV       CIV      planned 03-03..03-06, not done in W (not kept)
    C      MEC       MEC      starts and finishes in the week (kept)
    T      CIV       MEC      starts and finishes in the week, a day early (kept); changes discipline
    M      CIV       MEC      finish milestone planned 03-05, done 03-04; changes discipline
    N      -         MEC      new in W, started 03-04: unplanned work

A commitment belongs to the discipline W-1 gave it; the progress, the variances and the unplanned work
to the one W gives. The variance table lists the tasks whose dates moved: B (planned a week
later), T and M (earlier) only. Counts of week 1 (milestones and N out of them): starts A, B, C, T = 4, kept 3;
finishes 4, kept 3; PPC W/W-1 = 6 / 8. CIV in W-1 = A, B, T: 4 / 6. MEC in W-1 = C: 2 / 2.
"""

import os
import tempfile
from pathlib import Path

import pytest
from conftest import read_folder
from streamlit.testing.v1 import AppTest
from xerkit import FM, todo, xer_text

import xerscope

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
DD0, DD1, DD2 = "2026-03-02 08:00", "2026-03-09 08:00", "2026-03-16 08:00"
DONE = dict(act_start_date="2026-03-03 08:00", act_end_date="2026-03-06 17:00", status_code="TK_Complete")
FIRST_CODES = [("A", "CIV"), ("B", "CIV"), ("C", "MEC"), ("T", "CIV"), ("M", "CIV")]
SECOND_CODES = [("A", "CIV"), ("B", "CIV"), ("C", "MEC"), ("T", "MEC"), ("M", "MEC"), ("N", "MEC")]


def plan(start: str, end: str) -> dict:
    return dict(early_start_date=f"2026-03-{start} 08:00", early_end_date=f"2026-03-{end} 17:00")


def write(folder: str, name: str, tasks: list[dict], assigned: list[tuple[str, str]], data_date: str) -> None:
    codes = [(task, "Discipline", value) for task, value in assigned]
    (Path(folder) / name).write_text(xer_text(tasks, codes=codes, data_date=data_date), encoding="utf-8")


@pytest.fixture
def ppc_page():
    folder = tempfile.mkdtemp()
    first = [todo(code, **plan("03", "06")) for code in "ABCT"]
    first.append(todo("M", **FM, early_end_date="2026-03-05 17:00"))
    early = dict(DONE, act_end_date="2026-03-05 17:00")  # one day before the plan
    second = [todo("A", **DONE), todo("B", **plan("10", "13")), todo("C", **DONE), todo("T", **early)]
    second.append(
        todo("M", **FM, early_end_date="2026-03-05 17:00", act_end_date="2026-03-04 17:00", status_code="TK_Complete")
    )
    second.append(todo("N", act_start_date="2026-03-04 08:00", status_code="TK_Active"))
    third = [todo(code, **plan("17", "20")) for code in "ABCTMN"]
    write(folder, "a.xer", first, FIRST_CODES, DD0)
    write(folder, "b.xer", second, SECOND_CODES, DD1)
    write(folder, "c.xer", third, SECOND_CODES, DD2)
    os.environ["XERSCOPE_DATA"] = folder
    os.environ.pop("XERSCOPE_BASELINE", None)
    at = read_folder(AppTest.from_file(APP, default_timeout=120).run())
    at.switch_page("views/ppc.py").run()
    at.selectbox(key="ppc_week").set_value(at.selectbox(key="ppc_week").options[0]).run()
    assert not at.exception
    return at


def counts_line(at) -> str:
    return next(c.value for c in at.caption if "PPC Finish = " in c.value and "PPC W/W−1 = " in c.value)


def shown(at) -> dict[str, set[str]]:
    """The Activity IDs in each table of the page; a table that is not drawn (no row) is empty."""
    kinds = {
        "commitments and milestones": "commitment",
        "unplanned": "act_end_date",
        "progress": "pct_prev",
        "variances": "start_var_w1",
    }
    codes = {kind: set() for kind in kinds}
    for table in at.dataframe:
        for kind, column in kinds.items():
            if column in table.value.columns and not (kind == "unplanned" and "commitment" in table.value.columns):
                codes[kind] |= set(table.value["task_code"])
    return codes


def pick(at, text: str) -> None:
    at.selectbox[[box.label for box in at.selectbox].index("Task code (P6 activity code)")].set_value(
        "Discipline"
    ).run()
    at.multiselect(key="ppc_code_values:Discipline").set_value([text]).run()
    assert not at.exception


def test_without_filter_the_page_shows_every_task(ppc_page):
    assert "PPC W/W−1 = 6 / 8 = " in counts_line(ppc_page)
    assert shown(ppc_page) == {
        "commitments and milestones": {"A", "B", "C", "T", "M"},
        "unplanned": {"N"},
        "progress": {"A", "C", "T", "M"},
        "variances": {"B", "T", "M"},
    }


def test_civil_keeps_what_each_block_reads_in_its_own_update(ppc_page):
    """CIV: commitments of W-1 (A, B, T and the milestone M); progress and variances of W (A, B)."""
    pick(ppc_page, "civ")
    assert "PPC W/W−1 = 4 / 6 = " in counts_line(ppc_page)
    assert shown(ppc_page) == {
        "commitments and milestones": {"A", "B", "T", "M"},
        "unplanned": set(),
        "progress": {"A"},
        "variances": {"B"},
    }


def test_mechanics_keeps_what_each_block_reads_in_its_own_update(ppc_page):
    """MEC: commitments of W-1 (C only: T and M were CIV); unplanned N, progress and variances of W."""
    pick(ppc_page, "mec")
    assert "PPC W/W−1 = 2 / 2 = " in counts_line(ppc_page)
    assert shown(ppc_page) == {
        "commitments and milestones": {"C"},
        "unplanned": {"N"},
        "progress": {"C", "T", "M"},
        "variances": {"T", "M"},
    }
