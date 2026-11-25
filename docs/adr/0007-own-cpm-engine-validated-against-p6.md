# ADR-0007: An own CPM engine in Python, P6-exact by evidence, with MPXJ kept as an optional cross-check

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29: `analysis/cpm.py` and `crosscheck.py` in `49ad764` (initial commit); validation against P6 23.12 and MPXJ's `PrimaveraScheduler` in `69d6f99`; 2026-10-30: `verify/` package and CI evidence gates in `881fdb0` (#2) |
| Scope | `src/xerscope/analysis/cpm.py`, `src/xerscope/analysis/resource_placement.py`; `src/xerscope/verify/` and `src/xerscope/crosscheck.py`; `xerscope recalc`, `xerscope crosscheck` |
| Sources | Oracle P6 Professional 23.12 / 24 scheduling behaviour (F9); P6 Professional 23.12.1 held-out corpus; MPXJ `PrimaveraScheduler` (joniles/mpxj, pinned commit); [docs/cpm.md](../cpm.md) (purpose and Validation); [CONTRIBUTING.md](../../CONTRIBUTING.md), "Changing the CPM engine"; recent engine commits `4dbebba`, `8c07ded`, `9278f49` |

## Context

Several results of xerscope need the dates P6 would compute now, not only the dates stored in the
file:

- **Integrity** (`standards/integrity.toml`): INT-01 and INT-03 compare the stored activity and
  assignment dates with a recalculation (`compare_with_stored`, `compare_assignments`); INT-04
  names the activities on a logic loop with `loop_members`, the set the engine refuses
  (`CycleError`); INT-07 and INT-08 read the recalculated dates too. A file edited after its last
  F9 makes every float-based check read stale numbers, and only a P6-exact recalculation shows it.
- **The critical path test** (DCMA-12 `dcma_12_critical_path_test`, DECM 06A401a
  `decm_06a401a_critical_path_test`, both through `critical_path_output`): delay the first open
  activity of the longest path by `slip_days` (600 working days in `dcma.toml` and `decm.toml`),
  reschedule, check that the finish moves (`cpm.critical_path_test`).
- **The longest path fallback** (`analysis/longest_path.py`), the half-step forensic reading
  (`analysis/forensics.py`), and the recalculation views of the app.

These results are only worth showing if they equal P6's under the scheduling options the file
carries (progressed-activities option, float type, lag calendar, SS lag from early or actual
start, expected finish, open ends critical, must finish by, relationships to other projects),
under every constraint type, and for resource-dependent work. MPXJ's `PrimaveraScheduler`, the
only other open implementation at hand, models a subset of P6's options:
`verify/mpxj_cpm.py::mpxj_unsupported` names a file it cannot compare (progressed activities
under Actual Dates or Progress Override, SS lag from actual start, open ends critical, no lag
calendar stated, relationships to other projects ignored, a non-driving assignment on
resource-dependent work). It is also Java (a JDK and `jpype1` at run time), and the PyPI release
(16.10.0) predates the fix of joniles/mpxj#972 (`tests/reference/mpxj_cpm.py`).

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Use MPXJ's `PrimaveraScheduler` as the engine | no engine to maintain | Java runtime in the app and the image; the unsupported options above give no answer; a difference with P6 cannot be fixed in xerscope |
| Trust the stored dates only, no recalculation | nothing to write | INT-01/INT-03 and the critical path test become impossible; stale files pass unseen |
| **An own engine in Python, validated against P6's output, MPXJ kept as an optional second opinion (chosen)** | a large module (`cpm.py` and `resource_placement.py`) and a validation corpus to keep | every rule needs evidence; shapes no P6 output covers stay open |

## Decision

