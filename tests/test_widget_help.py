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


# Helps built by the code, not written as a literal: reviewed by reading each (file, kind of expression).
# downloads.py and ui.py pass a help_text parameter or variable built from the label (ui._filter_help),
# files_window.py the details line of a file, loading.py an f-string of the projects read, state.py the
# joined lines of the Files button.
REVIEWED_COMPUTED_HELP = {
    ("downloads.py", "Name"),
    ("files_window.py", "Name"),
    ("ui.py", "Name"),
    ("loading.py", "IfExp"),
    ("state.py", "Call"),
}


def has_help(call: ast.Call, file_name: str = "") -> bool:
    """Whether the call passes a help that says something: a literal text that is not blank, an
    f-string with a literal part that is not blank, or an expression listed in REVIEWED_COMPUTED_HELP.
    help=None, help="" and a missing ``help`` do not count."""
    helps = [keyword.value for keyword in call.keywords if keyword.arg == "help"]
    if not helps:
        return False
    value = helps[0]
    if isinstance(value, ast.Constant):
        return isinstance(value.value, str) and bool(value.value.strip())
    if isinstance(value, ast.JoinedStr):
        return any(isinstance(part, ast.Constant) and part.value.strip() for part in value.values)
    return (file_name, type(value).__name__) in REVIEWED_COMPUTED_HELP


def widget_calls_without_help_in(source: str, file_name: str) -> list[str]:
    """The place of each widget call in ``source`` that passes no help: ``st.button(...)`` and a bare
    ``button(...)`` (from streamlit import button) alike; a call through ``**kwargs`` passes none
    unless it also names ``help``."""
    missing = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name in WIDGET_CALLS and not has_help(node, file_name):
            missing.append(f"{file_name}:{node.lineno} {name}")
    return missing


def widget_calls_without_help(path: Path) -> list[str]:
    """The place of each widget call in one file that passes no help."""
    return widget_calls_without_help_in(path.read_text(), str(path.relative_to(APP_FOLDER)))


@pytest.mark.parametrize(
    ("call", "accepted"),
    [
        ('st.button("x", help="Back to the standard\'s values")', True),
        ('st.button("x", help=f"Back to {name}")', True),
        ('st.button("x", help="")', False),
        ('st.button("x", help="   ")', False),
        ('st.button("x", help=None)', False),
        ('st.button("x", help=f"{name}")', False),
        ('st.button("x", help=text)', False),
        ('st.button("x", **options)', False),
        ('st.button("x", help="Back", **options)', True),
        ('button("x")', False),
        ('button("x", help="Back")', True),
        ('st.button("x")', False),
        ('st.markdown("x")', True),
    ],
)
def test_the_help_check_reports_a_blank_or_missing_help(call, accepted):
    """The checker itself: a widget call is reported when its help is missing, None, blank, a bare
    name nobody reviewed, or hidden in **kwargs; a text, or an f-string holding one, passes."""
    assert (widget_calls_without_help_in(call, "page.py") == []) is accepted


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
