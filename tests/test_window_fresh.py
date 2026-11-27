"""The Files window's widgets start fresh each time it opens, so the browser shows what the server counts.

Streamlit drops the widgets a closed window leaves behind only after a run that was not stopped by
st.stop(); a page that stops (nothing loaded, a read under way, the baseline awaited) keeps them in the
session while the browser forgets them. Reopened, the boxes then showed empty under a counter that
still said "3 of 8 ticked", and the first click sent False for every box. AppTest has no browser
state: what it can see is the keys, and the values the server holds. The browser side is
scripts/windows_check.py.
"""

from pathlib import Path

import pytest
from conftest import (
    baseline_upload,
    close_window,
    file_boxes,
    files_line,
    files_upload,
    is_waiting_for_baseline,
    open_files,
    read_folder,
)
from streamlit.testing.v1 import AppTest

import xerscope
from xerscope.app.session import BL_FILE

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")


@pytest.fixture
def at(sample_dir, monkeypatch):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    monkeypatch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
    return AppTest.from_file(APP, default_timeout=120).run()


def _keys(at) -> set[str]:
    return {box.key for box in file_boxes(at)}


@pytest.mark.oracle("property")
def test_no_checkbox_key_survives_from_one_opening_to_the_next(at):
    """The page under the window stops (nothing is loaded): the old keys must still not come back."""
    first = _keys(open_files(at))
    assert first
    close_window(at)
    second = _keys(open_files(at))
    assert second and not first & second
    assert not any(key in at.session_state for key in first)  # the old ones are dropped too


@pytest.mark.oracle("property")
def test_esc_cancels_the_ticks_on_a_page_stopped_by_st_stop(at):
    """Nothing is ticked by default (a file is read only once asked for): ticks Esc cancelled must not return."""
    open_files(at)
    for box in file_boxes(at)[:3]:
        box.check()
    at.run()
    assert [box.value for box in file_boxes(at)].count(True) == 3
    close_window(at)
    open_files(at)
    assert [box.value for box in file_boxes(at)].count(True) == 0
    assert at.caption[[c.value for c in at.caption].index("0 of 8 ticked")]


@pytest.mark.oracle("property")
def test_esc_cancels_a_fourth_tick_and_keeps_the_validated_three(at):
    read_folder(at, 3)
    open_files(at)
    file_boxes(at)[3].check()
    at.run()
    close_window(at)
    open_files(at)
    assert [box.value for box in file_boxes(at)] == [True] * 3 + [False] * 5
    assert "3 of 8 ticked" in [c.value for c in at.caption]


@pytest.mark.oracle("property")
def test_done_is_disabled_with_nothing_ticked_on_a_loaded_series_and_says_why(at):
    """EDGE-01: Clear then Done used to unload every file without a word."""
    read_folder(at, 3)
    open_files(at)
    assert not at.button(key="files_done").disabled
    for box in file_boxes(at):
        box.uncheck()
    at.run()
    assert at.button(key="files_done").disabled
    assert any(c.value.startswith("Tick a file") for c in at.caption)
    file_boxes(at)[0].check()
    at.run()
    assert not at.button(key="files_done").disabled
    assert not any(c.value.startswith("Tick a file") for c in at.caption)
    assert files_line(at) == "Files · 3 files · 1 project"  # nothing was applied meanwhile


@pytest.mark.oracle("property")
def test_a_baseline_upload_cancelled_by_esc_is_not_applied_at_the_next_done(at, sample_dir):
    """A new choice of files: the pages wait for its baseline (st.stop), the window opens on it by itself.
    The upload Esc cancelled there stays in the session; it must not be applied at the next Done."""
    read_folder(at, 2)
    open_files(at)
    file_boxes(at)[2].check()
    at.run()
    at.button(key="files_done").click()
    at.run()
    assert is_waiting_for_baseline(at)
    at.selectbox(key="draft_bl_choice").set_value(BL_FILE).run()
    data = sorted(sample_dir.glob("*.xer"))[0].read_bytes()
    baseline_upload(at).set_value([("bl.xer", data, "text/plain")]).run()
    close_window(at)
    at.button(key="baseline_button").click()
    at.run()
    at.selectbox(key="draft_bl_choice").set_value(BL_FILE).run()
    at.button(key="files_done").click()
    at.run()
    assert "bl_file" not in at.session_state or not at.session_state["bl_file"]


@pytest.mark.oracle("property")
def test_uploads_cancelled_by_esc_are_not_read_at_the_next_done_and_no_keep_key_survives(at, sample_dir):
    """Nothing is loaded, so the page stops under the window: the files Esc cancelled stay in the
    upload widget's session state while the browser shows it empty, with their boxes still ticked."""
    files = sorted(sample_dir.glob("*.xer"))[:2]
    open_files(at)
    files_upload(at).set_value([(f.name, f.read_bytes(), "text/plain") for f in files]).run()
    first = {box.key for box in at.checkbox if box.key.startswith("keep:")}
    assert len(first) == 2
    close_window(at)
    open_files(at)
    assert not first & {box.key for box in at.checkbox}
    assert not any(box.key.startswith("keep:") for box in at.checkbox)
    at.button(key="files_done").click()
    at.run()
    assert at.session_state["store"] is None


@pytest.mark.oracle("property")
def test_an_untick_of_an_uploaded_file_cancelled_by_esc_shows_it_ticked_again(at, sample_dir):
    """The pages wait for the baseline (st.stop): the box a closed window left unticked in the session
    must not come back unticked while the browser draws it ticked, as the validated choice says."""
    files = sorted(sample_dir.glob("*.xer"))[:3]
    open_files(at)
    files_upload(at).set_value([(f.name, f.read_bytes(), "text/plain") for f in files]).run()
    at.button(key="files_done").click()
    at.run()
    assert is_waiting_for_baseline(at)
    close_window(at)
    at.button(key="files_button").click()
    at.run()
    next(box for box in at.checkbox if box.key.startswith("keep:")).uncheck()
    at.run()
    close_window(at)
    at.button(key="files_button").click()
    at.run()
    assert [box.value for box in at.checkbox if box.key.startswith("keep:")] == [True] * 3
