# xerscope

Weekly Primavera P6 schedule analysis, aligned on P6 Professional 24. Point it at a folder
of weekly `.xer` exports and a baseline XER: schedule health (P6 Check Schedule, DCMA DECM
v8.0, DCMA 14-Point, your own standard), a P6-exact recalculation (activities and
resource assignments), week-over-week changelog, earned value in labour hours with
S-curve, milestone trend, PPC, a Gantt with WBS explorer, and a Power BI export.

## Quick start

```bash
uv sync                                       # Python >= 3.11
uv run xerscope sample --out data/sample      # 8 demo weekly updates
uv run xerscope app --data data/sample        # http://localhost:8501
```

Your files: `uv run xerscope app --data ~/exports/projet --baseline ~/exports/BL.xer`, or
upload them in the sidebar. The baseline can also be any loaded update (default: the first).

Windows (PowerShell) is identical with `\` paths. Install uv once:
`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.

### Docker

```bash
mkdir -p exports && cp ~/exports/projet/*.xer exports/   # your weekly XERs (read-only in the container)
docker compose up -d --build                              # http://localhost:8501
```

- **Image:** uv builds from `uv.lock` (CPython 3.14 managed by uv), the runtime is
  distroless `cc-debian12:nonroot`: no shell, no package manager, non-root user.
- **Network:** the app listens on all interfaces *inside* the container, and compose
  publishes it on `127.0.0.1` only, so the schedules stay off the network as with
  `xerscope app`. Publishing it wider is a deliberate change to `compose.yaml`; put
  authentication in front.
- **Hardening:** read-only root filesystem, exports mounted read-only, all capabilities
  dropped, `no-new-privileges`, health check on `/_stcore/health`.
- **Baseline / own standards:** uncomment `XERSCOPE_BASELINE` / `XERSCOPE_STANDARDS` in
  `compose.yaml`. Any CLI command also runs in the image:
  `docker run --rm -v "$PWD/exports:/data:ro" xerscope check /data --standard P6`.
- **Production:** pin the base images by digest (`docker buildx imagetools inspect`).

## Roadmap

| # | Feature | Where | Status |
|---|---|---|---|
| 1 | Sanity check: P6 Check Schedule (Pro 24), DCMA DECM v8.0, DCMA 14-Point, Integrity (P6-exact recalculation), your own standard (TOML) | Schedule health · `xerscope check` · `xerscope recalc` | done |
| 2 | Compare two XER: changelog of activities, durations, relationships, progress, dates, float, constraints, budgets, resource assignments | Changelog · `xerscope changelog` | done |
| 3 | Baseline: PV (BL labour units × Schedule % Complete, working time of each calendar) | Earned value | done |
| 4 | Snapshot vs baseline: EV, EV %, SPI, BEI (P6 and DCMA), S-curve, EAC | Earned value | done |
| 5 | Milestone trend analysis (forecast over reporting date) | Milestone trend | done |
| 6 | PPC (Last Planner, W-1 forecast vs W actual) + progress delta actual W − actual W-1, by WBS | PPC & progress | done |
| 7 | Gantt & WBS explorer (roll-ups, summary bars, focus a node) | Gantt & WBS | done |
| 8 | Data analysis, forecast, TIA | | next |

## Recalculate like P6

```bash
uv run xerscope recalc week42.xer --out recalc.csv
```

This reschedules the file the way P6 Professional 24 does, then compares every stored
early/late date, total and free float, and every resource assignment's remaining dates.
It honours:

- every calendar: work periods, holidays and exceptions;
- the four relationship types, with lags on the calendar the project names (successor by
  default);
- SS lag of a started predecessor: Early Start (expired lag subtracted) or Actual Start;
- the nine constraint types, primary and secondary;
- Retained Logic, Progress Override or Actual Dates, and expected finish;
- resource-dependent activities on their resources' calendars, driving assignments,
  assignment lag, duration = units / units per hour;
- ALAP, LOE, open ends, "must finish by", and the longest path.

On real P6 exports it reproduces P6 to the minute: 25,302 of 25,302 activity values and
9,360 of 9,360 assignment dates, plus every longest-path flag. A gap on your file means
it was edited after the last F9, or it uses something not modelled (leveling).
`INT-01` and `INT-03` in the Integrity standard run the same checks in the app. Details
and evidence: [docs/cpm.md](docs/cpm.md).

## Compare with P6's Check Schedule

```bash
uv run xerscope check week42.xer --standard P6 --baseline BL.xer --out xerscope-p6.csv
```

