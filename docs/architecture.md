# Code walkthrough

Data flows one way:

```
.xer bytes ─▶ parser ─▶ RawXer ─▶ model ─▶ Snapshot ─▶ SnapshotStore ─▶ analyses ─▶ pages / CLI / Power BI
             (format)            (P6 meaning)      (weekly series)
```

`xer/__init__.py` is the entry most callers use: `load_snapshot(source, project_code=, name=,
project_id=, pmxml_index=)` reads a path or the bytes of one file (an XER, or a P6 XML export read for
one of its baselines) into a `Snapshot`; `load_header(path)` reads only what the file picker shows;
`xer_files(folder)` and `pmxml_files(folder)` list a folder's `.xer` and `.xml` files.

## 1. `xer/parser.py`: the file format

The XER format is tab-separated:

- `ERMHDR` line: version and export date;
- `%T` starts a table, `%F` gives its fields, `%R` is a row, `%E` ends the file.

`parse_bytes` behaviour (`decode_xer`, then `parse_text`; `read_xer` for a path):

- **Encoding:** a UTF-16 or UTF-32 byte order mark is honoured (`XerError` when the bytes do not
  decode as it); otherwise UTF-8 (with or without BOM), then cp1252, which is what P6 writes on
  Windows. Bytes neither reads are replaced, with a warning.
- **Lines:** read in one pass, split on `\n` only, because calendar blobs can contain `\r` and task
  names characters `splitlines()` would break on.
- **Rows:** padded or cut to the field count of the `%F` line as they are appended; `%R` rows outside
  a named `%T` table are skipped, with a warning.
- **Values:** everything is kept as **strings**. The parser knows the format, not P6.
- **Structure P6 never writes:** a table written twice or a column named twice in a `%F` line
  raises `XerError`; so does a file with neither `ERMHDR` header nor table. Lines after `%E` are
  not read.
- **Tabs an editor leaves:** spaces or tabs after `%E` still end the file, and blank names after
  the last column of a `%F` line are dropped (`_Table.fields`); a blank or repeated name before
  the last column is still refused (XER-05/06).

Output: `RawXer(tables: {name: DataFrame[str]}, source, version, export_date, encoding, warnings, header, ended)`.
`ended` is False when the file has no `%E` line; the parse still succeeds (the file picker reads
the header of a file being copied) and `build_snapshot` refuses it.

**Load contract.** `build_snapshot` returns a `Snapshot` or raises `XerError`, nothing else,
whatever the file holds: cut short, keys repeated (`task_id`, `wbs_id`, `clndr_id`), identity
columns missing, values unreadable, dates outside 1900-2199 or numbers infinite (both read as
blank). `tests/test_load_contract.py` documents each case and checks the contract over every
table and column of a file built in code.
`keep=` keeps only the named tables, each with the listed columns (the rows of the others
are not split).

## 2. `xer/model.py`: what P6 means

`build_snapshot(raw)` picks one project (`project_id` or `project_code` when given) and builds
a typed `Snapshot`; `project_task_counts` and `selected_by` record that choice. By default
(`_default_project`) the baseline copies are set aside (a project another one names as its
Project Baseline, `sum_base_proj_id`, or copied from a project of the file, `orig_proj_id`),
then the most `TASK` rows win, then the latest data date, then the first in the file; when
every project is a baseline copy, the most `TASK` rows, then the first in the file. `read_header(raw)` applies the same project and data-date rules to
`PROJECT` and `TASK` alone (`HEADER_TABLES`): the folder picker describes each file with it
before the file is read, and a test checks it against `build_snapshot` on the sample and
reference files. Each P6 rule lives in one place:

| Concern | Rule |
|---|---|
| Identity | Activities keyed by `task_code` (Activity ID), not `task_id`, which changes on re-import |
| Data date | `PROJECT.last_recalc_date`, else the planned start (`plan_start_date`) |
| Units | durations and float stored in hours; `_d` columns are working days of the activity's calendar (`day_hr_cnt`) |
| Lag | `lag_hr` as stored; `lag_d` on the predecessor's calendar (Oracle's conversion rule) |
| Critical | project definition: total float ≤ `critical_drtn_hr_cnt`, or longest path (`critical_path_type`); `Settings.critical_float_days` when the file sets no threshold |
| % complete | by `complete_pct_type`: physical, duration, units (`percent_complete`) |
| Best dates | `start` / `finish` = actual > remaining early (`restart_date` / `reend_date`) > early > planned (`forecast_dates` for the remaining early dates) |
| Forecast finish | latest activity finish (`scd_end_date` can be stale: kept as `scheduled_finish`, with a warning) |
| Labour hours | TASK budgeted/actual/remaining labour units (nonlabor in `nonlabor_budget_qty`, `nonlabor_actual_qty`, `nonlabor_remaining_qty`), else assignments by resource type |
| Assignments | `assignments` = TASKRSRC typed: resource type (TASKRSRC, else RSRC; `role` for role-only), name, resource calendar, driving flag, units, rates, lags, dates |
| EV technique | `ev_compute_type` / `ev_user_pct` of each activity's WBS; `Snapshot.wbs` also holds `ev_etc_compute_type` / `ev_etc_user_value` (ETC technique, reported, not applied) |
| Links | `relationships`: codes and both lags (hours and days); `is_external` flags a predecessor in another project. A predecessor that is a `TASK` row of another project of the same file is named `[ext]<task_id>` in `pred_code`, as in `external_links`, never by its own Activity ID: that ID may also exist in this project and would read as a link from the local activity. Links whose other end has no `TASK` row in the file are dropped from `relationships` (counted in `external_links_dropped`). `external_links` keeps the links to and from other projects (same `[ext]` naming) |
| Calendars | `work_calendars` (parsed `clndr_data`), `calendar(id)` falls back to the project's |
| Options | `options["sched"]` = the raw SCHEDOPTIONS row, `options["project"]` = the raw PROJECT critical-path and plan-end fields, `options["export"]` = the P6 version and product of the `ERMHDR` line, `progressed` (retained logic / progress override / actual dates), `must_finish_by`, `lag_calendar` (successor when blank, per Oracle), `critical_path_type`, `critical_float_hr` |
| Projects of the file | `file_projects`: one row per `PROJECT` row (TASK rows, `sum_base_proj_id`, `orig_proj_id`, the project settings); `file_baseline` reads the Project Baseline pointer from it (section 5) |

`Snapshot.activities` excludes WBS summary rows: every count and chart uses it.

**Snapshot contract.** `model.py` declares the minimum columns of each frame: `TASK_COLS` plus
`LABOR_COLS` for `tasks`, `REL_COLS_MODEL` for `relationships`, `ASSIGNMENT_COLS_MODEL` for
`assignments`. `build_snapshot` raises `XerError` if one is missing, and the store's
`HISTORY_COLS`, `REL_COLS` and `ASSIGNMENT_COLS` must be subsets (checked in `tests/test_store.py`).
The frames may carry more (raw XER columns); the lists are a floor, not a filter.

**Value checks.** `xer/validate.py` holds one function per rule on a file's values (`unique_rows`,
`unreadable_cells`, `bounded_sequence`, `usable_hours`, `nonnegative_remaining`, `placeholder_clashes`…):
each repairs the frame the way the rule says (a duplicate key keeps its first row, an unusable number
reads as 0, an unknown link type is dropped) and adds one line to the snapshot's warnings, so the CPM,
the checks and the pages receive values that are unique, finite and bounded. Nothing there reads P6
semantics.

## 3. `xer/calendar.py`: working time

- **`WorkCalendar`:** working periods per weekday plus dated exceptions, parsed from the
  `clndr_data` tree `(0||name(attrs)(children))` (`parse_clndr_data`).
- **`TimeAxis`:** the same periods laid out on an absolute minute axis with cumulative
  work, which makes every date computation exact (details in [cpm.md](cpm.md)).

The rest of `xer/` reads P6 XML exports, for their baselines only:

- **`pmxml.py`:** baselines from a P6 XML export (`APIBusinessObjects`): each `BaselineProject`
  converted to the XER tables `build_snapshot` reads (`read_pmxml_baseline`, `list_baselines`,
  `choose_baseline`; `index_pmxml` / `PmxmlIndex` for what the app lists).
