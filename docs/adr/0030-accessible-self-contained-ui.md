# ADR-0030: Accessible, self-contained UI: WCAG 2.2 AA checked in a browser, self-hosted fonts, status colours reserved

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-03 (`67d9a98`, #51: fonts served from `app/static/`, SIL OFL licences beside them); Onest and JetBrains Mono with the warm theme from 2026-11-05 (`0844f9a`, #109); the axe-core check of the rendered pages from 2026-11-13 (`0f57291`, #214); the field outline at 3:1 from 2026-11-19 (`7a05c8c`). The single colour set in `viz/charts.py` dates from 2026-10-29 (`49ad764`) and was reworked since |
| Scope | `scripts/accessibility.py`, `.github/workflows/accessibility.yml`, `pyproject.toml` (`[dependency-groups] accessibility`), `src/xerscope/app/static/`, `src/xerscope/app/.streamlit/config.toml`, `src/xerscope/app/theme.py`, `src/xerscope/app/style.css`, `src/xerscope/viz/charts.py` (`SERIES`, `STATUS`, `NEUTRAL`, `ACCENT`), `src/xerscope/viz/gantt.css`, `src/xerscope/app/ui.py` (`STATUS_STYLE`); `tests/test_accessibility.py`, `tests/test_analysis_and_viz.py` |
| Sources | WCAG 2.2: SC 1.4.3 (contrast, 4.5:1 for text), SC 1.4.11 (non-text contrast, 3:1), SC 2.1.1 (keyboard); axe-core 4.14.0; `67d9a98` "UI/fonts hud (#51)"; `0844f9a` "App: warm theme with a petrol accent, Onest, KPIs as a readout (#109)"; `0f57291` "Weekly accessibility check of the rendered pages with axe-core (#214)"; `7a05c8c` "Fields: the outline at rest reaches 3:1 on every background"; [docs/architecture.md](../architecture.md) §6 (`charts.py`), §7 (`static/`, `style.css`, `.streamlit/config.toml`); [CONTRIBUTING.md](../../CONTRIBUTING.md) (the `accessibility` group and script) |

## Context

The app shows schedules to planners on a desktop and, through the remote deployment (ADR-0025),
on a phone; Streamlit lets each viewer switch between a light and a dark theme. Its pages are
read for status: red, amber and green mean fail, error (a check that could not run) and pass on
the check pages (Schedule health, Audit).

Unit tests of colour constants do not see the page as a browser renders it: in November 2026 a
run of axe-core by hand on the demo series found three defects of the app's own (captions at
Streamlit's 60 % opacity reaching 4.43:1 on the light sidebar for the 4.5:1 of SC 1.4.3; a
text-only button under the pointer at 3.4 to 3.6:1 in the dark theme; the box scrolling the
Gantt rows unreachable from the keyboard, SC 2.1.1), and nothing would have rerun it
(`0f57291`). A field at rest was outlined with the theme's `borderColor`, 1.18:1 to 1.41:1 on the
app's surfaces (`7a05c8c`).

A font loaded from a font host is a request from every viewer's browser to a third party, and
fails where the network is closed; the app otherwise sends nothing out (ADR-0024).

## Options considered

| Option | Cost | Limit |
|---|---|---|
| Contrast checked by unit tests of the colour constants only | none beyond the tests | misses what Streamlit's own CSS does to the page (opacity, hover colours, focus), and the markup (names, keyboard) |
| axe-core in every pull request's CI | a browser in the test jobs | installs a browser and takes minutes on each pull request; every job of `tests.yml` gates the publish (ADR-0027) |
| **axe-core on the rendered pages weekly and by hand, beside unit tests of every colour pair (chosen)** | a separate workflow, a pinned axe-core, a list of Streamlit's own findings to keep current | a regression is seen up to a week after its merge; what axe-core cannot decide is not seen |
| Fonts from a font host (Google Fonts) | none | a third-party request per viewer; no font on a closed network |
| **Fonts in the package, served by the app (chosen)** | about 74 KB of woff2 with their licences | latin subset only |

## Decision

