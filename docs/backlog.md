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
- [ ] **Weekly exports after F9**: `xerscope recalc` on them is the only check on
      progressed and resource-dependent work outside the synthetic corpus. Add a
      `--report` that groups the differences by shape (link type × status × option).

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

- [ ] A file holding several projects: the biggest one is taken (one warning); the CLI
      has `--project`, the sidebar has no selector. Stores mixing projects only warn.
- [ ] Upload signature is name + size: a corrected file of the same size is ignored; the
      baseline file is outside the signature; "Folder not found" keeps the old data;
      duplicate data dates are merged with `.iloc[-1]` / `aggfunc="first"`
      (`state.py`, `earned_value.py`, `health.py`).
- [ ] No warning when the baseline is newer than the update.
- [ ] `app/.streamlit/config.toml` applies through `xerscope app` only (`cwd`); a plain
      `streamlit run` loses the theme and binds all interfaces. Move it or pass flags.
- [ ] Recomputed on every interaction: `rollup`, `categorise`, `ppc_series`,
      `milestone_trend`, `forecast_curve`, `export_tables`, the baseline file hash.
- [ ] Colours live in four places and disagree (amber ×3, two blues; the series palette
      uses the status green and red). Gantt height grows without bound (300 rows ≈ 9,000 px);
      PPC bar labels overlap past ~30 weeks; search ignores accents.
- [ ] `test_app.py` mostly asserts "renders": no test for the upload path, a baseline
      file, one snapshot, switching updates with a WBS row selected.

## Deployment and CI

- [ ] Verify on the NAS: `TS_AUTH_ONCE` across a restart; the Docker Hub login step
      (`image.yml`: a step's own `env` is not visible to its `if`); the tailscale state
      folder is a bind mount writable by uid 65532.
- [ ] Brute force on basic auth: no rate limit; `XERSCOPE_PATH` exists in the remote image
      only; Caddy logs 127.0.0.1 (no `trusted_proxies`).
- [ ] Supervisor: `wait(timeout=10)` never kills; a SIGTERM during `tailscale up` still
      starts the children; PID 1 reaps no orphans; the healthcheck ignores tailscaled.
- [ ] Images pinned by tag, not digest; no dependabot `docker` ecosystem; no image scan;
      sidecars without `read_only` / `cap_drop`; tailscaled logs leave the box
      (`TS_NO_LOGS_NO_SUPPORT`).
- [ ] CI: no `ruff check` / `format --check`; eight jobs refetch the corpora without a
      cache; missing reference data skips tests instead of failing; no image built on
      pull requests; `test_docker.py` greps text only.

## Structure (only once the above is done, at constant output)

- [ ] `cpm.py`: the status × link × lag × option cases are spread over four methods; a
      table read by both passes would make each cell a test.
- [ ] Views build frames inline; pure functions per page would be testable without
      AppTest. One cache policy (`st.cache_data` for parsing, `memo` for analyses).
- [ ] `tests/test_p6_heldout.py` is four of the suite's seven minutes: score the sets in
      parallel.
