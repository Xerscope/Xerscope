"""The container keeps the app's security defaults (no Docker needed to run this)."""

import re
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


def test_only_a_tested_commit_is_published():
    """image.yml runs after a `tests` run, publishes only when that run succeeded on a push (main or
    a v* tag, both tested), and builds that run's commit. A workflow_run sees main as github.ref and
    github.sha: tags and revision come from the triggering run, never from {{is_default_branch}} or type=sha."""
    image = (ROOT / ".github" / "workflows" / "image.yml").read_text()
    on = image[image.index("\non:") : image.index("\nconcurrency:")]
    assert "workflow_run:" in on and "workflows: [tests]" in on and "types: [completed]" in on
    assert 'branches: [main, "v*"]' in on
    assert "push:" not in on and "workflow_dispatch" not in on  # no path around the tests
    assert "github.event.workflow_run.conclusion == 'success'" in image
    assert "github.event.workflow_run.event == 'push'" in image
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in image
    assert "{{is_default_branch}}" not in image and "type=sha" not in image
    assert "type=raw,value=latest,enable=${{ github.event.workflow_run.head_branch == 'main' }}" in image
    assert "value=${{ github.event.workflow_run.head_branch }}" in image  # the semver tag
    assert "org.opencontainers.image.revision=${{ github.event.workflow_run.head_sha }}" in image
    tests = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert re.search(r"^name: tests$", tests, re.M)
    assert 'tags: ["v*"]' in tests[: tests.index("pull_request:")]  # a release tag runs the tests


def test_a_pull_request_changing_the_image_builds_and_scans_it():
    """The container job runs on a pull request whose diff touches what the image is built or
    scanned from; the filter is grep -E on `git diff --name-only`, applied here to sample paths
    (the pattern uses only ^, $, |, groups and \\., which read the same in Python's re)."""
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    changes = wf[wf.index("\n  changes:") : wf.index("\n  container:")]
    assert "if: github.event_name == 'pull_request'" in changes and "fetch-depth: 2" in changes
    assert "git diff --name-only HEAD^1 HEAD" in changes
    pattern = re.search(r"grep -qE '([^']+)' changed\.txt", changes).group(1)
    built = ["Dockerfile", "uv.lock", "pyproject.toml", "src/xerscope/cli.py", ".github/trivy/Dockerfile"]
    other = ["README.md", "docs/deploy.md", "tests/test_docker.py", "deploy/caddy/Dockerfile", "src.txt"]
    assert [path for path in built + other if re.search(pattern, path)] == built
    container = wf[wf.index("\n  container:") : wf.index("\n  deploy:")]
    assert "needs: changes" in container
    cond = "if: ${{ !cancelled() && (github.event_name != 'pull_request' || needs.changes.outputs.image == 'true') }}"
    assert cond in container


def test_runs_on_main_are_never_cancelled_by_the_next_push():
    """Only a pull request's previous run is cancelled by a new push: every commit merged to main is
    tested to the end, and a publish under way is not cut."""
    workflows = (ROOT / ".github" / "workflows").glob("*.yml")
    cancels = {p.name: re.findall(r"cancel-in-progress: (\$\{\{[^}]*\}\}|\S+)", p.read_text()) for p in workflows}
    assert cancels["tests.yml"] == ["${{ github.event_name == 'pull_request' }}"]
    assert cancels["image.yml"] == ["false"]
    assert not any(c for name, c in cancels.items() if name not in ("tests.yml", "image.yml")), cancels


def test_ci_tools_are_pinned_to_one_release():
    """A new ruff rule or a compromised release does not reach CI unannounced: every uvx tool is
    pinned to a release, and setup-uv installs the uv release the Dockerfile builds with."""
    workflows = "".join(p.read_text() for p in (ROOT / ".github" / "workflows").glob("*.yml"))
    tools = re.findall(r"run: uvx (\S+)", workflows)
    assert tools and all(re.fullmatch(r"[\w-]+@\d+\.\d+\.\d+", t) for t in tools), tools
    uv = re.search(r"^FROM ghcr\.io/astral-sh/uv:(\d+\.\d+\.\d+)-", (ROOT / "Dockerfile").read_text(), re.M).group(1)
    setups = re.findall(r"uses: astral-sh/setup-uv@\S+ # v\S+\n\s+with:\n((?:\s{10}\S.*\n)+)", workflows)
    assert len(setups) == workflows.count("astral-sh/setup-uv@"), setups
    assert all(f'version: "{uv}"' in block for block in setups), setups


