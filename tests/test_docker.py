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
    assert "trusted_proxies static 127.0.0.1/32" in caddy  # the visitor's IP, trusted from tailscaled's loopback only
    # userspace tailscaled relays tailnet traffic to loopback: Caddy's admin API (which can
    # rewrite the config, basic_auth included) must not exist
    assert "admin off" in caddy
    env = (ROOT / "deploy" / ".env.example").read_text()
    assert "XERSCOPE_PASSWORD_HASH='$" in env  # unquoted, Compose interpolates the $ of a bcrypt hash
    # each wrong password costs the NAS one bcrypt run, without CPU quota: cost 10, not Caddy's 14
    assert "'$2a$10$...'" in env and "--bcrypt-cost 10" in env
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    for text in (env, wf, (ROOT / "docs" / "deploy.md").read_text(), (ROOT / "README.md").read_text()):
        assert "hash-password --plaintext" not in text  # the default cost is 14
    serve = (ROOT / "deploy" / "tailscale-serve.json").read_text()
    assert '"AllowFunnel"' in serve and "127.0.0.1:8080" in serve
    assert '"/"' in serve  # the secret prefix is Caddy's job (XERSCOPE_PATH), serve.json is not edited
    assert "handle_path /{$XERSCOPE_PATH}/*" in caddy and "respond 404" in caddy  # 404 before auth elsewhere
    assert "request>uri regexp {$XERSCOPE_PATH} <prefix>" in caddy  # no prefix in the log, the rest of the path kept
    assert "resp_headers>Location regexp {$XERSCOPE_PATH} <prefix>" in caddy


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
    assert c.count("cap_drop: [ALL]") == 5 and c.count("no-new-privileges") == 5  # tailscale, caddy, app, llm, llm-tls
    # one capability back, for Caddy only: its binary is setcap cap_net_bind_service, and exec fails without it
    assert c.count("cap_add:") == 2 and c.count("cap_add: [NET_BIND_SERVICE]") == 2  # the two Caddy binaries
    app = (ROOT / "compose.yaml").read_text()  # the app's writable dirs belong to its user, not root
    assert "/home/nonroot:uid=65532,gid=65532" in app and "/tmp:uid=65532,gid=65532" in app
    nas = (ROOT / "deploy" / "compose.yaml").read_text()  # same user as `user:`, the image's nonroot by default
    uid, gid = "${XERSCOPE_UID:-65532}", "${XERSCOPE_GID:-65532}"
    assert f'user: "{uid}:{gid}"' in nas and "HOME: /home/nonroot" in nas
    assert f"/home/nonroot:uid={uid},gid={gid}" in nas and f"/tmp:uid={uid},gid={gid}" in nas
    assert "65532," not in nas.replace(uid, "").replace(gid, "")  # no uid written outside the variables
    assert 'TS_NO_LOGS_NO_SUPPORT: "true"' in c and 'TS_USERSPACE: "true"' in c


