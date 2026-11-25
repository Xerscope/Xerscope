# ADR-0005: Primavera P6 Professional as the reference; every rule names its source, open questions are recorded not guessed

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`49ad764`, initial commit: README "aligned on P6 Professional 24"; `69d6f99`, held-out P6 23.12 corpus and MPXJ); written as Rule 2 of `CONTRIBUTING.md` on 2026-11-02 (`9ef651d`, #22) |
| Scope | `src/xerscope/analysis/cpm.py`, `src/xerscope/analysis/p6/`, `analysis/dcma/`, `analysis/decm/`, `analysis/integrity.py`, `src/xerscope/standards/*.toml`, `src/xerscope/verify/`, `docs/standards.md`, `docs/cpm.md`, `docs/backlog.md` |
| Sources | Oracle P6 Professional 24 User Guide, Check Schedule (101393) and client help 101248; P6 EPPM help 46277-46291; DCMA DECM v8.0; DCMA-EA PAM 200.1 (14-Point); `69d6f99` "Validate the CPM against P6 23.12 (held-out corpus), MPXJ's scheduler and two new P6 exports"; `6a72be9` "... P6-12, P6-13 and P6-15..17 follow a P6 Professional report (#18)"; `d53f4f4` "P6 checks against a P6 Professional 26.8 Check Schedule report: P6-01, P6-10a/b, INT-08 (#80)"; `9ef651d` (#22, `CONTRIBUTING.md`) |

## Context

xerscope recomputes what planners otherwise read in Primavera P6: early and late dates, float,
the critical path, the Check Schedule report, the scheduling log. Its users compare its numbers
with P6 and with the standards their contracts cite. A number that differs from P6 with no stated
reason cannot be trusted, and a rule written from intuition cannot be reviewed.

The documentation is incomplete and sometimes contradicts P6's behaviour:

- the P6 Professional 24 help of the Check Schedule dialog (101248) is silent on several
  populations, and the P6 EPPM help of each report section (46277-46291) differs from it in four
  places (finish milestones in the logic successor check, completed activities in late activities,
  an activity without baseline finish in BEI, the remaining finish of in-progress work in invalid
  dates; `docs/standards.md`);
- report R1, a P6 Professional Check Schedule report on a real schedule, contradicts 101248 on
  P6-12 (completed activities left out) and P6-13 (BEI divides by every baseline activity);
- no public XER comes from P6 Professional 24 itself, and no public file comes with a Check
  Schedule report (`README.md` "Validation").

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Follow the help text alone | the texts are public and citable | silent or contradicted by P6's own reports in the places above |
| Follow an independent engine (MPXJ's PrimaveraScheduler) as the reference | runs on any file | MPXJ differs from P6 on shapes the held-out corpus settled (`verify/mpxj_cpm.py`, `P6_SETTLED`) and contradicts itself on some (`mpxj_inconsistent`) |
| P6 Professional 24 documentation as the target; P6's own output, from versions that bracket 24, as the evidence; each check from its own standard's text; where nothing settles a behaviour, write it as UNRESOLVED and pin the chosen reading with a test (chosen) | evidence has to be produced (a corpus fetched, a synthetic project scheduled in P6, a report kept outside the repository) | a behaviour no P6 output shows stays a reading, listed as open |

## Decision

**Target.** Calculation behaviour follows the P6 Professional 24 documentation; the app is
"aligned on P6 Professional 24" (`README.md`). Checks follow their own standard: the P6 Check
Schedule help (101248; EPPM 46277-46291 where it is silent), DCMA DECM v8.0, DCMA 14-Point
(PAM 200.1), and the Integrity checks the P6 scheduling log (Schedule Project Log).

**Evidence from the versions that bracket 24.**

| Behaviour | Evidence | Where |
|---|---|---|
| CPM: early / late dates, floats | P6 Professional 23.12.1 held-out corpus (30 sets of 12 synthetic schedules scheduled by P6, results read from its database) | `tests/test_p6_heldout.py`, `verify/p6_corpus.py` |
| CPM, assignments, longest path | public P6 exports with stored dates, among them a P6 25.12 export | `tests/test_cpm.py` |
| Check Schedule populations and scheduling log | a P6 Professional 26.8 Check Schedule report and F9 log on CHECKSCHED, a synthetic project of 14 activities and 18 relationships anyone can rebuild | `tests/test_p6_checksched.py` |
| P6-12, P6-13, P6-15 to P6-17 | report R1, kept by the maintainer outside the repository and cited by this label only | rebuilt by hand in `tests/test_p6_check_schedule.py`; local check `tests/test_p6_witness.py` |

**Order of authority.** P6's output first: where a report contradicts the help, the report is
followed (R1 on P6-12 and P6-13; a P6 Professional 26.8 report on P6-01 start milestones and on
Invalid Progress Dates printed as two lines, P6-10a / P6-10b; where 101248 is silent, a P6
Professional r22.12 report analysed by Ten Six). For the CPM, P6 wins over MPXJ, and the
difference is recorded against MPXJ (`P6_SETTLED`). Expected values are never xerscope's own
output (`docs/cpm.md` "Validation").

**Every rule names its source.** The `source` field of each metric in `standards/*.toml`
(Oracle page, DECM metric ID, PAM paragraph), the docstring of each check function (the Oracle
pages are cited in each docstring of `analysis/p6/check_schedule.py`), and `docs/cpm.md` for each
CPM rule ("Record in docs/cpm.md which source settled the rule", `CONTRIBUTING.md`).

**Open questions are written, not guessed.** Where no source settles a behaviour:

- `UNRESOLVED:` in the metric's `source` (e.g. `standards/dcma.toml`) or in the rule's docstring
  (`analysis/p6/check_schedule.py`, `analysis/dcma/fourteen_point.py`,
  `analysis/decm/schedule_metrics.py`);
- an entry of `UNRESOLVED` in `verify/mpxj_cpm.py` for a CPM difference with MPXJ that no P6
  output settles: a comparison that meets one is reported, not failed;
- an item of `docs/backlog.md` ("Proof: get an oracle for what has none", "CPM: where the engine
  still differs from P6 23.12").

The reading chosen meanwhile is pinned by a named test (for example
`tests/test_p6_check_schedule.py::test_relationship_checks_say_which_external_links_they_hold`)
until a P6 output settles it.

## Consequences

- A reviewer can check any rule against a citable text or a P6 output; a disagreement with P6
  names a rule to fix rather than a tuning.
- Not established, and said so in `README.md`: no export from P6 Professional 24 itself (23.12
  and 25.12 bracket it), no public file with a Check Schedule report, and resource-dependent work is
  the largest CPM gap. Users are asked to run `xerscope recalc` and `xerscope check` next to P6 on
  their own files.
- R1 cannot be shared: the tests rebuild each behaviour it settled by hand, and the repository
  quotes none of its figures, dates or names (see
  [ADR-0014](0014-no-real-schedule-in-repository.md)).
- Open items, from `docs/backlog.md`: more Check Schedule reports on shareable files (LOE in
  P6-01, P6-10a with a remaining early start before the data date, the hours per day behind `x`
  on a calendar other than 8 h, FF / SF links in P6-15, the constraint options of P6-16 / P6-17);
  a DECM output on one real file; P6-13 against a separate Project Baseline (`docs/standards.md`,
  "Unresolved").

## Verification

- `tests/test_p6_heldout.py`: `test_share_of_values_identical_to_p6_never_drops` (`FLOORS`, one
  per set), `test_rule_reproduces_p6_on_its_corpus_witness` (`PINNED`, one corpus activity per
  rule); requires the fetched corpus (`tests/reference/fetch_p6_heldout.py`).
- `tests/test_p6_checksched.py`: `test_the_p6_standard_has_the_lines_of_the_report`,
  `test_check_schedule_counts_match_the_p6_26_report`,
  `test_check_schedule_lists_match_the_p6_26_report`,
  `test_late_activities_variance_matches_the_report`, `test_the_recalculation_reproduces_p6s_f9`,
  `test_integrity_lists_match_the_p6_26_scheduling_log`.
- `tests/test_p6_check_schedule.py`: Oracle's help, one quoted sentence per test, and R1's
  behaviours rebuilt by hand.
- `tests/test_crosscheck_mpxj.py`: `test_random_networks_agree_with_mpxj`,
  `test_hand_cases_agree_with_mpxj`, `test_demo_dates_are_confirmed_by_mpxj`; only a named
  `UNRESOLVED` case or an MPXJ inconsistency excuses a difference (CI job `crosscheck`, Windows,
  Java 21 and 25).
- `tests/test_p6_witness.py`: local only (`XERSCOPE_REQUIRE=witness`), skipped in CI.
- CI job `oracle-report` (`scripts/oracle_report.py`, never a gate): how many tests compare with
  P6, MPXJ, a standard's text, a property or the golden file (see
  [ADR-0008](0008-evidence-hierarchy-oracle-markers-and-floors.md)).

## References

- `src/xerscope/verify/mpxj_cpm.py`: `UNRESOLVED`, `P6_SETTLED`, `mpxj_inconsistent`
- `src/xerscope/verify/p6_corpus.py`: `p6_heldout_score`
- `src/xerscope/analysis/p6/check_schedule.py` (module and rule docstrings, P6 Professional 26.8
  report), `src/xerscope/analysis/integrity.py` (P6 log messages mirrored, P6 Professional 26.8 log)
- `src/xerscope/standards/p6.toml`, `dcma.toml`, `decm.toml`, `integrity.toml` (`source` fields)
- `README.md`: intro, "Validation"
- `CONTRIBUTING.md`: Rules 2 and 3, "Adding or changing a check", "Changing the CPM engine"
- `docs/standards.md`: "P6 Check Schedule (P6 Professional 24: 17 checks, 18 report lines)",
  "Sources" (R1)
- `docs/cpm.md`: "Validation"
- `docs/backlog.md`
- Related: [ADR-0007](0007-own-cpm-engine-validated-against-p6.md),
  [ADR-0008](0008-evidence-hierarchy-oracle-markers-and-floors.md),
  [ADR-0009](0009-standards-as-toml-one-function-per-check.md),
  [ADR-0014](0014-no-real-schedule-in-repository.md)
