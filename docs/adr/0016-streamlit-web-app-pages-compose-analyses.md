# ADR-0016: Streamlit web app: pages compose analyses and figures; the Gantt is a custom component that never parses schedule text as HTML

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 (`49ad764`, initial commit: a Streamlit multipage app declared with `st.navigation`); the Gantt became a component on 2026-11-02 (`db6ebbe`, #28) and a Streamlit components v2 component on 2026-11-03 (`04a73f1`, #60) |
| Scope | `src/xerscope/app/streamlit_app.py`, `app/views/*.py`, `app/ui.py`, `app/theme.py`, `app/state.py`, `app/session.py` (`debug_page`); `src/xerscope/viz/gantt.py`, `viz/gantt.js`, `viz/gantt.css`, `viz/charts.py` |
| Sources | `db6ebbe` "Gantt & WBS: tree grid and timeline drawn as one P6-style chart (#28)"; `00a0ed3` "Gantt & WBS: the page stays fast on large schedules (#30)"; `04a73f1` "UI/live theme (#60)"; `af57a08` "App: pages linked to each other, one update per session, background reading of the series, UI fixes (#125)"; [docs/architecture.md §6, §7](../architecture.md); [CONTRIBUTING.md](../../CONTRIBUTING.md) "Where a change goes" |

## Context

The users are planning engineers who read Primavera P6 exports. They expect P6-like views (an
Activities view with a WBS tree beside a Gantt, check results, earned value curves) and should
not have to install anything beyond Python and the package. Every number shown must trace to an
analysis, a population and a source (ADR-0010), so the user interface must not hold a second copy
of any calculation.

The Gantt is the hardest view. A real schedule has thousands of activities and hundreds of WBS
nodes; P6 lets the user fold and unfold WBS rows freely. A Plotly Gantt cannot fold a WBS row
and zooms on every drag; a Streamlit rerun per fold redraws the whole page. Activity and WBS
names come from the XER file, a file the user did not necessarily write: they must never be
parsed as HTML in the browser, and the code drawn in the browser must not reach the network.

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Plotly Gantt drawn by `viz/` and shown with `st.plotly_chart` (the Gantt until `db6ebbe`) | no custom front-end code | no WBS folding: exploring the WBS needed a table, a breadcrumb and a second chart; Plotly zoomed on every drag (`db6ebbe` message) |
| A self-built HTML page in an iframe (`st.iframe`, a page-level Content-Security-Policy `default-src 'none'`; from `db6ebbe` to `04a73f1`) | fold in the browser, network blocked by the CSP | page colours and font embedded per theme: the Gantt did not follow a theme switch without a rerun; relied on what the iframe permits (`04a73f1` message) |
| **A Streamlit components v2 component registered once in `app/ui.py`, fed data only, its script checked statically (chosen)** | `gantt.js` and `gantt.css` to maintain; the safety of the script rests on a static test, not on an iframe sandbox | the component is not sandboxed: the test on `gantt.js` is what keeps HTML parsing and network calls out |

The choice of Streamlit itself predates the repository's history (`49ad764`); an alternative web
framework is not recorded in history.

## Decision

**A Streamlit multipage app.** `app/streamlit_app.py` (`main`, run by `xerscope app`) declares
the pages with `st.navigation` in three groups:

| Group | Pages (title, file in `app/views/`) |
|---|---|
| Schedule | Overview (`overview.py`, the default page), Gantt & WBS (`gantt.py`) |
| Analysis | Schedule health (`health.py`), Audit (`audit.py`), Changelog (`changelog.py`), Delay analysis (`forensics.py`), Earned value (`earned_value.py`), Milestone trend (`milestones.py`), PPC & progress (`ppc.py`) |
| Data | Export for Power BI (`export.py`), Debug (`debug.py`) |

Then it applies the style (`theme.apply_style`), draws the sidebar loader
(`loading.sidebar_loader`) and the glossary (`ui.glossary`), and runs the page. The guard
`if __name__ == "__main__"` keeps the app out of the file-reading worker processes, which run the
file again as `__mp_main__` (ADR-0017).

**The Debug page** describes the server's reading of every file. It is in the navigation on a
workstation; on a locked deployment (`XERSCOPE_DATA_LOCKED`) only when `XERSCOPE_DEBUG_PAGE` is
`1`, `true` or `yes` (`session.debug_page`). `deploy/compose.yaml` passes
`XERSCOPE_DEBUG_PAGE: ${XERSCOPE_DEBUG_PAGE:-}`, off when unset.

**Pages compose; they do not calculate.** A page calls analyses (`analysis/`) and figure
builders (`viz/`) and lays out the result. The rule is CONTRIBUTING.md's "Where a change goes":
a chart goes in `viz/`, never in `app/views/`; a page goes in `app/views/<page>.py`, "composing
analyses and figures", never "a calculation". `viz/` imports only `config` and
`analysis.wbs.ROOT` (`LAYERS` in `tests/test_architecture.py`), so a figure builder cannot run an
analysis itself. No page imports another page and no app module imports a page.

**One look, in one place.** `app/ui.py` holds what every page shares: the KPI readout (`kpis`),
`table` (with column filters on long tables), `chart` and its "How to read" popover
(`reading_popover`), the one column-label dictionary `COLUMNS` (`task_code` shown as "Activity ID",
dates and units formatted the same everywhere), the status styles (`STATUS_STYLE`), the score
cards (`score_cards`) and the Gantt component (`GANTT`). `app/theme.py:apply_style` sends
`style.css` with the chart and status colours of `viz/charts.py` as CSS variables, and the font
fallback. The page header and its context banner are in `app/state.py` (`page_header`,
`context_banner`).

**One update for the session.** `state.snapshot_picker` writes the update picked on any page to
`st.session_state["snap_choice"]` (`session.SNAP_CHOICE`); every page's picker starts from it.
`state.go_to` and `state.open_in_gantt` write the session, then switch page (a check's tasks to
the Gantt, a table row to the Gantt, a check to the Audit).

**The Gantt component.** `viz/gantt.py` builds the rows in P6 order (`gantt_rows`: each WBS node,
its own activities, then its child nodes; bar colour from `categorise`: critical, near critical
within `Settings.near_critical_float_days`, normal, complete) and the data (`gantt_data`);
`gantt_assets` reads `gantt.js` and `gantt.css`. `app/ui.py` registers them once:
`GANTT = st.components.v2.component("xerscope_gantt", **gantt_assets())`, and
`app/views/gantt.py` mounts it with `ui.GANTT(data=gantt_data(...))`.

- WBS rows open and close in the browser without a rerun; a click on an activity row or bar sends
  its row id (`"a:<Activity ID>"`) and nothing else.
- Rows are virtualised: only the rows in view, plus `BUFFER = 30` above and below, exist in the
  DOM, and events are handled once per column, so a schedule of 15,000 activities scrolls like a
  small one (`gantt.js`; measured in `00a0ed3`: 53 rows in the page after Expand all of 17,501).
- A month or a week timescale (`WEEK_WINDOW`, `SPAN_PAD`), no zoom; row height `ROW_PX = 26`.
- Schedule text reaches the browser only as the component's data. `gantt.js` writes every text
  through one helper (`element`), which sets `node.textContent`; it holds no `innerHTML`,
  `eval`, `fetch`, `XMLHttpRequest`, `WebSocket`, `sendBeacon`, dynamic `import(` or
  `DOMParser`.
- Page colours and font come from the theme's `--st-*` variables (`gantt.css`), so the Gantt
  follows a theme switch without a rerun; bar colours come from the one palette of
  `viz/charts.py` (`PALETTE` in `viz/gantt.py`).

## Consequences

Positive:

- A planning engineer opens P6-like views with `uv run xerscope app`, on localhost, with
  nothing else to install.
- The UI layer holds no calculation: a number on a page is the number the analysis returns, and
  the tests of `analysis/` cover it.
- A hostile activity name stays data: it cannot run script in the page.
- Large schedules stay usable: folding costs no rerun, scrolling draws only the rows in view.

Negative:

- `gantt.js` and `gantt.css` are front-end code outside Python's tooling; their safety rests on
  the static checks of `tests/test_viz.py` and their behaviour on browser checks.
- Streamlit reruns the whole script on most interactions; fragments and the session memo
  (ADR-0017) are needed to keep pages fast.
- Two interactions cannot be driven by `AppTest` (the upload path and a WBS row selection,
  `on_select`); they are checked by hand before a release ([docs/backlog.md](../backlog.md),
  "App").

## Verification

- `tests/test_viz.py::test_gantt_keeps_schedule_text_out_of_the_markup` (a hostile name such as
  `</script><img ...>` travels as data, never in the markup, style or script),
  `::test_gantt_script_never_parses_text_as_html_nor_calls_out`,
  `::test_gantt_script_writes_every_text_through_one_function` (one `.textContent =`, no
  `innerText`, `createTextNode`, `insertAdjacentText`),
  `::test_gantt_rows_follow_the_wbs_tree_in_p6_order`, `::test_gantt_rows_scale_to_a_large_schedule`,
  `::test_gantt_timescales_and_links`, `::test_gantt_height_follows_the_rows_drawn_up_to_the_cap`.
- `tests/test_analysis_and_viz.py::test_gantt_page_colours_and_font_follow_the_theme_in_the_browser`.
- `tests/test_app.py::test_every_page_renders`, `::test_one_snapshot_renders_every_page`,
  `::test_gantt_payload_carries_the_row_size_the_height_cap_and_an_epoch_that_follows_the_filters`,
  `::test_debug_page_and_runtime_block_are_not_shown_on_a_locked_deployment`.
- `tests/test_page_golden.py::test_page_shows_what_the_golden_file_holds`: every page's elements
  frozen in `tests/golden/pages.json` (ADR-0011).
- `tests/test_architecture.py::test_layer_imports_match_the_architecture_doc` (what `viz` may
  import) and `::test_the_app_modules_import_one_way_and_the_pages_read_each_name_from_its_module`
  (no page imports another, `state.py` read by the pages only).
- `tests/test_docker.py::test_remote_debug_page_follows_the_env_file_and_is_off_by_default`.
- `tests/test_accessibility.py` (ADR-0030).

## References

- `src/xerscope/app/streamlit_app.py:main`; `src/xerscope/app/session.py:debug_page`, `SNAP_CHOICE`.
- `src/xerscope/app/ui.py`: `GANTT`, `kpis`, `table`, `chart`, `reading_popover`, `COLUMNS`,
  `STATUS_STYLE`, `score_cards`; `src/xerscope/app/theme.py:apply_style`.
- `src/xerscope/app/state.py`: `snapshot_picker`, `compare_picker`, `go_to`, `open_in_gantt`,
  `page_header`, `context_banner`.
- `src/xerscope/viz/gantt.py`: `categorise`, `gantt_rows`, `gantt_data`, `gantt_assets`,
  `ROW_PX`, `WEEK_WINDOW`; `src/xerscope/viz/gantt.js` (`element`, `BUFFER`); `src/xerscope/viz/gantt.css`.
- [docs/architecture.md](../architecture.md) §6 (`gantt.py`, `gantt.js`, `gantt.css`; `charts.py`),
  §7 (`streamlit_app.py`, `ui.py`, `theme.py`, `state.py`, Pages, Import edges).
- [CONTRIBUTING.md](../../CONTRIBUTING.md), "Where a change goes".
- Related: ADR-0001 (layers), ADR-0010 (traced numbers), ADR-0011 (golden pages), ADR-0017
  (background loading and memo), ADR-0020 (the Gantt's Ask field), ADR-0030 (accessible UI).
