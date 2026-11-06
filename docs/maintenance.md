# Maintenance plan

What keeps xerscope correct, secure and changeable with one maintainer. Each item says when, what
to run, and what "done" means. Most of it is already automated; the rest is short.

## 0. Major risks (Nov 2026)

Two risks outweigh everything else in this plan; both are rated **major**.

### R1. Type annotations nobody checks

96 % of the functions carry type annotations (801 of 835), but no tool reads them: `mypy`
reports **63 inconsistencies in 16 files** (`uvx --from mypy mypy src --ignore-missing-imports`).
Most are an `Optional` value used without a check: `arg-type` 20, `union-attr` 10, `var-annotated`
8, `misc` 6, `operator` 5. Some may be latent bugs (e.g. `xer/calendar.py:264` returns
`TimeAxis | None` where callers expect a `TimeAxis`; `analysis/cpm.py:589` reads `base.frame`
on a `Schedule | None`). Annotations that are not checked drift, and a reader trusts them.
Hot spots: `sample.py` 12, `analysis/rules.py` 11, `analysis/cpm.py` 10, `app/state.py` 8.

| Step | Effort | Done when |
|---|---|---|
| Fix the 63 findings, one commit per module, each `Optional` narrowed or its annotation corrected | 1 day | `mypy src` prints no error |
| Add `mypy` to the dev group and to the `tests.yml` lint job, blocking | 1 h | a PR with a type error is red |
| `[tool.mypy]` in `pyproject.toml`: `check_untyped_defs`, `warn_unused_ignores`, `strict_optional` | 1 h | config in the repository, not in a command line |
| Later, module by module: `disallow_untyped_defs` on `xer/` and `analysis/` | ½ day per package | the core is fully typed |

Do it when no other PR is open on `src/`: the fixes touch 16 files.

### R2. One person knows everything (bus factor 1)

The code, the P6 semantics, the deployment and the accounts live with one maintainer. The
repository holds the knowledge (§5), but not the access, and nobody else has ever run the
release or restored the deployment.

| Step | Effort | Done when |
|---|---|---|
| Secrets and access inventory, kept outside the repository (password manager or sealed note): GitHub org owner, GHCR and Docker Hub tokens, Tailscale admin and auth keys, deployment `.env`, NAS account | 1 h | a second trusted person knows where it is and how to open it |
| A second owner on the GitHub organisation and on the Tailscale tailnet | ½ h | two people can rotate a token or revoke access |
| Recovery runbook: rebuild the remote stack from an empty machine (deploy.md §1–9 as one checklist, with timings) | 2 h | written in deploy.md |
| Recovery drill: someone else follows the runbook and cuts a release from `CHANGELOG.md` | ½ day, yearly | done once, dated in this file |
| Walkthrough recording or session: code-map.md, cpm.md, one check end to end, one release | 2 h | a second person can answer "where is X" without the maintainer |
| Optional: require one review on `main` once a second contributor exists | — | Scorecard "Code-Review" passes |

## 1. What runs by itself

| When | What | Where | If it goes red |
|---|---|---|---|
| Every push and PR | tests (full suite, reference files, P6 held-out corpus, MPXJ cross-check), ruff, format, bandit, pip-audit, attribution | `.github/workflows/tests.yml`, `attribution.yml` | fix before merging; never skip a test or lower a floor |
| Every push to `main`, every `v*` tag | images built, scanned (Trivy), published with provenance, SBOM and attestation | `image.yml` | read the Trivy finding; a new exception goes in `deploy/caddy.trivyignore.yaml` with a reason and an expiry |
| Mondays | the test workflow (new CVEs without a push), CodeQL, Scorecard | `tests.yml`, `codeql.yml`, `scorecard.yml` | Security tab: triage within the week |
| Weekly | Dependabot: uv, GitHub Actions, Docker base images, compose, Caddy | `.github/dependabot.yml` | comment `@dependabot rebase` before merging, then merge if green |

## 2. Recurring tasks

### Weekly (≈ 15 min)

- Merge green Dependabot PRs after a rebase. A major version of pandas, Streamlit, Plotly or
  pyarrow gets its own PR and a look at the app (`uv run xerscope app --data data/sample`).
- Read the Security tab (CodeQL, Scorecard, Dependabot alerts).

### Monthly (≈ 1 h)

- **Trivy exceptions:** open `deploy/caddy.trivyignore.yaml`; renew or drop each entry before its
  `expired_at`. The next one expires on **2026-12-02**.
- **Caddy rate-limit module:** its version is a pseudo-version bumped by hand
  (`deploy/caddy/Dockerfile`); check the upstream repository for a new commit or tag.
- **Floors:** `uv run pytest tests/test_p6_heldout.py -q`; raise any `FLOORS` value the engine now
  exceeds (at two decimals), in a commit of its own. Floors only go up.
- **Backlog:** prune `docs/backlog.md`; close what was done, move what was decided into the docs.

### Quarterly (≈ ½ day)