**WCAG 2.2 A and AA, checked in a browser.** `scripts/accessibility.py` generates the demo series
(8 weeks) in a temporary folder, starts `xerscope app` on it on a free local port
(`XERSCOPE_SYNC_LOAD=1`), opens it in headless Chromium (playwright) and runs axe-core with the
tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa` (`TAGS`) on:

- the files window, and the sidebar's Files line under the pointer once the files are read;
- each URL path of `PAGES`, reached through the sidebar's navigation link, at a desktop
  (1440 × 900) and a phone (390 × 844) width (`WIDTHS`). `PAGES` holds 11 paths: `""`
  (Overview), `gantt`, `activity`, `health`, `audit`, `changelog`, `earned_value`, `milestones`,
  `ppc`, `export`, `debug`;
- all of it in the light and the dark theme (`THEMES`): 2 × (2 + 11 × 2) = 48 states when every
  path has a link.

`PAGES` was written with the script (`0f57291`, 2026-11-13). The app's navigation
(`streamlit_app.py`) no longer matches it: the Activity page was removed on 2026-11-21
(`e51f2dd`), so no link ends in `/activity`, and the Delay analysis page added on 2026-11-19
(`c870926`, `views/forensics.py`, path `forensics`) is not in the list (Consequences).

A finding is a rule and the element it names; `KNOWN` lists, by rule and the `data-testid` of the
element or an ancestor, the findings that are Streamlit's own markup (three entries: the `list`
and `listitem` rules on `stSidebarNavItems`, the `target-size` of the clear button in
`stMultiSelect`). The run fails on any finding `KNOWN` does not cover, on a `KNOWN` entry no
state shows any more (the list must not outlive its reason), and when axe-core does not report a
button without a name planted in the page (a run that sees nothing proves nothing). axe-core is no
dependency of the repository: the script reads `axe.min.js` from where npm put it and refuses it
unless its SHA-256 is `AXE_SHA256`, the 4.14.0 build (4.12.1 does not report the 4.43:1 caption
contrast). Not seen: what axe-core cannot decide (text over an overlay), the table cells (drawn on
a canvas), the text inside the charts, and states behind a click other than the files window.

**When it runs.** `.github/workflows/accessibility.yml`: every Monday (06:23 UTC) and by hand,
never on a pull request or a push, outside `tests.yml`, with a 20-minute timeout. It runs
`uv sync --locked --group accessibility` (`playwright==1.64.1`, an exact version because the
Chromium build installed comes with it, in its own group so the test jobs do not install it),
`playwright install --with-deps chromium`, `npm install --no-save --ignore-scripts
axe-core@4.14.0`, then the script, whose Markdown summary goes to the job summary.

**Colour pairs, tested without a browser.** `.streamlit/config.toml` sets both themes; its text,
link and table-header colours reach 4.5:1 on both backgrounds of each theme, captions are set to
65 % opacity in `style.css` (4.5:1 on every surface), a field's outline at rest is the text
colour at `--xs-field` (50 % light, 40 % dark: at least 3:1 on every background), a text button
under the pointer takes the accent, and the Gantt's row box takes the keyboard focus
(`gantt.js`).

**One set of chart and status colours for both themes.** `viz/charts.py` holds `SERIES` (six
categorical colours: azure, copper, teal, brass, orchid, violet, in a fixed order), `STATUS`
(`critical`, `warning`, `good`, `complete`, `info`, `muted`) and `NEUTRAL` (reference lines: data
date, reporting line, index 1.0). Every one of them except `info` (a label background only)
reaches 3:1 (SC 1.4.11) on the background and secondary background of both themes, so no chart
is redrawn on a theme switch. The `SERIES` order was checked with a palette validator on a light
and a dark surface: adjacent pairs at least 8 CVD delta E (worst 12.6) and 15 normal-vision delta
E (worst 16.0). Red, amber and green belong to `STATUS` and mean a status only (the check
statuses of `app/ui.py`'s `STATUS_STYLE` are white text on a `STATUS` colour, 4.5:1); `SERIES`
keeps clear of those hues. `ACCENT` is the one colour set per theme (the theme's `linkColor`,
through CSS `light-dark()`, `theme.apply_style`). Text, grid and axes are left to Streamlit's
Plotly theme, and the Gantt reads the theme's `--st-*` variables (`gantt.css`).

**Fonts served by the app.** `app/static/` holds Onest and JetBrains Mono as variable woff2 files
(weight axis, latin subset) with their SIL OFL 1.1 licences (`OFL-Onest.txt`,
`OFL-JetBrainsMono.txt`). `config.toml` sets `enableStaticServing = true` (it serves that folder
at `app/static/` and nothing else) and declares both as `[[theme.fontFaces]]`; the same body
family is set on the Plotly charts. When Streamlit did not read the config (`theme.theme_loaded()`
false), `theme.font_fallback_css()` inlines both files as `data:` URLs from `FONT_FILES`, since
the static folder is then not served. No request leaves for a font host.

## Consequences

Positive:

- Contrast, names and keyboard access are checked on the pages as rendered, in both themes and at
  phone width, and a run that cannot see a planted defect fails instead of passing.
- A theme switch changes no chart; a red or green mark always means a status.
- The app renders its own faces offline and sends no viewer's address to a font host.

Negative:

- A regression on a page is reported up to a week after its merge, not on its pull request.
- `KNOWN` tracks Streamlit's markup: a Streamlit upgrade that changes it turns the run red until
  the list is updated.
- A new colour must hold 3:1 on four backgrounds; the categorical palette stops at six series.
- The latin subset leaves other scripts to the fallback family.
- `PAGES` is a list kept by hand and no test compares it with the navigation: it still names
  `activity` and lacks `forensics` (Decision). Follow-up: align it with the pages of
  `streamlit_app.py` (or derive it from them) and rerun the workflow.

## Verification

- `tests/test_accessibility.py`: `::test_known_findings_alone_pass`,
  `::test_a_known_entry_covers_the_element_under_it_too`,
  `::test_a_known_rule_elsewhere_is_a_new_finding`,
  `::test_another_rule_in_a_known_place_is_a_new_finding`,
  `::test_a_known_entry_no_page_shows_is_reported`,
  `::test_summary_counts_the_known_findings_and_lists_the_others`, `::test_exit_code`,
  `::test_the_accessibility_job_runs_weekly_or_by_hand_with_its_own_dependencies`.
- `tests/test_analysis_and_viz.py::test_marks_reach_3_to_1_on_both_themes`,
  `::test_text_colours_reach_wcag_aa_on_both_backgrounds`,
  `::test_captions_reach_wcag_aa_on_every_background`,
  `::test_the_outline_of_a_field_reaches_3_to_1_on_every_background`,
  `::test_a_text_button_under_the_pointer_takes_the_accent_not_the_primary_colour`,
  `::test_gantt_rows_scroll_from_the_keyboard`,
  `::test_accent_is_the_link_colour_of_each_theme_and_primary_carries_white_text`,
  `::test_gantt_page_colours_and_font_follow_the_theme_in_the_browser`,
  `::test_fonts_are_served_by_the_app_and_used_everywhere` (every font face is a file of
  `app/static/` with its licence, `enableStaticServing` on, the same family on the charts).
- `tests/test_app.py::test_font_fallback_inlines_both_faces`.
- The weekly `accessibility` workflow run and its job summary.

## References

- `scripts/accessibility.py`: `AXE_SHA256`, `TAGS`, `PAGES`, `THEMES`, `WIDTHS`, `KNOWN`, `judge`,
  `measure`, `demo_app`, `main`.
- `.github/workflows/accessibility.yml`; `pyproject.toml` `[dependency-groups]` `accessibility`.
- `src/xerscope/app/.streamlit/config.toml` (`[server] enableStaticServing`, `[theme]`,
  `[[theme.fontFaces]]`); `src/xerscope/app/static/`; `src/xerscope/app/theme.py`
  (`FONT_FILES`, `theme_loaded`, `font_fallback_css`, `apply_style`); `src/xerscope/app/style.css`
  (`--xs-field`, captions).
- `src/xerscope/viz/charts.py` (`SERIES`, `STATUS`, `NEUTRAL`, `ACCENT`, `TEXT`);
  `src/xerscope/viz/gantt.css`; `src/xerscope/app/ui.py` (`STATUS_STYLE`).
- [docs/architecture.md](../architecture.md) §6 (`charts.py`), §7 (`.streamlit/config.toml`,
  `static/`, `style.css`); [CONTRIBUTING.md](../../CONTRIBUTING.md) (`uv sync --locked --group
  accessibility`, the `accessibility` workflow).
- Related: ADR-0016 (the Streamlit app and the Gantt component), ADR-0024 (nothing leaves the
  machine), ADR-0026 (exact versions), ADR-0027 (what gates the publish).
