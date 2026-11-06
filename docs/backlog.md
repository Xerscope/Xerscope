# Backlog

What is known to be wrong, unproven or missing, in the order it is worth doing. One
line per item; the evidence is in the tests or the file named. Remove an item when it
is done, add one when a check or a recalculation disagrees with P6.

## Proof: get an oracle for what has none

- [ ] **More P6 Check Schedule reports on shareable files.** `tests/test_p6_checksched.py`
      holds one: a synthetic project checked by P6 Professional 26.8, its F9 export rebuilt
      with xerkit, every line and list of the report and the F9 log asserted. Report R1
      (docs/standards.md, Sources) settled P6-12, P6-13 and P6-15 to P6-17 and stays local
      (`tests/test_p6_witness.py`). Still a reading of Oracle's help only, because no report
      shows it yet: LOE in P6-01, an in-progress activity whose remaining early start is
      before the data date (P6-10a), the hours per day behind `x` on a calendar other than
      8 h, FF / SF links in P6-15, the constraint options of P6-16 / P6-17.
- [ ] **DECM**: a DECM output on one real file, for `decm.toml`. The v8.0 sheets are read
      (docs/standards.md, Sources); what they leave open or contradict is under
      "DECM conformance" below.
- [ ] **Weekly exports after F9**: `xerscope recalc --report` on them is the only check on
      progressed and resource-dependent work outside the synthetic corpus; each shape it
      lists with differences is a rule to settle, with the P6 dates as the answer.

## DECM conformance

Where the official sheet (index in docs/standards.md, Sources) contradicts the current
rule; none is fixed. The 06A205a and 06A209a sheets name no LOE exclusion, so LOE stays
in, as coded (the `source` strings in `decm.toml` still call it unsaid).

- [ ] **06A401a**: the sheet compares the constraint-method critical path with the
      contractor's critical path; the code runs the delay-injection test (`cpm.py`
      `critical_path_test`).
- [ ] **06A504a / b**: the sheet's denominator is the activities with an actual date in
      the previous month's IMS; the code uses the union of both months.
- [ ] **06A505a**: the sheet's "in progress" is EV % > 0 and < 100, and X also counts an
      actual finish; the code takes started or % > 0, actual start only.
- [ ] **06A506c**: the sheet does not exclude LOE; the code does.
- [ ] **06A210a**: exemption for LOE whose only successors are end-item deliverables or
      contract completion; not modelled.
- [ ] **DCMA-08**: PAM 200.1 section 4.8 also asks for a baseline start "within the detail
      planning period or rolling wave"; weekly XERs carry no such period, so every baseline
      start qualifies. The baseline duration is converted with the activity's current calendar.
- Still open, the sheets do not settle them: 06A205a leads (negative lags); 06A506b "on or
  before" against "before" (the sheet uses both).

## CPM: where the engine still differs from P6 23.12

Measured by `tests/test_p6_heldout.py` (`xerscope crosscheck --p6`).

- [ ] **Resource-dependent work**: 81 % of the corpus values (`cpm.py rsrc_early`,
      `place_late`). Still open: what a successor sees of an activity whose placement
      was pushed by a finish bound (H14-02 A1220 wants its FF predecessor one hour
      earlier than displayed; H10-10 A1140 a lead four days earlier); started
      resource-dependent work under Retained Logic (late dates 60 %); the late start
      bound's instant on the activity calendar (H22-03 A1070 against H13-10).
- [ ] **Rules observed, not explained** (`cpm.py expected_finish`, `successor_limits`,
      `backward`, `floats`): started work under Progress Override with an FF/SF
      predecessor keeps its remaining duration when the expected finish is earlier; the
      free float of started work under Progress Override, with counter-examples H4-08
      A1010, H12-07 A1120, H17-04 A1040; no free float where the expected finish applies
      (265 of 265); under an expected finish earlier than a Mandatory Finish the
      successors drive the late dates, capped by the expected finish on task-dependent
      work but by the mandatory date on resource-dependent work (H25-05 A1150, 3 cases).
