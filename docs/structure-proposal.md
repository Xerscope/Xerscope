# Package tree restructuring proposal

Status: proposed, not applied. Decision pending with the maintainer; once agreed, the decision is recorded as an ADR in docs/adr/.

Checked against `dd6c71b`. Scope: the tree of `src/xerscope` and `tests/`; moves and splits with no change of behaviour, no new dependency, no plugin, no dependency injection and no generic engine.

## Problem

The repository is not disordered as a whole. The layers (`xer`, `store`, `analysis`, `viz`, `app`, `cli`) are fixed by ADR-0001 and checked by `tests/test_architecture.py`. The real problems are local and measured.

1. **`xer/model.py` (1728 lines, MI 4.4, rank C) gathers five responsibilities**: the column lists and the P6 code tables, the value readers, the contract and the `Snapshot` class, project selection with the header, and the build chain. Fourteen analysis and app modules import tables and readers from the same place as the build internals.
2. **`cli.py` (1037 lines, MI 5.07, rank C)**:
   - About a third of the file (L653-993) is the Ask lexicon and `ask-bench` logic, not argument wiring.
   - `APP_PATH` (L16) depends on the location of `cli.py`.
   - Its 43 lazy imports are relative (`from .export import …`, `from .crosscheck import …`, `from .app import diagnostic`…). Their target therefore also depends on the location of the file.
3. **The CLI loads Streamlit for `pv-compare`.** `app/diagnostic.py:38` takes `as_dates` from `ui`, which imports streamlit and registers the Gantt component. Yet `as_dates` is defined in `table_filters.py:27`, which does not import Streamlit.
4. **The generic CSV and zip serialisers live in the Power BI module** (`export.py`). `anonymize` therefore depends on `export`, and through it on `store`.
5. **`analysis/explain.py` (981 lines) mixes two subjects**:
   - the explanation of a `CheckResult` (L1-313);
   - a catalogue of page texts (L314-981).
   The catalogue contains 15 `file:line` citations (`charts.py:70-83`, `config.py:12`, `store.py:231-236`, `ui.py:400-405`, `debug.py:379-381`…), some of which are already stale.
6. **Test files serve as libraries** for other tests: 12 `test_*` modules are imported by other tests. In addition, `conftest.py` serves both as a conftest and as a helper module. Until this is settled, no test can change folder.
7. **Smaller debts**:
   - `task_filters` imports `fold` through the Ask facade.
   - `fitness_baseline.json` is partly stale (see PR 0a).
   - `scripts/accessibility.py:41` gives a stale page list.
   - The docstring of `app/state.py:1` is wrong.

Some things are **not** problems to fix by a move: the size of `cpm.py` comes from the single class `_Run`, and that of `anonymize.py` from the single class `Anonymizer`. They call for internal method refactorings.

## Options

| Option | What it does | Cost | Limit |
|---|---|---|---|
| **A. Status quo and small fixes** | Only points 3 and 7, plus the line citations in `explain` | 4 to 5 PRs of under 60 lines | `model.py` and `cli.py` stay at rank C. Tests still cannot be moved. |
| **B. Targeted splits within the existing layers (recommended)** | A, plus: split of `model.py` within `xer/`, `cli` becomes a package from which `ask` and the lexicon are taken out, serialisers to `csv_safe`, text catalogue taken out of `explain`, two app subpackages (`baseline/`, `debug/`), test kits | About 30 to 35 PRs of 400 lines at most, including 6 to 7 preliminary docstring PRs. One PR (`READINGS`) exceeds the budget (Q1). Import paths change in about 40 tests and about 30 doc files. | `cpm.py` stays a single rank C module (the engine, about 2000 lines). |
| **C. Full grouping by domain** | B, plus: `analysis/{engine,forensics,builtin,progress}/`, `app/{widgets,sidebar}/`, tests mirroring the code, test subfolders | More than 50 PRs. About 150 import sites in about 90 files, 6 configuration files indexed by path, 88 test paths cited in 52 files. | The gain is mostly cosmetic. Mirroring the tests would be arbitrary: 38 tests import only `analysis`, and many cross 3 or 4. The risk of a silently missed patch increases. |

## Proposed choice: option B

Sources:
- **ADR-0001 and `tests/test_architecture.py`.** Layers stay at the top and grouping is by feature within a layer. No feature package crosses layers. This is sometimes called "package by layered feature" (phauer.com); this wording could not be re-checked offline, and the rule rests on ADR-0001 in any case.
- **`scripts/same_code.py`.** A top-level definition moves unchanged. A class counts as a single definition, so `_Run` is not split. Known limit: within a function, `same_code` compares imports by the names they bring in, not by module. A relative import whose target changes silently is therefore not detected (see PR 7).
- **PEP 8.** Short subpackage names without underscores, and `__all__` for the public API.
- **PEP 420 and the packaging guide.** Each new code subpackage receives an ordinary `__init__.py`, empty apart from its docstring. `app/views/`, `sheets/`, `standards/` and `static/` stay folders without `__init__.py`.
- **pytest goodpractices.** This page recommends `--import-mode=importlib` for new projects. The `prepend` mode is kept nonetheless, because 41 `from conftest import` lines depend on it. `pythonpath = ["tests"]` is not added: with `prepend`, `tests/` is already on the path as long as the tests stay flat. The setting would only serve Q9, which is deferred.
- **`pickle` docs and caches.**
  - `Snapshot` crosses the `spawn` processes of `app/reading.py`, in memory only. A class is found there by its qualified name.
  - `reading.py` imports only `xerscope.store` and `xerscope.xer`. It is therefore enough that `xer/snapshot.py` imports without Streamlit.
  - No pickle is stored on disk, and there is neither `st.cache_data` nor a persistent cache indexed by module path.

Cross-cutting rule: **no compatibility shim at the old paths.**
- Test monkeypatches target module globals (`model.file_baseline`, `cpm._comparison`, `cli.LEXICON_MAX_BYTES`, `'xerscope.analysis.checks.run_metric'`, etc.). A shim would make them patch a copy with no effect, without any visible failure.
- An import kept only to re-export is also flagged by F401.
- Importers are therefore updated in the same PR.
- Only exception: the existing facades (`xer/__init__`, `analysis/__init__`, `analysis/query`), which keep re-exporting.
- `cli/__init__` imports from `common` only what it uses itself (`_expand`, `_write_csv`, `_add_*`, `_when`). It does not import `INPUT_ERROR`, which only `fail` uses: `test_cli.py:17-20` moves to `cli.common.INPUT_ERROR`.

## Verification (each PR)

