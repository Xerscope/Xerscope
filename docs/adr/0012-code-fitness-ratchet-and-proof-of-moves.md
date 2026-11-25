# ADR-0012: Code fitness ratchet, docstring rules and a mechanical proof that a refactor only moves code

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-08 (`930af13`, "Fitness ratchet: complexity, maintainability, duplication, layers, dependencies", #149); docstring rules on 2026-11-09 (`679472b`, #180); `same_code.py` on 2026-11-10 (`0a2dada`, #181) |
| Scope | `scripts/fitness.py`, `scripts/duplication.py`, `scripts/same_code.py`, `tests/fitness_baseline.json`, `tests/test_fitness.py`, `tests/test_duplication.py`, `tests/test_same_code.py`, `tests/test_docstrings.py`, `tests/test_architecture.py` (`LAYERS`), `pyproject.toml` (`[dependency-groups]` dev, `[tool.ruff.lint]`, `[tool.mypy]`, `[tool.deptry.*]`), `.github/workflows/tests.yml` (jobs `lint`, `fitness`), `scripts/check_value_justification.py`, `.github/CODEOWNERS` |
| Sources | [CONTRIBUTING.md](../../CONTRIBUTING.md), "Readable code", "Verification" ("Docstrings", "Moved code", "Code fitness"); PEP 257; PEP 8 ("Documentation Strings"); commits `930af13`, `679472b`, `0a2dada` |

## Context

The maintainer reads, changes and debugs the code by hand (CONTRIBUTING.md, "Readable code"):
code he cannot follow is not done, whatever the tests say. The large modules (`analysis/cpm.py`,
the app state, `xer/model.py`, the Ask parser) were to be refactored, and nothing measured
where they started, nor stopped a later change from making a module harder to read, adding a
copied function, breaking a layer rule or adding a type error. Before `679472b`, the 735
docstrings of `src/xerscope` followed no written rule (158 public objects without one, 341
summaries over several lines, per the commit message).

A refactor that moves functions between modules produces a diff too large to check line by
line, and the golden files (ADR-0011) see results, not code: nothing stated "this definition
is the one `main` has".

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Review only, no measure | none | a regression shows only to the reader who notices it; a refactor cannot show what it improved |
| Absolute thresholds on the whole code (a lint gate such as `ruff --select C901` at a fixed ceiling) | one setting | fails at once on the existing debt, or is set so loose it stops nothing; alternative not recorded in history beyond the manual `C901` listing in [docs/backlog.md](../backlog.md), "Structure" |
| **A ratchet: measures per module and global, compared with a committed baseline that only moves the wrong way with a justified line; docstring debt listed per file and only shrinking; a script that compares definitions with `main` (chosen)** | a baseline to regenerate when a measure improves; exact tool versions to maintain | a green check means "no worse than the baseline", not "good"; readability itself stays a review matter |

## Decision

**Fitness ratchet.** `scripts/fitness.py` measures `src/xerscope` and writes `fitness.json`:

- per module: maintainability index and its rank (radon MI; A >= 20, B 10-19, C < 10),
  highest cyclomatic complexity and functions above 15 (radon), highest cognitive complexity
  and functions above 15 (complexipy; `LIMIT = 15`, complexipy's default ceiling), functions
  with a type 1/2 structural clone anywhere in `src`, and type 3 near clones
  (`scripts/duplication.py`);
- global: mypy errors (`[tool.mypy]`, Python 3.11, missing imports ignored), deptry violations
  (with the mappings and ignores of `[tool.deptry.*]`), and import-linter contracts generated
  from `LAYERS` in `tests/test_architecture.py` (one `forbidden` contract per layer, so the
  layer rules are written once; `app/views`, with no `__init__.py`, is left to
  `tests/test_architecture.py`).

`--check tests/fitness_baseline.json` fails when a measure is worse than the baseline: a lower
MI rank, any count or maximum that went up, broken contracts that went up, or a new module
that is not rank A, has a function above 15 or a clone. The MI value, the near clones and the
contract total are reported, not checked (`UNCHECKED`). An improvement is listed; `--out
tests/fitness_baseline.json` rewrites the baseline so the gain is kept. `--markdown` appends a
summary whose first table, "What remains" (mypy errors, functions over 15 cyclomatic and
cognitive, cloned functions, modules below rank A), is written whatever the baseline allows.

A measure the new baseline lets get worse needs one line in the pull request description,
`fitness/<module>.<measure>: old -> new — why, and the pull request that brings it back`;
`scripts/check_value_justification.py` (workflow `values`) reads the baseline at the base
commit and fails on a missing line (ADR-0008). `tests/fitness_baseline.json` is listed in
`.github/CODEOWNERS`.

**Pinned tools.** The dev group of `pyproject.toml` pins the measuring tools exactly,
because the baseline holds their numbers and a new release can score the same code
differently: `complexipy==8.3.0`, `deptry==0.25.1`, `import-linter==2.16`, `mypy==2.4.1`,
`radon==6.0.1`. The CI job runs on Python 3.13, the baseline's (radon 6.0.1 cannot tokenise
`xer/parser.py` on 3.11).

**Structural clones.** `scripts/duplication.py` normalises each function's syntax tree
(name, decorators and docstring dropped, every name replaced by `_`, every literal by `...`,
attribute names and operators kept). Equal trees are type 1/2 clones; trees whose node
sequences match at `THRESHOLD = 0.9` or above (difflib ratio) are type 3 near clones.
Functions under `MIN_NODES = 30` normalised nodes are left out. Standard library only.

**Docstrings.** ruff selects the pydocstyle rules (`D`) with the `pep257` convention on
`src/xerscope` (`tests/**` and `scripts/**` ignore `D`). The files not yet at the standard are
listed in `[tool.ruff.lint.per-file-ignores]`, each with the rules it does not meet (67 files,
260 (file, rule) pairs); a file leaves the list when brought to the standard, no rule is
added. `tests/test_docstrings.py` checks what ruff does not: a function or class docstring
holds at most `MAX_LINES = 12` lines (the 22 longer ones are named in `LONG` and can only
leave it), the `src/` debt holds docstring rules only, names existing files and stays at or
under `MAX_DEBT = 267` pairs, and every name a docstring cites between double backquotes and
every cited repository path exists.

**Proof of moves.** `scripts/same_code.py <base> [<head>]` reads `src/xerscope` at two
revisions (or one and the working tree) as text, runs nothing and reads no schedule, and
compares the syntax tree of every top-level definition wherever it lives: comments, layout
and the file a definition is in do not count; module-level imports and module docstrings are
left out; an import inside a function counts by the names it brings in. `--ignore-docstrings`
also leaves out function and class docstrings. Exit status 1 on any definition changed,
removed or added, printed with its file on each side and the lines that differ; a definition
that only changed its name is reported as renamed. It is a command for the author and the
reviewer (`uv run python scripts/same_code.py origin/main`), not a CI job.

**Readable-code rules.** One role per function, one level of nesting (two at most), whole-word
names, units in names, nothing clever where plain works (CONTRIBUTING.md, "Readable code").
ruff checks the case of names and built-in shadowing (`N`, `A`); cognitive complexity above
15 is counted by the ratchet; the rest is part of review. A rewrite for readability comes with
its proof: the same output before and after (golden files, ADR-0011, or a digest of outputs).

## Consequences

Positive:

- Every pull request is measured against the last accepted state; the code can only get
  worse with a stated reason and a pull request named to bring it back.
- A gain (a function split, a clone removed) is kept by rewriting the baseline.
- The layer rules of ADR-0001 are enforced twice from one source (`LAYERS`): by
  `tests/test_architecture.py` and by the generated import-linter contracts.
- A refactor that only moves code, or only rewrites docstrings, carries a proof the reviewer
  can rerun.

Negative:

- Tool upgrades are deliberate: a new version of radon, complexipy, mypy, deptry or
  import-linter means a new baseline.
- The baseline accepts the existing debt (91 mypy errors in the committed baseline, functions
  over 15, modules below rank A); "What remains" shows it on every run, nothing forces it down.
- `same_code.py` does not see import order or what a name now resolves to; the tests and the
  golden files cover those.

Follow-ups: [docs/backlog.md](../backlog.md), "Structure (only once the above is done, at
constant output)".