def test_every_dependabot_version_update_waits_a_week():
    """Each ecosystem's version updates wait 7 days after a release; security updates do not wait
    (GitHub docs: cooldown applies to version updates, not security updates)."""
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text()
    entries = dependabot.split("  - package-ecosystem:")[1:]
    assert len(entries) == 6
    for entry in entries:
        days = re.search(r"^    cooldown:\n      default-days: (\d+)", entry, re.M)
        assert days and int(days.group(1)) >= 7, entry


def test_published_images_carry_provenance_and_sbom():
    """Each pushed image carries a full SLSA provenance and an SBOM, on ghcr.io and Docker Hub alike
    (one build-push step pushes every tag of both registries)."""
    image = (ROOT / ".github" / "workflows" / "image.yml").read_text()
    assert image.count("docker/build-push-action@") == 1
    step = image[image.index("docker/build-push-action@") :]
    assert "provenance: mode=max" in step and "sbom: true" in step
    assert "push: true" in step and "tags: ${{ steps.meta.outputs.tags }}" in step


def test_ci_cannot_pass_by_skipping_its_evidence():
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert "XERSCOPE_REQUIRE: reference,p6-corpus\n" in wf and "XERSCOPE_REQUIRE: reference,p6-corpus,mpxj" in wf
    assert re.search(r"uvx ruff@\S+ check src tests", wf) and re.search(r"uvx ruff@\S+ format --check src tests", wf)
    assert "pull_request:" in wf and "load: true" in wf and "_stcore/health" in wf
    assert ".github/trivy/scan.sh xerscope:ci" in wf  # the app image is scanned
    for line in wf.splitlines():
        if "uses:" in line:
            assert re.search(r"@[0-9a-f]{40} # v", line), line  # pinned by commit, tag in the comment


def test_sidecars_hardened():
    c = (ROOT / "deploy" / "compose.yaml").read_text()
    assert c.count("cap_drop: [ALL]") == 4 and c.count("no-new-privileges") == 4
    # one capability back, for Caddy only: its binary is setcap cap_net_bind_service, and exec fails without it
    assert c.count("cap_add:") == 1 and "cap_add: [NET_BIND_SERVICE]" in c
    app = (ROOT / "compose.yaml").read_text()  # the app's writable dirs belong to its user, not root
    assert "/home/nonroot:uid=65532,gid=65532" in app and "/tmp:uid=65532,gid=65532" in app
    nas = (ROOT / "deploy" / "compose.yaml").read_text()  # same user as `user:`, the image's nonroot by default
    uid, gid = "${XERSCOPE_UID:-65532}", "${XERSCOPE_GID:-65532}"
    assert f'user: "{uid}:{gid}"' in nas and "HOME: /home/nonroot" in nas
    assert f"/home/nonroot:uid={uid},gid={gid}" in nas and f"/tmp:uid={uid},gid={gid}" in nas
    assert "65532," not in nas.replace(uid, "").replace(gid, "")  # no uid written outside the variables
    assert 'TS_NO_LOGS_NO_SUPPORT: "true"' in c and 'TS_USERSPACE: "true"' in c


def test_runtime_image_carries_no_pip():
    """pip in the managed CPython is never run and its vendored packages carry CVEs."""
    df = (ROOT / "Dockerfile").read_text()
    assert "site-packages/pip " in df and "site-packages/pip-*.dist-info" in df and "bin/pip*" in df