```
uv run python scripts/same_code.py origin/main          # must list only moves; --ignore-docstrings only for a docstring PR
uv run python scripts/duplication.py                    # identical report before/after
uv run python scripts/fitness.py --check tests/fitness_baseline.json   # after --out regeneration if a key is new or renamed, justification in the PR
uv run pytest -n auto --dist loadfile                   # full suite
git diff --exit-code origin/main -- tests/golden/       # goldens unchanged
uv run pytest --collect-only -q | sed 's#^tests/[^:]*::##' | sort > nodes.txt   # same list before/after (test PRs)
uv run python scripts/oracle_report.py                  # same totals (test PRs)
uv run ruff check --select D <new modules>              # a new file has no per-file-ignores entry
```

Value justification (`check_value_justification.py`): `_worse` counts a new key from 0, or from rank A. Every moved or renamed module therefore requires, even for a pure move, a PR description line for each non-zero measure (`cc_max`, `cognitive_max`, and `mi_rank` if it is not A).

Additional checks depending on the area touched:
- **CPM and CLI crosscheck**:
  - `uv run pytest tests/test_crosscheck_mpxj.py tests/test_reference.py` with Java;
  - then `XERSCOPE_REQUIRE=reference,p6-corpus`, so that a wrong data path fails instead of being skipped.
  - The default CI never runs `xerscope crosscheck`: `test_cli.py` does not call it, and the MPXJ tests skip themselves without Java.
- **App**: `uv build --wheel` in the scratchpad, then compare `unzip -l` before and after. This checks that `.streamlit/`, `static/`, `style.css` and `gantt.js`/`gantt.css` are shipped.

---

## 1. Target tree

Legend:
- `=`: unchanged;
- `+`: new file (code moved byte-identical);
- `~`: keeps the same name but is slimmed;
- `>`: moved (old path -> new path);
- `(opt)`: optional, subject to decision.

```
src/xerscope/
├── __init__.py                      =
├── config.py                        =
├── csv_safe.py                      ~ receives Fmt, CSV_FLOAT_FORMAT, csv_bytes, _bytes, zip_frames (from export.py)
├── export.py                        ~ keeps export_tables, write_tables, zip_tables; imports Fmt and _bytes from csv_safe
├── anonymize.py                     =
├── store.py                         = (only the import lines change)
├── sample.py                        =
├── crosscheck.py                    = (opt: folded into verify/__init__, see Q5)
├── cli/                             > cli.py -> cli/__init__.py
│   ├── __init__.py                  ~ main, COMMANDS, _cmd_app, APP_PATH, other subcommands
│   ├── __main__.py                  + 2 lines and a docstring: keeps `python -m xerscope.cli` (see PR 7)
│   ├── common.py                    + fail, INPUT_ERROR, _expand, _add_*, _write_csv, _when
│   └── ask.py                       + ask-bench (L653-809) and lexicon (L811-993)
├── xer/
│   ├── __init__.py                  = (facade; its imports point to the new modules)
│   ├── parser.py                    =
│   ├── codes.py                     + tables STATUS…SCHEDULE_OPTIONS (L106-195), ScheduleOption, constraints_label (L196)
│   ├── values.py                    + _blank_to_na, forecast_dates, to_datetime, to_number, _parse_date, percent_complete,
│   │                                  _ensure_cols, _require, _warn_unknown_codes, _unique (L202-313), EARLIEST/LATEST_DATE
│   ├── snapshot.py                  + column lists TASK_DATE_COLS…LABOR_COLS (L41-105), column contracts,
│   │                                  CODE/UDF lists, FileBaseline, file_baseline, _chain, Snapshot
│   ├── projects.py                  + _task_table, _project_table (L314-339), baseline_copies, _select_project, _file_projects,
│   │                                  _data_date, projects_text, HEADER_TABLES, FileHeader, read_header
│   ├── model.py                     ~ _BuildInputs, build steps, _check_snapshot_columns, build_snapshot
│   ├── calendar.py                  =
│   ├── validate.py                  =
│   ├── pmxml.py                     = (opt: xer/pmxml/__init__.py + scan.py, see Q6)
│   └── pmxml_scan.py                =
├── verify/                          = (__init__, mpxj_reader, mpxj_cpm, p6_corpus, shapes)
├── analysis/
│   ├── __init__.py                  = (same import order: dcma, decm, integrity, p6)
│   ├── explain.py                   ~ L1-313: CheckResult -> Explanation, critical_definition
│   ├── readings.py                  + L314-981: source constants, SPI_WINDOW_READING, *_READING, READINGS, schedule_reading
│   ├── cpm.py                       ~ (opt) without critical_path_test, see PR 14
│   ├── critical_path.py             + (opt) critical_path_test, CptResult, _DelayOutcome and helpers (cpm.py:2268-2497)
│   ├── baseline.py, populations.py, wbs.py, task_filters.py, resource_placement.py,
│   │   rules.py, standards.py, checks.py, audit.py, integrity.py, evm.py, progress.py,
│   │   changelog.py, forensics.py, longest_path.py, baseline_resolution.py, query.py   =
│   ├── ask/ (13 modules)            =
│   └── dcma/, decm/, p6/            =
├── viz/                             = (charts.py, gantt.py, gantt.js, gantt.css)
├── app/
│   ├── __init__.py                  =
│   ├── streamlit_app.py, theme.py, style.css, static/, .streamlit/, views/ (11 pages)   =
│   ├── session.py, cache.py, downloads.py, sets.py, state.py, ui.py                    =
│   ├── glossary.py, table_filters.py, code_picker.py, explanation_panel.py, task_panel.py  = (opt widgets/, Q8)
│   ├── loading.py, files_window.py, baseline_warnings.py, reading.py                   = (opt sidebar/, Q8)
│   ├── baseline/                    +
│   │   ├── __init__.py              + (docstring only)
│   │   ├── baseline_file.py         > app/baseline_file.py
│   │   ├── baseline_export.py       > app/baseline_export.py
│   │   ├── baselines.py             > app/baselines.py
│   │   ├── baseline_window.py       > app/baseline_window.py
│   │   └── xml_baselines.py         > app/xml_baselines.py
│   └── debug/                       +
│       ├── __init__.py              + (docstring only)
│       ├── diagnostic.py            > app/diagnostic.py
│       ├── expected_finish_forms.py > app/expected_finish_forms.py
│       └── recalculation_departures.py > app/recalculation_departures.py
├── sheets/P6/*.md                   =
└── standards/*.toml                 =

tests/
├── conftest.py                      ~ fixtures, hooks, environment variables, hypothesis profiles
├── xerkit.py, rulekit.py, pmxmlkit.py, file_projects.py, asklex.py   =
├── appkit.py                        + AppTest helpers (conftest.py:101-220); APP, _ok, app (test_app); PAGES (test_page_golden)
├── evidencekit.py                   + missing, REFERENCE_HINT, P6_CORPUS_HINT, mpxj_or_skip (from conftest)
├── cpmkit.py                        + random_network (from test_cpm_properties)
├── evkit.py                         + planned, progressed, DAY_MIN, SHAPES, random_update (from test_earned_schedule, test_ev_contracts)
│                                      + EVM data from test_evm_weekly and test_evm_code_filter
├── codekit.py                       + GLOBAL_P1/P2, PROJECT_P1, _code_snapshot, _code_text, _label (from test_code_types_blind)
├── glossarykit.py                   + PAGES (from test_glossary; distinct list, without forensics)
├── pvkit.py, referencekit.py        + BASELINE, UPDATE, WED (test_pv_p6); REFERENCE_DATA, reference_names (test_characterization)
├── test_*.py (140)                  = flat (subfolders belong to Q9)
├── reference/, golden/, ask/        =
└── fitness_baseline.json, mutation_baseline.json   =
```

