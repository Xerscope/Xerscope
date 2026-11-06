# Code walkthrough

Data flows one way:

```
.xer bytes ─▶ parser ─▶ RawXer ─▶ model ─▶ Snapshot ─▶ SnapshotStore ─▶ analyses ─▶ pages / CLI / Power BI
             (format)            (P6 meaning)      (weekly series)
```

## 1. `xer/parser.py`: the file format

The XER format is tab-separated:

- `ERMHDR` line: version and export date;
- `%T` starts a table, `%F` gives its fields, `%R` is a row, `%E` ends the file.

`parse_bytes` behaviour:

- **Encoding:** tries UTF-8 (with or without BOM), then cp1252, which is what P6 writes on
  Windows.
- **Lines:** splits on `\n` only, because calendar blobs can contain `\r`.
- **Short rows:** padded to the field count.
- **Values:** everything is kept as **strings**. The parser knows the format, not P6.

Output: `RawXer(tables: {name: DataFrame[str]}, version, export_date, encoding, warnings)`.
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
| Data date | `PROJECT.last_recalc_date`, else the planned start |
| Units | durations and float stored in hours; `_d` columns are working days of the activity's calendar (`day_hr_cnt`) |
| Lag | `lag_hr` as stored; `lag_d` on the predecessor's calendar (Oracle's conversion rule) |
| Critical | project definition: total float ≤ `critical_drtn_hr_cnt`, or longest path |
| % complete | by `complete_pct_type`: physical, duration, units |
| Best dates | `start` / `finish` = actual > remaining early (`restart_date` / `reend_date`) > early > planned |
| Forecast finish | latest activity finish (`scd_end_date` can be stale: kept, with a warning) |
| Labour hours | TASK budgeted/actual/remaining labour units (nonlabor in `nonlabor_*_qty`), else assignments by resource type |
| Assignments | `assignments` = TASKRSRC typed: resource type (TASKRSRC, else RSRC; `role` for role-only), name, resource calendar, driving flag, units, rates, lags, dates |
| EV technique | `ev_compute_type` / `ev_user_pct` of each activity's WBS; `Snapshot.wbs` also holds `ev_etc_compute_type` / `ev_etc_user_value` (ETC technique, reported, not applied) |
| Links | `relationships`: codes and both lags (hours and days); `is_external` flags a predecessor in another project. A predecessor that is a `TASK` row of another project of the same file is named `[ext]{task_id}` in `pred_code`, as in `external_links`, never by its own Activity ID: that ID may also exist in this project and would read as a link from the local activity. Links whose other end has no `TASK` row in the file are dropped from `relationships`. `external_links` keeps the links to and from other projects (same `[ext]` naming) |
| Calendars | `work_calendars` (parsed `clndr_data`), `calendar(id)` falls back to the project's |
| Options | `options["sched"]` = the raw SCHEDOPTIONS row, `options["project"]` = the raw PROJECT critical-path and plan-end fields, `progressed` (retained logic / progress override / actual dates), `must_finish_by`, `lag_calendar` (successor when blank, per Oracle), `critical_*` |

`Snapshot.activities` excludes WBS summary rows: every count and chart uses it.

**Snapshot contract.** `model.py` declares the minimum columns of each frame: `TASK_COLS` plus
`LABOR_COLS` for `tasks`, `REL_COLS_MODEL` for `relationships`, `ASSIGNMENT_COLS_MODEL` for
`assignments`. `build_snapshot` raises `XerError` if one is missing, and the store's
`HISTORY_COLS`, `REL_COLS` and `ASSIGNMENT_COLS` must be subsets (checked in `tests/test_store.py`).
The frames may carry more (raw XER columns); the lists are a floor, not a filter.

## 3. `xer/calendar.py`: working time

- **`WorkCalendar`:** working periods per weekday plus dated exceptions, parsed from the
  `clndr_data` tree `(0||name(attrs)(children))`.
- **`TimeAxis`:** the same periods laid out on an absolute minute axis with cumulative
  work, which makes every date computation exact (details in [cpm.md](cpm.md)).

## 4. `store.py`: the weekly series

