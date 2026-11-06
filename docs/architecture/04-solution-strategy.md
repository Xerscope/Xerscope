# 4. Solution strategy

The decisions below shape every module. Each is detailed as an ADR in
[09-architecture-decisions.md](09-architecture-decisions.md); this section is the summary a reader
needs before the building blocks.

| Decision | Quality goal served | Short rationale | Evidence |
|---|---|---|---|
| **One-way data flow**: `.xer bytes → parser → RawXer → model → Snapshot → SnapshotStore → analyses → pages / CLI / Power BI`; no layer reaches back up | Modifiability, analysability | Each stage has one input type and one output type; a page composes results, it computes nothing | `docs/architecture.md` opening diagram; `tests/test_architecture.py` `LAYERS` |
| **Strings in the parser, types in the model**: `parse_text` keeps every value a `str` (`dtype=object`); `build_snapshot` converts, validates and derives | Resistance, functional correctness | The parser knows the format, not P6; a crafted file can only produce strings, and typing failures surface as `XerError` or NaN, not code paths | `xer/parser.py` module docstring; `xer/model.py` `to_datetime`, `to_number`, `_require` |
| **Checks as explicit functions, differences as TOML data**: each built-in check is one `@rule` function quoting its source; the TOML holds target, unit, parameters and source; custom standards reuse the parameterised rules of `rules.py` | Analysability, modifiability | P6's "Large Float" and DCMA-06 look alike but differ in unit and population; a branch per standard would hide that | `analysis/rules.py` docstring; `standards/p6.toml`, `dcma.toml`, `decm.toml`, `integrity.toml`, `custom-template.toml`; `docs/architecture.md` §5 |
| **Standards validated on load**: rule name, parameter names and types (`Rule.validate`), population keywords (`EXCLUSIONS`), target syntax (`parse_target`) | Functional correctness | A bad standard is refused before any check runs, in the CLI and in the app upload | `analysis/standards.py` `_parse_metric`, `parse_target`; `analysis/rules.py` `Rule.validate` |
| **Exact minutes with `TimeAxis`**: each calendar laid on an absolute minute axis with cumulative work; starts are period beginnings, finishes period ends; the axis grows on demand | Functional correctness | P6 reference files reproduce to the minute; no float drift from day fractions | `xer/calendar.py` `TimeAxis` docstring; `docs/cpm.md` "Time: TimeAxis" |
| **One CPM engine, cached on the snapshot**: `schedule(snapshot)` with no extra options stores its `Schedule` on the snapshot object (`_xs_schedule`); INT-01, INT-03, the critical path test and the Debug page share it | Performance efficiency | A 4,217-activity file schedules in about 2 s; the recalculation runs once per snapshot per process | `analysis/cpm.py` `schedule`, `compare_with_stored`; `docs/cpm.md` "Performance" |
| **Populations as a funnel of named, sourced steps**: `Funnel.exclude(key, source)` where `key ∈ EXCLUSIONS` and `source ∈ STEP_SOURCES`; the funnel travels in `RuleOutput` and `CheckResult` to the Audit page | Analysability | A reviewer sees each filter, the text it follows and the rows it removed | `analysis/populations.py` `Funnel`, `Step`, `EXCLUSIONS`, `STEP_SOURCES`; `app/sets.py` |
| **Per-session caches keyed on content, never process-wide**: `_parse` keyed on `sha256(bytes)`, `memo` keyed on `data_identity()` (files, projects, baseline, EV basis) + the analysis key; LRU of `MEMO_SIZE = 128` | Confidentiality, performance | When a session ends nothing of its files stays in the server; a corrected file of the same name is re-read | `app/state.py` `_parse`, `memo`, `data_identity` |
| **Independent oracles, strongest first**: P6 Professional's own output on a held-out corpus (`FLOORS` never lowered), real P6 exports to the minute, MPXJ as a second opinion with `P6_SETTLED` / `UNRESOLVED`, property tests on random networks | Functional correctness | "A number changes only with evidence"; a gain on one shape that costs another is not a fix | `verify/`, `tests/test_p6_heldout.py`, `tests/test_cpm.py`, `tests/test_crosscheck_mpxj.py`, `tests/test_cpm_properties.py` |
| **Distroless, non-root, read-only runtime; loopback-only publication**: `compose.yaml` publishes `127.0.0.1:8501` only; `deploy/` publishes nothing and reaches the world through userspace tailscaled | Confidentiality, resistance | The schedules are not on the network; no shell to escape into; capabilities dropped | `Dockerfile`, `compose.yaml`, `deploy/compose.yaml`, `tests/test_docker.py` |
| **Anonymisation by allowlist with leak check**: `KEEP` / `CODES` / `LABELS` / `MONEY` / `GUIDS`; HMAC-SHA256 codes under a session key; every output field compared with the originals' text before it is handed out (`LeakError`) | Confidentiality | Downloads are anonymised by default; a value that would still name the original is refused, not hoped away | `anonymize.py` module docstring, `Anonymizer.leaks` |
| **Layer rules as an executable test** | Modifiability | `LAYERS` is both the documentation and the check; a doc change without the test change fails | `tests/test_architecture.py`; `docs/architecture.md` "Layer rules" |

## Technology choices in one line each

- **pandas** frames for every table: long-format ("tidy") history frames make week-over-week
  analysis a `groupby`, and Plotly and Power BI read the same frames (`store.py` docstring).
- **Plotly** for charts, one y-axis per chart, theme colours from `viz/charts.py`.
- **Streamlit** for the app, with a custom Gantt component (`st.components.v2`, `viz/gantt.js`)
  that renders only the rows in view.
- **TOML** (`tomllib`, standard library) for standards; no YAML, no JSON schema dependency.
- **uv** for locking, installing and building the image's venv.
- **Caddy** rather than Streamlit for authentication, so the app code holds no credential logic.

## Approach to the hard problem: matching P6

The CPM docstring (`analysis/cpm.py`) states every rule the engine follows and names the corpus
activity it came from (`tests/test_p6_heldout.py`). Where the corpus and Oracle's text do not
settle a behaviour, `docs/cpm.md` "Conventions no reference file settles" and
`verify/mpxj_cpm.py` `UNRESOLVED` record the open question. The workflow in `CONTRIBUTING.md`
("Changing the CPM engine") is: reproduce on a reference file, change one rule, rerun P6 files,
corpus and MPXJ, raise the floors when identical shares go up, never lower them.