Reason for each move, in one line:
- `xer/model.py` -> `xer/codes.py` (tables, `ScheduleOption`, `constraints_label`): what 14 modules actually import, without pulling in the build internals.
- `xer/model.py` -> `xer/values.py`: the value readers are the common base; they are placed lowest to avoid cycles.
- `xer/model.py` -> `xer/snapshot.py`: the data contract read by `store`, `analysis` and `app`, column lists included (`store.py:18` imports `LABOR_COLS`, `ASSIGNMENT_COLS_MODEL` and `REL_COLS_MODEL`). `Snapshot` and `file_baseline` stay in the same module, because the monkeypatch requires it.
- `xer/model.py` -> `xer/projects.py`: project selection and the header form a distinct subject, with its own entry point `read_header`. `_task_table` and `_project_table` go with it, otherwise there is a `projects <-> model` cycle.
- `cli.py` -> `cli/__init__.py`: makes it possible to take the Ask logic out; the `LAYERS` key stays `cli`.
- `cli.py` -> `cli/common.py`: the shared helpers must leave `__init__` to avoid the `__init__` <-> `ask` cycle.
- `cli.py` -> `cli/ask.py`: about 340 lines of lexicon and benchmark logic, which stay in the cli layer (file writing, display).
- `export.py` -> `csv_safe.py` (serialisers): "the only CSV writer" according to its own docstring. `anonymize` no longer depends on `export` or on `store`.
- `analysis/explain.py` -> `analysis/readings.py`: a split by consumer (the app pages), not by standard.
- `app/{baseline_*,baselines,xml_baselines}.py` -> `app/baseline/`: the cross private imports stay within a single package. `BASELINE_DOMAIN` in `test_architecture` justifies it only in part, since it also contains `baseline_warnings`, which stays at the root.
- `app/{diagnostic,expected_finish_forms,recalculation_departures}.py` -> `app/debug/`: a trio without Streamlit (after 0d), used by the Debug page and by `cli pv-compare`.
- `tests/conftest.py:101-220` -> `tests/appkit.py`, and the shared names of the `test_*` -> kits: a test must not be a library. This is the prerequisite for any future move.

## 2. Files to split

| File | Content that leaves | Destination | Nature |
|---|---|---|---|
| `xer/model.py` L106-196 | P6 code tables, `ScheduleOption`, `constraints_label` | `xer/codes.py` | pure move, preceded by a docstring PR (D205, D102: L141, L152) |
| `xer/model.py` L202-313 | value readers, `_ensure_cols`, `_require`, `_unique`, `_warn_unknown_codes` (same names) | `xer/values.py` | pure move, preceded by a docstring PR (D205, D209, D103, D401: L207, L221, L307, L362) |
| `xer/model.py` L41-105 and L392-513 except `_check_snapshot_columns` (L476) | column lists, column contracts, CODE/UDF lists | `xer/snapshot.py` | pure move |
| `xer/model.py` L514-692 and `_chain` (L799) | `FileBaseline`, `file_baseline`, `Snapshot` | `xer/snapshot.py` | pure move, preceded by a docstring PR (D102, D205, D209: L528-683) |
| `xer/model.py` L314-339, L999-1145, L1579-1617 | `_task_table`, `_project_table`, project selection, `_data_date`, `FileHeader`, `read_header` | `xer/projects.py` | pure move, preceded by a docstring PR (D205, D209, D401: L1000-1111, L1606) |
| `cli.py` | `fail`, `INPUT_ERROR`, `_expand`, `_add_*`, `_write_csv`, `_when` | `cli/common.py` | pure move |
| `cli.py` L811-993 | lexicon (`_build_lexicon`, `_lexicon_report`, `_purge_suggestions`, `_lexicon_export`, `LEXICON_MAX_BYTES`…) | `cli/ask.py` | pure move, preceded by a docstring PR (D205, D209, D401: L675-981) |
| `cli.py` L653-809 | ask-bench (`_anonymised_bench`, `_anonymised_case`) | `cli/ask.py` | pure move |
| `cli.py:16` | `APP_PATH`: `Path(__file__).parent` -> `.parent.parent` | `cli/__init__.py` | **one-line change**, flagged by `same_code`, to be announced |
| `cli.py`, 43 relative lazy imports | `from .export …`, `from .crosscheck …`, `from .app …`, etc. | absolute `from xerscope.…` | **import line changes**, invisible to `same_code`, to be announced and checked by grep |
| `export.py` L25 and L37-82 | `Fmt`, `CSV_FLOAT_FORMAT`, `csv_bytes`, `_bytes`, `zip_frames` | `csv_safe.py` | pure move; `export` re-imports `Fmt` and `_bytes` (private name) for `write_tables` and `zip_tables` |
| `analysis/explain.py` L314-981 | page text catalogue | `analysis/readings.py` | pure move in 3 PRs, bottom up, preceded by a **value change** PR (citations) and a docstring PR (D205, D209, D401: L447, L930, L954, L972) |
| `analysis/cpm.py` L2268-2497 (opt) | `critical_path_test` and its helpers | `analysis/critical_path.py` | pure move; `_Run`, `_early` and `_late` do not move |
| `tests/conftest.py` L101-220 | AppTest helpers; `missing` and the hints | `tests/appkit.py`, `tests/evidencekit.py` | pure move; `same_code` does not cover `tests/`, the proof comes from git rename detection and the list of collected nodes |
| 12 `test_*` modules imported by other tests | shared names | `cpmkit`, `evkit`, `appkit`, `codekit`, `glossarykit`, `pvkit`, `referencekit`; `test_file_baseline._series_and_export` to a kit or `appkit` | pure move (same proof) |

