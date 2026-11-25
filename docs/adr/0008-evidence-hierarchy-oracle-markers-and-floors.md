# ADR-0008: Evidence hierarchy for expected values: P6 output first, oracle markers on tests, floors that never drop

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29: `FLOORS` and the P6 held-out corpus test in `69d6f99`; 2026-10-30: `XERSCOPE_REQUIRE`, `missing()` and `PINNED` in `881fdb0` (#2); 2026-11-08: oracle marker (`ORACLE_KINDS`), `scripts/check_value_justification.py` and `values.yml` in `bb43109` (#148) |
| Scope | `tests/` (`conftest.py`, `test_p6_heldout.py`, `test_cpm.py`, `test_crosscheck_mpxj.py`), `pyproject.toml` (`[tool.pytest.ini_options]`), `scripts/oracle_report.py`, `scripts/check_value_justification.py`, `.github/workflows/tests.yml`, `.github/workflows/values.yml` |
| Sources | [docs/cpm.md](../cpm.md), "Validation" (three sources, strongest first); [CONTRIBUTING.md](../../CONTRIBUTING.md), Rule 3, "Golden file", "Moved values", "Oracle marker"; P6 Professional 23.12.1 held-out corpus (danafitkowski/cpp-cpm-engine, pinned in `tests/reference/sources.py`) |

## Context

A test that compares xerscope with a number xerscope produced proves only that nothing changed;
it does not prove that the number is right. xerscope is worth using only if its numbers are the
ones P6 or the standard would give (CONTRIBUTING.md, opening paragraph). So each expected value
needs a stated origin, an order of trust between origins, and guards that stop:

- a test from passing in CI because its evidence was missing and it skipped;
- a share of values identical to P6 from going down unnoticed;
- a computed value, a floor or a target from moving in a pull request without its evidence.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Expected values written from xerscope's own output (snapshot tests only) | cheap | freezes errors as well as results; says nothing about P6 |
| Every source treated alike (P6 exports, MPXJ, hand calculations) | simple | a disagreement between sources has no rule to settle it |
| **A ranked hierarchy (P6 first), every test labelled with its oracle, missing evidence failing in CI, floors and moved values justified (chosen)** | marker on each test, a values workflow, a P6 corpus to fetch | the marker is not yet on every test; the corpus is synthetic |

## Decision

**Hierarchy of evidence**, strongest first ([docs/cpm.md](../cpm.md), "Validation"); none of
them is xerscope's own output, and where two disagree P6 wins and the difference is recorded
against the other:

1. **P6 Professional 23.12.1 on the held-out corpus**: 30 sets of 12 synthetic schedules (H1 to
   H30), frozen before P6 scheduled them, P6's early and late dates and floats read back after F9
   (`tests/reference/fetch_p6_heldout.py`, scored through `crosscheck.p6_heldout_score` by
   `tests/test_p6_heldout.py` and `xerscope crosscheck --p6`). `FLOORS` holds each set's share of
   values identical to P6 at the last measurement (lowest: H10, 0.982) and fails on any drop;
   `PINNED` names the corpus activity each rule of the engine was taken from (67 rules, 136
   witnesses), so a regression on one rule is named rather than averaged away.
2. **Real P6 exports** with stored dates, compared to the minute (`tests/test_cpm.py`: dates,
   floats, longest path flag, LOE dates, assignment dates).
3. **MPXJ's `PrimaveraScheduler`**, an independent engine (`tests/test_crosscheck_mpxj.py`,
   `xerscope crosscheck --cpm`); open differences are named in `crosscheck.UNRESOLVED`, those P6
   settled in `crosscheck.P6_SETTLED` (ADR-0007).

