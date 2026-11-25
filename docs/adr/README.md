# Architecture decision records

Each record states one decision that the code embodies today: the context, the options weighed, the choice, what it costs, and what in the repository proves it holds (a test, a CI job, a script). A record is read with the code: when the code and a record disagree, the code is the fact and the record is corrected or superseded.

## Format

`NNNN-<slug>.md`, title `# ADR-NNNN: <decision>`, then a header table (Status, Date, Scope, Sources) and the sections Context, Options considered, Decision, Consequences, Verification, References. The Date is the commit that introduced the decision (`git log`), followed by the commits that shaped it.

Status is `Proposed`, `Accepted` or `Superseded by ADR-NNNN`. A record is never rewritten to change a decision: a new record supersedes it and the old one names its successor.

A technical change presented as Problem / Options / Choice / Verification (CONTRIBUTING.md) becomes a record here once the maintainer agrees: Problem goes in Context, Choice and its source in Decision.

## Index

### Foundations: reading P6 data

| ADR | Decision | Status | Since |
|---|---|---|---|
| [ADR-0001](0001-layered-architecture-one-way-data-flow.md) | Layered architecture with one-way data flow (xer -> store -> analysis -> viz -> app, cli on top) | Accepted | 2026-10-29 |
| [ADR-0002](0002-format-parser-then-p6-model-with-load-contract.md) | Two-stage XER reading: a format-only parser, then one model that owns every P6 meaning, under a load contract | Accepted | 2026-10-29 |
| [ADR-0003](0003-activity-identity-by-task-code.md) | Activities are identified by task_code (Activity ID), never task_id | Accepted | 2026-10-29 |
| [ADR-0004](0004-hours-stored-working-days-on-activity-calendar.md) | Units: hours stored, working days of the activity's own calendar, exact working time on a minute axis | Accepted | 2026-10-29 |
| [ADR-0005](0005-p6-professional-as-reference-sources-settle-behaviour.md) | Primavera P6 Professional as the reference; every rule names its source, open questions are recorded not guessed | Accepted | 2026-10-29 |
| [ADR-0006](0006-weekly-series-store-one-snapshot-per-data-date.md) | A weekly series store: one snapshot per data date, long-format frames for every analysis | Accepted | 2026-10-29 |

### Engine and evidence

| ADR | Decision | Status | Since |
|---|---|---|---|
| [ADR-0007](0007-own-cpm-engine-validated-against-p6.md) | An own CPM engine in Python, P6-exact by evidence, with MPXJ kept as an optional cross-check | Accepted | 2026-10-29 |
| [ADR-0008](0008-evidence-hierarchy-oracle-markers-and-floors.md) | Evidence hierarchy for expected values: P6 output first, oracle markers on tests, floors that never drop | Accepted | 2026-10-29 |
| [ADR-0009](0009-standards-as-toml-one-function-per-check.md) | Standards as TOML data; one explicit function per built-in check, parameterised rules for a company standard | Accepted | 2026-10-29 |
| [ADR-0010](0010-traced-numbers-named-populations-and-explanations.md) | Every number traced: one named population vocabulary (Funnel) and an explanation beside each result | Accepted | 2026-11-03 |
| [ADR-0011](0011-golden-characterization-tests.md) | Characterization (golden) files freeze every standard's result and every page | Accepted | 2026-11-01 |
| [ADR-0012](0012-code-fitness-ratchet-and-proof-of-moves.md) | Code fitness ratchet, docstring rules and a mechanical proof that a refactor only moves code | Accepted | 2026-11-08 |
| [ADR-0013](0013-mutation-testing-weekly-baseline.md) | Mutation testing of selected modules, run weekly against a committed baseline | Accepted | 2026-11-12 |

### Data privacy

| ADR | Decision | Status | Since |
|---|---|---|---|
| [ADR-0014](0014-no-real-schedule-in-repository.md) | No real schedule in the repository: tests build files in code or fetch pinned public files | Accepted | 2026-10-29 |
| [ADR-0015](0015-anonymised-downloads-by-default.md) | Downloads anonymised by default with a per-session HMAC key and a column allowlist | Accepted | 2026-11-03 |

### Application

| ADR | Decision | Status | Since |
|---|---|---|---|
| [ADR-0016](0016-streamlit-web-app-pages-compose-analyses.md) | Streamlit web app: pages compose analyses and figures; the Gantt is a custom component that never parses schedule text as HTML | Accepted | 2026-10-29 |
| [ADR-0017](0017-background-loading-worker-processes-and-session-memo.md) | Files read in background worker processes; per-session memo cache keyed on data identity and baseline | Accepted | 2026-11-06 |
| [ADR-0018](0018-baseline-read-per-page-with-kind-and-source.md) | The baseline is read per page, and every baseline carries its kind, how it was found and its source | Accepted | 2026-11-21 |
| [ADR-0019](0019-p6-xml-export-for-baselines.md) | P6 XML (PMXML) export read for baselines, streamed and converted to the XER tables | Accepted | 2026-11-06 |
| [ADR-0020](0020-ask-field-deterministic-grammar-no-llm.md) | The Gantt 'Ask' field is a deterministic bilingual grammar over the file's own lexicon; no language model is deployed | Accepted | 2026-11-06 |
| [ADR-0021](0021-ask-lexicon-as-data-outside-repository-and-image.md) | Ask lexicon as data outside the repository and the image: curated, generated and suggested folders | Accepted | 2026-11-09 |
| [ADR-0022](0022-power-bi-star-schema-export.md) | Power BI export as a star schema in Parquet or CSV | Accepted | 2026-10-29 |
| [ADR-0023](0023-csv-formula-injection-neutralised.md) | Every CSV neutralised against formula injection (CWE-1236) | Accepted | 2026-11-09 |

### Deployment and supply chain

| ADR | Decision | Status | Since |
|---|---|---|---|
| [ADR-0024](0024-local-first-hardened-container.md) | Local first: localhost only, and a distroless, non-root, read-only container published on loopback | Accepted | 2026-10-29 |
| [ADR-0025](0025-remote-access-tailscale-funnel-and-caddy.md) | Remote access through Tailscale Funnel and Caddy, with no published port | Accepted | 2026-10-29 |
| [ADR-0026](0026-pinned-supply-chain-lockfile-digests-shas.md) | Pinned supply chain: uv lockfile, digest-pinned images, SHA-pinned actions, delayed Dependabot updates | Accepted | 2026-10-29 |
| [ADR-0027](0027-publish-only-tested-commits-with-provenance.md) | Only a tested commit is published, with SLSA provenance, an SBOM and a build attestation | Accepted | 2026-11-09 |
| [ADR-0028](0028-security-scanning-trivy-codeql-scorecard-audit.md) | Continuous security scanning: Trivy on images, CodeQL, OpenSSF Scorecard, pip-audit and bandit | Accepted | 2026-10-29 |
| [ADR-0029](0029-typed-folder-read-under-one-root.md) | A folder typed in the Files window is read only under one root | Accepted | 2026-11-20 |
| [ADR-0030](0030-accessible-self-contained-ui.md) | Accessible, self-contained UI: WCAG 2.2 AA checked in a browser, self-hosted fonts, status colours reserved | Accepted | 2026-11-03 |

## Pending

[docs/structure-proposal.md](../structure-proposal.md) proposes sub-packages and file splits of `src/xerscope` and `tests/`. It is not applied; once the maintainer settles its open questions, the decision is recorded here as a new record.
