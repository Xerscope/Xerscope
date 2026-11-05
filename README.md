# xerscope

[![tests](https://github.com/Xerscope/xerscope/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Xerscope/xerscope/actions/workflows/tests.yml)
[![image](https://github.com/Xerscope/xerscope/actions/workflows/image.yml/badge.svg?branch=main)](https://github.com/Xerscope/xerscope/actions/workflows/image.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.13%20%7C%203.14-blue)](pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Weekly Primavera P6 schedule analysis, aligned on P6 Professional 24. Point it at a folder
of weekly `.xer` exports and a baseline XER, and get the numbers a planning engineer would
read in P6, each traced to a formula, a population and a source:

- **Schedule health:** P6 Check Schedule, DCMA DECM v8.0, DCMA 14-Point, Integrity, or
  your own standard written in TOML.
- **P6-exact recalculation:** early / late dates, floats, longest path and resource
  assignments, compared with the dates stored in the file.
- **Weekly series:** changelog between updates, earned value in labour hours with
  S-curve, milestone trend, PPC (Last Planner), Gantt with WBS explorer.
- **Export:** Power BI star schema (Parquet or CSV).

## Contents

- [Quick start](#quick-start)
- [Command line](#command-line)
- [Web app](#web-app)
- [Definitions that matter](#definitions-that-matter)
- [Validation](#validation)
- [Deployment](#deployment)
- [Documentation](#documentation)
- [Roadmap](#roadmap)
- [Contributing](#contributing) · [Security](#security) · [Licence](#licence)

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (it installs Python ≥ 3.11 if needed).

```bash
git clone https://github.com/Xerscope/xerscope && cd xerscope
uv sync --locked
uv run xerscope sample --out data/sample      # 8 demo weekly updates with planted findings
uv run xerscope app --data data/sample        # http://localhost:8501
```

Your own files: `uv run xerscope app --data ~/exports/project --baseline ~/exports/BL.xer`,
or upload them in the sidebar. The baseline can also be any loaded update (default: the
first). Schedules stay on your machine: the app listens on localhost, and an uploaded file
is held in the session's memory, never written to disk.

Windows (PowerShell) is identical with `\` paths. Install uv once:
`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.

### Docker

```bash
mkdir -p exports && cp ~/exports/project/*.xer exports/   # read-only in the container
docker compose up -d --build                               # http://localhost:8501
```

| Property | Value |
|---|---|
| Build | uv from `uv.lock`, CPython 3.14 managed by uv |
| Runtime | distroless `cc-debian13:nonroot`: no shell, no package manager, non-root |
| Network | listens on all interfaces inside the container; `compose.yaml` publishes it on `127.0.0.1` only. Publishing it wider is a deliberate change: put authentication in front |
| Hardening | read-only root filesystem, exports mounted read-only, all capabilities dropped, `no-new-privileges`, health check on `/_stcore/health` |

Any CLI command runs in the image:
`docker run --rm -v "$PWD/exports:/data:ro" xerscope check /data --standard P6`.

## Command line

| Command | Does |
|---|---|
| `app` | launch the web app on localhost (`--data`, `--baseline`, `--standards`, `--port`, `--host`) |
| `check` | run a standard and print the P6-style summary (`--baseline` / `--planned-baseline`, `--out`, `--flagged DIR`, `--expect CSV`, `--fail-on`) |
| `recalc` | reschedule like P6 and compare with the stored dates (`--out`, `--report`, `--show N`) |
| `changelog` | every change between two files |
| `standards` | list standards and rules (`--rules`), or write a template (`--template`) |
| `export` | Power BI tables |
| `crosscheck` | compare with MPXJ, needs Java (`--cpm`: MPXJ's scheduler; `--p6`: the P6 held-out corpus) |
| `info` | one line per snapshot |
| `sample` | generate the demo series |

`uv run xerscope <command> --help` lists every option.

### Recalculate like P6

```bash
uv run xerscope recalc week42.xer --out recalc.csv
```

Reschedules the file the way P6 Professional 24 does, then compares every stored early /
late date, total and free float, and every resource assignment's remaining dates. It
honours:

- every calendar: work periods, holidays and exceptions;
- the four relationship types, with lags on the calendar the project names (successor by
  default);
- SS lag of a started predecessor: Early Start (expired lag subtracted) or Actual Start;
- the nine constraint types, primary and secondary;
- Retained Logic, Progress Override or Actual Dates, and expected finish;
- resource-dependent activities on their resources' calendars, driving assignments,
  assignment lag, duration = units / units per hour;
- ALAP, LOE, open ends, "must finish by", and the longest path.

A gap on your file means it was edited after the last F9, or it uses something not
modelled (leveling). `--report` groups the differences by activity shape, so one week's
differences point at one rule. `INT-01` and `INT-03` of the Integrity standard run the
same comparison in the app. Details and evidence: [docs/cpm.md](docs/cpm.md).

### Compare with P6's Check Schedule

```bash
uv run xerscope check week42.xer --standard P6 --baseline BL.xer --out xerscope-p6.csv
```

Prints the table of P6's Check Summary (check, target, actual %, found, total). In P6:
Tools › Check Schedule on the same file and baseline, then compare line by line.

- **Checks:** the 17 of `standards/p6.toml`, in Oracle's groups: the 14 of the P6
  Professional 24 dialog help, plus out of sequence and dangling start / finish as a P6
  Professional report prints them.
- **Targets:** the dialog's documented defaults (< 5 %, < 1 % for the inaccuracy checks,
  FS > 90 %, BEI > 0.95 as a P6 Professional report prints it). Copy `src/xerscope/standards/p6.toml` and set them to yours.
- **Validation:** `--flagged out/` writes the items found per check; `--expect report.csv`
  diffs the counts against the ones typed from P6's summary (exit 1 on a difference).
- **Definitions:** each check cites the Oracle page or report it comes from. Differences
  with DCMA and DECM: [docs/standards.md](docs/standards.md). Formula and pinning test of
  every number: [docs/formulas.md](docs/formulas.md).

`--standard DECM`, `--standard DCMA` or `--standard my.toml` work the same way. Given
several files, `check` runs them as one series, so DECM's checks against the previous
update (actuals changed, riding the status date) work too.
`xerscope standards --template my.toml` writes a commented template for your own standard.

## Web app

| Page | What it shows |
|---|---|
| Overview | forecast finish per update, slips, snapshot table |
| Gantt & WBS | Gantt grouped by WBS as in P6: tree grid with roll-ups (% complete by hours, float) beside the timeline, WBS rows fold open and closed; a WBS picked in the list sets the KPIs and opens the Gantt on it; comparison outline (previous update, baseline, any file), logic links, month / week timescale |
| Activity history | one activity across every update |
| Schedule health | standard picker (P6, DECM, DCMA, Integrity, uploaded TOML), Check Summary, flagged items with the rule's definition, metric trend, CSV of every flagged item |
| Audit | one check: the sets behind its count (counted, checked not counted, excluded), the check re-run with another target or threshold (this page only), the `[[metric]]` table to make it permanent |
| Changelog | any two files: headline counts, every change (filterable, CSV), weekly counts |
| Earned value | PV, EV, AC, forecast S-curve (hours or % BAC); SPI (labour units; the cost SPI, P6 column, and the other cost figures behind the sidebar checkbox Costs, off by default), BEI (P6 / DCMA), EV/AC per update; Schedule %, Performance % and EV technique per activity |
| Milestone trend | MTA chart, slip since first forecast and since last week in working days |
| PPC & progress | PPC per week with target, the week's commitments and outcome, progress and earned hours by WBS and activity |
| Export for Power BI | `dim_snapshot`, `fact_activity`, `fact_relationship`, `fact_assignment` (Parquet or CSV) |

Configuration (environment variables, also set by the `app` flags):

| Variable | Effect |
|---|---|
| `XERSCOPE_DATA` | folder of weekly `.xer` files to preload |
| `XERSCOPE_BASELINE` | baseline `.xer` |
| `XERSCOPE_STANDARDS` | folder of your own standard `.toml` files |
| `XERSCOPE_DATA_LOCKED` | `true`: the sidebar offers no folder field and no `.xer` upload, only `XERSCOPE_DATA` is read (remote deployment) |

## Definitions that matter

- **Activity matching:** by Activity ID (`task_code`), never by `task_id`, which changes
  on re-import.
- **Data date:** `PROJECT.last_recalc_date`.
- **Forecast finish:** the latest activity finish (`scd_end_date` is often stale).
- **P6 options honoured:** critical definition, lag calendar, progressed-activity option,
  SS lag option, float type, expected finish, and % complete type (physical, duration or
  units).
- **Working time:** from each calendar's `clndr_data`, work periods and exceptions
  included. Durations, float shifts and slips are in working days; P6 checks compare
  hours, as P6 does.
- **Day units:** "wd" is working days, on the activity's calendar for an activity and on
  the project calendar for the project finish; calendar days are labelled "cal. d".
- **Labour hours:** from TASK (budgeted, actual and remaining labour units), falling back
  to labour and role assignments in TASKRSRC. Nonlabor units are kept apart.
- **Start / Finish:** as P6's columns: actual date, else the remaining early date (they
  differ from early dates after leveling), else planned.
- **PV:** baseline labour units × Schedule % Complete, linear in working time of each
  activity's calendar between its baseline start and finish, to the minute. Which
  baseline values and dates follows P6's Admin Preference "When calculating earned value
  from a baseline use" (sidebar: *Earned value basis*); default budgeted values with
  planned dates, as P6.
- **EV:** baseline labour units × Performance % Complete, by the WBS's EV technique
  (activity % complete, 0/100, 50/50, custom %). Activities not in the baseline earn
  nothing and are listed. AC is the actual hours; EAC = AC + remaining.
- **PPC commitments:** activities that update W-1 forecasts to finish before W's data
  date (in a recalculated file, those forecast to finish during the week). An activity
  deleted in W counts as scope change, not as a miss.

## Validation

Expected values come from someone other than xerscope wherever possible. Details and open
questions: [docs/cpm.md](docs/cpm.md#validation), [docs/backlog.md](docs/backlog.md).

| What | Against | Result |
|---|---|---|
| CPM: early / late dates, floats | P6 Professional 23.12.1 held-out corpus (cpp-cpm-engine, MIT: 360 synthetic schedules scheduled by P6, results read from its database), `tests/test_p6_heldout.py` | 99.9 % identical on task-dependent work without LOE, 92 % on all task-dependent work, 81 % on resource-dependent work (89 % of all 54,726 values); a floor per set, one pinned witness per rule |
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

- **Local:** `xerscope app` or `docker compose up` (above); nothing leaves the machine.
- **Remote, nothing installed on the client:** `deploy/compose.yaml` publishes the app at
  `https://xerscope.<tailnet>.ts.net/<random>/` through Tailscale Funnel, behind a login
  checked by Caddy, which also limits each visitor to 120 requests a minute
  (`deploy/caddy/Dockerfile`: Caddy with the `caddy-ratelimit` module). tailscaled runs in
  userspace (no TUN device, route or DNS change), no port is published, and the five
  settings are environment variables in `deploy/.env` (template: `deploy/.env.example`). The host pulls the public images
  `ghcr.io/xerscope/xerscope:latest` and `ghcr.io/xerscope/xerscope-caddy:latest` built by
  `.github/workflows/image.yml` (a Docker Hub copy of each when configured, docs/deploy.md §8).
  `tests/test_docker.py` and the CI job `deploy` pin those properties.

```bash
cd deploy && cp .env.example .env    # TS_AUTHKEY, XERSCOPE_USER, XERSCOPE_PASSWORD_HASH, XERSCOPE_PATH, XERSCOPE_EXPORTS
docker run --rm caddy:2.11.8 caddy hash-password --algorithm bcrypt --bcrypt-cost 10 --plaintext '<password>'
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
| [docs/deploy.md](docs/deploy.md) | the remote deployment on a NAS |
| [docs/backlog.md](docs/backlog.md) | what is known to be wrong, unproven or missing |

Source layout:

```
src/xerscope/
├── xer/            parser.py (bytes → tables of strings), model.py (P6 meaning, units, labour hours),
│                   calendar.py (working time, exact to the minute)
├── store.py        snapshots → weekly history frames
├── analysis/       p6/ dcma/ decm/ integrity.py (one function per check), populations.py,
│                   rules.py (registry, parameterised rules for your own standard), standards.py,
│                   checks.py, explain.py, baseline.py, cpm.py, changelog.py, evm.py, progress.py, wbs.py
├── standards/      p6, decm, dcma, integrity, custom-template (.toml)
├── viz/            Plotly figures (S-curve, indices, MTA, PPC) and the WBS Gantt (HTML/JS)
├── app/            Streamlit, one file per page
├── verify/         independent checks: P6 corpus, MPXJ scheduler and reader, difference shapes
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
| 4 | Snapshot vs baseline: EV, EV %, SPI, BEI (P6 and DCMA), S-curve, EAC | Earned value | done |
| 5 | Milestone trend analysis (forecast over reporting date) | Milestone trend | done |
| 6 | PPC (Last Planner, W-1 forecast vs W actual) + progress delta, by WBS | PPC & progress | done |
| 7 | Gantt & WBS explorer (roll-ups, summary bars, focus a node) | Gantt & WBS | done |
| 8 | Data analysis, forecast, TIA | | next |

Known gaps and open questions are tracked in [docs/backlog.md](docs/backlog.md).

## Contributing

Setup, the verification gate, conventions and the pull request checklist:
[CONTRIBUTING.md](CONTRIBUTING.md). In short:

```bash
uv sync --locked
uv run python tests/reference/fetch.py            # pinned third-party XERs (checksum-verified)
uv run python tests/reference/fetch_p6_heldout.py # P6 23.12 held-out corpus (pinned commit)
uv run pytest -rs                                 # corpus and MPXJ tests skip when their data is missing
uvx ruff check src tests && uvx ruff format --check src tests
```

No real schedule enters the repository, its issues or its pull requests: tests build their
files in code (`tests/xerkit.py`) or download pinned public ones.

## Security

The app binds localhost by default; the images run non-root on a read-only root
filesystem; GitHub Actions are pinned by commit SHA; Dependabot, `pip-audit`, `bandit` and
Trivy run in CI. Report a vulnerability privately: [SECURITY.md](SECURITY.md).

## Licence

Apache License 2.0: see [LICENSE](LICENSE) and [NOTICE](NOTICE).
