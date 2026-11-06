# 9. Architecture decisions

Architecture Decision Records in MADR format. Every record is **reconstructed**: the repository
holds no ADR log, so context and consequences are read back from the code, its docstrings and the
docs. Each cites the file that evidences it. Dates are not determined from code (git history was
not used to date them).

---

## ADR-001: Keep every parsed value a string in the parser; type in the model

- **Status:** accepted (reconstructed)
- **Context:** XER files come from many P6 versions and encodings (UTF-8 with or without BOM,
  cp1252), may carry `\r` inside calendar blobs, short rows and broken rows. A crafted file must
  fail to load, not execute.
- **Decision:** `xer/parser.py` produces `RawXer(tables: {name: DataFrame[str]})` with
  `dtype=object`; it knows `ERMHDR`, `%T`, `%F`, `%R`, `%E` and nothing of P6. `xer/model.py`
  converts with `to_datetime` / `to_number` (`errors="coerce"`), maps enumerations and raises
  `XerError` on a missing required column.
- **Consequences:** the parser never changes when an analysis does; typing failures are NaN, not
  exceptions; the trust boundary is one module (section 8.5). Cost: a second pass over every
  table, and coerced values are not yet counted in the warnings (`docs/backlog.md`).
- **Evidence:** `xer/parser.py` module docstring; `xer/model.py` `_require`, `to_datetime`;
  `SECURITY.md`.

## ADR-002: Identity by `task_code`, never `task_id`

- **Status:** accepted (reconstructed)
- **Context:** `task_id` is a database key that changes when a project is re-imported; weekly
  exports must be joined across weeks.
- **Decision:** every frame, history, changelog, anonymiser mapping and Gantt row id uses
  `task_code`; `task_id` resolves relationships inside one file only and is excluded from
  `HISTORY_COLS`. A predecessor from another project of the file is named `[ext]{task_id}`.
- **Consequences:** week-over-week analysis is a `groupby`; a renumbered activity is a new one
  (mitigated by `baseline.renumbered` by GUID and `relinked`); a duplicate `task_code` in one file
  is a warning and `by_code` keeps the first.
- **Evidence:** `xer/model.py` docstring "Key decisions"; `store.py` `HISTORY_COLS` comment;
  `CONTRIBUTING.md`.

## ADR-003: Durations and floats stored in hours; `_d` columns in working days of the activity's calendar

- **Status:** accepted (reconstructed)
- **Context:** P6 stores hours; every standard threshold is in working days (DCMA 44 days) or
  hours (P6 "x" = 352 h). P6 converts with the Admin Preference hours per day, which the XER does
  not carry.
- **Decision:** keep P6's hours as stored (`*_hr`, `*_hr_cnt`); derive `_d` with the activity's
  `CALENDAR.day_hr_cnt` (`hours_to_days`); lags on the predecessor's calendar for `lag_d`.
- **Consequences:** no silent unit mixing; P6 and DCMA checks can state their unit in TOML
  (`unit`, `limit_hours` vs `limit_days`); the Admin Preference conversion remains an open item
  (`docs/backlog.md`, "Hours per day of the `_d` columns").
- **Evidence:** `xer/model.py` docstring; `xer/calendar.py` `hours_to_days`; `standards/p6.toml`
  `params = { limit_hours = 352 }`; `dcma/fourteen_point.py` `DCMA_HIGH_DAYS = 44`.

## ADR-004: Exact minute arithmetic with `TimeAxis`

- **Status:** accepted (reconstructed)
- **Context:** reproducing P6 dates to the minute across calendars with exceptions is impossible
  with day fractions; starts are period beginnings and finishes period ends in P6.
- **Decision:** each `WorkCalendar` gets a `TimeAxis`: working periods as minute offsets, cumulative
  work in an `int64` numpy array, `work(ts)` and its inverse `at(w, finish)`; the axis grows on
  demand and stays anchored on its first origin.
- **Consequences:** reference files reproduce to the minute; `Snapshot.work_hours` vectorises by
  calendar; cost: a half-minute rounds to even, so sub-minute lags can land on either side
  (`docs/backlog.md`).
- **Evidence:** `xer/calendar.py` `TimeAxis` docstring; `docs/cpm.md` "Time: TimeAxis";
  `tests/test_cpm.py`.

## ADR-005: One explicit function per built-in check; TOML holds target, unit, source; parameterised rules for custom

