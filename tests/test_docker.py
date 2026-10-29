"""The container keeps the app's security defaults (no Docker needed to run this)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compose_publishes_on_loopback_only():
    compose = (ROOT / "compose.yaml").read_text()
    ports = [line.strip() for line in compose.splitlines() if line.strip().startswith('- "') and ":8501" in line]
    assert ports == ['- "127.0.0.1:8501:8501"']
    assert ":/data:ro" in compose and "read_only: true" in compose and "cap_drop: [ALL]" in compose


def test_image_runs_as_nonroot_from_the_lockfile():
    df = (ROOT / "Dockerfile").read_text()
    assert "distroless/cc-debian13:nonroot" in df and "USER nonroot" in df
    assert df.count("uv sync --locked --no-dev") == 2


def test_build_context_holds_only_the_package():
    ignore = [x for x in (ROOT / ".dockerignore").read_text().splitlines() if x and not x.startswith("#")]
    assert ignore[0] == "*" and "!src/" in ignore and "!tests/" not in ignore


def test_funnel_stack_publishes_nothing_on_the_host():
    """Tailscale userspace + Caddy auth + xerscope on an internal network: no host port, no TUN."""
    compose = (ROOT / "compose.funnel.yaml").read_text()
    assert not re.search(r"^\s+ports:", compose, re.M) and "network_mode: host" not in compose
    assert 'TS_USERSPACE: "true"' in compose and "internal: true" in compose
    assert "networks: [egress, internal]" in compose  # tailscaled needs a route out; the app has none
    assert "network_mode: service:tailscale" in compose  # Caddy shares the Tailscale namespace
    assert "--advertise-routes" not in compose and "exit-node" not in compose
    caddy = (ROOT / "deploy" / "Caddyfile").read_text()
    assert "basic_auth" in caddy and "reverse_proxy xerscope:8501" in caddy and "auto_https off" in caddy
    serve = (ROOT / "deploy" / "tailscale-serve.json").read_text()
    assert '"AllowFunnel"' in serve and "127.0.0.1:8080" in serve


def test_nas_compose_pulls_the_published_image_and_publishes_nothing():
    compose = (ROOT / "deploy" / "compose.nas.yaml").read_text()
    assert "build:" not in compose and "image: mish1ma/xerscope:" in compose
    assert (
        not re.search(r"^\s+ports:", compose, re.M)
        and 'TS_USERSPACE: "true"' in compose
        and "internal: true" in compose
    )
    wf = (ROOT / ".github" / "workflows" / "image.yml").read_text()
    assert "packages: write" in wf and "ghcr.io" in wf and "push: true" in wf


def test_remote_image_keeps_everything_on_the_container_loopback():
    """One image for a host that can only run images: no published port, no TUN device,
    Caddy and xerscope bound to 127.0.0.1, non-root, SIGTERM stops every child."""
    df = (ROOT / "Dockerfile.remote").read_text()
    assert "distroless/cc-debian13:nonroot" in df and "USER nonroot" in df and "EXPOSE" not in df
    assert "FROM tailscale/tailscale:" in df and "FROM caddy:" in df
    sup = (ROOT / "deploy" / "remote" / "supervisor.py").read_text()
    assert "--tun=userspace-networking" in sup and "--accept-routes=false" in sup
    assert "default_bind 127.0.0.1" in sup and "http://127.0.0.1:8080" in sup
    assert '"--server.address", "127.0.0.1"' in sup and "reverse_proxy 127.0.0.1:8501" in sup
    assert "signal.SIGTERM" in sup and "finally:" in sup
