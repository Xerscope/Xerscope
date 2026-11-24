# Task A — Redesign where two things do the same thing, and sourced tooltips

## Status against the code

What became of each proposal, checked against the current tree (the packages are those of
`docs/refactor-front-plan.md`, whose status table gives the evidence in full).

| Proposal | Package | Status | Evidence |
|---|---|---|---|
| A1.1 duplicate findings DF-01 to DF-13, DP-01, DP-04, DP-07, DP-09, DP-13, DP-14, VB-11 | P1, P2, P3, P4a, P5, P8, P9a, P15 | Done | `ui.fmt_number` / `ui.MISSING` everywhere, `app/explanation_panel.py`, `session.counted`, `viz/charts.DAY`, `diagnostic._differences_wide`, `downloads.built_download`, `ui.COLUMNS` with a help field, `ui.code_label` in the Gantt task picker |
| A1.1 DF-14, DP-08 | backlog, P7b | Open | `drop_duplicates(…).set_index("task_code")` in `ui.latest_names`; `session._parse` still cleared past 64 entries |
| A1.1 AR-04, AR-08 | P11b, P11a | Open | `views/export._data_date` reads `last_recalc_date` only; PPC help texts still in `views/ppc.py` |
| A1.1 AR-10 | P4b | Done | `rowPx` / `chromePx` sent in `gantt_data`; `gantt.js` writes `--row` (option 2 of the plan, not the template of this note) |
| R1 Panel | P2, P15 | Done | `explanation_panel.metric_panel(result, explanation, reading=None, detailed=False)` |
| R2 Download | P8, P15 | Done | `downloads.built_download`, `downloads.download_text`, `help_text` on `show_download` |
| R3 one formatting module | P1, P12a | Partial | one owner, `app/ui.py` (`MISSING`, `fmt_date`, `fmt_number`, `stamp`, `numbers_as_text`); no separate `app/format.py`; viz keeps `charts.DAY` and `charts.format_shift` |
| R4 table contract | P15 | Done | `ui.COLUMNS` entries are `(label, kind, help)`; `ui.table(…, empty=…)`; `tests/test_table_contract.py` |
| R5 per-session cache primitive | P7b | Open | no `_lru` helper; `_parse` (`session.py`), `memo` (`cache.py`, `MEMO_SIZE = 128`) and `hold` / `held` (`downloads.py`) keep three policies |
| A2 widget help texts | P14 | Done | `tests/test_widget_help.py`; `parameter_help` was not added: `views/audit.parameter_widget` writes one help per kind of input |
| A3 readings | P13 | Done | `analysis/explain.py` `Reading`, `READINGS` (51 keys); each builder sets `layout.meta["reading"]` through `charts._with_house_style`; `ui.chart(figure, reading=None)` takes a `READINGS` key (not a `Reading` as in A3.3) and draws `ui.reading_popover`; `tests/test_readings.py` |

Line numbers below locate the code on the tree this note was written on, before the split of
`state.py`; the table "Line numbers in the rest of this plan" at the top of
`docs/refactor-front-plan.md` gives where each cited `state.py` function lives now, and
`views/activity.py` has been removed.

---

Scope: `src/xerscope/app/**`, `src/xerscope/viz/**`. Inputs: `docs/refactor-front/findings.json`
(94 findings, 4 votes each), `docs/refactor-front/review.json`, `docs/refactor-front/widgets-without-help.txt`
(70 call sites), `docs/refactor-front-plan.md` (P1–P12). Every line number below was read with
`sed -n` or `grep -n` on that tree unless marked *(not reopened: location from the finding)*.
Nothing is decided here: each change is a proposal and waits for the maintainer.

Conventions kept throughout: identity is `task_code`; durations and floats are hours in the model,
`_d` and `wd` columns are working days of the activity's own calendar (`CONTRIBUTING.md`, Units);
sources are named, never linked.

---

## A1. Redesign where two things do the same thing

### A1.1 Findings kept (category duplicate-function / duplicate-feature, ≥ 3 confirmed-or-partly votes)

22 findings pass the 3/4 rule: DF-01 … DF-14, DP-01, DP-04, DP-07, DP-08, DP-09, DP-13, DP-14,
VB-11 (filed as duplicate-feature), AR-04, AR-08, AR-10 (filed as duplicate-function). DP-02, DP-03,
DP-05, DP-06, DP-10, DP-11, DP-12 have 0 confirming votes and are left out. DF-01 and DP-01 describe the
same pair and are treated as one.

For each: what the merge is, the optimisation the merge enables, and the gain counted in the code.