- **Status:** accepted (reconstructed)
- **Context:** P6's "Large Float" and DCMA-06 look alike but differ in unit and population; a
  single rule with `if standard == ...` branches would hide the difference from a reviewer.
- **Decision:** `analysis/p6/`, `dcma/`, `decm/` and `integrity.py` hold one `@rule` function per
  check whose docstring quotes its source; `standards/*.toml` holds `target`, `unit`, `params`,
  `source`. `rules.py` offers parameterised rules (`missing_logic`, `lag`, `float`, ...) that a
  custom TOML composes. Standards are validated on load (`Rule.validate`, `parse_target`,
  `EXCLUSIONS` keys).
- **Consequences:** a reviewer holds one function against one Oracle page; adding a company
  standard needs no Python; the price is some duplication between the explicit checks and the
  generic rules, mitigated by shared helpers (`share_of_type`, `late_output`, `bei_from_baseline`).
- **Evidence:** `analysis/rules.py` module docstring; `docs/architecture.md` §5 "Why explicit
  functions plus TOML"; `analysis/standards.py`.

## ADR-006: Populations as a `Funnel` of named, sourced steps

- **Status:** accepted (reconstructed)
- **Context:** the project's value is that every number is traceable to a population and a
  source; a count without the rows behind it cannot be audited against a P6 report.
- **Decision:** `populations.Funnel.exclude(key, source)` with `key ∈ EXCLUSIONS` and
  `source ∈ STEP_SOURCES` (unknown source raises); the funnel travels in `RuleOutput` and
  `CheckResult`; `audit.split` cuts counted / checked / excluded sets from them without recomputing.
- **Consequences:** the Audit page shows each filter, the text it follows and the rows it removed;
  `sets_long` exports them; rules must build populations through the funnel to be auditable.
- **Evidence:** `analysis/populations.py`; `analysis/audit.py`; `app/sets.py`.

## ADR-007: Explanations generated from rule docstrings and effective parameters

- **Status:** accepted (reconstructed)
- **Context:** page text about a check drifts from the code; the explanation must be the code's own.
- **Decision:** a docstring convention (title, `Counts: a / b`, `Excludes:` lines, method text) read
  by `rules.read_docstring`; `explain.explain(result)` builds `Explanation` (formula with the
  actual numbers, verdict against the target, population lines, parameters with origin
  "standard" or "default", method).
- **Consequences:** one source of truth for what a check does; `tests/test_explain.py` checks
  explanations match results; the docstring shape is now an API.
- **Evidence:** `analysis/rules.py` docstring "Docstring convention"; `analysis/explain.py`.

## ADR-008: One CPM engine, cached on the snapshot object

- **Status:** accepted (reconstructed)
- **Context:** INT-01, INT-03, the critical path test, the Debug page and the weekly history all
  need the plain recalculation; a 4,217-activity file takes about 2 s.
- **Decision:** `cpm.schedule(snapshot)` without extra options stores its `Schedule` as
  `snapshot._xs_schedule` via `object.__setattr__`; `compare_with_stored` caches `_xs_comparison`
  and returns copies. `_Run` keeps state in plain dicts (10x faster than frame lookups).
- **Consequences:** one run per snapshot per process; the cache is invisible to the dataclass
  (not a declared field); a snapshot must be treated as immutable after scheduling.
- **Evidence:** `analysis/cpm.py` `schedule`, `compare_with_stored`, `_Run` docstring;
  `docs/cpm.md` "Performance".

## ADR-009: Per-session caches keyed on content; no process-wide cache of file data

- **Status:** accepted (reconstructed)
- **Context:** Streamlit reruns a page on every interaction; a process-wide cache would keep one
  user's schedules alive for another session on the same server.
- **Decision:** `_parse` keyed on `sha256(bytes)` in `st.session_state`; `memo` keyed on
  `data_identity()` (files, projects, baseline, EV basis) plus the analysis key, LRU of 128; no
  `st.cache_data` for file content.
- **Consequences:** a corrected file of the same name is re-read; results of two baselines
  coexist; a session's data disappears with it; the baseline file is re-hashed on each rerun
  (noticeable above ~50 MB, `docs/backlog.md`).
- **Evidence:** `app/state.py` `_parse`, `memo`, `data_identity`, `MEMO_SIZE`.

