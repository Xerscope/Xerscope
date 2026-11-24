# ADR-0001: Layered architecture with one-way data flow (xer -> store -> analysis -> viz -> app, cli on top)

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`49ad764`, initial commit: the one-way data flow of `docs/architecture.md`); enforced from 2026-11-06 (`4d841b9`, #121) |
| Scope | every Python module of `src/xerscope`: `xer/`, `store.py`, `export.py`, `csv_safe.py`, `anonymize.py`, `analysis/`, `viz/`, `verify/`, `crosscheck.py`, `sample.py`, `app/`, `cli.py`, `config.py` (the data folders `standards/` and `sheets/` hold no Python and no layer rule) |
| Sources | `4d841b9` "Reference tests skip without the fetched files; layer rules match the imports (#121)"; `930af13` "Fitness ratchet: complexity, maintainability, duplication, layers, dependencies (#149)"; `330647d` "refactor(front): state.py split by concern, one direction of imports"; `f65a16a` "P6d: the pages import each name from its module; the app's import graph guarded"; `d50b380` "Architecture test: every import form of an app module, every module listed"; `docs/architecture.md` (data-flow diagram, "Layer rules", §7 "Import edges") |

## Context

xerscope turns weekly Primavera P6 exports into numbers that a planner compares with P6 and
with a standard. A wrong number is only fixable if its computation lives in one known place.
The data has a natural direction:

```
.xer bytes ─▶ parser ─▶ RawXer ─▶ model ─▶ Snapshot ─▶ SnapshotStore ─▶ analyses ─▶ pages / CLI / Power BI
             (format)            (P6 meaning)      (weekly series)
```

Three forces push against that direction:

- a page is the quickest place to add a figure, so computations drift into `app/views/`;
- a written layer rule drifts from the code: before #121 the "Layer rules" of
  `docs/architecture.md` said `analysis/` imported `config.py` and `viz/` imported `config.py`
  only, while the code had `viz/gantt.py` reading `analysis.wbs.ROOT`, `analysis/` never reading
  `config.py`, and `sample.py` was not listed (`4d841b9`);
- inside `app/`, `state.py` re-exported every name the pages read, so the import graph showed
  "every page depends on state" and hid who depends on the baseline domain, the caches, the
  loading or the downloads; a cycle through `state.py` could pass unseen (`f65a16a`). The test
  itself read only `from xerscope.app.<module> import ...`, so the 22 imports written
  `from xerscope.app import ui` were invisible to it (`d50b380`).

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Layer rules written in `docs/architecture.md` only, checked in review | none | drifted from the code before #121 (above); a reviewer cannot see a new import edge in a diff of a page |
| A package-level rule only ("nothing outside `app/` imports `app/`") | one assertion | says nothing of `viz/` computing, `analysis/` reaching `verify/`, or the app's internal graph |
| Every layer's cross-layer imports listed exactly in a test, the app's internal edges listed exactly, and import-linter contracts generated from the same list (chosen) | a test and a generated configuration to keep in step with the doc | a new edge needs a change in three places (doc, `LAYERS` / `APP_EDGES`, code); `app/views/` is not a regular package, so import-linter cannot see it |

## Decision

Data flows one way, from the file to the pages, and each layer imports only the layers below
it. `LAYERS` in `tests/test_architecture.py` is the single list; it holds, for each layer,
**exactly** what it imports from the other layers:

| Layer | Imports (exactly) |
|---|---|
| `xer/` | `config` |
| `store.py` | `xer`, `config` |
| `export.py` | `store`, `config`, `csv_safe` |
| `anonymize.py` | `xer`, `export` |
| `analysis/` | `xer`, `store` (never `viz/`, `app/` or `verify/`) |
| `viz/` | `config` and, of `analysis/wbs.py`, the constant `ROOT` only: it draws frames, it does not compute schedule results |
| `verify/` | `xer`, `analysis.cpm`, `config`; nothing in the app depends on it |
| `crosscheck.py` | `verify` (re-exports it) |
| `sample.py` | `xer`, `analysis.cpm`, `config` |
| `app/` | `xer`, `store`, `analysis`, `viz`, `export`, `anonymize`, `config`; imported by nothing but Streamlit and `cli.py` |
| `cli.py` | `xer`, `store`, `analysis`, `export`, `sample`, `verify`, `crosscheck`, `anonymize`, `config` and, of `app/`, `app.diagnostic` only (`pv-compare` reads the same frames as the Debug page); not `viz/` |

`csv_safe.py` imports nothing of xerscope. `config.py` (`Settings`, `DATE_FMT`, `DATETIME_FMT`)
is read from below.

Inside `app/`, `APP_EDGES` in the same test lists, for every module of `app/` (one entry each),
exactly the app modules it imports. The rules it encodes:

- `ui` is the shared look any module may read, and reads only `glossary`, `table_filters` and
  `theme`;
- the baseline domain (`baseline_file`, `baseline_export`, `baselines`, `baseline_window`,
  `baseline_warnings`) never reads `state`, `loading`, `downloads` or (except `baseline_warnings`)
  `cache`;
- `state.py` holds only the page-level pieces (context banner with its baseline-rule labels
  `BASELINE_RULES` / `checks_rule`, page header, the baseline warnings under it
  (`state.baseline_warnings`, not the module `baseline_warnings.py`), `snapshot_picker` /
  `compare_picker`, `require_store`, `standards`, `go_to` / `open_in_gantt`) and is imported by
  the pages only (the test would also allow `streamlit_app`, which does not import it); every
  other name a page reads is imported from the module that defines it;
- no app module imports a page (`app/views/`), no page imports another, and the graph has no
  cycle.

The edges are written in prose in `docs/architecture.md` §7 (Import edges); `CONTRIBUTING.md`
"Where a change goes" names, per kind of change, the module it goes in and where it never goes
(a chart in `viz/`, never `app/views/`; a page composes analyses and figures, never a
calculation).

## Consequences

- Each concern has one place: a P6 meaning in `xer/model.py`, a check in `analysis/`, a chart
  in `viz/`, a page in `app/views/`. A reviewer finds a number's computation without reading
  the pages.
- `analysis/` and `verify/` can be tested without Streamlit; the background readers
  (`app/reading.py`) import no Streamlit.
- A new cross-layer or app-internal import fails the test until `LAYERS` / `APP_EDGES` and the
  doc say the same: a change of edge is a visible decision in the diff.
- Known departures, kept visible: `app/diagnostic.py` and `app/expected_finish_forms.py` still
  sit in `app/` although `cli.py` reads `app.diagnostic` (`docs/refactor-front-plan.md`, P11a,
  Open); `INDEX_ALERT` and `PPC_TARGET` are still constants of `viz/charts.py`; computations
  remain inside some views (changelog, health, ppc, gantt), listed in `docs/backlog.md`,
  Structure.
- import-linter reads regular packages only: `app/views/` (Streamlit pages, no `__init__.py`)
  is checked by `tests/test_architecture.py` alone.

## Verification

- `tests/test_architecture.py::test_layer_imports_match_the_architecture_doc`: walks every
  import of `src/xerscope` (AST, relative imports resolved), compares each layer's cross-layer
  imports with `LAYERS` both ways (an unused rule fails too), and asserts that `cli` is the only
  importer of `app/`.
- `tests/test_architecture.py::test_every_form_of_an_import_of_an_app_module_is_read`: the
  import reader sees `from xerscope.app import ui`, `from xerscope.app.session import ...`,
  `import xerscope.app.cache` and relative imports.
- `tests/test_architecture.py::test_the_app_modules_import_one_way_and_the_pages_read_each_name_from_its_module`:
  the set of app modules equals the keys of `APP_EDGES`, each module's edges equal its entry,
  no module or page imports a page, the baseline domain reads none of `state`, `loading`,
  `downloads`, `cache` beyond its entry, no app module but `streamlit_app` may import `state`
  (none does; the pages do), no cycle.
- `scripts/fitness.py` (`contracts()`): one import-linter `forbidden` contract per `LAYERS` key
  (11 in `tests/fitness_baseline.json`, `import_contracts_broken: 0`); CI job `fitness` in
  `.github/workflows/tests.yml` fails when the count of broken contracts goes up
  (`tests/test_fitness.py`).

## References

- `tests/test_architecture.py`: `LAYERS`, `APP_EDGES`, `BASELINE_DOMAIN`, `imports`,
  `imported_names`, `app_imports`
- `scripts/fitness.py`: `contracts`, `import_contracts`
- `src/xerscope/xer/__init__.py`: `load_snapshot`, the entry most callers use
- `docs/architecture.md`: data-flow diagram, "Layer rules" (section 5), §7 `app/` and its
  "Import edges" paragraph, §9 Tests
- `CONTRIBUTING.md`: "Where a change goes"
- Related: [ADR-0002](0002-format-parser-then-p6-model-with-load-contract.md) (the `xer/`
  layer), [ADR-0006](0006-weekly-series-store-one-snapshot-per-data-date.md) (the store),
  [ADR-0012](0012-code-fitness-ratchet-and-proof-of-moves.md) (the fitness ratchet),
  [ADR-0016](0016-streamlit-web-app-pages-compose-analyses.md) (pages compose analyses)