| Id | Where (opened) | Merge | Optimisation enabled | Gain counted |
|---|---|---|---|---|
| DF-01 / DP-01 | `audit.py:103-123` (`show_explanation`, 21 lines), `health.py:281-302` (`show_check`, 22 lines), `health.py:239-251` (`show_method`, 13 lines) | One `show_calculation(result, explanation)` for the left column; Audit calls `show_method` instead of `audit.py:118-123` | `explain(result)` is called once per panel and the same `Explanation` object feeds the calculation, the method and (A3) the reading; a wording change is one edit | Lines: 21 + 22 → ~8 + 8 call sites, −27 lines; copies of the "Note not in formula" guard 2 → 1; copies of the Method/Source caption 2 → 1 |
| DF-02 | `earned_value.py:78-79` (`format_number`), `ui.py:278-280` (`fmt_number`), call sites `earned_value.py:114, 121, 276, 332, 339` | Delete `format_number`; 5 call sites call `ui.fmt_number(value, "{:.2f}")` | One dash constant (`ui.MISSING`, `ui.py:262`) and one `None`/NaN rule for the whole page | −3 lines; dash literals in `earned_value.py` 1 → 0 |
| DF-03 | `task_panel.py:52-65` (`_text`, `_when`, `_days`, `_yes`), `task_panel.py:113`, `244-245` | `_when` → `ui.fmt_date` with a `DATETIME_FMT` template argument (format unchanged); `_days` → `ui.fmt_number(value, "{:.1f} wd")`; lines 113, 244, 245 → `ui.fmt_number(value, PY_FORMATS["pct"])` | One formatting module for the card and the history readout | Dash literals in `task_panel.py` 7 → 0 (4 helpers + 3 inline); −10 lines |
| DF-04 | `overview.py:48`, `forensics.py:99`, `ppc.py:72-73` (`_pct`, writes `n/a`), `ppc.py:127`, `task_panel.py:113, 244-245`, `charts.py:580` (date variant, `build_half_step`); `gantt.py:225` *(not reopened)* | Every KPI value through `ui.fmt_number(value, PY_FORMATS[kind])`; `charts.py:580` through one `DAY` constant in viz (viz may not import app, `docs/architecture.md`, "Layer rules") | One formatting module (redesign R3); the `pct` template exists once (`ui.py:490-498`) | `grep -rn '"–" if\|"n/a" if' app viz`: 16 lines today → 0 outside `ui.py`; two spellings of a missing value (`–`, `n/a`) → one (the `n/a` → `–` change is a visible change, planned in P9) |
| DF-05 | `state.py:954-969`, `1025`, `1056` *(not reopened)* | One `_date_span(snapshots)`; `_which_updates` = count + span | None beyond readability | −8 lines, per the finding |
| DF-06 | `state.py:1115-1116`, `1337` *(not reopened)*, `state.py:472` (opened: `" · + baseline copy" if aside == 1 else …`) | `counted(number, word, plural=None)` | None | 3 hand-written plural branches → 1 helper |
| DF-07 | `debug.py:389-391` (`calendar_zip_tag`, nested in a `with` body), `debug.py:427-429` (`zip_tag`), `state.py:1759-1760` *(not reopened)* | `snapshot_identity(snapshot)` in `state.py`; one module-level `zip_tag(anonymous, *extra)` | `data_identity()` is called twice per rerun for the calendar zip (`debug.py:397` and `406`); one tag object computed once per rerun and reused for `hold` and `held` | 2 tag builders → 1; `data_identity()` calls per rerun of the Debug page for the two zips 3 → 2 (one per zip) |
| DF-08 | `diagnostic.py:309-330`, `333-354` *(not reopened)* | `_differences_wide(comparison, key, fields)` | One pivot pass per table instead of one per copy of the algorithm | −15 lines, per the finding and P5 |
| DF-09 | `diagnostic.py:639-641`, `692-700` *(not reopened)* | Voters' correction kept: contracts differ (`dropna` vs `fillna(0.0)`); only the "column present or typed empty" guard becomes one function with an explicit `fill` | None | 3 guards → 1 |
| DF-10 | `viz/gantt.py:73-78`, `111-118` (def lines read by `grep -n "^def"`; bodies not reopened) | Column forms map over `_iso_text` / `_rounded_number` | One implementation of the ISO stamp and of the rounding, so a change in digits is one edit; the row builder `_task_rows` (`gantt.py:121-144`, opened) keeps its one pass | 2 pairs → 2 functions, −6 lines |
| DF-11 | `health.py:432-438` (`st.download_button` direct), `state.py:2024-2046` (`show_download`) | `download_text(label, text, name)` in `state.py` or `show_download` accepting plain bytes with `suffix=False` | The button style (icon, label suffix, refusal) exists once; A2 adds `help=` in one place for every download | `grep -rn "st.download_button" app`: 2 lines → 1 |
| DF-12 | `ui.py:273-275` (`stamp`), `charts.py:493` (`weeks["data_date"].dt.strftime("%Y-%m-%d")`), `charts.py:580`; `xml_baselines.py:65, 153` *(not reopened)* | `xml_baselines` uses `ui.stamp`; viz declares `DAY = "%Y-%m-%d"` used at 493 and 580 and in `DATE_AXIS` (`charts.py:43`) | One day format per layer | 5 literals → 2 constants (one per layer) |
| DF-13 | `ui.py:283-295` (`numbers_as_text`), `ui.py:501-515` (`_column_for`), `ui.py:517-528` (`column_config`); hand-written constructors at `health.py:110, 346, 380-381, 396-400`, `changelog.py:53-54`, `sets.py:57, 91`, `export.py:37-39`, `milestones.py:91-94`, `ppc.py:78-86`, `audit.py:129`, `earned_value.py:351-352` | Redesign R4: `ui.COLUMNS` owns label, kind and help; a view passes `overrides` only for a format exception | `column_config` built once per table from one table; the `help` of A2 lands in `_column_for` once | `grep -rn 'column_config\.\(Number\|Text\|Date\|Datetime\|Checkbox\)Column' app` minus `ui.py`: 25 constructors in 9 files → the format exceptions only (expected ≤ 6: `health.py:346` `%.2f` on date-named columns, `380-381` editor bounds, `audit.py:129` text `now`, `earned_value.py:351-352` wide formula and dated value column, `export.py:38` `%,d`); `format="%d"` literal: 9 → 0 |
| DF-14 | `ui.py:746-748` (`latest_names`), `viz/gantt.py:86` (def line only), `diagnostic.py:958` *(not reopened)*; known (`docs/backlog.md`, Structure, "set_index … 13 places") | Voters' correction: `Snapshot.by_code` keeps the first row of one snapshot and cannot serve a history frame with `keep="last"`; front share = one `names_by_code(frame, keep)` or `memo`-ised `latest_names` | `latest_names` runs `drop_duplicates` on the whole `store.history` per rerun on Task history (`activity.py:22`) and Milestones (`milestones.py:55`, via `names`); memoised, once per data set | `drop_duplicates(...).set_index("task_code")` in the front 3 → 1; one history pass per data set instead of one per rerun |
| DP-04 | `state.py:757-764`, `1836-1845` *(not reopened)* | Record only; one `_sidebar_flag(key, default)` if a third copy appears | None | 0 now; prevents a third copy |
| DP-07 | `debug.py:389-414` (26 lines), `debug.py:427-455` + `486-492` (36 lines), `export.py:72-89` + `99-110` (30 lines), `health.py:140-177` (38 lines); the other policy `state.py:2049-2075` (`download`) | Redesign R2: one `built_download(...)` owning button → `fetch(prepare=True)` → `hold` → `held` → `show_download` | One `held` lookup per slot per rerun and one tag per rerun; the refusal path (`fetched.refused`, `state.py:2035-2037`) is reached from one function | 130 lines across 4 sites → ~35 (helper) + 4 × ~8 (calls) ≈ 67, −63 lines; control-flow copies 4 → 1; `st.button` labels for "Build …" stay as they are (`pages.json` lists them) |
| DP-08 | `state.py:72-83` (`_parse`: dict, `clear()` past 64), `state.py:1717-1741` (`memo`: LRU, `MEMO_SIZE = 128`), and a third per-session policy `state.py:2015-2021` (`hold`/`held`: one slot, signature + tag); known (`docs/backlog.md`, Structure) | One `_lru(cache_name, size)` primitive under `_parse` and `memo`; `hold`/`held` stay a slot (a different contract: one value per slot) but are documented beside it | Eviction: `_parse` drops every parsed file at the 65th key (`state.py:79-80`), so a series of more than 64 files re-parses the whole series on the next rerun; an LRU re-parses one file | Cache policies 3 → 2 (LRU + slot); worst-case re-parses on a 65-file series: 64 → 1 |
| DP-09 | `gantt.py:350-358` (`names = dict(zip(...))`, lambda label), `ui.py:746-753` (`latest_names`, `code_label`), `activity.py:22-23`, `milestones.py:51-57` | `show_task_picker` passes `format_func=partial(ui.code_label, names)` with `names` a Series indexed by `task_code` | One label builder; with DF-14 memoised, zero per-rerun dict builds for the three pickers | Label builders 2 → 1; per-rerun name dict builds on the Gantt page 1 → 0 |
| DP-13 | `overview.py:40-52` (sentence twice, format `{round(shift, 1):+g} wd`), `changelog.py:26-32` (`{:+.1f} wd`), `forensics.py:82-89` (`{:+.1f} wd`), `task_panel.py:237-243` (a fourth copy, `{:+.1f} wd since first`); `charts.py:461-463` (`format_shift`, `{round(shift_wd, 1):+g} wd`) | `ui.finish_kpi(label, finish, shift_wd, first_sentence)` with one base sentence and one wd format; the viz `format_shift` stays (layer rule) and the two formats are aligned in P9 | One help sentence (A2/A3 can then cite the calendar and the sign once) | Sentence copies 5 → 1; wd formats in the front 3 (`+g`, `+.1f`, `+.1f … since first`) → 1 in `app/`, 1 in `viz/` |
| DP-14 / VB-11 | `milestones.py:91-94` (labels + `YYYY-MM-DD`), `ppc.py:84` (`data_date` → "Week ending"), `forensics.py:26-48` + `122`, `152` (`rename` before `ui.table`), `ui.py:129-258` (`COLUMNS`: `data_date` → "Status date"; no `first_forecast`, `latest_forecast`, `slip_wd`, `last_week_wd`, `total`, `kinds`, `step`, `finish_before_replanning`, …) | Redesign R4: the missing keys go in `COLUMNS`; `forensics` passes the raw frame; a page-specific label (PPC "Week ending") stays an explicit `overrides` entry, listed as such | The filter popover and the CSV read the same field names; `rename` copies disappear | DataFrame copies per rerun: `forensics.py:122` and `152` (`rename`) 2 → 0, `ppc.py:153` (`rename`) 1 → 0; label tables 3 (`STEP_LABELS`, `SERIES_LABELS`, `COLUMNS`) → 1 |
| AR-04 | `export.py:63-69` (`_data_date`: `last_recalc_date` only), `xer/model.py:1496-1503` *(not reopened; the voters opened it)* | `read_header(raw).data_date` from the model | One data-date rule (`CONTRIBUTING.md`, Where a change goes) | Rules 2 → 1; the result can move for a baseline file whose `last_recalc_date` is blank (then `plan_start_date`): a computed-value change, so a test fails first (`review.json`, P11 note) |
| AR-08 | `ppc.py:91-133` (help texts of the three PPC cards), `ppc.py:139-146` (Commitments caption), `explain.py` `KPI_FORMULAS` PPC entries (within 280-420) | Page help keeps the population caveat only ("n/a when nothing was due"); the Commitments caption is a template over `KPI_FORMULAS` + the week's numbers | The explanation lives in `explain.py` only (`CONTRIBUTING.md`, "A metric's explanation") | Formula wordings 3 → 1 |
| AR-10 | `viz/gantt.py:36` (`ROW_PX = 26`), `viz/gantt.js:9` (`const ROW = 26`), `gantt.css:35, 39-40, 46` *(not reopened)* | `gantt_assets()` (`gantt.py:253-260`) substitutes `--row-px` in the CSS and `ROW_PX` in the JS from the Python constant | `fitted_height` (`gantt.py:203-206`) and the browser agree by construction | Literals 6 → 1; `review.json` notes this turns the assets into templates, a rendering change inside a "byte-identical" package: the AppTest Gantt test must read the rendered component |

### A1.2 Five larger redesigns the duplicates point to

#### R1 — One "Panel" contract for the explanation of a metric

**Problem.** Health (`health.py:281-302`), Audit (`audit.py:103-123`) draw the same explanation in two
copies; Overview cards (`overview.py:37-67`), the Changelog readout (`changelog.py:21-44`), Forensics
(`forensics.py:77-111`), PPC (`ppc.py:91-133`) and Earned value (`earned_value.py:95-125`) each carry
their help as page strings in the KPI tuple, beside `KPI_FORMULAS` (`explain.py`), which `ui.kpis`
only opens in a "Formulas" popover (`ui.py:388-397`). The explanation of a figure therefore exists in
up to three places (tuple help, `KPI_FORMULAS`, `Explanation`), and A3's "How to read" has no slot.

**Options.**
1. `app/panel.py`: `show_calculation(result, explanation)`, `show_method(metric, explanation,
   parameters)` (plan P2) plus `metric_panel(result, reading=None)` composing both and an optional
   `Reading` popover. Pages call one function. Cost: ~70 lines moved, 15 new. Limit: a new module in
   `app/`, which composes and computes nothing (allowed by `docs/architecture.md` §7).
2. Keep `health.show_method` and import it from `audit.py`. Cost: 20 lines. Limit: a page importing a
   page.
3. Fold the helpers into `ui.py`. Cost: as 1. Limit: `ui.py` already mixes CSS, formatting, KPIs,
   filters and tables (`ui.py:66-130, 262-308, 357-432, 540-632, 675-713`; RD-10).

