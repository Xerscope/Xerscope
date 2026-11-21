"""The table contract of ``app/ui.py``: a column is labelled once, in ``COLUMNS``, and an empty table says why.

- labels: on every page of the demo series, each column of each table is labelled as ``COLUMNS`` labels it, or
  is one of the listed exceptions (a label that means another thing on one page, a column named by its date);
- empty tables: a page never draws a bare empty grid; the Debug page keeps every grid, its header being the
  information, and writes under each empty one why it is empty;
- ``ui.table(empty=...)``: the page's sentence replaces the grid of a frame without a row;
- the Gantt task picker writes "Task ID · name" as ``ui.code_label`` does.
"""

import json
import re
from itertools import chain

import pandas as pd
import pytest
from conftest import read_folder
from streamlit.testing.v1 import AppTest
from test_page_golden import APP, PAGES

from xerscope.app import ui

pytestmark = pytest.mark.oracle("characterization")

# Columns whose label is not the one of COLUMNS on the page that draws them: the key is the column, the value the
# labels it carries by decision (each one has its comment in the page's source).
LISTED_LABELS = {
    "data_date": {"Week ending"},  # the PPC tables: the week a row closes
    "lookahead_date": {"Plan read"},
    "kept": {"Kept (starts + finishes)"},  # PPC weeks: a count; in the commitments table, yes / no
    "committed": {"Committed (starts + finishes)"},
    "slip_wd": {"Slip since first (wd)"},  # Milestones; in COLUMNS, Delay analysis's slip due to progress
    "found": {
        "Found (report)",
        "Found (xerscope)",
    },  # Schedule health: the editor types the P6 report's, the comparison reads ours
    "total": {"Total (report)", "Total (xerscope)"},
    "rows": {"Rows"},  # Export; Debug block 7 holds a rows column of text
}
# Column names that are not field names and are not in COLUMNS: headers a page writes itself, for a table that
# is not a list of tasks.
LISTED_NAMES = {"P6 column", "this update", "set by"}  # Earned value's calculation; the parameters table
DATE_NAME = re.compile(r"\d{4}-\d{2}-\d{2}")  # a column per update, named by its status date
FIELD_NAME = re.compile(r"[A-Za-z0-9_.\-]+")


def dataframes(block):
    """Every ``dataframe`` element under ``block``, in the order of the page, with its parent's children."""
    found = []
    for element in getattr(block, "children", {}).values():
        if element.type == "dataframe":
            found.append(element)
        found += dataframes(element)
    return found


def expected_labels(name: str) -> set[str]:
    """The labels a column named ``name`` may carry: COLUMNS', the field name written out, a listed one."""
    default = str(name).replace("_", " ").capitalize()
    known = {COLUMNS_LABELS[name]} if name in COLUMNS_LABELS else {default}
    return known | LISTED_LABELS.get(name, set()) | {str(name)}  # the field name itself: a table read beside P6


COLUMNS_LABELS = {name: label for name, (label, _kind, _help) in ui.COLUMNS.items()}


