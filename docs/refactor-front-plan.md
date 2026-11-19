# Front refactoring plan (`app/`, `viz/`)

Scope: `src/xerscope/app/**` and `src/xerscope/viz/**`. The CPM engine, the parser and the
analyses are out of scope; a package that touches `analysis/` does so only to receive code
moved out of a page, never to change a computed value. The one exception (P11b, the data date
of a baseline file inside the anonymised extract) is its own package with its own failing-before
test, and is named as such.

Second pass (19 November): this version applies the critic's rule violations, places every
consensus finding, adds the security review of the front, the "how to read" readings, the widget
help texts and the files the first lenses never opened. Decision of 19 November, recorded here:
**the "how to read this chart" tooltips belong to this interface refactor** (P13), not to a later
documentation task.

## 1. Scope and method

The front was audited through six lenses (duplicate functions `DF`, duplicate features `DP`,
readability `RD`, visual bugs `VB`, loading and caching `LD`, layer rules `AR`), each finding
tied to `file:line` ranges opened by the auditor, cross-checked with the AST near-clone report
(`scripts/duplication.py` on `app/` and `viz/` (threshold 0.80), threshold 0.80) and `scripts/fitness.py`
output. `refactor-front/findings.json` holds 94 ids. 80 received four independent skeptic votes
(confirmed / partly / rejected, with the lines re-opened and, where a claim was a measurement,
re-run under `AppTest`); the other 14 carry no vote because they describe the same lines as a
voted id and were merged into it before the vote (appendix B lists the mapping). A finding is kept
when at least three of four votes confirm it or confirm it in part (consensus rule 3/4); where a
voter said `partly`, its corrected locations and reduced impact replace the auditor's (appendix G
lists every correction and where it was applied). All 80 voted findings reached consensus; none
was rejected (appendix A is empty and kept as a record). Items already listed in
`docs/backlog.md` "Structure" (lines 200-211) are cited as known (appendix C), not re-reported.

A second review (`refactor-front/review.json`, `refactor-front/redesign-and-readings.md`, `refactor-front/security-and-uncovered.md`) then read
the plan against the repository rules: a package mixes no move with a behaviour change (skill,
Refactoring 1); a change of behaviour is presented Problem / Options / Choice / Verification and
waits for the maintainer (skill, Engineering standard 4); a computed value moves only with a test
that fails before (CONTRIBUTING rule 3); a pull request aims at 400 lines (standard 5); no real
schedule data, activity name, project code or file path anywhere (rule 1); identity is
`task_code`, hours in the model, `_d` and `wd` are working days of the activity's own calendar.
Sources are named, never linked (the TOML `source` fields carry addresses; the plan, the readings
and the help texts do not, and `ui.without_addresses`, `ui.py:328`, strips them at display).

Naming in this plan: "Pna" is a move or a rename, output byte-identical, proven by
`scripts/same_code.py` and the goldens; "Pnb" is a behaviour change, presented Problem / Options
/ Choice / Verification, with the test that fails before it. "mechanical executor" marks mechanical moves
and renames where the target is fully specified; "senior" marks a package where a behaviour or a
design decision is taken. **`state.py` is changed only with the maintainer (Quentin): nothing in
P6, P7, P9b or U1 is coded before his agreement on the Problem / Options / Choice of that package.**

## 2. Safety net first

Per the skill section "Refactoring": move code first, change a behaviour in another pull
request, and prove that nothing computed moved. Before the first package, record the
reference state once on `main`:

```bash
uv run pytest -rs                                            # whole suite, MPXJ skips said
uv run pytest tests/test_characterization.py                 # tests/golden/standards.json
uv run pytest tests/test_page_golden.py                      # tests/golden/pages.json
uv run pytest tests/test_app.py -q -x                        # every page renders headless
uv run pytest tests/test_app_parity.py -q                    # page numbers == analysis API
uv run pytest tests/test_app_cache.py tests/test_app_background.py -q
uv run python scripts/duplication.py src --threshold 0.8 > dup_main.txt   # kept for the diff
uv run python scripts/fitness.py --check tests/fitness_baseline.json
uvx ruff check src tests scripts && uvx ruff format --check src tests scripts
uvx bandit -r src -ll                                        # CI job audit; "No issues identified"
```

`scripts/duplication.py` defaults to `THRESHOLD = 0.9` (`scripts/duplication.py:26`): the 0.81 to
0.87 pairs the packages promise to remove are invisible without `--threshold 0.8` (first review,
safety-net table).

Then, on every package branch, the same commands plus:

```bash
uv run python scripts/same_code.py <base of the package branch>    # moved definitions unchanged
uv run python scripts/duplication.py src --threshold 0.8 | diff dup_main.txt -   # fewer clones, never more
uv run python scripts/fitness.py --check tests/fitness_baseline.json  # ratchet only improves
```

`same_code.py` is run against the commit the package branched from, not `origin/main`: on a
branch ahead of `main` the report lists every unrelated change (first review: 81 ADDED, 47 CHANGED
on a branch 36 commits ahead) and the criterion "a pure move reports none" cannot be read.

Pass criteria common to every package: `standards.json` byte-identical; `pages.json`
byte-identical unless the package is a "b" package that names the changed lines in its
description and regenerates the file in a separate reviewed commit; `same_code.py` reports
only the definitions the package says it rewrote (a pure move reports none); the duplication
diff shows removed lines only; the fitness ratchet passes without editing
`tests/fitness_baseline.json` (an improvement is regenerated by the maintainer).

For packages that rewrite a function body (not a move), the proof is the one the skill asks
for: the old module loaded from the package base beside the new one, the same demo series
(`uv run xerscope sample`) through both, whole outputs compared (figure JSON digest for
`viz/`, `AppTest` element list for `app/`), then one planted defect per rewritten function,
each of which must fail the comparison. The script
`docs/refactor-front/time_pages.py` (LD-13) is kept as the perf smoke reference; it takes the
output folder as its first argument (`time_pages.py:12`), and its counters (`baseline_for`,
`Baseline.from_snapshot`, `run_metric` per rerun) become assertions in `tests/test_app_cache.py`
in P7. Note that `pages.json` lists labels, values, texts, table columns and trace types
(`tests/test_page_golden.py:3-6`), not widget `help`: a help text is pinned by an AppTest of its
own (P14), not by the golden.

## 2bis. Security review of the front

Read whole for this pass (`refactor-front/security-and-uncovered.md`): `viz/gantt.js` (421 lines), `app/style.css`
(297 lines), `app/reading.py`, the HTML sinks of `app/`, the caches, the inputs. Commands run:
`uvx bandit -r src -ll` → "No issues identified" (25 035 lines scanned, 4 low findings skipped by
`# nosec`); `uv run pytest tests/test_app_robustness.py tests/test_fuzz_parser.py -q` → pass.
Premise corrected: there is no `components.html` call in `app/` or `viz/`; the HTML sinks are four
`st.html` calls and one `st.components.v2.component`.

| Sink | What reaches the browser | Serialisation | Pinned by |
|---|---|---|---|
| `state.py:432` `_section_title` | two fixed strings of the Files window | `html.escape` on both | — |
| `state.py:536` | the literal `<hr class="xd-rule">` | constant | — |
| `ui.py:122` `apply_style` | `style.css` (repo file), CSS variables from `viz/charts.py` constants (`ui.py:118-121`), inlined fonts (`ui.py:75-88`) | constant text, no file data | — |
| `task_panel.py:203` `card_html` | every label and value of the activity card, from the XER | `html.escape` on title, label, value (`task_panel.py:148-153`) | `tests/test_app_robustness.py:69` |
| `ui.py:57` `GANTT = st.components.v2.component(...)`, called at `views/gantt.py:328-342` | `gantt_data` rows (names, codes, dates, numbers) as `data=` | JSON by Streamlit; the markup is the fixed `<div id="gantt"></div>` (`viz/gantt.py:257`) | `tests/test_viz.py:336, 345` |

Every Markdown a page writes goes through `ui.md_text` (links broken, specials escaped), checked by
`tests/test_app_robustness.py:69-96` on a crafted table name and file name.

- **SE-01 — `gantt.js` DOM sinks: checked, no issue.** Every text node is created by `el()` with
  `textContent` (`gantt.js:20-25`); no `innerHTML`, `insertAdjacentHTML`, `outerHTML`, `srcdoc`,
  `document.write`, `eval` (grep → 0; the list is asserted by `tests/test_viz.py:345`). Style and
  attribute sinks take numbers or palette constants only (`gantt.js:14, 16, 88, 237-238, 253-254,
  267, 273, 278, 306, 371`); a category outside the four fixed labels falls back to `P.Normal`
  (`267`). What goes back to Python is a row id (`392, 398`), accepted only if it names an activity
  drawn (`views/gantt.py:313-316`) or a WBS of the branch (`343`). Pinned by `tests/test_viz.py:336-360`.
- **SE-02 — the component is not sandboxed (low, informational; OWASP ASVS 5.0.0 output encoding,
  CWE-79).** `ui.py:54-57` registers a v2 component "not an iframe"; the shadow root is no security
  boundary. The barrier is the discipline of SE-01, pinned lexically. Options: (1) leave, the test
  list is the guard (cost 0; limit: a deny-list of names, `new DOMParser()` or `setAttribute("on…")`
  would pass); (2) extend `tests/test_viz.py:345` with `DOMParser`, `setAttribute("on`, `javascript:`
  and a positive check that every text write goes through `el()` or `textContent` (cost: 10 lines of
  test; limit: still lexical); (3) move the component to an iframe (cost: loses the theme variables
  `gantt.css:1-15` reads; `ui.py:54-56` says why it was not done). Choice: maintainer; (2) changes
  no behaviour and is listed in P16a. Verification: `uv run pytest tests/test_viz.py -q -k gantt`.
- **SE-03 — CSP (low).** Deployed, `deploy/Caddyfile` sets `frame-ancestors 'self'; object-src
  'none'; base-uri 'none'`, pinned by `tests/test_docker.py:309, 384`; no `script-src` (whether a
  hashed `script-src` works on Streamlit 1.67 is unverified). On a workstation there is no CSP.
  Options: (1) leave (no injection path found, SE-01); (2) try a hashed policy on the deployed
  stack and record the breakage (cost: one deploy run; limit: Streamlit's bundle changes per
  release). Choice: maintainer; out of this plan's scope (`deploy/`), recorded.
- **SE-04 — pickle between processes (`app/reading.py`): checked, no issue.** The parent pickles
  `(name, bytes, chosen_project)` into a `spawn` pool (`reading.py:96-97`), the worker returns
  objects the parser built; the file fills values, never the stream. Local pipe, same user.
  `BrokenProcessPool` → in-process fallback (`reading.py:105-114`). `streamlit_app.py:60-62`
  guards `__main__`.
- **SE-05 — Ask field: no model, nothing leaves the process.** `grep -rn "llm_backend\|QUERY_URL"`
  → 0. Grammar parser only (`analysis/ask/`), sentence cut at 300 characters (`views/gantt.py:99-106`),
  `RecursionError` caught (`134-136`); no network import under `src/` (`tests/test_docker.py:734`);
  fuzzed by `tests/test_fuzz_ask.py`.
  **SE-05a (low) — one thing survives the session by design:** `state.teach` (`state.py:179-190`)
  appends `(word, label, column, filter, date)` to `XERSCOPE_LEXICON/suggested/` on a "Did you
  mean" click (`views/gantt.py:173-177`); `label` is a word of the loaded file's vocabulary. Guards
  in `analysis/ask/suggested.py:55-95`; nothing is written when no lexicon folder is set
  (`state.py:137-138`). The page does not say that a click writes a file on the server. Options:
  (1) leave, document in `docs/deploy.md` (not checked whether it does); (2) one caption under the
  offers: "A pick is kept for review in the lexicon folder" (cost 1 line, P14 carries the text);
  (3) opt-in per deployment, already the case through `XERSCOPE_LEXICON`. Choice: maintainer.
  Verification: `uv run pytest tests/test_fuzz_ask.py tests/test_docker.py -q -k lexicon`
  (`tests/test_docker.py:757`).
- **SE-06 — session persistence: checked, two notes.** Every cache is in `st.session_state`
  (`_parsed` 72-83, `items` bytes 702/715, `bl_file` 421-423, `_headers` 261-273, `_memo`
  1720-1734, `_file_baselines`, `_pmxml_index` 896, `_load_job`/`_score_job`, `taught` 184);
  `grep -rn "cache_data\|cache_resource\|@st.cache" src/xerscope` → 0; `functools.cache` only on
  lexicon files and the font CSS (`state.py:141-166`, `ui.py:74-75`), no session data. No temp
  file. Downloads are bytes to `st.download_button` (`state.py:2038-2046`), anonymised unless the
  sidebar toggle is off; `disableDataExport = true` (`app/.streamlit/config.toml:20-22`). Note 1:
  memory on a shared instance (200 MB per upload, `config.toml:8`), mitigated by
  `XERSCOPE_DATA_LOCKED` and `maxUploadSize = 1` on the remote (`tests/test_docker.py:302`).
  Note 2: `runtime_table` discloses `Path.cwd()` and versions (`ui.py:90-110`) on the Debug page
  only, hidden on a locked instance (`state.py:639-645`, `streamlit_app.py:48-50`). P7b's
  `functools.cache` on `builtin_standards` would be the first process-wide cache of
  non-session data in the front: that is why it is a decision for the maintainer (P7b), not a
  "same results" edit.
- **SE-07 — inputs: checked, one note.** Uploads typed `.xer` (`state.py:443-445`), the parser does
  not trust the extension ("Snapshot or XerError", `tests/test_fuzz_parser.py:131-155`); Health CSV
  and TOML uploads with their errors caught (`health.py:361-371, 439-446`); folder `text_input`
  only when not locked, files read by names looked up in the listing (`state.py:569-570, 590-592`,
  CWE-22 checked); `number_input` at `audit.py:50` accepts any float into a rule parameter (what a
  rule does with an absurd value is unverified; the `status "error"` path exists); table filters use
  `str.contains(regex=False)` (`analysis/task_filters.py:22-26`, no ReDoS).

