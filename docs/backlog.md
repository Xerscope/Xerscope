# Backlog

What is known to be wrong, unproven or missing, in the order it is worth doing. One
line per item; the evidence is in the tests or the file named. Remove an item when it
is done, add one when a check or a recalculation disagrees with P6.

## Proof: get an oracle for what has none

- [ ] **P6 Check Schedule report** (P6 Professional 24) on a shareable file, with that
      file's F9 export, under `tests/reference/`; one assertion per count. One P6
      Professional report on a real schedule settled P6-12, P6-13 and P6-15 to P6-17
      (`p6.toml` `source` fields), but it cannot enter the repository. Still a reading of Oracle's help only: LOE in P6-01,
      remaining early start for in-progress work (P6-10), 352 h = 8 h/day, FF / SF links in
      P6-15, the constraint options of P6-16 / P6-17.
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

- [ ] **06A212a**: the sheet's population is the FS, SS, FF and SF relationships with an
      incomplete predecessor; the code uses an incomplete successor (`decm/schedule_metrics.py`).
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
      Progress Override alone loses 678 values for 407. The deciding factor is not found.
- [ ] Free float of unstarted mandatory-constrained work: 0 in P6 for 538 of 570 values,
      positive here; the 32 positive ones differ from the engine's too (H23-08 A1220).
- [ ] The corpus is synthetic, one generator, scheduled by 23.12: shapes it never draws
      are untested. No public 24 export exists; 23.12 and 25.12 bracket it.

## Checks and earned value

- [ ] **P6 Check Schedule readings a real report has not settled** (evidence so far: the
      P6 Professional 24 help 101248 and one P6 Professional r22.12 report analysed by Ten Six,
      https://tensix.com/using-the-p6-check-schedule-tool/; the standard targets Pro 24):
      - P6-02 / P6-03 count the secondary constraint (`cstr_type2`); the help is silent.
      - P6-11: 101248 counts an expense as cost loading; Ten Six writes that fixed-price
        (lump sum) costs do not register. The help is followed.
      - P6-13: in that report P6 Professional showed BEI 6 / 6 = 1.0 where 11 activities
        were due (P6 EPPM gave 0.55 on the same schedule); the P6 Professional report behind P6-12
        divides by every baseline activity, which xerscope follows. The r22.12 figure fits
        neither reading and is not explained.

- [ ] CPLI is n/a without a Must Finish By date (DCMA's float is to the contract finish,
      which P6 holds there). A project that keeps the contract date as a milestone or in
      the baseline gets no index: a `finish_date` parameter would need the DCMA text to
      allow it.

- [ ] **Earned value against Oracle P6** (pages under docs.oracle.com/cd/F88968_01/client_help/en_US/):
      - PV: P6 computes it per resource assignment with a date ratio; the code per activity,
        in working time (`evm.py`).
      - Manual future-period buckets are not modelled.
      - BAC and AC are labour hours only.
      - Resource curves are treated as a technique (`EvPoint.not_modelled`); curves under
        Units are not reported.
      - The ETC technique "PF x (BAC - EV)" is ignored (EAC = AC + remaining).
      - 0/100 and 50/50 with a non-physical % complete are untested.
      - The quote for the EV-basis Admin Preference ("When calculating earned value from a
        baseline use") is unverified.

## App

- [ ] Not reachable by AppTest: the upload path (`file_uploader`) and a WBS row selection
      (`on_select`); both are checked by hand before a release.
- [ ] Baseline file: the sidebar re-hashes its bytes on every rerun (`_parse` key);
      noticeable above ~50 MB only.
- [ ] Memory per loaded file: a synthetic 43 MB export (97,121 activities) holds about
      0.65 GB parsed, plus its raw bytes in session state. This sets how many weeks fit under
      the NAS's memory cap (docs/deploy.md §7): drop the bytes once parsed.

## Deployment and CI

- [ ] Verify on the NAS, after the next pull: `TS_AUTH_ONCE` across a restart; the Docker
      Hub login step now conditioned on a job-level secret; the tailscale state folder is
      a bind mount writable by uid 65532; the hardened sidecars (`cap_drop`, Caddy
      read-only) still start.
- [ ] The password prompt has no rate limit (stock Caddy has no such module): a Caddy
      build with `caddy-ratelimit`, or Tailscale Serve with a tailnet login once the viewer
      can install Tailscale.
- [ ] Sidecar images in `deploy/compose.yaml` pinned by tag, not digest (the Dockerfile's
      are): `docker buildx imagetools inspect` the tailscale and caddy tags once and write
      `@sha256:` after each (Dependabot keeps tag and digest together).
- [ ] Caddy image: 9 Trivy findings (7 CVEs) accepted until 2026-12-02 (`deploy/caddy.trivyignore.yaml`,
      none reachable in this stack). At expiry the CI job `deploy` turns red: move to a
      Caddy release that fixes them, or renew each entry with its reason.
- [ ] Verify on the NAS: tailscaled on a read-only root (the CI job `deploy` checks it on
      GitHub's Docker, not on the Synology kernel) and the memory caps applied (no
      `does not support memory limit` in the Project's build output).
- [ ] Password hash in bcrypt (cost 14); OWASP's Password Storage Cheat Sheet now puts
      argon2id first. Caddy 2.11.6 takes `basic_auth argon2id`, its defaults are OWASP's
      46 MiB, t=1, p=1 variant; switching needs a new hash in `.env` and room in Caddy's
      memory cap for parallel attempts at 46 MiB each.
- [ ] One login shared by every visitor: one `basic_auth` account each would let one be
      revoked, and told apart in the log, alone.
- [ ] The published image carries no SBOM attestation and no signature: `sbom: true` and a
      keyless cosign step in `image.yml` (verified from a PC; Container Manager checks none).
- [ ] The container job in CI starts the app image but opens no page: an AppTest-like
      request through the published port would catch a broken runtime.

## Structure (only once the above is done, at constant output)

- [ ] Complexity hotspots still above 10 (`ruff check src --select C901`): `parse_text` 17,
      `build_gantt` 16, and in the CPM `pred_bounds`, `forward`, `successor_limits`, `backward`,
      `longest_path`; `sample.py` (`_cpm`, `_progress`, `generate`). CPM internals and
      `sample.py` are left as they are.
- [ ] Duplications: `set_index("task_code")` in 13 places where `Snapshot.by_code` could
      serve; three changelog row builders (`_change`, `assignment_change`,
      `relationship_change`).
- [ ] Computations still inside `app/views` (changelog, health, ppc, gantt): pure
      functions per page would be testable without AppTest. One cache policy
      (`_parse` and `memo`, both in session state).
- [ ] `cpm.py`: the status × link × lag × option cases are spread over four methods; a
      table read by both passes would make each cell a test.
- [ ] `tests/test_p6_heldout.py` is four of the suite's seven minutes: score the sets in
      parallel.