`analysis/cpm.py` is xerscope's own CPM engine. `schedule(snapshot)` recomputes, as P6
Professional does on F9, every activity's early and late dates, total and free float, longest
path and resource-assignment dates, from the logic, durations, calendars (on a minute axis,
`TimeAxis`, see ADR-0004), constraints, progress and assignments of the XER, and returns a
`Schedule` (`frame` indexed by `task_code`: `es`, `ef`, `remaining_start`, `ls`, `lf`, `tf_hr`,
`ff_hr`, `resource_dependent`, `longest_path`, `rem_override_hr`...; `finish`, `options`,
`warnings`, `assignments`). It honours the options read into `Options.from_snapshot`:
`progressed` (Retained Logic, Progress Override, Actual Dates), `float_type` (`FLOAT_TYPE`),
`lag_calendar`, `open_critical`, `lag_from_early_start`, `use_expected_finish`, `must_finish_by`,
`honor_external` and `collapse_early_expected_finish` (by export version), plus every constraint
type in primary and secondary slots (`START_LIKE`, `LATE_LIKE`, `MANDATORY`,
`AS_SECOND_CONSTRAINT`). Resource-dependent placement is in `analysis/resource_placement.py`
(`place_forward`, `place_backward`, `assignment_late_dates`), pure functions the engine calls.
What it does not model (leveling, multiple float paths) is reported in `warnings`, not computed.
The plain recalculation and its comparison with the stored dates are cached on the snapshot.

MPXJ is optional and a hint only:

- the extra `crosscheck` (`pyproject.toml`: `mpxj>=16.10.0`, `jpype1>=1.7.1`, a JDK on `PATH`);
- `verify/mpxj_cpm.py`: MPXJ's `PrimaveraScheduler` as a second engine (`mpxj_schedule`,
  `cpm_crosscheck`), its scheduler compiled from a pinned commit by `tests/reference/mpxj_cpm.py`
  (`MPXJ_CPM_COMMIT`); `P6_SETTLED` lists the shapes P6 settled against MPXJ, `UNRESOLVED` the
  open ones, `mpxj_inconsistent` MPXJ's self-contradictions;
- `verify/mpxj_reader.py`: MPXJ as an independent reader of the XER tables (`compare_file`,
  `compare_paths`);
- `verify/p6_corpus.py` (`p6_heldout_score`) and `verify/shapes.py` (`difference_report`) are
  pure Python and need no MPXJ.

`crosscheck.py` re-exports `verify/`; nothing in the app imports either (layer rules,
ADR-0001). The engine follows P6; where MPXJ and P6 disagree, P6 wins (ADR-0008).

An engine change follows the procedure of [CONTRIBUTING.md](../../CONTRIBUTING.md), "Changing
the CPM engine": reproduce the difference on a reference file or a hand case; change one rule at
a time; rerun the P6 files, the held-out corpus and the MPXJ cross-check (a gain on one shape
that costs another is not a fix); raise the matching `FLOORS` values, never lower them; record
in [docs/cpm.md](../cpm.md) which source settled the rule.

Commands:

```bash
uv run xerscope recalc FILE.xer            # stored values reproduced per field, first differences (--show N)
uv run xerscope recalc FILE.xer --report   # differences grouped by activity shape (verify/shapes.py)
uv run xerscope crosscheck --p6 SET_DIR    # the recalculation against P6 23.12 on a held-out set
uv run xerscope crosscheck --cpm FILE.xer  # against MPXJ's scheduler (needs the crosscheck extra)
uv run xerscope crosscheck PATHS           # MPXJ as an independent reader
```

## Consequences

Positive:

- INT-01 / INT-03, the critical path test and the longest path read P6-exact values under every
  option the engine models, including those MPXJ does not.
- The app and the container need no Java runtime.
- A difference is fixable in xerscope and is pinned by a corpus witness once fixed
  (`PINNED` in `tests/test_p6_heldout.py`: 67 rules, 136 witnesses).

Negative:

- `cpm.py` is a large module (about 2,500 lines) whose rules are kept to P6 by evidence, not by
  a specification Oracle publishes; several rules are observed in P6's output and not explained
  by any Oracle page.
