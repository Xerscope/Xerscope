"""Every chart and metric table carries its "How to read" popover, and every reading names its source.

Three checks, as tests/test_glossary.py checks the help of every card:

- static: each ``build_`` function of viz/charts.py gives its figure a reading key that
  analysis/explain.py READINGS knows, the Gantt has a reading, and no source is a web address
  or an unknown name;
- rendered: on each page of the demo series, the popovers labelled "How to read" are one per chart,
  one for the Gantt, and one per table whose key READINGS holds;
- mutation: a builder planted without a key is found by the static check, and ``ui.chart`` raises on
  a figure without one when XERSCOPE_STRICT_READINGS=1 (set by conftest).
"""

import ast
from pathlib import Path

import plotly.graph_objects as go
import pytest
from conftest import read_folder
from streamlit.testing.v1 import AppTest
from test_page_golden import APP, PAGES

import xerscope
from xerscope.analysis.explain import READINGS
from xerscope.app import ui

pytestmark = pytest.mark.oracle("characterization")

PACKAGE = Path(xerscope.__file__).parent
CHARTS = PACKAGE / "viz" / "charts.py"
READING_LABEL = "How to read"
TABLE_KEY_PREFIXES = (
    "params_",
    "flag_",
    "table_",
    "debug_",
)  # one table per check or per block: the key holds its name

# Names a source may give: the standards and documents the repository already cites.
KNOWN_SOURCES = (
    "P6",
    "xerscope",
    "EIA-748",
    "Last Planner",
    "AACE RP 29R-03",
    "DCMA 14-Point",
    "TOML",
    "docs/formulas.md",
    "`source`",  # the field of a check in standards/*.toml
    "settings_table",
    "weekly_change_matrix",
    "export_tables",
)


def reading_keys(builder: ast.FunctionDef) -> list[object]:
    """The reading key of each ``_with_house_style(figure, key, ...)`` call of ``builder``."""
    calls = [node for node in ast.walk(builder) if isinstance(node, ast.Call)]
    styled = [call for call in calls if getattr(call.func, "id", "") == "_with_house_style"]
    keyed = [call.args[1] for call in styled if len(call.args) > 1 and isinstance(call.args[1], ast.Constant)]
    return [key.value for key in keyed]


def builders(source: str) -> list[ast.FunctionDef]:
    """Every ``def build_...`` of ``source``."""
    functions = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)]
    return [function for function in functions if function.name.startswith("build_")]


def builders_without_reading(source: str) -> list[str]:
    """The names of the builders of ``source`` that give their figure no reading key READINGS knows."""
    missing = []
    for builder in builders(source):
        keys = reading_keys(builder)
        if len(keys) != 1 or keys[0] not in READINGS:
            missing.append(builder.name)
    return missing


def test_every_builder_gives_its_figure_a_reading_key():
    assert len(builders(CHARTS.read_text(encoding="utf-8"))) == 10
    assert builders_without_reading(CHARTS.read_text(encoding="utf-8")) == []


def test_a_builder_planted_without_a_reading_key_is_found():
    planted = "def build_planted(frame):\n    return go.Figure()\n"
    assert builders_without_reading(CHARTS.read_text(encoding="utf-8") + planted) == ["build_planted"]


def test_the_gantt_has_a_reading():
    assert READINGS["gantt"].how


def test_no_source_is_a_web_address():
    addresses = [key for key, reading in READINGS.items() if "http" in reading.source or "www." in reading.source]
    assert not addresses


def test_every_reading_has_a_source_the_repository_names():
    unnamed = [key for key, reading in READINGS.items() if not any(name in reading.source for name in KNOWN_SOURCES)]
    assert not unnamed


def test_every_known_source_is_written_somewhere_in_the_repository():
    text = " ".join(path.read_text(encoding="utf-8") for path in PACKAGE.rglob("*") if path.suffix in {".py", ".toml"})
    assert [name for name in KNOWN_SOURCES if name not in text] == []


def test_a_figure_without_a_reading_key_raises_when_readings_are_strict(monkeypatch):
    monkeypatch.setenv(ui.STRICT_READINGS, "1")
    with pytest.raises(ValueError):
        ui.chart(go.Figure())


# Tables that are no metric table: the Files and baseline window's per-file settings.
TABLES_WITHOUT_READING = {"baseline_per_file"}


def tables_without_reading(source: str) -> list[str]:
    """The ``key`` of each ``ui.table`` call of ``source`` that passes no ``reading``, or a constant one
    READINGS does not hold. A table drawn only on a series the demo lacks is caught here, not on the page."""
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
    tables = [call for call in calls if getattr(call.func, "attr", "") == "table"]
    tables = [call for call in tables if getattr(getattr(call.func, "value", None), "id", "") == "ui"]
    missing = []
    for call in tables:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        key = ast.unparse(keywords["key"]) if "key" in keywords else "?"
        reading = keywords.get("reading")
        if reading is None or (isinstance(reading, ast.Constant) and reading.value not in READINGS):
            missing.append(key.strip("'\""))
    return missing


def test_every_table_of_the_app_passes_a_reading():
    files = sorted((PACKAGE / "app").rglob("*.py"))
    missing = {key for path in files for key in tables_without_reading(path.read_text(encoding="utf-8"))}
    assert missing == TABLES_WITHOUT_READING


def test_a_table_planted_without_a_reading_is_found():
    planted = 'ui.table(frame, key="planted")\nui.table(frame, key="named", reading="not_a_reading")\n'
    assert tables_without_reading(planted) == ["planted", "named"]


@pytest.fixture(scope="module")
def pages(sample_dir):
    """Every element of each page on the demo series, visited in the order of the menu, and the ``key`` and
    ``reading`` of each ``ui.table`` call the page made: a dataframe's key is not in the element."""
    tables = {}
    real_table = ui.table

    def recording_table(frame, *, key, reading=None, **kwargs):
        tables[current_page].append((key, reading))
        return real_table(frame, key=key, reading=reading, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("XERSCOPE_DATA", str(sample_dir))
        patch.delenv("XERSCOPE_BASELINE", raising=False)
        patch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
        patch.setattr(ui, "table", recording_table)
        app = read_folder(AppTest.from_file(APP, default_timeout=180).run())
        elements = {}
        for current_page in PAGES:
            tables[current_page] = []
            app.switch_page(f"views/{current_page}.py").run()
            assert not app.exception, (current_page, [error.value for error in app.exception])
            elements[current_page] = list(app.main)
        yield elements, tables


def has_reading(key: str) -> bool:
    """Whether a table of this key is one appendix E lists: the key itself, or a prefix when one table is
    drawn per check or per block."""
    return key in READINGS or key.startswith(TABLE_KEY_PREFIXES)


@pytest.mark.parametrize("page", PAGES)
def test_a_table_the_readings_list_has_its_popover(pages, page):
    _, tables = pages
    unread = [key for key, reading in tables[page] if has_reading(key) and reading is None]
    assert not unread


@pytest.mark.parametrize("page", PAGES)
def test_a_page_has_one_popover_per_chart_per_gantt_and_per_table_with_a_reading(pages, page):
    elements, tables = pages
    popovers = [
        element
        for element in elements[page]
        if element.type == "popover" and element.proto.popover.label == READING_LABEL
    ]
    charts = [element for element in elements[page] if element.type == "plotly_chart"]
    gantts = [element for element in elements[page] if element.type == "bidi_component"]
    read_tables = [key for key, reading in tables[page] if reading is not None]
    assert len(popovers) == len(charts) + len(gantts) + len(read_tables)
