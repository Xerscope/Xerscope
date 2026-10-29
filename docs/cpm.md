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

Three sources, strongest first. None of them is xerscope's own output. Where two
disagree, P6 wins and the difference is recorded against the other.

**1. P6 Professional 23.12.1: the held-out corpus** (danafitkowski/cpp-cpm-engine, MIT;
fetched at test time by `tests/reference/fetch_p6_heldout.py`, scored by
`tests/test_p6_heldout.py` and `xerscope crosscheck --p6`). 360 synthetic schedules,
frozen before P6 saw them, imported into P6, scheduled with F9, early / late dates and
floats read back from P6's database: progressed (in and out of sequence, suspended),
constrained (every type, mandatory dates, expected finishes), multi-calendar,
level-of-effort and resource-dependent work, under every scheduling option.

| Scope | Values | Identical to P6 |
|---|---|---|
| H1–H7: task-dependent work, every option, no LOE | 9,444 | 99.5 % |
| task-dependent work, all 30 sets | 41,868 | 85.0 % |
| resource-dependent work (P6's import sizing laid over the case) | 12,858 | 61.9 % |

`FLOORS` in the test holds each set's share and fails on any drop; `PINNED` names the
corpus activity each rule of the engine was taken from, so a regression on one rule is
named rather than averaged away. Rules taken from the corpus: float-type codes; an SF
link from a started predecessor applies; the expected finish stands in for start +
remaining (remaining 0 when it falls before the start, a later FF / SF bound wins);
mandatory dates never put early dates before the data date; the late start an SS / SF
bound gives is written at the bound's instant; lags into a finished successor pass back
in full (FS / FF) or unexpired (SS / SF); under Progress Override the start of work under
way is an actual (FS / SS links to and from it bind nothing, FF / SF links still do);
suspended work resumes on its resume date; a constraint of the wrong kind on a milestone
is ignored; LOE late dates follow their links' late dates. What is still open is in
`docs/backlog.md`.

**2. Real P6 exports** with stored dates, exact clock time required (`tests/test_cpm.py`):

| File | Scheduled by | Activities | Values | Identical |
|---|---|---|---|---|
| Hotel Project | P6 6.0 | 4,217 (7,586 links; 11 calendars; holidays; ALAP; must finish by) | 25,302 | all |
| Terminal Building | P6 5.0 | 66 (SNLT, 7-day calendar, must finish by) | 396 | all |
| 20 kW PV plant | P6 25.12 | 25 | 150 | all |
| XER editor sample | P6 20.12 | 52, 10 of them level of effort | 252 | all |
| Hotel + Terminal assignments | P6 6.0 / 5.0 | 2,340 assignments | 9,360 | all |
| Longest path flag | Hotel, Terminal | 4,283 open activities | 4,283 | all |

All four are unstarted; the corpus covers what they do not. No P6 Professional 24 file is
public: 23.12 and 25.12 bracket it.

**3. MPXJ's `PrimaveraScheduler`**, a second engine written independently and tuned by
its authors against P6 (`tests/test_crosscheck_mpxj.py`, built from a pinned commit by
`tests/reference/mpxj_cpm.py`). It reproduces 99.96 % of Hotel and all of Terminal; on
random networks of every kind the two engines agree to the working minute outside the
cases named in `crosscheck.UNRESOLVED` (no P6 output settles them yet) and
`crosscheck.P6_SETTLED` (the corpus settled them against MPXJ). Where MPXJ contradicts
itself (`mpxj_inconsistent`) its value is discarded. MPXJ models P6's default options only.

| Open case (UNRESOLVED) | xerscope | MPXJ |
|---|---|---|
| FF / SF lag from a finished activity | expires from the actual date, as FS | counted from the data date (twice for FF) |
| SF into progressed work, or from a finished activity | one rule (below) | a per-status case table |
| lead from started or finished work | backward pass drops it (SS/SF) | differs by status |
| FF / SS / SF from a finished activity into started work | carried date + unexpired lag | actual dates |
| resource-dependent activity, resources on other calendars | each assignment starts on its resource calendar | starts on the activity calendar |
| assignment lag on a resource-dependent activity | in the activity dates | left out |
| free float with a lead, or of a mandatory-constrained activity | to the successor bound | 0 |
| lag calendar not stated in the file | successor's (Oracle) | predecessor's |

To check the engine on your own schedules: export a file after F9 in P6 and run
`xerscope recalc` on it; every stored date and float is compared to the minute.

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
| Compute total float as | `sched_float_type`: `FT_FF` finish float, `FT_SS` start float, `FT_Min` the smaller; `FT_Start`/`FT_Total` (imported codes) are reported as the finish float, as P6 23.12 does | Finish float |
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
    then pushes the successor further.
  - Backward pass: the same shortened lag (MPXJ does the same); a lead from started work
    is dropped.
- **SF from a started predecessor** to unstarted work binds nothing past the data date:
  it ties the finish to the predecessor's start, an actual in the past (as MPXJ).
- **Duration:** finish = start + remaining duration, in working minutes of the activity's
  calendar.
- **In progress:** the actual start is kept. The remaining work starts at the data date:
  - **Retained Logic** (default) and **Actual Dates**: it also waits for unfinished
    predecessors;
  - **Progress Override:** it ignores them;
  - **expected finish** (option "Use Expected Finish Dates"): the early finish is the
    expected finish and the remaining duration is recomputed from it, for the backward
    pass too; not for ALAP, nor with an FF / SF predecessor, nor before the early start
    or the data date (as MPXJ).
- **Complete:** shown with its actual dates. Under **Retained Logic** it passes logic
  through, as P6 does (MPXJ, issue #972, checked against real P6 schedules): it carries to
  its successors the date its own unfinished predecessors still impose (the data date if
  none), plus the part of a positive lag not yet expired since its actual finish (FS, FF)
  or start (SS, SF); a lead is dropped. With no out-of-sequence progress this is the same
  as "actual finish + lag". Under Actual Dates and Progress Override the actual dates
  drive and a finished predecessor no longer holds work in progress.
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
| any activity | finish ≤ the same project end: an activity whose successors only bound its start (SS, SF) would otherwise float past the end (MPXJ caps the same way; no P6 file has the case) |
| finished successor (Retained Logic) | its carried late date: FS drops the lag, FF keeps it, SS / SF keep it unless the predecessor started |
| Start on / Start on or before | start ≤ date |
| Finish on / Finish on or before | finish ≤ date |
| Mandatory | the date |
| Actual Dates option | a started successor bounds its predecessors by its *actual* dates: out-of-sequence progress gives the predecessor negative float, growing each period it stays open (Oracle warns of exactly this) |

Resource-dependent activities place each driving assignment's late finish on its
resource calendar the same way.

**Float.**

- **Total float** = late − early finish, in working hours of the activity's calendar.
  It uses the project's float type: finish float (default), start float, or the smaller.
- **Free float** = room to the earliest successor bound, using successors' early dates (a
  finished successor sits at its carried date). It can exceed total float when the late
  finish stops at the project end, as in MPXJ.
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
| late start from a start bound (SS / SF successor, start constraint) | the bound's own instant, the previous period end when it falls in non-working time (Fri 17:00, not Mon 07:00) | P6 23.12 corpus, H3-02 A1240 and 93 other values, under every lag calendar |
| start milestone, early | like a task start | xerlock MS-020: 08:00 the next morning |
| start milestone, late | kept as is if on a period edge, else the previous working time | Hotel HCMEB4000 16:00; xerlock MS-020 08:00 |
| finish milestone, early | kept as is if working time or a period edge, else next working time | Hotel: 16:00 right after its predecessor |
| finish milestone, late | a period end | Hotel |

## Conventions no reference file settles

- **Resource-dependent activity:** FF/SF bounds and the float are measured on the
  activity's calendar; the start is the earliest driving assignment start. The corpus
  agrees with 62 % of the values only; this is the engine's largest open area.
- **Start float vs finish float:** equal on task-dependent work (in P6 too); they differ
  on resource-dependent work only, where the float-type option decides.
- **LOE dates:** Oracle's and Boyle's descriptions, confirmed by the P6 20.12 export for
  early dates and by the corpus for late dates and float. LOE are excluded from INT-01.

## Property tests

`tests/test_cpm_properties.py` schedules 260 seeded random networks (all link types,
leads and lags, progress in logic sequence, every P6 option, every constraint type, three
calendars, LOE) and checks what any recalculation must satisfy: each relationship holds
on early and late dates; a task lasts its remaining duration early and late; total float
= late − early finish; free float ≥ 0; no negative float without constraints; zero float
on the longest path when nothing dangles; constraints hold in working time; with FS links
only, delaying an activity never brings the finish earlier (with FF it can: a longer
activity whose finish is fixed starts earlier and pulls its SS successors along).
Out-of-sequence progress, which legitimately gives negative float, is left to the MPXJ
comparison, which checks the values themselves, not only their consistency.

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