Docstring debt rule:
- pyproject says "A new file has no entry; … no line gains a rule", and CONTRIBUTING L203 says the same.
- A new module therefore has no `per-file-ignores` entry.
- `ruff --select D` on the code to move gives about 15 new pairs, while 7 remain under `MAX_DEBT` (267 allowed, 260 used).
- Each split is therefore preceded by a PR that fixes the docstrings of the code concerned, at its current location (`same_code --ignore-docstrings`). D209 is fixed automatically; D401 and D205 are fixed by hand.
- Alternative: move only code that already passes the D rules.

Splits that change code and therefore each have their own PR, still with no change of behaviour:
- `app/diagnostic.py:38` imports `as_dates` from `table_filters`: a single import, `same_code` stays green, and `APP_EDGES` is updated. Verified: importing `table_filters`, `expected_finish_forms` and `recalculation_departures` does not load streamlit.
- `analysis/task_filters.py:19` imports `fold` from `.ask.text` (one line).
- The `READINGS` texts cite functions or constants that exist (for example `SPI_WINDOW_READING`, `charts.<function>`) or lose their line numbers. **`charts.LABEL_DECIMALS` does not exist**: "three decimals" (`charts.py:248`) has no constant to name, and adding one would be a code change. This is a **displayed value that changes**: `test_readings` must be checked, and `pages.json` does not contain these texts.
- The docstring of `app/state.py:1` ("page kit"): docstring PR.

## 3. What does not move, and why

- **`app/streamlit_app.py`, `.streamlit/config.toml`, `static/`, `style.css`, `theme.py`, `views/`**:
  - Their paths are computed from `__file__` (`VIEWS`, `parents[2]`, `theme.STYLE`/`STATIC`) and from `cli.APP_PATH` (cwd). `config.toml` uses `app/static/...` URLs.
  - About 15 tests build `AppTest` from `app/streamlit_app.py`.
  - The page file names are URLs and the keys of `tests/golden/pages.json`. `scripts/accessibility.py` clicks `a[href$='/name']`.
- **`viz/`**: small and coherent. `gantt.js`/`gantt.css` must stay next to `gantt.py` (`files(__package__)`, `test_viz.py:346,368`).
- **`xer/calendar.py`**: indexed by path in the mutation baseline and in `[tool.mutmut] source_paths`.
- **`xer/parser.py`**: ADR-0002, fuzzing, 6 tests.
- **The `xer` layer name**: no `xer/formats/`. The name is fixed in `LAYERS`, in the fitness contracts and in ADR-0001, and it is used by about 74 imports.
- **`analysis/cpm.py` (class `_Run`)**:
  - It cannot be split by phase in a provable way: a class counts as a single definition in `same_code`, and mixins would come close to the "generic engine".
  - Its private names (`_Run`, `_Axes`, `_date_range`, `FLOAT_TYPE`…) are imported by `verify/mpxj_cpm.py` and by tests.
  - No `analysis/engine/`: about 45 imports would have to change, plus `LAYERS 'analysis.cpm'`, with no structural gain.
- **`analysis/{baseline,populations,rules,standards,checks,audit,wbs,task_filters,query}.py`**: almost everything imports them. `analysis.wbs.ROOT` is fixed in `LAYERS['viz']`, and `query.py` stays the Ask facade (about 19 importers).
- **`analysis/{p6,dcma,decm}/` and `integrity.py`**: a `builtin/` grouping would be cosmetic. It would touch 7 fitness keys with clones (read as "(new)" regressions), `LONG`, the per-file-ignores and the rule registration order.
- **`analysis/evm.py` and `progress.py`**: a split would force a cross import between packages (`progress` -> `evm` as a lazy import), and `progress.py` is in the mutation baseline. Taking `pv_p6_comparison` out remains possible later (about 500 lines of diff, two PRs).
- **`rules.py`**: `AnalysisContext` (about 24 importers) and the `@rule` functions are kept; they register at import in a given order (see Q7).
- **`anonymize.py`**: its rank C comes from one class. The only remedy is a method refactoring, out of scope. No `privacy/` package.
- **`config.py`, `store.py`, `sample.py`, `csv_safe.py` at the top**: a single responsibility each, already at rank A. Wrapping them in a package would change the `LAYERS` keys, the contracts and about ten citations, for nothing.
- **`app/session.py`, `cache.py`, `downloads.py`, `sets.py`, `state.py`**: the app root. Placing `cache` or `baseline_warnings` in `baseline/`, or `sets` in `widgets/`, would create a cycle between packages.
- **`app/ui.py`**: stays at the root. `runtime_table` computes `parents[1]` and `test_app.py:2885` uses the same formula, so an error would go unnoticed. The column and formatting splits are deferred (Q8).
- **`scripts/`**: 7 scripts, 1,267 lines, flat.
- **In `tests/`**:
  - `test_architecture.py`: imported by `fitness.py:40` and cited in the docs.
  - `test_p6_heldout.py`, `golden/`, `fitness_baseline.json`, `mutation_baseline.json`: paths hard-coded in `check_value_justification.py`, `CODEOWNERS` and `mutation.yml`.
  - `test_p6_checksched.py`: cited in the `source` field of `p6.toml`, hence in `pages.json`.
  - `test_crosscheck_mpxj.py`, `test_reference.py`: `tests.yml:168`.
  - `reference/`: CI cache keys, CONTRIBUTING, `cli.py`, `dcma.toml`.
  - `test_app.PAGES` (`"views/*.py"`, with forensics): no other test imports it, it stays in `test_app`.
- **No `__init__.py` in `tests/`**: otherwise `reference` would become `tests.reference`.
- **Package data, page paths, mutation baseline**: hatch ships everything under `src/xerscope`. `standards`, `sheets`, `files(__package__)` in viz, the `views/` path, `pages.json` and the mutation baseline are not touched by the moves. The CI `src/` filter (`tests.yml:185`) covers the new paths.

## 4. Move constraints and risks

To update **in the same PR** as the move:

1. **`tests/test_architecture.py`**:
   - `LAYERS` is checked by exact equality, in both directions.
   - With PR 1:
     - `anonymize` goes from `{'xer','export'}` to `{'xer','csv_safe'}`;
     - `csv_safe` receives an entry if the serialisers import `config`;
     - `app` gains `csv_safe` (`downloads`, `views/health`, `views/debug`) and keeps `export` because of `views/export`;
     - `cli` gains `csv_safe` (`_write_csv`).
   - `LAYERS['cli']` already contains `verify`: folding `crosscheck` (Q5) only requires removing `crosscheck`.
   - With PR 15, `cli` points to `'app.debug.diagnostic'` (prefix).
   - `APP_EDGES` must first be rewritten to handle subpackages (PR 0b):
     - dotted-path keys;
     - `rglob` excluding `views/`;
     - `app_modules` must no longer use `split('.')[2]`.
   - The DAG covers only the **sibling subpackages** (`baseline`, `debug`), without the app root: `app/baseline/*` imports root modules (`session`, `ui`), and root modules (`cache`, `state`, `loading`, `files_window`, `baseline_warnings`, `downloads`) import `baseline/*`. A DAG including the root would fail immediately.
   - A stale `app.diagnostic` rule would silently fall back to "all of `xerscope.app` is allowed".
2. **`tests/fitness_baseline.json`**:
   - Keys are relative to `src/xerscope`. A moved module is judged as new (compared with 0 or rank A).
   - Each move PR therefore regenerates the baseline with `--out` and justifies each non-zero measure of the new keys (`cc_max`, `cognitive_max`) in the description.
   - `cli/__init__.py` stays at rank C during PRs 7 to 9: without regeneration in the same PR, `fitness --check` fails with "(new) mi_rank: C".
   - The baseline is already stale (see PR 0a).
3. **`pyproject.toml`**:
   - The `src/...` keys of `[tool.ruff.lint.per-file-ignores]` must exist (`test_docstrings.py:84`). A new file has no entry, and a line gains no rule (see §2).
   - On the `cli.py` -> `cli/__init__.py` rename, the existing entry is renamed, with no new rule.
   - `[tool.mutmut]`: `source_paths` does not change here. `pytest_add_cli_args_test_selection` lists 15 tests by path, and only the weekly job checks them.
   - No `pythonpath` (see the sources).
4. **`tests/test_docstrings.py`**:
   - The `LONG` keys are `path:qualname` (for example `analysis/cpm.py:_late`, `xer/calendar.py:TimeAxis`). None of the functions moved by PR 14 is in `LONG`.
   - Dotted citations keep passing but become wrong. They are fixed in a docstring PR (`same_code --ignore-docstrings`):
     - `` ``xer.model.leveled`` `` in `app/diagnostic.py:602`;
     - `` ``xer.model.ScheduleOption`` `` in `analysis/changelog.py:408`;
     - `` ``xer.model._labor_hours`` `` in `analysis/baseline.py:90`;
     - `` ``cli._write_csv`` `` in the module docstring of `csv_safe.py`, after PR 8.
5. **`tests/test_sheets.py`**:
   - L18 reads only `xer/model.py`: it must read all `xer/*.py` before the codes are moved (PR 0c).
   - L19 is not recursive: an `rglob` is needed before any future test subfolder.
6. **Tests that pin file names**:
   - `tests/test_downloads.py:148-160` requires the only `.to_csv(` to be in `export.py:`. To update in PR 1 (`csv_safe.py:`).
   - `tests/test_lexicon.py`: `P6_NAMES` is indexed by `path.relative_to(APP)` (`"diagnostic.py"` at L24, `"baseline_window.py"` at L40). It must change to `debug/diagnostic.py` in PR 15 and to `baseline/baseline_window.py` in PR 16. Otherwise the P6 phrases are no longer exempted and `test_the_interface_speaks_the_lexicon` fails.
   - `tests/test_docker.py:113` takes `"src/xerscope/cli.py"` as an example path. It still passes the `src/` filter but becomes stale: to update in PR 7.
   - `tests/test_cli.py:17-20`: `cli.INPUT_ERROR` -> `cli.common.INPUT_ERROR` (PR 8). `tests/test_downloads.py:126` (`from xerscope.cli import _write_csv`) still resolves, since `__init__` uses `_write_csv`. It can be pointed to `cli.common` in the same PR.
7. **Monkeypatches** (the target follows the name, never a shim):
   - `model.file_baseline` -> `snapshot.file_baseline`;
   - `cli.LEXICON_MAX_BYTES` and `cli._lexicon_export` -> `cli.ask.*`;
   - `cli.subprocess` stays valid as long as `_cmd_app` is in `cli/__init__`;
   - `xerscope.xer.read_pmxml_baseline` and `xerscope.xer.pmxml._index_by_parsing` do not change;
   - app targets (`session.load_snapshot`, `baselines._file_baseline`, `baseline_export.resolutions`, `downloads.index_pmxml`…): the module moves with the name, so the target string is updated.
8. **Relative imports and paths computed from `__file__`**: `same_code` sees neither a relative import whose target changes (it compares imported names, not the module) nor a computed path.
   - Check at each PR that renames a module into a package: `git grep -nE 'from \.[a-z]' -- src/xerscope/cli/`. Only `.common` and `.ask` may remain.
   - Paths to check: `cli.APP_PATH` and the cwd of `test_docker.py:293`, `ui.runtime_table`, `theme`, `streamlit_app`.
9. **Pickle**: `Snapshot` goes through the `spawn` workers, and `xer/snapshot.py` must import without Streamlit, which is the case. `reading.py` imports only `store` and `xer`, so the `__init__.py` files of `app/baseline/` and `app/debug/` have no effect on the workers. They are kept empty on principle, not for this reason. No pickle or cache is indexed on a module path.
10. **Package data**: nothing moves. Checked by `uv build` and `unzip -l` before and after the app PRs.
11. **Docs**, updated by hand, since only the `src` docstrings are checked:
    - CONTRIBUTING "Where a change goes" (L119-128);
    - `docs/architecture.md` §1-5, §7 (the "Import edges" paragraph changes together with `APP_EDGES`), the layer table and "Layer rules";
    - ADR 0001, 0002, 0003, 0004, 0006, 0009, 0012, 0014-0016, 0019-0024, depending on the module;
    - `docs/formulas.md`, `docs/cpm.md`, `README.md` (tree L358), `SECURITY.md` (csv_safe);
    - comments (`config.toml`, `charts.py`, `anonymize.py:140`, `model.py:501`).
    - Method: `git grep -n '<old path>'` in each PR.
