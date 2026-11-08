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
build). A fourth, `lexicon-init`, runs the app's image on demand only, then exits: `up` and
Build leave it out (§10). Container Manager with Projects (DSM 7.2+) is required: the stack is a compose file.

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
| `lexicon/` | create it with `generated/`, `curated/` and `suggested/` in it, owned by the app's account (§10) |

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
capped at 1 MB (`STREAMLIT_SERVER_MAX_UPLOAD_SIZE`); a lexicon file sent there is refused (no
`[standard]` table) and never read by the Ask field, which reads the NAS folder only (§10).
A message from the browser is capped at 1 MB (`STREAMLIT_SERVER_MAX_WIDGET_STATE_SIZE`); the
Ask sentence is cut at 300 characters by the page itself. An error shows no traceback on the page
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
# XERSCOPE_LOAD_WORKERS=1                  # files read at once (§7)
# XERSCOPE_DEBUG_PAGE=1                    # the Debug page, for a diagnosis only (§9)
# XERSCOPE_LEXICON_DIR=/volume1/docker/xerscope/lexicon   # the Ask lexicon folder (§10)
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

**Files read at once.** On Done the app reads the chosen files on `XERSCOPE_LOAD_WORKERS`
processes (default `1` here). Each holds the export it reads, about 1 GB at the peak for 40 MB,
plus about 0.13 GB for its own Python, inside the same cap, while the app keeps the files already
read (0.75 GB each). At the end of a load the peak is about `weeks × 0.75 + workers × 1.1` GB for
exports of that size: 6 weeks on 2 workers, 6.7 GB, needs `XERSCOPE_MEM_LIMIT=8g`; the default
`2g` holds one file at a time and a couple of weeks. Two workers read about 1.8 times faster than
one; raise both values together, then read the peak in Container Manager as above.

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
- [ ] Memory and PID caps on the four containers, bounded tmpfs, read-only root filesystems; no CPU quota (§7). The build output carries no `does not support memory limit`.
- [ ] `lexicon/` (§10): owned by the app's account, mode 700; `curated/` read-only in both containers, `generated/` written by `lexicon-init` only, `suggested/` by the app only (purged by `lexicon-init` and by the app). `lexicon-init` is not started by Build (profile `lexicon`, §10).
- [ ] The visitor cannot type a folder path nor upload an XER (`XERSCOPE_DATA_LOCKED`), sees no traceback (§5) and no Debug page (`XERSCOPE_DEBUG_PAGE` unset).
- [ ] Caddy answers every request, 404 and 401 included, with `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'self'`, `Strict-Transport-Security` and `Permissions-Policy` (the CI job `deploy` runs the stack and checks them); no `Server` header except on the 401; downloads (`/media/*`) carry `Cache-Control: no-store`.
- [ ] `docker` shared folder readable by your account only (`.env`: key + hash in clear).
- [ ] No `ports:` anywhere. `egress` network for tailscaled only; `internal` has no gateway: the app reaches nothing and the LAN does not reach the app.
- [ ] Caddy: `admin off`, `default_bind 127.0.0.1`; the log keeps the visitor's IP (`trusted_proxies`, loopback only) and the path, with the prefix replaced by `<prefix>` in the request line, Referer and redirect, in the access log and in the error log (global `log` block); it drops Streamlit's XSRF token (WebSocket subprotocol) and the downloaded file's name (the tables export carries the project code).
- [ ] Caddy refuses with 429, before the password check, a visitor over 300 requests a minute (per IPv4 address, per IPv6 /64; the CI job `deploy` checks it); the `caddy` container runs the `xerscope-caddy` image (§2 step 3: `list-modules` shows `rate_limit`).
- [ ] One shared password: change it when the viewer changes; the day the viewer can install Tailscale, drop Funnel for Serve + Tailscale login.
- [ ] Review the Caddy log now and then (Container → caddy → Log): one IP, one login, the paths you expect.

## 10. The Gantt "Ask" field

