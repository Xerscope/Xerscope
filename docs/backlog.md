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

Measured by `tests/test_p6_heldout.py` (`xerscope crosscheck --p6`): 54,726 values, 99.6 %
identical (234 differ).

- [ ] **Resource-dependent work**: 99.3 % of its 12,858 values (`cpm.py rsrc_early`,
      `place_late`, `analysis/resource_placement.py`). What still differs lies mostly on the
      late side: late dates and total float of unstarted work at 97.9 to 98.9 %, of started work
      under Retained Logic at 98.8 to 99.2 % (H10-07 A1160, H26-09 A1200); early dates at 99.6 to
      99.9 % (H24-01 A1170, started, Retained Logic, FT_Min, differs on its early dates too).
- [ ] **Task-dependent work**: 99.7 % of its 41,868 values; the differences gather in H29,
      H16, H10, H24 and H27, mostly late dates and total float (H10-07 A1110 to A1280: late
      dates two hours later than P6's, on a chain that also holds resource-dependent work;
      H16-04, H27-07). The deciding factor is not found.
- [ ] **Total float under FT_Start, FT_Total and FT_Min**: 8 activities have P6's four dates
      and another total float. 7 are resource-dependent, under FT_Start (H27-04 A1220, H29-03
      A1470, H29-04 A1440, H29-05 A1560, H30-05 A1550) and FT_Total (H30-06 A1450, H30-07
      A1580); 1 is task-dependent, under FT_Min (H22-10 A1180). `tests/test_p6_heldout.py`
      requires the agreement under FT_FF and FT_SS only.
- [ ] **Rules observed, not explained** (`cpm.py expected_finish`, `successor_limits`,
      `late_bounds`, `floats`): each agrees with the corpus and no Oracle page states it.
      Started work under Progress Override with an FF/SF predecessor keeps its remaining
      duration when the expected finish is earlier; the free float of started work under
      Progress Override runs past its start-type links and finished successors (H2-05 A1030;
      the former counter-examples H4-08 A1010, H12-07 A1120, H17-04 A1040 now agree); no free
      float on unstarted work under a primary Mandatory Start or Finish (508 of 508) nor where
      an expected finish is in force (707 of 707); with an expected finish in force a
      Mandatory Finish no longer pins unstarted work, the late finish is the lesser of the
      successors' bound and the date (H25-05 A1150); the project's late finish caps a pinned
      date (H12-09 A1330). P6 Professional 26.8 is measured on none of them.
- [ ] The corpus is synthetic, one generator, scheduled by 23.12: shapes it never draws
      are untested. No public P6 Professional 24 export exists; 23.12 and 25.12 bracket it.
- [ ] Sub-minute durations and lags: `TimeAxis.at` rounds half minutes to even, so 7.5 min
      lands on 7 or 8 depending on the axis anchor (other activities' dates), and the two passes
      can round apart (negative float on an unconstrained network). The corpus draws whole
      hours; how P6 rounds below the minute is undocumented.

## Checks and earned value

- [ ] **P6 Check Schedule readings a real report has not settled** (evidence so far: the
      P6 Professional 24 help 101248, report R1 and the P6 Professional 26.8 report of
      `tests/test_p6_checksched.py` (docs/standards.md, Sources), and one P6 Professional
      r22.12 report analysed by Ten Six, https://tensix.com/using-the-p6-check-schedule-tool/;
      the standard targets P6 Professional 24):
      - P6-02 / P6-03 count the secondary constraint (`cstr_type2`); the help is silent.
      - P6-11: 101248 counts an expense as cost loading; Ten Six writes that fixed-price
        (lump sum) costs do not register. The help is followed.
      - P6-13: R1 and the 26.8 report divide by every baseline activity, which xerscope
        follows, but both measure a project that is its own baseline. In the r22.12 report,
        with a separate baseline, P6 Professional showed BEI 6 / 6 = 1.0 where 11 activities
        were due (P6 EPPM gave 0.55 on the same schedule): a figure that fits neither reading.
        A 26.8 report on a project with a separate baseline assigned settles it.

- [ ] **Earned value against Oracle P6** (pages under docs.oracle.com/cd/F88968_01/client_help/en_US/):
      - PV: Labor Units: per activity (P6 Professional 26 glossary); Cost: per assignment
        (P6 Professional 26 glossary), implemented for the cost SPI (`planned_value_cost`).
        The date difference of that formula is taken in working time (assumed, unverified);
        `PV_COST_WORKING_TIME` switches to calendar time if a P6 Professional report contradicts it.
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
      - Resource curves are not modelled: as an EV technique they fall back to activity %
        complete and are listed (`EvPoint.not_modelled`); on an assignment they are listed for
        PV cost (`EvPoint.not_modelled_cost`) and only counted for PV labour units (Debug
        block 9, `evm.pv_labor_check`).
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
- [ ] INT-08 compares clock times. Across calendars P6 writes an FF 0 successor finish at
      Mon 16:00 before its predecessor's Mon 17:00 (H20-12 A1170), the same working minute on
      the successor's calendar. The engine now gives P6's date there (`crosscheck --p6`), so
      INT-08 can list such a link as broken: compare on the lag calendar.

## App

- [ ] Not reachable by AppTest: the upload path (`file_uploader`) and a WBS row selection
      (`on_select`); both are checked by hand before a release.
- [ ] Baseline file: an XER picked in the folder or named by `XERSCOPE_BASELINE` is read and
      hashed again on every rerun (`_disk_baseline_file`, the `_parse` key); an upload and a P6
      XML file keep their digest. Noticeable above ~50 MB only.
- [ ] Memory per loaded file: a synthetic 43 MB export (97,121 activities) holds about
      0.65 GB parsed, plus its raw bytes in session state. This sets how many weeks fit under
      the NAS's memory cap (docs/deploy.md §7): drop the bytes once parsed.
- [ ] Baseline in each file: building the baseline from the file re-reads the whole export, cached per
      session; costly on ~40 MB files. It also needs the raw bytes kept in session state, which the
      item above would drop.
- [ ] Display rounding: a value beside its status can contradict it (P6-13 at 0.9545 shows
      0.95 and passes > 0.95); Python rounds half to even, Streamlit tables half away from zero
      (2.5 h: 2 on a card, 3 in a table); the Gantt % has no decimals (99.6 % shows 100 %).
- [ ] Gantt "Ask", a model: none deployed (docs/deploy.md §10 holds the measurements:
      55 % understanding, a third of grounded summaries misusing a value, on a 4-core x86
      faster than the NAS). What would change the measurement, in order: a per-request literal grammar
      (IDs, dates, floats as the only alternatives in a fixed sentence frame) with a role
      check; `ngram-simple` speculation and `-lm mmap+mlock` on llama-server; a fine-tuned
      Flan-T5-small on synthetic pairs under ONNX Runtime; or a GPU host on the tailnet. The
      measurement client has been removed: a new measurement needs one again (`ask-bench`
      scores the grammar only).
- [ ] Parser: a tab inside a text value shifts the row's later fields (only fields beyond
      the %F width are warned of); a line break inside one cuts the row, its first part padded
      and the rest passed over, without a warning. None in the 407 XER files of
      `tests/reference`.