@pytest.fixture(scope="module")
def pages(sample_dir):
    """Each page of the demo series, visited in the order of the menu: its dataframes and their Streamlit config."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("XERSCOPE_DATA", str(sample_dir))
        patch.delenv("XERSCOPE_BASELINE", raising=False)
        patch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
        patch.setenv("XERSCOPE_DEBUG_PAGE", "1")
        app = read_folder(AppTest.from_file(APP, default_timeout=180).run())
        visited = {}
        for page in PAGES:
            app.switch_page(f"views/{page}.py").run()
            assert not app.exception, (page, [error.value for error in app.exception])
            visited[page] = app.main
        yield visited, app


def column_labels(element) -> dict:
    """The label each column of one dataframe element carries, as Streamlit received it (None: the field name)."""
    config = json.loads(element.proto.columns)
    return {
        name: setting.get("label") if isinstance(setting, dict) else setting
        for name, setting in config.items()
        if name != "_index"
    }


def mistake_in(page: str, name: str, label: str | None) -> str | None:
    """What is wrong with the column ``name`` labelled ``label`` on ``page``, or None."""
    is_field_name = name in COLUMNS_LABELS or FIELD_NAME.fullmatch(name) or DATE_NAME.fullmatch(name)
    if not (is_field_name or name in LISTED_NAMES):
        return f"{page}: column {name!r} is a label written by the page, not a field name"
    if label is None or label in expected_labels(name) or DATE_NAME.fullmatch(label):
        return None
    return f"{page}: {name!r} is labelled {label!r}, COLUMNS has {COLUMNS_LABELS.get(name)!r}"


@pytest.mark.parametrize("page", PAGES)
def test_each_column_of_each_table_is_labelled_as_columns_labels_it(pages, page):
    visited, _ = pages
    labelled = chain.from_iterable(column_labels(element).items() for element in dataframes(visited[page]))
    mistakes = [mistake_in(page, name, label) for name, label in labelled]
    assert [mistake for mistake in mistakes if mistake] == []


def siblings(block):
    """The children of ``block`` and of every container under it, each as a list in the order drawn."""
    children = list(getattr(block, "children", {}).values())
    yield children
    for child in children:
        yield from siblings(child)


@pytest.mark.parametrize("page", [page for page in PAGES if page != "debug"])
def test_a_page_other_than_debug_draws_no_empty_grid(pages, page):
    visited, _ = pages
    assert [element for element in dataframes(visited[page]) if element.value.empty] == []


def empty_grids_with_followers(children: list) -> list:
    """Each empty dataframe among ``children`` with the element drawn right after it (a list of zero or one)."""
    found = []
    for position, element in enumerate(children):
        if element.type == "dataframe" and element.value.empty:
            found.append((element, children[position + 1 : position + 2]))
    return found


def is_caption(following: list) -> bool:
    """Whether the element drawn after a grid is a caption with a sentence."""
    return bool(following) and following[0].type == "caption" and bool(following[0].value)


def test_debug_keeps_its_six_empty_grids_and_says_under_each_why_it_is_empty(pages):
    visited, _ = pages
    empty_grids = list(chain.from_iterable(empty_grids_with_followers(row) for row in siblings(visited["debug"])))
    assert len(empty_grids) == 6
    assert [grid.value.columns for grid, following in empty_grids if not is_caption(following)] == []


def _empty_table_script():
    import pandas as pd

    from xerscope.app import ui

    ui.table(pd.DataFrame({"task_code": []}), key="t_said", empty="Nothing was looked for here.")
    ui.table(pd.DataFrame({"task_code": []}), key="t_bare")
    ui.table(pd.DataFrame({"task_code": ["A1"]}), key="t_full", empty="Never shown: the frame has a row.")


def test_a_table_given_a_sentence_draws_it_in_place_of_an_empty_grid_only():
    app = AppTest.from_function(_empty_table_script, default_timeout=60).run()
    assert not app.exception
    assert [caption.value for caption in app.caption] == ["Nothing was looked for here."]
    assert [len(element.value) for element in app.dataframe] == [0, 1]  # the table without a sentence keeps its grid


def test_a_column_carries_its_sentence_then_the_acronyms_of_its_label():
    frame = pd.DataFrame({"task_name": ["x"], "spi_4w": [1.0], "removed": [3]})
    config = ui.column_config(frame)
    assert config["task_name"]["help"].startswith("The task's name as the file writes it")
    assert config["spi_4w"]["help"].startswith("SPI: Schedule Performance Index")  # no sentence: the glossary only
    raw = ui.column_config(frame, raw_labels=True)
    assert raw["task_name"]["help"] is None  # a field name can mean another thing in a table read beside P6


def test_the_columns_the_pages_use_are_all_in_columns():
    """Appendix F's list of the keys COLUMNS lacked; ``rows`` stays out: Debug block 7 holds it as text."""
    keys = [
        "first_forecast",
        "latest_forecast",
        "slip_wd",
        "last_week_wd",
        "total",
        "kinds",
        "step",
        "removed",
        "left",
        "finish_before_replanning",
        "replanning_wd",
        "residual_wd",
        "period_wd",
        "engine_gap_wd",
        "longest_path_float_d",
        "matched",
        "added",
        "held_by",
        "finish_case",
        "found_exp",
        "total_exp",
        "match",
        "flagged",
        "columns",
        "table",
    ]
    assert [key for key in keys if key not in ui.COLUMNS] == []


def test_the_task_picker_of_the_gantt_writes_the_task_id_and_its_name(pages, store):
    _, app = pages
    app.switch_page("views/gantt.py").run()
    tasks = store.latest.activities
    expected = [f"{code} · {name}" for code, name in zip(tasks["task_code"], tasks["task_name"], strict=True)]
    options = app.selectbox(key="gantt_task_pick").options
    assert len(options) > 20 and set(options) <= set(expected)  # the page's default filters leave some out
