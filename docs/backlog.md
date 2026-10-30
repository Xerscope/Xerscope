# Backlog

What is known to be wrong, unproven or missing, in the order it is worth doing. One
line per item; the evidence is in the tests or the file named. Remove an item when it
is done, add one when a check or a recalculation disagrees with P6.

## Proof: get an oracle for what has none

- [ ] **P6 Check Schedule report** (P6 Professional 24) on one real file, with that file's
      F9 export, under `tests/reference/`; one assertion per count. Today every P6 check
      population is one reading of Oracle's help pages (`src/xerscope/standards/p6.toml`
      `source` fields, P6 Professional 24 dialog help 101248 first): LOE in P6-01,
      completed activities in P6-12, BEI due counted in the baseline (P6-13), remaining
      early start for in-progress work (P6-10), milestones in P6-04's denominator,
      352 h = 8 h/day.
- [ ] **DECM**: the same for `decm.toml`. Open readings, each stated in the TOML `source`:
      06A205a counts LOE and ignores leads; 06A209a includes LOE; DCMA-11 keeps
      milestones, DCMA-14 drops them.
- [ ] **Weekly exports after F9**: `xerscope recalc --report` on them is the only check on
      progressed and resource-dependent work outside the synthetic corpus; each shape it
      lists with differences is a rule to settle, with the P6 dates as the answer.

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

- [ ] CPLI is n/a without a Must Finish By date (DCMA's float is to the contract finish,
      which P6 holds there). A project that keeps the contract date as a milestone or in
      the baseline gets no index: a `finish_date` parameter would need the DCMA text to
      allow it.

## App

- [ ] Not reachable by AppTest: the upload path (`file_uploader`) and a WBS row selection
      (`on_select`); both are checked by hand before a release.
- [ ] Baseline file: the sidebar re-hashes its bytes on every rerun (`st.cache_data`);
      noticeable above ~50 MB only.

## Deployment and CI

- [ ] Verify on the NAS, after the next pull: `TS_AUTH_ONCE` across a restart; the Docker
      Hub login step now conditioned on a job-level secret; the tailscale state folder is
      a bind mount writable by uid 65532; the hardened sidecars (`cap_drop`, Caddy
      read-only) still start.
- [ ] The password prompt has no rate limit (stock Caddy has no such module): a Caddy
      build with `caddy-ratelimit`, or Tailscale Serve with a tailnet login once the viewer
      can install Tailscale.
- [ ] Base images pinned by tag, not digest: `docker buildx imagetools inspect` the four
      of them and write the digests into the Dockerfiles once (Dependabot keeps them up).
- [ ] The container job in CI starts the app image but opens no page: an AppTest-like
      request through the published port would catch a broken runtime.

## Structure (only once the above is done, at constant output)

- [ ] `cpm.py`: the status × link × lag × option cases are spread over four methods; a
      table read by both passes would make each cell a test.
- [ ] Views build frames inline; pure functions per page would be testable without
      AppTest. One cache policy (`st.cache_data` for parsing, `memo` for analyses).
- [ ] `tests/test_p6_heldout.py` is four of the suite's seven minutes: score the sets in
      parallel.