def test_os_fixes_are_pinned_justified_and_listed_by_ci():
    """Each Debian fix laid over the distroless base names its exact version, has a comment line
    with the CVE it closes, reaches the runtime stage, and the CI job prints it on every run."""
    df = (ROOT / "Dockerfile").read_text()
    fixes = re.search(r'^ARG OS_FIXES="([^"]*)"', df, re.M)
    assert fixes, "OS_FIXES must stay a literal ARG: CI and this test read it"
    for entry in fixes.group(1).split():
        pkg, sep, version = entry.partition("=")
        assert sep and version, f"{entry}: package=version, an exact Debian version"
        assert re.search(rf"^#\s+{re.escape(pkg)}: CVE-\d{{4}}-\d+", df, re.M), f"{pkg}: no CVE comment"
    runtime = df[df.rindex("FROM gcr.io/distroless/") :]
    assert "COPY --from=os-fixes /out/ /" in runtime
    tests_yml = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert "Debian fixes laid over the distroless base" in tests_yml
    assert "GITHUB_STEP_SUMMARY" in tests_yml[tests_yml.index("Debian fixes laid over") :]


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
    assert c.count("mem_limit:") == 4 and c.count("pids_limit:") == 4
    assert "mem_limit: ${XERSCOPE_MEM_LIMIT:-2g}" in c
    assert not re.search(r"^\s+(cpus|cpu_quota|cpu_period|cpuset):", c, re.M)
    tmpfs = re.findall(r"^\s+- (/[\w/]+)(\S*)", c, re.M)  # tmpfs entries are the only "- /path" list items
    assert len(tmpfs) == 7 and all("size=" in opts for _, opts in tmpfs), tmpfs
    assert c.count("read_only: true") == 4  # tailscaled writes its socket to tmpfs, its state to the volume
    assert "- /var/run/tailscale:" in c  # the CLI's default socket path (containerboot symlinks it there)


def test_remote_debug_page_follows_the_env_file_and_is_off_by_default():
    """Compose reads .env only for the ${...} of the compose file: a variable the app reads reaches
    the container only through its environment block. XERSCOPE_DEBUG_PAGE=1 in .env then shows the
    Debug page on the locked instance; left unset, it stays off."""
    c = (ROOT / "deploy" / "compose.yaml").read_text()
    app = c[c.index("\n  xerscope:") :]
    assert re.search(r"^\s+XERSCOPE_DEBUG_PAGE: \$\{XERSCOPE_DEBUG_PAGE:-\}", app, re.M)
    assert re.search(r"^# XERSCOPE_DEBUG_PAGE=1\b", (ROOT / "deploy" / ".env.example").read_text(), re.M)


def test_remote_load_workers_follow_the_env_file_and_default_to_one():
    """Each worker process holds one export while it reads it (about 1 GB parsed for a 40 MB export,
    docs/deploy.md §7), inside the app's memory cap: under the default 2 GB cap the remote app reads
    one file at a time. XERSCOPE_LOAD_WORKERS in .env raises it, with XERSCOPE_MEM_LIMIT."""
    c = (ROOT / "deploy" / "compose.yaml").read_text()
    app = c[c.index("\n  xerscope:") :]
    assert re.search(r"^\s+XERSCOPE_LOAD_WORKERS: \$\{XERSCOPE_LOAD_WORKERS:-1\}", app, re.M)
    assert re.search(r"^# XERSCOPE_LOAD_WORKERS=\d", (ROOT / "deploy" / ".env.example").read_text(), re.M)


