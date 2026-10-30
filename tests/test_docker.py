"""The container keeps the app's security defaults (no Docker needed to run this)."""

import re
import sys
import threading
import time
from pathlib import Path

import pytest

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
    for name in ("Caddyfile", "Caddyfile.nas"):
        caddy = (ROOT / "deploy" / name).read_text()
        assert "basic_auth" in caddy and "reverse_proxy xerscope:8501" in caddy and "auto_https off" in caddy
        assert "trusted_proxies static private_ranges" in caddy  # the visitor's IP, not tailscaled's loopback
    nas = (ROOT / "deploy" / "compose.nas.yaml").read_text()
    assert "STREAMLIT_SERVER_BASE_URL_PATH" not in nas  # Funnel strips the secret prefix: the app stays at "/"
    # userspace tailscaled relays tailnet traffic to loopback: Caddy's admin API (which can
    # rewrite the config, basic_auth included) must not exist, in any of the three Caddyfiles
    for f in ["deploy/Caddyfile", "deploy/Caddyfile.nas", "deploy/remote/supervisor.py"]:
        assert "admin off" in (ROOT / f).read_text(), f
    assert 'TS_AUTH_ONCE: "true"' in compose  # a single-use key must not be replayed on restart
    env = (ROOT / ".env.example").read_text()
    assert "XERSCOPE_PASSWORD_HASH='$" in env  # unquoted, Compose interpolates the $ of a bcrypt hash
    serve = (ROOT / "deploy" / "tailscale-serve.json").read_text()
    assert '"AllowFunnel"' in serve and "127.0.0.1:8080" in serve


def test_nas_compose_pulls_the_published_image_and_publishes_nothing():
    compose = (ROOT / "deploy" / "compose.nas.yaml").read_text()
    assert "build:" not in compose and re.search(r"image: \S+/xerscope:", compose)
    assert (
        not re.search(r"^\s+ports:", compose, re.M)
        and 'TS_USERSPACE: "true"' in compose
        and 'TS_AUTH_ONCE: "true"' in compose
        and "internal: true" in compose
    )
    wf = (ROOT / ".github" / "workflows" / "image.yml").read_text()
    assert "packages: write" in wf and "ghcr.io" in wf and "push: true" in wf


def test_ci_cannot_pass_by_skipping_its_evidence():
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert "XERSCOPE_REQUIRE: reference,p6-corpus\n" in wf and "XERSCOPE_REQUIRE: reference,p6-corpus,mpxj" in wf
    assert "ruff check src tests" in wf and "ruff format --check src tests" in wf
    assert "pull_request:" in wf and "load: true" in wf and "_stcore/health" in wf and "trivy-action" in wf
    for line in wf.splitlines():
        if "uses:" in line:
            assert re.search(r"@[0-9a-f]{40} # v", line), line  # pinned by commit, tag in the comment


def test_sidecars_hardened():
    for f in ["compose.funnel.yaml", "deploy/compose.nas.yaml"]:
        c = (ROOT / f).read_text()
        assert c.count("cap_drop: [ALL]") == 3 and c.count("no-new-privileges") == 3, f
        assert 'TS_NO_LOGS_NO_SUPPORT: "true"' in c and 'TS_USERSPACE: "true"' in c, f


def test_remote_image_keeps_everything_on_the_container_loopback():
    """One image for a host that can only run images: no published port, no TUN device,
    Caddy and xerscope bound to 127.0.0.1, non-root, SIGTERM stops every child."""
    df = (ROOT / "Dockerfile.remote").read_text()
    assert "distroless/cc-debian13:nonroot" in df and "USER nonroot" in df and "EXPOSE" not in df
    assert "FROM tailscale/tailscale:" in df and "FROM caddy:" in df
    sup = (ROOT / "deploy" / "remote" / "supervisor.py").read_text()
    assert "--tun=userspace-networking" in sup and "--accept-routes=false" in sup
    assert "default_bind 127.0.0.1" in sup and "\\n:8080 {" in sup  # loopback bind, any Host header
    assert "127.0.0.1:8080 {" not in sup  # a host in the site address would reject Funnel's Host header
    assert '"--server.address", "127.0.0.1"' in sup and "reverse_proxy 127.0.0.1:8501" in sup
    assert "signal.SIGTERM" in sup and "finally:" in sup


# --- the remote supervisor, run for real with harmless children ---------------------------------


def _supervisor():
    import importlib.util

    spec = importlib.util.spec_from_file_location("supervisor", ROOT / "deploy" / "remote" / "supervisor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_supervisor_kills_a_child_that_ignores_sigterm():
    sup = _supervisor()
    procs = sup.Procs()
    procs.start("polite", [sys.executable, "-c", "import time; time.sleep(60)"])
    procs.start(
        "deaf",
        [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"],
    )
    time.sleep(1.0)  # let the handler install
    procs.stop()
    t0 = time.monotonic()
    procs.wait(timeout=2)
    assert time.monotonic() - t0 < 10
    assert all(p.poll() is not None for p in procs.procs.values())
    assert procs.procs["deaf"].returncode == -9 and procs.procs["polite"].returncode == -15


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_supervisor_restarts_a_dead_child_and_keeps_the_liveness_file(tmp_path, monkeypatch):
    sup = _supervisor()
    monkeypatch.setattr(sup, "ALIVE", tmp_path / "alive")
    procs = sup.Procs()
    procs.start("short", [sys.executable, "-c", "import time; time.sleep(0.2)"])
    procs.last["short"] -= 10  # no back-off for the test
    procs.start("long", [sys.executable, "-c", "import time; time.sleep(60)"])
    first_pid = procs.procs["short"].pid
    threading.Timer(3.0, procs.stop).start()
    assert procs.watch() == 0
    procs.wait(timeout=2)
    assert procs.procs["short"].pid != first_pid  # restarted
    assert (tmp_path / "alive").exists()


def test_url_path_accepts_a_safe_prefix_only(monkeypatch, capsys):
    sup = _supervisor()
    monkeypatch.setenv("XERSCOPE_PATH", "/k7Qx2mPz-aB_cdefgh/")
    assert sup.url_path() == "/k7Qx2mPz-aB_cdefgh"
    monkeypatch.setenv("XERSCOPE_PATH", "short")
    assert sup.url_path() == "/short" and "16 or more" in capsys.readouterr().out
    monkeypatch.setenv("XERSCOPE_PATH", "a/b")
    with pytest.raises(SystemExit):
        sup.url_path()
    monkeypatch.setenv("XERSCOPE_PATH", "")
    assert sup.url_path() == ""
