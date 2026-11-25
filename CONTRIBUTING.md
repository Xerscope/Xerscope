# Contributing to xerscope

xerscope is worth using only if its numbers are the ones P6 or the standard would give,
and if each can be traced to a formula, a population and a source. Every rule below
protects that.

## Setup

```bash
uv sync --locked                                  # Python >= 3.11, dev tools included
uv run python tests/reference/fetch.py            # pinned third-party XERs (checksum-verified)
uv run python tests/reference/fetch_p6_heldout.py # P6 23.12.1 held-out corpus (pinned commit, needs git)
uv sync --locked --extra crosscheck               # optional: MPXJ + jpype, needs a JDK 21 or 25
uv run python tests/reference/mpxj_cpm.py         # optional: MPXJ's scheduler, pinned commit (git, javac)
uv sync --locked --group accessibility            # optional: playwright, for scripts/accessibility.py
```

The fetched files land in `tests/reference/data/` (not tracked). A test whose evidence is
missing skips and says which command fetches it; CI sets `XERSCOPE_REQUIRE`
(`reference,p6-corpus`, plus `mpxj` in the crosscheck job) so the same test fails there
instead (`missing` in `tests/conftest.py`). A fourth name, `witness`, is set by hand for the
P6 witness reports (Verification), which CI never has.

Read [docs/architecture.md](docs/architecture.md) first. Read [docs/cpm.md](docs/cpm.md)
before touching `analysis/cpm.py` or `xer/calendar.py`, and
[docs/standards.md](docs/standards.md) before touching a check or a standard.

## Rules

1. **No real schedule enters the repository.** Real `.xer` files, their activity names,
   project codes, company names and file paths are never committed, quoted in docs,
   tests, issues, pull requests or commit messages. Tests build their files in code
   (`tests/xerkit.py`) or use the pinned public files of `tests/reference/sources.py`
   (downloaded, never vendored). CI fails if a `.xer`, `.parquet`, `.csv` or `.xlsx` is
   tracked.
2. **P6 semantics come from Oracle, checks from their standard.** Calculation behaviour
   follows the P6 Professional 24 documentation; checks follow the P6 Check Schedule
   help, DCMA DECM v8.0 or DCMA 14-Point, and the Integrity checks the P6 scheduling log
   (Schedule Project Log). Each rule names its source (`source` field of the TOML,
   docstring of the function). Where no source settles a behaviour, write it down as an
   open question instead of guessing: `UNRESOLVED:` in the metric's `source`, an entry of
   `UNRESOLVED` in `verify/mpxj_cpm.py` for a CPM difference with MPXJ, or
   [docs/backlog.md](docs/backlog.md).
3. **A number changes only with evidence.** A change that moves a computed value comes
   with a test that fails before and passes after, and the evidence for the new value: a
   P6 export, the held-out P6 corpus, MPXJ's scheduler, or a hand calculation written in
   the test.
4. **Simple over clever.** One function per check, one place per P6 concept, no new
   dependency without a reason stated in the pull request.
5. **Read what exists before writing.** Before the first line of a change, read the modules
   it will sit beside and search the code base for what it needs: a population is built
   with `analysis/populations.py` (`activity_funnel`, `EXCLUSIONS`, `Funnel.keep`, the
   `has_…` helpers), so its steps and what each removed can be shown and debugged; a table
   of activities takes `flagged_activities` and its standard columns; a column is labelled
   and formatted once in `app/ui.py` (`COLUMNS`), never renamed in a page; a funnel is shown
   with `app/sets.py`; a P6 name comes from `xer/model.py`. On a page: the update is picked
   with `state.snapshot_picker` (one choice for the session), figures go through `ui.kpis`
   with their formulas in `analysis/explain.py` (`KPI_FORMULAS`), tables through `ui.table`,
   downloads through `downloads.csv_download` (`app/downloads.py`); a chart is built from the helpers of
   `viz/charts.py` (`_line`, `_with_house_style`, `_widen_dates`, `SERIES`, `STATUS`). A
   filter written by hand where a named step exists, or a second copy of a helper, is a
   defect of the change even when its numbers are right; so is a chart or a table that
   repeats what the one beside it shows. The pull request lists what was reused.

Units: durations and floats are stored in hours; `_d` columns are working days of the
activity's own calendar; activities are identified by `task_code` (Activity ID), never
`task_id`. Mixing hours and days, or calendar days and working days, is the most common
source of a wrong number.

## Readable code

The maintainer reads, changes and debugs this code by hand. Code he cannot follow is not
done, whatever the tests say. These rules apply to every line written or modified; an
existing file is brought to them when it is touched, not by a mass rename.

Reading:

1. **A function does one thing, and its name says which.** `_code_column` gives the new
   code of each row; it does not also empty the other columns.
2. **One level of nesting, two at most.** A loop holding an `if` holding another `if` is
   split: each case becomes a function with a name. The fitness check counts it
   (cognitive complexity above 15 is a debt, and may not grow).
3. **A docstring says what comes out, and why when it is not obvious.** It names the
   source for a rule (Oracle page, PAM section). It does not repeat the code.
4. **A comment explains a reason, never a line.** "the codes first: the labels are built
   from them" stays; "loop over the columns" goes.
5. **Nothing clever where plain works.** No nested comprehension, no chained conditional
   expression, no helper used once to save two lines.
6. **A rewrite for readability changes no result.** It comes with the proof: the same
   output before and after (golden files, or a digest of the outputs), stated in the
   pull request.
7. **The pull request says what to read first** and what each part does.

Names:

1. Whole words, not letters: `for column in columns`, not `for c in columns`.
2. No abbreviation outside the P6 vocabulary: `axis`, `calendar`, `predecessors`, not
   `ax`, `cal`, `preds`.
3. A function that returns something is named after what it returns
   (`flagged_activities`).
4. A function that acts carries a verb (`record`, `write_private`).
5. A yes/no function starts with `is_`, `has_` or `can_`.
6. A table is named after its rows (`tasks`, `links`), never `df`.
7. A duration or a date carries its unit (`total_float_hr`, `lag_d`).
8. P6 fields keep their XER name (`task_code`, `cstr_type`).

Allowed short forms: `i` for a plain counter; the units `hr`, `wd`, `d`; the trade's
acronyms (WBS, LOE, CPM, BEI, EV). ruff checks the case of names and that none hides a
Python built-in (`N`, `A`); whether a name is clear is for the review.

Before / after, `Anonymizer.table`: one function of 38 lines with six cases three levels
deep became four, each one case to read (`table`, `_code_column`, `_label_column`,
`_other_column`), with a byte-identical anonymised file.

## Where a change goes

| Change | Goes in | Never in |
|---|---|---|
| What a P6 column means (units, identity, best dates, % complete type) | `xer/model.py` | analyses, pages |
| Working time, calendars | `xer/calendar.py` (`WorkCalendar`, `TimeAxis`) | ad hoc date arithmetic |
| A check on a file's values (unique keys, finite and bounded numbers, known codes) | one function in `xer/validate.py`, one warning line | the parser, an analysis |
| A built-in check | one function in `analysis/p6/`, `dcma/`, `decm/` or `integrity.py` + its metric in `standards/*.toml` (+ its sheet in `sheets/P6/` for a P6 metric) | a page |
| A rule for your own standard | a parameterised `@rule` in `analysis/rules.py` | an `if standard == ...` branch |
| A metric's explanation | `analysis/explain.py` | page text |
| A chart | `viz/` | `app/views/` |
| A page | `app/views/<page>.py`, composing analyses and figures | a calculation |
| A word or phrase of the Gantt Ask field | `analysis/ask/` (entry point `analysis/query.py`) | a page |
| A tunable default no standard owns | `config.py` (`Settings`) | constants scattered in modules |

## Verification

Run before opening a pull request, and report what was run and what it printed:

```bash
uv run pytest -rs                                # the whole suite; MPXJ tests skip without Java: say so
uvx ruff@0.17.4 check src tests scripts          # no new finding
uvx ruff@0.17.4 format --check src tests scripts
uvx bandit@1.9.4 -r src -ll                      # medium and high severity only
```

The versions are the ones `.github/workflows/tests.yml` pins (jobs `lint` and `audit`); CI
also runs the suite in parallel (`uv run pytest -rs -n auto --dist loadfile`), the fitness
check below, `pip-audit` on the lock file, the MPXJ crosscheck on Windows with Java 21 and
25, the image build and scan (on a pull request, only when it touches the `Dockerfile`, the
lock, `pyproject.toml`, `src/` or the Trivy pin), and the `deploy/` stack. The `test` job ends
with a CLI smoke test (`xerscope sample`, `info`, `export`); the crosscheck job also runs
`xerscope crosscheck` on the reference files and the demo set, and
`tests/test_crosscheck_mpxj.py` with `tests/test_reference.py`; the `oracle-report` job
writes `scripts/oracle_report.py` to the job summary and gates nothing. Besides `tests.yml`, a
pull request runs `codeql.yml` (CodeQL analysis of the sources), and `scanner.yml` when it
touches `.github/trivy/` (the Trivy pin scanned with itself; also daily, with the published
images); `scorecard.yml` (OpenSSF Scorecard) runs on `main` and weekly.