For the checks, the evidence is the text of the standard (Oracle's help, DECM, PAM 200.1) and P6
Check Schedule reports; for invariants, properties on generated inputs; for refactors, the golden
files (ADR-0011).

**Oracle marker.** A test declares where its expected values come from with
`@pytest.mark.oracle(kind)` (marker declared in `pyproject.toml`), `kind` one of `ORACLE_KINDS` in
`tests/conftest.py`: `p6`, `mpxj`, `standard` (the text of a standard), `property` (holds on any
input) or `characterization` (xerscope's own frozen output). Any other kind, or a marker with
keyword arguments, stops the collection (`pytest_collection_modifyitems` raises
`pytest.UsageError`). `scripts/oracle_report.py` counts the collected tests by kind and those
without a marker (row `(none)`); it is a witness, not a gate (it exits 0 once collection succeeds).
The marker is not yet on every test; the report shows how many remain unmarked.

**Missing evidence fails in CI.** A test whose evidence is absent calls `missing(what, hint)`
(`tests/conftest.py`): it skips locally and says which command fetches the evidence, and fails
when `XERSCOPE_REQUIRE` names `what` (`reference`, `p6-corpus`, `mpxj`, `witness`; no CI job
requires `witness`, the local P6 report of `tests/test_p6_witness.py`, so that test skips in CI).
`.github/workflows/tests.yml` sets `XERSCOPE_REQUIRE: reference,p6-corpus` in job `test` and
`reference,p6-corpus,mpxj` in job `crosscheck`.

**Moved values and floors.** A pull request that moves a value of `tests/golden/standards.json`,
of `FLOORS` (`tests/test_p6_heldout.py`) or of a standard TOML (prose fields `name`,
`description`, `source` aside) gives one line per value in its description:
`ID: old -> new — source`. `scripts/check_value_justification.py` (standard library only, run by
`.github/workflows/values.yml` on `opened`, `synchronize`, `reopened` and `edited`) compares the
pull request with its base, prints the lines to complete, and fails on a missing line and on any
`FLOORS` value lowered or removed, even when justified. The same line is asked for a measure of
`tests/fitness_baseline.json` that gets worse (ADR-0012).

**A number changes only with evidence** (CONTRIBUTING.md Rule 3): a change that moves a
computed value comes with a test that fails before and passes after, and the evidence for the
new value (a P6 export, the held-out corpus, MPXJ's scheduler, or a hand calculation written in
the test).

## Consequences

Positive:

- Each expected value can be traced to its origin, and the share of tests resting on P6 or a
  standard's text is visible in every CI run (job `oracle-report`, written to the job summary).
- CI cannot go green by skipping its evidence.
- The engine's agreement with P6 only ratchets up; a lower floor cannot be merged.
- A reviewer sees every moved number with its source in the pull request description.

Negative:

- The corpus and the reference files must be fetched (pinned commit and checksums, cached in CI);
  the MPXJ job needs Java and runs on Windows only.
- Many tests do not yet carry the marker; the report counts them, nothing enforces it.
- What no P6 output settles stays open (`UNRESOLVED`, `docs/backlog.md`), however well MPXJ and
  xerscope agree.

Follow-ups: [docs/backlog.md](../backlog.md), "Proof: get an oracle for what has none" and
"CPM: where the engine still differs from P6 23.12".

## Verification

- `tests/test_oracle_report.py::test_known_kinds_and_unmarked_tests_pass_collection`,
  `::test_an_unknown_or_malformed_kind_stops_collection`, `::test_tally_counts_unmarked_tests_apart`,
  `::test_render_lists_kinds_then_unmarked_then_total`,
  `::test_collect_reads_the_marker_of_each_collected_test`.
- `tests/test_check_value_justification.py::test_a_moved_golden_value_needs_its_line`,
  `::test_a_floor_raised_needs_its_line_and_is_not_lowered`,
  `::test_a_floor_lowered_or_removed_fails_even_when_justified`,
  `::test_a_standard_target_and_param_need_a_line_prose_does_not`,
  `::test_a_line_inside_an_html_comment_does_not_count`,
  `::test_a_fitness_measure_that_gets_worse_needs_its_line`.
- `tests/test_p6_heldout.py::test_share_of_values_identical_to_p6_never_drops`,
  `::test_rule_reproduces_p6_on_its_corpus_witness` (module marker `oracle("p6")`).
- `tests/test_cpm.py::test_recalculation_reproduces_the_stored_dates_to_the_minute`;
  `tests/test_crosscheck_mpxj.py::test_p6_xerscope_and_mpxj` (marked `p6`: P6's stored dates
  decide, MPXJ is measured against them).
- CI: `.github/workflows/tests.yml` jobs `test`, `crosscheck` (`XERSCOPE_REQUIRE`) and
  `oracle-report` (`continue-on-error: true`); `.github/workflows/values.yml` job
  `value-justification`.

## References

- `tests/conftest.py`: `ORACLE_KINDS`, `pytest_collection_modifyitems`, `missing`.
- `tests/test_p6_heldout.py`: `FLOORS`, `PINNED`.
- `pyproject.toml`: `[tool.pytest.ini_options]` `markers` (`oracle(kind)`).
- `scripts/oracle_report.py`: `tally`, `render`; `scripts/check_value_justification.py`.
- `src/xerscope/verify/p6_corpus.py:p6_heldout_score`; `src/xerscope/verify/mpxj_cpm.py`:
  `UNRESOLVED`, `P6_SETTLED`.
- [docs/cpm.md](../cpm.md), "Validation"; [CONTRIBUTING.md](../../CONTRIBUTING.md), "Verification"
  ("Golden file", "Moved values", "Oracle marker"), "Changing the CPM engine".
- Related: ADR-0005 (P6 as the reference), ADR-0007 (CPM engine), ADR-0011 (golden files),
  ADR-0012 (fitness ratchet).
