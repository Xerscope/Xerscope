"""The app under inputs that change between reruns or come from a crafted file: no page crashes,
and what it shows stays true to the files read."""

from pathlib import Path

import pytest
from conftest import baseline_box, files_done, open_files, read_folder
from streamlit.testing.v1 import AppTest

import xerscope

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")


@pytest.fixture
def app(sample_dir, monkeypatch):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    monkeypatch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
    return read_folder(AppTest.from_file(APP, default_timeout=120).run())


def _ok(at):
    assert not at.exception, [e.value for e in at.exception]


def test_export_offers_a_new_extract_once_a_baseline_file_is_chosen(app, sample_dir):
    """The anonymised extract holds the files read when it was built. A baseline file chosen after
    it is not in it: the page must not offer the old extract (nor crash on its report)."""
    app.switch_page("views/export.py").run()
    app.button(key="anon_build").click().run()
    _ok(app)
    assert [b.proto.label for b in app.get("download_button") if b.key == "anon_download"]

    baseline_box(app).select("Separate baseline file")
    data = sorted(sample_dir.glob("*.xer"))[0].read_bytes()
    app.file_uploader(key="bl_upload").set_value([("bl.xer", data, "text/plain")]).run()
    files_done(app)
    app.switch_page("views/export.py").run()
    _ok(app)
    assert not [b for b in app.get("download_button") if b.key == "anon_download"]
    assert app.button(key="anon_build")


def test_an_anonymizer_is_not_served_for_a_baseline_file_replaced_under_the_same_name(monkeypatch):
    """The leak check compares an output with the text of the files read: a baseline file replaced
    under the same name is other text, so the anonymizer of the old one does not serve it."""
    from xerkit import todo, xer_text

    from xerscope.app import state

    monkeypatch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
    update = xer_text([todo("A1")]).encode()
    session = {
        "signature": ("folder", "x", ("a.xer", "d")),
        "items": [("a.xer", update)],
        "bl_choice": state.BL_FILE,
        "bl_file": ("bl.xer", xer_text([todo("A1", task_name="First name")]).encode()),
    }
    assert state.anonymizer(prepare=True, session=session) is not None
    session["bl_file"] = ("bl.xer", xer_text([todo("A1", task_name="Second name")]).encode())
    assert state.anonymizer(session=session) is None
    assert "Second name" in state.anonymizer(prepare=True, session=session).secrets_


CRAFTED = "![x](https://example.invalid/p.png)"


def test_text_from_a_crafted_file_and_its_name_are_shown_literally(tmp_path, monkeypatch):
    """A table name and a file name are the file's text: shown as written, never as a Markdown
    image or link (which the browser would fetch, or show as a link the file chose)."""
    from conftest import file_boxes, open_files

    name = "![y](p).xer"
    (tmp_path / name).write_text(f"ERMHDR\t23.12\t2026-03-02\n%T\tPROJECT\n%F\t{CRAFTED}\t{CRAFTED}\n")
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = open_files(AppTest.from_file(APP, default_timeout=120).run())
    _ok(at)
    (box,) = file_boxes(at)
    assert box.label.startswith(r"\!\[y\]\(p\)\.xer") and r"\!\[x\]\(https" in box.help
    box.check()
    at.run()
    files_done(at)
    _ok(at)
    (error,) = [e.value for e in at.sidebar.error]
    assert r"\!\[y\]\(p\)" in error and r"\!\[x\]\(https" in error
    assert "![" not in error


def _folder_of(tmp_path, sample_dir, count):
    for path in sorted(sample_dir.glob("*.xer"))[:count]:
        (tmp_path / path.name).write_bytes(path.read_bytes())
    return sorted(tmp_path.glob("*.xer"))


def test_a_file_gone_from_the_folder_is_named_and_the_others_stay_read(tmp_path, sample_dir, monkeypatch):
    """A ticked file removed from the folder (an export moved on the share) is named in the sidebar;
    the series is read again without it."""
    files = _folder_of(tmp_path, sample_dir, 3)
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = read_folder(AppTest.from_file(APP, default_timeout=120).run())
    assert len(at.session_state["store"]) == 3
    files[1].unlink()
    at.run()
    _ok(at)
    assert [s.source for s in at.session_state["store"]] == [files[0].name, files[2].name]
    assert [e.value.replace("\\", "") for e in at.sidebar.error] == [
        f"{files[1].name}: no longer in the folder; the file is skipped"
    ]
    at.run()  # the message stays while the choice is the same
    assert len(at.sidebar.error) == 1


def test_a_file_gone_between_the_listing_and_its_reading_does_not_crash_the_page(tmp_path, sample_dir, monkeypatch):
    """The folder is listed, then each file is read: a file removed in between (os.stat fails) is
    named, as one gone before the listing."""
    from xerscope.app import state

    files = _folder_of(tmp_path, sample_dir, 2)
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = read_folder(AppTest.from_file(APP, default_timeout=120).run())
    listed = state.xer_files(tmp_path)
    monkeypatch.setattr(state, "xer_files", lambda root: listed)
    files[0].unlink()
    at.run()
    _ok(at)
    assert [s.source for s in at.session_state["store"]] == [files[1].name]
    assert [e.value.replace("\\", "") for e in at.sidebar.error] == [
        f"{files[0].name}: no longer in the folder; the file is skipped"
    ]
    open_files(at)  # the window lists the folder: the stale entry is described, not stat'ed blindly
    _ok(at)