def test_remote_app_settings_reach_streamlit():
    """The remote-only settings in deploy/compose.yaml override the packaged config.toml, as the app runs."""
    import os
    import subprocess
    import sys

    c = (ROOT / "deploy" / "compose.yaml").read_text()
    assert 'XERSCOPE_DATA_LOCKED: "true"' in c
    env = dict(re.findall(r"^\s+(STREAMLIT_[A-Z_]+): \"?([^\"\s#]+)", c, re.M))
    assert env == {
        "STREAMLIT_SERVER_MAX_UPLOAD_SIZE": "1",
        "STREAMLIT_SERVER_MAX_WIDGET_STATE_SIZE": "1",  # MB per message from the browser: a sentence, a click
        "STREAMLIT_CLIENT_SHOW_ERROR_DETAILS": "none",
    }
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
    # a hidden option, not listed by `config show`: `streamlit run` reads it from this variable
    from streamlit.web import cli

    assert "STREAMLIT_SERVER_MAX_WIDGET_STATE_SIZE" in {p.envvar for p in cli.main_run.params}


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
    froms = [f.split("@")[0] for f in re.findall(r"^FROM (\S+)", df, re.M)]  # tags; the digests: their own test
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
    assert "ipv6_prefix 64" in block and "events 300" in block and "window 1m" in block
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert 'docker build -t "$XERSCOPE_CADDY_IMAGE" caddy' in wf and "HTTP/1.1 429" in wf


def test_caddy_build_forces_the_fixed_x_net_and_proves_it():
    """Caddy 2.11.8 and 2.11.9 pin golang.org/x/net v0.60.0 (CVE-2026-78661, fixed in 0.62.0). The
    image is ours, so the build replaces the module rather than excepting the finding, and fails
    unless the built binary records x/net v0.62.0 (go version -m reads the binary's build info)."""
    df = (ROOT / "deploy" / "caddy" / "Dockerfile").read_text()
    fixed = re.search(r"--replace golang\.org/x/net=golang\.org/x/net@(v\d+\.\d+\.\d+)", df)
    assert fixed and tuple(map(int, fixed.group(1)[1:].split("."))) >= (0, 62, 0), fixed
    pattern = "golang\\.org/x/net[[:space:]]+" + fixed.group(1).replace(".", "\\.")  # as the grep spells it
    assert f"go version -m /usr/bin/caddy | grep -Eq '{pattern}'" in df
    jose = re.search(r"--replace github\.com/go-jose/go-jose/v4=github\.com/go-jose/go-jose/v4@(v\d+\.\d+\.\d+)", df)
    assert jose and tuple(map(int, jose.group(1)[1:].split("."))) >= (4, 1, 6), jose  # CVE-2026-116587
    assert "grep -Eq 'github\\.com/go-jose/go-jose/v4[[:space:]]+v4\\.1\\.6'" in df


def test_base_images_pinned_by_digest():
    df = (ROOT / "Dockerfile").read_text()
    froms = re.findall(r"^FROM (\S+)", df, re.M)
    assert len(froms) == 3 and all(re.search(r":[\w.-]+@sha256:[0-9a-f]{64}$", f) for f in froms), froms


def test_no_scan_exception_file():
    """Findings are fixed or recorded, never excepted: no Trivy ignore file in the repository, and
    the scan script takes none. Every HIGH and CRITICAL finding is listed, unfixed ones included."""
    assert not list(ROOT.glob("**/*.trivyignore*")) and not list(ROOT.glob("**/.trivyignore*"))
    script = (ROOT / ".github" / "trivy" / "scan.sh").read_text()
    assert "--ignorefile" not in script and "ignorefile" not in script
    assert "--exit-code 0" in script and script.index("--exit-code 0") < script.index("--exit-code 1")
    workflows = "".join(p.read_text() for p in (ROOT / ".github" / "workflows").glob("*.yml"))
    assert "trivyignore" not in workflows and "--ignorefile" not in workflows


def test_deploy_images_are_scanned_on_pull_requests():
    """A Dependabot bump of Caddy or Tailscale is scanned before it is merged: the deploy job runs on
    pull requests and neither scan step is skipped there."""
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    deploy = wf[wf.index("\n  deploy:") :]
    for image in ("Caddy", "Tailscale"):
        step = deploy[deploy.index(f"- name: Known vulnerabilities in the {image} image") :]
        step = step[: step.index("- name:", 1)]
        assert ".github/trivy/scan.sh" in step and "pull_request" not in step, step
    assert "if:" not in deploy[: deploy.index("steps:")]  # the job itself runs on every event


