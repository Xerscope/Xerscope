# The CPM engine (`analysis/cpm.py`)

`schedule(snapshot)` recomputes every activity's early and late dates, total and free
float, longest path and resource-assignment dates the way Primavera P6 Professional 24
does when you press F9, from the logic, durations, calendars, constraints, progress,
assignments and scheduling options stored in the XER.

It serves:

- **INT-01 / INT-03** (Integrity standard): are the stored activity and assignment dates
  what P6 would calculate now? If not, the file was edited after the last schedule, and
  every float-based check (P6 Large/Negative float, DCMA-06/07, the critical path) reads
  stale numbers.
- **The critical path test** (DCMA-12, DECM 06A401a): delay the first open activity of the
  longest path by 600 working days, reschedule, check the finish moves by as much.
- **CPLI** (DCMA-13), in exact working time.

```bash
uv run xerscope recalc week42.xer --out recalc.csv   # field-by-field agreement + all dates
```

## Validation

Recalculating real P6 exports and comparing with what P6 stored, exact clock time
required (`tests/test_cpm.py`):

| File | Scheduled by | Activities | Values compared | Identical |
|---|---|---|---|---|
| Hotel Project | P6 6.0 | 4,217 (7,586 links: FS/SS/FF/SF; 11 calendars; holidays; ALAP; must finish by) | 25,302 | 25,302 |
| Terminal Building | P6 5.0 | 66 (SNLT, 7-day calendar, must finish by) | 396 | 396 |
| xerlock sample | P6-format, progressed | 24 (3 complete, 3 in progress, progress override) | 126 | 126 |
| Hotel + Terminal assignments | P6 6.0 / 5.0 | 2,340 assignments (labour, nonlabor, material) | 9,360 | 9,360 |
| Longest path flag | all three | 4,304 open activities | 4,304 | 4,304 |

Values = early start, early finish, late start, late finish, total float, free float of
each open activity; for assignments, remaining early start / finish and remaining late
start / finish (TASKRSRC `restart_date`, `reend_date`, `rem_late_*`); the longest path is
P6's `driving_path_flag`. Plus xerlock's stated critical path test (MEP-020 +600 wd,
finish 2026-09-08 → 2028-12-27) and CPL (1,080 h).

The engine is mutation-tested: plausible bugs injected one at a time (snapping, lag
calendars, options, ALAP, time axis, SS expired lag, resource calendars, assignment lag
and duration, Actual Dates, longest path). Each is caught, except swapping start float
for finish float: the two coincide in this engine (see "Conventions" below).