Prints the same table as P6's Check Summary (check, target, actual %, found, total). In P6:
Tools › Check Schedule on the same file and baseline, then compare line by line.

- **Checks:** the 14 of P6 Professional 24, in its order and groups (dangling start /
  finish are EPPM-only, not in this list).
- **Targets:** P6 targets are set in its dialog and Oracle does not document defaults. Copy
  `src/xerscope/standards/p6.toml` and set them to yours.
- **Definitions:** each check's population cites the Oracle help page it comes from. All
  differences with DCMA and DECM are listed in [docs/standards.md](docs/standards.md).

`--standard DECM`, `--standard DCMA` or `--standard my.toml` work the same way. Given
several files, `check` runs them as one series, so DECM's checks against the previous
update (actuals changed, riding the status date) work too.
`xerscope standards --template my.toml` writes a commented template for your own standard.

### Remote access without installing anything on the client (Tailscale Funnel + Caddy)

`compose.funnel.yaml` publishes the app at `https://xerscope.<tailnet>.ts.net` for people
who cannot run Tailscale themselves (a corporate laptop on its own VPN), behind a username
and password checked by Caddy. The host network is untouched: tailscaled runs in userspace
(no TUN device, no route, no DNS change), no port is published, and the only traffic is
Tailscale's outbound connection. `tests/test_docker.py` pins those properties.

```bash
cp .env.example .env                       # TS_AUTHKEY (tag:xerscope), XERSCOPE_USER, XERSCOPE_PASSWORD_HASH
docker run --rm caddy:2.11.2 caddy hash-password --plaintext 'your password'
docker compose -f compose.funnel.yaml up -d --build
docker compose -f compose.funnel.yaml exec tailscale tailscale funnel status
```

**On a host that can only run an image** (a NAS with Container Manager and no terminal):
`Dockerfile.remote` builds `xerscope-remote`, one image holding xerscope, Tailscale (userspace)
and Caddy, driven by a small supervisor (`deploy/remote/supervisor.py`). Build and push it
from any machine with Docker, then create one container in the NAS UI:

```bash
docker build -f Dockerfile.remote -t ghcr.io/xerscope/xerscope-remote:latest . && docker push ghcr.io/xerscope/xerscope-remote:latest
```

| In the Container Manager form | Value |
|---|---|
| Image | `ghcr.io/xerscope/xerscope-remote:latest` |
| Environment | `TS_AUTHKEY` (tagged key), `XERSCOPE_USER`, `XERSCOPE_PASSWORD_HASH` (`caddy hash-password`) or `XERSCOPE_PASSWORD` |
| Volumes | `/volume1/plannings` → `/data` read-only; a folder or named volume → `/var/lib/tailscale` |
| Ports | none |
| Capabilities / privileged | none |

Then open `https://xerscope.<tailnet>.ts.net`: the browser asks for the username and
password. Inside the container Caddy and xerscope listen on 127.0.0.1 only, tailscaled has
no TUN device, and the supervisor stops every process on SIGTERM; `tests/test_docker.py`
pins those properties, and the stack was run end to end outside Docker (401 without
credentials, 200 with, loopback listeners only, clean shutdown).