def test_tailscale_x_net_html_absence_is_recorded_before_the_scan():
    """CVE-2026-78661 (golang.org/x/net v0.60.0 in the Tailscale image) is not excepted: the scan
    reports it. A step before the scan records that the vulnerable package is absent from the
    image's binaries: Go keeps every function name in its binaries even when stripped (-s -w), so
    tailscale.com/ names must be found (the names are readable) and no golang.org/x/net/html. name may be."""
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    step = wf[wf.index("No golang.org/x/net/html code in the Tailscale binaries") :]
    step = step[: step.index("- name:", 1)]
    assert all(b in step for b in ("containerboot", "tailscaled", "tailscale "))
    assert "grep -aq 'tailscale.com/'" in step and "grep -aq 'golang.org/x/net/html\\.'" in step
    assert not re.search(r"^\s*! ", step, re.M)  # bash -e does not stop on a negated command: checks use if
    assert wf.index("No golang.org/x/net/html code") < wf.index("Known vulnerabilities in the Tailscale image")


def test_trivy_is_pinned_by_digest_and_proposed_a_week_after_release():
    """CI scans with one Trivy image, pinned by digest in .github/trivy/Dockerfile and bumped by
    Dependabot after a 7-day cooldown (Trivy's compromised March 2026 releases were withdrawn
    within hours, GHSA-69fq-xp46-6x23). No Trivy GitHub Action runs: they were part of that
    compromise. The image goes to Trivy as a tar, never with the Docker socket."""
    pin = (ROOT / ".github" / "trivy" / "Dockerfile").read_text()
    (image,) = re.findall(r"^FROM (\S+)", pin, re.M)  # one image, and it is Trivy's, by digest
    assert re.fullmatch(r"ghcr\.io/aquasecurity/trivy:[\d.]+@sha256:[0-9a-f]{64}", image), image
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text()
    entry = dependabot[dependabot.index("directory: /.github/trivy") :]
    entry = entry[: entry.find("- package-ecosystem") if "- package-ecosystem" in entry else len(entry)]
    days = re.search(r"default-days: (\d+)", entry)
    assert days and int(days.group(1)) >= 7, entry
    workflows = {p.name: p.read_text() for p in (ROOT / ".github" / "workflows").glob("*.yml")}
    assert not any("aquasecurity/trivy-action" in w or "setup-trivy" in w for w in workflows.values())
    assert workflows["tests.yml"].count(".github/trivy/scan.sh") == 3
    script = (ROOT / ".github" / "trivy" / "scan.sh").read_text()
    assert "docker save" in script and "--input" in script and "docker.sock" not in script
    assert "--exit-code 1" in script and "--ignore-unfixed" in script and "HIGH,CRITICAL" in script


def test_the_pinned_trivy_is_scanned_every_day():
    """New CVEs land without a push: the Trivy CI uses is scanned with itself every day and on any
    change to its pin. A finding there allows a bump before the cooldown ends."""
    wf = (ROOT / ".github" / "workflows" / "scanner.yml").read_text()
    assert re.search(r"cron: \"\d+ \d+ \* \* \*\"", wf)  # daily
    assert "permissions:\n  contents: read" in wf and "persist-credentials: false" in wf
    assert ".github/trivy/**" in wf and '.github/trivy/scan.sh "$(sed -n' in wf


def test_the_published_images_are_scanned_every_day():
    """The images the NAS pulls are scanned by the daily scanner run with the same pinned Trivy, so a
    CVE published after the last push is seen the next day."""
    wf = (ROOT / ".github" / "workflows" / "scanner.yml").read_text()
    job = wf[wf.index("\n  published:") :]
    assert "if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'" in job
    assert "image: [ghcr.io/xerscope/xerscope:latest, ghcr.io/xerscope/xerscope-caddy:latest]" in job
    assert 'run: .github/trivy/scan.sh "$IMAGE"' in job and "IMAGE: ${{ matrix.image }}" in job
    compose = (ROOT / "deploy" / "compose.yaml").read_text()  # the tags scanned are the ones pulled
    assert "ghcr.io/xerscope/xerscope:latest}" in compose and "ghcr.io/xerscope/xerscope-caddy:latest}" in compose


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


