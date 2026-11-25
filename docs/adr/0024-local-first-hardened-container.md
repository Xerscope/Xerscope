# ADR-0024: Local first: localhost only, and a distroless, non-root, read-only container published on loopback

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`49ad764`, "initial git commit": `address = "localhost"`, XSRF on, usage statistics off, the uv build on distroless, `127.0.0.1:8501:8501` in `compose.yaml`); runtime `cc-debian13:nonroot` the same day (`8221f3a`, "Review 2026 10 29", #2); pip removed from the managed CPython on 2026-10-30 (`68f7e34`, #9); tmpfs owned by the image's user on 2026-10-30 (`db432e8`, #8); Debian fixes laid over the base on 2026-11-09 (`3577903`, #170); Streamlit's table download off on 2026-11-04 (`1d9cf77`, #58) |
| Scope | `src/xerscope/app/.streamlit/config.toml`, `src/xerscope/cli.py` (`app --host`), `src/xerscope/app/files_window.py` (uploads), `Dockerfile`, `.dockerignore`, `compose.yaml` |
| Sources | Streamlit configuration options (`server.address`, `server.enableXsrfProtection`, `browser.gatherUsageStats`, `client.disableDataExport`); distroless images (`gcr.io/distroless/cc-debian13`, user `nonroot`, uid 65532); uv, "Using uv in Docker"; [SECURITY.md](../../SECURITY.md), scope; [README.md](../../README.md), "Quick start" ("Docker"); commits `49ad764`, `8221f3a`, `68f7e34`, `db432e8`, `3577903` |

## Context

The schedules xerscope reads are confidential: activity names, WBS, resources and dates of a
company's projects. A planner runs the app on a workstation or in Docker on a PC. Streamlit, by
default, listens on every interface, sends usage statistics, and lets every table be downloaded
as CSV. A container image brings its own risks: a shell and a package manager an attacker can
use, a root user, a writable root filesystem, and OS packages whose vulnerabilities the scanner
reports. Any exposure beyond the machine must be a deliberate choice with authentication in
front (ADR-0025).

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Streamlit's defaults: every interface, a usual Python base image (`python:slim`) running as root | nothing to configure | the schedules reachable from the network; a shell, pip and apt inside; root in the container |
| A hosted service holding the schedules | an account, a server | the data leaves the user's machine: against the premise |
| **Localhost by default; an image built by uv from `uv.lock`, run on distroless `cc` as `nonroot`, published on the host's loopback only, read-only, no capability (chosen)** | a two-stage build; the Debian fixes laid over the base by hand until the base carries them | no shell in the image for debugging; publishing wider is a deliberate edit of `compose.yaml` |

## Decision

**The app on a workstation** (`app/.streamlit/config.toml`, read because `xerscope app` runs
Streamlit from the app folder, `cli._cmd_app`):

- `[server] address = "localhost"`; `xerscope app --host` defaults to `localhost` and passes it as
  `--server.address`; `0.0.0.0` "exposes your schedules to the network" (its help text);
- `enableXsrfProtection = true`, `enableCORS = true`;
- `[browser] gatherUsageStats = false`, also passed on the command line;
- `[client] disableDataExport = true` (no CSV download or clipboard copy from a table; ADR-0023)
  and `toolbarMode = "viewer"`;
- `enableStaticServing = true` serves the self-hosted fonts of `app/static/`: no request leaves
  for a font host;
- an uploaded XER is kept in the session's memory only and never written to disk (the Files
  window's help text); `maxUploadSize = 200` MB per file.

**The image** (`Dockerfile`):

- three stages, every base pinned by digest (ADR-0026); `os-fixes` and `build` start from
  `ghcr.io/astral-sh/uv:0.13.8-trixie-slim`. `build` installs a uv-managed CPython (`PYTHON_VERSION=3.14`,
  `UV_PYTHON_PREFERENCE=only-managed`) and runs `uv sync --locked --no-dev` twice (dependencies,
  then the package, `--no-editable`) into `/app/.venv`; it removes pip, its dist-info and its
  scripts from the managed CPython, never run in the image and whose vendored packages the
  scanner flags;
- `os-fixes` downloads the Debian packages listed in `ARG OS_FIXES` (each `package=version`
  with a comment naming the CVE it closes; today `zlib1g`), extracts them and writes their dpkg
  record and md5sums under `/var/lib/dpkg/status.d`, so the scanner reads the fixed version; an
  entry is removed once a distroless digest ships it;
- runtime `gcr.io/distroless/cc-debian13:nonroot` (glibc and libstdc++ for pyarrow, no shell, no
  package manager), the fixes, the interpreter and the venv copied at the same paths, `/data`
  owned by `nonroot`, `USER nonroot`, `XERSCOPE_DATA=/data`, Streamlit's file watcher off;
- `HEALTHCHECK` reads `http://127.0.0.1:8501/_stcore/health` with the venv's Python;
- `ENTRYPOINT ["/app/.venv/bin/xerscope"]`, `CMD ["app", "--host", "0.0.0.0", "--port", "8501"]`:
  inside the container the app must listen on all interfaces to be reachable at all; what reaches
  it is decided where the port is published;
- the build context is `pyproject.toml`, `uv.lock`, `README.md` and `src/` only (`.dockerignore`).

**The compose file** (`compose.yaml`): `ports: ["127.0.0.1:8501:8501"]` only, `./exports`
mounted on `/data:ro`, `read_only: true`, tmpfs `/tmp` and `/home/nonroot` owned by uid/gid 65532
(some Docker builds mount a bare tmpfs root-only and Streamlit then fails reading
`~/.streamlit/secrets.toml`), `cap_drop: [ALL]`, `no-new-privileges:true`,
`restart: unless-stopped`. Publishing wider (`"8501:8501"`) is a deliberate change: the comment
asks for authentication in front.

## Consequences

Positive:

- On a workstation the schedules are reachable from the machine itself only; nothing is sent to
  Streamlit's telemetry; an upload never lands on disk.
- In the container, an attacker who reaches code execution finds no shell, no package manager,
  no pip, no root, no writable root filesystem and no capability.
- Every dependency comes from `uv.lock`; the image's OS packages are those of a pinned distroless
  digest plus a named, justified list of fixes.

Negative:

- No shell in the image: a diagnosis goes through the CLI (`docker run --rm <image> --help`: the entrypoint is `xerscope`)
  or the Debug page, not `docker exec sh`.
- `OS_FIXES` is maintained by hand: an entry stays until a distroless digest carries the fix.
- A remote reader needs the separate stack of `deploy/` (ADR-0025).

Follow-ups: [docs/backlog.md](../backlog.md), "Deployment and CI": the container job reads the
health endpoint but runs no page through the published port.

## Verification

- `tests/test_docker.py::test_compose_publishes_on_loopback_only`,
  `::test_image_runs_as_nonroot_from_the_lockfile` (distroless `cc-debian13:nonroot`,
  `USER nonroot`, two `uv sync --locked --no-dev`), `::test_build_context_holds_only_the_package`,
  `::test_runtime_image_carries_no_pip`, `::test_os_fixes_are_pinned_justified_and_listed_by_ci`,
  `::test_base_images_pinned_by_digest`, `::test_sidecars_hardened` (the tmpfs of `compose.yaml`
  owned by 65532), `::test_nothing_in_src_reaches_the_network`.
- `tests/test_cli.py::test_app_stays_on_localhost_and_uses_the_packaged_theme`.
- `tests/test_analysis_and_viz.py::test_tables_offer_no_raw_data_export`,
  `::test_menu_offers_the_theme_switch_and_no_developer_options`.
- `.github/workflows/tests.yml`, job `container`: the image builds, starts, answers on 8501 and
  reads a mounted folder; prints the Debian fixes laid over the base; Trivy scans it (ADR-0028).

## References

- `src/xerscope/app/.streamlit/config.toml` (`[server]`, `[browser]`, `[client]`).
- `src/xerscope/cli.py`: `_args_app`, `_cmd_app`.
- `src/xerscope/app/files_window.py` (the uploader's help: session memory only).
- `Dockerfile` (`PYTHON_VERSION`, `OS_FIXES`, stages `os-fixes`, `build`, runtime), `.dockerignore`,
  `compose.yaml`.
- [README.md](../../README.md), "Quick start" ("Docker"); [SECURITY.md](../../SECURITY.md), scope.
- Related: ADR-0023 (CSV neutralisation), ADR-0025 (remote access), ADR-0026 (pinned supply
  chain), ADR-0028 (security scanning).
