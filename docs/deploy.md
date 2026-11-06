# Deployment guide: Synology DS918+, DSM 7.4, Container Manager (Projects)

Target: one person outside the home network, on a laptop that can install nothing, reaches
`https://xerscope.<tailnet>.ts.net/<random>/` behind a password. The NAS publishes no port;
everything goes out through Tailscale Funnel.

```
GitHub Actions ──push──▶ ghcr.io/xerscope/xerscope:latest, xerscope-caddy:latest (public, no login)
                                   │ pull (Container Manager > Project)
      ┌─────────────── project "xerscope" on the DS918+ ───────────────┐
      │ tailscale (userspace, Funnel) ◀─── https ─── visitor's browser │
      │   └─ caddy 127.0.0.1:8080 (rate_limit, basic_auth) ─▶ xerscope │
      │                                     └─ /volume1/<shared-folder>:ro │
      └──────────────────────────────────────────────────────────────────┘
```

Three containers from three images: Tailscale's official one, and two built here by
`.github/workflows/image.yml`, the app and Caddy with the `rate_limit` module
(`deploy/caddy/Dockerfile`; the stock caddy image has no such module and the NAS cannot
build). Container Manager with Projects (DSM 7.2+) is required: the stack is a compose file.

## 1. What DSM 7.4 changes

| DSM ≤ 7.1, package *Docker* | DSM 7.2+, package *Container Manager* |
|---|---|
| no Compose UI → one hand-made all-in-one container (tailscaled + Caddy + Streamlit under a supervisor) | **Project** = a docker-compose stack from a folder → `deploy/compose.yaml`, three official images |
| registry login form only; `ghcr.io` rejected ("returned bad result") | a **public** ghcr package needs no login: Compose pulls `ghcr.io/xerscope/xerscope:latest` directly |
| env vars typed in the container form (key, prefix, hash) | a **`.env`** file next to `compose.yaml` (key, login, hash, prefix, exports folder), read by Compose for its `${...}` interpolation; no other file is edited |
| node state in `tailscale-state/node/` | official image reads the root of `tailscale-state/` → move the files once (§6) |

Caddy and Tailscale are now updated independently of the app (Dependabot bumps the
Tailscale pin in `deploy/compose.yaml` and the caddy tags in `deploy/caddy/Dockerfile`), and the app container runs read-only, non-root, on an internal network with
no route to the internet.

## 2. Pre-flight (from your PC, once)

1. **Image published.** GitHub → Actions → `image` → last run on `main` green. Package
   list: `github.com/orgs/Xerscope/packages`.
2. **Packages public.** Packages `xerscope` and `xerscope-caddy` → Package settings → Danger
   zone → visibility **Public**. A public image pulls anonymously; the repository is public, the image adds
   nothing to what is already readable. (A private package would need a classic PAT
   `read:packages`, and Container Manager cannot log in to `ghcr.io` — use the Docker Hub
   mirror instead, §8.)
3. **Pull it somewhere that is not the CI.**

   ```bash
   docker pull ghcr.io/xerscope/xerscope:latest
   docker run --rm ghcr.io/xerscope/xerscope:latest --help          # distroless: no shell, only the CLI
   docker inspect ghcr.io/xerscope/xerscope:latest \
     --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'   # = commit sha
   docker run --rm ghcr.io/xerscope/xerscope-caddy:latest caddy list-modules | grep rate_limit
   ```

   The DS918+ is x86-64: `linux/amd64` only, which is what the workflow builds.

## 3. Secrets (from your PC)

Password hash — Caddy gets a bcrypt hash, never the password:

```bash
docker run --rm caddy:2.11.8 caddy hash-password --algorithm bcrypt --bcrypt-cost 10 --plaintext 'your passphrase'   # → $2a$10$...
```

Use a long passphrase (24+ characters, generated; a password manager or
`openssl rand -base64 24`). Note it: a bcrypt hash cannot be reversed.

Why cost 10 and not Caddy's default 14: every wrong password costs one bcrypt run on the
NAS's CPU, and the stack has no CPU quota (§7), so at cost 14 (about 1.25 s per attempt on
a 2-core x86 test machine) a few clients retrying in a loop hold every core of the NAS. Cost
10 is 16 times cheaper (about 0.08 s). The cost only slows an offline attack on a stolen
hash, and a generated 24-character passphrase (about 140 bits) is out of reach at either cost.

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
| `caddy/` | not used on the NAS: the Caddy image is pulled (`xerscope-caddy`), never built there |

