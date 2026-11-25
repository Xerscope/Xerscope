# ADR-0002: Two-stage XER reading: a format-only parser, then one model that owns every P6 meaning, under a load contract

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`49ad764`, initial commit: `xer/parser.py` and `xer/model.py` apart); load contract from 2026-11-06 (`dc6da0d`, #133) |
| Scope | `src/xerscope/xer/parser.py`, `src/xerscope/xer/model.py`, `src/xerscope/xer/validate.py`, `src/xerscope/xer/__init__.py`, `src/xerscope/store.py` (column lists) |
| Sources | `6bc2b60` "Model: declared Snapshot column contract" (2026-11-01); `dc6da0d` "Load contract: a damaged .xer gives a XerError, never a library exception (#133)"; `5ca0f45` "Software audit: edge-case tests, load contract, typed errors, supply chain, app findings (#165)" (introduces `xer/validate.py` and `tests/test_fuzz_parser.py`); `a122f44` "Reader: warn of a filled cell read as blank (XER-01)"; `SECURITY.md` (scope); `docs/architecture.md` §1, §2 |

## Context

An XER file is the trust boundary of xerscope: users hand the app exports copied from a share
(possibly still being written), edited by hand, or crafted. Two concerns are mixed in a file:

- the **format** (an `ERMHDR` line, `%T` / `%F` / `%R` / `%E` tags, tab-separated values, an
  encoding chosen by the P6 client);
- the **P6 meaning** of the values (which column is the identity, where the data date is, which
  unit a duration is in, which calendar a lag uses, what "critical" means for this project).

Before #133 a file cut short was read as complete (its last row padded, the tables after it
lost, no warning); a repeated `task_id`, `wbs_id` or `clndr_id`, a column named twice, a table
written twice, a date such as `-1` or `9999-12-31`, or `1e400` in a number raised pandas
errors, and on the app's synchronous load path every page then failed (`dc6da0d`). Before
`a122f44`, a cell the file fills but typing cannot read (a decimal comma, month 13) read as blank
without a word, so a duration `8,5` took a task out of the checks.

`SECURITY.md` puts in scope: "a crafted `.xer` or P6 XML file must not do more than fail to load".

## Options considered

| Option | Cost | Limit |
|---|---|---|
| One reader that types values as it parses (or a third-party reader as the main path) | one module | each P6 rule mixed with format handling; a format change touches the analyses; MPXJ is kept as an independent reader for comparison only (`verify/mpxj_reader.py`, `xerscope crosscheck`) |
| Repair every damaged file and always return a snapshot | none for the user up front | a file cut short or with two rows on one key yields numbers from a partial or arbitrary schedule without a word (`tests/test_load_contract.py` docstring) |
| Format-only parser, one model for every P6 rule, value checks one function each, and a two-outcome load contract (chosen) | three modules and a contract test plus a fuzzer | a file P6 would never write is refused (structure) or repaired with a warning (values): the user must read the warnings |

## Decision

**Stage 1, the format: `xer/parser.py`.** `parse_bytes` (`decode_xer`, then `parse_text`;
`read_xer` for a path) knows the XER format only and keeps every value as a string in
`RawXer(tables, source, version, export_date, encoding, warnings, header, ended)`:

- encoding: a UTF-16 or UTF-32 byte order mark is honoured (`XerError` when the bytes do not
  decode as it); otherwise UTF-8 with or without BOM (`utf-8-sig`), then cp1252; bytes neither
  reads are replaced, with a warning;
- lines are read in one pass and split on `\n` only (calendar blobs can contain `\r`, task names
  characters `splitlines()` would break on);
- a short row is padded, a long one cut, to the `%F` width as it is appended; `%R` rows outside a
  named `%T` table are skipped with a warning;
- a table written twice, a column named twice in a `%F` line, or a file with neither `ERMHDR`
  nor table raises `XerError`; lines after `%E` are not read; `ended` is False when the file has
  no `%E` line (the parse succeeds so the file picker can still read a header).

**Stage 2, the P6 meaning: `xer/model.py`.** `build_snapshot(raw, project_code=, settings=,
project_id=)` turns a `RawXer` into a typed, read-only `Snapshot` and is the single place for
each P6 rule: identity (`task_code`, [ADR-0003](0003-activity-identity-by-task-code.md)), data
date (`PROJECT.last_recalc_date`, else `plan_start_date`), units and lag calendar
([ADR-0004](0004-hours-stored-working-days-on-activity-calendar.md)), the critical definition,
% complete by `complete_pct_type`, best dates, forecast finish, labour hours, EV technique,
links (`[ext]<task_id>` for another project's predecessor), calendars and options
(`docs/architecture.md` §2 table). `read_header(raw)` applies the same project and data-date
rules to `PROJECT` and `TASK` alone (`HEADER_TABLES`) for the file picker. A P6 XML export read
for a baseline (`xer/pmxml.py`) is converted to the same XER tables and goes through the same
`build_snapshot`.

**Value checks: `xer/validate.py`.** One function per rule on a file's values (`unique_rows`,
`timezone_cells` / `blank_timezones`, `unreadable_cells`, `unreadable_status_date`,
`bounded_sequence`, `usable_hours`, `nonnegative_remaining`, `placeholder_clashes`). Each repairs
the frame the way its rule says (a duplicate `PROJECT.proj_id` keeps its first row, an unusable
number reads as 0) and adds one line to the snapshot's
`warnings`. Nothing there reads P6 semantics. An unknown `TASKPRED.pred_type` is not a value
check: `model._relationships` keeps the link with its code and warns that it is ignored by the
recalculation (`_warn_unknown_codes`).

