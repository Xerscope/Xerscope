# ADR-0021: Ask lexicon as data outside the repository and the image: curated, generated and suggested folders

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-09 (`989308e`, "Ask (1/4): grammar, comparisons, dates, constraints, logic, longest path", #166: the packaged `src/xerscope/lexicon/fr-en.toml` removed, "no lexicon ships with the package"); the three folders, the suggestions file and its guards the same day (`df38749`, "Ask (2/4): lexicon folder on the NAS: generated/, curated/, suggested/", #167; `9ee644f`, "Ask (3/4): limits and hardening of the Ask input and suggestions", #168); `lexicon-init` on demand, exports checked and read one at a time (`4d9f78c`, "Ask (4/4): lexicon build on demand, exports checked and streamed", #169). The packaged file had come with the Ask field on 2026-11-06 (`71377b4`, #141) |
| Scope | `src/xerscope/analysis/ask/lexicon.py`, `src/xerscope/analysis/ask/generated.py`, `src/xerscope/analysis/ask/suggested.py`, `src/xerscope/app/loading.py` (`_lexicon_dirs`, `lexicon_and_errors`, `refusals`, `file_variants`, `session_lexicon`, `teach`), `src/xerscope/app/views/gantt.py` ("Did you mean"), `src/xerscope/cli.py` (`lexicon`, `LEXICON_MAX_BYTES`), `deploy/compose.yaml` (`lexicon-init`, `XERSCOPE_LEXICON`, `XERSCOPE_LEXICON_DIR`) |
| Sources | [docs/deploy.md](../deploy.md) §10 (folders table, threat model), §9 (checklist); [docs/user-guide.md](../user-guide.md), "Reference": "Command line" (`lexicon`) and "Environment variables" (`XERSCOPE_LEXICON`); Docker docs, "Using profiles with Compose"; commits `71377b4`, `989308e`, `df38749`, `9ee644f`, `4d9f78c` |

## Context

The Gantt "Ask" field (ADR-0020) reads a sentence against the file's own labels. A company
says its labels its own way: "CVC" for "HVAC", "mécanique" for "Mechanical", an abbreviation
of its WBS names. Those trade words, and the spellings a series of exports itself uses for one
word ("Fondation" / "Fondations", "Mec." / "Mechanical"), reveal the company's vocabulary and
its projects' words.

The Ask field first shipped with a bilingual lexicon packaged in `src/xerscope/lexicon/fr-en.toml`
(`71377b4`): the words lived in the repository and in every install. The forces:

- the repository is public and the image is published (ADR-0014: no real schedule data in the
  repository); a company's words are schedule-derived data of the same kind;
- the deployed app container runs with a read-only root filesystem (ADR-0024, ADR-0025), so it
  cannot keep what it learns inside the image;
- the reach of the Ask field must grow (new words, new exports) without a release;
- the remote stack is reachable by whoever holds the URL and the password, so any folder the
  app writes is written from a web page.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| A lexicon packaged with the code (`src/xerscope/lexicon/fr-en.toml`, the first version) | none: one file read at start | the company's words in the public repository and the published image; a new word needs a release |
| Words taught in the app written straight into the lexicon the Ask field reads | no review step | a visitor's typing becomes every session's grammar; the app needs a writable lexicon |
| **A private folder named by `XERSCOPE_LEXICON`, outside repository and image, split into `curated/` (by hand), `generated/` (by an on-demand build) and `suggested/` (appended by the app, read by nothing) (chosen)** | three folders to create and own on the host; a manual copy from `suggested/` to `curated/`; an on-demand service to run | the Ask field reads a taught word in other sessions only once the maintainer copies it; nothing is understood before the folder is filled |

## Decision

**Trade words are data, not code.** No lexicon ships with the package: `load_lexicon` reads only
the folders it is given (`analysis/ask/lexicon.py`), and with none it returns an empty lexicon.
A lexicon file is TOML: `[[group]] words = [...]` tables, each group read as one (every word
folded; a group of fewer than two words is dropped, `lexicon_from_groups`). A group that names
its source `column` holds within that column only and is read by `generated.load_variants`, not
by `load_lexicon`. A `[[refuse]] column = "...", words = [...]` table (two words or more) drops
the generated group of that column holding all its words (`generated.load_refusals`,
`generated.refuse`); a refusal wins over `generated/` and over the variants derived in memory.

**One root, three folders** (`GENERATED`, `CURATED`, `SUGGESTED` in `lexicon.py`; the root is
`XERSCOPE_LEXICON`, read by `app/loading.py:_lexicon_dirs`):

| Folder | Written by | Read by the Ask field |
|---|---|---|
| `curated/` | the maintainer, by hand; read-only in both containers | yes: trade words (`lexicon_and_errors`), refusals (`refusals`), its own column groups (`file_variants`) |
| `generated/` | `xerscope lexicon build` only (the `lexicon-init` service): `variants.toml` and `report.txt` | `variants.toml`, less the curated refusals (`file_variants`); `report.txt` never |
| `suggested/` | the app only, appending `suggestions.toml` | never |

The app reads `curated/` and `generated/` once per process (`functools.cache`); the load
errors (file not UTF-8 with its byte, not TOML with tomllib's line and column, a group or
refusal number) are listed in Debug block 14, never the words. `xerscope lexicon [FOLDER]`
checks a folder the same way, prints its groups and exits 1 when a file does not load;
`--word` prints the words read as one.

**Generated variants.** `analysis/ask/generated.py` groups the words of one source column
(`COLUMNS`, XER table.field; `TASK.task_code` never grouped) by written rules only: folding,
French and English plurals (w / w+s, w / w+es, -al / -aux), an abbreviation written with its dot
(3+ letters, `MIN_ABBREVIATION`) and the one longer word of the column it begins. Two words one
letter apart (6+ letters, `MIN_EDITED`) are never grouped: they are listed in `report.txt`,
section "to review (one letter apart, not used)", for the maintainer to copy the true typos
into `curated/`. The app derives the same variants in memory per session and never writes them.

**`lexicon build`.** `xerscope lexicon build FOLDER --out ROOT` (`cli._build_lexicon`) reads the
exports of `FOLDER` one at a time, keeping their words only (`generated.add_terms`); each
export is checked first and skipped with a fixed reason (`too large` over `LEXICON_MAX_BYTES`,
64 MB; `unreadable`; `incomplete`; `missing table TASK`; `missing table PROJWBS`; `no
project`), named in `report.txt` only. It replaces `ROOT/generated/variants.toml` and
`report.txt` whole through `lexicon.write_private` (a `tempfile.mkstemp` file of the same
folder, 0600, then `os.replace`), then purges `ROOT/suggested/`. A missing `generated/` or
`suggested/` is named and never created (exit 1); no valid export leaves `generated/` as it is
(exit 1). The output prints counts, never a word nor an export name.

**`lexicon-init` on the remote stack** (`deploy/compose.yaml`): the app's image and account,
`command: ["lexicon", "build", "/data", "--out", "/lexicon"]`, `profiles: [lexicon]` (left out
of `docker compose up`; run with `docker compose run --rm lexicon-init`), `network_mode: none`,
`read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`, healthcheck disabled, memory cap
`XERSCOPE_MEM_LIMIT` (default `2g`), 64 PIDs, `restart: "no"`. `/data` and
`XERSCOPE_LEXICON_DIR` (default `/docker/xerscope/lexicon`) are mounted read-only, with
`generated/` and `suggested/` mounted writable over them. The app sets
`XERSCOPE_LEXICON: /lexicon`, mounts the folder read-only and `suggested/` writable, and does
not depend on `lexicon-init`: it starts with the last `generated/` (or none).

**Suggestions.** A word the Ask field does not know is offered the closest labels ("Did you
mean", `gantt.py`); a click holds for the visitor's session (`loading.teach`, `session_lexicon`)
and appends one `[[suggestion]]` to `suggested/suggestions.toml` (`suggested.record`): the
unknown word, the label, its source column (`SOURCES`: `PROJWBS.wbs_name` or
`RSRC.rsrc_short_name`), the filter (facet, value) and the UTC date, never the sentence asked.
The guards, each in `suggested.py`:

- the file name is fixed (`FILE`), never taken from the input;
- word and label NFKC-normalised, at most `MAX_WORD` (64) and `MAX_LABEL` (160) characters, made
  of letters, digits and `PUNCTUATION` only (no control character, newline, bracket, quote,
  backslash, `=`), no invisible Hangul filler (`INVISIBLE`), refused otherwise (`clean`);
- every value written through `json_quote`, so no TOML table can be injected;
- an exclusive `fcntl.flock` serialises the size check and the append, on the file the path
  names once locked (`_locked`);
- the file stops at `MAX_BYTES` (256 KB); one correction (word, label, column) is kept once;
- the file is created 0600 and opened with `O_NOFOLLOW`; nothing is printed or logged; without
  `flock` (Windows) nothing is recorded;
- a suggestion older than `RETENTION` (90 days) whose word `curated/` does not hold is purged,
  by `lexicon build` (`suggested.purge`) and by the next record under the same lock.

A refused record shows a neutral line that does not repeat the word. No lexicon file can be
uploaded (the only upload of the locked app is a standard, and a file without a `[standard]`
table is refused) nor downloaded from the app (Debug block 14 shows counts per column only).

## Consequences

Positive:

- The repository and the published image hold no company word: the tests build a generic
  lexicon in code (`tests/asklex.py`).
- A new trade word or a refusal takes effect at the next app start, without a release; new
  exports give new variants at the next `lexicon-init` run.
- What a visitor teaches never reaches another session until a person reviews it; the folder
  written from the web page is bounded in name, content, size and age.
- `lexicon-init` cannot reach the network nor write outside its two folders; its memory peak is
  the largest export's, whatever their number.

Negative:

- Three folders to create by hand, owned by the app's account (Docker would create a missing one
  owned by root, and the containers could not write it).
- The maintainer copies words from `suggested/` and from the "to review" section of `report.txt`
  into `curated/` by hand; until then a taught word holds for one session only.
- On a NAS, `lexicon-init` has no button in Container Manager: it is run through SSH; the app
  reads a new `generated/` after a restart (Project → Build).
- A visitor holding the URL and the password can fill `suggestions.toml` up to its cap; past it
  corrections stop being recorded, the app keeps working.

Follow-ups: none recorded in [docs/backlog.md](../backlog.md) for the lexicon folder; the
language-model item of its "App" section concerns the Ask grammar (ADR-0020).

## Verification

- `tests/test_ask_suggested.py`, one test per guard:
  `::test_a_correction_records_the_word_the_label_its_column_the_filter_and_the_date`,
  `::test_a_word_outside_the_allowed_characters_or_length_is_refused`,
  `::test_word_and_label_are_nfkc_normalised`, `::test_a_label_too_long_or_an_unknown_source_is_refused`,
  `::test_the_file_name_never_comes_from_the_input`, `::test_a_symlink_in_place_of_the_file_is_not_followed`,
  `::test_a_full_file_refuses_the_next_entry_and_is_left_as_it_is`,
  `::test_concurrent_writes_are_whole_entries_and_stay_under_the_cap`,
  `::test_concurrent_writes_from_processes_all_land`, `::test_nothing_is_printed_or_logged`,
  `::test_purge_drops_what_curated_did_not_take_after_the_retention`,
  `::test_a_record_purges_what_expired_without_the_init_service`,
  `::test_the_same_correction_is_recorded_once`,
  `::test_a_file_removed_between_open_and_check_leaks_no_descriptor`,
  `::test_a_date_written_without_time_zone_is_read_as_utc_and_purged`,
  `::test_an_invisible_hangul_filler_is_refused`, and the other tests of the file.
- `tests/test_docker.py::test_the_app_reads_the_nas_lexicon_and_writes_suggested_only`,
  `::test_the_lexicon_init_service_is_sealed`, `::test_the_compose_file_is_valid_for_docker_compose`
  (skipped without the docker CLI), `::test_no_lexicon_file_goes_into_the_image` (every `*.toml`
  packaged under `src/xerscope` is a standard or Streamlit's `config.toml`).
- `tests/test_query.py::test_lexicon_is_data_the_user_extends`,
  `::test_no_lexicon_file_is_packaged_or_tracked_under_src`,
  `::test_a_generated_file_is_read_back_per_column`,
  `::test_a_curated_file_not_utf8_or_misshaped_is_skipped_and_named_without_its_words`,
  `::test_a_curated_refusal_drops_the_generated_group_that_holds_its_words`.
- `tests/test_app.py::test_the_ask_field_reads_curated_words_only`,
  `::test_a_correction_lands_in_suggested_without_the_sentence_and_is_not_read_back`,
  `::test_a_correction_refused_by_a_guard_says_so_without_the_word`,
  `::test_generated_variants_are_read_less_the_curated_refusals`,
  `::test_a_lexicon_uploaded_as_a_standard_never_reaches_the_ask_field`,
  `::test_debug_ask_variants_block_shows_counts_only`,
  `::test_debug_lists_the_curated_load_errors_to_every_session_without_their_words`.
- `tests/test_cli.py::test_lexicon_command`,
  `::test_lexicon_build_skips_each_refused_export_and_names_it_in_the_report_only`,
  `::test_lexicon_build_holds_one_export_in_memory_at_a_time`,
  `::test_lexicon_build_with_no_valid_export_leaves_generated_as_it_was`,
  `::test_lexicon_build_rewrites_generated_and_purges_suggested`,
  `::test_lexicon_build_reports_the_groups_new_since_the_last_run`.
- `tests/test_ask_variants.py::test_one_letter_apart_never_groups_nor_chains_groups`,
  `::test_lexicon_build_names_a_missing_folder`.

`tests/test_lexicon.py` is not about this lexicon: it checks the interface's own terms.

## References

- `src/xerscope/analysis/ask/lexicon.py`: `GENERATED`, `CURATED`, `SUGGESTED`,
  `lexicon_from_groups`, `tables`, `words_of`, `load_lexicon`, `learn`, `write_private`,
  `json_quote`.
- `src/xerscope/analysis/ask/generated.py`: `COLUMNS`, `GROUPED`, `MIN_ABBREVIATION`,
  `MIN_EDITED`, `add_terms`, `variants_from`, `near_spellings_from`, `group_words`,
  `load_variants`, `load_refusals`, `refuse`, `counts`, `to_toml`.
- `src/xerscope/analysis/ask/suggested.py`: `FILE`, `MAX_WORD`, `MAX_LABEL`, `MAX_BYTES`,
  `RETENTION`, `PUNCTUATION`, `INVISIBLE`, `SOURCES`, `clean`, `entry`, `record`, `_locked`,
  `purge`.
- `src/xerscope/app/loading.py`: `_lexicon_dirs`, `lexicon_and_errors`, `refusals`,
  `file_variants`, `session_lexicon`, `teach`.
- `src/xerscope/cli.py`: `_args_lexicon`, `_cmd_lexicon`, `LEXICON_MAX_BYTES`,
  `_lexicon_export`, `_build_lexicon`, `_lexicon_report`, `_purge_suggestions`.
- `deploy/compose.yaml` (services `lexicon-init` and `xerscope`), `deploy/.env.example`
  (`XERSCOPE_LEXICON_DIR`).
- [docs/deploy.md](../deploy.md) §10 (folders, `lexicon-init`, threat model), §9 (checklist).
- Related: ADR-0014 (no real schedule in the repository), ADR-0020 (the Ask field's grammar),
  ADR-0024 (read-only container), ADR-0025 (remote access).
