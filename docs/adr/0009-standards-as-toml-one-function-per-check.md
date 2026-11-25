# ADR-0009: Standards as TOML data; one explicit function per built-in check, parameterised rules for a company standard

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29: standards as TOML, `rules.py` and `standards.py` in `49ad764` (initial commit; every check then a parameterised rule, e.g. P6-01 `rule = "missing_logic"`); 2026-11-02: one explicit function per built-in check in `af85f4e` (P6-01..04, DCMA-01..04) and `ec3e6ea` (DCMA-05..14); scores by criterion (`item`) added in `fca7ba9` (Standards: a score by criterion of the source (item), P6-10a/b one item (#324), 2026-11-19) |
| Scope | `src/xerscope/standards/*.toml`; `src/xerscope/analysis/p6/check_schedule.py`, `analysis/dcma/fourteen_point.py`, `analysis/decm/schedule_metrics.py`, `analysis/integrity.py`; `analysis/rules.py`, `analysis/standards.py`, `analysis/checks.py`; `xerscope standards`, `xerscope check`, `xerscope app --standards` |
| Sources | Oracle P6 Professional 24 Check Schedule help (101248, 101393); DCMA DECM v8.0 Guideline 6; DCMA-EA PAM 200.1 (14-Point); P6 scheduling log; [docs/architecture.md §5](../architecture.md) ("Why explicit functions plus TOML"); [docs/standards.md](../standards.md) (introduction, "Same check, several definitions"); [CONTRIBUTING.md](../../CONTRIBUTING.md), "Where a change goes", "Adding or changing a check" |

## Context

xerscope runs several schedule standards whose checks look alike but are not the same check.
P6's Large Float (`p6_06_large_float`) compares hours against the dialog's `x` and excludes
completed and LOE activities; DCMA-06 counts working days of each activity's calendar over
incomplete activities, milestones and LOE excluded (PAM 200.1 §4.0). The P6, DCMA and DECM
readings of logic, constraints, lags, durations and BEI differ in unit, population and boundary
([docs/standards.md](../standards.md), "Same check, several definitions"), and those differences
change results on real files.

A reviewer must be able to hold each built-in check against its source text (the Oracle page,
the DCMA sheet) line by line. At the same time, a company needs its own standard (its targets,
exclusions and units) without writing Python. Targets also differ between sites and versions
(the P6 dialog's defaults, a company procedure) and must be changeable as data.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| One generic, parameterised implementation per kind of check, with the standards as parameter sets | least code | a P6 check becomes a combination of parameters a reviewer cannot read against the Oracle page; four P6 checks have no parameter set that reproduces them (`tests/test_custom_standard_equals_p6.py`) |
| Checks hard-coded per standard with `if standard == ...` branches | quick to start | the branches interleave sources; targets are code; no company standard |
| **Standards as TOML data; one explicit function per built-in check; parameterised rules for a company standard (chosen)** | two kinds of rule to maintain (explicit and generic) and a docstring convention | the generic rules cannot express every built-in population |

## Decision

**Every standard is a TOML file** with a `[standard]` table (`id`, `name`, `description`,
`source`) and `[[metric]]` tables (`id`, `name`, `rule` required; `target`, `source`, `params`,
`unit`, `group`, `item`, `description` optional). Built-in, in
`src/xerscope/standards/`:

| File | Standard | Metrics |
|---|---|---|
| `p6.toml` | P6 Check Schedule (P6 Professional 24): 17 checks on 18 report lines, Invalid Progress Dates as P6-10a / P6-10b | 18 |
| `decm.toml` | DCMA DECM v8.0, Guideline 6 schedule tests | 16 |
| `dcma.toml` | DCMA 14-Point (legacy) | 14 |
| `integrity.toml` | recalculation of activities and assignments, and the P6 scheduling-log checks (INT-01 to INT-08) | 8 |
| `custom-template.toml` | the commented starting point of a company standard | 14 examples |

**Built-in checks are one explicit function each**, registered with `@rule(name, unit, ...)` in
`analysis/p6/check_schedule.py` (`p6_01_logic`...), `analysis/dcma/fourteen_point.py`
(`dcma_06_high_float`...), `analysis/decm/schedule_metrics.py` (`decm_06a211a_high_float`...) and
`analysis/integrity.py` (`int_01_recalculated`...). Each takes an `AnalysisContext` and returns a
`RuleOutput` (`flagged`, `numerator`, `denominator`, `value`, `note`, `checked`, `funnel`,
`counted`, `status`); its docstring states the population and quotes the source. The built-in
TOML names the function and gives the target and the source; `params` appear only where the
function reads a value: thresholds (P6's `limit_hours = 352`; DCMA's and DECM's `limit_days = 44`
and `slip_days = 600`, xerscope's choice since neither source gives a length; DECM's
`status_period_days = 28`, `riding_window_wd = 3` and `remaining_tolerance_wd = 2`) and DCMA's
`date_grain = "day"`, which departs on purpose from the rule's default (timestamp).
`tests/test_calendar_and_standards.py::test_threshold_defaults_of_the_rules_equal_the_standard_files`
requires every built-in metric to state each threshold parameter its rule takes (names ending in
`_hours`, `_days` or `_wd`; 13 in all) with the rule's default value; `date_grain` is not checked.

**A company standard picks rules as data.** `analysis/rules.py` holds the registry (`RULES`) and
the parameterised rules: `missing_logic`, `dangling`, `lag`, `relationship_type`,
`constraints`, `float`, `duration`, `invalid_dates`, `on_data_date`, `no_resource`,
`late_vs_baseline`, `bei`. Their parameters (`exclude` from the `EXCLUSIONS` keys, `links`,
`op`, `value`, `unit`, exemptions, constraint `types`...) are validated by `Rule.validate`
against the function's signature and type hints and, for the lists of names, against `ALLOWED`.
A company standard may also name a built-in function (the template uses
`dcma_12_critical_path_test`). It is loaded by `analysis/standards.py` (`load_standard`,
`loads_standard`, `parse_standard`), which rejects, with the file and metric named: a missing
`[standard]` or `[[metric]]`, an id outside `[A-Za-z0-9._-]`, a duplicate id, an unknown rule
(listing the available ones), unknown or ill-typed parameters, a unit outside `UNITS` (`%`,
`ratio`, `count`, `days`, `pass/fail`) or one that does not fit the rule (only `%` and `count` are
interchangeable), an unknown key and a target that does not parse
(`parse_target`: `< <= > >= ==` a number, `%` only on a `%` metric, `pass` or `info`). UTF-8,
UTF-16 and a BOM are read (`decode`).

**Where a standard comes from.** `builtin_standards()`, plus every `*.toml` of the folder named
by `XERSCOPE_STANDARDS` (set by `xerscope app --standards <folder>`; `discover_standards`
reports a file that fails to load and one whose id replaces another), plus the files uploaded on
the Schedule health page in the session (`app/state.py:standards`). `xerscope standards` lists the
standards, `--rules` the rules and their parameters, `--template [FILE]` writes the template.

**Running.** `analysis/checks.py`: `run_metric` turns a `RuleOutput` into a `CheckResult` with
status `pass`, `fail`, `info`, `n/a` or `error`; a rule that needs a baseline and has none is
`n/a`; a rule that raises gives `error` with the exception in `note`, never a crashed page or
command. `standard_score` counts criteria in pass over criteria evaluated (pass + fail); metrics
sharing an `item` are one criterion, failed when one of them fails (P6-10a / P6-10b).

**No branch on the standard.** CONTRIBUTING.md, "Where a change goes": a built-in check goes in
one function plus its metric in the TOML (and its sheet in `sheets/P6/` for a P6 metric); a rule
for a company standard is a parameterised `@rule`, never an `if standard == ...` branch.

## Consequences

Positive:

- Each built-in check reads like its source and is reviewed against it; the differences between
  standards are visible functions, not flags.
- Targets and the values the source fixes are data, so a site changes them without code, and a
  moved target is a moved value that needs its justification line (ADR-0008).
- A company standard is written, validated and uploaded without code; an invalid file fails on
  load with its file and metric named.
- One failing rule leaves the others and the page intact.

Negative:

- Two sets of rules to maintain. The generic rules reproduce 14 of the 18 P6 lines exactly; P6-13
  (BEI), P6-15 (out of sequence), P6-16 and P6-17 (dangling) have no parameter set that gives the
  same population (`tests/test_custom_standard_equals_p6.py`, module docstring).
- Each function's docstring, the TOML, the funnel, the calculation sheet and
  [docs/standards.md](../standards.md) must agree; tests hold them together (below).

Follow-ups: [docs/backlog.md](../backlog.md), "DECM conformance" (where the DECM sheets contradict
the current rules) and "Proof: get an oracle for what has none" (more P6 Check Schedule reports).

## Verification

- `tests/test_calendar_and_standards.py::test_builtin_standards`,
  `::test_template_is_a_valid_standard`, `::test_invalid_standard_fails_loudly`,
  `::test_duplicate_ids_rejected`, `::test_standard_files_in_utf16_and_bom_load`,
  `::test_threshold_defaults_of_the_rules_equal_the_standard_files`.
- `tests/test_custom_standard_equals_p6.py::test_the_equivalence_table_names_every_p6_check_but_four`,
  `::test_the_generic_rule_set_like_the_p6_check_gives_its_result` and the funnel equivalence
  tests of the same file.
- `tests/test_rules.py::test_broken_rule_reports_error_not_crash`,
  `::test_results_have_no_nan_status`; `tests/test_scores.py::test_info_na_and_error_are_in_neither_term`.
- `tests/test_standards_conformity.py::test_every_metric_runs_and_has_a_row_in_the_docs`,
  `::test_docstring_exclusions_are_the_funnel_steps`, `::test_docs_targets_match_the_toml`.
- `tests/test_p6_check_schedule.py` (one quoted sentence of Oracle's help per test);
  `tests/test_characterization.py` (every metric of every built-in standard against
  `tests/golden/standards.json`, ADR-0011).
- `.github/workflows/values.yml`: a moved target or parameter in a standard TOML needs its line.

## References

- `src/xerscope/standards/p6.toml`, `decm.toml`, `dcma.toml`, `integrity.toml`, `custom-template.toml`.
- `src/xerscope/analysis/rules.py`: `rule`, `Rule`, `RULES`, `RuleOutput`, `AnalysisContext`, `ALLOWED`.
- `src/xerscope/analysis/standards.py`: `Metric`, `Standard`, `parse_target`, `parse_standard`,
  `load_standard`, `loads_standard`, `builtin_standards`, `discover_standards`, `template_text`, `UNITS`.
- `src/xerscope/analysis/checks.py`: `run_metric`, `run_standard`, `CheckResult`, `standard_score`,
  `StandardScore`.
- `src/xerscope/cli.py` (`standards`, `check`, `app --standards`); `src/xerscope/app/state.py:standards`.
- [docs/architecture.md §5](../architecture.md); [docs/standards.md](../standards.md);
  [docs/formulas.md](../formulas.md) section 1.6 (score);
  [CONTRIBUTING.md](../../CONTRIBUTING.md), "Where a change goes", "Adding or changing a check".
- Related: ADR-0005 (sources settle behaviour), ADR-0008 (moved values), ADR-0010 (populations and
  explanations), ADR-0011 (golden files).
