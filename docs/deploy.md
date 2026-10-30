# Deployment guide: GHCR → Synology DS918+ (Container Manager, no terminal)

Target: one person, outside the home network, on a corporate laptop that cannot install
anything, reaches `https://xerscope.<tailnet>.ts.net` behind a password. The NAS keeps
its configuration; nothing is published on its ports.

```
GitHub Actions ──push──▶ ghcr.io/xerscope/xerscope (+ a Docker Hub mirror)
                                   │ pull
                              DS918+ Container Manager
      ┌─────────────────── project "xerscope" ───────────────────┐
      │ tailscale (userspace) ◀── Funnel ◀── visitor's browser   │
      │   └─ caddy :8080 (basic_auth) ──▶ xerscope :8501         │
      │                                 └─ /volume1/plannings:ro │
      └────────────────────────────────────────────────────────────┘
```

## 1. GHCR in five facts (vs Docker Hub)

| | Docker Hub | GHCR |
|---|---|---|
| Image name | `mish1ma/xerscope` | `ghcr.io/xerscope/xerscope` (owner **lowercase**, even though the org is `Xerscope`) |
| Who pushes | you, `docker push` | the `image` workflow, with the job's own `GITHUB_TOKEN` (`packages: write`). You never push by hand. |
| Visibility | per repo | per **package**; defaults to the repo's visibility (public: anyone pulls, no login) |
| Pull auth | Docker Hub login (public images: none) | public package: none. Private package or fork: GitHub login + a **personal access token (classic)** with scope `read:packages`; the account password does not work on `ghcr.io`. |
| Where to look | hub.docker.com | `github.com/orgs/Xerscope/packages` (org packages) and the "Packages" box on the repo page |

Rationale: no separate account, no rate limit on pulls, and the image is linked to the
commit that built it (`sha-<short>` tag + OCI labels).

## 2. Pre-flight checks (do once, from your PC)

1. **The workflow published something.** Actions → `image` → last run on `main` is green,
   two jobs (`xerscope`, `xerscope-remote`). Then the org package list shows both.
2. **The package is linked to the repo.** Package page → "Package settings": source
   repository = `Xerscope/xerscope`; visibility follows the repository (public).
3. **Private package or fork only — make a pull token.** GitHub → Settings → Developer
   settings → Personal access tokens → *Tokens (classic)* → scope **`read:packages` only**,
   expiry 90 days. (Fine-grained tokens: not reliably accepted by `ghcr.io` for pulls.)
   Then `echo "$GHCR_TOKEN" | docker login ghcr.io -u <github-login> --password-stdin`.
4. **Pull from a machine that is not the CI.**

   ```bash
   docker pull ghcr.io/xerscope/xerscope:latest
   docker run --rm ghcr.io/xerscope/xerscope:latest --help          # distroless: no shell, only the CLI
   docker run --rm -v "$PWD/exports:/data:ro" ghcr.io/xerscope/xerscope:latest check /data --standard P6
   ```

   `denied` on a private package: wrong scope, expired token, or the org blocks personal
   tokens (Org settings → Third-party access → Personal access tokens).
5. **Know which build you pulled.**

   ```bash
   docker inspect ghcr.io/xerscope/xerscope:latest \
     --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'   # = commit sha
   docker buildx imagetools inspect ghcr.io/xerscope/xerscope:latest           # digest, platform (amd64 only)
   ```

   The DS918+ is x86-64: `linux/amd64` is enough. Don't add arm64 unless you target another NAS.

## 3. Prepare the secrets (from your PC)

```bash
docker run --rm caddy:2.11.2 caddy hash-password --plaintext 'a long passphrase'   # → $2a$14$...
```

Tailscale admin console:

- ACL: tag owner `"tag:xerscope": ["autogroup:admin"]` and
  `"nodeAttrs": [{ "target": ["tag:xerscope"], "attr": ["funnel"] }]`.
