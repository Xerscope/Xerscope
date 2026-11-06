# 2. Architecture constraints

Constraints are the givens the architecture must work within. Each line names the file that
evidences it.

## 2.1 Technical constraints

| Constraint | Evidence | Consequence |
|---|---|---|
| Python ≥ 3.11 (`requires-python`); CI runs 3.11, 3.13 and 3.14; the image runs a uv-managed CPython 3.14 | `pyproject.toml`, `.github/workflows/tests.yml`, `Dockerfile` (`ARG PYTHON_VERSION=3.14`) | `tomllib` from the standard library; `X \| Y` unions; no dependency that lags behind 3.14 |
| Dependencies locked with `uv.lock`; `uv sync --locked` everywhere (dev, CI, image); version floors in `pyproject.toml` set to the last audited releases | `pyproject.toml` comments, `Dockerfile` (two `uv sync --locked --no-dev`), `tests/test_docker.py` | Builds are reproducible; an install that ignores the lock still cannot pull an older vulnerable version |
| Four runtime dependencies only: pandas, plotly, pyarrow, streamlit; MPXJ + JPype as an optional extra needing a JDK | `pyproject.toml` (`dependencies`, `optional-dependencies.crosscheck`) | "No new dependency without a reason stated in the PR" (`CONTRIBUTING.md` rule 4) |
| Input format: the P6 XER tab-separated text export (`ERMHDR`, `%T`, `%F`, `%R`, `%E`), UTF-8 or cp1252 | `xer/parser.py` (`ENCODINGS`) | No database access, no XML/P6 API; everything P6 knows must be in the file |
| Runtime image is distroless (`gcr.io/distroless/cc-debian13:nonroot`): no shell, no package manager, non-root | `Dockerfile` | Health check is a Python one-liner; `/data` is created at build time; any CLI command runs through the entrypoint |
| The remote stack must run on a NAS Container Manager that cannot build images or log in to ghcr.io | `deploy/compose.yaml` header, `docs/deploy.md` §1, §8 | Images are pulled, never built there; the Caddy image with `rate_limit` is prebuilt by `image.yml` |
| Streamlit's execution model: a page script reruns top to bottom on each interaction; state lives in `st.session_state` | `app/state.py` (`memo`, `_parse`), `app/streamlit_app.py` | Per-session caches keyed on file digests; nothing process-wide so one session's files never leak to another |
| Oracle's documentation and P6 Professional's output are the reference, not a specification the project owns | `analysis/cpm.py` docstring, `standards/p6.toml` header, `docs/cpm.md` "Conventions no reference file settles" | Behaviour the docs do not settle is recorded as an open question (`verify/mpxj_cpm.py` `UNRESOLVED`) |

## 2.2 Organisational constraints

| Constraint | Evidence | Consequence |
|---|---|---|
| Licence Apache-2.0, with `LICENSE` and `NOTICE` shipped in the wheel | `pyproject.toml` (`license`, `license-files`) | Third-party reference files (LGPL MPXJ, AGPL xerlock) are downloaded at test time, never vendored (`tests/reference/sources.py`) |
| **No real schedule enters the repository**: no real `.xer`, activity name, project code, company name or file path in code, docs, tests, issues or commit messages | `CONTRIBUTING.md` rule 1; CI step "No schedule or data export is tracked" (`tests.yml`, `lint` job) | Tests build files with `tests/xerkit.py`; the witness test (`tests/test_p6_witness.py`) reads a local, uncommitted folder and skips in CI |
| **A number changes only with evidence**: a test that fails before and passes after, plus a P6 export, the held-out corpus, MPXJ or a hand calculation | `CONTRIBUTING.md` rule 3; `tests/test_p6_heldout.py` `FLOORS` ("never lower them"); `tests/test_characterization.py` golden file | Refactors must leave `golden/standards.json` unchanged; an intended change rewrites it in a run that fails by design |
| Commits and pull requests carry their author's identity and project context only; a tool identity or attribution trailer fails the `attribution` workflow | `.github/workflows/attribution.yml`, `CONTRIBUTING.md` | Commit text states problem, change, verification; the workflow greps for tool identities |
| CI minutes are scarce on a private repository: Linux + two Pythons on PRs, full matrix (Windows included) on Mondays and by hand | `tests.yml` header | The container and deploy jobs do not run on pull requests |
| Dependabot proposes weekly updates for uv, GitHub Actions, the Dockerfile `FROM` lines, the compose images and the Caddy builder tags | `.github/dependabot.yml` | Human review of each bump; `@dependabot rebase` before merge (`CONTRIBUTING.md`) |

## 2.3 Conventions

| Convention | Evidence | Why it matters |
|---|---|---|
| **Identity is `task_code`** (Activity ID), never `task_id` (a database key that changes on re-import) | `xer/model.py` docstring; `store.py` `HISTORY_COLS` | Week-over-week joins, history, changelog and anonymisation all key on `task_code` |
| **Hours vs days**: durations, floats and lags are stored in hours (`*_hr`, `*_hr_cnt`); `_d` columns are working days of the activity's own calendar (`CALENDAR.day_hr_cnt`); lags convert on the calendar the scheduling options designate | `xer/model.py`, `xer/calendar.py` `hours_to_days`, `CONTRIBUTING.md` | "Mixing hours and days, or calendar days and working days, is the most common source of a wrong number" |
| **Oracle as source**: P6 semantics come from the P6 Professional 24 documentation; checks from the P6 Check Schedule help, DECM v8.0 or DCMA 14-Point; each rule names its source | `standards/*.toml` `source` fields; rule docstrings; `populations.STEP_SOURCES` | A reviewer can hold a function against the page it cites |
| Dates are ISO `YYYY-MM-DD HH:MM` (`DATETIME_FMT`), P6's own XER format; a date parsed without a format is an error in tests | `config.py`; `pyproject.toml` `filterwarnings` ("Could not infer format" → error) | No locale guessing |
| One function per rule, one place per P6 concept, no `if standard == ...` branch | `CONTRIBUTING.md` "Where a change goes" table; `analysis/rules.py` docstring | Differences between standards are TOML parameters |
| Layer rules are a test: `LAYERS` in `tests/test_architecture.py` lists exactly what each layer may import | `tests/test_architecture.py` | A new cross-layer import fails CI unless the rule (and `docs/architecture.md`) are changed with it |
| Rule docstrings have a fixed shape (title, `Counts:`, `Excludes:` lines, then method text) that `explain.py` reads | `analysis/rules.py` module docstring | The explanation shown to the user is generated from the same text a reviewer reads |
| Ruff: line length 120, target py311, rule sets E/F/W/B/I/UP/SIM/C4/PIE/RET/PLE/PLW; `ruff format --check` in CI | `pyproject.toml` `[tool.ruff]`, `tests.yml` `lint` job | Formatting and import order are not reviewed by hand |
| Placeholders only in examples: `<login>`, `<random>`, `<tailnet>`; no real hostname, path prefix, username or token | `deploy/.env.example`, `docs/deploy.md`, `CONTRIBUTING.md` | The deploy files are safe to publish; `tests/test_docker.py` asserts no key or hash is written in them |
| Red, amber and green are reserved for status and never decorate; one palette for light and dark themes | `app/.streamlit/config.toml`, `viz/charts.py` (`STATUS`, `SERIES`, `ACCENT`) | Charts and Gantt bars read the same way as the check status labels |