Add a `.env` from `.env.example` with the five values (§6). Container Manager's Environment
fields at project creation do not feed the compose file's `${...}` interpolation: left empty,
the build stops with `error while interpolating services.tailscale...`.
`docker` is a shared folder: restrict it to your DSM account (Control Panel → Shared
Folder → Permissions). DSM stores the project's variables in clear too, readable by any
DSM administrator — same confidentiality as the folder, not a vault.

## 5. The exports folder

A shared folder (for example `planning`), weekly `.xer` dropped by Synology Drive or
SMB; sub-folders are not read. Mounted read-only: the app cannot alter or delete anything.
On the NAS the app runs as a dedicated DSM account, the only one besides yours that can read
the folder; *Everyone* would open the exports to every NAS account. Create the account
(Control Panel → User: group `users`, every application denied, no access to any other
shared folder), give it read-only on a shared folder that holds only the exports to show
(for example `xerscope-data`: hidden, no recycle bin, not encrypted, since an encrypted
folder is not mounted at boot), and read its uid with a Task Scheduler script run as your
own account: `id <account> > /volume1/docker/xerscope/uid.txt 2>&1`. Then
`XERSCOPE_UID` and `XERSCOPE_GID` in `.env`. Without them the app runs as uid 65532, which
has no right on that folder: the page shows no file and the log says `Permission denied`.

The case of the folder name matters inside the container: `/volume1/Planning` and
`/volume1/planning` are two different paths. Copy it from File Station.

The visitor reads this folder and nothing else: `XERSCOPE_DATA_LOCKED` removes the files
window's field that takes a path and the XER uploads (exports and baseline: one parsed 40 MB export
takes about 1 GB, so a few uploads would exhaust the app's memory cap, §7). New weeks go in
the shared folder. The only upload left is a standard (.toml) on the Schedule health page,
capped at 1 MB (`STREAMLIT_SERVER_MAX_UPLOAD_SIZE`). An error shows no traceback on the page
(`STREAMLIT_CLIENT_SHOW_ERROR_DETAILS`), only in the log.

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
XERSCOPE_PASSWORD_HASH='$2a$10$...'     # single quotes: unquoted, Compose reads the $ as variables
XERSCOPE_PATH=<random>                 # no slashes
XERSCOPE_EXPORTS=/volume1/<shared-folder>   # exact case
XERSCOPE_UID=<uid>                          # the dedicated account (§5)
XERSCOPE_GID=<gid>
# XERSCOPE_IMAGE=<image>@sha256:<digest>    # the build to run, pinned (§7)
# XERSCOPE_CADDY_IMAGE=<image>@sha256:<digest>   # the same for Caddy (§7, §8)
# XERSCOPE_MEM_LIMIT=2g                     # the app's memory cap (§7)
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
| new app or Caddy build | Container → Image → the image (`ghcr.io/xerscope/xerscope`, `ghcr.io/xerscope/xerscope-caddy`, or their Docker Hub copies) → Update, then Project → Action → **Build** (recreates from the new image; the node state is kept, the URL does not change) |
| pin a build | `.env`: `XERSCOPE_IMAGE=<image>@sha256:<digest>`, Build. The `image` run prints the digest (`pushing manifest for …@sha256:…`); a tag (`sha-<short>`, `:0.1.0` from a git tag `v0.1.0`) can be pushed again by whoever holds the push token, a digest cannot change. Rollback = the previous digest, Build |
| new password or login | edit `.env` → Project → Action → Build (Caddy reads them at start) |
| new `deploy/` files (a merged PR changed `Caddyfile`, `compose.yaml` or `tailscale-serve.json`) | copy the changed files over the ones in `docker/xerscope/`, keep `.env`, add any new variable from `.env.example`, Build |
| hash made at another cost | bcrypt reads the cost from the hash: a `$2a$14$` hash still logs in, but every wrong password then costs the NAS cost 14 (§3). Regenerate it at cost 10, `.env`, Build |
| new prefix | `.env` → `XERSCOPE_PATH` → Build; the old URL goes 404 at once |
| new Tailscale key | only for a new node: Project → Stop, Container Manager → Volume → delete `xerscope_tailscale-state`, new key in `.env`, Build; delete the old machine in the admin console |

Caddy/Tailscale bumps: Dependabot opens a PR on `deploy/`. After merge, a Caddy bump is a
new `xerscope-caddy` image (update it as above); a Tailscale bump is the pin in
`compose.yaml`: copy it to the NAS, Build. The `caddy-ratelimit` version in
`deploy/caddy/Dockerfile` is bumped by hand, with the caddy tags.

