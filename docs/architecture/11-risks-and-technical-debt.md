# 11. Risks and technical debt

[../backlog.md](../backlog.md) is the authoritative, ordered list of what is known to be wrong,
unproven or missing; it is maintained with the code. This section groups its items by architectural
risk, adds measurements taken while writing this set, and names what is not covered anywhere.

## 11.1 Risk: the oracle is incomplete

| Risk | Where it shows | Mitigation in place | Residual |
|---|---|---|---|
| No public P6 Professional 24 export exists; the held-out corpus is synthetic, one generator, scheduled by 23.12 | `docs/backlog.md` "CPM" | Floors per set; four real exports of other versions reproduced to the minute; MPXJ crosscheck | Shapes the generator never draws are untested; 23.12 and 25.12 bracket 24 |
| Resource-dependent work still differs from P6 on some shapes (81 % of the corpus values are resource-dependent) | `cpm.py` `rsrc_early`, `place_late`; backlog items on finish bounds, late start bound instant | Witness activities per rule in `tests/test_p6_heldout.py` | Open; the backlog lists the corpus cases |
| Mandatory dates and the late dates: the deciding factor for when successors drive them is not found | `cpm.py` backward pass | Pinned in both passes (right for most of the corpus) | Documented as open |
| P6 Check Schedule readings without a report to settle them (LOE in P6-01, P6-10a, FF/SF in P6-15, constraint options P6-16/17, secondary constraints in P6-02/03) | `standards/p6.toml` `source` fields | One synthetic project checked by P6 Professional 26.8 and one local witness report (R1) | Needs more shareable P6 reports |
| DECM sheets contradict the current rules in named places (06A401a, 06A504a/b, 06A505a, 06A506c, 06A210a) | `docs/backlog.md` "DECM conformance" | Each contradiction is written down with the sheet id | Not fixed; no DECM output on a real file yet |
| Earned value against Oracle: manual future-period buckets, resource curves, ETC technique "PF x (BAC - EV)", Actual Cost / CPI / EAC in cost are not modelled | `analysis/evm.py`, `EvPoint.not_modelled` | Reported, not silently approximated (Debug block 8, EV page warning) | Open |
| Sub-minute rounding: `TimeAxis.at` rounds half minutes to even | `xer/calendar.py` | Corpus draws whole hours | P6's sub-minute rounding is undocumented |

## 11.2 Risk: module size and complexity

