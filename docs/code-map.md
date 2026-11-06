# Code map and debugging guide

Where each concept lives, and where to look first when a number, a page or a file goes wrong.
For the narrative walkthrough read [architecture.md](architecture.md); for the arc42 views read
[architecture/](architecture/README.md). This page is the index you keep open while working.

## 1. The pipeline in one picture

```
 .xer bytes
    │  xer/parser.py      strings only; %T %F %R %E; encoding; warnings          → RawXer
    │  xer/validate.py    duplicates, time zones, bounds, negative / huge values   (warnings)
    │  xer/calendar.py    clndr_data → WorkCalendar → TimeAxis (exact working minutes)
    │  xer/model.py       one project, typed: tasks, relationships, assignments    → Snapshot
    ▼
 store.py              weekly series, one snapshot per data date                    → SnapshotStore
    ▼
 analysis/             cpm.py (recalculation) · rules.py + p6/ dcma/ decm/ integrity.py (checks)
                       standards.py (TOML) · checks.py (run) · explain.py (words)
                       evm.py · progress.py · changelog.py · baseline.py · wbs.py
    ▼
 viz/ (figures)   app/ (Streamlit pages)   cli.py (commands)   export.py (Power BI)   anonymize.py
```

Data flows one way. A layer imports only the layers above it in this picture;
`tests/test_architecture.py` fails on any other import.

## 2. Where is…