**Memory.** Each container has a memory and a PID cap, and its tmpfs a size
(`deploy/compose.yaml`): past its cap the kernel kills that container alone, Docker restarts
it, and the NAS keeps its RAM. The app's cap is `XERSCOPE_MEM_LIMIT`, default `2g`. Measured
on a synthetic 43 MB export (97,121 activities): 0.95 GB at the peak of parsing, Streamlit's
cached copy included; a DCMA check on it, 0.9 GB on its own; each further file of that size
held in the session adds about 0.75 GB. A real export carries wider rows, so fewer
activities per MB: after loading the usual weeks, read the app's memory in Container Manager
and keep the cap above it, within what the NAS can spare. If the Project's build output says
`Your kernel does not support memory limit capabilities`, Docker dropped the cap. There is no
CPU quota on purpose: Docker refuses to create a container with one on a kernel without CFS
bandwidth control.

## 8. Image on Docker Hub

A **public** Docker Hub repository pulls without a registry login: steps 1 and 2 below, skip
step 3. Anyone holding the Read & Write token can push a `latest` the NAS would pull at
the next Update, so pin `XERSCOPE_IMAGE` to a digest (§7).

A private ghcr package needs a GitHub token on the NAS, which Container Manager does not
handle. Keep the image private on Docker Hub instead, where Container Manager logs in
natively:

1. hub.docker.com → Create repository `xerscope`, **Private** (the free plan includes one),
   and `xerscope-caddy`, **Public**: Caddy and its module only, the Caddyfile and the
   secrets are mounted at run time. Create both before the first run: a push to a missing
   repository creates it with the account's default visibility. Account settings →
   Personal access tokens: one **Read & Write** for GitHub, one **Read-only** for the NAS.
2. GitHub → repository → Settings → Secrets and variables → Actions: secrets
   `DOCKERHUB_USERNAME` (`<docker-hub-login>`) and `DOCKERHUB_TOKEN` (the Read & Write one);
   variable `DOCKERHUB_IMAGE_OWNER` = `<docker-hub-login>`. Actions → `image` → Run workflow;
   the run pushes both images to both registries.
3. NAS: Container Manager → Registry → Docker Hub → Settings → Edit → login + the read-only
   token → **Use**.
4. `.env`: `XERSCOPE_IMAGE=<docker-hub-login>/xerscope:latest` and, if ghcr is out of reach
   for Caddy too, `XERSCOPE_CADDY_IMAGE=<docker-hub-login>/xerscope-caddy:latest` (nothing
   to edit in `compose.yaml`). Build.

If Build still answers `pull access denied`, the project's pull does not use the registry
login: pull once from Container Manager → Registry (search the image) or Image → Add, then
Build; Compose starts from the local image without pulling again.

The ghcr package can stay private: only the NAS reads the Docker Hub copy.

## 9. Security checklist

- [ ] Package public = source already public; nothing else in the image (no data, no secret: `tests/test_docker.py` pins it).
- [ ] Tailscale key: tagged, single-use, non-ephemeral; once the node is up, delete it from the admin console and its line from `.env` (`TS_AUTH_ONCE`: it is never replayed, the node lives in the volume).
- [ ] Tailnet policy: tagged nodes reach nothing (`grants` source `autogroup:member`, §3).
- [ ] App image pinned by digest (`@sha256:`), not by tag (§7); the Dockerfile's base images are pinned the same way.
- [ ] Memory and PID caps on the three containers (four with the optional `llm`, §10), bounded tmpfs, read-only root filesystems; no CPU quota (§7). The build output carries no `does not support memory limit`.
- [ ] The visitor cannot type a folder path nor upload an XER (`XERSCOPE_DATA_LOCKED`), sees no traceback (§5) and no Debug page (`XERSCOPE_DEBUG_PAGE` unset).
- [ ] Caddy answers every request, 404 and 401 included, with `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'self'`, `Strict-Transport-Security` and `Permissions-Policy` (the CI job `deploy` runs the stack and checks them); no `Server` header except on the 401; downloads (`/media/*`) carry `Cache-Control: no-store`.
- [ ] `docker` shared folder readable by your account only (`.env`: key + hash in clear).
- [ ] No `ports:` anywhere. `egress` network for tailscaled only; `internal` has no gateway: the app reaches nothing and the LAN does not reach the app.
- [ ] Caddy: `admin off`, `default_bind 127.0.0.1`; the log keeps the visitor's IP (`trusted_proxies`, loopback only) and the path, with the prefix replaced by `<prefix>` in the request line, Referer and redirect, in the access log and in the error log (global `log` block); it drops Streamlit's XSRF token (WebSocket subprotocol) and the downloaded file's name (the tables export carries the project code).
- [ ] Caddy refuses with 429, before the password check, a visitor over 120 requests a minute (per IPv4 address, per IPv6 /64; the CI job `deploy` checks it); the `caddy` container runs the `xerscope-caddy` image (§2 step 3: `list-modules` shows `rate_limit`).
- [ ] One shared password: change it when the viewer changes; the day the viewer can install Tailscale, drop Funnel for Serve + Tailscale login.
- [ ] Review the Caddy log now and then (Container → caddy → Log): one IP, one login, the paths you expect.

