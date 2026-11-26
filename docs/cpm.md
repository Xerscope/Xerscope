# The CPM engine (`analysis/cpm.py`)

`schedule(snapshot)` recomputes every activity's early and late dates, total and free
float, longest path and resource-assignment dates the way Primavera P6 Professional
(23.12 / 24) does when you press F9, from the logic, durations, calendars, constraints,
progress, assignments and scheduling options stored in the XER. It returns a `Schedule`:
one row per activity (`es`, `ef`, `remaining_start`, `ls`, `lf`, `tf_hr`, `ff_hr`,
`resource_dependent`, `longest_path`, `rem_override_hr`, the remaining hours an expected
finish set), the recalculated finish, the options read, the warnings and the assignment
dates. Resource-dependent placement is in `analysis/resource_placement.py` (pure
functions the engine calls).

It serves:

- **INT-01 / INT-03** (Integrity standard): are the stored activity and assignment dates
  what P6 would calculate now (`compare_with_stored`, `compare_assignments`)? If not, the
  file was edited after the last schedule, and every float-based check (P6 Large/Negative
  float, DCMA-06/07, the critical path) reads stale numbers. INT-07 and INT-08 read the
  recalculated dates too, and INT-04 names the activities on a logic loop with
  `loop_members`, the same set the engine refuses (`CycleError.members`).
- **The critical path test** (DCMA-12, DECM 06A401a): delay the first open activity of the
  longest path by 600 working days (`slip_days` in the standard), reschedule, check the
  finish moves (`critical_path_test`, below).
- **The longest path** (`analysis/longest_path.py`), the forensic comparisons
  (`analysis/forensics.py`) and the recalculation views of the app.

```bash
uv run xerscope recalc week42.xer                    # stored values reproduced per field, first differences
uv run xerscope recalc week42.xer --out recalc.csv   # + the recalculated dates and float, one row per activity
uv run xerscope recalc week42.xer --report           # + the differences grouped by activity shape
```

`--show N` sets how many differences are printed (20 by default), `--project` picks a
project in a multi-project file.

## Validation

Three sources, strongest first. None of them is xerscope's own output. Where two
disagree, P6 wins and the difference is recorded against the other.

**1. P6 Professional 23.12.1: the held-out corpus** (danafitkowski/cpp-cpm-engine, MIT,
pinned commit in `tests/reference/sources.py`; fetched by
`tests/reference/fetch_p6_heldout.py`, scored by `tests/test_p6_heldout.py` and
`xerscope crosscheck --p6`, both through `crosscheck.p6_heldout_score`). 30 sets of 12
synthetic schedules (H1–H30), frozen before P6 saw them, imported into P6, scheduled with
F9, early / late dates and floats read back from P6's database (359 cases carry P6's
results): progressed (in and out of sequence, suspended), constrained (every type,
mandatory dates, expected finishes), multi-calendar, level-of-effort and
resource-dependent work, under every scheduling option.