def _uses(workflow: str) -> list[str]:
    return [line for line in workflow.splitlines() if "uses:" in line]


def test_published_images_carry_provenance_sbom_and_an_attestation():
    """SLSA provenance and an SBOM from BuildKit, a GitHub build attestation of the digest, with the
    permissions those need and no more (AUDIT-DEP-02)."""
    wf = (ROOT / ".github" / "workflows" / "image.yml").read_text()
    assert "provenance: mode=max" in wf and "sbom: true" in wf
    assert "actions/attest-build-provenance@" in wf
    assert "subject-digest: ${{ steps.build.outputs.digest }}" in wf and "push-to-registry: true" in wf
    assert "subject-name: ghcr.io/xerscope/${{ matrix.image }}" in wf  # lowercase, the name ghcr.io serves
    job = wf[wf.index("  publish:") :]
    perms = job[job.index("permissions:") : job.index("steps:")]
    assert set(re.findall(r"^\s+([\w-]+): (read|write)", perms, re.M)) == {
        ("contents", "read"),
        ("packages", "write"),
        ("id-token", "write"),
        ("attestations", "write"),
    }
    assert re.search(r"^permissions:\n  contents: read\n\n", wf, re.M)  # the workflow default stays read-only
    for line in _uses(wf):
        assert re.search(r"@[0-9a-f]{40} # v", line), line
    # a release tag publishes an immutable version tag next to latest and the commit tag (AUDIT-DEP-01)
    assert 'tags: ["v*"]' in wf and "type=semver,pattern={{version}}" in wf and "type=sha" in wf
    assert "type=raw,value=latest,enable={{is_default_branch}}" in wf


def test_codeql_and_scorecard_run_pinned_with_minimal_permissions():
    """SAST and the Scorecard measure (AUDIT-DEP-04): on main, weekly, every action pinned by commit,
    the job writing security events (and the Scorecard's OIDC token) only."""
    codeql = (ROOT / ".github" / "workflows" / "codeql.yml").read_text()
    scorecard = (ROOT / ".github" / "workflows" / "scorecard.yml").read_text()
    for wf in (codeql, scorecard):
        assert "branches: [main]" in wf and re.search(r"^\s+- cron: \"", wf, re.M)
        assert "security-events: write" in wf and "persist-credentials: false" in wf
        assert "pull_request_target" not in wf and "write-all" not in wf
        assert not re.search(r"^\s+(contents|packages|actions|checks|pull-requests|issues): write", wf, re.M)
        for line in _uses(wf):
            assert re.search(r"@[0-9a-f]{40} # v", line), line
    assert "pull_request:" in codeql and "languages: python" in codeql
    assert "github/codeql-action/init@" in codeql and "github/codeql-action/analyze@" in codeql
    assert "id-token: write" not in codeql
    assert "ossf/scorecard-action@" in scorecard and "publish_results: true" in scorecard
    assert "id-token: write" in scorecard and "github/codeql-action/upload-sarif@" in scorecard
    assert "if: github.repository == 'Xerscope/xerscope'" in scorecard  # publish_results refuses a fork
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text()
    assert "package-ecosystem: github-actions" in dependabot  # the pins move with Dependabot, not by hand


def test_caddy_base_images_pinned_by_digest():
    """deploy/caddy/Dockerfile pins its two caddy bases by digest like the app's Dockerfile (AUDIT-DEP-01);
    Dependabot (docker ecosystem, /deploy/caddy) bumps tag and digest together."""
    df = (ROOT / "deploy" / "caddy" / "Dockerfile").read_text()
    froms = re.findall(r"^FROM (\S+)", df, re.M)
    assert len(froms) == 2 and all(re.search(r":[\w.-]+@sha256:[0-9a-f]{64}$", f) for f in froms), froms
    assert froms[0].split("@")[0].removesuffix("-builder") == froms[1].split("@")[0]
    assert froms[0].split("@")[1] != froms[1].split("@")[1]  # two images, two digests