## ADR-010: Strongest oracle first; floors that never drop; open questions written down

- **Status:** accepted (reconstructed)
- **Context:** no P6 licence in CI; P6 Professional's behaviour is the only acceptable truth.
- **Decision:** `verify/p6_corpus.py` scores the engine against P6 23.12.1's output on a public
  held-out corpus with `FLOORS` per set that may only rise; real P6 exports are reproduced to the
  minute in `tests/test_cpm.py`; MPXJ is a second opinion with `P6_SETTLED` and `UNRESOLVED`;
  property tests cover shapes no oracle has. `XERSCOPE_REQUIRE` turns a skip into a failure in CI.
- **Consequences:** "a gain on one shape that costs another is not a fix"; the corpus is synthetic
  and scheduled by 23.12, so shapes it never draws are untested (`docs/backlog.md`).
- **Evidence:** `tests/test_p6_heldout.py`, `verify/mpxj_cpm.py`, `tests/conftest.py`,
  `.github/workflows/tests.yml`.

## ADR-011: Distroless, non-root, read-only image; loopback-only or no publication

- **Status:** accepted (reconstructed)
- **Context:** the image may be pulled onto a NAS by a Container Manager with no terminal; the
  schedules must not be on the network.
- **Decision:** uv build stage → `gcr.io/distroless/cc-debian13:nonroot`, both bases pinned by
  digest, pip removed, `USER nonroot`; `compose.yaml` publishes `127.0.0.1:8501` only; `deploy/`
  publishes nothing and runs tailscaled in userspace with Caddy in its namespace; all containers
  `read_only`, `cap_drop ALL`, bounded memory and PIDs.
- **Consequences:** no shell in the image (health check is Python); any CLI runs through the
  entrypoint; `/data` must be created at build time; `tests/test_docker.py` pins the properties.
- **Evidence:** `Dockerfile`, `compose.yaml`, `deploy/compose.yaml`, `tests/test_docker.py`.

## ADR-012: Authentication and rate limiting in Caddy, not in the app

- **Status:** accepted (reconstructed)
- **Context:** Streamlit has no built-in authentication; Funnel exposes a public HTTPS name that
  scanners find within seconds from certificate logs.
- **Decision:** Caddy (custom image with `caddy-ratelimit`) does `basic_auth` with a bcrypt hash
  (cost 10, chosen for the NAS's CPU), a secret path prefix with 404 elsewhere before auth, a per-IP
  rate limit before the bcrypt run, security headers and redacted logs. The app receives plain
  requests at `/`.
- **Consequences:** no credential logic in Python; one shared login (listed as debt); the custom
  Caddy image must be built and published by CI since the NAS cannot build.
- **Evidence:** `deploy/Caddyfile`, `deploy/caddy/Dockerfile`, `docs/deploy.md` §3.

## ADR-013: Anonymisation by allowlist with an explicit leak check

- **Status:** accepted (reconstructed)
- **Context:** users need to share results and sometimes files without the project's names and
  codes; a denylist misses unknown columns.
- **Decision:** `anonymize.py` keeps only `KEEP` columns, renames `CODES` with HMAC-SHA256 under a
  session key, rebuilds `LABELS`, zeroes `MONEY`, replaces `GUIDS`, empties every other column and
  drops every other table (both reported by name); before handing anything out, every field is
  searched for every unkept original text and file name (`LeakError`). The app anonymises downloads
  by default.
- **Consequences:** P6 and xerscope compute the same results on the copy
  (`tests/test_anonymize.py`); a new XER column is emptied until it is allowlisted; the key lives in
  the session only.
- **Evidence:** `anonymize.py` module docstring; `app/state.py` `anonymous_exports`.

## ADR-014: Layer rules as an executable test

- **Status:** accepted (reconstructed)
- **Context:** a one-way data flow decays unless checked; a doc alone is not enforced.
- **Decision:** `tests/test_architecture.py` parses every import in `src/xerscope` with `ast` and
  asserts that each layer's cross-layer imports equal `LAYERS[layer]` exactly, and that only `cli`
  imports `app`.
- **Consequences:** adding a dependency means editing the test and `docs/architecture.md` together;
  narrow exceptions are spelled as dotted names (`analysis.wbs.ROOT`, `app.diagnostic`).
- **Evidence:** `tests/test_architecture.py`; `docs/architecture.md` "Layer rules".
