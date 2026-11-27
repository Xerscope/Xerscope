"""The PPC page draws the target the user types."""

import json
from pathlib import Path

import pytest
from conftest import read_folder
from streamlit.testing.v1 import AppTest

import xerscope

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")


def target_line(app) -> tuple[list[float], list[str]]:
    """The heights of the dotted horizontal lines of the PPC chart and the texts that label them."""
    specs = [json.loads(chart.proto.spec) for chart in app.get("plotly_chart")]
    layout = specs[0]["layout"]  # the one chart of the page: percent plan complete by week
    heights = [shape["y0"] for shape in layout.get("shapes", []) if shape["y0"] == shape["y1"]]
    return heights, [note["text"] for note in layout.get("annotations", [])]


@pytest.mark.oracle("property")
def test_the_ppc_target_input_moves_the_chart_target_line(sample_dir):
    """ "PPC target (%)" is "the dotted line of the chart" (its own help text): 80 by default
    (PPC_TARGET), and the line follows the value typed, here 60."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("XERSCOPE_DATA", str(sample_dir))
        patch.delenv("XERSCOPE_BASELINE", raising=False)
        patch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
        app = read_folder(AppTest.from_file(APP, default_timeout=180).run())
        app.switch_page("views/ppc.py").run()
        assert not app.exception
        by_default = target_line(app)
        app.number_input[0].set_value(60).run()
        assert not app.exception
        typed = target_line(app)
    assert by_default[0] == [80] and "target 80%" in by_default[1]
    assert typed[0] == [60] and "target 60%" in typed[1]