def test_deployment_documents_immutable_image_refs_and_the_key_check():
    """compose keeps :latest as the first-start default only; the guide pins a release and its digest,
    says how a release is cut and how to check TS_AUTHKEY left the container (AUDIT-DEP-01, -03)."""
    compose = (ROOT / "deploy" / "compose.yaml").read_text()
    # one :latest default per image reference: the app, caddy and lexicon-init (the app's image)
    assert compose.count(":latest}") == 3 and "docs/deploy.md §7" in compose
    env = (ROOT / "deploy" / ".env.example").read_text()
    assert "XERSCOPE_IMAGE=ghcr.io/xerscope/xerscope:0.1.0@sha256:<digest>" in env
    assert "XERSCOPE_CADDY_IMAGE=ghcr.io/xerscope/xerscope-caddy:0.1.0@sha256:<digest>" in env
    guide = (ROOT / "docs" / "deploy.md").read_text()
    assert "### Pinning and upgrading the image" in guide
    assert "docker buildx imagetools inspect ghcr.io/xerscope/xerscope:0.1.0" in guide
    assert "docker-content-digest" in guide
    assert "gh attestation verify oci://ghcr.io/xerscope/xerscope@sha256:<digest>" in guide
    assert "git tag v0.1.0" in guide and "CHANGELOG.md" in guide
    assert "docker inspect <tailscale-container> --format '{{.Config.Env}}'" in guide
    assert not re.search(r"tskey-auth-[A-Za-z0-9]{4}", guide)  # placeholders only
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert changelog.startswith("# Changelog") and "## [Unreleased]" in changelog and "## [0.1.0]" in changelog
    assert re.search(r"https://keepachangelog\.com/", changelog)  # the format it follows, linked
    readme = (ROOT / "README.md").read_text()
    assert "git tag `v0.1.0`" in readme and "CHANGELOG.md" in readme


def test_nothing_in_src_reaches_the_network():
    """No outbound code in src/: the deployed app and the CLI reach nothing."""
    outbound = re.compile(r"^\s*(import|from)\s+(urllib|socket|http\.client|requests|httpx|aiohttp|websocket)")
    offenders = {}
    for path in (ROOT / "src" / "xerscope").rglob("*.py"):
        lines = [n for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if outbound.match(line)]
        if lines:
            offenders[path.relative_to(ROOT).as_posix()] = lines
    assert not offenders, offenders
    c = (ROOT / "deploy" / "compose.yaml").read_text()
    assert re.search(r"^  internal:\n\s+internal: true", c, re.M)


def _service(compose: str, name: str) -> str:
    """The block of one service of a compose file, its comments included."""
    start = re.search(rf"\n  {name}:[ \t]*(#.*)?\n", compose).start()
    end = re.search(r"\n(  \S|\S)", compose[start + 1 :])
    return compose[start : start + 1 + end.start()] if end else compose[start:]


LEXICON = "${XERSCOPE_LEXICON_DIR:-/docker/xerscope/lexicon}"


def test_the_app_reads_the_nas_lexicon_and_writes_suggested_only():
    """The lexicon folder lives on the NAS: read-only in the app, but for suggested/, where the
    Ask corrections are appended; the app starts on its own, with the last generated/ (or none)."""
    app = _service((ROOT / "deploy" / "compose.yaml").read_text(), "xerscope")
    assert re.search(r"^\s+XERSCOPE_LEXICON: /lexicon\s", app, re.M)
    mounts = re.findall(r"^\s+- (\$\{XERSCOPE_LEXICON_DIR[^\s#]+)", app, re.M)
    assert mounts == [f"{LEXICON}:/lexicon:ro", f"{LEXICON}/suggested:/lexicon/suggested"]
    assert "depends_on" not in app and "lexicon-init" not in app


