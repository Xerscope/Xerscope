# ADR-0013: Mutation testing of selected modules, run weekly against a committed baseline

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-12 (`fe37b9b`, "Mutation score with a baseline that cannot go down, on three modules", #201); weekly-only trigger and memory limit the same day (`174f22f`, #202); time limit and baseline from the first full GitHub run (`acf280e`, #206) |
| Scope | `pyproject.toml` (`[tool.mutmut]`, dev group `mutmut==3.8.1`), `scripts/mutation.py`, `tests/mutation_baseline.json`, `tests/test_mutation.py`, `.github/workflows/mutation.yml`, `.github/CODEOWNERS` |
| Sources | [CONTRIBUTING.md](../../CONTRIBUTING.md), "Verification" ("Weekly checks"); mutmut 3.8.1 (`stats.status_by_exit_code`, as cited in `scripts/mutation.py`); commits `fe37b9b`, `174f22f`, `acf280e` |

## Context

Line coverage says a line ran, not that a test would fail if that line computed something
else. The arithmetic modules (progress and earned-value figures, working time on a calendar,
the standards' targets and parameters) can lose a `<` for a `<=` or a constant by one without
any test noticing. Before `fe37b9b`, such mutations were done by hand, one test at a time, and
nothing measured how much of a module the tests protect, nor stopped that share from going
down (commit message).

A full mutation run is long: the first full run on GitHub took 94 minutes for 2,378 mutants
(`acf280e`). Two mutants of the calendar blob parser looped while growing a list without end;
mutmut limits a mutant's CPU time, not its memory, and the first run ended on a runner
shutdown (`174f22f`).

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Coverage only | none beyond the suite | a line that runs counts as tested even when no assertion depends on it |
| Mutation run on a pull request that touches the mutated modules, their tests, the configuration or the baseline (`paths` filter), plus every Monday and by hand (the first version of `mutation.yml`, `fe37b9b`) | about 52 minutes per full run at the measured pace (`174f22f`; the first full GitHub run took 94 minutes, `acf280e`) | too slow for a pull request; a runaway mutant could hold the runner |
| **A weekly and manual run on three listed modules, each mutant under a memory limit, compared with a committed baseline (chosen, `174f22f`)** | one run a week; a baseline to raise when the score rises | a drop is seen up to a week after the pull request that caused it; decorated `@rule` checks are out of reach |

## Decision

**What is mutated.** `[tool.mutmut]` `source_paths` lists three modules:
`src/xerscope/analysis/progress.py`, `src/xerscope/xer/calendar.py` and
`src/xerscope/analysis/standards.py`. mutmut leaves decorated functions alone, so the `@rule`
checks of `analysis/p6` and `analysis/dcma` are out of its reach and their modules are not
listed. `also_copy = ["src", "docs"]` copies the rest of the package as it is, and `docs/`
because a test reads `docs/standards.md`.

**What runs against each mutant.** `pytest_add_cli_args_test_selection` names the fast test
files that exercise those modules (`test_rules.py`, `test_p6_check_schedule.py`,
`test_p6_checksched.py`, `test_calendar_and_standards.py`, `test_boundaries_blind.py`,
`test_standards_conformity.py`, `test_ppc_blind.py`, `test_weekly.py`,
`test_shift_calendar.py`, `test_time_semantics.py`, `test_result_contracts.py`,
`test_demo_counts_blind.py`, `test_characterization.py`, `test_scores.py`, `test_explain.py`).
A mutant only a slow suite would kill (P6 corpus, MPXJ, app pages) counts as survived.

**The check.** `scripts/mutation.py` reads the `*.py.meta` files mutmut leaves under
`mutants/` and counts, per module, mutants, killed (exit codes 1 and 3: a failed test, or an
internal error of pytest), survived (0), no tests (5, 33) and unchecked (no exit code).
`--check tests/mutation_baseline.json` fails when:

- a module's share of killed mutants is lower than in the baseline (compared as
  `killed × baseline mutants` against `baseline killed × mutants`, so a changed mutant count
  does not mislead);
- a module of the baseline was not measured;
- a mutant was left unchecked (an interrupted run).

A higher score, and a module absent from the baseline, are listed, not failed, so the baseline
can be raised and the gain kept. The baseline holds, per module, mutants / killed / survived /
no tests: `analysis/progress.py` 979 / 848 / 131 / 0, `analysis/standards.py` 404 / 256 / 131
/ 17, `xer/calendar.py` 995 / 745 / 225 / 24. mutmut is pinned to `==3.8.1` in the dev group
because the baseline holds its counts and the exit-code mapping is its own.

**The workflow.** `.github/workflows/mutation.yml` runs on `workflow_dispatch` and on
`schedule` (`cron: "47 5 * * 1"`, every Monday), never on a pull request or a push. It is a
separate workflow so it does not gate the image publish (every job of `tests.yml` does). One
job, `timeout-minutes: 150`, Python 3.13 (the baseline's): `uv sync --locked`, then
`ulimit -v 4000000` (about 4 GB of address space per process) before `uv run mutmut run`, so a
mutant that allocates without end ends on a `MemoryError`, counted as killed; then
`uv run python scripts/mutation.py --markdown "$GITHUB_STEP_SUMMARY" --check
tests/mutation_baseline.json`. Runs of one branch do not overlap (`concurrency`).
`tests/mutation_baseline.json` is listed in `.github/CODEOWNERS`.

## Consequences

Positive:

- The share of each module's mutants the fast tests kill can only go up; a weaker test suite
  turns the Monday run red.
- The job summary lists the counts on every run, green or red.
- A runaway mutant costs one `MemoryError`, not a lost runner; a stuck run stops at 150
  minutes instead of GitHub's six-hour default.

Negative:

- A drop is found up to a week after the pull request that caused it, and is not tied to it by
  CI.
- Three modules only; the `@rule` checks, the CPM engine and the app are not mutated.
- Survivors (131 + 131 + 225 in the baseline) are counted, not listed in the repository; a
  mutant only a slow test kills counts as survived.

Follow-ups: none recorded in [docs/backlog.md](../backlog.md).

## Verification

- `tests/test_mutation.py::test_counts_read_from_the_exit_codes`, `::test_same_scores_pass`,
  `::test_lower_score_fails_even_with_more_mutants_killed`,
  `::test_same_share_on_another_count_passes`, `::test_higher_score_is_listed_not_failed`,
  `::test_module_of_the_baseline_not_measured_fails`, `::test_unchecked_mutants_fail`,
  `::test_new_module_is_listed_not_checked`, `::test_check_exit_code`,
  `::test_the_mutation_job_runs_weekly_or_by_hand_and_caps_the_memory_of_a_mutant` (only
  `workflow_dispatch` and a Monday `schedule`; a `timeout-minutes` above 94 and at most 180;
  `ulimit -v` right before `uv run mutmut run`; the check against the baseline after it;
  `mutmut` absent from `tests.yml`).
- CI: `.github/workflows/mutation.yml` job `mutation`. `tests/test_mutation.py` itself runs in
  every `tests.yml` job `test`.

## References

- `scripts/mutation.py`: `measure`, `compare`, `score`, `markdown`, `KILLED`, `SURVIVED`,
  `NO_TESTS`.
- `pyproject.toml`: `[tool.mutmut]` (`source_paths`, `also_copy`,
  `pytest_add_cli_args_test_selection`), `[dependency-groups]` dev (`mutmut==3.8.1`).
- `.github/workflows/mutation.yml`; `tests/mutation_baseline.json`.
- [CONTRIBUTING.md](../../CONTRIBUTING.md), "Verification" ("Weekly checks");
  [docs/architecture.md](../architecture.md) §9.
- Related: ADR-0011 (golden files), ADR-0012 (fitness ratchet), ADR-0027 (only a tested commit
  is published).