- [ ] **Mandatory dates and the late dates**: pinned in both passes here, and that is
      right in most of the corpus, but P6 lets successors drive the late dates of some
      unstarted Mandatory Start / Finish activities (H12-09 A1330 under Progress
      Override, H25-03 A1180 against H10-05 A1180): letting successors drive under
      Progress Override alone loses 678 values for 407. Factors found by
      docs/deep-dive/engine-gaps.md (50 % of all corpus differences): P6 pins only a mandatory
      date in the first slot, on unstarted work, with no expected finish in force; a second-slot
      mandatory date is a floor / cap, work under way gets no late bound from it. Experiment 1
      there names the witnesses; it is cheaper after the link and constraint tables
      (docs/architecture/13-patterns-for-a-solo-developer.md, P1).
- [ ] Free float of unstarted mandatory-constrained work: 0 in P6 for 538 of 570 values,
      positive here; the 32 positive ones differ from the engine's too (H23-08 A1220).
- [ ] **Milestones with an expected finish** (new, 9.6 % of the differences): P6 sits a start or
      finish milestone at max(logic, expected finish); `forward` applies the expected finish
      to tasks only (H23-09 A1200, H26-11 A1370; docs/deep-dive/engine-gaps.md, experiment 2).
- [ ] The corpus is synthetic, one generator, scheduled by 23.12: shapes it never draws
      are untested. No public 24 export exists; 23.12 and 25.12 bracket it.
