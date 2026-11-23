# Changelog

All notable changes to xerscope are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions
[Semantic Versioning](https://semver.org/spec/v2.0.0.html): while the version is 0.y.z the
public API (the CLI, the `xerscope` package, the standards TOML) may still change between
minor versions.

A release is a git tag `vX.Y.Z` on `main`, cut by the maintainer after the version and date
below are filled in: `.github/workflows/image.yml` then publishes `ghcr.io/xerscope/xerscope:X.Y.Z`
and `xerscope-caddy:X.Y.Z` with their provenance (docs/deploy.md §7).

## [Unreleased]

Conformity work from the audit of 2026-11 (`audit-report.md`, `conformity-plan.md`).

### Added

- Baselines: a `baselines` subfolder of the updates' folder holds baseline files, .xer or P6 XML, offered as
  the separate baseline file under "baselines/<name>" and never read as updates, so a baseline exported as
  its own XER can be picked on a locked server even under the name of an update. A baseline XER that holds
  several projects (the project and the baseline exported with it) gets a project picker in the window.
- Health: each check that reads a baseline names in its row the one it was measured against, "name
  (Project ID) · kind"; Debug block 5 lists the baseline used by each update.

- Baselines: a P6 Project Baseline held in the file is named as P6's Maintain Baselines names it, its name
  then its Project ID ("Terminal works - B1 (BL, P6 Project Baseline in two.xer)"); the Project ID alone
  when the file holds no name. The sidebar says in one line when updates measure earned value against a
  user's primary baseline in P6, which the file does not carry.
- Baselines: a page warns when P6's Update Baseline changed the baseline after the update's status date
  (Last Update Date, from the XER or the P6 XML): it may no longer be the plan the update was measured against.
- Baselines: `Baseline.kind` and `found_by` say how the baseline of an update relates to it (in file,
  exact, probable, chosen, fallback, planned, series) and what found it; set by every path of the app,
  read by one classifier (`app.baselines.kind_of`) for the context banner, the sidebar and the Debug
  page, so a baseline read from the export is no longer called "in file". An update left undecided by the
  resolution (the versions of the export around its project hold different baselines) is not measured,
  not even by the fallback, until the Files and baseline window gets a choice for it: one of the two
  candidate baselines (applied as "chosen", alerted like a probable one) or the fallback.

- PPC & progress page: lookahead reliability, Tasks Anticipated and Tasks Made Ready of the
  week against the plans of 1, 2, 4 and 8 updates before (Hamzeh, Ballard & Tommelein 2012,
  figure 5; `progress.lookahead_series`, formulas.md §4), with every week's counts.
- Rules for a company standard (`xerscope standards --rules`, formulas.md §2.5): `on_data_date`
  (activities starting or finishing on the data date); `float` with `op = "between"` and
  `value_max` (a float band, bounds included, reversed bounds refused on load); `missing_logic`
  exemptions `single_project_start` / `single_project_finish` (one task only, a shared date
  passes none); `relationship_type` with `zero_lag` (type and zero lag together) and `listed`
  (the links of the type instead of the others); `no_resource` with `kind = "labour_units"`
  (budgeted labour units above zero); `lag` with `unit = "project_pct"` (a limit as a share of
  the project's working hours, `Snapshot.project_work_hours`). Built-in standards unchanged.
- Overview: a score card for every standard the app lists (the `--standards` folder and the
  session's uploads), not only the four built-in ones.
- Schedule health: a standard uploaded on the page is in the picker on the run that loads it; the
  population steps of a standard of your own name its `source` text.
- Standards: a metric's optional `item` ties it to a criterion of the source; the score counts
  criteria (an item fails when one of its metrics fails, the card names which). P6-10a and
  P6-10b are one item: the P6 score reads 17 criteria for 18 metrics (formulas.md §1.6).
- Remote deployment: the HTML shell (`/`, `index.html`) is `Cache-Control: no-store` like the
  downloads; the browser keeps the public JS chunks only.
- Remote deployment: `XERSCOPE_STANDARDS` points at the exports folder, so a standard of your
  own (.toml) dropped beside the exports is read at each start (`deploy/compose.yaml`,
  docs/deploy.md §5).
- Delay analysis page and `analysis/forensics.py`: the half-step reading of each week (AACE RP
  29R-03 MIP 3.4, contemporaneous split: the bifurcated, half-stepped update). The previous update
  is rescheduled with the update's changes applied one step at a time (progress as 3.4.K.4.b
  defines it, then scope, durations, logic, constraints, calendars and options): the finish before
  replanning and the week's slip, then what the replanning did; how the finish is held (last task,
  Must Finish By, Mandatory Finish), the longest path's float, the series over every update
  (formulas.md §5.1). The baseline is not read. A week whose recalculated finish is not the one P6
  stored in the file is flagged: its shifts may be the recalculation's.
- Delay analysis: the longest path of each update against the one before (`analysis/longest_path.py`,
  AACE RP 29R-03 3.4.E.9 and SVP 2.3.B.6): the tasks that stayed, entered, were finished, or are
  still open and left the path, per week and over the series (formulas.md §5.2).
- Debug, block 3: the recalculated finish against the file's, the tasks where the recalculated early
  dates first differ from the stored ones, and the same tasks counted by form with no Task ID and no
  date (formulas.md §5.3). The Delay analysis warning points to it.
- Delay analysis: the week's commitments made on the previous update's longest path, kept or not,
  and their PPC beside the week's PPC in the series (formulas.md §5.2); where the week's
  revisions fall, within the lookahead (6 weeks, `Settings.lookahead_weeks`) or beyond it
  (formulas.md §5.1).
- Changelog: categories Calendars (working time changed) and Options (scheduling option changed,
  Must Finish By included); "remaining duration cut" on work not started (formulas.md §5).
- Supply chain (plan bloc F): the published images carry BuildKit's SLSA provenance
  (`mode=max`), an SPDX SBOM and a GitHub build-provenance attestation of their digest
  (AUDIT-DEP-02); CodeQL on the Python sources and the OpenSSF Scorecard run on `main`,
  pull requests and weekly (AUDIT-DEP-04); `tests/test_fuzz_parser.py` fuzzes the XER
  boundary with Hypothesis (`parse_bytes` and `build_snapshot` return a value or raise
  `XerError`, never another exception), 200 examples locally and 1000 under
  `HYPOTHESIS_PROFILE=ci`; this changelog.
- `docs/deploy.md`: how to read an image's digest from ghcr.io, verify its attestation, pin
  it in `.env` and bump it (AUDIT-DEP-01); how a release is cut; how to check with
  `docker inspect` that `TS_AUTHKEY` has left the tailscale container (AUDIT-DEP-03).

### Changed

- CPM: `TimeAxis.work` reads one timestamp with `bisect` on lists kept with the axis instead of a numpy
  call per value: a recalculation of the Hotel reference file (4 217 activities) takes 0.38 s instead of
  1.0 s, every schedule of the reference data and the P6 corpus unchanged to the minute.
- The pages, `streamlit_app.py` and the tests import each name from the module that defines it;
  `app/state.py` no longer re-exports what the other modules define. `tests/test_architecture.py`
  guards the app's import graph: the edges between the app modules written in the test, the baseline
  domain reading neither `state`, `loading`, `downloads` nor `cache`, `state.py` imported by the pages
  only, no cycle.

- `app/baselines.py` (1 338 lines) cut by responsibility, no behaviour changed (`scripts/same_code.py`:
  same code): `app/baseline_file.py` (the separate baseline file), `app/baseline_export.py` (the P6 XML
  export in use and the resolution), `app/baselines.py` (`baseline_for` and the paths that build the
  Baseline of an update), `app/baseline_window.py` (the window's Baseline section),
  `app/baseline_warnings.py` (the sidebar's Baseline line and its warnings), `app/cache.py` (`memo`,
  the checks' results, the score job); the parse cache and `_cache_for` in `app/session.py`, the exports
  and `costs_shown` in `app/downloads.py`. Dependencies run one way, no cycle; `state.py` keeps its
  re-exports; the tests patch the module that calls the patched name.

- Funnel stack, CVE-2026-97054 (Go `net/http`, fixed in Go 1.27.4): `tailscale/tailscale`
  v1.104.4 → v1.104.7 (Go 1.27.4); `deploy/caddy/Dockerfile` on Caddy 2.11.9 (its builder holds
  Go 1.27.4, the build checks it), x/net replaced by v0.63.0, the go-jose/v4 replace dropped (2.11.9 requires the
  fixed v4.1.6).
- Licence: from this change on the project is proprietary, all rights reserved (`LICENSE`,
  `NOTICE`, `pyproject.toml`); the revisions published before it were under Apache-2.0.
- `deploy/compose.yaml`: `:latest` stays the default for a first start, the documented
  setting for a NAS is a release tag with its digest (AUDIT-DEP-01).
- `deploy/caddy/Dockerfile`: the two `caddy:2.11.8` base images are pinned by digest, as the
  app's `Dockerfile` already pins its bases (AUDIT-DEP-01).
- `.github/workflows/image.yml`: the job declares its own permissions (`packages`,
  `id-token`, `attestations` write; `contents` read).

### Fixed

- Changelog: a scheduling option and its values are shown under the names of P6's Schedule Options
  dialog ("Define critical activities as: Longest Path"), not the codes of the file (`CT_DrivPath`).
- Delay analysis: a step counts the changes it carries; a rename or a move to another WBS is counted
  at no step (they were counted at the last one).
- Debug, block 3: the counts of the steps table are whole numbers.
- Baselines: "Link renumbered tasks by GUID" renamed the baseline's frame but not the tasks of its own
  file, so P6-13 counted a renumbered task as no longer in the schedule and the BEI due in the baseline
  lost it, while the earned value found it (`baseline.relinked`). A baseline of the P6 XML export that
  cannot be read stopped every page; its update now has no baseline and the sidebar names it. DCMA-13
  (CPLI) reads the baseline finish of the end milestone without a Must Finish By and did not name the
  baseline in its result; it does (`checks.BASELINE_READERS`). The Files and baseline window lists, once
  the files are read, the baseline each file names and what it is measured against; the sidebar's
  message on missing Project Baselines says that P6 writes none in an XER and asks for the P6 XML export.

- Delay analysis: the page no longer stops on a series where an update holds whole hours only and
  the next a fraction of an hour (a remaining duration of 19.2 h): the half-step schedule carries
  the value as it is.
- Parser and model: the findings of `audit-report.md` (AUDIT-XER, AUDIT-CPM, AUDIT-APP)
  closed by plan blocs A to E are listed here as they land; the crashes the fuzzer still
  finds are recorded in `tests/test_fuzz_parser.py` with their finding.

## [0.1.0] - unreleased

First tagged release: the XER parser and model, the CPM engine checked against P6 exports,
the P6 Check Schedule, DCMA DECM and DCMA 14-Point standards, earned value, PPC, MTA and the
changelog series, the Gantt, the Power BI export, the Streamlit app, the CLI and the Docker
and Tailscale Funnel deployment.

[Unreleased]: https://github.com/Xerscope/xerscope/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Xerscope/xerscope/releases/tag/v0.1.0
