"""A folder typed in the Files window is read only under the folder root (app/session.py).

The root is XERSCOPE_FOLDER_ROOT, else the folder of XERSCOPE_DATA, else the home directory. A folder
outside it is refused with a message, never listed, never read.
"""

import os
from pathlib import Path

import pytest
from conftest import file_boxes, open_files
from streamlit.testing.v1 import AppTest

import xerscope
from xerscope.app import session
from xerscope.sample import generate

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")

pytestmark = pytest.mark.oracle("characterization")


def test_the_root_is_the_variable_then_the_data_folder_then_home(tmp_path, monkeypatch):
    monkeypatch.delenv("XERSCOPE_FOLDER_ROOT", raising=False)
    monkeypatch.delenv("XERSCOPE_DATA", raising=False)
    assert session.folder_root() == Path(os.path.realpath(Path.home()))
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path / "exports"))
    assert session.folder_root() == Path(os.path.realpath(tmp_path / "exports"))
    monkeypatch.setenv("XERSCOPE_FOLDER_ROOT", str(tmp_path))
    assert session.folder_root() == Path(os.path.realpath(tmp_path))


def test_a_folder_under_the_root_is_accepted_and_one_outside_or_climbing_out_is_not(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "exports").mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.setenv("XERSCOPE_FOLDER_ROOT", str(root))
    assert session.folder_under_root(str(root)) == Path(os.path.realpath(root))
    assert session.folder_under_root(str(root / "exports")) == Path(os.path.realpath(root / "exports"))
    assert session.folder_under_root(str(root / "exports" / "..")) == Path(os.path.realpath(root))
    assert session.folder_under_root(str(tmp_path / "elsewhere")) is None
    assert session.folder_under_root(str(root / ".." / "elsewhere")) is None
    assert session.folder_under_root(str(root) + "x") is None  # a sibling whose name starts like the root


def test_the_files_window_refuses_a_folder_outside_the_root(tmp_path, monkeypatch):
    data, elsewhere = tmp_path / "data", tmp_path / "elsewhere"
    generate(data, weeks=2)
    generate(elsewhere, weeks=2)
    monkeypatch.setenv("XERSCOPE_DATA", str(data))
    monkeypatch.delenv("XERSCOPE_FOLDER_ROOT", raising=False)
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = open_files(AppTest.from_file(APP, default_timeout=120).run())
    assert file_boxes(at)
    at.text_input(key="files_folder").input(str(elsewhere)).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Folder outside" in e.value for e in at.error)
    assert not file_boxes(at)
