"""Characterization (golden) test: freeze what every page shows on the demo series.

For each page, in the order of the menu, the elements of the page are listed top to bottom, one
line each: texts in full, a metric with its value and delta, a widget with its label (and its
value when it is a choice), a table with its row count and columns, a chart with its trace
types. The lists are compared with tests/golden/pages.json. Colours and layout are not seen.

One app visits the pages in order, as a user would: what a page shows can depend on the pages
opened before it (the Overview scores are computed once Schedule health has been opened).

After an intended change of a page, regenerate and commit the file with the change:

    XERSCOPE_UPDATE_GOLDEN=1 uv run pytest tests/test_page_golden.py

That run rewrites the file and fails; the next run, without the variable, must pass.
"""

import difflib
import json
import os
from pathlib import Path

import pytest
from conftest import read_folder
from streamlit.testing.v1 import AppTest

import xerscope

pytestmark = pytest.mark.oracle("characterization")

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
GOLDEN = Path(__file__).parent / "golden" / "pages.json"
PAGES = ["overview", "gantt", "activity", "health", "audit", "changelog", "earned_value", "milestones", "ppc",
         "export", "debug"]  # fmt: skip
TEXTS = {"title", "header", "subheader", "caption", "markdown", "info", "warning", "error", "success", "code"}
CHOICES = {"selectbox", "multiselect", "toggle", "checkbox", "text_input", "button_group"}
LAYOUT = {"column", "flex_container", "empty"}  # hold or reserve a place, show nothing themselves


def _line(element) -> str:
    kind = element.type
    if kind in TEXTS:
        return f"{kind}: {element.value}"
    if kind == "metric":
        return f"metric: {element.label} = {element.value}" + (f" ({element.delta})" if element.delta else "")
    if kind == "dataframe":
        return f"dataframe: {len(element.value)} rows | " + ", ".join(map(str, element.value.columns))
    if kind == "plotly_chart":
        traces = json.loads(element.proto.spec)["data"]
        return "plotly_chart: " + ", ".join(sorted(trace.get("type", "scatter") for trace in traces))
    if not hasattr(element, "label"):
        return kind
    return f"{kind}: {element.label}" + (f" = {element.value}" if kind in CHOICES else "")


def shown(block) -> list[str]:
    """One line per element of ``block``, in the order of the page; layout containers are walked, not listed."""
    lines = []
    for element in getattr(block, "children", {}).values():
        if element.type not in LAYOUT:
            lines.append(_line(element))
        lines += shown(element)
    return lines


@pytest.fixture(scope="module")
def pages(sample_dir):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("XERSCOPE_DATA", str(sample_dir))
        patch.delenv("XERSCOPE_BASELINE", raising=False)
        patch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
        app = read_folder(AppTest.from_file(APP, default_timeout=180).run())
        observed = {"sidebar": shown(app.sidebar)}
        for page in PAGES:
            app.switch_page(f"views/{page}.py").run()
            assert not app.exception, (page, [e.value for e in app.exception])
            observed[page] = shown(app.main)
        yield observed


def test_the_listing_reads_every_kind_of_element_the_pages_use(pages):
    """A page that shows nothing, or an element read as its bare kind, would freeze nothing: every page
    has a title and a metric or a table, and only two kinds have no text of their own."""
    for page in PAGES:
        assert pages[page][0].startswith("title: "), page
    bare = {line for lines in pages.values() for line in lines if ": " not in line}
    assert bare == {"popover", "bidi_component"}  # the help window of a block; the Gantt component


@pytest.mark.parametrize("page", ["sidebar", *PAGES])
def test_page_shows_what_the_golden_file_holds(pages, page):
    if os.environ.get("XERSCOPE_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(pages, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        pytest.fail(f"{GOLDEN.name} rewritten; rerun without XERSCOPE_UPDATE_GOLDEN", pytrace=False)
    expected = json.loads(GOLDEN.read_text(encoding="utf-8")).get(page, [])
    diff = list(difflib.unified_diff(expected, pages[page], "golden", "now", lineterm="", n=1))
    assert not diff, f"{page}: the page differs from {GOLDEN.name}\n" + "\n".join(diff[:60])