- Settings → Keys → **Reusable: no, Ephemeral: no, Pre-authorized: yes, Tag: `tag:xerscope`**.
  Non-ephemeral so the node survives container restarts (its state lives in `./tailscale-state`).
- DNS → MagicDNS + HTTPS certificates must be on (Funnel needs the `*.ts.net` cert).

## 4. Files on the NAS

File Station → `docker/xerscope/` (that is `/volume1/docker/xerscope/`):

| File | From | Edit |
|---|---|---|
| `compose.yaml` | `deploy/compose.nas.yaml` | `TS_AUTHKEY`; keep `/volume1/plannings` or point it at the shared folder of the exports. Image: `mish1ma/xerscope:latest` (Docker Hub, section 5) |
| `Caddyfile` | `deploy/Caddyfile.nas` | user + bcrypt hash |
| `tailscale-serve.json` | `deploy/tailscale-serve.json` | nothing |
| `tailscale-state/` | — | create empty folder |

Exports: a shared folder (`plannings`), weekly `.xer` dropped through Synology Drive or
SMB. Mounted read-only: the app cannot alter or delete them.

## 5. Registry login in Container Manager

**Tested 2026-10 on DSM 7.2, with the package still private: Container Manager rejected
ghcr.io** ("returned bad result" on the Registry form and on Image → Add from URL, with a
token that `docker login ghcr.io` accepts). A public package needs no login, so try
**Image → Add → Add from URL → `https://ghcr.io/xerscope/xerscope`** first. If the UI still
refuses, the app image is mirrored on **Docker Hub** (`mish1ma/xerscope`, the project's
account), which Container Manager handles natively; `compose.nas.yaml` pulls that one.

To publish your own mirror from a fork:

1. hub.docker.com → Create repository `xerscope`.
2. hub.docker.com → Account settings → Personal access tokens → New: `github-actions`,
   permissions **Read & Write** → copy it.
3. GitHub → the fork → Settings → Secrets and variables → Actions: secrets
   `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`, variable `DOCKERHUB_IMAGE_OWNER` = your
   Docker Hub account (and `DOCKERHUB_REMOTE` = `true` for the remote image too).
4. Actions → `image` → Run workflow; `docker pull <you>/xerscope:latest` confirms it.
5. For a private mirror, a second Docker Hub token for the NAS, **Read-only**.

Container Manager → **Registry** → select **Docker Hub** → Settings → Edit → username and
the read-only token (public mirror: nothing to enter) → **Use**. Then Project → Create pulls
the image by itself.

### ghcr.io with a private package

Container Manager → **Registry** → Settings → **Add**:

| Field | Value |
|---|---|
| Registry name | `ghcr` |
| Registry URL | `https://ghcr.io` |
| Username | your GitHub login |
| Password | the `read:packages` token |

Select it with **Use**. Then Registry → search `xerscope/xerscope` won't work (GHCR has no
search API): go to **Image → Add → From URL** and enter
`ghcr.io/xerscope/xerscope:latest` — or just create the project, Compose pulls it.

## 6. Create the project

Container Manager → **Project** → Create → "Create docker-compose.yml from existing
path" → `/docker/xerscope` → Next → Build. Expected: three containers up, `xerscope`
shows *healthy* after ~30 s (`/_stcore/health`).

Checks, in order:

1. `xerscope` log: `You can now view your Streamlit app` — if `Permission denied` on
   `/data`, the shared folder's permissions exclude "Everyone/others" read; the container
   runs as uid 65532 (`nonroot`), so give the folder read for *Everyone* or `chown` via
   File Station → Properties → Permission.
2. `tailscale` log: `Serve config loaded`, no `funnel: not permitted` (ACL step missed).
   Admin console → Machines → `xerscope` listed, tag shown, "Funnel" badge on.
3. From your phone on mobile data: `https://xerscope.<tailnet>.ts.net` → 401 prompt →
   credentials → the app. On the NAS, Network → nothing new on ports 80/443/8501
   (`docker` bridge only).