## 10. Optional: a local language model for the Gantt "Ask" field

The Gantt page takes a sentence ("critical not started in civil works", "jalons en retard")
and turns it into its own filters (`analysis/query.py`). Without a model, a keyword grammar
over the file's lexicon (WBS, activity codes, resources, activity-name words, trade synonyms
in both languages, typos) answers: 100 % of `tests/ask/dev.toml`, 100 % of the held-out
sentences, 100 % of the demo's own lexicon (`ask-bench --self`); on a company's file,
`ask-bench <folder> --self --lexicon <folder>` lists what its lexicon file should add. The `llm` profile of `deploy/compose.yaml` adds a llama.cpp server for what the
grammar misses. It
receives the file's WBS, code and resource names only: no activity, no date, no number
(`tests/test_query_llm.py` checks the request). An answer that does not come, in 20 s, or
does not parse, is replaced by the grammar's: the page never waits on the model.

Before any model: the grammar reads the trade words of `lexicon/fr-en.toml` and those of
the folder `XERSCOPE_LEXICON` names, mounted read-only like the exports (`*.toml` files,
`[[group]] words = ["CVC", "HVAC"]`): a company's own words and abbreviations find its
nodes without a model. `xerscope lexicon <folder>` checks the files; `xerscope ask-bench
<folder> --cases <sentences>.toml --lexicon <folder> --anonymize` measures the gain on a
real schedule without naming anything.

What the model does, with the profile on: it **summarises** what a sentence found, in one
English sentence, from the values xerscope computed (the funnel's steps and counts, the ten
worst floats as Activity ID, float and finish date, the successors of the worst: never a
name, never the file), streamed into the banner under the template answer (`query.facts`,
`query.summary`). Every number, Activity ID and date of the summary must be among the values
given, or the summary is dropped and the template answer stands alone (`query.grounded`).
The standard questions ("what is critical", "what is late", "milestones not started",
"what is in progress") are summarised ahead, in the background, when a file is loaded, so
they answer at once; a new question streams, first words after about a second once the
prefix is warm, forty words in ten to twenty seconds on the NAS. Measured on the demo's
held-out sentences with Qwen3.5-2B Q4 (`ask-bench --url … --summary`, a 4-core x86 faster
than the NAS): 20/20 summaries in 4 to 9 s, 17/20 kept by the guard, and, read by a person,
about a third of the kept ones misuse a value (a step count called days, another activity's
date): the guard proves the values exist, not that they are used right. The verdict, for
now: leave the summary off and let the template answer, which is always right, stand; the
code and `ask-bench --summary` stay for the day a better model or a GPU changes the
measurement. The model is not used to understand the sentence either: measured at 55 %
against the grammar's 100 %, that path stays for `ask-bench --url` only.

**The link is TLS to the model's own certificate, with a key, or nothing.** The app refuses
to configure a model over plain http, without the certificate or without the key
(`query.llm_backend`); the model does not start without a key; nothing listens on the
model's address but its TLS front; and the model's containers are rootless and sealed.

1. Put one GGUF model in a folder the `XERSCOPE_UID` account can read, e.g. `models/` next to
   `exports/`. On the DS918+ (Celeron J3455, 4 cores, no GPU) a 3B model quantised Q4_K_M
   (about 2 GB) answers in 8-15 s and fits `XERSCOPE_LLM_MEM_LIMIT=3g` with a 4k context; a
   1.5B model answers in 4-6 s and misses more negations.
