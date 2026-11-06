> Note : analyse faite sur un worktree partant de `main` avant l'audit (commit `af57a08` : sans `xer/validate.py`, sans le parser en flux, sans la validation TOML ni les tests d'audit). Les scores de mutation de `calendar.py` et `standards.py` sont donc à reprendre ; ceux de `rules.py`, `populations.py` et `evm.py` restent représentatifs. Le crosscheck MPXJ, noté « skippé » ici, a depuis été exécuté (31 + 196 tests verts).

# Rigour review of `tests/` (xerscope, branch claude/wizardly-ptolemy-b4zjg4)

Scope: the 46 `tests/test_*.py` files (~1,600 collected tests), read against ISO/IEC/IEEE 29119-4
techniques (equivalence partitioning, boundary-value analysis, decision tables, error guessing) and
the usual test smells (tautology, assertion-free / type-only, smoke, characterization without an
oracle). Reference points: CONTRIBUTING.md rules 2-3 ("P6 semantics come from Oracle", "a number
changes only with evidence"), `tests/xerkit.py`, `tests/rulekit.py`, `tests/conftest.py`.

Overall verdict first: this suite is far above the usual bar. Nearly every rule test states its
source sentence, every expected count is written by hand on a schedule small enough to recount, the
P6 Check Schedule has a P6 26.8 witness (`test_p6_checksched.py`), the CPM has P6 23.12's held-out
corpus and MPXJ, and the golden file freezes every metric. The smells below are therefore mostly
*gaps at the edges*: target boundaries of the standards never exercised, equivalence classes
(resource-dependent tasks, LOE in progress, zero-duration tasks) missing from the rule fixtures,
a handful of `> 0` / `in codes(...)` assertions where an exact list is countable, and a few
numbers pinned from the demo series without a stated hand count.

## 1. Smell table

Legend: T = tautology, A = assertion-free / type-only, S = smoke, B = boundary gap, E = equivalence
class gap, C = characterization without an independent source. "Source" names the oracle the
proposed assertion rests on.

| file::test | smell | why | proposed stricter assertion (and source) |
|---|---|---|---|
| test_weekly.py::test_bei_series_one_row_per_update_p6_and_dcma | T | `expected_p6` is computed in the test with the very formula the code uses (`is_complete.sum() / len(counted)` after dropping milestones and LOE); if `bei_series` and the rule share a wrong population the test still passes | type the eight ratios by hand from `sample.py` (which activities are complete in each week) and cite the `demo-planned` P6-13 entries of `tests/golden/standards.json` as the cross-check: `assert out["bei_p6"].tolist() == pytest.approx([0, 1/26, ...])` |
| test_weekly.py::test_health_wide_has_one_row_per_check_and_one_column_per_update | C | `[10.344828, 0, 7.142857, 4.166667]`, `shape == (18, 10)` are page output frozen in place; only the first (3/29, K5040, M9999, M1000) is counted by hand | write each as a fraction with its hand count: `pytest.approx([3/29, 0, 2/28, 1/24])` and name the two soft-constrained (P2040, X4050) and the one large duration (P2030) activities from `sample.py`; otherwise move the frozen numbers to the golden file where they belong |
| test_weekly.py::test_category_totals_sums_counts_and_lists_kinds | C | `[9, 50, 1]` pinned from the demo with no derivation | derive: Progress 9 = N started + M finished + K % changes between weeks 1 and 2 of the generator (count them in `sample.py`), Dates 50 = starts/finishes moved; write the count in the comment or keep only the structural assertions (`kinds` text, dtype) and let the golden/characterization file hold the numbers |
| test_weekly.py::test_weekly_change_matrix_counts_per_category_kind_and_week | C | `matrix.shape == (13, 9)`, `sum() == 365`, `[0,0,0,1,0,0,0]` | same as above: name the one activity the generator adds in week 5 (`sample.py`) in the comment; the 365 total needs a stated count or belongs in the golden file |
| test_weekly.py::test_forecast_finish_shift_since_first_update_in_working_days | C | `== 15.0` with no derivation | state the two finishes (first and last update's project finish from the generator) and the calendar: `# 2026-xx-xx -> 2026-yy-yy = 15 wd on the project's Mon-Fri calendar` |
| test_analysis_and_viz.py::test_negative_float_appears_after_vendor_delay | A/E | `after.numerator > 0` where the exact set is countable: the vendor delay is `P2030.remaining += 10` in `sample.py` and negative float reaches its successors on the longest path | `assert codes(after) == [...]` listing P2030 and its FS successors through the finish milestone (take the list from the `demo` DCMA-07 golden entry and check each against the generator's chain), and `after.numerator == len(...)` |
| test_analysis_and_viz.py::test_planted_lead_open_end_and_missing_resources | A | `"K5040" in codes(DCMA-01)` tolerates any extra open end | `assert codes(run_on_store(store, 0, "DCMA-01")) == ["K5040"]` (sample.py: only K5040 has no successor; the project start milestone is excluded as a milestone by PAM 4.0) |
| test_analysis_and_viz.py::test_planted_high_duration | A | `"P2030" in codes(DCMA-08)` | exact list: `== ["P2030"]` (sample.py plants one 60-day activity) |
| test_analysis_and_viz.py::test_baseline_execution | A | `0 < late.value < 1` | exact fraction from the generator's slow activities: `(late.numerator, late.denominator) == (n, d)`; the `bei_dcma` list in test_weekly already gives 5/8 for the planned baseline, so the first-as-baseline figure is countable the same way |
| test_analysis_and_viz.py::test_health_history_is_long_format | A | `neg[5] > 0` | `neg[5] == <count>` (same hand count as above) |
| test_app.py::test_every_page_renders | S | asserts only `not at.exception` and a non-empty title for 12 pages | for each page assert one computed value that the page must show: Overview score card text == `standard_score(run_standard(P6, ...)).value`; Health table has 18 rows for P6 (`len(std["P6"].metrics)`); Gantt `_gantt_data` task rows == `len(store.latest.activities)`; EV page `st.metric` SPI equals `ev_point(...).spi` formatted |
| test_app.py::test_one_snapshot_renders_every_page | S | docstring promises "with one they say so" but only `_ok(at)` is asserted | `assert any("two updates" in i.value for i in at.info)` (or the app's exact wording) on the PPC, trend and earned-value pages |
| test_explain.py::test_formula_restates_the_numbers | B | the formula is only checked when `r.denominator` is truthy: a zero denominator (n/a with 0 checked) is never worded-checked | add a hand case: `snap([done("A")])` for P6-04 gives denominator 0; assert `explain(r).formula` says `0 ... checked` and the verdict is "Not applicable" |
| test_rules.py / test_p6_check_schedule.py (targets) | B | of the 18 P6 + 14 DCMA + 16 DECM targets only two are tested *at* the boundary (P6-08 at 5 %, P6-07 at 90 %); `< 1 %`, `<= 0 %`, `> 0.95`, `>= 0.95`, `< 2 %`, `<= 10 %`, `<= 1 %` never are | see §3 cases 1-6 (one hand schedule per boundary, strict vs inclusive pairs P6/DCMA) |
| test_rules.py::test_float_threshold_in_hours_vs_working_days | B | float boundary tested at 352 (not flagged) and 353 (flagged) for P6-06 but the *negative* boundary is tested only at -8: float exactly 0 is in no test | add `todo("Z", total_float_hr_cnt="0")`: flagged by none of P6-14 / DCMA-07 / P6-06 / DCMA-06 (101248 "less than 0"; PAM 4.7 "less than 0 working days") |
| test_rules.py::test_lead_long_lag_and_fs_share | B | P6-05 long lag tested at 400 h (flagged) and 352 h (not); the first flagged value 353 h is untested, and lag exactly 0 vs 1 h for P6-08 is tested only through the chain fixture (8 h) | add links with lag 353 (flagged) and lag 1 h (P6-08 flagged, "lag" = any positive lag, 101248) and lag 0 (not) |
| test_rules.py (all rule fixtures) | E | no rule test contains a `TT_Rsrc` (resource-dependent) activity; it is a task to every check (101248 excludes only WBS summary, LOE, milestones) but the model could mis-classify it (`is_milestone` / `is_loe` derived from `task_type`) | add `todo("RD", task_type="TT_Rsrc", remain_drtn_hr_cnt="400")` to the P6-04 / P6-06 / P6-11 / P6-01 fixtures: counted in the denominator and flagged like a `TT_Task` |
| test_rules.py::test_missed_tasks_and_late_activities, test_p6_check_schedule.py::test_p6_12_milestone_loe_wbs_and_completed_are_excluded | E | the LOE equivalence class is covered only *not started* (`todo("LOE", ...)`); an LOE in progress and an LOE complete after its baseline finish are not in any P6-12 / DCMA-11 / P6-13 fixture (status x type matrix incomplete) | add `active("LOE2", task_type="TT_LOE", early_end_date=late)` and `done("LOE3", task_type="TT_LOE", act_end_date=late)` with baseline finishes before the data date: none flagged, none counted (101248; PAM 4.0) |
| test_rules.py::test_dcma_14_leaves_out_zero_duration_tasks_and_says_so vs test_dcma_01_follows_pam_200_1 | E | PAM 200.1 §3.1.2.4 reads "zero duration tasks (milestones)" and DCMA-10 / DCMA-14 exclude `no_duration` (fourteen_point.py lines 296, 464ff); DCMA-01..09 exclude `milestones` by *type* only. A `TT_Task` with 0 h original duration is therefore a milestone for DCMA-10/14 and a task for DCMA-01/03/05/06: no test pins this difference | add `todo("ZERO", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0")` to the LOGIC fixture: assert DCMA-01 denominator includes it (current behaviour) and record in the test (or `UNRESOLVED`) that PAM 4.0 "milestones" may mean the same zero-duration reading; the test makes the choice visible |
| test_rules.py::test_invalid_progress_dates | B | P6-10a tests an in-progress remaining start before the data date (RUN, LATE) and a not-started start *on* it (test_p6_check_schedule ON); an in-progress activity whose remaining start is exactly the data date (the normal P6 case for every started activity after F9) is not in the fixture | add `active("ONDD", restart_date=DD, reend_date="2026-03-06 17:00")`: not flagged, in the denominator (101248 "earlier than the data date") |
| test_p6_check_schedule.py::test_start_constraints_on_started_activities_are_not_included | E | the started exemption is tested on `active`; a *completed* activity with a start constraint is out by the completed exclusion, but a started activity with a **secondary** start constraint (`cstr_type2`) is untested | `active("A", cstr_type2="CS_MSO", cstr_date2=...)`: P6-02 numerator 0 (the sentence applies to "start constraints", primary or secondary) |
| test_rules.py::test_constraint_sets_differ_between_p6_and_dcma | E | P6-02 / P6-03 on a milestone: P6-03 flags a constrained finish milestone (test_planted_constraints X4050) but P6-02 with `CS_MANDFIN` on a milestone is untested | add `todo("MM", **FM, cstr_type="CS_MANDFIN", cstr_date=...)`: in P6-02's numerator and denominator (101248 names no milestone exclusion for constraints) |
| test_calendar_and_standards.py::test_working_exception_and_midnight_end | B | a *working* exception with its own hours (4 h Monday) is checked with `periods()` only; `work_hours`, `TimeAxis.add/between` across that day are not, so an engine that reads exceptions as non-working days would pass `work_hours` tests (all exception tests use a non-working holiday) | `assert cal.work_hours(T("2026-04-06 08:00"), T("2026-04-07 08:00")) == 4` and `TimeAxis(cal, ...).add(T("2026-04-06 08:00"), 4*60, finish=True) == T("2026-04-06 12:00")` (P6 calendar exceptions: Oracle "Calendars" help, an exception replaces the day's hours) |
| test_calendar_and_standards.py::test_work_hours_are_exact_within_days | B | the holiday boundary is tested Thu 17:00 -> Mon 08:00 (0 h) but not an instant *inside* the holiday (`work_hours(Fri 03 Apr 10:00, Mon 08:00)`) nor `add()` landing on the holiday morning | `cal.work_hours(T("2026-04-03 10:00"), T("2026-04-06 08:00")) == 0`; `ax.add(T("2026-04-02 17:00"), 60, finish=True) == T("2026-04-06 09:00")` |
| test_shift_calendar.py::test_44_working_days_is_not_greater_than_44_on_an_8_2_hour_calendar | B (good) | the float-point boundary is covered for days; the same `round(value, 6)` guard in `Metric.status` (standards.py) has no test | `Metric(..., comparator="<=", threshold=5).status(5.0000000001) == "pass"` and `.status(5.000001) == "fail"` (the guard is xerscope's own: say so in the docstring) |
| test_spi_cost.py::test_planned_value_cost_before_the_baseline_start_is_zero | A | asserts only `spi_cost is None` | add `(point.pv_cost, point.ev_cost, point.bac_cost) == (0, 0, 16500)` (BAC is the sum of the assignment and expense costs, 16500 by hand in `_costed`) |
| test_weekly.py::test_pv_spreads_over_working_days | B | PV at the data date on the *end* boundary (Fri 13 Mar 17:00 -> 80 h, and 18:00 -> still 80) is untested; only interior instants are | `_pv_at(bl, "2026-03-13 17:00") == 80` and `_pv_at(bl, "2026-03-14 08:00") == 80`; `_pv_at(bl, "2026-03-02 08:00") == 0` (Oracle: Schedule % Complete 0 before the planned start, 100 after the planned finish) |
| test_weekly.py::test_ev_spi_and_unbaselined | E | EV is tested for an `active` activity (25 %); a *complete* activity's EV (= BAC) and a *not started* one (0) with hours are only indirectly covered through the W1/W2 series | one fixture with the three statuses on one baseline: `earned(...)["ev_hr"].tolist() == [0, 20, 80]` |
| test_weekly.py::test_per_activity_pv_sums_to_the_headline_pv, test_progress_delta_with_a_baseline_adds_up_to_ev, test_bl_cost_is_read_on_the_baseline_snapshot | T (mild) | consistency between two code paths, not a value: both sides come from the code | keep, but each already sits next to a hand-valued test; add the hand value to the consistency assert (`== pytest.approx(80/3)`), which the first one can |
| test_cpm.py::test_longest_path_matches_p6s_flag | A (mild) | `open_["on_longest_path"].sum() > 0` guards against an empty comparison | `== LONGEST[name]` with the count typed from each P6 file (a P6 export is the source) |
| test_characterization.py / test_audit.py | C (by design) | golden numbers are code output; acceptable because documented, but the golden file holds no `note` text, so a rule that silently changes its wording or its `checked` set keeps the same counts | add the `len(checked)` and the `funnel` step labels to `entry_of()` so a population change shows in the diff |
| test_p6_heldout.py::FLOORS | B (ratchet) | floors lag the measured values (see §4); a regression of up to 1 pp on H10 and up to 0.9 pp on several sets passes today | raise the floors to the measured values at 3 decimals (table in §4) |
| test_crosscheck_mpxj.py (5 tests), test_reference.py (2 tests) | skipped | `jpype`/`mpxj` not installed in this environment although Java is present: 7 tests skip, so the only *independent engine* for random networks, hand cases, the demo and real-file calendars never runs in CI by default | see §5 |
| test_p6_witness.py | skipped | no witness folder: the only check of the P6 Check Schedule against P6 Professional *on a real schedule* is off by default | see §5 |

## 2. Equivalence-class matrix of the rule fixtures (status x type x baseline)

Collected from the fixtures of test_rules.py and test_p6_check_schedule.py (x = present in at
least one rule test, - = absent):

| | task not started | task in progress | task complete | LOE not started | LOE in progress | LOE complete | start ms | finish ms | WBS summary | TT_Rsrc |
|---|---|---|---|---|---|---|---|---|---|---|
| no baseline | x | x | x | x | x (INT-06 only) | - | x | x | x | - |
| with baseline (P6-12/13, DCMA-08/11/14, 06A204b/501a) | x | x | x | x | - | - | x (06A204b) | x | x | - |

Gaps: LOE in progress / complete under every baseline check; `TT_Rsrc` everywhere; a complete
`TT_WBS` (P6 exports WBS summaries with status) in none; a start milestone with a baseline finish for
P6-13 (only a finish milestone is tested). Each is one row to add to an existing fixture; expected
counts follow the source sentences already quoted in the tests.

## 3. Boundary cases to add (target comparators)

`Metric.status` compares `round(value, 6)` with the threshold using `<`, `<=`, `>`, `>=`. Only
P6-08 (5 %) and P6-07 (90 %) are tested at the boundary. Hand schedules for the others, each under
10 activities:

1. **P6-02 `< 1 %` vs DCMA-05 `<= 5 %`**: 100 not-started tasks, one with `CS_MANDFIN` -> P6-02
   (1, 100) `fail`; 20 tasks one with `CS_MSO` -> DCMA-05 (1, 20) `pass`. Source: 101248 "less than
   1 percent"; PAM 200.1 4.5 "5 % or less".
2. **P6-06 `< 1 %` / DCMA-06 `<= 5 %`**: 20 tasks, one with float 353 h -> DCMA-06 `pass` at exactly
   5 %; P6-06 on 100 tasks `fail` at exactly 1 %.
3. **P6-13 `> 0.95` vs DCMA-14 `>= 0.95`**: baseline of 20 tasks finishing before the data date,
   19 done: P6-13 value 0.95 `fail`, DCMA-14 value 0.95 `pass`. Source: EPPM 91574 "greater than
   0.95"; PAM 200.1 §3.1.2.4 "BEI ... 0.95 or greater".
4. **DCMA-13 `>= 0.95`**: CPL 20 wd, total float -1 wd (-8 h) -> 19/20 = 0.95 `pass`; -9 h ->
   `fail`. Source: PAM 200.1 §3.1.2.3.
5. **P6-15 `< 2 %`**: 50 open activities, one out of sequence -> `fail`; **06A205a `<= 10 %`**:
   10 links one lagged -> `pass`; **06A506c `<= 1 %`**: 100 open, one riding -> `pass`.
6. **`<= 0 %` / `<= 0` counts** (P6-16/17, DCMA-02/07/09, 06A204b...): one flagged of 1,000 is
   still `fail` (no rounding to 0 %): `round(0.1, 6)` keeps it; assert `status == "fail"` with
   value 0.1.
7. **Rounding guard**: `Metric.status(5.0000000001)` under `<= 5%` is `pass`; `4.9999999999` under
   `< 5%` is `fail` (rounds to 5.0). Document the guard's purpose in the test.

Other boundaries: float exactly 0 (none of P6-14 / DCMA-07 / 06A211a); remaining duration exactly
0 on a `TT_Task` not started (P6-04 denominator yes, numerator no; DCMA-14 population no);
remaining start exactly on the data date for an in-progress activity (P6-10a not flagged); actual
finish exactly on the data date (covered: ON); baseline finish exactly on the data date (covered:
SAME); a holiday on the first or last day of a PV spread (covered: Good Friday at the end;
**not** covered at the start: baseline starting on 2026-04-03 must spread nothing that day).

## 4. Floors (tests/test_p6_heldout.py) - current vs measured today

Measured with `tests/reference/data/p6-heldout` on this checkout (script
a 10-line script over `verify/p6_corpus.py`); all sets 0 errors.

| set | floor | measured | raisable to (3 dp, floor) | set | floor | measured | raisable to |
|---|---|---|---|---|---|---|---|
| H1 | 1.00 | 1.0000 | - | H16 | 0.89 | 0.8991 | 0.899 |
| H2 | 0.99 | 0.9981 | 0.998 | H17 | 0.95 | 0.9528 | 0.952 |
| H3 | 0.99 | 0.9967 | 0.996 | H18 | 0.97 | 0.9793 | 0.979 |
| H4 | 1.00 | 1.0000 | - | H19 | 0.98 | 0.9821 | 0.982 |
| H5 | 0.99 | 0.9967 | 0.996 | H20 | 0.94 | 0.9444 | 0.944 |
| H6 | 0.99 | 0.9987 | 0.998 | H21 | 0.99 | 0.9969 | 0.996 |
| H7 | 1.00 | 1.0000 | - | H22 | 0.99 | 0.9942 | 0.994 |
| H8 | 0.99 | 0.9962 | 0.996 | H23 | 0.76 | 0.7654 | 0.765 |
| H9 | 0.99 | 0.9989 | 0.998 | H24 | 0.72 | 0.7211 | 0.721 |
| H10 | 0.96 | 0.9705 | **0.97** (2 dp) | H25 | 0.74 | 0.7455 | 0.745 |
| H11 | 0.99 | 0.9938 | 0.993 | H26 | 0.78 | 0.7857 | 0.785 |
| H12 | 0.98 | 0.9881 | 0.988 | H27 | 0.76 | 0.7650 | 0.765 |
| H13 | 0.99 | 0.9907 | 0.990 | H28 | 0.74 | 0.7452 | 0.745 |
| H14 | 0.95 | 0.9550 | 0.955 | H29 | 0.76 | 0.7683 | 0.768 |
| H15 | 0.99 | 0.9957 | 0.995 | H30 | 0.85 | 0.8520 | 0.852 |

At the current 2-decimal convention only **H10 (0.96 -> 0.97)** can be raised. At 3 decimals, 26
of 30 floors can be raised; the slack today is up to 1.05 pp (H10), 0.93 pp (H18), 0.91 pp (H16).
Each set has 1,000-4,000 compared values, so 0.5 pp is 6-20 values: a regression of that size
passes the ratchet today, which is why `PINNED` exists. Recommendation: floors at 3 decimals equal
to `floor(measured * 1000) / 1000`, and add the measured value as a comment so the slack is visible.

No other numeric floor exists in the suite: `test_total_float_agrees_wherever_the_four_dates_do`
requires `len(w) > 2000` (loose count guard), `test_float_type_codes_read_as_p6_does` requires
`FT_Min >= 0.96` (measure and pin), `test_gantt_rows_scale_to_a_large_schedule` `< 2 s`.

## 5. Skipped-by-default evidence

| evidence | condition | skips here | what stays unprotected without it |
|---|---|---|---|
| MPXJ cross-check (`test_crosscheck_mpxj.py`, 5 tests; `test_reference.py` 2 tests) | `jpype` + `mpxj` installed (`--extra crosscheck`), Java on PATH, `mpxj-cpm-*.jar` built | yes: Java 21 present, `jpype`/`mpxj` **not installed** in the locked default group | the only independent scheduler on random networks of every link type, on the hand cases, on the demo; and the only check that every calendar of every real export is read as another reader reads it. Without it, calendar parsing of real files rests on xerscope's own stored-date reproduction (`test_cpm.py`), which cannot see a wrong exception day that P6's stored dates happen not to cross |
| P6 witness (`test_p6_witness.py`) | a local `tests/reference/data/witness/*/expected.csv` | yes (no folder) | the P6 Check Schedule counts on a real P6 Professional 24 report; today the counts are witnessed only on the 14-activity synthetic project of `test_p6_checksched.py` (P6 26.8) and the help text |
| held-out corpus (`test_p6_heldout.py`) | `fetch_p6_heldout.py` run | no (present) | - |
| reference XERs (`test_cpm.py`, `test_reference.py`, `test_characterization.py` reference section, `test_audit.py`) | `fetch.py` run | no (present) | - |

`XERSCOPE_REQUIRE=mpxj,witness,reference,p6-corpus` turns every skip into a failure; CI should set
at least `reference,p6-corpus` and a scheduled job `mpxj`.

## 6. Top 20 stricter tests, in priority order (exact assertion + independent source)

1. `test_p6_check_schedule.py`: **BEI boundary** - baseline 20 tasks due, 19 complete:
   `run(P6,"P6-13",...).status == "fail"` and `run(DCMA,"DCMA-14",...).status == "pass"`, both
   `value == pytest.approx(0.95)`. Source: EPPM 91574 "greater than 0.95"; PAM §3.1.2.4.
2. **Hard-constraint boundary** - 100 tasks, one `CS_MANDFIN`: `P6-02 (1,100) fail`; 20 tasks one
   `CS_MSO`: `DCMA-05 (1,20) pass`. Source: 101248 "less than 1 percent"; PAM 4.5.
3. **CPLI boundary** - CPL 20 wd, float -8 h: `DCMA-13 value == 0.95, status == "pass"`; -9 h:
   `"fail"`. Source: PAM §3.1.2.3.
4. **Float exactly 0** - `todo("Z", total_float_hr_cnt="0")` flagged by none of P6-14, DCMA-07,
   P6-06, DCMA-06, 06A211a; denominator counts it. Source: 101248 "less than 0"; PAM 4.6/4.7.
5. **`TT_Rsrc` is a task** - in the P6-04 / P6-06 / P6-11 / P6-01 fixtures: counted and flagged as
   a `TT_Task`. Source: 101248 exclusion lists name only WBS summary, LOE, milestones.
6. **LOE in progress and complete under the baseline checks** - P6-12, DCMA-11, P6-13, DCMA-14:
   never flagged, never counted. Source: 101248 "Level of Effort activities are not included";
   PAM 4.0.
7. **Zero-duration `TT_Task`** across DCMA-01/03/05/06 and DCMA-14: pin that DCMA-14 drops it
   (`no_duration`) while the others keep it, with the PAM sentences side by side; if the authors
   decide otherwise, this is the failing test that drives the change.
8. **In-progress remaining start on the data date** - `active("ONDD", restart_date=DD, ...)`: P6-10a
   not flagged, in the denominator. Source: 101248 "earlier than the data date".
9. **Secondary start constraint on a started activity** - P6-02/P6-03 numerator 0; DCMA-05 counts
   it. Source: 101248 "start constraints applied to started activities are not included".
10. **Working exception day in `work_hours` / `TimeAxis.add`** - 4-h Monday exception:
    `work_hours(Mon 08:00, Tue 08:00) == 4`; `add(Mon 08:00, 240 min, finish=True) == Mon 12:00`.
    Source: Oracle P6 "Calendars" help (exceptions replace the day's hours); the P6 23.12 corpus
    files carry such exceptions.
11. **`Metric.status` rounding guard** - `5.0000000001` under `<= 5%` passes, `4.9999999999` under
    `< 5%` fails. Source: xerscope's own `round(value, 6)`; say so.
12. **Lag 353 h and lag 1 h** - P6-05 flags 353 h (first flagged value), P6-08 flags 1 h, not 0.
    Source: 101248 "greater than" x; Lags option "relationships with lag".
13. `test_weekly.py::test_bei_series_...` - replace the formula-computed `expected_p6` with the
    eight hand-typed fractions (sample.py) cross-checked against the golden `demo-planned` P6-13
    entries.
14. `test_analysis_and_viz.py::test_negative_float_appears_after_vendor_delay` - exact
    `codes(after)` from the generator's chain downstream of P2030.
15. `test_analysis_and_viz.py::test_planted_*` - `== ["K5040"]`, `== ["P2030"]`, exact DCMA-14
    fraction.
16. `test_app.py::test_every_page_renders` - one computed value per page (Overview score text ==
    `standard_score(...)`.value; Health 18 rows; Gantt task rows == activities; EV SPI text).
17. `test_app.py::test_one_snapshot_renders_every_page` - assert the "needs two updates" message on
    the three series pages.
18. `test_weekly.py::test_pv_spreads_over_working_days` - PV at the planned finish instant (80), one
    minute after (80), at the planned start (0). Source: Oracle Schedule % Complete definition.
19. `test_weekly.py` - **PV with a holiday on the first day** of the baseline span (2026-04-03 start):
    `pv_hr` 0 that day, 80 h over the remaining 4 working days. Source: calendar exception.
20. `test_p6_heldout.py::FLOORS` - raise H10 to 0.97 now; move to 3-decimal floors per §4 and
    pin `FT_Min` share from `test_float_type_codes_read_as_p6_does` at its measured value.

## 7. What the review could not do

- `tests/test_audit_edges_xer.py` and `tests/test_audit_edges_app.py` named in the brief do not
  exist on this branch; `tests/test_audit.py` was used for the calendar / rules / standards
  mutation runs instead.
- `docs/architecture/13-patterns-for-a-solo-developer.md` does not exist; `docs/architecture.md`
  §9 (Tests) was read in its place.
- The whole suite (13 min) was not rerun; skips were inferred from `conftest.missing()` conditions
  and the environment (Java present, `jpype`/`mpxj` absent, no witness folder, corpus and reference
  files present).
