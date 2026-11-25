# ADR-0023: Every CSV neutralised against formula injection (CWE-1236)

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-09 (`5ca0f45`, "Software audit: edge-case tests, load contract, typed errors, supply chain, app findings", #165: `csv_safe.py`, finding AUDIT-APP-07, merged with `csv_bytes` into one CSV writer); Streamlit's own table download and copy disabled earlier, on 2026-11-04 (`1d9cf77`, "Tables offer no raw CSV download or copy", #58) |
| Scope | `src/xerscope/csv_safe.py`, `src/xerscope/export.py` (`csv_bytes`, `_bytes`, `zip_frames`), `src/xerscope/cli.py` (`_write_csv`), `src/xerscope/app/downloads.py`, `src/xerscope/app/views/health.py`, `src/xerscope/app/views/debug.py`, `src/xerscope/anonymize.py` (`Anonymizer.csv`, `Anonymizer.zip_frames`), `src/xerscope/app/.streamlit/config.toml` (`[client]`) |
| Sources | OWASP, "CSV Injection" (the characters that start a formula, the leading apostrophe); MITRE CWE-1236, "Improper Neutralization of Formula Elements in a CSV File"; [SECURITY.md](../../SECURITY.md), scope ("what leaves the app"); [docs/architecture.md](../architecture.md), "Outside `analysis/`" (`csv_safe.py`) and Layer rules; commits `5ca0f45`, `1d9cf77` |

## Context

Every text cell xerscope writes to a CSV comes from an XER file: activity names, WBS names,
resource names, notes built from them. A crafted file can name an activity `=cmd|...` or
`=HYPERLINK(...)`; opened in Excel or LibreOffice, a cell starting with `=`, `+`, `-` or `@`
is evaluated as a formula. The audit of the app layer (`5ca0f45`, AUDIT-APP-07) found that every
CSV xerscope wrote copied the XER text as is. CSVs leave xerscope by several roads: the Power BI
tables, the CLI's `check --out` / `--flagged` and `recalc --out`, the page downloads, the
anonymised tables and the Debug diagnostic. Power BI does not evaluate formulas, but the same
files are opened in a spreadsheet. The neutralisation must not change numbers or dates, nor the
dtypes a reader relies on.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Leave the text as is, warn the reader | none | a crafted file runs in the reader's spreadsheet |
| Neutralise at each download site | local | one forgotten writer leaks; every new download must remember it |
| **One function, `csv_safe`, inside the one CSV writer `export.csv_bytes`, which every CSV goes through; Parquet left raw (chosen)** | a leading apostrophe on the affected text cells | a reader wanting the raw text strips the apostrophe, or reads the Parquet export |

## Decision

`csv_safe.csv_safe(frame)` returns a copy of the frame with `'` prefixed to every `str` cell
that starts with one of `FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")` (OWASP CSV injection
guidance). Only columns of dtype `object` or `string` are read, and in them only `str` cells
change: numeric and date columns keep their values and dtype, a negative number stays a number,
`None` stays missing, the caller's frame is untouched.

`csv_safe` is called in one place, `export.csv_bytes` (UTF-8 with BOM, floats to four decimals,
dates as `DATETIME_FMT`), the only `to_csv` call under `src/xerscope`. Every CSV goes through it:

| Road | Writer |
|---|---|
| Power BI CSVs (`xerscope export --format csv`, the Export page's CSV zip) | `export._bytes` → `csv_bytes` |
| CLI files: `check --out`, `check --flagged`, `recalc --out` and the other CLI CSVs | `cli._write_csv` → `csv_bytes` |
| Page downloads (plain) | `app/downloads.py` and `app/views/health.py` → `csv_bytes`; zips through `export.zip_frames` (Schedule health sets, Debug diagnostic and calendar detail) |
| Anonymised tables | `Anonymizer.csv` → `csv_bytes`; `Anonymizer.zip_frames` → `export.zip_frames` |

Streamlit's own table toolbar would bypass this path: `[client] disableDataExport = true` in the
packaged `app/.streamlit/config.toml` removes its CSV download and clipboard copy, so tables leave
the app only through the app's own buttons (ADR-0015 decides whether those are anonymised).

Parquet (`export._bytes` with `fmt="parquet"`) is not neutralised: it is the route for the raw
text, and no spreadsheet evaluates it.

`csv_safe.py` imports nothing of xerscope; `export.py` imports it (Layer rules).

## Consequences

Positive:

- No CSV xerscope writes can run a formula in the reader's spreadsheet, whatever the file holds.
- One writer: a new download built on `csv_bytes` or `zip_frames` is neutralised without a
  decision of its own.
- Numbers, dates and their dtypes are unchanged, so totals in a spreadsheet or BI tool stay right.

Negative:

- A legitimate text starting with `-` or `+` (a note such as `+2 d`, a name starting with a dash)
  reads with a leading apostrophe in the CSV; a reader removes it (Excel: Data > Text to
  Columns) or reads the Parquet export.
- A `str` cell in a mixed column is neutralised too: the column is text for a spreadsheet anyway.
- The module docstring of `csv_safe.py` names `app/state.py` among the page-download writers; the
  page downloads now go through `app/downloads.py` and `app/views/health.py` (a docstring to align).

Follow-ups: none recorded in [docs/backlog.md](../backlog.md).

## Verification

- `tests/test_audit_edges_app.py::test_csv_safe_touches_text_cells_only` (the six starts, numbers,
  dates, mixed column, caller's frame untouched),
  `::test_csv_export_neutralises_formula_cells` (Power BI CSVs and zip neutralised, Parquet raw,
  numeric columns still numbers), `::test_cli_csv_writers_neutralise_formula_cells` (`check
  --flagged`, `check --out`, `recalc --out`, BOM kept), `::test_anonymised_csv_neutralises_formula_cells`
  (`Anonymizer.csv`, `Anonymizer.zip_frames`).
- `tests/test_analysis_and_viz.py::test_tables_offer_no_raw_data_export` (`disableDataExport`).
- `tests/test_app.py` compares a downloaded note with `csv_safe` of the expected note.
- `tests/test_architecture.py::test_layer_imports_match_the_architecture_doc` (`LAYERS["export"]`
  holds `csv_safe`).

## References

- `src/xerscope/csv_safe.py`: `FORMULA_STARTS`, `csv_safe`.
- `src/xerscope/export.py`: `CSV_FLOAT_FORMAT`, `csv_bytes`, `_bytes`, `zip_frames`.
- `src/xerscope/cli.py`: `_write_csv`; `src/xerscope/app/downloads.py`;
  `src/xerscope/app/views/health.py`; `src/xerscope/app/views/debug.py`;
  `src/xerscope/anonymize.py`: `Anonymizer.csv`, `Anonymizer.zip_frames`.
- `src/xerscope/app/.streamlit/config.toml`, `[client]` (`disableDataExport`).
- [SECURITY.md](../../SECURITY.md), scope; [docs/architecture.md](../architecture.md),
  "Outside `analysis/`" (`csv_safe.py`).
- Related: ADR-0015 (anonymised downloads), ADR-0022 (Power BI export).
