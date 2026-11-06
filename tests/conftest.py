import os
from pathlib import Path

import pytest

from xerscope.sample import generate
from xerscope.store import SnapshotStore

# MPXJ's scheduler built from its pinned commit (tests/reference/mpxj_cpm.py), first on the
# classpath of whichever test starts the JVM.
_MPXJ_CPM = sorted((Path(__file__).parent / "reference" / "data").glob("mpxj-cpm-*.jar"))
if _MPXJ_CPM:
    os.environ.setdefault("XERSCOPE_MPXJ_CPM_JAR", str(_MPXJ_CPM[-1]))


# AppTest returns when the script run ends: the app reads every file and computes the Overview
# scores in that run (state.background_jobs). test_app_background.py lifts this for its own tests.
os.environ.setdefault("XERSCOPE_SYNC_LOAD", "1")


@pytest.fixture(scope="session")
def sample_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("sample")
    generate(out, weeks=8)
    return out


@pytest.fixture(scope="session")
def store(sample_dir):
    return SnapshotStore.from_folder(sample_dir)


REFERENCE_HINT = "uv run python tests/reference/fetch.py"
P6_CORPUS_HINT = "uv run python tests/reference/fetch_p6_heldout.py"


def missing(what: str, hint: str) -> None:
    """Skip the test for want of ``what`` (reference, p6-corpus, mpxj); fail instead when
    XERSCOPE_REQUIRE names it, so CI cannot pass by skipping its evidence."""
    msg = f"{what} missing: {hint}"
    if what in os.environ.get("XERSCOPE_REQUIRE", "").split(","):
        pytest.fail(msg, pytrace=False)
    pytest.skip(msg)


def mpxj_or_skip():
    """The MPXJ cross-check: jpype + mpxj installed, a Java runtime on PATH."""
    import importlib.util
    import shutil

    for mod in ("jpype", "mpxj"):
        if importlib.util.find_spec(mod) is None:
            missing("mpxj", f"{mod} not installed: uv sync --extra crosscheck")
    if shutil.which("java") is None:
        missing("mpxj", "no Java runtime on PATH")


@pytest.fixture
def require_reference():
    """Path of a pinned third-party XER, or a skip with the fetch instruction."""

    def get(name: str) -> Path:
        path = Path(__file__).parent / "reference" / "data" / name
        if not path.exists():
            missing("reference", REFERENCE_HINT)
        return path

    return get


def file_boxes(at):
    """The tick boxes of the folder's files in the Files… window (empty while it is closed)."""
    return [box for box in at.checkbox if box.key and box.key.startswith("read:")]


def open_files(at):
    """Press the sidebar's Files line: the window opens on its Files section."""
    at.button(key="files_button").click()
    return at.run()


def files_done(at):
    """Press Done in the Files… window."""
    at.button(key="files_done").click()
    return at.run()


def read_folder(at, count=None):
    """Nothing is read until files are ticked: open the Files… window, tick every file of the
    folder (or the first ``count``) and press Done."""
    open_files(at)
    for box in file_boxes(at)[:count]:
        box.check()
    return files_done(at)


def files_line(at):
    """The sidebar's Files line: ``Files · <N> files · <K> projects``, or ``Files · none read``."""
    return at.button(key="files_button").label


def window(at):
    """The Files and baseline window, opened from the Files line if it is closed."""
    if not any(button.key == "files_done" for button in at.button):
        open_files(at)
    return at


def close_window(at):
    """Close the window without Done (what Esc or a click outside does)."""
    at.session_state["files_open"] = False
    return at.run()


def project_box(at, source):
    """The list of the projects of file ``source`` in the window (opened if closed); None when the
    file holds one project and has no list."""
    boxes = [box for box in window(at).selectbox if box.key == f"draft_file_project:{source}"]
    return boxes[0] if boxes else None


def pick_project(at, source, proj_id):
    """Pick project ``proj_id`` for file ``source`` in the window, then press Done."""
    project_box(at, source).set_value(proj_id)
    at.run()
    return files_done(at)


def selection(at):
    """The window's Selection details table (file, project, picked by…); the window is closed after."""
    table = next(frame for frame in window(at).dataframe if "selected_by" in frame.value.columns).value
    close_window(at)
    return table


class BaselineBox:
    """A baseline selector of the window (``bl_choice``, ``ev_basis``, ``bl_fallback``), read and set
    as a user does: the window opened from the sidebar's Baseline line, the choice made on its draft,
    then Done. The window is opened again after Done, so the selectors can be read back."""

    def __init__(self, at, key):
        self.at, self.key = at, key

    @property
    def element(self):
        if not any(box.key == f"draft_{self.key}" for box in self.at.selectbox):
            self.at.button(key="baseline_button").click()
            self.at.run()
        return self.at.selectbox(key=f"draft_{self.key}")

    @property
    def value(self):
        return self.element.value

    @property
    def options(self):
        return self.element.options

    @property
    def label(self):
        return self.element.label

    def set_value(self, value):
        self.element.set_value(value)
        self.at.run()
        self.at.button(key="files_done").click()
        self.at.run()
        self.at.button(key="baseline_button").click()
        self.at.run()
        return self

    select = set_value

    def run(self):
        return self.at.run()


def baseline_box(at, key="bl_choice"):
    return BaselineBox(at, key)
