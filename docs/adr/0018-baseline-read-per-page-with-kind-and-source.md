# ADR-0018: The baseline is read per page, and every baseline carries its kind, how it was found and its source

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-21 (`8455e45`, P17 recorded as decided; `f74f6fe`, one contract `kind` / `found_by`); implemented 2026-11-22 (`1b7568f`); each check names its baseline from 2026-11-23 (`4a4fea6`) |
| Scope | `src/xerscope/app/baselines.py` (`baseline_for`, `baseline_for_checks`, `origin_baseline`, `kind_of`, the builders of each kind), `app/state.py` (`context_banner`, `BASELINE_RULES`), `app/baseline_warnings.py` (`KIND_TEXT`), `app/baseline_window.py`, `app/xml_baselines.py`, `app/views/health.py`, `audit.py`, `gantt.py`, `earned_value.py`; `src/xerscope/analysis/baseline.py` (`Baseline`, `KIND_*`), `analysis/checks.py` (`run_metric`, `CheckResult.baseline`, `note_with_baseline`, `BASELINE_READERS`) |
| Sources | `8455e45` "docs: P17, the baseline each page reads (Problem, Options, Choice, Verification)"; `1b7568f` "refactor(front): the baseline each page reads"; `f74f6fe` "Baselines: one contract (kind, found_by), one classifier, and the user's choice for an undecided update"; `4a4fea6` "Name on each check the baseline it was measured against"; `2fcdc13` "Default baseline from the file's P6 Project Baseline, manual fallback, every result names its baseline (#83)"; [docs/refactor-front-plan.md](../refactor-front-plan.md) P17 and §6 "Baseline context — which baseline each page reads (decided)"; [docs/architecture.md §5](../architecture.md) "Baseline sources", §7; Oracle P6 help (Project Baselines, Earned Value settings); PMI Practice Standard for Earned Value Management; Lipke 2009 (Earned Schedule reliability studies) |

## Context

An update can be measured against several baselines: the Project Baseline its own file names
(`PROJECT.sum_base_proj_id`), the baseline it names read from a P6 XML export (ADR-0019), a
separate XER or P6 XML file, another loaded update, or its own planned dates (`target_*`). A
series mixes these: some files hold their baseline, some do not, some name a baseline the export
does not hold.

