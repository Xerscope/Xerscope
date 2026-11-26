# IT deployment guide

Français : [Guide de déploiement pour la DSI](it-deployment-guide.fr.md)

This guide describes how xerscope is delivered, what it needs from a host, and what it leaves to the
organisation that hosts it. It is written for the IT department and the security officer (RSSI) of
an organisation that handles sensitive information and plans to host xerscope for a team of
planners.

## Purpose, audience and status

xerscope reads weekly Primavera P6 schedule exports (`.xer`) and reports on them. It is delivered as
a Python package, as a container image of its web app, as a Caddy reverse proxy image, and as two
Compose files.

You decide the sensitivity of the data, the zone, the accreditation (homologation) and the hardening
of the host. The guide gives you facts that you can check in the repository, and it makes no claim
of compliance, certification or accreditation. Where it cites a French reference document, it says
how the shipped files stand against that document and stops there.

Three status words have a fixed meaning. *Not provided*: the repository holds nothing on the point.
*Not established*: the files do not settle it. *Left to the host*: the decision or the setting is
yours.

### Deployment options and their test status

Table 1 lists the four ways to run the web app and what the project tests for each.

**Table 1.** Deployment options and their test status

| Option | What it is | Shipped | Tested by the project |
|---|---|---|---|
| A | A planner's workstation, `uv run xerscope app`, loopback only | Yes: the source tree and [`uv.lock`](../uv.lock) | The test suite runs in CI on Python 3.11 and 3.14 on each push to `main` and on each pull request. The packaged setting `address = "localhost"` keeps the app on the loopback interface |
| B | The local image with [`compose.yaml`](../compose.yaml), published on the host's loopback, no authentication | Yes | [`tests/test_docker.py`](../tests/test_docker.py) pins the loopback publication, the non-root user, the build from the lockfile and the build context. The CI job `container` builds the image, starts it, reads `/_stcore/health` on port 8501 and reads a mounted folder |
| C | The remote stack [`deploy/compose.yaml`](../deploy/compose.yaml): Tailscale Funnel, Caddy, the app | Yes | `tests/test_docker.py` pins the layout. The CI job `deploy` validates the Compose file, starts `tailscale` and `caddy` and checks Caddy's answers, "without the app and without a tailnet login" ([`tests.yml`](../.github/workflows/tests.yml)). No test exercises Funnel, the tailnet policy or the certificate |
| D | An internal server behind your own reverse proxy and authentication, without Tailscale | No | No |

The Docker procedures of this guide combine the shipped files with standard Docker and Compose
commands. The project tests the properties named in table 1, not each procedure from end to end.

### Versions

The guide describes the repository at commit `4a8eab2`. The package version is `0.1.0`
([`pyproject.toml`](../pyproject.toml)), and [`CHANGELOG.md`](../CHANGELOG.md) carries the heading
`## [0.1.0] - unreleased`: no release exists. The command line has no `--version` option and the app
shows its version on no page.

The software is proprietary: [`LICENSE`](../LICENSE) states that no licence is granted. The two
embedded fonts are under the SIL Open Font License 1.1 ([`NOTICE`](../NOTICE)).

## System summary

xerscope is a reading tool. It parses the exports that planners produce each week, recalculates the
schedule, runs quality checks, and draws pages (Gantt, earned value, changelog, milestone trend). It
never writes to an export and never connects to a P6 database.

### Components, users and data

The web app is a Streamlit application started by the `xerscope app` command. The same package
provides a command line (`check`, `export`, `sample`, `lexicon`, and eight other commands). The
Caddy image and the Tailscale image belong to option C only.

Two kinds of people use a deployment. Planners open the pages in a browser. An administrator of the
host installs the files, places the exports in a folder and holds the secrets. Everything runs on
your host: the shipped files give the supplier no access to a deployment, and usage statistics are
off in the packaged Streamlit settings (`gatherUsageStats = false`).

The app reads `.xer` files, and P6 XML exports when they hold a baseline. It also reads standards
written as `.toml` files and, on two pages, small `.csv` reports exported from P6. A schedule holds
activity names, WBS names, activity codes, user defined field values, resources, dates, durations,
units, costs and logic.

You decide how sensitive those files are, and classified information is outside the scope of this
guide. The repository holds no real schedule: the demo series written by `xerscope sample` is
synthetic (eight files, `PRJ-ALPHA_2026-08-31.xer` to `PRJ-ALPHA_2026-10-19.xer`).

### What is stored, and where

The design keeps schedule data in memory: an export that is never copied cannot be left behind.
Table 2 gives the details and the exceptions.

**Table 2.** Where data is stored, and for how long

