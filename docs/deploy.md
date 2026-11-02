# Deployment guide: Synology DS918+, DSM 7.4, Container Manager (Projects)

Target: one person outside the home network, on a laptop that can install nothing, reaches
`https://xerscope.<tailnet>.ts.net/<random>/` behind a password. The NAS publishes no port;
everything goes out through Tailscale Funnel.

```
GitHub Actions ──push──▶ ghcr.io/xerscope/xerscope:latest (public package, no login)
                                   │ pull (Container Manager > Project)
      ┌─────────────── project "xerscope" on the DS918+ ───────────────┐
      │ tailscale (userspace, Funnel) ◀─── https ─── visitor's browser │
      │   └─ caddy :8080 on 127.0.0.1 (basic_auth) ──▶ xerscope :8501   │
      │                                     └─ /volume1/<shared-folder>:ro │
      └──────────────────────────────────────────────────────────────────┘
```

Three containers from three images; the app image is the only one built here. Container
Manager with Projects (DSM 7.2+) is required: the stack is a compose file.

## 1. What DSM 7.4 changes

| DSM ≤ 7.1, package *Docker* | DSM 7.2+, package *Container Manager* |
|---|---|
| no Compose UI → one hand-made all-in-one container (tailscaled + Caddy + Streamlit under a supervisor) | **Project** = a docker-compose stack from a folder → `deploy/compose.yaml`, three official images |
| registry login form only; `ghcr.io` rejected ("returned bad result") | a **public** ghcr package needs no login: Compose pulls `ghcr.io/xerscope/xerscope:latest` directly |
| env vars typed in the container form (key, prefix, hash) | a **`.env`** file next to `compose.yaml` (key, login, hash, prefix, exports folder), read by Compose for its `${...}` interpolation; no other file is edited |
| node state in `tailscale-state/node/` | official image reads the root of `tailscale-state/` → move the files once (§6) |

Caddy and Tailscale are now updated independently of the app (Dependabot bumps the pins
in `deploy/`), and the app container runs read-only, non-root, on an internal network with
no route to the internet.

## 2. Pre-flight (from your PC, once)

1. **Image published.** GitHub → Actions → `image` → last run on `main` green. Package
   list: `github.com/orgs/Xerscope/packages`.
2. **Package public.** Package `xerscope` → Package settings → Danger zone → visibility
   **Public**. A public image pulls anonymously; the repository is public, the image adds
   nothing to what is already readable. (A private package would need a classic PAT
   `read:packages`, and Container Manager cannot log in to `ghcr.io` — use the Docker Hub
   mirror instead, §8.)
3. **Pull it somewhere that is not the CI.**

   ```bash
   docker pull ghcr.io/xerscope/xerscope:latest
   docker run --rm ghcr.io/xerscope/xerscope:latest --help          # distroless: no shell, only the CLI
   docker inspect ghcr.io/xerscope/xerscope:latest \
     --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'   # = commit sha
   ```

   The DS918+ is x86-64: `linux/amd64` only, which is what the workflow builds.

## 3. Secrets (from your PC)

Password hash — Caddy gets a bcrypt hash, never the password:

```bash
docker run --rm caddy:2.11.6 caddy hash-password --plaintext 'your passphrase'   # → $2a$14$...
```

Use a long passphrase (24+ characters, generated; a password manager or
`openssl rand -base64 24`). Note it: a bcrypt hash cannot be reversed.

Secret URL prefix — `openssl rand -hex 12` → `<random>` (24 hex chars, 96 bits). Internet
scanners find every new `*.ts.net` name within seconds (the certificate is in the public CT
logs); Caddy answers 404 to every path outside `/<random>/` before the password prompt, and
its log never holds the prefix (request line, Referer and redirect are redacted).

Tailscale admin console:

- Access controls:
  `"tagOwners": { "tag:xerscope": ["autogroup:admin"] }` and
  `"nodeAttrs": [{ "target": ["tag:xerscope"], "attr": ["funnel"] }]`.
  The default policy rule (source `*`, in `acls` or `grants`) lets tagged nodes reach every device of the tailnet: a
  compromised `xerscope` container would reach your PC. Narrow its source to user devices,
  which excludes tagged nodes:
  `"grants": [{ "src": ["autogroup:member"], "dst": ["*"], "ip": ["*"] }]`.
  Funnel does not depend on grants. Machines → `xerscope` → Access then lists no
  destination.
- Settings → Keys → Generate auth key: **Reusable: no, Ephemeral: no, Pre-authorized:
  yes, Tags: `tag:xerscope`**. Non-ephemeral so the node (and its URL) survives restarts.
- DNS → MagicDNS and HTTPS certificates **on**.

A key or a prefix pasted anywhere else than the NAS (chat, ticket, screenshot) is burned:
revoke the key, change the prefix.