def test_llm_sidecar_is_optional_and_reaches_nothing():
    """The language model behind the Gantt Ask field: off unless asked; on a network of its own where
    nothing listens; rootless, read-only, noexec, no IPC, pinned; on its loopback behind a TLS front
    with a certificate made on the NAS and a key on every request; the app's default stays the grammar."""
    c = (ROOT / "deploy" / "compose.yaml").read_text()
    llm = c[c.index("  llm:") : c.index("  llm-tls:")]
    tls = c[c.index("  llm-tls:") : c.index("\nvolumes:")]
    app = c[c.index("  xerscope:") : c.index("  llm:")]
    uid, gid = "${XERSCOPE_UID:-65532}", "${XERSCOPE_GID:-65532}"
    assert "profiles: [ai]" in llm and "profiles: [ai]" in tls and "ports:" not in llm and "ports:" not in tls
    # the model's network holds the model and the app; the app listens on its `internal` address alone
    assert re.search(r"networks:[^\n]*\n\s+ai:[^\n]*\n\s+ipv4_address: 172\.29\.0\.20", llm)
    assert "internal:" not in llm and "egress" not in llm
    assert '["app", "--host", "172.28.0.10", "--port", "8501"]' in app
    assert "http://172.28.0.10:8501/_stcore/health" in app and "ipv4_address: 172.28.0.10" in app
    assert "# ai:" in app and "#   ipv4_address: 172.29.0.10" in app
    assert re.search(r"^  ai:[^\n]*\n\s+internal: true", c, re.M) and "subnet: 172.29.0.0/24" in c
    assert "subnet: 172.28.0.0/24" in c
    # rootless and sealed, both of them
    assert re.search(r"image: ghcr\.io/ggml-org/llama\.cpp:server-b\d+", llm)  # a build number, not a floating tag
    assert f'user: "{uid}:{gid}"' in llm and f'user: "{uid}:{gid}"' in tls
    for part in (llm, tls):
        assert "read_only: true" in part and "ipc: none" in part and "mem_limit:" in part and "pids_limit:" in part
        assert "cap_drop: [ALL]" in part and "no-new-privileges" in part
        tmpfs = re.findall(r"^\s+- /[\w/]+:(\S+)", part, re.M)
        assert tmpfs and all("noexec,nosuid" in opts and f"uid={uid}" in opts for opts in tmpfs), tmpfs
    assert ":/models:ro" in llm and llm.count(":/") == 1  # one mount: the model folder, read-only
    assert "- ./llm-certs:/certs:ro" in tls and "- ./llm.Caddyfile:/etc/caddy/Caddyfile:ro" in tls
    assert "llm-pki" not in c  # no volume anything writes
    assert "--parallel 1" in llm  # one visitor: no second model context on the NAS's memory
    assert "--cache-reuse 256" in llm  # the vocabulary prefix, read once at the file's load, is kept
    # the model listens on its loopback; the TLS front shares its namespace and is the only listener
    # on the fixed address; the key is required (the model does not start without one), never logged
    assert "LLAMA_ARG_HOST: 127.0.0.1" in llm and "LLAMA_API_KEY: ${XERSCOPE_LLM_KEY:-}" in llm
    assert 'test -n "$$LLAMA_API_KEY" ||' in llm and "exit 1" in llm
    assert "network_mode: service:llm" in tls and re.search(r"image: caddy:\d+\.\d+\.\d+", tls)
    caddy = (ROOT / "deploy" / "llm.Caddyfile").read_text()
    assert "admin off" in caddy and "auto_https off" in caddy and "default_bind 172.29.0.20" in caddy
    assert "https://172.29.0.20:8443" in caddy and "tls /certs/llm.crt /certs/llm.key" in caddy
    assert "reverse_proxy 127.0.0.1:8080" in caddy and "tls internal" not in caddy
    assert "request>headers>Authorization delete" in caddy  # the key never reaches a log
    # the app names the model by its fixed address, over TLS, trusting the model's certificate alone, with the key
    assert "# XERSCOPE_QUERY_URL: https://172.29.0.20:8443" in app  # told by hand, never on by default
    assert "# XERSCOPE_QUERY_KEY: ${XERSCOPE_LLM_KEY:-}" in app and "# XERSCOPE_QUERY_CA: /run/llm-ca.crt" in app
    assert "# - ./llm-certs/llm.crt:/run/llm-ca.crt:ro" in app  # the certificate, never the key
    assert "llm.key" not in app and "http://llm:" not in c
    assert "http://172.2" not in c.replace("http://172.28.0.10:8501/_stcore", "")
    env = (ROOT / "deploy" / ".env.example").read_text()
    assert "# XERSCOPE_QUERY_URL=https://172.29.0.20:8443" in env and "# XERSCOPE_MODELS=" in env
    assert "# XERSCOPE_LLM_KEY=<random>" in env  # a placeholder, never a value
    assert "deploy/llm-certs/" in (ROOT / ".gitignore").read_text()
    for text in (c, env, caddy, (ROOT / "docs" / "deploy.md").read_text()):
        assert "api.openai.com" not in text and "anthropic.com" not in text  # self-hosted only


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
    assert "request>uri regexp {$XERSCOPE_PATH} <prefix>" in global_block
    assert "request>headers>Referer regexp {$XERSCOPE_PATH} <prefix>" in global_block


def test_tailscale_key_is_optional_once_the_node_exists():
    """TS_AUTH_ONCE: the key is read on the first start only, so it can leave the NAS afterwards."""
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    assert "TS_AUTHKEY: ${TS_AUTHKEY:-}" in compose and 'TS_AUTH_ONCE: "true"' in compose