| You are looking for | File | Entry point | Its tests | Its doc |
|---|---|---|---|---|
| How a line of the .xer is split | `xer/parser.py` | `parse_bytes`, `parse_text` | `test_parser.py`, `test_fuzz_parser.py`, `test_audit_edges_xer.py` | architecture.md §1 |
| What a P6 column means (units, identity, best dates, % complete) | `xer/model.py` | `build_snapshot`, `Snapshot` | `test_model.py`, `test_reference.py` | architecture.md §2 |
| A value refused or repaired on read | `xer/validate.py` | one function per rule | `test_audit_edges_xer.py` | architecture.md §2 |
| Working time, holidays, hours ↔ days | `xer/calendar.py` | `WorkCalendar`, `TimeAxis`, `hours_to_days` | `test_shift_calendar.py`, `test_calendar_and_standards.py` | cpm.md "Time" |
| Which project of a file is read | `xer/model.py` | `_default_project`, `read_header` | `test_file_baseline.py`, `test_renumbered.py` | architecture.md §2 |
| The weekly series, duplicate dates | `store.py` | `SnapshotStore`, `DuplicateDataDate` | `test_store.py` | architecture.md §4 |
| Early / late dates, float, critical path | `analysis/cpm.py` | `schedule`, `_Run.forward`, `_Run.backward`, `_Run.floats` | `test_cpm.py`, `test_cpm_properties.py`, `test_p6_heldout.py`, `test_crosscheck_mpxj.py` | cpm.md |
| How a link bounds its successor | `analysis/cpm.py` | `_Run.pred_bounds`, `start_link`, `successor_limits` | `test_cpm.py` | cpm.md "Algorithm" |
| A constraint, an expected finish | `analysis/cpm.py` | `forward_constraints`, `expected_finish`, the constraint loop of `backward` | `test_cpm.py` | cpm.md |
| Resource-dependent activities | `analysis/cpm.py` | `rsrc_early`, `place_late` | `test_cpm.py`, held-out H8+ | cpm.md, backlog.md |
| Level of effort | `analysis/cpm.py` | `_Run.level_of_effort` | `test_cpm.py` | cpm.md "LOE" |
| A P6 Check Schedule check | `analysis/p6/check_schedule.py` | `p6_01_logic` … | `test_p6_check_schedule.py`, `test_p6_checksched.py` | standards.md |
| A DCMA 14-Point check | `analysis/dcma/fourteen_point.py` | `dcma_01_logic` … | `test_rules.py`, `test_standards_conformity.py` | standards.md |
| A DECM v8 check | `analysis/decm/schedule_metrics.py` | `decm_06a…` | `test_rules.py` | standards.md |
| Integrity (recalculation vs file) | `analysis/integrity.py` | `int_01_recalculated` … | `test_rules.py` | standards.md "Integrity" |
| A generic rule of your own standard | `analysis/rules.py` | `@rule` functions | `test_rules.py` | standards.md "Your own standard" |
| Who is counted (exclusions, funnel) | `analysis/populations.py` | `activity_funnel`, `without`, `EXCLUSIONS` | `test_rules.py`, `test_app_parity.py` | formulas.md |
| Targets, units, TOML validation | `analysis/standards.py` | `parse_standard`, `Metric.evaluate` | `test_calendar_and_standards.py`, `test_audit_edges_app.py` | standards.md |
| Running a standard, pass / fail | `analysis/checks.py` | `run_standard`, `run_metric` | `test_rules.py`, `test_scores.py` | — |
| The sentence under a result | `analysis/explain.py` | `explain` (reads the rule docstring) | `test_explain.py` | rules.py module docstring |
| Earned value, PV, SPI, BEI | `analysis/evm.py`, `analysis/baseline.py` | `pv_curve`, `ev_point`, `Baseline` | `test_pv_p6.py`, `test_spi_cost.py`, `test_weekly.py` | formulas.md, deep-dive/ev-gaps.md |
| Milestone trend, PPC | `analysis/progress.py` | `milestone_trend`, `ppc_series` | `test_weekly.py` | formulas.md |
| What changed between two files | `analysis/changelog.py` | `changelog` | `test_analysis_and_viz.py` | — |
| A chart | `viz/charts.py`, `viz/gantt.py` (+ `gantt.js`) | `build_*`, `gantt_data` | `test_viz.py` | — |
| A page | `app/views/<page>.py` | top-level script | `test_app.py` (renders every page headless) | — |
| Files window, baseline picker, caches | `app/state.py` | `sidebar_loader`, `require_store`, `memo`, `baseline_for` | `test_app.py`, `test_app_cache.py`, `test_app_background.py` | architecture.md §6 |
| Tables, KPIs, formats, chart wrapper | `app/ui.py` | `table`, `kpis`, `chart`, `fmt_date`, `fmt_number` | `test_app.py`, `test_table_filters.py` | — |
| Debug page tables | `app/diagnostic.py` | `options_table`, `recalculation_table` … | `test_diagnostic.py` | — |
| CSV safety | `csv_safe.py` | `csv_safe` | `test_audit_edges_app.py` | — |
| Anonymised downloads | `anonymize.py` | `Anonymizer` | `test_anonymize.py`, `test_anonymous_file_names.py` | architecture.md |
| Power BI export | `export.py` | `export_tables` | `test_downloads.py` | README |
| CLI commands | `cli.py` | `main`, `_cmd_*` | `test_cli.py` | README |
| Demo data | `sample.py` | `generate` | many | — |
| Independent checks (P6 corpus, MPXJ) | `verify/` (`crosscheck.py` façade) | `p6_heldout_score`, `cpm_crosscheck`, `compare_file` | `test_p6_heldout.py`, `test_crosscheck_mpxj.py` | cpm.md "Validation" |
| Tunable defaults | `config.py` | `Settings` | — | — |
| Deployment | `Dockerfile`, `compose.yaml`, `deploy/` | — | `test_docker.py` | deploy.md |

## 3. Debugging: symptom → first look

Run the command or open the doc in the "first look" column before reading code. Never put the
real file in an issue or a test: rebuild the shape with `tests/xerkit.py`.

