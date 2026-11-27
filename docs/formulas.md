# Formulas

Every number xerscope computes, as the code computes it. File and function names refer
to `src/xerscope/`; test names to `tests/`. Where this document and the code differ, the
code is right and this document is wrong.

## 1. Conventions

### 1.1 Inputs (xer/model.py `build_snapshot`)

| Quantity | Source | Notes |
|---|---|---|
| Data date | `PROJECT.last_recalc_date`; blank: `PROJECT.plan_start_date`; both blank: none | Rules that need it return n/a or error |
| Activity ID | `TASK.task_code` | `task_id` is used only to resolve links inside one file; an Activity ID repeated in the project keeps its first `TASK` row, the others are left out with their relationships, assignments and expenses (a warning) |
| Activities | `TASK` rows of the project with `task_type != TT_WBS` (`Snapshot.activities`) | WBS summary rows are excluded from every population and count |
| Relationships | `TASKPRED` rows of the project whose predecessor and successor both have a `TASK` row in the file | Others are dropped (a warning when the predecessor is not in another project); `is_external` = predecessor in another project; a predecessor that is a `TASK` row of another project of the file is named `[ext]{task_id}` in `pred_code` (as in `Snapshot.external_links`), so it is never taken for the local activity with the same Activity ID; `has_external_pred` / `has_external_succ` flag activities linked to other projects |
| Hours per day (`hours_per_day`) | `CALENDAR.day_hr_cnt` of the activity's calendar; blank, 0 or under a minute: 8 (`config.Settings.default_hours_per_day`); calendar not in the file: the project calendar's, else the file's first calendar's, else 8 (`fallback_hours_per_day`, a warning) | |
| Start / Finish (`start`, `finish`) | actual date, else `restart_date` / `reend_date`, else `early_start_date` / `early_end_date`, else `target_start_date` / `target_end_date` | P6's Start / Finish columns |
| Forecast finish (`finish_date`) | max `finish` over activities (WBS summary excluded) | `PROJECT.scd_end_date` is kept as `scheduled_finish` only |
| Total float (days) `total_float_d` | `total_float_hr_cnt / hours_per_day`; NaN when complete | `free_float_d` likewise |
| Remaining duration (days) `remaining_d` | `remain_drtn_hr_cnt / hours_per_day` | |
| Original duration (days) `original_d` | `target_drtn_hr_cnt / hours_per_day` | |
| Lag (hours) `lag_hr` | `TASKPRED.lag_hr_cnt`, blank = 0 | |
| Lag (days) `lag_d` | `lag_hr / hours_per_day` of the **predecessor's** calendar | Display only; rules use hours unless `unit = "days"` |
| Labour hours `labor_budget_hr / labor_actual_hr / labor_remaining_hr` | per activity and per column, `TASK.target_work_qty / act_work_qty / remain_work_qty`; a blank value takes the sum of `TASKRSRC.target_qty / (act_reg_qty + act_ot_qty) / remain_qty` over its assignments with `rsrc_type` in {RT_Labor, role, blank}; else 0 (`_labor_hours`; nonlabour quantities likewise from `*_equip_qty` and RT_Equip assignments) | `Snapshot.options["labor_source"]` = TASK, TASKRSRC, TASK+TASKRSRC or none |
| Has resource | activity has at least one `TASKRSRC` row (any type, roles included) | |
| Has expense | activity has at least one `PROJCOST` row | |

### 1.2 Status words (boolean columns on `activities`)

| Word | Definition | EXCLUDE key (your own standard, rules.py) |
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
| critical | not complete, not WBS summary, and: `PROJECT.critical_path_type == CT_DrivPath` → `driving_path_flag == Y`; else `critical_drtn_hr_cnt` present → `total_float_hr_cnt <= critical_drtn_hr_cnt`; else `total_float_d <= Settings.critical_float_days` (0) | LOE included, as P6 |

In your own standard, a rule's `exclude` list removes activities matching any listed key
(`rules.activities`, `rules.activities_funnel`). Link populations (`links`, built by `rules.link_funnel`,
also used by the explicit P6, DCMA and INTEGRITY relationship checks): `all`; `not_both_complete` = drop
links whose predecessor and successor are both complete; `succ_incomplete` = drop links whose
successor is complete; then one step per `exclude` key applied to the successor, and `exclude_loe`
drops links with a level of effort at either end. Links whose successor is a WBS summary are always dropped.

### 1.3 Percent complete (xer/model.py `percent_complete`)

By `TASK.complete_pct_type`: `CP_Drtn`: `(target_drtn_hr_cnt − remain_drtn_hr_cnt) / target_drtn_hr_cnt × 100`,
floored at 0, 100 once complete, undefined when original duration is 0;
`CP_Units`: `(act_work_qty + act_equip_qty) / (actual + remain_work_qty + remain_equip_qty) × 100`,
undefined when the total is 0; any other type: `phys_complete_pct`. Undefined values fall
back to `phys_complete_pct`, then to 100 if complete else 0. Clipped to [0, 100], not
rounded (EV and 06A505b read it; pages round for display). Pinned by `test_reference.py::test_percent_complete_matches_p6_export`,
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
- Every hours-to-days division (`_d` columns, `working_days`, the day thresholds of DCMA-08 and
  06A506c) goes through `calendar.hours_to_days`, rounded to 1e-6 day: P6 stores N days as
  N x `day_hr_cnt` in decimal hours, and 360.8 h / 8.2 is 44.00000000000001 in binary floating
  point, which a "greater than 44 working days" test would count.
- "wd" in this document = working days of the calendar named for that quantity.
  "Project calendar" = `PROJECT.clndr_id`, else the first calendar in the file, else the
  Monday–Friday 8 h default (`Snapshot.calendar()`).
- `Snapshot.work_hours` / `working_days` (row-wise) use each row's `clndr_id`; blank or
  unknown ids fall back to the project calendar; NaN where a date is missing.