2. Make the model's certificate once, in `docker/xerscope/llm-certs/` (not in git), readable
   by the `XERSCOPE_UID` account only:

   ```bash
   mkdir -p llm-certs && openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
     -days 3650 -subj /CN=xerscope-llm -addext subjectAltName=IP:172.29.0.20 \
     -keyout llm-certs/llm.key -out llm-certs/llm.crt
   ```

   ```bash
   chown -R <XERSCOPE_UID> llm-certs && chmod 700 llm-certs && chmod 600 llm-certs/llm.key
   ```

3. `.env`: `XERSCOPE_LLM_KEY=$(openssl rand -hex 24)`, `XERSCOPE_MODELS=<folder>`,
   `XERSCOPE_LLM_MODEL=<file>.gguf`.
4. `compose.yaml`, `xerscope` service: uncomment the three `XERSCOPE_QUERY_*` lines, the
   `llm-ca.crt` volume line and the `llm` network lines. The URL is `https://172.29.0.20:8443`,
   the key is the one above, the certificate is the one made in step 2 (self-signed: it is
   its own CA, and the app trusts it alone).
5. Build with the profile: Container Manager runs `docker compose --profile llm up -d`
   (`llm` and `llm-tls` are in the `llm` profile only; without it nothing changes).

How the pieces hold (`tests/test_docker.py`, `tests/test_query_llm.py`):

- **A network of its own, where nothing listens.** The model is on `llm` (`172.29.0.20`),
  an internal network with no gateway that holds the model and the app alone. The app sits on
  it at `172.29.0.10` but Streamlit binds its `internal` address (`172.28.0.10`, the
  `command` and `healthcheck` of the service) and nothing else: from the model's namespace
  there is no app port, no Caddy, no tailscaled and no internet to reach. The app names the
  model by its address, so a container that took the service name is not spoken to.
- **Loopback and a TLS front.** The stock llama.cpp image is built without SSL, so the
  model listens on `127.0.0.1:8080` of its own namespace (`LLAMA_ARG_HOST`) and `llm-tls`,
  a stock Caddy sharing that namespace (`network_mode: service:llm`, as the funnel's Caddy
  shares tailscaled's), is the only listener on `172.29.0.20`, on 8443, with the certificate
  of step 2. The app verifies the connection against that certificate alone
  (`XERSCOPE_QUERY_CA`, read at the first call); any other certificate is refused.
- **A key on every request.** `XERSCOPE_LLM_KEY` is the model's `LLAMA_API_KEY`; the app
  sends it as a bearer token; a request without it gets 401 and the app falls back on the
  grammar. The front's log deletes the `Authorization` header; the app logs nothing of the
  call; llama-server logs no header.
- **The vocabulary is handed over once.** At a file's load the app sends the model the
  static prefix of every prompt (rules, lexicon, the file's labels) in the background
  (`query.warm`, `cache_prompt`, the server's `--cache-reuse`); the server keeps that state,
  so a sentence then costs its own tokens. Nothing is learnt: the model's weights never
  change, and a restart of the model forgets the prefix until the next load.
- **Rootless and sealed.** Both containers run as `XERSCOPE_UID`, read-only, with every
  capability dropped (the Caddy binary's file capability aside, as the funnel's Caddy),
  `no-new-privileges`, `ipc: none`, `noexec,nosuid` tmpfs, memory and PID caps. The model
  mounts its model folder read-only and nothing else; the front mounts its Caddyfile and the
  certificate read-only and writes nothing. A model can answer wrongly at worst: every id it
  answers is checked against the vocabulary.

A GPU machine of the tailnet instead of the NAS would be the same three variables pointed
at it, with the same front in front of it; it is not covered here (the app would then
leave its networks, which `tests/test_docker.py` pins).

## 11. Troubleshooting

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
| 429, Caddy log `"status": 429` | over 120 requests a minute from one address (a crawler, a retry loop, or many people behind one company proxy) | wait a minute; if it is real use, raise `events` in `deploy/Caddyfile`, Build |
| caddy log `unrecognized directive: rate_limit` | the stock `caddy` image runs instead of `xerscope-caddy` | `compose.yaml` and `.env` (`XERSCOPE_CADDY_IMAGE`) as in `deploy/` |
| app lists no file | `XERSCOPE_EXPORTS` path/case, or permission | §5 |
| the app container restarts while files load (Container Manager: exited, then running) | the memory cap: the kernel killed it | load fewer weeks at once, or raise `XERSCOPE_MEM_LIMIT` in `.env` within the NAS's free RAM (§7), Build |
| old node still listed in the admin console | state folder emptied | delete the stale machine there |