Then, depending on what changed:

| Changed | Also run | Pass criterion |
|---|---|---|
| CPM, calendars, options | `uv run pytest tests/test_cpm.py tests/test_cpm_properties.py tests/test_p6_heldout.py` | P6 reference files identical to the minute; no `FLOORS` entry lowered |
| CPM, with Java | `uv run pytest tests/test_crosscheck_mpxj.py` | new differences fixed or named in `UNRESOLVED` with a reason |
| A check or the CPM, before merging | `XERSCOPE_REQUIRE=witness uv run pytest tests/test_p6_witness.py` | each P6 Check Schedule report of a local witness folder (`tests/reference/data/witness/`: anonymised `.xer`, optional `baseline.xer`, `expected.csv`; never committed, so CI always skips it) reproduced count for count |
| A check or a standard | `uv run pytest tests/test_rules.py tests/test_p6_check_schedule.py tests/test_calendar_and_standards.py tests/test_explain.py tests/test_standards_conformity.py tests/test_sheets.py` | one hand-made schedule per behaviour, count written in the test; TOML, docstring, funnel, sheet and `docs/standards.md` agree |
| Any computed number | `uv run pytest tests/test_characterization.py` | no change in `tests/golden/standards.json`, or the change reviewed (below) |
| Parser or model | `uv run pytest tests/test_parser.py tests/test_model.py tests/test_reference.py` | third-party stated results still met |
| App pages | `uv run pytest tests/test_app.py tests/test_page_golden.py` | every page renders headless; no change in `tests/golden/pages.json`, or the change reviewed |
| `Dockerfile`, `compose.yaml`, `deploy/`, `.github/workflows/` | `uv run pytest tests/test_docker.py` | loopback only, non-root, no published port in `deploy/`, no secret logged, CI tools and images pinned |

**Golden file.** `tests/test_characterization.py` compares every metric of every built-in
standard with `tests/golden/standards.json`: a refactor changes no number. After an
intended change, `XERSCOPE_UPDATE_GOLDEN=1 uv run pytest tests/test_characterization.py`
rewrites the file and fails by design; review the diff, then rerun without the variable.
`tests/test_page_golden.py` does the same for what each page shows on the demo series
(`tests/golden/pages.json`), with the same variable.

**Moved values.** A pull request that moves a value of the golden file, of `FLOORS` or of
a standard TOML (prose fields aside) gives one line per value in its description,
`ID: old -> new — source`; the `values` workflow (`scripts/check_value_justification.py`)
prints the lines to complete, and fails on a missing one or on a lowered `FLOORS` value.

**Oracle marker.** `@pytest.mark.oracle(kind)` names where a test's expected values come
from: `p6`, `mpxj`, `standard` (the text of a standard), `property` (holds on any input)
or `characterization` (xerscope's own frozen output). Another kind stops the collection.
`uv run python scripts/oracle_report.py` counts the tests by kind.

**Docstrings.** Form: PEP 257 (a one-line summary written as a command and ending in a
period, a blank line before any detail), checked by ruff in the job `lint`. Public modules,
classes, functions and methods have one; a private function whose name says it all needs
none (PEP 8, Documentation Strings). Content: what the code does not already say, and
nothing else:

- the unit (hours, working days, minutes) and the calendar a number is counted on;
- the population a check counts;
- the source of a business rule: the Oracle page, the DECM or DCMA item, the corpus
  activity, or "observed, not explained";
- a side effect (a frame edited in place, a cache written) and the errors raised.

Argument and return types are in the annotations, not repeated. A comment in a body says
why, never what the line does. At most 12 lines for a function or a class
(`tests/test_docstrings.py`, `MAX_LINES`); the docstrings already longer are listed in its
`LONG`, which only shrinks: an entry leaves when its docstring is shortened (the test fails
on one no longer over the limit), none is added. An example gives values a named test proves; a longer worked
example goes to `docs/`. Double backquotes are for names of xerscope: the same test fails on
one that no longer exists, and on a cited path that is gone. Another library's class is cited
in plain text with the library and its version ("MPXJ 16.10, TableProjectReader"). The files not yet at the standard are listed in `pyproject.toml`
(`per-file-ignores`): a file leaves the list when it is brought to it, no rule is added, and
the same test caps the `src/` entries at `MAX_DEBT` (file, rule) pairs.

**Moved code.** `uv run python scripts/same_code.py origin/main` compares every top-level
definition of `src/xerscope` with `main`, wherever it now lives, and fails on one that
differs: the proof that a pull request only moves code. With `--ignore-docstrings`, the proof
that it only rewrites docstrings. It reads the code as text, runs nothing and reads no
schedule; what it leaves out is listed at the top of the script.

**Code fitness.** `uv run python scripts/fitness.py --check tests/fitness_baseline.json`
measures each module (maintainability index, cyclomatic and cognitive complexity,
structural clones) and the whole (mypy errors, deptry violations, the import contracts
generated from `LAYERS` in `tests/test_architecture.py`), and fails if a measure is worse
than the baseline. When a change improves one, `--out tests/fitness_baseline.json`
rewrites the baseline so the gain is kept; review the diff. A measure the new baseline lets get
worse needs its line in the pull request description, like a moved value (`values` workflow):
`fitness/<module>.<measure>: old -> new — why, and the pull request that brings it back`. The
job summary lists what remains (mypy errors, functions over 15, clones, modules below rank A)
on every run: a green check means "no worse than the baseline", not "nothing left".

**Weekly checks.** Two workflows run every Monday and by hand, never on a pull request, and
gate no publish. `mutation`: `uv run mutmut run` on the modules of `[tool.mutmut]`
(`pyproject.toml`), then `uv run python scripts/mutation.py --check
tests/mutation_baseline.json`, which fails when a module's share of killed mutants goes
down. `accessibility`: `uv run python scripts/accessibility.py --axe <axe.min.js>` runs
axe-core 4.14.0 on every page against WCAG 2.2 A and AA, and fails on a finding outside the
script's `KNOWN` list (Streamlit's own markup).

