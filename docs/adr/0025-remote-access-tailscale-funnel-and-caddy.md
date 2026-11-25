# ADR-0025: Remote access through Tailscale Funnel and Caddy, with no published port

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`8221f3a`, "Review 2026 10 29", #2: "Remote access through Tailscale Funnel + Caddy, host network untouched"); one stack in `deploy/` with secrets from the environment on 2026-10-30 (`24ade64`, #4); secret prefix from `XERSCOPE_PATH` on 2026-10-30 (`6002d08`, #6); log redaction, headers, bcrypt cost 10, `caddy-ratelimit` and no XER upload on 2026-11-02 (`707921e`, #26); caps, locked data folder on 2026-11-02 (`1ce74f9`); 300 requests a minute on 2026-11-06 (`bdd27ca`, #134); connections closed and Secure cookie on 2026-11-19 (`c6b65dc`, #315); CSP and HSTS tightened on 2026-11-19 (`37323a1`, #317); a standard beside the exports on 2026-11-19 (`35f9760`, #321); HTML shell never stored on 2026-11-20 (`5ba79e5`, #333) |
| Scope | `deploy/compose.yaml`, `deploy/Caddyfile`, `deploy/caddy/Dockerfile`, `deploy/tailscale-serve.json`, `deploy/.env.example`, `src/xerscope/app/session.py` (`_data_locked`, `debug_page`), `.github/workflows/tests.yml` (job `deploy`) |
| Sources | Tailscale, Funnel and userspace networking; Caddy documentation (`basic_auth`, `handle_path`, `header`, `log` filters, `trusted_proxies`) and `github.com/mholt/caddy-ratelimit`; OWASP ASVS 5.0.0, 3.4.1 and 3.4.3 (HSTS, CSP minimum, cited in `37323a1`); [docs/deploy.md](../deploy.md) §3 (secrets), §7 (update, memory), §9 (security checklist); [README.md](../../README.md), "Deployment"; [SECURITY.md](../../SECURITY.md), scope; commits listed in Date |

## Context

Some readers of the schedules work on a corporate laptop that can install nothing (no Tailscale
client, their own VPN) and sit outside the network of the host running xerscope, a PC or a NAS.
They need a browser URL. The host must publish no port, change none of its routes or DNS, and
share its CPU and memory with other services. Every `*.ts.net` name appears in the public
certificate transparency logs and is probed by scanners within seconds. Streamlit has no
authentication of its own, keeps an XSRF token in a cookie and on its WebSocket subprotocol,
and names downloads after the project code. The local defaults (ADR-0024) still apply inside.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Publish the app's port on the host, behind a router port forward | none | the host network exposed; TLS, authentication and rate limiting all to build on the host |
| Tailscale Serve, readers on the tailnet | a Tailscale client per reader | the readers cannot install one: the problem itself |
| An all-in-one image (tailscaled, Caddy and Streamlit under a supervisor, `Dockerfile.remote`) | one container for a host without Compose | its own process management, a second image to build and scan; dropped in `24ade64` once Container Manager ran Compose projects |
| **Tailscale Funnel in userspace, Caddy in its network namespace (secret prefix, rate limit, basic auth, headers, redacted logs), the app on an internal network, nothing published (chosen)** | three images to keep current, a `.env` of secrets, a custom Caddy build | one shared password for every reader; Caddy and Tailscale software out of xerscope's control |

## Decision

**Path of a request:** `https://xerscope.<tailnet>.ts.net/<random>/` → `tailscale` (Funnel,
TLS) → `caddy` on `127.0.0.1:8080` of the same namespace → `xerscope` (alias `app`, port 8501).

**`tailscale`** (`tailscale/tailscale:v1.104.7`): `TS_USERSPACE: "true"` (no TUN device, route
or DNS change), `TS_AUTH_ONCE: "true"` (the auth key is read on the first start only;
`TS_AUTHKEY` may then be deleted), `--advertise-tags=tag:xerscope`, `TS_NO_LOGS_NO_SUPPORT`,
node state in the named volume `tailscale-state`. `tailscale-serve.json` terminates HTTPS on 443,
proxies `/` to `http://127.0.0.1:8080` and sets `AllowFunnel`. Networks `egress` (outbound to
Tailscale) and `internal`.

**`caddy`** (`deploy/caddy/Dockerfile`: `caddy:2.11.9` built with `xcaddy` and
`github.com/mholt/caddy-ratelimit` pinned to one commit, `golang.org/x/net` replaced by
`v0.63.0`; the build fails without `http.handlers.rate_limit`), `network_mode: service:tailscale`.
The `Caddyfile`:

- global: `admin off`, `auto_https off`, `default_bind 127.0.0.1`, `trusted_proxies static
  127.0.0.1/32` (the log keeps the visitor's IP);
- `redir /<prefix> /<prefix>/ 308`; `handle_path /{$XERSCOPE_PATH}/*` strips the prefix
  (Streamlit serves `/`); every other path `respond 404`, before authentication;
- inside the prefix, in order: `rate_limit` (zone `per_visitor`, key `{client_ip}`,
  `ipv6_prefix 64`, `events 300`, `window 1m`: 429 without a bcrypt run), then `basic_auth`
  (`XERSCOPE_USER`, `XERSCOPE_PASSWORD_HASH`, bcrypt cost 10, docs/deploy.md §3), then `/_stcore/metrics` and
  `/_stcore/agent/*` answer 404, then `reverse_proxy app:8501`;
- on every response, 404 and 401 included: `Referrer-Policy no-referrer`,
  `X-Content-Type-Options nosniff`, `Content-Security-Policy "frame-ancestors 'self';
  object-src 'none'; base-uri 'none'"`, `Strict-Transport-Security "max-age=31536000;
  includeSubDomains"`, `Permissions-Policy "camera=(), microphone=(), geolocation=()"`;
  `Server` removed on every response but the 401 (a deferred deletion, which does not run on
  an error); `Connection: close` on every response but a WebSocket handshake;
  `Set-Cookie` gets `; Secure`; `Cache-Control: no-store` on downloads (`/media/*`) and on the
  page itself (`/`, `/index.html`);
- logs: the prefix replaced by `<prefix>` in the request URI, Referer and redirect `Location`;
  `Sec-Websocket-Protocol` (Streamlit's XSRF token and session id) and `Content-Disposition`
  (the export's file name carries the project code) deleted; the global log block filters the
  error log (proxy errors print the request): the prefix replaced in the request URI and Referer,
  `Sec-Websocket-Protocol` deleted.

**`xerscope`** (`XERSCOPE_IMAGE`, default `ghcr.io/xerscope/xerscope:latest`, pinned by digest
in `.env`, docs/deploy.md §7): on the `internal` network only (`internal: true`, no gateway),
user `XERSCOPE_UID:XERSCOPE_GID` (default 65532), the exports mounted read-only on `/data`.
The app runs locked:

- `XERSCOPE_DATA_LOCKED: "true"`: no folder field, no XER upload (`session._data_locked`);
- the Debug page off unless `XERSCOPE_DEBUG_PAGE=1` in `.env` (`session.debug_page`), its
  runtime block hidden on this stack;
- `STREAMLIT_SERVER_MAX_UPLOAD_SIZE: "1"` (MB: only a standard can be uploaded),
  `STREAMLIT_SERVER_MAX_WIDGET_STATE_SIZE: "1"` (MB per browser message),
  `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS: none` (tracebacks to the log, not the page);
- `XERSCOPE_LOAD_WORKERS` default 1, `XERSCOPE_STANDARDS: /data` (a standard beside the
  exports), `XERSCOPE_LEXICON: /lexicon` (ADR-0021).

**Every container** (`tailscale`, `caddy`, `xerscope`, `lexicon-init`): `read_only: true`,
`cap_drop: [ALL]` (Caddy alone gets `NET_BIND_SERVICE` back, which its binary's file capability
needs to exec), `no-new-privileges`, a memory cap (256 MB for `tailscale` and `caddy`,
`XERSCOPE_MEM_LIMIT` default `2g` for the app and `lexicon-init`) and a PID cap; sized tmpfs for
`tailscale`, `caddy` and `xerscope` (`lexicon-init` has none: it writes only its two bind-mounted
folders);
no CPU quota (Docker refuses one on a kernel without CFS bandwidth control). No `ports:` in the
file. The five required settings (the secrets `TS_AUTHKEY`, `XERSCOPE_USER`,
`XERSCOPE_PASSWORD_HASH`, `XERSCOPE_PATH`, and the exports folder `XERSCOPE_EXPORTS`) come from
`deploy/.env`, interpolated by Compose; none is written in the compose file.

**The shared password is the weakest link**: README "Deployment" asks for a long one, changed
when someone leaves, and an identity-aware proxy (Cloudflare Access, OIDC) if the audience grows;
docs/deploy.md §9 says to drop Funnel for Serve with a Tailscale login the day the reader can
install Tailscale.

## Consequences

Positive:

- The host publishes nothing and keeps its network as it was; the only outbound traffic is
  Tailscale's own, and the app container has no route to the internet nor to the LAN.
- A scanner sees a 404 without the prefix, a 429 past 300 requests a minute, a 401 without the
  password; a wrong password costs one bcrypt run at cost 10.
- The logs hold what a review needs (path, status, visitor IP) and nothing reusable (prefix,
  XSRF token, file names).
- A visitor cannot point the app at another folder, upload an export, or read a traceback; the
  stack cannot starve the host's memory.

Negative:

- One login shared by every reader: no revocation of one reader alone, no reader told apart in
  the log.
- Three images to keep current: Caddy with its module is built by the project
  (`image.yml`), the module bumped by hand; Tailscale by Dependabot.
- `.env` holds the key and the hash in clear on the host: the folder's permissions are the only
  protection.
- The rate limit counts every request: a first visit with a cold cache fetches about 125 JS
  chunks, which set the limit at 300.

Follow-ups: [docs/backlog.md](../backlog.md), "Deployment and CI": password hash in argon2id
(bcrypt cost 10 today), one `basic_auth` account per reader, the read-only tailscaled and the
memory caps verified on the NAS kernel.

## Verification

- `tests/test_docker.py::test_funnel_stack_publishes_nothing_on_the_host`,
  `::test_funnel_stack_pulls_the_published_image_and_takes_its_secrets_from_the_environment`,
  `::test_sidecars_hardened`, `::test_funnel_stack_bounds_what_it_takes_from_the_nas`,
  `::test_tailscale_key_is_optional_once_the_node_exists`,
  `::test_remote_debug_page_follows_the_env_file_and_is_off_by_default`,
  `::test_remote_load_workers_follow_the_env_file_and_default_to_one`,
  `::test_remote_app_settings_reach_streamlit`, `::test_nothing_in_src_reaches_the_network`.
- `tests/test_docker.py::test_caddy_upstream_is_not_shadowed_by_the_tailscale_hostname`,
  `::test_caddy_error_log_redacts_the_secret_prefix`, `::test_caddy_security_headers_and_their_ci_check`,
  `::test_caddy_logs_keep_no_token_and_no_project_code`,
  `::test_caddy_closes_each_connection_except_a_websocket_handshake`,
  `::test_ci_fails_when_the_secret_prefix_reaches_the_log`, `::test_caddy_marks_the_app_cookie_secure`,
  `::test_caddy_answers_404_on_the_app_routes_the_page_never_asks_for`,
  `::test_caddy_policy_forbids_plug_ins_and_base_and_hsts_covers_sub_domains`,
  `::test_caddy_image_carries_the_rate_limit_module_at_pinned_versions`,
  `::test_caddy_build_forces_the_fixed_x_net_and_proves_it`, `::test_caddy_base_images_pinned_by_digest`.
- `tests/test_app.py::test_locked_folder_gives_the_visitor_no_path_field_and_no_upload`,
  `::test_debug_page_and_runtime_block_are_not_shown_on_a_locked_deployment`.
- `.github/workflows/tests.yml`, job `deploy`: the compose file validated with the NAS's
  variables; tailscaled started on a read-only root; Caddy checked outside and inside the prefix
  (404, 401, headers, `Connection`, the prefix absent from the log); the rate limit (429); Trivy
  on the Caddy and Tailscale images.

## References

- `deploy/compose.yaml` (services `tailscale`, `caddy`, `lexicon-init`, `xerscope`; networks
  `egress`, `internal`), `deploy/Caddyfile`, `deploy/caddy/Dockerfile`,
  `deploy/tailscale-serve.json`, `deploy/.env.example`.
- `src/xerscope/app/session.py`: `debug_page`, `data_locked`, `_data_locked`.
- [docs/deploy.md](../deploy.md) §3 (secrets, bcrypt cost, prefix, tailnet policy), §7 (update,
  pinning, memory), §9 (security checklist); [README.md](../../README.md), "Deployment";
  [SECURITY.md](../../SECURITY.md), scope.
- Related: ADR-0021 (lexicon folder and `lexicon-init`), ADR-0024 (the app's image and local
  defaults), ADR-0026 (pinned supply chain), ADR-0027 (published images), ADR-0028 (scanning).
