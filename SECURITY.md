# Security

Supported: the `main` branch and the latest published image.

Report a vulnerability through GitHub's private vulnerability reporting on this repository
(Security tab → Report a vulnerability), not in a public issue. Expect an acknowledgement
within a week.

In scope:

- the parser and the analyses: a crafted `.xer` or P6 XML file must not do more than fail to
  load;
- the web app's defaults: `localhost` only, XSRF on, telemetry off, uploads held in the
  session's memory and never saved by xerscope's own code (while a file over 1 MB arrives,
  Streamlit's upload handler passes it through a temporary file of the system's temporary
  directory, deleted once read), a folder typed in the Files window read only under
  `XERSCOPE_FOLDER_ROOT`;
- what leaves the app: every CSV neutralised against formula injection (`csv_safe.py`),
  downloads anonymised by default (*Anonymous exports*);
- the container image: non-root, read-only root filesystem; port 8501 published on
  127.0.0.1 only in `compose.yaml`, none in `deploy/`;
- the remote stack in `deploy/`: Tailscale Funnel, Caddy basic auth and rate limit, the
  secret URL prefix, the app's container without a route to the internet, the data locked
  to the exports folder (`XERSCOPE_DATA_LOCKED`: no folder field, no `.xer` upload, no Debug
  page unless `XERSCOPE_DEBUG_PAGE` asks for it), and the `lexicon-init` service run without
  network.

Out of scope: the security of a deployment that changes those defaults, the Tailscale and
Caddy software themselves (the `caddy-ratelimit` module included), and the third-party
schedules the tests download.

Dependencies are pinned in `uv.lock` with version floors in `pyproject.toml`; GitHub
Actions are pinned by commit SHA and the base images by digest. Dependabot proposes updates
(Python, Actions, Docker) after a seven-day cooldown, security updates without delay. In CI,
`pip-audit` and `bandit` run on every pull request, every push to `main` and every Monday;
CodeQL on every pull request, every push to `main` and every Monday; Trivy scans the
published images every day.
