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
