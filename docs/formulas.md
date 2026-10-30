# Formulas

Every number xerscope computes, as the code computes it. File and function names refer
to `src/xerscope/`; test names to `tests/`. Where this document and the code differ, the
code is right and this document is wrong.

## 1. Conventions

### 1.1 Inputs (xer/model.py `build_snapshot`)

| Quantity | Source | Notes |
|---|---|---|
| Data date | `PROJECT.last_recalc_date`; blank: `PROJECT.plan_start_date`; both blank: none | Rules that need it return n/a or error |
| Activity ID | `TASK.task_code` | `task_id` is used only to resolve links inside one file; duplicates keep the first row in joins |
| Activities | `TASK` rows of the project with `task_type != TT_WBS` (`Snapshot.activities`) | WBS summary rows are excluded from every population and count |
| Relationships | `TASKPRED` rows of the project whose predecessor and successor both have a `TASK` row in the file | Others are dropped (a warning when the predecessor is not in another project); `is_external` = predecessor in another project; `has_external_pred` / `has_external_succ` flag activities linked to other projects |
| Hours per day (`hours_per_day`) | `CALENDAR.day_hr_cnt` of the activity's calendar; 0 or missing: 8 (`config.Settings.default_hours_per_day`) | |
| Start / Finish (`start`, `finish`) | actual date, else `restart_date` / `reend_date`, else `early_start_date` / `early_end_date`, else `target_start_date` / `target_end_date` | P6's Start / Finish columns |
| Forecast finish (`finish_date`) | max `finish` over activities (WBS summary excluded) | `PROJECT.scd_end_date` is kept as `scheduled_finish` only |
| Total float (days) `total_float_d` | `total_float_hr_cnt / hours_per_day`; NaN when complete | `free_float_d` likewise |
| Remaining duration (days) `remaining_d` | `remain_drtn_hr_cnt / hours_per_day` | |
| Original duration (days) `original_d` | `target_drtn_hr_cnt / hours_per_day` | |
| Lag (hours) `lag_hr` | `TASKPRED.lag_hr_cnt`, blank = 0 | |
| Lag (days) `lag_d` | `lag_hr / hours_per_day` of the **predecessor's** calendar | Display only; rules use hours unless `unit = "days"` |
| Labour hours `labor_budget_hr / labor_actual_hr / labor_remaining_hr` | `TASK.target_work_qty / act_work_qty / remain_work_qty` when any `target_work_qty` is present in the project; else sums of `TASKRSRC.target_qty / (act_reg_qty + act_ot_qty) / remain_qty` over assignments with `rsrc_type` in {RT_Labor, role, blank}; else 0 | `Snapshot.options["labor_source"]` = TASK / TASKRSRC / none |
| Has resource | activity has at least one `TASKRSRC` row (any type, roles included) | |
| Has expense | activity has at least one `PROJCOST` row | |

### 1.2 Status words (boolean columns on `activities`)

| Word | Definition | EXCLUDE key (rules.py) |
|---|---|---|
| complete | `status_code == TK_Complete` | `complete` |
| started | `status_code != TK_NotStart` (in progress or complete) | `started` |
| complete before data date | `act_end_date < data date` (no data date: complete) | `complete_before_data_date` |
| milestone | `task_type` in {TT_Mile, TT_StartMile, TT_FinMile} | `milestones` |
| start milestone | `task_type` in {TT_Mile, TT_StartMile} | (exemption `start_milestone`) |
| finish milestone | milestone and not start milestone | (exemption `finish_milestone`) |
| LOE | `task_type == TT_LOE` | `loe` |
| no duration | not (`target_drtn_hr_cnt > 0`) | `no_duration` |
| WBS summary | `task_type == TT_WBS` | always excluded |
| critical | not complete, not WBS summary, and: `PROJECT.critical_path_type == CT_DrivPath` → `driving_path_flag == Y`; else `critical_drtn_hr_cnt` present → `total_float_hr_cnt <= critical_drtn_hr_cnt`; else `total_float_d <= 0` | LOE included, as P6 |

A rule's `exclude` list removes activities matching any listed key (`rules.activities`).
Link populations (`rules.link_population`): `all`; `not_both_complete` = drop links whose
predecessor and successor are both complete; `succ_incomplete` = drop links whose
successor is complete. Links whose successor is a WBS summary are always dropped.

### 1.3 Percent complete (xer/model.py `percent_complete`)

By `TASK.complete_pct_type`: `CP_Drtn`: `(target_drtn_hr_cnt − remain_drtn_hr_cnt) / target_drtn_hr_cnt × 100`,
floored at 0, 100 once complete, undefined when original duration is 0;
`CP_Units`: `(act_work_qty + act_equip_qty) / (actual + remain_work_qty + remain_equip_qty) × 100`,
undefined when the total is 0; any other type: `phys_complete_pct`. Undefined values fall
back to `phys_complete_pct`, then to 100 if complete else 0. Clipped to [0, 100], rounded
to 2 decimals. Pinned by `test_reference.py::test_percent_complete_matches_p6_export`,
`test_percent_complete_rules`.