Not covered by an existing test and recorded, no package: an upload above the cap; a `.xer` whose
content is PMXML or binary through the page (the parser fuzz covers the function); a hostile value
in `code_values` labels reaching `selectbox` option labels (`code_picker.py:20-37`; whether
Streamlit parses option labels as Markdown is unverified); `read_header`/`load_header` on fuzzed
input (the picker's path, see section 6, file picker); `teach` with a hostile label (guards exist).

## 3. Work packages

Each package is one pull request aimed at 400 changed lines, independently mergeable in the
order of section 4. A "b" package changes a behaviour and lists what the user sees change.

### P1 — Formatting helpers converge on `ui` (effort S, executor: mechanical executor; move, byte-identical)

**Problem.** The missing-value dash and the "value with unit" formatter are rewritten in
seven modules beside `ui.MISSING` / `ui.fmt_number` / `ui.fmt_date` / `ui.stamp`
(`ui.py:262-280`, `273-275`): `earned_value.py:78-79`, `task_panel.py:53-65, 113, 244-245`,
`gantt.py:225`, `overview.py:48`, `forensics.py:99`, `ppc.py:72-73, 127`,
`xml_baselines.py:65, 153`. `ppc._pct` writes `n/a` where every other page writes `–`. Voters'
correction (DF-04): `overview.py:48` and `forensics.py:99` test `is None`, the others `pd.isna`;
the shape duplication is smaller than claimed, the `n/a` vs `–` inconsistency is real.

**Options.**
1. Replace each inline expression with `ui.fmt_number(value, template)` and `ui.MISSING`;
   add nothing to `ui`. Cost: ~40 lines; limit: `task_panel._when` uses `DATETIME_FMT`, so
   it keeps its own template string passed to `ui.fmt_date` (format unchanged).
2. Add a `ui.kpi_value(kind, value)` reading `PY_FORMATS[kind]` (`ui.py:490-498`). Cost: one new
   helper plus the same call-site edits; limit: not every unit (`wd`, `pts`) is a kind yet.
3. Leave `task_panel` helpers and only delete `earned_value.format_number`. Cost: minimal;
   limit: leaves five dash literals.

**Choice.** Option 1 (CONTRIBUTING Readable 5: no helper duplicated; Readable 1). `ppc._pct`
keeps `n/a` in this package (output byte-identical); the `n/a` → `–` wording change is a
one-line follow-up in P9a (visual fixes). The `viz/charts.py:580` date variant is handled in
P4a (viz may not import `app`, `docs/architecture.md:180`). Moving the formatters out of `ui.py`
into their own module (A1 redesign R3, option 1) is P12a's business, not P1's.

**Verification.** `uv run pytest tests/test_app.py tests/test_page_golden.py -q`:
`pages.json` identical. `scripts/duplication.py --threshold 0.8` diff: the
`format_number`/`fmt_number` 0.81 pair disappears. `same_code.py` lists only the deleted
`format_number` and the four `task_panel` helpers.

**Findings.** DF-02 (`earned_value.py:78-79`, `ui.py:262, 278-280`), DF-03
(`task_panel.py:53-65, 113, 244-245`), DF-04 (`ppc.py:72-73, 127`, `gantt.py:225`,
`task_panel.py:113, 244-245`; corrected list), DF-12 app share (`xml_baselines.py:65, 153` →
`ui.stamp`), RD-05 only as "fix on touch": no mass rename of `fmt_*` (CONTRIBUTING:49-51;
voters count 33 or 39 call sites, both too many for a rename). Merged, unvoted: DP-02, DP-03,
VB-03, VB-04, AR-05 (same lines, appendix B).

### P2 — One explanation panel for Health and Audit (effort S, executor: mechanical executor; move, byte-identical)

**Problem.** `audit.show_explanation` (`audit.py:103-123`) and `health.show_check`
(`health.py:281-302`) are the same ten statements for the left column; `audit.py:119-123`
re-inlines `health.show_method` (`health.py:239-251`) minus the parameters table. The
formula is drawn as a Markdown `####` under a `#####` group (`health.py:289, 310`,
`audit.py:109`). Voters: real, impact medium (two pages, ~15 lines), same finding as DP-01.

**Options.**
1. New `app/explanation_panel.py` with `show_calculation(result, explanation)` and
   `show_method(metric, explanation, parameters)`; both pages call them. Cost: ~60 lines
   moved; limit: a new module in `app/` (allowed: it composes, computes nothing).
2. Keep the helpers in `health.py` and import them from `audit.py`. Cost: 20 lines; limit: a
   page importing another page, a dependency the architecture document does not foresee.
3. Put them in `ui.py`. Cost: same as 1; limit: `ui.py` already has too many jobs (RD-10).

**Choice.** Option 1 (CONTRIBUTING "Where a change goes": one presentation of an explanation
in one place; `docs/architecture.md` §7: `app/` composes). The heading levels (VB-16) are not
touched here; they change in P9a because `pages.json` lists the Markdown texts. The module is the
home of P15's Panel contract (`metric_panel` with a reading slot) once P13 exists.

**Verification.** `pages.json` identical (same Markdown strings in the same order on Health and
Audit). `duplication.py --threshold 0.8` diff: the 0.81 `show_explanation`/`show_check` pair gone.
`same_code.py` against the package base lists only `show_explanation`, `show_check`, `show_method`.

**Findings.** DF-01 / DP-01 (`audit.py:103-123`, `health.py:239-251, 281-302`).

### P3 — `state.py` small duplicates and names (effort S, executor: mechanical executor, with Quentin; move, byte-identical)

**Problem.** `_dates_or_file` is `_which_updates` without the count (`state.py:954-969`) and
the span is inlined a third time at `1056`; `_count` (`1115-1116`) exists but `1337` and
`472` pluralise by hand and it has no docstring; `_metric_key` (`1759-1760`) has none;
`anonymous_exports`/`costs_shown` (`1836-1845`) are one reader; loop variables `s`, `w`, `c`
(`state.py:462, 736, 959, 968, 1055-1058, 1083, 1146, 1698`; `overview.py:130-137`;
`debug.py:57, 444`; `ui.py:265`); `ui.chart(fig)` (`ui.py:310-316`).

**Options.**
1. `_date_span(snapshots)` used by both and by `1056`; `counted(number, word, plural=None)`
   with docstring, used at `1337` and `472`; docstrings on `_metric_key`; rename loop
   variables; `fig` → `figure`. Cost: ~50 lines. Limit: `_sidebar_flag` for DP-04 is a
   helper used twice to save one line each; left as is, recorded so no third copy appears.
2. Also fold `_dates_or_file` into `_which_updates` by a `count: bool` flag. Cost: same;
   limit: a boolean parameter that changes what the function does (Readable 1).

**Choice.** Option 1 (Readable 1, 3; Names 1, 2). `state.py` is touched: the list of lines above
is agreed with Quentin before the branch is opened.

**Verification.** `pages.json` identical (the strings `"3 files"`, `"1 task"`,
`" · + baseline copy"` unchanged, checked by grep on the golden). `same_code.py` reports the
renamed loop variables as changed bodies: list them in the PR; the mutant test is the golden.

**Findings.** DF-05, DF-06, DP-04, RD-07, RD-08, RD-19 (state part: `1115-1116`,
`1759-1760`). Merged, unvoted: DP-05, RD-13 (DF-05), DP-10 (DF-06; `analysis.explain.noun`,
`explain.py:50-52`, stays the vocabulary owner, `counted` is for the sidebar's three words only).

### P4a — `viz/gantt.py` and `viz/charts.py` helpers and names (effort S, executor: mechanical executor; move, byte-identical)

**Problem.** Scalar/vector twins `_iso`/`_iso_column`, `_number`/`_number_column`
(`gantt.py:73-78, 111-118`) with trailing comments instead of docstrings; one-letter names
`t`, `n`, `cmp`, `tf`, `cat`, `p`, `s`, `k`, `r`, `d` (`gantt.py:41-47, 75-108, 121-146,
164-170, 185-190, 221-234`); `"%Y-%m-%d"` hand-written at `charts.py:493, 580`; `build_scurve`
(`charts.py:128-207`, three near-identical `go.Scatter` blocks at `155-184`) and `build_mta`
(`280-360`, groupby body `323-355`) inline their trace blocks. Voters' correction (RD-18): the
auditor had the two ranges swapped, and `fitness.json` gives `viz/charts.py` cognitive 10, not
12-14: this is the 60-line guide, not complexity.

**Options.**
1. Make the column forms map over `_iso_text` / `_rounded_number` (single implementation, unless
   the one-pass comment at `gantt.py:120` is load-bearing: then share the format constant only);
   rename on touch; one `DAY = "%Y-%m-%d"` in `charts.py`; extract `_mta_trace` and
   `_series_trace`. Cost: ~120 lines. Limit: none on output; the Gantt rows JSON and every figure
   JSON must be byte-identical.
2. Rename only. Cost: smaller; limit: DF-10, RD-18 stay.

**Choice.** Option 1 (Names 1, 2, 3; Readable 3). Figure and Gantt JSON digest identical before and
after. The `ROW_PX` token (AR-10) is **not** in this package: it turns `gantt.css`/`gantt.js` into
templates, a rendering change (P4b).

**Verification.** Digest script (to write beside the package): build every figure of `viz/charts.py` and
`gantt_data()` on the demo series from the package base and from the branch, compare
`figure.to_json()` and the Gantt rows JSON byte for byte; plant one defect
(`digits` off by one in `_rounded_number`) and see it fail.
`uv run pytest tests/test_app.py -q -k gantt`; `uv run pytest tests/test_viz.py -q`.
`fitness.py --check`: `viz/gantt.py` MI not lower.

**Findings.** DF-10, RD-06, VB-18, RD-19 (viz part), RD-18 (`charts.py:128-207, 155-184,
280-360, 323-355`, corrected), DF-12 viz share (`charts.py:493, 580`). Merged, unvoted: DP-11.

### P4b — One row-size constant for the Gantt (effort S, executor: senior; behaviour)

**Problem.** `ROW_PX = 26` (`viz/gantt.py:36`), `const ROW = 26` (`gantt.js:9`), `26px` in
`gantt.css:35, 39-40, 46`, and `GRID_W = 420` (`gantt.js:10`) written into `--grid-w` (`17`) that
`gantt.css` reads (`34, 43`); `CHROME_PX = 96` (`gantt.py:37`) is a sum by comment only. Nothing
checks that the files agree (AR-10, GX-02); `fitted_height` (`gantt.py:203-206`) and the browser
agree by coincidence.

**Options.**
1. `gantt_assets()` (`gantt.py:253-260`) substitutes `--row-px` in the CSS and `ROW_PX` in the JS
   from the Python constant. Cost: ~15 lines; limit: the assets become templates, a wrong token
   breaks the grid, so an AppTest must read the rendered component's data and a test must render
   the substituted text.
2. The script writes `--row` from `D.rowPx` sent in the payload, the CSS reads `var(--row)`. Cost:
   4 CSS edits, 2 JS lines, one key in `gantt_data` (`gantt.py:237-249`); limit: Python still owns
   the number, the JS constant goes, the CSS literal goes; `CHROME_PX` is not covered.
3. A test that greps the three files for the same number. Cost: 6 lines; no runtime change;
   limit: the duplication stays.

**Choice.** Waits for the maintainer. Option 2 is the one the `B` review suggests (no template, the
payload already carries `height`); option 3 is the floor if neither runtime change is wanted.
Source: skill "one place per concept"; CONTRIBUTING "constants scattered in modules".

**Verification.** Failing-before test: `tests/test_viz.py` asserts that the number in `gantt_data`
(or the substituted asset) equals `ROW_PX` and that `gantt.css`/`gantt.js` hold no `26` literal:
fails on the current tree. Then `uv run pytest tests/test_viz.py tests/test_app.py -q -k gantt`;
a screenshot before/after on the demo series (CONTRIBUTING Readable 6) in the PR; the
`test_gantt_height_follows_the_rows_drawn_up_to_the_cap` fixture (`tests/test_viz.py:456`)
unchanged.

**Findings.** AR-10, GX-02.

### P5 — Debug page and `diagnostic.py` duplicates (effort M, executor: mechanical executor; move, byte-identical)

**Problem.** `recalculation_table` and `assignments_table` share a 15-line pivot
(`diagnostic.py:309-330, 333-354`); nested `number`/`date` closures in
`assignment_dates_table` (`692-700`) beside `_numbers_of` (`639-641`); two zip-tag builders on
the Debug page, one nested in an expander body (`debug.py:389-391, 427-429`), with the
`(source, data_date)` identity pair repeated in `state._metric_key` (`1759-1760`).

**Options.**
1. `_differences_wide(comparison, key, fields)` returning `out`; module-level
   `_column_or(frame, column, convert, fill)` replacing the two closures (contracts differ,
   `dropna` vs `fillna(0.0)`, so `_numbers_of` stays); `snapshot_identity(snapshot)` in
   `state.py` (with Quentin); one module-level `zip_tag(anonymous, *extra)` in `debug.py`. Cost:
   ~120 lines.
2. Leave the closures (one voter rates them a different contract) and do the pivot only.
   Cost: smaller; limit: Readable 2 (nested defs in a 60-line function) remains.

**Choice.** Option 1 with the voter's correction: `_numbers_of` is not merged with `number`;
only the "column present or typed empty" guard becomes one function with explicit `fill`.

**Verification.** `uv run pytest tests/test_app.py -q -k debug`; Debug tables on the demo
series: `diagnostic_frames` output frames compared `pd.testing.assert_frame_equal` against
the package base (script to write beside the package), one planted defect (swap `stored`/`computed` in the
pivot) fails it. `duplication.py --threshold 0.8` diff: the 0.87 and 0.85/0.84 pairs gone.

**Findings.** DF-08, DF-09 (`692-700`, corrected), DF-07 (`debug.py:389-391, 427-429`,
`state.py:1759-1760`). Merged, unvoted: DP-06 (DF-07), DP-12 (DF-08), RD-14 (DF-09).

### P6a — Split `state.py` by concern: the move (effort L, executor: senior, with Quentin; move, byte-identical)

**Problem.** `state.py` is 2101 lines, MI 0 (rank C, the only one in the front), docstring
"Data loading shared by every page" (`state.py:1`) while holding the parse cache (`72-128`),
the lexicon (`135-191`), `LoadJob` (`208-257`), the Files window (`258-636`), baseline
resolution (`770-1570`), `memo`/`ScoreJob` (`1688-1835`), anonymiser and downloads
(`1836-2101`). Session keys for the Gantt and Audit pages are spelled as literals in three
modules (`gantt.py:30-39`, `state.py:1653`, `health.py:207-224`, `audit.py:152, 177`).

**Options.**
1. Pure move in one PR: `app/loading.py` (`72-128`, `208-257`, `554-636`),
   `app/files_window.py` (`258-552`), `app/baseline_choice.py` (`770-1570`),
   `app/cache.py` (`1688-1835`), `app/downloads.py` (`1836-2101`), `app/keys.py` (session key
   constants); `state.py` keeps the session keys and re-exports every public name for one release
   so no view changes. Cost: ~2000 lines moved, 0 rewritten.
2. Several PRs, one module each. Cost: five PRs, each under 400 lines; limit: five releases of
   re-exports and five `same_code.py` runs where one proves the same thing.

**Choice.** Option 1, **above the 400-line rule by design**, acceptable only under this review
method, written in the PR template: `scripts/same_code.py <base>` is the whole review (every
definition reported as a move, none as a change), the reviewer reads the module boundaries and
the re-export list, not the bodies; `tests/test_architecture.py` passes with the new modules
inside `app` (LAYERS unchanged); `pages.json` identical. **`state.py` is changed only with the
maintainer (Quentin); nothing is coded before his agreement on this Problem / Options / Choice.**
Which module owns `memo` vs `_parse` is decided here with him, with the backlog item DP-08 in
view: both go to `app/cache.py` so P7b can unify them without crossing a module.

**Verification.** `uv run python scripts/same_code.py <base>` prints no changed definition;
`uv run pytest tests/test_architecture.py tests/test_app.py tests/test_page_golden.py -q`;
`pages.json` identical; `fitness.py --check` passes (the baseline is regenerated by the maintainer
after merge, `state.py` having shrunk).

**Findings.** RD-09, RD-16, LD-08 (keys module).

### P6b — Split the four long functions of `state.py`, and the same pattern elsewhere (effort M, executor: senior, with Quentin; rewrite, output byte-identical)

**Problem.** `sidebar_loader` is the only C901 hit in the front (`state.py:691-767`, ruff 12 > 10,
radon 17; voters: one hit in a composer is medium, not high), `_window` nests five levels
(`525-551`), `_folder_boxes` does four jobs (`306-353`), `_baseline_fields` is 71 lines
(`1377-1447`); `reading.py:83-114` (`_read_on_workers`, RD-04) and
`health.show_report_comparison` (`health.py:351-403`, 53 lines, depth 4: `with` > `if upload` >
`try` > `if missing`, RD-15) show the same pattern.

**Options.**
1. `sidebar_loader` → `load_series()` (lines 695-731, the decision, with `_start_or_read` and
   `_collect_finished_job`) and `draw_sidebar(store)` (733-767), the split of U1 (section 6);
   `_window` → `_draw_sections` and `_on_done`; `_folder_boxes` → `_doubles_by_date` and
   `_select_all_line`; `_baseline_fields` → `_reset_stale_drafts` and `_baseline_file_fields`;
   `_read_on_workers` extracted in `reading.py`; `_uploaded_counts(upload, got) ->
   pd.DataFrame | None` for `health.py:362-373`. Cost: ~220 rewritten lines.
2. Only the C901 hit. Cost: 60 lines; limit: RD-02, RD-03, RD-04, RD-15 stay.

**Choice.** Option 1 (skill Readable 1, 2), **after** the maintainer settles U1 (section 6): the
`sidebar_loader` split is U1's subject, and the invariant "placeholder first, read second, label
third" (`state.py:693, 695, 733-745`) is the contract the split keeps.

**Verification.** `pages.json` identical; `uvx ruff check src --select C901` prints no hit in
`app/`; `fitness.py --check` shows `app/state.py` and `app/views/health.py` MI not lower; the
U1 unit test (`load_series()` with an injected session dict, section 6) added here;
`tests/test_app_robustness.py:97-137` green (files gone between listing and read).

**Findings.** RD-01, RD-02, RD-03, RD-04, RD-15.

### P7 — Caching: no baseline rebuilt on rerun (effort M, executor: senior, with Quentin; same results)

**Problem.** `metric_result` evaluates `AnalysisContext(snapshot, store, baseline_for(snapshot))`
before `memo` checks its cache (`state.py:1749-1756`, cache check `1731-1735`):
20 `baseline_for` per Health rerun, each building `Baseline.planned`/relinked uncached
(`1556-1567`). The sidebar rebuilds the loaded-update Baseline every rerun (`817`, `1292-1293`);
the context banner and the page body each call `baseline_for` (`state.py:1142-1150`,
`gantt.py:51`, `earned_value.py:461, 504-530`; voters measured 2 per rerun on Gantt, Audit, PPC).
`standards()` re-reads every TOML per rerun (`1570-1576`, `standards.py:218-249`; voters: ~5 ms,
low). The baseline folder is listed three times per rerun and the file read from disk
(`837-843, 869-872, 1225-1232, 1271, 920`). `memo` hashes an uploaded baseline on every call in
`BL_EACH` mode (`1700, 1908-1911, 122-125`). Debug `guid_match_table` (`debug.py:51`) and PPC
`progress_delta`/`rollup_delta` (`ppc.py:275-278`) bypass `memo`. The Gantt vocabulary memo is
keyed on `len(taught)` (`gantt.py:104-116`). The background `LoadJob` reparses files already in
the session cache (`state.py:230-235`, `reading.py:97, 114` vs `state.py:117`; voters: a one-off
per series change, parallel on the pool, medium not high).

**Options.**
1. Minimal, same results, session-only: `memo` takes the context lazily (callable built in the
   miss branch); `baseline_for` memoised in session on `(signature, projects, choice, basis,
   link)`, reusing `st.session_state['baseline']` as `_file_baselines` does (`1543-1552`);
   folder listed once per run and passed down; digest stored next to the uploaded bytes
   (`421-423`); `memo` around `guid_match_table` and `progress_delta`; vocabulary key
   `tuple(taught)`; `LoadJob` receives only the items missing from `_parsed`. Cost: ~230 lines
   across `cache.py`, `baseline_choice.py`, `loading.py`, `debug.py`, `ppc.py`, `gantt.py`.
   Limit: `standards()` still reads the TOML per rerun (5 ms).
2. Also `functools.cache` on `builtin_standards`. Cost: 2 lines; limit: the first process-wide
   cache of the front (SE-06); the uploaded standards merge stays per session, so nothing
   user-specific is shared, but the invariant "every cache is session state" is given up.
3. Also unify `_parse` on `memo` and give the dict caches one LRU helper (DP-08, LD-10, A1 R5).
   Cost: +120 lines; limit: `memo` keys are prefixed by `data_identity()` which reads the store,
   so parse keys need an `identity=False` switch, a behaviour decision.

**Choice.** Option 1 in P7 (same results, session-only: no design decision taken). Options 2 and 3
are P7b, where the maintainer decides. LD-09 (superseded `ScoreJob` thread) also P7b, with a
bounded `join(timeout=0)` poll. `tests/test_app_cache.py` gains the counters of LD-13.

**Verification.** `uv run pytest tests/test_app_cache.py tests/test_app_background.py
tests/test_app_parity.py -q`: new assertions "0 `Baseline.from_snapshot`, 0
`Baseline.planned`, 0 `renumbered` on a rerun with nothing changed" on Health, Debug,
Gantt, Overview. `pages.json` and `standards.json` identical.
`docs/refactor-front/time_pages.py <folder>`: Health rerun under 0.10 s on the demo series
(was 0.22 to 0.24 s; 0.50 s with `BL_PLANNED + guid_link`), reported in the PR, not asserted.

**Findings.** LD-01, LD-02, LD-03, LD-05, LD-06, LD-07 (known family), LD-11, LD-12, LD-13
(script kept).

### P7b — Cache policy decisions (effort S, executor: senior, with Quentin; behaviour)

**Problem.** Three per-session caching policies: `_parse` (`state.py:72-83`, dict cleared past 64:
a 65-file series re-parses the whole series on the next rerun, `79-80`), `memo` (`1717-1741`, LRU
of 128 keyed on `data_identity`), `hold`/`held` (`2015-2021`, one slot). `standards()` re-reads the
TOML per rerun (LD-04). A superseded `ScoreJob` thread is never joined (LD-09).

**Options.**
1. `_lru(name, size)` under `_parse` (key `("parse", name, digest, project_id)`, no identity
   prefix) and `memo`; `hold`/`held` documented beside as "one value per slot". Cost: ~25 lines,
   −10; limit: `memo(…, keep=False)` and the identity prefix stay.
2. Leave `_parse`, document the two policies (backlog item). Cost: 0; limit: the 65th file empties
   the cache.
3. `_parse` under `st.cache_data`. Cost: 2 lines; limit: process-wide memory of a file's content,
   against `state.py:73-75` ("never in a process-wide cache").
For `builtin_standards`: (a) `functools.cache`, process-wide, non-session data (SE-06 note);
(b) session memo; (c) leave (5 ms).

**Choice.** Waits for the maintainer: option 1 for the LRU, and (a), (b) or (c) for the standards.
Source: `docs/backlog.md` Structure "One cache policy (`_parse` and `memo`)".

**Verification.** Failing-before test: load 65 small `xerkit` files and count `load_snapshot`
calls across a rerun (expected 65, fails today with 130); `standards()` TOML reads per process
asserted per the choice; `uv run pytest tests/test_app_cache.py tests/test_app_background.py -q`.

**Findings.** DP-08, LD-10 (known, backlog), LD-04, LD-09; A1 redesign R5.

### P8 — Downloads and table column builders (effort M, executor: mechanical executor; rewrite, output byte-identical)

**Problem.** The "Build" button → `fetch(prepare=True)` → `hold` → `held` → `show_download`
sequence is written by hand four times (`debug.py:393-414, 432-455, 486-492`,
`export.py:72-110`, `health.py:152-177`) while `state.download` (`2048-2075`) owns the
other policy; `health.py:432-438` is the only direct `st.download_button` outside `state.py`
(voters: `show_download` takes a `Fetched`, the template is plain text, so the bypass was the
only option; real as a duplicated button style). Voters on DP-07: ~15 lines per site, refusal
handling already in `show_download` (`state.py:2035-2037`), impact medium.
`NumberColumn(name, format="%d")` is hand-written at `health.py:110, 346, 396-399`,
`changelog.py:53`, `sets.py:57, 91` (identical comprehension twice), `export.py:38-39`,
`milestones.py:93-94` (voters: 6 files, 9 `format="%d"` literals, not "9 views"), while
`ui._column_for` (`ui.py:501-515`) builds a column from a kind.

**Options.**
1. `downloads.built_download(slot, tag, build_label, label, file_name, mime, plain,
   anonymised, sources, *, key, spinner=None)` owning the five steps; `downloads.download_text(label,
   text, name)` for the template; `ui.count_columns(*names)` / `ui.number_columns(kind, *names)`
   from the existing tables; `sets.py:57/91` share one constant. Cost: ~180 lines; limit:
   the export variant has a spinner and `plain=None`, health two slots on one tag: the
   helper takes `spinner: str | None` and is called twice for health.
2. Only the column builders. Cost: 60 lines; limit: DP-07 stays.

**Choice.** Option 1 ("Where a change goes": one place owns the button style and refusal
handling; Readable 5). This is A1 redesign R2 (Download contract); P15 adds the `help` parameter
to it later.

**Verification.** `uv run pytest tests/test_downloads.py tests/test_app.py -q`;
`pages.json` identical (button labels, table columns and formats unchanged: the golden lists
widget labels and table columns). `grep -rn "st.download_button" src/xerscope/app` returns
one line; `grep -rn "prepare=True" src/xerscope/app` returns the helper and `state.download`
only (today 6 hits).

**Findings.** DP-07, DF-11 (`health.py:432-438`, `state.py:2035-2046`, corrected), DF-13
(corrected list), VB-11 format-only overrides part.

### P9a — Visual consistency fixes (effort M, executor: senior; behaviour, `pages.json` regenerated once)

**Problem.** User-visible inconsistencies, each a behaviour change: the navigation title
"Task history (to be removed)" (`streamlit_app.py:35`); the same unit written `d`,
`wd` or none (`charts.py:423, 431`, `forensics.py:43, 99-102`, `earned_value.py:181`; voters:
`charts.py:197` has its unit on the axis, dropped); the same situation is `st.info` on one page
and `st.warning`/`st.error` on another (`health.py:482-487`, `earned_value.py:471-473`,
`forensics.py:185-187`, `debug.py:64-66`, `changelog.py:127-129`, `audit.py:167-169`);
`ppc._pct` writes `n/a` (`ppc.py:72-73`); h4 formula under h5 group under h3 section
(`health.py:289, 310`, `audit.py:109`, `ui.py:458-461`); the "Working days gained (+) or lost
(−)" sentence copied at `overview.py:40-52` (twice), `changelog.py:28-31`, `forensics.py:84-87`,
`task_panel.py:237-243` with two `wd` formats (`{:+g}` vs `{:+.1f}`; voters: three different
figures, shared wording only); column labels disagreeing with `ui.COLUMNS` (`ppc.py:84` "Week
ending" vs `ui.py:208` "Status date"; `forensics.py:26-34, 122, 152` renames before `ui.table`;
voters: the CSV at `forensics.py:154` downloads the unrenamed frame, the "CSV carries display
labels" claim is false). KPI dates `%d %b %Y` (`ui.py:268-270`) vs ISO in tables
(`ui.py:501-507`; voters: a deliberate pair documented in the docstring; `first_forecast`,
`latest_forecast` absent from `COLUMNS`, so `milestones.py:91-92` overrides exist for the label).

**Options.**
1. One PR per visible change, each regenerating `pages.json` in its own reviewed commit.
   Cost: eight small PRs; limit: review traffic.
2. One PR, one regenerated golden, the PR text listing every changed line of `pages.json`
   under a heading per finding. Cost: ~200 lines; limit: a reviewer must read the golden
   diff as a whole.

**Choice.** Option 2 with the golden diff grouped per finding in the PR description
(CONTRIBUTING Readable 7). Decisions proposed to the maintainer: remove the Activity page
(`views/activity.py`, 24 lines, and `streamlit_app.py:35`; the Gantt already opens the same panel,
`gantt.py:378`, and Milestones reuse `latest_names`/`code_label`, so nothing else goes: UF-03) or
retitle it; unit vocabulary `wd` for `_d` columns, `cal. d` for calendar days, `h` for hours
(Names 7); severity rule written in `ui.py` (`info` = a choice still to make or a page not
applicable, `warning` = a result to read with care, `error` = nothing can be shown) with
`ui.need()`/`ui.caveat()`; formula drawn as styled text, group as `####`; one sentence constant and
one `{:+.1f} wd` format for the finish KPIs (the viz `format_shift`, `charts.py:461-463`, aligned,
layer rule kept); `first_forecast`, `latest_forecast`, `slip_wd`, `step` added to `ui.COLUMNS`,
page renames removed, `ppc` "Week ending" kept as a deliberate weekly label and documented beside
`COLUMNS`; VB-01: document in `ui.py` why KPIs use `%d %b %Y` and tables ISO (voters rate the mix
low, P6 users expect ISO in tables). **The Audit default standard and the session-key merge are
not here (P9b).**

**What changes for the user.** Navigation label (or page gone); unit suffixes on four labels; six
message boxes change colour or icon; `n/a` → `–` on PPC; heading outline h1 > h3 > h4
(screen-reader order); one wording and one decimal format for the finish-shift help; forensics
filter popover shows field labels from `COLUMNS`. No number changes: `standards.json` identical,
`test_app_parity.py` green.

**Verification.** `uv run pytest tests/test_app_parity.py tests/test_characterization.py -q`
identical; `XERSCOPE_UPDATE_GOLDEN=1 uv run pytest tests/test_page_golden.py`, diff
reviewed and listed per finding, then rerun without the variable; AppTest count of `#### `
markdowns on Health drops from 18 to 3 (one per group); `tests/test_app.py` green with the page
list of `tests/test_page_golden.py:33` updated if the Activity page goes.

**Findings.** VB-13 / UF-03, VB-02 (corrected list), VB-06, DF-04 (`n/a`), VB-16, DP-13
(corrected), VB-11 (labels; corrected), DP-14 (corrected), VB-01 (decision only).

### P9b — Audit opens on a default standard, one session key (effort S, executor: senior, with Quentin; behaviour)

**Problem.** Audit opens empty with no default standard (`audit.py:151-153`
`st.segmented_control("Standard", …, key="audit_std")`, `167-169`) while Health defaults to P6
(`health.py:463-475`); `health_std` and `audit_std` are two session keys for one choice. This is a
loading behaviour, not a visual one (first review).

**Options.**
1. Audit defaults to `P6` and both pages share one key in `keys.py` (P6a). Cost: ~15 lines;
   limit: a user who picked DCMA on Health sees DCMA on Audit, a coupling to say in the help text
   (P14: "The standard whose checks can be audited").
2. Audit defaults to `P6`, keys stay separate. Cost: 3 lines; limit: two keys for one choice.
3. Leave empty, add a caption "pick a standard". Cost: 1 line; limit: VB-14 stays.

**Choice.** Waits for the maintainer. Source: CONTRIBUTING "one place per P6 concept".

**Verification.** Failing-before AppTest: a direct visit to Audit renders result tables (fails
today, the page stops at the picker); `XERSCOPE_UPDATE_GOLDEN=1` on `audit` only, diff listed;
`uv run pytest tests/test_app.py -q -k audit`.

**Findings.** VB-14.

### P10 — Chart house style and layout tokens (effort S, executor: mechanical executor; behaviour, visual)

**Problem.** Right margin 110 px reserved on every chart (`charts.py:51`) and overridden
back to 20 by hand on three (`454, 594, 625`), kept uselessly on `build_metric_trend`
(`543-569`); three trend charts without an x-axis title (`128-207, 242-274, 543-569`) while
four title it "Status date" (`405, 430, 451, 622`); `build_activity_float` shows a one-entry
legend (`431`) while `452, 567` pass `legend=False`; status colour `#a15c00` copied into
`style.css:297` outside the `--s1..--s6` tokens `apply_style` writes (`ui.py:118-124`,
`charts.py:25`; on the dark theme the bar keeps the light theme's amber, contrast unverified:
CS-03/AR-09); `ui.BADGE` adds a sixth colour `muted` outside `STATUS` (`ui.py:51`); orphan MTA
comment (`style.css:3, 105-107`, CS-01) with the square now done in Plotly (`charts.py:356-359`);
table `max_height` in six ad hoc sizes (`ui.py:675-680` default 560; 260/420/480/640/700 at the
sites listed in VB-10, corrected); fixed Gantt grid 420 px with no narrow-screen rule
(`gantt.js:10, 17, 108`, `gantt.css:22, 32-37, 43-46`; voters: a P6 Gantt is a desktop tool, the
hidden bars are reasoned, not rendered: impact low); `@media (max-width: 640px)` written three
times in `style.css` (`64, 248, 278`, CS-04); two identical button blocks (`style.css:229-246`,
`257-269`, CS-02).

**Options.**
1. `_with_house_style(figure, height, unit, *, x_title="Status date", end_labels=False,
   legend=None)` deciding margin and legend (`legend = len(figure.data) > 1` when None);
   `apply_style` writes `--status-*` tokens from `charts.STATUS` as `light-dark(...)` like
   `--accent`; `style.css:297` uses `var(--status-warning)`; `muted` into `charts.STATUS`; delete
   the orphan comment; merge the three `@media` blocks and the two button blocks; `ui.TABLE_SHORT
   = 420`, `ui.TABLE_LONG = 640` replacing the literals; Gantt `--grid-w: min(420px, 55vw)` and a
   `@media (max-width: 640px)` rule collapsing `%`/`Float`, header labels "% complete" and
   "Float (wd)". Cost: ~170 lines. Limit: visible on every chart (margins, axis titles, legend)
   and in the Gantt header: a visual change, listed as such.
2. Charts only, no CSS. Cost: 80 lines; limit: VB-09, CS-02, CS-03, CS-04 stay.

**Choice.** Option 1. The MTA height cap (VB-08, 760 → fits container) is left out: the phone
blank band is reasoned, not rendered; the senior checks it in a browser first.

**What changes for the user.** Narrower right margin on `build_metric_trend` and `build_ppc`
(the PPC target annotation anchors inside the plot); x-axis title "Status date" on three
charts; no legend on single-series float chart; the Ask warning bar follows the theme; table
heights 420/640; Gantt usable below 640 px and header "Float (wd)".

**Verification.** Figure JSON digest script from P4a run per chart: only `layout.margin.r`,
`layout.xaxis.title`, `layout.showlegend` differ, listed in the PR; `pages.json`
regenerated (trace types unchanged, table rows unchanged); AppTest Gantt tests green;
contrast of `--status-*` on both theme backgrounds ≥ 4.5:1 computed and stated (WCAG 2.2 AA).

**Findings.** VB-17, VB-07, VB-05 / AR-09 / CS-03, VB-08 (comment part) / CS-01, VB-10
(corrected), VB-09, CS-02, CS-04.

### P11a — Layer rules pinned and computations out of pages (effort M, executor: senior; moves, byte-identical, one PR per move)

**Problem.** `tests/test_architecture.py` checks imports only (`8-31, 51-63`); nothing pins
"no computation in a page", "no plotly in `app/`", "no streamlit in `viz/`". Pages still
compute: `earned_value.py:533-534` two merges; `milestones.py:26-35` a population;
`overview.py:24-25, 54, 59` two deltas and `score_section` cognitive 21 (`79-97`; voters: the
complexity, not the arithmetic, is the debt); `earned_value.show_calculation` (`242-369`) holds
~95 lines of explanation rows in the page; `INDEX_ALERT`/`PPC_TARGET` live in `viz/charts.py:39-40`
and `0.95` is a literal in `glossary.py:27, 43`; PPC help text restates `KPI_FORMULAS`
(`ppc.py:98, 104-105, 111` vs `explain.py:381-389`; voters: a partial duplicate, the page keeps
the "n/a when nothing was due" caveat, `139-146` is the week's numbers, not a formula);
`app/diagnostic.py` (980 lines, MI 19.2) computes counts and is imported by `cli.py:439-479`,
special-cased in LAYERS (`test_architecture.py:21-30`); `diagnostic.py:840-980` holds a P6 CSV
export reader; its companion `app/expected_finish_forms.py` (78 lines, imported by
`diagnostic.py:35`, UF-02) moves with it.

**Options.**
1. One PR per move, each with its hand-made test: `evm_series_with_indices` in
   `analysis/evm.py`; `finish_milestones` in `analysis/populations.py`;
   `change_since_previous` (`analysis/evm.py:750`) reused by overview and `score_section`
   split per U1 (`scores_held` / `scores_polled` / `scores_on_button`, section 6);
   `EV_CALCULATION_ROWS` in `analysis/explain.py`; `Settings.index_alert`,
   `Settings.ppc_target_pct` in `config.py`, charts take them as parameters; glossary reads the
   threshold from the standard; PPC help keeps only the population caveat;
   `diagnostic.py` + `expected_finish_forms.py` → `analysis/diagnostic.py`, `840-980` →
   `analysis/p6_export.py`, LAYERS exception removed; then the three new asserts in
   `test_architecture.py`. Cost: eight PRs of 50-250 lines.
2. Pin the rules first (asserts with an allow-list of the current offenders), then shrink
   the list PR by PR. Cost: same total; limit: an allow-list in a test is a debt list that
   can rot.

**Choice.** Option 1, asserts last so each lands green (CONTRIBUTING "Where a change goes" rows;
architecture document "pages compose, compute nothing"). **No computed value moves in P11a**; the
`export._data_date` replacement, which does, is P11b.

**Verification.** Per move: `same_code.py` reports the moved definitions as moves;
`standards.json`, `pages.json` identical; one hand-made xerkit test per new analysis function;
`tests/test_architecture.py` passes with the exception removed and the three new asserts;
`fitness.py --check` green (`diagnostic` moves module, measure follows); `cli.py:439-479` import
path updated, `uv run xerscope pv-compare --help` runs.

**Findings.** AR-01, AR-02, AR-03, AR-14 (corrected: `overview.py:79-97, 24-25, 54, 59`), RD-12,
AR-06, AR-07, AR-08 (corrected), AR-13, RD-11, AR-11 (`ui.fold`/`ui.search_mask` wrappers
deleted), AR-12 (`unknown_acronyms` → test helper; `anonymizers_built` left, intent unverified),
UF-02.

### P11b — The export's data date comes from the model (effort S, executor: senior; behaviour, computed value)

**Problem.** `export._data_date(raw)` (`app/views/export.py:63-69`) reads `last_recalc_date` only,
through `pd.to_datetime(errors="coerce")`; the model's `_data_date` (`src/xerscope/xer/model.py:1496-1503`)
falls back to `plan_start_date` and names the column it used; `read_header` exists at
`model.py:1522`. One P6 concept, two rules (CONTRIBUTING "What a P6 column means → `xer/model.py`").
Voters: medium, not high: it only dates the separate baseline file inside the anonymised extract
(`export.py:83`) when its `PROJECT.last_recalc_date` is blank.

**Options.**
1. `read_header(raw).data_date` in `export.py`. Cost: 5 lines; limit: the data date of a
   baseline with a blank `last_recalc_date` becomes `plan_start_date` instead of `None`: a
   computed value moves (CONTRIBUTING rule 3).
2. Keep `export._data_date`, add the same fallback by hand. Cost: 3 lines; limit: the second
   copy of the rule stays.
3. Leave as is, document the difference. Cost: 0; limit: AR-04 stays.

**Choice.** Waits for the maintainer; option 1 is the one the rule points to. Source:
`docs/architecture.md` §2 (`xer/model.py`: what P6 means).

**Verification.** Failing-before test: an `xerkit` baseline with `last_recalc_date` blank and
`plan_start_date` set, run through the anonymised extract, asserts the baseline file's data date
equals `plan_start_date` (fails today: `None`); `uv run pytest tests/test_export.py
tests/test_anonymize.py tests/test_app.py -q -k export` (test file names to be confirmed on the
branch); the anonymised extract on the demo series byte-identical (every demo baseline has
`last_recalc_date`); `standards.json`, `pages.json` identical.

**Findings.** AR-04 (corrected: `export.py:63-69, 83`, `xer/model.py:1496-1503`).

### P12a — `ui.py` split: theme and table filters (effort M, executor: mechanical executor; move, byte-identical)

**Problem.** `ui.py` (764 lines) mixes CSS injection (`66-124`; `125-129` are `ROW_HEIGHT`,
`HEADER_HEIGHT` and the start of `COLUMNS`, not theme), formatting (`262-308`), KPI
cards (`357-432`), a filter mini-language with regexes (`533-633`: `FILTER_HINT` at `533`,
`filter_rows` ending at `633`) and tables (`675-713`); `filter_rows` nests for > try >
if/elif/else (`615-628`, depth 3; voters: fitness cognitive 10, not 14, a style nit),
`_number_test` has no docstring (`571`) while `_date_test` has one (`595-596`).

**Options.**
1. Move `533-633` to `app/table_filters.py` (pure, tested without Streamlit) and `66-124`
   to `app/theme.py`; `_mask(kind, text, values)` dispatch dict; docstring; `ui` re-exports the
   names for one release. Cost: ~160 lines moved, 20 rewritten. The formatting block
   (`262-308`) moves to `app/format.py` in the same PR only if the maintainer wants R3's module
   (A1); otherwise it stays in `ui.py`.
2. Leave `ui.py` whole, only fix `filter_rows`. Cost: 30 lines; limit: RD-10 stays.

**Choice.** Option 1 (skill standard 1; Readable 2, 3). Runs after P8 and P9a so the
`COLUMNS` additions are already in. `tests/test_table_filters.py` **already exists** (135 lines:
operator, range and period cases at `45-118`): P12a moves its imports to the new module, it does
not write it. VB-15 (`blank_missing`) is **not** here (P12b).

**Verification.** `same_code.py`: moves only, plus `filter_rows`/`_mask` listed;
`uv run pytest tests/test_table_filters.py tests/test_app.py tests/test_page_golden.py -q`;
`pages.json` identical.

**Findings.** RD-10, RD-17 (corrected: `ui.py:571, 612-632`).

### P12b — One mechanism to hide a missing value in a table (effort S, executor: senior; behaviour)

**Problem.** Three mechanisms hide `None` in tables: `placeholder=MISSING` on `st.dataframe`
(`ui.py:704-705`), `blank_missing` on object/string columns (`ui.py:298-305`, called at `698`),
`numbers_as_text` (`283-295`, called at `gantt.py:402`, `earned_value.py:412`). Voters: whether
`placeholder` alone renders the dash for NaN in float and object columns on Streamlit 1.67 is
front-end behaviour, unverified headless; `numbers_as_text` also applies the kind's template and
right alignment, so it is **not** dead; `blank_missing` is likely redundant.

**Options.**
1. Delete `blank_missing` if a browser check (not AppTest) shows the dash on NaN in both column
   kinds with `placeholder` only. Cost: −10 lines, one frame copy fewer per render; limit: the
   proof is a screenshot, not a test.
2. Keep all three, document which does what in `ui.table`'s docstring. Cost: 5 lines.
3. Delete `blank_missing` and `numbers_as_text` both. Cost: −25 lines; limit: loses the kind
   template on the Gantt and EV tables, and numeric filters on text columns (voters).

**Choice.** Waits for the maintainer after the browser check; option 3 is excluded by the voters.

**Verification.** Screenshot before/after of the Gantt table view and `ev_updates` with a missing
value; `pages.json` identical (the golden lists columns and row counts, not cell text);
`uv run pytest tests/test_app.py -q`.

**Findings.** VB-15 (corrected: `ui.py:283-305, 698, 704-705`, `gantt.py:401-403`,
`earned_value.py:411-413`).

### P13 — Readings: how to read each chart and table, sourced (effort L, executor: senior for the `Reading` contract and the coverage test, mechanical executor for the texts; behaviour, `pages.json` gains one popover per figure and listed table)

Decision of 19 November: these tooltips belong to this interface refactor.

**Problem.** The reading of a figure exists today as a page caption (`overview.py:120-124`,
`earned_value.py:390-393`, `milestones.py:80-83`, `forensics.py:116-120, 145-149`), as a builder
docstring (`charts.py:128-144, 280-299, 483-491`), or nowhere (`build_activity_dates`,
`build_activity_float`, `build_finish_trend`, `build_metric_trend`, the Gantt beyond its legend).
Thresholds are drawn (`charts.py:39-40`, `266-271`, `524-537`) but not said with their source.
The rule "a metric's explanation lives in `analysis/explain.py`, never page text" (CONTRIBUTING
"Where a change goes") is not met for figures. `grep -n "^def build_" viz/charts.py` finds 10
builders (`128, 242, 280, 402, 421, 434, 483, 543, 572, 598`), plus the Gantt.

**Options.**
1. `analysis/explain.py`: a frozen `@dataclass Reading(how, meaning, conclude, source)` and
   `READINGS: dict[str, Reading]` keyed by figure name (`"scurve"`, `"index_trend"`, `"mta"`,
   `"activity_dates"`, `"activity_float"`, `"finish_trend"`, `"ppc"`, `"metric_trend"`,
   `"half_step"`, `"slip_trend"`, `"gantt"`) and by table key (`"health_results"`, …). Each
   `build_*` sets `figure.update_layout(meta={"reading": "<key>"})` (viz imports nothing from
   `analysis/`, `docs/architecture.md:180`). `ui.chart(fig, reading=None)` reads
   `reading or READINGS[fig.layout.meta["reading"]]` and draws, beside the section title, a
   `st.popover("How to read", icon=":material/help:")` with four short paragraphs; the Gantt page
   draws the same popover beside its toolbar from `READINGS["gantt"]`; `ui.table(..., reading=…)`
   draws it above the frame. Parameter thresholds (PPC target, metric target) are formatted into
   `conclude` by the page (`Reading.conclude.format(target=…)`), the text staying in `explain.py`.
   Cost: ~120 lines of text in `explain.py` (appendix E), ~20 lines in `ui.py`, one line per
   builder, one argument per table call. Limit: one more element per chart in `pages.json`
   (regenerated once, reviewed).
2. Put the reading in the figure (`layout.annotations` or a subtitle). Cost: small. Limit: cut on
   a phone, read by no screen reader; the rule puts explanations in `explain.py`.
3. One "How to read" expander per page listing every figure. Cost: small. Limit: the reading sits
   far from the chart.

**Choice.** Option 1 (CONTRIBUTING "A metric's explanation → `analysis/explain.py`"; the same
shape as `KPI_FORMULAS` + `_formulas_popover`, `ui.py:388-397`; `SPI_WINDOW_READING`,
`explain.py:296`, already is a reading kept there). The `source` field holds names only;
`ui.without_addresses` (`ui.py:328`) is applied as `show_method` does (`health.py:249-251`).
The senior writes the dataclass, `ui.chart`/`ui.table` slots and the coverage test; the mechanical executor
dev copies the texts of appendix E into `READINGS`, word for word.

**Coverage test** (`tests/test_readings.py`, new; in the spirit of `tests/test_glossary.py:44-51`,
which walks every page's `metric` elements and checks their help). Three checks: *static*, every
`def build_` in `viz/charts.py` (by `ast`) sets a `meta` reading key and every key is in
`explain.READINGS`; `READINGS["gantt"]` exists; no `Reading.source` contains `http` or `www.`;
every source names one of the strings already in the repository (`standards/*.toml` `source`
prefixes with their addresses stripped, `explain.P6 / EVMS / LPS / LIPKE / XS`, "AACE RP 29R-03",
"DCMA 14-Point", "Oracle P6 EPPM 26 help, Schedule Project Log"). *Rendered*, with `AppTest` on the
demo series (`PAGES`, `tests/test_page_golden.py:33`): per page, the count of `plotly_chart`
elements equals the count of popovers labelled "How to read", and each `dataframe` whose key is in
`READINGS` has one. *Mutation*: `ui.chart` with `reading=None` and a figure without `meta` raises
under `XERSCOPE_STRICT_READINGS=1` (set by `conftest`); the test plants a builder without `meta`
and sees the static check fail.

**What changes for the user.** One "How to read" popover beside every chart and every metric
table, four paragraphs: how to read, what it means, what to conclude, source.

**Verification.** `uv run pytest tests/test_readings.py tests/test_explain.py tests/test_app.py
tests/test_page_golden.py -q`: `pages.json` changes by exactly one `popover: How to read` line per
figure and listed table, regenerated with `XERSCOPE_UPDATE_GOLDEN=1` in a separate reviewed
commit; `standards.json` unchanged; `fitness.py --check` passes; `tests/test_docstrings.py` on the
new dataclass. Data privacy: readings are static project text; no schedule value enters a
`Reading` except the formatted threshold parameters.

**Findings.** A3 (no finding id; 11 figures, 30 table readings, appendix E).

### P14 — Widget help texts (effort M, executor: mechanical executor for the texts, senior for the wrapper slots; visible, `pages.json` unchanged)

**Problem.** 70 widget call sites have no `help=` (`docs/refactor-front/widgets-without-help.txt`;
every one opened with its context). `_column_for` (`ui.py:501-515`) gives `help=spelled_out(label)`,
an acronym gloss only: 46 of the 130 `COLUMNS` get one, 84 get none.

**Options.**
1. Two sentences per widget (what it does, when to use it), copied from appendix F into each
   call; four wrappers carry the help once: `_filter_inputs` (`ui.py:668, 671`: the column's help
   from `COLUMNS` plus the operator hint of `FILTER_HINT`, `ui.py:533-537`),
   `_open_in_gantt_button` (`ui.py:723`), `show_download`/`csv_download` (`state.py:2024-2033`,
   a `help` parameter, one default text for the 25 download sites), `parameter_widget`
   (`audit.py:45-50`: `parameter_help(rule_name, name)` reading the rule's docstring or the notes
   `explain._population` writes, `explain.py:205-209`, fallback texts in appendix F). Column help
   is R4's `help` field (P15). Cost: ~70 one-line edits, ~20 lines in wrappers.
2. A `HELP: dict[key, str]` in `ui.py` looked up by widget key. Cost: same text, one table;
   limit: a key renamed silently loses its help; the text sits far from the widget.
3. Help only on the widgets whose label does not say what they do (~25). Cost: a third; limit:
   the coverage test cannot be written.

**Choice.** Option 1 (the text beside the widget, as `pages.json` lists the widget). Markdown is
accepted by Streamlit's `help`. Texts name sources, never link them; P6 field names are given
where the model gives one.

**What changes for the user.** A tooltip on every widget. `pages.json` does not list help
(`tests/test_page_golden.py:3-6`), so the golden is unchanged.

**Verification.** New AppTest in `tests/test_glossary.py` style: for every page, every widget
element (`selectbox`, `multiselect`, `button`, `toggle`, `checkbox`, `text_input`, `number_input`,
`file_uploader`, `radio`, `segmented_control`, `date_input`, `download_button`) has a non-empty
`help`, except a listed allowance; fails today on 70 sites. `uv run pytest tests/test_app.py
tests/test_page_golden.py tests/test_glossary.py -q`; `pages.json` identical.

**Findings.** A2 (no finding id; 70 sites, appendix F); SE-05a option (2) text.

### P15 — Front contracts: Panel, Download, Table (effort L, executor: senior; behaviour)

**Problem.** Three things are done in several ways. *Panel*: Health and Audit draw the same
explanation (P2 merges the copies); Overview cards (`overview.py:37-67`), Changelog
(`changelog.py:21-44`), Forensics (`forensics.py:77-111`), PPC (`ppc.py:91-133`), Earned value
(`earned_value.py:95-125`) carry help as page strings in the KPI tuple beside `KPI_FORMULAS`,
which `ui.kpis` opens in a "Formulas" popover (`ui.py:388-397`); the explanation of a figure can
exist in three places and P13's reading has no slot. *Download*: P8 owns the sequence; the
`help` of P14 must land in it once. *Table*: `ui.COLUMNS` (`ui.py:129-258`) owns label and kind;
views bypass it with hand-written `column_config` constructors (DF-13, P8 removes the counts),
label tables applied by `rename` (`forensics.py:26-34, 122, 152`, `ppc.py:84, 153`), and
`numbers_as_text`; each `ui.table` render can copy the frame up to four times (`ui.py:697, 304,
729, 287`) plus the view's `rename`. `ui.table` has no empty-state parameter (`ui.py:675-713`):
PPC guards `commitments` (`ppc.py:147-149`) but not `153, 194, 206`; Debug guards INT-01/03
(`debug.py:117-124`) but not `195-196, 208-209, 226-227` (voters' AppTest: 5 of 30 Debug frames
empty on the demo; the PPC and Forensics case is conditional, not shown on the demo) (VB-12).
Three selectboxes label a task "code · name" (`ui.code_label`, `ui.py:751-753`, used by
`activity.py:23`, `milestones.py:55`) while the Gantt rebuilds the label inline
(`gantt.py:352, 357`) (DP-09).

**Options.**
1. *Panel*: `explanation_panel.metric_panel(result, reading=None)` composing P2's two functions
   and the P13 popover; KPI help strings move to `KPI_FORMULAS`/`READINGS` where they explain a
   figure, stay in the page where they state a population caveat. *Download*: `help` parameter on
   `built_download`/`show_download`/`csv_download` (P14 text). *Table*: `COLUMNS` grows a third
   field `help` (appendix F, "Columns" table); the missing keys (`first_forecast`, `latest_forecast`,
   `slip_wd`, `last_week_wd`, `total`, `kinds`, `step`, `removed`, `left`, `finish_before_replanning`,
   `replanning_wd`, `residual_wd`, `period_wd`, `engine_gap_wd`, `longest_path_float_d`, `matched`,
   `added`, `held_by`, `finish_case`, `found_exp`, `total_exp`, `match`, `flagged`, `rows`,
   `columns`, `table`) are added; views drop constructors and renames; `overrides` kept for named
   exceptions only (PPC "Week ending"; the dated value column `earned_value.py:352`; the `now` text
   column `audit.py:129`; `%.2f` on date-named columns `health.py:346`); `ui.table(frame,
   empty="…")` draws a caption instead of a 38 px empty grid when `frame.empty`, pages pass the
   sentence, Debug keeps the grid where the header is the information;
   `gantt.show_task_picker` passes `format_func=partial(ui.code_label, names)` with `names` a
   Series indexed by `task_code` (`latest_names` memoised once per data set, DF-14's front share).
   Cost: ~40 `COLUMNS` lines, ~60 removed in views, ~30 in `ui.table`, ~10 in `gantt.py`. Limit:
   a label used by two pages with two meanings stays an override, listed in a comment; the
   Forensics filter popover then filters on field names (a visible change in the filter keys,
   named in the PR).
2. `ui.count_columns`/`number_columns` builders only (P8). Cost: 60 lines; limit: labels still
   live in the views.
3. A per-page `COLUMNS` dictionary merged into `ui.COLUMNS` at import. Cost: small; limit: the
   same key defined twice is a silent override.

**Choice.** Option 1 (`ui.py:4-5` promises "the same column names … everywhere"; CONTRIBUTING
"Where a change goes"). Waits for the maintainer on the `empty=` sentences and on which Debug
blocks keep the grid.

**What changes for the user.** Column headers byte-identical; a help tooltip on every column; a
caption instead of an empty grid where a page passes `empty=`; the Forensics filter popover keyed
on field names; the Gantt task picker label unchanged.

**Verification.** Failing-before tests: an AppTest asserting, for every `dataframe` of every page,
that each column's label equals `COLUMNS[name][0]` or a listed override (fails today on
Forensics, PPC, Milestones); the voters' AppTest survey counting empty `dataframe` elements on
Debug (5 today → the agreed number). `uv run pytest tests/test_app.py tests/test_page_golden.py
-q`; `pages.json` regenerated once (caption lines replace empty tables), diff listed;
`grep -rn "column_config\." src/xerscope/app/views` lists the named exceptions only;
`duplication.py --threshold 0.8` drops no pair but adds none.

**Findings.** VB-12 (corrected: `ui.py:675-713`, `debug.py:195-196, 208-209, 226-227`,
`ppc.py:147-153`), DP-09 (`gantt.py:350-361`, `ui.py:746-753`, `activity.py:22-23`,
`milestones.py:52-58`), DF-13 (labels part), VB-11 / DP-14 (table part), DF-14 front share
(memoised `latest_names`; the backlog item stays); A1 redesigns R1, R2 (help), R4.

### P16a — `gantt.js`, `gantt.css` and the small modules: names and duplicates (effort M, executor: mechanical executor; rename, output byte-identical)

**Problem.** `viz/gantt.js` (421 lines) was never brought to the Names rules while its Python side
was: `D`, `P` (6, 8), `el`, `cls` (20-21), `r` (40, 56, 80, 180-193, 213-216, 235-282), `b` (68),
`d, t, y, m, h, min` (28-30), `v` (34), `cat` (85), `t0, t1, c0, c1` (120-121, 214-215), `g, t`
(324-325), `p, s, x0, x1, i0, i1` (296-303), `k, v` (289), `gcol, tcol, ghead` (107-113), `cmp_*`
(215) (GX-01). `gridRow` and `timelineRow` open the same way (`236-238` vs `259-261`); the three
legend items are the same four statements (`85-101`); `box()` (250-256) and the `diamond` branch
(271-274) both place by `x()` (GX-03). `.tip` uses a literal `rgba(0,0,0,0.15)` shadow
(`gantt.css:76-80`, GX-06). `selectedIndex` scroll test `> 1` (`gantt.js:412-416`) reads as an
off-by-one, harmless (GX-07, checked). `expected_finish_forms.py:51` `for c in constraints`
(UF-02); `code_picker.py:30-35` a three-line conditional in a keyword argument (UF-01);
`sets.py:56` hard-codes `key="ask_funnel"` (UF-06); `glossary.unknown_acronyms` (`glossary.py:119-121`)
has no caller in `src` (UF-05, AR-12); `streamlit_app.py` draws `ui.glossary()` (40 bullets) in the
sidebar on every rerun (`streamlit_app.py:57`, `ui.py:434-442`, UF-04); `xml_baselines._same_date_columns`
(`157-184`) is two levels of comprehension (UF-07); fonts and `runtime_table` (UF-08) checked, no change.

**Options.**
1. Rename on touch in `gantt.js` (whole words, `row`, `task`, `category`, `startX`…), one
   `rowShell(kind, index, selected)` and one `legendItem(swatchClass, text)`, the `.tip` shadow on a
   theme variable; `for constraint in constraints`; `key` parameter on `show_steps`; SE-02 option
   (2) in `tests/test_viz.py:345`. Cost: ~150 lines, JS mostly. Limit: no JS test runner in the repo
   (unverified); the proof is `tests/test_viz.py -k gantt` (data and asset checks) plus a
   screenshot before/after of the demo Gantt, and the Gantt rows JSON identical.
2. Leave the script, do the Python small modules only. Cost: 20 lines; limit: GX-01, GX-03 stay.

**Choice.** Option 1 (Names 1, 2; Readable 5). GX-04 and GX-05 are **not** here (P16b, section 6).

**Verification.** `uv run pytest tests/test_viz.py tests/test_app.py -q -k gantt`;
`gantt_assets()` text diff reviewed as a rename (no new identifier that is not a whole word);
screenshot before/after in the PR; `same_code.py` on the Python files lists only
`expected_finish_forms` and `sets.show_steps`.

**Findings.** GX-01, GX-03, GX-06, GX-07 (checked), UF-01, UF-02 (names part), UF-05, UF-06,
UF-07, UF-08 (checked), SE-02 option (2).

### P16b — What `gantt.js` does per event (effort S, executor: senior; behaviour, rendering timing)

**Problem.** Measured by reading, not profiled (GX-04): *scroll* is throttled to one
`drawWindow(false)` per animation frame (`gantt.js:402-407`), but `drawLinks` iterates every link
of the chart per new row window (`295-309`): on a 15 000-activity schedule with links on, O(links)
per window. *resize* runs a full `render()` per event, unthrottled (`408-409`). *mousemove* runs two
`querySelectorAll` and a `getBoundingClientRect` on every move (`369-381`, `200`).

**Options.**
1. Index links by first row once per `render()` (a `Map` from row index to links) so `drawLinks`
   walks only the window; the same `requestAnimationFrame` gate on resize; rebuild the tip only on
   a row change. Cost: ~25 lines; limit: memory O(links); no profiler run in the repo to prove the
   gain.
2. Resize gate only. Cost: 4 lines.
3. Leave; record.

**Choice.** Waits for the maintainer, with a before/after timing on `tests/test_viz.py:379`'s
large-schedule fixture rendered in a browser (manual).

**Verification.** `uv run pytest tests/test_viz.py -q -k gantt`; Gantt rows JSON identical
(the payload does not change); a manual scroll and resize on the demo series.

**Findings.** GX-04. GX-05 (`host.xsOpen` kept across data changes) is B12, section 6.

## 4. Dependency order and invariants

Order of merge:

1. **P1, P2, P3, P4a, P5** are independent of each other and of everything else; merge first
   in any order (small, mechanical, output byte-identical). P3 and P5's `snapshot_identity`
   touch `state.py`: agreed with Quentin first.
2. **P6a** (state move) after P3 (so the renamed helpers move once); **P6b** after P6a and after
   the U1 decision (section 6).
3. **P7** after P6a (both caches in `app/cache.py`, baseline resolution in
   `app/baseline_choice.py`); **P7b** after P7, on the maintainer's choice.
4. **P8** after P6a (downloads live in `app/downloads.py`).
5. **P9a** after P2 (explanation panel owns the heading change) and P6a (`keys.py`); it is the
   first package that regenerates `pages.json`. **P9b** after P6a, on the maintainer's choice.
6. **P4b** after P4a, on the maintainer's choice (option 2 touches `gantt_data`).
7. **P10** after P4a (digest script and `DAY` constant) and P9a (one golden regeneration
   reviewed before the next).
8. **P11a** after P9a (labels settled) in the order given inside it, asserts last; **P11b** on its
   own, after the maintainer's choice, any time.
9. **P12a** after P8 and P9a; **P12b** after P12a and the browser check.
10. **P13** after P2 (the panel exists) and P10 (chart layout settled: one golden regeneration);
    the senior's contract first, the texts second.
11. **P14** after P13 (shared wrapper slots) and P8 (the download helper carries the help).
12. **P15** after P8, P9a, P13, P14: it composes the three contracts.
13. **P16a** after P4a and P10 (the CSS and JS text settled); **P16b** after P16a and the B12
    decision (section 6), since both touch the render loop.

What must not change, in every "a" package and in P1, P2, P3, P5, P7, P8:

- No computed value moves: `tests/golden/standards.json` identical; `tests/test_app_parity.py`
  green; no function in `analysis/`, `xer/` or `cpm` is edited except to receive moved code
  verbatim (`same_code.py` shows a move, not a change).
- User-visible output byte-identical: `tests/golden/pages.json` unchanged; figure JSON digests
  unchanged; Gantt rows JSON unchanged.
- Identity stays `task_code`; durations in hours; `_d` and `wd` = working days of the activity's
  own calendar; no real schedule data, activity names, project codes or file paths from real
  `.xer` files in tests, fixtures, docs, help texts or readings.
- `tests/fitness_baseline.json` is not edited by a package; an improvement is regenerated by
  the maintainer after merge.
- No mass rename (`fmt_date`, `fmt_number` keep their names; renames happen on touch only,
  CONTRIBUTING:49-51).
- `state.py` is changed only with the maintainer (Quentin).

The "b" packages (P4b, P7b, P9a, P9b, P10, P11b, P12b, P13, P14, P15, P16b) change what the user
sees or how the app behaves and list every change in section 3; each waits for the maintainer's
choice; P11b is the only one that moves a computed value (the data date of a baseline with a blank
`last_recalc_date` inside the anonymised extract), with its failing-before test.

## 5. Appendices

### A. Contested findings

None. Every voted finding reached the 3/4 consensus; corrections from `partly` votes were applied
to locations and impact (appendix G) rather than recorded as disagreements.

### B. Rejected and merged findings

None rejected. Fourteen ids in `refactor-front/findings.json` carry no vote: they describe the same lines
as a voted id and are treated as that id (the vote on the lines is the vote on both):

| Unvoted id | Merged into | Same lines |
|---|---|---|
| DP-02 | DF-02 | `earned_value.py:78-79`, `ui.py:278-280` |
| DP-03 | DF-03 | `task_panel.py:52-66`, `ui.py:262-280` |
| DP-05, RD-13 | DF-05 | `state.py:954-969` |
| DP-06 | DF-07 | `debug.py:389-391, 427-429`, `state.py:1759-1760` |
| DP-10 | DF-06 | `state.py:1115-1116`; `explain.noun` (`explain.py:50-52`) stays the owner |
| DP-11 | DF-10 | `viz/gantt.py:73-78, 111-118` |
| DP-12 | DF-08 | `diagnostic.py:309-330, 332-354` |
| RD-14 | DF-09 | `diagnostic.py:639-641, 692-700` |
| VB-03, VB-04, AR-05 | DF-02 / DF-03 / DF-04 | the dash and formatter literals (P1); the per-page decimal rule (`pct` 1 decimal, shift `+.1f`) is P9a's unit decision |
| AR-09 | VB-05 | `charts.py:25`, `style.css:294-297`, `ui.py:51` (P10) |
| AR-15 | DF-14 | `ui.py:747-748`, `viz/gantt.py:86`, `diagnostic.py:958` (known, backlog) |

Near-clone pairs from `dup_app.txt`/`dup_viz.txt` that were opened and found not to be duplicates
are listed under DF-15 and excluded from every package: `ui.code_label` vs `state._count`;
`anonymous_exports` vs `costs_shown` as a merge (kept as two readers, DP-04); `glossary.acronyms`
vs `unknown_acronyms`; `ui._number_test` vs `_date_test`; `ppc.show_progress_by_activity` vs
`show_variances`; `viz/gantt._iso_column` vs `_number_column`.

### C. Already known (docs/backlog.md "Structure", lines 200-211)

- `set_index("task_code")` duplication: front share at `ui.py:746-748`, `viz/gantt.py:86`,
  `diagnostic.py:958` (DF-14, AR-15). `Snapshot.by_code` (`model.py:603-606`) keeps the first row
  of one snapshot, so the history/compare frames (`keep="last"`) need a different helper; P15
  memoises `latest_names` (one history pass per data set instead of one per rerun); the backlog
  item owns the rest.
- One cache policy for `_parse` and `memo` (DP-08) and the all-or-nothing eviction of the
  session dicts (LD-10): P7b, after P7, with the backlog item cited.
- Computations inside `app/views` (changelog, health, ppc, gantt): the PPC `progress_delta`
  memo (LD-07) belongs to this family; P11a adds `earned_value`, `milestones`, `overview` to
  the list the backlog names.
- `build_gantt` complexity 16 (backlog): not touched by P4a, which renames and extracts
  converters only.

### D. Findings covered, by package

| Package | Findings |
|---|---|
| P1 | DF-02, DF-03, DF-04 (corrected), DF-12 (app), RD-05 (on touch); merged DP-02, DP-03, VB-03, VB-04, AR-05 |
| P2 | DF-01 / DP-01 |
| P3 | DF-05, DF-06, DP-04, RD-07, RD-08, RD-19 (state); merged DP-05, RD-13, DP-10 |
| P4a | DF-10, RD-06, VB-18, RD-19 (viz), RD-18 (corrected), DF-12 (viz); merged DP-11 |
| P4b | AR-10, GX-02 |
| P5 | DF-07, DF-08, DF-09 (corrected); merged DP-06, DP-12, RD-14 |
| P6a | RD-09, RD-16, LD-08 |
| P6b | RD-01, RD-02, RD-03, RD-04, RD-15 |
| P7 | LD-01 (corrected), LD-02, LD-03, LD-05, LD-06, LD-07, LD-11, LD-12 (corrected), LD-13 |
| P7b | DP-08, LD-10, LD-04, LD-09; A1 R5 |
| P8 | DP-07 (corrected), DF-11 (corrected), DF-13 (corrected, formats), VB-11 (formats); A1 R2 |
| P9a | VB-13 / UF-03, VB-02 (corrected), VB-06, VB-16, DP-13 (corrected), VB-11 (labels, corrected), DP-14 (corrected), VB-01, DF-04 (`n/a`) |
| P9b | VB-14 |
| P10 | VB-17, VB-07, VB-05 / AR-09 / CS-03, VB-08 (comment) / CS-01, VB-10 (corrected), VB-09, CS-02, CS-04 |
| P11a | AR-01, AR-02, AR-03, AR-06, AR-07, AR-08 (corrected), AR-11, AR-12, AR-13, AR-14 (corrected), RD-11, RD-12, UF-02 (move) |
| P11b | AR-04 (corrected) |
| P12a | RD-10, RD-17 (corrected) |
| P12b | VB-15 (corrected) |
| P13 | A3 readings (11 figures, 30 tables) |
| P14 | A2 help texts (70 sites); SE-05a option (2) |
| P15 | VB-12 (corrected), DP-09, DF-13 (labels), VB-11 / DP-14 (table), DF-14 (front share); A1 R1, R2 (help), R4 |
| P16a | GX-01, GX-03, GX-06, GX-07, UF-01, UF-02 (names), UF-05, UF-06, UF-07, UF-08, SE-02 (2) |
| P16b | GX-04 |
| section 6 | GX-05 / B12, U1, file picker |
| checked, no package | SE-01, SE-03, SE-04, SE-05, SE-06, SE-07, CS-05 (test idea recorded), CS-06, UF-04 |
| excluded | DF-15 (false positives), DF-14 (known, backlog) |

Every one of the 94 ids of `refactor-front/findings.json` appears above; DP-09, RD-15 and VB-12, absent
from the first version, are in P15, P6b and P15.

### E. Readings (P13 texts, copied word for word into `explain.READINGS`)

Thresholds and sources are those the repository names: `INDEX_ALERT = 0.95` (`charts.py:39`),
`PPC_TARGET = 80` (`charts.py:40`), `critical_float_days = 0`, `near_critical_float_days = 10`
(`config.py:12-13`), DCMA-06 `total_float_d > 44` (`standards/dcma.toml:70`), BEI ≥ 0.95
(`dcma.toml:141`; P6-13 > 0.95 `p6.toml:164`), CPLI ≥ 0.95 (`dcma.toml:132`), `EVMS = "DCMA EVMS
(EIA-748)"`, `LPS = "Last Planner (PPC)"`, `LIPKE = "Earned Schedule (Lipke)"` (`explain.py:288-291`),
AACE RP 29R-03 MIP 3.4 (`docs/formulas.md:477`). No source in the repository sets a threshold for
SPI or CPI: 0.95 on the indices chart is xerscope's alert line, said as such.

#### E.1 Figures

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
200.1 §; DECM v8.0 metric ID; Oracle P6 EPPM 26 help, Schedule Project Log), shown by `show_method`.

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

#### E.2 Metric tables shown by `ui.table`

Each table's reading is one `Reading` attached by the page; the columns' help comes from `COLUMNS`
(appendix F, P15). Call sites from `grep -rn "ui.table(" app`:

| Page · table (key) | Where | How to read / what it means / conclude | Source |
|---|---|---|---|
| Overview · Updates loaded (`overview_updates`) | `overview.py:128` | One row per weekly XER: status date, file, forecast finish, finish shift (wd, later = negative), counts of tasks by status, critical, relationships, % complete by count. A finish shift < 0 week after week is a slipping project. | xerscope `store.summary` (`store.py:209-238`) |
| Health · Results (`health_results`) | `health.py:106-112` | One row per check in the standard's order: status (pass red/green labels), id, group, check, result in its unit, found / checked, target, items listed. Fail = result on the wrong side of the target; info and n/a are not scored. | The standard's TOML `source` per check; `SCORE_HELP` (`ui.py:400-405`) for the score |
| Health · Parameters (`params_<id>`) | `health.py:244-248` | parameter, value, set by (standard or default): the effective settings of the check. | the TOML |
| Health · Flagged items (`flag_<id>`) | `health.py:263-268` | The tasks or links the check lists, culprits first; select a row to open the Gantt. | the check's `source` |
| Health · All checks, all updates (`health_trend`) | `health.py:342-348` | One row per check, one column per update (value, `%.2f`). Read a row left to right as the check's history. | idem |
| Health · Report comparison (`health_report`) | `health.py:393-403` | Found / total typed from the P6 report beside xerscope's, Match ticked when equal. A mismatch names the population to audit. | P6 Professional Check Schedule report |
| Audit · Settings sheet (`sheet_settings`) | `audit.py:130-132` | setting, now, default, accepts: the `[[metric]]` values to paste into a standard file. | `analysis/audit.settings_table` |
| Sets (Health, Audit) · Counted / Checked, not counted / Excluded (`table_<key>`) | `sets.py:46` | The three sets behind a count; nothing is recomputed (`audit.split`). | the check's `source` |
| Sets · Funnel (`funnel`, `ask_funnel`) | `sets.py:53-58`, `87-92` | start, then one row per population step: its label, the text it follows, rows removed, rows left; last row = counted. The denominator is the last step's left. | `populations.STEP_SOURCES` (docs/formulas.md:127-128: Oracle P6 help 101248 and 46282, R1, Ten Six, PAM 200.1, DECM 8.0, xerscope) |
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

### F. Help texts (P14 and P15 texts, copied word for word)

Method: each of the 70 call sites of `widgets_without_help.txt` was opened with its surrounding
lines. The text for `help=` is two sentences: what the widget does, when to use it. Markdown is
accepted by Streamlit's `help`.

Sites carried by a wrapper (4 + 5 generic):

- `ui.py:316` `st.plotly_chart` inside `ui.chart` (`ui.py:310-316`): not a widget; the reading goes
  in the popover `ui.chart(fig, reading=…)` of P13.
- `ui.py:668`, `ui.py:671` (`_filter_inputs`): one input per column; the help is the column's help
  from `COLUMNS` plus the operator hint already in `placeholder` (`FILTER_HINT`, `ui.py:533-537`).
  Inject in the wrapper: `help=column_help(column) + "\n\nOperators: " + FILTER_HINT[kind]`.
- `ui.py:723` (`_open_in_gantt_button`): one text in the wrapper, below.
- `state.py:2038` (`show_download`): a `help` parameter on `show_download` (`2024-2033`) and
  `csv_download`, defaulting to "Downloads this table as it is shown; with Anonymous exports on
  (sidebar), Task IDs and names are replaced as in every other download of the session."
  (`docs/architecture.md:201-214`). The 25 download sites then need no text.
- `audit.py:45, 47, 49, 50` (`parameter_widget`): the label is the rule parameter's name; propose
  `help=parameter_help(rule_name, name)` reading the rule's docstring `Parameters` section or the
  notes `explain._population` already writes (`explain.py:205-209`, `_limit_note` `149-152`), so the
  text exists once in `analysis/`. Fallback text below.

#### `app/code_picker.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 20 | selectbox | Task code (P6 activity code) | Picks one activity code type of the file (P6 ACTVTYPE); its values then filter the page's tasks. Use it to read one trade, area or contract on its own; None keeps every task. |
| 27 | multiselect | Code values | The values of the picked code type to keep; a typed text followed by Enter keeps every value containing it. Use it to narrow to a few values when the type has many. |

#### `app/sets.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 67 | selectbox | Rows removed by | Lists the rows one population step took out of this check's denominator (the steps are in the funnel table above). Use it to see which tasks or links an exclusion removed, and why. |

#### `app/state.py`

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

#### `app/ui.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 668 / 671 | multiselect / text_input | (column filters) | Injected by `_filter_inputs`: the column's help, then "Operators: contains… / <0, >=5, -10..0 / >2026-11-01, 2026-11, 2026-11..2026-12" (`FILTER_HINT`). Every filter must hold; an empty text filters nothing. |
| 723 | button | Open {code} in the Gantt | Switches to the Gantt on the selected row's task, in the update shown. Use it to see the task's bar, logic and card. |

#### `app/views/activity.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 23 | selectbox | Task | One Activity ID (task_code) with its latest name; its forecast dates, float and progress are then followed through every loaded update. Use it to read how one task moved week by week. |

#### `app/views/audit.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 45 | multiselect | (parameter name) | Fallback: The values this parameter accepts (several at a time), starting from the standard's. Change them to see the check re-run with another population; the standard itself is not changed. |
| 47 | selectbox | (parameter name) | Fallback: One of the values this parameter accepts, starting from the standard's. Change it to re-run the check with another reading; the standard itself is not changed. |
| 49 | checkbox | (parameter name) | Fallback: Switches this parameter on or off for the audit, starting from the standard's value. The standard itself is not changed. |
| 50 | number_input | (parameter name) | Fallback: The threshold of this parameter, in the unit its name says (`limit_hours`: hours as P6 stores them; `limit_days`: working days of each task's calendar; `audit.py:137-138`). Change it to see what the count becomes. |
| 151 | segmented_control | Standard | The standard whose checks can be audited: P6 Check Schedule, DCMA 14-Point, DCMA DECM v8.0, Integrity, or an uploaded one. Pick the one your report follows. |
| 172 | selectbox | Check | One check of the standard: its sets (counted, checked but not counted, excluded), its population step by step and the same check re-run with the settings below. Use it to explain one number of Schedule health. |
| 192 | button | Reset | Puts every setting of this audit back to the standard's values and forgets those kept for the session. Use it after trying other thresholds. |

#### `app/views/changelog.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 62 | multiselect | Category | Keeps the changes of the picked categories (Scope, Dates, Logic, Durations, Resources, Constraints…; the Project rows are never listed here). Empty keeps all. |
| 65 | multiselect | Change | Keeps the picked kinds of change within the categories. Use it to list one kind, such as durations changed, on its own. |
| 66 | text_input | Search | Keeps the rows whose Task ID, name, WBS or field contains the text, ignoring case and accents. Use it to follow one task or one WBS branch. |
| 104 | selectbox | To (newer) | The later of the two updates compared; the changes are read as To minus From. Use it with From to compare any two weeks, not only consecutive ones. |
| 106 | selectbox | From (older) | The earlier of the two updates compared. The buttons below set it one, four updates back or to the first loaded. |
| 117 | button | Previous / 4 back / First | Sets From to the update before To, four updates before it, or the first loaded. Use "4 back" for a monthly reading. |

#### `app/views/debug.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 294 | file_uploader | P6 Activities export | P6's Activities view saved as CSV (labour units in hours) with Activity ID, Planned Value Labor Units, Earned Value Labor Units, Schedule % Complete. Use it to hold xerscope's PV and EV against P6's, task by task; the file stays in this session's memory. |
| 311 | selectbox | Column not found: {field} | The column of your export that carries this field, when its header is not P6's default. Pick it once per field; required fields block the comparison until picked. |
| 317 | number_input | Gap tolerance (h) | Difference in hours between xerscope and P6 above which a task is listed as differing (PV and EV, labour units). Use it to hide rounding gaps; 0 lists every difference. |
| 321 | number_input | PV labor units total shown by P6 (h, optional) | The project PV total P6 shows, to compare with xerscope's sum. Fill it when the task list of the export is partial. |
| 393 | button | Build calendar detail | Builds block 13 (each calendar's hours per period, weekday periods, exceptions) as one zip of CSV files, anonymised when the sidebar switch is on. Use it to check a calendar P6 and xerscope read differently. |
| 486 | button | Build diagnostic | Builds blocks 1 to 9, 11 and 13 as CSV, block 10 without its activity list, as one zip. Use it to send what xerscope read and decided for this update, without the XER file. |

#### `app/views/earned_value.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 378 | toggle | Show as % of BAC | Draws PV, EV, AC and the forecast as a share of the Budget at Completion instead of labour hours; each update's points over its own BAC, the curves over the BAC of the update shown. Use it to compare updates whose baselines differ in size. |

#### `app/views/export.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 45 | radio | Format | Parquet keeps the column types (dates, numbers) for Power BI; CSV opens anywhere. Pick Parquet for Power BI, CSV for a spreadsheet. |
| 99 | button | Build anonymized extract | Rebuilds every loaded file and the separate baseline file with new Task IDs, WBS, project, resource and calendar names; dates, durations, units and logic unchanged. Use it to share a schedule P6 and xerscope compute the same results on. |

#### `app/views/forensics.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 166 | selectbox | Update | The update read against the one before it: the week's delay (finish before replanning) and what the week's replanning did to the finish. Pick any update after the first. |

#### `app/views/gantt.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 99 | text_input | Ask the schedule | A sentence in English or French ("critical not started in civil works", "jalons en retard") turned into the page's filters from the file's own words; no model reads the schedule. Use it instead of the filters below; a × on a chip drops that filter. |
| 158 | button | (clarify choice) | Picks which code value or type the word meant when the file has several of that name. Click one; the choice is kept for this sentence. |
| 176 | button | (teach suggestion) | Teaches, for this session, that the word you typed means this label of the file. Click the right one; nothing is kept beyond the session. (SE-05a, if option 2 is chosen: "A pick is kept for review in the lexicon folder of the server.") |
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

#### `app/views/health.py`

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

#### `app/views/milestones.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 48 | button | Finish milestones | Picks every finish milestone of the latest update. Use it as the usual MTA set. |
| 49 | button | Critical milestones | Picks the critical finish milestones only. Use it on a large schedule where every milestone would crowd the chart. |
| 50 | button | Clear | Empties the pick. |
| 51 | multiselect | Milestones and key tasks (up to N) | The milestones and tasks whose forecast date is followed update by update; each keeps the colour of its tag in the chart. Up to N at a time; a task's finish is used, a start milestone's start. |

#### `app/views/overview.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 93 | button | Compute scores | Runs every built-in standard on the latest update and fills the score cards; Schedule health reuses the results. Use it when the cards read "not computed yet"; it takes several seconds on a large file. |

#### `app/views/ppc.py`

| Line | Widget | Label | help= |
|---|---|---|---|
| 225 | number_input | PPC target (%) | The dotted line of the chart: the share of commitments kept you aim for, in percent. 80 is xerscope's default (`charts.py:40`); Last Planner System (PPC) sets no fixed target in the sources this repository names. |
| 234 | selectbox | Week ending | The update W whose commitments are read: what W−1 forecast to start or finish by W's status date, against what W reports done. Pick a week; the first update has no W−1. |

#### Columns of `ui.COLUMNS` without a help (P15, `help` field)

`_column_for` (`ui.py:501-515`) gives `help=spelled_out(label)`: 46 of the 130 columns get an
acronym gloss, 84 get none. For the 46, the gloss stays and the text below is prepended. Unit and
P6 field named where the model gives one; "(model.py not reopened)" marks a field name taken from
the P6 vocabulary rather than read in `xer/model.py` this session.

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
| data_date | Status date | The project's data date (PROJECT.last_recalc_date; the model falls back to plan_start_date, `xer/model.py:1496-1503`). Every "before / after the status date" check counts from it. |
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

Columns used by pages but absent from `COLUMNS` today (they get label and help with P15):
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

### G. Corrections from `partly` votes, applied

| Id | Correction from the voter | Applied in |
|---|---|---|
| DF-01 | impact medium, not high; same as DP-01 | P2 |
| DF-04 | `overview.py:48`, `forensics.py:99` test `is None`, not the same expression; kept list `ppc.py:72-73, 127`, `gantt.py:225`, `task_panel.py:113, 244-245`; `charts.py:580` is viz | P1, P4a |
| DF-09 | `dropna` vs `fillna(0.0)`: different contracts, not one function; the nested defs stand | P5 |
| DF-11 | `show_download` takes a `Fetched`; the bypass was the only option; `state.py:2035-2046` | P8 |
| DF-13 | 6 files, 9 `format="%d"` literals, not 9 views; `numbers_as_text` builds `TextColumn` only | P8 |
| DF-14 | `Snapshot.by_code` keeps the first row of one snapshot; the front needs `keep="last"` | appendix C, P15 |
| DP-07 | ~15 lines per site; refusal handling already in `show_download`; impact medium | P8 |
| DP-13 | three different figures, shared sentence and format only; `overview.py:40-52`, `changelog.py:28-31`, `forensics.py:84-87` | P9a |
| DP-14 | `data_date` label at `ui.py:208`, not 218; `first_forecast`/`latest_forecast` absent from `COLUMNS`, the overrides supply a label; KPI long date vs ISO tables is a documented pair | P9a, P15 |
| RD-01 | one C901 hit in a composer: medium | P6b |
| RD-05 | 33 or 39 call sites; a rename is the mass rename CONTRIBUTING:50-51 forbids | P1 (on touch) |
| RD-17 | depth 3, fitness cognitive 10, not 14; `ui.py:571, 612-632` | P12a |
| RD-18 | ranges swapped: `build_scurve` 128-207 (blocks 155-184), `build_mta` 280-360 (body 323-355); cognitive 10 | P4a |
| VB-02 | `charts.py:197` has its unit on the axis; kept `charts.py:423, 431`, `forensics.py:43, 99-102`, `earned_value.py:181` | P9a |
| VB-08 | the phone blank band is plausible, unverified | P10 (left out) |
| VB-09 | desktop tool; hidden bars reasoned, not rendered; impact low | P10 |
| VB-10 | default 560 at `ui.py:680`, not 641 | P10 |
| VB-11 | the CSV at `forensics.py:154` downloads the unrenamed frame; `ui.py:208`; "Week ending" deliberate | P9a, P15 |
| VB-12 | Debug 5 of 30 frames empty on the demo; PPC/Forensics conditional; `ui.table` at `ui.py:675-713` | P15 |
| VB-15 | `placeholder` at `ui.py:704-705`; `numbers_as_text` not dead (kind template, alignment); `blank_missing` unverified | P12b |
| LD-01 | one-off per series change, parallel pool; impact medium | P7 |
| LD-04 | ~5 ms per rerun; low | P7b |
| LD-12 | `gantt.py:51`, `earned_value.py:461, 504-530`; 2 `baseline_for` per rerun on Gantt, Audit, PPC | P7 |
| LD-13 | a measurement, not a defect; timings unverified by the voters | §2 (script kept) |
| AR-04 | medium: dates only the baseline file inside the extract (`export.py:83`); module is `xer/model.py:1496-1503` | P11b |
| AR-08 | partial duplicate: the page keeps the "n/a when nothing was due" caveat; `ppc.py:139-146` is the week's numbers | P11a |
| AR-14 | two deltas are trivial; the complexity (`score_section`, 79-97) is the debt | P11a |

## 6. Open items framed for the maintainer

Choice left open on each; nothing is coded before the maintainer's answer.

### B12 — "Gantt reduced to 4 rows" (GX-05)

**Problem (code evidence).** The server computes the component's height on the branches *it* opens:
`gantt_data(... open_ids=open_row_ids(...))` (`views/gantt.py:328-336`) → `fitted_height(rows,
set(open_rows), height)` = `min(height, CHROME_PX + ROW_PX * max(MIN_ROWS, visible_rows(rows,
open_ids)))` (`viz/gantt.py:203-206`, `MIN_ROWS = 4`, line 38). While a filter is on, `open_row_ids`
opens every WBS row (`viz/gantt.py:65`, `filtering=True`, `views/gantt.py:299`). The browser then
**merges** what the page sends with what it kept: `const open = new Set([...(host.xsOpen || []),
...D.open]); host.xsOpen = open` (`gantt.js:49-50`), on an element that survives reruns (comment
45-47). After a word typed then erased in Ask: `filtering` is False, `open_ids = {"w:<focus>"}` →
height for the focus node's direct rows (often 4 → `96 + 4 × 26 = 200 px`), but `host.xsOpen`
still holds every branch → `visibleRows()` in the browser (53-63) draws them all inside a 200 px
box. The state the height was computed on and the state drawn are two different sets, by design of
the merge.

**Option 1 — height on all rows of the tree.** `fitted_height` → `min(height, CHROME_PX + ROW_PX *
max(MIN_ROWS, len(rows)))`, or pass every WBS id from the page. Cost: one line in `viz/gantt.py:206`
or `views/gantt.py:334`; the chart then takes `GANTT_HEIGHT` (680, `views/gantt.py:40`) on any tree
of ≥ 22 rows; "no blank space under a short tree" (docstring 204-205) is given up. **Test that
changes:** `tests/test_viz.py:456` lines 462-466 (`fitted_height(rows, {"w:0"}, 680) == chrome +
least * row` becomes 680 for its 42-row fixture). Limit: does not fix the inverse case (viewer
collapses everything: a 680 px box for 4 rows).

**Option 2 — the browser fixes the height.** In `render()` (`gantt.js:335-360`), after `shown =
visibleRows()`, set `root.style.height = Math.min(D.maxHeight, CHROME + shown.length * ROW) + "px"`
and send `maxHeight` in the payload beside `height`. The component is in the page's DOM
(`ui.py:54-56`), so the page reflows at once. Cost: ~4 lines JS, one key in `gantt_data`
(`viz/gantt.py:237-249`), `CHROME` duplicated in JS unless sent as `D.chromePx` (P4b). Benefit:
height follows every fold/unfold and the toolbar buttons (74-83). Limit: `fitted_height` becomes the
first-paint estimate only; no JS test runner in the repo (unverified).

**Option 3 — reset `host.xsOpen` when the filter state changes.** The page knows `filtering`
(`views/gantt.py:299`) and the Ask text (`asked`, 99); send `D.openEpoch` (a counter bumped in
session state when `filtering` flips or `asked` changes) and in `gantt.js:49`: `if (host.xsEpoch !==
D.openEpoch) host.xsOpen = null; host.xsEpoch = D.openEpoch;` before the merge. Cost: ~6 lines JS +
~4 lines Python (with Quentin: a session key). Keeps "the branches opened by the viewer stay open
across reruns" for picks and toggles (the comment's own cases, 45-47) and drops them exactly when the
server recomputed the tree. Limit: the server height is still only right for the branches it opened.
Options 2 and 3 are not exclusive.

**Choice.** Open.

**Verification (all options).** `uv run pytest tests/test_viz.py -q -k gantt`; `uv run pytest
tests/test_app.py -q`; by hand on the sample series: Gantt page → type a word in Ask that matches a
few tasks → erase it → the chart shows the focus node's rows at the height of those rows (or the
cap), not 4 rows with an inner scroll. Screenshot before/after in the PR (CONTRIBUTING Readable 6).

### U1 — "loading order" (`state.py`: with Quentin only)

**Problem.** `sidebar_loader` (`state.py:691-767`, radon C 17, ruff C901 12 > 10) does four things
in one body: (a) the load decision, `_chosen_items()` → `_forget_previous_series()` → three branches
"thread job / in-run read / nothing" (695-718); (b) collecting a finished job (719-727); (c) applying
the per-file project choice (729-731); (d) drawing: the Files button (733-745), the errors (746-747),
the baseline picker and prompt (748-750), the window (751-752), the two sidebar switches (753-767).
`LoadJob` (208-236) and `ScoreJob` (1775-1811) are already small (radon A). The Overview's
`score_section` (`views/overview.py:79-97`, C 17) mixes the three states (polling / button / held)
with the cards' drawing.

**Proposed split (which function keeps which lines).** `load_series() -> SnapshotStore | None`
(new, pure of drawing except the progress line): lines 695-731, with `_start_or_read(signature,
items, gone)` for 698-718 and `_collect_finished_job()` for 719-727 (the `_poll_load` fragment call,
726-727, is the one drawing exception, or moves to the caller); `draw_sidebar(store)` (new): lines
733-767 unchanged; `sidebar_loader()` becomes `store = load_series(); draw_sidebar(store)`;
`streamlit_app.py:56` unchanged. The in-run read's progress line (704-713) uses `sidebar.empty()` and
can take the container as an argument. `overview.score_section` → `scores_held()` (80-81, 87-88) /
`scores_polled(job)` (83-91) / `scores_on_button()` (92-93), `ui.score_cards(...)` (94-96) kept in
the caller (P11a).

**Invariant to keep (what is drawn before the first file is read).** In order: `st.set_page_config`
(`streamlit_app.py:28`), the navigation (30-52), `ui.apply_style()` (55), then inside
`sidebar_loader` the `files_line = sidebar.container()` placeholder (`state.py:693`) **before**
`_chosen_items()` reads any byte (695; it may read the folder's files, 569-592): the Files line keeps
the top slot of the sidebar whatever the read does, and the button's label is written after the read
(733-745, comment 732). Pages run last (`pages.run()`, 58) and stop on `require_store` while a job
runs (`state.py:1591-1602`). The split must keep: placeholder first, read second, label third.

**Choice.** Open: whether the split is wanted, and whether `load_series` may draw the progress line.

**Test.** `load_series()` testable without AppTest by injecting the session dict as the `memo`
helpers do (`session=None` pattern, `state.py:840, 849`): given `files_source = ("upload", [(name,
bytes)])` and `XERSCOPE_SYNC_LOAD=1` (`background_jobs()`, 128-132), it returns a store, sets
`signature`, `items`, `errors`, and `_load_job is None`; a second call with the same source returns
without re-reading (`_parsed` keys unchanged). Regression net: `tests/test_app.py`,
`tests/test_app_robustness.py:97-137`, `tests/test_page_golden.py`.

### File picker slow to open

**What `read_header` reads.** The picker calls `_header(path)` per file (`state.py:259-273`) →
`load_header(path)` → `read_xer(path, keep=HEADER_TABLES)` → `read_header(raw)`
(`xer/__init__.py:51-54`), `HEADER_TABLES = {"PROJECT": None, "TASK": ("task_id", "task_code",
"proj_id")}` (`xer/model.py:1506`). `keep` does **not** stop the read: `_Reader.run` walks every line
to `%E` (`xer/parser.py:235-249`) and only skips splitting the `%R` lines of tables left out
(`253-255`); `read_bytes()` reads the whole file. A session cache keyed `(str(path), size,
mtime_ns)` exists (`state.py:261-266`, cleared past 256): a new tab starts cold.

**Measured on the sample series** (20 synthetic files of 14 KB, `uv run xerscope sample --weeks 20`;
the maintainer's series was not available): `load_header` 4.4 ms mean per file, 89 ms for 20; of
which `parse_bytes(keep=HDR)` 0.21 ms, full parse 0.68 ms, `read_header(raw)` 2.9 ms (pandas fixed
cost dominates on small files). On a synthetic scale-up of the same file (rows repeated with new ids):
2.3 MB → `parse keep=HDR` 16 ms, full 40 ms, `read_header` 3 ms. Table order in the sample: PROJECT,
CALENDAR, SCHEDOPTIONS, PROJWBS, RSRC, TASK, TASKPRED, TASKRSRC; TASK ends at 73 % of the file.
Extrapolated (not measured) to a 40 MB export: ~280 ms per file for the header scan, ~5-6 s for 20
files on first open; on real exports TASKRSRC and TASKPRED after TASK are usually the largest
tables, so stopping at the end of TASK saves most of the scan, consistent with "x5 on 20 files".

**Option 1 — stop at the end of TASK (the maintainer's local, unpushed variant).** In `_Reader.run`
(`parser.py:235-249`), end the loop when a `%T` opens a table after every `keep` table has been seen.
Cost: ~6 lines in the parser + the `ended` flag semantics (`RawXer.ended` is False when `%E` was not
read, `docs/architecture.md` §1: the picker tolerates it, `build_snapshot` refuses it, so the header
path must set a distinct "stopped early"). Limit: a file whose TASK comes before PROJECT, or with two
TASK tables (refused anyway), needs a test each (`tests/test_parser.py`). Still reads the whole file
into memory. Out of this plan's scope (`xer/`), framed here because the symptom is the front's.

**Option 2 — a header cache keyed on path + mtime + size, process-wide or on disk.** The session
cache exists; the cold start is per tab. A process-wide `functools.lru_cache` would hold
`FileHeader` (project codes, counts, data date: data from the files) across sessions, against
"nothing from a file remains after the session" and SE-06's "no cross-session cache"; a disk sidecar
is worse. Cost: 5 lines; limit: breaks the session-only invariant → **not recommended unless the
maintainer accepts the exception for headers on a locked instance** where every session reads the
same folder anyway (`XERSCOPE_DATA`, `state.py:440`).

**Option 3 — read the header in the background, draw the list first.** The picker draws each tick
box with its label from `_describe_file` (`state.py:276-300`); with a `LoadJob`-like thread (or the
existing pool of `reading.py`) filling `_headers` and a `st.fragment(run_every=1.0)` like
`_poll_load` (`state.py:245-256`), the window opens at once with "reading…" labels that fill in.
Cost: ~40 lines in `state.py` (with Quentin); limit: more state (a job slot), and a tick before the
header is known must still be accepted (`most_recent_first`, `state.py:200-205`, re-reads the header
from bytes anyway). Options 1 and 3 compose; 1 is the cheapest and keeps the invariants.

**Choice.** Open.

**Verification.** `uv run pytest tests/test_parser.py tests/test_model.py tests/test_reference.py -q`
(parser contract: "Snapshot or XerError", `read_header` vs `build_snapshot` agreement,
`docs/architecture.md` §2); `tests/test_fuzz_parser.py` with `load_header` added to the fuzzed
functions (gap noted in 2bis); the timing script's two numbers (`parse keep=HDR` per MB,
before/after) written in the PR, measured on the maintainer's series locally, never with a file name
in the PR.

## Review of this plan

First pass (`refactor-front/review.json`): completeness over sections 2 to 5 and appendix D, every line cited
re-opened on the working tree. Second pass (19 November): the corrections below, every line re-opened
again (`sed -n`, `grep -n`) before being written.

### Resolved by the second pass

- **Missing findings.** `DP-09`, `RD-15`, `VB-12` were absent from every package and from the text;
  their definitions were read in `refactor-front/findings.json` (each 4/4 confirmed, VB-12 with one `partly`)
  and placed: DP-09 and VB-12 in P15 (Table contract), RD-15 in P6b. The 14 unvoted ids
  (`DP-02, DP-03, DP-05, DP-06, DP-10, DP-11, DP-12, RD-13, RD-14, VB-03, VB-04, AR-05, AR-09,
  AR-15`), which the first version counted neither in "68" nor in "80", are mapped to their voted
  twin in appendix B; appendix D now covers all 94 ids.
- **Move and behaviour mixed.** P4 → P4a (renames, byte-identical) and P4b (the `ROW_PX` token,
  a rendering change, waits for the maintainer); P9 → P9a (visual fixes) and P9b (Audit default
  standard and the `health_std`/`audit_std` key merge, a loading behaviour); P11 → P11a (moves) and
  P11b (`export._data_date` → `read_header`, the one computed-value change, with its failing-before
  `xerkit` test); P12 → P12a (moves) and P12b (`blank_missing`, after a browser check). P7's
  `functools.cache` on `builtin_standards` moved to P7b as a design decision (first process-wide
  cache of the front, SE-06).
- **Wrong line ranges.** The model's data-date rule is `src/xerscope/xer/model.py:1496-1503`
  (opened: the function starts at 1496); the theme block is `ui.py:66-124` (`125-129` are
  `ROW_HEIGHT`, `HEADER_HEIGHT`, `COLUMNS`); the filter block is `ui.py:533-633` (`FILTER_HINT` at
  533, `filter_rows` returns at 633); `tests/test_table_filters.py` exists (135 lines, cases at
  45-118) and is moved, not written; `ui.table` is `ui.py:675-713` with the default at 680;
  `build_scurve`/`build_mta` ranges unswapped; every `partly` correction of appendix G applied in the
  package text.
- **P6a above 400 lines.** The review method is now explicit in P6a: `same_code.py <base>` is the
  whole review; `state.py` is changed only with the maintainer (Quentin); nothing is coded before his
  Problem / Options / Choice agreement; the same sentence in section 1 and section 4.
- **Safety net.** `--threshold 0.8` on `duplication.py`; `same_code.py` against the package base, not
  `origin/main`; `time_pages.py` takes its output folder; `bandit` added; the golden's content
  (labels, values, texts, columns, trace types; not `help`) stated so P14's proof is an AppTest.
- **Uncovered files.** `code_picker.py`, `expected_finish_forms.py`, `views/activity.py`,
  `streamlit_app.py`, `static/` and the fonts, `gantt.js`, `style.css`, `glossary.py`, `sets.py`,
  `reading.py`, `xml_baselines.py` were read whole (`refactor-front/security-and-uncovered.md`): GX-, CS-, UF- findings
  placed in P4b, P9a, P10, P11a, P16a, P16b or recorded as checked; `tests/test_accessibility.py`
  and `scripts/accessibility.py` are now cited (P10 contrast, P13 test style).
- **Security.** Section 2bis: five HTML sinks listed with their serialisation and the test that pins
  each; SE-01 to SE-07 checked; what no test covers, recorded.
- **Readings and help.** P13 (readings, decision of 19 November), P14 (help texts), P15 (the three
  front contracts) added; the texts are in appendices E and F in full, so an executor copies them.
- **Open items.** B12, U1 and the file picker framed in section 6 with their options, the test each
  option changes, and the Choice left open.

### Still open

- **Nine choices wait for the maintainer**: P4b (row constant), P7b (cache policy, process-wide
  standards cache), P9a (Activity page: remove or retitle; unit vocabulary; severity rule), P9b
  (Audit default and key), P11b (data-date rule), P12b (`blank_missing`), P15 (`empty=` sentences,
  Debug grids), P16b (render loop), and section 6 (B12, U1, file picker). None is coded before.
- **Unverified claims kept as such**: the phone rendering of the MTA (VB-08) and of the Gantt below
  480 px (VB-09); whether `placeholder` alone renders the dash on Streamlit 1.67 (VB-15); whether
  Streamlit parses option labels as Markdown (`code_picker.py:20-37`); whether a hashed `script-src`
  works on Streamlit (SE-03); what a rule does with an absurd `audit.py:50` value; the 40 MB
  extrapolation of the header scan (file picker); the gain of P16b (no profiler run).
- **Out of scope but named**: `deploy/Caddyfile` CSP (SE-03), the parser change of the file picker's
  option 1 (`xer/parser.py`), `docs/deploy.md` on the lexicon's `suggested/` folder (SE-05a).
- **Test file names assumed in P11b** (`tests/test_export.py`, `tests/test_anonymize.py`) are to be
  confirmed on the branch.
- **`pages.json` carries the demo series' synthetic project code in its sidebar caption**; it is the
  repository's own sample, not a real schedule, and this plan does not quote it.

### Safety net, run once on the working tree (first pass, read-only commands only)

| Command | Result |
|---|---|
| `uv run pytest -rs` | pass (exit 0; 26 skips, all `tests/test_reference.py` "reference missing", not MPXJ) |
| `uv run pytest tests/test_characterization.py` | pass |
| `uv run pytest tests/test_page_golden.py` | pass |
| `uv run pytest tests/test_app.py -q -x` | pass |
| `uv run pytest tests/test_app_parity.py -q` | pass |
| `uv run pytest tests/test_app_cache.py tests/test_app_background.py -q` | pass |
| `uv run python scripts/duplication.py src > dup_main.txt` | runs (36 near clones) at the default threshold 0.9 (`scripts/duplication.py:26`); none of the 0.81-0.87 pairs appears: section 2 now writes `--threshold 0.8` |
| `uv run python scripts/fitness.py --check tests/fitness_baseline.json` | pass (reports two "better" in `xer/pmxml.py`) |
| `uvx ruff check src tests scripts` | pass |
| `uvx ruff format --check src tests scripts` | pass (226 files) |
| `uvx bandit -r src -ll` | pass ("No issues identified", second pass) |
| `uv run pytest tests/test_app_robustness.py tests/test_fuzz_parser.py -q` | pass (second pass) |
| `uv run python scripts/same_code.py origin/main` | exit 1: 81 ADDED, 47 CHANGED, 2 REMOVED, the branch being 36 commits ahead of `origin/main`: section 2 now says "the base of the package branch" |
| `docs/refactor-front/time_pages.py <folder>` | runs with an output folder (`time_pages.py:12`): Health rerun 0.22 s, in line with the 0.24 s quoted in P7 |
| `XERSCOPE_UPDATE_GOLDEN=1 ...` (P9a) | not run: it rewrites `tests/golden/pages.json` |

Everything else in section 2 is runnable as written.
