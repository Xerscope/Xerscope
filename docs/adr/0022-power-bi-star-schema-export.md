# ADR-0022: Power BI export as a star schema in Parquet or CSV

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`49ad764`, "initial git commit": `export.py` with the four tables and both formats, the Export page); CSV floats to four decimals on 2026-11-06 (`ab67657`, "CSV downloads write floats to four decimals", #119); CSV cells neutralised on 2026-11-09 (`5ca0f45`, #165, ADR-0023) |
| Scope | `src/xerscope/export.py`, `src/xerscope/store.py` (`summary`, `history`, `relationship_history`, `assignment_history`), `src/xerscope/app/views/export.py`, `src/xerscope/cli.py` (`export`) |
| Sources | [docs/user-guide.md](../user-guide.md), "Reference": "Command line" (`export`) and "Web app" (Export for Power BI); [docs/architecture.md](../architecture.md), "Outside `analysis/`" (`export.py`) and Layer rules; `pyproject.toml` (`pyarrow`, `[tool.deptry.per_rule_ignores]` `DEP002`); commits `49ad764`, `ab67657`, `5ca0f45` |

## Context

Planners and their managers build their own reports in Power BI or another BI tool. They need
the same numbers the app shows, week after week, without re-reading XER files in the BI tool
and without a second implementation of P6's meanings. The store already holds every update as
long-format frames keyed by `snapshot_idx` (ADR-0006), and an activity is identified across
weeks by its `task_code` (ADR-0003). Units matter: durations and floats are in working days of
each activity's calendar (ADR-0004), so a BI tool needs the hours per day to sum or compare them.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| One flat table per update (a CSV per week) | simplest file | the BI tool must stack the weeks and rebuild the relations; a week is not related to the others |
| A BI tool reading the XER files itself | none in xerscope | P6's meanings (status, float, calendars, critical) reimplemented in the BI model, so the numbers can disagree with the app |
| **A star schema of the store's own frames: one snapshot dimension, three fact tables, Parquet or CSV (chosen)** | four files; `pyarrow` as a dependency | the schema follows the store's columns: a renamed column is a change for every BI model built on it |

## Decision

`export.export_tables(store)` returns the store's frames under the star schema's names (the
module docstring draws it):

```
dim_snapshot (snapshot_idx)  1─*  fact_activity     (snapshot_idx, task_code)
                             1─*  fact_relationship (snapshot_idx, pred_code, succ_code)
                             1─*  fact_assignment   (snapshot_idx, taskrsrc_id; task_code)
```

| Table | Frame | One row per |
|---|---|---|
| `dim_snapshot` | `SnapshotStore.summary` | update: `snapshot_idx`, `data_date`, `source`, `project`, `forecast_finish`, activity counts by status, `critical`, `relationships`, `pct_complete_count`, `finish_shift_wd` (working days the forecast finish moved since the previous update, negative when later) |
| `fact_activity` | `SnapshotStore.history` | (update, activity), WBS summary rows excluded: `HISTORY_COLS` (dates, floats and durations in days, `hours_per_day` of the activity's calendar, status flags, constraints, labour columns) |
| `fact_relationship` | `SnapshotStore.relationship_history` | (update, relationship): `pred_code`, `succ_code`, `type`, `lag_hr`, `lag_d`, `is_external` |
| `fact_assignment` | `SnapshotStore.assignment_history` | (update, resource assignment): `taskrsrc_id`, `task_code`, resource, budgeted, actual and remaining units, dates (the internal `task_id` and `role_id` left out) |

Every fact table carries `snapshot_idx` and `data_date` (`SnapshotStore._stack`). A BI model
relates `dim_snapshot` to each fact table on `snapshot_idx`, and uses `task_code` to follow one
activity across weeks and to join assignments to their activity. `fact_activity` carries
`hours_per_day`, so days × `hours_per_day` gives back P6's hours.

**Formats** (`Fmt = Literal["parquet", "csv"]`): Parquet through pandas' engine, `pyarrow`
(declared in `pyproject.toml` and listed under `DEP002` of deptry: never imported by name), keeps
the column types; CSV goes through `export.csv_bytes`, the one CSV writer of xerscope: UTF-8
with BOM, floats to four decimals (`CSV_FLOAT_FORMAT`), dates as `DATETIME_FMT`, every text cell
passed through `csv_safe` (ADR-0023). Parquet is not neutralised: it keeps the raw text.

**Where it is written:**

- CLI: `xerscope export FOLDER [--out export] [--format parquet|csv] [--project CODE]` builds
  the store of the folder (`SnapshotStore.from_folder`) and writes one `<table>.<format>` per
  table (`write_tables`), printing each path. The CLI export is not anonymised.
- App: the page "Export for Power BI" (`app/views/export.py`) lists the four tables with their
  rows and columns, offers Parquet or CSV in one zip (`zip_tables`) and a preview of
  `fact_activity`. With the sidebar's *Anonymous exports* on (the default), the zip is built by
  `Anonymizer.frame` on each table and its name loses the project code (ADR-0015). The same page
  builds the anonymised XER extract.

`export.py` imports `store.py`, `config.py` and `csv_safe.py` only (Layer rules).

## Consequences

Positive:

- The BI tool and the app read the same frames, so their numbers agree; P6's meanings stay in
  `xer/` and `analysis/`.
- One relation on `snapshot_idx` gives every week; `task_code` follows an activity whatever its
  internal `task_id` in each export.
- Parquet keeps dates and numbers typed for Power BI; CSV opens anywhere and is safe to open in a
  spreadsheet.

Negative:

- The fact tables follow the store's columns (`HISTORY_COLS`, `REL_COLS`, `ASSIGNMENT_COLS`): a
  column renamed there changes every BI model built on the export.
- Only what the store holds is exported: per-check results (Schedule health) and earned value
  series are separate downloads of their pages, not tables of the star schema.
- Days are per activity calendar: summing `total_float_d` across calendars needs
  `hours_per_day`.

Follow-ups: none recorded in [docs/backlog.md](../backlog.md).

## Verification

- `tests/test_store.py::test_export` (the four Parquet files, a CSV zip),
  `::test_fact_activity_carries_hours_per_day_so_days_convert_back`.
- `tests/test_cli.py::test_export_csv` (`xerscope export --format csv` writes `dim_snapshot.csv`).
- `tests/test_audit_edges_app.py::test_parquet_export_with_empty_relationship_and_assignment_tables`,
  `::test_csv_export_neutralises_formula_cells` (CSV neutralised, Parquet raw).
- `tests/test_anonymize.py::test_csv_exports_write_hours_to_four_decimals`.
- `tests/test_app.py::test_exports_are_anonymised_by_default_and_plain_when_switched_off`.
- `tests/test_architecture.py::test_layer_imports_match_the_architecture_doc` (`LAYERS["export"]`).

## References

- `src/xerscope/export.py`: `Fmt`, `export_tables`, `CSV_FLOAT_FORMAT`, `csv_bytes`, `_bytes`,
  `write_tables`, `zip_tables`, `zip_frames`.
- `src/xerscope/store.py`: `HISTORY_COLS`, `REL_COLS`, `ASSIGNMENT_COLS`, `SnapshotStore._stack`,
  `history`, `relationship_history`, `assignment_history`, `summary`.
- `src/xerscope/app/views/export.py`; `src/xerscope/cli.py`: `_args_export`, `_cmd_export`.
- [docs/user-guide.md](../user-guide.md), "Reference": "Command line" and "Web app"; [docs/architecture.md](../architecture.md),
  "Outside `analysis/`" (`export.py`).
- Related: ADR-0003 (identity by `task_code`), ADR-0004 (units), ADR-0006 (the store),
  ADR-0015 (anonymised downloads), ADR-0023 (CSV neutralisation).
