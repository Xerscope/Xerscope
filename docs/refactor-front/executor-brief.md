# Brief for an executor or a reviewer of a front refactoring package

Given, in this order, to whoever implements or reviews a package of
`docs/refactor-front-plan.md`. It adds nothing to the repository's rules; it says which ones
bind a package and in what order they are read.

## Status against the code

The brief applies to the packages the plan's status table (top of `docs/refactor-front-plan.md`)
marks Open or Partial: P6c (the assignments left in `session.py`, `baselines.py` and
`baseline_warnings.py`), P7b, P9b, P11a, P11b, P12a (the test imports), P12b, P16b, P18 and the file picker of section 6.
Checked against the repository: the ruff and bandit versions below are those of
`.github/workflows/tests.yml` (ruff 0.17.4, bandit 1.9.4); CI runs the fitness check and
`uv run pytest -rs -n auto --dist loadfile`, while `scripts/duplication.py`, `scripts/same_code.py`
and the diff checks are run by the executor, not by CI; `scripts/same_code.py` takes `base`, an optional `head` and
`--ignore-docstrings`; `scripts/duplication.py` defaults to `--threshold 0.9`; the protected files
named below exist. `tests/test_architecture.py` also pins the app-internal import graph
(`APP_EDGES`) and the rule that only `streamlit_app.py` and the pages import `state.py`.

## Read first

1. The project skill (`xerscope`), whole file: non-negotiables, where things go, the
   verification gate, engineering standards, readable code, names, writing.
2. `CONTRIBUTING.md`, whole file. When the skill and this file differ, the file wins and the
   difference is reported in the package's commit message.
3. `docs/architecture.md`, the layers: `app/` composes analyses and figures (some computation
   still sits in the views, see `docs/backlog.md` "Structure" and package P11a); `viz/` draws frames and imports only `config.py` and `analysis.wbs.ROOT`; a page
   never imports another page.
4. The package's section of the plan: Problem / Options / Choice / Verification / Findings. The
   Choice is made: the package implements exactly that option, nothing more, nothing less. A
   package whose Choice is "open" is not implemented.

## Binding rules

- A refactoring package moves no computed value and changes no user-visible output:
  `tests/golden/pages.json`, `tests/golden/standards.json`, the figure JSON and the Gantt rows
  JSON are byte-identical. When this cannot hold, the executor stops and reports why; a test or
  a golden is never adjusted to the code.
- Not written by a package: the goldens, `tests/fitness_baseline.json`,
  `tests/mutation_baseline.json`, `pyproject.toml`, `tests/test_architecture.py`,
  `tests/test_fitness.py`, the scripts under `scripts/`, `.github/`, anything under
  `analysis/`, `xer/`, `verify/`. A new test may be added; an existing test is modified only
  with the reason in the commit message.
- No exception is added to pass a check: no `noqa`, `nosec`, `pragma`, `type: ignore`,
  `fmt: skip`, `xfail`, `skip`, ruff per-file ignore, `KNOWN` entry, complexity threshold or
  import-linter exemption. A check that fails names a defect of the change, not of the check.
- No real schedule data, activity name, project code, company name or real file path. The demo
  series comes from `uv run xerscope sample --out <scratch directory>`.
- Readable code and Names apply to every line written or touched (the skill lists them). New
  names are whole words; `fmt_date` and `fmt_number` keep their names (no mass rename).
- Simple over clever: no new dependency, no abstraction for a single use.
- No session narration and no tool mention in code, docstrings, tests or commit text.
- Git: the package branch only, no push by the executor, no force. The executor leaves the
  working tree with the package's changes and commits nothing; the reviewer commits once the
  gate is green, under the maintainer's git identity.

## Method of the executor

1. Read the cited code at the lines the plan gives, with the voters' corrections.
2. Write the comparison script first (figure JSON digest for `viz/`, `AppTest` element list or
   `assert_frame_equal` for `app/`), run it base against the unchanged tree, see it pass.
3. Make the change.
4. Run the script again; plant the defect the plan names; see the script fail; revert the
   defect; see it pass.
5. Run the full gate below and read every output.
6. Report: files changed, the definitions `same_code.py` will list and why each one is allowed
   by the package text, each gate command with PASS or FAIL and its key lines, the proof result.

## Full gate

A passing subset is not the suite.

```bash
uv run pytest -rs -p no:cacheprovider                 # whole suite; the skips named
uvx ruff@0.17.4 check src tests scripts
uvx ruff@0.17.4 format --check src tests scripts
uvx bandit@1.9.4 -r src -ll
uv run python scripts/fitness.py --check tests/fitness_baseline.json
uv run python scripts/duplication.py src --threshold 0.8 | diff <report on the base> -   # removed lines only
uv run python scripts/same_code.py <base commit>      # a move reports none; a rewrite only what the package says
git diff --stat <base commit> -- tests/golden/        # empty
git diff --stat <base commit> -- src/xerscope/analysis src/xerscope/xer src/xerscope/verify   # empty
git status --short                                    # nothing outside the package's files
```

Then the package's own proof (its Verification paragraph), with the planted defect.

## Method of the reviewer

The reviewer trusts nothing in the executor's report and re-runs everything.

1. Read the whole diff against the base commit: only what the Choice says; every finding
   listed under Findings is addressed at its lines; no other file; no behaviour change.
2. Review every added or modified line against Readable code and Names, quoting the rule
   number. A letter or an abbreviation outside the P6 vocabulary in new code is a rejection.
3. Run the full gate and the proof, planting the defect again.
4. Check that no exception marker and no protected file appears in the diff.
5. Every definition `same_code.py` prints is in the executor's list and justified by the
   package text; otherwise reject.
6. Approve and commit, or reject with `file:line`, the rule, and what to change. A rejected
   package goes back to the executor once; a second rejection stops the chain.

Commit message: first line `refactor(front): <package title in plain words>`; body: Problem
(two lines), What changes (files and functions, moved or rewritten), Verification (one line per
gate command with what it printed, the proof and the planted defect).
