# 12. Glossary

Domain terms are the planner's; technical terms are the code's. Where a term is a real identifier
it is in backticks. `app/glossary.py` (`GLOSSARY`) holds the acronyms the app expands on hover.

## Domain terms (Primavera P6 and the standards)

| Term | Meaning in xerscope |
|---|---|
| **XER** | P6's tab-separated text export: an `ERMHDR` line, then tables introduced by `%T`, fields by `%F`, rows by `%R`, closed by `%E`. Read by `xer/parser.py`. |
| **Activity ID** (`task_code`) | The user-visible identifier of an activity; the identity xerscope uses across weeks. `task_id` is P6's internal key and is not. |
| **Data date** (status date) | `PROJECT.last_recalc_date`, else the planned start; the point from which remaining work is scheduled. `Snapshot.data_date`, `data_date_source`. |
| **Update** / **snapshot** | One weekly export, one project of it, as a `Snapshot`; the series holds one per data date. |
| **Baseline** (BL) | The plan an update is measured against: a separate XER, a loaded update, each update's planned dates (`target_*`), or the project the file names as its P6 Project Baseline (`sum_base_proj_id`). `analysis/baseline.Baseline`, `Baseline.source`. |
| **Project Baseline** (P6) | The `PROJECT` row another project points at with `sum_base_proj_id`; `orig_proj_id` names the project it was copied from. `Snapshot.file_baseline`. |
| **Baseline copy** | A project of the file that is some other project's baseline; set aside when picking the default project (`baseline_copies`). |
| **Early / late dates** | Earliest and latest start and finish from the forward and backward passes; `es`, `ef`, `ls`, `lf` in `Schedule.frame`; `early_start_date` … `late_end_date` as stored. |
| **Total float** | Late minus early finish by default (P6 "finish float"), or start, or the smaller (`FLOAT_TYPE`); stored in hours (`total_float_hr_cnt`), shown in working days (`total_float_d`). |
| **Free float** | Working time to the earliest successor constraint; `free_float_hr_cnt`, `ff_hr`. |
| **Critical** | By the project's definition: total float ≤ `critical_drtn_hr_cnt`, or on the longest path (`critical_path_type`). `is_critical`. |
| **Longest path** | The chain of activities driving the project finish; `on_longest_path`, `_Run.longest_path`. |
| **Retained Logic / Progress Override / Actual Dates** | P6's three ways to schedule out-of-sequence progress (`SCHEDOPTIONS`); `Options.progressed`, `PROGRESSED`. |
| **Expected finish** | A date typed on an in-progress activity that resets its remaining duration (`expect_end_date`, `rem_override_hr`). |
| **Lag / lead** | Time added to a relationship (`lag_hr`; a lead is negative), counted on the calendar the project names (`lag_calendar`: successor by default). |
| **FS / SS / FF / SF** | Relationship types finish-to-start, start-to-start, finish-to-finish, start-to-finish (`REL_TYPE`). |
| **Constraint** | Date restriction on an activity (`cstr_type`, `cstr_date`, secondary `cstr_type2`): Mandatory Start/Finish, Start/Finish On, On or Before, On or After, As Late As Possible. "Hard" differs by standard (`P6_HARD_CONSTRAINTS`, `DECM_HARD_CONSTRAINTS`, `HARD_CONSTRAINTS`). |
| **ALAP** | As Late As Possible: the activity moves right by its free float. |
| **LOE** (level of effort) | `TT_LOE`: an activity whose dates follow its links' dates and that drives nothing; excluded by many checks (`EXCLUSIONS["loe"]`). |
| **Milestone** | `TT_Mile` (start) or `TT_FinMile` (finish): zero duration; `is_milestone`, `is_start_milestone`. |
| **WBS** | Work breakdown structure (`PROJWBS`); `wbs_code`, `wbs_l1`; summary rows are not activities (`is_wbs_summary`). |
| **Resource-dependent** | `TT_Rsrc`: scheduled on its resources' calendars (`rsrc_early`); assignments in `TASKRSRC`. |
| **Driving assignment** | An assignment whose dates set the activity's (`driving`). |
| **Percent complete type** | Physical, Duration or Units (`complete_pct_type`); `percent_complete` follows it as P6 displays. |
| **Earned value** (EV, PV, AC, SPI, BEI) | In labour hours: PV = BL x Schedule % Complete, EV = BL x Performance % Complete (WBS EV technique), AC = actual hours, SPI = EV / PV; cost SPI from `target_cost`. BEI = baseline execution index: activities finished / activities due by the data date. `analysis/evm.py`, `rules.bei`. |
| **MTA** | Milestone trend analysis: each milestone's forecast date in every update (`progress.milestone_trend`). |
| **PPC** | Percent plan complete (Last Planner): commitments in W-1 kept in W (`progress.ppc_series`). |
| **P6 Check Schedule** | Tools › Check Schedule in P6 Professional 24: 14 documented checks plus out of sequence and dangling start/finish from a report; `standards/p6.toml`, 18 lines (P6-10 on two). |
| **DCMA 14-Point** | The Defense Contract Management Agency's legacy schedule assessment (PAM 200.1); `standards/dcma.toml`, DCMA-01 … DCMA-14. |
| **DECM** | DCMA EVMS Compliance Metrics v8.0, Guideline 6 schedule tests, metric ids like `06A204b`; `standards/decm.toml`. |
| **Integrity** | xerscope's own standard: INT-01/03 recalculate and compare, INT-02/04–08 mirror the P6 scheduling log; `standards/integrity.toml`. |
| **F9** | P6's schedule command; a file not rescheduled after an edit will differ from a recalculation. |
| **Out of sequence** | A started activity whose predecessor logic is not satisfied (FS predecessor not complete, SS not started). |
| **Dangling** | An open end: no predecessor driving the start or no successor driven by the finish (P6-16/17, 06A204b). |
| **Working day (wd)** | A day of the activity's own calendar (`day_hr_cnt`), as opposed to a calendar day. |

