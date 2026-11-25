# ADR-0010: Every number traced: one named population vocabulary (Funnel) and an explanation beside each result

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-03: `Funnel` and `STEP_SOURCES` in `22e7cdf` (#59); 2026-11-04: `EXCLUSIONS` in `ff5e888` (#68); the generic rules were brought to return their funnel on 2026-11-18 in `1c3095c` (#290, float), `1f740a0` (#291, constraints and no_resource), `140dfe1` (#294, link rules), `b51bc8d` (#299, missing_logic and dangling) and `292724f` (#301, invalid_dates, late_vs_baseline and bei) |
| Scope | `src/xerscope/analysis/populations.py`, `analysis/explain.py`, `analysis/audit.py`, `analysis/ask/funnel.py`; `src/xerscope/app/sets.py`, `app/explanation_panel.py`, `app/ui.py`; `src/xerscope/sheets/P6/*.md` |
| Sources | [CONTRIBUTING.md](../../CONTRIBUTING.md), opening paragraph and Rule 5 ("Read what exists before writing"); [docs/architecture.md §5](../architecture.md) (`populations.py`, `explain.py`, `audit.py`); the texts named by `STEP_SOURCES` (Oracle help 101248, 46278, 46282; PAM 200.1; DECM 8.0; AACE RP 29R-03...) |

## Context

xerscope is worth using only if each of its numbers can be traced to a formula, a population and a
source (CONTRIBUTING.md, opening paragraph). The same exclusions (completed tasks, level of effort,
milestones, tasks completed before the status date...) recur across the P6, DCMA, DECM and
Integrity checks and the rules of a company standard. Written by hand in each check, they drift
apart in wording and in effect, and a user cannot see which rows a check left out or why a count
differs from P6's report. The same need arises on the Gantt page, where the Ask field turns a
sentence into filters (ADR-0020): the user must see what each understood filter removed.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Each check filters its rows with its own pandas expression and returns only its counts | least code | no record of what was removed; exclusions worded and coded differently from one check to the next; the Audit page would have to recompute |
| A log of filters written as free text by each check | small | text cannot be tested against the code, and still invites a second copy of each filter |
| **One vocabulary of named, sourced exclusions and a `Funnel` that records each step; a separate explanation layer that only reads results (chosen)** | every rule builds its population through the funnel and declares its steps | a rule that does not fit an activity funnel (pass/fail, ratio, assignment checks) has none |

## Decision

**One vocabulary.** `analysis/populations.py` holds `EXCLUSIONS`, the single list of named ways to
leave tasks out of a population, each an `Exclusion(label, text, removes)`: `complete` ("not
complete"), `complete_before_data_date`, `started`, `loe`, `milestones`, `no_duration`. The keys are
the values a company standard writes in `params.exclude` (`ALLOWED["exclude"]` in `rules.py`); the
`text` is the wording of a rule's "Excludes:" docstring line.

**A population is built one named, sourced step at a time.** `Funnel(rows, data_date)` starts
from the file's tasks (`activity_funnel(snapshot)`: WBS summaries are never tasks) and records a
`Step(label, source, removed, left)` per call to `Funnel.keep(label, source, predicate)` or
`Funnel.exclude(key, source)`. `source` must be a key of `STEP_SOURCES` (the text the step follows:
`101248`, `46278`, `46282`, `Ten Six`, `R1`, `model`, `PAM 200.1`, `DECM 8.0`, `AACE 29R-03`,
`xerscope`, `ask`); another value raises `ValueError`. The checks of every built-in standard and
the generic rules of `rules.py` return their funnel in `RuleOutput.funnel` (with the population in
`checked`); the Gantt page's Ask filter is applied as a funnel with source `ask`
(`analysis/ask/funnel.py:apply`). The other building blocks of the module (`has_predecessor_in_project`,
`constrained_by`, `links_between`, `flagged_activities`, `flagged_relationships`...) are the
shared answers to recurring questions; CONTRIBUTING.md Rule 5 makes a hand-written filter where
a named step exists a defect of the change, even when its numbers are right.

**Showing the steps.** `app/sets.py:show_funnel` prints "Population, step by step" under the
audited check on the Audit page (`analysis/audit.py:funnel_table`, each step with the text it
follows); `app/sets.py:show_steps` shows a funnel's steps for the Gantt page's Ask filter (in an
expander of the same name) and for the longest path on the Delay analysis page.
`app/sets.py:show_sets` gives the Counted / Checked, not counted / Excluded tabs on the Schedule
health and Audit pages: `analysis/audit.py:split` cuts those three sets (`SET_NAMES`) from what
the rule returned (`CheckResult.checked`, `counted`, `flagged`) and recomputes nothing; `sets_long` gives every check's sets in one table, `with_settings` and
`toml_block` re-run a metric with audited settings and print its `[[metric]]` table.

**An explanation beside each result.** `analysis/explain.py:explain(result)` turns a
`CheckResult` into an `Explanation`: what is measured, the formula with the actual numbers, the
verdict, the method (the rule's docstring), the population lines (the docstring's, then the
sentences written from the parameters), the effective parameters marked `standard` or `default`, the
flagged-list label and the baseline used. `app/explanation_panel.py` shows it on the Health and
Audit pages with the metric's `source`. `KPI_FORMULAS` holds the formula and source of each
figure shown with `ui.kpis`; `READINGS` holds the "How to read" text of each chart and table
(`ui.chart`, `ui.table` take a `reading` key), and under `XERSCOPE_STRICT_READINGS=1` (set by
`tests/conftest.py`) a figure without a reading raises.

**Calculation sheets.** Each P6 metric has a hand-written sheet, `src/xerscope/sheets/P6/<id>.md`
(18 sheets: population steps, counted items, value, target, sources), read by
`analysis/audit.py:sheet`; `tests/test_sheets.py` keeps it consistent with the TOML, the model,
the rule's funnel and the test names.

## Consequences

Positive:

- Every count can be followed from the file's tasks to the denominator, step by step, each step
  with its source, and the excluded rows can be downloaded.
- An exclusion has one implementation and one wording everywhere; the docstring, the funnel, the
  sheet and [docs/standards.md](../standards.md) are tested against each other.
- The explanation and the Audit sets read the result; they cannot disagree with the number shown.

Negative:

- Every new rule must build its population through `Funnel` and keep its docstring's "Excludes:"
  line equal to its steps.
- Some checks have no activity funnel: DCMA-12 (pass/fail), DCMA-13 (ratio) and INT-03
  (assignments) (`NO_POPULATION` in `tests/test_standards_conformity.py`). In `tests/test_sheets.py`,
  `NO_FUNNEL` holds only `int_03_assignments_recalculated`; DCMA-12 and DCMA-13 pass there because
  their denominator is `None`.
- Only the P6 standard has calculation sheets (`WITH_SHEETS = ["P6"]` in `tests/test_sheets.py`).

## Verification

- `tests/test_sheets.py::test_one_sheet_per_metric_and_no_other`,
  `::test_sheet_matches_the_standard_and_the_code`,
  `::test_the_rule_the_sheet_and_the_standard_name_the_same_steps`,
  `::test_the_rule_docstring_excludes_what_its_steps_remove`,
  `::test_funnel_ends_on_the_denominator_and_removes_the_excluded` (start minus every step's
  removals equals the denominator, for every metric of the four built-in standards).
- `tests/test_standards_conformity.py::test_docstring_exclusions_are_the_funnel_steps`.
- `tests/test_custom_standard_equals_p6.py`: the generic rules show the same funnel as the P6
  checks they reproduce (`::test_the_generic_float_rule_shows_the_same_funnel_as_p6_large_and_negative_float`,
  `::test_the_generic_link_rules_show_the_same_funnel_as_p6_lags_and_relationship_types`...).
- `tests/test_rules_funnel_logic.py`, `tests/test_rules_funnel_dates_baseline.py`: the funnels of
  the generic rules.
- `tests/test_explain.py::test_formula_restates_the_numbers`, `::test_verdict_follows_status`,
  `::test_parameters_show_standard_and_defaults`, `::test_explain_tables_match_registry`,
  `::test_every_exemption_has_a_mask`.
- `tests/test_readings.py::test_every_builder_gives_its_figure_a_reading_key`,
  `::test_every_table_of_the_app_passes_a_reading`,
  `::test_a_figure_without_a_reading_key_raises_when_readings_are_strict`.
- `tests/test_audit.py` (the sets behind a count).

## References

- `src/xerscope/analysis/populations.py`: `EXCLUSIONS`, `Exclusion`, `STEP_SOURCES`, `Step`,
  `Funnel.keep`, `Funnel.exclude`, `activity_funnel`, `without`.
- `src/xerscope/analysis/rules.py`: `RuleOutput.funnel`, `RuleOutput.checked`, `ALLOWED`.
- `src/xerscope/analysis/explain.py`: `explain`, `Explanation`, `KPI_FORMULAS`, `READINGS`.
- `src/xerscope/analysis/audit.py`: `split`, `sets_long`, `funnel_table`, `with_settings`,
  `toml_block`, `sheet`.
- `src/xerscope/analysis/ask/funnel.py:apply`.
- `src/xerscope/app/sets.py:show_funnel`; `src/xerscope/app/explanation_panel.py:show_calculation`,
  `metric_panel`; `src/xerscope/app/ui.py` (`STRICT_READINGS`).
- `src/xerscope/sheets/P6/`.
- [CONTRIBUTING.md](../../CONTRIBUTING.md), opening paragraph and Rule 5;
  [docs/architecture.md §5](../architecture.md).
- Related: ADR-0009 (standards and rules), ADR-0020 (Ask field).