**With Container Manager Projects (compose)** instead: `.github/workflows/image.yml`
publishes `ghcr.io/xerscope/xerscope:latest` (and, with the Docker Hub secrets set,
`mish1ma/xerscope:latest`, which Synology's Container Manager accepts) on every push to
`main`, so the NAS only pulls. In File Station, create `docker/xerscope/` holding `deploy/compose.nas.yaml`,
`deploy/tailscale-serve.json` and `deploy/Caddyfile.nas` renamed to `Caddyfile` with your
hash written in (make it on any machine with Docker); then Container Manager > Project >
Create from that folder. Put the exports in a shared folder (`/volume1/plannings` in the
file) and upload new weeks through Drive or SMB. Step by step, registry login and checks:
[docs/deploy.md](docs/deploy.md).

Allow Funnel for the tag in the tailnet ACL (`"nodeAttrs": [{"target": ["tag:xerscope"],
"attr": ["funnel"]}]`). A shared password is the weakest link of this setup: use a long
one, change it when someone leaves, and prefer Cloudflare Access or an OIDC login if the
audience grows.

## Pages

| Page | What it shows |
|---|---|
| Overview | Forecast finish per update, slips, snapshot table |
| Gantt & WBS | WBS tree with roll-ups (% complete by hours, finish vs baseline). Select a node to focus the Gantt. Grouped bars, comparison outline (previous update, baseline, any file), logic links |
| Activity history | One activity across every update |
| Schedule health | Standard picker (P6, DECM, DCMA, Integrity, uploaded TOML), Check Summary table, flagged items with the rule's definition, metric trend across updates, CSV |
| Changelog | Any two files. Headline counts, then every change, filterable, CSV. Weekly side-by-side counts |
| Earned value | PV, EV, AC, forecast S-curve (hours or % BAC); SPI, BEI (P6 / DCMA), EV/AC per update; Schedule %, Performance % and EV technique per activity |
| Milestone trend | MTA chart, slip since first forecast and last week in working days |
| PPC & progress | PPC per week with target, the week's commitments and outcome, progress points and earned hours by WBS and activity |
| Export for Power BI | `dim_snapshot`, `fact_activity`, `fact_relationship`, `fact_assignment` (Parquet or CSV) |

## Definitions that matter

- **Activity matching:** activities are matched across files by Activity ID (`task_code`),
  never by `task_id`, which changes on re-import.
- **Data date:** `PROJECT.last_recalc_date`.
- **Forecast finish:** the latest activity finish (`scd_end_date` is often stale).
- **P6 options honoured:** critical definition, lag calendar, progressed-activity option,
  SS lag option, float type, expected finish, and % complete type (physical, duration or
  units).
- **Working time:** comes from each calendar's `clndr_data`, work periods and exceptions
  included. Durations, float shifts and slips are in working days. P6 checks compare
  hours, as P6 does.
- **Labour hours:** come from TASK (budgeted, actual and remaining labour units), falling
  back to labour and role assignments in TASKRSRC. Nonlabor units are kept apart.
- **PV:** baseline labour units × Schedule % Complete: linear in working time of each
  activity's calendar between its baseline start and finish, to the minute. Which
  baseline values and dates is P6's Admin Preference "When calculating earned value from
  a baseline use" (sidebar: *Earned value basis*); default budgeted values with planned
  dates, as P6.
- **Start / Finish:** as P6's columns: actual date, else the remaining early date (they
  differ from early dates after leveling), else planned.
- **EV:** baseline labour units × Performance % Complete, by the WBS's EV technique
  (activity % complete, 0/100, 50/50, custom %). Activities not in the baseline earn
  nothing and are listed. AC is the actual hours; EAC = AC + remaining.
- **PPC commitments:** activities that update W-1 forecast to finish before W's data date
  (in a recalculated file, those forecast to finish during the week). An activity deleted
  in W counts as scope change, not as a miss.
- **Day units:** every "wd" is working days, on the activity's calendar for an activity
  and on the project calendar for the project finish; calendar days are labelled "cal. d".

## Validation

Expected values come from someone other than xerscope wherever possible:

| Reference | Checked |
|---|---|
| MPXJ test exports (real P6 8.2 / 8.4 / 20.12) | lag-calendar option per file; % complete for duration, physical and units types |
| xerlock sample + its parsed fixture | every activity's dates, float, durations, % complete, critical and longest path; all relationships (345/345) |
| xerlock DCMA results | all 12 stated DCMA values, critical path test activity and shift, CPL 1080 h |
| P6-scheduled exports (Hotel P6 6.0, Terminal P6 5.0, both unstarted) | CPM recalculation: every early/late date, total and free float, exact clock time (25,302 + 396 values); every longest-path flag (4,283) |
| xerlock's sample (synthetic, xerlock's own engine, Progress Override) | the same 126 values: agreement with another tool, not with P6 |
| MPXJ's PrimaveraScheduler, a second CPM engine (`tests/test_crosscheck_mpxj.py`) | 275 random networks (unstarted, progressed in and out of sequence, resource dependent, nine constraint types), the hand cases and the demo: same dates and floats to the working minute, except named open questions ([docs/cpm.md](docs/cpm.md#validation)) |
| Hotel and Terminal TASKRSRC | every assignment's remaining early/late start and finish (2,340 assignments, 9,360 dates) |
| xerlock critical path test | +600 wd on MEP-020 moves the finish 2026-09-08 → 2028-12-27 |
| MPXJ as independent reader | `xerscope crosscheck` on any file (55,685/55,685 fields on the P6 exports, 680/680 on the others) |
| 260 seeded random networks (`tests/test_cpm_properties.py`) | CPM invariants: links hold early and late, durations, float = LF − EF, no negative float unconstrained with in-sequence progress, constraints, monotone finish with FS links |
| Hand-built schedules (`tests/xerkit.py`) | every rule, each P6 / DCMA / DECM difference, Oracle's documented options (SS lag, Actual Dates, lag calendar default, resource-dependent activities), calendars, PV, EV techniques, PPC, changelog, WBS roll-ups |
| Demo series | each finding the generator plants is found, in the week it appears. Its stored dates are written by xerscope's CPM, so on their own they prove nothing: MPXJ recomputes them independently (test above) |

