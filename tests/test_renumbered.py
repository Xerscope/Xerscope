"""Tasks renumbered between a baseline and an update, found by TASK.guid, and the option that links them."""

import pandas as pd
import pytest
from xerkit import snap, todo

from xerscope.analysis import Baseline
from xerscope.analysis.baseline import relinked, renumbered
from xerscope.analysis.evm import ev_point

WEEK = {"early_start_date": "2026-03-02 08:00", "early_end_date": "2026-03-13 17:00", "target_work_qty": "80"}


def _codes(frame):
    return list(zip(frame["old_code"], frame["new_code"], strict=True))


def test_a_task_with_the_same_guid_under_a_new_activity_id_is_renumbered():
    # B becomes B2 with its GUID; A keeps code and GUID; C is deleted; D is new with its own GUID
    old = snap([todo("A", guid="g1"), todo("B", guid="g2"), todo("C", guid="g3")])
    new = snap([todo("A", guid="g1"), todo("B2", guid="g2"), todo("D", guid="g4")])
    assert _codes(renumbered(old, new)) == [("B", "B2")]


def test_blank_and_shared_guids_and_codes_still_present_are_left_out():
    # E and F share a GUID in the old file, G has none, H keeps its code but its GUID moved to H2:
    # H is still in the update, so H2 is a new task that copied a GUID, not H renumbered
    old = snap([todo("E", guid="dup"), todo("F", guid="dup"), todo("G"), todo("H", guid="g8")])
    new = snap([todo("E2", guid="dup"), todo("G2"), todo("H", guid="g9"), todo("H2", guid="g8")])
    assert renumbered(old, new).empty


def test_a_file_without_guid_column_finds_nothing():
    assert renumbered(snap([todo("A")]), snap([todo("A2")])).empty


def test_linking_by_guid_counts_the_renumbered_task_as_p6_does_when_the_baseline_was_renumbered():
    """Baseline A and B, 80 h each over 10 working days; update at day 2 holds A and B2 (B's GUID).
    Without the link B counts as deleted (PV 16 h, B2 not baselined); with it, B2 takes B's
    baseline row: BAC 160 h, PV 2 x 80 x 2/10 = 32 h, nothing deleted."""
    baseline = Baseline.from_snapshot(snap([todo("A", guid="g1", **WEEK), todo("B", guid="g2", **WEEK)]))
    update = snap([todo("A", guid="g1"), todo("B2", guid="g2")], data_date="2026-03-04 08:00")
    alone = ev_point(update, baseline)
    assert (alone.bac_hr, alone.pv_hr) == pytest.approx((80, 16)) and (alone.deleted, alone.unbaselined) == (
        ["B"],
        ["B2"],
    )
    linked = relinked(baseline, update)
    point = ev_point(update, linked)
    assert (point.bac_hr, point.pv_hr) == pytest.approx((160, 32)) and (point.deleted, point.unbaselined) == ([], [])
    assert "B2" in linked.frame.index and "B" not in linked.frame.index
    assert linked.frame.loc["B2", "ev_start"] == pd.Timestamp("2026-03-02 08:00")


def test_linking_changes_nothing_without_renumbered_tasks():
    baseline = Baseline.from_snapshot(snap([todo("A", guid="g1", **WEEK)]))
    assert relinked(baseline, snap([todo("A", guid="g1")])) is baseline


def _app(tmp_path, monkeypatch):
    """a (2026-03-02): A and B; b (2026-03-09): A and B renumbered B2. No baseline in the files,
    so the first update is the default baseline."""
    from pathlib import Path

    from conftest import read_folder
    from streamlit.testing.v1 import AppTest
    from xerkit import xer_text

    import xerscope

    (tmp_path / "a.xer").write_text(
        xer_text([todo("A", guid="g1", **WEEK), todo("B", guid="g2", **WEEK)], data_date="2026-03-02 08:00")
    )
    (tmp_path / "b.xer").write_text(
        xer_text([todo("A", guid="g1", **WEEK), todo("B2", guid="g2", **WEEK)], data_date="2026-03-09 08:00")
    )
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120)
    return read_folder(at.run())


def _guid_warnings(at):
    return [element.value.replace("\\", "") for element in at.sidebar.warning if "GUID" in element.value]


def test_the_sidebar_names_renumbered_tasks_and_the_option_links_them(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch)
    assert not at.exception
    (warning,) = _guid_warnings(at)
    assert "1 task" in warning and "b.xer" in warning
    at.button(key="baseline_button").click()
    at.run()
    at.checkbox(key="draft_guid_link").check()
    at.run()
    at.button(key="files_done").click()
    at.run()
    assert not at.exception and not _guid_warnings(at)
    assert any("linked to the baseline by GUID" in caption.value for caption in at.sidebar.caption)


def test_no_guid_warning_when_nothing_is_renumbered(tmp_path, monkeypatch):
    from pathlib import Path

    from conftest import read_folder
    from streamlit.testing.v1 import AppTest
    from xerkit import xer_text

    import xerscope

    for name, day in (("a.xer", "2026-03-02 08:00"), ("b.xer", "2026-03-09 08:00")):
        (tmp_path / name).write_text(xer_text([todo("A", guid="g1", **WEEK)], data_date=day))
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120)
    at = read_folder(at.run())
    assert not at.exception and not _guid_warnings(at)


def test_the_debug_table_names_the_pairs_against_the_baseline_and_the_previous_update():
    from xerscope.app.diagnostic import renumbered_table

    week1 = snap([todo("A", guid="g1"), todo("B", guid="g2")], data_date="2026-03-02 08:00")
    week2 = snap([todo("A", guid="g1"), todo("B2", guid="g2")], data_date="2026-03-09 08:00")
    week3 = snap([todo("A3", guid="g1"), todo("B2", guid="g2")], data_date="2026-03-16 08:00")
    table = renumbered_table(week3, Baseline.from_snapshot(week1), week2)
    assert table.values.tolist() == [["baseline", "A", "A3"], ["baseline", "B", "B2"], ["previous update", "A", "A3"]]
    assert renumbered_table(week1, None, None).empty


def test_the_option_warns_when_the_baseline_has_no_guid(tmp_path, monkeypatch):
    """A P6 XML baseline carries no GUID xerscope can compare (xer/pmxml.py writes it blank): with the
    option ticked nothing is linked, which the sidebar says instead of staying silent."""
    from pathlib import Path

    from conftest import read_folder
    from pmxmlkit import activity, baseline, pmxml_bytes
    from streamlit.testing.v1 import AppTest
    from xerkit import xer_text

    import xerscope

    data = tmp_path / "updates"
    data.mkdir()
    (data / "a.xer").write_text(xer_text([todo("A", guid="g1", **WEEK)], data_date="2026-03-09 08:00"))
    a = activity("A", "1001", "2026-03-02T08:00:00", "2026-03-13T17:00:00", 80)
    (tmp_path / "export.xml").write_bytes(pmxml_bytes([baseline("370", "BL-1", [a])], current_baseline="370"))
    monkeypatch.setenv("XERSCOPE_DATA", str(data))
    monkeypatch.setenv("XERSCOPE_BASELINE", str(tmp_path / "export.xml"))
    at = AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120)
    at = read_folder(at.run())
    assert not at.exception and not _guid_warnings(at)  # option off: nothing to say
    at.button(key="baseline_button").click()
    at.run()
    at.checkbox(key="draft_guid_link").check()
    at.run()
    at.button(key="files_done").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    (warning,) = _guid_warnings(at)
    assert "no GUID" in warning and "export.xml" in warning
