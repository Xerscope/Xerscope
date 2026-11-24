# ADR-0015: Downloads anonymised by default with a per-session HMAC key and a column allowlist

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-03 (`fa33a37`, "Anonymised downloads: flagged lists and an XER extract", #37); the sidebar switch, on by default, and the per-session HMAC key the same day (`06db1af`, "UI/anon toggle", #56); codes redrawn when they spell an original on 2026-11-05 (`17eb135`, #113); project ids renewed on 2026-11-08 (`533a8e0`, #154) |
| Scope | `src/xerscope/anonymize.py`, `src/xerscope/app/downloads.py`, `src/xerscope/app/loading.py` (sidebar switch), `src/xerscope/app/views/export.py`, `src/xerscope/app/views/debug.py`, `src/xerscope/app/diagnostic.py`, `src/xerscope/cli.py` (`ask-bench --anonymize`) |
| Sources | Oracle, "XER Import/Export Data Map Guide (Project)", P6 23 (column meanings of the allowlist, cited in the module docstring); [docs/architecture.md](../architecture.md), "Outside `analysis/`" (`anonymize.py`); [CONTRIBUTING.md](../../CONTRIBUTING.md), "Readable code" (Before / after, `Anonymizer.table`); commits `fa33a37`, `06db1af`, `17eb135`, `533a8e0` |

## Context

What xerscope computes is shared beyond the planner: flagged lists sent to a contractor,
a Power BI model, a diagnostic attached to a bug report, an XER handed to someone who will
check the result in P6. Before `fa33a37`, the flagged lists of Schedule health left the app
with the real Activity IDs, names and WBS codes, and there was no way to hand out a schedule
without its names, users and free text (commit message). The copy must stay useful: P6 and
xerscope must compute the same dates, floats and checks on it, and an activity must keep one
new code across every download of a session, so lists and extract can be joined.

The pages themselves are seen by the planner only and must show the real data.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Plain downloads, anonymisation left to the user | none | every shared file carries names, codes, users and free text |
| A blocklist of known sensitive columns | short list | a column P6 adds, or one not thought of, leaks by default |
| New codes numbered over the files read (the first version, `fa33a37`) | simple | an activity gets another code when a download reads fewer files; exporting one update cost reading the whole series (`06db1af`) |
| **An allowlist per table, codes from an HMAC under a per-session key, every output checked against the originals' text, on by default for every download (chosen)** | the allowlist to extend for each new P6 column used; files read again to build the anonymiser | an unknown column is emptied, so a useful column is lost until listed; HMAC codes can spell an original (handled by redrawing) |

## Decision

**What is anonymised.** A sidebar toggle "Anonymous exports" (`key="anon_exports"`, default
on, per session; `app/downloads.py:anonymous_exports`) decides every download the same way:
page CSVs (Gantt, Earned value, PPC, changelog, audit, Delay analysis), the Schedule health lists and sets,
the Power BI zip (`Anonymizer.frame` on each table; the file name loses the project code),
the Debug diagnostic and its calendar detail (`Anonymizer.zip_frames`). On, a download is
built only by its anonymised path, never by the plain one (`downloads.fetch`); off, the same
downloads carry the files' own codes and names. The anonymised XER extract (Export page) is
always anonymised. The pages always show the files' own data.

**Allowlist, table by table** (`anonymize.py`):

- `KEEP`: columns copied as they are, per table (`PROJECT`, `PROJWBS`, `CALENDAR`, `TASK`,
  `TASKPRED`, `TASKRSRC`, `RSRC`, `ROLES`, `PROJCOST`, `SCHEDOPTIONS`, `CURRTYPE`, `UMEASURE`,
  `OBS`, `UDFTYPE`): keys, dates, durations, units, flags and P6 enumerations only.
  `CALENDAR.clndr_data` passes only when it holds no word outside `CALENDAR_WORDS`
  (otherwise `LeakError`).
- `CODES`: Activity ID, WBS, project, resource, role and OBS codes become `X<kind>` followed
  by the first hex digits of HMAC-SHA256(key, `"<kind>:<original>"`), upper case: 12 digits
  for activities, 8 for the other kinds (`WIDTH`). A code whose digits spell an original value
  of the files read is drawn again from `"<kind>:<original>:<n>"`; two originals on one code
  raise `CodeClash` (a `LeakError`), never written. The project node of `PROJWBS` takes the
  project kind.
- `LABELS`: names rebuilt from the row's new code (`"Activity XA…"`, `"WBS …"`,
  `"Resource …"`, `"Role …"`, `"Calendar <clndr_id>"`).
- Project ids: every column naming a project by its id (`PROJECT_ID_COLUMN`, e.g. `proj_id`,
  `sum_base_proj_id`, `pred_proj_id`) gets a 9-digit id from HMAC-SHA256(key,
  `"proj_id:<original>"`), drawn again when it equals an original id: a pointer still names
  the same project.
- `MONEY`: costs and prices written `0` (P6 counts an assignment or an expense, not its
  cost); `MONEY_COLUMNS` (`bl_cost`, `bac_cost`, `pv_cost`, `ev_cost`) zeroed in the tables
  xerscope computes.
- `GUIDS`: replaced by new random GUIDs, the same original getting the same new one.
- Any other column is emptied and any other table left out; both are reported by name only
  (`Report.emptied_columns`, `Report.dropped_tables`). The `ERMHDR` line loses the exporting
  user, his full name and the database name.

