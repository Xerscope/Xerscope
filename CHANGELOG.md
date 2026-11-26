# Changelog

All notable changes to xerscope are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions
[Semantic Versioning](https://semver.org/spec/v2.0.0.html): while the version is 0.y.z the
public API (the CLI, the `xerscope` package, the standards TOML) may still change between
minor versions.

A release is a git tag `vX.Y.Z` on `main`, cut by the maintainer after the version and date
below are filled in: `.github/workflows/image.yml` then publishes `ghcr.io/xerscope/xerscope:X.Y.Z`
and `xerscope-caddy:X.Y.Z` with their provenance (docs/deploy.md §7).

## [Unreleased]

Work since the changelog was started: the conformity plan and the global audit of 2026-11 (their
reports are kept outside the repository; what remains open is in `docs/quality-plan.md` and
`docs/backlog.md`).

### Added

- Documentation: a user guide (`docs/user-guide.md`, French in `docs/user-guide.fr.md`) laid out as
  concepts, a first run on the demo series, one how-to per goal, reference, troubleshooting, limits and
  glossary; an IT deployment guide (`docs/it-deployment-guide.md`, French in
  `docs/it-deployment-guide.fr.md`) for hosting on an internal server: flow matrix, accounts and secrets,
  container hardening against ANSSI-FT-082, origin of the images, procedures, known gaps. The README
  sections "Command line", "Web app" and "Definitions that matter" moved to the user guide.

- Reader (XER-01): a cell the file fills but the reader cannot type (a number or a date it cannot read, an
  infinite number, a date outside 1900-2200) still reads as blank, and is now warned of by table, column,
  count and Activity ID; an unreadable PROJECT.last_recalc_date says where the status date was taken from.

- Earned value: the Earned Schedule figures in three groups, one per question (where the project stands, at
  what pace, whether it ends on the planned finish), the pace of the last four weeks and since the first
  update as figures, a paragraph putting the figures in words (TSPI read on Lipke's band), and the weeks the
  4 weeks' figures add up. No figure changes.

- Baselines: a `baselines` subfolder of the updates' folder holds baseline files, .xer or P6 XML, offered as
  the separate baseline file under "baselines/<name>" and never read as updates, so a baseline exported as
  its own XER can be picked on a locked server even under the name of an update. A baseline XER that holds
  several projects (the project and the baseline exported with it) gets a project picker in the window.
- Health: each check that reads a baseline names in its row the one it was measured against, "name
  (Project ID) · kind"; Debug block 5 lists, for each update, the project and the baseline it points to
  and the baseline used.

- Baselines: a P6 Project Baseline held in the file is named as P6's Maintain Baselines names it, its name
  then its Project ID ("Terminal works - B1 (BL, P6 Project Baseline in two.xer)"); the Project ID alone
  when the file holds no name. The sidebar says in one line when updates measure earned value against a
  user's primary baseline in P6, which the file does not carry.
- Baselines: a page warns when P6's Update Baseline changed the baseline after the update's status date
  (Last Update Date, from the XER or the P6 XML): it may no longer be the plan the update was measured against.
- Baselines: `Baseline.kind` and `found_by` say how the baseline of an update relates to it (in file,
  exact, probable, chosen, fallback, planned, series) and what found it; set by every path of the app,
  read by one classifier (`app.baselines.kind_of`) for the context banner, the sidebar and the Debug
  page, so a baseline read from the export is no longer called "in file". An update left undecided by the
  resolution (the versions of the export around its project hold different baselines) is not measured,
  not even by the fallback, until the Files and baseline window gets a choice for it: one of the two
  candidate baselines (applied as "chosen", alerted like a probable one) or the fallback.

- Earned value page, Earned Schedule (Lipke, "Schedule is Different", 2003; formulas.md §3,
  `evm.earned_schedule`): the plan reached as a date, the time gap in days and SPI(t), read on plan
  time (the working time of at least one of the baseline calendars of the tasks measured); SPI and pace
  over the last four weeks and since the first update, the forecast finishes and TSPI with the hours
  needed to hold the planned finish; the weeks of the window one by one, the lag a baseline copied from
  a project under way carries, and what each change of baseline absorbs. None is computed on the
  update's own planned dates, which P6 moves with the early dates until a task starts.
- Earned value page: the earned value, the Earned Schedule and the BEI on the tasks of a P6 activity
  code (`evm.update_and_baseline_of_code`, `baseline.restricted`).
- PPC & progress page: the results filtered by a P6 activity code; the code picker is
  `app/code_picker.py`, shared with the Gantt.
- Debug, block 9: EV - PV of the Earned Schedule's tasks by status (`evm.schedule_gap_by_status`), and
  the user defined fields that hold a value in the project (`Snapshot.udf_fields`, UDFTYPE / UDFVALUE).
- Debug, block 2: the expected finishes counted by form (status, type, constraints, FF / SF
  predecessor), counts only (`app/expected_finish_forms.py`).
- Rules: every generic rule returns its population funnel as the P6 checks do (`float`,
  `constraints`, `no_resource`, `lag`, `relationship_type`, `missing_logic`, `dangling`,
  `invalid_dates`, `late_vs_baseline`, `bei`), so "show funnel" counts what each exclusion took out.
  Rows, counts and flagged tasks unchanged.
- Files window: a folder typed in it is read only under one root (`XERSCOPE_FOLDER_ROOT`, else the
  folder of `XERSCOPE_DATA`, else the home directory); a folder outside it is refused.
- `tests/reference/fetch_p6_heldout.py` also checks out the two P6 probe folders on expected finish
  of the pinned corpus.
- PPC & progress page: lookahead reliability, Tasks Anticipated and Tasks Made Ready of the
  week against the plans of 1, 2, 4 and 8 updates before (Hamzeh, Ballard & Tommelein 2012,
  figure 5; `progress.lookahead_series`, formulas.md §4), with every week's counts.
- Rules for a company standard (`xerscope standards --rules`, formulas.md §2.5): `on_data_date`
  (activities starting or finishing on the data date); `float` with `op = "between"` and
  `value_max` (a float band, bounds included, reversed bounds refused on load); `missing_logic`
  exemptions `single_project_start` / `single_project_finish` (one task only, a shared date
  passes none); `relationship_type` with `zero_lag` (type and zero lag together) and `listed`
  (the links of the type instead of the others); `no_resource` with `kind = "labour_units"`
  (budgeted labour units above zero); `lag` with `unit = "project_pct"` (a limit as a share of
  the project's working hours, `Snapshot.project_work_hours`). Built-in standards unchanged.
- Overview: a score card for every standard the app lists (the `--standards` folder and the
  session's uploads), not only the four built-in ones.
- Schedule health: a standard uploaded on the page is in the picker on the run that loads it; the
  population steps of a standard of your own name its `source` text.
- Standards: a metric's optional `item` ties it to a criterion of the source; the score counts
  criteria (an item fails when one of its metrics fails, the card names which). P6-10a and
  P6-10b are one item: the P6 score reads 17 criteria for 18 metrics (formulas.md §1.6).
- Remote deployment: the HTML shell (`/`, `index.html`) is `Cache-Control: no-store` like the
  downloads; the browser keeps the public JS chunks only.
- Remote deployment: `XERSCOPE_STANDARDS` points at the exports folder, so a standard of your
  own (.toml) dropped beside the exports is read at each start (`deploy/compose.yaml`,
  docs/deploy.md §5).
- Delay analysis page and `analysis/forensics.py`: the half-step reading of each week (AACE RP
  29R-03 MIP 3.4, contemporaneous split: the bifurcated, half-stepped update). The previous update
  is rescheduled with the update's changes applied one step at a time (progress as 3.4.K.4.b
  defines it, then scope, durations, logic, constraints, calendars and options): the finish before
  replanning and the week's slip, then what the replanning did; how the finish is held (last task,
  Must Finish By, Mandatory Finish), the longest path's float, the series over every update
  (formulas.md §5.1). The baseline is not read. A week whose recalculated finish is not the one P6
  stored in the file is flagged: its shifts may be the recalculation's.
- Delay analysis: the longest path of each update against the one before (`analysis/longest_path.py`,
  AACE RP 29R-03 3.4.E.9 and SVP 2.3.B.6): the tasks that stayed, entered, were finished, or are
  still open and left the path, per week and over the series (formulas.md §5.2).
- Debug, block 3: the recalculated finish against the file's, the tasks where the recalculated early
  dates first differ from the stored ones, and the same tasks counted by form with no Task ID and no
  date (formulas.md §5.3). The Delay analysis warning points to it.
- Delay analysis: the week's commitments made on the previous update's longest path, kept or not,
  and their PPC beside the week's PPC in the series (formulas.md §5.2); where the week's
  revisions fall, within the lookahead (6 weeks, `Settings.lookahead_weeks`) or beyond it
  (formulas.md §5.1).
- Changelog: categories Calendars (working time changed) and Options (scheduling option changed,
  Must Finish By included); "remaining duration cut" on work not started (formulas.md §5).
- Supply chain (plan bloc F): the published images carry BuildKit's SLSA provenance
  (`mode=max`), an SPDX SBOM and a GitHub build-provenance attestation of their digest
  (AUDIT-DEP-02); CodeQL on the Python sources runs on `main`, pull requests and weekly, the
  OpenSSF Scorecard on `main` and weekly (AUDIT-DEP-04); `tests/test_fuzz_parser.py` fuzzes the XER
  boundary with Hypothesis (`parse_bytes` and `build_snapshot` return a value or raise
  `XerError`, never another exception), 200 examples locally and 1000 under
  `HYPOTHESIS_PROFILE=ci`; this changelog.
- `docs/deploy.md`: how to read an image's digest from ghcr.io, verify its attestation, pin
  it in `.env` and bump it (AUDIT-DEP-01); how a release is cut; how to check with
  `docker inspect` that `TS_AUTHKEY` has left the tailscale container (AUDIT-DEP-03).

### Changed

- Baseline dates of a separate baseline follow the earned value basis, as P6's BL Project Start / Finish
  do: the planned dates of the baseline's activities with "Budgeted values with planned dates" (the
  default), their current Start / Finish with the two "current dates" options. They were the current
  dates whatever the basis. Late activities, BEI, finish variances, the Gantt and the MTA read them, so
  their results can change for an activity already started when the baseline was taken, or whose
  baseline was changed and not rescheduled. A result that reads a baseline is computed again when the
  basis changes. Sources and what remains unverified: `docs/standards.md`, P6 Check Schedule.

- CPM against the held-out P6 23.12.1 corpus (`tests/test_p6_heldout.py`, docs/cpm.md): from 89.4 % to
  99.6 % of its 54,726 values identical, `FLOORS` raised with each step. An unstarted milestone with
  an expected finish sits at it, under a Mandatory Start at the later of the two; with an expected
  finish in force a Mandatory Finish no longer pins work not started (the late finish is the lesser of
  the successors' bound and the date) and Finish On / Finish On or After lose their early side; work
  under way is no longer pinned by a mandatory date in the backward pass; no free float on unstarted
  work under a primary mandatory constraint nor where an expected finish is in force; only the primary
  constraint pins, the second one bounds beside it; the project's late finish caps a pinned date.
  Resource-dependent work is placed forward and back as P6 places it (`analysis/resource_placement.py`),
  As Late As Possible included; under a Mandatory Finish it runs on from the pinned start; a finish
  floor moves it by its start; its start float runs to the late finish less its span; an assignment
  without units per hour lasts its own window. The corpus scorer schedules each case with the float
  type P6 held.
- The app's front (`docs/refactor-front-plan.md`): one number formatter and one missing-value dash; a
  "How to read" popover beside every chart and metric table (texts in `analysis/explain.py`, one
  panel, `app/explanation_panel.py`) and a help text on every widget; one table contract (labels and
  help in `ui.COLUMNS`) and a caption for an empty table; one house style for the charts
  (`app/theme.py`), the table filters in `app/table_filters.py`; `app/state.py` split by concern
  (`session`, `loading`, `files_window`, `downloads`, `baselines`), one direction of imports; the Activity page removed,
  the Gantt's task panel giving the same access; the Delay analysis churn chart removed
  (`viz/charts.build_path_churn`), the churn table under it carrying the same counts; the Gantt sized on the rows it draws.
- The baseline each page reads (P17): Health, Audit, the BEI and the Gantt read the file's own P6
  Project Baseline when it holds one (`baselines.baseline_for_checks`), else the window's choice; the
  cumulative earned value reads the origin of the series (`baselines.origin_baseline`), and the switch
  "P6 view: the file's baseline" the update's own; the context banner names the rule the page applies.
- A series just read waits for its baseline: the Files and baseline window opens on its Baseline
  section, and nothing is computed against a baseline before Done there.
- Audit: the settings form asks for the rule's parameters, then for the target, and states the
  settings in sentences; `value_max` is asked for under a band (`op = "between"`) only. Field outlines
  reach a 3:1 contrast on every background.
- Remote deployment (Caddy): each connection is closed after its response, except a WebSocket
  handshake; the app's cookie is marked Secure; `_stcore/metrics` and `_stcore/agent/openapi.json`
  answer 404; the Content-Security-Policy adds `object-src 'none'` and `base-uri 'none'`, HSTS
  `includeSubDomains`. The CI job `deploy` fails when the secret path prefix reaches Caddy's log.
- `tests/test_architecture.py` reads every import form of an app module (`from xerscope.app import ui`
  included) and lists every module. The audit reports are kept outside the repository.
- CPM: `TimeAxis.work` reads one timestamp with `bisect` on lists kept with the axis instead of a numpy
  call per value: a recalculation of the Hotel reference file (4 217 activities) takes 0.38 s instead of
  1.0 s, every schedule of the reference data and the P6 corpus unchanged to the minute.
- The pages, `streamlit_app.py` and the tests import each name from the module that defines it;
  `app/state.py` no longer re-exports what the other modules define. `tests/test_architecture.py`
  guards the app's import graph: the edges between the app modules written in the test, the baseline
  domain reading neither `state`, `loading`, `downloads` nor `cache`, `state.py` imported by the pages
  only, no cycle.
- `app/baselines.py` (1 338 lines) cut by responsibility, no behaviour changed (`scripts/same_code.py`:
  same code): `app/baseline_file.py` (the separate baseline file), `app/baseline_export.py` (the P6 XML
  export in use and the resolution), `app/baselines.py` (`baseline_for` and the paths that build the
  Baseline of an update), `app/baseline_window.py` (the window's Baseline section),
  `app/baseline_warnings.py` (the sidebar's Baseline line and its warnings), `app/cache.py` (`memo`,
  the checks' results, the score job); the parse cache and `_cache_for` in `app/session.py`, the exports
  and `costs_shown` in `app/downloads.py`. Dependencies run one way, no cycle; the tests patch
  the module that calls the patched name.
- Finish variance has P6's sign, baseline finish minus finish: a late finish reads negative (the Check
  Schedule report of P6 Professional 26.8, `tests/test_p6_checksched.py`), in the late activities and on the WBS
  nodes.
- CSV downloads: one writer (`export.csv_bytes`), floats to 4 decimals, dates as P6 writes them.
- Funnel stack, CVE-2026-97054 (Go `net/http`, fixed in Go 1.27.4): `tailscale/tailscale`
  v1.104.4 → v1.104.7 (Go 1.27.4); `deploy/caddy/Dockerfile` on Caddy 2.11.9 (its builder holds
  Go 1.27.4, the build checks it), x/net replaced by v0.63.0, the go-jose/v4 replace dropped (2.11.9 requires the
  fixed v4.1.6).
- Licence: from this change on the project is proprietary, all rights reserved (`LICENSE`,
  `NOTICE`, `pyproject.toml`); the revisions published before it were under Apache-2.0.
- `deploy/compose.yaml`: `:latest` stays the default for a first start, the documented
  setting for a NAS is a release tag with its digest (AUDIT-DEP-01).
- `deploy/caddy/Dockerfile`: the two caddy base images are pinned by digest, as the app's
  `Dockerfile` already pins its bases (AUDIT-DEP-01).
- `.github/workflows/image.yml`: the job declares its own permissions (`packages`,
  `id-token`, `attestations` write; `contents` read).

### Fixed

- Delay analysis: a completed activity carrying a Mandatory Finish no longer reads as what holds the
  project finish; a Mandatory Finish holds it only when it carries the project's early finish, and is
  read before a Must Finish By (ANALYSIS-01).
- Overview: a standard uploaded again under the same id is scored again, and a standard settled in
  error stops the polling and keeps its message (APP-01); the score cards stop polling once every
  score is shown.
- Baselines: the sidebar draws one renumbering line or none, none for a baseline without GUID (a P6
  XML export, whose reader writes the GUID blank) (APP-02).
- Baselines: the sidebar counted an update measured against a probable baseline as one whose P6
  Project Baseline is missing (14 of 20 on a series with 6 exact and 14 probable); it counts, as a
  warning, only the updates with no baseline that are not left undecided.
- Files and baseline window: the "(none)" of the folder's baseline file picker was read as a file
  name, and the folder itself as the baseline file (`IsADirectoryError`), which stopped the window on
  every series read from a folder.
- Gantt: a WBS node and a resource with the same label each get their "Did you mean" button instead of
  stopping the page (APP-03).
- `xerscope recalc FOLDER --out FILE` writes one CSV per file (`<file>_<FILE>`), not every file over
  the one before (TOOLS-01).
- Readings: four Delay analysis tables and the PPC lookahead table get their "How to read"; the
  coverage test reads every table (FEAT-02).
- P6 XML baseline file: the search for its index reads CDATA sections (P6 Professional 20.12 writes a
  project's Id and Name in one), instead of falling back to the full pass.
- Tables: a missing number reads as a dash; the audit sheet's target as text, its TOML block in UTF-8.
  The Files and baseline window opened by itself holds the Baseline section alone, and Done keeps the
  series. `Snapshot.file_baseline` is resolved once per snapshot (the cache key read it on every call).
- Reader (XER-05/06): a tab or a space after the `%E` end tag, and blank names after the last column of a
  `%F` line (tabs an editor left), no longer refuse a readable file. A file with no `%E` and a column named
  twice before the last one are still refused.
- Changelog: a scheduling option and its values are shown under the names of P6's Schedule Options
  dialog ("Define critical activities as: Longest Path"), not the codes of the file (`CT_DrivPath`).
- Delay analysis: a step counts the changes it carries; a rename or a move to another WBS is counted
  at no step (they were counted at the last one).
- Debug, block 3: the counts of the steps table are whole numbers.
- Baselines: "Link renumbered tasks by GUID" renamed the baseline's frame but not the tasks of its own
  file, so P6-13 counted a renumbered task as no longer in the schedule and the BEI due in the baseline
  lost it, while the earned value found it (`baseline.relinked`). A baseline of the P6 XML export that
  cannot be read stopped every page; its update now has no baseline and the sidebar names it. DCMA-13
  (CPLI) reads the baseline finish of the end milestone without a Must Finish By and did not name the
  baseline in its result; it does (`checks.BASELINE_READERS`). The Files and baseline window lists, once
  the files are read, the baseline each file names and what it is measured against; the sidebar's
  message on missing Project Baselines says that P6 writes none in an XER and asks for the P6 XML export.

- Delay analysis: the page no longer stops on a series where an update holds whole hours only and
  the next a fraction of an hour (a remaining duration of 19.2 h): the half-step schedule carries
  the value as it is.
- Parser and model: the findings of the conformity audit (AUDIT-XER, AUDIT-CPM, AUDIT-APP)
  closed by plan blocs A to E are listed here as they land; the crashes the fuzzer still
  finds are recorded in `tests/test_fuzz_parser.py` with their finding.

## [0.1.0] - unreleased

First tagged release: the XER parser and model, the CPM engine checked against P6 exports,
the P6 Check Schedule, DCMA DECM and DCMA 14-Point standards, earned value, PPC, MTA and the
changelog series, the Gantt, the Power BI export, the Streamlit app, the CLI and the Docker
and Tailscale Funnel deployment.

[Unreleased]: https://github.com/Xerscope/xerscope/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Xerscope/xerscope/releases/tag/v0.1.0