- [ ] Sub-minute durations and lags: `TimeAxis.at` rounds half minutes to even, so 7.5 min
      lands on 7 or 8 depending on the axis anchor (other activities' dates), and the two passes
      can round apart (negative float on an unconstrained network). The corpus draws whole
      hours; how P6 rounds below the minute is undocumented (granularity documented in cpm.md,
      AUDIT-CPM-08).

## Checks and earned value

- [ ] **P6 Check Schedule readings a real report has not settled** (evidence so far: the
      P6 Professional 24 help 101248 and one P6 Professional r22.12 report analysed by Ten Six,
      https://tensix.com/using-the-p6-check-schedule-tool/; the standard targets Pro 24):
      - P6-02 / P6-03 count the secondary constraint (`cstr_type2`); the help is silent.
      - P6-11: 101248 counts an expense as cost loading; Ten Six writes that fixed-price
        (lump sum) costs do not register. The help is followed.
      - P6-13: in that report P6 Professional showed BEI 6 / 6 = 1.0 where 11 activities
        were due (P6 EPPM gave 0.55 on the same schedule); R1
        divides by every baseline activity, which xerscope follows. The r22.12 figure fits
        neither reading and is not explained.

- [ ] **Earned value against a P6 output**: no EV number is pinned against P6 yet, only hand
      calculations. docs/deep-dive/ev-gaps.md ranks the global changes (Schedule % Complete time
      convention, which baseline values P6 reads, the WBS ETC technique, read but not applied)
      and lists the P6 Activities export that would settle them (§6).
- [ ] **Earned value against Oracle P6** (pages under docs.oracle.com/cd/F88968_01/client_help/en_US/):
      - PV: Labor Units: per activity (Pro 26 glossary); Cost: per assignment (Pro 26 glossary),
        implemented for the cost SPI (`planned_value_cost`). The date difference of that
        formula is taken in working time (assumed, unverified); `PV_COST_WORKING_TIME`
        switches to calendar time if a P6 Professional report contradicts it.
      - Manual future-period buckets are not modelled.
      - Schedule % Complete: which finish? The P6 Professional 26 help (G57535-02, glossary)
        gives two. Planned Value Labor Units: "how much of the activity's baseline duration has
        been completed" (baseline finish). Planned Value Cost, activity without resources:
        "(Data date - Baseline Start) / (Planned Finish - Baseline Start)" (current planned
        finish). `schedule_pct` and the activity part of `planned_value_cost` use the baseline
        finish (`ev_finish`). To settle: a P6 Activities export with "Planned Value Labor Units",
        BL start / finish and Planned Finish, on an update whose Planned Finish has moved from
        the baseline finish (no resource curve, data date inside both spans), compared with
        `xerscope pv-compare UPDATE.xer --baseline BL.xer --p6 export.csv` (a separate
        baseline file: with `--planned-baseline` the two finishes are the same date).
      - BAC, PV and EV cost are modelled (cost SPI); Actual Cost, CPI (cost) and EAC (cost) are
        not: AC, CPI and EAC stay in labour hours.
      - Cost uses the budgeted values (`target_cost`) whatever the EV basis.
      - Resource curves are treated as a technique (`EvPoint.not_modelled`); curves under
        Units are not reported.
      - The ETC technique "PF x (BAC - EV)" is not applied (EAC = AC + remaining); the technique
        of each WBS is read and reported (Debug block 8, warning on the Earned value page).
      - 0/100 and 50/50 with a non-physical % complete are untested.
      - The quote for the EV-basis Admin Preference ("When calculating earned value from a
        baseline use") is unverified.
- [ ] **Hours per day of the `_d` columns**: `CALENDAR.day_hr_cnt` of the activity's
      calendar. P6 converts with the Admin Preferences hours per time period unless "Use
      assigned calendar to specify the number of work hours for each time period" is set
      (Oracle, Time Periods tab - Admin Preferences); the XER does not carry that setting.
- [ ] DCMA-13 CPLI divides the finish driver's float, measured on its own calendar, by the
      project calendar's hours per day.
- [ ] Finish variance sign: shown as finish - BL finish (late positive). P6 Professional's
      "Variance - BL Project Finish Date" is BL - finish (Finish Date Variance help, Ten Six);
      EPPM page 47223 writes finish - BL. A P6 report settles it.
- [ ] INT-08 compares clock times. Across calendars P6 writes an FF 0 successor finish at
      Mon 16:00 before its predecessor's Mon 17:00 (H20-12 A1170), the same working minute on
      the successor's calendar; the engine gives Tue 08:00 there, so no false positive shows
      yet. Compare on the lag calendar when the engine reaches P6's date.

## App

- [ ] Visual campaign leftovers (visual-debug-report.md): tap targets under 44 px on phones
      (Streamlit theme sizes); author decisions on the "Task history (to be removed)" page, one
      date format, the Method / Source texts, French demo data, the SPI delta "+0.00".
- [ ] Not reachable by AppTest: the upload path (`file_uploader`) and a WBS row selection
      (`on_select`); both are checked by hand before a release.
- [ ] Baseline file: the sidebar re-hashes its bytes on every rerun (`_parse` key);
      noticeable above ~50 MB only.
- [ ] Memory per loaded file: a synthetic 43 MB export (97,121 activities) holds about
      0.65 GB parsed, plus its raw bytes in session state. This sets how many weeks fit under
      the NAS's memory cap (docs/deploy.md §7): drop the bytes once parsed.
- [ ] Baseline in each file: building the baseline from the file re-reads the whole export, cached per
      session; costly on ~40 MB files. It also needs the raw bytes kept in session state, which the
      item above would drop.
- [ ] Display rounding: a value beside its status can contradict it (P6-13 at 0.9545 shows
      0.95 and passes > 0.95); Python rounds half to even, Streamlit tables half away from zero
      (2.5 h: 2 on a card, 3 in a table); the Gantt % has no decimals (99.6 % shows 100 %).
- [ ] CSV downloads: the page downloads write floats to four decimals (#119); the Power BI
      CSVs (`export.py`) still write raw float digits, and dates come in two formats.
- [ ] Parser: a tab or a line break inside a text value shifts or drops the row's later
      fields without a warning (a longer row is warned, a shorter one is padded silently); coerced
      numbers and dates are not counted in the warnings. None in the 394 reference files.

## Deployment and CI

- [ ] Verify on the NAS, after the next pull: `TS_AUTH_ONCE` across a restart; the Docker
      Hub login step now conditioned on a job-level secret; the tailscale state folder is
      a bind mount writable by uid 65532; the hardened sidecars (`cap_drop`, Caddy
      read-only) still start.
- [ ] Tailscale in `deploy/compose.yaml` pinned by tag, not digest (the app's Dockerfile and the
      two caddy bases are): `docker buildx imagetools inspect` the tag once and write `@sha256:`
      after it (Dependabot keeps tag and digest together).
- [ ] Verify on the NAS: the `xerscope-caddy` image starts with the capabilities of
      `deploy/compose.yaml` (cap_drop ALL + NET_BIND_SERVICE, like the stock image), and a
      wrong password in a loop from a PC ends in 429.
- [ ] Caddy image: Trivy findings accepted until 2026-12-02 (one entry left in the file today) (`deploy/caddy.trivyignore.yaml`,
      none reachable in this stack). At expiry the CI job `deploy` turns red: move to a
      Caddy release that fixes them, or renew each entry with its reason.
- [ ] Verify on the NAS: tailscaled on a read-only root (the CI job `deploy` checks it on
      GitHub's Docker, not on the Synology kernel) and the memory caps applied (no
      `does not support memory limit` in the Project's build output).
- [ ] Password hash in bcrypt cost 10 (docs/deploy.md §3: each wrong password costs the NAS
      one hash run). OWASP's Password Storage Cheat Sheet puts argon2id first; Caddy 2.11.6
      takes `basic_auth argon2id`, but its default 46 MiB per attempt turns the CPU cost
      into a memory cost against Caddy's 256 MB cap.
- [ ] One login shared by every visitor: one `basic_auth` account each would let one be
      revoked, and told apart in the log, alone.
- [ ] The published image carries provenance and SBOM attestations (`image.yml`, SLSA L2) but no
      image signature: a keyless cosign step would add one (verified from a PC; Container
      Manager checks none). First run on `main`: check that `push-to-registry` succeeds on GHCR.
- [ ] Type annotations are not checked: `mypy` reports 63 inconsistencies in 16 files (risk R1,
      docs/maintenance.md §0): fix, then make it blocking in the lint job.
- [ ] Bus factor 1 (risk R2, docs/maintenance.md §0): access inventory, second owner on GitHub
      and Tailscale, a recovery runbook and one drill.
- [ ] The container job in CI starts the app image but opens no page: an AppTest-like
      request through the published port would catch a broken runtime.

## Structure (only once the above is done, at constant output)

- [ ] Complexity hotspots still above 10 (`ruff check src --select C901`, Nov 2026): in the CPM
      `successor_limits` 16, `forward`, `backward`, `level_of_effort`, `_loop_members` 13,
      `pred_bounds`, `longest_path`, `_network` 12; the parser's `_Reader.run` 14 (the old
      `parse_text` is gone); `anonymize.py` `table` 13, `frame` 12; `state.sidebar_loader` 12;
      `standards._parse_metric` 12; `sample.py` `_cpm` 18, `_progress` 14.
- [ ] Duplications: `set_index("task_code")` in 16 places where `Snapshot.by_code` could
      serve; three changelog row builders (`_change`, `assignment_change`,
      `relationship_change`).
- [ ] Computations still inside `app/views` (changelog, health, ppc, gantt): pure
      functions per page would be testable without AppTest (architecture/13, P3). One cache
      policy (`_parse` and `memo`, both in session state). `app/state.py` is 1,538 lines:
      split it behind its current names (P2).
- [ ] `cpm.py`: the status × link × lag × option cases are spread over four methods; a
      table read by both passes would make each cell a test (architecture/13, P1: link,
      constraint and placement tables, at constant output, before the mandatory-date experiment).
- [ ] `tests/test_p6_heldout.py` is four of the suite's seven minutes: score the sets in
      parallel.
- [ ] Test rigour (docs/deep-dive/tests-review.md): 20 stricter tests to write (exact
      boundaries at each target, dates equal to the data date, the generic rules of a custom
      standard); mutation scores to redo on `calendar.py` and `standards.py`; `FLOORS` H10 can
      rise from 0.96 to 0.97.