def test_funnel_stack_bounds_what_it_takes_from_the_nas():
    """A memory and a PID cap per container and bounded tmpfs, so the app cannot starve the NAS.
    No CPU quota: Docker refuses to create a container with one on a kernel without CFS
    bandwidth control, while it only drops a memory or PID cap it cannot apply."""
    c = (ROOT / "deploy" / "compose.yaml").read_text()
    assert c.count("mem_limit:") == 5 and c.count("pids_limit:") == 5  # tailscale, caddy, app, llm, llm-tls
    assert "mem_limit: ${XERSCOPE_MEM_LIMIT:-2g}" in c
    assert not re.search(r"^\s+(cpus|cpu_quota|cpu_period|cpuset):", c, re.M)
    tmpfs = re.findall(r"^\s+- (/[\w/]+)(\S*)", c, re.M)  # tmpfs entries are the only "- /path" list items
    assert len(tmpfs) == 11 and all("size=" in opts for _, opts in tmpfs), tmpfs
    assert c.count("read_only: true") == 5  # tailscaled writes its socket to tmpfs, its state to the volume
    assert "- /var/run/tailscale:" in c  # the CLI's default socket path (containerboot symlinks it there)


def test_remote_app_settings_reach_streamlit():
    """The remote-only settings in deploy/compose.yaml override the packaged config.toml, as the app runs."""
    import os
    import subprocess
    import sys

    c = (ROOT / "deploy" / "compose.yaml").read_text()
    assert 'XERSCOPE_DATA_LOCKED: "true"' in c
    env = dict(re.findall(r"^\s+(STREAMLIT_[A-Z_]+): \"?([^\"\s#]+)", c, re.M))
    assert env == {"STREAMLIT_SERVER_MAX_UPLOAD_SIZE": "1", "STREAMLIT_CLIENT_SHOW_ERROR_DETAILS": "none"}
    app_dir = ROOT / "src" / "xerscope" / "app"  # `xerscope app` runs Streamlit from here (cli.py)
    shown = subprocess.run(
        [sys.executable, "-m", "streamlit", "config", "show"],
        cwd=app_dir,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "\nmaxUploadSize = 1\n" in shown and '\nshowErrorDetails = "none"\n' in shown


def test_caddy_security_headers_and_their_ci_check():
    caddy = (ROOT / "deploy" / "Caddyfile").read_text()
    headers = (
        "Referrer-Policy no-referrer",
        "X-Content-Type-Options nosniff",
        "frame-ancestors 'self'",
        'Strict-Transport-Security "max-age=31536000"',
        'Permissions-Policy "camera=(), microphone=(), geolocation=()"',
    )
    for line in headers:
        assert line in caddy, line
    block = caddy[caddy.index("    header {") : caddy.index("    }", caddy.index("    header {"))]
    # a deletion defers the whole block, and deferred ops skip the 401: -Server has its own directive
    assert "-Server" not in block and "    header -Server" in caddy
    assert "header @download >Cache-Control no-store" in caddy and "@download path /media/*" in caddy
    # the page names the hashed JS chunks of the running image: revalidated, so a reload after an update
    # never asks for chunks the new image no longer has; the chunks themselves keep their cache
    assert "@page path / /index.html" in caddy and "header @page >Cache-Control no-cache" in caddy
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text()  # the deploy job runs Caddy and reads them
    assert "docker compose up -d tailscale caddy" in wf and "frame-ancestors 'self'" in wf
    assert "Strict-Transport-Security" in wf and "Permissions-Policy" in wf


def test_caddy_logs_keep_no_token_and_no_project_code():
    """Streamlit's WebSocket subprotocol carries its XSRF token and session id, and the tables
    export is named after the project code: both logs drop them."""
    caddy = (ROOT / "deploy" / "Caddyfile").read_text()
    assert caddy.count("request>headers>Sec-Websocket-Protocol delete") == 2  # error log and access log
    assert "resp_headers>Content-Disposition delete" in caddy


def test_caddy_image_carries_the_rate_limit_module_at_pinned_versions():
    """The stock caddy image has no rate_limit: deploy/ runs Caddy built from deploy/caddy/Dockerfile,
    published by image.yml next to the app (ghcr and the Docker Hub copy), at one Caddy release
    and one caddy-ratelimit commit."""
    df = (ROOT / "deploy" / "caddy" / "Dockerfile").read_text()
    froms = re.findall(r"^FROM (\S+)", df, re.M)
    assert len(froms) == 2 and froms[0].startswith("caddy:") and froms[0].endswith("-builder"), froms
    assert froms[0].removesuffix("-builder") == froms[1]  # builder and runtime: the same Caddy release
    assert re.search(r"^FROM caddy:\d+\.\d+\.\d+", df, re.M)  # a release, not a moving 2 or latest
    module = re.search(r"--with github\.com/mholt/caddy-ratelimit@(\S+)", df).group(1)
    # a tag or a pseudo-version (one commit), which Go checks against sum.golang.org; never a branch
    assert re.fullmatch(r"v\d+\.\d+\.\d+(-0\.\d{14}-[0-9a-f]{12})?", module), module
    assert "grep -qx http.handlers.rate_limit" in df  # the build fails without the module
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    assert "image: ${XERSCOPE_CADDY_IMAGE:-ghcr.io/xerscope/xerscope-caddy:" in compose
    assert "XERSCOPE_CADDY_IMAGE=<docker-hub-login>/xerscope-caddy" in (ROOT / "deploy" / ".env.example").read_text()
    image = (ROOT / ".github" / "workflows" / "image.yml").read_text()
    assert "{ image: xerscope-caddy, context: deploy/caddy, file: deploy/caddy/Dockerfile }" in image
    assert "docker.io/${{ vars.DOCKERHUB_IMAGE_OWNER }}/${{ matrix.image }}" in image  # the Docker Hub fallback
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text()
    assert "directory: /deploy/caddy" in dependabot
    caddy = (ROOT / "deploy" / "Caddyfile").read_text()
    block = caddy[caddy.index("rate_limit {") : caddy.index("basic_auth {")]
    assert "key {client_ip}" in block  # the visitor; {remote_host} is tailscaled's 127.0.0.1 for everyone
    assert "ipv6_prefix 64" in block and "events 120" in block and "window 1m" in block
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert 'docker build -t "$XERSCOPE_CADDY_IMAGE" caddy' in wf and "HTTP/1.1 429" in wf


def test_base_images_pinned_by_digest():
    df = (ROOT / "Dockerfile").read_text()
    froms = re.findall(r"^FROM (\S+)", df, re.M)
    assert len(froms) == 2 and all(re.search(r":[\w.-]+@sha256:[0-9a-f]{64}$", f) for f in froms), froms


def test_caddy_scan_exceptions_are_dated_and_reasoned():
    """Each Trivy exception for the Caddy image names its CVE, why it is not reachable here, and an expiry."""
    import datetime

    text = (ROOT / "deploy" / "caddy.trivyignore.yaml").read_text()
    entries = re.findall(r"- id: (\S+)\n\s+statement: (.+)\n\s+expired_at: (\d{4}-\d{2}-\d{2})", text)
    assert entries and len(entries) == text.count("- id:"), entries
    for cve, statement, expiry in entries:
        assert cve.startswith(("CVE-", "GHSA-")) and len(statement) > 20, cve
        datetime.date.fromisoformat(expiry)
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert wf.count("trivyignores:") == 1 and "trivyignores: deploy/caddy.trivyignore.yaml" in wf


def test_schedules_stay_out_of_git():
    """Real exports never reach the public repository: the folders the compose files read and
    every .xer are ignored, CI fails on a tracked one, and the remote stack logs to the NAS default driver."""
    import subprocess

    probes = ["exports/a.xer", "deploy/a.xer", "a.XER", "data/a.xer", "export/a.csv"]
    out = subprocess.run(["git", "check-ignore", *probes], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert out.split() == probes
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert not re.search(r"\.(xer|parquet|xlsx?|csv)$", tracked, re.I | re.M)
    assert "git ls-files | grep -iE" in (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    c = (ROOT / "deploy" / "compose.yaml").read_text()
    # the daemon's default driver: Container Manager's Log tab shows nothing for json-file or local
    assert not re.search(r"^\s+logging:", c, re.M)