- The held-out corpus is synthetic and scheduled by P6 23.12; shapes it never draws are untested.

Follow-ups: [docs/backlog.md](../backlog.md), "CPM: where the engine still differs from P6
23.12" (resource-dependent late side, task-dependent sets H10 / H16 / H24 / H27 / H29, rules
observed not explained, sub-minute rounding), and "Proof: get an oracle for what has none"
(weekly exports after F9 checked with `xerscope recalc --report`).

## Verification

- `tests/test_p6_heldout.py::test_share_of_values_identical_to_p6_never_drops` (one `FLOORS`
  entry per set H1 to H30, lowest 0.982),
  `::test_rule_reproduces_p6_on_its_corpus_witness` (`PINNED`),
  `::test_float_type_codes_read_as_p6_does`, `::test_total_float_agrees_wherever_the_four_dates_do`.
- `tests/test_cpm.py::test_recalculation_reproduces_the_stored_dates_to_the_minute`,
  `::test_longest_path_matches_p6s_flag`, `::test_level_of_effort_dates_reproduce_p6`,
  `::test_assignment_dates_reproduce_p6`, and the hand cases of `tests/test_cpm.py` and
  `tests/test_cpm_*.py` (one file per constraint, expected-finish or resource-placement case).
- `tests/test_cpm_properties.py::test_invariants_not_started`, `::test_invariants_progressed`,
  `::test_invariants_fs_only`, `::test_options_constraints_calendars` (seeded random networks).
- `tests/test_crosscheck_mpxj.py::test_p6_xerscope_and_mpxj`,
  `::test_random_networks_agree_with_mpxj`, `::test_hand_cases_agree_with_mpxj`,
  `::test_demo_dates_are_confirmed_by_mpxj`.
- CI, `.github/workflows/tests.yml`: job `test` runs the suite with
  `XERSCOPE_REQUIRE: reference,p6-corpus`; job `crosscheck` (Windows, Java 21 and 25) builds the
  pinned scheduler (`tests/reference/mpxj_cpm.py --force`) and runs
  `tests/test_crosscheck_mpxj.py tests/test_reference.py` with `XERSCOPE_REQUIRE:
  reference,p6-corpus,mpxj`.
- `tests/test_architecture.py` (`LAYERS`): `verify/` imports only `xer/`, `analysis/cpm.py` and
  `config.py`; nothing in `app/` imports `verify/` or `crosscheck.py`.

## References

- `src/xerscope/analysis/cpm.py`: `schedule`, `Options`, `Schedule`, `compare_with_stored`,
  `compare_assignments`, `loop_members`, `CycleError`, `critical_path_test`, `CptResult`.
- `src/xerscope/analysis/resource_placement.py`: `place_forward`, `place_backward`,
  `assignment_late_dates`.
- `src/xerscope/analysis/integrity.py`; `src/xerscope/analysis/dcma/fourteen_point.py:dcma_12_critical_path_test`;
  `src/xerscope/analysis/decm/schedule_metrics.py:decm_06a401a_critical_path_test`.
- `src/xerscope/verify/mpxj_cpm.py` (`mpxj_unsupported`, `P6_SETTLED`, `UNRESOLVED`),
  `src/xerscope/verify/mpxj_reader.py`, `src/xerscope/verify/p6_corpus.py`,
  `src/xerscope/verify/shapes.py`, `src/xerscope/crosscheck.py`; `tests/reference/mpxj_cpm.py`.
- [docs/cpm.md](../cpm.md): purpose, "Validation", "Critical path test", "Not modelled".
- [docs/architecture.md §5](../architecture.md) (`cpm.py`, `resource_placement.py`, "`verify/`:
  independent checks, strongest source first").
- Related: ADR-0004 (units and the minute axis), ADR-0005 (P6 as the reference), ADR-0008
  (evidence hierarchy).
