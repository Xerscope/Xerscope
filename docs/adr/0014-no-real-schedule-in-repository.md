# ADR-0014: No real schedule in the repository: tests build files in code or fetch pinned public files

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`49ad764`, "initial git commit": `tests/xerkit.py`, `tests/reference/sources.py` and `fetch.py`, `src/xerscope/sample.py` already there); the rule written on 2026-11-02 (`9ef651d`, CONTRIBUTING.md Rule 1, #22); the CI guard and `.gitignore` entries on 2026-11-02 (`6d7f09a`, "Keep schedules out of git and bound the remote app's log") |
| Scope | `.gitignore`, `.github/workflows/tests.yml` (job `lint`), `tests/xerkit.py`, `tests/pmxmlkit.py`, `tests/file_projects.py`, `tests/reference/` (`sources.py`, `fetch.py`, `fetch_p6_heldout.py`, `expected.py`), `tests/test_p6_witness.py`, `tests/conftest.py` (`missing`), `src/xerscope/sample.py`, `src/xerscope/cli.py` (`sample`) |
| Sources | [CONTRIBUTING.md](../../CONTRIBUTING.md), Rule 1; [docs/architecture.md](../architecture.md) §9; `.github/pull_request_template.md`, checklist; commits `49ad764`, `9ef651d`, `6d7f09a`, `8f2f7a8` ("Clean/witness", #62), `6efeb22` ("Audit reports out of the repository") |

## Context

The repository is public. The schedules xerscope is built for are confidential: an
activity name, a project code, a company name or a file path can identify a client or a
site. Git keeps a file in its history after it is deleted, so a schedule committed once is
published for good. A `git add .` next to the default export folder of the compose files
(`exports/`) would have published real exports before `6d7f09a`.

The tests still need schedules: small ones whose expected numbers a reader can count, and real
P6 exports whose stored dates and stated results prove the reader and the engine (ADR-0005,
ADR-0008).

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Commit real or lightly edited exports as test fixtures | none at first | confidential data public and in history for good; hand-anonymisation is error-prone |
| Vendor third-party sample files into the repository | simple, offline | licences (MPXJ is LGPL, xerlock AGPL) and no check that the file is the one its stated results describe |
| **Files built in code, public third-party files pinned by commit and SHA-256 and downloaded, local-only witness folders, a generated demo series, and a CI guard on tracked file types (chosen)** | builders to maintain; a fetch step in CI; real-schedule witnesses run by hand only | real-schedule evidence never runs in CI; a guard by extension does not see a schedule pasted into a text file |

## Decision

**Rule** (CONTRIBUTING.md Rule 1). Real `.xer` files, their activity names, project codes,
company names and file paths are never committed, nor quoted in docs, tests, issues, pull
requests or commit messages. The pull request template repeats it as the first checklist item.

**Files built in code.**

- `tests/xerkit.py` builds tiny XER files in tests (numeric ids, full calendars written out as
  P6 writes them, `clndr_data`, constants such as `MON_FRI_8H`), so each expected number is
  countable by hand and any reader (xerscope, MPXJ, P6) sees the same working time.
- `tests/pmxmlkit.py` builds tiny P6 XML exports (a project, its `BaselineProject` elements, a
  calendar) the same way; `tests/file_projects.py` holds XER text with two projects in one file.
- `src/xerscope/sample.py` (`generate`, default 8 weeks, seed 7) generates a realistic weekly
  series rescheduled week by week, with findings planted on purpose (a lead, an open end,
  activities without resources, a high duration, a hard constraint turned to negative float, a
  logic change, an actual date after the data date, a scope addition, `task_id` changing in
  every file while `task_code` stays). `xerscope sample [--out data/sample] [--weeks 8]`
  writes it; `tests/conftest.py` builds it for the suite (`sample_dir`, `store`).

**Public files, pinned, never vendored.** `tests/reference/sources.py` pins each third-party
file by the commit of its repository and its SHA-256 (`FILES`: local name -> (url, sha256)),
so the stated results of `tests/reference/expected.py` cannot drift from the files they
describe. `tests/reference/fetch.py` downloads them into `tests/reference/data/` (git-ignored)
and refuses a file whose checksum differs. `tests/reference/fetch_p6_heldout.py` checks out
the P6-scheduled held-out corpus at `P6_HELDOUT_COMMIT` (sparse, blob-filtered). CI caches
`tests/reference/data` keyed on the hash of these three scripts and fetches before the tests.

**Real-schedule witnesses stay local.** `tests/test_p6_witness.py` compares xerscope's P6
Check Schedule with P6 Professional 24 reports on real schedules. Each witness is a folder
under `tests/reference/data/witness/` (git-ignored) holding one anonymised `.xer` (the app's
anonymised XER extract, ADR-0015), an optional anonymised `baseline.xer`, and `expected.csv`
(`id,found,total`). Without a folder the test skips through `missing("witness", ...)`; CI's
`XERSCOPE_REQUIRE` does not name `witness`, so CI never runs it. It is run by hand before
merging a change to the checks or the CPM (`XERSCOPE_REQUIRE=witness uv run pytest
tests/test_p6_witness.py`).

**Guards.** `.gitignore` lists `data/`, `export/`, `exports/`, `*.xer`, `*.XER`,
`tests/reference/data/`. The `lint` job of `.github/workflows/tests.yml` has the step "No
schedule or data export is tracked (the repository is public)":
`! git ls-files | grep -iE '\.(xer|parquet|xlsx?|csv)$'`, so a tracked `.xer`, `.parquet`,
`.xlsx`, `.xls` or `.csv` (any case) fails the run. Session material is not kept in the
repository either: the audit reports were removed in `6efeb22`, their findings going into the
pull requests that act on them.

## Consequences

Positive:

- Nothing confidential can enter the repository by a file of a schedule type, and every test
  input is either countable by hand or traceable to a public commit and checksum.
- Third-party licences are respected: the files are fetched, not redistributed.
- The demo series gives the app, the golden files (ADR-0011) and the CLI smoke test of CI a
  realistic input with known findings.

Negative:

- Evidence on real schedules (P6 reports on client files) never runs in CI; it depends on the
  maintainer running the witness test before a merge.
- The guard is by extension: a schedule renamed or pasted into another file is caught only by
  review.
- CI depends on the third-party repositories staying reachable (mitigated by the cache).

Follow-ups: [docs/backlog.md](../backlog.md), "Proof: get an oracle for what has none" (more
P6 Check Schedule reports on shareable files).

## Verification

- `tests/test_docker.py::test_schedules_stay_out_of_git`: `exports/a.xer`, `deploy/a.xer`,
  `a.XER`, `data/a.xer`, `export/a.csv` are ignored by git; `git ls-files` lists no file of
  the guarded types; the `lint` job keeps its `git ls-files | grep -iE` step.
- `tests/test_p6_witness.py::test_p6_check_schedule_reproduces_the_witness_report` (skips
  without a local witness folder).
- `tests/test_reference.py` and `tests/test_characterization.py::test_reference_files_match_golden`
  on the fetched files; `tests/test_analysis_and_viz.py` (`test_planted_*`) on the demo's
  planted findings.
- CI: `.github/workflows/tests.yml` job `lint` (the tracked-file step) and job `test`
  (reference cache, `fetch.py`, `fetch_p6_heldout.py`, `XERSCOPE_REQUIRE: reference,p6-corpus`,
  CLI smoke test on `xerscope sample`).

## References

- `tests/xerkit.py`: `clndr_data`, `MON_FRI_8H`; `tests/pmxmlkit.py`: `WORKDAY`, `EXCEPTIONS`.
- `tests/reference/sources.py`: `FILES`, `P6_HELDOUT_COMMIT`, `P6_HELDOUT_REPO`;
  `tests/reference/fetch.py:fetch`; `tests/reference/fetch_p6_heldout.py:fetch`.
- `tests/conftest.py`: `missing`, `REFERENCE_HINT`, `P6_CORPUS_HINT`, fixtures `sample_dir`, `store`.
- `src/xerscope/sample.py:generate`; `src/xerscope/cli.py`: `_args_sample`, `_cmd_sample`.
- [CONTRIBUTING.md](../../CONTRIBUTING.md), Rule 1; [docs/architecture.md](../architecture.md) §9.
- Related: ADR-0005 (P6 as the reference), ADR-0008 (evidence hierarchy), ADR-0011 (golden
  files), ADR-0015 (anonymised downloads).