- [ ] Parser (XER-05 / XER-06, docs/quality-plan.md): `%E` followed by a tab reads as a file
      cut short and two trailing tabs on a `%F` line as a column named twice; both refuse a
      file P6 may write.

## Deployment and CI

- [ ] Verify on the NAS, after the next pull: `TS_AUTH_ONCE` across a restart; the Docker
      Hub login step now conditioned on a job-level secret; the tailscale state in its
      named volume (`tailscale-state`) kept across a Build; the hardened sidecars
      (`cap_drop`, Caddy read-only) still start.
- [ ] Tailscale in `deploy/compose.yaml` pinned by tag, not digest (the app's Dockerfile and
      the two caddy bases of `deploy/caddy/Dockerfile` are): `docker buildx imagetools
      inspect` the tag once and write `@sha256:` after it (Dependabot keeps tag and digest
      together).
- [ ] Verify on the NAS: the `xerscope-caddy` image starts with the capabilities of
      `deploy/compose.yaml` (cap_drop ALL + NET_BIND_SERVICE, like the stock image), and a
      wrong password in a loop from a PC ends in 429.
- [ ] Caddy image: `deploy/caddy/Dockerfile` replaces golang.org/x/net by v0.63.0 (CVE-2026-78661;
      Caddy 2.11.8 and 2.11.9 pin v0.60.0). Drop the replace once a Caddy release requires
      x/net >= 0.62.0: a replace pins one version and would hold back a newer one.
- [ ] Tailscale image: CVE-2026-78661 (golang.org/x/net/html, fixed in x/net 0.62.0, in no
      Tailscale release yet) accepted until 2026-12-09 (`deploy/tailscale.trivyignore.yaml`; the
      repository's other scan exception is `.github/trivy/self.trivyignore.yaml`, for the
      Trivy image itself). The CI job `deploy` proves the parser absent from the image's
      binaries on every run. Move to the first Tailscale release with x/net >= 0.62.0 as soon as
      it is out and delete the file with that bump: the job turns red at expiry, and as soon as
      the finding is gone from the image.
- [ ] Trivy runs from `.github/trivy/Dockerfile` (pinned by digest, Dependabot after a 7-day
      cooldown) and is scanned with itself daily (`scanner.yml`): a red run there means the
      pinned Trivy has a fixed HIGH/CRITICAL finding; bump it then, without waiting for the cooldown.
- [ ] Verify on the NAS: tailscaled on a read-only root (the CI job `deploy` checks it on
      GitHub's Docker, not on the Synology kernel) and the memory caps applied (no
      `does not support memory limit` in the Project's build output).
- [ ] Password hash in bcrypt cost 10 (docs/deploy.md §3: each wrong password costs the NAS
      one hash run). OWASP's Password Storage Cheat Sheet puts argon2id first; Caddy 2.11.6
      takes `basic_auth argon2id`, but its default 46 MiB per attempt turns the CPU cost
      into a memory cost against Caddy's 256 MB cap.
- [ ] One login shared by every visitor: one `basic_auth` account each would let one be
      revoked, and told apart in the log, alone.
- [ ] The published image carries an SBOM and provenance (`image.yml`, docs/deploy.md §7) but
      no signature: a keyless cosign step (verified from a PC; Container Manager checks none).
- [ ] The container job in CI starts the app image and reads its health endpoint
      (`/_stcore/health`) but runs no page: an AppTest-like request through the published port
      would catch a broken runtime.

## Structure (only once the above is done, at constant output)

- [ ] Complexity hotspots still above 10 (`ruff check src --select C901`): `_code_items` 15
      (`analysis/ask/lexer.py`), `_parse_metric` 12 (`analysis/standards.py`).
- [ ] Duplications: `set_index("task_code")` in 18 places where `Snapshot.by_code` could
      serve; three changelog row builders (`_change`, `assignment_change` inside
      `_assignment_changes`, `_relationship_change`).
- [ ] Computations still inside `app/views` (changelog, health, ppc, gantt): pure
      functions per page would be testable without AppTest. One cache policy
      (`_parse` and `memo`, both in session state).
- [ ] `cpm.py`: the status × link × lag × option cases are spread over four methods; a
      table read by both passes would make each cell a test.
- [ ] `tests/test_p6_heldout.py` is four of the suite's seven minutes: score the sets in
      parallel.