- **`pmxml_scan.py`:** where the projects, baselines, calendars and resources of an export lie, found
  by searching its bytes instead of parsing every tag (`scan_export`); an export that is not plain
  elements (`NotPlain`) is parsed instead.

## 4. `store.py`: the weekly series

`SnapshotStore` (`from_paths`, `from_folder`) sorts snapshots by data date and holds one per data date: given two files
with the same data date (versions of one draft, an update and its baseline copy) it raises
`DuplicateDataDate` naming them, and the user keeps one. `selection()` lists the files of the
series and the project taken from each: the Files section of the app's Files and baseline window
shows, for each file, the project read and the rule that picked it, with a list of its projects
when more than one is left once its baseline copies are set aside (otherwise "+ baseline copy") (by `proj_id`, each project named by code, data date, activities and
the project it is a baseline copy of), and the full table under "Selection details". A project
picked there applies on Done, like the rest of the window, and reads that file again and no other;
the files without a choice keep their default project. The sidebar's Files line counts the files
and the projects read, the latter in the alert colour when the series mixes projects. The session caches (`memo`, the file baselines) are keyed
on the `proj_id` read from each file. `SnapshotStore` exposes long-format frames:

- `history`: one row per (snapshot, activity);
- `relationship_history`;
- `assignment_history`: one row per (snapshot, resource assignment);
- `summary`: one row per snapshot.

Week-over-week analysis becomes a groupby; Plotly and Power BI read the same frames.

## 5. `analysis/`: everything computed

| Module | Input → output | Notes |
|---|---|---|
| `p6/check_schedule.py`, `dcma/fourteen_point.py`, `decm/schedule_metrics.py`, `integrity.py` | context → `RuleOutput(flagged, numerator, denominator, value)` | the built-in standards: one explicit function per check (`p6_01_logic`, `dcma_06_high_float`, `decm_06a211a_high_float`, `int_01_recalculated`…), its docstring quoting the source |
| `populations.py` | snapshot → named, sourced population steps (`EXCLUSIONS`, `Funnel`) and the other building blocks (with a predecessor, into open work…) | the one vocabulary of exclusions (complete, LOE, milestones…) that every standard's checks and the parameterised rules use |
| `rules.py` | the `@rule` registry (`RULES`); `AnalysisContext` + parameters → `RuleOutput` | parameterised rules (`exclude`, `links`, `op`, `value`, `unit`…) for your own standard, and helpers shared with the explicit checks |
| `standards.py` | TOML → `Standard(metrics)` (`load_standard`, `builtin_standards`, `discover_standards`, `template_text`) | validated on load (rule, parameter names, population keywords, target syntax) |
| `checks.py` | standard + `AnalysisContext` (defined in `rules.py`) → `CheckResult` per metric (`run_metric`, `run_standard`); `standard_score`; `health_history` over the series; `compare_counts` against a P6 summary | a failing rule returns status "error", never crashes the page |
| `audit.py` | `CheckResult` → the three sets behind its count (`split`, `sets_long`); a metric → the same metric with other settings (`with_settings`) and its `[[metric]]` table (`toml_block`) | cuts what the rule returned, recomputes nothing; read by the Audit and Schedule health pages |
| `baseline.py` | BL snapshot (or planned dates) → frame `bl_start, bl_finish, bl_labor_hr…` | shared by BEI, missed, late, PV |
| `baseline_resolution.py` | an update's Project Baseline pointer + the P6 XML export + the loaded updates → `Resolution` (`resolution`, `resolutions`) | which baseline an update is measured against when its file does not hold the one it names (below) |