## Technical terms (the code)

| Term | Meaning |
|---|---|
| **`RawXer`** | Output of the parser: `tables` of string frames, `version`, `export_date`, `encoding`, `warnings`, `header`. |
| **`Snapshot`** | Typed view of one project in one export; the central domain object (`xer/model.py`). |
| **Snapshot contract** | The minimum columns of `tasks`, `relationships`, `assignments` (`TASK_COLS` + `LABOR_COLS`, `REL_COLS_MODEL`, `ASSIGNMENT_COLS_MODEL`); a floor, not a filter. |
| **`SnapshotStore`** | The weekly series; long-format `history`, `relationship_history`, `assignment_history`, `summary`. |
| **`WorkCalendar`** | Working periods per weekday plus exceptions, parsed from `clndr_data`. |
| **`TimeAxis`** | A calendar on an absolute minute axis with cumulative work; `work(ts)` and `at(w, finish)` make date arithmetic exact. |
| **`Schedule`** | Result of `cpm.schedule`: frame of `es`, `ef`, `ls`, `lf`, `tf_hr`, `ff_hr`, `rem_override_hr`, `longest_path`; `finish`, `warnings`, `assignments`. |
| **`_Run`** | One recalculation: network, forward, backward, floats, LOE, longest path, in that order. |
| **`Options`** | The scheduling options the CPM reads from `SCHEDOPTIONS` and `PROJECT`. |
| **`CycleError`** | A relationship loop; `members` are the activities on it. |
| **`@rule`** | Decorator registering a check function in `RULES` with its unit, `needs_baseline`, `links`. |
| **`Rule`** | Registry entry: function, unit, docstring parts, `params`, `validate`. |
| **`RuleOutput`** | What a rule returns: `flagged`, `numerator`, `denominator`, `value`, `note`, `checked`, `counted`, `funnel`, `status`. |
| **`Metric`** | One `[[metric]]` of a standard: `id`, `rule`, `params`, `unit`, `comparator`, `threshold`, `source`, `group`. |
| **`Standard`** | A TOML standard loaded: `id`, `name`, `metrics`. |
| **`AnalysisContext`** | `snapshot`, `store`, `baseline`: everything a rule may read. |
| **`CheckResult`** | A metric's result with `status` in `pass`, `fail`, `info`, `n/a`, `error`. |
| **`Funnel` / `Step`** | A population built one named, sourced filter at a time; `EXCLUSIONS`, `STEP_SOURCES`. |
| **`Explanation`** | `explain.explain(result)`: measured, formula, verdict, method, population, parameters, baseline. |
| **`AuditSets`** | Counted / checked / excluded rows cut from a `CheckResult`. |
| **Calculation sheet** | `sheets/P6/<id>.md`: population, counted items, Oracle text, worked example (`audit.sheet`). |
| **`Baseline.planned`** | The planned dates (`target_start_date`, `target_end_date`) of an update as its own baseline. |
| **`memo` / `data_identity`** | The app's per-session analysis cache and its key (files, projects, baseline, EV basis). |
| **`Anonymizer`** | Allowlist-based anonymisation with HMAC codes and a leak check (`LeakError`, `CodeClash`). |
| **xerkit** | `tests/xerkit.py`: builds tiny XER files in code so expected numbers are countable by hand. |
| **Held-out corpus** | Public synthetic schedules scheduled by P6 Professional 23.12.1 with P6's results (`tests/reference/fetch_p6_heldout.py`); `FLOORS` pin the share of identical values. |
| **Witness** | A local, uncommitted anonymised real schedule plus its P6 report (`tests/test_p6_witness.py`); R1 is one such report. |
| **MPXJ** | Open-source Java library reading P6 files with its own `PrimaveraScheduler`; the second opinion (`verify/mpxj_*`). |
| **`P6_SETTLED` / `UNRESOLVED`** | Shapes where P6 settled a difference against MPXJ, and the open ones (`verify/mpxj_cpm.py`). |
| **Golden file** | `tests/golden/standards.json`: every metric's result on the demo and reference files; `XERSCOPE_UPDATE_GOLDEN=1` rewrites it in a run that fails by design. |
| **Star schema** | `dim_snapshot` with `fact_activity`, `fact_relationship`, `fact_assignment` related on `snapshot_idx` (`export.py`). |
| **Distroless** | `gcr.io/distroless/cc-debian13:nonroot`: glibc and libstdc++ only, no shell, no package manager. |
| **Funnel (Tailscale)** | Tailscale's public HTTPS ingress to a node; not the `populations.Funnel` class. |
| **Secret prefix** (`XERSCOPE_PATH`) | The random path under which the remote app answers; every other path is 404 before authentication. |
| **`XERSCOPE_DATA_LOCKED`** | Remote mode: the visitor reads the server folder only, no path field, no XER upload. |
| **arc42 / C4 / ISO 42010** | The template, diagram model and standard this documentation set follows (see README). |