12. **Displayed texts**: `analysis/explain.py:501` displays `` `export.export_tables` ``, so `export_tables` does not move. `app/ui.py:229` cites `explain.py`, and the citation stays true: `critical_definition` (L297) stays in `explain.py`.
13. **Order and cycles**:
    - `model.py` is split bottom up: codes, values, snapshot (columns, then class), projects (with `_task_table`/`_project_table`), and `model` keeps the build and `_check_snapshot_columns`. Each module imports only those before it. `model` imports `projects`, never the reverse.
    - `cli`: `common` leaves before `ask`, otherwise there is a cycle with `__init__`.
    - `readings` leaves bottom up (tail, then `READINGS`, then constants), so that `readings` imports `explain` without the reverse ever happening. No definition crosses the L313/314 boundary in either direction.
    - The rules register in the same order in `analysis/__init__.py`.

**Risks**:
- A silently missed patch if a shim is added (hence the ban).
- A relative import that changes target silently (PR 7): hence the rewrite to absolute and the grep check.
- Missing test data causing a *skip* instead of a failure: use `XERSCOPE_REQUIRE`.
- The MPXJ tests skipped without Java: run the `crosscheck` job.
- The docstring debt budget (7 pairs): hence the preliminary docstring PRs.
- `cli/__init__` measures about 19.5 MI after extraction: rank A, but close to the limit.
- The weekly mutation CI is the only safeguard on the `mutmut` paths.
- The honest cost: about 40 test files and about 30 doc files see their import paths or citations change. Only the facades (`xerscope.xer`, `xerscope.analysis`, `xerscope.cli:main`) stay stable.

## 5. Ordered PR plan

Size: a moved block counts twice, and the sizes given include removals and additions. All PRs pass the common verification above; only the checks specific to each PR are listed here. "Docs" means a docstring PR (`same_code --ignore-docstrings`) on the code that will move, at its current location.

**Phase 0: prerequisites, no move**

| # | PR | Diff | Own verification |
|---|---|---|---|
| 0a | Regenerate `fitness_baseline.json`: remove `app/views/activity.py`, add the 18 missing modules (`xer/pmxml_scan.py`, several app modules…), update the stale values (`xer/model.py` MI 7.4 -> 4.4, `app/baselines.py` C -> A (46.5), `analysis/explain.py` MI 38.7 -> 25.05) | about 40 (baseline) + about 36 lines of justification | `fitness --check` green; `check_value_justification` green |
| 0b | `test_architecture` handles app subpackages (dotted keys, `rglob`, DAG between sibling subpackages only, root excluded), plus `docs/architecture.md` §7 | about 60-80 | `pytest tests/test_architecture.py`; contracts unchanged (`import_contracts_broken` = 0) |
| 0c | `test_sheets` reads all `xer/*.py` and switches to `rglob` | about 6 | same list of collected nodes; same `oracle_report` totals |
| 0d | `diagnostic` imports `as_dates` from `table_filters`; `APP_EDGES['diagnostic']`; doc §7 | about 10 | `python -c "import xerscope.app.diagnostic, sys; assert 'streamlit' not in sys.modules"`; `same_code` green |
| 0e | `task_filters` imports `fold` from `.ask.text` | about 2 | `same_code` green |
| 0f | `READINGS` texts: the 15 `file:line` citations become names of existing functions or constants, or lose their line numbers (no `LABEL_DECIMALS`, no constant added) | under 40 | `pytest tests/test_readings.py tests/test_page_golden.py`; `git diff tests/golden` empty; each changed value listed in the PR |
| 0g | Dotted `xer.model.*` docstrings fixed where the target is already known, plus the docstring of `app/state.py` | about 10 | `same_code --ignore-docstrings` |

**Phase 1: core**

| # | PR | Diff | Own verification |
|---|---|---|---|
| 1 | `Fmt`, `CSV_FLOAT_FORMAT`, `csv_bytes`, `_bytes`, `zip_frames`: `export.py` -> `csv_safe.py`; `export` re-imports `Fmt` and `_bytes`; importers (`anonymize`, `cli`, `app/downloads`, `views/health`, `views/debug`); `views/export` keeps `from xerscope.export import Fmt…`, resolved by the re-import (or point it to `csv_safe`); `LAYERS` (`anonymize`, `csv_safe`, `app`, `cli`); `test_downloads.py:148-160`; architecture.md, ADR-0022/0023, SECURITY.md | about 180 | `pytest tests/test_anonymize* tests/test_downloads.py tests/test_export*` |
| 2a | Docs: D205, D102 in the code tables | about 10 | `ruff --select D` on the range |
| 2 | `xer/codes.py` (L106-196); about 12 importers; no per-file-ignores entry | about 300 | `test_sheets` green; `ruff --select D src/xerscope/xer/codes.py` |
| 3a | Docs: D205, D209, D103, D401 in the value readers | about 15 | same |
| 3 | `xer/values.py` (L202-313, private helpers under the same name); `test_audit_edges_xer`, `test_time_semantics` | about 260 | no cycle (`python -c "import xerscope.xer"`) |
| 4 | `xer/snapshot.py`: column lists (L41-105), column contracts and CODE/UDF lists (L392-513 except `_check_snapshot_columns`, which stays in `model.py`); `store.py:18`; `test_store` | about 380 | `pytest tests/test_store.py`; no new mypy error |
| 5a | Docs: D102, D205, D209 in `FileBaseline`/`Snapshot` (L528-683) | about 20 | same |
| 5 | `xer/snapshot.py`: `FileBaseline`, `file_baseline`, `_chain`, `Snapshot`; monkeypatch target of `test_file_baseline:709` | about 400 | `pytest tests/test_file_baseline.py tests/test_reading.py` (pickle spawn) |
| 6a | Docs: D205, D209, D401 in project selection (L1000-1111, L1606) | about 15 | same |
| 6 | `xer/projects.py`, with `_task_table` and `_project_table`; `store` (`projects_text`); `test_audit_edges_xer`; CONTRIBUTING L119-121, ADR 0001-0004/0006/0012 (or doc PR 6b if the diff overflows) | about 400 | no `projects <-> model` cycle; `fitness`: `xer/model.py` goes from C to A |

**Phase 2: CLI**