### 1.4 Working time (xer/calendar.py)

- Working periods per weekday and per exception date are parsed from
  `CALENDAR.clndr_data`, to the minute; overlapping periods are merged. A calendar
  without a usable blob gets `round(week_hr_cnt / day_hr_cnt)` working days (1–7, default
  5) of `day_hr_cnt` hours from 08:00; a missing calendar is Monday–Friday 8 h from 08:00.
- `work_hours(a, b)` = working minutes between `a` and `b` / 60, negative when `b < a`.
  A timestamp in non-working time counts as the start of the next working period.
- `working_days(a, b)` = `work_hours(a, b) / hours_per_day` where `hours_per_day` is
  `CALENDAR.day_hr_cnt`, not the length of the parsed day.
- "wd" in this document = working days of the calendar named for that quantity.
  "Project calendar" = `PROJECT.clndr_id`, else the first calendar in the file, else the
  Monday–Friday 8 h default (`Snapshot.calendar()`).
- `Snapshot.work_hours` / `working_days` (row-wise) use each row's `clndr_id`; blank or
  unknown ids fall back to the project calendar; NaN where a date is missing.

### 1.5 Targets and statuses (analysis/standards.py, analysis/checks.py)

| Target text | Comparator | Threshold | Metric unit |
|---|---|---|---|
| `< 5%`, `<= 5%`, `> 90%`, `>= 90%` | `<`, `<=`, `>`, `>=` | 5, 90 | `%` only |
| `<= 0`, `<= 10` | `<=` | 0, 10 | `count` |
| `>= 0.95` | `>=` | 0.95 | `ratio` |
| `pass` | `==` | 1.0 | `pass/fail` (rule value 1.0 = passed, 0.0 = failed) |
| `info` or absent | none | none | any |

A metric's parameters are checked on load against the rule's signature (`Rule.validate`):
unknown name, wrong choice, non-number, non-flag, string instead of list; a metric may
swap `%` and `count`, no other unit. Value per unit (`checks.run_metric`): `%`: the rule's `value` if it set one (only
`relationship_type`), else `100 × numerator / denominator`, none when the denominator
is 0; `count`: `numerator`; `ratio`, `pass/fail`: the rule's `value`.

Status: `n/a` when the metric needs a baseline and none is loaded, or the value is none
(empty population, missing data date or previous update); `error` when the rule raised
(the note carries the exception); `info` when the target is `info`; else `pass` if
`comparator(round(value, 6), threshold)` holds, else `fail`. So `<= 0%` and `<= 0` pass
only when the numerator is 0.

## 2. Standards

Column key: **Population** = rows the rule examines (denominator unless stated);
**Found** = rows counted in the numerator. All activity populations exclude WBS summary
rows. "Reference" = `test_reference.py::test_dcma_matches_stated_result[<id>]` against
xerlock's published counts on its sample file.

### 2.1 P6 Check Schedule (`standards/p6.toml`, standard id `P6`)

