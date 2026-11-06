# Earned value in xerscope against P6: definitions, settings, evidence, gaps

Branch `claude/wizardly-ptolemy-b4zjg4`, HEAD `dd32a06`. Read-only
analysis; nothing under `src/` changed. Line numbers are those of this commit.

Scope: `src/xerscope/analysis/evm.py` (EV), `analysis/baseline.py` (baseline frame, EV basis,
assignment costs), `analysis/progress.py` (weekly EV delta), the P6 export comparison in
`app/diagnostic.py` and `cli.py pv-compare`, `xer/model.py` (columns), the docs
(`docs/formulas.md` §3, `docs/backlog.md` "Checks and earned value", `docs/standards.md`,
`sheets/P6/P6-13.md`) and the tests (`test_weekly.py`, `test_spi_cost.py`, `test_pv_p6.py`,
`test_file_baseline.py`, `test_cli.py`).

Evidence legend for the tables: **hand** = expected value written by hand in the test from a
schedule built with `tests/xerkit.py`; **P6 CSV** = a pinned P6 Activities export; **R1** = the
confidential P6 Professional Check Schedule report the maintainer keeps outside the repo
(`docs/standards.md`, Sources); **none** = no test fixes the number against a P6 output.

---

## 1. Definition table

| Quantity | xerscope formula (file:line) | P6 field / formula it claims to match (source named in the repo) | Test pinning it | Evidence |
|---|---|---|---|---|
| BAC (labour units) | `Σ ev_labor_hr` over baseline activities present in the update (`ev_point`, evm.py:598-600, `current["bl_labor_hr"].sum()`); `ev_labor_hr` = baseline `labor_budget_hr` (`target_work_qty`, else Σ TASKRSRC `target_qty` of labour / role assignments: model.py:1191-1216) or actual + remaining under the "at completion" basis (baseline.py:52, 63-65). `Baseline.bac_hours` (baseline.py:140-142) sums every baseline activity (plan size). | "Budget At Completion - Labor Units"; totals over "the activities of the current project" (P6 Pro 25, *How data is summarized*, quoted evm.py:15-19, formulas.md §3 BAC row). EV basis = Admin Preferences > Earned Value "When calculating earned value from a baseline use" (baseline.py:15-17; quote marked **unverified** in backlog.md:105-106). | `test_ev_basis_follows_p6_admin_preference` (test_weekly.py:668), `test_activities_deleted_since_the_baseline_are_left_out_of_bac_pv_and_ev` (:169), `test_labour_hours_fall_back_to_assignments` (:333) | hand |
| Schedule % Complete | `100 × clip((w(t) − w(ev_start)) / (w(ev_finish) − w(ev_start)), 0, 1)`, `w` = working minutes on the **baseline activity's calendar** (`bl_clndr_id`, read in the baseline file), `t` = the update's data date instant; zero working span → 100 once `ev_finish <= t` (`_elapsed`, evm.py:209-241; `schedule_pct` :244-247). Under the default basis `ev_start/ev_finish` = the baseline project's `target_start_date/target_end_date` (Planned dates), blank → its current Start/Finish (baseline.py:48-51). | "Schedule % Complete = share of the activity's baseline duration elapsed at the data date" (evm.py:6-10, no page cited); glossary formula quoted in formulas.md §3 PV cost row: "(Data date − Baseline Start) / (Planned Finish − Baseline Start)" — a **date difference**; working time is the repo's reading (evm.py:36-39 "assumed, unverified"). | `test_pv_is_schedule_pct_complete_in_working_time` (test_weekly.py:121), `test_pv_spreads_over_working_days` (:111), `test_pv_skips_calendar_holiday` (:137), `test_planned_dates_baseline_spreads_on_the_current_dates_with_a_current_dates_basis` (:697) | hand |
| PV (labour units) | per baseline activity `ev_labor_hr × Schedule % / 100` (`earned`, evm.py:572); `ev_point.pv_hr` = Σ over activities present in the update (:601); deleted baseline activities apart in `pv_deleted_hr` (:613). PV curve `_Spread`/`_ramp_sum` (:118-185) = same ramp per activity, daily grid, end of day (:195-207). | "Planned Value Labor Units" = BL labour units × Schedule % Complete (evm.py:6, formulas.md §3). **The same repo also quotes the Pro 26 glossary saying PV Labor Units is per labour assignment with resource-curve distribution** (`pv_labor_check` docstring, evm.py:273-277): the activity-level formula is what the KPI uses, the assignment-level one is a diagnostic only. | `test_per_activity_pv_sums_to_the_headline_pv` (test_weekly.py:130), `test_ev_spi_and_unbaselined` (:144), `test_pv_compare_*` (test_cli.py:185, 218) | hand |
| Performance % Complete | `performance_pct` (evm.py:521-545): technique from `PROJWBS.ev_compute_type` (`ev_technique`, :69-84); activity → `pct_complete`; 0/100 → 100 if complete else 0; 50/50 → 100 / 50 / 0; custom → 100 / `ev_user_pct` / 0; wbs_milestones and resource_curves → `pct_complete` (fallback, listed in `EvPoint.not_modelled`, :604-605). `pct_complete` by `complete_pct_type` (model.py:173-210): CP_Phys `phys_complete_pct`, CP_Drtn `(orig − rem)/orig` (100 once complete), CP_Units `(act labour + act nonlabour) / (act + remaining)`, blank → physical → status. | P6 WBS Earned Value tab, "Technique for computing performance percent complete" (evm.py:11-14). `pct_complete` "checked against MPXJ's P6 8.4 test export and xerlock's rules" (model.py:180-181, `tests/test_reference.py`). | `test_performance_pct_follows_the_wbs_ev_technique` (test_weekly.py:250), `test_ev_technique_codes` (:322), `test_ev_uses_the_unrounded_percent_complete` (:194); `pct_complete`: `tests/test_reference.py` on `mpxj/percent-complete-8.4.xer` | hand; % complete types: third-party P6 8.4 export (stated results) |
| EV (labour units) | `ev_labor_hr × Performance % / 100` per baseline activity (evm.py:573); Σ over activities present in the update (:602); unbaselined activities earn 0 (:597, 603). | "Earned Value Labor Units = BAC Labor Units × Performance % Complete" (evm.py:11; formulas.md §3 EV row). | `test_ev_spi_and_unbaselined`, `test_current_dates_on_a_planned_dates_baseline_move_pv_only` (test_weekly.py:724), `test_progress_delta_with_a_baseline_adds_up_to_ev` (:636) | hand |
| AC | `Σ labor_actual_hr` over **every** activity of the update, baselined or not (evm.py:603); `ac_unbaselined_hr` apart (:608). | "Actual Labor Units" (evm.py:20-21). | `test_ev_spi_and_unbaselined`, `test_cpi_divides_by_all_actual_hours_and_ev_per_ac_by_the_baselined_ones` (test_weekly.py:207) | hand |
| ETC | `Σ labor_remaining_hr` over every activity (evm.py:604); the WBS technique is **read and reported only** (`etc_settings`, :95-115; page warning earned_value.py:247-251). | "Estimate To Complete Labor Units"; P6: per WBS, remaining units or `PF × (BAC − EV)` (Pro 25, Earned Value tab - WBS Details; evm.py:22-26). | `test_etc_settings_count_the_wbs_by_etc_technique` (test_weekly.py:287) asserts the ETC does **not** move with the technique | hand (pins the divergence) |
| EAC | `AC + ETC` (`EvPoint.eac_hr`, evm.py:437-439). | "Estimate At Completion Labor Units" (= AC + ETC in P6 too, but P6's ETC follows the WBS technique). | `test_ev_spi_and_unbaselined` (`eac_hr == 140`), `test_forecast_curve_starts_at_ac_and_ends_at_eac` (:471) | hand |
| SPI (labour units) | `EV / PV`, None when PV = 0 (evm.py:441-443). | "Schedule Performance Index - Labor Units" (formulas.md §3). | `test_ev_spi_and_unbaselined` (1.25) | hand |
| SPI (cost) | `EV cost / PV cost` (evm.py:445-448); PV cost per assignment `target_cost × elapsed share` on the assignment's own dates and resource calendar, expenses and unassigned budget on the activity's dates (`planned_value_cost`, :250-257); EV cost = `bl_cost × Performance %` (:576). | Pro 26 glossary quotes (PDF G57535-02) for BAC, Planned Value Cost, Earned Value Cost, SPI (evm.py:32-48; formulas.md §3). Working time "assumed, unverified" (`PV_COST_WORKING_TIME`, evm.py:62-64). | `tests/test_spi_cost.py` (whole file: :78, :92, :110, :136, :150) | hand |
| CPI | `EV / AC` over all actual hours (evm.py:459-461); `productivity` = EV / AC on baselined work (:450-456), a xerscope-only ratio. | "Cost Performance Index - Labor Units" = EV Labor Units / Actual Labor Units (EPPM help 47224, formulas.md §3 CPI row). | `test_cpi_divides_by_all_actual_hours_and_ev_per_ac_by_the_baselined_ones` | hand |
| % complete (activity) | `pct_complete` (model.py:173-210), see Performance %. | "Activity % Complete" per "% Complete Type" (model.py:115-116). | `tests/test_reference.py` (MPXJ 8.4 file, xerlock) | third-party stated results |
| % scheduled | = Schedule % Complete above; project level `pv_pct = 100 × PV / BAC` (evm.py:466-471, 476-477). | P6 shows Schedule % per activity; the project-level share is xerscope's. | `test_pv_is_schedule_pct_complete_in_working_time` | hand |
| VAC | **not computed** (no `vac` field in `EvPoint.as_row`, evm.py:463-491). | P6 "Variance At Completion - Labor Units = BAC − EAC". | none | none |
| SV | `EV − PV` (evm.py:475). | "Schedule Variance - Labor Units". | covered through `test_cpi_...` row columns (:233) | hand |
| BEI (P6-13) | completed (not LOE, not milestone) / **every** baseline activity, whatever its baseline finish (`p6_13_bei`, analysis/p6/check_schedule.py:324-345); listed: due by the data date and not complete. | P6 Professional Check Schedule report R1; help 101248 and EPPM 46277 say "calculated to finish before the data date" (P6-13.md:24-30, standards.md:25, 75, 83-84, p6.toml:162). | `test_p6_13_bei_is_completed_over_all_baseline_activities`, `test_p6_13_a_baseline_milestone_is_not_counted`, `test_bei_p6_counts_due_in_the_baseline_dcma_in_the_schedule` (tests/test_rules.py), `test_bei_series_one_row_per_update_p6_and_dcma` (test_weekly.py:751) | hand, shape taken from R1 (not in the repo) |
| BEI (DCMA-14) | completed with actual finish ≤ data date (by calendar day) / due (`bl_finish <= data date`, missing baseline finish counts as due); LOE, milestones, zero-duration tasks out (`dcma_14_bei`, analysis/dcma/fourteen_point.py:463-480 → `bei_from_snapshot`, rules.py:648-690). | DCMA-EA PAM 200.1 §3.1.2.4 (dcma.toml:136-142). | same tests; `test_bei_series_...` pins 4/7 and 5/8 on the demo series | hand |
| Weekly EV gain | `progress_delta` (progress.py:200-236): `ev_labor_hr × (Perf %(W) − Perf %(W−1)) / 100` with a baseline, `labor_budget_hr × Δpct` without. | xerscope definition (sums to EV(W) − EV(W−1)); no P6 counterpart claimed. | `test_progress_delta_with_a_baseline_adds_up_to_ev`, `test_progress_delta_gives_back_the_hours_of_a_deleted_activity` (test_weekly.py:636, 644) | hand |

**Summary of the table.** Every labour-unit and cost EV number is pinned by a hand calculation on a
synthetic schedule; **no number is pinned against a P6 output**. The repo says so itself for the
cost rows ("the figure of a P6 report is the oracle, none is pinned yet", formulas.md §3 SPI cost
row) and for the time convention (evm.py:36-39, backlog.md:92-95). BEI is the only EV-adjacent
figure settled by a P6 output (R1), and that output is not in the repository.

---

## 2. P6 settings that change EV, and what xerscope does with them

| P6 setting | Where it lives in the XER | xerscope | file:line | Reference files |
|---|---|---|---|---|
| WBS "Technique for computing performance percent complete": Activity % complete | `PROJWBS.ev_compute_type = EC_Cmp_pct` (blank → same) | **applied** (`pct_complete`) | evm.py:73-74, 540 | every file: `EC_Cmp_pct` or blank |
| … 0/100 | `EC_0_100` | **applied** | evm.py:81-82, 535, 541 | none holds it (hand test only) |
| … 50/50 | `EC_50_50` | **applied** | evm.py:77-78, 536, 542 | none |
| … Custom percent complete (`ev_user_pct`) | `EC_User_pct`, `PROJWBS.ev_user_pct` | **applied** (blank user % → 0) | evm.py:75-76, 527-530, 537, 543 | none |
| … WBS milestones percent complete | `EC_WBS_pct`; the milestones themselves are in a WBS table the model does not read | **ignored** → falls back to `pct_complete`, activity listed in `EvPoint.not_modelled` | evm.py:79-80, 604-605 | none |
| … Activity percent complete using resource curves | code containing "crv"/"curve"/"rsrc" (no reference file shows the actual code; backlog.md:100-101) | **ignored** → `pct_complete`, listed | evm.py:81-82 | none |
| WBS "Technique for computing ETC": remaining units / PF = 1 / PF = 1/CPI / PF = 1/(CPI × SPI) / entered PF (`ev_etc_user_value`) | `PROJWBS.ev_etc_compute_type` (`EE_Rem_hr`, `EE_PF_1`, `EE_PF_cpi`; the two other codes not identified), `ev_etc_user_value` | **reported only**: `etc_settings`, Debug block 8, page warning; ETC stays remaining hours | evm.py:87-131, 604; earned_value.py:142, 247-251; formulas.md §3 ETC technique row | Hotel Project: 365 of 964 WBS on `EE_PF_1`; mpxj percent-complete-8.4: `EE_PF_cpi` |
| Activity "% Complete Type" (Duration / Physical / Units) | `TASK.complete_pct_type` | **applied** in `pct_complete` (Units = labour + nonlabour units) | model.py:115-116, 173-210; counts in block 11 (model.py:395-397, 913-916) | all three in mpxj percent-complete-8.4; others CP_Drtn or CP_Phys |
| Admin Preferences > Earned Value "When calculating earned value from a baseline use" (budgeted/planned dates, budgeted/current dates, at-completion/current dates) | not in the XER (admin-level); sidebar choice | **applied** as a user choice, default budgeted + planned dates | baseline.py:34-39, 42-69; app/state.py:1002-1020 | n/a |
| Baseline choice (Project Baseline vs user's primary; `use_project_baseline_flag`) | `PROJECT.sum_base_proj_id`, `use_project_baseline_flag` | **applied** for the pointer (`baseline_in_file`, falls back to a separate XER or planned dates); the flag is **reported only** (block 11) | baseline.py:150-169; diagnostic.py:474-477 | pv file points to an absent project 370 |
| Planned dates as baseline when no baseline is assigned | `TASK.target_start_date/target_end_date` | **applied** (`Baseline.planned`) | baseline.py:129-137 | all |
| Renumbered activities (GUID link) | `TASK.guid` | **applied** on option (`relinked`) | baseline.py:175-212 | none |
| Resource curves (`curv_id`) for PV spreading | `TASKRSRC.curv_id`; the curve table itself is not read | **ignored** (linear), counted in `EvPoint.not_modelled_cost` and block 09 `labor_assignments_with_curve` | baseline.py:98; evm.py:290, 319-320, 606-607 | 0 curves in every reference file |
| Manual future-period buckets | not in the XER as read | **ignored** | backlog.md:96 | n/a |
| Calendar for PV time-phasing (labour) | `TASK.clndr_id` **of the baseline file's activity**, calendars of the baseline file | **applied** (working time), the convention itself unverified | evm.py:9-10, 190, 222-226, 244-247 | Hotel: every labour assignment is on a resource calendar other than the activity's (block 09, `task_dependent_on_other_calendar` = 1110) |
| Calendar for PV cost (per assignment) | `TASKRSRC.rsrc_clndr_id` (the resource's), else the activity's | **applied**; P6 schedules task-dependent assignments on the activity's calendar (diagnostic.py:400-402), so the cost PV spreads on a calendar P6 does not use for those | baseline.py:90, 97; evm.py:252-254 | Hotel: 1110/1110 |
| Data date instant | `PROJECT.last_recalc_date` with its time | **applied** at the instant; end-of-day variant computed as a diagnostic only | evm.py:302, 322-325 | 00:00 in every reference file but xerlock (08:00) |
| Cost vs units | `TASKRSRC.target_cost`, `PROJCOST.target_cost` for BAC/PV/EV cost; labour units for AC/ETC/EAC/CPI | cost **applied** for BAC/PV/EV/SPI; Actual Cost, CPI cost, EAC cost **not computed**; nonlabour units enter only the Units % complete | baseline.py:72-109; backlog.md:97-99 | Hotel: 1114 equipment, 54 material assignments |
| Project-level totals ("adding the values for each activity in the summary") | — | **applied**: Σ over activities of the update; P6's summary rows (WBS/project) not compared | evm.py:15-19 | — |

---

## 3. The PV time-phasing method against P6

**xerscope.** One linear ramp per **activity**, from `ev_start` to `ev_finish`, in **working
minutes of the baseline activity's calendar** (`TimeAxis` of the baseline file), evaluated at
the **instant** of the update's data date (`_elapsed`, evm.py:209-241). All labour hours of the
activity, whatever their assignments, follow that one ramp. Zero-span rows step at their finish.
The cumulative curve (`pv_curve`) is the same ramps sampled at the end of each calendar day.

**P6 (as the repo documents it).** Two texts are quoted and they do not describe the same thing:

- EPPM help / Pro help: "Planned Value Labor Units = BL Labor Units × Schedule % Complete",
  Schedule % = (Data date − BL Start) / (BL Finish − BL Start): a **date difference**, per
  activity (evm.py:6-10, formulas.md §3). Whether P6 takes it in calendar time or in the
  activity's working time, and whether a data date at 00:00 counts that day, is not settled
  by any output in the repo (evm.py:36-39 and 273-282 say so).
- Pro 26 glossary "Planned Value Labor Units": the sum over labour **assignments** of their
  baseline units distributed over the assignment dates **with the resource curve**
  (evm.py:273-277). This is the P6 resource-spreadsheet view of PV, and is what P6's
  time-distributed data (Resource Usage Spreadsheet, the Activity Usage Profile) uses.

So the KPI follows the first text and ignores the second; `pv_labor_check` (evm.py:269-339,
Debug block 09) already computes the four alternatives per update (activity vs assignment,
working vs calendar time, instant vs end of day) so that a P6 export can tell which one P6 uses.

**Magnitude, measured on the Hotel Project reference file** (4,217 activities, 1,110 labour
assignments, BAC 27,183 h, assignments on the activity's dates but on resource calendars other
than the activity's; `Baseline.planned`, data date moved by hand every three months):

| Date | PV activity, working time (KPI) | assignment, working time | activity, calendar time | activity, end of day |
|---|---|---|---|---|
| 2012-12-01 | 933.9 | −9.7 | −6.4 | 0.0 |
| 2013-03-01 | 3,602.6 | −7.7 | −3.0 | **+40.0** |
| 2013-06-01 | 8,667.1 | **−58.4** | −58.0 | 0.0 |
| 2013-09-01 | 12,751.5 | −5.6 | +6.7 | 0.0 |
| 2013-12-01 | 19,095.2 | −0.7 | +18.3 | +1.6 |
| 2014-03-01 | 24,899.8 | −39.0 | −28.4 | +0.1 |

Columns 3-5 are gaps against column 2 in hours. On this file (no curves, assignments on the
activity's dates, 8 h calendars) each convention moves the project PV by **0.0 to 0.7 %** at a
date, i.e. SPI by under 0.01. The per-activity gaps are larger than the totals (they cancel). The
differences grow with: resource curves (not modelled at all: a bell curve halves the PV at the
start of an activity), assignments with their own planned dates or lags (block 09 counts them),
24 h / 7-day calendars (calendar time ≈ working time there, so a working-time assumption is
wrong by the weekends), long activities with few hours, and a data date at 00:00 (end of day
adds one working day of every in-progress activity, here +40 h on one date = 1.1 %). Without the
author's export none of these can be told apart from a P6 difference in the data itself.

---

## 4. Evidence in the repository today

- **No P6 Activities export with PV/EV columns is pinned.** `tests/reference/sources.py` lists
  XER files only (MPXJ, xerlock, P6-Viewer, the 20 kW PV repo, PrimeveraXEREditor, the held-out
  CPM corpus); the only CSV files under `tests/reference/data/` are the held-out CPM results
  (dates and floats, no EV columns).
- **`tests/test_pv_p6.py` is a test of the comparison tool, not of P6.** Its `P6` frame
  (test_pv_p6.py:48-59) is typed by hand with deliberately different values ("P6: A 50 / 62.5
  (125 h)", "C 16 as if its baseline were this week", "H baselined in P6") to exercise the
  gap-cause columns; the assertions pin the gap arithmetic (−27 h, −12.5 h, bands, causes), not
  any P6 behaviour. Same for `test_cli.py:185-240` (the CLI writes the five tables from a
  synthetic CSV).
- **No reference XER has progressed earned value.** On every reference file the data date is
  before or at the first baseline start (PV = 0 under the planned baseline) and actual hours are
  0, except mpxj `percent-complete-8.4.xer` (BAC 400, EV 200, AC 200, PV 0 because the data date
  precedes the planned dates: SPI undefined). No file has a resource curve, a usable in-file
  baseline (`file_baseline.usable` is False everywhere; the PV file points to an absent project
  370), or a non-default EV technique. Only the ETC technique varies (Hotel `EE_PF_1`, mpxj
  `EE_PF_cpi`), and it is ignored by the KPI.
- **`pv-compare` runs** (`uv run xerscope pv-compare --help` printed the expected usage:
  `path --p6 CSV`, `--baseline` or `--planned-baseline`, `--column FIELD=HEADER`, `--tolerance`,
  `--p6-total`, `--project`, `--out`). It reads headers `Activity ID`, `Planned Value Labor
  Units`, `Earned Value Labor Units`, `Schedule % Complete` (required) and `BL Project Labor
  Units` / `Budgeted Labor Units`, `Activity Status`, `BL Project Start`, `BL Project Finish`,
  `Planned Start`, `Planned Finish` (optional) (diagnostic.py:551-562), handles P6's number
  formats, "A"/"*" date flags, band and total rows, and writes five tables (totals by group,
  gap by Schedule % band on both sides, gap causes, gap by calendar, activities in gap). There
  is nothing in the repo to run it on: the remaining differences on a real export are unknown.
- What the comparison **cannot yet attribute**: it has no column for Performance % Complete,
  Actual / Remaining / ETC / EAC Labor Units or the WBS techniques, so an EV gap cannot be split
  between a % complete difference and a BL-units difference beyond `bl_hr_differs`, and the ETC
  divergence is not measured at all.

---

## 5. Likely causes of EV divergence, ranked, with the one global change for each

Ranked by expected effect on SPI/EAC for a real progressed schedule with a baseline, given
what is applied, ignored or unverified above. "Evidence" names the export columns (section 6)
that settle each.

| # | Cause | Expected effect | The single global change | Evidence needed |
|---|---|---|---|---|
| 1 | **Time convention of Schedule % Complete** (working time on the baseline activity's calendar at the data-date instant, vs calendar time, vs end of the data-date day). Unverified (evm.py:36-39, 273-282). Touches every in-progress activity on every update. | 0-1 % of PV on an 8 h/5 d file; several % with 24 h or 7-day calendars or a 00:00 data date; the sign is systematic, so SPI is biased on every update. | One switch in `_elapsed` (working_time / `when` convention) used by `schedule_pct`, `planned_value_cost`, `pv_curve`; the diagnostic already computes the three variants (`pv_labor_check`). Pick the one whose `Schedule % Complete` matches the export to 0.01 pt on every activity, then delete the others. | `Schedule % Complete`, `BL Project Start`, `BL Project Finish`, `Calendar` (activity) per activity; the project's data date with its time. The `10_pv_p6_by_schedule_pct` and `10_pv_p6_by_calendar` tables isolate it. |
| 2 | **Which baseline values P6 reads** (dates: the baseline project's Planned vs current Start/Finish; units: Budgeted vs At Completion of the baseline; activities absent from the baseline: 0 in xerscope, P6 behaviour not documented in the repo — test_pv_p6 *assumes* P6 baselines them with their own values). The admin preference quote is unverified (backlog.md:105-106). | Whole activities move between PV 0 and PV > 0; BAC changes; large on re-baselined or heavily added-to schedules. | `ev_basis` already exists (baseline.py:34-39): keep the one whose `BL Project Start/Finish/Labor Units` equal the baseline XER's values on every activity; add the rule for unbaselined activities once the export shows P6's value for them (`in update, not in baseline` row of `10_pv_p6_totals`). | `BL Project Start`, `BL Project Finish`, `BL Project Labor Units`, `Budgeted Labor Units`, `At Completion Labor Units`, plus the Admin Preferences > Earned Value setting (a screenshot or the words) and the baseline assigned (Project Baseline name). |
| 3 | **ETC technique ignored**: `PF × (BAC − EV)` not applied; ETC = remaining hours whatever the WBS says. | Changes EAC and VAC only (not SPI); on a project like Hotel (38 % of WBS on PF = 1) EAC can differ by the whole (remaining − (BAC − EV)) of those WBS. | Implement the four codes per WBS in `ev_point` (one function, `etc_hr` per activity = remaining, or `PF × (bl_labor_hr − ev_hr)` with PF 1, 1/CPI, 1/(CPI × SPI), `ev_etc_user_value`), keep the warning for codes not identified. Needs the project-level CPI/SPI or the WBS-level one: the export says which. | `Estimate To Complete Labor Units`, `Estimate At Completion Labor Units`, `Remaining Labor Units` per activity; WBS export with `Earned Value` tab fields (ETC technique, PF); the two unidentified codes read on a WBS set to 1/(CPI × SPI) and to a custom PF. |
| 4 | **PV per activity instead of per assignment** (Pro 26 glossary) — assignments with their own dates, lags or resource calendars. | ≤ 0.7 % on Hotel (assignments on the activity dates); larger with lagged or shortened assignments (block 09 `planned_start_later_than_activity`, `with_original_lag`). | If the export matches `pv_assignment_hr` and not `pv_activity_hr` (block 09 `gap_hr`), switch `earned()` to the assignment spread already written in `pv_labor_check` (one line: use `by_assignment` where the activity has labour assignments). Resolve the calendar question of row 2 of §2 (task-dependent assignments on the activity's calendar) at the same time. | `Planned Value Labor Units` against both diagnostic totals (`09_pv_labor_check`); a Resource Assignments export with `Planned Start/Finish`, `Budgeted Units`, `Planned Value Labor Units`? (P6 shows PV at assignment level in the Resource Assignments view), `Calendar` of the resource. |
| 5 | **Resource curves and future-period buckets** not modelled. | Zero when `curv_id` is blank everywhere (every reference file); up to tens of % of an activity's PV at its start/end when a curve is set. | Read the XER's curve table and spread each curved assignment by its 21-point curve in `_Spread`; otherwise document as unsupported and keep the count (block 09 `labor_assignments_with_curve`). | The count of assignments with a curve in the author's file (block 09); if > 0, `Planned Value Labor Units` of those activities and the curve names. |
| 6 | **Performance % under a non-default technique** (0/100, 50/50, custom with non-physical % type: untested, backlog.md:104; WBS milestones: ignored; "with resource curves": ignored). | Zero on a project on `EC_Cmp_pct` everywhere (every reference file); whole-activity EV jumps otherwise. | Nothing to change until a file shows the techniques; then one hand test per technique from the export's `Performance % Complete`. | `Performance % Complete`, `Activity % Complete`, `% Complete Type` per activity and the WBS `Earned Value` tab fields. |
| 7 | **Population of the totals**: activities deleted since the baseline, added since, LOE and WBS summary activities, P6 view filters and summary rows. Handled by the comparison (groups, `P6 total - export rows`) but the P6 total vs Σ activities is unverified. | Any size; a filtered view explains most "P6 total ≠ export" cases. | None in the KPI; `--p6-total` in `pv-compare` already measures it. | The project-level `Planned Value Labor Units` / `Earned Value Labor Units` as P6 shows them on the project row, with an unfiltered Activities view. |
| 8 | **Cost side**: Actual Cost, CPI cost, EAC cost absent; cost always on budgeted values. | Only if the author reads cost SPI/CPI. | Add `ac_cost = Σ TASKRSRC act_reg_cost + act_ot_cost + PROJCOST act_cost` and the cost CPI/EAC; one function beside `planned_value_cost`. | `Actual Cost`, `Budget At Completion`, `Planned Value Cost`, `Earned Value Cost`, `Cost Performance Index`, `Estimate At Completion`. |
| 9 | **VAC** not computed. | Reporting gap only. | `vac_hr = bac_hr − eac_hr` in `EvPoint.as_row` (depends on #3). | `Variance At Completion - Labor Units`. |

The key the author is looking for ("une amélioration globale") is #1 + #2 together: both are
one-switch conventions already parameterised in the code (`_elapsed`'s `working_time` and
`when`; `EV_BASES`), both bias every update in the same direction, and one export of one update
settles both at once. #3 is the only item that is a real missing feature with a documented P6
formula and a reference file that exercises it (Hotel, `EE_PF_1`), and it only moves EAC.

---

## 6. What the author must provide from P6 (never committed; anonymised or summarised only)

One update XER already in hand, its baseline (the baseline XER, or the baseline exported inside
the XER so that `sum_base_proj_id` resolves), and from P6 on **the same XER at the same data
date**, saved as CSV (not XLSX, diagnostic.py:565, 586):

1. **Activities view, unfiltered, grouped by nothing, no summary rows** (or with them: the tool
   sets band/total rows aside), columns in this order:
   `Activity ID`, `Activity Status`, `Activity Type`, `% Complete Type`, `Calendar`,
   `Activity % Complete`, `Performance % Complete`, `Schedule % Complete`,
   `Duration % Complete`, `Units % Complete`, `Physical % Complete`,
   `Budgeted Labor Units`, `BL Project Labor Units`, `Actual Labor Units`,
   `Remaining Labor Units`, `At Completion Labor Units`,
   `Planned Value Labor Units`, `Earned Value Labor Units`,
   `Estimate To Complete Labor Units`, `Estimate At Completion Labor Units`,
   `Variance At Completion - Labor Units`,
   `Schedule Performance Index - Labor Units`, `Cost Performance Index - Labor Units`,
   `Start`, `Finish`, `Planned Start`, `Planned Finish`, `BL Project Start`, `BL Project Finish`,
   `WBS`.
   (Optional cost columns: `Budget At Completion`, `Planned Value Cost`, `Earned Value Cost`,
   `Actual Cost`, `Schedule Performance Index`, `Cost Performance Index`.)
   `pv-compare` reads the four required and six optional headers today; the others are for the
   author's own reading until the comparison grows columns for them.
2. **The project row** of the same view (project-level PV and EV Labor Units), for `--p6-total`.
3. **The settings**, as text: Admin Preferences > Earned Value ("When calculating earned value
   from a baseline use …", and "Performance % Complete: …"); Project Details > Settings
   (baseline for EV: project baseline vs primary); the WBS Earned Value tab of two or three WBS
   elements (technique, ETC technique and PF); whether any WBS uses WBS milestones or curves.
4. **The data date** with its time of day, and whether the project was scheduled (F9) before the
   export.
5. Optional, for #4/#5 of §5: a **Resource Assignments** view export with `Activity ID`,
   `Resource ID`, `Budgeted Units`, `Planned Start`, `Planned Finish`, `Curve`, `Calendar`.

Then run `uv run xerscope pv-compare UPDATE.xer --baseline BL.xer --p6 activities.csv
--p6-total <project PV> --out pv_compare` and share **only** the four code-free tables
(`10_pv_p6_totals`, `10_pv_p6_by_schedule_pct`, `10_pv_p6_gap_causes`, `10_pv_p6_by_calendar`)
plus Debug block 09 (`09_pv_labor_check`, `09_pv_labor_by_status`, `09_assignment_dates`) and
block 08 (`08_etc_techniques`), which carry counts and hours only. The `activities_in_gap`
table holds Activity IDs and names and stays local. Whatever convention the export confirms is
then written into one hand test per behaviour, as the project's rules require.