| Scope | Values | Identical to P6 |
|---|---|---|
| H1–H7: task-dependent work, every option, no LOE | 9,444 | 99.9 % |
| task-dependent work, all 30 sets | 41,868 | 99.7 % |
| resource-dependent work (P6's import sizing laid over the case) | 12,858 | 99.3 % |
| all | 54,726 | 99.6 % |

Dates agree on the same clock time, floats within 0.01 h. `FLOORS` in the test holds each
set's share (every set at 0.982 or more, H10 the lowest) and fails on any drop; `PINNED`
names the corpus activity each rule of the engine was taken from (67 rules, 136
witnesses), so a regression on one rule is named rather than averaged away. Rules taken
from the corpus include: float-type codes; an SF link from a started predecessor applies;
the expected finish stands in for start + remaining (remaining 0 when it falls before the
start, a later FF / SF bound wins); mandatory dates never put early dates before the data
date; a mandatory date in the second slot pins nothing; the project's late finish caps a
pinned date; work under way under a mandatory date takes the late dates of the network;
the late start an SS / SF bound gives is written at the bound's instant; lags into a
finished successor pass back in full (FS / FF) or unexpired (SS / SF); under Progress
Override the start of work under way is an actual (FS / SS links to and from it bind
nothing, FF / SF links still do) and an SS from a started predecessor is measured from
the data date; an external early start still binds work under way; suspended work
resumes on its resume date; a constraint of the wrong kind on a milestone is ignored;
LOE late dates follow their links' late dates; resource-dependent work takes its bounds
on the activity calendar and places each driving assignment from there (early and late),
with the expected finish measured on the resource calendar; "make open-ended activities
critical" never puts a late finish past the Must Finish By and counts any successor row
(finished, WBS summary) as a successor; As Late As Possible moves the remaining work of
started activities and holds no free float; an activity whose expected finish applies,
and unstarted work under a primary mandatory constraint, have no free float; a second
constraint tighter than a mandatory date still holds; an LOE's start-type link from a
started predecessor is measured from the data date and its late start never passes its
late finish. What is still open is in `docs/backlog.md`.

**2. Real P6 exports** with stored dates, exact clock time required (`tests/test_cpm.py`):

| File | Scheduled by | Activities | Values | Identical |
|---|---|---|---|---|
| Hotel Project | P6 6.0 | 4,217 (7,586 links; 11 calendars; holidays; ALAP; must finish by) | 25,302 | all |
| Terminal Building | P6 5.0 | 66 (SNLT, 7-day calendar, must finish by) | 396 | all |
| 20 kW PV plant | P6 25.12 | 25 | 150 | all |
| XER editor sample | P6 20.12 | 52, 10 of them level of effort | 252 (+ the 10 LOE's dates and floats) | all |
| Hotel + Terminal assignments | P6 6.0 / 5.0 | 2,340 assignments (2,278 + 62) | 9,360 | all |
| Longest path flag | Hotel, Terminal, PV, XER editor sample (LOE included) | 4,360 open activities | 4,360 | all |

All four are unstarted; the corpus covers what they do not. No P6 Professional 24 file is
public: 23.12 and 25.12 bracket it. The same test also runs xerlock's sample (synthetic,
dated by xerlock's own engine, the only reference under Progress Override); the three
values it stores against P6 23.12 are named in `NOT_P6`.

**3. MPXJ's `PrimaveraScheduler`**, a second engine written independently and tuned by
its authors against P6 (`tests/test_crosscheck_mpxj.py`, built from a pinned commit by
`tests/reference/mpxj_cpm.py`; `xerscope crosscheck --cpm`). On Hotel and Terminal it
matches P6 on more than 99.9 % of the values, and xerscope on every value it misses; on
random networks of every kind the two engines agree to the working minute outside the
cases named in `crosscheck.UNRESOLVED` (no P6 output settles them yet) and
`crosscheck.P6_SETTLED` (the corpus settled them against MPXJ: an SF from a started
predecessor, lag into a finished successor, an expected finish before the early start or
under an FF / SF predecessor). Where MPXJ contradicts itself (`mpxj_inconsistent`) the
difference is not counted against either engine. MPXJ models a subset of P6's options;
`mpxj_unsupported` names a file it cannot compare: progressed activities under Actual
Dates or Progress Override, SS lag from Actual Start, open ends critical, no lag calendar
stated (P6 uses the successor's, MPXJ the predecessor's), relationships to other projects
ignored, a non-driving assignment on resource-dependent work.

| Open case (`UNRESOLVED` key) | xerscope | MPXJ |
|---|---|---|
| `ff_sf_lag_from_finished`: FF / SF lag from a finished activity | expires from the actual dates, as FS | counted from the data date (twice for FF) |
| `sf_progressed`: SF into progressed work, or from a finished activity | one rule (below) | a per-status case table |
| `lead_from_progressed`: a lead from finished work, or an FS / FF lead from started work | backward pass drops it | differs by status (SS / SF leads from started work agree) |
| `finished_into_started`: FF / SS / SF from a finished activity into started work | carried date + unexpired lag | differs |
| `rsrc_calendar`: resource-dependent activity, resources on other calendars | bound on the activity calendar, each assignment from there on its resource calendar (corpus H8-03 A1240) | starts on the activity calendar |
| `assignment_lag`: assignment lag on a resource-dependent activity | in the activity dates | left out |
| `free_float_lead`: free float with a lead to a successor | to the successor bound | differs |
| `free_float_mandatory`: free float of an activity with a mandatory constraint | 0 on unstarted work under a primary Mandatory Start / Finish (corpus), else to the successor bound | differs |

To check the engine on your own schedules: export a file after F9 in P6 and run
`xerscope recalc` on it; every stored date and float is compared to the minute.
`--report` groups the differences by the shape of the activity (`verify/shapes.py`:
status, type, constraints, expected finish, predecessor and successor link kinds, lag,
progressed-activities option): one shape with every value wrong is one rule to fix, with
the stored dates as the answer.

## Time: `TimeAxis` (`xer/calendar.py`)

A calendar is turned into a sorted array of working periods in absolute minutes, with the
cumulative working minutes at each period start. Two functions do all the arithmetic:

- `work(ts)`: working minutes from the axis anchor to `ts`. Non-working time maps to the
  next period's start, so the function is monotone and continuous.
- `at(w, finish)`: the inverse. On a boundary, Monday 17:00 and Tuesday 08:00 are the same
  working minute; `finish=True` returns the period end, `finish=False` the next start.

Everything else is built on these two, by binary search (`numpy.searchsorted`, `bisect`
for a single value):

- `add(ts, minutes, finish)`: adding or subtracting duration, `at(work(ts) ± d, …)`;
- `between(a, b)`: working minutes between two dates, `work(b) − work(a)`;
- `snap_start`, `snap_finish`, `keep_or_next`, `keep_or_previous`: snapping a date to
  working time;
- `work_many`: `work` for an array (PV curves, variances, `Snapshot.work_hours`).

The axis extends itself when a date falls outside it (a 600-day delay runs years ahead,
negative float runs back before the data date), up to the dates pandas can hold
(1677–2262); beyond them the engine raises `ScheduleError`. Work values stay anchored on
the first origin, so a value computed before the axis grew is still valid after it.

Calendars come from `CALENDAR.clndr_data`: the work week (P6 numbers days 1 = Sunday to
7 = Saturday) and the exceptions (Excel serial dates; an empty exception is a holiday, one
with periods is a working day with its own hours). If the blob is missing or has no
working weekday, the work week is inferred from `day_hr_cnt` and `week_hr_cnt` (days from
08:00; the blob's exceptions are kept).

## Options read from the file (P6 Professional 24, Schedule Options › General)

`Options.from_snapshot` reads them from `SCHEDOPTIONS` and `PROJECT`; a file without a
SCHEDOPTIONS row for the project is scheduled with P6's defaults, with a warning.

| Option | XER | Default when blank (Oracle) |
|---|---|---|
| When scheduling progressed activities use (`progressed`) | `sched_retained_logic`, `sched_progress_override` (both `N` = Actual Dates) | Retained Logic |
| Calculate start-to-start lag from (`lag_from_early_start`) | `sched_lag_early_start_flag` | Early Start |
| Calendar for scheduling relationship lag (`lag_calendar`) | `sched_calendar_on_relationship_lag`: `rcal_Successor`, `rcal_Predecessor`, `rcal_24Hour`, `rcal_ProjDefault` | **Successor** activity calendar |
| Compute total float as (`float_type`, `FLOAT_TYPE`) | `sched_float_type`: `FT_FF` finish float, `FT_SS` start float, `FT_Min` the smaller; `FT_Start`/`FT_Total` (imported codes) are reported as the finish float, as P6 23.12 does | Finish float |
| Make open-ended activities critical (`open_critical`) | `sched_open_critical_flag` | no |
| Use expected finish dates (`use_expected_finish`) | `sched_use_expect_end_flag` | yes |
| Ignore relationships to and from other projects (`honor_external`) | `sched_outer_depend_type`: `SD_Both` honours the stored external dates, any other value ignores them | honoured |
| Calculate multiple float paths | `enable_multiple_longest_path_calc` | no (see Not modelled) |
| Must finish by (`must_finish_by`) | `PROJECT.plan_end_date` | none |
| (export version, `collapse_early_expected_finish`) | ERMHDR major version: below 26 or absent, an expected finish earlier than the early start brings the remaining to 0; 26 and above, it is ignored (Snapping) | below 26 |

Lag entered in days is converted to hours on the **predecessor's** calendar (Oracle),
whatever calendar the lag is then scheduled on: `relationships.lag_d` uses it.

## Algorithm

**Graph.** Activities are matched by Activity ID. Level-of-effort activities are taken out
of the network (their dates come last, from their links); a link between two LOEs is
ignored with a warning, and so is a link of an unknown type. The others are put in
topological order (Kahn's algorithm). A logic loop raises `CycleError`, whose `members`
are the activities on the loop (Tarjan's strongly connected components), not those
downstream of it. A remaining duration, lag, assignment duration or delay that is not
finite or exceeds `MAX_HOURS` (10⁶ h) raises `ScheduleError` before the passes run. On
load the model already reads such a remaining duration or relationship lag as 0, with a warning
(`validate.usable_hours`), so from a loaded file only an assignment's lag or duration or
a requested delay can reach that error. A negative remaining duration is read as 0
(warned).

**Earliest start.** `max(data date, project planned start)`. P6 never schedules remaining
work before either.

**Forward pass (early dates)**, for each activity in topological order:

| Bound | Rule |
|---|---|
| FS | start ≥ pred finish + lag |
| SS | start ≥ pred start + lag (started predecessor: see below) |
| FF | finish ≥ pred finish + lag |
| SF | finish ≥ pred start + lag (started predecessor: see below) |
| Start on / Start on or after | start ≥ date |
| Finish on / Finish on or after | finish ≥ date (dropped when an expected finish applies to work not started) |
| Mandatory start / finish (primary slot) | the date, whatever the logic, except that the early dates never fall before the data date; a Mandatory Finish no longer pins when an expected finish applies. In the second slot, on work not started, it is scheduled as a Start On / Finish On and pins nothing |
| Second constraint beside a Mandatory Start | bounds on top of it: the later of the two dates |
| External early start (link to a project not in the file) | start ≥ date, also for work under way under Progress Override, which frees it from the links of this project only (H8-08 A1020, H10-12 A1130, H15-09 A1110) |
| Suspended work | start ≥ its resume date (H8-07 A1020) |

- **Lag calendar:** lags are added on the calendar the project names.
- **SS / SF lag of a started predecessor** (Oracle, "Calculate start-to-start lag from"):
  - *Early Start* (default): expired lag = working time from the predecessor's actual
    start to the data date; successor bound = the predecessor's remaining early start +
    the lag not yet expired. Under Progress Override it is measured from the data date
    (H17-10 A1270).
  - *Actual Start*: bound = actual start + lag, i.e. the data date plus the remaining lag
    (a finished predecessor's actual start too, H6-07 A1190). Under Actual Dates the
    option is disabled: actual start.
  - The two differ when the predecessor is itself held back (retained logic): Early Start
    then pushes the successor further.
  - Backward pass: the same shortened lag (MPXJ does the same); a lead from started work
    is dropped.
- **SF from a started predecessor** applies, from the predecessor's remaining early start
  plus the unexpired lag (corpus H1-08 A1240; MPXJ binds nothing, `P6_SETTLED`). Under
  Progress Override an SF from work under way binds nothing (H10-02 A1250).
- **Duration:** finish = start + remaining duration, in working minutes of the activity's
  calendar.
- **In progress:** the actual start is kept. The remaining work starts at the data date:
  - **Retained Logic** (default) and **Actual Dates**: it also waits for unfinished
    predecessors;
  - **Progress Override:** its start is an actual, so FS / SS predecessors no longer bound
    it; FF / SF predecessors still bound its finish (H1-11 A1040);
  - its constraints are not applied in the forward pass (reported in `warnings`).
- **Expected finish** (option "Use Expected Finish Dates"; `expected_finish`): on
  task-dependent work, not As Late As Possible, the expected finish stands in for start +
  remaining duration: the early finish is the expected finish, or the early start when it
  falls before it (remaining 0), and the remaining duration is recomputed from it, for the
  backward pass too (`rem_override_hr`). An FF / SF bound later than it wins, with the
  file's remaining duration (H24-07 A1210). An unstarted milestone sits at the later of
  its logic and its expected finish.
- **Complete:** shown with its actual dates. Under **Retained Logic** it passes logic
  through, as P6 does (MPXJ, issue #972, checked against real P6 schedules): it carries to
  its successors the date its own unfinished predecessors still impose (the data date if
  none), plus the part of a positive lag not yet expired since its actual finish (FS, FF)
  or start (SS, SF); a lead is dropped; between two finished activities only the carried
  date passes. With no out-of-sequence progress this is the same as "actual finish +
  lag". Under Actual Dates and Progress Override a finished predecessor bounds unstarted
  work by its actual dates + lag and no longer bounds the start of work under way (under
  Progress Override its FF / SF links still bound the finish).
- **Resource dependent** (`TT_Rsrc`, Oracle: "scheduled according to the calendars for
  the resources … the latest finish date of all driving resources is used for the early
  finish"), as the corpus shows P6 23.12 placing it (`rsrc_early`): the logic's bound is
  taken on the activity's own calendar; each driving assignment (`rollup_dates_flag`) is
  placed from there on its resource's calendar (`RSRC.clndr_id`), plus its lag, for
  remaining units / units per hour (without a rate, the working time of its own remaining
  window: H25-09 A1480), and pushed back behind a later finish bound; the activity starts
  at the earliest assignment start, on its own calendar, and the assignments then run
  forward from that start (a finish bound is met, not tight). P6 places the work a second
  time from the activity calendar's next opening and shows that placement
  (`first_placement`). An expected finish measures the remaining work on the resource
  calendar from the first placement, and applies even when it falls on the finish the
  units and rate give (no free float: H26-03 A1300, H29-02 A1300, H29-10 A1410, H30-06
  A1260, H30-12 A1600); one before the start keeps the file's remaining
  duration. A finish constraint on unstarted work moves it by its start
  (`moved_by_finish_floors`). Without a driving assignment that has a duration the
  activity is scheduled on its own calendar (warned). Witnesses: H8-03 A1240, H10-02
  A1360, H26-11 A1090, H14-05 A1040.

**Backward pass (late dates)**, in reverse order:

| Bound | Rule |
|---|---|
| FS | finish ≤ succ late start − lag |
| SS | start ≤ succ late start − lag |
| FF | finish ≤ succ late finish − lag |
| SF | start ≤ succ late finish − lag |
| no open successor | finish ≤ project "must finish by" if set, else the latest early finish; with "make open-ended activities critical", an activity without any successor row ends at its own early finish, never past the Must Finish By (H25-05 A1380); one whose successors bind nothing (finished, WBS summary) is not open-ended (H27-04 A1390) |
| any activity | finish ≤ the same project end: an activity whose successors only bound its start (SS, SF) would otherwise float past the end (MPXJ caps the same way; no P6 file has the case) |
| external late finish (link to a project not in the file) | finish ≤ date, unless relationships to other projects are ignored |
| finished successor (Retained Logic) | its carried late date: FS / FF pass the lag back in full (H1-08 A1020), SS / SF the part not yet expired (H6-07 A1030), nothing between two finished activities (H1-08 A1050) |
| Progress Override, started successor | FS / SS links to it bind nothing (its start is an actual, H5-06 A1030); FF / SF still do (H3-03 A1030) |
| Start on / Start on or before | start ≤ date |
| Finish on / Finish on or before | finish ≤ date |
| Mandatory (primary slot, work not started) | the date, capped by the project's late finish (the float then goes negative; H12-09 A1330); a second constraint of the same end that is tighter still holds (H23-08 A1220), and under a Mandatory Start a finish date in the second slot too (H26-08 A1280); with an expected finish in force the Mandatory Finish no longer pins: the late finish is the lesser of the successors' bound and the date (H23-03 A1210, H25-05 A1150) |
| work under way | no mandatory date bounds its late dates (H3-02 A1050); a Start On or Before, Mandatory Start or Mandatory Finish in either slot drops both constraints from the backward pass; otherwise its finish constraints hold |
| Actual Dates option | a started successor bounds its predecessors by its *actual* dates: out-of-sequence progress gives the predecessor negative float, growing each period it stays open (Oracle warns of exactly this) |

Resource-dependent activities mirror the forward pass: the late bounds are taken on the
activity calendar first, then each driving assignment runs back on its resource calendar
(`place_backward`; H10-04 A1220, H8-11 A1040, H9-08 A1230); a late start an SS bound
drives is written at the bound's instant, as on task-dependent work (H26-04 A1440); their
late finish stays capped by the Mandatory Finish under an expected finish (H25-05 A1150).

**Float.**

- **Total float** = late − early finish, in working hours of the activity's calendar.
  It uses the project's float type: finish float (default), start float, or the smaller.
- **Free float** = room to the earliest successor bound, using successors' early dates (a
  finished successor sits at its carried date). It can exceed total float when the late
  finish stops at the project end, as in MPXJ.
  For an open end, it runs to the project's early finish (not to "must finish by":
  Terminal shows 8 h of total float but 0 free float). Under Progress Override, work
  under way runs past its own SS / SF links and past finished successors (H2-04 A1110,
  H2-05 A1030). None, whatever its successors' dates, for: an activity whose expected
  finish is in force, whether or not it sets the duration (corpus, 707 of 707 such
  values: H1-08 A1090, H5-01 A1120); unstarted work under a primary Mandatory Start /
  Finish (508 of 508); As Late As Possible work, unless the project calculates multiple
  float paths (H23-02 A1220). Observed, not explained.
- **As late as possible:** in reverse order, an ALAP activity moves right to use its free
  float, against its successors' already moved dates; the remaining work of a started
  ALAP activity moves the same way (H27-05 A1170). Free float is measured after that, as
  P6 shows it: Hotel's chained ALAP activities pin this.

**Longest path** (Oracle: "activities that have an early finish equal to the latest
calculated early finish for the project and tracing all driving relationships for those
activities back"): from the open activities finishing last, walk back through every
relationship from an unfinished predecessor whose bound reaches the successor's
remaining start (FS / SS) or early finish (FF / SF), in working time of the successor's
calendar. Under Progress Override work under way has no driving predecessor. When only
milestones (start or finish) set the project finish, an activity with no working minute
of its calendar before that finish also ends the project (Friday 17:00 before a milestone
written Monday 08:00; to test in P6); when the milestone is on another calendar, the gap
is still read on the activity's own calendar, with a warning. A level-of-effort activity is on the path when one
of its links into a path activity drives that activity's date (the P6 20.12 export flags
its ten LOEs, each spanning two activities of the path); the trace stops at the LOE,
whose own dates come from its links.

**Driving relationships** (`Schedule.links`, P6's Driving checkbox of the Relationships
tab; Oracle web services, Relationship.Driving: "determines the early dates for the
successor activity"). P6 does not export the flag (XER data map, TASKPRED). A link from an
unfinished predecessor into unfinished work drives when the date it allows reaches the
successor's remaining start (FS, SS) or early finish (FF, SF), in working time of the
successor's calendar; past a mandatory start or finish it does not (the constraint sets the
date; corpus H10-04 A1310). Checked against P6's own relationship date, TASKPRED.aref, which
P6 writes on every link of the Hotel, Terminal, PV and xereditor exports (the corpus leaves
it blank): the link drives exactly when aref reaches the successor's remaining start, 7,742
links of 7,742, As Late As Possible successors included (tests/test_driving.py). Links of a
level-of-effort activity place the LOE and are not listed. Only the plain recalculation
(the one cached on the snapshot) lists them; a delayed run (critical path test, what-if) does not. Open: a successor whose date
no link reaches (MPXJ marks its latest predecessor driving; UNRESOLVED
`driving_held_by_data_date`).

**Assignments.** Task dependent: remaining start = the activity's remaining start +
assignment lag, finish = start + remaining units / units per hour (else the activity's
remaining duration), on the activity calendar; late dates likewise from the late start.
Exactly what P6 stored on 2,340 Hotel and Terminal assignments. Resource dependent: the
dates the passes placed each driving assignment at.

**Level of effort.** Each relationship ties the end of the LOE it names. Start-type ends
(SS / FS predecessors, SS / SF successors) give its start, the earliest of them, never
before the data date; finish-type ends (FF / SF predecessors, FF / FS successors) its
finish, the latest (tied to none: the project finish). An FF predecessor and an FF
successor to the same activity give the same finish, as Boyle shows in P6 ("Constructing
LOE activities in Primavera P6"). An LOE under way shows its actual start. A start-type
link from a started predecessor is measured from the data date plus the unexpired lag
(H10-01 A1300); the late start never passes the late finish (same case). A finished
task's actual finish holds the late start of an FS link, the late date a finished
activity passes back that of an SS link (conventions below). Free float 0. It drives
nothing.

**No data date.** P6 always stores one. A file without a data date and a planned start
is scheduled from the earliest activity date it carries, with a warning; with no date at
all `ScheduleError` is raised.

## Snapping: how a computed instant is written

The same working minute can be written two ways (Monday 17:00 or Tuesday 08:00). P6's
choice matters, because a later lag on another calendar starts from the written time.
Each rule below is pinned by a real file (`_early`, `_late`, `expected_finish`):

| What | Rule | Evidence |
|---|---|---|
| task start | the start of a working period (a predecessor ending 17:00 → next morning) | all files |
| task finish | the end of a working period | all files |
| early finish pushed by FF/SF/finish constraint into non-working time | the next working time | Hotel HCSWB3Z2190: 30 Oct 08:00 after the Eid holidays, not 24 Oct 16:00 |
| late finish | a period end (a successor starting 08:00 → previous evening) | all files |
| late start from a start bound (SS / SF successor, start constraint) | the bound's own instant, the previous period end when it falls in non-working time (Fri 17:00, not Mon 07:00) | P6 23.12 corpus, H3-02 A1240, under every lag calendar |
| start milestone, early | like a task start | xerlock MS-020: 08:00 the next morning |
| start milestone, late | kept as is if working time or a period edge, else the previous working time | Hotel HCMEB4000 16:00; xerlock MS-020 08:00 |
| finish milestone, early | kept as is if working time or a period edge, else next working time | Hotel: 16:00 right after its predecessor |
| finish milestone, late | a period end | Hotel |
| task with no remaining duration (not a milestone) | early dates at a period start, late dates at a period end: the evening before an FS successor's 08:00 late start | P6 Professional 24 export (three open activities, FS successors); SS / FF / SF bounds unverified |
| expected finish earlier than the early start (task-dependent, no FF / SF predecessor, no ALAP) | ERMHDR major version < 26 (or absent): remaining brought to 0, EF = ES; ≥ 26: expected finish ignored, EF = ES + the stored remaining (`Options.collapse_early_expected_finish`, `KEEP_EARLY_EXPECTED_FINISH_FROM`) | < 26: P6 23.12 corpus, H1-02 A1170 (94 of 94 cases). ≥ 26: 26.x project exports (26.5 / 26.8, Project Management Cloud), 112 cases over 14 updates, all FS lag 0, no ALAP; source level observed. 24 / 25 unverified |
| expected finish off the activity's calendar (a holiday, a weekend, after hours) or on a period start | the expected finish ends the previous working period before the remaining is derived from it (08:00 -> 17:00 the day before); an FF bound is compared with it in working time | 26.x project exports: 4 activities on 2 calendars (finish 31 Dec in a Christmas break stored 24 Dec 17:00; 17:48 stored 17:00); source level observed |

## Conventions no reference file settles

- **Resource-dependent activity:** bounds are taken on the activity's calendar, the
  float is measured on it; each assignment is placed on its resource calendar from the
  activity's start. The corpus agrees with 99.3 % of the values; this is the engine's
  largest open area (docs/backlog.md).
- **Start float vs finish float:** equal on task-dependent work (in P6 too); they differ
  on resource-dependent work only, where the float-type option decides.
- **LOE dates:** Oracle's and Boyle's descriptions, confirmed by the P6 20.12 export for
  early dates and by the corpus for late dates and float. LOE are excluded from INT-01.
- **LOE late start behind a finished task:** an FS link from a finished task (not a start
  milestone) holds the late start at its actual finish plus the lag, written at the next
  working start, never past the late finish. Witnesses: H14-07 A1170, H18-09 A1340, H25-01 A1380,
  H9-04 A1390 (14 of 14 such tasks with clean neighbours; observed, no Oracle page states
  it). A finished start milestone holds nothing (H16-02 A1290, H10-11 A1210); H8-02 A1250
  is still open.
- **LOE late start behind a finished SS predecessor:** an SS link from a finished activity
  holds the late start at the late date that activity passes back to its other successors
  (`lcarry`, Retained Logic) plus the lag, never past the late finish. Witnesses: H8-07
  A1230, H12-12 A1330, H26-11 A1220, H8-02 A1240 (observed, no Oracle page states it).
- **An activity whose `clndr_id` is not in the file's CALENDAR table:** read on the
  project's calendar, then the file's first calendar, then the standard one
  (`Snapshot.calendar`, `_BuildInputs.fallback_hours_per_day`), and the file is flagged in
  `warnings`. No Oracle page states this case, and no reference file contains it (0 of 394,
  every one of which carries a CALENDAR row for each calendar its activities name), so a
  real P6 export is not expected to produce it. MPXJ resolves it the same way:
  `PrimaveraReader` leaves the task calendar null for an unknown id
  (`primavera/TableProjectReader.java`), and `Task.getEffectiveCalendar` falls back to
  `ProjectFile.getDefaultCalendar`, then `ProjectCalendarContainer.findOrCreateDefaultCalendar`
  (named calendar, else the first one, else a created default). A P6 Professional 24 export
  of such a file would settle it; until then the rule comes from a reimplementation, not
  from Oracle.

## Property tests

`tests/test_cpm_properties.py` schedules 260 seeded random networks of 14 activities.
180 of them (60 unstarted, 60 progressed, 60 with FS links and no lead, half of these
progressed; elsewhere all link types, leads and lags; milestones; any progress in logic
sequence) are checked for what any recalculation must satisfy: each relationship holds on early and late dates; a task lasts
its remaining duration early and late; total float = late − early finish; free float ≥ 0;
no negative float without constraints; zero float on the longest path when nothing
dangles; constraints hold in working time; with FS links only, delaying an activity never
brings the finish earlier (with FF it can: a longer activity whose finish is fixed starts
earlier and pulls its SS successors along). The other 80 run the P6 options in turn, every
constraint type, three calendars and LOE, with progress that may be out of sequence; they
check only that the schedule completes and that the constraints hold in working time.
Out-of-sequence progress, which legitimately
gives negative float, is left to the MPXJ comparison, which checks the values
themselves, not only their consistency.

## Critical path test

`critical_path_test(snapshot, delay_days)`. The delayed activity is the first open one
(by remaining start, then Activity ID; milestones and LOE are not delayed) on the
recalculated longest path, not "total float ≤ 0": with negative float that takes in less
critical paths, whose delay is partly absorbed. The delayed activity drops its expected
finish, which would absorb the delay. The finish is the latest early finish of the end
points (activities no work other than a level of effort follows), measured on the
delayed activity's calendar.

Pass = the whole delay reached the finish (it can move further when the path crosses
calendars with other non-working days: Hotel moves +611 wd for +600; read in calendar
days, the finish moved at least as much as the delayed activity's own finish), or part of
it did and nothing stopped the rest: the end points that finish the plain schedule moved
and no expected finish downstream gave up remaining duration. Fail = those end points do
not move (nothing follows the delayed finish, or a mandatory date or a link that binds
nothing stops the delay), or an expected finish absorbs part of it; the note names the
mandatory-constrained activities and the expected finishes that may hold it back
(`CptResult.blocking`).

## Not modelled

These are reported in `warnings`, not computed:

- leveling: detected when an open activity's stored remaining early start differs from
  its early start (`xer.model.leveled`, a load warning that `xerscope recalc` repeats);
- multiple float paths: the dates and floats are computed, the float path numbers
  (`float_path`, `float_path_order`) are not.

Also warned: constraints on work under way (the forward pass keeps the actual start; no
reference file covers the case), work under way without an actual start, finished work
without actual dates, links between two LOEs, links of an unknown type.

Relationships to projects that are not in the file are honoured through the external
early start and late finish P6 stored on the activity (a warning names the activities they
bound). Links to other projects that are in the file are read (`Snapshot.external_links`),
but no reference file has them, so they are not used as logic. In
`Snapshot.relationships` such a predecessor is named `[ext]{task_id}`, so the engine
never confuses it with a local activity that has the same Activity ID
(`tests/test_cpm.py`).

## Performance

The plain recalculation (file options, no delay) is cached on the snapshot, and so is
its comparison with the stored dates (`compare_with_stored`): INT-01, INT-03, the other
integrity checks, the critical path test and the app's views share them, and each call
gets its own copy, so an edit by one caller never reaches the cache. The snapshot is
immutable; an edited one is a new snapshot (`dataclasses.replace`) with an empty cache.
The critical path test adds one more run.
