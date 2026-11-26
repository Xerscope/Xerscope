# xerscope user guide

xerscope reads weekly Primavera P6 exports (`.xer`) and reports on them, from a command line and
from a web app that runs on your own machine. This guide has eight parts:

- [About this guide](#about-this-guide)
- [Concepts](#concepts)
- [Getting started](#getting-started)
- [Tasks](#tasks)
- [Reference](#reference)
- [Troubleshooting](#troubleshooting)
- [Limits](#limits)
- [Glossary and related documents](#glossary-and-related-documents)

## About this guide

This guide is for a planning engineer who knows Primavera P6 well and can paste a command in a
terminal. You do not need to know Python. The guide covers xerscope on your own machine:
installing it, the command line, the web app and the local Docker image. It does not cover
hosting the app for a team; for that, see [docs/it-deployment-guide.md](it-deployment-guide.md)
and [docs/deploy.md](deploy.md).

The guide describes the following versions:

- xerscope 0.1.0. The command line has no `--version` option and the app shows no version.
- Python 3.11 or later. The automated tests run on 3.11, 3.13 and 3.14; 3.12 installs but is
  not tested.
- The P6 Check Schedule standard follows the P6 Professional 24 documentation.
- The recalculation applies the rules of P6 Professional 23.12 / 24. It is checked against
  schedules computed by P6 Professional 23.12.1, and some checks against P6 Professional 26.8
  reports. No output of P6 Professional 24 itself is among the test references.
- xerscope reads `.xer` exports as updates, and a P6 XML export for its baselines only.
- The app and the command line are in English. The **Ask the schedule** field also reads French.

The guide uses the following conventions:

- "You" is the reader. You type every command in a terminal opened in the folder that holds the
  xerscope source, and every command starts with `uv run xerscope`.
- A label of the app is in bold, spelled as the app displays it, for example **Done**. Commands,
  file names, values and messages that the tool prints are in code font.
- A word in capitals inside a command or a label, such as `ACTIVITIES_CSV` or NAME, is a
  placeholder. In a label, N, K and M stand for numbers.
- The guide uses P6's words: *data date*, *activity*, *Activity ID*. The app's labels say
  *status date*, *task* and *Task ID* for the same things.
- The app spells *labor* and *anonymized*. The guide quotes labels as they are and writes
  *labour* and *anonymised* elsewhere.
- Dates and times are written as the tool prints them: `2026-10-19` or `19 Oct 2026`, and the
  24-hour clock (`08:00`).
- Every example uses the demo series, a synthetic project named `PRJ-ALPHA`.

For depth, the guide links to [docs/formulas.md](formulas.md), [docs/standards.md](standards.md),
[docs/cpm.md](cpm.md) and [docs/backlog.md](backlog.md). The full list is in
[Related documents](#related-documents).

## Concepts

This part explains the ideas behind the numbers. It contains no procedure.

### Updates, the weekly series and snapshots

An *update* is one `.xer` export of a schedule at one data date. xerscope reads several updates
of the same project together, as a *series*, because most of its readings are comparisons: what
changed between two weeks, what was promised last week and done this week, how the forecast
finish moved. A single update still gives the checks, the recalculation and the Gantt.

A series is ordered by data date, then by file name. It holds one update per data date: two
files with the same data date cannot both be read, because nothing says which one is the week's
schedule. In a folder, the updates are the files directly in it whose name ends in `.xer`, in
any letter case; subfolders are not read. *Snapshot* is the app's word for an update once it is
read. When a file holds several projects, xerscope reads one: baseline copies are set aside,
then the project with the most activities wins, then the latest data date, then the first in
the file. You can choose another project in the app and on the command line.

### What xerscope reads from an update

A few readings differ from what a quick look at the XER tables suggests:

- The data date is `PROJECT.last_recalc_date`, else `PROJECT.plan_start_date`. When both are
  blank the update has no data date: the app skips the file, and on the command line the checks
  that need a data date read `n/a`. The app's labels call it the *status date*, and DECM's
  "status date" is read as P6's data date.
- The forecast finish of the project is the latest activity finish, WBS summary rows left out.
  `PROJECT.scd_end_date` is not used; when the two differ by more than one day, xerscope warns.
- Start and Finish follow P6's columns of the same name: the actual date, else the remaining
  early date, else the early date, else the planned date.
- Budgeted, actual and remaining labour hours come from `TASK`. A blank value falls back, per
  activity and per column, to the activity's labour, role or untyped assignments in `TASKRSRC`.
  Nonlabor units are kept apart, and material assignments enter neither total.
- xerscope applies the project's own settings: the critical definition, the lag calendar, the
  progressed-activity option, the SS lag option, the float type, expected finish dates and the
  % complete type (physical, duration or units). It also reads "Make open-ended activities
  critical", the option for relationships to other projects, and Must Finish By.

For the exact fields and fallbacks, see [docs/formulas.md](formulas.md).

### Baselines and the kinds the app offers

A baseline is the plan that planned value, BEI, missed activities and late activities are
measured against. xerscope does not guess it: you choose it, and every result says which
baseline it used. The choice has five kinds:

- **Baseline in each file (P6 Project Baseline)**: each update is measured against the project
  its own file names as its Project Baseline (`PROJECT.sum_base_proj_id`). That baseline is
  usable when it is another project of the same file, owns activities and, when it records the
  project it was copied from, was copied from the analysed project. With a P6 XML export of the
  baselines at hand, the baseline an update names is read from the export.
- **Separate baseline file**: one file, an XER or a P6 XML export, for the whole series.
- A loaded update, for example the first export, taken before any progress.
- **Planned dates in each file (target_*)**: each update against its own planned dates.
- **None**.

The first kind follows a baseline that changes over time, update by update; the others hold one
plan still. That matters when you compare weeks: updates measured against different plans do
not show one trend, and the sidebar says so when it happens. xerscope records how each update's
baseline was found: *in file*, *exact* (the baseline the update names, read from the P6 XML
export), *probable*, *chosen*, *fallback*, *planned*, *series* (one baseline for every update)
or *none*. By the code's own definition, only *in file* and *exact* are the baseline P6 itself
used.

Two groups of pages read the baseline differently. **Schedule health**, **Audit** and
**Gantt & WBS** read the Project Baseline of the update's own file whenever the file holds a
usable one, whatever you chose, as a P6 check on that file does. **Earned value** measures its
cumulative figures against the origin of the series, the baseline that does not move from one
update to the next, unless you turn on its P6 view.

The *earned value basis* is a second choice: which baseline hours and dates planned and earned
value use. The default is budgeted values with planned dates. Its help text quotes P6's Admin
Preference "When calculating earned value from a baseline use"; that wording was not checked
against P6.

### How activities are matched between files

Activities are matched between files by Activity ID (`TASK.task_code`). `task_id` is not used
for matching: the code treats it as a number that can change from one export to the next (a
statement about P6 that was not checked), and the demo series changes it in every file while
the Activity IDs stay. When an Activity ID is repeated in a project, the first `TASK` row is
kept and a warning names the others, which are left out with their relationships, assignments
and expenses.

An activity renumbered between two files therefore counts as one deleted and one new activity;
the changelog and PPC note it. For a baseline you can change that: with **Link renumbered tasks
by GUID** on, an update activity that carries a baseline activity's `TASK.guid` under a new
Activity ID is measured against that baseline activity. The option is off by default, and has
no effect with a baseline read from a P6 XML export, where the GUID is blank.

### Standards and checks

A *standard* is a list of checks. Four are built in: P6 Check Schedule, DCMA 14-Point, DCMA DECM
v8.0 (schedule) and Integrity. You can write your own as a TOML file. A *check* has a population
(the activities or relationships it looks at), a count found, a value, a target and a status:

- `pass` or `fail`: the value meets or misses the target.
- `info`: the check has no target, or reports its value for review.
- `n/a`: the check needs a baseline and none is loaded, or it has nothing to measure (an empty
  population, no data date, no earlier update).
- `error`: the rule could not run. The note carries the reason; the page or command goes on.

The same name does not mean the same count in every standard. The P6 checks compare hours, as
P6 does; DCMA 14-Point and DECM count working days. BEI in the P6 standard divides by every
baseline activity; DCMA's divides by the activities due at the data date. For the differences,
see [docs/standards.md](standards.md#same-check-several-definitions). The status is judged on
the value rounded to six decimals, while the display shows fewer: a value of 0.9545 shows
`0.95` and passes `> 0.95`.

The *score* of a standard is the criteria in pass over the criteria evaluated (pass plus fail).
Checks in `info`, `n/a` or `error` are in neither term, and checks that share an item are one
criterion: the P6 standard has 18 lines and 17 criteria. The score is a xerscope convention; the
app's own help says that no source defines a global score. Every check can be traced to its
population, its calculation and its source on the **Audit** page.

### Recalculation

xerscope has its own critical path engine. It reschedules a file with the rules of P6
Professional 23.12 / 24, every date on the activity's own calendar to the minute, then compares
what it computed with what the file stores. The engine applies the following:

- every calendar, with its work periods, holidays and exceptions;
- the four relationship types, with lag on the calendar that the project's option designates
  (the successor's by default);
- SS lag of a started predecessor, counted from its early start or from its actual start;
- the nine constraint types, primary and secondary;
- Retained Logic, Progress Override or Actual Dates, and expected finish dates;
- resource-dependent activities on their resources' calendars, with driving assignments and
  assignment lag;
- As Late As Possible, level of effort, open ends, Must Finish By and the longest path.

One rule follows the P6 version that exported the file. An expected finish earlier than the
early start brings the remaining duration to 0 for an export of a version below 26. From
version 26, the stored remaining duration is kept.

The comparison covers the stored early and late dates, total float and free float of every
activity that is not completed and not a level of effort, and the remaining dates of their
resource assignments. A date agrees when it is the same clock time to the minute. The point of
the comparison is trust in the file: by the code's own reading, a difference means that the
file was edited after the last F9, or that it uses a scheduling feature xerscope does not
model. Checks such as large float or negative float read the float stored in the file, so the
comparison tells you whether that float is what the file's own logic produces. The Integrity
standard runs the same comparison as checks INT-01 and INT-03. For the algorithm and its
evidence, see [docs/cpm.md](cpm.md).

### Units of time

P6 stores durations, float and lag in hours, and xerscope keeps them in hours. Three units
appear in the outputs:

- Hours. The P6 Check Schedule checks compare hours.
- Working days (`wd`): the hours divided by the hours per day of a calendar
  (`CALENDAR.day_hr_cnt`; 8 hours when that field is blank, 0 or under a minute). For an
  activity it is the activity's own calendar; for a project total, such as the shift of the
  forecast finish, it is the project calendar.
- Calendar days (`cal. d`). One figure uses them: **Time gap** on the **Earned value** page.

Working time comes from each calendar's `clndr_data`: the work periods of each day of the week
and the exceptions. An exception without hours is a non-working day; an exception with hours is
a working day with those hours. A date that goes later reads negative wherever a move is given
in working days: the finish shift, a milestone's slip, the changelog's date moves, the start
and finish variances. Schedule variance and the time gap are negative when the project is
behind.

### Planned value, earned value and commitments

The earned value figures are in labour hours:

- Planned value (PV) is the baseline labour units times Schedule % Complete, which is linear in
  working time between the baseline start and finish, to the minute, on the baseline activity's
  calendar as the baseline file defines it.
- Earned value (EV) is the baseline labour units times Performance % Complete, which follows
  the earned value technique of the activity's WBS: activity % complete, 0/100, 50/50 or
  custom %. An activity of the update that is not in the baseline earns nothing and is listed.
- AC is the actual labour hours of every activity of the update, ETC the remaining hours, and
  EAC is AC plus ETC. Cost figures stay hidden until you turn on **Costs**.

PPC reads two consecutive updates, W−1 and W. A *commitment* is a start or a finish that W−1
plans on or before W's data date, for an activity not yet started (or not yet finished) in
W−1. It is kept when W holds the actual date on or before that data date. PPC Start and PPC
Finish are the commitments kept over the commitments made, for each kind; PPC W/W−1 covers
both. Work already late at W−1 is committed too, by default. Milestones and level of effort
activities are left out, and an activity deleted in W is a scope change, not a miss. When
nothing was due, PPC shows a dash, not 0.

The start and finish variance of an activity is its date in W−1 (or W−2) minus its date in W,
in working days of its calendar in W; it is blank when a date is missing.

### What stays on your machine

xerscope is meant for schedules that must not leave your machine:

- The app listens on `localhost` only, unless you start it with another `--host`. It has no
  login: every program and every local user of the same machine can reach it.
- xerscope's own code makes no network call. Usage statistics are off, and the app serves its
  two fonts itself.
- An uploaded file is held in the session's memory and is never written to disk. The app writes
  nothing to disk, with one exception: a correction taught in the **Ask the schedule** field is
  recorded when a lexicon folder is configured, which is off by default.
- The command line writes only where you ask it to, and downloads are anonymised by default.

These statements rest on xerscope's code. The code of Streamlit and Plotly, which the app is
built on, was not audited, and no browser traffic was captured.

## Getting started

At the end of this part, xerscope is installed, the app shows a demo series of eight weekly
updates, and you have read the same check in the app and on the command line.

Before you begin, make sure that you have a terminal, git, uv (the tool that installs and runs
xerscope), Python 3.11 or later, and network access for the installation. The commands were run
on Linux; they have not been checked on Windows or macOS.

### Install xerscope and generate the demo series

To install xerscope and create the demo files, follow these steps:

1. Fetch the source into a folder named `xerscope`. This step needs read access to the
   repository and was not checked on a fresh machine.
   ```bash
   git clone https://github.com/Xerscope/Xerscope xerscope
   ```
2. Enter the folder. Every later command runs from it.
   ```bash
   cd xerscope
   ```
3. Install xerscope and what it depends on, at the versions that the `uv.lock` file fixes. uv
   creates the environment in a `.venv` folder of the source.
   ```bash
   uv sync --locked
   ```
4. Check the installation by listing the commands.
   ```bash
   uv run xerscope --help
   ```
   The output starts with `usage: xerscope [-h]` and lists 12 commands, from `app` to `lexicon`.
5. Generate the demo series.
   ```bash
   uv run xerscope sample
   ```
   The command prints the eight files it wrote, one per week. The date in each name is the data
   date of the update:
   ```text
   data/sample/PRJ-ALPHA_2026-08-31.xer
   data/sample/PRJ-ALPHA_2026-09-07.xer
   ...
   data/sample/PRJ-ALPHA_2026-10-19.xer
   ```

### Start the app and read the files

To read the eight files in the app, follow these steps:

1. Start the app on the demo folder.
   ```bash
   uv run xerscope app --data data/sample
   ```
   The terminal prints `URL: http://localhost:8501` and stays busy while the app runs.
2. In your browser, open `http://localhost:8501`. The **Overview** page shows the message "Load
   your weekly XER exports from the sidebar's Files line (upload or folder path)." and the
   sidebar shows **Files · none read**. Nothing is read yet.
3. In the sidebar, click **Files · none read**. The **Files and baseline** window opens. It
   lists the eight files, none selected; the first line reads
   `PRJ-ALPHA_2026-08-31.xer — PRJ-ALPHA · 31 Aug 2026 · 29 tasks`. The counter reads **0 of 8
   ticked**.
4. Click **Select all**. The counter reads **8 of 8 ticked**.
5. Click **Done**. The files are read, with the progress in the sidebar. Then the window comes
   back by itself, this time with its **Baseline** section only: **Baseline (BL)** is set to
   `2026-08-31 · PRJ-ALPHA_2026-08-31.xer`, the first update. The page says "8 files · 1 project
   read. Choose the baseline in the window (the sidebar's Baseline line opens it again), then
   Done: the pages are computed once, against it."
6. Click **Done** again to keep that baseline. The **Overview** page is drawn. The sidebar shows
   **Files · 8 files · 1 project** and **Baseline · update 2026-08-31**. Under the page title,
   one line sums up what is read:
   ```text
   PRJ-ALPHA · status date 19 Oct 2026 · BL update 2026-08-31 (the window's choice) · EV budgeted, planned dates · costs off · 8 files · 1 project
   ```
   Four figures follow: **Forecast finish** `23 Mar 2027`, **Shift since first update**
   `-15.0 wd`, **Tasks complete** `7 / 30` and **Critical tasks** `18`. The forecast finish is
   15 working days later than in the first update.

### Read one page

To read the schedule checks of the last update, follow these steps in the app:

1. In the navigation, under **Analysis**, click **Schedule health**. **Standard** is on
   **P6 Check Schedule** and **Update** is on `2026-10-19 · PRJ-ALPHA_2026-10-19.xer`. The cards
   read **P6 Check Schedule score** `29 %`, **Checks passed** `6 / 18` and **Checks failed**
   `12`. The **Results** table has one row per check.
2. Under **Detail by check**, click the first line, `FAIL P6-01 · Logic — 8.7 % (2 / 23) ·
   target < 5%`. The panel reads "8.7 % misses the target < 5 %." and lists the two activities
   that the check found.

### Run the same check on the command line

To get the same result without the app, follow these steps:

1. Open a second terminal in the `xerscope` folder. The app keeps running in the first one.
2. Run the P6 Check Schedule checks on the last update, with the first update as the baseline.
   ```bash
   uv run xerscope check data/sample/PRJ-ALPHA_2026-10-19.xer --baseline data/sample/PRJ-ALPHA_2026-08-31.xer
   ```
   The output has 18 lines of checks and starts as follows:
   ```text
   P6 Check Schedule · PRJ-ALPHA_2026-10-19.xer · data date 2026-10-19 · baseline BL 2026-08-31 · PRJ-ALPHA_2026-08-31.xer
       id                             check target  actual  found  total status
    P6-01                             Logic   < 5%    8.70      2     23   fail
    P6-02                  Hard Constraints   < 1%    0.00      0     22   pass
    P6-03                  Soft Constraints   < 5%    9.09      2     22   fail
   ...
   ```
   The line P6-01 carries the figures of the page: 2 found out of 23. Six lines read `pass` and
   12 read `fail`, as the cards of the page do.
3. In the first terminal, press `Ctrl+C` to stop the app. Streamlit prints `Stopping...`.

You have installed xerscope, read a series of eight updates against a baseline, and obtained the
same check results in the app and on the command line. The demo series carries deliberate
defects, listed in [Demo series](#demo-series). To work on your own files, go to
[Load files and choose the baseline](#load-files-and-choose-the-baseline).

## Tasks

Each guide in this part reaches one goal. The commands use the demo series from
[Getting started](#getting-started), so each one runs as written from the folder of the source;
replace `data/sample` and the demo file names with your own. Every option of every command is
in [Reference](#reference).

### Load files and choose the baseline

Use this guide to read your own weekly exports in the app and to set the baseline they are
measured against. Keep one `.xer` file per data date in the folder. For what each baseline
means, see [Baselines and the kinds the app offers](#baselines-and-the-kinds-the-app-offers).
To read the `.xer` files of a folder, follow these steps:

1. Start the app on the folder, then open `http://localhost:8501` in your browser.
   ```bash
   uv run xerscope app --data data/sample
   ```
2. In the sidebar, click **Files · none read**. The **Files and baseline** window lists the
   `.xer` files of the folder, none selected.
3. Select the checkbox of each file to read, or click **Select all**.
4. If a file holds several projects, choose the project to read in the list under **Project read
   from each file · why**.
5. Click **Done**. The files are read, and the window comes back with its **Baseline** section.
6. In **Baseline (BL)**, choose the baseline. If you choose **Baseline in each file (P6 Project
   Baseline)**, also choose in **When a file has no baseline** what the other updates are
   measured against; with **None**, their baseline checks read `n/a`.
7. Click **Done**. The pages are computed against the baseline. The sidebar's **Baseline** line
   and the line under each page title name it.

To change the baseline later, click the sidebar's **Baseline** line, choose, and click **Done**.
The same section holds **Earned value basis** and **Link renumbered tasks by GUID**; select the
latter when the sidebar reports renumbered tasks. To name a separate baseline file at start, add
`--baseline FILE` to the `app` command: **Baseline (BL)** then starts on **Separate baseline
file**.

To read another folder without restarting, enter an absolute path, or a path that starts with
`~`, in the **…or read a folder** field of the window. The folder must lie under the folder
root: the `--data` folder when you gave one, else your home directory. To read files that are
in no such folder, add them under **Upload .xer files** (up to 200 MB each); uploaded files take
precedence over the folder. The upload was read in the code and has not been exercised in a
browser.

#### Use a P6 XML export or a baselines subfolder

Use a P6 XML export when your `.xer` files name a Project Baseline that they do not hold. The
app's own notice describes the export in P6 as "Export > Primavera P6 XML, Baselines to
Export". To use the export, follow these steps:

1. Put the `.xml` file in the folder of the updates, next to the `.xer` files.
2. In the **Baseline** section of the **Files and baseline** window, choose **Baseline in each
   file (P6 Project Baseline)** in **Baseline (BL)**.
3. In **Baseline file in the folder**, make sure that the `.xml` file is chosen. A single `.xml`
   file is chosen by itself.
4. Click **Done**. Each update is measured against the baseline its file names, read from the
   export. An update measured against a *probable* baseline is announced under the title of
   each page and in the sidebar.

If you choose **Separate baseline file** instead, one baseline of the export serves every
update: the one the latest update names, else the export's Project Baseline, else its only
baseline. On the command line, `--baseline` also takes a P6 XML export: it reads the export's
Project Baseline, else its only baseline, and does not look at the baseline each update names.
The reading of an export with several baselines was read in the code and has not been run.

To offer baseline files that must never be read as updates, put them (`.xer` files or P6 XML
exports) in a subfolder named `baselines` of the folder of the updates. Choose **Separate
baseline file**, then the file in **Baseline file in the folder**, where it is listed as
`baselines/<name>`. The command line does not read that subfolder.

### Check schedule health against a standard

Use this guide to run the checks of a standard on one update or on the whole series, and to get
the activities that each check found. To read the checks in the app, follow these steps on the
**Schedule health** page:

1. In **Standard**, choose the standard, and in **Update**, the update. The cards give the score
   and the number of checks passed, failed, for review and not applicable; the **Results** table
   has one row per check.
2. Under **Detail by check**, click a check. Its panel gives what the check measures, its
   calculation, its population, its source and the items it found. **Show the N tasks in the
   Gantt** opens those activities in the schedule.
3. To see a check over time, go to **Trend across updates**, click **Compute the trend on the N
   updates**, then choose the check in **Check**.
4. To keep the results, click **Summary (CSV)** or **All flagged items (CSV)**.

To run a standard on every update of a folder and write the results, run the `check` command:

```bash
uv run xerscope check data/sample --standard DCMA --baseline data/sample/PRJ-ALPHA_2026-08-31.xer --out results.csv --flagged flagged
```

The command prints one table per update, in data date order, then `written results.csv`. The
CSV holds one row per check and per update. The `flagged` folder holds one CSV per update and
per check that found something, such as `PRJ-ALPHA_2026-08-31_DCMA-01.csv`. Without a baseline
option, the checks that need a baseline read `n/a`. The page reads the Project Baseline of the
update's own file when the file holds a usable one; to reproduce it, use `--baseline-in-file`.

### Audit one check

Use this guide when a count surprises you and you want to see which activities are behind it,
or what the check gives with another threshold. The audit is in the app only. Follow these
steps on the **Audit** page:

1. Choose the standard in **Standard**, the update in **Update** and the check in **Check**. On
   **Schedule health**, the **Audit this check** button of a check's panel does it for you.
2. Under **Sets**, read the tabs **Counted**, **Checked, not counted** and **Excluded**, each
   with a **Download CSV** button, then **Population, step by step**: each step, what it
   removed and what it left.
3. For a check of the P6 standard, open **Calculation sheet: population, fields, sources, worked
   example**.
4. To try other settings, change **Rule parameters** or **Target** under **Settings for this
   audit**. The cards **Audit** and **Audit status** show the result beside the standard's own;
   **Reset** goes back to the standard's values. The changes stay on this page.
5. To make a setting permanent, open **Settings: how to change this check for good** and copy
   the `[[metric]]` block into a standard of your own.

### Recalculate like P6 and read the differences

Use this guide to find out whether the dates and float stored in a file are the ones its own
logic produces. For what is compared and why, see [Recalculation](#recalculation). Follow these
steps:

1. Run the `recalc` command with a report and a CSV of the recalculated values.
   ```bash
   uv run xerscope recalc data/sample/PRJ-ALPHA_2026-10-19.xer --report --out recalc.csv
   ```
   The output is similar to the following:
   ```text
   PRJ-ALPHA_2026-10-19.xer · 30 activities · data date 2026-10-19 08:00 · recalculated finish 2027-03-23 16:00
     early_end_date            22 / 22      identical
   ...
     total_float_hr_cnt        22 / 22      identical
     assignments (19): 76 / 76 stored dates identical
     written recalc.csv
   ```
2. Read each line as the stored values reproduced over the stored values compared.
3. If a line shows a difference, read the table that follows it: per activity and field, the
   stored value, the computed value and the gap in working hours (`gap_hr`). The block
   `differences by activity shape`, which `--report` adds, groups the differences by status,
   type, constraint, links and option, so that one week's differences point at one rule.
4. Read the lines that start with `warning:`. They name what xerscope does not model in this
   file, such as leveling.

The exit code is 0 whatever the number of differences. In the app, the same comparison is on
the **Schedule health** page: choose **Integrity** in **Standard** and read INT-01 (**Schedule
recalculated**; the four dates and total float, without free float) and INT-03 (**Assignments
recalculated**). The values that differ are on the **Debug** page, in the block **3 · INT-01 /
INT-03 differences**.

### Compare two updates

Use this guide to list everything that changed between two exports. To compare two loaded
updates, follow these steps on the **Changelog** page:

1. In **From (older)** and **To (newer)**, choose the two updates. The page starts on the latest
   update and the one before it.
2. Read the cards: **Forecast finish**, **Added / deleted**, **Logic changes**, **Durations
   changed**, **Retroactive actuals** and **Became critical**.
3. Under **All changes**, narrow the list with **Category**, **Change** and **Search**. To keep
   the whole list, click **Download changelog (CSV)**.

To compare two files on the command line, older first, run the `changelog` command. It prints
the number of changes of each kind, then `written changelog.csv (60 changes)`.

```bash
uv run xerscope changelog data/sample/PRJ-ALPHA_2026-10-12.xer data/sample/PRJ-ALPHA_2026-10-19.xer --out changelog.csv
```

### Read the delay analysis

Use this guide to see what moved the project finish between an update and the one before it.
The page needs at least two updates and does not read the baseline. For the method, the
half-stepped update analysis, see
[docs/formulas.md](formulas.md#51-half-step-reading-of-a-week-analysisforensicspy). Follow these
steps on the **Delay analysis** page:

1. In **Update**, choose an update after the first one.
2. Read the caption **Finish held by** (the last task, Must Finish By or a mandatory finish) and
   the cards: **Finish before replanning** with the week's slip, **Finish shown**, **Longest
   path float** and **Tasks matched**.
3. Under **Step by step**, read what each kind of change did to the finish: progress, scope,
   durations, logic, constraints, then calendars and options.
4. Under **Longest path**, read which activities stayed on the longest path, entered it or left
   it, and the week's commitments on that path.
5. Under **Every update**, read the series: a finish shown that holds still while the finish
   before replanning keeps slipping is a delay absorbed by replanning.

If the page warns that xerscope does not recalculate the finish P6 stored in the file, read the
shifts as indications only.

### Follow earned value

Use this guide to read planned value, earned value and schedule performance over the series.
The page needs a baseline that carries labour hours. For the definitions, see
[Planned value, earned value and commitments](#planned-value-earned-value-and-commitments).
Follow these steps on the **Earned value** page:

1. In **Update**, choose the update, and read the first cards: **Percent complete**, **Percent
   scheduled**, **SPI (labor units)**, **SV**, **BEI (P6 / DCMA)** and **EAC**.
2. Read the Earned Schedule figures under **Where the project stands**, **At what pace** and
   **Does it end on the planned finish**.
3. Under **S-curve**, read PV, EV and AC over time. **Show as % of BAC** gives percentages.
4. To measure the update against its own baseline, as P6 computes its planned value, turn on
   **P6 view: the file's baseline**.
5. To see cost figures, select **Costs** in the sidebar. The page adds the **SPI** card and the
   cost rows and columns.
6. Open **Earned hours by task** to read Schedule %, Performance % and the EV technique of each
   activity. Under the table, the page lists the activities that are not in the baseline and
   those whose EV technique is not modelled.

### Follow milestones

Use this guide to watch the forecast dates of milestones move from update to update. The trend
needs at least two updates. Follow these steps on the **Milestone trend** page:

1. In **Milestones and key tasks (up to 6)**, choose the milestones or activities. The page
   starts on the finish milestones of the latest update, critical first; the **Finish
   milestones**, **Critical milestones** and **Clear** buttons set the list in one click.
2. Read the chart, one line per milestone. The last point is red when the milestone moved later
   in the last update and green when it moved earlier.
3. Under **Slippage**, read the slip of each milestone in working days on its own calendar. A
   later date reads negative.

### Measure PPC

Use this guide to measure, week by week, how many of the starts and finishes planned for the
week happened. The page needs at least two updates. Follow these steps on the **PPC &
progress** page:

1. In **Week ending**, choose the update that closes the week.
2. Optional: in **PPC target (%)**, set the target. It moves the dotted line of the chart.
3. To leave out the work that was already late at W−1, clear **Include commitments late at
   W−1**.
4. Read **PPC Start**, **PPC Finish** and **PPC W/W−1**, with **Starts kept** and **Finishes
   kept**. A dash means that nothing was due.
5. Under **Commitments**, read each commitment and its outcome; **Milestones committed** and
   **Unplanned work** are listed apart, outside the counts. Under **Start and finish
   variance**, read how each activity's dates moved against W−1 and W−2.

### Explore the Gantt and ask the schedule

Use this guide to look at one update as a Gantt grouped by WBS, and to filter it with a
sentence. To explore an update, follow these steps on the **Gantt & WBS** page:

1. In **Update**, choose the update. In **Compare with**, choose what the outline behind each
   bar shows: **Previous update**, **Baseline (BL)**, **First snapshot**, **None** or another
   loaded update.
2. To focus on a branch, choose it in **WBS**; the cards and the chart follow. Narrow the rows
   with **Status**, **Float** and **Search**.
3. Turn on **Logic links** to draw the relationships, and turn off **Hide LOE** to show level of
   effort activities. In **Timescale**, choose **Month** or **Week**.
4. Click an activity in the chart. Its card opens with its identity, status, dates,
   constraints, resources and logic, and its **History across updates**.
5. To keep the rows shown, open **Table view** and click **Download CSV**.

To filter the Gantt with a sentence, follow these steps on the same page:

1. In **Ask the schedule**, enter a sentence, for example `critical not started in civil
   works`, and press `Enter`. A banner under the field says what was understood. On the last
   update of the demo it reads "2 activities critical not started in CIV · Civil works; worst
   float -9 wd (C3050), latest finish 20/12/2026."
2. To drop one filter, click its chip, which ends with **×**. To clear the sentence, click
   **Show all**.
3. If the banner names a word it does not know, click one of the labels under **Did you mean**,
   or rephrase with the file's own words.

The field reads English and French. It combines words with `and`, `or`, `not` and parentheses,
compares measures (`float < 10 d`) and reads dates (`starting next week`). The words that name
a WBS node, a code or a resource must be the file's own. The field uses a keyword grammar; no
model is involved.

### Export for Power BI and download anonymised data

Use this guide to take data out of xerscope, with or without the names of your project. To
download the Power BI tables from the app, follow these steps:

1. In the sidebar, decide whether downloads are anonymised. **Anonymous exports** is on by
   default: downloads carry new Task IDs and names, and other text is emptied. The pages always
   show the files' own data.
2. On the **Export for Power BI** page, in **Format**, choose `parquet` or `csv`.
3. If **Anonymous exports** is on, click **Prepare anonymized downloads**. The files are read
   again for the anonymiser.
4. Click the download button. The zip holds four tables: `dim_snapshot`, `fact_activity`,
   `fact_relationship` and `fact_assignment`.

The same toggle and the same two steps apply to the downloads of the other pages. To download an
anonymised copy of the XER files themselves, click **Build anonymized extract** under
**Anonymized XER extract**, then **Download anonymized XER (.zip)**; the extract is anonymised
whatever the toggle says. The downloads were read in the code and have not been built through
the page. On the command line, the `export` command writes the four tables from a folder of
updates and prints their paths; these tables are not anonymised.

```bash
uv run xerscope export data/sample --out export --format csv
```

### Write your own standard in TOML

Use this guide to run your company's own checks and targets. Follow these steps:

1. Write the commented template to a file. The command prints `written my.toml`.
   ```bash
   uv run xerscope standards --template my.toml
   ```
2. List the rules and their parameters.
   ```bash
   uv run xerscope standards --rules
   ```
3. Edit the `my.toml` file. Give the standard an `id` and a `name` of its own, and write one
   `[[metric]]` table per check, each with an `id`, a `name` and a `rule`. The file format is in
   [The standard file](#the-standard-file).
4. Run the standard on an update. The table is titled with the standard's name; a mistake in
   the file stops the command with one line that names the file and the fault.
   ```bash
   uv run xerscope check data/sample/PRJ-ALPHA_2026-10-19.xer --standard my.toml
   ```

To use the standard in the app, open **Use your own standard** on the **Schedule health** page
and add the file under **Upload a standard (.toml)**; the standard is kept for the session. To
offer standards to every session, start the app with `uv run xerscope app --standards FOLDER`,
where `FOLDER` holds your `.toml` files; a file added to it is seen without a restart. To change
the target of a built-in check, the **Audit** page gives the `[[metric]]` block to copy. For the
rules in detail, see [docs/standards.md](standards.md#your-own-standard).

### Compare xerscope with P6

Use this guide to hold xerscope's numbers against P6's on the same file. P6's own menus are
outside what this guide has checked. To compare the counts of P6's Check Schedule report with
xerscope's, follow these steps:

1. In P6, run Check Schedule on the same project, data date and baseline, and note the found
   and total counts of each line.
2. Write the counts in a CSV file named `p6-summary.csv`, with the columns `id`, `found` and
   `total` and the ids that xerscope prints. This example holds xerscope's own counts on the
   demo, so that the next command reports a match:
   ```text
   id,found,total
   P6-01,2,23
   P6-06,3,22
   ```
3. Run the check with the `--expect` option.
   ```bash
   uv run xerscope check data/sample/PRJ-ALPHA_2026-10-19.xer --expect p6-summary.csv
   ```
   After the table of results, the command prints one line per count compared, with a `match`
   column, then `all counts match`. When a count differs, it prints the number of differences
   and returns the exit code 1.

In the app, the same comparison is on the **Schedule health** page, in **Compare with a P6
Check Schedule report**: enter the counts in **Found (report)** and **Total (report)**, or add
the CSV under **Report counts (.csv)**. Lines left empty are not compared.

To compare planned and earned value activity by activity, follow these steps:

1. In P6, save the Activities view as a CSV file with the columns Activity ID, Planned Value
   Labor Units, Earned Value Labor Units and Schedule % Complete. Use the same data date and
   baseline as the file: nothing checks it for you.
2. Run the `pv-compare` command. Replace `ACTIVITIES_CSV` with the path of the CSV file.
   ```bash
   uv run xerscope pv-compare data/sample/PRJ-ALPHA_2026-10-19.xer --baseline data/sample/PRJ-ALPHA_2026-08-31.xer --p6 ACTIVITIES_CSV
   ```
3. Read the totals table that the command prints: PV and EV by xerscope, by P6, and the gap,
   for the matched activities and for the activities that only one side holds. The five tables
   written in the `pv_compare` folder give the gap by Schedule % band, by candidate cause and by
   calendar, and the activities in gap.

If the export names a column otherwise, name it with `--column`, for example
`--column pv_hr="PV Labor Units"`. In the app, the same comparison is on the **Debug** page, in
the block **10 · PV against a P6 export**.

### Run with the local Docker image

Use this guide to run the app in a container on your own machine instead of installing uv and
Python. No Docker command of this guide has been run: the statements come from the `Dockerfile`
and `compose.yaml` files. Building the image needs network access and Docker with BuildKit.
Follow these steps in the folder of the source:

1. Create the folder that the container reads, and copy your `.xer` files into it.
   ```bash
   mkdir -p exports
   cp data/sample/*.xer exports/
   ```
2. Build the image and start the container.
   ```bash
   docker compose up -d --build
   ```
3. In your browser, open `http://localhost:8501`, and read the files as in
   [Load files and choose the baseline](#load-files-and-choose-the-baseline). The window opens
   on `/data`, which is the `exports` folder, mounted read-only.

The container is published on `127.0.0.1` only. The upload, the folder field (limited to
`/data`) and the **Debug** page are available. To give a baseline file, put it in
`exports/baselines/` and choose it in **Baseline file in the folder**, or upload it in the
window; a baseline `.xer` placed directly in `exports/` is listed among the updates. After an
update of the source, run `docker compose up -d --build` again. To run a command of the command
line in the image, pass it after the image name; `crosscheck` does not run in the image, and a
command that writes files needs a writable folder mounted in the container.

```bash
docker run --rm -v "$PWD/exports:/data:ro" xerscope check /data --standard P6
```

## Reference

This part describes the command line, the app and their settings.

### Command line

The following table lists the 12 commands. `uv run xerscope COMMAND --help` prints the options
of a command; some options are listed there without a description.

| Command | Purpose | Positional arguments |
|---|---|---|
| `app` | Launch the web app | None |
| `info` | Summarise updates, one line each | `paths`: one or more files or folders |
| `check` | Run a standard | `paths`: one or more files or folders |
| `standards` | List standards and rules, or print the template | None |
| `recalc` | Reschedule like P6 and compare with the stored dates | `paths`: one or more files or folders |
| `changelog` | List what changed between two files | `old`, then `new`: two files |
| `export` | Write the Power BI tables | `folder`: one folder |
| `crosscheck` | Compare xerscope with MPXJ | `paths`: one or more files or folders |
| `pv-compare` | Compare PV and EV with a P6 Activities export | `path`: one file, the update |
| `sample` | Generate the demo series | None |
| `ask-bench` | Score the reading of the **Ask the schedule** field | `path`: one file or one folder; the latest update is read |
| `lexicon` | List or build the words the Ask field reads as one | `folder`: an optional folder of `*.toml` groups; or `build`, then `source`, a folder of `.xer` files |

The following rules apply to the commands that read files:

- A folder stands for the `.xer` files directly in it, in any letter case. Subfolders and other
  files are not read.
- A file named explicitly is read whatever its extension. A P6 XML export named as an update is
  read for one of its baselines, without a warning.
- `~` is expanded in the paths of `info`, `check`, `recalc`, `crosscheck` and `ask-bench`, and
  in the three path options of `app`.
- `info`, `check` and `export` read the files in data date order, then by file name. `recalc`
  reads them in the order given. `info`, `check`, `export` and `ask-bench` refuse two files
  with the same data date.
- In a folder, one unreadable `.xer` file stops the command, except for `lexicon build`.
- Existing output files are overwritten without a question. Nothing is written except where an
  option or a default folder says so.

#### Options

The following table lists every option. *Off* is the default of an option that takes no value.

| Command | Option | Default | Meaning |
|---|---|---|---|
| `app` | `--data DATA` | None | Folder of weekly `.xer` files that the Files window opens on. Passed to the app as `XERSCOPE_DATA`, made absolute. |
| `app` | `--baseline BASELINE` | None | Baseline `.xer`, or a P6 XML export holding the baseline. Passed as `XERSCOPE_BASELINE`. The kind of file is told from its content. |
| `app` | `--standards STANDARDS` | None | Folder of standard `.toml` files. Passed as `XERSCOPE_STANDARDS`. |
| `app` | `--port PORT` | `8501` | Port, an integer. |
| `app` | `--host HOST` | `localhost` | Interface to listen on. `0.0.0.0` exposes the schedules to the network; no warning is shown at run time. |
| `check` | `--standard STANDARD` | `P6` | `P6`, `DCMA`, `DECM` or `INTEGRITY` in any letter case, or the path of a `.toml` file. The help text names only P6 and DCMA. |
| `check` | `--baseline BASELINE` | None | One baseline file, an XER or a P6 XML export, for every update. |
| `check` | `--planned-baseline` | Off | Measure each file against its own planned dates (`target_*`). |
| `check` | `--baseline-in-file` | Off | Measure each file against the P6 Project Baseline it holds (`sum_base_proj_id`). Needs distinct file names. |
| `check` | `--out OUT` | None | Write every result to this CSV, one row per check and per file. The folder must exist. |
| `check` | `--flagged DIR` | None | Write the items found, one CSV per file and per check that found something, named `<file name without extension>_<check id>.csv`. The folder is created. |
| `check` | `--expect CSV` | None | Compare with counts typed from P6's Check Schedule summary. Columns `id`, `found`, `total`, plus `file` when several files are checked. |
| `check` | `--fail-on {none,fail,error}` | `none` | `fail`: exit code 1 when a result is `fail` or `error`. `error`: exit code 1 on `error` only. Not evaluated when `--expect` finds a difference. |
| `standards` | `--rules` | Off | List the 68 rules, each with its unit, its parameters and their defaults, and its method. |
| `standards` | `--template [FILE]` | Off | Write the template of a standard to `FILE` in UTF-8, or print it when no file is named. |
| `recalc` | `--out OUT` | None | Write the recalculated dates and float of every activity to this CSV. With several files, one CSV per file, named `<file name without extension>_<name given>`. |
| `recalc` | `--report` | Off | Group the differences by activity shape. |
| `recalc` | `--show SHOW` | `20` | Number of difference lines to print, for activities and again for assignments. |
| `changelog` | `--out OUT` | None | Write every change to this CSV, one row each. |
| `export` | `--out OUT` | `export` | Folder to write to, created if missing. |
| `export` | `--format {parquet,csv}` | `parquet` | File format of the tables. |
| `crosscheck` | `--out OUT` | None | Write every comparison to this CSV. |
| `crosscheck` | `--cpm` | Off | Compare the recalculation with MPXJ's scheduler. |
| `crosscheck` | `--p6` | Off | Read the paths as folders of the P6 held-out sets and compare the recalculation with what P6 23.12 scheduled. |
| `crosscheck` | `--show SHOW` | `20` | Number of differences to print, for `--cpm` and `--p6`. |
| `pv-compare` | `--baseline BASELINE` | None | Baseline `.xer` or P6 XML export. One of `--baseline` and `--planned-baseline` is required. |
| `pv-compare` | `--planned-baseline` | Off | Use the update's planned dates (`target_*`). |
| `pv-compare` | `--p6 CSV` | Required | P6 Activities view saved as CSV. |
| `pv-compare` | `--column FIELD=HEADER` | P6's headers | A column that the export names otherwise. Repeatable. |
| `pv-compare` | `--tolerance H` | `0.01` | Gap in hours under which an activity agrees. |
| `pv-compare` | `--p6-total H` | None | PV labor units total shown by P6. Adds a totals line. |
| `pv-compare` | `--out OUT` | `pv_compare` | Folder for the five tables, created if missing. |
| `sample` | `--out OUT` | `data/sample` | Folder to write to, created with its parents. |
| `sample` | `--weeks WEEKS` | `8` | Number of weekly files. 0 or less writes nothing. |
| `ask-bench` | `--cases CASES` | None | TOML file of `[[case]]` sentences with known filters. Repeatable. The command needs `--cases`, `--self` or both. |
| `ask-bench` | `--self` | Off | Score the file's own labels, said every way the grammar reads. |
| `ask-bench` | `--anonymize` | Off | Score `--cases` on the anonymised copy of the file. |
| `ask-bench` | `--lexicon LEXICON` | None | Folder of `*.toml` synonym groups to add. |
| `ask-bench` | `--show SHOW` | `20` | Missed sentences to print per set. |
| `lexicon` | `--word WORD` | None | Print the words read as this one. |
| `lexicon` | `--out OUT` | None | With `build`: the lexicon folder. Its `generated` and `suggested` subfolders must exist. |
| `info`, `check`, `recalc`, `changelog`, `export`, `pv-compare` | `--project PROJECT` | Chosen by rule | Project short name (`PROJECT.proj_short_name`), exact and case-sensitive, for files that hold several projects. `changelog` applies it to both files, `pv-compare` to the update. |

When several baseline options of `check` are given, the first that exists wins for each update:
the baseline in the file, then the `--baseline` file, then the planned dates, else none.

#### Output

The following table says what each command prints on standard output and what it writes.

| Command | Prints | Writes |
|---|---|---|
| `app` | `You can now view your Streamlit app in your browser.` and `URL: http://localhost:<port>`. | Nothing. |
| `info` | One line per update: `data_date`, `source`, `forecast_finish`, `finish_shift_wd` (working days against the previous line, negative when the finish goes later), `activities`, `complete`, `critical`, `relationships`. Load warnings go to stderr as `warning: ...`. | Nothing. |
| `check` | Per update, a title line `<standard name> · <file> · data date YYYY-MM-DD · baseline <label or none>`, then a table: `id`, `check`, `target`, `actual` (two decimals, no unit), `found`, `total`, `status`. A check that is not computed prints `NaN`, `<NA>`, `<NA>` and `n/a`. With `--expect`: the comparison, then `all counts match` or, on stderr, `<n> difference(s)`. | With `--out`: a CSV with the columns `file`, `data_date`, `id`, `group`, `check`, `description`, `target`, `result`, `count`, `actual`, `found`, `total`, `status`, `note`, announced by `written <path>`. With `--flagged`: the CSV files of the items found. |
| `standards` | Each built-in standard as `<id> <name> (<n> metrics)`, then one line per check with its id, name, target and rule. | With `--template FILE`: the template, announced by `written <FILE>`. |
| `recalc` | Per file: a title line with the number of activities, the data date and the recalculated finish; one line per field, `<identical> / <compared> identical`, for `early_end_date`, `early_start_date`, `free_float_hr_cnt`, `late_end_date`, `late_start_date` and `total_float_hr_cnt`; a table of the differences (`task_code`, `field`, `stored`, `computed`, `gap_hr`, `agree`); the assignments line; the warnings. | With `--out`: a CSV of the recalculated values, not of the comparison, with the columns `task_code`, `status_code`, `es`, `ef`, `remaining_start`, `ls`, `lf`, `tf_hr`, `ff_hr`, `resource_dependent`, `longest_path`, `rem_override_hr`, `task_name`. |
| `changelog` | A table: `category`, `change`, `count`. The categories are Project, Scope, Tasks, Durations, Relationships, Progress, Dates, Float, Constraints, Resources, Calendars and Options. | With `--out`: a CSV with the columns `category`, `change`, `task_code`, `task_name`, `wbs_code`, `field`, `before`, `after`, `delta`, `unit`, announced by `written <file> (<n> changes)`. |
| `export` | The four paths written. | `dim_snapshot`, `fact_activity`, `fact_relationship` and `fact_assignment`, with the extension of the format. The tables are not anonymised. |
| `crosscheck` | `agree` and `checks` per file, then `<n> disagreement(s) out of <m> checks`. | With `--out`: a CSV of every comparison. |
| `pv-compare` | `<update> at <data date> against <csv> (tolerance 0.01 h)`; a totals table by group (`all`, `matched`, `only P6`, `only xerscope`, `in update, not in baseline`, `in baseline, not in update`); `<n> activities in gap; tables written to <folder>/`. | `10_pv_p6_totals.csv`, `10_pv_p6_by_schedule_pct.csv`, `10_pv_p6_gap_causes.csv`, `10_pv_p6_by_calendar.csv` and `10_pv_p6_activities_in_gap.csv`. Only the last one holds activity codes and names. |
| `sample` | The paths written. | One file per week from 2026-08-31, named `PRJ-ALPHA_<data date>.xer`. The content is the same on every run. |
| `ask-bench` | The scores. | Nothing. |
| `lexicon` | The groups of the `*.toml` files of the folder, one per line, then `<n> group(s), <m> word(s) in <FOLDER>`; a line `error: <file>: <reason>` for a file that does not load. Without a folder: `0 group(s), 0 word(s)`, because no lexicon ships with xerscope. | `lexicon build FOLDER --out LEXICON_FOLDER` reads the `.xer` files of `FOLDER` (64 MB each at most) and writes `generated/variants.toml` and `generated/report.txt` under the lexicon folder. |

The `app` command opens no browser and stays in the foreground. It does not check that its
paths exist, keeps a variable already set in the environment when its option is not given, and
accepts no other Streamlit option. The `crosscheck` command, without an option and with
`--cpm`, needs Java and the optional extra installed with `uv sync --extra crosscheck`; with
`--p6` it needs neither. With `--cpm` and without the `XERSCOPE_MPXJ_CPM_JAR` variable, it uses
the scheduler of the released MPXJ and prints a warning. For the lexicon of a hosted app, see
[docs/deploy.md](deploy.md#10-the-gantt-ask-field).

CSV files are UTF-8 with a byte order mark and a comma separator. Numbers have four decimals
and dates read `YYYY-MM-DD HH:MM`. A text cell that a spreadsheet would run as a formula is
neutralised. A spreadsheet can read the status `n/a` as an empty cell. The folder of a `--out`
CSV and of `standards --template FILE` must exist.

#### Columns of the P6 Activities export

The following table gives the fields of `pv-compare --column` and the headers that the command
looks for in the CSV. Headers are matched without regard to letter case or repeated spaces. The
file name must end in `.csv`, and the separator can be a comma, a semicolon or a tab.

| Field | Header expected | Required |
|---|---|---|
| `task_code` | Activity ID | Yes |
| `pv_hr` | Planned Value Labor Units | Yes |
| `ev_hr` | Earned Value Labor Units | Yes |
| `schedule_pct` | Schedule % Complete | Yes |
| `bl_hr` | BL Project Labor Units, or Budgeted Labor Units | No |
| `status` | Activity Status | No |
| `bl_start`, `bl_finish` | BL Project Start, BL Project Finish | No |
| `start`, `finish` | Planned Start, Planned Finish | No |

#### Demo series

The following table lists the events planted in the series that `sample` writes. Weeks are
counted from 0, the first file.

| Week | Event | What it shows |
|---|---|---|
| 0 | No progress; P2030 is a 60-day activity | The baseline; a high duration |
| From 2 | E1030 and P2030 progress slowly | Slippage, float erosion |
| 4 | Activity C3045 is added; E1040 loses 3 days | A scope change; PPC below 100 % |
| 5 | The remaining duration of P2030 grows by 10 days | Negative float through the hard constraint of X4050 |
| 6 | The SS+10 link from C3050 to X4030 becomes FS; C3010 has an actual finish after the data date; E1020 loses 7 days | A logic change; an invalid date; PPC below 100 % |
| Always | E1040 to E1050 has a 3-day lead; K5040 has no successor; K5040 and E1050 have no resources; `task_id` changes in every file | A lead, an open end, missing resources, matching by Activity ID |

#### Exit codes

The following table gives the exit codes of every command except `app`, which returns the exit
code of Streamlit.

| Code | Meaning | Cases |
|---|---|---|
| 0 | Done | Every command that ends normally, `recalc` with differences and `ask-bench` with low scores included. |
| 1 | A finding | `check --fail-on` (stderr: `<n> result(s) with status error/fail`); `check --expect` (stderr: `<n> difference(s)`); a `crosscheck` difference; a `lexicon` file that does not load. |
| 1 | A command that cannot do its work | `ask-bench` without `--cases` and `--self` (stderr); `lexicon build` when `generated/` or `suggested/` is missing, no file passes its check or the suggestions file is not TOML (stdout); `crosscheck` without its extra (a Python traceback). |
| 2 | Input that cannot be used | A missing path, a file cut short or damaged, an unknown standard: one line `xerscope: <reason>` on stderr. A mistake in the command itself: the usage, then a line `xerscope: error: ...` or `xerscope <command>: error: ...`. `lexicon build` without `FOLDER` or `--out`: its usage on stdout. |

### Web app

The app is one browser page with a sidebar, a navigation and a window for the files.

#### Pages

The following table lists the pages by navigation group. The update column says which update a
page reads. *Shared* means the **Update** list, whose choice carries over to the other pages
that have one; it starts on the latest update.

| Group | Page | Update | Content |
|---|---|---|---|
| Schedule | **Overview** (opening page) | Latest | **Forecast finish**, **Shift since first update**, **Tasks complete**, **Critical tasks**; **Score by standard**, one card per available standard, computed in the background; **Forecast finish by update**; **Updates loaded**; **Limits**, drawn when the files hold something xerscope reads differently from P6. |
| Schedule | **Gantt & WBS** | Shared | **Compare with**; **Ask the schedule**; **WBS**; cards **Focus**, **% complete**, **Forecast finish**, **Labor hours**, **Open critical**; filters **Status**, **Float**, **Search**, **Task code (P6 activity code)**; **Logic links** (off), **Hide LOE** (on), **Timescale**; the chart, grouped by WBS, with the columns **Activity / WBS**, **% complete**, **Float (wd)** and the buttons **Collapse all**, **Expand all**, **Level**; **Task**; the task card and **History across updates**; **Population, step by step**; **Table view**. |
| Analysis | **Schedule health** | Shared | **Standard** (starts on P6 Check Schedule), **Failed checks only**; score and count cards; **Results**; **Show the sets of**; **Detail by check** with **Expand all**; **Trend across updates**; **Compare with a P6 Check Schedule report**; **Use your own standard**. |
| Analysis | **Audit** | Shared | **Standard**, **Check**; **Settings for this audit** (**Rule parameters**, **Target**, **Reset**); **Calculation**; **Sets**; **Calculation sheet: population, fields, sources, worked example** (P6 standard only); **Settings: how to change this check for good**. |
| Analysis | **Changelog** | **From (older)**, **To (newer)** | Buttons **Previous**, **4 back**, **First**; six cards; **Changes by category**; **All changes** with **Category**, **Change**, **Search**; **Every week, side by side**. |
| Analysis | **Delay analysis** | Shared | **Finish before replanning**, **Finish shown**, **Longest path float**, **Tasks matched**; **Step by step**; the revisions within and beyond a lookahead of 6 weeks; **Longest path**; **Every update**. The baseline is not read. |
| Analysis | **Earned value** | Shared | **P6 view: the file's baseline** (off); the cards; the Earned Schedule figures; **S-curve** with **Show as % of BAC** (off); **Performance indices by update**; **How it is calculated**; **The weeks of the 4 weeks' figures**; **Earned hours by task**. |
| Analysis | **Milestone trend** | Latest | **Milestones and key tasks (up to 6)**, **Finish milestones**, **Critical milestones**, **Clear**; the chart; **Slippage**; **Data**. |
| Analysis | **PPC & progress** (heading: **PPC & weekly progress**) | **Week ending** | **PPC target (%)** (80), **Include commitments late at W−1** (selected); **Percent plan complete by week**; **Commitments**; **Progress by WBS**; **Milestones committed**; **Unplanned work**; **Progress by task**; **Start and finish variance**; **Lookahead reliability**. |
| Data | **Export for Power BI** | Latest | The four tables with their rows and columns; **Preview fact_activity**; **Format**; the download; **Anonymized XER extract**. |
| Data | **Debug** | Shared | What xerscope read from the file and what it decided, in 14 numbered blocks, and **Diagnostic**. Hidden when the data is locked. |

The following elements are on every page:

- Under the title, a line that is also a button: `<project codes> · status date <date> · BL
  <where> (<rule>) · EV <basis> · costs on|off · N files · K projects`. Clicking it opens the
  **Files and baseline** window. The rule is one of "the window's choice", "assigned in this
  update", "origin of the series" and "P6 view: this update's baseline".
- A table with more than 10 rows has a **Filter columns** control. A text filter keeps the rows
  that contain the text. A number filter reads `<0`, `>=5`, `=3` or `-10..0`. A date filter
  reads `>2026-11-01`, `2026-11` or `2026-11..2026-12`.
- A table or chart has a **How to read** control. A row selected in a table of activities gives
  a button that opens the activity in the Gantt. A missing value is written `–`.
- The tables cannot be exported or copied through their own toolbar; the download buttons are
  the way out.

The blocks of the **Debug** page are drawn in this order: **1 · Scheduling options
(SCHEDOPTIONS, PROJECT)**, **2 · Expected finish**, **3 · INT-01 / INT-03 differences**,
**4 · Check Schedule parameters applied (P6 standard)**, **5 · Baseline and calendars**,
**6 · Load warnings**, **7 · Costs in the file (TASKRSRC, PROJCOST)**, **8 · Earned Value
settings of the WBS (PROJWBS)**, **9 · XER tables and planned value labor units**, **10 · PV
against a P6 export**, **11 · Project settings (PROJECT, TASK.complete_pct_type)**,
**13 · Calendar detail (CALENDAR.clndr_data, hours per time period)**, **12 · App runtime
(where the theme and fonts come from)**, **14 · Ask vocabulary (variants generated per source
column)**. Block 12 is not drawn when the data is locked.

#### Downloads

The following table lists the downloads. `<date>` is the data date as `YYYY-MM-DD`. With
**Anonymous exports** on, a download comes after **Prepare anonymized downloads** and its label
ends with " · anonymized".

| Page | Button | File |
|---|---|---|
| Gantt & WBS, **Table view** | **Download CSV** | `gantt_<date>.csv` |
| Schedule health | **Summary (CSV)** | `<standard id>_<date>_summary.csv` |
| Schedule health | **All flagged items (CSV)** | `<standard id>_<date>_flagged.csv` |
| Schedule health | **Prepare all sets**, then **All sets (CSV)** or **All sets (ZIP)** | `<standard id>_<date>_sets.csv` or `.zip` |
| Schedule health, a check's panel | **Download list (CSV)** | `<check id>_<date>.csv` |
| Schedule health and Audit, a set | **Download CSV** | `<check id>_<date>_counted.csv`, `_not_counted.csv`, `_excluded.csv`; on Audit also `_removed.csv` |
| Schedule health | **Download the template** | `my-standard.toml`, never anonymised |
| Changelog | **Download changelog (CSV)** | `changelog_<from date>_<to date>.csv` |
| Delay analysis | **Download steps (CSV)** | `half_step_<from date>_<to date>.csv` |
| Delay analysis | **Download series (CSV)** | `half_step_series.csv` |
| Delay analysis | **Download longest path (CSV)** | `longest_path_churn.csv` |
| Earned value | **Download CSV** | `earned_<date>.csv` |
| Earned value | **Download deleted tasks (CSV)** | `earned_deleted_<date>.csv` |
| PPC & progress | **Download CSV** | `progress_<date>.csv` |
| PPC & progress | **Download variances (CSV)** | `variances_<date>.csv` |
| Export for Power BI | **Download PARQUET tables (.zip)** or **Download CSV tables (.zip)** | `<project code>_xerscope_<format>.zip`; anonymised: `xerscope_<format>.zip` |
| Export for Power BI | **Build anonymized extract**, then **Download anonymized XER (.zip)** | `xerscope_anonymised_xer.zip`, always anonymised |
| Debug | **Build calendar detail**, then **Download calendar detail (.zip)** | `xerscope_calendars_<date>.zip` |
| Debug | **Build diagnostic**, then **Download diagnostic (.zip)** | `xerscope_diagnostic.zip` |

In an anonymised download, Task IDs, WBS codes and project ids are renamed, names are rebuilt
from the new codes, the columns xerscope writes itself are kept, and any other text of the file
is emptied. Dates, durations, units and logic are kept. Costs are written as 0. The new codes
are the same in every download of one session and change with the session.

#### Sidebar

The following table lists the sidebar from top to bottom. The lines from **Baseline** to
**Costs** exist once a series is read.

| Element | Kind | Default | Effect |
|---|---|---|---|
| **Files · none read**, then **Files · N files · K projects** | Button | Not applicable | Opens the **Files and baseline** window on its **Files** section. Its tooltip gives the projects read and the first and last data dates. |
| **Reading the updates · n/N** | Progress | Not applicable | Shown while several files are read in the background. |
| Load errors | Messages | Not applicable | One per file that could not be read; the other files load. |
| **Baseline · NAME** | Button | Not applicable | Opens the window on its **Baseline** section. The name is "in each file", "planned dates", "none", "update" with the data date of the update, the baseline file's name, or "file missing". |
| Baseline lines | Captions and warnings | Not applicable | The baseline's label, tasks and labour hours, and the warnings about the baselines. |
| **Anonymous exports** | Toggle | On | Anonymises the downloads. The pages always show the files' own data. |
| **Costs** | Checkbox | Cleared | Shows the cost figures on **Earned value**. |
| **Glossary** | Expander | Closed | Every acronym of the pages with its full name, definition and source (37 entries). |

#### Files and baseline window

The following table lists the controls of the window. Nothing applies before **Done**, and
closing the window in another way drops every change. To list the files, the window reads only
the project, the data date and the number of activities of each file.

| Section | Control | Default | Effect |
|---|---|---|---|
| Files | **Upload .xer files** | Empty | Takes several `.xer` files, 200 MB each at most. Not drawn when the data is locked. |
| Files | **…or read a folder** | The `--data` folder | Lists the `.xer` files of the folder. The folder must lie under the folder root. Not drawn when the data is locked. |
| Files | A checkbox per file: `<file> — <project> · <dd Mon YYYY> · N tasks` | Cleared; a reopened window selects the last validated choice | Selects the file. The label adds ` · K projects` for a file of several projects, ` — same date as <file>` for a double, or reads `<file> — unreadable`. |
| Files | **Select all**, **Clear** | Not applicable | Select every readable file except the doubles of one data date; clear all. The counter reads **N of M ticked**. |
| Files | **Project read from each file · why** | The project chosen by rule | One line per file, and a list of projects for a file that holds several. |
| Files | **Selection details** | Closed | A table: file, project, the rule that picked it, data date and its source, baseline in the file, tasks. |
| Baseline | **Baseline (BL)** | See the paragraph that follows this table | The baseline of the series. |
| Baseline | **Earned value basis** | **Budgeted · planned dates** | Also offers **Budgeted · current dates** and **At completion · current dates**. No check is rerun. |
| Baseline | **Link renumbered tasks by GUID** | Cleared | Measures a renumbered activity against the baseline activity that has its GUID. |
| Baseline | **When a file has no baseline** | **None** | Drawn with **Baseline in each file (P6 Project Baseline)**. Offers the other entries of **Baseline (BL)**. |
| Baseline | **Baseline of FILE (undecided)** | None chosen | For an update whose baseline the export does not settle: **None: not measured**, **Baseline ID, held by version ID** or **The fallback above**. |
| Baseline | **Baseline file in the folder** | **(none)**, or the folder's single `.xml` file | The `.xml` files next to the updates and the `.xer` and `.xml` files of the `baselines` subfolder. |
| Baseline | **Baseline .xer, or a P6 XML export with its baselines** | Empty | Takes one `.xer` or `.xml` file. Not drawn when the data is locked. |
| Baseline | **Project read from the baseline file** | The project chosen by rule | For a baseline XER of several projects. |
| Both | **Done** | Not applicable | Applies the choices. Disabled while two uploads share a name. |

**Baseline (BL)** offers, in this order: **Baseline in each file (P6 Project Baseline)**, only
when a file holds a usable baseline or a P6 XML export is at hand; **Separate baseline file**;
each loaded update as `<YYYY-MM-DD> · <file name>`; **Planned dates in each file (target_*)**;
**None**. It starts on **Baseline in each file (P6 Project Baseline)** when a file holds a
usable baseline and no baseline file was named at start, on **Separate baseline file** when one
was named, and otherwise on the first update. After **Done** on a new choice of files, the
window opens again by itself on its **Baseline** section, and the pages wait for a second
**Done**. A later change of baseline takes one **Done**.

#### Keyboard shortcuts

The following table lists the shortcuts that the app declares. They were read in the code and
have not been pressed in a browser.

| Key | Where | Effect |
|---|---|---|
| `F` | Any page | Opens the window on its **Files** section. |
| `B` | Any page, once a series is read | Opens the window on its **Baseline** section. |
| `Ctrl+Enter` | **Files and baseline** window | **Done**. |
| `Esc` | **Files and baseline** window | Closes the window without applying. |

### Environment variables

The following table lists the variables that you can set before you start xerscope. A yes-or-no
variable is on for `1`, `true` or `yes` in any letter case, and off for any other value.

| Variable | Default | Effect |
|---|---|---|
| `XERSCOPE_DATA` | Not set | Folder of weekly `.xer` files that the Files window opens on. Set by `app --data`. |
| `XERSCOPE_BASELINE` | Not set | Baseline `.xer`, or a P6 XML export holding the baselines. Set by `app --baseline`. |
| `XERSCOPE_STANDARDS` | Not set | Folder of standard `.toml` files, read again at each run of a page. A file that reuses the id of a built-in standard replaces it. A folder that does not exist is ignored without a message. Set by `app --standards`. |
| `XERSCOPE_FOLDER_ROOT` | `XERSCOPE_DATA`, else your home directory | The folder that a path entered in the Files window must lie under. The value `/` accepts no folder but `/`. |
| `XERSCOPE_DATA_LOCKED` | Off | Yes or no. On: no folder field, no upload of a schedule or of a baseline, and no **Debug** page; only the files of `XERSCOPE_DATA` are offered. |
| `XERSCOPE_DEBUG_PAGE` | Off | Yes or no. On: the **Debug** page is shown even when the data is locked. |
| `XERSCOPE_LOAD_WORKERS` | One process per core, at most 2 | Number of files read at once. `1` reads in the calling thread. An invalid value is ignored. |
| `XERSCOPE_LEXICON` | Not set | Lexicon folder of the **Ask the schedule** field, with the subfolders `curated`, `generated` and `suggested`. |
| `XERSCOPE_SYNC_LOAD` | Off | Yes or no. On: the files are read and the scores computed in the page run instead of in the background; **Overview** then has a **Compute scores** button. |
| `XERSCOPE_MPXJ_CPM_JAR` | Not set | Path of the MPXJ scheduler build that `crosscheck --cpm` uses. |

A further variable, `XERSCOPE_STRICT_READINGS`, serves the automated tests only.

### Standards

The following table lists the built-in standards.

| Identifier | Name | Checks | Groups |
|---|---|---|---|
| `P6` | P6 Check Schedule | 18 lines for 17 checks | Inflexibility and Inefficiency, Inaccuracy, Lateness |
| `DCMA` | DCMA 14-Point | 14 | None |
| `DECM` | DCMA DECM v8.0 (schedule) | 16 | Logic; Constraints and float; Critical path; Baseline, forecast and actual dates |
| `INTEGRITY` | Integrity | 8 (INT-01 to INT-08) | None |

Calculation sheets exist for the P6 standard only. Three DECM checks (06A504a, 06A504b and
06A506c) compare each update with the latest update dated at least 28 days before it. The
checks that need a baseline are P6-12 and P6-13; DCMA-08, DCMA-11 and DCMA-14; and 06A501a.
DCMA-13 also reads `n/a` when the project has neither a Must Finish By date nor a baseline.

The following table lists the checks of the P6 standard with the targets of the built-in file.

| Identifier | Name | Group | Target |
|---|---|---|---|
| P6-01 | Logic | Inflexibility and Inefficiency | `< 5%` |
| P6-02 | Hard Constraints | Inflexibility and Inefficiency | `< 1%` |
| P6-03 | Soft Constraints | Inflexibility and Inefficiency | `< 5%` |
| P6-04 | Large Durations | Inflexibility and Inefficiency | `< 5%` |
| P6-05 | Long Lags | Inflexibility and Inefficiency | `< 5%` |
| P6-06 | Large Float | Inflexibility and Inefficiency | `< 1%` |
| P6-07 | Relationship Types | Inflexibility and Inefficiency | `> 90%` |
| P6-08 | Positive Lags | Inflexibility and Inefficiency | `< 5%` |
| P6-09 | Negative Lags | Inaccuracy | `< 1%` |
| P6-10a | Invalid Progress Before Data Date | Inaccuracy | `< 1%` |
| P6-10b | Invalid Progress After Data Date | Inaccuracy | `< 1%` |
| P6-11 | Resource / Cost | Inaccuracy | `< 1%` |
| P6-12 | Late Activities | Lateness | `< 5%` |
| P6-13 | BEI | Lateness | `> 0.95` |
| P6-14 | Negative Float | Lateness | `< 1%` |
| P6-15 | Out of Sequence | Inaccuracy | `< 2%` |
| P6-16 | Dangling Start Activities | Inaccuracy | `<= 0%` |
| P6-17 | Dangling Finish Activities | Inaccuracy | `<= 0%` |

The built-in file attributes P6-01 to P6-14 to the P6 Professional 24 help. The limit of
P6-04, P6-05 and P6-06 is 352 hours in that file. P6-10a and P6-10b are one criterion of the
score. The app writes `≤` and `≥` where the command line prints `<=` and `>=`.

#### The standard file

The following table describes the TOML file of a standard. `xerscope standards --template`
prints a commented example with 14 checks.

| Table | Key | Required | Values |
|---|---|---|---|
| `[standard]` | `id` | Yes | Letters, digits, `.`, `_` and `-`. An uploaded file cannot reuse the id of a built-in standard. |
| `[standard]` | `name` | Yes | Text, shown in the lists and titles. |
| `[standard]` | `description`, `source` | No | Text. |
| `[[metric]]` | `id` | Yes | Letters, digits, `.`, `_` and `-`. |
| `[[metric]]` | `name` | Yes | Text. |
| `[[metric]]` | `rule` | Yes | One of the rules that `xerscope standards --rules` lists. |
| `[[metric]]` | `target` | No | `<= 5%`, `>= 0.95`, `== 0`, `pass`, `info`, or none. The operators are `<`, `<=`, `>`, `>=` and `==`. |
| `[[metric]]` | `unit` | No | `%`, `count`, `ratio` or `pass/fail`. A unit other than the rule's own is accepted only between `%` and `count`. |
| `[[metric]]` | `params` | No | The parameters of the rule. |
| `[[metric]]` | `description`, `source`, `group`, `item` | No | Text. Checks with the same `item` are one criterion of the score. |

Twelve rules take parameters and are meant for a standard of your own: `missing_logic`,
`dangling`, `lag`, `relationship_type`, `constraints`, `float`, `duration`, `invalid_dates`,
`on_data_date`, `no_resource`, `late_vs_baseline` and `bei`.

### Fixed values and sizes

The following table lists values that are fixed in the code. No option, variable or control
changes them, except where the table says so.

| Value | Setting | Scope |
|---|---|---|
| Hours per day when a calendar gives none | 8 | Every conversion to working days |
| Total float at or under which an activity is critical | 0 working days | When the project defines nothing else |
| Total float at or under which an activity is near critical | 10 working days | Gantt colours and filters |
| Rows from which a table gets column filters | More than 10 | Every table of the app |
| Lookahead | 6 weeks | **Delay analysis** page |
| PPC target | 80 % | **PPC & progress** page, where it can be changed |
| Size of an uploaded file | 200 MB at most | The upload fields |
| Processes that read files | 2 at most | The app |
| Length of a sentence | 300 characters at most | **Ask the schedule** field |
| Milestones or activities picked | 6 at most | **Milestone trend** page |

## Troubleshooting

The following table lists symptoms, from the command line to the app. Messages are quoted as
the tool prints them; a part between angle brackets stands for a name or a number.

| Symptom | Cause | What to do |
|---|---|---|
| `xerscope: <path>: no such file or folder`, or `xerscope: [Errno 2] No such file or directory: '<path>'`; exit code 2 | A path given to a command does not exist. The `app` command does not check its paths and starts anyway. | Correct the path. |
| `xerscope: no .xer file in <folder>`; exit code 2 | The folder holds no file ending in `.xer`. Subfolders are not read. | Name the folder that holds the exports. |
| `<file>: incomplete file, no %E end line (still being copied, or cut short)` | The export is not complete. | Wait for the copy to end, or export the file again. |
| `<file>: not an XER file (no ERMHDR header, no tables)` | The file is not a P6 XER export. | Give a `.xer` file exported by P6. |
| `xerscope: unknown standard '<name>': use DCMA, DECM, INTEGRITY, P6 or a .toml file` | `--standard` names neither a built-in standard nor an existing file. | Use one of the four identifiers, or the path of your `.toml` file. |
| `several files per status date, keep one per date: <date>: <files>` (in the app, it ends with `Untick the others.`) | Two files have the same data date. | Keep one file per data date. |
| `<file>: project '<name>' not found (has [...])` | `--project` does not match a project short name of the file. The match is case-sensitive. | Use one of the names that the message lists. |
| `xerscope: --baseline-in-file needs distinct file names` | Two files of two folders have the same name. | Rename one, or check the folders one at a time. |
| `xerscope --version` prints the usage and an error | There is no `--version` option. | The version is 0.1.0. |
| `Port 8501 is not available`; exit code 1 | Another program, or another xerscope, uses the port. | Stop it, or start the app with `--port` and another number. |
| After `Ctrl+C`, a Python `KeyboardInterrupt` traceback follows `Stopping...` | The command does not catch the interrupt. Seen when the interrupt was sent by a tool; not checked by typing `Ctrl+C`. | Nothing: the app has stopped. |
| The Files window shows **Folder not found** | The folder does not exist, or you entered a relative path. A relative path is read from the app's own folder, so the path `data/sample` that the opening message suggests is not found. | Enter an absolute path or a path that starts with `~`. |
| `Folder outside <root>: set XERSCOPE_FOLDER_ROOT to read another tree` | The folder is not under the folder root: the `--data` folder when given, else your home directory. | Start the app with `--data` on that folder, or set `XERSCOPE_FOLDER_ROOT`. Do not set it to `/`. |
| The Files window shows **No .xer file in that folder** | The folder holds no `.xer` file directly in it. | Enter the folder that holds the exports. |
| A file reads `<file> — unreadable` in the Files window | The file cannot be read as an XER. Its tooltip gives the reason. | Export the file again. **Select all** skips it. |
| `<file>: no status date (PROJECT.last_recalc_date); the file is skipped` | The file carries no data date. | Export the project again once it has a data date. |
| `N files named <name>: untick all but one`; **Done** is disabled | Two uploaded files have the same name. | Clear the checkbox of all but one. |
| Every page shows `N files · K projects read. Choose the baseline in the window (...), then Done` | The files are read and the baseline is not confirmed yet. | Click the sidebar's **Baseline** line, then **Done**. |
| The sidebar shows **Baseline · file missing** | The `--baseline` path does not exist. | Restart with the right path, or choose another baseline in the window. |
| `Baseline not read: <file>: N baselines and none named as the Project Baseline: ...` | The P6 XML export holds several baselines and names none as the Project Baseline. On the command line the same reason comes with exit code 2. | In the app, choose **Baseline in each file (P6 Project Baseline)**: each update is then looked for by the baseline it names. |
| `Baseline not read: <file>: not an XER file (no ERMHDR header, no tables)` | An `.xml` file of the folder is not a P6 XML export. | Choose another file in **Baseline file in the folder**. |
| `<xml>: no baseline in this P6 XML export (tick them under Baselines to Export)` | The export was made without its baselines. | Export again from P6 with the baselines. |
| Checks read `n/a` with the note `needs a baseline`; **Earned value** says "Choose a baseline from the sidebar's Baseline line (...)" | No baseline is chosen, or the update's file has none. | Choose a baseline in the window, or give `--baseline`, `--planned-baseline` or `--baseline-in-file` to `check`. |
| Three DECM checks read `n/a` with the note `needs an update 28 days older` | 06A504a, 06A504b and 06A506c need an update dated at least 28 days before the one checked. | Load the earlier updates. On a weekly series the checks are computed from the fifth update. |
| A page says "Load at least two XER files to compare them." or a similar sentence | **Changelog**, **Delay analysis**, **PPC & progress** and **Milestone trend** compare updates. | Load at least two updates. |
| `N task(s) renumbered since the baseline: turn on Link by GUID in the Baseline window. ...` | Activity IDs changed since the baseline. | In the **Baseline** section of the **Files and baseline** window, select **Link renumbered tasks by GUID**. |
| "The word « x » is in neither this file nor the lexicon." | The **Ask the schedule** field does not know the word. | Use the file's own words, or click a label under **Did you mean**. |
| A download button is replaced by an error `<what> not written: it still holds values of ...` | The anonymiser found original values left in the output and refused to write it. | Nothing is written. To download the data with its own names, turn off **Anonymous exports**. |
| The page keeps an older look after an update of xerscope (other fonts) | By the app's own text: an old running copy, or a page that did not load the theme. The browser's part was not tested. | Stop the app and start it again with `uv run xerscope app`: it runs the code of the source folder as it is. Then reload the page with the cache bypassed (`Ctrl+Shift+R`). For the local image, run `docker compose up -d --build`. On the **Debug** page, block 12 shows what the running app read: `Config read` must say `yes`. |
| `check --expect` stops with `<csv>: columns total missing` or `<csv>: add a 'file' column, N files were checked` | The CSV lacks a column. | Give the columns `id`, `found` and `total`, and `file` when several files are checked. |
| `xerscope: pv-compare: give --baseline BL.xer or --planned-baseline` | `pv-compare` needs a baseline. | Add one of the two options. |
| `<csv>: column(s) not found for pv_hr; headers read: ... Name them with --column FIELD=HEADER.` | The P6 export names a column otherwise. | Add `--column` with the field and the header of your export. |
| `<file>: invalid TOML: ...`, `unknown rule '<name>'`, `needs a [standard] table with id and name`, or `id 'P6' is a built-in standard's; give yours another id` | The standard file has a fault. | Correct the file. `uv run xerscope standards --rules` lists the rule names. |
| `crosscheck` ends with a traceback and `RuntimeError: crosscheck needs the optional extra: uv sync --extra crosscheck` | The optional extra is not installed. | Run `uv sync --extra crosscheck`. Java must be on `PATH`: the automated tests use JDK 21 and 25. What the command prints without Java was not run. |
| `warning: MPXJ's released scheduler predates its out-of-sequence fix (#972); ...` | `crosscheck --cpm` runs without the pinned scheduler build. | Build it with `tests/reference/mpxj_cpm.py` and set `XERSCOPE_MPXJ_CPM_JAR` to its path. |
| A test run skips tests with `mpxj missing: no Java runtime on PATH` | The tests that use MPXJ need Java. | Install a JDK (21 or later) if you need those tests. |
| In the local Docker image, a baseline `.xer` placed in `exports/` is listed as an update | Every `.xer` file of the folder is listed. | Leave it unselected, or put it in `exports/baselines/`. |

## Limits

This part says what xerscope does not model and what has not been established. The measured
results are in the [Validation section of the README](../README.md#validation), and the open
work is in [docs/backlog.md](backlog.md).

### What xerscope does not model

The recalculation does not model resource leveling, multiple float paths (dates and float are
unaffected, but the float path numbers are not computed) or relationships to projects that are
not in the file. A file that uses them can show differences that are not errors of the file.
`recalc` and the **Debug** page warn when a file looks leveled. A working period that crosses
midnight counts no work, with a note.

That the result equals P6's is not something the code proves. It is measured against schedules
computed by P6 Professional 23.12.1, with a floor per reference set that the tests enforce; the
lowest floor is 98.2 % of stored values reproduced. For the conventions that no reference file
settles, see [docs/cpm.md](cpm.md#conventions-no-reference-file-settles).

Earned value has the following limits, detailed in
[docs/formulas.md](formulas.md#7-known-limits):

- Resource curves and manual future-period values are not modelled: planned value is spread
  linearly.
- The earned value technique "WBS milestones" and unknown techniques are not modelled: the
  activity % complete is used, and the page lists the activities.
- The ETC technique of each WBS is reported, not applied: ETC is the remaining hours.
- Actual cost, a cost CPI and a cost EAC are not modelled. Cost figures use the budgeted values
  whatever the earned value basis.

The code marks the readings of P6 Check Schedule that no source settles: a secondary hard
constraint (P6-02), an external link on one side only (P6-01), FF and SF relationships (P6-15),
and completed activities and links to other projects in the dangling checks (P6-16, P6-17). A
baseline read from a P6 XML export carries no GUID, so renumbered activities cannot be linked
to it.

xerscope has no login, no `--version` option, no language other than English, and no time
impact analysis. The values of [Fixed values and sizes](#fixed-values-and-sizes) cannot be
changed.

### What has not been established

The following points rest on reading the code or the configuration files, not on a run:

- Windows and macOS: every run was on Linux.
- Docker: no image was built and no container was started.
- A browser: the keyboard shortcuts, uploads, downloads built through the page, the **Ask the
  schedule** field through the page, and what a reload does to a session.
- A first installation: `git clone` and `uv sync --locked` on a machine without xerscope, and
  whether uv fetches Python by itself.
- Reading in the background: the progress bar and the worker processes.
- A P6 XML export with several baselines; files with several projects, with a baseline inside,
  with renumbered activities, with costs or with activity codes. The demo series has none of
  these.
- The memory that a large file needs.

## Glossary and related documents

This part defines the terms of the guide and lists the documents that complete it.

### Glossary

The following list gives the terms of this guide. P6 terms keep P6's spelling.

- **AC**: actual cost; here, the labour units actually spent to date, on every activity.
- **Activity ID**: P6's identifier of an activity (`TASK.task_code`); **Task ID** in the app.
- **BAC**: budget at completion; the baseline labour hours of the activities the update holds.
- **Baseline (BL)**: the plan that an update is measured against.
- **BEI**: Baseline Execution Index; activities completed over activities due by the data date.
  The P6 standard divides by every baseline activity.
- **Check**: one test of a standard, with a population, a target and a status.
- **Commitment**: a start or a finish that update W−1 plans on or before W's data date.
- **Criterion**: one or several checks that share an item and count once in the score.
- **Data date**: the date up to which the schedule is statused; **status date** in the app.
- **DCMA**: Defense Contract Management Agency, author of the 14-Point Assessment and of DECM.
- **DECM**: DCMA EVMS Compliance Metrics; here, its schedule metrics, version 8.0.
- **EAC**, **ETC**: estimate at completion (AC plus ETC); estimate to complete (remaining hours).
- **Earned value basis**: the baseline hours and dates that PV and EV use.
- **EV**: earned value; baseline labour units times Performance % Complete.
- **Forecast finish**: the latest finish of the project's activities.
- **FS**, **SS**, **FF**, **SF**: the four relationship types. In the app, **FF** is Finish to
  Finish, not free float.
- **Half-step**: the earlier update rescheduled with the later update's progress only.
- **LOE**, **WBS**, **MTA**: level of effort; work breakdown structure; milestone trend analysis.
- **P6 Project Baseline**: the baseline that a project names in `PROJECT.sum_base_proj_id`.
- **P6 XML export**: P6's XML export format, read by xerscope for its baselines.
- **Planned dates**: the `target_*` dates of an activity.
- **Population**: the activities or relationships that a check looks at.
- **PPC**: percent plan complete; commitments kept over commitments made.
- **PV**: planned value; baseline labour units times Schedule % Complete.
- **Recalculation**: xerscope's own scheduling of a file, compared with the stored dates.
- **Score**: criteria in pass over criteria in pass or fail.
- **Series**, **update**, **snapshot**: the updates of one project, ordered by data date; one
  `.xer` export of the schedule at one data date; an update once it is read.
- **SPI**, **SV**: schedule performance index (EV over PV); schedule variance (EV minus PV).
  **SPI(t)** and **TSPI** are the Earned Schedule indices, in time instead of hours.
- **Standard**: a list of checks with their targets, built in or written in TOML.
- **TA**, **TMR**: Tasks Anticipated and Tasks Made Ready, the lookahead measures of PPC.
- **TF**: total float.
- **W**, **W−1**: an update and the one before it.
- **wd**, **cal. d**: working days of the activity's calendar, or of the project calendar for
  a project total; calendar days.
- **XER**: P6's tab-separated export file.

### Related documents

The following documents complete this guide:

- [docs/it-deployment-guide.md](it-deployment-guide.md): hosting the app for a team.
- [docs/deploy.md](deploy.md): the remote deployment, and the lexicon of the Ask field.
- [docs/formulas.md](formulas.md): the formula and population of every number.
- [docs/standards.md](standards.md): the standards, their sources and their differences.
- [docs/cpm.md](cpm.md): the recalculation engine.
- [docs/backlog.md](backlog.md): what is known to be wrong, unproven or missing.
- [docs/architecture.md](architecture.md): the code, module by module.
- [docs/adr/README.md](adr/README.md): the architecture decision records.
- [README.md](../README.md): the overview of the project and its validation.
- [CONTRIBUTING.md](../CONTRIBUTING.md): the setup for contributors and the tests.