`SnapshotStore` sorts snapshots by data date and holds one per data date: given two files
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
| `p6/check_schedule.py`, `dcma/fourteen_point.py`, `decm/schedule_metrics.py`, `integrity.py` | context → `RuleOutput(flagged, numerator, denominator, value)` | the built-in standards: one explicit function per check, its docstring quoting the source |
| `populations.py` | snapshot → named, sourced population steps (`EXCLUSIONS`, `Funnel`) and the other building blocks (with a predecessor, into open work…) | the one vocabulary of exclusions (complete, LOE, milestones…) that every standard's checks and the parameterised rules use |
| `rules.py` | the `@rule` registry; `AnalysisContext` + parameters → `RuleOutput` | parameterised rules (`exclude`, `links`, `op`, `value`, `unit`…) for your own standard, and helpers shared with the explicit checks |
| `standards.py` | TOML → `Standard(metrics)` | validated on load (rule, parameter names, population keywords, target syntax) |
| `checks.py` | standard + `AnalysisContext` (defined in `rules.py`) → `CheckResult` per metric; `health_history` over the series | a failing rule returns status "error", never crashes the page |
| `baseline.py` | BL snapshot (or planned dates) → frame `bl_start, bl_finish, bl_labor_hr…` | shared by BEI, missed, late, PV |

