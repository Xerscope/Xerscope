# Quality plan (global audit of 2026-11-22)

Scope: the whole repository. Source: eight independent read-only reviews (xer, analysis, app and
viz, structure, performance at scale, shipped features driven as a planner, cli and deployment,
tests and documentation), every bug claim reproduced by a second reviewer before it is listed here.
Method unchanged: Problem / Options / Choice / Verification written and agreed before code; one PR
per item, 400 lines at most, byte-identical moves proved by `scripts/same_code.py`; no exception
marker added to pass a check. `analysis/cpm.py` and `analysis/evm.py` belong to the engine session:
their items are handed over, not done here.

Each item carries its status: **Done** (the commit, and the pull request that merged it),
**Open**, or **Partial** (what remains). File and line coordinates are those of the audit.

Measured on a scaled series (8 files of 26 MB, 58 000 activities each), the maintainer's symptom
reproduced: load + Overview 46-54 s plus 81 s of standards scoring, Health DCMA 69-93 s, INTEGRITY
89-95 s, Earned value 16-19 s, Debug 67 s, Forensics about 13 minutes, 3.6 GB resident after the
pages. One `cpm.schedule` takes 15 s at this size, half of it in `TimeAxis.work` called 888 000
times on one-element arrays; the pages then run it many times.

## Q1 — Confirmed bugs (one PR each, S)