The suite is mutation-tested. Plausible bugs were injected one at a time: 21 in the
checks (populations, exemptions, units, calendar mapping, PV spreading, weighting…), 20
in the CPM (snapping, lag calendars, options, ALAP, time axis) and 14 in the P6 Pro 24 /
DECM / resource work (expired SS lag, resource calendars, assignment lag and rate, Actual
Dates, longest path, EV techniques, PV ramp, DECM exemptions, axis anchoring), plus 8 on
the corrective pass (backward SS lag, LOE ends, Start/Finish columns, EV basis, calendar
overlaps, parser rows, no data date). Every one
makes it fail except one: swapping start float for finish float, which coincide in this
engine (see docs/cpm.md).

What is **not** established: no public P6 export has progress, resource-dependent
activities or P6 Professional 24 behind it, and none comes with a P6 Check Schedule
report. Progressed and resource-loaded rules rest on Oracle's documentation and on MPXJ;
their open questions are listed in docs/cpm.md. Run `xerscope recalc` and
`xerscope check` next to P6 on your own files: a recalculation that matches P6 there is
the proof for your schedules, and any gap names a rule to fix.

## Tests

```bash
uv run python tests/reference/fetch.py      # pinned third-party XERs (checksum-verified)
uv sync --extra crosscheck                  # MPXJ + jpype, needs a JDK (javac) for the next line
uv run python tests/reference/mpxj_cpm.py   # MPXJ's scheduler at a pinned commit (CPM crosscheck)
uv run pytest -rs                           # 533 tests; the MPXJ ones skip without Java
```

The UI tests render every page headless (Streamlit AppTest), so they run the same on
Windows. GitHub Actions (`.github/workflows/tests.yml`) runs:

- the suite on Windows and Linux, Python 3.11, 3.13 and 3.14;
- an audit job (pip-audit on OSV and PyPI, plus bandit), also every Monday;
- the MPXJ crosscheck on Java 21 and 25: reader comparison and the CPM against MPXJ's
  scheduler.

## Architecture

Module by module: [docs/architecture.md](docs/architecture.md). The CPM: [docs/cpm.md](docs/cpm.md).

```
src/xerscope/
├── xer/parser.py        bytes → {TABLE: DataFrame[str]}              format only
├── xer/model.py         RawXer → Snapshot                             P6 semantics, units, labour hours
├── xer/calendar.py      clndr_data → WorkCalendar                     working hours, exact to the minute
├── store.py             [Snapshot] → tidy history frames              the weekly time series
├── analysis/
│   ├── rules.py         one parameterised function per check          the only check code
│   ├── standards.py     TOML → Standard (validated)                   P6, DCMA, yours = data
│   ├── checks.py        run a standard, health history
│   ├── explain.py       how each result was computed (formula, population, parameters)
│   ├── baseline.py      designated BL XER or planned dates
│   ├── cpm.py           P6-exact CPM: passes, float, longest path, assignments; recalc, CPT
│   ├── changelog.py     two snapshots → every change
│   ├── evm.py           PV (Schedule %), EV (WBS technique), AC, SPI, forecast curve
│   ├── progress.py      MTA, PPC, progress delta
│   └── wbs.py           WBS tree and roll-ups
├── standards/*.toml     p6 (Pro 24), decm (v8.0), dcma (14-point), integrity, custom-template
├── viz/                 Plotly: Gantt (+ WBS bars), S-curve, indices, MTA, PPC
├── app/                 Streamlit, one file per page; ui.py = shared look; .streamlit/ = theme
├── export.py            Power BI star schema
├── sample.py            demo generator with planted findings
└── cli.py               xerscope {app,info,check,recalc,standards,changelog,export,crosscheck,sample}
```

Why rules plus TOML: P6 "Large Float" and DCMA-06 are the same check with different units
and populations. Keeping one function and moving the differences into data:

- avoids two implementations drifting apart;
- lets you write your own standard without touching code;
- makes each difference testable on its own.

## Security

- **Network:** the app listens on localhost only; `--host 0.0.0.0` is the explicit opt-in.
- **Dependencies:** minimum versions are pinned to releases audited clean (2026-10-28), so
  an install that ignores `uv.lock` cannot pull an older vulnerable version.
- **CI:** actions are pinned by commit SHA; Dependabot proposes updates weekly.
