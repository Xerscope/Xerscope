"""When P6's Update Baseline last changed a baseline, read from the XER and the P6 XML, and the warning
when that is after an update's status date.

Sources: XER data map v23, PROJECT.last_baseline_update_date "Last Update Date"; P6 EPPM REST and Web
Services references, BaselineProject.LastBaselineUpdateDate, "The date this project baseline was last
changed by Baseline Update"; P6 Professional help, Update a baseline ("the module stores the date on which
the baseline was last updated"). The XML element name follows the API field name, as ObjectId, DataDate and
CurrentBaselineProjectObjectId do; no public XML written by P6 holds one, so it is unverified on a real file.
"""

from pathlib import Path

import pandas as pd
import pytest
from conftest import read_folder
from file_projects import BASELINE_DATE, two_projects
from pmxmlkit import activity, baseline, pmxml_bytes
from streamlit.testing.v1 import AppTest

import xerscope
from xerscope.analysis.baseline import Baseline, baseline_in_file, last_updated
from xerscope.xer import load_snapshot

pytestmark = pytest.mark.oracle("standard")

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
TASK = activity("A", "1001", "2026-03-02T08:00:00", "2026-03-13T17:00:00", 80)


def _xml_baseline(updated: str | None) -> Baseline:
    element = baseline("370", "BL-1", [TASK])
    if updated is not None:
        element = element.replace(
            "<BaselineProject>", f"<BaselineProject><LastBaselineUpdateDate>{updated}</LastBaselineUpdateDate>", 1
        )
    data = pmxml_bytes([element], current_baseline="370")
    return Baseline.from_snapshot(load_snapshot(data, name="export.xml", project_id="370"))


def test_the_xml_baseline_carries_its_last_update_date():
    assert last_updated(_xml_baseline("2026-03-20T08:00:00")) == pd.Timestamp("2026-03-20 08:00")


def test_an_xml_baseline_never_updated_has_no_last_update_date():
    assert last_updated(_xml_baseline(None)) is None


def test_the_xer_baseline_carries_its_last_update_date():
    text = two_projects()
    held = baseline_in_file(load_snapshot(text.encode(), name="two.xer"), text.encode())
    assert last_updated(held) == pd.Timestamp(BASELINE_DATE)


def _warnings(tmp_path, monkeypatch, updated: str) -> list[str]:
    text = two_projects().replace(BASELINE_DATE, updated)
    (tmp_path / "two.xer").write_text(text)
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    app = read_folder(AppTest.from_file(APP, default_timeout=120).run())
    app.switch_page("views/health.py").run()
    assert not app.exception, [element.value for element in app.exception]
    return [element.value.replace("\\", "") for element in app.main.warning if "updated in P6" in element.value]


@pytest.mark.parametrize(
    ("updated", "warned"),
    [
        ("2026-03-09 08:00", True),  # a week after the update's status date, 2026-03-02 08:00
        ("2026-03-02 08:00", False),  # on the status date itself: not after it
        ("2026-01-12 08:00", False),  # before it
    ],
)
def test_a_baseline_updated_after_the_update_is_named_on_the_page(tmp_path, monkeypatch, updated, warned):
    lines = _warnings(tmp_path, monkeypatch, updated)
    assert len(lines) == (1 if warned else 0)
    if warned:
        assert "the baseline was updated in P6 on " in lines[0] and "after the update's status date" in lines[0]