Thresholds in hours as P6 compares them; 352 h is the TOML author's reading of
44 days × 8 h. Targets are the Check Schedule dialog defaults as the P6 EPPM 25 help
states them (strict comparisons: "less than 5%", "greater than 90%", BEI "0.95 or
greater"); the dialog's own values must be copied in for pass/fail to match a report.
Constraint sets follow the P6 Professional help: hard = Mandatory Start, Start On,
Mandatory Finish, Finish On; soft = On or Before / On or After, As Late As Possible.

| Id | Name | Population | Found | Unit | Target | Source (TOML) | Tests (test_rules.py) |
|---|---|---|---|---|---|---|---|
| P6-01 | Logic | activities not complete | no predecessor or no successor among the project's own links; an external link counts as a link; started activities and start milestones pass the predecessor side, finish milestones the successor side | % | < 5% | 46291: WBS summary and actual-finish removed; actual start or start milestone pass the predecessor check; finish milestones pass the successor check; external links pass | test_p6_logic_exemptions, test_external_successor_passes_p6_logic, test_start_milestone_without_successor_is_an_open_end_for_p6, test_link_to_an_activity_not_in_the_file_is_dropped |
| P6-02 | Hard constraints | not complete, not LOE | `cstr_type` or `cstr_type2` in {CS_MANDSTART, CS_MSO, CS_MANDFIN, CS_MEO}; a start constraint (MSO, MSOA, MSOB, MANDSTART) on a started activity does not count | % | < 1% | 46286: WBS summary, actual-finish and LOE removed; start constraints ignored once started | test_constraint_sets_differ_between_p6_and_dcma |
| P6-03 | Soft constraints | not complete, not LOE | `cstr_type` or `cstr_type2` in {CS_MSOB, CS_MSOA, CS_MEOB, CS_MEOA, CS_ALAP}, same started exemption | % | < 5% | 46285: Start on or before / on or after, Finish on or before / on or after, As late as possible | test_constraint_sets_differ_between_p6_and_dcma |
| P6-04 | Large durations | not complete, not LOE (milestones stay in) | `remain_drtn_hr_cnt > 352` | % | < 5% | 101248 (P6 Professional 24 help, Check Schedule dialog): completed, WBS summary and LOE not included | test_large_duration_remaining_vs_original |
| P6-05 | Long lags | links `not_both_complete` | `lag_hr > 352` | % | < 5% | 46288: links between two actual-finished activities removed | test_lead_long_lag_and_fs_share |
| P6-06 | Large float | not complete, not LOE | `total_float_hr_cnt > 352` | % | < 1% | 46284: WBS summary, actual-finish and LOE removed | test_float_threshold_in_hours_vs_working_days |
| P6-07 | Relationship types | links `not_both_complete` | value = `100 × FS links / links`; listed: non-FS links | % | > 90% | 46287: actual = share of FS links in the subset | rule: test_lead_long_lag_and_fs_share (DCMA-04); population: test_link_populations_differ |
| P6-08 | Lags | links `not_both_complete` | `lag_hr > 0` | % | < 5% | 46289 | test_link_populations_differ, test_link_to_an_activity_not_in_the_file_is_dropped |
| P6-09 | Negative lags | links `not_both_complete` | `lag_hr < 0` | % | < 1% | 46290: links between two actual-finished activities removed | rule: test_lead_long_lag_and_fs_share (DCMA-02) |
| P6-10 | Invalid progress dates | not LOE, not complete before the data date | forecast: not complete and forecast start < data date (remaining early start once started; `in_progress = "start"`), forecast = `restart_date` else `early_start_date`; actual: `act_start_date > data date` or `act_end_date > data date` | % | < 1% | 101248 (P6 Professional 24 help, Check Schedule dialog): not started, start before the data date; in progress, remaining early start before it or actual start after it; completed, actual finish after it | test_invalid_progress_dates |
| P6-11 | Resource / cost | not milestone, not LOE (complete stay in) | no `TASKRSRC` row and no `PROJCOST` row | % | < 1% | 46279: WBS summary, milestones and LOE removed (completed activities stay in); a role assignment counts | test_resource_or_expense |
| P6-12 | Late activities | not milestone, not LOE (complete stay in) | `work_hours(bl_finish → finish) > 0` on the activity's current calendar, `bl_finish` else `target_end_date` (`no_baseline = "planned"`); `finish_variance_wd` = that / `hours_per_day` | % | < 5% | 101248 (P6 Professional 24 help, Check Schedule dialog): milestones, WBS summary and LOE not included; no baseline counterpart = late when the remaining early finish is later than the planned finish; 46278: variance in working time | test_missed_tasks_and_late_activities, test_late_activities_use_working_time |
| P6-13 | BEI | not LOE, not milestone, in the snapshot (completed) and in the baseline (due); due = baseline activity with `bl_finish <= data date` (`due_from = "baseline"`) | value = complete activities in population / due; listed: due and not complete | ratio | >= 0.95 | 101248 (P6 Professional 24 help, Check Schedule dialog): completed activities of the open project / baseline activities finishing before its data date | test_bei_p6_counts_due_in_the_baseline_dcma_in_the_schedule, test_baseline_metrics_are_na_without_baseline |
| P6-14 | Negative float | not complete, not LOE | `total_float_hr_cnt < 0` | % | < 1% | 46283: WBS summary, actual-finish and LOE removed | test_float_threshold_in_hours_vs_working_days |

Note: the `source` strings are Oracle help page ids (101248: the P6 Professional 24
Check Schedule dialog; 462xx: P6 EPPM Schedule Check Report sections) as read from those
pages by the TOML author; no P6 population above has been verified
against a P6 Check Schedule report (docs/backlog.md).

### 2.2 DCMA DECM v8.0, Guideline 6 (`standards/decm.toml`, standard id `DECM`)

"Incomplete" = not complete (started activities included). Status date = data date;
"on or before the status date" is read as "before the data date".

| Id | Name | Population | Found | Unit | Target | Source (TOML) | Tests (test_rules.py) |
|---|---|---|---|---|---|---|---|
| 06A204b | Dangling logic | incomplete, not LOE | open start: milestone with no predecessor; task with no FS/SS predecessor (an external predecessor counts as FS/SS). Open finish: milestone with no successor; task with no FS/FF successor. Exempt: `bl_start == min bl_start` of the whole baseline (start side), `bl_finish == max bl_finish` (finish side); without a baseline, `target_start_date` / `target_end_date` over all activities of the file | % | <= 0% | 06A204b: open start = only FF/SF or no predecessor (milestone: none); open finish = only SS/SF or no successor (milestone: none); earliest baseline start / latest baseline finish exempt | test_decm_dangling_logic, test_decm_milestone_needs_only_one_link_per_side, test_decm_project_start_exemption_does_not_move_once_work_is_done, test_decm_open_ends_on_a_progressed_schedule |
| 06A205a | Lags | incomplete (LOE included: `loe = true`) | at least one predecessor link with `lag_hr > 0` (`sign = "positive"`; `negative` counts leads, `any` both) | % | <= 10% | 06A205a: X/Y <= 10%; the sheet does not say whether LOE count or whether leads (negative lags) do: LOE kept, positive lags only | test_decm_lags_summary_logic_and_loe |
| 06A208a | Summary tasks with logic | WBS summary rows (`tasks`) | appears as predecessor or successor of any link | count | <= 0 | 06A208a: X = 0 | test_decm_lags_summary_logic_and_loe |
| 06A209a | Hard constraints | not complete (LOE included) | `cstr_type` or `cstr_type2` in {CS_MANDSTART, CS_MANDFIN}; no started exemption | % | <= 0% | 06A209a: X/Y = 0%; Primavera P6 hard constraints = Mandatory Start, Mandatory Finish; the sheet does not say whether LOE count: kept | rule only: test_constraint_sets_differ_between_p6_and_dcma |
| 06A210a | LOE with discrete successors | incomplete LOE | has a successor in the file that is not LOE | % | <= 0% | 06A210a: X = 0 | test_decm_lags_summary_logic_and_loe |
| 06A211a | High total float | not complete, not LOE | `total_float_d > 44` | % | info | 06A211a: the population DECM samples; X/Y <= 20% of the sample with inadequate rationale | rule only: test_float_threshold_in_hours_vs_working_days (DCMA-06) |
| 06A212a | Out of sequence | links whose successor is incomplete (LOE included) and whose predecessor is an activity | using `start` / `finish` (actual, else forecast): FS `S.start < P.finish`; SS `S.start < P.start`; FF `S.finish < P.finish`; SF `S.finish < P.start`; lags ignored | count | <= 0 | 06A212a: X = 0; FS (S.AS\|S.FS) < P.FF, SS (S.AS\|S.FS) < P.FS, FF (S.AF\|S.FF) < P.FF, SF (S.AF\|S.FF) < P.FS | test_decm_out_of_sequence_counts_relationships |
| 06A401a | Critical path test | see §2.5 | +600 wd | pass/fail | pass | 06A401a: the schedule's critical path is the longest path (constraint method) | rule: test_critical_path_test_passes_on_clean_logic, test_critical_path_test_fails_when_a_mandatory_date_absorbs_the_delay |
| 06A501a | Missing baseline dates | all activities | no `bl_start` or no `bl_finish` (not in the baseline, or baseline dates blank) | % | <= 5% | 06A501a: X/Y <= 5%, summaries excluded | test_decm_baseline_and_actual_dates |
| 06A504a | Actual starts changed | activities with an actual start in this update, plus those present in both updates with one in the earlier update; earlier = the latest update whose data date is <= this one − `period_days` (28; 0 = the preceding update) | present in both updates with an earlier actual start and a different (or now blank) actual start | % | <= 10% | 06A504a: X/Y <= 10%, Y = tasks with an actual start; compared with the update one status period (28 days) earlier | test_decm_actuals_changed_needs_the_previous_update, test_actuals_changed_counts_a_removed_date_on_both_sides |
| 06A504b | Actual finishes changed | same, on actual finish | same | % | <= 10% | 06A504b: X/Y <= 10%, Y = tasks with an actual finish; compared with the update one status period (28 days) earlier | test_decm_actuals_changed_needs_the_previous_update |
| 06A505a | In progress without actual start | `pct_complete > 0` or started (LOE included) | no `act_start_date` | % | <= 5% | 06A505a: X/Y <= 5% | test_decm_baseline_and_actual_dates |
| 06A505b | Complete without actual finish | `pct_complete >= 100` or complete | no `act_end_date` | % | <= 5% | 06A505b: X/Y <= 5% | none |
| 06A506a | Actual dates after the status date | denominator: activities with an actual start (all activities examined) | `act_start_date > data date` or `act_end_date > data date` | % | <= 5% | 06A506a: X/Y <= 5%, Y = tasks with an actual start | test_decm_baseline_and_actual_dates |
| 06A506b | Forecast dates before the status date | all activities | not complete and (not started and forecast start < data date, or forecast finish < data date); `include_data_date = false` | count | <= 0 | 06A506b: X = 0, forecast on or before the status date (= before P6's data date) | rule: test_invalid_progress_dates |
| 06A506c | Riding the status date | incomplete, not LOE, present in the latest update whose data date is <= this data date − 28 days | not started in both and `0 <= work_hours(data date → start) <= 3 × hours_per_day` in both (each on its own data date); or started in both and `abs(remaining_d now − remaining_d then) <= 2` | % | <= 1% | 06A506c: X/Y <= 1%; start within 3 wd of the status date in both updates, or remaining duration within +/- 2 wd | test_decm_riding_the_status_date, test_decm_riding_the_status_date_started_work |

### 2.3 DCMA 14-Point (`standards/dcma.toml`, standard id `DCMA`)

No `source` strings in the TOML; the standard is calibrated on xerlock's published
result (`tests/reference/expected.py`). Lag thresholds are in hours (rule default);
float and duration thresholds in working days of the activity's calendar.

| Id | Name | Population | Found | Unit | Target | Tests |
|---|---|---|---|---|---|---|
| DCMA-01 | Logic | not complete, not LOE | no predecessor / no successor as P6-01 (external links count) except that only activities with no predecessor and the earliest `start` among them pass the predecessor side, and only activities with no successor and the latest `finish` among them pass the successor side (computed over all activities, complete included); plus dangling start: has predecessors but none FS/SS, not started, no external predecessor, not project start; dangling finish: has successors but none FS/FF, no external successor, not project finish | % | <= 5% | test_rules: test_dcma_logic_counts_dangling_and_exempts_only_project_ends, test_dangling_start_and_finish_rule; Reference |
| DCMA-02 | Leads | links `succ_incomplete` | `lag_hr < 0` | count | <= 0 | test_lead_long_lag_and_fs_share; Reference |
| DCMA-03 | Lags | links `succ_incomplete` | `lag_hr > 0` | % | <= 5% | test_link_populations_differ; Reference |
| DCMA-04 | Relationship types | links `succ_incomplete` | value = `100 × FS / links` | % | >= 90% | test_lead_long_lag_and_fs_share; Reference |
| DCMA-05 | Hard constraints | not complete, not LOE | `cstr_type` or `cstr_type2` in {CS_MSO, CS_MSOB, CS_MEO, CS_MEOB, CS_MANDSTART, CS_MANDFIN}; no started exemption | % | <= 5% | test_constraint_sets_differ_between_p6_and_dcma; Reference |
| DCMA-06 | High float | not complete, not LOE | `total_float_d > 44` | % | <= 5% | test_float_threshold_in_hours_vs_working_days; Reference |
| DCMA-07 | Negative float | not complete, not LOE | `total_float_d < 0` | count | <= 0 | Reference |
| DCMA-08 | High duration | not complete, not LOE, not milestone | `original_d > 44` | % | <= 5% | test_large_duration_remaining_vs_original; Reference |
| DCMA-09 | Invalid dates | not LOE (complete stay in) | as P6-10 (forecast before or actual after the data date) | count | <= 0 | test_invalid_progress_dates; Reference |
| DCMA-10 | Resources | not complete, not LOE, not milestone, `target_drtn_hr_cnt > 0` | no `TASKRSRC` row and no `PROJCOST` row | % | <= 0% | test_resource_or_expense |
| DCMA-11 | Missed tasks | not LOE and `bl_finish <= data date` (milestones and complete stay in; no baseline finish = not due) | not complete, or `date(act_end_date) > date(bl_finish)` | % | <= 5% | test_missed_tasks_and_late_activities; Reference (TOML `source`: milestones kept, as in xerlock's results) |
| DCMA-12 | Critical path test | see §2.5 | +600 wd | pass/fail | pass | test_critical_path_test_passes_on_clean_logic, test_critical_path_test_fails_when_a_mandatory_date_absorbs_the_delay; test_reference: test_critical_path_test_delays_the_same_activity_as_xerlock; test_cpm: test_critical_path_test_lands_on_xerlocks_date, test_critical_path_test_shift_in_working_days; Reference |
| DCMA-13 | CPLI | see §2.5 | `(CPL + TF) / CPL` | ratio | >= 0.95 | test_cpli_uses_the_finish_float, test_cpli_needs_a_must_finish_by_date, test_calendar_holiday_counts_in_cpl; test_reference: test_cpl_matches_xerlock_hand_calculation; Reference |
| DCMA-14 | BEI | not LOE, not milestone; due = `bl_finish <= data date` (no baseline finish = not due) | value = complete in population / due | ratio | >= 0.95 | test_bei_p6_counts_due_in_the_baseline_dcma_in_the_schedule (TOML `source`: milestones left out, xerlock's results pin the value) |

### 2.4 Integrity (`standards/integrity.toml`, standard id `INTEGRITY`)

Source string: "xerscope: analysis/cpm.py, validated against P6-scheduled exports".

| Id | Name | Population | Found | Unit | Target | Tests |
|---|---|---|---|---|---|---|
| INT-01 | Schedule recalculated | not complete, not LOE, with at least one stored value among `early_start_date`, `early_end_date`, `late_start_date`, `late_end_date`, `total_float_hr_cnt` | at least one of those fields disagrees with the recalculation (§6); the note counts values, the ratio counts activities | % | <= 0% | test_rules: test_recalculated_flags_stale_dates; test_cpm: test_recalculation_reproduces_the_stored_dates_to_the_minute |
| INT-02 | Out-of-sequence progress | started, not LOE | has a predecessor link (predecessor an activity) with FS: predecessor actual finish blank or `> act_start_date`; SS: predecessor actual start blank or `> act_start_date` | count (value = found; denominator = started) | info | test_out_of_sequence_progress_is_listed |
| INT-03 | Assignments recalculated | `TASKRSRC` rows the recalculation schedules, with a stored `restart_date`, `reend_date`, `rem_late_start_date` or `rem_late_end_date` | at least one of those dates differs from the recalculation (exact timestamp) | % | <= 0% | test_rules: test_assignment_dates_integrity; test_cpm: test_assignment_dates_reproduce_p6 |

### 2.5 Critical path rules (rules.py `cpli`, `critical_path_test`; cpm.py `critical_path_test`)

**CPLI.** `end` = the activity with the latest `finish` among not complete, not LOE
activities (milestones included; ties: first row). `CPL = working_days(data date, end.finish)`
on the project calendar. `TF = end.total_float_hr_cnt / project calendar hours_per_day`
(blank float = 0). `CPLI = (CPL + TF) / CPL`; n/a when `CPL <= 0`, when there is no open
activity or data date, or when `PROJECT.plan_end_date` (Must Finish By) is blank: DCMA
measures the float to the contract finish, P6 writes it only against that date, and
without it the last activity's float is 0 and the index 1.0 whatever the schedule.

**Critical path test.** `base` = recalculated schedule (cpm.py). Delayed activity =
among not complete, not LOE, not milestone activities on the recalculated longest path,
the earliest `remaining_start` (ties: lowest `task_code`); none → fail. Delay =
`600 × hours_per_day` of that activity, added to its remaining duration; the schedule is
recalculated. Finish = max early finish over activities with no successor, before and
after. Shift = working hours between the two finishes on the delayed activity's
calendar. Pass when `shift >= delay − 1e-6 h`. On failure the note lists activities with
a mandatory constraint.

## 3. Earned value (analysis/baseline.py, analysis/evm.py)

Units: labour hours. Baseline = a designated XER (`Baseline.from_snapshot`) or the
snapshot's own `target_*` dates (`Baseline.planned`), matched by `task_code` (first row
per code kept).

| Symbol | Definition |
|---|---|
| `bl_start`, `bl_finish` | baseline's `start` / `finish` (from_snapshot) or the snapshot's `target_start_date` / `target_end_date` (planned); used by P6-12, P6-13, DCMA-11, DCMA-14, 06A204b, 06A501a, WBS roll-up |
| EV basis (`ev_basis`) | `budgeted_planned` (default): `ev_start/ev_finish` = baseline `target_start_date/target_end_date` (blank → `bl_start/bl_finish`), `ev_labor_hr` = `labor_budget_hr`; `budgeted_current`: `bl_start/bl_finish`, `labor_budget_hr`; `at_completion_current`: `bl_start/bl_finish`, `labor_actual_hr + labor_remaining_hr` |
| BAC | `Σ ev_labor_hr` over the baseline frame |
| Schedule % (per activity, at instant `t`) | `100 × clip((w(t) − w(ev_start)) / (w(ev_finish) − w(ev_start)), 0, 1)`, `w` = working minutes on the baseline activity's calendar (`bl_clndr_id`, baseline file's calendars); zero working duration: 100 when `ev_finish <= t`, else 0; rounded to 2 decimals in `earned()` |
| PV (at `t`) | `Σ ev_labor_hr × Schedule %(t) / 100` over baseline activities with `ev_labor_hr > 0` and both dates (`_Spread`, exact, unrounded); `ev_point.pv_hr` = PV at the data date |
| PV curve (`pv_curve`) | per calendar day from the first `ev_start` to the last `ev_finish`: `pv_cum_hr` = PV at 00:00 of the next day (end of that day), `pv_hr` = daily difference, `pv_pct = 100 × pv_cum_hr / BAC` |
| EV technique (`ev_technique`) | `PROJWBS.ev_compute_type` of the activity's WBS, lower-cased: blank/none or contains "cmp" → activity; "user"/"custom" → custom; "50" → 50/50; "wbs"/"mile" → wbs_milestones; "crv"/"curve"/"rsrc" → resource_curves; "0" → 0/100; else activity |
| Performance % (`performance_pct`) | activity: `pct_complete`; 0/100: 100 if complete else 0; 50/50: 100 complete, 50 started, else 0; custom: 100 complete, `PROJWBS.ev_user_pct` (blank → 0) started, else 0; wbs_milestones, resource_curves: `pct_complete` (fallback, activity listed in `not_modelled`); clipped to [0, 100] |
| EV | `Σ ev_labor_hr × Performance % / 100` over baseline activities; an activity absent from the snapshot earns 0; snapshot activities absent from the baseline (`unbaselined`) earn 0 |
| AC | `Σ labor_actual_hr` over all snapshot activities (unbaselined, LOE, complete included) |
| `ac_unbaselined_hr` | `Σ labor_actual_hr` over `unbaselined` |
| ETC | `Σ labor_remaining_hr` over all snapshot activities |
| EAC | `AC + ETC` |
| SV | `EV − PV` |
| SPI | `EV / PV`; none when PV = 0 |
| `productivity` (EV/AC) | `EV / (AC − ac_unbaselined_hr)`; none when that is 0 |
| `pv_pct`, `ev_pct` | `100 × PV / BAC`, `100 × EV / BAC`; none when BAC = 0 |
| Forecast curve (`forecast_curve`) | per calendar day from the data date's day to the last open finish: `AC + Σ labor_remaining_hr` of not complete activities with remaining hours > 0, spread linearly in working time (activity's own calendar) from `max(start, data date)` to `max(finish, that start)`; a row names a day and holds the cumulative at its end, as `pv_curve` |
| BEI | P6-13: `complete / (baseline activities with bl_finish <= data date)`; DCMA-14: `complete / (bl_finish <= data date)`; both over activities not LOE, not milestone; `complete` counts every complete activity in that population, due or not |

`evm_series` = one `EvPoint` row per snapshot against one baseline. Pinned by
`test_weekly.py`: test_pv_spreads_over_working_days,
test_pv_is_schedule_pct_complete_in_working_time, test_pv_skips_calendar_holiday,
test_ev_spi_and_unbaselined, test_performance_pct_follows_the_wbs_ev_technique,
test_ev_technique_codes, test_ev_basis_follows_p6_admin_preference,
test_labour_hours_fall_back_to_assignments,
test_evm_series_one_point_per_update_against_one_baseline,
test_forecast_curve_starts_at_ac_and_ends_at_eac.

## 4. Progress (analysis/progress.py, store.py)

**PPC** (`committed`, `ppc_series`), for each consecutive pair W-1 → W of the series
(sorted by data date, then source name):
committed = activities of W-1 that are not complete, not LOE (milestones included by
default) with `finish` (W-1 Start/Finish column) `< data date of W`, and still present in
W; completed = those complete in W; `PPC = 100 × completed / committed`, none when
committed = 0. Activities deleted in W are listed (`status_now = deleted`) and left out
of both counts. Pinned by test_ppc_counts_only_commitments_still_in_the_update,
test_ppc_series_one_row_per_week.

**Progress delta** (`progress_delta(prev, cur, baseline)`), per activity of either update:

| Column | Formula |
|---|---|
| `pct_prev`, `pct_now` | `pct_complete` in W-1 / W; 0 when absent |
| `pct_delta` | `round(pct_now − pct_prev, 2)` (points) |
| `labor_budget_hr` | without baseline: W's value, W-1's for an activity deleted in W; with baseline: `ev_labor_hr` (0 if not in the baseline) |
| `earned_hr_week` | without baseline: `labor_budget_hr × pct_delta / 100`; with baseline: `ev_labor_hr × (Performance %(W) − Performance %(W-1)) / 100`, absent = 0, so the column sums to `EV(W) − EV(W-1)` |
| `actual_hr_week` | `labor_actual_hr(W) − labor_actual_hr(W-1)`, absent = 0 |
| `new`, `deleted` | not in W-1 / not in W (`status = deleted`) |

A deleted activity contributes `−pct_prev` points and negative earned hours. Pinned by
test_progress_delta_weighted_by_hours, test_progress_delta_with_a_baseline_adds_up_to_ev,
test_progress_delta_gives_back_the_hours_of_a_deleted_activity.

**Roll-up** (`rollup_delta`, by `wbs_l1` default): sums of `labor_budget_hr`,
`earned_hr_week`, `actual_hr_week`; `activities_progressed` = count of `pct_delta > 0`;
`progress_pts = 100 × earned_hr_week / budget_hr` (NaN when budget 0); a `Project` row of
totals.

**MTA** (`milestone_trend`, `milestone_slips`): per milestone (any activity flagged
milestone in any update) and update, `forecast` = `start` for start milestones, `finish`
otherwise. `slip_wd = round(working_days(first forecast, latest forecast), 1)` and
`last_week_wd` = same between the last two updates (0 with one update), on the
milestone's calendar as of the latest update. Pinned by test_milestone_slip_in_working_days.

**Finish shift** (`SnapshotStore.summary.finish_shift_wd`):
`round(working_days(previous finish_date, this finish_date), 1)` on this (newer)
update's project calendar; none for the first update or a missing finish. Other
`summary` columns: counts of activities, complete, in progress (started and not
complete), not started, critical, relationships; `pct_complete_count = round(100 ×
complete / activities, 1)`. Pinned by test_store.py::test_summary_tracks_slip.

**WBS roll-up** (analysis/wbs.py `rollup`), per WBS node over every activity below it:
`pct_complete = Σ labor_budget_hr × pct_complete / Σ labor_budget_hr` when the node's
budget hours > 0 (`weight = hours`), else `Σ original_d × pct_complete / Σ original_d`
(`weight = duration`); `critical` = not complete and critical; `min_float_d`;
`start = min start`, `finish = max finish`, `bl_finish = max bl_finish`;
`finish_var_wd = round(working_days(bl_finish, finish), 1)` on the project calendar;
`budget_hr`, `actual_hr`, `remaining_hr` sums. Pinned by
test_wbs_rollup_hours_weighting_and_tree.

## 5. Changelog (analysis/changelog.py)

Two updates of one project, activities matched by `task_code` (first row per code).
`before` / `after` are display strings; `delta` is numeric with `unit`.

| Category | Change | Condition | Delta (unit) |
|---|---|---|---|
| Project | data date | always | `working_days(old, new)` on the new update's project calendar (wd) |
| Project | forecast finish | always | same, on `finish_date` (wd) |
| Project | activities, relationships | always | new count − old count |
| Scope | added / deleted | code only in new / only in old | — |
| Activities | renamed, moved to another WBS, type changed, calendar changed | `task_name`, `wbs_code`, `type`, `clndr_id` differ (NaN = NaN) | — |
| Durations | original duration changed | `original_d` differs | `new − old` (wd, each on its own activity calendar) |
| Durations | remaining duration increased | `remaining_d(new) > remaining_d(old) + 1e-9` and not complete in new | `new − old` (wd) |
| Progress | started / finished / status reverted | `status` differs; reverted when the order Not started < In progress < Complete goes down | — |
| Progress | actual start / finish changed (retroactive) | both present and different | — |
| Progress | actual start / finish removed | present in old, blank in new | — |
| Progress | % complete | `round(pct(new) − pct(old), 2) != 0` | that difference (pts) |
| Dates | start moved / finish moved | not complete in new and `abs(round(working_days(old date, new date), 2)) > 0.005`, on the new update's activity calendar | that value (wd) |
| Float | total float changed | not complete in new and `abs(round(total_float_d(new) − total_float_d(old), 2)) > 0.005` | that difference (wd) |
| Float | became critical / no longer critical | `is_critical` false → true; true → false and not complete in new | — |
| Constraints | primary / secondary constraint added / removed / changed | `cstr_type` (`cstr_type2`) differs, or present and its date differs | — |
| Resources | budgeted labour hours changed | `round(labor_budget_hr(new) − old, 2) != 0` | that difference (h) |
| Resources | resource assigned / removed / budgeted units changed | per (activity in both updates, resource label): `TASKRSRC.target_qty` summed per resource appears / disappears / `round(new − old, 2) != 0` | units difference (units) |
| Relationships | added / deleted | (pred, succ) pair only in new / only in old | — |
| Relationships | type changed / lag changed | pair in both with a different set of (type, `lag_hr`): type changed when the set of types differs, else lag changed | — |

`summary(log)` counts rows per (category, change), Project rows excluded. Pinned by
test_changelog_finds_each_kind_of_change, test_changelog_relationships,
test_changelog_project_rows_and_summary, test_identical_files_have_no_changes,
test_changelog_lists_assignment_changes.

## 6. CPM output compared with P6 (analysis/cpm.py `compare_with_stored`, `compare_assignments`)

The engine recalculates early/late dates and floats as described in the module
docstring of `cpm.py` (forward and backward pass to the minute on each activity's
calendar; lag calendar, progressed-activity option, constraints, expected finish,
resource-dependent assignments, LOE, ALAP, Must Finish By, open-ends-critical option).

| Computed | Stored (`TASK`) | Identical when |
|---|---|---|
| `es` (`remaining_start` for in-progress activities) | `early_start_date` | same timestamp (`pd.Timestamp ==`) |
| `ef` | `early_end_date` | same timestamp |
| `ls` | `late_start_date` | same timestamp |
| `lf` | `late_end_date` | same timestamp |
| `tf_hr` | `total_float_hr_cnt` | `round(computed − stored, 2) == 0` |
| `ff_hr` | `free_float_hr_cnt` | `round(computed − stored, 2) == 0` (compared; INT-01 leaves it out by default) |
| assignment `restart`, `reend`, `rem_late_start`, `rem_late_end` | `TASKRSRC.restart_date`, `reend_date`, `rem_late_start_date`, `rem_late_end_date` | same timestamp |

Rows: not complete, not LOE activities; `gap_hr` for dates = working hours from stored
to computed on the activity's calendar (0 with `agree = False` means the same working
minute shown at a different clock time). Pinned by test_cpm.py (see §2.4) and
`tests/test_p6_heldout.py`.