| # | PR | Diff | Own verification |
|---|---|---|---|
| 7 | `git mv cli.py cli/__init__.py`; the 43 relative imports become absolute `from xerscope.…` (17 of them will then leave for `cli/ask.py`); `APP_PATH` becomes `.parent.parent`; add `cli/__main__.py` (docstring + `raise SystemExit(main())`) to keep `python -m xerscope.cli`, and remove the `if __name__ == "__main__"` block at L1036, now dead; `test_docker.py:113`; fitness key and per-file-ignores renamed; baseline regenerated (rank C justified) | about 100 | `pytest tests/test_cli.py tests/test_docker.py`; `xerscope app --help`; `python -m xerscope.cli --help`; `xerscope crosscheck` with Java; `git grep -nE 'from \.[a-z]' src/xerscope/cli/` empty; `same_code` flags only `APP_PATH`, the `__main__` block and the imports, all announced |
| 8 | `cli/common.py` (helpers), imported by `__init__` for what it uses; `test_cli.py:17-20` -> `cli.common.INPUT_ERROR`; baseline regenerated | about 130 | `pytest tests/test_cli.py tests/test_audit_edges_app.py tests/test_downloads.py`; `ruff` without F401 |
| 9a | Docs: D205, D209, D401 in L675-981 | about 20 | same |
| 9 | `cli/ask.py`: lexicon; targets `cli.ask.LEXICON_MAX_BYTES` and `cli.ask._lexicon_export`; baseline regenerated | about 380 | `pytest tests/test_cli.py tests/test_lexicon.py` |
| 10 | `cli/ask.py`: ask-bench; `csv_safe` docstring (`cli.common._write_csv`); ADR 0014/0020-0024 and docs | about 340 | `pytest tests/test_ask_bench.py tests/test_cli.py`; `fitness`: MI of `cli/__init__` above 19, rank A |

**Phase 3: analysis** (bottom up, `readings` imports `explain` and never the reverse)

| # | PR | Diff | Own verification |
|---|---|---|---|
| 11a | Docs: D205, D209, D401 (L447, L930, L954, L972); docstrings of `viz/charts.py:74` and `test_page_golden.py:42` | about 15 | `same_code --ignore-docstrings` |
| 11 | `analysis/readings.py`: tail L917-981 (`TSPI_*`, `schedule_reading` and its helpers); tests (`test_schedule_reading`, including the string `'explain.schedule_reading'`) | about 150 | goldens unchanged; `pytest tests/test_explain.py tests/test_schedule_reading.py` |
| 12 | `READINGS` alone (a single assignment, L505-914, 410 lines), impossible to cut at a definition boundary; 7 views, `app/ui` | about 840 (**over budget, Q1**) | goldens unchanged; `pytest tests/test_readings.py`; `same_code` |
| 13 | Constants and readings L314-504 (`P6`, `EVMS`…, `SPI_WINDOW_READING`, `*_READING`); remaining importers | about 400 | goldens unchanged; `pytest tests/test_readings.py tests/test_explain.py` |
| 14 (opt) | `analysis/critical_path.py` (`critical_path_test`, L2268-2497); `rules.py:46`; 2 tests; docs/cpm.md (no `LONG`) | about 460, so over budget: to cut in 2 or to submit to Q1 | `pytest tests/test_cpm*.py tests/test_rules.py`; `test_crosscheck_mpxj` with Java |

**Phase 4: app** (after 0b and 0d)

| # | PR | Diff | Own verification |
|---|---|---|---|
| 15 | `app/debug/` (the trio); `LAYERS['cli']` becomes `'app.debug.diagnostic'`; `cli/__init__` pv-compare; about 26 test imports; `test_lexicon.py` (`"debug/diagnostic.py"`) | about 160 | `pytest tests/test_diagnostic.py tests/test_cli.py tests/test_lexicon.py`; wheel identical apart from paths |
| 16 | `app/baseline/` (5 modules); `APP_EDGES`; about 30 src and test imports; monkeypatch targets (`baselines._file_baseline`, `baseline_export.resolutions`); `test_lexicon.py` (`"baseline/baseline_window.py"`); doc §7, README | about 260 | `pytest tests/test_app*.py tests/test_file_baseline.py tests/test_baseline_*.py tests/test_pmxml.py tests/test_lexicon.py`; goldens |

**Phase 5: tests** (proof by git rename detection, the node list and `oracle_report`)

| # | PR | Diff | Own verification |
|---|---|---|---|
| 17 | AppTest helpers of `conftest.py` (L101-220) -> `appkit.py`; `missing` and the hints -> `evidencekit.py`; about 30 importers (`test_oracle_report` keeps `import conftest` for the hook) | about 300 | identical node list; `XERSCOPE_REQUIRE=reference,p6-corpus pytest` |
| 18 | `cpmkit.random_network`; 5 importers | about 100 | same |
| 19 | `evkit`: `test_earned_schedule`, `test_ev_contracts`, plus the data of `test_evm_weekly` (imported by `test_app:776`) and of `test_evm_code_filter` (`test_app:713`) | about 250 | same |
| 20 | `appkit`: `APP`, `_ok`, `app` (from `test_app`) and `PAGES` (bare names, from `test_page_golden`, whose `APP` is identical); `glossarykit.PAGES` (from `test_glossary`, without forensics) for `test_widget_help:15`; importers `test_widget_help`, `test_readings`, `test_table_contract` | about 150 | same |
| 21 | `codekit` (`test_code_types_blind` -> `test_app`, `test_ask_ambiguous_codes_blind`, `test_query` ×2); `pvkit` (`test_pv_p6` -> `test_cli` ×2) | about 200 | same |
| 22 | `referencekit` (`test_characterization` -> `test_audit:12`); `test_file_baseline._series_and_export` -> kit (`test_baseline_per_page`) | about 150 | same; after this PR, `git grep -nE '(from\|import) test_' tests/` is empty |

The three `PAGES` lists are different and cannot live byte-identical in a single module: `test_app.PAGES` stays in `test_app` (no other test imports it), `test_page_golden.PAGES` goes to `appkit`, and `test_glossary.PAGES` goes to `glossarykit`.

Out-of-series fix, to place anywhere: `scripts/accessibility.py:41`, page list (remove `activity`, add `forensics`). This is a tool fix, not a move.

## 6. Open questions for the maintainer

1. **400-line budget for a pure move.**
   - PR 12 (`READINGS`, a single 410-line assignment, about 840 lines of diff) cannot be cut.
   - PRs 5, 6, 9, 13 and 14 are at the limit or above.
   - Can up to about 850 lines of diff be accepted when `same_code.py` proves there are only moves? Otherwise, `READINGS` stays in `explain.py` and `readings.py` receives only the rest.
2. **Re-exports in `xer/model.py`.** The proposal updates the importers (about 40 src and test files across PRs 2 to 6) and keeps none, because of the monkeypatches and F401. Would you rather the unpatched importers go through the `xerscope.xer` facade instead?
3. **P11a.** `docs/refactor-front-plan.md` sends `diagnostic` to `analysis/`, but `analysis` is not allowed to import `config` (`DEFAULT_SETTINGS`). Three choices:
   - (A) `app/debug/`, keeping the `cli -> app.debug` edge (proposed);
   - (B) a new top-level `diagnostic/` layer that imports `{xer, analysis, config}`, after moving `as_dates` into `xer` (2 to 3 PRs);
   - (C) an ADR that allows `analysis -> config`.
   The P11a plan must be amended in every case.
