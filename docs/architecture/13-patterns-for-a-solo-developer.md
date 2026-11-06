# 13. Patterns for one developer: what to keep, what to add, what to refuse

This section closes the audit and the visual campaign of November 2026. It answers one question:
which design patterns make xerscope cheap to change for a single developer, given what the
product has to do (read weekly P6 exports, recalculate like P6, judge against standards, explain
every number). The yardstick is the **cost of a change**, counted in files touched and in the
evidence a change needs, not an abstract notion of cleanliness.

Everything here is grounded in the code of this branch. Nothing is a rewrite: every proposal is
made "at constant output", which in this repository means the P6 reference files, the held-out
corpus floors (`tests/test_p6_heldout.py`), the golden standards and the app pages stay
identical while the structure moves.

## 13.1 Patterns already in place, and why they must stay

| Pattern (common name) | Where it lives | What it buys a solo developer |
|---|---|---|
| **Pipeline, one-way data flow** | `parser → model → Snapshot → SnapshotStore → analyses → pages/CLI` (`docs/architecture.md`) | A bug is in one stage; a stage is tested without the others. |
| **Parse, don't validate** at the boundary | `xer/parser.py` keeps strings, `xer/model.py` types, `xer/validate.py` bounds and dedupes | Every later stage can trust dtypes, units and identities; hostile files stop at one door. |
| **Rules as data + Registry** (a Strategy without classes) | `@rule` in `analysis/rules.py`, metrics in `standards/*.toml`, `checks.run_standard` | A company standard is a TOML file, zero code; a new generic rule is one function. A difference between standards is a parameter, never an `if standard == …`. |
| **Convention over configuration for explanations** | `explain.py` reads the rule docstring (`Counts:`, `Excludes:`) | The explanation cannot drift from the rule: same text, one place. |
| **Immutable value objects + memoised derivation** | `Snapshot`, `Schedule` (`frozen=True`), `schedule()` cached on the snapshot, `state.memo()` keyed on `data_identity()` | No invalidation logic to maintain; a result is a function of its inputs. |
| **Thin pages, computation below** | `app/views/*.py` compose `analysis/` and `viz/`; `app/state.py` and `app/ui.py` hold the shared plumbing | Pages can be rendered headless in tests (`tests/test_app.py`). |
| **Architecture fitness functions** | `tests/test_architecture.py` (layer imports), `tests/test_docker.py` (deployment properties), the CI check that no `.xer` is tracked, `FLOORS` of the corpus | The rules of CONTRIBUTING.md are executable: a regression fails a test instead of waiting for a review. |
| **Characterisation by reference corpora** | pinned third-party XERs, P6 held-out sets, MPXJ cross-check | The engine can be restructured freely; the floors say whether it still computes the same thing. |

These are the right patterns for this product. The recommendations below sharpen them; none
replaces them.

## 13.2 The cost of a change today

Measured on this branch (files to touch, evidence required). "Evidence" is CONTRIBUTING.md rule 3.

