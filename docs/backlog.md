# Backlog

What is known to be wrong, unproven or missing, in the order it is worth doing. One
line per item; the evidence is in the tests or the file named. Remove an item when it
is done, add one when a check or a recalculation disagrees with P6.

## Proof: get an oracle for what has none

- [ ] **P6 Check Schedule report** (P6 Professional 24) on one real file, with that file's
      F9 export, under `tests/reference/`; one assertion per count. Today every P6 check
      population is one reading of Oracle's help pages (`src/xerscope/standards/p6.toml`
      `source` fields): completed activities kept in P6-11, no-baseline counted as due in
      P6-13, remaining duration in P6-04, LOE in P6-01, start constraints ignored once
      started, 352 h = 8 h/day.
- [ ] **DECM**: the same for `decm.toml`. Open readings, each stated in the TOML `source`:
      06A205a counts LOE and ignores leads; 06A209a includes LOE; DCMA-11 keeps
      milestones, DCMA-14 drops them.
- [ ] **Weekly exports after F9**: `xerscope recalc --report` on them is the only check on
      progressed and resource-dependent work outside the synthetic corpus; each shape it
      lists with differences is a rule to settle, with the P6 dates as the answer.

## CPM: where the engine still differs from P6 23.12

Measured by `tests/test_p6_heldout.py` (`xerscope crosscheck --p6`).

- [ ] **Resource-dependent work**: 62 % of the corpus values. Start with assignment lag
      placement and the finish on the resource calendar; the expected-finish rule there
      still follows MPXJ's reading (`cpm.py forward`).
- [ ] **Two rules observed, not explained** (`cpm.py expected_finish`, `successor_limits`):
      started work under Progress Override with an FF/SF predecessor keeps its remaining
      duration when the expected finish is earlier; the free float of started work under
      Progress Override, with counter-examples H4-08 A1010, H12-07 A1120, H17-04 A1040.
- [ ] Open ends under "make open-ended activities critical" beside a constraint or ALAP
      (70 %); Mandatory Finish late dates a successor drives (H25-03 A1180 against
      H10-05 A1180); the LOE longest-path flag (`test_longest_path_matches_p6s_flag`,
      strict xfail on the 20.12 export).
- [ ] The corpus is synthetic, one generator, scheduled by 23.12: shapes it never draws
      are untested. No public 24 export exists; 23.12 and 25.12 bracket it.

## Checks and earned value

- [ ] CPLI uses the schedule's total float, 0 without a Must Finish By date, so the index
      is 1.0 by construction on such files (`rules.py cpli`; the note says so). Decide
      whether to measure against the baseline finish instead, and cite the DCMA text.

## App

- [ ] Not reachable by AppTest: the upload path (`file_uploader`) and a WBS row selection
      (`on_select`); both are checked by hand before a release.
- [ ] Baseline file: the sidebar re-hashes its bytes on every rerun (`st.cache_data`);
      noticeable above ~50 MB only.

## Deployment and CI

- [ ] Verify on the NAS, after the next pull: `TS_AUTH_ONCE` across a restart; the Docker
      Hub login step now conditioned on a job-level secret; the tailscale state folder is
      a bind mount writable by uid 65532; the hardened sidecars (`cap_drop`, Caddy
      read-only) still start; the remote image's healthcheck (all three processes).
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