**Against P6 on your own file** (locally, never committed):
`uv run xerscope check FILE.xer --standard P6 --expect p6-summary.csv` and
`uv run xerscope recalc FILE.xer --report`.

### Adding or changing a check

1. Find the source text (Oracle help page, DECM metric ID, 14-Point item); write down
   population, numerator, denominator, unit and target before coding.
2. Build the smallest schedule that shows the behaviour with `xerkit`, write the expected
   count by hand in the test, watch it fail.
3. Implement the function; add the metric to the TOML with its `source`.
4. Check `xerscope standards` lists the metric, `xerscope standards --rules` its rule, and
   the app explains it.
5. Update [docs/standards.md](docs/standards.md) and [docs/formulas.md](docs/formulas.md);
   for a P6 metric, its calculation sheet `src/xerscope/sheets/P6/<id>.md`.

### Changing the CPM engine

1. Reproduce the difference on a reference file or a hand case; keep the failing case.
2. Change one rule at a time; rerun the P6 files, the held-out corpus and the MPXJ
   crosscheck. A gain on one shape that costs another is not a fix.
3. Raise the matching `FLOORS` values when the share of identical values goes up; never
   lower them.
4. Record in [docs/cpm.md](docs/cpm.md) which source settled the rule.

## Commits and pull requests

- One branch per change, merged through a pull request; nothing is pushed to `main`.
  Branch names say what changes (`fix/mta-stop-at-completion`, `docs/nas-env-file`).
- Commit subject: imperative or descriptive, one line, what changes
  (`P6-12: completed activities are out of late activities`). Body: the problem, what
  changes, how it was verified (command and result).
- The pull request description follows the template: problem, change, verification,
  evidence for any moved number.
- Commit messages, pull requests, comments and docs carry project context only: what the
  code does, why, which source. No session logs, no tool attribution trailers
  (`Co-authored-by` or session lines naming a tool), no generated-by lines.
- Author and committer are the contributor's own name and email, never a tool's: set
  `git config user.name` / `user.email` in the clone before the first commit. The
  `attribution` workflow (run again when the description is edited) fails a pull request
  whose commits (author, committer, message), title or description break these two rules.
- The `values` workflow, also run again on an edit of the description, fails a pull request
  whose description lacks a line for a moved value (Verification, Moved values).
- Pull requests are squash-merged: edit the squash message so the subject describes the
  change, not the branch name.
- Before merging a Dependabot pull request, comment `@dependabot rebase` so it builds on
  the current `main`.

## Documentation

Docs and comments state what the code does, why, and the source. A pull request that
changes behaviour updates the doc that describes it in the same pull request; a known
gap goes to [docs/backlog.md](docs/backlog.md), and leaves it when fixed.

A technical decision that the code alone does not explain (a choice between several ways of
doing it, a rule no source settles, a trade-off kept on purpose) is recorded as an
architecture decision record in `docs/adr/`, named `NNNN-<slug>.md` with the next number and
titled `# ADR-NNNN: <decision>`. Like the existing records, it opens with a table (Status,
Date, Scope, Sources) and has the sections `Context` (the problem), `Options considered`,
`Decision` (the choice and its source), `Verification`, `Consequences` and `References`.

## Security

Vulnerabilities are reported privately: see [SECURITY.md](SECURITY.md).
