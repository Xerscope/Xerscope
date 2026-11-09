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