## 7. Update to a new build

Nothing auto-updates (no Watchtower, by design: an update must be a decision).

1. Image → `ghcr.io/xerscope/xerscope` → **Update** (Action → Update), or re-add from URL.
2. Project → xerscope → **Action → Build** (recreates the containers from the new image;
   `tailscale-state` keeps the node identity, the URL does not change).

Prefer a tag you chose over `latest` once this is in use: push a git tag `v0.1.0`, the
workflow publishes `ghcr.io/xerscope/xerscope:0.1.0`; put that in `compose.yaml`. Rollback =
change the tag, Build again. `sha-<short>` tags exist for every `main` build too.

## 8. Security checklist

Internet scanners find every new `*.ts.net` name within seconds (the certificate is in the
public CT logs) and probe `/`, `/.env`, `/wp-admin`... Basic auth answers 401; to keep them
out of the container entirely, set `XERSCOPE_PATH=/<random>` on the remote image: Funnel
then publishes only that prefix and Tailscale answers 404 to the rest. The URL to hand out
becomes `https://xerscope.<tailnet>.ts.net/<random>/` — trailing slash included, the page's
relative asset URLs need it. Tailscale strips the prefix before proxying, so Caddy and the app
keep seeing `/`.

- [ ] Private package or fork: pull token = `read:packages` only, rotated at expiry.
- [ ] Tailscale key: tagged, non-ephemeral, single-use; delete it from the admin console once the node is up.
- [ ] `compose.yaml` on the NAS holds the key and the bcrypt hash: the `docker` share must not be readable by other NAS users.
- [ ] No `ports:` anywhere. Two networks: `egress` (plain bridge, tailscale only, outbound) and `internal` (no gateway: xerscope cannot reach the internet, the NAS LAN cannot reach xerscope).
- [ ] Basic auth is one shared password → change it when the viewer changes; move to Tailscale Serve + a Tailscale login (no Funnel) the day the viewer can install Tailscale, or to Cloudflare Access.
- [ ] Caddy logs IP + path to stdout (Container Manager → container → Log): review them from time to time.

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `pull access denied` / `unauthorized` | private package: not logged in on ghcr, wrong scope, expired token | Registry → re-add with a fresh classic token `read:packages` |
| `manifest unknown` | tag typo, or the workflow didn't run for that tag | check Actions; owner is lowercase `xerscope` |
| `no matching manifest for linux/arm64` | not this NAS (amd64) — another one | add `platforms: linux/amd64,linux/arm64` + `docker/setup-qemu-action` to the workflow |
| container `xerscope` restarts, log empty | read-only FS without `tmpfs` | keep `/tmp` and `/home/nonroot` in `tmpfs:` |
| `funnel: not permitted` | ACL `nodeAttrs` missing or key not tagged | fix ACL, re-issue a tagged key, delete `tailscale-state/`, Build |
| 404 on `https://xerscope.<tailnet>.ts.net` | serve.json not mounted, or Caddy down | `tailscale` log → `Serve config loaded`; `caddy` log |
| 502 | xerscope not healthy yet, or `/data` unreadable | wait 40 s; xerscope log |
| Streamlit shows nothing after upload | upload goes to the container's tmpfs, lost on restart | drop files in the shared folder instead |

## 10. Alternative: single container (`xerscope-remote`)

If Projects/compose is not available on the NAS, `ghcr.io/xerscope/xerscope-remote:latest`
bundles the three processes (see `Dockerfile.remote`, `deploy/remote/supervisor.py`).
Container Manager → Image → Add from URL → Run → set the environment variables
(`TS_AUTHKEY`, `XERSCOPE_USER`, `XERSCOPE_PASSWORD_HASH`), the two volumes, no port.
Same ACL, same checks. The compose form is preferred: three official images, each
updatable separately, and Caddy/Tailscale not rebuilt when the app changes.
