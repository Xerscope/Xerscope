# 1. Introduction and goals

## 1.1 Requirements overview

xerscope reads weekly Primavera P6 exports (`.xer`) and reports on them the way a planning engineer
would read them in P6 Professional 24. Its value, stated in `CONTRIBUTING.md` and the module
docstrings, is that **its numbers are the numbers P6 or the standard would give, and every number
can be traced to a formula, a population and a source**.

Functional scope, as implemented (`README.md`, `cli.py`, `app/streamlit_app.py`):

| Capability | Where | Evidence |
|---|---|---|
| Parse one project out of an XER export into a typed `Snapshot` | `xer/parser.py`, `xer/model.py` | `tests/test_parser.py`, `tests/test_model.py` |
| Hold a weekly series, one snapshot per data date | `store.py` (`SnapshotStore`) | `tests/test_store.py` |
| Recalculate the schedule as P6 does (early/late dates, floats, longest path, assignments) | `analysis/cpm.py` | `tests/test_cpm.py`, `tests/test_p6_heldout.py` |
| Run schedule-quality checks: P6 Check Schedule, DCMA DECM v8.0, DCMA 14-Point, Integrity, custom TOML | `analysis/p6/`, `dcma/`, `decm/`, `integrity.py`, `rules.py`, `standards/*.toml` | `tests/test_rules.py`, `tests/test_characterization.py` |
| Explain every result (formula, verdict, population, parameters, source) | `analysis/explain.py`, `analysis/audit.py`, `sheets/P6/*.md` | `tests/test_explain.py`, `tests/test_sheets.py` |
| Weekly series analyses: changelog, earned value, milestone trend, PPC, WBS roll-up | `analysis/changelog.py`, `evm.py`, `progress.py`, `wbs.py` | `tests/test_weekly.py` |
| Web app (Streamlit) with eleven pages | `app/` | `tests/test_app.py` |
| Command line (`app`, `check`, `recalc`, `changelog`, `standards`, `export`, `crosscheck`, `pv-compare`, `info`, `sample`) | `cli.py` | `tests/test_cli.py` |
| Power BI star-schema export (Parquet or CSV) | `export.py` | CI smoke test in `.github/workflows/tests.yml` |
| Anonymised copies of files and downloads | `anonymize.py` | `tests/test_anonymize.py` |
| Independent verification against P6's corpus and MPXJ | `verify/`, `crosscheck.py` | `tests/test_p6_heldout.py`, `tests/test_crosscheck_mpxj.py` |
| Hardened container, optional remote stack (Tailscale Funnel + Caddy) | `Dockerfile`, `compose.yaml`, `deploy/` | `tests/test_docker.py` |

## 1.2 Quality goals

The five goals below are the ISO/IEC 25010 reading of the four non-negotiables in
`CONTRIBUTING.md` ("P6 semantics come from Oracle", "No real schedule enters the repository",
"A number changes only with evidence", "Simple over clever") and of the security section of
`SECURITY.md`. They are ordered; when two conflict, the higher one wins.

| # | ISO 25010 characteristic | Goal as the project states it | How the architecture serves it |
|---|---|---|---|
| 1 | **Functional correctness** | P6 reference files reproduced to the minute; checks follow the text of their standard | `TimeAxis` exact minute arithmetic; one function per check reading like its source; held-out `FLOORS` that never drop (`tests/test_p6_heldout.py`) |
| 2 | **Confidentiality** (security) | No real schedule in the repository, in the image or in a log; schedules stay on the user's machine | `tests/xerkit.py` builds test files in code; pinned public reference files; localhost binding; anonymised downloads by default; Caddy log redaction |
| 3 | **Analysability** (maintainability) | Every number traceable to a formula, a population and a source | `RuleOutput.funnel` (named, sourced steps); `explain.py`; `audit.split`; `docs/formulas.md`; `source` field of every TOML metric |
| 4 | **Modifiability** (maintainability) | One place per P6 concept; a difference between standards is data, not a branch | Layer rules enforced by `tests/test_architecture.py`; TOML-parameterised rules; `config.Settings` for the few tunables |
| 5 | **Resistance / integrity** (security) | A crafted `.xer` fails to load, it never executes or escapes | Parser keeps every value a string; model types it; `XerError` on a malformed file; no `eval`, no HTML from file text |

Performance efficiency is a stated secondary goal: `docs/cpm.md` records that a 4,217-activity
file schedules in about 2 s and that the plain recalculation is cached on the snapshot.

## 1.3 Stakeholders

ISO/IEC/IEEE 42010 asks for stakeholders and their concerns; the viewpoints that address them are
the sections of this set.

| Stakeholder | Role (from the docs) | Concerns | Addressed in |
|---|---|---|---|
| Planning engineer | Loads weekly exports in the app, reads health, Gantt, EV, PPC | Numbers equal to P6's; explanations under every check; nothing leaves the machine | 3, 6, 8, 10 |
| Project controls reviewer | Compares a P6 Check Schedule report with `xerscope check --expect` | Same counts as P6 line by line; the items behind each count (`--flagged`) | 5, 6 |
| Remote viewer | Opens the app through Tailscale Funnel on a locked-down laptop | A password, a URL, no install; no upload path, no traceback | 7 |
| Operator (PC or NAS administrator) | Runs `compose.yaml` or `deploy/compose.yaml` | No published port, read-only, bounded memory, pinned images, how to update and roll back | 7, 11 |
| Power BI analyst | Reads `dim_snapshot` and `fact_*` tables | Stable column set (`HISTORY_COLS`), one key (`snapshot_idx`, `task_code`) | 5, 6 |
| Maintainer / contributor | Changes a rule, the CPM, a page | Where a change goes; the verification gate; layer rules; evidence before a number moves | 2, 4, 5, 8, 9 |
| Security reviewer | Reviews the image and the Funnel stack | Trust boundary at the parser, supply chain, logs without secrets | 7, 8, 11 |
| Oracle P6 and the standards (DCMA, DECM) | Not people, but the sources every behaviour is held against | A behaviour without a source is an open question, not a guess (`crosscheck.UNRESOLVED`, `docs/cpm.md`) | 4, 9 |
