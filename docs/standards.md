# Standards in xerscope

Built in: **P6 Check Schedule** (P6 Professional 24), **DCMA DECM v8.0** (the schedule
metrics DCMA applies from FY2026), **DCMA 14-Point** (legacy, still the common screen),
**Integrity** (does the file match a P6-exact recalculation) and **your own standard**.
All are TOML files (`src/xerscope/standards/`). The four built-in ones name one explicit
function per check (`analysis/p6/`, `dcma/`, `decm/`, `integrity.py`) and the TOML only gives
each its target; your own standard picks parameterised rules from `analysis/rules.py` and sets
their parameters, population and target.

GAO-16-89G and NDIA PASEG v6.0 are out of scope for now (notes at the end).

## Same check, several definitions

| Check | P6 Check Schedule | DCMA 14-Point | DECM v8.0 |
|---|---|---|---|
| Units | hours (limit `x` in `p6.toml`) | working days of each activity's calendar | working days |
| Activities checked | WBS summary and actual-finished removed; LOE removed for constraints, float, durations, BEI; completed activities stay in for resource / cost | incomplete activities; LOE and milestones excluded (PAM 200.1 §4.0) | incomplete (no actual finish) tasks and milestones; LOE per metric |
| Relationships checked | all except links between two finished activities; a link from another project counted only when that project is in the file (UNRESOLVED, below) | links into incomplete work, a predecessor in another project of the file included | links into incomplete work |
| Logic | open ends; an actual start passes the predecessor check, start and finish milestones are counted (101248 exempts start milestones, P6 Professional 26.8 and r22.12 reports do not), external links pass | open ends of incomplete non-milestone tasks (PAM 200.1 §4.1); no exemption, no dangling | 06A204b: open start = only FF/SF predecessors or none; open finish = only SS/SF successors or none; a milestone only needs one link; started tasks count; earliest baseline start / latest baseline finish of the whole IMS (LOE included, ties share it) exempt |
| Hard constraints | Mandatory Start, Start On, Mandatory Finish, Finish On (P6 Professional; EPPM counts the two Mandatory only) | MSO, MFO, SNLT, FNLT and mandatory | Mandatory Start, Mandatory Finish (Primavera), target 0 % |
| Lags | links with a positive lag | links with a positive lag | activities with ≥ 1 lagged predecessor, ≤ 10 % |
| Long durations | remaining > `x` hours, milestones out | original > 44 wd | n/a |
| Out of sequence | n/a | n/a | 06A212a: relationships from an incomplete predecessor, actual else forecast dates, X = 0 |
| BEI | completed / every baseline activity, whatever its baseline finish (P6 Professional report; 101248 says those due only) | an activity without a baseline finish counts as due (PAM 200.1 §3.1.2.4, "Tasks missing baseline finish dates are included in the denominator", read as "with no baseline finish"; `UNRESOLVED`: "missing" could mean "missed") | n/a (EVMS cost metrics) |

These differences change results on real files: see `tests/test_rules.py` for one
hand-made schedule per difference.

## P6 Check Schedule (P6 Professional 24: 17 checks, 18 report lines)

Order and groups of the P6 Professional 24 User Guide (Check Schedule, page 101393).

