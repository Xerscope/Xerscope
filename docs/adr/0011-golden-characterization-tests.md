# ADR-0011: Characterization (golden) files freeze every standard's result and every page

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-01 (`f9bb3bc`, "Tests: characterization test freezing every built-in standard's output"); baseline sections and the always-failing update mode the same day (`8c2c145`); the page golden file on 2026-11-13 (`7b515f0`, #212) |
| Scope | `tests/test_characterization.py`, `tests/golden/standards.json`, `tests/test_page_golden.py`, `tests/golden/pages.json`, `tests/conftest.py` (`store`, `sample_dir`, `read_folder`), `scripts/check_value_justification.py`, `.github/workflows/values.yml`, `.github/CODEOWNERS`, `.github/pull_request_template.md` |
| Sources | [CONTRIBUTING.md](../../CONTRIBUTING.md), "Verification" ("Golden file", "Moved values"), "Readable code" rule 6; [docs/architecture.md](../architecture.md) §9; commits `f9bb3bc`, `8c2c145`, `7b515f0`, `b1f5236` ("Page golden: wrap the page list under the line limit"), `37244b8` ("Health page golden: the baseline column of the results table") |

## Context

Most of xerscope's code turns a schedule into numbers (check counts, ratios, flagged
activities) and into pages that show them. Refactors of the large modules, readability
rewrites (CONTRIBUTING.md, "Readable code") and moves between modules are frequent; each of
them must change no number and no page. A unit test pins one behaviour on a hand-made file;
it does not show that the 56 metrics of the four built-in standards, run on a realistic
series with and without a baseline, still give what they gave before. A reviewer cannot
check that by reading a large diff.

The output to freeze must be reproducible without a real schedule (ADR-0014) and must carry
no activity name, so the frozen file can be committed to a public repository.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Unit tests only, one hand-made file per behaviour | already there | proves each rule in isolation, not that a refactor left every result of every standard unchanged |
| Snapshot of whole result frames or rendered HTML | simple to write | holds names and layout noise; a diff is unreadable and changes for reasons that are not results |
| **Golden files of the identifying parts only (status, counts, value, flagged identifiers; page elements as text lines), rewritten on request by a run that always fails (chosen)** | two test files, two JSON files to review on intended changes | freezes xerscope's own output: proves "unchanged", never "right" (that is ADR-0008's role) |

## Decision

**Standards golden file.** `tests/test_characterization.py` (marker `oracle("characterization")`)
runs every metric of every standard returned by `builtin_standards()` (P6, DCMA, DECM,
INTEGRITY) through `run_standard` and stores, per metric, in `tests/golden/standards.json`:

- `status`, `numerator`, `denominator`;
- `value`, rounded to 6 decimals (`VALUE_DECIMALS`: float noise below that is not a change);
- `flagged`: the sorted identifiers of the flagged rows, Activity IDs (`task_code`) or
  `pred->succ` for relationship rows, never names (`flagged_identifiers`); an empty list for
  a rule whose rows carry neither column (its counts still pin it);
- `note` only when `status` is `error`, so a changed exception shows.

The file has four sections, one per test:

| Section | Test | Input |
|---|---|---|
| `demo` | `test_demo_series_matches_golden` | the demo series (8 weekly files from `sample.generate`, fixture `store`), no baseline, the series passed so previous-update checks run |
| `demo-planned` | `test_demo_planned_baseline_matches_golden` | the same series with `Baseline.planned` |
| `demo-first-as-baseline` | `test_demo_first_as_baseline_matches_golden` | the same series with the first update as baseline (`Baseline.from_snapshot(store.first)`) |
| `reference` | `test_reference_files_match_golden` | the pinned third-party `.xer` files of `tests/reference/sources.py`, `p6viewer/Hotel Project.xer` excluded (`EXCLUDED_REFERENCE`: 4,217 activities, covered by the CPM tests); skips through `missing("reference", ...)` when not fetched, fails in CI where `XERSCOPE_REQUIRE` names `reference` |

These are the three ways `xerscope check` can be called on a series, plus the reference files.
A difference fails with the count of differing entries and the first 20 (`SHOWN_DIFFS`),
each as `key: golden=... now=...`.

