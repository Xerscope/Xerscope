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
| no Compose UI → one hand-made all-in-one container (tailscaled + Caddy + Streamlit under a supervisor) | **Project** = a docker-compose stack from a folder → `deploy/compose.nas.yaml`, three official images |
| registry login form only; `ghcr.io` rejected ("returned bad result") | a **public** ghcr package needs no login: Compose pulls `ghcr.io/xerscope/xerscope:latest` directly |
| env vars typed in the container form (key, prefix, hash) | secrets live in files next to the compose: `compose.yaml` (key), `Caddyfile` (hash), `tailscale-serve.json` (prefix) |
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

Password hash — the Caddyfile holds a bcrypt hash, never the password:

```bash
docker run --rm caddy:2.11.6 caddy hash-password --plaintext 'your passphrase'   # → $2a$14$...
```

Use a long passphrase (24+ characters, generated; a password manager or
`openssl rand -base64 24`). Note it: a bcrypt hash cannot be reversed.

Secret URL prefix — `openssl rand -hex 12` → `<random>` (24 hex chars). Internet scanners
find every new `*.ts.net` name within seconds (the certificate is in the public CT logs);
with a prefix, Tailscale answers 404 to everything else and the request never reaches Caddy.

Tailscale admin console:

- Access controls:
  `"tagOwners": { "tag:xerscope": ["autogroup:admin"] }` and
  `"nodeAttrs": [{ "target": ["tag:xerscope"], "attr": ["funnel"] }]`.
- Settings → Keys → Generate auth key: **Reusable: no, Ephemeral: no, Pre-authorized:
  yes, Tags: `tag:xerscope`**. Non-ephemeral so the node (and its URL) survives restarts.
- DNS → MagicDNS and HTTPS certificates **on**.

A key or a prefix pasted anywhere else than the NAS files (chat, ticket, screenshot) is
burned: revoke the key, change the prefix.

## 4. Files on the NAS

File Station → `docker/xerscope/` (`/volume1/docker/xerscope/`), four entries:

| On the NAS | From `deploy/` | Edit |
|---|---|---|
| `compose.yaml` | `compose.nas.yaml` | `TS_AUTHKEY`; the `/volume1/<shared-folder>` line (§5) |
| `Caddyfile` | `Caddyfile.nas` | `<login>` and the `$2a$14$...` hash |
| `tailscale-serve.json` | `tailscale-serve.json` | handler key `"/"` → `"/<random>"` (keep the leading slash, no trailing one) |
| `tailscale-state/` | — | empty folder; Properties → Permission → *Everyone* read/write (tailscaled runs non-root) |

`docker` is a shared folder: restrict it to your DSM account (Control Panel → Shared
Folder → Permissions), the key and the hash are in clear in there.

The three files are typed as they are: Compose does not interpolate `$` in the Caddyfile,
and the hash is not in `compose.yaml`.

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

Coming from the earlier all-in-one container: stop and delete it first, then in
`tailscale-state/` move the content of `node/` one level up (`tailscaled.state`, …) and
remove `node/`. Same node, same URL. Never run both with the same state folder.

Container Manager → **Project** → **Create**:

- Project name: `xerscope`
- Path: `/docker/xerscope`
- Source: *Use existing docker-compose.yml* (it finds `compose.yaml`) → Next → Next → Done.

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
| new app build | Container → Image → `ghcr.io/xerscope/xerscope` → Update, then Project → Action → **Build** (recreates from the new image; the node state is kept, the URL does not change) |
| pin a version | push a git tag `v0.1.0` → the workflow publishes `:0.1.0`; put that tag in `compose.yaml`, Build. Rollback = previous tag, Build. `sha-<short>` tags exist for every `main` build |
| new password | new hash in `Caddyfile` → Action → **Stop**, **Build** (Caddy reads the file at start) |
| new prefix | edit `tailscale-serve.json` → Stop, Build; the old URL goes 404 at once |
| new Tailscale key | only after deleting `tailscale-state/` content (new node, same hostname: the admin console shows the old one offline, delete it) |

Caddy/Tailscale bumps: Dependabot opens a PR on `deploy/`; after merge, change the two
pins in `compose.yaml` on the NAS, Build.

## 8. If Container Manager will not pull from ghcr.io

Project → Build fails with `pull access denied` or `bad result` on a **public** package
means the DSM proxy or an old Container Manager still mishandles ghcr. The workflow also
publishes the app image to Docker Hub, which Container Manager handles natively:

1. GitHub → repository → Settings → Secrets and variables → Actions:
   secrets `DOCKERHUB_USERNAME` (`<docker-hub-login>`), `DOCKERHUB_TOKEN` (hub.docker.com →
   Account settings → Personal access tokens, **Read & Write**); variable
   `DOCKERHUB_IMAGE_OWNER` = `<docker-hub-login>`. Actions → `image` → Run workflow.
2. In `compose.yaml` on the NAS: `image: <docker-hub-login>/xerscope:latest`. A public Docker
   Hub repository pulls anonymously too; a private one takes Container Manager → Registry →
   Docker Hub → Settings → Edit → login + a **read-only** token → Use.
3. Build.

Same image, same digest-equivalent content: the workflow pushes one build to both names.

## 9. Security checklist

- [ ] Package public = source already public; nothing else in the image (no data, no secret: `tests/test_docker.py` pins it).
- [ ] Tailscale key: tagged, single-use, non-ephemeral; delete it from the admin console once the node is up (`TS_AUTH_ONCE` means it is never replayed).
- [ ] `docker` shared folder readable by your account only (key + hash in clear).
- [ ] No `ports:` anywhere. `egress` network for tailscaled only; `internal` has no gateway: the app reaches nothing and the LAN does not reach the app.
- [ ] Caddy: `admin off`, `default_bind 127.0.0.1`; the log keeps the visitor's IP (`trusted_proxies`) and drops the Referer (it would hold the prefix).
- [ ] One shared password: change it when the viewer changes; the day the viewer can install Tailscale, drop Funnel for Serve + Tailscale login.
- [ ] Review the Caddy log now and then (Container → caddy → Log): one IP, one login, the paths you expect.

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Build: `pull access denied` on ghcr | package private, or Container Manager and ghcr | §2 step 2; else §8 |
| `manifest unknown` | tag typo; owner must be lowercase `xerscope` | check the `image` run for that tag |
| tailscale log `permission denied` `/var/lib/tailscale` | `tailscale-state/` not writable by the container's user | §4 permission on the folder |
| `funnel: not permitted` | ACL `nodeAttrs` missing or key not tagged | fix ACL, new tagged key, empty `tailscale-state/`, Build |
| `Serve config loaded` absent | `tailscale-serve.json` not mounted or invalid JSON | File Station → check the name; validate the JSON |
| 404 on the full URL | handler key ≠ URL path, or missing trailing slash | key `"/<random>"`, URL `/<random>/` |
| 502 | app not healthy yet, or `/data` unreadable | wait 40 s; xerscope log; §5 |
| 401 loops | hash made for another login, or `$` mangled | regenerate with `caddy hash-password`, paste as is in the Caddyfile |
| app lists no file | wrong folder path/case, or permission | §5 |
| page after upload disappears on restart | upload lands in the container's tmpfs | drop files in the shared folder instead |
| old node still listed in the admin console | state folder emptied | delete the stale machine there |
