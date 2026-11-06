> Note : analyse faite sur un worktree partant de `main` avant l'audit (commit `af57a08` : sans `xer/validate.py`, sans le parser en flux, sans la validation TOML ni les tests d'audit). Les scores de mutation de `calendar.py` et `standards.py` sont donc à reprendre ; ceux de `rules.py`, `populations.py` et `evm.py` restent représentatifs. Le crosscheck MPXJ, noté « skippé » ici, a depuis été exécuté (31 + 196 tests verts).

# Targeted mutation testing (mutmut 3.8.1)

Setup: a scratch copy of `src/` and `tests/` (no corpus, no reference files) under
a scratch copy of the repository, `uv sync --locked` there, `[tool.mutmut]` appended to a copy of
`pyproject.toml` per module (`source_paths = ["src"]`, `only_mutate = [<module>]`,
`pytest_add_cli_args_test_selection = [<the fast tests named in the brief>]`,
`pytest_add_cli_args = ["-p", "no:cacheprovider", "-x"]`, `timeout_multiplier = 5`,
`timeout_constant = 5`), `mutmut run --max-children 4`, each run bounded by `timeout`. mutmut 3
runs, for each mutant, only the tests that executed the mutated function during the stats pass, so
"no tests" below means *none of the selected test files reaches that function*. Score =
killed / (total - no tests). Driver scripts: `mut/run_module.sh`, `mut/show_survivors.sh`,
`mut/show_from_cache.sh`; raw outputs: `tests/mut_<module>*.txt|log`, caches
`tests/mutants_<module>/`.

The brief named `tests/test_audit_edges_xer.py` and `tests/test_audit_edges_app.py`; neither exists
on this branch, so `tests/test_audit.py` (the audit sets) was used in their place.

## Summary

| module | tests used | mutants | killed | survived | timeout | no tests | other | score |
|---|---|---|---|---|---|---|---|---|
| xer/calendar.py | test_shift_calendar, test_calendar_and_standards, test_audit | 783 | 583 | 171 | 4 | 24 | 1 segfault | **76.8 %** (583/759) |
| analysis/rules.py + populations.py | test_rules, test_explain, test_audit | 836 | 576 | 201 | 0 | 59 | - | **74.1 %** (576/777) |
| analysis/standards.py | test_calendar_and_standards, test_audit | 356 | 218 | 121 | 0 | 17 | - | **64.3 %** (218/339) |
| analysis/evm.py | test_pv_p6, test_spi_cost, test_weekly, test_analysis_and_viz | 1968 | 1492 | 476 | 0 | 0 | - | **75.8 %** (1492/1968) |

Wall time: calendar ~19 min, rules+populations 16.5 min, standards 8 min, evm 10 min (4 children
each). No module had to be truncated.

## xer/calendar.py (783 mutants, ~19 min wall with 4 children)

Survivors by function: `WorkCalendar.from_row` 42, `TimeAxis._build` 26, `TimeAxis.at` 15,
`TimeAxis.work_many` 10, `TimeAxis.minute` 9, `parse_clndr_data` 9, `TimeAxis._raw` 8,
`work_hours` 6, `axis` 6, `_parse_tree` 6, `is_working` 4, `_ensure` 4, `_interval` 4, others 1-3.
"No tests" (24): `WorkCalendar.standard`, `_Node.find` partly, `working_days` partly: no selected
test calls them (the CPM tests do, but were out of scope here).

Classes of survivors:

- **Equivalent or near-equivalent** (not test gaps): the `errors="coerce"` removals, `str(None)`
  for `clndr_name`, `dtype=None` / `strict=` variants, `ValueError(None)` messages, the axis
  origin dates (`date(2020,1,1)` -> any date: by design "results never depend on the day the axis
  was built"), the growth margins (400 -> 401). About 60 of the 171.
- **Real gaps** (a test in the named files should have caught them): 15 listed below.

The 15 most meaningful survivors, with the test that should have killed each:

| # | mutant (line) | why it matters | test that should catch it |
|---|---|---|---|
| 1 | `_interval`: `start, end = h0*60 - m0, h1*60 + m1` (and `+ m1` -> `- m1`) | every working period of every test calendar starts and ends on a full hour (`08:00`, `12:00`, `13:00`, `17:00`, `16:00`, `18:00`), so the minutes term is never exercised: a calendar with `08:30-12:15` would be read wrong and no test notices | `test_calendar_and_standards.py::test_work_hours_are_exact_within_days`: add a calendar `clndr_data(range(2,7), [("08:30","12:15"),("13:00","17:00")])` and assert `work_hours(Mon 08:30, Mon 12:15) == 3.75` (also closes the review's "non-hour period" boundary) |
| 2 | `_interval`: `end += MINUTES_PER_DAY` -> `end = MINUTES_PER_DAY` | the `f|00:00` midnight-end convention is tested only from a `00:00` start (24 h day), where both expressions give 1440; a shift `22:00-00:00` would be read as `22:00-24:00` either way... but `16:00-00:00` with the mutant still gives 1440: equivalent here. Kept because it shows the test fixture's blind spot: no night shift is in any calendar test | add a night-shift calendar `[("22:00","06:00")]` (end before start, wraps) and assert its hours: P6 stores such a shift as two periods; assert the parser's behaviour explicitly |
| 3 | `parse_clndr_data`: `1 <= int(d.name) <= 7` -> `< 7` / `<= 8` | Saturday (7) is working in `SEVEN_DAYS_8H`, yet no selected test asserts Saturday hours of C7D; `<= 8` is equivalent (no day 8), `< 7` drops Saturday | `test_calendar_and_standards.py::test_p6_day_numbers_start_on_sunday`: parse `SEVEN_DAYS_8H` too and assert `[8]*7`; `test_shift_calendar` could use C7D once |
| 4 | `parse_clndr_data`: `serial.lstrip("-")` -> `rstrip` / `lstrip(None)` | negative Excel serials (pre-1899) never appear in a fixture, so the guard is untested; harmless today, but a fixture with a bad serial (`d|abc`) would also show the `or` mutation (`serial or ...`) crashing | add one malformed exception node to `test_working_exception_and_midnight_end` and assert it is skipped |
| 5 | `WorkCalendar.from_row`: `hpd > 0` -> `hpd >= 0` / `> 1`; `pd.notna(hpd) and` -> `or` | `day_hr_cnt = "0"` or `""` never occurs in a fixture; a zero hours-per-day calendar would divide by zero downstream (`hours_to_days`) | `test_missing_blob_infers_workweek_from_hour_counts`: add `day_hr_cnt = "0"` and `""` rows and assert `hours_per_day == 8.0` (the default) |
| 6 | `from_row`: `whc > 0` -> `>= 0` / `> 1`; `whc / hpd` -> `whc * hpd` | the inferred workweek is tested for 56/8 = 7 and `""`; `whc * hpd` survives because 56*8 = 448 -> clamped to 7 as well, and `""` skips the branch | add `week_hr_cnt = "24"` with `day_hr_cnt = "8"` (3 working days) and `"0"` (default 5) |
| 7 | `from_row`: `any(parsed[0])` -> `any(parsed[1])` | a blob with an empty week but exceptions would be taken as parsed; a blob with a week but no exceptions (`MON_FRI_10H`) would fall back to the hour-count inference, which happens to give the same 5 x 10 h week | assert `from_data is True` for a C10 calendar built from `MON_FRI_10H` (no exceptions) |
| 8 | `from_row`: `from_data=False` -> `True`, and the fallback's `{}` / `hpd` -> `None` | `from_data` is read only by `test_reference.py` (MPXJ, skipped here) | assert `from_data` in `test_missing_blob_infers_workweek_from_hour_counts` |
| 9 | `TimeAxis.at`: `while w + base < 0 or (finish and w + base == 0)` -> `and`, `<= 0`, `== 1`; the symmetric end-of-axis loop (`cum[-1]` -> `cum[-2]`, `not finish` -> `finish`) | the growth-at-the-boundary logic (a finish exactly at the axis origin must grow backwards one more period) is never hit: every test lands well inside the axis | `test_time_axis_values_survive_growing_backwards`: build `TimeAxis(cal, date(2026,3,2), date(2026,3,2))` (one day) and assert `at(0, finish=True) == Fri 2026-02-27 17:00` and `at(ax.cum[-1], finish=False) == Tue 2026-03-03 08:00` (P6 start/finish conventions, docs/formulas.md) |
| 10 | `TimeAxis.minute`: `//` -> `/` (float minutes), `m < 0` -> `m <= 0` / `m < 1`, `>= span_min` -> `>` | sub-minute timestamps and a timestamp exactly at the axis origin or exactly at `span_min` never occur | assert `ax.work(ax.t0) == -ax.base` and `ax.work(ax.t0 + span)` after a grow; and that `minute(ts)` is an `int` for a timestamp with seconds (`2026-03-02 08:00:30`) |
| 11 | `TimeAxis.work_many`: `// 60e9` -> `/ 60e9`, `// 60000000001`, `- base` -> `+ base`, `0` -> `1` for NaT | `work_many` (the vectorised path used by the CPM and the EV spread) is reached only through `test_audit`'s demo runs, which assert counts, not minutes; its NaT -> 0 contract is untested | add to `test_time_axis_values_survive_growing_backwards`: `ax.work_many([T1, pd.NaT, T2]).tolist() == [ax.work(T1), 0, ax.work(T2)]` |
| 12 | `TimeAxis._periods`: `if b > a` -> `b >= a` | a zero-length period (`s|08:00|f|08:00`) is read by `_interval` as a full day (end <= start -> +1440), so `b == a` never reaches `_periods`; the guard is dead unless `_merge` produces one. Equivalent today; document or remove | - |
| 13 | `work_hours`: the four `or` -> `and` variants on the NaN guard | only one side is ever NaN in a test (`working_days` with NaT finish via the audit); `work_hours(NaT, x)` and `(x, NaT)` are not asserted | `test_work_hours_are_exact_within_days`: `assert math.isnan(cal.work_hours(pd.NaT, mon8)) and math.isnan(cal.work_hours(mon8, None))` |
| 14 | `working_days`: `0.0 if pd.isna(h)` -> `1.0` | the NaN -> 0 day convention is never asserted | `assert cal.working_days(pd.NaT, mon8) == 0.0` |
| 15 | `_ensure`: `d < self.first` -> `<=`, `d > self.last` -> `>=`; `d - margin` -> `d + margin` | a date exactly on the axis' first/last day triggers a rebuild one day early (harmless) or, with `d + margin`, a rebuild that does not include `d` when `d < first`... which the `min(self.first, ...)` still covers: near-equivalent. Shows that growth is only exercised far from the edge | the one-day axis case of #9 covers it |

Timeouts (4) and the segfault (1) are in `TimeAxis._grow` / `_build` mutants that make the growth
loop infinite (`span = max(401, ...)` style changes combined with `last -= timedelta`): expected.

## analysis/rules.py + populations.py (836 mutants, 16.5 min)

Survivors by function: `read_docstring` 52, `link_funnel` 38, `rule` (the decorator) 19,
`bei_from_snapshot` 15, `Rule._check_vocabulary` 14, `invalid_date_reason` 11, `link_population` 9,
`_check_value` 7, `share_of_type` 6, `late_output` 4, `critical_path_output` 4, `Funnel.keep` 3,
`finish_driver` 3, `_project_ends` 2, `_exempt_masks` 2, `lag_flagged` 2, `as_flag` 2, singles.
"No tests" (59): all of `bei_from_baseline`: it is reached only by the generic `bei` rule with
`due_from = "baseline"`, which no built-in standard and no test uses (P6-13 is an explicit function).

Classes: `read_docstring` / `rule` / `_check_vocabulary` / `_check_value` survivors (92) are the
docstring-to-explanation parser and the TOML validation messages (`ValueError(None)`, text case):
the explanation text is asserted for a handful of lines only, so most wording mutations survive;
low value. `link_funnel` / `link_population` survivors (47) include parameter defaults and step
labels **and** every `link_funnel(None, ...)` variant: the generic `lag` / `relationship_type`
rules that call `link_population` are exercised only through the custom template's CUS-04 in
test_explain, so a broken call signature survives.

The 15 most meaningful survivors:

| # | mutant (line) | why it matters | test that should catch it |
|---|---|---|---|
| 1 | `bei_from_snapshot`: `is_due = bl_finish <= data_date` -> `< data_date` | a baseline finish exactly on the status date is "due" (PAM 200.1 §3.1.2.4 "on or before"); DCMA-14's fixtures have no such row (test_dcma_11_due_by_day covers DCMA-11 only) | test_rules.py: DCMA-14 with `target_end_date = "2026-03-02 08:00"` (= data date), not finished: `counts == (0, 1)` |
| 2 | `bei_from_snapshot`: `late = due[~is_done[due.index]]` -> `due[is_done...]` | the *flagged list* of DCMA-14 (due-not-done tasks) is never asserted: `codes(r)` is asserted only as `[]` | test_bei_p6_counts_due...: `assert codes(dcma) == ["C", "NEW"]` |
| 3 | `bei_from_snapshot`: `completed_by_data_date: bool = False` -> `True`; `date_grain = "timestamp"` -> other | the defaults are never used by a caller (DCMA-14 passes both explicitly): dead defaults, or a missing test of the P6 EPPM reading | call `bei_from_snapshot(population, dd, True)` once in test_rules with a task finished after the data date: counted as completed |
| 4 | `forecast_before` (populations.py): `early_finish < data_date` -> `<=` | an in-progress remaining finish *exactly at* the status date is not invalid (P6: "earlier than"); no fixture has one (RUN finishes 02-27, LATE 03-05) | test_invalid_progress_dates: `active("ATDD", restart_date=DD, reend_date=DD)` not flagged by P6-10a / DCMA-09 |
| 5 | `actual_after`: `start > data_date` -> `>=` | an actual **start** exactly on the data date is valid; only the actual **finish** on the data date is tested (ON) | test_p6_10b_...: `active("STARTDD", act_start_date=DD)` not flagged, in the denominator |
| 6 | `invalid_date_reason`: `[forecast & actual, forecast]` -> `[forecast | actual, forecast]` and every reason text | the combined "forecast before and actual after" reason is never asserted (no fixture has both on one task), and the P6-10a/10b reason strings are never read | test_invalid_progress_dates: a task with `early_start_date` before DD and `act_end_date` after DD; `r.flagged["reason"]` equals the three texts |
| 7 | `lag_flagged`: `fillna(0)` -> `fillna(1)` | a relationship with a **blank** `lag_hr_cnt` (P6 writes blanks) is a 0 lag; no fixture leaves the lag blank | test_lead_long_lag_and_fs_share: add `("A", "B", "FS", "")` and assert P6-08 does not flag it |
| 8 | `_exempt_masks`: `finish_milestone = is_milestone & ~is_start_milestone` -> `|` / `& is_start_milestone` | the `finish_milestone` exemption key is validated (`test_every_exemption_has_a_mask`) but never used by a test, so its mask is unchecked | test_missing_logic_keeps_exemptions...: `succ_exempt=["finish_milestone"]` on LOGIC: F passes, M0 still flagged |
| 9 | `_project_ends`: `tasks[~isin(succ_code)]` -> `tasks[isin(...)]`; `first = None` | the project_start exemption is tested only on LOGIC, where the earliest start (D0) is complete and excluded anyway, so the wrong set gives the same answer | a fixture whose earliest-starting open task has no predecessor and is not the one with the smallest start among linked tasks: `pred_exempt=["project_start"]` must pass exactly it |
| 10 | `late_output`: `.round(2)` -> `.round(3)`; numerator `len(flagged)` -> `None` | `finish_variance_wd` is asserted with `approx(..., abs=0.01)`, which hides the rounding; the `None` numerator survives because `run_metric` recomputes it from the flagged rows | assert `r.flagged["finish_variance_wd"].iloc[0] == 0.12` exactly for the 1/8 d case (P6 shows two decimals) |
| 11 | `finish_driver`: `& ~is_loe & finish.notna()` -> `|` variants | DCMA-12/13 pick the finish driver; no fixture has an LOE with the latest finish (which must be skipped) | test_cpli_...: add `todo("LOE", task_type="TT_LOE", early_end_date="2026-04-30 17:00")` and assert the CPL still ends at Z |
| 12 | `share_of_type`: `share = None`, `note=mix` dropped | P6-07/DCMA-04's `note` (the type mix "FS 2, SS 1") is never asserted; the value survives because `run_metric` derives it from numerator/denominator (equivalent) | test_p6_07_...: `assert r.note == "FS 2, SS 1"` |
| 13 | `critical_path_output`: `note="no remaining work"` -> other text / `None` | the all-complete schedule case of DCMA-12 is not tested | `run(DCMA, "DCMA-12", snap([done("A")]))`: `status == "n/a"` and `"no remaining work" in note` |
| 14 | `link_population(context, links, exclude_loe, exclude)` -> any argument `None` (9 survivors), `exclude_loe` default flipped | the generic `lag` and `relationship_type` rules run only via CUS-04 of the template; their populations (`links = "all" / "succ_incomplete" / ...`, `exclude_loe`) are untested | a `test_custom_rules.py`: every `@rule` of rules.py run through `loads_standard` on LINKS / LOGIC with each `links` value and `exclude_loe = true`, counts by hand |
| 15 | `activities(context, exclude)`: `without(..., data_date=None, ...)` | the `complete_before_data_date` exclusion needs the data date; every generic rule passes it but no generic-rule test uses that exclusion | the same custom-rule test with `exclude = ["complete_before_data_date"]` |

## analysis/standards.py (356 mutants, 8 min)

Survivors: `parse_standard` 41, `_parse_metric` 40, `Metric.evaluate` 17, `loads_standard` 7,
`builtin_standards` 6, `decode` 3, `template_text` 2, `parse_target` 2, `load_standard` 2.
"No tests" (17): `discover_standards` (the app's folder scan).

Most `parse_standard` / `_parse_metric` survivors are error-message wording (`ValueError(None)`,
`entry.get("source", "")` -> `None`, `group`, `description` fallbacks): test_invalid_standard_fails_loudly
matches 13 messages but none reads `source`, `group` or the docstring-derived `description`. The
important ones:

| # | mutant | why it matters | test |
|---|---|---|---|
| 1 | `Metric.evaluate`: `"pass" if (...) and False` / `or True` (always fail / always pass) | **no selected test asserts a pass/fail status** (the two files named for this module do not; test_rules does). A scope artefact, but it shows `evaluate` has no unit test of its own | add to test_calendar_and_standards: `Metric(..., unit="%", comparator="<", threshold=5).evaluate(4.9) == "pass"`, `(5.0) == "fail"`, `(None) == "n/a"`, `Metric(comparator=None).evaluate(3) == "info"` |
| 2 | `Metric.evaluate`: `round(value, 6)` -> `round(value, 7)` / `round(value)` | the rounding guard has no test at all (review.md §3.7) | `evaluate(5.0000000001)` under `<= 5` is `"pass"`; `evaluate(5.4)` under `<= 5` with `round(value)` would wrongly pass: assert `"fail"` |
| 3 | `evaluate`: `comparator is None or threshold is None` -> `and` / `is not None` | an informational metric with a comparator but no threshold (buildable from code) | assert `Metric(comparator="<", threshold=None).evaluate(1) == "info"` |
| 4 | `parse_target("pass")` -> `("==", 2.0)` | the pass/fail metrics (DCMA-12, 06A401a) carry threshold 1.0; the only check is indirect (`value=1.0 if passed`) | `assert parse_target("pass", "pass/fail") == ("==", 1.0)` and DCMA-12's `threshold == 1.0` |
| 5 | `parse_target`: `("", "info")` -> `("XXXX", "info")` | an empty `target = ""` is informational; untested | `loads_standard` with `target = ""` gives `comparator is None` |
| 6 | `parse_standard`: `"id" not in head or "name" not in head` -> `and`; `where = path or "standard"` | a `[standard]` table missing `name` only is accepted by the mutant; the file name in the message is never checked | `loads_standard('[standard]\nid = "X"\n')` raises "needs a [standard] table" and the message starts with the file name |
| 7 | `_parse_metric`: `description = entry.get("description", rule.doc first line)` -> `None` / other key | the default description (first docstring line) is what the app shows for every built-in metric without a `description` | assert a metric without `description` has `RULES[rule].doc.splitlines()[0]` |
| 8 | `_parse_metric`: `source = entry.get("source", "")` -> `None`, `group` likewise | CONTRIBUTING rule 2: every rule names its source; nothing asserts the field survives parsing | `assert all(m.source for std in builtin_standards().values() for m in std.metrics)` (test_standards_conformity.py) |
| 9 | `parse_standard`: `enumerate(..., start=1)` -> `start=2` | "metric #N" in error messages is off by one | `match="metric #1"` in one `test_invalid_standard_fails_loudly` case |

## analysis/evm.py (1968 mutants, 10 min)

Survivors by function: `pv_p6_comparison` 127, `pv_labor_check` 95, `ev_technique` 25,
`pv_curve` 23, `performance_pct` 22, `earned` 21, `_elapsed` 21, `forecast_curve` 20, `_pct_band` 20,
`_Spread.at` 18, `_ramp_sum` 17, `_Spread.build` 15, `etc_settings` 12, `EvPoint.as_row` 11,
`evm_series` 7, `ev_point` 6, `etc_technique_counts` 6, `planned_value_cost` 5, `bei_series` 4.

`pv_p6_comparison` and `pv_labor_check` (222 survivors, 47 % of all) are the diagnostic tables:
mostly column-name / label / `astype(None)` / `sort=` mutations on frames whose columns the tests
read by name (a renamed column is caught where read, survives where only carried). The
calculation survivors:

| # | mutant | why it matters | test |
|---|---|---|---|
| 1 | `_Spread.build`: `snapshot.calendar(calendar_id)` -> `calendar(None)` | every `pv_curve` / `forecast_curve` fixture runs on the project calendar (C8), so a spread that ignores the activity's calendar gives the same curve; `test_gap_by_baseline_calendar` covers `_elapsed` (ev_point), not the curves | test_weekly.py::test_pv_spreads_over_working_days on a C10 activity (80 h = 8 days of 10 h): `pv_hr` 10 per day, 8 rows; `forecast_curve` on C7D: the Saturday row grows |
| 2 | `_Spread.at`: `cumulative = [[1.0], ...]`; steps `total += ...` -> `total = ...` | zero-duration rows (a milestone with hours, an assignment with start == finish) in a PV spread are never in a fixture: the "step" branch is untested | a baseline with `todo("M", **FM, target_work_qty="10", early_end_date=...)`: `pv_cum_hr` jumps by 10 at M's instant, 0 before |
| 3 | `_elapsed`: `durations > 0` -> `>= 0` / `> 1`; the zero-span branch | same class through `schedule_pct`: a zero-length span is 0 before its instant and 1 from then on, untested | `schedule_pct` on a milestone baseline: 0 the minute before, 100 at its instant |
| 4 | `_ramp_sum`: `-hours / durations` -> `+hours / durations` / `-hours * durations` | the finish breakpoint's slope change survives because no grid point lies after one activity's finish while another still runs (sum of two ramps) | `pv_curve` with two overlapping activities (A Mon-Fri 40 h, B Wed-Tue 40 h): daily `pv_hr` by hand `[8, 8, 16, 16, 16, 0, 0, 8, 8]` |
| 5 | `_ramp_sum`: `np.where(position < 0, 0.0, result)` -> `1.0` | PV before the baseline starts is tested only through `spi_cost is None` (test_spi_cost) | `_pv_at(bl, "2026-02-27 17:00") == 0` in test_weekly |
| 6 | `pv_curve`: `ev_labor_hr > 0` -> `> 1` / `>= 0`; `freq="D"` dropped | activities with 0 < hours <= 1 never occur; `freq` default is "D" (equivalent) | a 1 h activity in the baseline: present in the curve |
| 7 | `etc_settings`: `proj_node_flag != "Y"` -> any (5 survivors) | the project node row is never in a fixture's WBS for `etc_settings` (`_wbs` writes `"N"` only) | add the W0 project node to `_wbs` and assert it is not listed |
| 8 | `earned` / `performance_pct` / `ev_technique` (68, label and fillna mutants) | `ev_technique("EC_WBS_pct") == "wbs_milestones"` is asserted, but `perf_pct` under `wbs_milestones` / `resource_curves` (fallback to activity %) is not | `test_performance_pct_follows_the_wbs_ev_technique`: add `("EC_WBS_pct", "active", 25)` and assert `ev_point(...).on_fallback` names A |
| 9 | `forecast_curve` (20) | the `fc_start = max(start, data_date)` / `fc_finish = max(finish, fc_start)` clamps are tested only with start == data date | an open activity whose `start` is before the data date and one whose `finish` is before it: both spread from the data date, the second all at once |
| 10 | `EvPoint.as_row` / `evm_series` (18) | column order is asserted for the first 14 and the last 4 names; the middle (`unbaselined`, `ac_unbaselined_hr`, `deleted`, `pv_deleted_hr`...) is not | assert the full `list(row.index)` once |

## Reading across the four modules

1. The **explicit P6 / DCMA / DECM checks are well protected**: the rules.py survivors sit almost
   entirely in the generic parameterised rules and the explanation parser. The hand-counted
   fixtures of test_rules.py and test_p6_check_schedule.py do their job.
2. The **generic rule engine for custom standards** (`lag`, `relationship_type`, `float`,
   `duration`, `constraints`, `invalid_dates`, `no_resource`, `late_vs_baseline`, `bei` with
   `due_from = "baseline"`) is covered only by validation tests and one CUS-04 run: a
   `test_custom_rules.py` with each rule, each `links` / `exclude` value and hand counts is the
   single highest-value addition.
3. **Boundaries at the data date** survive in both directions (`<` vs `<=` on the remaining
   finish, the actual start, the baseline finish for BEI): the gap review.md §3 found by reading.
4. **Calendar arithmetic** survives where fixtures are too regular: full-hour periods, no night
   shift, no working exception in `work_hours`, no zero-length spread, no non-project calendar in
   the PV/forecast curves, no blank lag.
5. `Metric.evaluate` and `parse_target` have no unit test; the status logic is checked only
   through the rules.
