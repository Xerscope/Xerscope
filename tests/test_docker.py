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
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    assert not re.search(r"^\s+ports:", compose, re.M) and "network_mode: host" not in compose
    assert 'TS_USERSPACE: "true"' in compose and "internal: true" in compose
    assert "networks: [egress, internal]" in compose  # tailscaled needs a route out; the app has none
    assert "network_mode: service:tailscale" in compose  # Caddy shares the Tailscale namespace
    assert "--advertise-routes" not in compose and "exit-node" not in compose
    assert "STREAMLIT_SERVER_BASE_URL_PATH" not in compose  # Funnel strips the secret prefix: the app stays at "/"
    assert 'TS_AUTH_ONCE: "true"' in compose  # a single-use key must not be replayed on restart
    # the node state is a named volume: root without DAC_OVERRIDE cannot write a host folder owned by a NAS user
    assert "- tailscale-state:/var/lib/tailscale" in compose and "./tailscale-state" not in compose
    caddy = (ROOT / "deploy" / "Caddyfile").read_text()
    assert "basic_auth" in caddy and "reverse_proxy app:8501" in caddy and "auto_https off" in caddy
    assert "trusted_proxies static private_ranges" in caddy  # the visitor's IP, not tailscaled's loopback
    # userspace tailscaled relays tailnet traffic to loopback: Caddy's admin API (which can
    # rewrite the config, basic_auth included) must not exist
    assert "admin off" in caddy
    env = (ROOT / "deploy" / ".env.example").read_text()
    assert "XERSCOPE_PASSWORD_HASH='$" in env  # unquoted, Compose interpolates the $ of a bcrypt hash
    serve = (ROOT / "deploy" / "tailscale-serve.json").read_text()
    assert '"AllowFunnel"' in serve and "127.0.0.1:8080" in serve
    assert '"/"' in serve  # the secret prefix is Caddy's job (XERSCOPE_PATH), serve.json is not edited
    assert "handle_path /{$XERSCOPE_PATH}/*" in caddy and "respond 404" in caddy  # 404 before auth elsewhere
    assert "request>uri replace" in caddy and "resp_headers>Location delete" in caddy  # no prefix in the log


def test_funnel_stack_pulls_the_published_image_and_takes_its_secrets_from_the_environment():
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    assert "build:" not in compose  # no Dockerfile on a NAS: the image is pulled
    assert "image: ${XERSCOPE_IMAGE:-ghcr.io/xerscope/xerscope:" in compose
    for var in ("TS_AUTHKEY", "XERSCOPE_USER", "XERSCOPE_PASSWORD_HASH", "XERSCOPE_PATH", "XERSCOPE_EXPORTS"):
        assert "${" + var in compose, var  # no secret written in the file
    assert not re.search(r"tskey-auth-[A-Za-z0-9]|\$2a\$", compose)
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
    c = (ROOT / "deploy" / "compose.yaml").read_text()
    assert c.count("cap_drop: [ALL]") == 3 and c.count("no-new-privileges") == 3
    for f in ["compose.yaml", "deploy/compose.yaml"]:  # the app's writable dirs belong to its user, not root
        app = (ROOT / f).read_text()
        assert "/home/nonroot:uid=65532,gid=65532" in app and "/tmp:uid=65532,gid=65532" in app, f
    assert 'TS_NO_LOGS_NO_SUPPORT: "true"' in c and 'TS_USERSPACE: "true"' in c


def test_runtime_image_carries_no_pip():
    """pip in the managed CPython is never run and its vendored packages carry CVEs."""
    df = (ROOT / "Dockerfile").read_text()
    assert "site-packages/pip " in df and "site-packages/pip-*.dist-info" in df and "bin/pip*" in df


def test_caddy_upstream_is_not_shadowed_by_the_tailscale_hostname():
    """Caddy shares tailscale's namespace and its /etc/hosts, where tailscale's hostname maps to
    tailscale itself: an upstream with that name reaches tailscale, not the app (502, refused)."""
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    caddy = (ROOT / "deploy" / "Caddyfile").read_text()
    hostnames = re.findall(r"^\s+hostname:\s*(\S+)", compose, re.M)
    upstreams = re.findall(r"reverse_proxy\s+([\w.-]+):\d+", caddy)
    assert hostnames == ["xerscope"] and upstreams == ["app"]
    assert not set(hostnames) & set(upstreams)
    assert re.search(r"internal:\n\s+aliases: \[app\]", compose)  # the name Caddy uses, on the app's only network


def test_caddy_error_log_redacts_the_secret_prefix():
    """The site's log block filters access logs only; proxy errors go to the default logger
    with the request line, so the global log block filters it too."""
    caddy = (ROOT / "deploy" / "Caddyfile").read_text()
    global_block = caddy[caddy.index("{") : caddy.index(":8080")]
    assert "log {" in global_block and "format filter" in global_block
    assert "request>uri replace REDACTED" in global_block and "request>headers>Referer delete" in global_block


def test_tailscale_key_is_optional_once_the_node_exists():
    """TS_AUTH_ONCE: the key is read on the first start only, so it can leave the NAS afterwards."""
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    assert "TS_AUTHKEY: ${TS_AUTHKEY:-}" in compose and 'TS_AUTH_ONCE: "true"' in compose