## 4. Files on the NAS

File Station → `docker/xerscope/` (`/volume1/docker/xerscope/`) = a copy of the `deploy/`
folder of the repository:

| On the NAS | Edit |
|---|---|
| `compose.yaml` | nothing |
| `Caddyfile` | nothing (login and hash come from the environment) |
| `tailscale-serve.json` | nothing |

Add a `.env` from `.env.example` with the five values (§6). Container Manager's Environment
fields at project creation do not feed the compose file's `${...}` interpolation: left empty,
the build stops with `error while interpolating services.tailscale...`.
`docker` is a shared folder: restrict it to your DSM account (Control Panel → Shared
Folder → Permissions). DSM stores the project's variables in clear too, readable by any
DSM administrator — same confidentiality as the folder, not a vault.

## 5. The exports folder

A shared folder (for example `planning`), weekly `.xer` dropped by Synology Drive or
SMB; sub-folders are read too. Mounted read-only: the app cannot alter or delete anything.
The container runs as uid 65532 (`nonroot`), which is nobody on the NAS: the folder needs
read for *Everyone* (File Station → Properties → Permission → Advanced; or Control Panel →
Shared Folder → Permissions → "Everyone" read). Without it the page shows no file and the
log says `Permission denied`.

The case of the folder name matters inside the container: `/volume1/Planning` and
`/volume1/planning` are two different paths. Copy it from File Station.

## 6. Create the project

Coming from the earlier all-in-one container: stop and delete it first, and delete its
machine in the Tailscale admin console. This project starts a new node in its own Docker
volume, with a new key; the hostname, and so the URL, stay the same.

First the **`.env`** in `docker/xerscope/`, next to `compose.yaml`: the five lines of
`deploy/.env.example`, made on a PC and uploaded (Notepad → Save as → type "All files",
name `".env"` with the quotes). A missing value stops the build with its name.

```
TS_AUTHKEY=tskey-auth-...              # first start only (TS_AUTH_ONCE): once the node is up, delete this line and the key in the admin console
XERSCOPE_USER=<login>
XERSCOPE_PASSWORD_HASH='$2a$14$...'     # single quotes: unquoted, Compose reads the $ as variables
XERSCOPE_PATH=<random>                 # no slashes
XERSCOPE_EXPORTS=/volume1/<shared-folder>   # exact case
```

Then Container Manager → **Project** → **Create**:

- Project name: `xerscope`
- Path: `/docker/xerscope`
- Source: *Use existing docker-compose.yml* (it finds `compose.yaml`) → Next → Next → Done.
  Leave the Environment fields empty: they do not reach the compose file's `${...}`.

Container Manager pulls the three images (the ghcr pull needs no registry entry) and starts
the stack. Expected after ~40 s, in Container → each container → Log:

1. `xerscope`: `You can now view your Streamlit app`. The `/_stcore/health` check turns
   the container *Healthy*.
2. `tailscale`: `Serve config loaded`, then `funnel` lines. No `funnel: not permitted` (ACL
   step missed) and no `permission denied` on `/var/lib/tailscale` (§4 folder permission).
   Admin console → Machines → `xerscope`, tag `xerscope`, Funnel badge.
3. `caddy`: `serving initial configuration`. Nothing listening on the NAS: Control Panel
   → Terminal/Network show no 8080/8501; the project's networks are Docker bridges only.