| Change | Files touched | Evidence | Verdict |
|---|---|---|---|
| A check for your own standard, with an existing generic rule | 1 TOML | none (parameters only) | cheap, keep |
| A new generic rule | `rules.py` (+ docstring), `custom-template.toml`, `tests/test_rules.py` | hand-made `xerkit` schedule with the count written in the test | cheap, keep |
| A new built-in check (P6, DCMA, DECM) | one function in `analysis/p6/` or `dcma/` or `decm/`, its TOML metric, `docs/standards.md` table, a test | source text of the standard + hand count | cheap, keep |
| A new XER column | `xer/model.py` (one table builder) and, if bounded, `xer/validate.py` | a reference file that carries it | cheap |
| A new page | `app/views/<page>.py`, one `st.Page` line, one headless render test | none | cheap to add, **costly to get right**: a page author must know `state.py` (88 functions, 1 238 lines, six concerns) to pick the right helper |
| A new P6 scheduling option | `Options` + `Options.from_snapshot`, then a branch in **one to four** of `_Run.pred_bounds` (CC 22), `forward` (42), `successor_limits` (41), `backward` (22) | a P6 export showing the option, corpus floors unchanged or raised | **expensive**: the status × link type × lag × option cases are spread over four methods (the author's own backlog says the same) |
| A change in what a page computes (changelog, health, ppc, gantt) | the view itself | AppTest only | **medium**: the computation sits in the view, so the test needs Streamlit |

Two places are expensive, and both were flagged by the audit's complexity numbers: the CPM passes
and `app/state.py`. The rest of the codebase is already cheap to change.

## 13.3 Recommended patterns, in order of value for the business need

### P1. Table-driven link semantics in the CPM (the one structural change worth its risk)

**Problem.** `_Run.forward`, `pred_bounds`, `successor_limits` and `backward` each encode the same
decision table: for a relationship of type FS/SS/FF/SF, a predecessor that is not started / in
progress / complete, a lag on a given calendar, and the options (retained logic vs progress
override vs actual dates, lag from early start, expected finish), which date bounds which. The
table is written four times, once per pass and direction, as nested `if`s. A new option touches
all four; a bug fix in one can miss the others.

**Pattern.** *Table-driven method* with an explicit activity state. One module
`analysis/cpm_links.py` (or a section of `cpm.py`) holding:

```python
class Status(Enum): NOT_STARTED, IN_PROGRESS, COMPLETE

# (link type, predecessor status, pass) -> function(pred dates, lag, options) -> bound
BOUNDS: dict[tuple[str, Status, Literal["early", "late"]], Callable[..., Bound]]
```

The passes become loops that look the bound up and take the max (forward) or min (backward). Each
cell is a 5-line pure function with its own test (one `xerkit` schedule per cell: 4 types × 3
statuses × 2 passes = 24 cells, most trivial). The options that change a cell's behaviour are
parameters of the cell function, not branches around the loop.

**Why this and not more.** It removes the duplication the author already named in `docs/backlog.md`
("a table read by both passes would make each cell a test"), it brings the four methods from CC
22–42 to under 15 each, and it changes nothing observable. It does *not* mean a scheduler
framework, a graph library or an event system.

**Gate.** Done in three commits (early bounds, late bounds, LOE and resource-dependent cases),
each with the P6 files identical to the minute, `FLOORS` not lowered, MPXJ cross-check with
no new `UNRESOLVED` entry. If a commit cannot meet that, it is reverted, not patched.

### P2. Split `app/state.py` by concern, keep its public names

**Problem.** `state.py` holds the parse cache, the Files window, the baseline logic, the context
banner and page header, navigation helpers and the metric memo. A page author reads 1 238 lines
to find `require_store`, `page_header`, `snapshot_picker`, `baseline_for`, `memo`.

**Pattern.** *Module per concern* behind a stable facade: `app/state/__init__.py` re-exports the
twenty names the pages use today, implemented in `state/cache.py` (`_parse`, `memo`,
`data_identity`), `state/files.py` (window, folder and upload boxes, `LoadJob`),
`state/baseline.py`, `state/context.py` (banner, header, `require_store`), `state/navigation.py`.
No page changes; `tests/test_architecture.py` gains the rule that pages import `state` only.

**Gate.** `tests/test_app.py` and `test_app_cache.py` unchanged and green; `git diff --stat` of
`views/` is empty.

### P3. Pure "page data" functions for the four pages that still compute

**Problem.** Changelog, Schedule health, PPC and Gantt build frames inside the view; their logic
is testable only through AppTest (slow, and blind to the upload path, as the backlog notes).

**Pattern.** *Humble view*: for each of those pages, one `compute_<page>(store, snapshot, …) ->
<Page>Data` (a frozen dataclass of frames and scalars) placed in `analysis/pages/` or next to the
analysis it belongs to, and the view reduced to widgets and `ui.table`/`ui.chart` calls. Tests call
`compute_*` on `xerkit` schedules in milliseconds; AppTest keeps one render test per page.

**Gate.** `tests/test_app_parity.py` (the page shows what the analysis computes) stays the
contract; each extracted function gets the tests that were implicit in the view.

### P4. One error contract, enforced

**Problem.** The audit found nine paths where a pandas or datetime exception reached a page. Most
are closed; the rule that prevents the next one is not written down.

**Pattern.** *Boundary exceptions*: everything that leaves `xer/` is `XerError`; everything that
leaves `analysis/cpm.py` is `ScheduleError` (`CycleError` is one); everything that leaves
`analysis/standards.py` is `ValueError`. Pages catch exactly those, in `require_store` and in the
few places that load a file or a TOML, and nowhere else. The fuzz test
(`tests/test_fuzz_parser.py`) is the fitness function for `xer/`; a similar 20-line property over
random `xerkit` networks ("schedule() raises ScheduleError or returns a Schedule") would be the
one for the engine.

### P5. Fitness functions for the two numbers the audit measured

- A complexity ceiling: `ruff check src --select C901` with `max-complexity = 15` in
  `pyproject.toml`, with a `# noqa: C901` and a one-line reason on the few functions deliberately
  left above it (today: `parse_text` is gone; the four CPM passes until P1 lands; `sample.py`).
- A size ceiling on modules the layer test already parses: fail when a module in `app/` exceeds
  800 lines (P2 brings `state.py` under it).

Both are cheap, run in the existing `ruff` step, and turn "we should split this" into a test.

### P6. Keep the rule registry exactly as it is

The temptation after P1–P3 is to generalise: a `Rule` base class, a plugin loader, a DSL. Refuse
it. The registry is a dict of functions with typed parameters; TOML validation already rejects a
wrong parameter name with the exact name. A class hierarchy would add indirection for no new
capability, and the one real extension point (a company rule nobody has written yet) is served by
`custom-template.toml` and a generic rule. If a customer needs a rule the generic ones cannot
express, the answer is one more `@rule` function in this repository, with its test.

## 13.4 What not to introduce

| Idea | Why not here |
|---|---|
| A plugin system or entry points for rules | One developer, one repository: a function and a TOML line are the plugin. |
| Dependency injection container, service classes | The pipeline passes values; there is no runtime wiring to configure. |
| An ORM or a database for the weekly series | `SnapshotStore` in memory plus Parquet export covers the product; a database adds a schema to migrate. |
| Async or a task queue beyond `LoadJob` | One background thread reads files; the rest is CPU-bound pandas, better served by vectorisation. |
| A frontend framework next to Streamlit | The Gantt (`viz/gantt.js`) is the only custom component and it is small; the rest is pages. |
| Micro-packages (`xerscope-core`, `xerscope-app`) | Packaging overhead for a single deployable. The layer test already gives the boundary. |
| Generic "metric engine" abstractions over EV, PPC, MTA | Each is one module with one definition page in `docs/formulas.md`; sharing a base class would hide the definitions that make the numbers traceable. |

## 13.5 Working method that fits these patterns

- **One change, one evidence, one commit.** Already the rule; the commit template "problem /
  what changes / how verified" is the design review.
- **Restructure at constant output, then change behaviour.** P1–P3 are pure moves; the corpus
  floors and the golden files are the referee. Never combine a move with a value change.
- **Fitness functions over review checklists.** Every rule in CONTRIBUTING.md that can be a test
  is one (layers, data, deployment, complexity, size, fuzz). The checklist is for what cannot be.
- **ADR-lite.** A decision that the next reader would question gets ten lines in
  `09-architecture-decisions.md` (context, decision, consequence). The fourteen reconstructed there
  are the backlog of decisions that were implicit.
- **Visual campaign as a release step.** The Playwright scripts of the November campaign run in
  under ten minutes on the demo series; running them before a release catches the class of
  defects (contrast, truncation, `None` in tables, modebar on touch) that unit tests cannot.

## 13.6 Suggested order and effort

| Step | Effort | Risk | Prerequisite |
|---|---|---|---|
| P5 fitness functions (complexity, size) | ½ day | none | — |
| P4 error contract written + engine property test | ½ day | none | — |
| P2 `state.py` split | 1 day | low (tests unchanged) | — |
| P3 page data functions (4 pages) | 2 days | low | P2 |
| P1 CPM link table | 3–5 days | medium (engine) | Java available for the MPXJ cross-check; the held-out corpus fetched |
| P6 (keep the registry) | 0 | — | a decision, not a task |

After P1 the "new P6 option" row of §13.2 becomes: `Options` + one cell function + one test,
with the corpus as evidence. That is the change the product will keep needing, and the one that
is expensive today.