| Symptom | First look | Then |
|---|---|---|
| A file does not load | the error text (it names the file and the table); `uv run xerscope info FILE.xer` | `xer/parser.py`, `xer/validate.py`; add the minimal bytes to `REGRESSIONS` in `tests/test_fuzz_parser.py` |
| A file loads with warnings | the warnings in the sidebar or `xerscope info` | `xer/validate.py` names each repair; architecture.md §2 |
| Wrong project read from a file | Files window, "Project read from each file · why" | `_default_project` in `xer/model.py` |
| Dates differ from P6 | `uv run xerscope recalc FILE.xer --report` (differences grouped by activity shape); Debug page, block "Recalculation" | cpm.md "Conventions no reference file settles" and backlog.md "CPM"; deep-dive/engine-gaps.md for the known families |
| Float differs, dates agree | cpm.md "Algorithm" (float type option) | `_Run.floats`, `total_float` |
| One activity looks wrong | Debug page with `XERSCOPE_DEBUG_PAGE=1`; the task panel on the Gantt page | the activity's options, constraints, expected finish and links in the Debug blocks |
| A check count differs from a P6 report | `uv run xerscope check FILE.xer --standard P6 --expect p6-summary.csv` | standards.md "Comparing with a P6 Check Schedule report"; the check's population lines in its docstring |
| A DCMA / DECM count looks off | the Audit page: the sets behind the count, and the check re-run with other settings | standards.md "Same check, several definitions"; formulas.md |
| A custom TOML is refused | the message names the file, the metric and the key | standards.md "Your own standard"; `analysis/standards.py` |
| EV / PV / SPI differs from P6 | Debug page blocks 08–10; `uv run xerscope pv-compare` with a P6 Activities CSV | formulas.md EV section; deep-dive/ev-gaps.md (known conventions and their effect) |
| A page crashes or shows nothing | the terminal running `xerscope app` (tracebacks go to the log, not the page, in the remote stack) | `tests/test_app.py` renders every page headless: reproduce there |
| A page is slow | the series reads in the background (`LoadJob`); `XERSCOPE_SYNC_LOAD=1` to read synchronously | `memo` keys in `app/state.py`; `test_app_cache.py` |
| Something wrong in a CSV / Power BI table | open the Parquet export (untouched by `csv_safe`) | `export.py`, `csv_safe.py` |
| The remote stack does not answer | deploy.md §9 checklist | `tests/test_docker.py` pins what the stack must keep |
| CI red on `attribution` | the job prints the offending line | CONTRIBUTING.md "Commits and pull requests" |
| CI red on a held-out floor | `uv run pytest tests/test_p6_heldout.py -q` prints the set and its share | never lower a floor: find what regressed (cpm.md "Validation") |

## 4. Debug switches

| Switch | Effect |
|---|---|
| `XERSCOPE_DEBUG_PAGE=1` | shows the Debug page (always shown locally; hidden on a locked instance) |
| `XERSCOPE_SYNC_LOAD=1` | reads the series in the page run instead of a background thread |
| `xerscope recalc --report` | differences between stored and recalculated dates, grouped by shape |
| `xerscope recalc --show CODE` | one activity's recalculation |
| `xerscope crosscheck --p6 <set folders>` / `--cpm FILE.xer` | score against the P6 held-out corpus / against MPXJ's scheduler (needs `uv sync --extra crosscheck`, a JDK and `tests/reference/mpxj_cpm.py`) |
| `xerscope check --flagged DIR` | one CSV per check with the flagged activities |
| Debug page, "Download diagnostic (.zip)" | a zip of every Debug table, anonymised when "Anonymous exports" is on |

## 5. Documents to read, by task

| Task | Read, in this order |
|---|---|
| First day on the code | README → this page → architecture.md → CONTRIBUTING.md |
| Change the engine | cpm.md (whole) → deep-dive/engine-gaps.md → architecture/13 §13.3 P1 |
| Add or change a check | standards.md → formulas.md → rules.py module docstring |
| Earned value | formulas.md → deep-dive/ev-gaps.md |
| Pages and UI | architecture.md §6 → app/ui.py docstrings → visual-debug-report.md |
| Deploy, security | deploy.md → SECURITY.md → audit-report.md §2 (DEP rows) |
| Plan the next work | backlog.md → maintenance.md → conformity-plan.md (bloc G) |