## Verification

- `tests/test_fitness.py::test_same_measures_pass`,
  `::test_module_leaving_rank_a_fails_while_mi_inside_the_rank_is_free`,
  `::test_each_count_or_maximum_that_goes_up_fails`,
  `::test_near_clones_and_the_contract_count_are_reported_not_checked`,
  `::test_improvements_are_listed_and_pass`,
  `::test_new_module_must_be_rank_a_without_complex_function_or_clone`,
  `::test_removed_module_is_not_a_regression`,
  `::test_the_summary_gives_what_remains_whatever_the_baseline_allows`.
- `tests/test_duplication.py` (type 1, type 2, type 3 above the threshold only, small functions
  left out, scoped names).
- `tests/test_same_code.py::test_a_move_with_its_imports_rewritten_is_the_same_code`,
  `::test_comments_and_layout_do_not_count`, `::test_docstrings_count_unless_left_out`,
  `::test_a_definition_that_only_changed_its_name_is_a_rename`, and the other tests of the file.
- `tests/test_docstrings.py::test_no_new_docstring_over_the_limit`,
  `::test_listed_long_docstrings_are_still_long`, `::test_docstring_debt_only_shrinks`,
  `::test_docstrings_cite_names_and_files_that_exist`.
- `tests/test_check_value_justification.py::test_a_fitness_measure_that_gets_worse_needs_its_line`,
  `::test_a_fitness_measure_that_improves_needs_no_line`,
  `::test_measures_fitness_reports_without_checking_are_free`,
  `::test_the_baseline_is_watched_owned_and_blocking`.
