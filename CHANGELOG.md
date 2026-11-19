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