4. From a phone on mobile data: `https://xerscope.<tailnet>.ts.net/<random>/` — trailing
   slash included (the page's relative asset URLs need it) → browser password prompt →
   the app. The same name without the prefix must answer 404.

First certificate: Tailscale asks Let's Encrypt on the first HTTPS request, up to a
minute of `connection reset` before the page comes up.

## 7. Update, rollback, change a secret

Nothing auto-updates: an update is a decision. Project → `xerscope` → **Action**:

| Want | Do |
|---|---|
| new app build | Container → Image → the app image (`ghcr.io/xerscope/xerscope` or the Docker Hub copy) → Update, then Project → Action → **Build** (recreates from the new image; the node state is kept, the URL does not change) |
| pin a version | push a git tag `v0.1.0` → the workflow publishes `:0.1.0`; put it in `.env` (`XERSCOPE_IMAGE=<image>:0.1.0`), Build. Rollback = previous tag, Build. `sha-<short>` tags exist for every `main` build |
| new password or login | edit `.env` → Project → Action → Build (Caddy reads them at start) |
| new prefix | `.env` → `XERSCOPE_PATH` → Build; the old URL goes 404 at once |
| new Tailscale key | only for a new node: Project → Stop, Container Manager → Volume → delete `xerscope_tailscale-state`, new key in `.env`, Build; delete the old machine in the admin console |

Caddy/Tailscale bumps: Dependabot opens a PR on `deploy/`; after merge, change the two
pins in `compose.yaml` on the NAS, Build.

## 8. Image on Docker Hub

A **public** Docker Hub repository pulls without a registry login: steps 1 and 2 below, skip
step 3. Anyone holding the Read & Write token can push a `latest` the NAS would pull at
the next Update, so pin `XERSCOPE_IMAGE` to a `sha-<short>` tag (§7).

A private ghcr package needs a GitHub token on the NAS, which Container Manager does not
handle. Keep the image private on Docker Hub instead, where Container Manager logs in
natively:

1. hub.docker.com → Create repository `xerscope`, **Private** (the free plan includes one).
   Account settings → Personal access tokens: one **Read & Write** for GitHub, one
   **Read-only** for the NAS.
2. GitHub → repository → Settings → Secrets and variables → Actions: secrets
   `DOCKERHUB_USERNAME` (`<docker-hub-login>`) and `DOCKERHUB_TOKEN` (the Read & Write one);
   variable `DOCKERHUB_IMAGE_OWNER` = `<docker-hub-login>`. Actions → `image` → Run workflow;
   the run pushes to both registries.
3. NAS: Container Manager → Registry → Docker Hub → Settings → Edit → login + the read-only
   token → **Use**.
4. `.env`: `XERSCOPE_IMAGE=<docker-hub-login>/xerscope:latest` (nothing to edit in
   `compose.yaml`). Build.

If Build still answers `pull access denied`, the project's pull does not use the registry
login: pull once from Container Manager → Registry (search the image) or Image → Add, then
Build; Compose starts from the local image without pulling again.

The ghcr package can stay private: only the NAS reads the Docker Hub copy.

## 9. Security checklist

- [ ] Package public = source already public; nothing else in the image (no data, no secret: `tests/test_docker.py` pins it).
- [ ] Tailscale key: tagged, single-use, non-ephemeral; once the node is up, delete it from the admin console and its line from `.env` (`TS_AUTH_ONCE`: it is never replayed, the node lives in the volume).
- [ ] Tailnet policy: tagged nodes reach nothing (`grants` source `autogroup:member`, §3).
- [ ] App image pinned to a `sha-<short>` or version tag, not `latest` (§7).
- [ ] `docker` shared folder readable by your account only (`.env`: key + hash in clear).
- [ ] No `ports:` anywhere. `egress` network for tailscaled only; `internal` has no gateway: the app reaches nothing and the LAN does not reach the app.
- [ ] Caddy: `admin off`, `default_bind 127.0.0.1`; the log keeps the visitor's IP (`trusted_proxies`) and redacts the request line, Referer and redirect (they hold the prefix), in the access log and in the error log (global `log` block).
- [ ] One shared password: change it when the viewer changes; the day the viewer can install Tailscale, drop Funnel for Serve + Tailscale login.
- [ ] Review the Caddy log now and then (Container → caddy → Log): one IP, one login, the paths you expect.

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Build: `unauthorized` / `pull access denied` on ghcr | the package is private | make it public (§2 step 2), or use the Docker Hub copy (§8) |
| `manifest unknown` | tag typo; owner must be lowercase `xerscope` | check the `image` run for that tag |
| tailscale log `permission denied` `/var/lib/tailscale`, then `state "NoState", waiting` in a loop | the state is a host folder (an older compose): root without capabilities cannot write there | use the named volume of `deploy/compose.yaml` |
| `funnel: not permitted` | ACL `nodeAttrs` missing or key not tagged | fix ACL, new tagged key, delete the `xerscope_tailscale-state` volume, Build |
| `Serve config loaded` absent | `tailscale-serve.json` not mounted or invalid JSON | File Station → check the name; validate the JSON |
| 404 on the full URL | URL ≠ `XERSCOPE_PATH`, or a slash inside the variable | value without slashes, URL `/<random>/` (`/<random>` alone redirects there) |
| 502, Caddy log `dial tcp <ip>:8501: connection refused` with the app *Healthy* | Caddy resolves `xerscope` to the tailscale container (its hostname, in the `/etc/hosts` of the namespace Caddy shares) | upstream `app:8501`, the app's network alias, as in `deploy/` (check: caddy → Terminal → `getent hosts app`) |
| 502 | app not healthy yet, or `/data` unreadable | wait 40 s; xerscope log; §5 |
| 401 loops | hash made for another login, or `$` mangled | regenerate with `caddy hash-password`, in `.env` between single quotes |
| app lists no file | `XERSCOPE_EXPORTS` path/case, or permission | §5 |
| page after upload disappears on restart | upload lands in the container's tmpfs | drop files in the shared folder instead |
| old node still listed in the admin console | state folder emptied | delete the stale machine there |