- CI: `.github/workflows/tests.yml` job `lint` (`uvx ruff@0.17.4 check src tests scripts`, with
  the `D`, `N`, `A` rules) and job `fitness` (`uv run python scripts/fitness.py --markdown
  "$GITHUB_STEP_SUMMARY" --check tests/fitness_baseline.json`, no `continue-on-error`); both are
  in the `needs` of job `publish`.

## References

- `scripts/fitness.py`: `modules`, `contracts`, `import_contracts`, `mypy_errors`,
  `deptry_violations`, `compare`, `remaining`, `markdown`, `LIMIT`, `UNCHECKED`.
- `scripts/duplication.py`: `functions`, `clones`, `near_clones`, `scan`, `THRESHOLD`, `MIN_NODES`.
- `scripts/same_code.py`: `definitions`, `differences`, `compare`, `report`, `read_version`.
- `tests/test_docstrings.py`: `MAX_LINES`, `LONG`, `MAX_DEBT`.
- `tests/test_architecture.py`: `LAYERS`.
- `pyproject.toml`: `[dependency-groups]` dev, `[tool.ruff.lint]` `select`,
  `[tool.ruff.lint.pydocstyle]`, `[tool.ruff.lint.per-file-ignores]`, `[tool.mypy]`,
  `[tool.deptry.package_module_name_map]`, `[tool.deptry.per_rule_ignores]`.
- [CONTRIBUTING.md](../../CONTRIBUTING.md), "Readable code", "Verification" ("Docstrings",
  "Moved code", "Code fitness"); [docs/architecture.md](../architecture.md) §9.
- Related: ADR-0001 (layers), ADR-0008 (values workflow), ADR-0011 (golden files),
  ADR-0013 (mutation baseline).
