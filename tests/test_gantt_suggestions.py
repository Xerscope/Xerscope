"""The Gantt's "Did you mean" buttons when the file holds the same label under two kinds."""

from pathlib import Path

import pytest
from conftest import read_folder
from streamlit.testing.v1 import AppTest
from xerkit import ROOT_WBS, todo, xer_text

import xerscope

pytestmark = pytest.mark.oracle("property")

CRANE_NODE = {
    "wbs_id": "20",
    "proj_id": "1",
    "parent_wbs_id": "10",
    "wbs_short_name": "CRANE",
    "wbs_name": "",
    "proj_node_flag": "N",
}
CRANE_RESOURCE = {"rsrc_id": "R1", "rsrc_short_name": "CRANE", "rsrc_name": "CRANE", "rsrc_type": "RT_Labor"}


def test_a_wbs_node_and_a_resource_with_the_same_label_each_get_their_button(tmp_path, monkeypatch):
    """A WBS node coded CRANE (no name, so its label is "CRANE") and a resource short-named CRANE:
    "crnae" is close to both, so both are offered. Each button is keyed on its kind as well as its
    label; with the label alone the two buttons shared a key and the page stopped."""
    text = xer_text(
        [todo("A", wbs_id="20")],
        wbs=[*ROOT_WBS, CRANE_NODE],
        resources=[CRANE_RESOURCE],
        rsrc=["A"],
    )
    (tmp_path / "a.xer").write_text(text)
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    app = AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120)
    app = read_folder(app.run())
    app.switch_page("views/gantt.py").run()
    app.text_input[0].set_value("crnae").run()
    assert not app.exception, [element.value for element in app.exception]
    offered = [button for button in app.button if button.key and button.key.startswith("teach_crnae")]
    assert sorted(button.label for button in offered) == ["CRANE", "CRANE"]