Measured on the current tree. Lines are `wc -l`; cyclomatic complexity (CC) from `radon cc`
(the backlog quotes ruff's `C901` figures, which count differently: `parse_text` 21 there, 42 here).

| Module | Lines | Hot spots (CC) | Why it matters |
|---|---|---|---|
| `analysis/cpm.py` | 1,664 | `_Run.forward` 42, `_Run.successor_limits` 41, `_Run.level_of_effort` 33, `_Run._assignments` 24, `_Run._network` 23, `_Run.pred_bounds` 22, `_Run.backward` 22, `_Run.longest_path` 20 | The status x link x lag x option cases are spread over four methods; a table read by both passes would make each cell a test (`docs/backlog.md` Structure) |
| `xer/model.py` | 1,317 | none above 20 | One module holds every P6 column meaning; large but flat |
| `app/state.py` | 1,238 | `_chosen_items` 18, `_folder_boxes` 14, `anonymizer` 14 | Sidebar, window, caches, baseline resolution and download helpers in one file; two cache policies (`_parse` and `memo`) |
| `xer/parser.py` | 147 | `parse_text` 42 | One loop with every tag, `keep` projection and warning case; small file, dense function |
| `anonymize.py` | 527 | `Anonymizer.table` 24, `Anonymizer.frame` 24 | Two parallel allowlist walkers (XER table vs app frame) |
| `sample.py` | 795 | `_cpm` 22, `_progress` 21, `_task_row` 20 | Demo generator with its own mini-CPM; left as is by decision (`docs/backlog.md`) |
| `app/views/*` | 2,092 | `health.show_check` 14 | Computations still inside views (changelog, health, ppc, gantt): not testable without `AppTest` |

Other structural debt from the backlog: `set_index("task_code")` in 13 places where
`Snapshot.by_code` could serve; three changelog row builders; `tests/test_p6_heldout.py` takes four
of the suite's seven minutes.

## 11.3 Risk: supply chain and deployment

| Item | Status | Evidence |
|---|---|---|
| **No SBOM, no provenance attestation, no signature on the published images** | Debt. `docker/build-push-action` runs without `sbom: true` or `provenance: true`; no cosign step | `.github/workflows/image.yml`; `docs/backlog.md` "Deployment and CI" |
| **Mutable `:latest` tags in `deploy/compose.yaml`** | Debt. Defaults are `ghcr.io/xerscope/xerscope:latest` and `ghcr.io/xerscope/xerscope-caddy:latest`; `docs/deploy.md` §7 and §9 tell the operator to pin `XERSCOPE_IMAGE=<image>@sha256:<digest>` in `.env`, but the shipped default is a tag anyone with the push token can move | `deploy/compose.yaml`, `deploy/.env.example` |
| **Tailscale and Caddy bases pinned by tag, not digest** | Debt. `tailscale/tailscale:v1.104.4`, `caddy:2.11.8-builder`, `caddy:2.11.8`; the app's `Dockerfile` pins by digest | `deploy/compose.yaml`, `deploy/caddy/Dockerfile`; backlog item |
| **Caddy image Trivy exceptions** | One dated entry in the file at the time of writing (the backlog speaks of 7 CVEs: the two have drifted apart), accepted until 2026-12-02 because the code path is ACME-only with `auto_https off`; the `deploy` job turns red at expiry | `deploy/caddy.trivyignore.yaml`, `docs/backlog.md` |
| **`caddy-ratelimit` pseudo-version bumped by hand** | Dependabot does not read a `RUN` line | `deploy/caddy/Dockerfile` |
| **bcrypt cost 10, one shared login** | Chosen for the NAS's CPU with no CPU quota; argon2id would turn CPU cost into memory against Caddy's 256 MB cap; one account cannot be revoked or told apart in the log | `docs/deploy.md` §3; backlog |
| **Verification on the real NAS pending** for several hardening changes (`TS_AUTH_ONCE` across restarts, read-only tailscaled on the Synology kernel, memory caps applied, `cap_drop` sidecars starting) | CI runs the stack on GitHub's Docker, not on the NAS kernel | backlog "Deployment and CI" |
| **CI container job opens no page** | The image starts and answers `/_stcore/health`, but no page is rendered through the published port | backlog |
| **Password hash and key in `.env` in clear** | Same confidentiality as the shared folder, not a vault; documented, not solved | `docs/deploy.md` §4 |

## 11.4 Risk: data handling in the app

| Item | Impact | Evidence |
|---|---|---|
| Raw bytes of each file kept in session state next to the parsed snapshot | About 1 GB per 40 MB export; sets how many weeks fit under the remote memory cap | `docs/backlog.md` "App"; `docs/deploy.md` §7 |
| Baseline-in-file re-reads the whole export per session | Costly on ~40 MB files; depends on the raw bytes the previous item would drop | backlog |
| Baseline file re-hashed on every rerun (`_parse` key) | Noticeable above ~50 MB | backlog |
| Display rounding can contradict a status (0.9545 shown as 0.95, passes > 0.95); Python rounds half to even, Streamlit tables half away from zero | A reader may doubt a correct verdict | backlog |
| CSV downloads write raw float digits and two date formats | Cosmetic, but visible to Power BI users | backlog |
| Parser: a tab or line break inside a text value shifts later fields without a warning; coerced numbers and dates are not counted; a duplicate `task_id` raises a pandas error | Silent misreads on malformed files; none seen in the 394 reference files | backlog |
| Upload path and WBS row selection not reachable by `AppTest` | Checked by hand before a release | backlog |

## 11.5 Documentation debt specific to this set

- No ADR log exists in the repository; section 9 reconstructs decisions from code and docs, and the
  dates of those decisions are not determined from code.
- `docs/architecture.md` and `tests/test_architecture.py` must be edited together when a layer rule
  changes; this set adds a third place (section 5) that quotes `LAYERS` and must follow.
- The "< 3 s for 4k activities" quality scenario is a reading of a measured figure in
  `docs/cpm.md`, not an asserted test (section 10, P-1).