4. **CLI split.** Stop at `common` and `ask` (proposed, `cli/__init__` goes to rank A), or go as far as one module per subcommand group (4 more PRs, small gain)?
5. **`crosscheck.py`.** Keep it, or fold it into `verify/__init__.py` (about 60 lines; first check that `verify` does not start jpype at import)? `LAYERS['cli']` already contains `verify`.
6. **`xer/pmxml/`** (`__init__.py` and `scan.py`), which would preserve all `xerscope.xer.pmxml` paths: do it or not? The gain is small.
7. **`rules.py`.** Should the shared helpers (L727-850) be separated into their own module, which would remove the `rules -> cpm` import? The rule registration order would not change.
8. **`app/widgets/` and `app/sidebar/`, splits of `ui.py`** (columns and pure formatting without Streamlit): to do after PRs 15 and 16, or to drop? They cost at least 4 PRs, and `runtime_table` must first leave `ui`.
9. **Subfolders of `tests/` by theme** (`cpm/`, `app/`, `rules/`, `ev/`, `query/`, but not `ask/`, which is a data folder; no folder name may shadow a top-level import).
   - Once the kits are in place (PRs 17 to 22), it is feasible.
   - Cost: 88 paths cited in 52 files, the `mutmut` selections, the per-file-ignores of 4 tests, about ten files that must stay at the top, and `pythonpath = ["tests"]` or `importlib` at that point.
   - Proposal: do not do it now.
10. **Names in subpackages**: keep `app/baseline/baseline_file.py` (proposed, grep search does not change) or remove the redundant prefix (`app/baseline/file.py`)? `same_code` allows it, but all citations and the `test_lexicon` keys change.
11. **`analysis/critical_path.py` (PR 14)**: do it? `cpm.py` stays at rank C whatever happens. The only gain is taking a self-contained block of about 230 lines out of the engine file.
12. **`cli/__main__.py` (PR 7)**: add it to keep `python -m xerscope.cli` (proposed, no use found in the repository, but it is the current behaviour), or accept the loss and announce it?

## Review corrections

All corrections were re-checked at `dd6c71b`, and none was rejected. Points 13 and 14 are accepted with one nuance each.

1. **PR 7 and the relative imports.**
   - The 43 relative lazy imports of `cli.py` (L59, 403, 435, 459, 514, 533, 570, 594…) become absolute imports in PR 7. Its diff goes from about 20 to about 100 lines.
   - Added the grep check (`from \.[a-z]` forbidden outside `.common` and `.ask`) and a run of `xerscope crosscheck` with Java.
   - The `same_code` limit on these imports is explained.
   - Added a `cli/__main__.py` and removal of the dead block at L1036, announced in the PR (new question 12).
2. **Docstring debt.**
   - The "minimal per-file-ignores" are removed: a new file has no entry.
   - Added docstring PRs 2a, 3a, 5a, 6a, 9a and 11a before each split concerned, with the rules reported by `ruff --select D`.
3. **`projects <-> model` cycle.** `_task_table` and `_project_table` (L314-339) go to `projects.py` with `read_header`. `model` imports `projects`, never the reverse.
4. **Slices of `model.py`.**
   - The column lists (L41-105, including `LABOR_COLS` used by `store.py:18`) go to `snapshot.py`.
   - `codes` covers L106-196, `ScheduleOption` and `constraints_label` included; `values` covers L202-313.
   - `_check_snapshot_columns` stays in `model.py`, which avoids a `TYPE_CHECKING` import and a mypy error.
5. **`readings`.**
   - The tail starts at L314 and covers 667 lines, i.e. about 1330 lines of diff.
   - `READINGS` (L505-914) becomes a PR on its own, over budget (Q1).
   - The PRs follow the bottom-up order to avoid a transient `explain <-> readings` cycle.
   - Point 11 of §4 is settled: `critical_definition` stays, and `ui.py:229` stays true.
6. **PR 0f.** `charts.LABEL_DECIMALS` is removed, since it does not exist. The 15 `file:line` citations are listed, and the PR cites existing names or removes the numbers, without adding a constant.
7. **PR 1.**
   - `Fmt` also goes to `csv_safe`, and `export` re-imports `Fmt` and `_bytes`.
   - `test_downloads.py:148-160` is updated.
   - `LAYERS` gains `csv_safe` for `app` and for `cli`; `app` keeps `export`.
8. **Phase 5.**
   - The 7 remaining test modules are covered (PR 19 widened, new PRs 21 and 22, kits `codekit`, `glossarykit`, `pvkit`, `referencekit`).
   - The three `PAGES` stay distinct.
   - The `conftest` helpers are at lines 101-220.
9. **`tests/test_lexicon.py`** (`P6_NAMES` keys) is added to PRs 15 and 16.
10. **PR 0b DAG.**
    - The DAG now covers only the sibling subpackages, without the root.
    - The justification by `BASELINE_DOMAIN` is qualified, since `baseline_warnings` stays at the root.
11. **`INPUT_ERROR`.**
    - The `cli/__init__` exception is removed for `INPUT_ERROR`, which would have been an unused import, hence a shim.
    - `test_cli.py:17-20` moves to `cli.common.INPUT_ERROR`.
12. **Fitness.**
    - Justification required for each non-zero measure of a moved key.
    - The baseline is regenerated in PRs 7 to 9 (`cli/__init__` at rank C).
    - PR 0a: about 36 lines of justification and the stale values (`model` 7.4 -> 4.4, `baselines` C -> A, `explain` 38.7 -> 25.05).
13. **pytest and phauer sources.**
    - pytest recommends `importlib`. `prepend` is kept because of the `from conftest import` lines: 41 counted here, 42 according to the review.
    - `pythonpath = ["tests"]` is removed from PR 0c and deferred to Q9.
    - The phauer.com citation is marked as not re-checked.
14. **Pickle.** The reasoning is corrected: `reading.py` imports only `store` and `xer`, and no pickle or cache is indexed on a module path. The "empty `__init__`" rule is kept on principle only.
15. **Small points.**
    - The sentence "`cli` depends on `verify` if `crosscheck` is removed" is deleted, since `verify` is already in `LAYERS['cli']`.
    - PR 14: no more `LONG` update, the range starts at L2268, and its about 460 lines exceed the budget.
    - `test_docker.py:113` is updated in PR 7, and the `csv_safe` docstring (`cli._write_csv`) in PR 10.
