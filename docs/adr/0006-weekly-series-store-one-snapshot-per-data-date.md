# ADR-0006: A weekly series store: one snapshot per data date, long-format frames for every analysis

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29: `SnapshotStore` and its long-format frames in `49ad764` (initial commit; two files sharing a data date then only gave a warning); 2026-11-03: `selection()` in `1554780` (#35) and the refusal of a duplicate data date (`DuplicateDataDate`) in `70fdbec` (#54) |
| Scope | `src/xerscope/store.py`; project selection in `src/xerscope/xer/model.py`; readers of the frames: `export.py`, `analysis/progress.py`, `app/files_window.py`, `cli.py`; `app/loading.py` builds the store and catches `DuplicateDataDate` |
| Sources | [docs/architecture.md §4](../architecture.md) (`store.py`: the weekly series); `store.py` module docstring; `tests/test_store.py`, `tests/test_model.py` |

## Context

xerscope reads a series of weekly P6 updates of one project. Its subject is the series, not a
single file: slippage, changes between W-1 and W, earned value over time, PPC, milestone trend,
the health of each update. Every one of those analyses needs the updates in time order and a way
to line up the same activity across them (by `task_code`, see ADR-0003).

Three forces shape the store:

- **The data date is the key of the series.** The earned-value, health and changelog histories
  are indexed on it. Two files with the same data date are, in practice, two versions of one draft
  or an update and its baseline copy; the file name does not say which one is the update.
- **One frame shape for every consumer.** pandas analyses, Plotly figures and the Power BI export
  must read the same numbers, so they must read the same frames.
- **A file can hold several projects** (a portfolio export, an update with its baseline copy).
  Which project a file is read for must be decided by a stated rule and shown to the user.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| A list of `Snapshot` objects, each analysis looping over it and building its own frame | none up front | every analysis re-implements the stacking; the charts and the Power BI tables can drift from the analyses |
| Wide frames (one column per week) | natural for a one-off pivot | a new week is a new column; Plotly and Power BI read long data; comparing W with W-1 needs column arithmetic |
| **A store sorted by data date, one snapshot per data date, exposing long-format frames (chosen)** | one class; the refusal of duplicates puts a decision on the user | the whole series is held in memory |

Keeping the last of several files with one data date silently (by name or by modification time)
is the obvious alternative to refusing them; the store's comment states why it is not done: which
file is the update "is the user's call, not the file name's". No other alternative is recorded in
the history.

## Decision

`SnapshotStore` (`store.py`) is the weekly series:

- **Construction.** `SnapshotStore(snapshots)`, `SnapshotStore.from_paths(paths, project_code)`,
  `SnapshotStore.from_folder(folder, pattern, project_code)` (`.xer` files found by
  `xer.xer_files`, or a glob `pattern`; no file raises `FileNotFoundError`). An empty series raises
  `ValueError("no snapshot")`.
- **Order.** Snapshots are sorted by data date, then by source name (`_sort_key`); a snapshot
  without a data date sorts last.
- **One update per data date.** Files that share a data date raise `DuplicateDataDate` (a
  `ValueError`), whose message names every file of each such date:
  `several files per status date, keep one per date: <date>: <file>, <file>`. The user keeps one.
  Two updates on the same day at different hours are kept, in time order, with a warning
  (`several updates on <day> at other hours: ...`); a series whose project codes differ is kept
  with a warning (`project code differs across snapshots (renamed or other project)`). The
  snapshots' own load warnings are gathered in `SnapshotStore.warnings`.
- **Access.** `first`, `latest`, `labels`, `index_of`, `by_label`, `previous`, iteration and indexing.
- **Long-format frames**, each row keyed by `snapshot_idx` and `data_date` inserted first
  (`_stack`), cached per store (`functools.cached_property`):
  - `history`: one row per (snapshot, activity), WBS summary rows excluded, columns `HISTORY_COLS`
    (a subset of the model's `TASK_COLS` + `LABOR_COLS`; internal keys such as `task_id` and raw
    P6 values that a derived column replaces are left out; `hours_per_day` is kept so the `_d`
    columns convert back to P6's hours);
  - `relationship_history`: one row per (snapshot, relationship), `REL_COLS` (= the model's
    `REL_COLS_MODEL`);
  - `assignment_history`: one row per (snapshot, resource assignment), `ASSIGNMENT_COLS` (the
    model's `ASSIGNMENT_COLS_MODEL` without `task_id` and `role_id`);
  - `summary`: one row per snapshot (source, project, forecast finish, activity counts by status,
    critical count, relationships, `pct_complete_count`, and `finish_shift_wd`: the finish movement
    in working days of the newer update's project calendar, negative when the finish goes later).
- **Which project each file is read for.** `selection()` returns one row per file: `file`,
  `project`, `selected_by`, `projects_in_file`, `data_date`, `data_date_from`, `baseline`,
  `activities`. `selected_by` is written by `xer/model.py`: `chosen` when a project was asked for,
  otherwise the rule of `_default_project` that decided: `only project`; else baseline copies
  (`baseline_copies`: rows named by another project's `sum_base_proj_id`, or copied from it through
  `orig_proj_id`) are set aside (`only project not a baseline copy` when one remains), then the most
  TASK rows, then the latest data date, then the first in file. The text names the deciding key and
  how many copies were set aside (`most TASK rows, 1 baseline copy set aside`); when every project
  is a baseline copy, the most TASK rows then file order decide (`..., every project a baseline
  copy`). `Snapshot.project_task_counts` holds the TASK rows by `proj_id` behind the
  "Projects in file" text (`projects_text`).

The same frames feed every consumer: the Power BI star schema (`export.export_tables`:
`dim_snapshot` = `summary`, `fact_activity` = `history`, `fact_relationship` =
`relationship_history`, `fact_assignment` = `assignment_history`, see ADR-0022), the weekly
analyses (`analysis/progress.py` reads `store.history`), and the app.

## Consequences

Positive:

- Week-over-week analysis is a `groupby` on `task_code` across `snapshot_idx`; Plotly and Power BI
  read the frames as they are.
- The key of every history is unambiguous: a series can never hold two updates for one status date.
- The project read from each file, and why, is visible: the app's Files and baseline window shows
  it per file and the full `selection()` table under "Selection details" (`app/files_window.py`).

Negative:

- A folder holding an update and its baseline copy (or two drafts) is refused until the user
  removes one. The CLI prints the message instead of a traceback (`cli.main` catches `ValueError`);
  the app shows it as an error ending "Untick the others." (`app/reading.py`), and when a project picked in the Files window would create a
  duplicate, it keeps the previous series and asks for another project (`app/loading.py`).
- The whole series is in memory; the frames are computed once per store and cached.

Follow-ups: none recorded in [docs/backlog.md](../backlog.md) for the store itself.

## Verification

- `tests/test_store.py::test_sorted_by_data_date`, `::test_previous`,
  `::test_task_ids_change_but_codes_join`, `::test_summary_tracks_slip`.
- `tests/test_store.py::test_same_data_date_twice_is_refused`: the exact `DuplicateDataDate`
  message, every file of the date named.
- `tests/test_audit_edges_app.py::test_three_identical_files_under_three_names_name_all_three`,
  `::test_snapshots_without_data_date_sort_by_name_and_sort_last`.
- `tests/test_store.py::test_selection_lists_every_file_in_the_series`,
  `::test_store_column_lists_exist_in_snapshot_frames` (`HISTORY_COLS`, `REL_COLS`,
  `ASSIGNMENT_COLS` are columns of the model and of the snapshot frames),
  `::test_fact_activity_carries_hours_per_day_so_days_convert_back`, `::test_export`.
- `tests/test_model.py::test_a_baseline_copy_with_as_many_activities_is_not_the_default`,
  `::test_a_copy_named_only_by_orig_proj_id_is_set_aside`,
  `::test_of_two_unrelated_projects_the_most_tasks_win`,
  `::test_as_many_tasks_then_latest_data_date_then_file_order`,
  `::test_when_every_project_is_a_baseline_copy_the_most_tasks_win`.
- `tests/test_architecture.py` (`LAYERS`): `store.py` imports only `xer/` and `config.py` (ADR-0001).

## References

- `src/xerscope/store.py`: `SnapshotStore`, `DuplicateDataDate`, `_sort_key`, `HISTORY_COLS`,
  `REL_COLS`, `ASSIGNMENT_COLS`, `SnapshotStore.selection`, `SnapshotStore._stack`,
  `SnapshotStore.history`, `relationship_history`, `assignment_history`, `summary`.
- `src/xerscope/xer/model.py`: `baseline_copies`, `_default_project`, `_deciding_rule`,
  `_select_project`, `projects_text`; `Snapshot.selected_by`, `Snapshot.project_task_counts`.
- `src/xerscope/export.py`: `export_tables`.
- `src/xerscope/app/files_window.py` ("Selection details"), `src/xerscope/app/reading.py`,
  `src/xerscope/app/loading.py`.
- [docs/architecture.md §4](../architecture.md).
- Related: ADR-0001 (layers), ADR-0003 (identity by `task_code`), ADR-0022 (Power BI export).