**Which calendar measures a shift.** Three `Snapshot` methods, no other call site reads a
`WorkCalendar` for a shift: `project_working_days(a, b)` (project calendar),
`activity_working_days(clndr_id, a, b)` (one activity's calendar) and `working_days(clndr, a, b)`
(row-wise, the same on each row's calendar). The convention is xerscope's: Oracle's help for the
Variance columns (P6 help 47223) says "Finish minus BL Project Finish" and names no calendar, so no
Oracle text settles it. Project-level dates use the project calendar, an activity's dates its own
calendar; of two updates, the newer (changelog, store) or the latest (MTA, task panel) supplies
the calendar.

| Shift | Dates | Calendar | Pinned by (tests/test_shift_calendar.py) |
|---|---|---|---|
| `summary.finish_shift_wd`, `finish_shift_since_first` | forecast finish of the project | project, newer / latest update | test_store_finish_shift_is_on_the_project_calendar, test_finish_shift_since_first_is_on_the_project_calendar |
| changelog Project rows | status date, forecast finish | project, new update | test_changelog_project_rows_are_on_the_project_calendar |
| WBS `finish_variance_wd` | a node's finish against its baseline finish (a node has no calendar) | project | test_wbs_finish_variance_is_on_the_project_calendar |
| DCMA-13 CPL and TF | data date to the measured end (§2.6); TF hours, or the end's margin to its baseline finish | project (`hours_per_day` of the project) | test_dcma_13_length_and_float_are_on_the_project_calendar |
| changelog Dates rows | an activity's start, finish | activity, new update | test_changelog_date_moves_are_on_the_activity_calendar |
| Gantt `shift_wd` | an activity's finish against the comparison update | activity, displayed update | test_gantt_finish_shift_is_on_the_activity_calendar |
| MTA `slip_wd`, `last_week_wd` | a milestone's forecast, start or finish | the milestone's own, latest update | test_milestone_slip_is_on_the_milestone_calendar |
| Task panel "since first" (`activity_finish_shift`) | the activity's forecast finish | the activity's own, latest update | test_activity_page_slip_is_on_the_activity_calendar |
| P6-12 variance, DCMA-08 limit, 06A506c windows | an activity's dates and durations | activity (`hours_per_day`) | test_p6_12_variance_is_on_the_activity_calendar, test_dcma_08_limit_is_in_days_of_the_activity_calendar, test_06a506c_windows_are_in_days_of_the_activity_calendar |

The critical path test measures its shift on the delayed activity's calendar (2.6). DCMA-13 takes
the finish driver's float on the project's `hours_per_day`, and its margin without a Must Finish By
in project working days (PAM 200.1 §3.1.2.3 gives "days" without a calendar): a convention that does
not follow the end activity's own calendar.

### 1.5 Targets and statuses (analysis/standards.py, analysis/checks.py)

| Target text | Comparator | Threshold | Metric unit |
|---|---|---|---|
| `< 5%`, `<= 5%`, `> 90%`, `>= 90%` | `<`, `<=`, `>`, `>=` (also `==`) | 5, 90 | `%` only |
| `<= 0`, `<= 10` | `<=` | 0, 10 | `count` |
| `>= 0.95` | `>=` | 0.95 | `ratio` |
| `pass` | `==` | 1.0 | `pass/fail` (rule value 1.0 = passed, 0.0 = failed) |
| `info` or absent | none | none | any |

A metric's parameters are checked on load against the rule's signature (`Rule.validate`): unknown name, wrong choice, non-number, non-flag, string instead of list; a metric may
swap `%` and `count`, no other unit. Value per unit (`checks.run_metric`): `%`: the rule's `value` if it set one (the relationship-type
rules: `relationship_type`, `p6_07_relationship_types`, `dcma_04_relationship_types`), else `100 × numerator / denominator`, none when the denominator
is 0; `count`: `numerator`; `ratio`, `pass/fail`: the rule's `value`.

Sets (`CheckResult.checked`, `counted`): every rule that returns a denominator also returns its rows (`checked`); `counted` holds the numerator's rows when they are not the listed ones
(the share of FS links, BEI's completed activities). `tests/test_audit.py` holds every built-in
metric to `len(checked) == denominator`, numerator rows = numerator, listed rows within `checked`.

Steps (`CheckResult.funnel`, every check of the four standards that has a row population): the population as the rule builds it, one filter at a
time, each with a label, the text it follows (`populations.STEP_SOURCES`: 101248, 46278, 46282, Ten Six, R1,
model, PAM 200.1, DECM 8.0, AACE 29R-03, xerscope, ask) and the rows it removed. `tests/test_sheets.py` holds, for every metric, the funnel's last step to the denominator and, for P6, the rule's steps, the
sheet's numbered population, the metric's `source` in p6.toml and the docstring's `Excludes:`
line to the same list.

Status: `n/a` when the metric needs a baseline and none is loaded, or the value is none
(empty population, missing data date or previous update); `error` when the rule raised
(the note carries the exception); `info` when the target is `info` or the rule reports its value
for review (`RuleOutput.status`, DCMA-13 on the planned dates baseline); else `pass` if
`comparator(round(value, 6), threshold)` holds, else `fail`. So `<= 0%` and `<= 0` pass
only when the numerator is 0.

### 1.6 Standard score (analysis/checks.py `standard_score`)

`score = criteria in pass / (criteria in pass + criteria in fail)`, with the number of fail and their
ids: card `67 %`, detail `3 evaluated · 1 fail: T-02` (`StandardScore.value`, `.detail`). A criterion is one metric, or the metrics that share an
`item` (one line of the source written as several metrics, e.g. a band as two bounds): it fails when
one of them fails, passes when none fails and one passes, and is not evaluated otherwise; a failed
item is listed with the metrics that failed it (`9 (CA-09b)`). Checks in `info`, `n/a` or `error`
are not evaluated and appear in neither term; a standard with no evaluated criterion has no score
(`–`, n/a). Built-in: P6-10a and P6-10b share `item = "P6-10"`, one check of the Check Schedule
dialog (101248, Invalid Progress Dates) that P6 Professional 26.8 prints on two lines, so the P6
score counts 17 criteria for 18 metrics; the other built-in standards have one metric per item of
their source. The function reads the
`status` of results already computed (§1.5) and recomputes no check: the app takes them from
`app/cache.py` `metric_result`, the per-session entry Schedule health, Audit and Earned value share, so a
score shown on Overview or Schedule health costs no calculation once Schedule health has run.

This is a xerscope convention. No DCMA, Oracle P6 or Acumen source defines a global score for a
schedule. Ten Six, "An Introduction to the DCMA 14-Point Assessment Guidelines" (Usage), reads the
14-Point as "not necessarily a pass/fail quality criterion. Exceeding assessment thresholds does not
necessarily indicate schedule failure": a check over its target is a flag to explain, so the
score summarises how many checks need reading, not whether the schedule is acceptable. The share
depends on which checks the standard evaluates (INTEGRITY: 4 of its 8 checks have a target, the others
are `info`), so scores of two standards, or of one standard with and without a baseline (checks that
need one are `n/a`), do not compare.

Overview shows one card per standard (built-in, `XERSCOPE_STANDARDS` folder, uploaded in the session)
for the latest update once its results are in the session's cache; otherwise "not computed yet" and a
"Compute scores" button, or the scores computed in a background job (`cache.score_job`) that fills each
card as its standard finishes. The four built-in standards take several seconds on a ~4,000-activity
export (CPM recalculation, critical path tests), too long to run in the page's own pass.

Tests: `tests/test_scores.py` (hand-made schedule: 2 pass, 1 fail, 1 n/a gives 2/3 and the failed id;
a standard with no evaluated check has no score; items: pass + fail is one fail naming the metric,
pass + n/a is one pass, info alone is not evaluated; P6-10a/b are one item); `tests/test_app_cache.py` (Overview cards = score of a
fresh calculation = Schedule health card; each metric computed once whichever page asks first).

## 2. Standards

Column key: **Population** = rows the rule examines (denominator unless stated);
**Found** = rows counted in the numerator. All activity populations exclude WBS summary
rows. "Reference" = `test_reference.py::test_dcma_matches_stated_result[<id>]` against
`tests/reference/expected.py` (the pamphlet's counts on xerlock's sample file; xerlock's own
value is noted where it differs).

### 2.1 P6 Check Schedule (`standards/p6.toml`, standard id `P6`)

Thresholds in hours as P6 compares them: `x` is the `limit_hours` parameter of P6-04, P6-05
and P6-06 in `p6.toml` (the dialog's "x", 352 h). DCMA-06, DCMA-08 and DECM 06A211a take
`limit_days` (44 working days of the activity's calendar) the same way. Each threshold is a parameter
of its own check with a default equal to the standard file's value (`LARGE_HOURS` in `p6/check_schedule.py`,
`DCMA_HIGH_DAYS` and `DCMA_SLIP_DAYS` in `dcma/fourteen_point.py`, `HIGH_FLOAT_DAYS`, `SLIP_DAYS`,
`STATUS_PERIOD_DAYS`, `RIDING_WINDOW_WD`, `RIDING_REMAINING_TOLERANCE_WD` in `decm/schedule_metrics.py`);
`test_threshold_defaults_of_the_rules_equal_the_standard_files` keeps the two equal. P6's 352 h is not
derived from DCMA's 44 days. Targets are the Check Schedule dialog defaults as the P6 EPPM 25 help
states them (strict comparisons: "less than 5%", "greater than 90%"), except BEI: the help
says "0.95 or greater", `p6.toml` holds `> 0.95` as report R1 prints it, so exactly 0.95 fails.
P6-15 to P6-17 are not in that help: `p6.toml` sets `< 2%`, `<= 0%` and `<= 0%`.
The dialog's own values must be copied in for pass/fail to match a report.
Constraint sets follow the P6 Professional help: hard = Mandatory Start, Start On,
Mandatory Finish, Finish On; soft = On or Before / On or After, As Late As Possible.

| Id | Name | Population | Found | Unit | Target | Source (TOML) | Tests (test_rules.py) |
|---|---|---|---|---|---|---|---|
| P6-01 | Logic | activities not complete | no predecessor or no successor among the project's own links; an external link counts as a link; started activities pass the predecessor side; start and finish milestones are counted | % | < 5% | 101248: completed and WBS summary activities not included; started activities need no predecessor (101248 also exempts start milestones; a P6 Professional 26.8 report lists a not-started one, as the r22.12 report analysed by Ten Six lists its Notice to Proceed: the reports win); nothing exempts a finish milestone (same reports); external links pass (46291) | test_p6_logic_exemptions, test_p6_logic_flags_the_finish_milestone_without_successor, test_external_successor_passes_p6_logic, test_start_milestone_without_successor_is_an_open_end_for_p6, test_link_to_an_activity_not_in_the_file_is_dropped; test_p6_checksched: test_check_schedule_lists_match_the_p6_26_report |
| P6-02 | Hard Constraints | not complete, not LOE | `cstr_type` or `cstr_type2` in {CS_MANDSTART, CS_MSO, CS_MANDFIN, CS_MEO}; a start constraint (MSO, MSOA, MSOB, MANDSTART) on a started activity does not count | % | < 1% | 46286: WBS summary, actual-finish and LOE removed; start constraints ignored once started | test_constraint_sets_differ_between_p6_and_dcma |
| P6-03 | Soft Constraints | not complete, not LOE | `cstr_type` or `cstr_type2` in {CS_MSOB, CS_MSOA, CS_MEOB, CS_MEOA, CS_ALAP}, same started exemption | % | < 5% | 46285: Start on or before / on or after, Finish on or before / on or after, As late as possible | test_constraint_sets_differ_between_p6_and_dcma |
| P6-04 | Large Durations | not complete, not LOE, not milestone | `remain_drtn_hr_cnt > x` | % | < 5% | 101248: completed, WBS summary and LOE not included; milestones also out (Ten Six P6 r22.12 report, EPPM 46282) | test_large_duration_remaining_vs_original |
| P6-05 | Long Lags | links `not_both_complete` | `lag_hr > x` | % | < 5% | 46288: links between two actual-finished activities removed | test_lead_long_lag_and_fs_share |
| P6-06 | Large Float | not complete, not LOE | `total_float_hr_cnt > x` | % | < 1% | 46284: WBS summary, actual-finish and LOE removed | test_float_threshold_in_hours_vs_working_days |
| P6-07 | Relationship Types | links `not_both_complete` | value = `100 × FS links / links`; listed: non-FS links | % | > 90% | 46287: actual = share of FS links in the subset | rule: test_lead_long_lag_and_fs_share (DCMA-04); population: test_link_populations_differ |
| P6-08 | Positive Lags | links `not_both_complete` | `lag_hr > 0` | % | < 5% | 46289 | test_link_populations_differ, test_link_to_an_activity_not_in_the_file_is_dropped |
| P6-09 | Negative Lags | links `not_both_complete` | `lag_hr < 0` | % | < 1% | 46290: links between two actual-finished activities removed | rule: test_lead_long_lag_and_fs_share (DCMA-02) |
| P6-10a | Invalid Progress Before Data Date | not LOE, not complete before the data date | not complete and forecast start < data date (remaining early start once started; `in_progress = "start"`), forecast = `restart_date` else `early_start_date` | % | < 1% | 101248 (P6 Professional 24 help, Check Schedule dialog): not started, start before the data date; in progress, remaining early start before it; a line of its own in a P6 Professional 26.8 report | test_invalid_progress_dates; test_p6_checksched: test_check_schedule_counts_match_the_p6_26_report |
| P6-10b | Invalid Progress After Data Date | idem | `act_start_date > data date` or `act_end_date > data date` | % | < 1% | 101248: in progress, actual start after the data date; completed, actual finish after it; a line of its own in a P6 Professional 26.8 report | test_invalid_progress_dates; test_p6_checksched: test_check_schedule_counts_match_the_p6_26_report |
| P6-11 | Resource / Cost | not milestone, not LOE (complete stay in) | no `TASKRSRC` row and no `PROJCOST` row | % | < 1% | 46279: WBS summary, milestones and LOE removed (completed activities stay in); a role assignment counts | test_resource_or_expense |
| P6-12 | Late Activities | not complete, not milestone, not LOE | `work_hours(bl_finish → finish) > 0` on the activity's current calendar, `bl_finish` else `target_end_date`; `finish_variance_wd` = `−round(that / hours_per_day, 2)` (P6's sign: late is negative) | % | < 5% | 101248 (P6 Professional 24 help, Check Schedule dialog): milestones, WBS summary and LOE not included; completed activities out as report R1 shows (same population as P6-04); no baseline counterpart = late when the remaining early finish is later than the planned finish; 46278: variance in working time | test_missed_tasks_and_late_activities, test_late_activities_use_working_time; test_p6_check_schedule: test_p6_12_milestone_loe_wbs_and_completed_are_excluded |
| P6-13 | BEI | not LOE, not milestone; numerator: complete activities of the snapshot; denominator: every activity of the baseline, whatever its `bl_finish` | value = complete / baseline activities; listed: `bl_finish <= data date` and not complete | ratio | > 0.95 (R1) | report R1 overrides 101248's "baseline activities finishing before the data date" | test_bei_p6_counts_due_in_the_baseline_dcma_in_the_schedule, test_baseline_metrics_are_na_without_baseline; test_p6_check_schedule: test_p6_13_bei_is_completed_over_all_baseline_activities |
| P6-14 | Negative Float | not complete, not LOE | `total_float_hr_cnt < 0` | % | < 1% | 46283: WBS summary, actual-finish and LOE removed | test_float_threshold_in_hours_vs_working_days |
| P6-15 | Out of Sequence | all activities (denominator); started activities examined | started, with an FS predecessor not complete or an SS predecessor not started (`populations.predecessors_ahead`); listed one row per (activity, predecessor), counted once per activity | % | < 2% | R1: pairs listed, counted once per activity; FF and SF unresolved | test_p6_check_schedule: test_p6_15_out_of_sequence_is_progress_while_a_predecessor_is_still_open |
| P6-16 | Dangling Start Activities | all activities (denominator); not complete, not milestone examined, not started either with `ignore_in_progress = true` (`p6.toml`) | has a predecessor, none FS or SS (no predecessor at all is P6-01's) | % | <= 0% | R1, 'Ignore In Progress Activities' checked (113174 documents no default) | test_p6_check_schedule: test_p6_16_dangling_start_ignores_in_progress_and_activities_without_predecessor, test_p6_16_and_17_leave_milestones_out |
| P6-17 | Dangling Finish Activities | all activities (denominator); not complete, not milestone examined, less those whose primary or secondary constraint the options `ignore_soft_constraints` / `ignore_hard_constraints` name (both false in `p6.toml`) | has a successor, none FS or FF (no successor at all is P6-01's) | % | <= 0% | R1; 113174 for the two options (soft: Start On, Start On or After / Before, Finish On, Finish On or After / Before, As Late As Possible; hard: Mandatory Start, Mandatory Finish), no default documented | test_p6_check_schedule: test_p6_17_dangling_finish_needs_a_successor_that_is_not_driven, test_p6_16_and_17_leave_milestones_out |

Note: the `source` strings are Oracle help page ids (101248: the P6 Professional 24
Check Schedule dialog; 462xx: P6 EPPM Schedule Check Report sections) as read from those
pages by the TOML author. P6-12, P6-13 and P6-15 to P6-17 follow report R1
(docs/standards.md, Sources) where it departs from or goes beyond the help; R1 is not in
the repository (real schedule), so the tests rebuild each behaviour by hand
(`tests/test_p6_check_schedule.py`).

### 2.2 DCMA DECM v8.0, Guideline 6 (`standards/decm.toml`, standard id `DECM`)

"Incomplete" = not complete (started activities included). Status date = data date;
"on or before the status date" (06A506b) includes a forecast on the data date itself.

| Id | Name | Population | Found | Unit | Target | Source (TOML) | Tests (test_rules.py) |
|---|---|---|---|---|---|---|---|
| 06A204b | Dangling logic | incomplete, not LOE | open start: milestone with no predecessor; task with no FS/SS predecessor. Open finish: milestone with no successor; task with no FS/FF successor. A link from or to another project counts, by its type. Exempt: `bl_start == min bl_start` of the whole baseline (start side), `bl_finish == max bl_finish` (finish side), ties included; without a baseline, or when the update is its own baseline, `target_start_date` / `target_end_date` over all activities of the file | % | <= 0% | 06A204b: open start = only FF/SF or no predecessor (milestone: none); open finish = only SS/SF or no successor (milestone: none); earliest baseline start / latest baseline finish exempt | test_decm_dangling_logic, test_decm_milestone_needs_only_one_link_per_side, test_decm_project_start_exemption_does_not_move_once_work_is_done, test_decm_open_ends_on_a_progressed_schedule |
| 06A205a | Lags | incomplete (LOE kept) | at least one predecessor link with `lag_hr > 0` (positive lags only) | % | <= 10% | 06A205a: X/Y <= 10%; the sheet does not say whether LOE count or whether leads (negative lags) do: LOE kept, positive lags only | test_decm_lags_summary_logic_and_loe |
| 06A208a | Summary tasks with logic | WBS summary rows (`tasks`) | appears as predecessor or successor of any link | count | <= 0 | 06A208a: X = 0 | test_decm_lags_summary_logic_and_loe |
| 06A209a | Hard constraints | not complete (LOE included) | `cstr_type` or `cstr_type2` in {CS_MANDSTART, CS_MANDFIN}; no started exemption | % | <= 0% | 06A209a: X/Y = 0%; Primavera P6 hard constraints = Mandatory Start, Mandatory Finish; the sheet does not say whether LOE count: kept | rule only: test_constraint_sets_differ_between_p6_and_dcma |
| 06A210a | LOE with discrete successors | incomplete LOE | has a successor in the file that is not LOE | % | <= 0% | 06A210a: X = 0 | test_decm_lags_summary_logic_and_loe |
| 06A211a | High total float | not complete, not LOE | `total_float_d > 44` | % | info | 06A211a: the population DECM samples; X/Y <= 20% of the sample with inadequate rationale | rule only: test_float_threshold_in_hours_vs_working_days (DCMA-06) |
| 06A212a | Out of sequence | links whose predecessor is incomplete (LOE included); the successor may be complete | using `start` / `finish` (actual, else forecast): FS `S.start < P.finish`; SS `S.start < P.start`; FF `S.finish < P.finish`; SF `S.finish < P.start`; lags ignored | count | <= 0 | 06A212a: X = 0; FS (S.AS\|S.FS) < P.FF, SS (S.AS\|S.FS) < P.FS, FF (S.AF\|S.FF) < P.FF, SF (S.AF\|S.FF) < P.FS | test_decm_out_of_sequence_counts_relationships, test_decm_out_of_sequence_ignores_a_completed_predecessor, test_decm_06a212a_keeps_a_level_of_effort_predecessor |
| 06A401a | Critical path test | see §2.6 | +600 wd | pass/fail | pass | 06A401a: the schedule's critical path is the longest path (constraint method) | rule: test_critical_path_test_passes_on_clean_logic, test_critical_path_test_fails_when_a_mandatory_date_absorbs_the_delay |
| 06A501a | Missing baseline dates | all activities | no `bl_start` or no `bl_finish` (not in the baseline, or baseline dates blank) | % | <= 5% | 06A501a: X/Y <= 5%, summaries excluded | test_decm_baseline_and_actual_dates |
| 06A504a | Actual starts changed | activities with an actual start in this update, plus those present in both updates with one in the earlier update; earlier = the latest update whose data date is <= this one − 28 days (`status_period_days`) | present in both updates with an earlier actual start and a different (or now blank) actual start | % | <= 10% | 06A504a: X/Y <= 10%, Y = tasks with an actual start; compared with the update one status period (28 days) earlier | test_decm_actuals_changed_needs_the_previous_update, test_actuals_changed_counts_a_removed_date_on_both_sides |
| 06A504b | Actual finishes changed | same, on actual finish | same | % | <= 10% | 06A504b: X/Y <= 10%, Y = tasks with an actual finish; compared with the update one status period (28 days) earlier | test_decm_actuals_changed_needs_the_previous_update |
| 06A505a | In progress without actual start | `pct_complete > 0` or started (LOE included) | no `act_start_date` | % | <= 5% | 06A505a: X/Y <= 5% | test_decm_baseline_and_actual_dates |
| 06A505b | Complete without actual finish | `pct_complete >= 100` or complete | no `act_end_date` | % | <= 5% | 06A505b: X/Y <= 5% | test_decm_100_percent_is_100_percent |
| 06A506a | Actual dates after the status date | denominator: activities with an actual start (all activities examined) | `act_start_date > data date` or `act_end_date > data date` | % | <= 5% | 06A506a: X/Y <= 5%, Y = tasks with an actual start | test_decm_baseline_and_actual_dates |
| 06A506b | Forecast dates before the status date | not complete (LOE included) | not started and forecast start <= data date, or forecast finish <= data date (`forecast_before`, `include_data_date = True`) | count | <= 0 | 06A506b: X = 0, forecast on or before the status date (v8.0 block 6; the data date is the status date) | test_decm_06a506b_counts_incomplete_tasks_only; rule: test_invalid_progress_dates |
| 06A506c | Riding the status date | incomplete, not LOE, present in the latest update whose data date is <= this data date − 28 days | not started in both and `0 <= work_hours(data date → start)` with `hours_to_days(that) <= 3` in both (each on its own data date and calendar); or started in both and `abs(remaining_d now − remaining_d then) <= 2` | % | <= 1% | 06A506c: X/Y <= 1%; start within 3 wd of the status date in both updates, or remaining duration within +/- 2 wd | test_decm_riding_the_status_date, test_decm_riding_the_status_date_started_work |

### 2.3 DCMA 14-Point (`standards/dcma.toml`, standard id `DCMA`)

Authority: DCMA-EA PAM 200.1 (Oct 2012) section 4, 3.1.2.3, 3.1.2.4; each metric's `source`
in the TOML cites its section. xerlock's published result is a comparison
(`tests/reference/expected.py` notes the differences). Lag thresholds are in hours;
float and duration thresholds in working days of the activity's calendar.

| Id | Name | Population | Found | Unit | Target | Tests |
|---|---|---|---|---|---|---|
| DCMA-01 | Logic | not complete, not LOE, not milestone (PAM 200.1 §4.0) | no predecessor or no successor (external links count); no project start/finish exemption, no dangling case (§4.1) | % | <= 5% | test_rules: test_dcma_01_follows_pam_200_1, test_missing_logic_keeps_exemptions_and_dangling_for_custom_standards; Reference (xerlock 2, pamphlet 0) |
| DCMA-02 | Leads | links `succ_incomplete`, successor not LOE, not milestone (PAM 200.1 §4.0) | `lag_hr < 0` | count | <= 0 | test_lead_long_lag_and_fs_share; Reference |
| DCMA-03 | Lags | links `succ_incomplete`, successor not LOE, not milestone (PAM 200.1 §4.0) | `lag_hr > 0` | % | <= 5% | test_link_populations_differ; Reference |
| DCMA-04 | Relationship types | links `succ_incomplete`, successor not LOE, not milestone (PAM 200.1 §4.0) | value = `100 × FS / links` | % | >= 90% | test_lead_long_lag_and_fs_share; Reference |
| DCMA-05 | Hard constraints | not complete, not LOE, not milestone (PAM 200.1 §4.0, §4.5) | `cstr_type` or `cstr_type2` in {CS_MSO, CS_MSOB, CS_MEO, CS_MEOB, CS_MANDSTART, CS_MANDFIN}; no started exemption | % | <= 5% | test_constraint_sets_differ_between_p6_and_dcma; Reference (xerlock 2, pamphlet 1) |
| DCMA-06 | High float | not complete, not LOE, not milestone (PAM 200.1 §4.0, §4.6) | `total_float_d > 44` | % | <= 5% | test_float_threshold_in_hours_vs_working_days; Reference |
| DCMA-07 | Negative float | not complete, not LOE, not milestone (PAM 200.1 §4.0, §4.7) | `total_float_d < 0` | count | <= 0 | Reference |
| DCMA-08 | High duration | not complete, not LOE, not milestone | baseline duration (`bl_duration_hr` / the activity's `hours_per_day`) > 44; n/a without a baseline; an activity absent from the baseline is not flagged (PAM 200.1 §4.8) | % | <= 5% | test_dcma_08_uses_the_baseline_duration_not_the_re_estimated_one, test_large_duration_remaining_vs_original; Reference |
| DCMA-09 | Invalid dates | not complete, not LOE, not milestone (PAM 200.1 §4.0) | not started and forecast start before the data date, or forecast finish before it, or actual start or finish after it; compared by calendar day (`date_grain = "day"` in dcma.toml; the rule's default `"timestamp"` is P6's reading) | count | <= 0 | test_dcma_09_follows_pam_200_1, test_dcma_09_compares_dates_by_day_p6_by_timestamp, test_invalid_progress_dates; Reference |
| DCMA-10 | Resources | not complete, not LOE, not milestone, `target_drtn_hr_cnt > 0` | no `TASKRSRC` row and no `PROJCOST` row; n/a when the project has no assignment and no activity with `labor_budget_hr > 0` (labour hours without assignments still fail, with a note) | % | <= 0% (PAM 200.1 §4.10) | test_resource_or_expense, test_dcma_10_is_na_for_a_project_without_resource_assignment, test_dcma_10_labour_hours_without_assignment_still_fail_with_a_note |
| DCMA-11 | Missed tasks | not LOE, not milestone; due = `bl_start` and `bl_finish` present and `bl_finish <= data date` by calendar day (`date_grain = "day"`; completed stay in) | `date(finish) > date(bl_finish)`, or `work_hours(bl_finish → finish) > 0` on the activity's calendar (the pamphlet's two readings joined by "or"), finish = actual else forecast | % | <= 5% | test_dcma_11_follows_pam_200_1 (PAM 200.1 §4.11, §4.0), test_missed_tasks_and_late_activities; Reference (xerlock 4, pamphlet 3) |
| DCMA-12 | Critical path test | see §2.6 | +600 wd (`slip_days`; xerscope's choice, PAM 200.1 §4.12 and DECM 06A401a give none) | pass/fail | pass | test_rules: test_critical_path_test_passes_on_clean_logic, test_critical_path_test_fails_when_a_mandatory_date_absorbs_the_delay and the other `test_critical_path_test_*`; test_reference: test_critical_path_test_delays_the_same_activity_as_xerlock; test_cpm: test_critical_path_test_shift_in_working_days; Reference |
| DCMA-13 | CPLI | see §2.6 | `(CPL + TF) / CPL` (PAM 200.1 §3.1.2.3; without a Must Finish By date TF = margin of the last open finish milestone to its baseline finish; n/a without a baseline; with the planned dates baseline the value is reported as `info`, not judged: a milestone's planned finish follows its early finish, margin 0, Oracle 47222) | ratio | >= 0.95 | test_cpli_uses_the_finish_float, test_cpli_is_na_without_must_finish_by_or_baseline, test_cpli_without_must_finish_by_uses_the_margin_to_the_baseline_finish_of_the_end_milestone, test_cpli_is_reported_for_review_with_the_planned_dates_baseline, test_calendar_holiday_counts_in_cpl; test_reference: test_cpl_matches_xerlock_hand_calculation; Reference |
| DCMA-14 | BEI | not LOE, not milestone, `target_drtn_hr_cnt > 0` (step 1); due = `bl_finish <= data date` by calendar day (no baseline finish = due, PAM 200.1 §3.1.2.4) | value = complete with an actual finish on or before the data date (by day, step 5) / due | ratio | >= 0.95 | test_bei_p6_counts_due_in_the_baseline_dcma_in_the_schedule, test_dcma_14_counts_completed_by_the_status_date_only, test_dcma_14_leaves_out_zero_duration_tasks_and_says_so |

### 2.4 Integrity (`standards/integrity.toml`, standard id `INTEGRITY`)

Source string: "xerscope: analysis/cpm.py, validated against P6-scheduled exports; Oracle P6 EPPM 26 help, Schedule Project Log". INT-02 and INT-04..08 mirror the log P6 writes at each F9 (section per check in `docs/standards.md`).

| Id | Name | Population | Found | Unit | Target | Tests |
|---|---|---|---|---|---|---|
| INT-01 | Schedule recalculated | not complete, not LOE, with at least one stored value among `early_start_date`, `early_end_date`, `late_start_date`, `late_end_date`, `total_float_hr_cnt` | at least one of those fields disagrees with the recalculation (§6); the note counts values, the ratio counts activities, and gives the latest early finish (stored `finish_date`, recalculated) and the activities with `external_early_start_date` or `external_late_end_date` | % | <= 0% | test_rules: test_recalculated_flags_stale_dates, test_recalculated_note_gives_the_latest_early_finish_and_external_dates; test_cpm: test_recalculation_reproduces_the_stored_dates_to_the_minute |
| INT-02 | Out of sequence activities | started activities (LOE included) | has an FS predecessor not complete, or an SS predecessor not started, at the data date (`populations.predecessors_ahead`, shared with P6-15) | count (value = found; denominator = started) | info | test_out_of_sequence_progress_is_listed, test_out_of_sequence_follows_the_status_at_the_data_date |
| INT-03 | Assignments recalculated | `TASKRSRC` rows the recalculation schedules, with a stored `restart_date`, `reend_date`, `rem_late_start_date` or `rem_late_end_date` | at least one of those dates differs from the recalculation (exact timestamp) | % | <= 0% | test_rules: test_assignment_dates_integrity; test_cpm: test_assignment_dates_reproduce_p6 |
| INT-04 | Relationship loops | every activity | lies on a logic loop (`cpm.loop_members`): a strongly connected component of more than one activity, read from the links alone on the network the passes schedule (non-LOE activities, links of a known type between two of them), the activities the engine names when it refuses a loop (`CycleError.members`) | count | <= 0 | test_relationship_loop_lists_the_activities_on_the_loop |
| INT-05 | Without predecessors or successors | every activity | no relationship into it (in the project or from another project), or none out of it | count (denominator = activities) | info | test_log_lists_activities_without_predecessors_or_successors_unfiltered |
| INT-06 | Actual date later than data date | every activity | `act_start_date > data date` or `act_end_date > data date` | count | <= 0 | test_log_lists_every_actual_date_after_the_data_date |
| INT-07 | Unsatisfied constraints | not complete, not LOE, with a dated constraint among Start on (or before, or after), Finish on (or before, or after), Mandatory start, Mandatory finish; start constraints of started activities excluded | recalculated `es` / `ef` not on the required side of `cstr_date` / `cstr_date2`, measured in working time of the activity's calendar (on or before: `<=`; on or after: `>=`; on, mandatory: `==`), so a date in non-working time is the start of the next working period. Unconfirmed against a P6 log | count (denominator = constrained) | info | test_unsatisfied_constraint_is_a_constraint_the_recalculated_date_misses |
| INT-08 | Unsatisfied relationships | relationships between two scheduled non-LOE activities of the file, lag >= 0, whose successor end (start for FS / SS, finish for FF / SF) has no actual date | FS: successor start < predecessor finish; SS: successor start < predecessor start; FF: successor finish < predecessor finish; SF: successor finish < predecessor start; successor at its recalculated early date, predecessor at its actual date else its recalculated early date; lag not added. A P6 Professional 26.8 log lists no out-of-sequence link here (test_p6_checksched.py) | count (denominator = relationships checked) | info | test_unsatisfied_relationship_is_a_link_the_successor_dates_break |

### 2.5 Rules for a company standard only (`analysis/rules.py`, listed by `xerscope standards --rules`)

| Rule | Population | Found | Unit | Source | Test |
|---|---|---|---|---|---|
| `on_data_date` | `exclude` applied (default: not complete) | `start` or `finish` (actual, else forecast, model columns) on the data date; `date_grain = "day"` compares calendar days, `"timestamp"` the stored instant | % | maintainer's reading of a company checklist (2026-11-19): "activities starting or finishing on the Data Date" | test_on_data_date_flags_a_start_or_finish_on_the_status_date_day |
| `float` with `op = "between"` | `exclude` applied | `value <= total float <= value_max`, both included | % | same checklist: "between 5 % and 15 % of the remaining activities have 0d-20d total float" (one metric per bound) | test_float_between_two_bounds_includes_both_bounds |
| `missing_logic` with `single_project_start` / `single_project_finish` | `exclude` applied | an open end passes only for the one task alone on the earliest start (latest finish); a shared date passes none | % | same checklist: "the first activity is the only activity permitted to not have a predecessor" | test_single_project_start_and_finish_pass_one_task_only |
| `relationship_type` with `zero_lag` / `listed` | links `links` | of the type and (``zero_lag``) lag = 0, blank = 0; the list shows the others or (``listed = "of_type"``) those counted | % | same checklist: "90 % of relationships are Finish-Start 0d lag", "Start-Finish not permitted" | test_relationship_type_with_zero_lag_counts_the_type_and_the_lag_together |
| `lag` with `unit = "project_pct"` | links `links` | `lag_hr` compared with `value / 100 × project_work_hours`, the working hours from `planned_start` to `finish_date` on the project's default calendar (`Snapshot.project_work_hours`); n/a without those dates | % | same checklist: "lag relationships that exceed 10 % of the project's Total Duration"; maintainer's decision (2026-11-19): total duration = working hours of the project, lag in hours as stored | test_lag_limit_as_a_share_of_the_project_working_hours |
| `no_resource` with `kind = "labour_units"` | `exclude` applied | `labor_budget_hr` is 0 or blank (and no expense when ``expenses_count``) | % | same checklist: "activities have resource labour units" | test_no_resource_can_require_budgeted_labour_units |

### 2.6 Critical path rules (dcma/fourteen_point.py `dcma_13_cpli`, `dcma_12_critical_path_test`; cpm.py `critical_path_test`)

**CPLI.** n/a without a data date or without open work. With a Must Finish By
(`PROJECT.plan_end_date`): `end` = the finish driver (`populations.finish_driver`), the not
complete, not LOE activity with the latest `finish` (milestones included; ties: a missing total
float first, else the least total float, then the lowest Activity ID); `CPL =
project_working_days(data date, end.finish)`; `TF = end.total_float_hr_cnt / project calendar
hours_per_day`, n/a when that float is blank (a missing float is not 0). Without a Must Finish
By (`_baseline_margin`): `end` = the open, not LOE finish milestone (`TT_FinMile`) with the latest
`finish` (ties: highest Activity ID); `CPL` as above to its stored finish; `TF =
project_working_days(end.finish, its bl_finish)`, negative when late; n/a without a baseline,
without such a milestone or without its baseline finish; with the planned dates baseline the
margin is 0 by construction (Oracle 47222) and the value is reported as `info`. `CPLI = (CPL +
TF) / CPL`; n/a when `CPL <= 0`. PAM 200.1 §3.1.2.3 measures the float of the completion
milestone "relative to the baselined finish date, when constrained"; reading the margin to the
baseline finish without a Must Finish By is xerscope's (UNRESOLVED in `dcma_13_cpli`).

**Critical path test** (`critical_path_output`: n/a without a data date or without open work).
`base` = recalculated schedule (cpm.py); a schedule error is a fail. Delayed activity = among
not complete, not LOE, not milestone activities on the recalculated longest path, the earliest
`remaining_start` (ties: lowest `task_code`); none → fail. Delay = `slip_days × hours_per_day`
of that activity (600 wd in dcma.toml and decm.toml), added to its remaining duration (its
expected finish dropped, `schedule(extra_hours=..., base=...)`); the schedule is recalculated.
Finish = max early finish over the end points (activities no non-LOE activity follows, LOE left
out), before and after. Shift = working hours between the two finishes on the delayed activity's
calendar. Pass when the whole delay arrived (`shift >= delay − 1e-6 h`, or the finish moved at
least as many calendar days as the delayed activity's own finish), or when part of it arrived with
nothing stopping the rest (the end points that finish the plain schedule moved and no expected
finish downstream gave up remaining duration). The note gives the move in working days (and on
the project calendar when it is less than the delay); on failure it names a delayed activity
without FS or FF successor, the open activities with a mandatory constraint, and the expected
finishes that absorbed the delay (`_what_stops_the_delay`).

## 3. Earned value (analysis/baseline.py, analysis/evm.py)

Units: labour hours, and cost for the rows marked cost. Baseline = a designated XER (`Baseline.from_snapshot`), the project the file names
as its P6 Project Baseline (`PROJECT.sum_base_proj_id` of the analysed project, built as a snapshot and
passed to `Baseline.from_snapshot`, so `bl_start` / `bl_finish` = P6's BL Project Start / Finish: its planned dates
(`target_*`) with "Budgeted values with planned dates", its actual > remaining > early dates with the two
"current dates" options (the window's "Earned value basis"; sources in docs/standards.md, P6 Check Schedule); used only when that project is in the file, has activities, and its
`orig_proj_id`, if filled, is the analysed project: `Snapshot.file_baseline`, `baseline_in_file`; Oracle P6
EPPM XER Import/Export Data Map, table PROJECT, v23; v26 unverified) or the snapshot's own `target_*` dates
(`Baseline.planned`), matched by `task_code` (first row per code kept). The app records how each update's
baseline was found (`Baseline.kind`: in file, exact, probable, chosen, fallback, planned, series) and
shows it with every result (`measured_against`).

| Symbol | Definition |
|---|---|
| `bl_start`, `bl_finish` | baseline's `start` / `finish` (from_snapshot) or the snapshot's `target_start_date` / `target_end_date` (planned); used by P6-12, P6-13, DCMA-11, DCMA-13 (margin without a Must Finish By), DCMA-14, 06A204b, 06A501a, WBS roll-up |
| `bl_duration_hr` | baseline's `target_drtn_hr_cnt` (DCMA-08) |
| EV basis (`ev_basis`, `baseline.EV_BASES`, P6 Admin Preferences, Earned Value) | `budgeted_planned` (default): `ev_start/ev_finish` = baseline `target_start_date/target_end_date` (blank → `bl_start/bl_finish`), `ev_labor_hr` = `labor_budget_hr`; `budgeted_current`: the baseline activity's Start / Finish (`start` / `finish`, i.e. `bl_start/bl_finish` of a baseline file), `labor_budget_hr`; `at_completion_current`: the same dates, `labor_actual_hr + labor_remaining_hr` |
| BAC | `Σ ev_labor_hr` over the baseline activities the update holds (`in_snapshot`): P6 totals its earned value fields over the activities of the current project ("adding the values for each activity in the summary", P6 Professional 25, How data is summarized), so a baseline activity deleted since has none; `baseline.bac_hours` (every baseline activity) stays the size of the plan (sidebar, PV curve) |
| Schedule % (`schedule_pct`, per activity, at instant `t`) | `100 × clip((w(t) − w(ev_start)) / (w(ev_finish) − w(ev_start)), 0, 1)`, `w` = working minutes on the baseline activity's calendar (`bl_clndr_id`, baseline file's calendars); zero or negative working duration: 100 when `ev_finish <= t`, else 0; a missing date: none (blank; `earned()` reads it as 0 for PV); unrounded, so the per-activity PV of `earned()` sums to `ev_point.pv_hr` (Oracle gives no rounding: PV = baseline labour units × Schedule % Complete) |
| PV (at `t`) | `Σ ev_labor_hr × Schedule %(t) / 100` over the baseline activities the update holds (`in_snapshot`; exact, unrounded); `ev_point.pv_hr` = PV at the data date. The PV of baseline activities the update no longer holds is left out, as in P6, and reported in `pv_deleted_hr` (`deleted_since_bl`: their count) |
| PV curve (`pv_curve(baseline, snapshot)`) | one row per instant: every midnight from the first `ev_start`'s day to the day after the last `ev_finish`, plus the update's data date when an update is given; `pv_cum_hr` = PV at that instant (`_Spread`, the same spread as Schedule %), `pv_hr` = difference with the previous row, `pv_pct = 100 × pv_cum_hr / BAC`. With an update: the baseline activities it holds and its BAC, so the curve at the data date is `ev_point.pv_hr`; without: every baseline activity and `baseline.bac_hours` |
| EV technique (`ev_technique`, `EV_TECHNIQUES`) | `PROJWBS.ev_compute_type` of the activity's WBS, exact code: blank or `EC_Cmp_pct` → activity; `EC_0_100` → 0/100; `EC_50_50` → 50/50; `EC_User_pct` → custom; `EC_WBS_pct` → wbs_milestones; any other code → unknown (never guessed). Only `EC_Cmp_pct` has been read from P6 exports; the other four codes are the tests' |
| Performance % (`performance_pct`) | activity: `pct_complete`; 0/100: 100 if complete else 0; 50/50: 100 complete, 50 started, else 0; custom: 100 complete, `PROJWBS.ev_user_pct` (blank → 0) started, else 0; wbs_milestones, unknown: `pct_complete` (fallback, activity listed in `EvPoint.not_modelled`); clipped to [0, 100] |
| EV | `Σ ev_labor_hr × Performance % / 100` over the baseline activities the update holds; snapshot activities absent from the baseline (`unbaselined`) earn 0 |
| Renumbered tasks (`baseline.renumbered`, option `relinked`) | a task of the update whose `TASK.guid` is a baseline task's, under another Activity ID, the old ID gone from the update and the new one absent from the baseline; blank GUIDs and GUIDs held by several tasks of a file are left out. P6 links a task to its baseline by Activity ID and renumbers the baseline with it when "Renumber Selected Activities in Baselines" is ticked (P6 Professional 24/25, Renumber Activity IDs). Off (default): such a task counts as deleted and not baselined, and the sidebar names them. On (window option "Link renumbered tasks by GUID"): the baseline row takes the new ID, update by update, for every baseline comparison. Whether P6 keeps `guid` when it copies a project is not documented |
| AC | `Σ labor_actual_hr` over all snapshot activities (unbaselined, LOE, complete included) |
| `ac_unbaselined_hr` | `Σ labor_actual_hr` over `unbaselined` |
| ETC | `Σ labor_remaining_hr` over all snapshot activities |
| ETC technique (`etc_technique`) | `PROJWBS.ev_etc_compute_type` of each WBS (project node left out): `EE_Rem_hr` remaining units, `EE_PF_1` PF = 1, `EE_PF_cpi` PF = 1/CPI (the codes of the reference files; the 1/(CPI × SPI) and entered-PF codes are not identified, any other code is shown as stored). Oracle (Pro 25, Earned Value tab - WBS Details): ETC = PF × (BAC − EV). Reported only: ETC above stays the remaining hours, and the page warns when a WBS has a code starting `EE_PF` |
| EAC | `AC + ETC` |
| VAC (`vac_hr`) | `BAC − EAC`; negative = overrun |
| SV | `EV − PV` |
| SPI (labor units, `spi`) | `EV / PV`; none when PV = 0. P6 column "Schedule Performance Index - Labor Units" |
| `bl_cost` / BAC cost (`bac_cost`) | per baseline activity `Σ TASKRSRC.target_cost` of its assignments (labour, nonlabour, material, roles) `+ Σ PROJCOST.target_cost` of its expenses, read on the baseline snapshot; BAC cost = `Σ bl_cost`. Independent of `ev_basis`. P6 Professional 26 help (PDF G57535-02, 9 Oct 2026, glossary): "Budget At Completion = Budgeted or Planned Labor Cost + Nonlabor Cost + Material Cost + Expense Cost. It is the same as the BL Total Cost." |
| PV cost (`pv_cost`) | P6 Professional 26 glossary: "Individual resource Budget At Completion × (Data Date of current project − Baseline Assignment Start Date) / (Baseline Assignment Finish Date − Baseline Assignment Start Date). The Planned Value Cost of an activity is the sum of the Planned Value Cost of each individual resource assignment on the activity. [...] If an activity has no resources, [...] Budget At Completion × Schedule % Complete [(Data date − Baseline Start) / (Planned Finish − Baseline Start)]." Implemented (`planned_value_cost`): per assignment, `target_cost × clip(share, 0, 1)`; a blank assignment date takes the activity's; expenses (PROJCOST) and the part of the budget no assignment carries take `bl_cost × share` on the activity's `ev_start/ev_finish`. Assignment dates: planned basis `target_start_date/target_end_date`; other bases actual, then remaining (`restart_date/reend_date`), then target. **The text writes a difference of dates: working time of the assignment's resource calendar (else the activity's) is assumed, unverified**; `evm.PV_COST_WORKING_TIME = False` switches to calendar time. Resource curves (`TASKRSRC.curv_id` not blank) and manual future-period values are not modelled (curves listed in `EvPoint.not_modelled_cost`). Whether the P6 Professional 24 behaviour is the same is not verified |
| EV cost (`ev_cost`) | `Σ bl_cost × Performance % / 100` (Glossary: "Earned Value Cost = Budget at Completion × Performance % Complete"), same technique as EV |
| SPI (cost, `spi_cost`) | `EV cost / PV cost`; none when PV cost = 0 (no cost in the baseline, or nothing planned yet). P6 column "Schedule Performance Index" (Glossary: "Schedule Performance Index (SPI) = Earned Value Cost / Planned Value Cost"). The Earned value page shows cost figures (cards, calculation rows, series columns, curve) only when the sidebar checkbox Costs is on, off by default because the schedules are sourced in hours and the costs in the file come from the resource prices; it then shows the cost index first and the labour units index second, otherwise the labour units index leads and a caption counts the assignments that carry a cost. P6 Professional 26 was read from its PDF, not run: the figure of a P6 report is the oracle, none is pinned yet |
| CPI (`cpi`) | `EV / AC`, all actual hours; none when AC = 0. P6 column "Cost Performance Index - Labor Units" = Earned Value Labor Units / Actual Labor Units (Oracle P6 EPPM help v25, page 47224, docs.oracle.com/cd/G18294_01/p6help/en/47224.htm) |
| `productivity` (EV/AC on baselined work) | `EV / (AC − ac_unbaselined_hr)`; none when that is 0 |
| `pv_pct`, `ev_pct` | `100 × PV / BAC`, `100 × EV / BAC`; none when BAC = 0 |
| Forecast curve (`forecast_curve`) | one row at the data date (`fc_cum_hr` = AC), then every midnight from the day after it to the day after the last open finish: `AC + Σ labor_remaining_hr` of not complete activities with remaining hours > 0, spread linearly in working time (activity's own calendar) from `max(start, data date)` to `max(finish, that start)`; a row holds the value at its instant, as `pv_curve` |
| BEI (`bei_series`: `bei_p6`, `bei_dcma`) | P6-13: `complete / (every baseline activity)`, `complete` = every complete activity of the update, due or not; DCMA-14: `complete with an actual finish on or before the data date / (bl_finish <= data date or blank)`, also without zero-duration activities; both over activities not LOE, not milestone (§2.1, §2.3) |

`evm_series` = one `EvPoint` row per snapshot against one baseline (`link_by_guid`: each update
against `relinked`; `code_filter`: the tasks of an activity code only, BAC, PV and EV on their baseline
tasks, AC and ETC on the update's, `update_and_baseline_of_code`). Pinned by
`test_weekly.py`: test_pv_spreads_over_working_days,
test_pv_is_schedule_pct_complete_in_working_time, test_pv_skips_calendar_holiday,
test_ev_spi_and_unbaselined, test_performance_pct_follows_the_wbs_ev_technique,
test_ev_technique_codes, test_ev_basis_follows_p6_admin_preference,
test_labour_hours_fall_back_to_assignments,
test_evm_series_one_point_per_update_against_one_baseline,
test_forecast_curve_starts_at_ac_and_ends_at_eac. Cost rows: `test_spi_cost.py`.

**Earned Schedule** (`earned_schedule`, `EarnedSchedule`; Lipke, "Schedule is Different", The
Measurable News, 2003). Measured activities: those of `ev_point` (in the update) with `ev_labor_hr
!= 0` and both EV dates; the EV earned on the others is reported as `ev_left_out_hr`. Plan time =
the union of the measured activities' baseline calendars (`union_of`: a minute counts when at least
one of them works); a plan day = the hours per day of the update's project calendar.

| Quantity | Definition |
|---|---|
| plan start, plan finish | first and last EV date of the measured activities |
| `pd_min`, `at_min` | plan-time minutes from the plan start to the plan finish (PD) and to the status date (AT) |
| `es_min` (ES) | plan-time minutes from the plan start to the instant at which the PV curve (`_Spread` on the measured activities) reaches the EV, read to the minute (Lipke's `C + (EV − PV_C) / (PV_C+1 − PV_C)` where the PV is linear). Where the plan asks for no hours over a stretch, every instant of it holds that EV and the status date is taken when it lies in the stretch, else the nearer end; once every hour is earned, ES = PD. None without a status date, with the planned dates baseline (a late start does not show in it), without a measured activity, or with a status date before the plan start (`note` says which) |
| `es_date` | that instant as a date (plan reached) |
| `sv_min`, `spi_t` | SV(t) = ES − AT (negative = behind); SPI(t) = ES / AT |
| `gap_calendar_d` | `(es_date − status date)` in calendar days, weekends included; none once ES = PD |
| `tspi` | `(PD − ES) / (PD − AT)` (Lipke, TD taken as PD); none once ES >= PD or AT >= PD |
| `finish_at(pace)` | status date + `(PD − ES) / pace` minutes of plan time (Lipke, IEAC(t) = AT + (PD − ES) / PF(t)); none without ES, once ES = PD, or without a pace above 0 |
| `weekly_gains` | per update after the first, both ends read on the baseline of the opening update (the plan in force during the week): `ev_gain_hr`, `pv_gain_hr`, `es_gain_min`, `at_gain_min`; `baseline_changed` when the closing update names another plan |
| `moving_window`, `gain_ratio` | the weeks from the last update dated at least 28 days before the data date, summed; SPI (4 weeks) = Σ EV gained / Σ PV gained (`spi_by_window`, `spi_4w`), pace = Σ ES gained / Σ AT gained; `gains_since_first` the same over every week with all four gains (pace, all updates) |
| `baseline_changes` | per update whose baseline differs from the previous update's: `gap_calendar_d` on the old and the new plan, `absorbed_d` = new − old, BAC of each, activities added and removed |
| `copied_lag` | in-progress activities that the baseline's own project had already started, with an EV finish before the baseline's status date, and their PV − EV (a baseline copied from a project under way) |
| `schedule_gap_by_status` | EV − PV of the measured activities by status: count, BL hours, PV, EV, hours ahead and behind |

The Earned value page shows plan reached, time gap and SPI(t); SPI, pace (4 weeks) and pace (all
updates); planned finish, the two forecast finishes and TSPI. Pinned by `tests/test_earned_schedule.py`.

## 4. Progress (analysis/progress.py, store.py)

**PPC** (`committed`, `ppc_series`), for each consecutive pair W-1 → W of the series
(sorted by data date, then source name): two kinds of commitment, read on the activities of W-1
that are neither milestones nor LOE:

| Commitment | Committed in W-1 | Kept in W |
|---|---|---|
| Finish | not complete, `finish <= data date of W` | complete, with `act_end_date <= data date of W` |
| Start | not started, `start <= data date of W` | started, with `act_start_date <= data date of W` |

`start` / `finish` are W-1's Start / Finish columns (actual, forecast, then planned). An actual
after W's data date (invalid progress for P6), or a status without its actual date, is a miss; an
actual entered late (before W-1's data date) still keeps it. An activity due to start and finish
within the week is two commitments. `include_overdue = False` keeps only the dates after W-1's
data date. Three series, each none (not 0) when its denominator is 0: `ppc_finish = 100 ×
finishes kept / finishes committed` (Last Planner's PPC: complete / planned), `ppc_start = 100 ×
starts kept / starts committed`, `ppc_week = 100 × kept / committed` over both kinds (PPC W/W-1).
Milestones are left out: a milestone repeats its predecessor's date, so counting it adds a
commitment the week the predecessor ends; `committed_milestones` lists them apart (a start milestone
commits its start, a finish milestone its finish). Activities deleted in W are listed (`status_now =
deleted`, `in_update` false) and left out of both counts. `unplanned_work`: activities new in W,
not milestone nor LOE, with an actual start on or before W's data date, out of the counts.
`code_filter`: the commitments of the tasks an activity code holds in W-1's file. `note`
(`_notes`): a pair more than 7 calendar days apart (`PPC_WEEK_DAYS`, dates compared at midnight: an
update missing, the point holds the commitments of every week between the two data dates), a W
without a data date (no commitment), a W-1 whose open activities have no date at all, Activity IDs
renumbered since W-1 (`renumbered`, by GUID or `task_id`: read as deleted + new). The PPC page shows
the note in the Commitments section of that week, not on the chart. Pinned by
test_ppc_counts_starts_and_finishes_and_leaves_milestones_out,
test_ppc_counts_only_commitments_still_in_the_update, test_ppc_series_one_row_per_week,
test_ppc_notes_a_point_that_spans_a_missing_update, test_ppc_regular_weekly_series_has_no_note,
test_ppc_week_at_another_hour_has_no_note; `tests/test_time_semantics.py`, `tests/test_ppc_code_filter.py`.

**Lookahead reliability** (`planned_for_week`, `lookahead_series`): for the week W-1 → W and a
horizon of n updates, the plan of W-1-n for the week is its commitments due by W's data date,
read as `committed` reads W-1's (with `include_overdue` false, only the dates after W-1's data
date), their outcome read in W; at n = 0 it is the weekly work plan, `committed(W-1, W)`.
`ta_pct = 100 × commitments of the weekly work plan held by the plan of W-1-n for the same week
/ commitments of the weekly work plan` (Tasks Anticipated) and `tmr_pct = 100 × commitments of
the plan of W-1-n for the week kept in W / commitments of that plan` (Tasks Made Ready,
TMR(n, 0)), both as Hamzeh, Ballard & Tommelein (2012), "Rethinking Lookahead Planning to
Optimize Construction Workflow", Lean Construction Journal, figure 5 (TA = 14/18, TMR = 11/20,
PPC = 13/18), first proposed by Ballard (1997). The unit is a commitment (Start or Finish), as
the PPC above; the sources count tasks. Activities deleted in W are left out, as for the PPC.
Horizons 1, 2, 4 and 8 updates: the sources measure one week (Ballard & Tommelein 2016, Current
Process Benchmark for the Last Planner System: "we are not aware that anyone has ever measured
beyond Week1") and two (Hamzeh et al. 2012); beyond, the reading is xerscope's. The example of
the 2016 benchmark (TA = FG/ACEFG) contradicts its own definition of TA; the 2012 figure is
followed. Pinned by tests/test_lookahead.py.

**Progress delta** (`progress_delta(prev, cur, baseline)`), per activity of either update:

| Column | Formula |
|---|---|
| `pct_prev`, `pct_now` | `pct_complete` in W-1 / W; 0 when absent |
| `pct_delta` | `round(pct_now − pct_prev, 2)` (points) |
| `labor_budget_hr` | without baseline: W's value, W-1's for an activity deleted in W; with baseline: `ev_labor_hr` (0 if not in the baseline) |
| `earned_hr_week` | without baseline: `labor_budget_hr × pct_delta / 100`; with baseline: `ev_labor_hr × (Performance %(W) − Performance %(W-1)) / 100`, absent = 0, so the column sums to `EV(W) − EV(W-1)` |
| `actual_hr_week` | `labor_actual_hr(W) − labor_actual_hr(W-1)`, absent = 0 |
| `new`, `deleted` | not in W-1 / not in W (`status = deleted`) |

A baseline without labour hours (`bac_hours` 0) is read as no baseline. A deleted activity
contributes `−pct_prev` points and negative earned hours. `progressed_tasks`: the rows where
`pct_delta`, `earned_hr_week` or `actual_hr_week` is not 0. Pinned by
test_progress_delta_weighted_by_hours, test_progress_delta_with_a_baseline_adds_up_to_ev,
test_progress_delta_gives_back_the_hours_of_a_deleted_activity.

**Date variances** (`date_variances(store, index)`), per activity of update W except LOE (its
dates follow the activities it spans): four columns `start_var_w1`, `finish_var_w1`, `start_var_w2`,
`finish_var_w2` = `working_days(date in W, date in W-k)`, i.e. reference − current, on the activity's
calendar in W: sign NEGATIVE = late (later than the reference), positive = earlier. Dates are P6's
Start / Finish (actual, else forecast). Missing date → blank, not 0 (no such update, the activity
not in it, or no date). A milestone has only the relevant end: a start milestone the start
columns, a finish milestone the finish ones. `moved_variances` keeps the rows where one of the
four is not 0 (blank is no move). Pinned by `test_weekly.py` test_variance_*.

**Roll-up** (`rollup_delta`, by `wbs_l1` default): `budget_hr` = Σ `labor_budget_hr`, Σ
`earned_hr_week`, Σ `actual_hr_week`; `activities_progressed` = count of `pct_delta > 0`;
`progress_pts = 100 × earned_hr_week / budget_hr` (NaN when budget 0); a `Project` row of
totals, its `progress_pts` on the totals (`project_progress`).

**MTA** (`milestone_trend`, `milestone_slips`): per milestone (any activity flagged
milestone in any update) and update, `forecast` = `start` for start milestones, `finish`
otherwise. `slip_wd = −round(working_days(first forecast, latest forecast), 1)` (first
minus latest: a milestone that went later reads negative) and `last_week_wd` = same between
the last two updates (0 with one update, blank for a milestone not in the latest update,
`deleted`), on the milestone's calendar as of the latest update. Pinned by
test_milestone_slip_in_working_days. The chart rows (`plotted_trend`) blank the forecast of an
update in which the milestone is complete with a forecast before that update's data date (it
only repeats the actual date below the diagonal), so the line breaks there; open, reopened
or complete-on-or-after-the-data-date points stay; the slippage table reads the full trend.
Pinned by test_mta_drops_a_milestone_complete_before_the_data_date. Each line keeps its own
series colour (`viz/charts.py` `build_mta`); the last point and the end label show the sign of `last_week_wd`:
red < 0 (later), green > 0 (earlier), no mark at 0. Pinned by
`test_viz.py` test_mta_lines_keep_their_own_colour_and_the_last_point_shows_the_move.

**Finish shift** (`SnapshotStore.summary.finish_shift_wd`):
`−working_days(previous finish_date, this finish_date)` on this (newer) update's project
calendar, not rounded: a finish that went later reads negative (days lost); none for the
first update or a missing finish. `finish_shift_since_first` is the same between the first
and the latest update. Other
`summary` columns: counts of activities, complete, in progress (started and not
complete), not started, critical, relationships; `pct_complete_count = round(100 ×
complete / activities, 1)`. Pinned by test_store.py::test_summary_tracks_slip.

**WBS roll-up** (analysis/wbs.py `rollup`), per WBS node (project node left out) over every
activity below it, plus a project row (`wbs_id = "__project__"`, depth 0):
`pct_complete = Σ labor_budget_hr × pct_complete / Σ labor_budget_hr` when the node's
budget hours > 0 (`weight = hours`), else `Σ original_d × pct_complete / Σ original_d`
(`weight = duration`); `activities`, `complete`; `critical` = not complete and critical;
`min_float_d`; `start = min start`, `finish = max finish`, `bl_finish = max bl_finish`;
`finish_variance_wd = −round(working_days(bl_finish, max finish of the activities the baseline
holds), 1)` on the project calendar (a node finishing later reads negative; an activity added
since the baseline does not count, `outside_bl` counts them); `budget_hr`, `actual_hr`,
`remaining_hr` sums. Pinned by
test_wbs_rollup_hours_weighting_and_tree.

## 5. Changelog (analysis/changelog.py)

Two updates of one project, activities matched by `task_code` (first row per code).
`before` / `after` are display strings; `delta` is numeric with `unit`. Sign of `delta`: a start, a
finish or the project's forecast finish reads working days gained (+) or lost (−), so a date that
goes later is negative, as the finish variances; every other row is after minus before.

| Category | Change | Condition | Delta (unit) |
|---|---|---|---|
| Project | status date | always | `working_days(old, new)` on the new update's project calendar: the working days elapsed (wd) |
| Project | forecast finish | always | `−working_days(old finish_date, new finish_date)`, same calendar (wd) |
| Project | activities, relationships | always | new count − old count |
| Scope | added / deleted | code only in new / only in old | — |
| Tasks | renamed, moved to another WBS, type changed, calendar changed | `task_name`, `wbs_code`, `type`, `clndr_id` differ (NaN = NaN); calendars shown by name | — |
| Durations | original duration changed | `target_drtn_hr_cnt` differs (hours, as P6 stores them: Oracle P6 EPPM 23 Application Administration Guide, "Using Calendars to Define Hours Per Time Period Settings"; a calendar change alone is not a duration change) | `original_d(new)` − the old hours / `hours_per_day` of the new calendar (wd) |
| Durations | remaining duration increased | `remain_drtn_hr_cnt(new) > remain_drtn_hr_cnt(old) + 1e-9` and not complete in new | same, on remaining (wd) |
| Durations | remaining duration cut | `remain_drtn_hr_cnt(new) < remain_drtn_hr_cnt(old) - 1e-9` and not started in new (work under way loses remaining duration as it progresses; on work not started a cut is a plan change) | same, on remaining (wd) |
| Progress | started / finished / status reverted | `status` differs; reverted when the order Not started < In progress < Complete goes down | — |
| Progress | actual start / finish changed (retroactive) | both present and different | — |
| Progress | actual start / finish removed | present in old, blank in new | — |
| Progress | % complete | `round(pct(new) − pct(old), 2) != 0` | that difference (pts) |
| Dates | start moved / finish moved | not complete in new and `abs(round(working_days(old date, new date), 2)) > 0.005`, on the new update's activity calendar | `−` that value (wd) |
| Float | total float changed | not complete in new, both floats present, and `abs(round((total_float_hr_cnt(new) − total_float_hr_cnt(old)) / hours_per_day(new), 2)) > 0.005` (hours, as P6 stores them; a calendar change alone is no float change) | that difference (wd) |
| Float | became critical / no longer critical | `is_critical` false → true; true → false and not complete in new | — |
| Constraints | primary / secondary constraint added / removed / changed | `cstr_type` (`cstr_type2`) differs, or present and its date differs | — |
| Resources | budgeted labour hours changed | `round(labor_budget_hr(new) − old, 2) != 0` | that difference (h) |
| Resources | resource assigned / removed / budgeted units changed | per (activity in both updates, resource label): `TASKRSRC.target_qty` summed per resource appears / disappears / `round(new − old, 2) != 0` | units difference (units) |
| Relationships | added / deleted | (pred, succ) pair only in new / only in old | — |
| Relationships | type changed / lag changed | pair in both with a different set of (type, `lag_hr`): type changed when the set of types differs, else lag changed | — |
| Calendars | working time changed | a calendar id in both updates whose hours per day, week or dated exceptions differ (`_calendar_definition`); `field` = the calendar's name | — |
| Options | scheduling option changed | one of `xer.model.SCHEDULE_OPTIONS` differs (blank and absent are equal). `field`, `before` and `after` carry the names of P6's Schedule Options dialog (Oracle P6 Professional 24 help, General tab): When scheduling progressed activities use (Retained Logic / Progress Override / Actual Dates), Calendar for scheduling Relationship Lag, Compute Total Float as, Make open-ended activities critical, Calculate start-to-start lag from (Early Start / Actual Start), Use Expected Finish Dates, Relationships to and from other projects, Define critical activities as (Total Float less than or equal to / Longest Path) and its hours, Must Finish By; a code the help does not name is shown as written | — |

`summary(log)` counts rows per (category, change), Project rows excluded; `category_totals` and
`headline_counts` read it; `weekly_change_counts` / `weekly_change_matrix` give it for every
consecutive pair of the series, one column per week (newer data date). Pinned by
test_changelog_finds_each_kind_of_change, test_changelog_relationships,
test_changelog_project_rows_and_summary, test_identical_files_have_no_changes,
test_changelog_lists_assignment_changes, test_changelog_lists_a_scheduling_option_and_a_must_finish_by_that_changed,
test_changelog_lists_a_calendar_whose_working_time_changed.

### 5.1 Half-step reading of a week (analysis/forensics.py)

AACE RP 29R-03, Forensic Schedule Analysis (rev. April 25, 2011), MIP 3.4 "Observational / Dynamic /
Contemporaneous Split", the bifurcated or half-stepped update analysis (3.4.K.4): the earlier update is
updated with the later update's progress data and recalculated at the later status date (the half-step
schedule); its move from the earlier update is the slip due to progress, the move from it to the later
update is due to the non-progress revisions, and the two add up to the move between the updates
(3.4.K.4.d to f). The SCL Delay and Disruption Protocol, 2nd ed. (February 2017), 11.6(c), describes
the same reading as the time slice windows analysis. Here the revisions are also applied one `Step` at
a time (`cpm.schedule` on a derived snapshot each), so the replanning is read by kind. The baseline
is not read.

| Step | Carries from the later update (activities in both updates unless stated) | Changelog categories counted |
|---|---|---|
| progress | status date; `status_code`, actual dates, suspend / resume, `phys_complete_pct`, the external early start / late finish bounds; `remain_drtn_hr_cnt` of the activities started in the later update whose remaining duration decreased (3.4.K.4.b: actual start, actual finish, increased percent complete, decreased remaining duration) | Progress |
| scope | activities added (their TASK rows, the links and assignments that reach them), deleted (taken out with theirs), `task_type` | Scope, Tasks: type changed |
| durations | `target_drtn_hr_cnt`, `expect_end_date`, every other `remain_drtn_hr_cnt` that changed (an increase, or a change on work not started: non-progress revisions, 3.4.K.4), the resource assignments | Durations, Resources |
| logic | every relationship of the later update (the scope step brought those that reach an added activity; the rest are the links between activities of both updates and the links to other projects) | Relationships |
| constraints | `cstr_type`, `cstr_date`, `cstr_type2`, `cstr_date2`, the project's Must Finish By | Constraints |
| calendars and options | `clndr_id`, the calendar definitions, the scheduling options, the planned start | Calendars, Options, Tasks: calendar changed |

| Quantity | Definition |
|---|---|
| `shift_wd` of a step | `0.0 − project_working_days(finish before the step, finish after it)` on the later update's project calendar, rounded to 0.01: days lost negative, as the changelog and the finish variances |
| finish before replanning | the finish after the progress step: where the earlier plan lands with the later update's status, nothing replanned |
| `slip_wd` | the progress step's shift: the delay of the week |
| `replanning_wd` | the shifts of the other steps, summed: what the replanning absorbed (positive) or added (negative) |
| `residual_wd` | the later update's recalculated finish against the last step's: 0 when the steps account for every change the engine reads; otherwise a change the changelog does not list |
| `period_wd` | `project_working_days(status date of the earlier update, status date of the later one)` on the later update's project calendar; `is_slip_beyond_period` when `slip_wd < −period_wd − 0.005`: 3.4.K.4.g, a revision in the half-step or work pushed into a non-working stretch |
| `engine_gap_wd` | `0.0 − project_working_days(Snapshot.finish_date, recalculated finish)` of an update, rounded to 0.01: the recalculated finish against the latest activity finish P6 stored in the file, 0 when reproduced to the minute. `is_finish_reproduced` when it is 0 for both updates of the week; otherwise the page warns that the shifts may be the recalculation's |
| `finish_case` | the project's finish is its latest early finish (Oracle P6 help, Activity Dates). `mandatory finish` when an open end point (no successor, not LOE, not complete) carries `CS_MANDFIN` and its early finish is the project's: the constraint sets the early and late finish to its date regardless of logic (Oracle P6 help, Mandatory finish constraint), so it is read first; else `must finish by` when `PROJECT.plan_end_date` is set (the project's late finish, P6 Web Services reference: the early finish still moves, float turns negative past it); else `last task`. A completed activity holds nothing: its finish is its actual finish (Oracle P6 help, Activity dates) |
| `longest_path_float_d` | lowest `tf_hr` of the recalculated longest path / hours per day of the project calendar: under a Must Finish By or a Mandatory Finish, where the delay the finish cannot show goes |
| `half_step_series` row | per update after the first: `finish_case`, `held_by`, `finish`, `finish_before_replanning`, `slip_wd`, `replanning_wd`, `residual_wd`, `period_wd`, `engine_gap_wd` (of the later update), `longest_path_float_d`, `tasks_matched`, `tasks_added`, `tasks_deleted`; a week that cannot be scheduled keeps its row with the reason in `note` and no figure |

A rename or a move to another WBS (the other kinds of the Tasks category) is no input of the
recalculation and is counted at no step.

**Where the revisions fall** (`revisions_by_horizon(old, new, lookahead_weeks)`). Per step after
progress, and for all of them: the changelog rows the step carries that name an activity, counted
`within the lookahead` when the activity's Start (actual, else forecast; the later update's, the
earlier one's for an activity deleted since) is on or before the later status date plus
`lookahead_weeks`, `beyond the lookahead` otherwise; `beyond_pct = 100 × beyond / (within +
beyond)`, blank when nothing was revised. Rows without an activity (Options, Calendars) or without
a start are left out. `lookahead_weeks` is `Settings.lookahead_weeks`, 6 by default. In the Last
Planner System the weeks ahead are where work is made ready (Ballard and Tommelein, "2020 Current
Process Benchmark for the Last Planner System", Lean Construction Journal, 2021); the split is
xerscope's reading and no source sets a threshold on the share.

What is progress and what is a revision follows 3.4.K.4 (the list of non-progress revisions:
activities added or deleted, logic links and lags, constraints, original durations, a remaining
duration increased or changed without a change in percent complete, calendar and holiday
assignments). Conventions no source settles (stated on the page): the order in which the kinds of
revision are applied, and the scheduling options, which the RP does not list, read with the
calendars.

Pinned by tests/test_forensics.py: a week without change moves nothing (property); a 2 wd delay
absorbed by a 2 wd cut reads −2 at progress and +2 at durations with the finish unmoved; one hand
case per step; every kind of change at once sums to the recalculated move with residual 0
(property); the three finish cases; the float under a Must Finish By (P6); the demo series has no
residual (characterization); a remaining duration increased on started work is a revision, not
progress (3.4.K.4); the period bound of 3.4.K.4.g; a step counts only the changes it carries; the
revisions of a week split at a 6-week lookahead (durations 2 / 2, logic 0 / 1, all 60 % beyond).

**What this reading rests on, measured (Nov 2026, held-out P6 corpus, 359 schedules).** The reading
moves one number, the recalculated project finish. xerscope's finish is P6's to the minute on 327
schedules (91.1 %): every schedule of 19 sets (H1 to H16, H18, H21, H22), 11 of 12 in H17, H19 and
H20, and 58 to 75 % in H23 to H30 (driving resources, an expected finish against a Mandatory
Finish, resource calendars). On a series of that last kind a shift can be the engine's and not the
schedule's: `engine_gap_wd` flags each such week on the page and in the series, and `xerscope
recalc` on the file lists the dates that differ. The steps themselves leave no residual on any of the 315 pairs of consecutive
corpus schedules that can be read (unrelated schedules, every kind of change at once); 15 pairs
are not read because links carried one kind at a time close a loop neither schedule has
(`half_step_series` keeps the row, with the reason). No P6 output exists for a half-step schedule:
the progress step has no oracle beyond the hand cases and the sum rule of 3.4.K.4.f.

### 5.2 Longest path of each update (analysis/longest_path.py)

AACE RP 29R-03 (rev. April 25, 2011) 3.4.E.9 ("use both the longest path and the least float criteria
to identify the controlling chain of activities") and SVP 2.3.B.6 ("for each update, identify all
changes made that extend, reduce, or change the longest path"); SCL Protocol 2nd ed. 11.6(c), the
contemporaneous critical path of each time slice.

| Quantity | Definition |
|---|---|
| longest path of an update | the activities P6 flagged (`TASK.driving_path_flag`, P6's Longest Path column) that are not complete; when the file flags none, the recalculated longest path (`cpm.schedule`), not complete; `source` = `P6 longest path` / `recalculated` / `none` (no flag and the file cannot be scheduled) |
| `change` of an activity on the path of either update | `stayed` (on both), `entered` (on the later only), `left: finished` (complete in the later), `left: still open` (in the later update, not complete, off its path: the path switched away from it), `left: deleted` (not in the later update) |
| `path_changes` row | `change`, `float_before_d` (P6's `total_float_d` in the earlier update), then the standard activity columns (`populations.ACTIVITY_COLS`, `total_float_d` the later update's); a deleted activity shows the earlier update's, without a float after |
| `path_churn` row | per update after the first: `on_path` = stayed + entered, `stayed`, `entered`, `left_finished`, `left_open`, `left_deleted`, `stability = stayed / (stayed + left_open)` (finished and deleted work could not stay; blank when nothing could), `path_source` of the later update, both sources when they differ |
| `path_commitments(old, new)` | the rows of `progress.committed(old, new)` (section 4, PPC) whose activity is on the longest path of `old`, the update that made the commitment, and still in `new` |
| `ppc_week`, `path_committed`, `path_kept`, `ppc_path` (in `path_churn`) | `ppc_week = 100 × kept / committed` over every commitment still in the later update, as the PPC page; the same over `path_commitments`; blank when nothing was committed. PPC counts every commitment alike; Hamzeh and Emdanat ("Last Planner System: the need for new metrics", IGLC) note it does not account for the criticality of a task. Restricting it to the longest path is xerscope's reading, not a published metric |
| population (`longest_path_funnel`) | a funnel of `analysis/populations.py`: every activity, `not complete`, `on the longest path (<source>)`; the page shows its steps and what each removed |

Pinned by tests/test_longest_path.py: the flagged path, open work only (P6); the recalculated path
when nothing is flagged; one change per activity, in reading order, with its floats; the churn of
three updates and its stability (0.5, then 1.0); two sources named; an update against itself; six
commitments of which four on the path, two kept (PPC 66.7 %, on the path 50 %).

### 5.3 Where the recalculation departs from the file (app/recalculation_departures.py, Debug block 3)

For the reading of 5.1, whose shifts are the recalculation's when `engine_gap_wd` is not 0.
The population is a funnel of `analysis/populations.py` (`departure_funnel`: not complete, not level
of effort, with a stored early date, one not the recalculated one, no predecessor in the same case),
and Debug shows its steps and what each removed.
`departures`: the unfinished activities with a stored early start or early finish the recalculation
does not give (`compare_with_stored`, exact clock time) and no predecessor in the same case: what
differs downstream follows from them. Per activity: stored and recalculated early finish, `gap_hr`
(recalculated minus stored, working hours of its calendar), status, type, constraints, an expected
finish, resource dependent, on the recalculated longest path. `departure_forms`: the same rows
counted by form, with no Activity ID and no date, for a diagnostic that can be shared. Pinned by
tests/test_diagnostic.py: test_departures_keep_the_activities_where_the_recalculation_first_differs,
test_departure_forms_are_in_the_anonymous_diagnostic_without_codes_or_dates.

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
| `ff_hr` | `free_float_hr_cnt` | `round(computed − stored, 2) == 0` (compared; INT-01 leaves it out, `integrity.STORED_FIELDS`) |
| assignment `restart`, `reend`, `rem_late_start`, `rem_late_end` | `TASKRSRC.restart_date`, `reend_date`, `rem_late_start_date`, `rem_late_end_date` | same timestamp |

Rows: not complete, not LOE activities (`compare_with_stored`, cached on the snapshot for the
plain recalculation); one row per assignment the recalculation schedules (`compare_assignments`);
`gap_hr` for dates = working hours from stored to computed on the activity's calendar (0 with
`agree = False` means the same working minute shown at a different clock time). Pinned by test_cpm.py (see §2.4) and
`tests/test_p6_heldout.py`.

## 7. Known limits

Stated by the code or docs/backlog.md; no DECM output has been compared. Two P6 Check
Schedule reports have: R1 (real schedule, not in the repository) and a P6 Professional 26.8 report
on a shareable synthetic project (`tests/test_p6_checksched.py`).

- P6 populations are a reading of the P6 Professional 24 dialog help (101248), else of
  the EPPM report pages, corrected by R1 for P6-12 and P6-13 and the only
  source for P6-15 to P6-17 (backlog). Open readings no report shows yet: LOE kept in P6-01
  (101248 is silent on LOE there); an in-progress activity whose remaining early start is before
  the data date (P6-10a); FF and SF links in P6-15; the defaults of the dangling options of P6-16 /
  P6-17 (113174 documents none); a baseline activity whose finish is blank is never listed as due in
  P6-13.
- `x` is an hour count (`limit_hours` in p6.toml): it assumes the calendar's hours per day; P6 targets are the EPPM 25 help's dialog defaults,
  not read from a Professional 24 dialog.
- DECM: the specification sheets (index in docs/standards.md, Sources) have been read.
  The 06A205a and 06A209a sheets name no LOE exclusion, so LOE stays in, as coded. Where a sheet contradicts a
  rule, or leaves a reading open (06A205a leads, 06A506b "on or before"), the items are listed in docs/backlog.md, "DECM conformance"; the formulas
  above are what the code does, not what the sheets say, for those. 06A401a runs the slip test of
  DCMA-12, an approximation of the sheet's constraint method.
- CPLI takes the schedule's total float, i.e. P6's distance to the Must Finish By date, when
  the project has one; without it, the margin of the last open finish milestone to its baseline
  finish (xerscope's reading). A contract finish kept elsewhere (a contract milestone, a
  constraint) is not read.
- DCMA-13 CPLI (`dcma_13_cpli`) under a Must Finish By reads the float of the latest-finishing open
  non-LOE activity (`finish_driver`), which may differ from `finish_date` (max over all activities);
  `critical_path_test` excludes milestones from the delayed candidates, CPLI does not.
- EV technique "WBS milestones" and unknown `ev_compute_type` codes are not modelled: they fall
  back to activity % complete and are listed in `EvPoint.not_modelled` (evm.py). The ETC technique
  is reported, not applied (ETC = remaining units). Resource curves (`TASKRSRC.curv_id`) are not
  modelled in PV cost (`EvPoint.not_modelled_cost`); Schedule % runs to the baseline finish where
  the P6 Professional 26 help names the current planned finish for PV cost (UNRESOLVED in
  `schedule_pct`).
- `pv_curve` and `forecast_curve` hold the value at their instant: a row dated a midnight holds
  the cumulative at the end of the day before.
- WBS roll-up % complete mixes percent-complete types and is not a P6 field (wbs.py).
- CPM not modelled: resource leveling, multiple float paths, relationships to projects
  not in the file (cpm.py); resource-dependent work, some Progress Override and mandatory-date
  rules still differ from P6 23.12 on part of the held-out corpus (docs/backlog.md, "CPM: where the
  engine still differs from P6 23.12").
