# ADR-0026: Pinned supply chain: uv lockfile, digest-pinned images, SHA-pinned actions, delayed Dependabot updates

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`49ad764`, initial commit: `uv.lock`, `uv sync --locked`, actions pinned by commit SHA, Dependabot for uv and github-actions); base images pinned by digest from 2026-11-02 (`1ce74f9`); the Trivy image pinned and a 7-day cooldown on its updates from 2026-11-06 (`345ff33`, #143); the cooldown on every ecosystem and `uvx` tools pinned to one release from 2026-11-09 (`2075740`, #171) |
| Scope | `uv.lock`, `pyproject.toml` (dependency floors), `Dockerfile`, `deploy/caddy/Dockerfile`, `deploy/compose.yaml`, `deploy/.env.example`, `.github/trivy/Dockerfile`, `.github/dependabot.yml`, `.github/workflows/*.yml`; `tests/test_docker.py` |
| Sources | `49ad764` "initial git commit"; `1ce74f9` "Deploy: memory and PID caps, read-only tailscaled, locked data folder, security headers"; `345ff33` "Deploy/tailscale trivy exception (#143)"; `5ca0f45` "Software audit: edge-case tests, load contract, typed errors, supply chain, app findings (#165)" (Caddy bases by digest, release tag and digest documented for the NAS); `2075740` "CI: no scan exceptions; images published after tests; provenance, SBOM, daily scan of published images (#171)"; GitHub Docs, "Optimizing the creation of pull requests for Dependabot version updates" (cooldown applies to version updates, not security updates); GHSA-69fq-xp46-6x23 (Trivy's compromised March 2026 releases); [docs/deploy.md §7](../deploy.md) "Pinning and upgrading the image"; [SECURITY.md](../../SECURITY.md) |

## Context

Every byte the project runs in CI or ships in an image comes from a third party: Python packages
from PyPI, base images from ghcr.io, gcr.io and Docker Hub, GitHub Actions, the uv binary and the
tools run with `uvx` (ruff, pip-audit, bandit). Each is named by something that can move: a
version range, an image tag, an action tag, a bare tool name. Whoever controls the upstream
repository can repoint a tag; a compromised release is live on the day it is published and is
usually withdrawn within days (Trivy's March 2026 releases were withdrawn within hours,
GHSA-69fq-xp46-6x23).

Before `2075740`, `tests.yml` ran `uvx ruff`, `uvx bandit` and `uvx pip-audit` without a version
and setup-uv without `version`: a new ruff rule could turn CI red with no change in the
repository, and a compromised release would have run in CI on its first day. Only the Trivy entry
of `dependabot.yml` had a cooldown. Before `1ce74f9` the `Dockerfile` only recommended pinning the
bases by digest ("in production"); before `5ca0f45` `deploy/caddy/Dockerfile` pinned Caddy by tag
and `deploy/compose.yaml` documented `:latest` as the thing to run.

The NAS deployment (ADR-0025) pulls images and runs them without a terminal: what it pulls must
be the build that was tested (ADR-0027), and a rollback must name the previous build exactly.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Version ranges, tags and bare tool names, upgraded as they come | nothing to maintain | a tag or a range can resolve to a different, possibly compromised, artifact at any run; CI can turn red with no change in the repository; a rollback cannot name the exact previous build |
| Pin everything, update by hand only | no automation to trust | pins fall behind; security fixes reach the repository only when someone looks |
| **Pin everything to an immutable identifier, let Dependabot propose the updates a week after release, security updates without delay (chosen)** | a lockfile, digests and SHAs to bump (mostly by Dependabot PRs); uv and the `uvx` tools bumped by hand | a release compromised and not withdrawn within the week is still proposed; Dependabot reads neither the uv version of setup-uv nor `uvx` versions nor the `caddy-ratelimit` version; the Tailscale image is pinned by tag, not digest ([docs/backlog.md](../backlog.md), "Deployment and CI") |

## Decision

**Python dependencies: a lockfile, always used.** `uv.lock` holds the exact version and hashes
of every dependency, extras and dependency groups included. Every install in CI and in the image
uses it: `uv sync --locked` in each job of `tests.yml` that installs the project (`--extra
crosscheck` in `crosscheck`; the `audit` job exports the same lock with `uv export --locked`),
`--group accessibility` in `accessibility.yml`, plain in `mutation.yml`, and twice `uv sync --locked --no-dev` in the
`Dockerfile`'s build stage. `--locked` fails when `uv.lock` does not match `pyproject.toml`
instead of re-resolving. `pyproject.toml`'s floors are the latest releases at the last audit
(its comment: "Floors = latest releases at the last audit (2026-10-28), so even an install that
ignores uv.lock cannot pull an older, vulnerable version. Bump them when you upgrade the lock.").
Tools whose numbers a committed baseline holds are exact: `complexipy`, `deptry`,
`import-linter`, `mypy`, `radon` (code fitness, ADR-0012), `mutmut` (ADR-0013) and
`playwright==1.64.1` (ADR-0030).

**Images: a digest behind every tag.**

- `Dockerfile`: its three `FROM` lines (`ghcr.io/astral-sh/uv:0.13.8-trixie-slim` for the
  `os-fixes` and `build` stages, `gcr.io/distroless/cc-debian13:nonroot` for the runtime) are
  `tag@sha256:<digest>`. Its header: "Base images are pinned by digest: a tag can be moved, a
  digest cannot." The lines are literal, because Dependabot cannot follow an `ARG`.
- `deploy/caddy/Dockerfile`: `caddy:<version>-builder` and `caddy:<version>`, each by digest,
  one Caddy release for both (Dependabot group `caddy`). The `caddy-ratelimit` version in its
  `RUN` line is bumped by hand.
- `.github/trivy/Dockerfile`: one line, `ghcr.io/aquasecurity/trivy:<version>@sha256:<digest>`.
  Nothing builds this file; it exists so that Dependabot proposes each Trivy release
  (ADR-0028). No Trivy GitHub Action is used: `aquasecurity/trivy-action` and `setup-trivy`
  were the components rewritten in the March 2026 compromise (`345ff33`).
- `deploy/compose.yaml`: Tailscale is pinned to one release tag (`tailscale/tailscale:v1.104.7`);
  the app and Caddy images default to `:latest` for a first start only. The documented setting
  for the NAS is a release tag and its digest in `deploy/.env.example`
  (`XERSCOPE_IMAGE=ghcr.io/<owner>/xerscope:0.1.0@sha256:<digest>`, the same for
  `XERSCOPE_CADDY_IMAGE`); [docs/deploy.md §7](../deploy.md) "Pinning and upgrading the image"
  says how to read a digest, check its attestation (ADR-0027), bump and roll back.

**GitHub Actions: a commit SHA, the version in a comment.** Every `uses:` line of every workflow
is `owner/action@<40-hex SHA> # vX.Y.Z`; the one exception is the local call
`uses: ./.github/workflows/image.yml`.

**uv and `uvx` tools: one release, bumped by hand.** setup-uv installs `version: "0.13.8"`, the
uv release of the `Dockerfile`'s `FROM` line, on every use. Every `run: uvx` names a release
(`ruff@0.17.4`, `pip-audit@2.10.1`, `bandit@1.9.4`); axe-core is installed as
`axe-core@4.14.0` and refused unless its SHA-256 matches (ADR-0030). `tests.yml` says why by
hand: "Dependabot reads neither."

**Dependabot: weekly proposals, a week after release.** `.github/dependabot.yml` has six
entries: `uv` (`/`, one group `python`), `github-actions` (`/`, one group `actions`), `docker`
(`/`, the `Dockerfile`'s `FROM` lines), `docker-compose` (`/deploy`, the Tailscale image),
`docker` (`/deploy/caddy`, group `caddy`), all weekly, and `docker` (`/.github/trivy`) daily.
Every entry carries `cooldown: default-days: 7`: a version update is proposed only once the
release is a week old, so a compromised release withdrawn within the week is never proposed.
Security updates are not delayed (GitHub: cooldown applies "for version updates, but not
security updates").

**Workflows: least privilege by default.** Every workflow but `scorecard.yml` sets
`permissions: contents: read` at the top (Scorecard's is `read-all`); a job that writes asks for
exactly what it writes (the publish job: `packages`, `id-token`, `attestations`; CodeQL and
Scorecard: `security-events`; the `published` scan: `packages: read`). Every `actions/checkout`
step (18 across the workflows) sets `persist-credentials: false`, so no later step finds the
token in `.git/config`.

## Consequences

Positive:

- A rerun of CI or of an image build resolves the same Python packages, the same base images and
  the same actions as the run before it; a change of version is a reviewed diff.
- A compromised upstream release must survive a week unnoticed before it is even proposed, and is
  then built and scanned on the pull request before a merge (ADR-0028: the container and deploy
  jobs run on pull requests that change the image or the stack).
- The NAS runs a digest; rolling back is putting the previous digest back (docs/deploy.md §7).

Negative:

- Bumps are work: Dependabot PRs every week, and the hand-bumped versions (uv, the `uvx` tools,
  `caddy-ratelimit`, the `OS_FIXES` of the `Dockerfile`) depend on someone reading the releases.
- A fix that is not a security advisory waits the cooldown too; a red daily scan of the Trivy
  image allows a bump before it ends ([docs/backlog.md](../backlog.md), "Deployment and CI").

Follow-ups ([docs/backlog.md](../backlog.md), "Deployment and CI"): pin the Tailscale image by
digest as well as tag; sign the published images (a keyless cosign step).

## Verification

- `tests/test_docker.py::test_image_runs_as_nonroot_from_the_lockfile` (two `uv sync --locked
  --no-dev` in the `Dockerfile`).
- `tests/test_docker.py::test_base_images_pinned_by_digest` (three `FROM` lines, each
  `tag@sha256:<64 hex>`), `::test_caddy_base_images_pinned_by_digest` (two caddy bases, one
  release, two digests), `::test_trivy_is_pinned_by_digest_and_proposed_a_week_after_release`
  (one Trivy image by digest, cooldown of at least 7 days, no Trivy action in any workflow).
- `tests/test_docker.py::test_ci_tools_are_pinned_to_one_release` (every `run: uvx` tool is
  `name@X.Y.Z`; every setup-uv installs the `Dockerfile`'s uv release).
- `tests/test_docker.py::test_every_dependabot_version_update_waits_a_week` (six entries, each
  `default-days` >= 7).
- `tests/test_docker.py::test_ci_cannot_pass_by_skipping_its_evidence` (every `uses:` of
  `tests.yml` is pinned by commit, tag in the comment),
  `::test_published_images_carry_provenance_sbom_and_an_attestation` and
  `::test_codeql_and_scorecard_run_pinned_with_minimal_permissions` (the same for `image.yml`,
  `codeql.yml`, `scorecard.yml`, with their permissions),
  `::test_the_pinned_trivy_is_scanned_every_day` (`scanner.yml`: `contents: read`,
  `persist-credentials: false`).
- `tests/test_docker.py::test_deployment_documents_immutable_image_refs_and_the_key_check`
  (`:latest` only as the compose default; `.env.example` pins a release and its digest).
- The jobs `lint`, `oracle-report`, `test`, `fitness` and `crosscheck` of `tests.yml` run
  `uv sync --locked`, and `audit` runs `uv export --locked`: each fails on a lock that does not
  match `pyproject.toml`.

## References

- `uv.lock`; `pyproject.toml` (`dependencies` and their floors comment, `[dependency-groups]`).
- `Dockerfile` (header, `ARG OS_FIXES`, the three `FROM` lines, `uv sync --locked`);
  `deploy/caddy/Dockerfile` (header, `FROM` lines); `.github/trivy/Dockerfile`;
  `deploy/compose.yaml` (`image:` lines); `deploy/.env.example`.
- `.github/dependabot.yml`; `.github/workflows/tests.yml` (header comment on pinning,
  `permissions`), every workflow's `uses:` and `actions/checkout` steps.
- [docs/deploy.md](../deploy.md) §7 "Pinning and upgrading the image", §9 (security checklist);
  [SECURITY.md](../../SECURITY.md); [CONTRIBUTING.md](../../CONTRIBUTING.md), "Verification"
  (the pinned tool versions).
- Related: ADR-0024 (the hardened container), ADR-0025 (the remote stack), ADR-0027 (what is
  published), ADR-0028 (scanning what is pinned), ADR-0030 (axe-core and playwright pinned).