In the tables the app shows (`Anonymizer.frame`), code columns (`task_code`, `pred_code`,
`succ_code`), WBS paths, Activity ID lists written by rules (`drives`, `lagged_from`,
`ahead_of`) and project ids are renamed, name columns rebuilt from the new codes, the `note`
column renamed (Activity IDs, file names, `proj_id N`) with any other original value replaced
by `[hidden]`; any other text column outside `SAFE_TEXT` is emptied and named.

**Leak check before anything leaves.** Every field and column name of an output is compared
with every text value of the originals that was not kept, searched for those values inside it,
for every original code anywhere, and for the source file names and their stems
(`Anonymizer.leaks`); one match and the output is refused (`LeakError`, shown on the page).

**Key and mappings.** One key per session, `secrets.token_bytes(32)` (`_anon_key` in the
session); an anonymiser is built on request for the files a download reads (`sources_of`:
the update shown; W-1 and W for changelog, PPC and the Delay analysis steps; W-2, W-1 and W
for the PPC date variances; the baseline's file when it lists baseline fields; every file for
Power BI, the XER extract and the Delay analysis longest-path churn and series), at most four kept per session, one built
from more files serving a download of fewer. With the same key a code is the same whichever
files were read, unless it was redrawn for spelling an original. Key and mappings live in the
session state only.

**CLI.** `xerscope ask-bench --anonymize` scores the Ask field on the anonymised copy of the
file: the sentences are rewritten with the new WBS and resource codes, a case searching names
is set aside, and a sentence still holding an original value is refused and counted, never
printed.

## Consequences

Positive:

- A download can be shared without exposing names, codes, users, free text or costs, and P6
  and xerscope compute the same results on the anonymised XER (`tests/test_anonymize.py`).
- The default is the safe one; plain downloads need a deliberate switch per session.
- Lists, Power BI tables, diagnostic and extract of one session share the same new codes.
- A new P6 column is safe by default: emptied and named until someone adds it to `KEEP`.

Negative:

- Building an anonymiser reads the files again (a spinner on first use per set of files).
- Codes differ between sessions (new key), so two downloads of different sessions cannot be
  joined; this is the intended limit of the key.
- Costs are lost in anonymised outputs (written 0); only the ratio `spi_cost`, which reveals
  no amount, is kept.

Follow-ups: none recorded in [docs/backlog.md](../backlog.md).

## Verification

- `tests/test_anonymize.py::test_demo_series_gives_the_same_results`,
  `::test_p6_exports_give_the_same_results`, `::test_no_text_value_of_the_original_is_left`,
  `::test_header_loses_user_and_database`,
  `::test_codes_follow_the_activity_across_files_whatever_their_order`,
  `::test_one_update_read_alone_gets_the_codes_of_the_whole_series`,
  `::test_two_ids_on_one_new_code_are_refused`, `::test_a_code_spelling_an_original_id_is_drawn_again`,
  `::test_unknown_tables_and_columns_are_left_out_and_named`,
  `::test_costs_are_zeroed_and_the_expense_kept`, `::test_calendar_data_with_unknown_words_is_refused`,
  `::test_flagged_csv_matches_check_on_the_anonymised_file`,
  `::test_no_original_project_id_is_left_in_any_anonymous_output`,
  `::test_a_new_project_id_equal_to_an_original_is_drawn_again`, and the other tests of the file.
- `tests/test_anonymous_file_names.py` (no file name in the diagnostic, the Power BI tables,
  the Schedule health lists, the changelog, earned hours and progress CSVs, the XER extract).
- `tests/test_downloads.py::test_switch_off_gives_the_plain_bytes_and_builds_no_anonymizer`,
  `::test_switch_on_is_the_default_and_never_runs_the_plain_build`,
  `::test_the_anonymizer_reads_only_the_sources_and_one_for_more_files_serves_fewer`,
  `::test_only_the_switch_decides`.
- `tests/test_app.py::test_exports_are_anonymised_by_default_and_plain_when_switched_off`,
  `::test_flagged_lists_and_xer_leave_the_app_anonymised_only`,
  `::test_debug_diagnostic_leaves_the_app_anonymised`,
  `::test_debug_diagnostic_in_plain_when_anonymous_exports_are_off`,
  `::test_health_all_sets_file_anonymised_holds_no_original_value`.
- `tests/test_cli.py::test_ask_bench_anonymised_shows_no_original_name`.

## References

- `src/xerscope/anonymize.py`: `KEEP`, `CODES`, `LABELS`, `MONEY`, `MONEY_COLUMNS`, `GUIDS`,
  `PROJECT_ID_COLUMN`, `WIDTH`, `DRAWS`, `CALENDAR_WORDS`, `HIDDEN`, `Report`, `LeakError`,
  `CodeClash`, `Anonymizer` (`from_raws`, `code`, `project_id`, `guid`, `table`, `xer`, `frame`,
  `csv`, `zip_xers`, `zip_frames`, `leaks`).
- `src/xerscope/app/downloads.py`: `anonymous_exports`, `anonymizer`, `fetch`, `sources_of`;
  `src/xerscope/app/loading.py` (the "Anonymous exports" toggle).
- `src/xerscope/cli.py`: `_anonymised_bench`, `_anonymised_case`.
- [docs/architecture.md](../architecture.md), "Outside `analysis/`" (`anonymize.py`) and §7
  (`downloads.py`); [CONTRIBUTING.md](../../CONTRIBUTING.md), "Readable code" (Before / after,
  `Anonymizer.table`).
- Related: ADR-0014 (no real schedule in the repository; witnesses use the anonymised
  extract), ADR-0023 (every CSV neutralised against formula injection), ADR-0022 (Power BI
  export).