**Pages golden file.** `tests/test_page_golden.py` (marker `oracle("characterization")`) opens
the app headless (`streamlit.testing.v1.AppTest`) on the demo series (`XERSCOPE_DATA` set to
`sample_dir`, every file ticked in the Files window by `conftest.read_folder`), with
`XERSCOPE_BASELINE` and `XERSCOPE_DATA_LOCKED` unset, and visits the sidebar then the pages of
`PAGES` in menu order (`overview`, `gantt`, `health`, `audit`, `changelog`, `forensics`,
`earned_value`, `milestones`, `ppc`, `export`, `debug`) in one app, as a user would (what a
page shows can depend on the pages opened before it). Each element becomes one line, top to
bottom: texts in full, a metric with its value and delta, a widget with its label (and its
value for a choice), a table with its row count and columns, a chart with its trace types, a
"How to read" popover by its label only. Layout containers are walked, not listed; colours
and layout are not seen. The lines are compared with `tests/golden/pages.json` as a unified
diff per page.

**Update mode.** With `XERSCOPE_UPDATE_GOLDEN=1`, each test rewrites its file (one section
for the standards file, after checking it survives the JSON round-trip; the whole file for
pages) and then fails on purpose (`pytest.fail`), so a rewrite can never pass green. The
next run, without the variable, must pass.

**Review of a moved value.** A pull request that moves a value of `tests/golden/standards.json`
gives one line per value in its description, `ID: old -> new — source`;
`scripts/check_value_justification.py` (workflow `values`) lists the lines to complete and
fails on a missing one (ADR-0008). `tests/golden/` is listed in `.github/CODEOWNERS`, so a
change requests the maintainer's review. A change of `tests/golden/pages.json` is reviewed
from its diff (pull request template checklist); the values workflow does not read it.

## Consequences

Positive:

- A refactor, a move or a readability rewrite carries a mechanical proof that no result moved:
  1,904 standard entries (56 metrics × 34 file and baseline combinations) and every element
  of 11 pages plus the sidebar.
- An intended change shows as a reviewable diff of identifiers and counts, never of names.
- The file is safe to commit: identifiers of a generated series and of public files only.

Negative:

- The golden files prove that nothing changed, not that the result is right; a wrong number
  frozen once stays until a test with evidence moves it (ADR-0008).
- Every intended change of a result or of a page text needs the file regenerated and its diff
  read; a page change touches `pages.json` even for a reworded caption.
- The pages test runs the whole app headless (default timeout 180 s per run), one of the
  slower files of the suite.

Follow-ups: none recorded in [docs/backlog.md](../backlog.md).

## Verification

- `tests/test_characterization.py::test_demo_series_matches_golden`,
  `::test_demo_planned_baseline_matches_golden`, `::test_demo_first_as_baseline_matches_golden`,
  `::test_reference_files_match_golden`.
- `tests/test_page_golden.py::test_the_listing_reads_every_kind_of_element_the_pages_use`
  (every page starts with a title; only `popover` and `bidi_component` are read as a bare kind),
  `::test_page_shows_what_the_golden_file_holds` (parametrised over the sidebar and `PAGES`).
- `tests/test_check_value_justification.py::test_a_moved_golden_value_needs_its_line`,
  `::test_added_and_removed_golden_values_read_absent`.
- CI: `.github/workflows/tests.yml` job `test` runs both files with
  `XERSCOPE_REQUIRE: reference,p6-corpus`; `.github/workflows/values.yml` job
  `value-justification`. `tests/test_characterization.py` is also in mutmut's test selection
  (`[tool.mutmut]`, ADR-0013).

## References

- `tests/test_characterization.py`: `flagged_identifiers`, `entry_of`, `observe`,
  `observe_series`, `update_golden`, `check_against_golden`, `EXCLUDED_REFERENCE`,
  `VALUE_DECIMALS`, `SHOWN_DIFFS`.
- `tests/test_page_golden.py`: `PAGES`, `shown`, `_line`, `is_reading`, fixture `pages`.
- `tests/conftest.py`: fixtures `sample_dir`, `store` (`generate(..., weeks=8)`), `missing`;
  helper `read_folder`.
- `src/xerscope/analysis/standards.py`: `builtin_standards`; `src/xerscope/analysis/checks.py`:
  `run_standard`; `src/xerscope/analysis/baseline.py`: `Baseline.planned`, `Baseline.from_snapshot`.
- [CONTRIBUTING.md](../../CONTRIBUTING.md), "Verification" ("Golden file", "Moved values"),
  "Readable code" rule 6; [docs/architecture.md](../architecture.md) §9.
- Related: ADR-0008 (evidence hierarchy), ADR-0012 (fitness ratchet and proof of moves),
  ADR-0014 (no real schedule in the repository).