**Choice.** Option 1 (CONTRIBUTING "Where a change goes": one presentation of an explanation;
"Readable code" 1 and 5). It replaces `audit.show_explanation` (`audit.py:103-123`) and the body of
`health.show_check` (`health.py:284-299`); `health.show_method` (`239-251`) moves. Before/after:
byte-identical markdown and element order on both pages (`tests/golden/pages.json` lists the texts;
the heading-level fix VB-16 is P9, not here). The reading popover of A3 is a later, listed addition
to the golden file.

**Verification.** `uv run pytest tests/test_app.py tests/test_page_golden.py -q` with `pages.json`
unchanged; `scripts/duplication.py --threshold 0.8` no longer lists the 0.81 pair
`audit.py:103 / health.py:281`; `same_code.py` against the package base lists only
`show_explanation`, `show_check`, `show_method`.

#### R2 — One "Download" contract

**Problem.** Four hand-written build-and-hold sequences (`debug.py:389-414`, `427-455` + `486-492`,
`export.py:72-110`, `health.py:140-177`) beside `state.download` (`state.py:2049-2075`, a "Prepare"
button policy), one direct `st.download_button` (`health.py:432-438`), and `csv_download`
(`state.py:2078-…`). Each site builds its tag, holds, reads the slot and shows; the health block holds
two slots on one tag. A fix to refusal handling or to the button style touches five places.

**Options.**
1. `state.built_download(slot, tag, build_label, label, file_name, mime, plain, anonymised, sources,
   *, key, spinner=None, suffix=True)` owning the five steps; `download_text(label, text, name, mime)`
   for the TOML template. Cost: ~45 lines new, ~130 removed. Limits: export shows a spinner and passes
   `plain=None`, `anonymous=True` (`export.py:76-88`); health holds two files on one tag
   (`health.py:168-169`): the helper is called twice with the same tag, or takes a list of
   (slot, label, name, mime, plain, anonymised).
2. Keep the four sites, extract only the tag builder (DF-07). Cost: 10 lines. Limit: DP-07 stays.
3. Make `state.download` grow a `build=True` mode. Cost: 20 lines. Limit: two policies in one function
   with branches, against "Readable code" 2.

**Choice.** Option 1 (plan P8, option 1). It replaces `debug.calendar_zip_tag` + the block
`debug.py:393-414`, `debug.build_diagnostic` + `debug.py:486-492`, `export.build_anonymised_extract`
+ `export.py:99-110`, `health.prepare_sets` body `146-177`, and the direct button
`health.py:432-438`. Before/after: byte-identical labels, icons and file names (the golden lists
widget labels); the Build buttons keep their keys (`debug_calendars_build`, `debug_build`,
`anon_build`, `sets_build`).

**Verification.** `uv run pytest tests/test_downloads.py tests/test_app.py -q`; `pages.json`
identical; `grep -rn "st.download_button" src/xerscope/app` returns the one line in `state.py`;
`grep -rn "prepare=True" src/xerscope/app` returns the helper and `state.download` only (today 6
hits).

#### R3 — One formatting module

**Problem.** The missing-value dash and the "value with unit" formatter are written in `ui.py:262-280`
and rewritten at `earned_value.py:78-79`, `task_panel.py:52-65, 113, 244-245`, `overview.py:48`,
`forensics.py:99`, `ppc.py:72-73, 127`, `charts.py:580` (16 `"–" if` / `"n/a" if` lines in `app/`
and `viz/`); the day stamp at `ui.py:273-275`, `charts.py:493, 580`; the wd shift in three formats
(DP-13). Two layers are involved: `viz/` may not import `app/` (`docs/architecture.md`, "Layer rules").

**Options.**
1. `app/format.py` (moved out of `ui.py:262-308`: `MISSING`, `fmt_date`, `stamp`, `fmt_number`,
   `numbers_as_text`, `blank_missing`, `PY_FORMATS`) and in `viz/charts.py` one `DAY` constant plus the
   existing `format_shift` (`charts.py:461-463`); every app site calls `format.*`. Cost: ~50 lines
   moved, ~25 call sites edited. Limit: `ui` re-exports the names so the 31 existing `ui.fmt_*` calls
   do not move in the same pull request.
2. Keep everything in `ui.py`, only delete the copies (plan P1). Cost: ~40 lines. Limit: `ui.py` stays
   764 lines with five jobs.
3. A `kpi_value(kind, value)` reading `PY_FORMATS[kind]`. Cost: one helper. Limit: `wd`, `pts` are not
   kinds yet (`ui.py:490-498` has `d1, d2, d3, h0, pct, signed, int`).

**Choice.** Option 1, in two steps: P1 first (byte-identical: `ppc._pct` keeps `n/a`), the module
split in P12 with the theme and the filters. Before/after: byte-identical until P9 turns `n/a` into
`–` on the PPC cards (one visible change, named in P9).

**Verification.** `pages.json` identical after step 1; `grep -rn '"–" if' src/xerscope/app
src/xerscope/viz` returns `format.py` (or `ui.py`) lines only; `duplication.py --threshold 0.8` drops
the `format_number` / `fmt_number` pair.

#### R4 — One table contract: `ui.table` + `column_config` from `ui.COLUMNS`, no view builds its own

**Problem.** `ui.COLUMNS` (`ui.py:129-258`, 130 columns) owns label and kind, `_column_for`
(`501-515`) builds the Streamlit column with `help=spelled_out(label)` (an acronym gloss only, 46 of
130 columns get one, 84 get none: computed from the table and `glossary.spelled_out`,
`glossary.py:124-127`). Views then bypass it: 25 hand-written `column_config.*Column` constructors in
9 files (DF-13), two label tables in `forensics.py:26-48` applied by `rename` (`122`, `152`), one in
`ppc.py:84`, and `numbers_as_text` (`ui.py:283-295`) rewrites columns as text to get a dash. Each
`ui.table` render can copy the frame up to four times (`ui.py:697` subset, `304` `blank_missing`,
`729` `status_style`, `287` `numbers_as_text`), plus the view's `rename`.

