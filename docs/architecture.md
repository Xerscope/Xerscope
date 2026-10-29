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

## 2. `xer/model.py`: what P6 means

`build_snapshot(raw)` picks one project (the one with the most activities, or
`project_code`) and builds a typed `Snapshot`. Each P6 rule lives in one place:

| Concern | Rule |
|---|---|
| Identity | Activities keyed by `task_code` (Activity ID), not `task_id`, which changes on re-import |
| Data date | `PROJECT.last_recalc_date`, else the planned start |
| Units | durations and float stored in hours; `_d` columns are working days of the activity's calendar (`day_hr_cnt`) |
| Lag | `lag_hr` as stored; `lag_d` on the predecessor's calendar (Oracle's conversion rule) |
| Critical | project definition: total float ≤ `critical_drtn_hr_cnt`, or longest path |
| % complete | by `complete_pct_type`: physical, duration, units |
| Best dates | `start` / `finish` = actual > early > remaining > planned |
| Forecast finish | latest activity finish (`scd_end_date` can be stale: kept, with a warning) |
| Labour hours | TASK budgeted/actual/remaining labour units (nonlabor in `nonlabor_*_qty`), else assignments by resource type |
| Assignments | `assignments` = TASKRSRC typed: resource type (TASKRSRC, else RSRC; `role` for role-only), name, resource calendar, driving flag, units, rates, lags, dates |
| EV technique | `ev_compute_type` / `ev_user_pct` of each activity's WBS |
| Links | relationships with codes and both lags (hours and days); links to other projects flagged and kept in `external_links` |
| Calendars | `work_calendars` (parsed `clndr_data`), `calendar(id)` falls back to the project's |
| Options | `options["sched"]` = the raw SCHEDOPTIONS row, `progressed` (retained logic / progress override / actual dates), `must_finish_by`, `lag_calendar` (successor when blank, per Oracle), `critical_*` |

`Snapshot.activities` excludes WBS summary rows: every count and chart uses it.

## 3. `xer/calendar.py`: working time

- **`WorkCalendar`:** working periods per weekday plus dated exceptions, parsed from the
  `clndr_data` tree `(0||name(attrs)(children))`.
- **`TimeAxis`:** the same periods laid out on an absolute minute axis with cumulative
  work, which makes every date computation exact (details in [cpm.md](cpm.md)).

## 4. `store.py`: the weekly series

`SnapshotStore` sorts snapshots by data date and exposes long-format frames:

- `history`: one row per (snapshot, activity);
- `relationship_history`;
- `assignment_history`: one row per (snapshot, resource assignment);
- `summary`: one row per snapshot.

Week-over-week analysis becomes a groupby; Plotly and Power BI read the same frames.

## 5. `analysis/`: everything computed

| Module | Input → output | Notes |
|---|---|---|
| `rules.py` | context + parameters → `RuleOutput(flagged, numerator, denominator, value)` | the only check code; one function per check, parameterised (`exclude`, `links`, `op`, `value`, `unit`…) |
| `standards.py` | TOML → `Standard(metrics)` | validated on load (rule, parameter names, population keywords, target syntax) |
| `checks.py` | standard + `AnalysisContext` → `CheckResult` per metric; `health_history` over the series | a failing rule returns status "error", never crashes the page |
| `baseline.py` | BL snapshot (or planned dates) → frame `bl_start, bl_finish, bl_labor_hr…` | shared by BEI, missed, late, PV |
| `cpm.py` | snapshot → early/late dates, floats, longest path, assignment dates; `compare_with_stored`, `compare_assignments`; `critical_path_test` | see [cpm.md](cpm.md) |
| `changelog.py` | two snapshots → one row per change | dates and durations in working days |
| `evm.py` | baseline + series → PV curve, EV/AC/SPI per update, forecast curve | labour units as P6: PV = BL × Schedule % Complete (exact working time), EV = BL × Performance % Complete (WBS EV technique) |
| `progress.py` | series → MTA trend, PPC, progress delta | PPC = Last Planner (W-1 commitments, W outcome) |
| `wbs.py` | snapshot → WBS tree with roll-ups | % complete weighted by hours, else duration |

Standards are data in `standards/*.toml`:

- `p6.toml`: P6 Professional 24 Check Schedule (14 checks, Oracle's groups);
- `decm.toml`: DCMA DECM v8.0, Guideline 6 schedule tests;
- `dcma.toml`: DCMA 14-Point (legacy);
- `integrity.toml`: recalculation of activities and assignments, out-of-sequence progress;
- `custom-template.toml`: the commented starting point for your own.

Why rules plus TOML: P6's "Large Float" and DCMA-06 are one function (`float`) with
different units and populations. A difference between standards is a parameter you can
read and test, not a second implementation.

## 6. `viz/`: figures

- **`gantt.py`:** status-coloured bars, comparison outlines, milestones, logic links, a
  data-date line and WBS summary bars (`wbs_rows`).
- **`charts.py`:** S-curve, indices, MTA, PPC and metric trend. The palette is a fixed
  categorical order, validated for colour-blind separation. There is one y-axis per chart.

## 7. `app/`: Streamlit

- **`streamlit_app.py`:** declares the pages (`st.navigation`).
- **`state.py`:** the sidebar (files, baseline), pickers, a per-session cache keyed on the
  loaded files, and the list of standards (built-in, `XERSCOPE_STANDARDS`, uploaded).
- **`ui.py`:** the shared look: page header (project · data date · baseline), bordered KPI
  cards, one column-label dictionary (`task_code` → "Activity ID", dates and units
  formatted the same everywhere), status colours (red / amber / green reserved for status).
- **`.streamlit/config.toml`:** the theme (white page, navy accent) and server settings
  (localhost only). `xerscope app` runs Streamlit from the app folder, so it applies
  wherever the command is started.
- **Schedule health:** a summary row per check, then one panel per check: what it measures,
  the calculation with its numbers (`analysis/explain.py`), the population (exclusions),
  the effective parameters (standard or default), the source, and the flagged items.
  All flagged items of all checks export as one CSV, the audit trail behind the scores.
- **Pages:** one file per page in `views/`. Pages only compose analyses and figures; no
  calculation lives in a page.

## 8. `cli.py`

| Command | Does |
|---|---|
| `app` | launches the UI on localhost (`--data`, `--baseline`, `--standards`, `--host`) |
| `check` | runs a standard on files and prints the P6-style summary (`--out` CSV) |
| `recalc` | reschedules and compares with stored dates (`--out` CSV) |
| `changelog` | changes between two files |
| `standards` | lists standards and rules, or writes the template |
| `export` | Power BI tables |
| `crosscheck` | compares the reading with MPXJ (Java) |
| `info` | one line per snapshot |
| `sample` | generates the demo series |

## 9. Tests (`tests/`)

| File | What it pins |
|---|---|
| `xerkit.py` | builds tiny XERs in code, so each expected number is countable by hand |
| `test_cpm.py` | real P6 files to the minute (dates, floats, longest path, assignments); each rule of the engine by hand |
| `test_rules.py` | each check, especially where P6 and DCMA differ |
| `test_reference.py` | third-party stated results (MPXJ, xerlock), MPXJ crosscheck |
| `test_weekly.py` | changelog, EV/PV, PPC, delta, WBS, MTA, CLI |
| `test_calendar_and_standards.py` | calendar parsing, TOML validation |
| `test_analysis_and_viz.py` | the demo's planted findings are found, figures build |
| `test_app.py` | every page renders headless, key options work |
| `reference/` | pinned third-party files (commit + SHA-256), downloaded by `fetch.py` |