What the reference files exercise, and what only hand-built tests cover (built from
Oracle's documented behaviour, not from P6 output):

| Verified against P6 output | Hand tests only (Oracle's documented rule) |
|---|---|
| FS, SS, FF, SF with lags | lag on successor / 24 h / project calendar (option read verified on MPXJ files) |
| 11 calendars, holidays, working exceptions, lunch breaks | start on, finish on, start/finish on or after, finish on or before |
| start on or before (SNLT) | mandatory start / finish |
| as late as possible, chained | retained logic (out-of-sequence), expected finish, Actual Dates |
| must finish by, open ends | SS lag from a started predecessor (Early Start / Actual Start), open ends critical |
| progress override with actuals | level of effort |
| start/finish milestones | resource-dependent activities on resource calendars |
| assignment dates of task-dependent activities (units / units per hour) | assignment lag |
| longest path | |

If your files use something in the right column, `xerscope recalc` on them is the check:
an exact match there is the same proof as for the left column.

## Time: `TimeAxis` (`xer/calendar.py`)

A calendar is turned into a sorted array of working periods in absolute minutes, with the
cumulative working minutes at each period start. Two functions do all the arithmetic:

- `work(ts)`: working minutes from the axis anchor to `ts`. Non-working time maps to the
  next period's start, so the function is monotone and continuous.
- `at(w, finish)`: the inverse. On a boundary, Monday 17:00 and Tuesday 08:00 are the same
  working minute; `finish=True` returns the period end, `finish=False` the next start.

Everything else is built on these two, by binary search (`numpy.searchsorted`):

- adding or subtracting duration: `at(work(ts) ± d, …)`;
- working hours between two dates: `work(b) − work(a)`;
- snapping a date to working time;
- `work_many`: the same for an array (PV curves, variances).

The axis extends itself when a date falls outside it (a 600-day delay runs years ahead,
negative float runs back before the data date). Work values stay anchored on the first
origin, so a value computed before the axis grew is still valid after it.

Calendars come from `CALENDAR.clndr_data`: the work week (P6 numbers days 1 = Sunday to
7 = Saturday) and the exceptions (Excel serial dates; an empty exception is a holiday, one
with periods is a working day with its own hours). If the blob is missing, the work week
is inferred from `day_hr_cnt` and `week_hr_cnt`.

## Options read from the file (P6 Professional 24, Schedule Options › General)

| Option | XER | Default when blank (Oracle) |
|---|---|---|
| When scheduling progressed activities use | `sched_retained_logic`, `sched_progress_override` (both `N` = Actual Dates) | Retained Logic |
| Calculate start-to-start lag from | `sched_lag_early_start_flag` | Early Start |
| Calendar for scheduling relationship lag | `sched_calendar_on_relationship_lag` | **Successor** activity calendar |
| Compute total float as | `sched_float_type` | Finish float |
| Make open-ended activities critical | `sched_open_critical_flag` | no |
| Use expected finish dates | `sched_use_expect_end_flag` | yes |
| Must finish by | `PROJECT.plan_end_date` | none |

Lag entered in days is converted to hours on the **predecessor's** calendar (Oracle),
whatever calendar the lag is then scheduled on: `relationships.lag_d` uses it.

## Algorithm

**Graph.** Activities are matched by Activity ID. LOE and WBS summary activities are
taken out of the network; the others are put in topological order. A logic loop raises
`CycleError`, which names the activities involved.

**Earliest start.** `max(data date, project planned start)`. P6 never schedules remaining
work before either.

**Forward pass (early dates)**, for each activity in topological order:

| Bound | Rule |
|---|---|
| FS | start ≥ pred finish + lag |
| SS | start ≥ pred start + lag (started predecessor: see below) |
| FF | finish ≥ pred finish + lag |
| SF | finish ≥ pred start + lag |
| Start on / Start on or after | start ≥ date |
| Finish on / Finish on or after | finish ≥ date |
| Mandatory start / finish | the date, whatever the logic |

- **Lag calendar:** lags are added on the calendar the project names.
- **SS lag of a started predecessor** (Oracle, "Calculate start-to-start lag from"):
  - *Early Start* (default): expired lag = working time from the predecessor's actual
    start to the data date; successor start ≥ the predecessor's internal (remaining)
    early start + the lag not yet expired.
  - *Actual Start*: successor start ≥ actual start + lag, i.e. the data date plus the
    remaining lag.
  - The two differ when the predecessor is itself held back (retained logic): Early Start
    then pushes the successor further. SF links from a started predecessor follow the
    same rule (convention, see below).
  - Backward pass: the same shortened lag. With the full lag, a driving SS link from a
    started activity left it negative float on an unconstrained network (fixed after the
    property tests found it; Oracle documents the forward pass only).
- **Duration:** finish = start + remaining duration, in working minutes of the activity's
  calendar.
- **In progress:** the actual start is kept. The remaining work starts at the data date:
  - **Retained Logic** (default) and **Actual Dates**: it also waits for unfinished
    predecessors;
  - **Progress Override:** it ignores them;
  - **expected finish:** if the project uses them, it sets the remaining finish.
- **Complete:** actual dates; they drive successors through their actual finish.
- **Resource dependent** (`TT_Rsrc`, Oracle: "scheduled according to the calendars for
  the resources … the latest finish date of all driving resources is used for the early
  finish"): each driving assignment (`rollup_dates_flag`) starts at the logic's bound plus
  its lag on its resource's calendar (`RSRC.clndr_id`) and lasts remaining units / units
  per hour; the activity runs from the earliest assignment start to the latest finish.
  Without a driving assignment with a rate it falls back to the activity calendar (warned).

**Backward pass (late dates)**, in reverse order:

| Bound | Rule |
|---|---|
| FS | finish ≤ succ late start − lag |
| SS | start ≤ succ late start − lag |
| FF | finish ≤ succ late finish − lag |
| SF | start ≤ succ late finish − lag |
| no open successor | finish ≤ project "must finish by" if set, else the latest early finish; its own early finish if "make open-ended activities critical" |
| Start on / Start on or before | start ≤ date |
| Finish on / Finish on or before | finish ≤ date |
| Mandatory | the date |
| Actual Dates option | a started successor bounds its predecessors by its *actual* dates: out-of-sequence progress gives the predecessor negative float, growing each period it stays open (Oracle warns of exactly this) |

Resource-dependent activities place each driving assignment's late finish on its
resource calendar the same way.

**Float.**

- **Total float** = late − early finish, in working hours of the activity's calendar.
  It uses the project's float type: finish float (default), start float, or the smaller.
- **Free float** = room to the earliest successor bound, using successors' early dates.
  For an open end, it runs to the project's early finish (not to "must finish by":
  Terminal shows 8 h of total float but 0 free float).
- **As late as possible:** in reverse order, an ALAP activity moves right to use its free
  float, against its successors' already moved dates. Free float is measured after that,
  as P6 shows it: Hotel's chained ALAP activities pin this.

**Longest path** (Oracle: "activities that have an early finish equal to the latest
calculated early finish for the project and tracing all driving relationships for those
activities back"): from the open activities finishing last, walk back through every
relationship whose bound equals the successor's start (FS/SS) or finish (FF/SF).

**Assignments.** Task dependent: remaining start = the activity's remaining start +
assignment lag, finish = start + remaining units / units per hour (else the activity's
remaining duration), on the activity calendar; late dates likewise from the late start.
Exactly what P6 stored on 2,340 Hotel and Terminal assignments.

**Level of effort.** Each relationship ties the end of the LOE it names. Start-type ends
(SS / FS predecessors, SS / SF successors) give its start, the earliest of them;
finish-type ends (FF / SF predecessors, FF / FS successors) its finish, the latest. An FF
predecessor and an FF successor to the same activity give the same finish, as Boyle shows
in P6 ("Constructing LOE activities in Primavera P6"). It drives nothing.

**No data date.** P6 always stores one. A file without a data date and a planned start
is scheduled from the earliest activity date it carries, with a warning.

## Snapping: how a computed instant is written

The same working minute can be written two ways (Monday 17:00 or Tuesday 08:00). P6's
choice matters, because a later lag on another calendar starts from the written time.
Each rule below is pinned by a real file:

| What | Rule | Evidence |
|---|---|---|
| task start | the start of a working period (a predecessor ending 17:00 → next morning) | all files |
| task finish | the end of a working period | all files |
| early finish pushed by FF/SF/finish constraint into non-working time | the next working time | Hotel HCSWB3Z2190: 30 Oct 08:00 after the Eid holidays, not 24 Oct 16:00 |
| late finish | a period end (a successor starting 08:00 → previous evening) | all files |
| start milestone, early | like a task start | xerlock MS-020: 08:00 the next morning |
| start milestone, late | kept as is if on a period edge, else the previous working time | Hotel HCMEB4000 16:00; xerlock MS-020 08:00 |
| finish milestone, early | kept as is if working time or a period edge, else next working time | Hotel: 16:00 right after its predecessor |
| finish milestone, late | a period end | Hotel |

## Conventions no reference file settles

The engine makes a reasonable choice for each of these and tests it, but no available
P6 output confirms it:

- **Late-start bound in non-working time** (e.g. via an SS lag on a 24 h calendar):
  written as the next period start, like every task start.
- **Finished predecessor with a lag, successor in progress:** the lag is not re-applied
  to the remaining work.
- **SF link from a started predecessor:** treated like SS (expired lag subtracted under
  Early Start). Oracle documents the option for SS only.
- **Resource-dependent activity:** FF/SF bounds and the float are measured on the
  activity's calendar; the start is the earliest driving assignment start.
- **Start float vs finish float:** the engine keeps start = finish − duration on both
  passes, so the two are equal for task-dependent activities.
- **LOE dates:** no reference file has an LOE, so the rule above is from Oracle's and
  Boyle's descriptions, not from stored P6 dates. LOE are excluded from INT-01.

## Property tests

`tests/test_cpm_properties.py` schedules 300 seeded random networks (all link types,
leads and lags, progress, every P6 option, every constraint type, three calendars, LOE)
and checks what any P6 recalculation must satisfy: each relationship holds on early and
late dates; a task lasts its remaining duration early and late; total float = late −
early finish; no negative float without constraints; zero float on the longest path when
nothing dangles; constraints hold in working time; delaying any activity never brings the
finish earlier.

## Critical path test

The delayed activity is the first open one (by remaining start) on the recalculated
longest path, not "total float ≤ 0": with negative float that takes in less critical
paths, whose delay is partly absorbed. Pass = the finish (latest early finish of the
activities without successors) moved by at least the delay, measured on the delayed
activity's calendar. It can move further when the path crosses calendars with other
non-working days (Hotel: +611 wd for +600); less means a constraint or broken logic
absorbed part of it.

## Not modelled

The engine reports a warning when these occur:

- leveling (detected when stored remaining early dates differ from the early dates);
- multiple float paths;
- relationships to projects that are not in the file.

Links to other projects that are in the file are read (`Snapshot.external_links`), but no
reference file has them, so they are not used yet.

## Performance

Hotel (4,217 activities, 7,586 links, 2,278 assignments) schedules in about 2 s. The plain
recalculation is cached on the snapshot, so INT-01, INT-03, the critical path test and the
weekly trend share it; the critical path test adds one more run.