**Baseline sources.** A baseline is one of: a separate XER, a loaded update, the planned dates of each update
(`Baseline.planned`), or the project the file itself names as the P6 Project Baseline. For the last,
`Snapshot.file_baseline` reads `PROJECT.sum_base_proj_id` of the analysed project (Oracle P6 EPPM XER
Import/Export Data Map, table PROJECT, v23: "Project Baseline"; `orig_proj_id` = "Original Project"; v26 map
not found, same XER format, unverified on 26). It is usable when that project is another PROJECT row of the
same file that owns activities and, when its `orig_proj_id` is filled, names the analysed project; otherwise
`note` says why not and the sidebar's choice applies. The app builds that project as a snapshot
(`load_snapshot(..., project_id=)`, exact because a baseline copy may carry the code of the project it was
copied from) and `Baseline.from_snapshot` gives its dates (actual > remaining > early = BL Project
Start / Finish). The sidebar choice "Baseline in each file" is the default when a ticked file has one; a file
without one has no baseline for that update (checks that need one are n/a), stated in the window's Selection details.
The memo key holds the project each file names and the fallback. In that mode a second selector, "When a file
has no baseline" (a separate baseline file, a loaded update, the planned dates, None; None by default, never
chosen for the user), gives the baseline of the updates whose file has no usable one, update by update.
`Baseline.source` says where the baseline of an update comes from; `run_metric` copies it to
`CheckResult.baseline` for every check the baseline changes (`needs_baseline`, the dangling logic and DCMA-08
readers, the `duration` rule on the baseline), `"none"` when it needs one and has none. `explain` carries it, the
Health and Audit panels print it under the check, and the exported notes (summary CSV, all sets) end with
`baseline: <source>`. Every page opens with a one-line context banner (`state.page_header`): the projects
read, the data date of the update shown, where the baseline `baseline_for` gives it comes from (in file,
fallback, planned dates, a loaded update, a separate file, none), the EV basis, costs on or off, and the count of files and projects; its
help reads "Baseline used for <update>: <source>", and pressing it opens the Files and baseline window. Health,
Audit and Earned value add the baseline's warnings under it (`state.baseline_warnings`; the Earned value curves
measure every update against the baseline of the one shown, the BEI against each update's own). Warnings name the files: in the sidebar, updates without a usable
baseline and what applies instead, a pointer that is not used and why (absent project, `orig_proj_id` of
another project, no activities), a series that mixes sources; on the pages, a baseline whose data date is after
the update's and a baseline that finds fewer than 90 % of the update's activities (the 06A501a / DCMA-11
"N of M matched" count). P6-12 and P6-13 read `context.baseline` like every rule that
needs one: they get the baseline of the sidebar choice (the file's, a separate XER, the planned dates) and
carry no pointer logic of their own.
| `cpm.py` | snapshot → early/late dates, floats, longest path, `rem_override_hr` (remaining set by an expected finish), assignment dates; `compare_with_stored`, `compare_assignments`; `critical_path_test` | see [cpm.md](cpm.md) |
| `changelog.py` | two snapshots → one row per change | dates and durations in working days |
| `evm.py` | baseline + series → PV curve, EV/AC/SPI per update, forecast curve | labour units as P6: PV = BL × Schedule % Complete (exact working time), EV = BL × Performance % Complete (WBS EV technique); cost: BAC from `target_cost`, PV per assignment, EV = BAC × Performance %, SPI = EV cost / PV cost |
| `progress.py` | series → MTA trend, PPC, progress delta | PPC = W-1 finish and start commitments, W outcome |
| `wbs.py` | snapshot → WBS tree with roll-ups | % complete weighted by hours, else duration |
| `explain.py` | `CheckResult` → formula, verdict, population, effective parameters, source | read-only account of a result, shown under every check in the app |
| `query.py` | a sentence ("critical not started in civil works") → `Filter`: the Gantt page's filters (WBS node, status, float category, activity codes, resources, milestones, LOE, text) | picks filters the page offers, computes nothing; a bilingual keyword grammar over the file's own lexicon (`Vocabulary`: WBS, code values, resources, the words of the activity names; a search word the file does not hold is dropped and named), with a `Backend` hook for a local language model that may decline, in which case the grammar answers |

Standards are data in `standards/*.toml`:

- `p6.toml`: P6 Professional 24 Check Schedule (17 checks: the 14 of the help plus out of sequence and dangling start/finish from a P6 Professional report; Oracle's groups; Invalid Progress Dates on two lines, P6-10a / P6-10b, as the report prints it);
- `decm.toml`: DCMA DECM v8.0, Guideline 6 schedule tests;
- `dcma.toml`: DCMA 14-Point (legacy);
- `integrity.toml`: recalculation of activities and assignments, and the warnings, errors and exceptions of the P6 scheduling log (loops, open ends, out-of-sequence progress, actual dates after the data date, unsatisfied constraints and relationships);
- `custom-template.toml`: the commented starting point for your own.

Why explicit functions plus TOML: P6's "Large Float" (`p6_06_large_float`) and DCMA-06
look alike but differ in unit and population. Each built-in check is one function that
reads like its source text, so a reviewer can hold it against the Oracle page or the DCMA
sheet; the TOML holds only the target and the source. Your own standard picks the
parameterised rules of `rules.py` (`float` among them) and sets units, exclusions and
targets as data.

Layer rules (imports, as the code has them; `tests/test_architecture.py` holds the same list and
checks the code against it, so a change here must be made there too):

- `xer/` imports only `config.py`; it knows nothing of the layers above.
- `store.py` imports `xer/` and `config.py`; `export.py` imports `store.py` and `config.py`;
  `anonymize.py` imports `xer/` only.
- `analysis/` imports `xer/` and `store.py`; never `viz/`, `app/` or `verify/`.
- `viz/` imports `config.py` and, from `analysis/wbs.py`, the constant `ROOT` only: it draws
  frames, it does not compute schedule results.
- `verify/` imports `xer/`, `analysis/cpm.py` and `config.py`; `crosscheck.py` re-exports it.
  Nothing in the app depends on it.
- `sample.py` imports `xer/`, `analysis/cpm.py` and `config.py`.
- `app/` imports `xer/`, `store.py`, `analysis/`, `viz/`, `export.py`, `anonymize.py` and `config.py`, and is imported
  by nothing but Streamlit and `cli.py`. Pages
  compose analyses and figures (some computation still sits in the views: see
  [backlog.md](backlog.md), Structure).
- `cli.py` is the entry point: it imports every layer, `app/diagnostic.py` included (`pv-compare`
  reads the same frames as the Debug page).

Outside `analysis/`:

- `config.py`: `Settings`, the few tunable defaults no standard owns (hours per day when a
  calendar is missing, critical and near-critical float for the Gantt colours). Settings are consumed at
  `build_snapshot` time (`xer/model.py`) and by `viz/gantt`; analysis reads the derived columns.
- `export.py`: the Power BI star schema (`export_tables`, written as Parquet or CSV, also zipped).
- `sample.py`: the demo series generator, with the findings it plants week by week.
- `anonymize.py`: anonymised copies of the loaded XER files and of every table the app hands
  out while the sidebar switch "Anonymous exports" is on (the default, per session): page CSVs,
  Schedule health lists, the Power BI zip (`Anonymizer.frame` on each table, no project code in
  the file name), the Debug diagnostic. Off, the same downloads carry the files' own codes and
  names; the XER extract stays anonymised. The pages always show the files' own data. An allowlist
  per table keeps keys, dates, durations, units, flags and P6 enumerations; codes get new
  values, `X<kind>` and the first hex digits of an HMAC-SHA256 of the original under a key
  drawn for the session (8 for activities; two IDs on one code are refused), names are rebuilt
  from them, costs set to 0, user, database and free text removed, unknown tables and columns
  left out and named. The `note` column (the rules' notes) is kept with each Activity ID and
  file name in it renamed; the rules write nothing else of the file into a note. A download reads only its own files (the update shown, W-1 and W for the
  changelog and PPC, the baseline's file when it lists baseline fields, every file for Power BI
  and the XER extract), and an activity keeps one code in every download of the session. Every
  output field is compared with the text values of the files read before it is handed out. The
  key and the mappings live in the session only.

### `verify/`: independent checks, strongest source first

| Module | Source | Role |
|---|---|---|
| `p6_corpus.py` | P6 Professional 23.12.1's own output on the held-out corpus (`p6_heldout_score`) | the oracle for the CPM: every rule the engine takes from it is pinned by a corpus activity in `tests/test_p6_heldout.py` |
| `mpxj_cpm.py` | MPXJ's PrimaveraScheduler (`mpxj_schedule`, `cpm_crosscheck`) | a second engine, a hint only: `P6_SETTLED` lists the shapes P6 settled against it, `UNRESOLVED` the open ones, `mpxj_inconsistent` its self-contradictions |
| `mpxj_reader.py` | MPXJ as a reader (`compare_file`, `compare_paths`) | the XER tables read two ways |
| `shapes.py` | the file's own stored dates (`difference_report`) | `xerscope recalc --report`: differences grouped by activity shape (status · type · constraint · links · option), so one week's differences point at one rule |

`crosscheck.py` re-exports all of it; the CLI and the tests import from there.

## 6. `viz/`: figures

- **`gantt.py`, `gantt.js`, `gantt.css`:** the Gantt grouped by WBS, laid out like P6's
  Activities view: a tree grid (Activity / WBS, % complete, float) on the left and the
  timeline on the right, one row each. `gantt_rows` builds the rows in P6 order (each
  WBS node, its own activities, then its child nodes) with float-category colours,
  comparison dates and finish shifts; `gantt_data` hands them, with the options, to a
  Streamlit component (`app/ui.py: GANTT`, `st.components.v2`) mounted in the page.
  A click on a WBS row opens or closes it; a click on an activity row or bar sends its row
  id (`"a:<Activity ID>"`) and nothing else.
  WBS rows open and close in the browser, without a rerun; only the rows in view are
  in the page, so a schedule of 15,000 activities scrolls like a small one. There is
  no zoom, only a month or week timescale. Schedule text reaches the browser only as the
  component's data and is never parsed as HTML (`textContent` only; `gantt.js` holds no
  network call, checked by a test). Page colours and font come from the theme's `--st-*`
  variables, so the Gantt follows a theme switch without a rerun.
- **`charts.py`:** S-curve, indices, MTA, PPC and metric trend, and the app's colours
  (`STATUS`, `SERIES`, `NEUTRAL`), one set for both themes, each mark >= 3:1 on
  the light and the dark background: the Gantt bars and the check-status labels in
  `app/ui.py` derive from them. `ACCENT` (decoration in `style.css`) is the one colour set
  per theme, the theme's link colour, applied through CSS `light-dark()`. Text, grid and axes
  are left to Streamlit's Plotly theme (`style.css` only fades the grid), so the charts
  follow a theme switch without a rerun. The series palette is a fixed
  categorical order, validated for colour-blind separation; status hues never decorate.
  There is one y-axis per chart.

## 7. `app/`: Streamlit

- **`streamlit_app.py`:** declares the pages (`st.navigation`); the Debug page is left out on a
  locked deployment unless `XERSCOPE_DEBUG_PAGE=1` (`state.debug_page`).
- **`state.py`:** the sidebar, whose Files and Baseline lines open one window (`st.dialog`,
  `_window`: files read on Done, baseline selectors kept in session state while it is closed;
  shortcuts F, B and Ctrl+Enter for Done), pickers, a per-session cache keyed on the loaded
  files, and the list of standards (built-in, `XERSCOPE_STANDARDS`, uploaded). One update for
  the session: `snapshot_picker` writes the choice to `snap_choice`, every page's picker starts
  from it; `go_to` / `open_in_gantt` write the session then switch page (a check's tasks to the
  Gantt, a table row to the Gantt, a check to the Audit). Two threads (`background_jobs`, off
  with `XERSCOPE_SYNC_LOAD=1`, which the tests set): on Done the most recent file is read in the
  script run and the pages open on it while `LoadJob` reads the others, most recent first, the
  store growing on each poll (`_poll_load`, a fragment); once the series is complete the Overview
  computes the built-in standards on the latest update in `ScoreJob` and writes the results where
  `metric_result` reads them. Neither thread touches the session state: the script run collects
  what they produced. A memo entry computed on a partial series carries that series in its key. The cache (`memo`) keys every entry on the files, the
  project read from each and the baseline in use, then on what the analysis reads; it keeps the
  `MEMO_SIZE` most recently used entries. An analysis that reads no baseline (change log, PPC,
  milestones, exports, forecast) or not the EV basis (the checks, the WBS rollup) leaves it out of
  its key. `metric_result` holds one result per (metric, update, baseline): Schedule health,
  Audit and the BEI of Earned value read the same entry; no check reads the columns the EV basis
  sets (`baseline.EV_COLS`). Series over every update (the health trend, computed on request,
  and the BEI series) reuse the entries there and keep only their numbers. A built download
  (Schedule health's sets, the Debug zip) is offered again only for the same `data_identity`.
- **`ui.py`:** the shared look (the page header and its context banner are in `state.py`): the KPI
  readout (one line per figure, a change of zero drawn neutral), column filters on long tables, one column-label dictionary (`task_code` → "Activity ID", dates and units
  formatted the same everywhere), status colours (red / amber / green reserved for status).
- **`.streamlit/config.toml`:** the light and dark themes (warm neutrals, petrol accent) and server settings
  (localhost only). `xerscope app` runs Streamlit from the app folder, so it applies
  wherever the command is started.
- **`static/`:** the fonts the theme loads (Onest, JetBrains Mono;
  variable woff2, latin subset, SIL OFL 1.1 with their licences), served by the app itself
  (`enableStaticServing`).
- **`style.css`:** what the theme cannot set (the KPI readout, the activity card under the Gantt, the milestone picker's tags in
  their line colour), sent by `ui.apply_style()` with the colours of `viz/charts.py`.
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
- **`sheets/<standard>/<id>.md`:** one calculation sheet per check (P6 for now), shown on the
  Audit page: population and counted items with their XER fields, the Oracle text it follows,
  a worked example, the key to change. `tests/test_sheets.py` keeps each sheet on the TOML's
  target and parameters, on fields and codes the model reads, on tests that exist.
- **Debug:** what xerscope read and decided for one update, to hold against P6 without the
  file: the scheduling options (raw XER value, value applied, blank-in-file defaults), the
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
  and block 11, the project settings of every project of the file (`PROJECT_SETTING_COLUMNS`, carried by
  the same `Snapshot.file_projects` rows, `absent` for a column the file lacks; of
  `baseline_names_to_export` only the number of names) with its tasks by `complete_pct_type`, and what
  each setting is in the XER data map and the P6 help (`SETTINGS_MEANING`). No KPI reads it.
  `app/diagnostic.py` builds the tables from the existing results; with anonymous exports on,
  `Anonymizer.zip_frames` hands them out with the codes of the anonymised extract (dates
  unchanged, cost figures 0 as in the extract).
- **Pages:** one file per page in `views/`. Pages compose analyses and figures; the
  Plotly figures are built in `viz/`.
- **`task_panel.py`:** one activity, named by its Activity ID: its card in the update shown
  (P6 properties, resource assignments, logic) and its history across updates. Opened under
  the Gantt for the activity picked there (`task_from_row_id` accepts an `a:` row id only, and
  the page only an activity the chart draws); every value is read from the snapshot or the
  store, card text is escaped. The Task history page draws the same history.

## 8. `cli.py`

| Command | Does |
|---|---|
| `app` | launches the UI on localhost (`--data`, `--baseline`, `--standards`, `--port`, `--host`) |
| `check` | runs a standard on files and prints the P6-style summary (`--baseline` or `--planned-baseline`, `--baseline-in-file` for the P6 Project Baseline each file holds, `--out` CSV, `--flagged DIR` for the items behind each count, `--expect CSV` to diff against a P6 Check Schedule summary, `--fail-on fail` for CI) |
| `recalc` | reschedules and compares with stored dates (`--out` CSV, `--report` groups the differences by activity shape, `--show N`) |
| `changelog` | changes between two files |
| `standards` | lists standards and rules, or writes the template |
| `export` | Power BI tables |
| `crosscheck` | compares the reading with MPXJ (Java); `--cpm` the recalculation with MPXJ's scheduler and the stored dates; `--p6` with P6's held-out corpus |
| `info` | one line per snapshot (`--project`) |
| `sample` | generates the demo series |

## 9. Tests (`tests/`)

| File | What it pins |
|---|---|
| `rulekit.py` | shared helpers of the rule tests: the built-in standards loaded once (`STANDARDS`), `run(std, metric_id, snapshot, baseline)`, `run_on_store(store, index, metric_id)` (the first update as baseline), `codes(result)` (flagged Activity IDs), `counts(result)` (numerator, denominator) |
| `test_characterization.py` + `golden/standards.json` | characterization (golden) test: status, numerator, denominator, value and flagged identifiers (Activity IDs or `pred->succ`, never names; a note only for an error) of every metric of every built-in standard, in four sections: `demo` (the demo series, no baseline), `demo-planned` (planned-dates baseline), `demo-first-as-baseline` (first update as baseline) and `reference` (the pinned third-party XERs, the large Hotel file excluded). A refactor must change no number. After an intended change, run with `XERSCOPE_UPDATE_GOLDEN=1`: that run rewrites the section and always fails by design, so a rewrite is never green; review the diff of `golden/standards.json`, then rerun without the variable |
| `test_p6_check_schedule.py` | the P6 Check Schedule rules written from Oracle's help (P6 Professional 24 101248; EPPM 25 91574 for the default targets): one quoted sentence of the help per test (target strictness, the `x` boundary, exclusions, the started exemption, the soft constraint set), with the DCMA reading as contrast where they differ |
| `xerkit.py` | builds tiny XERs in code (numeric ids, full calendars, as P6 writes them), so each expected number is countable by hand and any reader sees the same file |
| `test_cpm.py` | real P6 files to the minute (dates, floats, longest path, assignments); each rule of the engine by hand, including a predecessor in another project of the file that shares a local Activity ID |
| `test_p6_witness.py` | the P6 Check Schedule against P6 Professional 24 reports on real schedules: anonymised `.xer` and the report's counts in a local folder under `tests/reference/data/witness/`, never committed; skipped without it, so CI never runs it: run before merging a change to the checks or the CPM |
| `test_p6_heldout.py` | the CPM against P6 23.12's held-out corpus: a floor per set that never drops, one pinned witness activity per rule, the float-type codes read on P6's own dates |
| `test_crosscheck_mpxj.py` | the CPM against MPXJ's independent scheduler: P6 files three ways, random networks of every kind, the hand cases, the demo; open questions named in `crosscheck.UNRESOLVED`, P6-settled shapes in `P6_SETTLED` |
| `test_cpm_properties.py` | invariants on seeded random networks |
| `test_rules.py` | each check, especially where P6 and DCMA differ (helpers from `rulekit.py`) |
| `test_reference.py` | third-party stated results (MPXJ, xerlock), MPXJ crosscheck |
| `test_weekly.py` | changelog, EV/PV, PPC, delta, WBS, MTA |
| `test_calendar_and_standards.py` | calendar parsing, TOML validation |
| `test_analysis_and_viz.py` | the demo's planted findings are found, figures build |
| `test_app.py` | every page renders headless, key options work, downloads leave anonymised by default and plain with the switch off |
| `test_anonymize.py` | anonymised files give the same results (demo series, P6 exports) and hold no text of the originals |
| `test_parser.py`, `test_model.py`, `test_store.py`, `test_shapes.py` | format edge cases, P6 meaning of each column, the weekly series, the shape of the frames |
| `test_explain.py`, `test_cli.py`, `test_docker.py` | explanations match results; every command; compose / Dockerfile / Caddyfiles keep loopback-only (8501 on 127.0.0.1 in `compose.yaml`, no port in `deploy/`), non-root |
| `reference/` | pinned third-party files (`sources.py`: commit + SHA-256, downloaded by `fetch.py`; the held-out corpus by `fetch_p6_heldout.py`), their stated results (`expected.py`); MPXJ's scheduler built from a pinned commit by `mpxj_cpm.py` |
