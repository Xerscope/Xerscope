# ADR-0028: Continuous security scanning: Trivy on images, CodeQL, OpenSSF Scorecard, pip-audit and bandit

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`49ad764`, initial commit: the `audit` job, pip-audit and bandit); Trivy on the images from 2026-10-30 (`881fdb0`, through `aquasecurity/trivy-action`); Trivy from a digest-pinned image, `scan.sh` and the daily self-scan from 2026-11-06 (`345ff33`, #143); CodeQL and Scorecard from 2026-11-09 (`5ca0f45`, #165), Scorecard results private the same day (`844b177`, #176); daily scan of the published images and scans on pull requests from 2026-11-09 (`2075740`, #171); dated exceptions refused once stale from 2026-11-09 (`a243b5f`, #178) and 2026-11-16 (`c966309`, #245) |
| Scope | `.github/workflows/tests.yml` (jobs `audit`, `changes`, `container`, `deploy`), `.github/workflows/scanner.yml`, `.github/workflows/codeql.yml`, `.github/workflows/scorecard.yml`, `.github/trivy/` (`Dockerfile`, `scan.sh`, `self.trivyignore.yaml`), `deploy/tailscale.trivyignore.yaml`; `tests/test_docker.py` |
| Sources | `345ff33` "Deploy/tailscale trivy exception (#143)"; `2075740` "CI: no scan exceptions; images published after tests; provenance, SBOM, daily scan of published images (#171)"; `a243b5f` "CI: one dated scan exception, CVE-2026-78661 in the Tailscale image (#178)"; `844b177` "Scorecard: results kept private, no publish to the public API (#176)"; `c966309` "scanner: log in to ghcr, except the git of the Trivy image and keep it from running (#245)"; `d7a4850` "Funnel stack on Go 1.27.4: Caddy 2.11.9, Tailscale v1.104.7 (CVE-2026-97054) (#309)"; `4c86900` "Files window: the root check written as a guard CodeQL reads"; GHSA-69fq-xp46-6x23; [SECURITY.md](../../SECURITY.md); [CONTRIBUTING.md](../../CONTRIBUTING.md) "Verification"; [docs/backlog.md](../backlog.md) "Deployment and CI" |

## Context

Pinning (ADR-0026) makes every dependency exact; it does not say whether the exact version is
vulnerable. CVEs are published without any push to the repository: a release that was clean
when it was pinned becomes vulnerable later. Three kinds of code need watching: the Python
dependencies in `uv.lock`, the images (the app's distroless image, the Caddy image the project
builds, the upstream Tailscale image, and the Trivy image itself), and the project's own source.

Findings that cannot be fixed at once (no upstream release carries the fix) would otherwise turn
a job red every day and hide the next finding; an exception that is never removed hides the
finding for good. Two events in the history shaped the scanner: Trivy's March 2026 compromise
rewrote `aquasecurity/trivy-action` and `setup-trivy` (GHSA-69fq-xp46-6x23), which the CI used
until `345ff33`; and the scanner workflow was red every day from 10 November until `c966309`
(the ghcr packages are private; the Trivy image's own git carried three CVEs).

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Scan on the CI runs only (push, pull request, Monday) | no extra workflow | a CVE published between two pushes is seen up to a week later; the scanner's own image is never scanned |
| A third-party Trivy action, findings without a fix failing too | one `uses:` line | the action itself was compromised in March 2026; its default Trivy did not move unless the action did; a finding with no upstream fix keeps every run red |
| **Trivy from a digest-pinned image through `scan.sh`, fixed findings failing, dated exceptions refused once stale; a daily scan of the Trivy image and the published images; CodeQL, Scorecard, pip-audit and bandit beside it (chosen)** | one script, one daily workflow, exception files to renew or delete | an unfixed HIGH or CRITICAL finding is listed, not failed; CodeQL covers Python only |

## Decision

**Trivy, one image, one script.** `.github/trivy/Dockerfile` pins
`ghcr.io/aquasecurity/trivy:<version>@sha256:<digest>`; Dependabot proposes each release after a
7-day cooldown, checked daily (ADR-0026). `.github/trivy/scan.sh IMAGE [IGNOREFILE]` runs that
image:

- the image to scan is handed over as a tar (`docker save`): the Trivy container gets no Docker
  socket;
- `/dev/null` is mounted over `/usr/bin/git` in every scanning container: scanning a tar needs no
  git, and the CVEs of the Trivy image's git need it to run;
- a first run lists every HIGH and CRITICAL finding, fixed or not, excepted or not, without
  failing (`--exit-code 0`);
- a second run fails on any HIGH or CRITICAL finding that has a fix (`--ignore-unfixed
  --exit-code 1`), reading `IGNOREFILE` when one is given;
- before it, each `id:` of `IGNOREFILE` must appear in the first run's listing; an entry whose
  finding is no longer in the image makes the script exit 1 ("... is no longer found in IMAGE:
  delete the entry"), so an exception does not outlive its reason.

**Where Trivy runs.**

| Image | Where | When |
|---|---|---|
| the app image, built from the commit (`xerscope:ci`) | `tests.yml`, job `container` | push to `main` or a `v*` tag, the Monday run, by hand, and a pull request whose diff touches `Dockerfile`, `uv.lock`, `pyproject.toml`, `src/` or `.github/trivy/` (job `changes`) |
| the Caddy image built from `deploy/caddy/Dockerfile` | `tests.yml`, job `deploy` | every event, pull requests included; no exception file |
| the Tailscale image of `deploy/compose.yaml` | `tests.yml`, job `deploy` | every event; exception file `deploy/tailscale.trivyignore.yaml` |
| the pinned Trivy image, scanned with itself | `scanner.yml`, job `trivy` | daily, on a pull request or push to `main` that changes `.github/trivy/**`, by hand; exception file `.github/trivy/self.trivyignore.yaml` |
| `ghcr.io/<owner>/xerscope:latest` and `xerscope-caddy:latest`, as published | `scanner.yml`, job `published` | daily and by hand; logs in to ghcr.io with the workflow's token (`packages: read`); no exception file |

A container or deploy job that fails blocks the publish (ADR-0027). A red daily run of the
Trivy self-scan allows a Trivy bump before Dependabot's cooldown ends.

**Exceptions: two dated files, no other.** Each entry has an `id`, a `statement` (why the
finding does not apply here), an `expired_at` date and `purls` restricting it to one package
version, so another version is scanned again. `deploy/tailscale.trivyignore.yaml` holds
CVE-2026-78661 (golang.org/x/net v0.60.0, no Tailscale release with the fix), read by the
Tailscale scan alone; a step before that scan proves no `golang.org/x/net/html.` function name in
the image's three binaries (`containerboot`, `tailscale`, `tailscaled`).
`.github/trivy/self.trivyignore.yaml` holds the three git CVEs of the Trivy image
(CVE-2026-105437, CVE-2026-111760, CVE-2026-114466; `pkg:apk/alpine/git@2.54.0-r0` and
`git-init-template`), read by the self-scan alone. An entry ends, and the job turns red, at its
date, when the image holds another version, or when the finding is gone. Where the project builds
the image, the fix is built in instead of excepted: `deploy/caddy/Dockerfile` replaces
golang.org/x/net by a fixed version and fails unless the binary records the expected Go release
(go1.27.4 since `d7a4850`, CVE-2026-97054).

**CodeQL.** `codeql.yml` runs GitHub CodeQL on the Python sources with the
`security-and-quality` queries on every push to `main`, every pull request to `main` and every
Monday (05:17 UTC), so new queries run on unchanged code. It writes the SARIF upload only
(`security-events: write`). Its findings are fixed in the code rather than dismissed: the path
injection on a folder typed in the Files window was closed by reading only under one root,
rewritten as a guard CodeQL recognises (`9e824e7`, `4c86900`, ADR-0029); a test's possibly
unbound name was fixed in `dfe0dc6`.

**OpenSSF Scorecard.** `scorecard.yml` runs `ossf/scorecard-action` on every push to `main`,
every Monday (06:41 UTC) and by hand, in this repository only (no run on a fork). The result is
not sent to the public Scorecard API (`publish_results: false`, no `id-token`); it lands as SARIF
in the repository's code scanning. Its Dangerous-Workflow finding shaped the publish job
(ADR-0027).

**Dependencies and source.** The `audit` job of `tests.yml` (every run of `tests`) exports the
whole lock, `uv export --locked --all-extras --all-groups --no-hashes --no-emit-project`, and runs
`pip-audit@2.10.1` on it twice, once against OSV (`-s osv`) and once against PyPI (`-s pypi`),
then `bandit@1.9.4 -r src -ll` (medium and high severity). The same bandit command is part of
the local verification in CONTRIBUTING.md.

## Consequences

Positive:

- A CVE in a published image or in the scanner is seen the next morning, not at the next push.
- A bump of Caddy, Tailscale, the base images or the lock is built and scanned on its pull
  request, before the merge.
- No exception is silent or permanent: each is listed on every run, dated, scoped to one
  version, and refused once its finding is gone.

Negative:

- A HIGH finding without a fix only appears in the listing; it does not fail a job.
- A red scan of an upstream image (Tailscale) blocks every publish until a fixed release or a
  dated exception; renewing an exception is a reviewed change.
- The CodeQL and Scorecard results live in the repository's Security tab, not in the job logs.

Follow-ups ([docs/backlog.md](../backlog.md), "Deployment and CI"): move to the first Tailscale
release with x/net >= 0.62.0 and delete its exception file; drop the Caddy x/net replace once a
Caddy release requires a fixed version; bump Trivy when its self-scan is red.

## Verification

- `tests/test_docker.py::test_trivy_is_pinned_by_digest_and_proposed_a_week_after_release`
  (one Trivy image by digest, no Trivy action, three `scan.sh` calls in `tests.yml`, a tar
  without the Docker socket, fixed HIGH and CRITICAL findings fail).
- `tests/test_docker.py::test_scan_refuses_an_exception_whose_finding_is_gone` (runs `scan.sh`
  with a stand-in `docker`: exit 1 and the message when the excepted CVE is not listed).
- `tests/test_docker.py::test_the_tailscale_scan_exception_is_dated_and_read_by_its_scan_only`,
  `::test_the_trivy_self_scan_exception_covers_its_git_only_and_git_cannot_run` (exactly two
  exception files, their entries, purls and expiry bounds, the one scan that reads each, the
  listing run takes no exception, the git mount).
- `tests/test_docker.py::test_tailscale_x_net_html_absence_is_recorded_before_the_scan`.
- `tests/test_docker.py::test_the_pinned_trivy_is_scanned_every_day`,
  `::test_the_published_images_are_scanned_every_day` (daily cron, `packages: read`, ghcr login,
  the tags `deploy/compose.yaml` pulls).
- `tests/test_docker.py::test_a_pull_request_changing_the_image_builds_and_scans_it`,
  `::test_deploy_images_are_scanned_on_pull_requests`.
- `tests/test_docker.py::test_codeql_and_scorecard_run_pinned_with_minimal_permissions`
  (triggers, `security-events: write` only, `publish_results: false`, no run on a fork).
- `tests/test_docker.py::test_ci_tools_are_pinned_to_one_release` (pip-audit and bandit pinned).
- `tests/test_docker.py::test_caddy_build_forces_the_fixed_x_net_and_proves_it`.

## References

- `.github/trivy/scan.sh`, `.github/trivy/Dockerfile`, `.github/trivy/self.trivyignore.yaml`,
  `deploy/tailscale.trivyignore.yaml`.
- `.github/workflows/scanner.yml` (jobs `trivy`, `published`), `.github/workflows/tests.yml`
  (jobs `audit`, `changes`, `container`, `deploy`), `.github/workflows/codeql.yml`,
  `.github/workflows/scorecard.yml`.
- `deploy/caddy/Dockerfile` (the x/net replace and the Go version check).
- [SECURITY.md](../../SECURITY.md); [CONTRIBUTING.md](../../CONTRIBUTING.md) "Verification";
  [docs/backlog.md](../backlog.md) "Deployment and CI".
- Related: ADR-0024 (the image scanned), ADR-0025 (the Caddy and Tailscale images), ADR-0026
  (what is pinned), ADR-0027 (the scans gate the publish), ADR-0029 (a CodeQL finding fixed).
