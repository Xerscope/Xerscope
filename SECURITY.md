# Security

Supported: the `main` branch and the latest published image.

Report a vulnerability through GitHub's private vulnerability reporting on this repository
(Security tab → Report a vulnerability), not in a public issue. Expect an acknowledgement
within a week.

In scope: the parser and the analyses (a crafted `.xer` must not do more than fail to
load), the web app's defaults (`localhost` only, XSRF on, telemetry off), the container
image (non-root, read-only root filesystem, no published port) and the remote stack in
`deploy/` (Tailscale Funnel, Caddy basic auth, the secret URL prefix).

Out of scope: the security of a deployment that changes those defaults, the Tailscale and
Caddy software themselves, and the third-party schedules the tests download.

Dependencies are pinned in `uv.lock` with version floors in `pyproject.toml`; Dependabot
and a weekly `pip-audit` run in CI.
