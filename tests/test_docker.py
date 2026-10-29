"""The container keeps the app's security defaults (no Docker needed to run this)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compose_publishes_on_loopback_only():
    compose = (ROOT / "compose.yaml").read_text()
    ports = [line.strip() for line in compose.splitlines() if line.strip().startswith('- "') and ":8501" in line]
    assert ports == ['- "127.0.0.1:8501:8501"']
    assert ":/data:ro" in compose and "read_only: true" in compose and "cap_drop: [ALL]" in compose


def test_image_runs_as_nonroot_from_the_lockfile():
    df = (ROOT / "Dockerfile").read_text()
    assert "distroless/cc-debian12:nonroot" in df and "USER nonroot" in df
    assert df.count("uv sync --locked --no-dev") == 2


def test_build_context_holds_only_the_package():
    ignore = [x for x in (ROOT / ".dockerignore").read_text().splitlines() if x and not x.startswith("#")]
    assert ignore[0] == "*" and "!src/" in ignore and "!tests/" not in ignore
