import pytest

from xerscope.sample import generate
from xerscope.store import SnapshotStore


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