- **Coverage and mutation:** `uv run --with pytest-cov pytest --cov=xerscope --cov-branch`, and
  `mutmut` on one module (`calendar.py`, `rules.py`, `standards.py`, `evm.py` in turn). Add the
  tests that the surviving mutants point to. Baselines: coverage 90.7 % (Nov 2026), mutation
  64–77 % (docs/deep-dive/tests-mutation.md, to redo on calendar.py and standards.py).
- **Complexity:** `uvx radon cc -s -n D src` and `uvx radon mi -s src`. Nothing new above
  complexity 20; a module growing past 1,500 lines gets a split plan (architecture/13 §13.3).
- **Visual pass:** rerun the Playwright campaign on the demo series (nine states, every page,
  desktop and phone, light and dark) before a release that touches `app/` or `viz/`;
  compare with visual-debug-report.md.
- **Docs drift:** read code-map.md and architecture.md §1–4 against the code; fix what moved.
- **Reference corpora:** check the pinned commits in `tests/reference/sources.py` for upstream
  additions (new held-out sets, new MPXJ release). A new set is added at its measured floor.

### Each release

1. `main` green, including the MPXJ job.
2. `CHANGELOG.md`: move `[Unreleased]` under the new version with the date.
3. `git tag vX.Y.Z` on `main`, push the tag: `image.yml` publishes `:X.Y.Z` with its attestation.
4. Check the attestation: `gh attestation verify oci://ghcr.io/xerscope/xerscope:X.Y.Z --owner xerscope`.
5. Update the pinned image reference in your deployment (`deploy/.env`: tag and digest).
6. Smoke test the deployed app: Files window, one standard on Schedule health, one download.

Versioning: SemVer. A change to a computed value, a CSV column or a CLI exit code is at least a
minor version, and is listed under "Changed" in the changelog.

## 3. When P6 or a standard changes

| Event | Do |
|---|---|
| New P6 release (e.g. 25.x, 26.x) | read the "What's new" for scheduling and Check Schedule; export one schedule from it and run `xerscope recalc --report` and `check --expect`; record any difference in cpm.md "Conventions" or standards.md |
| New DCMA DECM version | diff the metric list; one function per changed metric, the TOML target, the comparison table in standards.md |
| A user reports a wrong number | rebuild the shape with `xerkit` (never commit their file), write the failing test, find the evidence (P6 export, corpus witness, hand calculation), then fix |

## 4. Health indicators to watch

| Indicator | Today (Nov 2026) | Alert when |
|---|---|---|
| Held-out corpus, values identical to P6 | 89.4 % (H1–H7 99.9 %) | any set below its floor (CI fails) |
| Full suite | 1,651 passed, ~15 min | > 20 min: parallelise `test_p6_heldout.py` (backlog) |
| Branch coverage | 90.7 % | below 88 % |
| Functions with complexity ≥ 20 | 12 | any new one |
| mypy errors (R1) | 63 | any, once mypy is in CI |
| People with admin access to GitHub, GHCR, Tailscale (R2) | 1 | fewer than 2 |
| Largest modules | `cpm.py` 1,828, `state.py` 1,538, `model.py` 1,403 lines | a module crosses 2,000 lines |
| Open Dependabot / CodeQL alerts | 0 | older than 2 weeks |
| Trivy exceptions | 1 (expires 2026-12-02) | any past its expiry |

## 5. Bus factor: what someone else needs

One maintainer means the knowledge must live in the repository.

- **Read path:** README → [code-map.md](code-map.md) → architecture.md → CONTRIBUTING.md.
- **Every number traceable:** each rule names its source (TOML `source`, docstring); each engine
  convention names its corpus witness (cpm.md); `PINNED` in `tests/test_p6_heldout.py` names the
  activity behind each rule.
- **Decisions written down:** architecture/09 (ADRs); a decision a reader would question gets ten
  lines there.
- **Secrets and access:** the GHCR and Docker Hub tokens, the Tailscale tailnet and the deployment
  `.env` are outside the repository; keep a sealed copy of where they are and who can rotate them.

## 6. Planned structural work (at constant output)

From architecture/13, in order; each step keeps every computed value identical before any
behaviour changes.

| Step | Effort | Gate |
|---|---|---|
| Complexity and module-size limits enforced by tests (P5) | ½ day | ruff C901 at 15 with named exceptions |
| Error contract written down, engine property test (P4) | ½ day | random networks: `schedule` returns or raises `ScheduleError` |
| `app/state.py` split behind its current names (P2) | 1 day | `test_app*.py` unchanged |
| Pure page-data functions for changelog, health, ppc, gantt (P3) | 2 days | `test_app_parity.py` unchanged |
| CPM link, constraint and placement tables (P1) | 3–5 days | P6 files to the minute, floors, MPXJ |
| Then the engine experiments: mandatory dates, milestones with an expected finish | 1–2 days | floors raised (deep-dive/engine-gaps.md) |