**Load contract.** `build_snapshot` returns a `Snapshot` or raises `XerError`, nothing else,
whatever the file holds:

| File holds | Outcome |
|---|---|
| no `%E` line (cut short, still being copied) | `XerError` "incomplete file" |
| a table written twice, or a table naming one column twice | `XerError` "appears twice" / "names column ... twice" (`xer/parser.py`) |
| no `PROJECT` or no `TASK` table (or an empty one) | `XerError` "PROJECT or TASK table missing" (`_project_table`, also in `read_header`) |
| a repeated `TASK.task_id`, `PROJWBS.wbs_id` or `CALENDAR.clndr_id` | `XerError` "has duplicate ..." (`_unique`) |
| an identity column missing (`TASK.task_id`, `task_code`, `CALENDAR.clndr_id`, ...) | `XerError` "has no column ..." (`_require`) |
| a date outside 1900-2199, or an infinite number | read as blank, like an unparseable value |
| a filled cell typing reads as blank (TASK and TASKRSRC dates and numbers) | blank, with a warning naming the table, column and Activity IDs (`unreadable_cells`) |

**Snapshot contract.** `model.py` declares the minimum columns of each frame: `TASK_COLS` plus
`LABOR_COLS` for `tasks`, `REL_COLS_MODEL` for `relationships`, `ASSIGNMENT_COLS_MODEL` for
`assignments`. `_check_snapshot_columns` raises `XerError` if one is missing, and the store's
`HISTORY_COLS`, `REL_COLS` and `ASSIGNMENT_COLS` must be subsets of them. The lists are a floor,
not a filter: frames may carry more raw XER columns.

## Consequences

- One P6 concept lives in one place; the checks, the CPM and the pages read the derived columns
  and never re-read raw XER semantics, so two checks cannot read one column two ways.
- The parser never changes when an analysis does (`xer/parser.py` docstring).
- A crafted or damaged file fails to load with one `XerError` line (CLI: exit code 2, one
  `xerscope: <message>` line on stderr); in the app the file is named and the other files load.
- Refusing rather than repairing rests on what P6 writes: the 394 P6 exports under
  `tests/reference/data` all end with `%E`, hold one table per name and one column per name, have
  unique `task_id`, `wbs_id` and `clndr_id`, and date nothing outside 2000-2027
  (`tests/test_load_contract.py` docstring).
- Repairs are visible but not blocking: the user must read the warnings (sidebar, Debug page,
  CLI).

## Verification

- `tests/test_load_contract.py`: `test_the_full_file_builds`, `test_a_file_cut_short_is_refused`,
  `test_a_cut_file_still_shows_its_header`, `test_lines_after_the_end_line_are_ignored`,
  `test_a_table_written_twice_is_refused`, `test_a_column_named_twice_is_refused`,
  `test_a_duplicated_primary_key_is_refused`, `test_a_date_outside_1900_2199_reads_as_no_date`,
  `test_dates_at_the_edges_of_the_range_are_kept`, `test_a_non_finite_number_reads_as_no_number`,
  `test_any_damage_gives_a_snapshot_or_a_xer_error`.
- `tests/test_fuzz_parser.py` (Hypothesis; `HYPOTHESIS_PROFILE=ci` runs 1000 examples per
  property instead of 200): `test_parse_bytes_returns_rawxer_or_xererror`,
  `test_build_snapshot_returns_snapshot_or_xererror`, `test_former_crashes_stay_fixed`
  (`REGRESSIONS`), and the same property for `read_pmxml_baseline` and `loads_standard`.
- `tests/test_parser.py`: `test_short_rows_are_padded_not_shifted`, `test_cp1252_fallback`,
  `test_utf8_is_preferred`, `test_rejects_non_xer`.
- `tests/test_unreadable_values.py`: `test_each_unreadable_cell_is_read_blank_and_named`,
  `test_an_unreadable_status_date_says_where_the_status_date_comes_from`.
- `tests/test_store.py::test_store_column_lists_exist_in_snapshot_frames`: the store's column
  lists are subsets of the model's declared columns.
- `tests/test_model.py::test_header_takes_what_build_snapshot_takes` and
  `test_header_matches_build_snapshot_on_sample_and_reference_files`: `read_header` agrees with
  `build_snapshot`.

## References

- `src/xerscope/xer/parser.py`: `decode_xer`, `parse_text`, `parse_bytes`, `read_xer`, `RawXer`,
  `XerError`, `ENCODINGS`, `WIDE_BOMS`
- `src/xerscope/xer/model.py`: `build_snapshot`, `read_header`, `HEADER_TABLES`, `TASK_COLS`,
  `LABOR_COLS`, `REL_COLS_MODEL`, `ASSIGNMENT_COLS_MODEL`, `_check_snapshot_columns`, `_unique`,
  `_require`
- `src/xerscope/xer/validate.py`: one function per value rule
- `src/xerscope/xer/__init__.py`: `load_snapshot`, `load_header`
- `docs/architecture.md` §1 (`parse_bytes` behaviour, "Load contract"), §2 (table, "Snapshot
  contract", "Value checks")
- `CONTRIBUTING.md` "Where a change goes" (a P6 column meaning goes in `xer/model.py`; a check on a
  file's values in one function of `xer/validate.py`, never the parser or an analysis)
- `SECURITY.md` (scope)
- Related: [ADR-0001](0001-layered-architecture-one-way-data-flow.md),
  [ADR-0003](0003-activity-identity-by-task-code.md),
  [ADR-0004](0004-hours-stored-working-days-on-activity-calendar.md),
  [ADR-0019](0019-p6-xml-export-for-baselines.md)