| Id | Where | Defect | Fix | Status |
|---|---|---|---|---|
| ANALYSIS-01 | `analysis/forensics.py:445` | `finish_case` reads a completed activity carrying a Mandatory Finish as what holds the project finish | exclude completed activities before the constraint test; failing-before test | Done in 1078784, refined in 0ba043f (a Mandatory Finish holds the finish only when it carries the project's early finish, read before a Must Finish By) (#344) |
| APP-01 | `app/cache.py:116` | the Overview score job is keyed on standard ids: a standard re-uploaded under the same id is never scored and the fragment polls every second for ever | key on the standards' content digest; stop polling on a settled error | Done in 578339b (#344): keyed on each standard as written (`_score_identity`), errors settled (`score_errors`) |
| APP-02 / FEAT-12 | `app/baseline_warnings.py:310` | "no task is linked" and "n tasks linked by GUID" drawn together; the GUID warning fires with nothing renumbered | one line per update, warning only when renumbered tasks stay unlinked (P18 appendix H) | Done in 79dd286 (#344); the reason documented for a P6 XML baseline (no GUID) in 62e4059 (#347) |
| APP-03 | `app/views/gantt.py:202` | two "Did you mean" buttons share a key when a WBS node and a resource carry the same label: the page stops | key on kind + label | Done in c12e07b (#344) |
| TOOLS-01 | `cli.py:335` | `recalc FOLDER --out FILE` writes every file's CSV to one path | one file per input, or refuse `--out` with a folder | Done in 3b70d2d (#344): several files, given or found in a folder, write `<file>_<FILE>` each |
| FEAT-02 | `app/views/forensics.py:145` | five tables without a reading, invisible to the coverage test | readings in `explain.READINGS`; test tightened to every `ui.table` | Done in 74158cd (#344) |

Risks to decide with the maintainer, same form:

- XER-01 (unreadable number or date reads as blank with no warning; one `validate.py` rule).
  Done in a122f44 (#349): `validate.unreadable_cells` and `validate.unreadable_status_date`.
- XER-05/06 (`%E` followed by a tab, two trailing tabs on `%F` refuse a valid file). Open
  (`xer/parser.py`; in docs/backlog.md, App).
- ANALYSIS-10 (06A506a flags rows outside its checked population). Open.
- TOOLS-05 (anonymiser never searches numeric Activity IDs). Open.
- TOOLS-11 (a `v*` tag publishes without the pull-request gates). Open.
- TOOLS-12 (`main()` files every `ValueError` as bad input). Open: `cli.main` still turns any
  `ValueError` or `OSError` into an input message.
- FEAT-07 (Debug and PPC read the window's baseline while Health reads the file's). Open:
  Health, Audit and Gantt read `baseline_for_checks` (P17, #342); Debug and PPC read
  `baseline_for`.

## Q2 — Performance outside the engine (ordered by gain per line)

1. **PERF-02** `xer/calendar.py:477`: scalar path with `bisect` on cached lists in `TimeAxis.work`
   (8.1 µs → 0.5 µs per call): about −40 % on every schedule, `cpm.py` untouched. Proof: same
   dates on every reference file, hand cases, timing before/after. S.
   Done in fe91302 (#346): a recalculation of the Hotel reference file 1.0 s → 0.38 s, every
   reference schedule and the P6 corpus unchanged (`tests/test_time_axis_scalar.py`).
2. **PERF-01 / APP-05 / ANALYSIS-02** Forensics: the half-step series computed on request (a
   button, as the Overview's scores), one memoised `HalfStep` per pair shared with the picked pair,
   unchanged steps not rescheduled (36 of 114 on the demo). 13 min → the pair shown only. M.
   Open: the Delay analysis page computes `half_step_series` on its first draw, with no button
   (`memo` keeps it once per data set), and no `HalfStep` is shared per pair: unchanged steps are
   still rescheduled.
3. **PERF-06 / ANALYSIS-05** DCMA-12 and 06A401a share one 600-day critical path test per update
   (one `memo` on the snapshot). About −30 s per scored update at scale. S. Open: each rule calls
   `rules.critical_path_output`, which runs `cpm.critical_path_test` again.
4. **PERF-07** `analysis/changelog.py:56`: `Series.map` instead of `.loc` per change row
   (5.6 s → 1.0 s on 58 000 activities), the rest of `_to_frame` vectorised. S. Open.
5. **PERF-10 / ANALYSIS-03 / APP-06** `progress.lookahead_series` and `ppc_series` build each
   week's `committed(W−1, W)` once (61 of 141 calls are repeats). S. Open.
6. **PERF-08** the Overview scores the four standards on the latest update right after the load
   (81 s at scale): score on request or P6 first and the others when asked. Maintainer's call. S.
   Open: with background jobs on, the score job starts after the load; the "Compute scores"
   button serves only when they are off (`XERSCOPE_SYNC_LOAD`).
7. **PERF-11** Debug block 14 folds 1.9 M cells inside a closed expander: compute when opened. S.
   Open.
8. **PERF-14 / APP-08** memory: raw file bytes kept for the session's life (about 1 GB for twenty
   exports) and schedule frames held per page; drop the bytes once parsed, bound the memo. M.
   Open (docs/backlog.md, App).
9. **PERF-09** `MAX_WORKERS = 2` is the NAS limit written as a constant: a `Settings` value. S.
   Open: `MAX_WORKERS` is still a constant of `app/reading.py`; `XERSCOPE_LOAD_WORKERS` only
   lowers it.

Handed to the engine session (reported with numbers in the perf report): PERF-03 (`_Engine.result`
per-activity Python, 26 s of 31), PERF-04 (`_comparison` reads 900 000 scalars with `.at`), PERF-05
(`compare_assignments` not cached on the snapshot, 11-13 s twice), PERF-12 / APP-07 (`weekly_gains`
recomputes `earned` 40 times), ANALYSIS-11 (hidden import of `evm.performance_pct` in
`progress.py`). Open, all five: `_comparison` still reads with `.at`, `compare_assignments` is
called uncached by `integrity.py` and `app/diagnostic.py`, `progress.py` still imports
`performance_pct` inside a function.

A test bounds each fixed page (TST-15): call counts of `cpm.schedule`, `committed`, `to_datetime`
on the demo in `tests/test_app_cache.py`, failing before each fix. Open: no such count in
`tests/test_app_cache.py` yet.

## Q3 — Structure (byte-identical moves, in this order)

Measured: 27 files over 400 lines; `app/` 26 flat modules, `analysis/` 20; `xer/model.py` 1 708
lines, cohesion 0.12, rank C; `cli.py` 54 functions, rank C; `app/ui.py` 430 lines of constants
before its first function; `views/debug.py` a 530-line script. The import-graph test does not see
`from xerscope.app import ui` (11 modules) nor the pages (fixed first by the tests session, B1).
B1 done in d50b380 (#343): `tests/test_architecture.py` reads every import form of an app module
and lists every module.

1. `app/baseline/` (`baseline_file`, `baseline_export`, `baselines`, `baseline_window`,
   `baseline_warnings`, `xml_baselines`; `baseline_resolution` is in `analysis/`) and
   `app/files/` (files_window, loading split into load_job, lexicon, sidebar); `APP_EDGES` keyed
   on the package. The 46 private names imported across modules lose their underscore first (one
   name per concept). M. Open.
2. `app/ui.py` → `app/ui/columns.py`, `format.py`, `tables.py`, `figures.py`, `runtime_table` to
   `diagnostic.py`; `ui.py` re-exports nothing, callers import the module they need. M. Open
   (`app/ui.py` 985 lines; the theme and the table filters already left it for `app/theme.py` and
   `app/table_filters.py`, #340).
3. `views/debug.py` and `views/gantt.py` as `show_<block>()` functions; `show_calculation` of
   Earned value split. S each. Open.
4. `xer/model/` by P6 concern (dates and numbers, tasks, links, assignments, WBS, calendars,
   options, baseline pointers, header), `__init__` re-exporting the 15 pinned names. L, after the
   calendar change (Q2.1), which has landed. Open.
5. `cli/` package, the lexicon build service to `analysis/ask/build.py`. M. Open.
6. `analysis/` sub-packages (checks machinery, weekly series, baseline) once the engine session's
   work merges, with it. L. Open.
7. Tests: `tests/app/test_<page>.py` from `test_app.py` (3 127 lines at the audit, 3 198 now),
   fixtures once in `conftest.py`, one module-scoped app per page file (154 launches at the
   audit). M. Open.

Practice counts to ratchet in `scripts/fitness.py` (TOOLS-08: lines per file, longest function):
56 functions nested deeper than 2, 70 nested comprehensions, 254 single-letter names, 79
abbreviations, 13 `df`, 39 bool functions without `is_`/`has_`, 67 of 95 files on the docstring
exemption list. Each move rewrites nothing; the rename-on-touch rule applies. Open: `fitness.py`
ratchets the maintainability rank, complexity, exact clones, mypy errors, deptry violations and
broken import-linter contracts, not these counts.

## Q4 — Messages (P18, `docs/refactor-front-plan.md` P18 and appendix H)

Confirmed by the features review on a real-shaped series: a 114-word red error repeated per file,
a GUID warning with nothing renumbered, "Pick one in the sidebar" where no picker exists, a server
path and an environment variable in a user error, one yellow line per file on the Overview for a
normal two-project file, readings and helps carrying stale `file.py:line` coordinates (FEAT-01,
03, 05, 09, 10, 11, 13, 14, 15).

Partial: the GUID warning is fixed (APP-02 / FEAT-12, Q1). The rest is open: "Pick one in the
sidebar" is still on Schedule health, and readings in `analysis/explain.py` still cite
`charts.py:` and `explain.py:` lines.

## Q5 — Demo and tests that see the features (TOOLS-07, L)

The demo carries no in-file baseline, no GUID, no calendar exception, no Must Finish By, no cost,
no SF link: 7 metrics never evaluated, 29 never flag, the baseline banner and the renumbered
warning never drawn in a test. Extend `sample.py` with each shape as a planted finding, then the
goldens show them. After it, the features of Q4 and the readings of Q1 have a test surface.

Open.

## Documentation and tests (tests session, tracks A and B)

TST-01..08 (TOOLS-03, the sign of `finish_shift_wd` in formulas.md, with them), TST-11..14, TST-16..18 and the six points of the front audit (import guard, docs
artefacts, architecture.md and CHANGELOG drift, weak tests) are the tests session's tracks; this
plan does not duplicate them. The full reports stay outside the repository.

Partial: the import guard is done (d50b380, #343); the CHANGELOG covers the merged pull requests;
the other items are tracked in those reports, not here.

When an item is done it keeps its line here with its status; what stays open at the end moves to
`docs/backlog.md` and this file is deleted.