| Place | What it holds | Lifetime |
|---|---|---|
| Session memory of the app | Uploaded bytes, parsed files, computed results (at most 128 cached results per session), anonymiser mappings (at most four sets) | The session. How long Streamlit keeps a session after the browser leaves is not set by xerscope |
| Process memory of the app | The lexicon of the **Ask the schedule** field, read once per process. It holds no session data | The process |
| Temporary directory | An uploaded file over 1 MB passes through a temporary file while it arrives, unnamed on Linux and deleted when read (Streamlit's upload handler, as its source reads). In both Compose files `/tmp` is a tmpfs, that is, memory | The upload |
| Lexicon folder (option C) | `suggested/suggestions.toml`, written by the app: one entry per correction a visitor clicks (word, label, column, facet, value, UTC time), never the sentence typed. `generated/variants.toml` and `generated/report.txt`, written by `lexicon-init` | Suggestions: purged after 90 days; file capped at 256 KB |
| Volume `tailscale-state` (option C) | The identity of the Tailscale node | Until the volume is removed |
| Container logs | See [Logging](#logging) in this guide | Set by the Docker service |
| Exports folder | Your files, mounted read-only (`:ro`) in both Compose files | Yours |

Downloads are built in memory. xerscope uses no Streamlit data cache (`st.cache_data`,
`st.cache_resource`), so one visitor never sees the files another visitor loaded through the app's
code.

### Personal data in an export

An export can identify people, which matters for your processing register. The CNIL defines personal
data as "toute information se rapportant à une personne physique identifiée ou identifiable." Table
3 lists what the code reads.

**Table 3.** Personal data in an export

| Data in the file | Shown by the app | Written in a plain download |
|---|---|---|
| Header line (`ERMHDR`): login and full name of the exporting user, database name | No: only the version and the product | No |
| Resources: `rsrc_name`, `rsrc_short_name` (a resource can be a named person) | Yes: task panel, changelog, labels of the **Ask the schedule** field | Yes: `fact_assignment` holds `rsrc_id`, `rsrc_short_name`, `rsrc_name` |
| Activity names, WBS names, activity code values, user defined field values | Yes | Yes |
| P6 audit columns (`create_user`, `update_user`) | No: no code reads them | No |

The pages always show the files' own data. The sidebar switch **Anonymous exports** is on by default
and changes downloads only. With the switch on, Task IDs, WBS, project, resource, role and OBS codes
become `X<kind><hex>` codes derived with HMAC-SHA256 under a key drawn for the session. Names are
rebuilt from the new codes, costs are set to 0, other text is emptied, and the header's user fields
become `ANON`. A file that still holds an original value is refused instead of being handed out.
Dates, durations, units and logic are unchanged.

Any visitor can turn the switch off for a session, and no setting forces it. With the switch off,
the tables export is named `<project code>_xerscope_<format>.zip`. Two places keep traces of
visitors: Caddy's log keeps their IP address, and the suggestions file keeps the words they clicked.

For your register, two points follow from the shipped files. The purpose of the processing is left
to the host: the software reads the exports and draws the reports named in the system summary, and
nothing else. As for who can see the personal data, every person who can open the app sees the same
pages, because the app has no role. The administrator of the host can read the exports folder, the
lexicon folder and the logs. The shipped files give the supplier no access.

## Regulatory frame and accreditation inputs

Which regime applies to your deployment follows from who you are and what the schedules hold. The
supplier asserts nothing about it. This section records what the French reference documents say, so
that you can place xerscope in your own analysis. For the full citations, see
[References](#references) in this guide.

### Regimes left to your determination

Table 4 lists each regime with what the cited documents state.

**Table 4.** Regimes and what the cited documents state

| Regime | What the cited documents say | Source |
|---|---|---|
| RGS | The homologation guide lists it among the regulations that make accreditation mandatory, for systems "traitant d'informations entre administrations ou entre administrations et administrés". The RGS is cited through that guide only | ANSSI and DINUM homologation guide, Version 2.2 – Mars 2026 |
| Decree on the State's information system | Named as "décret n°2022-513 du 8 avril 2022 relatif à la sécurité numérique du système d'information et de communication de l'Etat". Cited through that guide only | Same guide, §2.4 |
| II 901 | "Tout SI sensible doit être homologué. Toutes les interconnexions de ce SI doivent également être homologuées." For Diffusion Restreinte information, "l'application de l'II 901 est obligatoire."; for ordinary information, "ni l'IGI 1300 ni l'II 901 ne s'appliquent." The instruction is cited through that guide only | ANSSI-PG-075, Version 1.2, 24/09/2021 |
| IGI 1300 | "La mention Diffusion Restreinte n'est pas un timbre de classification mais une mention de protection." "La transmission d'informations Diffusion Restreinte est interdite sur le réseau Internet ou sur tout autre système d'information non homologué Diffusion Restreinte, sauf à faire l'objet de mesures de protection particulières". The wording of the two quotes is not established: compare it with the instruction before you rely on it | SGDSN, IGI 1300, file `igi-1300-20210809.pdf` |
| LPM, vital-importance operators | "Ces obligations s'appliquent aux systèmes d'information d'importance vitale (SIIV) désignés par les OIV et comprennent la déclaration d'incidents, la mise en œuvre d'un socle de règles de sécurité". A 2016 brochure: not evidence of the code de la défense as it stands | SGDSN brochure "La sécurité des activités d'importance vitale – Objectifs et enjeux" |
| NIS 2 | "La transposition de la directive NIS 2 en France est en cours." The ReCyF referential is a working document ("VERSION DE TRAVAIL") | ANSSI NIS 2 page, as published on 2026-11-26; ReCyF, Version 2.5 du 17/03/2026 |
| SecNumCloud | "Ce document constitue le référentiel d'exigences applicables à un prestataire de services d'informatique en nuage (SecNumCloud), ci-après dénommé le « prestataire »." Whether it concerns a server in your premises is not established | SecNumCloud referential, Version 3.2 du 8 mars 2022 |
| GDPR | Security "s'impose à tout responsable de traitement et sous-traitant à travers l'article 32 du Règlement général sur la protection des données (RGPD)." "Le registre est prévu par l'article 30 du RGPD." | CNIL, security guide (sheets dated 14 mars 2024; the sentence on article 32 is on <https://www.cnil.fr/fr/securite-avant-propos>) and register page (13 avril 2018) |

Whether the supplier is a "sous-traitant" in the GDPR sense is not answered by those pages. It
depends on whether the supplier processes data on your behalf, and nothing in the shipped files
gives the supplier access to your data.

The shipped files target a workstation (options A and B) and, in the words of the header of
`deploy/compose.yaml`, "a PC and for a NAS" (option C). If you choose a cloud offer instead, the
questions that SecNumCloud raises for sensitive systems are yours. The ANSSI guide on cloud hosting
notes that the qualification "ne préjuge en revanche pas du niveau de sécurité des services
numériques des clients qui seront portés par ces offres cloud."

### Accreditation

The homologation guide defines the accreditation decision as "un préalable à toute utilisation d'un
système d'information." It describes three levels (simplifié, intermédiaire, renforcé), chosen from
the criticality and the exposure of the system. Both ratings, and the level, are your decision. The
exposure scale matters when you compare the options: "faible : Le système d'information est ouvert
uniquement sur des réseaux maîtrisés (par exemple sur un intranet)." and "total : Le système
d'information est directement ouvert sur Internet". Option C publishes a URL on the Internet.

The guide names no file that an application supplier must hand over. Table 5 maps the pieces of the
accreditation file, with the row labels the guide prints, to the sections of this guide. Which piece
is required at which level is not established.

**Table 5.** Pieces of the accreditation file and the sections of this guide

| Piece of the file | Sections of this guide | Not provided |
|---|---|---|
| "Document d'accompagnement" | System summary; Flow matrix; Known gaps and residual risks | Volumes of your own data |
| "Dossier d'architecture technique" | Architecture; Flow matrix; Accounts, authentication, sessions and secrets; Container hardening | See table 6 |
| "Matrice de conformité" | Container hardening against ANSSI-FT-082 | Any other baseline, such as the 42 measures of the hygiene guide |
| "Analyse de risque" | Known gaps and residual risks, as input | The analysis itself |
| "Procédures d'exploitation" | Procedures | User management and incident handling |
| "Plan de maintien en condition opérationnelle" | Procedures (health check, backup); restart policies in Container hardening | The plan itself |
| "Plan de maintien en condition de sécurité" | Origin and integrity of images and dependencies; update and rollback procedures | Fix delays and a notification channel from the supplier |
| "Plan d'action" | Last column of the gaps table, as input | The plan itself |
| "Plan de résilience" | Backup and restore procedure | The plan itself; time to rebuild is not established |
| "Audits" | Tests and scans named in this guide | The repository holds no audit or penetration test report |
| "« Historique » du système d'information" | `CHANGELOG.md` | A release history: no release exists |

The ANSSI sheet "Les Essentiels – Architecture sécurisée de SI" lists the themes "à développer dans
un dossier d'architecture technique". Table 6 says where this guide addresses each theme.

**Table 6.** Themes of the technical architecture file and where this guide addresses them

| Theme, as printed | Where |
|---|---|
| "Contextes métier et réglementaire, nature et sensibilité des données et traitements" | System summary; this section. Sensitivity: left to the host |
| "Identification, authentification et gestion des droits d'accès" | Accounts, authentication, sessions and secrets |
| "Cloisonnement réseau, système et stockage" | Architecture; Container hardening |
| "Chiffrement des données en transit et au repos" | In transit: Architecture (TLS). At rest: not provided, nothing is encrypted by the shipped files |
| "Filtrage des flux" | Flow matrix. The filtering itself: left to the host |
| "Accès à distance (nomadisme numérique, tiers)" | Architecture, option C. Supplier access: none shipped |
| "Administration (dont la gestion des comptes à privilèges et DevSecOps)" | Accounts; Origin and integrity |
| "Maintien en condition de sécurité (MCS)" | Origin and integrity; Procedures |
| "Interconnexions (dont celle à Internet)" | Flow matrix |
| "Protection contre les codes malveillants" | Not provided |
| "Sécurité physique, contrôle d'accès et vidéoprotection" | Left to the host |
| "Continuité et reprise d'activité (dont les sauvegardes)" | Procedures (backup and restore) |
| "Supervision de sécurité (journalisation, détection, traitement des incidents)" | Logging. Detection and incident handling: not provided |

## Architecture

The architecture follows from one fact: the app holds the schedules and has no authentication of its
own. Each option is therefore defined by what stands between a browser and port 8501.

### Components and images

Table 7 is the component inventory. Digests are not copied here because Dependabot moves them: the
`FROM` lines of [`Dockerfile`](../Dockerfile) and
[`deploy/caddy/Dockerfile`](../deploy/caddy/Dockerfile) are the reference.

**Table 7.** Components and images

| Component | Built from | Versions | Runs as | Content |
|---|---|---|---|---|
| App image `ghcr.io/xerscope/xerscope` (local tag `xerscope:latest`) | `Dockerfile`: build stages on `ghcr.io/astral-sh/uv:0.13.8-trixie-slim`, runtime on `gcr.io/distroless/cc-debian13:nonroot`, each pinned by digest | CPython 3.14 (minor only); Streamlit 1.67.0, pandas 3.1.1, plotly 7.1.0 and pyarrow 26.0.1, as locked in `uv.lock` | `USER nonroot`, uid and gid 65532 (the base's values, as the `Dockerfile` reads) | The interpreter, `/app/.venv`, an empty `/data`, one Debian fix (`zlib1g`). No shell, no package manager, no pip (as the `Dockerfile` reads) |
| Caddy image `ghcr.io/xerscope/xerscope-caddy` | `deploy/caddy/Dockerfile`: `caddy:2.11.9-builder` and `caddy:2.11.9`, each pinned by digest | Caddy 2.11.9, `github.com/mholt/caddy-ratelimit` at commit `5625512f24f6`, `golang.org/x/net` replaced by v0.63.0, Go 1.27.4 | The image's default user. Root in the stock image: not established | Caddy and the `rate_limit` module. The `Caddyfile` and the secrets come at run time |
| Tailscale image | Not built by the project | `tailscale/tailscale:v1.104.7`, pinned by tag, not by digest | The image's default user, root according to the Compose file's comment: not established | Tailscale's own |
| Fonts | `src/xerscope/app/static/` | Onest and JetBrains Mono, latin subsets | Served by the app | Two `.woff2` files and their licence texts |

The published images are built for one architecture: the workflow has no `platforms:` key and no
emulation step, so the architecture is that of the `ubuntu-latest` runner (`linux/amd64`).

The maintenance status of the third-party components is not provided. The files give the versions of
Streamlit, pandas, plotly, pyarrow, Caddy and Tailscale, not their support period or their
end-of-life date.

Browser-side content is limited by construction. Fonts come from the app, the Gantt's JavaScript and
style sheet are files of the package, and the repository adds no external script or link to the
page. What Streamlit's own JavaScript asks a browser to fetch is not established.

### Networks and volumes

In option B, `compose.yaml` has no `networks:` key: Compose creates one project network for the
single service, and the only publication is `"127.0.0.1:8501:8501"`.

In option C, `deploy/compose.yaml` has no `ports:` key and declares two networks. The network
`egress` is an ordinary bridge to which `tailscale` alone is attached; `caddy`, which shares the
network namespace of `tailscale`, has the same way out. The network `internal` is declared
`internal: true`, which gives it no gateway, and `xerscope` is attached to it only, with the alias
`app`. The service `caddy` has no network of its own: `network_mode: service:tailscale` places it in
the network namespace of `tailscale`, where it listens on `127.0.0.1:8080`. Because `tailscale` is
attached to both networks, that container itself has a path to `app:8501`. The service
`lexicon-init` has `network_mode: none`.

The Compose file sets no project name. Started from a folder called `deploy`, the project is
`deploy`, the networks are `deploy_egress` and `deploy_internal`, and the volume is
`deploy_tailscale-state`. Table 8 lists every mount of the two Compose files.

**Table 8.** Mounts of the two Compose files

| File | Service | Mount | Mode |
|---|---|---|---|
| `compose.yaml` | `xerscope` | `./exports:/data` | Read-only |
| `deploy/compose.yaml` | `tailscale` | `tailscale-state:/var/lib/tailscale` (named volume) | Read-write |
| `deploy/compose.yaml` | `tailscale` | `./tailscale-serve.json:/config/serve.json` | Read-only |
| `deploy/compose.yaml` | `caddy` | `./Caddyfile:/etc/caddy/Caddyfile` | Read-only |
| `deploy/compose.yaml` | `xerscope`, `lexicon-init` | `${XERSCOPE_EXPORTS:-../exports}:/data` | Read-only |
| `deploy/compose.yaml` | `xerscope`, `lexicon-init` | `${XERSCOPE_LEXICON_DIR:-/docker/xerscope/lexicon}:/lexicon` | Read-only |
| `deploy/compose.yaml` | `xerscope`, `lexicon-init` | `${XERSCOPE_LEXICON_DIR:-/docker/xerscope/lexicon}/suggested:/lexicon/suggested` | Read-write |
| `deploy/compose.yaml` | `lexicon-init` | `${XERSCOPE_LEXICON_DIR:-/docker/xerscope/lexicon}/generated:/lexicon/generated` | Read-write |

### Option A: a workstation with uv

The planner runs the package from a checkout. With its default host, `xerscope app` binds
`localhost` and makes no outbound request at start. A WebSocket handshake whose `Origin` is neither
the request's host nor localhost makes Streamlit 1.67.0 request `checkip.amazonaws.com` (port 80,
then 443) to compare the origin with the machine's addresses. The request carries no schedule data,
and the handshake is refused. Nothing separates the app from the other processes of the workstation.
The folder field of the **Files and baseline** window reads any folder under one root:
`XERSCOPE_FOLDER_ROOT`, else the folder `XERSCOPE_DATA` names, else the home directory. This option
suits one planner on one machine and gives you no central control.

### Option B: the local image on the host's loopback

The same app runs in a container with a read-only root filesystem, no capability and a read-only
exports folder. The port is published on the host's loopback, so the app is reachable from the host
itself and from nowhere else. There is no authentication and no memory or process limit, and the
data is not locked: the upload field, the folder field (limited to `/data`) and the Debug page are
available. A comment in `compose.yaml` states the design choice: "Exposing it (e.g. "8501:8501") is
a deliberate choice; put authentication in front."

### Option C: the shipped remote stack

Option C is a public Internet entry point relayed by a third-party service, protected by one shared
login. A request for `https://xerscope.<tailnet>.ts.net/<XERSCOPE_PATH>/` reaches Tailscale Funnel,
which relays it to the `tailscale` container. In that address, `<tailnet>` stands for the name of
your tailnet and `<XERSCOPE_PATH>` for the value of that variable. TLS ends in tailscaled
([`deploy/tailscale-serve.json`](../deploy/tailscale-serve.json)). The request then goes to Caddy
over loopback and to the app over `internal`, both in plain HTTP.

[`deploy/Caddyfile`](../deploy/Caddyfile) answers 404 to every path outside the prefix, before any
authentication. Inside the prefix it applies a rate limit, then `basic_auth`, then answers 404 on
`/_stcore/metrics` and `/_stcore/agent/*`, then proxies to `app:8501`. The prefix exists because, as
the file's comment says, scanners find every `*.ts.net` name from the public certificate logs. The
app's service is locked (`XERSCOPE_DATA_LOCKED: "true"`): no folder field, no `.xer` upload, no
Debug page unless you ask for it. For the step-by-step on a Synology NAS, see the [Synology
deployment guide](deploy.md).

A sensitive organisation has to weigh this option against its own rules. No ANSSI or CNIL text cited
in this guide addresses third-party tunnelling or relay services by name. Table 9 therefore pairs
each property of the shipped stack with the nearest recommendation among the cited documents.

**Table 9.** Properties of option C and the nearest recommendations

| Property of the shipped stack | Nearest recommendation | Wording |
|---|---|---|
| The app is reachable from the Internet | ANSSI-PA-054, R40 "Ne pas exposer d'applications métiers directement sur Internet" | "Celles-ci ne doivent être accessibles qu'une fois le poste nomade connecté au VPN de l'entité." |
| Visitors' devices are not authenticated: no client certificate | ANSSI-PA-054, R40- "Dégradé À défaut - Authentifier les postes nomades avec une fonction dédiée en cas d'exposition d'applications métiers sur Internet" | "avec un serveur intermédiaire reverse-proxy et une configuration stricte reposant sur mTLS (mutual TLS)." The wording comes from the paragraph that introduces R40- |
| Inbound requests arrive over connections that the `tailscale` container opens outward, since no port is published | ANSSI-PA-066, R4 "Rendre incontournable la passerelle Internet sécurisée" | "Tout système d'information nécessitant une interconnexion avec Internet doit être protégé par une passerelle Internet sécurisée" |
| The relay is operated by a third party. What it can observe is Tailscale's design: not established | ANSSI-PA-066, R15- "Évaluer rigoureusement les risques d'une offre non qualifiée par l'ANSSI pour les fonctions relais externalisées" | "l'analyse de risque doit être menée avec d'autant plus de rigueur et d'exhaustivité." |
| One login and one password hash serve every reader: none is told apart in a log, none can be revoked alone | Guide d'hygiène informatique, measure 8; CNIL security guide, fiche 4 "Authentifier les utilisateurs" | "les comptes d'accès doivent être nominatifs."; "interdire les comptes partagés entre plusieurs utilisateurs." |
| No multi-factor authentication, no session timeout, no lock-out; attempts are bounded only by the rate limit of 300 requests per minute per address | ANSSI-PG-078, R1 "Privilégier l'authentification multifacteur"; R10 "Limiter dans le temps le nombre de tentatives d'authentification"; R12 "Limiter la durée de validité d'une session authentifiée" | "Les secrets temporaires de sessions (comme des cookies par exemple) doivent avoir une durée de vie limitée." |
| The channel is encrypted up to tailscaled, on your host | ReCyF (working document), 8.1-EI/EE | "(par exemple : VPN TLS ou IPSec, protocoles applicatifs chiffrés comme TLS, SSH, etc.)." |

Two more properties have no counterpart in table 9. The hosts and ports that the `tailscale`
container needs are not established by the files, and no proxy variable is set. A visitor who holds
the login can turn off **Anonymous exports** and download plain tables.

### Option D: an internal server behind your own reverse proxy

Option D is not shipped and not tested. It is your own integration, and you test it. The repository
holds no Compose file for it, and `tests/test_docker.py` pins the Funnel layout of
`deploy/compose.yaml`.

Three shipped parts can be reused unchanged. The app image listens on `0.0.0.0:8501` inside its
container, and what reaches it is decided by the network it joins. The `xerscope` and `lexicon-init`
service definitions of `deploy/compose.yaml` carry the lock, the upload limits, the memory and
process limits and the `internal` network. The `xerscope-caddy` image holds Caddy and the rate-limit
module only, so it can run another `Caddyfile`.

Three files would have to be adapted, each for a reason that the file itself shows:

- `deploy/compose.yaml`: the `tailscale` service, its volume and the `egress` network no longer
  apply. On `caddy`, `network_mode: service:tailscale` and `depends_on: [tailscale]` refer to that
  service, so Caddy needs a network shared with `xerscope` and a way in.
- `deploy/Caddyfile`: `default_bind 127.0.0.1` makes Caddy reachable from its own network namespace
  only. `auto_https off` and the site address `:8080` mean plain HTTP.
  `trusted_proxies static 127.0.0.1/32` names tailscaled: unless it names your proxy, the rate limit
  and the log see one address for everybody. The `Strict-Transport-Security` header and the
  `; Secure` added to cookies assume that visitors arrive over HTTPS.
- `deploy/tailscale-serve.json`: no longer used.

Whatever reverse proxy stands in front, the app needs five things from it:

- WebSocket: the upgrade on `/_stcore/stream` passes.
- `Host` header: it reaches the app unchanged. Streamlit 1.67.0 accepts the WebSocket when the host
  of the `Origin` header equals the request's `Host`. Otherwise it accepts only localhost, the
  server address, its own IP addresses or `server.corsAllowedOrigins`, which nothing sets.
- Prefix: the app serves `/`. `STREAMLIT_SERVER_BASE_URL_PATH` is not set and a test forbids it, so
  a proxy that publishes the app under a prefix strips the prefix and keeps the trailing slash.
- TLS: the app has none. Streamlit marks its XSRF cookie `Secure` only when it holds the certificate
  itself, which is why the shipped `Caddyfile` appends `; Secure`.
- Authentication: the app has none. On an instance without Caddy, `/_stcore/metrics` and
  `/_stcore/agent/openapi.json` answer 200 to anyone who reaches the port.

## Flow matrix

Every flow of each option is listed here, at run time and at install or update time. Ports are TCP.
A flow that no table lists is not needed by the shipped files. Two kinds of flow are implied and not
listed: the name resolution that precedes each named destination, and the hosts to which a registry
or a package index redirects a download.

### Flows of option A

Table 10 lists the flows of a workstation run.

**Table 10.** Flows of option A

| When | Source | Destination | Port, protocol | Opened by | Purpose |
|---|---|---|---|---|---|
| Run | Browser on the workstation | `127.0.0.1` | 8501 (`--port`), HTTP and WebSocket | The planner | Pages, uploads, downloads |
| Run | App | `checkip.amazonaws.com` | 80 HTTP, then 443 HTTPS | Streamlit | Only on a WebSocket handshake from a foreign origin. No schedule data |
| Install, update | Workstation | The source repository on `github.com` | 443, HTTPS (git) | Administrator | Source tree. Whether an anonymous clone works is not established |
| Install, update | Workstation | `pypi.org`, `files.pythonhosted.org` | 443, HTTPS | `uv sync --locked` | The locked packages, checked against the sha256 hashes of `uv.lock` |
| Install | Workstation | uv's download source for a managed Python | Not established | uv | Only when no suitable Python is present: uv's behaviour |

### Flows of option B

Table 11 lists the flows of the local image.

**Table 11.** Flows of option B

| When | Source | Destination | Port, protocol | Opened by | Purpose |
|---|---|---|---|---|---|
| Run | Browser on the host | `127.0.0.1` of the host, then the container | 8501, HTTP and WebSocket | The planner | Pages, uploads, downloads |
| Run | Health check inside the container | `127.0.0.1` of the container | 8501, HTTP | Docker, every 30 s | `GET /_stcore/health` |
| Run, at each start | App container | `checkip.amazonaws.com` | 80 HTTP, then 443 HTTPS | Streamlit | Streamlit looks up the public address to print its `External URL` line. No schedule data. A failure changes nothing |
| Build | Docker host | `ghcr.io`, `gcr.io` | 443, HTTPS | `docker compose up -d --build` | The two base images |
| Build | Build container | Debian's archive, on the mirrors that the uv base image configures | Not established | `apt-get download` | The packages of `OS_FIXES` |
| Build | Build container | uv's download source for the managed CPython | Not established | `uv python install` | CPython 3.14 |
| Build | Build container | `pypi.org`, `files.pythonhosted.org` | 443, HTTPS | `uv sync --locked` | The locked packages |
| Build | Docker host | Docker Hub | 443, HTTPS | BuildKit | The `# syntax=docker/dockerfile:1.7` line names a frontend image. BuildKit's behaviour: not established |

### Flows of option C

Table 12 lists the flows of the remote stack.

**Table 12.** Flows of option C

| When | Source | Destination | Port, protocol | Opened by | Purpose |
|---|---|---|---|---|---|
| Run | Any browser on the Internet | Tailscale's public endpoint for `xerscope.<tailnet>.ts.net` | 443, HTTPS | The visitor | The published URL |
| Run | `tailscale` container | Tailscale's services | Not established by the files | tailscaled, through `egress` | Control plane and relays. The file's comment states that "the only outbound traffic is Tailscale's own" |
| Run | tailscaled | Caddy, `127.0.0.1:8080` of the shared namespace | 8080, HTTP | tailscaled | Requests relayed by Funnel |
| Run | Caddy | `app:8501` on `internal` | 8501, HTTP and WebSocket | Caddy | Authenticated requests |
| Run | Health check inside the app container | `127.0.0.1` of the container | 8501, HTTP | Docker, every 30 s | `GET /_stcore/health` |
| Run, at each start | App container | `checkip.amazonaws.com` | 80, then 443 | Streamlit | Attempted, and without a route: `internal` has no gateway |
| On demand | `lexicon-init` | None | None | None | `network_mode: none` |
| Install, update | Docker host | `ghcr.io` | 443, HTTPS | `docker compose pull` | The app and Caddy images. A login is needed while the packages are private |
| Install, update | Docker host | Docker Hub | 443, HTTPS | `docker compose pull`, `docker run` | `tailscale/tailscale:v1.104.7`, and the stock `caddy:2.11.9` when you hash a password with the documented command |
| Install | Administrator's browser | Tailscale's admin console | 443, HTTPS | Administrator | Tailnet policy and auth key. Third-party service, not described by the files |

Nothing listens on the host in option C: the file has no `ports:` key and no host network. The
certificate of the public name is obtained by Tailscale. The Synology deployment guide says that
Tailscale asks Let's Encrypt for it on the first request: not established.

### Flows of option D

Option D has no shipped flow matrix. The app's side is fixed: one inbound flow to port 8501 (HTTP
and WebSocket) from your reverse proxy, the health check on the container's loopback, and the
start-up request to `checkip.amazonaws.com`.

### Blockable flows and operation without Internet access

At run time, every outbound flow of the app can be blocked on every option. A request to
`checkip.amazonaws.com` fails without consequence: Streamlit ignores the error. In option C, the
outbound flows of the `tailscale` container are the only ones the stack needs, and the files do not
list them.

The app runs with no Internet access once its image is present. Building the image needs the
Internet (table 11), so option B runs offline once `xerscope:latest` exists on the host. Option C as
shipped does not run offline: its only way in is Tailscale Funnel.

## Accounts, authentication, sessions and secrets

This section lists every account, system user, secret and setting of the shipped files.

### Accounts and system users

Table 13 lists the accounts. The app exposes no administration interface and the `Caddyfile` sets
`admin off`: administration is access to the host, that is, to the Docker service, the files of the
deployment and the exports folder.

**Table 13.** Accounts and system users

| Account | Where | Rights | Notes |
|---|---|---|---|
| Application accounts | None | None | The app has no login, no role and no user list |
| Shared login of option C | `XERSCOPE_USER` and `XERSCOPE_PASSWORD_HASH`, read by Caddy's `basic_auth` | Every page of the app | One login for all readers |
| App container user | `USER nonroot` (65532) in the image; `user: "${XERSCOPE_UID:-65532}:${XERSCOPE_GID:-65532}"` in option C | Reads the exports folder; writes `suggested/`; `lexicon-init` also writes `generated/` | The exports folder must be readable by that uid |
| `caddy` container user | No `user:` key | The image's default user, with `NET_BIND_SERVICE` as its only capability | Root in the stock image: not established |
| `tailscale` container user | No `user:` key | The image's default user, with no capability | Root according to the file's comment: not established |
| Host account that runs Docker | Your host | Docker's own | Left to the host |
| Tailnet administrator | Tailscale's admin console | Policy, keys, nodes | Third-party account, option C only |
| Supplier account | None | None | The supplier needs no remote access and the shipped files open none |

### Authentication and sessions

Options A and B have no authentication. In option C, the browser sends the login and the password
with each request (HTTP basic authentication), and Caddy's `basic_auth` checks the password against
a bcrypt hash. Caddy's configuration holds the hash, not the password. A request without the
password receives 401: the CI job `deploy` asserts it. What a wrong password receives and whether
the stored hash is salted are Caddy's behaviour: not established. The documented hash command uses
`--algorithm bcrypt --bcrypt-cost 10`. Nothing in the files enforces a password length or
composition. ANSSI-PG-078 distinguishes memory-hard derivation functions (R29) from iterative ones
(R29-). The text names scrypt and Argon2 for the first and PBKDF2 for the second; it does not name
bcrypt.

The rate limit is 300 requests per minute per client address (`events 300`, `window 1m`,
`ipv6_prefix 64`), applied before the password check, inside the prefix only. The 404 answers
outside the prefix are not limited. A client over the limit receives 429 with `Retry-After`. There
is no lock-out and no delay after wrong passwords. The shipped files provide no multi-factor
authentication and no connection to an identity provider.

The app has no session timeout, no idle timeout, no log-out and no audit trail, and HTTP basic
authentication has no log-out either. What a password change does to sessions that are already open
is not established. Table 14 lists the browser-side protections and where each is set.

**Table 14.** Browser-side protections

| Protection | Value | Set by |
|---|---|---|
| XSRF protection | `enableXsrfProtection = true`, `enableCORS = true` | Packaged Streamlit settings, every option |
| XSRF cookie `_streamlit_xsrf` | `Path=/`, `SameSite=Lax`, no `HttpOnly` (the page's script reads it); `Secure` appended by `header >Set-Cookie (.*) "$1; Secure"` | Streamlit 1.67.0; `deploy/Caddyfile`, option C |
| Framing and content | `Content-Security-Policy "frame-ancestors 'self'; object-src 'none'; base-uri 'none'"` | `deploy/Caddyfile` |
| HSTS | `Strict-Transport-Security "max-age=31536000; includeSubDomains"` | `deploy/Caddyfile` |
| Other headers | `Referrer-Policy no-referrer`, `X-Content-Type-Options nosniff`, `Permissions-Policy "camera=(), microphone=(), geolocation=()"`, `header -Server`, `Connection close` except on a WebSocket handshake | `deploy/Caddyfile` |
| Caching | `Cache-Control no-store` on `/`, `/index.html` and `/media/*` | `deploy/Caddyfile` |
| Table export | `disableDataExport = true`, `toolbarMode = "viewer"` | Packaged Streamlit settings |
| Error details | `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS: none` | `deploy/compose.yaml` |

No `X-Frame-Options` header is set. The headers of `deploy/Caddyfile` do not exist in options A and
B, where the app answers directly and names itself in a `server: uvicorn` header.

### Secrets

No default credential is shipped. [`deploy/.env.example`](../deploy/.env.example) holds placeholders
only, and Compose stops when one of the three required values is missing. Table 15 lists the
secrets.

**Table 15.** Secrets

| Secret | Placeholder in `.env.example` | Where it lives | Notes |
|---|---|---|---|
| `TS_AUTHKEY` | `tskey-auth-...` | `deploy/.env`; environment of `tailscale` | Read on the first start only (`TS_AUTH_ONCE: "true"`). Defaults to empty |
| `XERSCOPE_USER` | `<login>` | `deploy/.env`; environment of `caddy` | Required |
| `XERSCOPE_PASSWORD_HASH` | `'$2a$10$...'` | `deploy/.env`; environment of `caddy` | Required. Without the single quotes, Compose reads the `$` signs as variables and keeps `$2a$10` only |
| `XERSCOPE_PATH` | `<random>` | `deploy/.env`; environment of `caddy` | Required. The secret URL prefix, no slash. `openssl rand -hex 12` prints 24 characters. Nothing validates the value, and it is also used as a regular expression in the log filters |
| Node identity | None | Volume `tailscale-state` | Where the TLS certificate and its key live is not established |
| Anonymisation key | None | Session memory, `secrets.token_bytes(32)` | One per session |

The file `deploy/.env` holds those values in clear, and `.gitignore` keeps it out of git. Its
protection is the permissions of the folder: left to the host. Caddy reads its three values when its
container is created. The build context of the app image is `pyproject.toml`, `uv.lock`, `README.md`
and `src/` only, so the image holds no export and no secret.

### Settings read by the app

Table 16 lists the environment variables that the app's code reads.

**Table 16.** Environment variables that the app reads

| Variable | Default | Effect |
|---|---|---|
| `XERSCOPE_DATA` | Unset; `/data` in the image | Folder of the `.xer` files. Set by `xerscope app --data` |
| `XERSCOPE_BASELINE` | Unset | A separate baseline file. Set by `--baseline`. A commented line in both Compose files |
| `XERSCOPE_STANDARDS` | Unset; `/data` in option C | Folder of your own standards (`*.toml`), read at each page draw. Set by `--standards` |
| `XERSCOPE_FOLDER_ROOT` | Unset | Root under which a typed folder is read; else `XERSCOPE_DATA`, else the home directory |
| `XERSCOPE_DATA_LOCKED` | Unset; `"true"` in option C | With `1`, `true` or `yes` (any case): no folder field, no `.xer` or baseline upload, no Debug page |
| `XERSCOPE_DEBUG_PAGE` | Unset | With `1`, `true` or `yes`: the Debug page on a locked instance, "to whoever holds the URL". Its runtime block stays hidden |
| `XERSCOPE_LOAD_WORKERS` | One process per core, at most 2; `1` in option C | Number of reading processes. A value greater than 2 reads as 2 |
| `XERSCOPE_LEXICON` | Unset; `/lexicon` in option C | Lexicon folder of the **Ask the schedule** field. Unset: the app writes no file at all |
| `XERSCOPE_SYNC_LOAD`, `XERSCOPE_STRICT_READINGS` | Unset | Used by the tests only |

The command `xerscope app` also takes `--host` (default `localhost`; its help says that `0.0.0.0`
"exposes your schedules to the network") and `--port` (default 8501). The packaged Streamlit
settings add `maxUploadSize = 200` (MB per file), which option C lowers with
`STREAMLIT_SERVER_MAX_UPLOAD_SIZE: "1"` and `STREAMLIT_SERVER_MAX_WIDGET_STATE_SIZE: "1"`. A further
variable, `XERSCOPE_MPXJ_CPM_JAR`, serves the `crosscheck` command only, which cannot run in the
image.

### Settings of option C

Table 17 lists the 13 variables that `deploy/compose.yaml` reads from `deploy/.env`.

**Table 17.** Variables that `deploy/compose.yaml` reads from `deploy/.env`

| Variable | Default | Effect |
|---|---|---|
| `TS_AUTHKEY`, `XERSCOPE_USER`, `XERSCOPE_PASSWORD_HASH`, `XERSCOPE_PATH` | See table 15 | Secrets |
| `XERSCOPE_EXPORTS` | `../exports` | Host folder mounted read-only on `/data` |
| `XERSCOPE_UID`, `XERSCOPE_GID` | `65532` | Account of the `xerscope` and `lexicon-init` containers, and owner of the app's tmpfs |
| `XERSCOPE_IMAGE` | `ghcr.io/xerscope/xerscope:latest` | Image of `xerscope` and `lexicon-init` |
| `XERSCOPE_CADDY_IMAGE` | `ghcr.io/xerscope/xerscope-caddy:latest` | Image of `caddy` |
| `XERSCOPE_MEM_LIMIT` | `2g` | Memory limit of `xerscope` and of `lexicon-init` |
| `XERSCOPE_LOAD_WORKERS` | `1` | See table 16 |
| `XERSCOPE_LEXICON_DIR` | `/docker/xerscope/lexicon` | Host folder mounted on `/lexicon`. The mounts are unconditional, although `.env.example` calls the line optional |
| `XERSCOPE_DEBUG_PAGE` | Empty | See table 16 |

Three settings are not reachable from `.env`: a baseline file named by `XERSCOPE_BASELINE` (a
commented line of `deploy/compose.yaml`), the node's `hostname: xerscope`, and the rate limit
(`events` in `deploy/Caddyfile`). The file also fixes `HOME: /home/nonroot` for the app, and for
`tailscale` it sets `TS_USERSPACE: "true"`, `TS_STATE_DIR: /var/lib/tailscale`,
`TS_SERVE_CONFIG: /config/serve.json`, `TS_EXTRA_ARGS: --advertise-tags=tag:xerscope` and
`TS_NO_LOGS_NO_SUPPORT: "true"`, and no proxy variable.

## Container hardening against ANSSI-FT-082

This section compares the two Compose files with "Recommandations de sécurité relatives aux
déploiements de conteneur Docker" (ANSSI-FT-082, Version 1.0, 23/09/2020), recommendation by
recommendation. The document states that "ces recommandations n'ont pas de caractère normatif". It
was written against Docker "18.09.3", and it does not mention Docker Compose: the Compose keys named
here are the counterparts of the `docker run` options it prints.

### Recommendation by recommendation

Table 18 gives the position of each file. The titles are the document's.

**Table 18.** Position of the two Compose files against ANSSI-FT-082

| Recommendation | `compose.yaml` (option B) | `deploy/compose.yaml` (option C) |
|---|---|---|
| R1 "Isoler les systèmes sensibles de fichiers de l'hôte" | Met: no `privileged:` key; the only mount is `./exports:/data:ro` | Met: no `privileged:` key; no mount of `/`, `/dev`, `/proc`, `/sys` or the Docker socket (table 8) |
| R2 "Restreindre l'accès aux périphériques de l'hôte" | Not applicable: no `devices:` key | Not applicable: no `devices:` key; `TS_USERSPACE: "true"` needs no TUN device |
| R3 "Interdire la connexion du conteneur au réseau bridge docker0" | Left to the host (Docker service). The service joins the project network that Compose creates | Left to the host. Every service names its networks, `network_mode: service:tailscale` or `network_mode: none` |
| R4 "Isoler l'interface réseau de l'hôte" | Met: no `network_mode: host` | Met: no host network (pinned by `tests/test_docker.py`) |
| R5 "Créer un réseau dédié pour chaque connexion" | Met by Compose's default: no `networks:` key, so one project network serves the one service and its one published port | Partly met: `egress` and `internal` are dedicated, but `caddy` shares the network namespace of `tailscale`, so those two are not separated |
| R6 "Dédier des namespaces PID, IPC et UTS pour chaque conteneur" | Met: no `pid:`, `ipc:` or `uts:` key | Met: no `pid:`, `ipc:` or `uts:` key |
| R7 "Dédier un namespace USER ID pour chaque conteneur" | Left to the host (Docker service) | Left to the host; the uid that reads the exports folder changes under a remap |
| R7+ "Restreindre la création des Namespace USER ID à l'utilisateur root" | Left to the host (kernel setting) | Left to the host |
| R7- "Restreindre le partage du Namespace USER ID de l'hôte" | Not applicable: no `userns_mode:` key | Not applicable: no `userns_mode:` key |
| R8 "Interdire l'utilisation des capabilities" | Met: `cap_drop: [ALL]` | Met for `tailscale`, `xerscope` and `lexicon-init`: `cap_drop: [ALL]`. Not met for `caddy`: see R8- |
| R8- "Limiter l'utilisation des capabilities" | Not applicable | Used by `caddy`: `cap_drop: [ALL]` and `cap_add: [NET_BIND_SERVICE]`. The file's reason: the binary carries that file capability and the kernel refuses to run it with an empty bounding set. Caddy listens on 8080. The document's list of 19 "sensibles" capabilities does not hold `CAP_NET_BIND_SERVICE`; of that capability it says that the application "doit être configurée sur des ports non priviligiés", which Caddy is (8080) |
| R9 "Dédier les Control groups pour chaque conteneur" | Met: no `cgroup_parent:` key | Met: no `cgroup_parent:` key |
| R10 "Limiter l'utilisation de la mémoire de l'hôte pour chaque conteneur" | Not met: no `mem_limit` | Partly met: `mem_limit` on the four services (`256m`, `256m`, `${XERSCOPE_MEM_LIMIT:-2g}` twice); no swap limit (`memswap_limit`) |
| R11 "Limiter l'utilisation du CPU de l'hôte pour chaque conteneur" | Not met: no CPU limit | Not met: no CPU limit. The file's reason: Docker refuses to create a container with a quota on a kernel without CFS bandwidth control |
| R12 "Restreindre en lecture le système de fichiers racine de chaque conteneur" | Met: `read_only: true` | Met: `read_only: true` on the four services |
| R12- "Limiter l'écriture de l'espace de stockage de chaque conteneur" | Not applicable: R12 is met | Not applicable |
| R12- - "Limiter l'écriture de l'espace de stockage de l'ensemble des conteneurs" | Not applicable | Not applicable |
| R13 "Créer un système de stockage pour les données non persistantes" | Partly met: tmpfs on `/tmp` (`mode=1777`) and `/home/nonroot` (`mode=700`), owned by 65532, with no size | Partly met: seven tmpfs, each with a size. A mode is set on the two of `xerscope` only |
| R14 "Créer un système de stockage pour les données persistantes ou partagées" | Met for the read-only part: `./exports:/data:ro`. No writable mount | Partly met: read-only mounts carry `:ro`. The writable ones (`tailscale-state`, `generated/`, `suggested/`) carry no size limit. The app stops recording suggestions at 256 KB |
| R15 "Restreindre l'accès aux répertoires et aux fichiers sensibles" | Met by the mount list. File permissions: left to the host | Met by the mount list and by the uid of `XERSCOPE_UID`. Permissions on `deploy/.env`, the exports and the lexicon folder: left to the host |
| R16 "Exporter les journaux avec Docker" | Left to the host (Docker service). No `logging:` key | Left to the host. No `logging:` key, by choice stated in the file's header |
| R16- "Exporter les journaux depuis l'intérieur du conteneur" | Not met: no exporter in the image | Not met: no exporter in any container |

The two Compose files also set `security_opt: ["no-new-privileges:true"]` on every service, and the
app image runs as a non-root user. ANSSI-FT-082 does not mention those two points, process limits or
health checks, and it leaves images out of its scope, so the table does not rate them.

The hardening of `compose.yaml` and of `deploy/compose.yaml` applies to containers started by
Compose. A plain `docker run` of the image has none of it.

### Resource limits and storage per service

Table 19 lists the limits that each service carries.

**Table 19.** Resource limits and storage per service

| Service | Memory | Processes | CPU | tmpfs | Restart | Health check |
|---|---|---|---|---|---|---|
| `xerscope` (option B) | None | None | None | `/tmp`, `/home/nonroot`, no size | `unless-stopped` | The image's |
| `tailscale` | `mem_limit: 256m` | `pids_limit: 128` | None | `/tmp:size=16m`, `/var/run/tailscale:size=1m` | `unless-stopped` | None |
| `caddy` | `mem_limit: 256m` | `pids_limit: 128` | None | `/tmp`, `/data`, `/config`, `size=16m` each | `unless-stopped` | None |
| `xerscope` (option C) | `${XERSCOPE_MEM_LIMIT:-2g}` | `pids_limit: 256` | None | `/tmp` (`mode=1777,size=256m`), `/home/nonroot` (`mode=700,size=16m`) | `unless-stopped` | The image's |
| `lexicon-init` | `${XERSCOPE_MEM_LIMIT:-2g}` | `pids_limit: 64` | None | None | `"no"` | Disabled |

The image's health check is
`HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3`, a request to
`http://127.0.0.1:8501/_stcore/health` made with the image's Python. The service `caddy` waits for
`tailscale` to be started, not healthy (`depends_on: [tailscale]`).

The header of `deploy/compose.yaml` states that on a kernel without the memory and process cgroups,
Docker drops the limit with a warning and the stack still starts. Its comments give one sizing
figure, about 1 GB of memory for a parsed 40 MB export. The project's tests do not measure that
figure. The number of simultaneous sessions that fit under the limit is not established. Each
session holds its own parsed files. The app is one container with no replica: a restart empties the
sessions' memory, and planners read their files again.

### What stays with the host and the Docker service

ANSSI-FT-082 leaves two subjects out of its scope: "le Docker daemon et la gestion des images Docker
sont hors périmètre de l'étude." It also names residual risks that no Compose file removes. The
first is the daemon's own rights: "les processus Docker Community Edition (CE) s'exécutent avec les
droits de l'utilisateur root (UID=0)." The second is the host: "Un durcissement du système et des
services Docker conformément au guide « Recommandations de configuration d'un système GNU/Linux »
[1] publié par l'ANSSI doit être réalisé". That guide, ANSSI-BP-028, defines four levels (minimal,
intermédiaire, renforcé, élevé), and the level is your choice.

The following settings belong to the host: the default bridge (R3), user namespace remapping (R7,
R7+), the log driver (R16), and security modules. Neither Compose file sets a seccomp, AppArmor or
SELinux option, so the Docker service's defaults apply. The files state no minimum Docker or Compose
version. The `Dockerfile` needs BuildKit.

## Origin and integrity of images and dependencies

This section states where each artefact comes from and what can be verified. ANSSI-FT-082 does not
cover images. The nearest rule among the cited documents is general: "Seuls les dépôts internes à
l'organisation ou officiels (de la distribution ou de d'un éditeur) doivent être utilisés."
(ANSSI-BP-028, R59).

### Registries and tags

The workflow [`image.yml`](../.github/workflows/image.yml) publishes two images,
`ghcr.io/xerscope/xerscope` and `ghcr.io/xerscope/xerscope-caddy`. It runs only as the last job
(`publish`) of the `tests` workflow, on a push to `main` or of a `v*` tag. It runs only when eight
jobs succeeded: `lint`, `oracle-report`, `test`, `fitness`, `audit`, `crosscheck`, `container` and
`deploy`. Table 20 lists the tag rules.

**Table 20.** Tag rules of the published images

| Tag | Rule | Notes |
|---|---|---|
| `latest` | `type=raw,value=latest,enable={{is_default_branch}}` | Moves with `main`. Whether a tag push also moves it is not established |
| `X.Y.Z` | `type=semver,pattern={{version}}` on a git tag `vX.Y.Z` | No such tag exists: no release has been cut. Nothing checks that the tag is on `main` |
| `sha-<short>` | `type=sha` | Every build |

A package on ghcr.io is private when first published, and the repository's own daily scan logs in to
pull the two images. The visibility of the packages is a registry setting that the files do not
show. A copy goes to Docker Hub only when the workflow's secret `DOCKERHUB_TOKEN` and variable
`DOCKERHUB_IMAGE_OWNER` are set.

In `deploy/compose.yaml`, the references of the app and Caddy images are the variables
`XERSCOPE_IMAGE` and `XERSCOPE_CADDY_IMAGE`, so a reference to an internal registry needs no edit of
the file. The Tailscale reference is a literal on the `image:` line of the `tailscale` service.
`deploy/.env.example` documents the pinned form `tag@sha256:<digest>`. For the steps, see
[Import the images into an internal registry](#import-the-images-into-an-internal-registry) in this
guide.

### Provenance, SBOM and attestation

The build step sets `provenance: mode=max` and `sbom: true`. A second step,
`actions/attest-build-provenance`, attests the pushed digest with
`subject-name: ghcr.io/xerscope/<image>` and `push-to-registry: true`. The images carry no cosign
signature: no workflow has a cosign step. What the SBOM lists is not established.

The verification commands are recorded in the workflow and in the Synology deployment guide. No job
of the project runs them. The first verifies the attestation; the two others print the provenance
and the SBOM:

```bash
gh attestation verify oci://ghcr.io/xerscope/IMAGE_NAME@sha256:IMAGE_DIGEST --owner Xerscope
docker buildx imagetools inspect ghcr.io/xerscope/IMAGE_NAME@sha256:IMAGE_DIGEST --format '{{json .Provenance}}'
docker buildx imagetools inspect ghcr.io/xerscope/IMAGE_NAME@sha256:IMAGE_DIGEST --format '{{json .SBOM}}'
```

`IMAGE_NAME` is `xerscope` or `xerscope-caddy`, and `IMAGE_DIGEST` is the digest of the image, 64
hexadecimal characters. Whether the attestation verifies against a Docker Hub copy is not
established. The Tailscale image has no attestation from this project, and its tag can be moved.

### Sources that a build draws on

Table 21 lists the upstream sources of a build from source and how each is pinned.

**Table 21.** Upstream sources of a build

| Source | Used for | Pinning |
|---|---|---|
| `ghcr.io/astral-sh/uv:0.13.8-trixie-slim` | Build stages of the app image | Tag and digest |
| `gcr.io/distroless/cc-debian13:nonroot` | Runtime stage of the app image | Tag and digest |
| Debian archive | `OS_FIXES` (`zlib1g`) | `package=version`; the `Dockerfile` comment states that apt verifies the archive signature. A second comment states that the distroless base at its present digest ships the same fixed version, which makes the entry redundant |
| uv's managed CPython | The interpreter | `PYTHON_VERSION=3.14`: the minor version only |
| PyPI | The Python dependencies | Exact versions and sha256 hashes in `uv.lock`; both `uv sync` calls use `--locked` |
| `caddy:2.11.9-builder`, `caddy:2.11.9` | Caddy image | Tag and digest |
| Go modules | `caddy-ratelimit`, `golang.org/x/net` | One commit and one version. The build fails unless the binary records the expected versions and lists `http.handlers.rate_limit` |

The patch level of CPython is not pinned, so two builds of the same commit can differ, and the
reproducibility of the images is not established. The local image is built by `build: .` in
`compose.yaml`, which offers no setting to use a published image instead.

### Scans and updates in CI

Table 22 lists the checks that run in the supplier's pipeline. They do not cover your deployment.

**Table 22.** Checks in the supplier's pipeline

| Check | Scope | When | Blocking |
|---|---|---|---|
| Trivy (`.github/trivy/scan.sh`) | App image built from the commit | Job `container` | A HIGH or CRITICAL finding that has a fix fails the job and blocks the publication. A finding without a fix is listed only |
| Trivy | Caddy image and the Tailscale image | Job `deploy`, every event | Same rule. Two dated exceptions for the Tailscale image: CVE-2026-78661 (`golang.org/x/net` v0.60.0), `expired_at: 2026-12-09`, and CVE-2026-124709 (OpenSSL, `libssl3` and `libcrypto3` 3.5.9-r0), `expired_at: 2026-12-17`. Before the scan, the job checks that the three Tailscale binaries hold no `golang.org/x/net/html` code and load no shared library |
| Trivy | The two published `latest` images | [`scanner.yml`](../.github/workflows/scanner.yml), every day at 04:41 UTC | Does not gate a publication |
| `pip-audit@2.10.1` (OSV and PyPI), `bandit@1.9.4 -r src -ll` | Locked dependencies, source | Job `audit`, every run of `tests` | Blocks the publication |
| CodeQL, `security-and-quality` queries | Python sources | Push and pull request to `main`, Mondays at 05:17 UTC | Separate workflow |
| Dependabot | Python, Actions, Docker, Compose | Weekly (daily for the Trivy image), seven-day cooldown | Proposes updates |

Every action of the workflows is pinned by commit SHA. The `caddy-ratelimit` commit is bumped by
hand: Dependabot does not read it. Nothing in either stack updates itself.

### Supplier commitments

[`SECURITY.md`](../SECURITY.md) states three things. The supported versions are "the `main` branch
and the latest published image". A vulnerability is reported through GitHub's private vulnerability
reporting on the repository. The reporter can "Expect an acknowledgement within a week." It defines
no delay for a fix, no channel that announces a fix, and no end-of-support date. Those commitments
are not provided, and the repository holds no document that can be annexed to a contract as a
security assurance plan.

## Procedures

Each procedure names its option. Run the Docker commands from the folder that holds the Compose
file. For the meaning of a variable, see [Settings read by the app](#settings-read-by-the-app) and
[Settings of option C](#settings-of-option-c) in this guide.

### Install and start option A

To run the app on a workstation, you need uv and a copy of the source tree.

1. In the root of the source tree, install the locked dependencies:

   ```bash
   uv sync --locked
   ```

2. Start the app on your exports folder:

   ```bash
   uv run xerscope app --data EXPORTS_FOLDER
   ```

   Replace `EXPORTS_FOLDER` with the folder that holds the `.xer` files. The terminal prints
   `You can now view your Streamlit app in your browser.` and `URL: http://localhost:8501`.
3. Open `http://localhost:8501` in a browser on the same workstation. The sidebar shows
   **Files · none read** until a planner picks the files.

### Install and start option B

To run the local image, you need Docker with Compose and BuildKit, and Internet access for the
build.

1. In the root of the source tree, create the exports folder:

   ```bash
   mkdir -p exports
   ```

2. Copy your `.xer` files into `exports/`. The files must be readable by uid 65532.
3. Build the image and start the container:

   ```bash
   docker compose up -d --build
   ```

   Compose builds `xerscope:latest` and starts the service `xerscope`.
4. Open `http://localhost:8501` in a browser on the host.

### Install and start option C

To run the remote stack, you need Docker with Compose, a tailnet whose policy grants Funnel to
`tag:xerscope`, an auth key with that tag, and access to the three images. The policy and the key
are created in Tailscale's admin console: the Synology deployment guide describes them.

1. In the `deploy` folder, create the settings file:

   ```bash
   cp .env.example .env
   ```

2. In `.env`, fill in `TS_AUTHKEY`, `XERSCOPE_USER`, `XERSCOPE_PASSWORD_HASH`, `XERSCOPE_PATH` and
   `XERSCOPE_EXPORTS`. The comments of `.env.example` give the command that generates the hash and
   the command that generates the prefix. Keep the single quotes around the hash.
3. In `.env`, set `XERSCOPE_LEXICON_DIR` to an existing folder that holds `generated/`, `curated/`
   and `suggested/`, writable by the app's account. The mounts are unconditional, and what Docker
   does with a missing folder is not established.
4. Check that the settings are complete:

   ```bash
   docker compose config --quiet
   ```

   A missing required value stops the command with a message such as
   `required variable XERSCOPE_USER is missing a value: login for the password prompt`.
5. Start the stack:

   ```bash
   docker compose up -d
   ```

6. Read the state of Funnel:

   ```bash
   docker compose exec tailscale tailscale funnel status
   ```

7. Open `https://xerscope.<tailnet>.ts.net/<XERSCOPE_PATH>/`, with the trailing slash. The browser
   asks for the login and the password.

### Stop the app or change a setting

To stop option B or C, run `docker compose down`. In option C the volume `tailscale-state` stays, so
the node keeps its identity. To stop option A, press `Ctrl+C` in the terminal: Streamlit prints
`Stopping...`, then Python prints a traceback that ends with `KeyboardInterrupt`.

To change a setting or a secret of option C, edit `deploy/.env`, then run `docker compose up -d`
again. Compose recreates the services whose configuration changed. After a change of
`XERSCOPE_PATH`, the old URL answers 404.

### Check the health

To check option A or B, request the health route from the host:

```bash
curl -fsS http://127.0.0.1:8501/_stcore/health
```

The command prints `ok`. In option C no port is published: run `docker compose ps` and read the
health state of the `xerscope` service. The services `caddy` and `tailscale` have no health check.

### Update and roll back

Nothing updates itself. To update option A, update the source tree, run `uv sync --locked` and
restart the app. To update option B, update the source tree and run `docker compose up -d --build`
again. To update option C, follow these steps in the `deploy` folder.

1. Copy the lines `XERSCOPE_IMAGE` and `XERSCOPE_CADDY_IMAGE` of `.env` to a safe place. They are
   your way back.
2. In `.env`, set both lines to the build to run, pinned by digest, in the form
   `ghcr.io/xerscope/xerscope:IMAGE_TAG@sha256:IMAGE_DIGEST`.
3. If the update changes `Caddyfile`, `compose.yaml` or `tailscale-serve.json`, copy the changed
   files over yours, and add to `.env` any variable that `.env.example` gained.
4. Pull the images:

   ```bash
   docker compose pull
   ```

5. Recreate the containers:

   ```bash
   docker compose up -d
   ```

   The node state stays in its volume and the URL does not change.

To roll back, restore the two lines of step 1 and run `docker compose up -d` again. To change the
Tailscale version, edit the `image:` line of the `tailscale` service.

### Import the images into an internal registry

If your host must not pull from public registries, copy the images from a machine that can. These
are standard Docker commands.

1. On the machine with access, copy the app image to your registry:

   ```bash
   docker pull ghcr.io/xerscope/xerscope@sha256:IMAGE_DIGEST
   docker tag ghcr.io/xerscope/xerscope@sha256:IMAGE_DIGEST REGISTRY_HOST/xerscope/xerscope:IMAGE_TAG
   docker push REGISTRY_HOST/xerscope/xerscope:IMAGE_TAG
   ```

   Replace the following:

   - `IMAGE_DIGEST`: the digest of the image that you verified
   - `REGISTRY_HOST`: the host name of your registry
   - `IMAGE_TAG`: the tag that you give the copy

2. Repeat step 1 for `ghcr.io/xerscope/xerscope-caddy`, and for `tailscale/tailscale:v1.104.7`,
   which is referenced by tag.
3. In `deploy/.env`, set `XERSCOPE_IMAGE` and `XERSCOPE_CADDY_IMAGE` to the references in your
   registry.
4. In `deploy/compose.yaml`, replace the `image:` value of the `tailscale` service with the
   reference in your registry.

If the host reaches no registry, write each image to a file with `docker save`, carry the file, and
load it with `docker load`.

### Back up and restore

The app stores no schedule: for options A and B, back up your exports folder. For option C, follow
these steps.

1. Copy `deploy/.env` to a place that protects secrets.
2. Copy `Caddyfile`, `compose.yaml` and `tailscale-serve.json` if you changed them.
3. Copy the lexicon folder, and back up the exports folder with your own tools.

To restore, put the files and the folders back where `.env` points, then start the stack. If the
volume `tailscale-state` is lost, the stack starts as another node: set `TS_AUTHKEY` to a fresh key
first.

### Remove the application

To remove option C and its data, follow these steps in the `deploy` folder.

1. Stop the stack and delete its volume:

   ```bash
   docker compose down --volumes
   ```

   Docker removes the containers, the two networks and the volume `tailscale-state`.
2. Delete `deploy/.env`, which holds the secrets.
3. Delete the lexicon folder. Its files hold words taken from the exports and the corrections that
   visitors clicked.
4. Remove the three images from the host with `docker image rm`.
5. In Tailscale's admin console, remove the node and revoke the key.
6. Delete or archive the exports folder according to your own rules.

To remove option B, run `docker compose down`, remove the image `xerscope:latest`, and handle the
`exports` folder. To remove option A, delete the source tree with its `.venv` folder.

## Logging

This section states what each component writes. No shipped file sets a retention period.

### What each component writes

Table 23 lists the log output per component. Every container writes to its standard output, and the
Docker service keeps the lines with its default driver.

**Table 23.** Log output per component

| Component | Lines | Fields and filters |
|---|---|---|
| App (xerscope's own code) | None | The app's code has no logging call |
| App (Streamlit) | Start banner (`You can now view your Streamlit app in your browser.` and the URL lines), warnings, tracebacks of uncaught errors | Whether a traceback quotes a file name or a value is not established. In option C, tracebacks go to the log and not to the page |
| Caddy, access log | One line per request, `output stdout`, `format filter` wrapping `console` | Path, status and visitor IP are kept. The prefix is replaced by `<prefix>` in the request URI, the `Referer` and the redirect `Location`. `Sec-Websocket-Protocol` (Streamlit's XSRF token and session id) and `Content-Disposition` (a download's file name) are deleted |
| Caddy, default logger | Proxy errors, JSON | The prefix is replaced in the request URI and the `Referer`; `Sec-Websocket-Protocol` is deleted |
| tailscaled | Its own lines | `TS_NO_LOGS_NO_SUPPORT: "true"` is set so that no diagnostic log is sent to Tailscale. Content not established |
| `lexicon-init` | Counts, source column names, and the folder path in one error message | No export name and no word. `generated/report.txt` names the files it skipped |
| Suggestions of the **Ask the schedule** field | None | Nothing about a suggestion is printed or logged |

The CI job `deploy` fails when the secret prefix reaches Caddy's log. The `Caddyfile` has no filter
for the `Authorization` and `Cookie` request headers: what Caddy writes for them is Caddy's default
behaviour: not established.

### What is not logged or configured

No component records who did what. The app writes no event for a file read, a page opened or a
download. Caddy's access log shows the status of each request, 401 included, and cannot tell two
readers apart because the login is shared. Options A and B have no access log at all.

Neither the `Dockerfile` nor the Compose files set `TZ` or a locale. The timestamps that xerscope's
own code writes are in UTC. The time source of the timestamps is not provided: no shipped file
configures a clock or its synchronisation, which is left to the host. Neither Compose file has a
`logging:` key, so the size and the rotation of the logs are the Docker service's defaults. Export
to another machine and the retention period are left to the host.

## Known gaps and residual risks

The preceding sections state each limit where it applies. Table 24 gathers them, because an
accreditation file needs the residual risks in one place. The last column is an input for your
action plan, not a commitment of the supplier.

**Table 24.** Known gaps and residual risks

| Gap | Consequence | What the host can do |
|---|---|---|
| Option D is not shipped and not tested: the project's tests pin the Funnel layout and do not cover an adapted file | An internal deployment behind your proxy is your own integration | Build it from the reusable parts and test it |
| No user management: one shared login in option C, none in A and B | No reader is told apart; none can be revoked alone | Authenticate in front of the app with your identity provider |
| No session timeout, no log-out, no lock-out, no multi-factor authentication; the effect of a password change on open sessions is not established | A session lasts as long as the browser keeps it | Enforce them in your own proxy |
| No audit trail; the app logs nothing | No record of who read or downloaded what | Log at your proxy; export container logs |
| No test of the project exercises Funnel, the tailnet policy or the certificate | The entry point of option C is proven on your tailnet only | Test the published URL after each change of the stack |
| Option C is an Internet entry point relayed by a third party | The URL is reachable from any network, and the relay is outside your control | Rate the exposure in your risk analysis; compare with an internal entry point |
| Outbound hosts and ports of the `tailscale` container are not established; no proxy variable is set | The flow matrix of option C cannot be closed from the files | Obtain them from Tailscale's documentation and test |
| TLS versions and suites of option C are Tailscale's: not established. No TLS between tailscaled, Caddy and the app | In-transit protection inside the host relies on container networks | Terminate TLS on equipment that you control |
| `caddy` shares the network namespace of `tailscale` | Those two containers are not separated at network level | Accept it, or redesign in option D |
| The Tailscale image is pinned by tag; `tailscale` and `caddy` run as their image's default user | A moved tag changes the image; root inside two containers, with no capability or one | Pin a digest in your copy; rely on host hardening |
| Two accepted findings in the Tailscale image: CVE-2026-78661, exception ending 2026-12-09, and CVE-2026-124709, exception ending 2026-12-17 | Two known vulnerabilities stay until a Tailscale release carries their fixes | Follow the exception file `deploy/tailscale.trivyignore.yaml` |
| Findings without a fix are listed, not blocking | An image can be published with known unfixed findings | Scan the images yourself before use |
| No release exists; `latest` moves with `main`; package visibility not established | No stable version to name in a contract or a file | Pin by digest; ask the supplier for a tagged release |
| No image signature; no job of the project runs the verification commands; SBOM content not established | Integrity rests on digests and on the attestation | Run the verification commands; record the results |
| One architecture, and no job of the project builds for another; reproducibility not established; CPython patch level not pinned | A rebuild can differ from the published image | Build from source in your own pipeline if you require it |
| No CPU limit and no swap limit; no limit at all in option B | One container can use the host's CPU; option B can use its memory | Add limits in your copy of the Compose file |
| No test of the project measures the sizing figures; capacity per session not established | The default `2g` can be too small or too large | Measure with your own exports |
| Option B is not locked; `/_stcore/metrics` answers on a direct instance | Anyone on the host's loopback reads everything | Keep it for one-person use |
| **Anonymous exports** is not enforced | A visitor can download plain tables | Treat downloads as sensitive as the exports |
| An upload over 1 MB passes through a temporary file (Streamlit's upload handler, as its source reads) | In option A, the file transits the system's temporary directory | Prefer the folder to the upload |
| Streamlit requests `checkip.amazonaws.com` at each container start, and on a WebSocket handshake from a foreign origin | One outbound attempt at each start in options B and D, and on such a handshake in option A | Block it; the app runs without it |
| Browser-side requests of Streamlit's JavaScript are not established | An external request from the page cannot be ruled out from the files | Watch the page in a browser behind your proxy |
| Caddy's handling of `Authorization` and `Cookie` in its log is not established; tracebacks can quote values | Logs can hold more than the files show | Read a sample of the logs before you export them |
| No `logging:` key, no exporter, no `TZ`, no time source configured | Logs stay on the host with the service's defaults, dated by the host's clock | Configure the Docker service's log driver and the clock synchronisation of the host |
| No test of the project runs with `--userns-remap`; no minimum Docker or Compose version stated | Host hardening can break the stack | Test on your hardened host |
| No test of the project runs the Docker procedures of this guide from end to end, starts `lexicon-init` in its container or starts the stack without the `XERSCOPE_LEXICON_DIR` folder | A step can behave differently on your engine | Rehearse each procedure on a test host |
| The content of the app image (no shell, no package manager, uid 65532) is stated as the `Dockerfile` reads | Those properties rest on the base image | Inspect the image that you pull or build |
| No test of the project restores the stack; location of the TLS key not established | A restored stack can be a new node | Rehearse a restore |
| Containers share the kernel of the host; neither Compose file sets a seccomp, AppArmor or SELinux option, and user namespace remapping is left to the host | Isolation between a container and the host rests on the kernel and on the Docker service's defaults | Harden the host and keep its kernel patched |
| The maintenance status of the third-party components is not provided | A component can reach its end of support without notice from the supplier | Follow the support policy of each publisher |
| Password policy not enforced; the documented hash cost is 10 | The strength of the login rests on the password you choose | Generate a long password |
| Supplier commitments limited to `SECURITY.md`; the licence grants nothing | No fix delay, no notification, no end-of-support date | Settle them in a contract |

## References

Table 25 gives each document cited in this guide with its reference, version and date as printed,
and its address on the publisher's site as of 2026-11-26.

**Table 25.** Documents cited

| Document | Reference | Version, date | Address |
|---|---|---|---|
| "Recommandations de sécurité relatives aux déploiements de conteneur Docker" | ANSSI-FT-082 | Version 1.0, 23/09/2020 | <https://messervices.cyber.gouv.fr/documents-guides/docker_fiche_technique.pdf> |
| "Guide d'hygiène informatique – Renforcer la sécurité de son système d'information en 42 mesures" | None printed | Version 2.0 - Septembre 2017 | <https://messervices.cyber.gouv.fr/documents-guides/guide_hygiene_informatique_anssi.pdf> |
| "Recommandations relatives à l'authentification multifacteur et aux mots de passe" | ANSSI-PG-078 | Version 2.0, 08/10/2021 | <https://messervices.cyber.gouv.fr/documents-guides/anssi-guide-authentification_multifacteur_et_mots_de_passe.pdf> |
| "Recommandations de configuration d'un système GNU/Linux" | ANSSI-BP-028 | Version 2.0, 03/10/2022 | <https://messervices.cyber.gouv.fr/documents-guides/fr_np_linux_configuration-v2.0.pdf> |
| "Le guide de l'homologation de sécurité des systèmes d'information" (ANSSI, with DINUM) | None printed | Version 2.2 – Mars 2026 | <https://messervices.cyber.gouv.fr/documents-guides/guide-homologation-securite-web-04-2025.pdf> |
| "Recommandations pour les architectures des systèmes d'information sensibles ou Diffusion Restreinte" | ANSSI-PG-075 | Version 1.2, 24/09/2021 | <https://messervices.cyber.gouv.fr/documents-guides/anssi-guide-recommandations_architectures_systemes_information_sensibles_ou_diffusion_restreinte-v1.2.pdf> |
| "Recommandations pour l'hébergement dans le cloud des systèmes d'information sensibles" | None printed | Version 1.0 – Juillet 2024 | <https://messervices.cyber.gouv.fr/documents-guides/20240814_np_anssi_recommandations_hebergement_cloud_si_a5_v1g_fr.pdf> |
| "Prestataires de services d'informatique en nuage (SecNumCloud) – référentiel d'exigences" | None printed | Version 3.2 du 8 mars 2022 | <https://cyber.gouv.fr/sites/default/files/document/secnumcloud-referentiel-exigences-v3.2.pdf> |
| "Recommandations relatives à l'interconnexion d'un système d'information à Internet" | ANSSI-PA-066 | Version 3.0, 19/06/2020 | <https://messervices.cyber.gouv.fr/documents-guides/anssi-guide-passerelle_internet_securisee-v3.pdf> |
| "Recommandations sur le nomadisme numérique" | ANSSI-PA-054 | Version 2.0, 13/11/2023 | <https://messervices.cyber.gouv.fr/documents-guides/guide_nomadisme_anssi_pa_054_v2.pdf> |
| "Les Essentiels – Architecture sécurisée de SI" | None printed | V1.0 (08/25) | <https://messervices.cyber.gouv.fr/documents-guides/anssi_essentiels_architecture_securisee_v1.0.pdf> |
| "NIS 2 – Transposition nationale – Mesures de gestion des risques en matière de cybersécurité – ReCyF : Référentiel Cyber France (ReCyF)" | None printed | Version 2.5 du 17/03/2026, working document | <https://messervices.cyber.gouv.fr/documents-ressources/20260317_NIS_V2_ReCyF_v2.5.pdf> |
| ANSSI page "Directive NIS 2" | None | No date printed; page as of 2026-11-26 | <https://messervices.cyber.gouv.fr/nis2> |
| "Instruction générale interministérielle sur la protection du secret de la défense nationale" (SGDSN, IGI 1300) | None printed on the cover | File `igi-1300-20210809.pdf` | <https://www.sgdsn.gouv.fr/files/files/Nos_missions/igi-1300-20210809.pdf> |
| "La sécurité des activités d'importance vitale – Objectifs et enjeux" (SGDSN) | None | No date printed; PDF created 14/03/2016 | <https://www.sgdsn.gouv.fr/files/files/Nos_missions/plaquette-saiv.pdf> |
| "Guide de la sécurité des données personnelles" (CNIL) | None | Sheets dated 14 mars 2024 | <https://www.cnil.fr/fr/guide-de-la-securite-des-donnees-personnelles>; the sentence on article 32 is on <https://www.cnil.fr/fr/securite-avant-propos> |
| CNIL, "Donnée personnelle" and "Le registre des activités de traitement" | None | Register page dated 13 avril 2018 | <https://www.cnil.fr/fr/definition/donnee-personnelle>, <https://www.cnil.fr/fr/RGPD-le-registre-des-activites-de-traitement> |

### Documents cited through another document

This guide names the following documents only through a document of table 25 that cites them, and it
reports nothing from their own text:

- the II 901 (Instruction interministérielle n° 901/SGDSN/ANSSI du 28 janvier 2015);
- the Décret n° 2022-513 du 8 avril 2022;
- the Loi de programmation militaire and the code de la défense;
- the NIS 2 transposition law and its decrees;
- the RGS v2.0 documents;
- every text published on `legifrance.gouv.fr`.

No document of table 25 defines the content of a "dossier d'exploitation" or of a "dossier
d'installation", and none addresses container images, registries or image signatures.
