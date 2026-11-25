"""Every widget of the app carries a tooltip: what it does and when to use it.

The pages and the Files window are read with Streamlit's headless AppTest; the widgets that only appear
after a click or an upload (the Ask suggestions, the audit parameters, the debug export mapping) are
reached by reading every widget call of ``app/``.
"""

import ast
from pathlib import Path

import pytest
from conftest import open_files, read_folder
from streamlit.testing.v1 import AppTest
from test_app import APP, _ok
from test_glossary import PAGES

import xerscope

pytestmark = pytest.mark.oracle("characterization")

WIDGET_ELEMENTS = (
    "selectbox",
    "multiselect",
    "button",
    "toggle",
    "checkbox",
    "text_input",
    "number_input",
    "file_uploader",
    "radio",
    "button_group",  # st.segmented_control
    "date_input",
    "download_button",
)
WIDGET_CALLS = {*WIDGET_ELEMENTS, "segmented_control"}  # st.data_editor takes no help: its columns do
APP_FOLDER = Path(xerscope.__file__).parent / "app"


@pytest.fixture
def series(sample_dir, monkeypatch):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    return read_folder(AppTest.from_file(APP, default_timeout=120).run())


def widgets_of_kind_without_help(app: AppTest, kind: str) -> list[str]:
    """The key or label of each widget of one kind that has no help."""
    return [f"{kind} {widget.key or widget.label}" for widget in getattr(app, kind) if not widget.help]


def widgets_without_help(app: AppTest) -> list[str]:
    """The key or label of each widget on the page, in the sidebar or the window, that has no help."""
    missing = []
    for kind in WIDGET_ELEMENTS:
        missing.extend(widgets_of_kind_without_help(app, kind))
    return missing


def has_help(call: ast.Call) -> bool:
    """Whether the call passes a ``help`` keyword."""
    return "help" in {keyword.arg for keyword in call.keywords}


def widget_calls_without_help(path: Path) -> list[str]:
    """The place of each widget call in one file that passes no help."""
    missing = []
    for node in ast.walk(ast.parse(path.read_text())):
        is_widget_call = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        if is_widget_call and node.func.attr in WIDGET_CALLS and not has_help(node):
            missing.append(f"{path.relative_to(APP_FOLDER)}:{node.lineno} {node.func.attr}")
    return missing


def test_every_widget_of_every_page_has_a_help(series):
    missing = {}
    for page in PAGES:
        series.switch_page(page).run()
        _ok(series)
        missing[page] = widgets_without_help(series)
    assert {page: names for page, names in missing.items() if names} == {}


def test_every_widget_of_the_files_window_has_a_help(series):
    open_files(series)
    _ok(series)
    assert any(button.key == "files_done" for button in series.button)
    assert widgets_without_help(series) == []


def test_every_widget_call_of_the_app_passes_a_help():
    missing = []
    for path in sorted(APP_FOLDER.rglob("*.py")):
        missing.extend(widget_calls_without_help(path))
    assert missing == []