**Baseline for P6-12 and P6-13: choose "Planned dates in each file (target_*)".** P6's "BL Project
Start / Finish" are the Planned Start / Finish of the project baseline, and when the project is its
own baseline they are the file's own planned dates. P6 moves the planned dates of a not-started
activity with the schedule and freezes them when the activity starts, so only activities in progress
(or finished) can drift from them. Checked against report R1 (see Sources): with this choice Late
Activities lists the same activities with the same finish variance (to the hour) and BEI gives the
same ratio; with the project's own current dates or another baseline file it does not.
Populations from the P6 Professional 24 help of the Check Schedule dialog
([101248](https://docs.oracle.com/cd/F88968_01/client_help/en_US/101248.htm)); where it is
silent, from the P6 EPPM help of each report section (pages 46277–46291), which differs in
four places: EPPM lets finish milestones pass the logic successor check, removes completed
activities from late activities, counts an activity with no baseline finish as due in BEI,
and reads the remaining finish of in-progress work for invalid dates. Where 101248 is
silent and a P6 Professional r22.12 report analysed by Ten Six shows the behaviour
(finish milestones counted in logic, milestones out of large durations), the report is
followed. Where report R1 contradicts 101248, the report is followed:
P6-12 leaves completed activities out, P6-13 divides by every baseline activity.
A P6 Professional 26.8 report on the synthetic project of `tests/test_p6_checksched.py`, which
anyone can rebuild, shows the same three populations. P6-04: 1 / 11, its 14 activities less 2
milestones and 1 completed. P6-12: 2 / 11, the completed activity out. P6-13: BEI 1 / 12, every
non-milestone activity, where 3 were due by the data date.
Unresolved: both reports measure a project that is its own baseline. Ten Six reads an r22.12 report
with a separate baseline at 6 / 6 where 11 were due (https://tensix.com/using-the-p6-check-schedule-tool/),
which fits neither the help text nor these reports. The P6 26.8 report of a project with a separate
baseline assigned, holding a baseline activity that finishes after the data date and one finished early,
settles whether every baseline activity is counted there too. Without a data date P6-13 stays n/a: the
help defines it against the data date and no report exists for that case.
Invalid Progress Dates is one check of the dialog but two lines of the report (before / after the data
date, each with its own target, P6 Professional 26.8): P6-10a and P6-10b.
P6-15 to P6-17 (out of sequence, dangling start, dangling finish) are not in 101248; they
are written from R1 alone, and their open points are marked `UNRESOLVED` in the
rule docstrings (`analysis/p6/check_schedule.py`). Among them: P6-16 and P6-17 read only the
relationships between activities of the project, so a link to an activity of another project
neither makes a task dangling nor drives it, whereas P6-01 lets such a link pass (46291). The
Dangling help (113174, 101496, 101497) does not say how P6 treats it; the current reading is pinned by
`test_p6_16_and_17_do_not_read_links_to_other_projects` until a P6 report on a schedule with external
FS / FF links settles it. Both checks also leave completed tasks out of the numerator: no Oracle
text says so (113174 names in-progress tasks only, for Dangling Start), and the 26.8 report's one
completed task has FS logic on both sides, so it does not tell. Pinned by
`test_p6_16_and_17_never_count_a_completed_task`; settled by a P6 report on a completed task with
FF-only predecessors and one with SS-only successors.
P6-01 reads 46291 ("Activities with external predecessors or successors pass the check") link by
link: an external predecessor satisfies the predecessor test only, an external successor the successor
test only. The sentence could also mean that any external link passes the whole check; no report in
hand shows it. Pinned by `test_p6_01_external_link_passes_only_its_own_end`.
P6-16 / P6-17 leave milestones out because R1 shows 0 for milestones with FF / SS logic only; those
milestones carried Start on or after constraints, which "Ignore activities with soft constraints"
(113174) would also leave out of P6-17, and R1 does not record the options. The exclusion is a
reading until a report with the options unchecked shows it (`test_p6_16_and_17_leave_milestones_out`).
P6-15 reads FS and SS links between activities of the project; FF, SF and links to other projects
are not read (`test_p6_15_reads_fs_and_ss_links_inside_the_project_only`).
The relationship checks (P6-05, P6-07, P6-08, P6-09) count the links into the project's activities.
A link from an activity of another project is counted when that project's activities are in the
file (the predecessor reads `[ext]<task_id>`), and dropped when they are not
(`Snapshot.external_links_dropped`): the same project gives two denominators depending on what the
export holds. Oracle's relationship sections (113174, 46287–46290) say nothing about external links,
and the report lists "Projects Checked Have Links to the Following Closed Projects" without saying
whether those links are counted. Until a P6 report settles it, each check's note gives both numbers
(`test_relationship_checks_say_which_external_links_they_hold`). A link to a successor in another
project belongs to that project's relationships, never to this one's.
The subset column is the dialog help (101248) or, where that is silent, the EPPM help of
the report section (pages 46277–46291). Every percentage = items found / items in the
checked subset.

| ID | Group | Check | Subset (Oracle) | Default target (P6 dialog) |
|---|---|---|---|---|
| P6-01 | Inflexibility and Inefficiency | Logic | WBS summary, actual finish removed; start exemptions above; finish milestones counted (101248; Ten Six report) | < 5 % |
| P6-02 | | Hard constraints (Mandatory Start/Finish, Start On, Finish On) | WBS, actual finish, LOE removed; start constraints ignored once started | < 1 % |
| P6-03 | | Soft constraints (On or Before/After, As Late As Possible) | idem | < 5 % |
| P6-04 | | Large durations (remaining > `x` hours) | WBS, actual finish, LOE, milestones removed (26.8 report) | < 5 % |
| P6-05 | | Long lags (> `x` hours) | links, both-finished removed | < 5 % |
| P6-06 | | Large float (> `x` hours) | WBS, actual finish, LOE removed | < 1 % |
| P6-07 | | Relationship types (FS share) | links, both-finished removed | > 90 % |
| P6-08 | | Lags | idem | < 5 % |
| P6-09 | Inaccuracy | Negative lags | idem | < 1 % |
| P6-10a | | Invalid progress before data date (start, or remaining early start once started, before the data date) | WBS, LOE, finished-before-data-date removed | < 1 % |
| P6-10b | | Invalid progress after data date (actual start or finish after the data date) | idem | < 1 % |
| P6-11 | | Resource / cost | WBS, milestones, LOE removed (completed stay in); a role assignment counts | < 1 % |
| P6-12 | Lateness | Late activities (finish variance < 0, working time; no baseline: finish later than planned finish) | WBS, milestones, LOE, completed removed (R1; 26.8 report) | < 5 % |
| P6-13 | | BEI: completed / every baseline activity (R1; 26.8 report); listed: due by the data date and not completed | WBS, milestones, LOE removed on both sides | > 0.95 (report R1; EPPM help: 0.95 or greater) |
| P6-14 | | Negative float | WBS, actual finish, LOE removed | < 1 % |
| P6-15 | Inaccuracy | Out of sequence (started; an FS predecessor not completed at the data date, or an SS predecessor not started) | all activities; one row per activity and predecessor, counted once per activity | `p6.toml` |
| P6-16 | | Dangling start (predecessors exist, none FS or SS) | all activities; completed and milestones not counted, in progress not counted while `ignore_in_progress` is on (R1) | `p6.toml` |
| P6-17 | | Dangling finish (successors exist, none FS or FF) | all activities; completed and milestones not counted, nor the constrained tasks `ignore_soft_constraints` / `ignore_hard_constraints` leave out | `p6.toml` |

**Targets** are those of the Check Schedule dialog as the P6 EPPM 25 help prints them
([91574](https://docs.oracle.com/cd/G18294_01/p6help/en/91574.htm): "should be less than 5 %",
"less than 1 %", "greater than 90 %", BEI "0.95 or greater"); the P6 Professional help does not
print them. BEI follows report R1 instead (`> 0.95`), so exactly 0.95 fails as it does in that
report. P6-15 to P6-17 have no documented default, and the duration limit `x` of
P6-04 to P6-06 is a setting of the dialog: their values are in `p6.toml` only. Edit
`p6.toml` (or a copy) to match your dialog, so pass/fail lines up with P6.

**Dangling options.** The Relationships and Assignments tab of the dialog
([113174](https://docs.oracle.com/cd/G48902_01/client_help/en_US/113174.htm), P6 Professional 26)
has three options, read from `p6.toml` as rule parameters:

> **Ignore in-progress activities for dangling start activities**: Mark to disregard activities that
> are in progress when checking for activities with start dates not driven by their predecessors.

> **Ignore activities with soft constraints**: Mark to disregard activities with soft constraints when
> checking for activities with finish dates that do not drive successors. Soft constraints are Start On,
> Start On or After, Start On or Before, Finish On, Finish On or After, Finish On or Before, and As Late
> As Possible

> **Ignore activities with hard constraints**: Mark to disregard activities with hard constraints when
> checking for activities with finish dates that do not drive successors. Hard constraints are:
> Mandatory Start and Mandatory Finish.

| Option | Check | Parameter | `p6.toml` |
|---|---|---|---|
| Ignore in-progress activities | P6-16 | `ignore_in_progress` | `true` (checked in R1) |
| Ignore activities with soft constraints | P6-17 | `ignore_soft_constraints` | `false` |
| Ignore activities with hard constraints | P6-17 | `ignore_hard_constraints` | `false` |

These constraint sets are the options' own, not those of P6-02 / P6-03: Start On and Finish On
are soft here and hard on the Constraints tab
([113176](https://docs.oracle.com/cd/G48902_01/client_help/en_US/113176.htm)). Oracle documents no
default for the three options, nor whether "disregard" also removes the task from the
denominator: xerscope keeps it in the denominator and out of the numerator, as for every other
task P6-16 / P6-17 do not count. A constraint counts whether it is primary or secondary, as in
P6-02 / P6-03. The Debug page (block 04) shows the values in use. The XER data map lists no
column for Check Schedule settings, so they are not read from the file.

### Comparing with a P6 Check Schedule report

`xerscope check file.xer --standard P6 --baseline BL.xer --flagged out/` writes one CSV per
check with the activities (or relationships) found, to diff against the report's lists.
`--expect report.csv` compares the counts: a CSV with columns `id,found,total` (plus `file`
when several files are checked) typed from the report's summary; every line is printed as
expected / got and the command exits 1 on any difference. Exit codes of `check`: 0, 1 when
`--fail-on` or `--expect` finds the schedule short of the standard, 2 for a usage or input
error (no such file, unreadable XER or CSV, invalid standard), reported as one
`xerscope: <message>` line on stderr.

`--baseline-in-file` measures each file against the P6 Project Baseline it holds
(`PROJECT.sum_base_proj_id`, `Snapshot.file_baseline`), the project baseline Check Schedule reads for
Late Activities and BEI (101248, P6 Professional 25 help). A file without a usable one falls back on
`--baseline` or `--planned-baseline`, else none. It is the app's "Baseline in each file"
(`analysis.baseline.baseline_in_file`, shared by both).

On the Schedule health page, "Compare with a P6 Check Schedule report" does the same on the
update and baseline picked there: type the report's counts or upload that CSV; lines left empty are
not compared (`compare_counts` in `analysis/checks.py`, shared with `check --expect`). Nothing typed
or uploaded is kept on the server.

The Schedule health page shows the same results as `xerscope check` when both read the same
series with the same baseline (`tests/test_app_parity.py`). Two defaults differ: the app takes
the P6 Project Baseline in each file when a file holds one, a file without one getting the
fallback picked in the Files window (none by default), or the file named by `XERSCOPE_BASELINE`
on a locked server; `check` takes none unless `--baseline`, `--planned-baseline` or
`--baseline-in-file` is given. And the checks against an update one status period older (DECM
06A504a/b, 06A506c) depend on which files are read, so `check` must get the whole folder, not a
single week. To compare on real exports, download "Summary (CSV)" from the page and run `check`
on the same folder and baseline file.

## DCMA DECM v8.0, Guideline 6 (schedule)

EVMS Test Metric Specification v8.0 (21 Aug 2025). Only the automated tests an XER can
answer; DECM's status date is P6's data date.

| ID | Test | X / Y | Target |
|---|---|---|---|
| 06A204b | Dangling logic | open start or finish / incomplete non-LOE tasks and milestones | 0 % |
| 06A205a | Lags | with ≥ 1 lagged predecessor / incomplete tasks and milestones | ≤ 10 % |
| 06A208a | Summary tasks with logic | WBS summary activities with a link | X = 0 |
| 06A209a | Hard constraints | Mandatory Start / Finish / incomplete | 0 % |
| 06A210a | LOE with discrete successors | incomplete LOE driving non-LOE work / incomplete LOE | 0 % |
| 06A211a | High total float | > 44 wd / incomplete non-LOE (DECM samples these for rationale) | info |
| 06A212a | Out of sequence | FS (S.AS\|S.FS) < P.FF, SS (S.AS\|S.FS) < P.FS, FF (S.AF\|S.FF) < P.FF, SF (S.AF\|S.FF) < P.FS | X = 0 |
| 06A401a | Critical path test | longest path, +600 wd moves the finish | pass |
| 06A501a | Missing baseline dates | without baseline start or finish / all (summaries excluded) | ≤ 5 % |
| 06A504a / b | Actual start / finish changed | differs from the previous update / with that actual | ≤ 10 % |
| 06A505a | In progress without actual start | % complete > 0, no actual start / with progress | ≤ 5 % |
| 06A505b | Complete without actual finish | 100 %, no actual finish / at 100 % | ≤ 5 % |
| 06A506a | Actual dates after the status date | / with an actual start | ≤ 5 % |
| 06A506b | Forecast on or before the status date | incomplete with a forecast start (not started) or finish on or before the data date | X = 0 |
| 06A506c | Riding the status date | start within 3 wd of the data date in both of two monthly updates, or remaining duration within ± 2 wd / incomplete | ≤ 1 % |

Not included: 06A301a (vertical traceability), 06I101b (schedule margin), 06I201a
(schedule visibility tasks): they need a summary schedule or your coding convention.

**Status date vs data date.** The DECM status date is P6's data date (IPMR DID
DI-MGMT-81861 §3.7.1.3.5.13: "The progress line is the date on which the schedule is statused,
also known as "time-now," "data date," or "status date.""; 06A506c assumption 2: "If the Status
Date does not match the Period End Date, use the IMS Status Date"). Each sheet's comparator applies
to it as written: 06A506a flags an actual "after status date" (> data date, an actual on the data
date is valid); 06A506b flags a forecast "on or before the status date" (<= data date, block 6 and
"v8.0 Updated to include on or before status date 5, 6, 10"), so a not-started activity whose
remaining start is the data date, as P6 schedules it, is flagged. P6's own check keeps "earlier
than the data date" (101248); the `invalid_dates` rule of your own standard exposes the choice as
`include_data_date`.
`UNRESOLVED`: in v8.0, 06A506b block 10 step 3 still reads "forecast finish dates before the status
date" and 06A506c (no change in v8.0) treats invalid forecasts as "(i.e., < Status Date)", as do PAM
200.1 §4.9 ("the forecast date should be on or after 8/1/09") and the IPMR DID ("shall not be earlier
than the status date"). Block 6 is applied; a DCMA text (the DECM v8.0 workbook or the 08/21/2025
change note) would settle it.

## DCMA 14-Point (legacy)

Authority: DCMA-EA PAM 200.1, *DCMA Earned Value Management System Program Analyst
Pamphlet* (Oct 2012), section 4 (points 1-14, populations in 4.0), CPLI in 3.1.2.3 and BEI in
3.1.2.4. Copy read: [DCMA-PAM-200-1.pdf](https://mail.mosaicprojects.com.au/PDF-Gen/DCMA-PAM-200-1.pdf).
Each metric's `source` in `dcma.toml` cites its section. Sources in order of authority: PAM 200.1
([DCMA-PAM-200-1.pdf](https://www.dcma.mil/Portals/31/Documents/Policy/DCMA-PAM-200-1.pdf)), then
GAO-16-89G ([gao-16-89g.pdf](https://www.gao.gov/assets/gao-16-89g.pdf)), then Deltek Acumen
([metric descriptions](https://help.deltek.com/product/acumen/8.7/ga/DCMA%2014%20Point%20Assessment%20Metric%20Descriptions.html));
Ten Six, ScheduleReader and Mosaic only illustrate. Inputs are weekly XERs, so there is
no detail planning period (DCMA-08: every baseline start qualifies).

| # | Metric | Counts | Target |
|---|---|---|---|
| 1 | Logic | open ends of incomplete non-milestone tasks | ≤ 5 % |
| 2 | Leads | negative lags | 0 |
| 3 | Lags | positive lags | ≤ 5 % |
| 4 | Relationship types | FS share | ≥ 90 % |
| 5 | Hard constraints | MSO, MFO, SNLT, FNLT, mandatory | ≤ 5 % |
| 6 | High float | > 44 wd; a task without a float stays in the base, counted in the note | ≤ 5 % |
| 7 | Negative float | < 0; a task without a float stays in the base, counted in the note | 0 |
| 8 | High duration | baseline duration > 44 wd (n/a without a baseline) | ≤ 5 % |
| 9 | Invalid dates | incomplete tasks (§4.0, §4.9): forecast before / actual after the data date, by calendar day (`date_grain = "day"`; P6 compares timestamps) | 0 |
| 10 | Resources | duration but no resource or cost; n/a when the project has no assignment and no budgeted labour hours | 0 % |
| 11 | Missed tasks | due by the data date (baseline finish, by calendar day); missed when finished, or forecast to finish, on a later calendar date or with a Finish Variance > 0 in working time (PAM's two criteria, "or") | ≤ 5 % |
| 12 | Critical path test | +600 wd on the first open activity of the longest path moves the finish as much | pass |
| 13 | CPLI | (CPL + TF) / CPL, in working days of the project calendar; with a Must Finish By, CPL to the last open task and TF its float; without one, CPL and TF both on the open finish milestone ending last, TF being its margin to its baseline finish (n/a without a baseline or without a float) | ≥ 0.95 |
| 14 | BEI | completed (actual finish ≤ data date) / due (baseline finish ≤ data date), both by calendar day (PAM steps 2 and 5 use the same bound); tasks with no original duration out (PAM step 1) | ≥ 0.95 |

**Dates.** The pamphlet reasons in dates ("on or before 8/1/09, not after 8/1/09", §4.9): DCMA-09 and
DCMA-11 compare the status date by calendar day, and DCMA-14 reads both its due and its completed
tasks so (`date_grain = "day"` in `dcma.toml`). P6 keeps the timestamp (an actual at 12:00 is after a
data date at 08:00), which is the rule default and what
`p6.toml` uses. A missing total float (DCMA-06, 07, 13) is never read as 0: the task stays in the
population with a note, and the CPLI is n/a.

**DCMA-10.** PAM §4.10 applies "If the contractor does resource load their schedule": a project with no
`TASKRSRC` row (for its `proj_id`) and no budgeted labour hours on its tasks (`target_work_qty`) is
n/a; expenses alone do not load it. Hours on tasks without any assignment still fail, with a note
to check the export. The PAM asks that all tasks with a duration carry dollars or hours and states no percentage:
0 %. Population as PAM.

**DCMA-12.** Method: the first open activity of the longest path is lengthened by 600 wd, and the
finish must move by as much (PAM §4.12 names "a task of the critical path"; the first open task and the lengthening are xerscope's choice). The
delayed activity ignores its expected finish, which would otherwise fix its early finish and absorb the
slip. The move is read in working days of the delayed activity's calendar and, because the downstream path
may run on calendars with other non-working days, also in calendar days against the delayed activity's own
finish: the test passes when either reading reaches the delay, and the note gives both readings (hand case:
a week off in the delayed activity's calendar between its finish and the project's reads +595 wd for a
+600 delay that fully reached the finish). The other activities keep their expected finishes, so an expected finish downstream absorbs the slip (its activity's
remaining duration is cut, to 0 once pushed past that date, as P6 does with the option on): the test
fails and names it with the working days absorbed, as it names a mandatory date. The pamphlet's second criterion, "completion date shows
negative total float", adds no pass: with a Must Finish By the float of the end is `MFB - EF_end`,
which falls by exactly what the finish moves (+16 h to -64 h for a +80 h slip), and a Mandatory Finish
on the end keeps its float at 0 and fails both readings.

**DCMA-13.** CPL and TF are in working days of the project calendar (PAM and Acumen say days without
naming a calendar). Without a Must Finish By, the open finish milestone ending last is the measured milestone
(PAM §3.1.2.3, "until the next program milestone that is being measured"): CPL runs to its forecast finish and
TF is its margin to its baseline finish (project calendar, negative when late); a task
finishing after that milestone does not lengthen the CPL. n/a without a baseline, and n/a when the finish driver
has no float (a missing float is not 0). Both branches read the stored finish, the date P6 shows and the one
the milestone is chosen on; a stored finish the CPM would move is INT-01's finding.
Reported for review (status info, value 1.00, note "by construction") when the baseline is the planned dates of the file (`Baseline.is_planned`, target_* dates): P6 Professional 26
help, Dates columns (Oracle 47222) says the Planned Finish is calculated by the project scheduler and not changed
by it once the activity has started, so the planned finish of a not-started milestone follows its early finish
after scheduling and the margin is 0 by construction. A baseline file (or update) keeps the margin.

Differences with xerlock's published result on its sample schedule (the pamphlet wins;
`tests/reference/expected.py`, `tests/test_reference.py`): DCMA-01 0 (xerlock 2: SS-only
dangling finishes, finish milestone exempted), DCMA-04 23/25 (xerlock 25/27: links into
milestones counted), DCMA-05 1 (xerlock 2: a milestone counted), DCMA-11 3 (xerlock 4: a
milestone counted), DCMA-13 n/a (xerlock 1.0: no Must Finish By date and no baseline, so
the float to the contract finish is unknown). The other stated values, the critical path test (MEP-020, +600 wd; the
600 is xerscope's choice; the pamphlet and DECM 06A401a give none) and CPL (1080 h) reproduce.

## Integrity

Integrity answers one question before any other standard is read: are the dates in this file the ones
P6 would produce from its own logic? INT-01 and INT-03 recalculate the schedule and compare; INT-02 and
INT-04..08 reproduce the warnings, errors and exceptions of the P6 scheduling log (P6 EPPM 26 help,
[Schedule Project Log](https://docs.oracle.com/cd/G48897_01/p6help/en/99374.htm), written at each F9 with
"Log to file"). A failure means: reschedule in P6 (F9) and read its log, or a P6 rule xerscope does not
reproduce yet. The Schedule health page prints this text above the results.

| ID | Check | Log section | Source | Target |
|---|---|---|---|---|
| INT-01 | stored early/late dates and total float = a P6-exact recalculation; the note gives the latest early finish stored and recalculated, and the activities with external dates | Scheduling Results: "Latest Early Finish Date"; Exceptions: "Activities with external dates" | [99351](https://docs.oracle.com/cd/G48897_01/p6help/en/99351.htm), [99352](https://docs.oracle.com/cd/G48897_01/p6help/en/99352.htm) | <= 0% |
| INT-02 | started activities whose FS predecessor is not complete or SS predecessor not started at the data date (same reading as P6-15; FF and SF not listed) | Warnings: "Out of sequence activities" | [99350](https://docs.oracle.com/cd/G48897_01/p6help/en/99350.htm); link types calibrated on a P6 Check Schedule report | info |
| INT-03 | stored resource-assignment remaining dates = the recalculation | none (xerscope) | `analysis/cpm.py` | <= 0% |
| INT-04 | activities on a relationship loop (not those downstream of it) | Errors: "Activities that have invalid relationship loops" | [99374](https://docs.oracle.com/cd/G48897_01/p6help/en/99374.htm) | <= 0 |
| INT-05 | activities with no predecessor or no successor, unfiltered (P6-01 applies the Check Schedule exclusions) | Warnings: "Activities without predecessors", "Activities without successors" | [99350](https://docs.oracle.com/cd/G48897_01/p6help/en/99350.htm) | info |
| INT-06 | activities with an actual start or finish after the data date, unfiltered (P6-10b / 06A506a apply exclusions) | Warnings: "Activities with actual date later than data date" | [99350](https://docs.oracle.com/cd/G48897_01/p6help/en/99350.htm) | <= 0 |
| INT-07 | open, non-LOE activities whose recalculated early start or finish is on the wrong side of a constraint date. Unconfirmed against a P6 log | Exceptions: "Activities with unsatisfied constraints" | [99352](https://docs.oracle.com/cd/G48897_01/p6help/en/99352.htm) | info |
| INT-08 | relationships whose successor starts (FS, SS) or finishes (FF, SF) before the predecessor finishes (FS, FF) or starts (SS, SF); the successor end is a recalculated date (an actual one is out-of-sequence progress, listed by the log under its own warning, P6 Professional 26.8 log), the predecessor at its actual date else its recalculated early date; lag not applied, leads not evaluated | Exceptions: "Activities with unsatisfied relationships" | [99352](https://docs.oracle.com/cd/G48897_01/p6help/en/99352.htm) | info |

INT-07 and INT-08 stay at info until more P6 logs confirm the reading: the 26.8 log of the synthetic project CHECKSCHED (`tests/test_p6_checksched.py`) lists none of either, as xerscope does.

## Your own standard

```bash
uv run xerscope standards --template my-standard.toml   # every rule, commented
uv run xerscope standards --rules                        # rules and their parameters
uv run xerscope check exports/ --standard my-standard.toml --baseline BL.xer
uv run xerscope app --data exports/ --standards folder-with-my-toml/
```

A wrong rule, parameter name or value (choice, number, flag, list of names), population
keyword, unit or target is rejected on load with the exact name, so a typo cannot silently
change a result. The shape of the file is checked first, with the same kind of message
(`my-standard.toml: metric #3 (ACME-03): ...`): `[[metric]]` must be an array of tables,
`params` a table, `id`, `name`, `rule` and the optional text keys (`description`, `unit`,
`target`, `source`, `group`) strings; an `id` holds letters, digits, `.`, `_` and `-` only
(it names the `--flagged` files); a numeric parameter is finite (`nan` and `inf` would turn
every comparison into a silent pass); `target = "pass"` goes with a `pass/fail` rule and only
there, which takes no numeric target; a TOML nested thousands of levels deep is refused as
"too deeply nested". Every load error is a `ValueError` naming the file: the app lists it
under the standard picker, the CLI prints `xerscope: <message>` and exits 2. `group`
(optional) gives a section title. The formula behind every metric is in
[formulas.md](formulas.md).

To try a target or a threshold before writing it down, open the check on the Audit page:
it re-runs the check with the values set there, shows the sets behind the count, and gives
the `[[metric]]` table to paste here.

## Out of scope for now (research notes, Oct 2026)

| Standard | Current version | Note |
|---|---|---|
| DCMA DECM, other guidelines | v8.0 | EVMS cost data an XER does not carry |
| GAO Schedule Assessment Guide | GAO-16-89G, Dec 2015 | ten qualitative best practices |
| NDIA PASEG | v6.0, 30 Sep 2025 | guidance and GASP principles |
| AACE RP 29R-03 | rev. 2011 | window analysis: the base for the changelog and weekly trends, and for TIA later |

## Sources

- [Oracle P6 Professional 24 User Guide: Check Schedule](https://docs.oracle.com/cd/F88968_01/English/User_Guides/p6_pro_user/101393.htm)
- [Oracle P6 Professional 24 client help 101248: Check Schedule dialog box](https://docs.oracle.com/cd/F88968_01/client_help/en_US/101248.htm)
  (the source of the P6 populations)
- [Oracle P6 Professional 24: Schedule Options, General tab](https://docs.oracle.com/cd/F88968_01/client_help/en_US/general_tab_-_schedule_options_dialog_box.htm)
- [Oracle P6 help: Report tab of the Check Schedule dialog (section index)](https://docs.oracle.com/cd/G18294_01/p6help/en/101231.htm)
- [Oracle P6 help: Logic section](https://docs.oracle.com/cd/G18294_01/p6help/en/46291.htm),
  [Long lags](https://docs.oracle.com/cd/G18294_01/p6help/en/46288.htm),
  [Hard constraints](https://docs.oracle.com/cd/G18294_01/p6help/en/46286.htm),
  [Large durations](https://docs.oracle.com/cd/G18294_01/p6help/en/46282.htm),
  [BEI](https://docs.oracle.com/cd/G18294_01/p6help/en/46277.htm)
- [Oracle P6 help: About activity types](https://docs.oracle.com/cd/G18294_01/p6help/en/43407.htm)
- [Oracle P6 EPPM user guide: early and late dates, resource-dependent activities](https://docs.oracle.com/cd/F37125_01/English/User_Guides/p6_eppm_user/98346.htm)
- [Oracle P6 Professional: Earned Value admin preferences](https://docs.oracle.com/cd/F37128_01/client_help/en_US/earned_value_tab_-_admin_preferences_dialog_box.htm)
- [DECM v8.0 sheets index (SSI): schedule test specifications](https://ssitools.com/helpandsuport/DECM/help/ssi_decm_schedule_tests.htm):
  [06A204b](https://ssitools.com/helpandsuport/DECM/06A204b.pdf),
  [06A205a](https://ssitools.com/helpandsuport/DECM/06A205a.pdf),
  [06A209a](https://ssitools.com/helpandsuport/DECM/06A209a.pdf),
  [06A211a](https://ssitools.com/helpandsuport/DECM/06A211a.pdf),
  [06A212a](https://ssitools.com/helpandsuport/DECM/06A212a.pdf),
  [06A504a](https://ssitools.com/helpandsuport/DECM/06A504a.pdf),
  [06A506b](https://ssitools.com/helpandsuport/DECM/06A506b.pdf),
  [06A506c](https://ssitools.com/helpandsuport/DECM/06A506c.pdf)
- [DCMA EVMS Center](https://www.dcma.mil/HQ/EVMS/)
- [DCMA-EA PAM 200.1 (Oct 2012)](https://mail.mosaicprojects.com.au/PDF-Gen/DCMA-PAM-200-1.pdf)
- [Ten Six: options for scheduling progressed activities in P6](https://tensix.com/options-for-scheduling-progressed-activities-in-p6/)
- [Ten Six: using the P6 Check Schedule tool](https://tensix.com/using-the-p6-check-schedule-tool/)
- [Deltek Acumen: DCMA 14-Point Assessment metric descriptions](https://help.deltek.com/Product/Acumen/8.11/GA/DCMA%2014%20Point%20Assessment%20Metric%20Descriptions.html)
- [GAO-16-89G Schedule Assessment Guide](https://www.gao.gov/products/gao-16-89g)
- [NDIA PASEG v6.0](https://www.humphreys-assoc.com/?p=13023)
- [xerlock (reference results)](https://github.com/joaompfp/xerlock)
- **R1**: a P6 Professional Check Schedule report on a real schedule, with the matching XER.
  Confidential: kept by the maintainer outside the repository; the repository cites it by
  this label only, never its figures, dates or names. The tests rebuild each behaviour it
  settled by hand (`tests/test_p6_check_schedule.py`).
