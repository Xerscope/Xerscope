"""The Earned value page's "Show as % of BAC" toggle redraws the S-curve over the BAC."""

import base64
import json
from pathlib import Path

import numpy as np
import pytest
from conftest import read_folder
from streamlit.testing.v1 import AppTest

import xerscope

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")


def s_curve(app) -> dict:
    """The plotly spec of the S-curve: the chart that draws the trace "EV (earned)"."""
    specs = [json.loads(chart.proto.spec) for chart in app.get("plotly_chart")]
    return next(spec for spec in specs if "EV (earned)" in [trace.get("name") for trace in spec["data"]])


def last_earned_value(spec: dict) -> float:
    """The y of the last point of the EV trace (plotly sends numbers as base64 arrays)."""
    trace = next(trace for trace in spec["data"] if trace["name"] == "EV (earned)")
    y = trace["y"]
    values = np.frombuffer(base64.b64decode(y["bdata"]), dtype=y["dtype"]) if isinstance(y, dict) else y
    return float(values[-1])


@pytest.mark.oracle("property")
def test_the_percent_toggle_draws_the_s_curve_as_a_share_of_the_bac(sample_dir):
    """The KPI "Percent complete" is EV / BAC of the update shown (P6: Earned Value Labor Units / Budget At
    Completion). With the toggle on, the S-curve's last EV point, the update shown, is that same share and
    the axis reads "% of BAC"; with it off, the point is in labor hours, EV = share x BAC."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("XERSCOPE_DATA", str(sample_dir))
        patch.delenv("XERSCOPE_BASELINE", raising=False)
        patch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
        app = read_folder(AppTest.from_file(APP, default_timeout=180).run())
        app.switch_page("views/earned_value.py").run()
        assert not app.exception
        percent_complete = next(m for m in app.metric if m.label == "Percent complete")
        share = float(percent_complete.value.removesuffix(" %"))  # shown with one decimal
        hours_spec = s_curve(app)
        assert hours_spec["layout"]["yaxis"]["title"]["text"] == "labor hours"
        hours = last_earned_value(hours_spec)

        app.toggle(key="ev_pct_toggle").set_value(True).run()
        assert not app.exception
        percent_spec = s_curve(app)
    assert percent_spec["layout"]["yaxis"]["title"]["text"] == "% of BAC"
    assert last_earned_value(percent_spec) == pytest.approx(share, abs=0.05)
    assert hours != pytest.approx(share, abs=0.05)  # without the toggle the point is in hours, not the share
