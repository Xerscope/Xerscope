# ADR-0027: Only a tested commit is published, with SLSA provenance, an SBOM and a build attestation

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-09 (`5ca0f45`, #165: provenance, SBOM, attestation, changelog and release procedure; `2075740`, #171: publish only after a green `tests` run, no cancel on main; `cb7abe1`, #177: `image.yml` called as the last job of `tests`); the publish condition corrected on 2026-11-10 (`2727604`, #182). `image.yml` itself dates from 2026-10-29 (`8221f3a`) |
| Scope | `.github/workflows/image.yml`, `.github/workflows/tests.yml` (`publish` job, `concurrency`), `Dockerfile`, `deploy/caddy/Dockerfile`, `CHANGELOG.md`; `tests/test_docker.py` |
| Sources | `5ca0f45` "Software audit: edge-case tests, load contract, typed errors, supply chain, app findings (#165)"; `2075740` "CI: no scan exceptions; images published after tests; provenance, SBOM, daily scan of published images (#171)"; `cb7abe1` "CI: publish as the last job of tests, no workflow_run checkout (#177)"; `2727604` "CI: the publish job asks each job for success by name, so a push publishes again (#182)"; OpenSSF Scorecard check Dangerous-Workflow; GitHub Docs, "Using jobs in a workflow" (a skipped job skips its dependents unless the condition calls a status function); [docs/deploy.md §7, §8](../deploy.md); [README.md](../../README.md) "Deployment"; [CHANGELOG.md](../../CHANGELOG.md) |

## Context

The NAS of the remote deployment (ADR-0025) has no terminal and cannot build: it pulls the
images `ghcr.io/<owner>/xerscope` and `ghcr.io/<owner>/xerscope-caddy` (or their Docker Hub
copies) and runs them. Whatever is published is what runs.

Until `2075740`, `image.yml` ran on every push to `main`, beside `tests.yml` and without waiting
for it: one commit was published as `latest` on ghcr.io and Docker Hub two minutes before its
container scan failed on two HIGH zlib CVEs (commit message of `2075740`). The fix of that
commit started `image.yml` on `workflow_run` of `tests` and checked out the run's `head_sha`;
Scorecard then flagged it as Dangerous-Workflow (a `workflow_run` workflow checking out a ref
chosen by another run is the path by which a fork's pull request code can run next to the
publishing token), which `cb7abe1` removed. After `cb7abe1`, the publish job was skipped on every
push: `changes` runs on pull requests only, `container` needs it, and a job carrying the default
`success()` is skipped after a skipped job in its chain (`2727604`).

A puller also needs to know which commit and workflow built an image, and what packages it holds,
before pinning its digest (ADR-0026).

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Publish on every push to `main`, in parallel with the tests (before `2075740`) | none | a commit whose tests or scans fail can already be `latest` |
| A separate workflow on `workflow_run` of `tests`, checking out the tested `head_sha` (`2075740`) | one workflow, conditions on the triggering run | Scorecard Dangerous-Workflow: a static check cannot see that the push condition keeps a fork out; one wrong condition would open the token to a fork's code |
| **A reusable workflow (`workflow_call`) called by `tests.yml` as its last job, on a push, once every other job passed (chosen, `cb7abe1`)** | the condition must name each job's result (`2727604`) | a re-publish is a re-run of the `tests` run; the slow weekly checks (mutation, accessibility) cannot gate it |

## Decision

**Who calls the publish.** `image.yml` has a single trigger, `workflow_call`. `tests.yml` is its
only caller, in one job, `publish`, with:

- `needs: [lint, oracle-report, test, fitness, audit, crosscheck, container, deploy]`: every job
  of `tests.yml` except `changes` (pull requests only) and `publish` itself;
- `if:` `!cancelled() && github.event_name == 'push'` and `needs.<job>.result == 'success'` for
  each of those eight jobs, written out by name: a failed, cancelled or skipped job, or a pull
  request, publishes nothing;
- the permissions `contents: read`, `packages: write`, `id-token: write`, `attestations: write`,
  and the two Docker Hub secrets passed by name (no `secrets: inherit`).

`tests.yml` runs on a push to `main`, on a push of a `v*` tag, on pull requests, by hand and
every Monday; only the two push events can publish.

**What is built.** `image.yml` runs in the caller's push context: `actions/checkout` takes the
pushed commit (`github.sha`), no `ref:` and no `workflow_run` anywhere, so nothing checks out a
ref chosen by another run. The job runs only when `github.repository` is the project's own
repository and the event is a push: nothing is published from a fork. A matrix builds two images,
`xerscope` (`Dockerfile`, context `.`) and `xerscope-caddy` (`deploy/caddy/Dockerfile`, context
`deploy/caddy`), `fail-fast: false`.

**Tags.** `docker/metadata-action` (the owner lowercased, as ghcr.io requires) gives
`latest` on the default branch (`type=raw,value=latest,enable={{is_default_branch}}`), the
version on a `v*` tag (`type=semver,pattern={{version}}`, e.g. `0.1.0`) and `sha-<short>` on every
build (`type=sha`); its labels, the revision label included, come from the pushed commit. The same
tags go to Docker Hub (`docker.io/<DOCKERHUB_IMAGE_OWNER>/<image>`) only when the secrets
`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` and the variable `DOCKERHUB_IMAGE_OWNER` are set
([docs/deploy.md §8](../deploy.md)).

**Provenance, SBOM, attestation.** The one `docker/build-push-action` step pushes every tag of
both registries with `provenance: mode=max` (BuildKit's SLSA provenance: source, materials,
parameters) and `sbom: true` (an SPDX SBOM), both attached to the image index. Then
`actions/attest-build-provenance` writes a GitHub build-provenance attestation of the pushed
digest (`subject-name: ghcr.io/<owner>/<image>`, `subject-digest` from the build step,
`push-to-registry: true`), signed through the job's OIDC token (Sigstore). The Docker Hub copy has
the same digest, so one attestation covers both. A puller checks it with
`gh attestation verify oci://ghcr.io/<owner>/xerscope@sha256:<digest> --owner <owner>` and reads
the provenance and SBOM with `docker buildx imagetools inspect` (docs/deploy.md §7).

**Never cut.** `tests.yml`'s concurrency group is `tests-<workflow>-<ref>` with
`cancel-in-progress: ${{ github.event_name == 'pull_request' }}`: a new push cancels a pull
request's previous run only; every commit on `main` and every tag is tested to the end, and a
publish under way is not cut between registries. No other workflow cancels a run in progress.

**Releases.** A release is a git tag `vX.Y.Z` on `main`, cut by the maintainer once
`CHANGELOG.md` (Keep a Changelog, Semantic Versioning; `[Unreleased]` until then) has the version
and the date. The tag push runs `tests`; its `publish` job publishes `:X.Y.Z` next to `latest`.
Nothing but a tag on `main` publishes a version; publishing again is re-running the `tests` run of
that commit.

**What does not gate.** `mutation.yml` (about an hour and a half) and `accessibility.yml`
(a browser) are separate workflows, weekly and by hand, and `windows.yml` (a browser, on a pull request
that touches the app): every job of `tests.yml` gates the
publish, and those must not.

## Consequences

Positive:

- `latest` and every version tag are a commit whose lint, tests, fitness, audit, MPXJ cross-check,
  image build and scan and deploy-stack checks passed in the same run.
- The publishing token never shares a job with code a pull request chose.
- A digest can be traced to its commit and workflow run, and its packages listed, before the NAS
  is pinned to it (ADR-0026).

Negative:

- A red job anywhere in `tests.yml`, including a CVE in the Tailscale image (ADR-0028), blocks
  every publish until it is fixed or excepted.
- The images carry an SBOM and provenance but no signature ([docs/backlog.md](../backlog.md),
  "Deployment and CI": a keyless cosign step); Container Manager checks neither.
- The called workflow has no runs of its own (its badge went with `cb7abe1`); its log is the
  `publish` job of a `tests` run.

## Verification

- `tests/test_docker.py::test_only_a_tested_commit_is_published`: `workflow_call` is the only
  trigger of `image.yml`, no `workflow_run` and no `ref:`; the repository and push condition;
  `tests.yml` runs on `main` and `v*` tags; `publish` needs every job but `changes` and asks each
  for `'success'` by name; `tests.yml` is the only caller, once, without `secrets: inherit`; the
  labels come from metadata-action.
- `tests/test_docker.py::test_published_images_carry_provenance_and_sbom` (one build-push step,
  `provenance: mode=max`, `sbom: true`, every tag pushed),
  `::test_published_images_carry_provenance_sbom_and_an_attestation` (the attestation of the
  digest, the job's and the caller's exact permissions, the workflow default read-only, the
  `latest`, semver and sha tag rules).
- `tests/test_docker.py::test_runs_on_main_are_never_cancelled_by_the_next_push` (only
  `tests.yml` sets `cancel-in-progress`, for pull requests).
- `tests/test_accessibility.py::test_the_accessibility_job_runs_weekly_or_by_hand_with_its_own_dependencies`
  (no accessibility job in `tests.yml`).
- `tests/test_docker.py::test_deployment_documents_immutable_image_refs_and_the_key_check`
  (the documented pin is a release and its digest).

## References

- `.github/workflows/image.yml` (header comment, `publish` job: condition, permissions, matrix,
  `metadata-action` tags, `build-push-action` `provenance`/`sbom`,
  `attest-build-provenance`).
- `.github/workflows/tests.yml` (`on`, `concurrency`, `changes`, `container`, `publish`).
- `.github/workflows/mutation.yml`, `.github/workflows/accessibility.yml` (headers: why they are
  separate).
- [CHANGELOG.md](../../CHANGELOG.md) (header: how a release is cut);
  [docs/deploy.md](../deploy.md) §7 "Pinning and upgrading the image", §8 "Image on Docker Hub";
  [README.md](../../README.md) "Deployment".
- Related: ADR-0013 (mutation, weekly), ADR-0025 (the stack that pulls the images), ADR-0026
  (pinning), ADR-0028 (the scans that gate), ADR-0030 (accessibility, weekly).
