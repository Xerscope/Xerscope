# Contributing to xerscope

xerscope is worth using only if its numbers are the ones P6 or the standard would give,
and if each can be traced to a formula, a population and a source. Every rule below
protects that.

## Setup

```bash
uv sync --locked                                  # Python >= 3.11, dev tools included
uv run python tests/reference/fetch.py            # pinned third-party XERs (checksum-verified)
uv run python tests/reference/fetch_p6_heldout.py # P6 23.12 held-out corpus (pinned commit)
uv sync --locked --extra crosscheck               # optional: MPXJ + jpype, needs a JDK 21 or 25
uv run python tests/reference/mpxj_cpm.py         # optional: MPXJ's scheduler, pinned commit
```

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
   help, DCMA DECM v8.0 or DCMA 14-Point. Each rule names its source (`source` field of
   the TOML, docstring of the function). Where no source settles a behaviour, write it
   down as an open question (`UNRESOLVED`, [docs/backlog.md](docs/backlog.md)) instead of
   guessing.
3. **A number changes only with evidence.** A change that moves a computed value comes
   with a test that fails before and passes after, and the evidence for the new value: a
   P6 export, the held-out P6 corpus, MPXJ's scheduler, or a hand calculation written in
   the test.
4. **Simple over clever.** One function per check, one place per P6 concept, no new
   dependency without a reason stated in the pull request.

Units: durations and floats are stored in hours; `_d` columns are working days of the
activity's own calendar; activities are identified by `task_code` (Activity ID), never
`task_id`. Mixing hours and days, or calendar days and working days, is the most common
source of a wrong number.

## Where a change goes

| Change | Goes in | Never in |
|---|---|---|
| What a P6 column means (units, identity, best dates, % complete type) | `xer/model.py` | analyses, pages |
| Working time, calendars | `xer/calendar.py` (`WorkCalendar`, `TimeAxis`) | ad hoc date arithmetic |
| A built-in check | one function in `analysis/p6/`, `dcma/`, `decm/` or `integrity.py` + its metric in `standards/*.toml` | a page |
| A rule for your own standard | a parameterised `@rule` in `analysis/rules.py` | an `if standard == ...` branch |
| A metric's explanation | `analysis/explain.py` | page text |
| A chart | `viz/` | `app/views/` |
| A page | `app/views/<page>.py`, composing analyses and figures | a calculation |
| A tunable default no standard owns | `config.py` (`Settings`) | constants scattered in modules |

## Verification

Run before opening a pull request, and report what was run and what it printed:

```bash
uv run pytest -rs                     # the whole suite; MPXJ tests skip without Java: say so
uvx ruff check src tests scripts      # no new finding
uvx ruff format --check src tests scripts
uvx bandit -r src -ll
```

Then, depending on what changed:

| Changed | Also run | Pass criterion |
|---|---|---|
| CPM, calendars, options | `uv run pytest tests/test_cpm.py tests/test_cpm_properties.py tests/test_p6_heldout.py` | P6 reference files identical to the minute; no `FLOORS` entry lowered |
| CPM, with Java | `uv run pytest tests/test_crosscheck_mpxj.py` | new differences fixed or named in `UNRESOLVED` with a reason |
| A check or a standard | `uv run pytest tests/test_rules.py tests/test_p6_check_schedule.py tests/test_calendar_and_standards.py tests/test_explain.py` | one hand-made schedule per behaviour, count written in the test |
| Any computed number | `uv run pytest tests/test_characterization.py` | no change in `tests/golden/standards.json`, or the change reviewed (below) |
| Parser or model | `uv run pytest tests/test_parser.py tests/test_model.py tests/test_reference.py` | third-party stated results still met |
| App pages | `uv run pytest tests/test_app.py` | every page renders headless |
| `Dockerfile`, `compose.yaml`, `deploy/` | `uv run pytest tests/test_docker.py` | loopback only, non-root, no published port in `deploy/`, no secret logged |

**Golden file.** `tests/test_characterization.py` compares every metric of every built-in
standard with `tests/golden/standards.json`: a refactor changes no number. After an
intended change, `XERSCOPE_UPDATE_GOLDEN=1 uv run pytest tests/test_characterization.py`
rewrites the file and fails by design; review the diff, then rerun without the variable.

**Moved values.** A pull request that moves a value of the golden file, of `FLOORS` or of
a standard TOML (prose fields aside) gives one line per value in its description,
`ID: old -> new — source`; the `values` workflow (`scripts/check_value_justification.py`)
prints the lines to complete, and fails on a missing one or on a lowered `FLOORS` value.

**Oracle marker.** `@pytest.mark.oracle(kind)` names where a test's expected values come
from: `p6`, `mpxj`, `standard` (the text of a standard), `property` (holds on any input)
or `characterization` (xerscope's own frozen output). Another kind stops the collection.
`uv run python scripts/oracle_report.py` counts the tests by kind.

**Against P6 on your own file** (locally, never committed):
`uv run xerscope check FILE.xer --standard P6 --expect p6-summary.csv` and
`uv run xerscope recalc FILE.xer --report`.

### Adding or changing a check

1. Find the source text (Oracle help page, DECM metric ID, 14-Point item); write down
   population, numerator, denominator, unit and target before coding.
2. Build the smallest schedule that shows the behaviour with `xerkit`, write the expected
   count by hand in the test, watch it fail.
3. Implement the function; add the metric to the TOML with its `source`.
4. Check `xerscope standards --rules` lists it and the app explains it.
5. Update [docs/standards.md](docs/standards.md) and [docs/formulas.md](docs/formulas.md).

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
  code does, why, which source. No session logs, no tool attribution trailers, no
  generated-by lines.
- Author and committer are the contributor's own name and email, never a tool's: set
  `git config user.name` / `user.email` in the clone before the first commit. The
  `attribution` workflow fails a pull request whose commits, title or description break
  these two rules.
- Pull requests are squash-merged: edit the squash message so the subject describes the
  change, not the branch name.
- Before merging a Dependabot pull request, comment `@dependabot rebase` so it builds on
  the current `main`.

## Documentation

Docs and comments state what the code does, why, and the source. A pull request that
changes behaviour updates the doc that describes it in the same pull request; a known
gap goes to [docs/backlog.md](docs/backlog.md), and leaves it when fixed.

## Security

Vulnerabilities are reported privately: see [SECURITY.md](SECURITY.md).
