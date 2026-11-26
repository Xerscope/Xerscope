# ADR-0004: Units: hours stored, working days of the activity's own calendar, exact working time on a minute axis

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`49ad764`, initial commit: `xer/model.py` "Key decisions", `WorkCalendar` and `TimeAxis` in `xer/calendar.py`) |
| Scope | `src/xerscope/xer/calendar.py`, `src/xerscope/xer/model.py`, `src/xerscope/config.py` (`Settings.default_hours_per_day`), every consumer of `_d` columns (`analysis/`, `viz/`, `app/`, `export.py`) |
| Sources | Oracle P6 Schedule Options help ("Lag entered in a unit other than hours is converted to hours based on the predecessor activity's calendar", quoted in `xer/model.py` and `tests/test_model.py`); P6 Check Schedule threshold `x` in hours (`standards/p6.toml`); DCMA-EA PAM 200.1 §4.8 (44 working days); `fe91302` "perf(calendar): TimeAxis.work searches one timestamp with bisect on cached lists" (2026-11-22); `docs/cpm.md` "Time: `TimeAxis`" |

## Context

P6 stores every duration, float and lag of an XER in hours (`*_hr_cnt` columns) and every
calendar as a `clndr_data` blob of working periods per weekday plus dated exceptions, with its
hours per day in `CALENDAR.day_hr_cnt`. The standards xerscope checks speak in different units:
P6 Check Schedule compares hours (its `x` is 352 h), DCMA and DECM thresholds are in working days
(44 working days for high duration), and planners read days. Activities of one project may sit on
calendars of 8, 8.2 or 10 hours a day, on night shifts that cross midnight, or on calendars derived
from a base.

`CONTRIBUTING.md` names "mixing hours and days, or calendar days and working days" as the most
common source of a wrong number. Floating-point division adds its own trap: P6 stores N days of an
8.2 h calendar as N x 8.2 hours, and 360.8 h / 8.2 is 44.00000000000001, which would read as more
than 44 days (`hours_to_days` docstring).

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Convert to days on read, with one hours-per-day figure for the project | simple arithmetic | wrong for every activity on another calendar; loses P6's own unit, so P6 checks in hours no longer compare as P6 does |
| Date arithmetic with calendar days or a fixed working week, ad hoc in each analysis | none up front | holidays, exceptions, shifts and partial days ignored; each analysis would carry its own approximation (alternative not recorded in history beyond the default used when a calendar is missing) |
| Hours stored as P6 stores them; `_d` columns in working days of each activity's own calendar; all date arithmetic on one exact minute axis per calendar (chosen) | a calendar parser and an axis per calendar | every derived day value depends on reading the right calendar; a missing calendar needs a stated fallback |

## Decision

**Storage.** Durations, float and lag stay in hours as P6 stores them. Names carry their unit
(`lag_hr`, `lag_d`; `CONTRIBUTING.md` Names rule 7); P6 fields keep their XER name
(`total_float_hr_cnt`, `remain_drtn_hr_cnt`; Names rule 8); the allowed short forms are
`hr`, `wd`, `d`.