**Options.**
1. `COLUMNS` grows a third field, `help`, for every column (texts in A2 below); the missing keys
   (`first_forecast`, `latest_forecast`, `slip_wd`, `last_week_wd`, `total`, `kinds`, `step`,
   `source`-of-funnel, `finish_before_replanning`, `replanning_wd`, `residual_wd`, `period_wd`,
   `engine_gap_wd`, `longest_path_float_d`, `matched`, `added`, `held_by`, `finish_case`, `found_exp`,
   `total_exp`, `match`, `flagged`, `removed`, `left`, `rows`, `columns`, `table`) are added; views drop
   their constructors and renames; `overrides` is kept for named exceptions only (PPC "Week ending",
   the dated value column of `earned_value.py:352`, the `now` text column of `audit.py:129`, the
   `%.2f` on date-named columns of `health.py:346`). Cost: ~40 `COLUMNS` lines, ~60 lines removed in
   views. Limit: a label used by two pages with two meanings (`data_date`: "Status date" vs "Week
   ending") stays an override, listed in a comment.
2. `ui.count_columns(*names)` / `ui.number_columns(kind, *names)` builders only (plan P8 option 1).
   Cost: 60 lines. Limit: labels still live in the views; the filter popover still shows renamed
   headers on Forensics.
3. A per-page `COLUMNS` dictionary merged into `ui.COLUMNS` at import. Cost: small. Limit: the same
   key defined twice is a silent override.

**Choice.** Option 1 (`ui.py:4-5` promises "the same column names … everywhere"; CONTRIBUTING "Where a
change goes"). It replaces the constructors at `health.py:110, 346, 396-400`, `changelog.py:53-54`,
`sets.py:57, 91`, `export.py:37-39`, `milestones.py:91-94`, `ppc.py:78-86` and the renames at
`forensics.py:122, 152`, `ppc.py:153`. Before/after: headers byte-identical (the golden lists table
columns and row counts, not headers; an AppTest check of `column_config` labels is added); the filter
popover on Forensics then shows the same labels but filters on field names (a visible change in the
filter keys only, named in the pull request). DataFrame copies per table render: 4 → 3 when
`blank_missing` proves redundant with `placeholder=MISSING` (`ui.py:704`; the headless check of P12
decides), and the 3 `rename` copies go.

**Verification.** `uv run pytest tests/test_app.py tests/test_page_golden.py -q`; a new AppTest
asserting, for every `dataframe` element of every page, that each column's label equals
`COLUMNS[name][0]` or a listed override; `grep -rn "column_config\." src/xerscope/app/views` lists
the named exceptions only.

#### R5 — One per-session cache primitive

**Problem.** Three per-session caching policies: `_parse` (`state.py:72-83`, dict cleared past 64),
`memo` (`1717-1741`, LRU of 128 keyed on `data_identity`), `hold`/`held` (`2015-2021`, one slot
keyed on signature + tag). The clear-all of `_parse` re-parses a whole series past 64 files; `memo`
keys prefix `data_identity()`, which reads the store, so `_parse` cannot sit on `memo` as is
(DP-08's note).

**Options.**
1. `_lru(name, size)` returning the session dict with the eviction, used by `_parse` (size 64, key
   `("parse", name, digest, project_id)`, no identity prefix) and by `memo`; `hold`/`held` documented
   beside as the "one value per slot" contract. Cost: ~25 lines, −10. Limit: `memo(…, keep=False)` and
   the identity prefix stay as they are.
2. Leave `_parse` alone, document the two policies (backlog item). Cost: 0. Limit: the 65th file still
   empties the parse cache.
3. Put `_parse` under `st.cache_data`. Cost: 2 lines. Limit: process-wide memory of a file's content,
   against `state.py:73-75` ("never in a process-wide cache").

**Choice.** Option 1, after P6/P7 (the plan splits `state.py` there). Before/after: no visible change;
re-parse count on a 65-file series 64 → 1 (measured with `tests/test_app_cache.py` counters, as P7
turns the `time_pages.py` counters into assertions).

**Verification.** `uv run pytest tests/test_app_cache.py tests/test_app_background.py -q`; a test
loading 65 small `xerkit` files and counting `load_snapshot` calls across a rerun (expected 65, not
130).

---

## A2. Widgets without a help tooltip

Method: each of the 70 call sites of `widgets-without-help.txt` was opened with its surrounding lines
(each call site read with 7 lines before, 4 after). The text proposed for `help=` is two
sentences: what the widget does, when to use it. Markdown is accepted by Streamlit's `help`.

Sites skipped because a wrapper should carry the help once (4 + 5 generic):

- `ui.py:316` `st.plotly_chart` inside `ui.chart` (`ui.py:310-316`): not a widget; the reading goes
  in the popover `ui.chart(fig, reading=…)` of A3.
- `ui.py:668`, `ui.py:671` (`_filter_inputs`): one input per column; the help is the column's help
  from `COLUMNS` (R4) plus the operator hint already in `placeholder` (`FILTER_HINT`, `ui.py:533-537`).
  Inject in the wrapper: `help=column_help(column) + "\n\nOperators: " + FILTER_HINT[kind]`.
- `ui.py:723` (`_open_in_gantt_button`): one text in the wrapper, below.
- `state.py:2038` (`show_download`): add a `help` parameter to `show_download` (`2024-2033`) and to
  `csv_download`, defaulting to "Downloads this table as it is shown; with Anonymous exports on
  (sidebar), Task IDs and names are replaced as in every other download of the session."
  (`docs/architecture.md`, the `anonymize.py` entry). The 25 download sites then need no text.
- `audit.py:45, 47, 49, 50` (`parameter_widget`): the label is the rule parameter's name; propose
  `help=parameter_help(rule_name, name)` reading the rule's docstring `Parameters` section or the
  notes `explain._population` already writes (`explain.py:205-209`, `_limit_note` `149-152`), so the
  text exists once in `analysis/`. Fallback text below.

### `app/code_picker.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 20 | selectbox | Task code (P6 activity code) | Picks one activity code type of the file (P6 ACTVTYPE); its values then filter the page's tasks. Use it to read one trade, area or contract on its own; None keeps every task. |
| 27 | multiselect | Code values | The values of the picked code type to keep; a typed text followed by Enter keeps every value containing it. Use it to narrow to a few values when the type has many. |

### `app/sets.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 67 | selectbox | Rows removed by | Lists the rows one population step took out of this check's denominator (the steps are in the funnel table above). Use it to see which tasks or links an exclusion removed, and why. |

### `app/state.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 343 | button | Select all | Ticks every readable file of the folder except the doubles of one status date. Use it to load a whole folder in one go. |
| 344 | button | Clear | Unticks every file of the folder. Use it to start the choice again. |
| 443 | file_uploader | Upload .xer files | Reads P6 exports (.xer) kept in this session's memory only; nothing is written to disk. Use it for files on this computer; a folder path below reads from the server instead. |
| 446 | text_input | …or read a folder | A folder of the server whose .xer files are listed below for ticking. Use it for a weekly series kept on the server; uploads above take precedence. |
| 479 | selectbox | Project of {file} | The project of this file the pages analyse, when the file holds several (its P6 Project Baselines are listed aside). Use it when the analysed project is not the one picked by default. |
| 544 | button | Done | Reads the ticked files, then the pages draw once the whole series is loaded; another choice of files asks for its baseline once. Use Ctrl+Enter; Esc cancels. Disabled while two uploads share a name. |
| 1639 | selectbox | Snapshot / Update | The weekly update the page works on; one choice for the session, every page opens on it. Use it to read an earlier week; the latest update is picked until you choose. |
| 1670 | selectbox | Compare with | The dates to outline behind each Gantt bar: previous update, baseline, first update, another update or none. Use it to read slippage as the bar leaving its outline. |
| 2038 | download_button | (wrapper) | See the wrapper note above. |

### `app/ui.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 668 / 671 | multiselect / text_input | (column filters) | Injected by `_filter_inputs`: the column's help, then "Operators: contains… / <0, >=5, -10..0 / >2026-11-01, 2026-11, 2026-11..2026-12" (`FILTER_HINT`). Every filter must hold; an empty text filters nothing. |
| 723 | button | Open {code} in the Gantt | Switches to the Gantt on the selected row's task, in the update shown. Use it to see the task's bar, logic and card. |

### `app/views/activity.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 23 | selectbox | Task | One Activity ID (task_code) with its latest name; its forecast dates, float and progress are then followed through every loaded update. Use it to read how one task moved week by week. |

### `app/views/audit.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 45 | multiselect | (parameter name) | Fallback: The values this parameter accepts (several at a time), starting from the standard's. Change them to see the check re-run with another population; the standard itself is not changed. |
| 47 | selectbox | (parameter name) | Fallback: One of the values this parameter accepts, starting from the standard's. Change it to re-run the check with another reading; the standard itself is not changed. |
| 49 | checkbox | (parameter name) | Fallback: Switches this parameter on or off for the audit, starting from the standard's value. The standard itself is not changed. |
| 50 | number_input | (parameter name) | Fallback: The threshold of this parameter, in the unit its name says (`limit_hours`: hours as P6 stores them; `limit_days`: working days of each task's calendar; `audit.py:137-138`). Change it to see what the count becomes. |
| 151 | segmented_control | Standard | The standard whose checks can be audited: P6 Check Schedule, DCMA 14-Point, DCMA DECM v8.0, Integrity, or an uploaded one. Pick the one your report follows. |
| 172 | selectbox | Check | One check of the standard: its sets (counted, checked but not counted, excluded), its population step by step and the same check re-run with the settings below. Use it to explain one number of Schedule health. |
| 192 | button | Reset | Puts every setting of this audit back to the standard's values and forgets those kept for the session. Use it after trying other thresholds. |

### `app/views/changelog.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 62 | multiselect | Category | Keeps the changes of the picked categories (Scope, Dates, Logic, Durations, Resources, Constraints…; the Project rows are never listed here). Empty keeps all. |
| 65 | multiselect | Change | Keeps the picked kinds of change within the categories. Use it to list one kind, such as durations changed, on its own. |
| 66 | text_input | Search | Keeps the rows whose Task ID, name, WBS or field contains the text, ignoring case and accents. Use it to follow one task or one WBS branch. |
| 104 | selectbox | To (newer) | The later of the two updates compared; the changes are read as To minus From. Use it with From to compare any two weeks, not only consecutive ones. |
| 106 | selectbox | From (older) | The earlier of the two updates compared. The buttons below set it one, four updates back or to the first loaded. |
| 117 | button | Previous / 4 back / First | Sets From to the update before To, four updates before it, or the first loaded. Use "4 back" for a monthly reading. |

### `app/views/debug.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 294 | file_uploader | P6 Activities export | P6's Activities view saved as CSV (labour units in hours) with Activity ID, Planned Value Labor Units, Earned Value Labor Units, Schedule % Complete. Use it to hold xerscope's PV and EV against P6's, task by task; the file stays in this session's memory. |
| 311 | selectbox | Column not found: {field} | The column of your export that carries this field, when its header is not P6's default. Pick it once per field; required fields block the comparison until picked. |
| 317 | number_input | Gap tolerance (h) | Difference in hours between xerscope and P6 above which a task is listed as differing (PV and EV, labour units). Use it to hide rounding gaps; 0 lists every difference. |
| 321 | number_input | PV labor units total shown by P6 (h, optional) | The project PV total P6 shows, to compare with xerscope's sum. Fill it when the task list of the export is partial. |
| 393 | button | Build calendar detail | Builds block 13 (each calendar's hours per period, weekday periods, exceptions) as one zip of CSV files, anonymised when the sidebar switch is on. Use it to check a calendar P6 and xerscope read differently. |
| 486 | button | Build diagnostic | Builds blocks 1 to 9, 11 and 13 as CSV, block 10 without its activity list, as one zip. Use it to send what xerscope read and decided for this update, without the XER file. |

### `app/views/earned_value.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 378 | toggle | Show as % of BAC | Draws PV, EV, AC and the forecast as a share of the Budget at Completion instead of labour hours; each update's points over its own BAC, the curves over the BAC of the update shown. Use it to compare updates whose baselines differ in size. |

### `app/views/export.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 45 | radio | Format | Parquet keeps the column types (dates, numbers) for Power BI; CSV opens anywhere. Pick Parquet for Power BI, CSV for a spreadsheet. |
| 99 | button | Build anonymized extract | Rebuilds every loaded file and the separate baseline file with new Task IDs, WBS, project, resource and calendar names; dates, durations, units and logic unchanged. Use it to share a schedule P6 and xerscope compute the same results on. |

### `app/views/forensics.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 166 | selectbox | Update | The update read against the one before it: the week's delay (finish before replanning) and what the week's replanning did to the finish. Pick any update after the first. |

### `app/views/gantt.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 99 | text_input | Ask the schedule | A sentence in English or French ("critical not started in civil works", "jalons en retard") turned into the page's filters from the file's own words; no model reads the schedule. Use it instead of the filters below; a × on a chip drops that filter. |
| 158 | button | (clarify choice) | Picks which code value or type the word meant when the file has several of that name. Click one; the choice is kept for this sentence. |
| 176 | button | (teach suggestion) | Teaches, for this session, that the word you typed means this label of the file. Click the right one; nothing is kept beyond the session. |
| 191 | selectbox | WBS | The WBS branch drawn: the node, its activities, then its child nodes, as in P6's Activities view. Use it to focus a branch; the breadcrumb above climbs back. |
| 213 | button | {node} › | Moves the chart up to this ancestor node. Use it to climb back from a branch. |
| 244 | multiselect | Status | Keeps the activities with the picked P6 status (Not started, In progress, Complete). Empty keeps all. |
| 245 | multiselect | Float | Keeps the activities of the picked float category: Critical (P6 critical, float ≤ 0 d or driving path), Near critical (total float ≤ 10 wd), Normal, Complete (`config.py:12-13`). Use it to see the critical and near-critical work alone. |
| 246 | text_input | Search | Keeps the activities whose Task ID or name contains the text, ignoring case and accents. |
| 249 | toggle | Logic links | Draws the relationships between the activities shown, from the predecessor's driving end to the successor's driven end. Switch it on to read why a task waits; off on a large branch. |
| 250 | toggle | Hide LOE | Leaves out Level of Effort activities, whose bars span their predecessors and successors and carry no float of their own. Switch it off to see hammocks and management activities. |
| 288 | button | Show all (Ask banner) | Empties the Ask field and its filters; every activity of the branch is drawn again. |
| 296 | button | Show all (focus banner) | Drops the focus a Schedule health check set (its listed tasks) and draws the whole branch again. |
| 354 | selectbox | Task | The activity whose card (P6 properties, assignments, logic) and history are shown under the chart. Click a bar or a row in the chart, or pick a Task ID here. |

### `app/views/health.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 184 | selectbox | Show the sets of | Lists, for one check, the items it counted, the items checked but not counted and the items excluded from the file. Use it to see the tasks or links behind a count without leaving the page. |
| 307 | toggle | Expand all | Opens every check's panel at once (calculation, method, flagged items). Use it to read or print the whole standard; off, open checks one by one. |
| 322 | button | Compute the trend on the N updates | Runs every check of the standard on every loaded update, once per session; each update's result comes from the cache when it is there. Use it to see a check across weeks; it takes several seconds on a large file. |
| 329 | selectbox | Check | The check drawn in the trend chart below: its value per update against its target. |
| 361 | file_uploader | Report counts (.csv) | A CSV `id,found,total` typed from a P6 Check Schedule report run on the same update and baseline. Use it instead of typing the counts in the table below; nothing typed is kept on the server. |
| 375 | data_editor | (report counts) | Type the report's found and total per check; a line left empty is not compared. Use it to prove the page's counts against P6's. |
| 432 | download_button | Download the template | A TOML file with every rule, its parameters and a target, to edit into your own standard. Use it as the starting point; upload the result below. |
| 439 | file_uploader | Upload a standard (.toml) | Registers your standard for this session and lists it in the Standard picker above; a built-in id is refused. Use it to run your company's checks; the folder given to `xerscope app --standards` does the same for every session. |
| 463 | segmented_control | Standard | The checklist run on the update: P6 Check Schedule (the P6 Professional dialog's checks), DCMA 14-Point, DCMA DECM v8.0, Integrity (the Schedule Project Log checks), or an uploaded one. Pick the one your report follows; P6 is the default. |
| 474 | toggle | Failed checks only | Hides the checks in pass, info or n/a in the detail below. Use it to read what needs attention first. |

### `app/views/milestones.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 48 | button | Finish milestones | Picks every finish milestone of the latest update. Use it as the usual MTA set. |
| 49 | button | Critical milestones | Picks the critical finish milestones only. Use it on a large schedule where every milestone would crowd the chart. |
| 50 | button | Clear | Empties the pick. |
| 51 | multiselect | Milestones and key tasks (up to N) | The milestones and tasks whose forecast date is followed update by update; each keeps the colour of its tag in the chart. Up to N at a time; a task's finish is used, a start milestone's start. |

### `app/views/overview.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 93 | button | Compute scores | Runs every built-in standard on the latest update and fills the score cards; Schedule health reuses the results. Use it when the cards read "not computed yet"; it takes several seconds on a large file. |

### `app/views/ppc.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 225 | number_input | PPC target (%) | The dotted line of the chart: the share of commitments kept you aim for, in percent. 80 is xerscope's default (`charts.py:40`); Last Planner System (PPC) sets no fixed target in the sources this repository names. |
| 234 | selectbox | Week ending | The update W whose commitments are read: what W−1 forecast to start or finish by W's status date, against what W reports done. Pick a week; the first update has no W−1. |

### Columns of `ui.COLUMNS` without a help, with the text to add (R4, `help` field)

`_column_for` (`ui.py:501-515`) gives `help=spelled_out(label)`: 46 of the 130 columns get an
acronym gloss, 84 get none (computed from `ui.py:129-258` and `glossary.spelled_out`). For the 46,
the gloss stays and the text below is prepended. Unit and P6 field named where the model gives one;
"(model.py not reopened)" marks a field name taken from the P6 vocabulary rather than read in
`xer/model.py`.

| Column | Label | help= |
|---|---|---|
| task_name | Task name | The activity's name as the file writes it (TASK.task_name). Anonymised in downloads when the sidebar switch is on. |
| bl_name | Task name | The name the baseline gives the activity (baseline TASK.task_name), matched on task_code. |
| type / task_type | Type | P6 activity type: Task dependent, Resource dependent, Start or Finish milestone, Level of effort, WBS summary (TASK.task_type; model.py not reopened). Milestones and LOE are left out of most checks. |
| status | Status | P6 status: Not started, In progress, Complete (TASK.status_code; model.py not reopened). |
| start / finish | Start / Finish | The activity's current dates: actual when there is one, else remaining early dates (docs/architecture.md: "actual > remaining > early"). Date and time of the file. |
| act_start_date / act_end_date | Actual start / finish | Dates reported as done (TASK.act_start_date, act_end_date). An actual after the status date is flagged by P6-10b, DCMA-09, 06A506a. |
| target_start_date / target_end_date | Planned start / finish | P6 Planned dates (TASK.target_start_date, target_end_date): the baseline when no baseline file is set (Baseline: planned dates). |
| early_start_date / early_end_date | Early start / finish | Earliest dates the CPM forward pass gives (TASK.early_start_date, early_end_date). |
| late_start_date / late_end_date | Late start / finish | Latest dates without delaying the project (or its Must Finish By), from the backward pass (TASK.late_start_date, late_end_date). |
| constraint / constraint2 | Constraint / Secondary constraint | P6 primary / secondary constraint (TASK.cstr_type, cstr_type2) with its date. Hard: Mandatory Start/Finish (DCMA adds Start/Finish On and On or Before); soft: On or After, As Late As Possible (`standards/p6.toml:47, 56`, `dcma.toml:61`). |
| reason | Reason | Why the check lists this row, as the rule writes it. |
| lagged_from | Lag from | The predecessor the listed lag comes from (a relationship check). |
| drives | Drives | The successor this activity drives (critical path or dangling checks). |
| previous | Previous update | The value in the update one status period earlier (28 days, 06A504a/b): an actual date that changed since. |
| now | This update | The same field in the update shown. |
| pred_code / succ_code | Predecessor / Successor | Activity ID (task_code) of the relationship's predecessor / successor. |
| pred_name / succ_name | Predecessor / Successor name | Their names in the update. |
| lag_hr | Lag (h) | Relationship lag in hours as P6 stores it (TASKPRED lag; model.py not reopened). Negative = lead. |
| pred_start / pred_finish / succ_start / succ_finish | Pred. / Succ. start / finish | Current dates of the two ends of the relationship, as Start / Finish above. |
| pct_complete | % complete | P6 Activity % Complete following the activity's percent complete type: duration, physical or units (docs/formulas.md §1.3). |
| is_critical | Critical | P6 critical flag: total float ≤ the project's critical threshold, or on the longest path when the project's critical path type says so (`explain.critical_definition`, `explain.py:270-288`). |
| in_snapshot | In update | Baseline task still present in the update shown (BAC, PV and EV sum over these; docs/formulas.md §3). |
| labor_budget_hr / labor_actual_hr / labor_remaining_hr | Budget / Actual / Remaining (h) | Labour hours: TASK.target_work_qty / act_work_qty / remain_work_qty, else the sums of the task's labour assignments (docs/formulas.md:25). |
| schedule_pct | Schedule % | P6 Schedule % Complete: share of the baseline duration elapsed at the status date, in working time of the baseline calendar (docs/formulas.md §3). |
| perf_pct | Performance % | P6 Performance % Complete by the WBS's earned value technique (activity %, 0/100, 50/50, custom). |
| pv_pct | Percent scheduled | PV / BAC in %, labour hours (P6 Planned Value / Budget At Completion). |
| ev_pct | Percent complete | EV / BAC in %, labour hours (P6 Earned Value / Budget At Completion). |
| data_date | Status date | The project's data date (PROJECT.last_recalc_date, `export.py:63-69` reads it; the model falls back to plan_start_date). Every "before / after the status date" check counts from it. |
| source | File | The XER file the update was read from. |
| forecast_finish | Forecast finish | Latest finish of the project's activities in this update (actual, else remaining, else early finish; `KPI_FORMULAS` "Forecast finish"). |
| activities / complete / in_progress / not_started | Tasks / Complete / In progress / Not started | Counts of activities in the update; in progress = started and not complete (`store.py:221-224`). |
| critical | Critical | Count of activities flagged critical (`store.py:225`). |
| relationships | Relationships | Count of TASKPRED rows of the update (`store.py:226`). |
| pct_complete_count | % complete (count) | 100 × complete / activities, a count, not hours (`store.py:227`). |
| category / change / field | Category / Change / Field | Changelog: the family of the change (Scope, Dates, Logic, Durations, Resources…), its kind, and the XER field that changed (docs/formulas.md §5). |
| before / after | Before / After | The field's value in From and in To. |
| delta | Δ | After − before; for a start or finish, working days gained (+) or lost (−) on the task's calendar, a later date reads negative (`changelog.py:75-76`). |
| pct_prev / pct_now | % previous / % now | Activity % complete in W−1 / W; 0 when the task is absent (docs/formulas.md:385-387). |
| pct_delta | Δ % complete | pct_now − pct_prev, points (docs/formulas.md:388). |
| commitment | Commitment | Start or Finish: what W−1 forecast on or before W's status date (Last Planner System (PPC); docs/formulas.md:368-378). |
| kept | Kept | The commitment was met in W: started / complete on or before the status date. |
| in_update | In update | The committed task is still in W; a deleted task is listed and left out of the counts. |
| status_now | Status now | The task's status in W (deleted when absent). |
| planned_date | Forecast at W−1 | The start or finish W−1 forecast for the committed end. |
| actual_date | Actual | The actual start or finish W reports, when kept. |
| forecast_now | Forecast now | W's forecast for the committed end when it was not kept. |
| starts_kept / starts_committed / finishes_kept / finishes_committed | Starts / Finishes kept / committed | The week's counts behind PPC Start and PPC Finish; milestones and LOE left out (docs/formulas.md:368-378). |
| new / deleted | New / Deleted | Task absent from W−1 / absent from W (docs/formulas.md:393). |
| earned_hr_week / actual_hr_week | Earned / Actual this week (h) | Labour hours earned (budget × Δ% complete, or EV(W) − EV(W−1) with a baseline) / actual hours added between the two updates (docs/formulas.md:389-392). |
| budget_hr | Budget (h) | Σ labour budget hours of the WBS node's tasks (docs/formulas.md:399). |
| activities_progressed | Tasks progressed | Tasks of the node whose % complete rose this week (docs/formulas.md:400). |
| progress_pts | Progress (pts) | 100 × earned hours this week / budget hours of the node, points of % complete (docs/formulas.md:401). |
| group | Group | The standard's grouping of the check (the TOML's group). |
| check | Check | The check's name in the standard. |
| target | Target | The threshold the standard sets, in the check's unit (%, count, ratio, pass/fail). |
| result | Result | The value found, in the check's unit; n/a when the population is empty or an input (baseline) is missing. |
| count | Found / checked | Numerator / denominator behind the result (`checks.py:199-205`). |
| note | Note | What the check could not count or read, and the baseline it was computed on (`checks.py:235-240`). |

Columns used by pages but absent from `COLUMNS` today (they get label and help with R4):
`first_forecast`, `latest_forecast` ("First / Latest forecast": the milestone's forecast in the first
/ latest update; `progress.py:75-81`), `slip_wd` ("Slip since first (wd)": first − latest forecast on
the milestone's calendar, later = negative), `last_week_wd` ("Last update (wd)": the same between the
last two updates), `total` / `kinds` (changelog category totals, `changelog.py:435-439`), `step` /
`removed` / `left` / `source` (funnel steps: the step's label, rows it removed, rows left, the text it
follows; `audit.py:61-75`), `finish_before_replanning` / `replanning_wd` / `residual_wd` /
`period_wd` / `engine_gap_wd` / `longest_path_float_d` / `finish_case` / `held_by` / `matched` /
`added` (half-step series, `forensics.py:32-48`, AACE RP 29R-03 MIP 3.4), `flagged` ("Items listed"),
`found_exp` / `total_exp` / `match` (report comparison, `health.py:396-400`), `table` / `rows` /
`columns` (export tables, `export.py:37-39`).

---

## A3. "How to read this chart" for every figure and metric table

`grep -n "^def build_" viz/charts.py` finds 10 public builders (`charts.py:128, 242, 280, 402, 421,
434, 483, 543, 572, 598`), not 12; plus the Gantt (`viz/gantt.py`, `gantt.js`). The reading of each
below, then the design.

Thresholds and sources are those the repository names: `INDEX_ALERT = 0.95` (`charts.py:50`),
`PPC_TARGET = 80` (`charts.py:51`), `critical_float_days = 0`, `near_critical_float_days = 10`
(`config.py:12-13`), DCMA-06 `limit_days = 44` (`standards/dcma.toml:68`), BEI ≥ 0.95
(`dcma.toml:140`, P6-13 > 0.95 `p6.toml:163`), CPLI ≥ 0.95 (`dcma.toml:131`), `EVMS = "DCMA EVMS
(EIA-748)"`, `LPS = "Last Planner (PPC)"`, `LIPKE = "Earned Schedule (Lipke)"` (`explain.py:315-317`),
AACE RP 29R-03 MIP 3.4 (`docs/formulas.md` section 5.1). The line
references inside the reading texts below are those `explain.READINGS` carries; they point at the
tree this note was written on. No source in the repository sets a threshold for SPI
or CPI: 0.95 on the indices chart is xerscope's alert line, said as such.

### A3.1 Figures

**1. `build_scurve` (`charts.py:128-207`), Earned value page (`earned_value.py:380-388`).**
How to read: x = calendar dates, y = labour hours or % of BAC (toggle). PV (baseline) is a line through
every day of the plan; EV and AC are one point per update (circles, squares); the dashed line continues
AC with the remaining hours to the EAC label; the BAC label ends the PV curve. A dashed vertical line
marks the status date (`_mark_data_date`, `charts.py:70-83`); at it a vertical mark joins PV and EV,
labelled SV, green when EV ≥ PV, red when behind (`charts.py:210-240`).
What it means: EV under PV at the status date is work planned and not earned; AC above EV is hours spent
for less work; the forecast end above BAC is an overrun in hours.
What to conclude: SV < 0 is behind plan in hours; the gap EV–PV read along x is the time behind.
Source: Oracle P6 glossary definitions quoted in docs/formulas.md §3 (PV, EV, BAC, SPI); EVMS EIA-748 /
PMI Practice Standard for EVM for the names (explain.py `EVMS`).

**2. `build_index_trend` (`charts.py:242-277`), Earned value page (`earned_value.py:394-402`).**
How to read: x = status dates, y = a ratio; one line per index (SPI labour units, SPI 4 weeks, BEI DCMA,
EV / AC, and SPI cost when costs are on); a grey line at 1.0, a red dotted line at 0.95 labelled;
end labels give the last value (three decimals for SPI, `charts.py:248`).
What it means: 1.0 = on plan; SPI < 1 = less earned than planned to date; SPI (4 weeks) = the last
month alone (`SPI_WINDOW_READING`, `explain.py:296`); BEI = tasks completed / tasks due.
What to conclude: BEI < 0.95 is flagged by DCMA 14-Point (PAM 200.1 §3.1.2.4, `dcma.toml:141`) and by
P6 Check Schedule (> 0.95, `p6.toml:164`); for SPI and EV / AC the 0.95 line is xerscope's alert
(`charts.py:39`), no standard in the repository fixes it.
Source: DCMA 14-Point Assessment, item 14 (BEI); P6 Professional Check Schedule report (BEI); EVMS
EIA-748 for SPI; docs/formulas.md §3.

**3. `build_mta` (`charts.py:280-360`), Milestones page (`milestones.py:73-79`).**
How to read: x = reporting (status) date, y = forecast date of the milestone, both axes on the same
scale so the line forecast = status date is the 45° diagonal; below it is the past (shaded). One line
per milestone in its tag colour; a diamond where the update reports it complete, where the line meets
the diagonal. The last point is bigger and red when the date moved later in the last update, green when
earlier; the end label gives the code and the move in wd (`_mta_end_label`, `charts.py:377-387`).
What it means: a horizontal line is a stable forecast; a rising line is a milestone slipping week after
week; a line climbing parallel to the diagonal is a milestone that moves as fast as time passes.
What to conclude: red up-arrows on several milestones in the same update mean the week's replanning
moved the end dates; read the Slippage table for the wd on each milestone's calendar.
Source: docs/formulas.md §4 (MTA: `milestone_trend`, `milestone_slips`, `plotted_trend`); no external
standard is named in the repository for the MTA.

**4. `build_activity_dates` (`charts.py:402-411`), Task history (`task_panel.py:251`).**
How to read: x = status date, y = the task's forecast start and finish, one line each.
What it means: a finish rising from update to update is the task slipping; a flat start with a rising
finish is a duration growing.
What to conclude: compare with the Total float chart beside it: a slip with float falling to 0 puts the
task on the critical path.
Source: xerscope (`store.history`); P6 fields Start / Finish as docs/architecture.md defines them.

**5. `build_activity_float` (`charts.py:421-431`), Task history (`task_panel.py:254`).**
How to read: x = status date, y = total float in working days of the task's calendar; a red dotted line
at 0 labelled "critical".
What it means: float is the delay the task can take without moving the project finish (or its Must
Finish By); negative float = the project is already late against that date.
What to conclude: ≤ 0 d is critical (`config.py:12`; P6 Define critical activities, read by
`explain.critical_definition`); > 44 wd is high float for DCMA 14-Point, item 6 (`dcma.toml:70`), and
P6 Check Schedule Large Float (`p6.toml:86`).
Source: DCMA 14-Point Assessment, items 6 and 7; P6 Professional Check Schedule report (Large Float,
Negative Float).

**6. `build_finish_trend` (`charts.py:434-458`), Overview (`overview.py:125`).**
How to read: x = status date, y = the project's forecast finish, one point per weekly XER; the hover
gives the file and the shift in wd against the previous update.
What it means: a rising line is the end date slipping; the shift is working days on the newer
update's project calendar, later = negative (`store.py:231-236`).
What to conclude: a finish that holds while the half-step "finish before replanning" slips (Delay
analysis) is a delay absorbed by replanning.
Source: xerscope (`SnapshotStore.summary`, docs/formulas.md §4 Finish shift); P6 Latest Early Finish.

**7. `build_ppc` (`charts.py:483-540`), PPC page (`ppc.py:257`).**
How to read: x = week ending (status date, categorical), y = % 0–105; three lines: PPC Finish (Last
Planner's PPC), PPC Start, PPC W/W−1 (both kinds together); a red dotted line at the target with its
label in the right margin; an open marker = a week with a note (more than a week since the previous
update, or Task IDs changed); a gap = a week with nothing committed.
What it means: the share of what W−1 promised to start or finish by W's status date that W reports done
(docs/formulas.md:368-378); milestones and LOE are left out.
What to conclude: under the target line, commitments are not kept; the Commitments table names which.
80 % is xerscope's default target (`charts.py:40`); the repository names no PPC threshold from the
Last Planner System.
Source: Last Planner System (PPC); docs/formulas.md §4.

**8. `build_metric_trend` (`charts.py:543-569`), Schedule health, Trend (`health.py:331-339`).**
How to read: x = status date, y = the check's value in its unit (%, count, ratio); the hover gives
found / checked; a red dotted line at the target when the check has one (none for pass/fail).
What it means: the same check, same standard, on every loaded update.
What to conclude: on the wrong side of the target line the check fails that week; the target and its
direction are the TOML's (`standards/*.toml` `target`).
Source: the check's own `source` field (P6 Professional Check Schedule help page ids; DCMA-EA PAM
200.1 §; DECM v8.0 sheet id; Oracle P6 EPPM 26 help, Schedule Project Log), shown by `show_method`.

**9. `build_half_step` (`charts.py:572-595`), Delay analysis, Step by step (`forensics.py:121`).**
How to read: x = the steps of the half-step reading in order (scope, dates, logic, durations,
constraints, calendars, options…), y = working days the project finish moved when that kind of change
was applied to the earlier update; red bars = lost, green = gained; the hover gives the finish once
applied and the number of changes.
What it means: the earlier update is rescheduled with this update's changes one kind at a time
(analysis/forensics.py); each bar is what that kind did to the finish.
What to conclude: a progress bar deeper than the period (warning `forensics.py:124-129`) points to a
revision hidden in the half-step or to a non-working stretch; a residual (`130-134`) means a change the
changelog does not list moved the finish.
Source: AACE RP 29R-03 MIP 3.4 (observational, dynamic, contemporaneous, half-step; docs/formulas.md
§5.1).

**10. `build_slip_trend` (`charts.py:598-630`), Delay analysis, Every update (`forensics.py:151`).**
How to read: x = status date, y = date; two lines: "Finish shown" (the recalculated finish of each
update) and "Finish before replanning" (where the previous update's plan lands with this update's
progress alone).
What it means: the gap between them, week after week, is the delay the replanning absorbs.
What to conclude: a flat "Finish shown" over a rising "Finish before replanning" is a schedule being
re-planned to hold its date; read the series table for the wd of slip and replanning.
Source: AACE RP 29R-03 MIP 3.4; docs/formulas.md §5.1.

**11. The Gantt (`viz/gantt.py:1-14` docstring, `gantt_rows` 147-182, `gantt_data` 209-250;
`gantt.js:84-101` legend, `185-192` hover shift, `351-353` data date line), Gantt page
(`gantt.py:327` `ui.GANTT(...)`).**
How to read: a tree grid on the left (Activity / WBS, % complete, float) and the timeline on the
right, one row each, in P6 Activities-view order (WBS node, its activities, its child nodes). Bar colour
= float category: Critical (red, P6 critical), Near critical (amber, total float ≤ 10 wd), Normal
(blue), Complete (grey) (`PALETTE`, `gantt.py:29-35`; `categorise` 43-50). Diamonds = milestones; a
dark thin bar = WBS summary; a hollow outline behind a bar = the same activity in the comparison update
or baseline (legend item with the comparison label); a dashed vertical line = data date. Hover: "Finish
vs <comparison>" in wd, or "Finish vs BL (baselined tasks)".
What it means: slippage reads as the bar leaving its outline; red bars are the path that sets the
finish; amber bars are within 10 wd of it.
What to conclude: red bars not started before the data date line are the week's risk; the Float filter
and the Ask field isolate them. Thresholds: critical = total float ≤ 0 d or the project's critical path
type (P6 Define critical activities); near critical = 10 wd (xerscope setting, no standard).
Source: Oracle P6 Professional Activities view and Define critical activities (via
`explain.critical_definition`); xerscope `config.Settings`.

### A3.2 Metric tables shown by `ui.table`

Each table's reading is one `Reading` (A3.3) attached by the page; the columns' help comes from
`COLUMNS` (A2, R4). Call sites from `grep -rn "ui.table(" app`:

| Page · table (key) | Where | How to read / what it means / conclude | Source |
|---|---|---|---|
| Overview · Updates loaded (`overview_updates`) | `overview.py:128` | One row per weekly XER: status date, file, forecast finish, finish shift (wd, later = negative), counts of tasks by status, critical, relationships, % complete by count. A finish shift < 0 week after week is a slipping project. | xerscope `store.summary` (`store.py:209-238`) |
| Health · Results (`health_results`) | `health.py:106-112` | One row per check in the standard's order: status (pass red/green labels), id, group, check, result in its unit, found / checked, target, items listed. Fail = result on the wrong side of the target; info and n/a are not scored. | The standard's TOML `source` per check; `SCORE_HELP` (`ui.py:400-405`) for the score |
| Health · Parameters (`params_<id>`) | `health.py:244-248` | parameter, value, set by (standard or default): the effective settings of the check. | the TOML |
| Health · Flagged items (`flag_<id>`) | `health.py:263-268` | The tasks or links the check lists, culprits first; select a row to open the Gantt. | the check's `source` |
| Health · All checks, all updates (`health_trend`) | `health.py:342-348` | One row per check, one column per update (value, `%.2f`). Read a row left to right as the check's history. | idem |
| Health · Report comparison (`health_report`) | `health.py:393-403` | Found / total typed from the P6 report beside xerscope's, Match ticked when equal. A mismatch names the population to audit. | P6 Professional Check Schedule report |
| Audit · Settings sheet (`sheet_settings`) | `audit.py:130-132` | setting, now, default, accepts: the `[[metric]]` values to paste into a standard file. | `analysis/audit.settings_table` (`audit.py:220-226` in analysis) |
| Sets (Health, Audit) · Counted / Checked, not counted / Excluded (`table_<key>`) | `sets.py:46` | The three sets behind a count; nothing is recomputed (`audit.split`). | the check's `source` |
| Sets · Funnel (`funnel`, `ask_funnel`) | `sets.py:53-58`, `87-92` | start, then one row per population step: its label, the text it follows, rows removed, rows left; last row = counted. The denominator is the last step's left. | `populations.STEP_SOURCES` (docs/formulas.md:127-128: Oracle 101248, 46282, R1, Ten Six, PAM 200.1, DECM 8.0, xerscope) |
| Changelog · Changes by category (`changelog_categories`) | `changelog.py:49-56` | category, total changes, kinds seen. | docs/formulas.md §5 |
| Changelog · All changes (`changelog_all`) | `changelog.py:78` | One row per change: task, category, change, field, before, after, Δ (wd for dates, later = negative; after − before otherwise). | docs/formulas.md §5 |
| Changelog · Every week (`changelog_weekly`) | `changelog.py:91` | (category, change) rows, one column per week: counts. A kind that repeats every week is a habit of the updating, not an event. | `changelog.weekly_change_matrix` (`493-499`) |
| Delay analysis · Steps (`forensics_steps`) | `forensics.py:123` | step, finish once applied, shift (wd), changes applied: the table of the half-step bars. | AACE RP 29R-03 MIP 3.4 |
| Delay analysis · Series (`forensics_series`) | `forensics.py:153` | One row per update: finish held by (last activity, Must Finish By, Mandatory Finish), finish shown, finish before replanning, slip, replanning, residual, period (wd), recalculated vs file (wd), longest path float (d), matched / added / deleted, note. | AACE RP 29R-03 MIP 3.4; `FINISH_CASES` text (`forensics.py:20-25`) |
| Earned value · Calculation (`ev_calculation`) | `earned_value.py:347-354` | measure, P6 column, formula, value this update: each EV figure with its P6 name and the numbers behind it. | Oracle P6 glossary (docs/formulas.md §3); EVMS EIA-748 names |
| Earned value · Updates (`ev_updates`) | `earned_value.py:413` | One row per update: PV, EV, AC, SV, SPI, SPI 4 weeks, BEI P6 / DCMA, CPI, EV / AC baselined; indices written as text with a dash on the first update. | docs/formulas.md §3; DCMA 14-Point item 14 (BEI) |
| Earned value · Earned hours by task (`ev_tasks`) | `earned_value.py:422` | Per baseline task present in the update: EV budget, schedule %, PV, technique, performance %, EV, actual hours, EV finish. | docs/formulas.md §3 |
| Milestones · Slippage (`mta_slips`) | `milestones.py:86-96` | Per milestone: first and latest forecast, slip since first (wd), last update (wd), on its own calendar; later = negative. | docs/formulas.md §4 MTA |
| Milestones · Data (`mta_trend`) | `milestones.py:98` | The long frame of the chart: one row per milestone and update. | idem |
| PPC · Every week (`ppc_weeks`) | `ppc.py:79-88` | Per week: starts / finishes kept and committed, the three PPC, kept and committed together, note. | Last Planner System (PPC); docs/formulas.md §4 |
| PPC · Commitments (`ppc_commitments`), Milestones committed (`ppc_milestones`) | `ppc.py:150`, `167` | Per commitment: kind, kept, forecast at W−1, actual, forecast now, status now, in update. Milestones are shown but out of the PPC counts. | idem |
| PPC · Progress by WBS (`ppc_wbs`) | `ppc.py:153` | Per WBS level 1: progress points, earned and actual hours this week, budget, tasks progressed. | docs/formulas.md §4 Roll-up |
| PPC · Unplanned work (`ppc_unplanned`) | `ppc.py:177` | Tasks absent from W−1 with an actual start by W's status date: work done outside W−1's plan. | docs/formulas.md §4 |
| PPC · Progress by task (`ppc_progress`) | `ppc.py:194` | Tasks whose % complete, earned or actual hours moved: % previous, % now, Δ, earned and actual hours this week. | docs/formulas.md §4 Progress delta |
| PPC · Start and finish variance (`ppc_variances`) | `ppc.py:206` | Per task, wd of its calendar between its date in W−1 / W−2 and now (reference − current): negative = later. | xerscope (`analysis/progress.py`) |
| Gantt · Table view (`gantt_tasks`) | `gantt.py:403` | The bars as rows: task, WBS, status, float category, dates, total float and remaining (wd, dash when complete), % complete, budget hours, constraint. | as the Gantt |
| Task history · Resources (`task_resources`), Logic (`task_logic`), By update (`task_history`) | `task_panel.py:211, 218, 256` | TASKRSRC rows (units budgeted / actual / remaining); predecessors then successors with type and lag; one row per update with status, dates, float, durations, % complete, critical. | P6 Activity Details (Resources, Relationships) |
| Export · Tables (`export_tables`), Preview (`export_fact_activity`) | `export.py:32-42`, `60` | table, rows, columns of the star schema; the first 200 rows of fact_activity. | `export.export_tables` |
| Debug · blocks 1–14 (`debug_*`) | `debug.py:383-387, 424, 474` and others | Raw readings for comparison with P6; no reading beyond each block's caption (`debug.py:379-381, 419-423, 469-472`). | Oracle P6 EPPM 26 help, Schedule Project Log; P6 XER data map |

### A3.3 Design: `Reading`, `ui.chart(fig, reading=...)`, column help, coverage test

**Problem.** The reading of a figure exists today as a page caption (`overview.py:120-124`,
`earned_value.py:390-393`, `milestones.py:80-83`, `forensics.py:116-120, 145-149`), as a builder
docstring (`charts.py:128-144, 280-299, 483-491`), or nowhere (`build_activity_dates`,
`build_activity_float`, `build_finish_trend`, `build_metric_trend`, the Gantt beyond its legend).
Thresholds are drawn (`charts.py:39-40`, `266-271`, `524-537`) but not said with their source. The rule
"a metric's explanation lives in `analysis/explain.py`, never page text" (`CONTRIBUTING.md`, Where a
change goes) is not met for figures.

**Options.**
1. `analysis/explain.py`: a frozen `@dataclass Reading(how: str, meaning: str, conclude: str,
   source: str)` and `READINGS: dict[str, Reading]` keyed by figure name (`"scurve"`, `"index_trend"`,
   `"mta"`, `"activity_dates"`, `"activity_float"`, `"finish_trend"`, `"ppc"`, `"metric_trend"`,
   `"half_step"`, `"slip_trend"`, `"gantt"`) and by table key (`"health_results"`, …). Each
   `build_*` sets `figure.update_layout(meta={"reading": "<key>"})` (viz keeps importing nothing from
   `analysis/`, `docs/architecture.md`, "Layer rules"). `ui.chart(fig, reading: Reading | None = None)` reads
   `reading or READINGS[fig.layout.meta["reading"]]`, and draws, beside the section title, a
   `st.popover("How to read", icon=":material/help:")` with four short paragraphs; the Gantt page draws
   the same popover beside its toolbar from `READINGS["gantt"]`. Tables: `ui.table(..., reading=…)`
   draws the same popover above the frame; columns get their `help` from `COLUMNS` (R4). Thresholds
   that are parameters (PPC target, metric target) are formatted into `conclude` with `str.format` by
   the page (`Reading.conclude.format(target=…)`), the text itself staying in `explain.py`. Cost: ~120
   lines of text in `explain.py`, ~20 lines in `ui.py`, one line per builder, one argument per table
   call. Limit: a popover is one more element per chart in `pages.json` (regenerated once, reviewed);
   `README`-length readings go to `docs/formulas.md`, the popover holds four paragraphs.
2. Put the reading in the figure itself (`fig.layout.annotations` or a subtitle). Cost: small. Limit:
   text in the chart is cut on a phone and read by no screen reader; the rule puts explanations in
   `explain.py`.
3. One "How to read" expander per page listing every figure. Cost: small. Limit: the reading sits far
   from the chart; a page with six figures gets one long box.

**Choice.** Option 1 (CONTRIBUTING "A metric's explanation → `analysis/explain.py`"; the same shape as
`KPI_FORMULAS` + `_formulas_popover`, `ui.py:388-397`; `SPI_WINDOW_READING` already is a reading kept in
`explain.py:296`). The `source` field holds names only; `ui.without_addresses` (`ui.py:550`) is applied
anyway, as `show_method` does for the TOML `source` (`health.py:249-251`).

**Coverage test** (`tests/test_readings.py`, in the spirit of `tests/test_accessibility.py`, which
judges a run against a list of known entries, and of `tests/test_glossary.py:44-51`, which walks every
page's `metric` elements and checks their help). Three checks, described, not written:
1. *Static:* every `def build_` in `viz/charts.py` (by `ast`, as `scripts/same_code.py` reads code as
   text) sets a `meta` reading key, and every key is in `explain.READINGS`; `READINGS["gantt"]` exists;
   no `Reading.source` contains `http` or `www.`; every source names one of the strings already in the
   repository (`standards/*.toml` `source` prefixes, `explain.P6 / EVMS / LPS / LIPKE / XS`, "AACE RP
   29R-03", "DCMA 14-Point", "Oracle P6 EPPM 26 help, Schedule Project Log").
2. *Rendered:* with `AppTest` on the demo series (`PAGES` of `tests/test_page_golden.py:33`), for every
   page, the count of `plotly_chart` elements equals the count of popovers labelled "How to read", and
   each `dataframe` element whose key is in `READINGS` has one too; a chart drawn without a reading
   fails with the page and the figure's `meta`.
3. *Mutation:* `ui.chart` called with `reading=None` and a figure without `meta` raises in tests
   (`XERSCOPE_STRICT_READINGS=1`, set by `conftest`) so a new chart cannot ship silent; the test plants
   a builder without `meta` and sees check 1 fail.

**Verification.** `uv run pytest tests/test_readings.py tests/test_explain.py tests/test_app.py
tests/test_page_golden.py -q`: `pages.json` changes by exactly one `popover: How to read` line per
figure and per listed table, regenerated with `XERSCOPE_UPDATE_GOLDEN=1` in a separate reviewed
commit (plan §2); `tests/golden/standards.json` unchanged (no computed value touched);
`scripts/fitness.py --check tests/fitness_baseline.json` passes; `uvx ruff check` and `format --check`
clean; `tests/test_docstrings.py` on the new dataclass. Data privacy: readings are static project
text; no schedule value enters a `Reading` except the formatted threshold parameters.