Until P17, one global setting (the window's choice, `baseline_for`) served every page. The
methods behind the pages define the baseline differently:

- P6 Check Schedule (P6-12 Late Activities, P6-13 BEI) and the DCMA 14-Point items are defined on
  the baseline assigned in the update's file.
- A cumulative earned value index (SPI, Earned Schedule) needs a baseline that does not move from
  one update to the next (Practice Standard for EVM; Lipke 2009: the Earned Schedule reliability
  studies exclude re-planned projects).

"Baseline in each file" applied to Earned value is faithful to P6 and wrong for the cumulative
figures; a fixed origin applied to Health and Audit is right for earned value and wrong for the P6
checks (refactor-front-plan §6). Separately, where a baseline came from was told three ways that
disagreed: the sidebar read the resolution, the context banner a prefix of `Baseline.source`, the
Debug page the file's suffix; `source` was blank in three of four modes; an undecided update
silently took the fallback (`f74f6fe` message).

## Options considered

| Option | Cost | Limit |
|---|---|---|
| One global baseline for every page (before `1b7568f`) | none | serves either the P6 checks or the cumulative earned value, never both |
| A per-page selectbox of the baseline mode (P17 option 2) | small | four settings for one rule: the user decides what the methods already decide |
| **Two resolutions beside `baseline_for`: the checks read the file's assigned baseline, Earned value the series origin, with a "P6 view" switch (P17 option 1, chosen)** | about 60 lines in `baselines.py` and `state.py`, 20 in `earned_value.py`, the banner and readings | two baselines on one update can differ; the banner must say which rule each page applies |

## Decision

**Where a baseline comes from.** The window's "Baseline (BL)" choice (`baseline_window._baseline_options`)
offers "Baseline in each file (P6 Project Baseline)" (`BL_EACH`) when a ticked file holds a usable
one or a P6 XML export is at hand, a separate baseline file (`BL_FILE`), each loaded update,
"Planned dates in each file (target_*)" (`BL_PLANNED`) and `None`. `BL_EACH` leads and is the
default when a file holds one, unless `XERSCOPE_BASELINE` names a baseline file. In `BL_EACH` mode
`_per_file_baseline` takes, update by update, the file's own baseline (`_file_baseline`), else the
one found in the export (`_resolved_baseline`), else the fallback chosen under "When a file has no
baseline" (`_fallback_baseline`; `None` by default, never chosen for the user). An undecided update
(the export's versions around it hold different baselines) takes nothing, not even the fallback,
until the user chooses one of its candidates or the fallback in the window (`bl_undecided`,
`_chosen_baseline`).

**Every baseline carries its kind, what found it and its source.** `analysis/baseline.py:Baseline`
has `kind`, `found_by` and `source`, set by every path of `app/baselines.py` that builds one:

| `kind` (`KIND_*`) | Built by | Meaning |
|---|---|---|
| `in file` (`KIND_IN_FILE`) | `_file_baseline` | the P6 Project Baseline held by the update's own file |
| `exact` (`KIND_EXACT`) | `_resolved_baseline` | the baseline the update names, read from the P6 XML export |
| `probable` (`KIND_PROBABLE`) | `_resolved_baseline`, `_loaded_update_baseline` | a copy of the same generation, or the loaded update the pointer names; `source` opens with the `PROBABLE` text |
| `chosen` (`KIND_CHOSEN`) | `_chosen_baseline` | a candidate of an undecided update, chosen in the window |
| `fallback` (`KIND_FALLBACK`) | `_fallback_baseline` | the window's "When a file has no baseline" |
| `planned` (`KIND_PLANNED`) | `_planned` | the update's own planned dates (`target_*`) |
| `series` (`KIND_SERIES`) | `_series`, `origin_baseline` | one baseline for every update: a separate file, a loaded update, or the series origin |
| `none` (`KIND_NONE`) | `kind_of(None)` | no baseline |

`baselines.kind_of(baseline)` is the one classifier (`KIND_NONE` without one). The context banner
(`state.py`), the sidebar (`baseline_warnings.py`, worded through `KIND_TEXT`) and the Debug
page's table of the baseline each update is measured against (`xml_baselines.baseline_used_table`,
which reads `Baseline.kind` and `Baseline.found_by`) all read this contract. The window's per-file
table (`xml_baselines.baseline_per_file`) shows what each update names and what it is measured
against from the resolution's `found_by` (ADR-0019), not from `Baseline.kind`.

**The baseline each page reads** (decision P17):

| Page | Function | Baseline read |
|---|---|---|
| Schedule health, Audit, Gantt & WBS | `baselines.baseline_for_checks(snapshot)` | the baseline assigned in the update's file when it holds one (`KIND_IN_FILE`), else the window's (`baseline_for`) |
| Earned value, cumulative figures (PV, EV, SPI, Earned Schedule, S-curve, `evm_series`) | `earned_value.cumulative_baselines` → `baselines.origin_baseline(store, snapshot)` | the window's baseline of the first update (`store.first`), relinked to the update shown; kind `series`, `found_by` `"origin"` (`ORIGIN`), unless the origin is `probable` or `chosen`, which keep their kind |
| Earned value with the switch "P6 view: the file's baseline" (`key="ev_p6_view"`, off by default) | `baseline_for(snapshot)` | the update's own baseline as the window gives it: P6's Planned Value of the week |
| Earned value, the four weeks' window (`weekly_gains`) | `partial(baseline_for, link=False)` | the plan in force each week, in both switch positions |
| Earned value, BEI series | `evm.bei_series` with `baseline_for_checks` | each update's assigned baseline, as Schedule health computes it |

`state.context_banner(store, snapshot, baseline, rule)` names the baseline the page reads and the
rule that picked it, from `BASELINE_RULES`: "assigned in this update" (`RULE_CHECKS`), "origin of
the series" (`RULE_ORIGIN`), "P6 view: this update's baseline" (`RULE_P6_VIEW`), or the window's
(`RULE_WINDOW`); a probable or chosen baseline keeps its warning on the page. Health, Audit and the
Gantt pick their rule with `state.checks_rule(baseline)`: `RULE_CHECKS` when the baseline is
`KIND_IN_FILE`, else `RULE_WINDOW`.

**Every result names its baseline.** `checks.run_metric` sets `CheckResult.baseline` to the
baseline's `source` (else its label), `"none"` when the metric reads one and has none, `""` when
the metric reads none (`uses_baseline`: `needs_baseline`, a rule in `BASELINE_READERS`
(`decm_06a204b_dangling_logic`, `dcma_08_high_duration`, `dcma_13_cpli`), or a `field` parameter
of `"baseline"`). `CheckResult.against` is the short form "name (Project ID) · kind"
(`measured_against`), shown in the Health results table. `CheckResult.note_with_baseline` ends the
exported notes with `baseline: <source>` (`checks.summary_frame`, `audit.sets_long`).

## Consequences

Positive:

- The P6 checks match P6 Check Schedule on each update; the cumulative earned value reads one
  stable origin. In the common case (one baseline assigned once and kept) both are the same.
- One vocabulary of kinds: the banner, the sidebar, the window, the Debug tables and the exports
  cannot disagree on where a baseline came from.
- An undecided update is never measured against a baseline nobody chose.

Negative:

- Two pages can show figures against two different baselines of the same update; the banner and
  the readings must say so, and the user must read them.
- Building a file's baseline re-reads the export and keeps raw bytes in the session
  ([docs/backlog.md](../backlog.md), "App": "Baseline in each file").
- The banner's wording and the `KIND_TEXT` labels are subject to the message rule of P18
  (refactor-front-plan).

## Verification

- `tests/test_baseline_per_page.py::test_health_audit_and_gantt_read_the_baseline_assigned_in_the_update_under_a_series_choice`,
  `::test_earned_value_reads_the_origin_then_the_update_s_own_baseline_in_the_p6_view`,
  `::test_the_switch_changes_nothing_under_a_series_choice`,
  `::test_a_probable_origin_keeps_the_warning_on_the_earned_value_page`,
  `::test_on_the_demo_the_earned_value_page_reads_the_first_update_as_origin`.
- `tests/test_file_baseline.py::test_a_baseline_held_by_the_file_is_marked_in_file`,
  `::test_the_sidebar_defaults_to_the_baseline_in_the_file_and_the_panel_names_it`,
  `::test_the_fallback_selector_defaults_to_none_and_is_shown_with_the_file_mode`,
  `::test_each_update_uses_its_file_baseline_else_the_fallback`,
  `::test_the_baseline_found_for_each_update_is_applied_and_a_probable_one_is_announced`,
  `::test_a_result_names_the_baseline_it_was_computed_on`,
  `::test_the_exports_carry_the_baseline_of_the_result`.
- `tests/test_baseline_name.py::test_a_check_that_reads_a_baseline_names_it_in_the_results_table`,
  `::test_the_debug_table_names_the_baseline_of_each_update_by_its_name_and_project_id`.
- `tests/test_app.py::test_the_context_banner_states_each_setting_and_follows_its_changes`.
- `tests/test_app_cache.py::test_metric_result_runs_again_for_another_fallback` (the fallback in the
  cache key, ADR-0017).

## References

- `src/xerscope/app/baselines.py`: `baseline_for`, `_built_baseline`, `baseline_for_checks`,
  `origin_baseline`, `ORIGIN`, `linked_baseline`, `kind_of`, `_per_file_baseline`,
  `_file_baseline`, `_resolved_baseline`, `_chosen_baseline`, `_fallback_baseline`, `_planned`,
  `_loaded_update_baseline`, `_series`.
- `src/xerscope/analysis/baseline.py`: `Baseline` (`source`, `kind`, `found_by`), `KIND_*`,
  `measured_against`.
- `src/xerscope/analysis/checks.py`: `BASELINE_READERS`, `uses_baseline`, `run_metric`,
  `_baseline_named`, `CheckResult.baseline`, `CheckResult.against`, `CheckResult.note_with_baseline`.
- `src/xerscope/app/state.py`: `context_banner`, `checks_rule`, `BASELINE_RULES`, `RULE_WINDOW`,
  `RULE_CHECKS`, `RULE_ORIGIN`, `RULE_P6_VIEW`; `src/xerscope/app/baseline_warnings.py:KIND_TEXT`;
  `src/xerscope/app/baseline_window.py:_baseline_options`;
  `src/xerscope/app/views/earned_value.py:cumulative_baselines`.
- [docs/refactor-front-plan.md](../refactor-front-plan.md) P17, §6 "Baseline context — which
  baseline each page reads (decided)"; [docs/architecture.md](../architecture.md) §5 "Baseline
  sources", §7 (`baselines.py`, `baseline_window.py`, `baseline_warnings.py`).
- Related: ADR-0017 (the baseline in the cache key), ADR-0019 (baselines from a P6 XML export).