## 7. Known limits

Stated by the code or docs/backlog.md; nothing here is verified against P6 output.

- P6 populations are a reading of the P6 Professional 24 dialog help (101248), else of
  the EPPM report pages; no P6 Check Schedule report has been compared (backlog). Open
  readings: LOE kept in P6-01 (101248 is silent on LOE there); "remaining early finish" of a completed activity without baseline read as its
  actual finish in P6-12; a baseline activity whose finish is blank is never due in P6-13.
- 352 h assumes 8 h/day (p6.toml); P6 targets are the EPPM 25 help's dialog defaults,
  not read from a Professional 24 dialog.
- DECM readings not verified against the specification sheets: 06A205a counts LOE and
  ignores leads; 06A209a includes LOE; DCMA-11 keeps milestones, DCMA-14 drops them.
- CPLI takes the schedule's total float, i.e. P6's distance to the Must Finish By date;
  a contract finish kept elsewhere (a baseline, a contract milestone) is not read.
- `cpli` reads the float of the latest-finishing open non-LOE activity, which may differ
  from `finish_date` (max over all activities); `critical_path_test` excludes milestones
  from the delayed candidates, `cpli` does not.
- EV techniques "WBS milestones" and "resource curves" are not modelled: they fall back
  to activity % complete and are listed in `EvPoint.not_modelled` (evm.py).
- `pv_curve` and `forecast_curve` name a day and hold the cumulative at its end.
- WBS roll-up % complete mixes percent-complete types and is not a P6 field (wbs.py,
  backlog).
- CPM not modelled: resource leveling, multiple float paths, relationships to projects
  not in the file (cpm.py); resource-dependent work (77 % of its corpus values) and two
  Progress Override rules still differ from P6 23.12 on the held-out corpus (backlog).