def test_the_lexicon_init_service_is_sealed():
    """lexicon-init runs `xerscope lexicon build` on demand only (a profile: `up` leaves it out,
    `docker compose run --rm lexicon-init` runs it, docs/deploy.md §10): the exports read-only,
    the lexicon read-only but for generated/ (rewritten) and suggested/ (purged), no network, no
    capability, read-only root, the app's user, no restart."""
    nas = (ROOT / "deploy" / "compose.yaml").read_text()
    init = _service(nas, "lexicon-init")
    assert re.search(r"^\s+profiles: \[lexicon\]", init, re.M)
    assert "docker compose run --rm lexicon-init" in (ROOT / "docs" / "deploy.md").read_text(encoding="utf-8")
    assert "image: ${XERSCOPE_IMAGE:-ghcr.io/xerscope/xerscope:latest}" in init  # the app's own image
    assert 'command: ["lexicon", "build", "/data", "--out", "/lexicon"]' in init
    assert 'user: "${XERSCOPE_UID:-65532}:${XERSCOPE_GID:-65532}"' in init
    assert "network_mode: none" in init and "networks:" not in init and "ports:" not in init
    assert "read_only: true" in init and "cap_drop: [ALL]" in init and "cap_add" not in init
    assert 'security_opt: ["no-new-privileges:true"]' in init
    assert 'restart: "no"' in init and "disable: true" in init  # the image's healthcheck polls the app's port
    assert re.search(r"^\s+mem_limit: \$\{XERSCOPE_MEM_LIMIT:-2g\}", init, re.M) and "pids_limit:" in init
    mounts = re.findall(r"^\s+- (\S+:/(?:data|lexicon)\S*)", init, re.M)
    assert mounts == [
        "${XERSCOPE_EXPORTS:-../exports}:/data:ro",
        f"{LEXICON}:/lexicon:ro",
        f"{LEXICON}/generated:/lexicon/generated",
        f"{LEXICON}/suggested:/lexicon/suggested",
    ]
    writable = [m for m in mounts if not m.endswith(":ro")]
    assert all(m.split(":")[-1] in ("/lexicon/generated", "/lexicon/suggested") for m in writable)


def test_the_compose_file_is_valid_for_docker_compose(tmp_path):
    import shutil
    import subprocess

    if not shutil.which("docker"):
        pytest.skip("docker CLI not installed")
    env = {"PATH": "/usr/bin:/bin", "XERSCOPE_USER": "u", "XERSCOPE_PASSWORD_HASH": "h", "XERSCOPE_PATH": "p"}
    done = subprocess.run(
        [
            *("docker", "compose", "-f", str(ROOT / "deploy" / "compose.yaml")),
            *("--profile", "lexicon", "config", "--format", "json"),
        ],
        capture_output=True,
        text=True,
        env={**env, "HOME": str(tmp_path)},
        check=False,
    )
    if "unknown command" in done.stderr or "is not a docker command" in done.stderr:
        pytest.skip("docker compose plugin not installed")
    assert done.returncode == 0, done.stderr
    import json

    services = json.loads(done.stdout)["services"]
    init, app = services["lexicon-init"], services["xerscope"]
    assert init["network_mode"] == "none" and init["read_only"] and init["cap_drop"] == ["ALL"]
    writable = sorted(v["target"] for v in init["volumes"] if not v.get("read_only"))
    assert writable == ["/lexicon/generated", "/lexicon/suggested"]
    assert sorted(v["target"] for v in app["volumes"] if not v.get("read_only")) == ["/lexicon/suggested"]
    assert init["profiles"] == ["lexicon"] and "lexicon-init" not in app.get("depends_on", {})


def test_no_lexicon_file_goes_into_the_image():
    """The build context is src/ (.dockerignore); no file under src/xerscope holds lexicon
    tables, whatever its name: every *.toml there is a standard or Streamlit's config."""
    import tomllib

    package = ROOT / "src" / "xerscope"
    for path in package.rglob("*.toml"):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        assert not {"group", "refuse", "suggestion"} & set(data), path
        assert "standard" in data or path.name == "config.toml", path
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert [x for x in ignore if x.startswith("!")] == ["!pyproject.toml", "!uv.lock", "!README.md", "!src/"]