**Baseline sources.** A baseline is one of: a separate XER, a loaded update, the planned dates of each update
(`Baseline.planned`), or the project the file itself names as the P6 Project Baseline. For the last,
`Snapshot.file_baseline` reads `PROJECT.sum_base_proj_id` of the analysed project (Oracle P6 EPPM XER
Import/Export Data Map, table PROJECT, v23: "Project Baseline"; `orig_proj_id` = "Original Project"; v26 map
not found, same XER format, unverified on 26). It is usable when that project is another PROJECT row of the
same file that owns activities and, when its `orig_proj_id` is filled, names the analysed project; otherwise
`note` says why not and the sidebar's choice applies. The app builds that project as a snapshot
(`load_snapshot(..., project_id=)`, exact because a baseline copy may carry the code of the project it was
copied from) and `Baseline.from_snapshot` gives its dates (BL Project Start / Finish: its planned
dates on the earned value basis "planned dates", else its current dates, actual > remaining > early). It is named as P6's Maintain Baselines names it: the baseline project's name (the
`wbs_name` of its project node, P6's default "<project name> - B1"), then its Project ID; the Project ID
alone when the file holds no project node (`analysis.baseline.baseline_name`; Oracle P6 help, Create a
baseline and Maintain Baselines dialog box). An update whose `use_project_baseline_flag` is N measures
earned value against each user's primary baseline in P6 (Project Details > Settings), which the file does
not carry: the sidebar says so in one line and xerscope reads the project baseline. The sidebar choice "Baseline in each file" is the default when a ticked file has one; a file
without one has no baseline for that update (checks that need one are n/a), stated in the window's Selection details.
The memo key holds the project each file names and the fallback. In that mode a second selector, "When a file
has no baseline" (a separate baseline file, a loaded update, the planned dates, None; None by default, never
chosen for the user), gives the baseline of the updates whose file has no usable one, update by update.
A separate baseline file may be a P6 XML export (`xer/pmxml.py`: its `BaselineProject` elements, converted
to the XER tables `build_snapshot` reads; durations and units in hours, percentages x 100, calendar periods
ending a minute later than the XML's last working minute). `load_snapshot(..., project_id=)` names the
baseline. In the per-file mode the export is read for every update whose file holds none
(`analysis/baseline_resolution.py`, applied by `app/baselines.py` `_resolved_baseline`): the baseline the update names when
the export holds it (exact), else the loaded update whose project the update names, else the baseline the
versions of the export created just before and after the update's project both hold (`content_digest`); the
last two are "probable", their `source` says so and every page, warning and download repeats it. An undecided
update (the versions around it hold different baselines) takes nothing, not even the fallback, until the
window's Baseline section gets a choice for it (`bl_undecided`: one of the two candidate baselines, applied as
"chosen" and alerted like a probable one, or the fallback). `Baseline.kind` says how the baseline relates to
its update (`analysis.baseline.KIND_*`: in file, exact, probable, chosen, fallback, planned, series) and
`found_by` what found it; every path that builds a Baseline in the app sets both, and `baselines.kind_of` is the
one classifier the banner, the sidebar and the Debug page read. A baseline of the export that cannot be read leaves its
update without one and is named in the sidebar (`_export_read_errors`). The Baseline section of the window
lists, once the files are read, what each file names and what it is measured against, or would be in the
per-file mode (`xml_baselines.baseline_per_file`), with the hint that P6 writes no baseline in an XER.
`Baseline.source` says where the baseline of an update comes from; `run_metric` copies it to
`CheckResult.baseline` for every check the baseline changes (`needs_baseline`, the readers that do not declare
it: the dangling logic, DCMA-08 and the CPLI margin, `checks.BASELINE_READERS`; the `duration` rule on the
baseline), `"none"` when it needs one and has none. "Link renumbered tasks by GUID" (`baseline.relinked`) renames
the baseline's frame, its assignment costs and the tasks of its own file alike, so the checks that count the
baseline's tasks (P6-13, the BEI due in the baseline) agree with the earned value. `explain` carries it, the
Health and Audit panels print it under the check, and the exported notes (summary CSV, all sets) end with
`baseline: <source>`. Every page opens with a one-line context banner (`state.page_header`): the projects
read, the data date of the update shown, where the baseline the page reads comes from (in file,
fallback, planned dates, a loaded update, a separate file, none) and the rule that picked it, the EV basis, costs on or off, and the count of files and projects; its
help reads "Baseline used for <update>: <source>" and why the rule applies, and pressing it opens the Files and baseline window. The baseline is
read per page (`app/baselines.py`): Health, Audit and the Gantt read the one assigned in the update's file when
it holds one, else the window's choice (`baseline_for_checks`: P6 Check Schedule and the DCMA items are defined
on it); Earned value reads the origin of the series (`origin_baseline`, the first update's baseline, which does
not move) and, with its "P6 view" switch, the update's own (`baseline_for`), P6's Planned Value of the week; the
four weeks' window reads the plan in force each week in both positions. Health,
Audit and Earned value add the baseline's warnings under it (`state.baseline_warnings`; the Earned value curves
measure every update against the origin, the BEI against each update's own). Warnings name the files: in the sidebar, updates without a usable
baseline and what applies instead, a pointer that is not used and why (absent project, `orig_proj_id` of
another project, no activities), a series that mixes sources; on the pages, a baseline whose data date is after
the update's, a baseline P6's Update Baseline changed after the update's status date (`last_updated`: the
baseline project's `last_baseline_update_date`, from the XER or from `LastBaselineUpdateDate` in the P6 XML)
and a baseline that finds fewer than 90 % of the update's activities (`MATCH_WARN_BELOW`; the 06A501a / DCMA-11
"N of M matched" count). P6-12 and P6-13 read `context.baseline` like every rule that
needs one: they get the baseline of the sidebar choice (the file's, a separate XER, the planned dates) and
carry no pointer logic of their own.

| Module | Input → output | Notes |
|---|---|---|
| `cpm.py` | snapshot → `Schedule` (`schedule`): early/late dates, floats, longest path, `rem_override_hr` (remaining set by an expected finish), assignment dates; `compare_with_stored`, `compare_assignments`; `critical_path_test` | see [cpm.md](cpm.md) |
| `resource_placement.py` | the driving assignments of one activity, its time axis and bounds → dates (`place_forward`, `place_backward`, `assignment_late_dates`) | pure functions the CPM engine calls for resource-dependent work; the rules and their corpus sources are given where `cpm.py` calls them |
| `changelog.py` | two snapshots → one row per change (`changelog`); `summary`, `category_totals`, `weekly_change_matrix` over the series | dates and durations in working days |
| `forensics.py` | two snapshots → `HalfStep` (`half_step`: the finish of the earlier one rescheduled with the later one's changes applied one `Step` at a time), `finish_case`, `longest_path_float_d`, `engine_gap_wd`, `revisions_by_horizon` (`Settings.lookahead_weeks`); `half_step_series` over the series | AACE RP 29R-03 MIP 3.4 (half-stepped update analysis); reads `changelog` for the kinds of change and `cpm.schedule` on derived snapshots (`dataclasses.replace`); the baseline is not read ([formulas.md](formulas.md) 5.1) |
| `longest_path.py` | a snapshot → the open activities on its longest path (`longest_path`: P6's flag, else recalculated) and where it was read; two snapshots → `path_changes` (stayed, entered, left finished / still open / deleted), `path_commitments`; `path_churn` over the series | AACE RP 29R-03 3.4.E.9, SVP 2.3.B.6 ([formulas.md](formulas.md) 5.2) |
| `evm.py` | baseline + series → PV curve (`pv_curve`), EV/AC/SPI per update (`evm_series`), Earned Schedule (`earned_schedule`), four weeks' window (`moving_window`, `spi_by_window`), BEI series (`bei_series`), forecast curve | labour units as P6: PV = BL × Schedule % Complete (exact working time), EV = BL × Performance % Complete (WBS EV technique); cost: BAC from `target_cost`, PV per assignment, EV = BAC × Performance %, SPI = EV cost / PV cost; `pv_p6_comparison` holds PV against a P6 Activities export |
| `progress.py` | series → MTA trend (`milestone_trend`), PPC (`ppc_series`), look-ahead (`lookahead_series`: tasks anticipated and made ready), date variances, progress delta | PPC = W-1 finish and start commitments, W outcome |
| `wbs.py` | snapshot → WBS tree with roll-ups (`tree`, `rollup`; `ROOT`) | % complete weighted by hours, else duration |
| `activity_trail.py` | one activity and the activities around it, for the Gantt's task panel: `linked_chain` (the Activity IDs reached through its relationships, upstream, downstream or both, N links deep, every link or the driving ones), `logic_by_update` (in each update, the activity and the activities linked to it up to N links, with level, link, driving flag, P6's floats and constraints), `trail_by_update` (floats and constraints of a list of activities by update), `constraint_history` (the changelog's constraint rows by update), `driving_flags` | driving = `cpm.Schedule.links`, recalculated: P6 does not export its Driving flag ([cpm.md](cpm.md), Driving relationships) |
| `task_filters.py` | snapshot + filters → the tasks kept (`branch_tasks`, `filtered_tasks`, `CodeFilter`) | the Gantt page's filters (WBS branch, status, float category, text, activity code) and the activity code filter of the PPC and Earned value pages |
| `explain.py` | `CheckResult` → formula, verdict, population, effective parameters, source (`explain`); `READINGS`: the "How to read" text of each chart and table; `KPI_FORMULAS`; `schedule_reading` | read-only account of a result, shown under every check in the app; the popover of `ui.chart` and `ui.table` |
| `query.py` + `ask/` | a sentence ("critical not started in civil works") → `Filter`: the Gantt page's filters (WBS node, status, float category, activity codes, resources, milestones, LOE, text, and clauses no widget says: NOT, OR across facets, comparisons, dates) | picks filters the page offers, computes nothing; `query.py` is the one entry point the rest of xerscope imports, the grammar lives in `ask/` (below, "The Gantt "Ask" field") |

`analysis/ask/`, one module per step: `text` (folding, tokens, typo distance: `FUZZY`, `SURE`),
`lexicon` (a company's trade words: `load_lexicon`, `learn`), `grammar` (the phrase table and the
expression tree `Atom` / `Not` / `And` / `Or`), `clauses` (comparisons and dates), `vocab` (the file's own
labels: `Vocabulary`, `vocabulary`), `lexer` (tokens to items), `parser` (`parse_keywords`, `MAX_CHARS`),
`filters` (`Filter` and its written forms), `funnel` (`apply`: the filter over the rows), `answer`
(`answer`, `language`, `suggestions`), `generated` (the files' own variants: `variants`, `near_spellings`),
`suggested` (the corrections taught in the app, appended for review) and `bench` (`score`, `ratios`,
`coverage` on sentences with known filters).

Standards are data in `standards/*.toml`:

- `p6.toml`: P6 Professional 24 Check Schedule (17 checks: the 14 of the help plus out of sequence and dangling start/finish from a P6 Professional report; Oracle's groups; Invalid Progress Dates on two lines, P6-10a / P6-10b, as the report prints it);
- `decm.toml`: DCMA DECM v8.0, Guideline 6 schedule tests (16 metrics);
- `dcma.toml`: DCMA 14-Point (legacy);
- `integrity.toml`: recalculation of activities and assignments, and the warnings, errors and exceptions of the P6 scheduling log (loops, open ends, out-of-sequence progress, actual dates after the data date, unsatisfied constraints and relationships; INT-01 to INT-08);
- `custom-template.toml`: the commented starting point for your own.

Why explicit functions plus TOML: P6's "Large Float" (`p6_06_large_float`) and DCMA-06
look alike but differ in unit and population. Each built-in check is one function that
reads like its source text, so a reviewer can hold it against the Oracle page or the DCMA
sheet; the TOML holds only the target and the source. Your own standard picks the
parameterised rules of `rules.py` (`float` among them; `xerscope standards --rules` lists them) and
sets units, exclusions and targets as data.

Layer rules (imports, as the code has them; `tests/test_architecture.py` holds the same list in `LAYERS`
and checks the code against it, both ways, so a change here must be made there too):

- `xer/` imports only `config.py`; it knows nothing of the layers above.
- `store.py` imports `xer/` and `config.py`; `export.py` imports `store.py`, `config.py` and
  `csv_safe.py`; `anonymize.py` imports `xer/` and `export.py`. `csv_safe.py` imports nothing of xerscope.
- `analysis/` imports `xer/` and `store.py`; never `viz/`, `app/` or `verify/`.
- `viz/` imports `config.py` and, from `analysis/wbs.py`, the constant `ROOT` only: it draws
  frames, it does not compute schedule results.
- `verify/` imports `xer/`, `analysis/cpm.py` and `config.py`; `crosscheck.py` imports `verify/` only
  and re-exports its MPXJ and P6-corpus entry points. Nothing in the app depends on it.
- `sample.py` imports `xer/`, `analysis/cpm.py` and `config.py`.
- `app/` imports `xer/`, `store.py`, `analysis/`, `viz/`, `export.py`, `anonymize.py` and `config.py`, and is imported
  by nothing but Streamlit and `cli.py`. Pages
  compose analyses and figures (some computation still sits in the views: see
  [backlog.md](backlog.md), Structure).
- `cli.py` is the entry point: it imports `xer/`, `store.py`, `analysis/`, `export.py`, `sample.py`,
  `verify/` (`recalc --report`), `crosscheck.py`, `anonymize.py` (`ask-bench --anonymize`), `config.py`
  and, of `app/`, `app/diagnostic.py` only (`pv-compare` reads the same frames as the Debug page). It
  does not import `viz/`.

Outside `analysis/`:

- `config.py`: `Settings` (`DEFAULT_SETTINGS`), the few tunable defaults no standard owns:
  `default_hours_per_day` (8, when a calendar is missing; read by `xer/calendar.py` and `xer/model.py`),
  `critical_float_days` (0, the critical threshold when the file sets none; `xer/model.py`),
  `near_critical_float_days` (10, Gantt colours only; `viz/gantt.py`), `table_filter_min_rows` (10, app
  tables with more rows get column filters; `app/ui.py`) and `lookahead_weeks` (6, the Delay analysis
  page). Also `DATE_FMT` and `DATETIME_FMT`. The analyses read the derived columns.
- `export.py`: the Power BI star schema (`export_tables`: `dim_snapshot`, `fact_activity`,
  `fact_relationship`, `fact_assignment`; written as Parquet or CSV by `write_tables`, also zipped by
  `zip_tables` / `zip_frames`).
- `csv_safe.py`: `csv_safe` neutralises a cell a spreadsheet would run as a formula (CWE-1236) in every
  CSV xerscope writes: the Power BI tables, the CLI CSVs, the page downloads, the anonymised tables.
- `sample.py`: the demo series generator (`generate`), with the findings it plants week by week.
- `anonymize.py`: anonymised copies of the loaded XER files and of every table the app hands
  out while the sidebar switch "Anonymous exports" is on (the default, per session): page CSVs,
  Schedule health lists, the Power BI zip (`Anonymizer.frame` on each table, no project code in
  the file name), the Debug diagnostic. Off, the same downloads carry the files' own codes and
  names; the XER extract stays anonymised. The pages always show the files' own data. An allowlist
  per table keeps keys, dates, durations, units, flags and P6 enumerations; codes get new
  values, `X<kind>` and the first hex digits of an HMAC-SHA256 of the original under a key
  drawn for the session (12 for activities, 8 for the other kinds; a code that would spell an
  original value is drawn again; two originals on one code are refused, `CodeClash`), project ids
  get new 9-digit ids drawn the same way, GUIDs new random GUIDs, names are rebuilt
  from the new codes, costs set to 0, user, database and free text removed, unknown tables and columns
  left out and named. The `note` column (the rules' notes) is kept with each Activity ID and
  file name in it renamed; the rules write nothing else of the file into a note. A download reads only its own files (the update shown, W-1 and W for the
  changelog and PPC, the baseline's file when it lists baseline fields, every file for Power BI
  and the XER extract), and an activity keeps one code in every download of the session. Every
  output field is compared with the text values of the files read before it is handed out
  (`Anonymizer.leaks`; a match is refused, `LeakError`). The
  key and the mappings live in the session only.

### `verify/`: independent checks, strongest source first

| Module | Source | Role |
|---|---|---|
| `p6_corpus.py` | P6 Professional 23.12.1's own output on the held-out corpus (`p6_heldout_score`) | the oracle for the CPM: every rule the engine takes from it is pinned by a corpus activity in `tests/test_p6_heldout.py` |
| `mpxj_cpm.py` | MPXJ's PrimaveraScheduler (`mpxj_schedule`, `cpm_crosscheck`) | a second engine, a hint only: `P6_SETTLED` lists the shapes P6 settled against it, `UNRESOLVED` the open ones, `mpxj_inconsistent` its self-contradictions |
| `mpxj_reader.py` | MPXJ as a reader (`compare_file`, `compare_paths`) | the XER tables read two ways |
| `shapes.py` | the file's own stored dates (`difference_report`) | `xerscope recalc --report`: differences grouped by activity shape (status · type · constraint · links · option), so one week's differences point at one rule |

`crosscheck.py` re-exports `mpxj_cpm`, `mpxj_reader` and `p6_corpus` (not `shapes`); the CLI imports
from there, except `verify.shapes`, which it imports directly. The tests import from `crosscheck.py`
or from the `verify/` modules themselves (`shapes`, `p6_corpus`, `mpxj_reader`).

## 6. `viz/`: figures

- **`gantt.py`, `gantt.js`, `gantt.css`:** the Gantt grouped by WBS, laid out like P6's
  Activities view: a tree grid (Activity / WBS, % complete, float) on the left and the
  timeline on the right, one row each. `gantt_rows` builds the rows in P6 order (each
  WBS node, its own activities, then its child nodes) with float-category colours
  (`categorise`: critical, near critical within `Settings.near_critical_float_days`, normal, complete),
  comparison dates and finish shifts; `gantt_data` hands them, with the options and, when asked, the
  logic links between the activities drawn, to a
  Streamlit component (`app/ui.py: GANTT`, `st.components.v2`) mounted in the page; `gantt_assets`
  reads `gantt.js` and `gantt.css`. Three options serve the Tasks page with the same
  component: `columns` (the grid's columns after the name, `GRID_COLUMNS` by default,
  `ACTIVITIES_COLUMNS` there), `timeline=False` (the grid alone, the page's width) and
  `level_bands` (each WBS row shaded by its level, as P6 colours its WBS bands).
  A click on a WBS row opens or closes it; a click on an activity row or bar sends its row
  id (`"a:<Activity ID>"`) and nothing else.
  WBS rows open and close in the browser, without a rerun; only the rows in view are
  in the page, so a schedule of 15,000 activities scrolls like a small one. There is
  no zoom, only a month or week timescale. Schedule text reaches the browser only as the
  component's data and is never parsed as HTML (`textContent` only; `gantt.js` holds no
  network call, checked by a test). Page colours and font come from the theme's `--st-*`
  variables (`gantt.css`), so the Gantt follows a theme switch without a rerun.
- **`charts.py`:** S-curve, indices, MTA, PPC, metric trend, an activity's dates and float across
  updates, the finish trend, the half-step and slip charts of the Delay analysis (`build_*`), and the
  app's colours (`STATUS`, `SERIES`, `NEUTRAL`), one set for both themes, each mark >= 3:1 on
  the light and the dark background: the Gantt bars and the check-status labels in
  `app/ui.py` derive from them. `ACCENT` (decoration in `style.css`) is the one colour set
  per theme, the theme's link colour, applied through CSS `light-dark()` (`app/theme.py`). Text, grid and axes
  are left to Streamlit's Plotly theme (`style.css` only fades the grid), so the charts
  follow a theme switch without a rerun. The series palette is a fixed
  categorical order, validated for colour-blind separation; status hues never decorate.
  There is one y-axis per chart.

## 7. `app/`: Streamlit

- **`streamlit_app.py`:** declares the pages (`st.navigation`): Schedule (Overview, Gantt & WBS),
  Analysis (Schedule health, Audit, Changelog, Delay analysis, Earned value, Milestone trend, PPC &
  progress), Data (Export for Power BI, Debug). The Debug page is left out on a
  locked deployment (`XERSCOPE_DATA_LOCKED`) unless `XERSCOPE_DEBUG_PAGE=1` (`session.debug_page`). It
  keeps the app out of the file-reading worker processes (`__mp_main__`).
- **`baselines.py`:** which baseline each update is measured against, as the session chose it:
  `baseline_for` (cached per data set), `baseline_for_checks`, `origin_baseline`, the paths that build the `Baseline` of one update (its file's,
  the one resolved from the export, `_resolved_baseline`, the one chosen for an undecided update, the fallback, the planned
  dates, one baseline for the series), each setting `kind` and `found_by`; `kind_of`, the one
  classifier; `data_identity` and `_baseline_identity` for the cache keys. Draws nothing.
- **`baseline_file.py`:** the separate baseline file: picked in the folder (the P6 XML exports next to the
  updates, and every file of its `baselines` subfolder), uploaded, or named by
  `XERSCOPE_BASELINE`; `baseline_items` and `baseline_files_tag` for the downloads and the cache keys.
- **`baseline_export.py`:** the P6 XML export in use: its index, what the resolution reads of it
  (`export_contents`), the resolution of each update (`_resolution`, cached for the series), the
  baselines read from it (`_export_baseline`, one read per baseline and basis) and the candidates of an
  undecided update (`is_undecided`, `candidates`).
- **`baseline_window.py`:** the window's Baseline section: the choices it offers and their names
  (`_baseline_options`, `_baseline_short`, `banner_kind`), the fallback and the choice of each undecided
  update, the per-file table, the option "Link renumbered tasks by GUID".
- **`baseline_warnings.py`:** the sidebar's Baseline line (`_baseline_picker`; shortcut B) and what the sidebar says
  about the baseline in use: probable or chosen baselines, undecided updates, pointers not used, a series
  that mixes sources, the Project Baselines the files name but do not hold, the renumbered tasks.
- **`xml_baselines.py`:** the baselines a P6 XML export holds, held against the baseline each update names
  (`xml_baselines_table`, `resolution_table`, `baseline_per_file`), for the window and the Debug page.
- **`cache.py`:** the session's caches of what the pages compute: `memo` (keyed on `data_identity`,
  at most `MEMO_SIZE` entries), `metric_result` and the standard results, `ScoreJob` (`score_job`).
- **`session.py`:** read by the baseline domain, the windows and the pages; it reads `ui` only (for
  `fmt_date`, in the sidebar's data-date period `_period`): the session-state keys, the window's modes (`BL_*`) and drafts, the parse cache (`_parse`, `_pmxml_index`),
  the digests, `_cache_for`, the locked deployment (`data_locked`, `debug_page`) and the folder root
  (`folder_root`, `folder_under_root`: a folder typed in the window is read only under
  `XERSCOPE_FOLDER_ROOT`, else the folder of `XERSCOPE_DATA`, else the home directory).
- **`files_window.py`:** the one window the sidebar's Files and Baseline lines open (`st.dialog`
  "Files and baseline", `_window`): the file listing, uploads and the project read from each file, then
  the Baseline section; nothing applies before Done (Ctrl+Enter), which reads the files and sets the
  baseline choice; Esc cancels. `most_recent_first` orders the files to read, latest status date first.
- **`loading.py`:** reading the series into the session: the sidebar loader (`sidebar_loader`,
  `draw_sidebar`: the Files line, shortcut F, the errors, the pickers and the switches), `load_series`,
  the background jobs and the Ask field's lexicon (`lexicon`, `file_variants`, `session_lexicon`, `teach`).
  Two threads (`background_jobs`, off
  with `XERSCOPE_SYNC_LOAD=1`, which the tests set): on Done `LoadJob` hands every file to
  `app/reading.py`, which reads them on up to two worker processes (`MAX_WORKERS`; `spawn`, no Streamlit imported;
  `XERSCOPE_LOAD_WORKERS`, 1 reads in the thread; a pool that fails falls back to that). The pages
  wait and draw once on the complete series: `_poll_load`, a fragment, redraws only the progress bar
  each second and reruns the app once when the reading is done. A new choice of files then waits for
  its baseline: the window opens once on its Baseline section (`_ask_for_the_baseline`; with a
  single P6 XML export in the folder and no `XERSCOPE_BASELINE`, that export is picked), nothing is
  read for the baseline and the pages stop (`require_store`) until Done there (`BASELINE_SET`).
  Once the baseline is set the Overview computes the built-in standards on the latest update in `ScoreJob` and writes the results
  where `metric_result` reads them. Neither thread touches the session state: the script run
  collects what they produced. A new choice of files cancels both jobs (files not started are not
  read, checks not started are not computed), drops the memo and the baselines read from the
  files, and keeps in the parse cache only the files of the new series.
- **`reading.py`:** reading the chosen files on worker processes (`read_updates`, `read_update`,
  `worker_count`, `store_of`); imports no Streamlit.
- **`state.py`:** the page-level pieces only: the context banner and page header (`context_banner`,
  `page_header`, `checks_rule` and the `BASELINE_RULES` it names), `baseline_warnings`, the pickers
  (`snapshot_picker`, `compare_picker`), `require_store`, `standards` (built-in, `XERSCOPE_STANDARDS`,
  uploaded), `go_to` / `open_in_gantt`. Every other name a page reads comes from its defining module, which
  `tests/test_architecture.py` guards (the app's import edges, written in the test; the baseline domain
  reads none of the pages' machinery; `state.py` is imported by the pages only; no cycle). One update for
  the session: `snapshot_picker` writes the choice to `snap_choice`, every page's picker starts
  from it; `go_to` / `open_in_gantt` write the session then switch page (a check's tasks to the
  Gantt, a table row to the Gantt, a check to the Audit). The cache (`memo`) keys every entry on the files, the
  project read from each and the baseline in use, then on what the analysis reads; it keeps the
  `MEMO_SIZE` most recently used entries. An analysis that reads no baseline (change log, PPC,
  milestones, exports, forecast) or not the EV basis (the checks, the WBS rollup) leaves it out of
  its key. `metric_result` holds one result per (metric, update, baseline): Schedule health,
  Audit and the BEI of Earned value read the same entry; no check reads the columns the EV basis
  sets (`baseline.EV_COLS`). Series over every update (the health trend, computed on request,
  and the BEI series) reuse the entries there and keep only their numbers. A built download
  (Schedule health's sets, the Debug zip) is offered again only for the same `data_identity`.
- **`downloads.py`:** the anonymised downloads: the anonymisers of the session (`anonymizer`), the
  held bytes (`hold`, `held`, `build_and_hold`), the download buttons (`download`, `csv_download`,
  `show_download`) and the sidebar switches they read (`anonymous_exports`, `costs_shown`).
- **`ui.py`:** the shared look (the page header and its context banner are in `state.py`): the KPI
  readout (`kpis`; one line per figure, a change of zero drawn neutral), `table` with column filters on long tables
  (`Settings.table_filter_min_rows`, read by `table`; `table_filters.py` reads the typed filter text), `chart` and its "How to read" popover, one column-label dictionary (`task_code` → "Activity ID", dates and units
  formatted the same everywhere), status colours (red / amber / green reserved for status), the Gantt
  component (`GANTT`).
- **`theme.py`:** `apply_style`, which sends `style.css` with the chart and status colours of
  `viz/charts.py` as CSS variables, and the font fallback.
- **`glossary.py`:** the acronyms shown on the pages (full name, definition, source): the help of each
  column or card whose label holds one, and the Glossary expander under each page.
- **`table_filters.py`:** reads the text typed in a column filter, for a text, a number or a date
  column (`keep_mask`); no Streamlit.
- **`code_picker.py`:** the two widgets that pick a P6 activity code, its type then its values.
- **`explanation_panel.py`:** the explanation of a check as Health and Audit show it
  (`metric_panel`, `show_calculation`, `show_method`).
- **`sets.py`:** the sets behind a check and the population step by step (`show_sets`, `show_steps`),
  shared by Schedule health, Audit and the Gantt's Ask field.
- **`diagnostic.py`:** the tables of the Debug page (below), built from the existing results; with
  **`expected_finish_forms.py`** and **`recalculation_departures.py`** (the expected finishes by form,
  and where the recalculation first departs from the dates P6 stored, [formulas.md](formulas.md) 5.3),
  split out to keep it readable.
- **Import edges** (`APP_EDGES` in `tests/test_architecture.py`: one entry per module of `app/`, its edges
  compared exactly, every import form read): `ui` is the shared look any module may read, and reads only
  `glossary`, `table_filters` and `theme`. `code_picker`, `expected_finish_forms`, `glossary`, `reading`,
  `recalculation_departures`, `table_filters` and `theme` read no app module; `explanation_panel`,
  `task_panel`, `xml_baselines` and `session` read `ui` only. The baseline domain (`baseline_file`,
  `baseline_export`, `baselines`, `baseline_window`, `baseline_warnings`) reads
  `session`, `ui`, `xml_baselines` and its own modules, never `state`, `loading` or `downloads`; `cache` reads `baselines`,
  and `baseline_warnings` reads `cache`. `files_window` reads `baseline_window`, `session` and `ui`; `loading` reads
  `baseline_warnings`, `files_window`, `reading`, `session` and `ui`; `downloads` reads `baseline_file` and
  `session`; `sets` reads `downloads` and `ui`; `diagnostic` reads `expected_finish_forms`,
  `recalculation_departures` and `ui`; `state` reads the baseline domain, `downloads`, `loading`, `session` and
  `ui`; `streamlit_app` reads `loading`, `session`, `theme` and `ui`. `state` is read by the pages only. No module reads
  a page and no page reads another. A new module or a new edge is written here and in `APP_EDGES` in the
  same change.
- **`.streamlit/config.toml`:** the light and dark themes (warm neutrals, petrol accent) and server settings
  (localhost only). `xerscope app` runs Streamlit from the app folder, so it applies
  wherever the command is started.
- **`static/`:** the fonts the theme loads (Onest, JetBrains Mono;
  variable woff2, latin subset, SIL OFL 1.1 with their licences), served by the app itself
  (`enableStaticServing`).
- **`style.css`:** what the theme cannot set (the KPI readout, the activity card under the Gantt, the milestone picker's tags in
  their line colour), sent by `theme.apply_style()` with the colours of `viz/charts.py`.
- **Schedule health:** a summary row per check, then one panel per check: what it measures,
  the calculation with its numbers (`analysis/explain.py`), the population (exclusions),
  the effective parameters (standard or default), the source, and the flagged items.
  All flagged items of all checks export as one CSV, the audit trail behind the scores; the
  summary export adds each check's note. Under the results, "Show the sets of" (a fragment,
  nothing listed until a check is picked) shows that check's Counted / Checked, not counted /
  Excluded tables, or its note when it has no rows; "Prepare all sets" builds, on click,
  `audit.sets_long` (one row per item of every check: `check_id`, `set`, `note`, the item's
  fields, `pred_*` / `succ_*` fields of a relationship's two activities) as one CSV and as one
  CSV per check in a zip. Both read the sets `audit.split` cuts; `app/sets.py` is the display
  shared with the Audit page.
- **Audit:** one check at a time: the standard's result beside the same check re-run with
  the target and parameters set on the page (`analysis/audit.py` `with_settings`, validated
  as a standard file is), the three sets behind the count (counted, checked but not counted,
  excluded from the file; `audit.split` cuts them from `CheckResult.checked` / `counted`,
  nothing is recomputed), and the population step by step for every check with a row population (`populations.Funnel`: each
  filter named, with the text it follows and the rows it removed) and the `[[metric]]` table to paste into a standard file to make a
  change permanent. Settings stay on the page and in the session; Schedule health keeps the
  loaded standards.
- **`sheets/<standard>/<id>.md`:** one calculation sheet per check (P6 for now, `sheets/P6/`), shown on the
  Audit page: population and counted items with their XER fields, the Oracle text it follows,
  a worked example, the key to change. `tests/test_sheets.py` keeps each sheet on the TOML's
  target and parameters, on fields and codes the model reads, on tests that exist.
- **Debug:** what xerscope read and decided for one update, to hold against P6 without the
  file, in numbered blocks: the scheduling options (block 1: raw XER value, value applied, blank-in-file defaults), the
  projects of the file (`Snapshot.file_projects`: TASK rows, `sum_base_proj_id`, `orig_proj_id`,
  `last_baseline_update_date`, `add_date`, `use_project_baseline_flag`, and which one is the analysed
  project or its P6 Project Baseline), the activities with an expected finish and the remaining
  duration it set (`rem_override_hr`), the INT-01 / INT-03 differences with the inputs the CPM read,
  the P6 Check Schedule targets on the tabs of the P6 dialog, the baseline and the calendars, the
  Project Baseline every update of the series names (`diagnostic.baseline_pointers`, page only, not in
  the zip), the tasks renumbered since the baseline or the previous update by GUID
  (`diagnostic.renumbered_table`, page only), and the activities
  behind the load warnings (leveled activities, `scd_end_date` against the activities that
  end last), and the costs the file carries (TASKRSRC and PROJCOST `target_cost`,
  `cost_per_qty`; the cost SPI of the Earned value page is computed from them, beside the labour units SPI),
  the Earned Value settings of the WBS (block 8), the XER tables and the planned value labour units (block 9),
  the planned value against a P6 Activities export (block 10, as `xerscope pv-compare`),
  and block 11, the project settings of every project of the file (`PROJECT_SETTING_COLUMNS`, carried by
  the same `Snapshot.file_projects` rows, `absent` for a column the file lacks; of
  `baseline_names_to_export` only the number of names) with its tasks by `complete_pct_type`, and what
  each setting is in the XER data map and the P6 help (`SETTINGS_MEANING`). No KPI reads it.
  Block 12, the app runtime (where the theme and fonts come from), is not shown on a locked deployment.
  Block 13, the calendar detail (`diagnostic.calendar_detail_frames`, also its own zip): each calendar's
  hours per time period as stored (`day_hr_cnt` .. `year_hr_cnt`) beside the working time its
  `clndr_data` periods add up to, the periods of each weekday, and each dated exception with what it does
  to the weekday it replaces (non-working day, working day on a non-working weekday, other hours).
  Block 14 lists the Ask field's variants generated per source column.
  `app/diagnostic.py` builds the tables from the existing results; with anonymous exports on,
  `Anonymizer.zip_frames` hands them out with the codes of the anonymised extract (dates
  unchanged, cost figures 0 as in the extract).
- **Pages:** one file per page in `views/` (`overview`, `gantt`, `tasks`, `health`, `audit`, `changelog`,
  `forensics` for Delay analysis, `earned_value`, `milestones`, `ppc`, `export`, `debug`). Pages compose analyses and figures; the
  Plotly figures are built in `viz/`.
- **`activity_details.py`:** one task in one update, as P6's Activity Details shows it: its card
  (P6 properties), resource assignments, and relationships (predecessors on the left, successors
  on the right, the driving flag of each link recalculated by the CPM); as one block under the
  Gantt (`show_card`) or as P6's tabs General, Status, Resources, Relationships, Constraints on
  the Tasks page (`show_activity_details`).
- **`views/tasks.py`:** P6's Activities view: the WBS tree and its tasks in P6 order, drawn by the
  Gantt's component without its timeline (`viz.gantt_data`: `ACTIVITIES_COLUMNS`, level bands); a
  click on a task details it below with `activity_details`, and buttons step to the task before and
  after it in the tree.
- **`task_panel.py`:** the Gantt's panel around one task (its card from `activity_details`) and its
  history across updates. Opened under the Gantt for the activity picked there
  (`task_from_row_id` accepts an `a:` row id only, and the page only an activity the chart
  draws), or from a row of the panel. Above the card, the breadcrumb: the activities opened,
  then the predecessors and successors of the one shown (Levels, Driving links only), with
  their floats and constraints by update. Below, one chart of its forecast dates and total
  float on a shared status date axis (one hover per status date for both plots), the chain
  shown alone in the Gantt on request, and its constraint changes. Every value is read from
  the snapshot or the store, card text is escaped.

### The Gantt "Ask" field: talking to the schedule without a model reading it

A planner types "critiques non démarrés en génie civil" and the Gantt filters itself. The
sentence is read by a grammar over the file's own labels; no model reads the schedule, and the
answer is a template over values the page computed:

```
sentence ─▶ keyword grammar over the file's lexicon ─▶ Filter ─▶ funnel over the rows
            exact phrases, the company's words,                  ▼
            the files' variants, typos (difflib)         answer sentence (template),
                                                         chips, Gantt, table, CSV
```

- **The lexicon is the file's own** (`analysis/ask/vocab.py: Vocabulary`, built once per update from
  the snapshot's frames: WBS nodes with their code and name, activity-code values, resources, the
  Activity IDs, the words of the activity names, whether the file has milestones and LOE, the data
  date). Every layer matches the sentence against these labels and nothing else; an id outside them
  is dropped.
- **The trade words are data, not code, and none ships with the package.** A company keeps them in
  the folder `XERSCOPE_LEXICON` names, outside the repository, as `[[group]] words = [...]` tables
  (every word of a group read as every other: "mécanique" finds "Mechanical & electrical"). That
  folder holds `curated/` (edited by hand, read by the app), `generated/` (the files' own variants,
  written by `xerscope lexicon build` only) and `suggested/` (the corrections taught in the app,
  read by nothing until copied into `curated/`). `xerscope lexicon FOLDER` checks a folder;
  `ask-bench --lexicon` measures what it adds. The tests use a small generic lexicon built in code
  (`tests/asklex.py`).
- **The files' own variants** (`ask/generated.py`): words of one source column read as one by
  written rules only (case and accents, French or English plurals, an abbreviation with its dot and
  the one longer word it begins), never across columns; derived in memory per session, and written
  to `generated/` by `xerscope lexicon build` (the compose `lexicon-init` service). Near spellings are
  listed for review, never grouped.
- **An automatic lexicon, from the file itself.** The words of the activity
  names that appear under one WBS node alone become that node's aliases
  (`Vocabulary.node_words`: "foundations", "earthworks" name Civil works; "piping" names
  Mechanical & electrical); a word under several nodes names none and stays a search. Said
  alone, such a word gives the node and a search in it: the same rows as the search, and the
  answer names the node. Nothing to maintain: it follows the file.
- **The whole loaded file, measured on the file.** `ask-bench --self` (`query.coverage`)
  draws the phrases from the file's own lexicon (each node by code, name and every synonym,
  each resource, each status and float in both languages, milestones, LOE) and lists the
  labels the grammar cannot name: what the company's lexicon file should add. The demo is
  covered in full (`tests/test_ask_bench.py`).
- **The grammar** (`ask/grammar.py`, `ask/parser.py`): juxtaposition is AND, OR binds tighter than
  AND, NOT is the complement in the page's population, parentheses group; comparisons ("float < 10 d",
  "durée supérieure à 20 jours") and dates counted from the data date ("finissent avant fin
  décembre", "starting next week") are clauses (`ask/clauses.py`). A sentence is read up to
  `MAX_CHARS` (300) characters, the rest named as left out.
- **A word nothing holds is never silent.** It is set aside and named ("not in this file:
  commiss"), the other filters apply, and the page offers the closest labels of the file
  (`query.suggestions`, difflib over codes, names, name words and synonyms, from `SUGGEST`):
  a click teaches the word for the session (`loading.teach`, `query.learn`) and appends the
  correction, never the sentence, to `suggested/` for review (`ask/suggested.py`: fixed file name,
  bounded and filtered text, an exclusive lock, a size cap, 90 days' retention; threat model in
  [deploy.md](deploy.md) §10). A typo close enough (`FUZZY`) is read at once, marked unsure.
  A word that names several activity-code values or types of one name is filtered on none of
  them: the page asks back (`Filter.clarify`), and the choice is kept for that sentence.
- **One rule for a word that is both a node's and an activity's** ("electrical", in
  "Mechanical & electrical" and in "Electrical installation"): the node, and a search in it.
- **The output is a `Filter`** (WBS node, statuses, float categories, code values,
  resources, milestones, LOE, search words, and `clauses` for what no widget says): what the page's widgets offer, intersected
  with them. The page runs it as a `populations.Funnel` (`query.apply`): one named step per
  filter understood, source `ask`, so the caption (`query.funnel_line`) reads "212 → WBS CIV · Civil works 48 →
  status Not started 30 → float Critical 3" and the "Population, step by step" table under
  the chart is the same table every check shows (`app/sets.py`). The count a planner asks
  for is the last step's `left`; the steps are the trace. On the page the field comes first,
  the answer sits in a banner under it, and what was
  understood is one chip each: a chip's × drops its filter
  (`query.without`). In the banner, `query.answer`
  says it in one sentence, in the question's language (`query.language`): the count, what
  was asked, the worst total float and the latest finish of the rows, each a column of the
  frame, from a template, never from a model.
- **Confidence** comes with each answer: 1.0 for exact phrases, the weakest fuzzy ratio
  otherwise, lowered when two WBS nodes score as close (`MARGIN`: the sentence does not separate one
  cluster from the other); under `SURE` (0.9) the page says "unsure". `xerscope ask-bench`
  measures the grammar on sentences with known filters (`tests/ask/dev.toml` tuned on,
  `heldout.toml` written blind, `cases.toml`; floors in `tests/test_ask_bench.py`), per field and per
  confidence bucket; `--anonymize` runs it on the anonymised copy of a real file, the output and the
  sentences seeing the new codes only.
- **No model is deployed.** Nothing in `src/` reaches the network (`tests/test_docker.py`).
  `query.facts` (the funnel's steps and counts, the worst floats, values computed by xerscope, never a
  name) is what a model would be given to word an answer; nothing in the app calls it.

**Why no language model.** A small generative model (Qwen3.5-2B, quantised) was measured on the
held-out sentences and not kept; its measurement client has since been removed, and the figures are
in [deploy.md](deploy.md) §10.

1. *Cost.* A real schedule has hundreds of WBS nodes and resources: a model would read that lexicon
   on every question, at a few tokens per second on the deployment's CPU. The grammar answers in
   milliseconds, on the whole lexicon, every time.
2. *Truth.* The project's rule is that every number traces to a formula and a population.
   A model that reads activities and answers "3 milestones are late" cannot be traced, and
   small models invent ids and figures. Kept to routing over labels, a model could at worst pick the
   wrong label; it could not be pinned like the grammar.
3. *Measurability.* The grammar is scored on held-out sentences with floors a change cannot lower.
   A model's answers vary with the quantisation, the build and the prompt, so it cannot be held to a
   floor in the suite.

## 8. `cli.py`

| Command | Does |
|---|---|
| `app` | launches the UI on localhost (`--data`, `--baseline` XER or P6 XML, `--standards`, `--port`, `--host`) |
| `info` | one line per snapshot (`--project`) |
| `check` | runs a standard (`--standard P6`, `DCMA`, `DECM` or `INTEGRITY`, any case, or a `.toml`) on files and prints the P6-style summary (`--baseline` XER or P6 XML, or `--planned-baseline`; `--baseline-in-file` for the P6 Project Baseline each file holds; `--project`; `--out` CSV; `--flagged DIR` for the items behind each count; `--expect CSV` to diff against a P6 Check Schedule summary; `--fail-on none\|fail\|error` for CI) |
| `standards` | lists standards (`--rules` the rules and their parameters), or writes the template (`--template [FILE]`) |
| `recalc` | reschedules and compares with stored dates (`--project`, `--out` CSV, `--report` groups the differences by activity shape, `--show N`) |
| `changelog` | changes between two files (`--project`, `--out` CSV) |
| `export` | Power BI tables (`--out`, `--format parquet\|csv`, `--project`) |
| `crosscheck` | compares the reading with MPXJ (Java); `--cpm` the recalculation with MPXJ's scheduler and the stored dates; `--p6` with P6's held-out corpus (`--out`, `--show`) |
| `pv-compare` | PV and EV labour units of one update against a P6 Activities view saved as CSV (`--p6 CSV`, `--baseline` or `--planned-baseline`, `--column FIELD=HEADER`, `--tolerance`, `--p6-total`, `--project`, `--out` folder); the frames of Debug block 10 |
| `sample` | generates the demo series (`--out`, `--weeks`) |
| `ask-bench` | scores the Ask field's grammar on sentences with known filters (`--cases TOML`, `--self`, `--anonymize`, `--lexicon FOLDER`, `--show`) |
| `lexicon` | checks a lexicon folder (`--word` prints the words read as one); `lexicon build SOURCE --out LEXICON_FOLDER` writes the files' variants to `generated/` and purges `suggested/` |

## 9. Tests (`tests/`)

A test can carry `@pytest.mark.oracle(kind)`, where its expected values come from: `p6`, `mpxj`,
`standard`, `property` or `characterization` (marker declared in `pyproject.toml`; `tests/conftest.py`
stops the run on any other kind; `scripts/oracle_report.py` counts them, a test without the marker
under `(none)`). `conftest.py` also sets
`XERSCOPE_SYNC_LOAD=1` and `XERSCOPE_STRICT_READINGS=1`, provides the demo series (`sample_dir`,
`store`: `generate(..., weeks=8)`), and skips a test whose evidence is missing (reference files,
P6 corpus, MPXJ) unless `XERSCOPE_REQUIRE` names it.

| File | What it pins |
|---|---|
| `xerkit.py` | builds tiny XERs in code (numeric ids, full calendars, as P6 writes them), so each expected number is countable by hand and any reader sees the same file |
| `rulekit.py` | shared helpers of the rule tests: the built-in standards loaded once (`STANDARDS`), `run(std, metric_id, snapshot, baseline)`, `run_on_store(store, index, metric_id)` (the first update as baseline), `codes(result)` (flagged Activity IDs), `counts(result)` (numerator, denominator), `links(result)` (flagged relationships as sorted (pred_code, succ_code) pairs) |
| `pmxmlkit.py` | builds tiny P6 XML exports (a project, its `BaselineProject` elements, a calendar), as `xerkit` builds XER files |
| `file_projects.py` | XER text with two projects in one file, for the tests of the P6 Project Baseline pointer |
| `asklex.py` | a small lexicon of generic trade words for the Ask tests, built in the test (no lexicon ships with the package) |
| `ask/` | the Ask field's sentences with known filters: `dev.toml` (tuned on), `heldout.toml` (written blind), `cases.toml` |
| `test_characterization.py` + `golden/standards.json` | characterization (golden) test: status, numerator, denominator, value and flagged identifiers (Activity IDs or `pred->succ`, never names; a note only for an error) of every metric of every built-in standard, in four sections: `demo` (the demo series, no baseline), `demo-planned` (planned-dates baseline), `demo-first-as-baseline` (first update as baseline) and `reference` (the pinned third-party XERs, the large Hotel file excluded). A refactor must change no number. After an intended change, run with `XERSCOPE_UPDATE_GOLDEN=1`: that run rewrites the section and always fails by design, so a rewrite is never green; review the diff of `golden/standards.json`, then rerun without the variable |
| `test_page_golden.py` + `golden/pages.json` | characterization of what every page shows on the demo series, page by page in menu order (texts, metrics, widgets, table shapes, chart trace types); regenerated the same way with `XERSCOPE_UPDATE_GOLDEN=1` |
| `test_p6_check_schedule.py` | the P6 Check Schedule rules written from Oracle's help (P6 Professional 24 101248; EPPM 25 91574 for the default targets): one quoted sentence of the help per test (target strictness, the `x` boundary, exclusions, the started exemption, the soft constraint set), with the DCMA reading as contrast where they differ |
| `test_p6_checksched.py` | xerscope against a P6 Professional 26.8 Check Schedule report and F9 log on a synthetic project rebuilt in code |
| `test_p6_witness.py` | the P6 Check Schedule against P6 Professional 24 reports on real schedules: anonymised `.xer` and the report's counts in a local folder under `tests/reference/data/witness/`, never committed; skipped without it, so CI never runs it: run before merging a change to the checks or the CPM |
| `test_cpm.py` and `test_cpm_*.py` | real P6 files to the minute (dates, floats, longest path, assignments); each rule of the engine by hand, including a predecessor in another project of the file that shares a local Activity ID; one file per constraint, expected-finish or resource-placement case |
| `test_p6_heldout.py` | the CPM against P6 23.12's held-out corpus: a floor per set that never drops, one pinned witness activity per rule, the float-type codes read on P6's own dates |
| `test_crosscheck_mpxj.py` | the CPM against MPXJ's independent scheduler: P6 files three ways, random networks of every kind, the hand cases, the demo; open questions named in `crosscheck.UNRESOLVED`, P6-settled shapes in `P6_SETTLED` |
| `test_cpm_properties.py` | invariants on seeded random networks |
| `test_rules.py` | each check, especially where P6 and DCMA differ (helpers from `rulekit.py`) |
| `test_reference.py` | third-party stated results (MPXJ, xerlock), MPXJ as an independent reader |
| `test_weekly.py` | changelog, EV/PV, PPC, delta, WBS, MTA |
| `test_longest_path.py` | the longest path of each update and its churn: the P6 flag, the recalculated fallback, one change per activity |
| `test_driving.py` | the driving flag of each relationship: hand cases on calendar C8, the rule on P6's stored dates against the recalculated ones (reference files, held-out corpus), and against P6's own relationship date `TASKPRED.aref` |
| `test_activity_trail.py` | the task panel's analyses on hand-made networks: chain depth and direction, driving only, loops, levels, floats and constraints by update, constraint history |
| `test_forensics.py` | the half-step reading: one hand case per step, the invariants, the finish cases, the two changelog categories it needs |
| `test_calendar_and_standards.py` | calendar parsing, TOML validation |
| `test_analysis_and_viz.py` | the demo's planted findings are found, figures build |
| `test_architecture.py` | the layer rules (`LAYERS`) and the app's import edges (`APP_EDGES`) of section 7, against every import of `src/xerscope` |
| `test_load_contract.py`, `test_fuzz_parser.py` | the file boundary: a crafted `.xer` loads or raises `XerError`, never crashes or escapes |
| `test_query.py`, `test_ask_bench.py`, `test_fuzz_ask.py` | the Ask field: a sentence becomes filters, never a number; the floors of each sentence set; any sentence gives a filter and an answer |
| `test_sheets.py` | the calculation sheets against the TOML, the model and the tests |
| `test_app.py` | every page renders headless, key options work, downloads leave anonymised by default and plain with the switch off |
| `test_anonymize.py` | anonymised files give the same results (demo series, P6 exports) and hold no text of the originals |
| `test_parser.py`, `test_model.py`, `test_store.py`, `test_shapes.py` | format edge cases, P6 meaning of each column, the weekly series, the shape of the frames |
| `test_explain.py`, `test_cli.py`, `test_docker.py` | explanations match results; every command; compose / Dockerfile / Caddyfiles keep loopback-only (8501 on 127.0.0.1 in `compose.yaml`, no port in `deploy/`), non-root, nothing in `src/` reaching the network |
| `test_fitness.py`, `test_duplication.py`, `test_same_code.py`, `test_mutation.py` | the scripts of the refactoring proof (`scripts/fitness.py`, `duplication.py`, `same_code.py`, `mutation.py`) |
| `reference/` | pinned third-party files (`sources.py`: commit + SHA-256, downloaded into `reference/data/` by `fetch.py`, never vendored; the held-out corpus by `fetch_p6_heldout.py`), their stated results (`expected.py`); MPXJ's scheduler built from a pinned commit by `mpxj_cpm.py` |

The other `test_*.py` files each pin one behaviour named in their first docstring line (one per
baseline rule, page contract, check boundary or earned value case).

## 10. Decisions

The architecture decisions behind this layout (one function per check plus TOML, the layer rules,
P6 as the CPM oracle, no language model in the Ask field, the deployment's security defaults…) are
recorded one per file in [docs/adr/](adr/), each with its context, the options weighed, the choice
and its source.
