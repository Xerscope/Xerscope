# xerscope

[![tests](https://github.com/Xerscope/xerscope/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Xerscope/xerscope/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.13%20%7C%203.14-blue)](pyproject.toml)
[![License](https://img.shields.io/badge/license-all%20rights%20reserved-lightgrey)](LICENSE)

Weekly Primavera P6 schedule analysis, aligned on P6 Professional 24. Point it at a folder
of weekly `.xer` exports and a baseline XER, and get the numbers a planning engineer would
read in P6, each traced to a formula, a population and a source:

- **Schedule health:** P6 Check Schedule, DCMA DECM v8.0, DCMA 14-Point, Integrity, or
  your own standard written in TOML.
- **P6-exact recalculation:** early / late dates, floats, longest path and resource
  assignments, compared with the dates stored in the file.
- **Weekly series:** changelog between updates, delay analysis (half-stepped update
  analysis, longest path of each update), earned value in labour hours with S-curve and
  Earned Schedule, milestone trend, PPC (finish and start commitments), Gantt with WBS
  explorer and a sentence field that sets its filters ("Ask the schedule", no model).
- **Export:** Power BI star schema (Parquet or CSV), anonymised XER extract.

## Contents

- [Quick start](#quick-start)
- [User documentation](#user-documentation)
- [Validation](#validation)
- [Deployment](#deployment)
- [Documentation](#documentation)
- [Roadmap](#roadmap)
- [Contributing](#contributing) · [Security](#security) · [Licence](#licence)

## Quick start

Requires git and [uv](https://docs.astral.sh/uv/), with Python ≥ 3.11.

```bash
git clone https://github.com/Xerscope/xerscope && cd xerscope
uv sync --locked
uv run xerscope sample --out data/sample      # 8 demo weekly updates with planted findings
uv run xerscope app --data data/sample        # http://localhost:8501
```

The app opens with no file read: open **Files** in the sidebar, **Select all**, **Done**, then
choose the baseline and press **Done** again. The same series on the command line:
`uv run xerscope check data/sample --standard P6`. The
[user guide](docs/user-guide.md#getting-started) walks through both, step by step.

With Docker, `docker compose up -d --build` serves the app on `http://localhost:8501` from the
`exports` folder, mounted read-only and published on the host's loopback only:
[user guide](docs/user-guide.md#run-with-the-local-docker-image).

## User documentation

| Guide | Read it for |
|---|---|
| [User guide](docs/user-guide.md) ([français](docs/user-guide.fr.md)) | concepts (updates, baselines, standards, units), a first run on the demo series, one how-to per goal in the app and on the command line, the reference of every command, option, page and environment variable, troubleshooting, limits, glossary |
| [IT deployment guide](docs/it-deployment-guide.md) ([français](docs/it-deployment-guide.fr.md)) | hosting on an internal server: data handled, architecture, flow matrix, accounts and secrets, container hardening against ANSSI-FT-082, origin and integrity of the images, procedures, logging, known gaps |
| [Formula sheet](docs/formula-sheet.md) ([français](docs/formula-sheet.fr.md)) | every calculation in one entry: formula, unit and calendar, the funnel that cuts its population (start set, each step and its source, what is counted), target, source; funnel diagrams per standard |
| [docs/deploy.md](docs/deploy.md) | the shipped remote stack (Tailscale Funnel, Caddy) step by step on a Synology NAS |

## Validation

Expected values come from someone other than xerscope wherever possible. Details and open
questions: [docs/cpm.md](docs/cpm.md#validation), [docs/backlog.md](docs/backlog.md).

| What | Against | Result |
|---|---|---|
| CPM: early / late dates, floats | P6 Professional 23.12.1 held-out corpus (cpp-cpm-engine, MIT: 360 synthetic schedules scheduled by P6, results read from its database), `tests/test_p6_heldout.py` | 99.9 % identical on task-dependent work without LOE (sets H1–H7), 99.7 % on all task-dependent work, 99.3 % on resource-dependent work (99.6 % of all 54,726 values; every set at 98.2 % or more); a floor per set, one pinned witness per rule |
| CPM, assignments, longest path | public P6 exports with stored dates (Hotel 6.0, Terminal 5.0, PV 25.12, XER-editor 20.12), `tests/test_cpm.py` | every value identical to the minute: 26,100 activity values, 9,360 assignment dates, 4,360 longest-path flags |
| CPM | MPXJ's PrimaveraScheduler, a second engine, `tests/test_crosscheck_mpxj.py` | identical on random networks and the demo outside the named open cases |
| Reading of the XER tables | MPXJ as an independent reader, `xerscope crosscheck` | identical on every reference file |
| P6 Check Schedule | a P6 Professional 26.8 report and F9 log on a synthetic project, `tests/test_p6_checksched.py`; Oracle's help, one quoted sentence per test (`tests/test_p6_check_schedule.py`); report R1 (a P6 Professional report on a real schedule, outside the repository) for P6-12, P6-13 and P6-15 to P6-17 | every line and list of the 26.8 report identical; populations rebuilt by hand in the tests |
| DECM, DCMA 14-Point, EV, PPC, changelog | hand-built schedules (`tests/xerkit.py`), xerlock's sample file with the pamphlet's DCMA counts (`tests/reference/expected.py`) | counted by hand; **no DECM output confirms the populations yet** |
| Invariants | 260 seeded random networks, `tests/test_cpm_properties.py` | links hold in both passes, float = LF − EF, constraints |
| Demo series | its planted findings | found in the week they appear; its dates are xerscope's own, checked by MPXJ |

What is **not** established: no public export comes from P6 Professional 24 (23.12 and
25.12 bracket it), no public file comes with a Check Schedule report, and
resource-dependent work is the largest CPM gap. Run `xerscope recalc` and
`xerscope check` next to P6 on your own files: a match there is the proof for your
schedules, and any gap names a rule to fix.

## Deployment

- **Local:** `xerscope app` or `docker compose up -d --build` (above), on the machine's loopback;
  the flows of each option are in the [IT deployment guide](docs/it-deployment-guide.md#flow-matrix).
- **Remote, nothing installed on the client:** `deploy/compose.yaml` publishes the app at
  `https://xerscope.<tailnet>.ts.net/<random>/` through Tailscale Funnel, behind a login
  checked by Caddy, which also limits each visitor to 300 requests a minute
  (`deploy/caddy/Dockerfile`: Caddy with the `caddy-ratelimit` module). tailscaled runs in
  userspace (no TUN device, route or DNS change), no port is published, and the app's
  container has no route to the internet. Five settings are required, as environment
  variables in `deploy/.env` (template: `deploy/.env.example`, which also lists the optional
  ones: the images, the account the app runs as, its memory cap, files read at once, the Ask
  lexicon folder, the Debug page). The host pulls the images `ghcr.io/xerscope/xerscope`
  and `ghcr.io/xerscope/xerscope-caddy` (public packages, docs/deploy.md §2) built by
  `.github/workflows/image.yml` (a Docker Hub copy of each when configured, docs/deploy.md §8),
  `:latest` by default; pin a release and its digest with `XERSCOPE_IMAGE` and
  `XERSCOPE_CADDY_IMAGE` in `deploy/.env` (docs/deploy.md §7). A release is a
  git tag `v0.1.0` on `main`: the tag publishes `:0.1.0`, with SLSA provenance, an SBOM and a
  GitHub build attestation; `CHANGELOG.md` lists what each release carries.
  `tests/test_docker.py` and the CI job `deploy` pin those properties. The Ask field's
  lexicon is built from the exports on demand (`docker compose run --rm lexicon-init`,
  `xerscope lexicon build`, docs/deploy.md §10).

```bash
cd deploy && cp .env.example .env    # TS_AUTHKEY, XERSCOPE_USER, XERSCOPE_PASSWORD_HASH, XERSCOPE_PATH, XERSCOPE_EXPORTS
docker run --rm caddy:2.11.9 caddy hash-password --algorithm bcrypt --bcrypt-cost 10 --plaintext '<password>'
docker compose up -d
docker compose exec tailscale tailscale funnel status
```

Allow Funnel for the tag in the tailnet ACL
(`"nodeAttrs": [{"target": ["tag:xerscope"], "attr": ["funnel"]}]`). A shared password is
the weakest link of this setup: use a long one, change it when someone leaves, and prefer
an identity-aware proxy (Cloudflare Access, OIDC) if the audience grows.

Step by step on a Synology NAS (DSM 7.4, Container Manager), checks and troubleshooting:
[docs/deploy.md](docs/deploy.md).

## Documentation

| Document | Read it for |
|---|---|
| [docs/architecture.md](docs/architecture.md) | module by module: data flow, layers, where each P6 concept lives, the test files |
| [docs/cpm.md](docs/cpm.md) | the CPM engine: time axis, options, algorithm, validation, conventions no reference settles |
| [docs/standards.md](docs/standards.md) | the built-in standards, their sources, and where P6, DCMA and DECM count differently |
| [docs/formulas.md](docs/formulas.md) | the formula, population and pinning test of every number |
| [docs/deploy.md](docs/deploy.md) | the remote deployment on a NAS, the Gantt "Ask" field's lexicon |
| [docs/backlog.md](docs/backlog.md) | what is known to be wrong, unproven or missing |
| [docs/adr/](docs/adr/README.md) | architecture decision records |
| [docs/structure-proposal.md](docs/structure-proposal.md) | proposed, not applied: sub-packages and file splits of `src/xerscope` and `tests/`, with the pull request plan |
| [docs/quality-plan.md](docs/quality-plan.md) | the global audit's findings and the work items it set, one pull request each |
| [docs/refactor-front-plan.md](docs/refactor-front-plan.md) | the plan of the front refactoring (`app/`, `viz/`), package by package |
| [docs/refactor-front/](docs/refactor-front/executor-brief.md) | its working files: the brief of an executor or reviewer, the review findings, the redesign and security notes |

Also: [CONTRIBUTING.md](CONTRIBUTING.md) (setup, verification gate, conventions),
[CHANGELOG.md](CHANGELOG.md) (what each release carries), [SECURITY.md](SECURITY.md).

Source layout:

```
src/xerscope/
├── xer/            parser.py (bytes → tables of strings), validate.py (value checks, one per rule),
│                   model.py (P6 meaning, units, labour hours), calendar.py (working time, exact to
│                   the minute), pmxml.py + pmxml_scan.py (baselines from a P6 XML export)
├── store.py        snapshots → weekly history frames
├── analysis/       p6/ dcma/ decm/ integrity.py (one function per check), populations.py,
│                   rules.py (registry, parameterised rules for your own standard), standards.py,
│                   checks.py, explain.py, audit.py, baseline.py, baseline_resolution.py,
│                   cpm.py + resource_placement.py, longest_path.py, forensics.py, changelog.py,
│                   evm.py, progress.py, wbs.py, task_filters.py, query.py + ask/ (the Ask field)
├── standards/      p6, decm, dcma, integrity, custom-template (.toml)
├── sheets/         calculation sheets shown by Audit, one per check (P6/<id>.md: the P6 standard)
├── viz/            Plotly figures (S-curve, indices, MTA, PPC) and the WBS Gantt (HTML/JS/CSS)
├── app/            Streamlit: streamlit_app.py (navigation), views/ (one file per page), the
│                   Files window, sidebar, background reading, downloads
├── verify/         independent checks: P6 corpus, MPXJ scheduler and reader, difference shapes
├── crosscheck.py   one import for verify/
├── anonymize.py    anonymised copies of XER files and of the tables downloaded
├── csv_safe.py     CSV cells a spreadsheet would run as a formula, neutralised
├── config.py       tunable defaults no standard owns
├── export.py       Power BI star schema
├── sample.py       demo generator with planted findings
└── cli.py          command line
```

## Roadmap

| # | Feature | Where | Status |
|---|---|---|---|
| 1 | Sanity check: P6 Check Schedule (Pro 24), DCMA DECM v8.0, DCMA 14-Point, Integrity (P6-exact recalculation), your own standard (TOML) | Schedule health · `check` · `recalc` | done |
| 2 | Compare two XER: activities, durations, relationships, progress, dates, float, constraints, budgets, resource assignments | Changelog · `changelog` | done |
| 3 | Baseline: PV (BL labour units × Schedule % Complete, working time of each calendar) | Earned value | done |
| 4 | Snapshot vs baseline: EV, EV %, SPI, BEI (P6 and DCMA), S-curve, EAC, Earned Schedule | Earned value | done |
| 5 | Milestone trend analysis (forecast over reporting date) | Milestone trend | done |
| 6 | PPC (W-1 finish and start commitments vs W actual) + progress delta, by WBS | PPC & progress | done |
| 7 | Gantt & WBS explorer (roll-ups, summary bars, focus a node, task history across updates) | Gantt & WBS | done |
| 8 | Delay analysis: half-stepped update analysis (AACE 29R-03 MIP 3.4), longest path of each update | Delay analysis | done |
| 9 | "Ask the schedule": a sentence turned into the Gantt's filters, English or French, no model | Gantt & WBS · `ask-bench` · `lexicon` | done |
| 10 | Time impact analysis (TIA) | | next |

Known gaps and open questions of the features above are tracked in
[docs/backlog.md](docs/backlog.md).

## Contributing

Setup, the verification gate, conventions and the pull request checklist:
[CONTRIBUTING.md](CONTRIBUTING.md). In short:

```bash
uv sync --locked
uv run python tests/reference/fetch.py            # pinned third-party XERs (checksum-verified)
uv run python tests/reference/fetch_p6_heldout.py # P6 23.12 held-out corpus (pinned commit)
uv run pytest -rs                                 # corpus and MPXJ tests skip when their data is missing
uvx ruff@0.17.4 check src tests scripts && uvx ruff@0.17.4 format --check src tests scripts
```

No real schedule enters the repository, its issues or its pull requests: tests build their
files in code (`tests/xerkit.py`) or download pinned public ones.

## Security

The app binds localhost by default; both images run on a read-only root
filesystem, the app's as non-root, Caddy's as root with every capability dropped but
`NET_BIND_SERVICE`; GitHub Actions are pinned by commit SHA; Dependabot proposes updates, and
`pip-audit`, `bandit`, Trivy, CodeQL and OpenSSF Scorecard run in CI. Report a vulnerability privately: [SECURITY.md](SECURITY.md).

## Licence

All rights reserved, no licence granted: see [LICENSE](LICENSE). Third-party components:
[NOTICE](NOTICE).
