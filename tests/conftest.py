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


@pytest.fixture
def require_reference():
    """Path of a pinned third-party XER, or a skip with the fetch instruction."""
    from pathlib import Path

    def get(name: str) -> Path:
        path = Path(__file__).parent / "reference" / "data" / name
        if not path.exists():
            pytest.skip("reference files missing: uv run python tests/reference/fetch.py")
        return path

    return get