**Derived day columns.** Every `_d` column of `Snapshot.tasks` (`total_float_d`, `free_float_d`,
`remaining_d`, `original_d`) is in working days of the activity's own calendar
(`CALENDAR.day_hr_cnt`), through `calendar.hours_to_days`, rounded to `DAYS_DECIMALS` (6) so that
44 days of an 8.2 h calendar stay 44. `lag_d` is converted on the **predecessor's** calendar, per
Oracle, whatever calendar the CPM then schedules the lag on (`options["lag_calendar"]`,
`SCHEDOPTIONS.sched_calendar_on_relationship_lag`, successor when blank). Project-level figures
(data date to forecast finish, finish shifts, a WBS node's finish) use the project calendar
(`Snapshot.project_working_days`). Calendar days are labelled "cal. d" in the app.

**Which unit a check compares.** P6 checks compare hours, as P6 does (`standards/p6.toml`:
`limit_hours = 352`); DCMA and DECM count working days. The Power BI `fact_activity` carries
`hours_per_day` so days convert back (days x `hours_per_day` = P6's hours).

**Working time: `xer/calendar.py`.**

- `WorkCalendar` parses `clndr_data` (`parse_clndr_data`): working periods per weekday plus dated
  exceptions; a derived calendar inherits the exceptions of its base
  (`model._inherit_base_exceptions`). With no usable blob, or a blob with no working
  weekday (its exceptions kept), the workweek is inferred (`from_data=False`): `week_hr_cnt`
  divided by `day_hr_cnt` (or the default hours per day when `day_hr_cnt` is unusable) gives the
  number of days, and Monday to Friday applies when `week_hr_cnt` is missing or not positive.
- `TimeAxis` lays a calendar's working periods on an absolute minute axis with cumulative work.
  `work(ts)` gives the working minutes from the axis anchor to `ts` (non-working time maps to the
  next period's start, so the function is monotone and continuous); `at(w, finish)` is its
  inverse, returning a period end when `finish` and the next period start otherwise. Everything
  else (`add`, `between`, `snap_start`, `snap_finish`, `keep_or_next`, `keep_or_previous`,
  `work_many`) is built on these two by binary search: `numpy.searchsorted` for arrays,
  `bisect_left` on cached Python lists for one timestamp (`_raw_one`, `fe91302`). The axis grows
  on demand, earlier or later, and work values stay anchored on the first origin.

**Default.** `Settings.default_hours_per_day` (8.0, `config.py`) applies only when no hours per
day can be read: a `day_hr_cnt` that is missing, zero or under one minute, and the standard
calendar used when the file has none. An activity whose calendar is not in the file takes the
project's calendar, then the file's first calendar, then the standard one
(`_BuildInputs.fallback_hours_per_day`, `Snapshot.calendar`).

## Consequences

- Day values agree with P6 per activity, to the minute, on any calendar; the CPM, PV curves,
  variances and `Snapshot.work_hours` share one arithmetic.
- A threshold is compared in the unit its standard states: hours for P6, working days for DCMA
  and DECM.
- Consumers must not sum `_d` values across calendars without `hours_per_day`; the export gives
  that column for the purpose.
- `TimeAxis.work` is the hot path of the CPM (tens of thousands of calls per schedule); its scalar
  search was rewritten for speed (`fe91302`) under an equality test against the array search.

## Verification

- `tests/test_model.py::test_lag_days_use_the_predecessor_calendar_whatever_the_lag_calendar`
- `tests/test_model.py::test_critical_uses_project_float_threshold_in_hours`
- `tests/test_calendar_and_standards.py`: `test_work_hours_are_exact_within_days`,
  `test_working_exception_and_midnight_end`, `test_missing_blob_infers_workweek_from_hour_counts`,
  `test_unknown_task_calendar_falls_back_to_the_project_calendar`,
  `test_a_derived_calendar_inherits_the_holidays_of_its_base`,
  `test_time_axis_values_survive_growing_backwards`,
  `test_a_night_shift_split_at_midnight_as_p6_writes_it_runs_through_midnight`
- `tests/test_shift_calendar.py`: `test_44_working_days_is_not_greater_than_44_on_an_8_2_hour_calendar`,
  `test_store_finish_shift_is_on_the_project_calendar`,
  `test_wbs_finish_variance_is_on_the_project_calendar`
- `tests/test_time_axis_scalar.py`: `test_every_minute_of_the_axis_reads_the_same_by_both_searches`,
  `test_work_on_one_timestamp_equals_work_many`
- `tests/test_store.py::test_fact_activity_carries_hours_per_day_so_days_convert_back`
- `tests/test_p6_check_schedule.py::test_dcma_08_original_44_days_is_not_high_45_days_is`

## References

- `src/xerscope/xer/calendar.py`: `hours_to_days`, `DAYS_DECIMALS`, `parse_clndr_data`,
  `WorkCalendar` (`from_row`, `standard`, `work_hours`, `working_days`), `TimeAxis` (`work`,
  `work_many`, `at`, `add`, `between`, `_raw_one`)
- `src/xerscope/xer/model.py`: `_calendars`, `_relationships` (`lag_d`),
  `_BuildInputs.fallback_hours_per_day`, `Snapshot.working_days`, `Snapshot.project_working_days`
- `src/xerscope/config.py`: `Settings.default_hours_per_day`
- `docs/architecture.md` §2 ("Units", "Lag" rows), §3
- `docs/cpm.md` "Time: `TimeAxis` (`xer/calendar.py`)"
- `docs/user-guide.md` "Concepts" (What xerscope reads from an update, Units of time)
- `CONTRIBUTING.md` "Units" paragraph, Names rule 7
- Related: [ADR-0002](0002-format-parser-then-p6-model-with-load-contract.md),
  [ADR-0007](0007-own-cpm-engine-validated-against-p6.md),
  [ADR-0009](0009-standards-as-toml-one-function-per-check.md)