The Gantt page takes a sentence ("critical not started in civil works", "jalons en retard")
and turns it into its own filters, a one-sentence answer and a population funnel
(`analysis/query.py`): a keyword grammar over the file's lexicon (WBS, activity codes,
resources, activity-name words), the company's trade words and the files' variants, typos
read at a lower confidence. Nothing else runs: no model, no container, no network access.
Measured on the demo with the tests' generic lexicon (`tests/asklex.py`): 100 % of
`tests/ask/dev.toml`, 100 % of the held-out sentences, 100 % of the demo's own lexicon
(`ask-bench --self`); on a company's file, `xerscope ask-bench <folder> --self --lexicon
<folder>/curated --anonymize` lists what its lexicon should add, without naming anything.

**The lexicon folder lives on the NAS only.** No lexicon file is in the repository or the
image (`tests/test_docker.py` checks every `.toml` packaged), none can be uploaded (the
standard upload refuses one, §5) and none can be downloaded from the app.
`XERSCOPE_LEXICON_DIR` (default `/docker/xerscope/lexicon`; on DSM the full path,
`/volume1/docker/xerscope/lexicon`) holds three folders, created by hand in File Station,
owned by the `XERSCOPE_UID` account and readable by it only (Docker would create a missing
one owned by root, and the containers could not write it):

| Folder | Written by | Read by the Ask field | Holds |
|---|---|---|---|
| `generated/` | `lexicon-init` only, when you run it | `variants.toml` only, less the refusals | `variants.toml`: the exports' variants per source column, plurals and abbreviations (`ask/generated.py`); `report.txt`: groups per column, those new since the last run, and the section "to review (one letter apart, not used)": one pair per line with its column, never read by the Ask field |
| `curated/` | you, by hand; read-only in both containers | yes | `*.toml`: trade words (`[[group]] words = ["CVC", "HVAC"]`) and refusals of generated groups (`[[refuse]] column = "PROJWBS.wbs_name"`, `words = ["fondation", "fondations"]`: the generated group holding all those words is dropped; a refusal wins over `generated/`) |
| `suggested/` | the app only, appending | no | `suggestions.toml`: one `[[suggestion]]` per click on a "Did you mean" label: the unknown word, the label, its source column, the filter (facet, value) and the date, never the sentence asked |

Two words one letter apart are never read as one: on public XER files that rule joined
different words ("screed" / "screen", "coarse" / "course", "lighting" / "lightning") and
nothing in the files tells them from a typo ("gybsum" / "gypsum"). Read the "to review"
section of `report.txt` after a run and copy each true typo into a `curated/` file
(`[[group]] words = ["gybsum", "gypsum"]`).

A word taught by a click holds for the visitor's session at once; for every session, copy
it into a `curated/` file. A suggestion older than 90 days whose word `curated/` does not
hold is purged by `lexicon-init` and by the app at its next click, under the same lock: a
stack where `lexicon-init` is not run for months still keeps none past 90 days. `xerscope lexicon /lexicon/curated` checks the curated files (a bad
file is named, never fatal to the app; Debug block 14 lists the load errors to every session,
each as its file and line or refusal number, never the words it holds).

`lexicon-init` (`deploy/compose.yaml`) runs `xerscope lexicon build /data --out /lexicon`
with the app's image and account, no network (`network_mode: none`), a read-only root
filesystem, no capability, `no-new-privileges`, the exports read-only and the lexicon
read-only but for `generated/` and `suggested/`. Both must exist: a missing one stops it
with `error: create <folder> owned by the app account, see docs/deploy.md §10` and exit
code 1 (it never creates one: Docker would make it root's). Files are replaced through a temporary file
and a rename, created 0600 (`mkstemp`); its log holds counts only.

Each export is checked before the generation and skipped if it fails, the others still read:
read without error (`unreadable`), its `%E` end line present (`incomplete`, a file still being
copied), the tables `TASK` and `PROJWBS` present (`missing table TASK`, `missing table
PROJWBS`), a project to select (`no project`), at most 64 MB (`too large`: a 40 MB export
peaks at about 1 GB parsed, §7, and the default memory cap is 2 GB; `LEXICON_MAX_BYTES` in
`cli.py`). `report.txt` ends with a section `skipped (not read):`, one `<file>: <reason>` per
line; the log says `<n> file(s) skipped, named in generated/report.txt` and never names an
export (their names are often the project's), nor quotes one. When no export passes (or the
folder holds none), `generated/` is left as it is, the log says `error: no valid XER file in
the source folder (<n> skipped), generated/ left as it is` and the exit code is 1; the
suggestions are then not purged either (the app still purges them at its next click).

**When to run it.** `lexicon-init` is in the compose profile `lexicon`: `docker compose up`
and Container Manager's Build leave it out, and the app never waits for it. The app starts
with the `generated/` the last run left (none before the first run: the Ask field then reads
`curated/` and the variants it derives in memory from the loaded files). Run it after new
exports have landed, before reviewing `report.txt`, or after a curated refusal, from the
project folder:

```
docker compose run --rm lexicon-init
```

Compose enables the profile of a service named on the command line by itself (Docker docs,
"Using profiles with Compose"). On the NAS, Container Manager has no button for it: enable
SSH (Control Panel → Terminal & SNMP), then `cd /volume1/docker/xerscope && sudo docker
compose run --rm lexicon-init`, and disable SSH again. The output is one line per column
(`<column>: <n> group(s), <k> new`), then `suggestions: <kept> kept, <purged> purged`, exit
code 0. The app reads `generated/` once per process: Project → Action → Build to use the
new files (on a PC, `docker compose restart xerscope`).

Threat model of the folder, written from a web page. *Who writes:* anyone holding the URL and
the password reaches the teach buttons. *What they control:* the unknown word (any text typed
in the Ask field) and the choice among the labels offered (the file's own labels). *What
stops them:* the file name is fixed (`suggestions.toml`, no path from the input); word and
label are NFKC-normalised, at most 64 and 160 characters, letters, digits and
`` .-_'&/()·,:+#`` only (no control character, newline, bracket, quote, backslash, `=` or
invisible Hangul filler),
written through `json_quote`, so no TOML table can be injected; one exclusive `flock`
serialises the size check and the append; the file stops at 256 KB (a refusal shows a
neutral line that does not repeat the word); it is opened with `O_NOFOLLOW` (a symlink put
in its place is not followed) and created 0600; nothing is printed or logged. *What it cannot
reach:* the Ask field of any session, since `suggested/` is read by nothing until you copy a
word into `curated/`; `curated/` and `generated/`, read-only in the app. *What is left:* a
visitor can fill `suggestions.toml` up to its cap with distinct words (one correction, word,
label and column, is kept once; past the cap the corrections stop being recorded, the app
keeps working), and the words typed land on the NAS for up to 90 days.
`tests/test_ask_suggested.py` has one test per guard.

A language model was measured against this and not kept (`analysis/query.py: llm_backend`
stays as the measurement client of `ask-bench --url`): understanding the sentence,
Qwen3.5-2B Q4 reached 55 % of the held-out sentences against the grammar's 100 %, in
about 19 s a sentence on a 4-core x86 faster than the NAS; summarising an answer from
computed values, 17 of 20 summaries passed a value check and about a third of those
misused a value when read. The backlog says what would change that measurement.

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
| 429, Caddy log `"status": 429` | over 300 requests a minute from one address (a crawler, a retry loop, or many people behind one company proxy; one first visit is ~125) | wait a minute; if it is real use, raise `events` in `deploy/Caddyfile`, Build |
| caddy log `unrecognized directive: rate_limit` | the stock `caddy` image runs instead of `xerscope-caddy` | `compose.yaml` and `.env` (`XERSCOPE_CADDY_IMAGE`) as in `deploy/` |
| app lists no file | `XERSCOPE_EXPORTS` path/case, or permission | §5 |
| the app container restarts while files load (Container Manager: exited, then running) | the memory cap: the kernel killed it | load fewer weeks at once, or raise `XERSCOPE_MEM_LIMIT` in `.env` within the NAS's free RAM (§7), Build |
| old node still listed in the admin console | state folder emptied | delete the stale machine there |
