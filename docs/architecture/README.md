# Architecture documentation (arc42 / C4)

This folder documents xerscope the way the **arc42 template (v8)** lays an architecture out, with
**C4 model** diagrams in Mermaid, and the stakeholder / concern / viewpoint vocabulary of
**ISO/IEC/IEEE 42010**. Every statement is grounded in the code and configuration of this repository
(`src/xerscope/**`, `src/xerscope/standards/*.toml`, `Dockerfile`, `compose.yaml`, `deploy/`,
`.github/workflows/`, `pyproject.toml`, `tests/`). Where the code does not settle a point, the text
says "not determined from code" rather than guessing.

No real schedule data, project code, hostname or tailnet name appears here; examples use
placeholders such as `<tailnet>`, `<random>`, `<login>` and `PROJ-01`.

## The set

| arc42 section | File | What it answers |
|---|---|---|
| 1 Introduction and goals | [01-introduction-and-goals.md](01-introduction-and-goals.md) | What the system does, top quality goals (ISO 25010), who cares |
| 2 Constraints | [02-constraints.md](02-constraints.md) | Technical, organisational and convention constraints |
| 3 Context and scope | [03-context-and-scope.md](03-context-and-scope.md) | C4 L1 system context, C4 L2 containers, business and technical context |
| 4 Solution strategy | [04-solution-strategy.md](04-solution-strategy.md) | The handful of decisions that shape everything else |
| 5 Building blocks | [05-building-blocks.md](05-building-blocks.md) | C4 L3 components per package, layer rules, dependency diagram |
| 6 Runtime view | [06-runtime-views.md](06-runtime-views.md) | Sequence diagrams of the five main scenarios |
| 7 Deployment view | [07-deployment.md](07-deployment.md) | Local compose, Funnel stack, image pipeline, supply chain |
| 8 Cross-cutting concepts | [08-crosscutting-concepts.md](08-crosscutting-concepts.md) | Domain model, time, errors, caching, security, config, testing |
| 9 Architecture decisions | [09-architecture-decisions.md](09-architecture-decisions.md) | ADRs in MADR format, reconstructed from code and docs |
| 10 Quality requirements | [10-quality-requirements.md](10-quality-requirements.md) | Quality tree and concrete scenarios |
| 11 Risks and technical debt | [11-risks-and-technical-debt.md](11-risks-and-technical-debt.md) | Known gaps, hot spots, supply-chain debt |
| 12 Glossary | [12-glossary.md](12-glossary.md) | Domain and technical terms |

## How it relates to the existing documentation

The existing documents stay authoritative for their subject; this set links to them and does not
repeat them.

| Existing document | Role | Referenced from |
|---|---|---|
| [../architecture.md](../architecture.md) | Code walkthrough, module by module, with the layer rules | Sections 5 and 8 |
| [../cpm.md](../cpm.md) | The CPM engine: algorithm, TimeAxis, options, validation, open conventions | Sections 4, 6, 8, 10 |
| [../standards.md](../standards.md) | The four built-in standards, their differences and sources | Sections 1, 5, 8 |
| [../formulas.md](../formulas.md) | Every formula and the test that pins it | Sections 8, 10 |
| [../deploy.md](../deploy.md) | Step-by-step deployment on a NAS behind Tailscale Funnel | Section 7 |
| [../backlog.md](../backlog.md) | What is known to be wrong, unproven or missing | Section 11 |
| [../../CONTRIBUTING.md](../../CONTRIBUTING.md) | The non-negotiable rules and the verification gate | Sections 1, 2, 8 |
| [../../tests/test_architecture.py](../../tests/test_architecture.py) | The layer rules as an executable test (`LAYERS`) | Section 5 |

## Reading order

A newcomer reads 1, 3, 4 and 5, then [../architecture.md](../architecture.md). Someone changing the
CPM reads 8 (time model) and [../cpm.md](../cpm.md). Someone changing a check reads 5 (analysis),
6 (scenario c) and [../standards.md](../standards.md). An operator reads 7 and
[../deploy.md](../deploy.md). A reviewer of a dependency bump reads 7 (supply chain) and 11.

## Conventions used in this set

- Diagrams are Mermaid flowcharts and sequence diagrams. C4 levels are drawn as flowcharts with
  subgraphs (the Mermaid `C4Context` dialect is avoided for portability of rendering).
- Names in backticks are real identifiers from the code (`SnapshotStore`, `run_metric`,
  `TimeAxis`). A file path is relative to `src/xerscope/` unless it starts with `docs/`,
  `tests/`, `deploy/` or `.github/`.
- "Not determined from code" marks a statement the repository does not settle.
- Prose, code and diagram lines are kept at 120 characters or fewer. Markdown table rows cannot wrap,
  so a table row may be longer, as in the repository's existing docs (`docs/architecture.md`).
