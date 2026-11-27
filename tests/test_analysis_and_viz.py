"""Standards on the demo series: each deliberate finding of the generator must be found.

sample.py documents what it plants; these tests check the analysis finds exactly that,
independently of how the rules are written.
"""

import re
import tomllib
from pathlib import Path

import pandas as pd
import pytest
from rulekit import STANDARDS, codes, run_on_store

import xerscope
from xerscope.analysis import Baseline, health_history
from xerscope.analysis.activity_trail import logic_by_update
from xerscope.analysis.wbs import rollup
from xerscope.app import ui
from xerscope.viz import categorise, gantt_assets, gantt_data, gantt_rows
from xerscope.viz.charts import (
    ACCENT,
    FONT_FAMILY,
    NEUTRAL,
    SERIES,
    STATUS,
    TEXT,
    build_activity_dates,
    build_activity_float,
    build_activity_history,
)
from xerscope.viz.gantt import ACTIVITIES_COLUMNS


def test_planted_lead_open_end_and_missing_resources(store):
    assert run_on_store(store, 0, "DCMA-02").numerator == 1  # E1040 -> E1050 is FS -3 d
    assert "K5040" in codes(run_on_store(store, 0, "DCMA-01"))  # no successor
    assert codes(run_on_store(store, 0, "P6-11")) == ["E1050", "K5040"]


def test_planted_constraints(store):
    # X4050 is a finish milestone with finish-on-or-before: hard for DCMA, but PAM 200.1 4.0
    # excludes milestones from the analysis, so DCMA-05 no longer flags it (P6-03 below still does).
    assert codes(run_on_store(store, 0, "DCMA-05")) == []
    assert codes(run_on_store(store, 0, "P6-02")) == []  # P6: only mandatory dates are hard
    assert codes(run_on_store(store, 0, "P6-03")) == ["P2040", "X4050"]


def test_planted_high_duration(store):
    assert "P2030" in codes(run_on_store(store, 0, "DCMA-08"))  # 60 days


def test_negative_float_appears_after_vendor_delay(store):
    before = run_on_store(store, 4, "DCMA-07")
    after = run_on_store(store, 5, "DCMA-07")
    assert before.numerator == 0 and after.numerator > 0 and after.status == "fail"


def test_invalid_actual_date_from_week_6(store):
    assert codes(run_on_store(store, 5, "P6-10b")) == []
    assert codes(run_on_store(store, 6, "P6-10b")) == ["C3010"]


def test_baseline_execution(store):
    first = run_on_store(store, 0, "DCMA-14")
    assert first.status == "n/a"  # nothing due at the baseline date
    late = run_on_store(store, len(store) - 1, "DCMA-14")
    assert 0 < late.value < 1  # the slow activities finish after their baseline


def test_health_history_is_long_format(store):
    h = health_history(store, STANDARDS["DCMA"], Baseline.from_snapshot(store.first))
    assert len(h) == 14 * len(store)  # DCMA 14-Point
    neg = h[h["id"] == "DCMA-07"].set_index("snapshot_idx")["found"]
    assert neg[4] == 0 and neg[5] > 0


def test_gantt_rows_on_the_demo_series(store):
    s = store.latest
    tasks = s.activities.assign(category=categorise(s.activities))
    rows = gantt_rows(tasks, rollup(s), compare=store.first.activities, snapshot=s)
    drawn = [r["code"] for r in rows if r["kind"] == "task"]
    assert sorted(drawn) == sorted(s.activities["task_code"])  # every activity once
    assert rows[0]["id"] == "w:__project__" and rows[0]["depth"] == 0
    assert {r["category"] for r in rows if r["kind"] == "task"} >= {"Critical", "Complete"}
    data = gantt_data(rows, relationships=s.relationships, data_date=s.data_date, links=True)
    assert "Critical" in data["palette"] and data["links"]


@pytest.mark.oracle("property")
def test_gantt_task_rows_carry_p6_durations_and_the_grid_options(store):
    """An activity row carries P6's original and remaining duration in working days (TASK
    target_drtn_hr_cnt, remain_drtn_hr_cnt over the calendar's hours per day: xer.model), to one
    decimal; a WBS row has none. The defaults draw the Gantt page's grid: % complete and float, the
    timeline, no level bands."""
    s = store.latest
    tasks = s.activities.assign(category=categorise(s.activities))
    rows = gantt_rows(tasks, rollup(s))
    by_code = s.by_code
    for row in (r for r in rows if r["kind"] == "task"):
        assert row["original_d"] == round(float(by_code.loc[row["code"], "original_d"]), 1)
        assert row["remaining_d"] == round(float(by_code.loc[row["code"], "remaining_d"]), 1)
    assert all("original_d" not in r for r in rows if r["kind"] == "wbs")
    data = gantt_data(rows)
    assert [column["key"] for column in data["columns"]] == ["pct", "float_d"]
    assert (data["timeline"], data["levelBands"]) == (True, False)
    tasks_page = gantt_data(rows, columns=ACTIVITIES_COLUMNS, timeline=False, level_bands=True)
    assert [column["label"] for column in tasks_page["columns"]][:2] == ["Original (wd)", "Remaining (wd)"]


def test_gantt_compare_with_no_common_tasks(store):
    """Comparison sharing no task code (another project): no outline, no shift, rows still build."""
    s = store.latest
    other = store.first.activities.assign(task_code=lambda f: "ZZ-" + f["task_code"].astype(str))
    tasks = s.activities.assign(category=categorise(s.activities))
    rows = gantt_rows(tasks, rollup(s), compare=other, snapshot=s)
    assert all(r["cmp_finish"] is None and r["shift_wd"] is None for r in rows if r["kind"] == "task")


def test_activity_charts_follow_the_history(store):
    """The float chart draws the task alone, one point per update holding it; each point's hover lists
    that update's predecessors and successors. A neighbour picked is drawn too, named with its role."""
    code = "C3020"  # demo: predecessors C3010, E1020; successors C3030, C3040
    history = store.history
    history = history[history["task_code"] == code].sort_values("data_date")
    dates = build_activity_dates(history)
    logic = logic_by_update(store, code)
    float_chart = build_activity_float(logic)
    assert [trace.name for trace in dates.data] == ["Start", "Finish"]
    assert [trace.name for trace in float_chart.data] == ["C3020 · task"]
    assert len(float_chart.data[0].x) == len(history)
    first_hover = float_chart.data[0].customdata[0][2]
    predecessors, successors = first_hover.split("<b>Successors</b>")
    assert "<b>Predecessors</b>" in predecessors and "E1020 FS driving · TF 20.0 wd" in predecessors
    assert "C3040 SS driving · TF 85.0 wd" in successors
    assert float_chart.layout.yaxis.title.text == "Working days"
    assert float_chart.layout.hovermode == "x unified"  # one box per status date for every line drawn
    picked = build_activity_float(logic, shown=["C3030"])
    assert [trace.name for trace in picked.data] == ["C3020 · task", "C3030 · succ"]


@pytest.mark.oracle("property")
def test_activity_history_stacks_dates_and_float_on_one_date_axis(store):
    """The task panel's chart: Start and Finish above, the float lines below, every line on the same x
    axis, so one hover box per status date covers both plots (hoversubplots "axis", unified hover). No
    two lines share a colour: E1020, picked, is not drawn in Finish's colour."""
    code = "C3020"
    history = store.history[store.history["task_code"] == code].sort_values("data_date")
    figure = build_activity_history(history, logic_by_update(store, code), shown=["E1020"])
    assert [(trace.name, trace.yaxis) for trace in figure.data] == [
        ("Start", "y"),
        ("Finish", "y"),
        ("C3020 · task", "y2"),
        ("E1020 · pred", "y2"),
    ]
    assert {trace.xaxis or "x" for trace in figure.data} == {"x"}
    assert figure.layout.hovermode == "x unified" and figure.layout.hoversubplots == "axis"
    assert figure.layout.yaxis2.domain[1] < figure.layout.yaxis.domain[0]  # stacked, not overlaid
    colours = [trace.line.color for trace in figure.data]
    assert len(set(colours)) == len(colours)


def test_fmt_date_shows_a_dash_for_missing_dates():
    assert ui.fmt_date(pd.Timestamp("2026-11-02")) == "02 Nov 2026"
    assert ui.fmt_date(pd.NaT) == "–"
    assert ui.fmt_date(None, "—") == "—"
    assert ui.stamp(pd.Timestamp("2026-11-02")) == "2026-11-02"


def _themes() -> dict:
    config = Path(xerscope.__file__).parent / "app" / ".streamlit" / "config.toml"
    theme = tomllib.loads(config.read_text(encoding="utf-8"))["theme"]
    return {mode: theme[mode] for mode in ("light", "dark")}


def _contrast(foreground: str, background: str) -> float:
    """WCAG 2.2 contrast ratio (https://www.w3.org/TR/WCAG22/#dfn-contrast-ratio)."""

    def luminance(colour: str) -> float:
        channels = [int(colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_gantt_page_colours_and_font_follow_the_theme_in_the_browser():
    # a component in the page reads the theme's --st-* variables, which Streamlit updates live
    css = gantt_assets()["css"]
    for variable in ("--st-background-color", "--st-secondary-background-color", "--st-text-color", "--st-font"):
        assert f"var({variable})" in css, variable
    assert "#" not in css.split("#gantt {", 1)[1].split("}", 1)[0]  # no colour written in the root rule


def test_gantt_row_height_comes_from_the_payload_not_from_the_script_or_the_stylesheet():
    """viz.gantt owns the row height: the script writes ``--row`` from the payload and the stylesheet reads it."""
    css, script = gantt_assets()["css"], gantt_assets()["js"]
    assert "26px" not in css and "var(--row)" in css
    assert "const ROW =" not in script and 'setProperty("--row", payload.rowPx + "px")' in script


def test_marks_reach_3_to_1_on_both_themes():
    # One set for both themes (WCAG 2.2 SC 1.4.11, non-text contrast): lines, markers, bars and the
    # reference lines read on every page background, so nothing needs redrawing on a theme switch.
    backgrounds = [colour for theme in _themes().values() for colour in
                   (theme["backgroundColor"], theme["secondaryBackgroundColor"])]  # fmt: skip
    marks = [*SERIES, NEUTRAL] + [colour for tone, colour in STATUS.items() if tone != "info"]
    for colour in marks:
        for background in backgrounds:
            assert _contrast(colour, background) >= 3, (colour, background)


def test_accent_is_the_link_colour_of_each_theme_and_primary_carries_white_text():
    # ACCENT (style.css, light-dark()) is each theme's linkColor, so text in it reads (4.5:1);
    # primaryColor fills checkboxes and selected chips under white text and marks the page (3:1).
    for mode, theme in _themes().items():
        assert ACCENT[mode].lower() == theme["linkColor"].lower(), mode
        for background in (theme["backgroundColor"], theme["secondaryBackgroundColor"]):
            assert _contrast(ACCENT[mode], background) >= 4.5, (mode, background)
            assert _contrast(theme["primaryColor"], background) >= 3, (mode, background)
        assert _contrast("#ffffff", theme["primaryColor"]) >= 4.5, mode


def _backgrounds(theme: dict) -> list[str]:
    """Every surface text sits on: the page and its panels, the sidebar and its panels."""
    return [theme["backgroundColor"], theme["secondaryBackgroundColor"], *theme["sidebar"].values()]


def _faded(colour: str, background: str, share: float) -> str:
    """``colour`` drawn at ``share`` opacity over ``background``, as one opaque colour."""
    mixed = [
        round(share * int(colour[i : i + 2], 16) + (1 - share) * int(background[i : i + 2], 16)) for i in (1, 3, 5)
    ]
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


@pytest.mark.oracle("standard")
def test_captions_reach_wcag_aa_on_every_background():
    """WCAG 2.2 SC 1.4.3, 4.5:1. A caption is the theme's text at the opacity style.css gives it. At
    Streamlit's own 60 % the light theme falls short on two surfaces: 4.45 on a panel (#F7F5F1) and
    4.43 on the sidebar (#F4F1EC), measured in the browser on the sidebar's baseline line."""
    css = (Path(xerscope.__file__).parent / "app" / "style.css").read_text(encoding="utf-8")
    share = float(re.search(r'^\[data-testid="stCaptionContainer"\] \{ opacity: ([\d.]+); \}$', css, re.M).group(1))
    # the caption that holds a link fades its text alone, by the same share
    assert f"color-mix(in srgb, currentColor {share:.0%}, transparent)" in css
    for mode, theme in _themes().items():
        for background in _backgrounds(theme):
            faded = _faded(theme["textColor"], background, share)
            assert _contrast(faded, background) >= 4.5, (mode, background, faded)


FIELDS = (  # the element Streamlit outlines, for each kind of field the app draws
    '[data-testid="stTextInputRootElement"]',
    '[data-testid="stNumberInputContainer"]',
    '[data-testid="stSelectbox"] > div > div',
    '[data-testid="stMultiSelect"] > div > div',
)


@pytest.mark.oracle("standard")
def test_the_outline_of_a_field_reaches_3_to_1_on_every_background():
    """WCAG 2.2 SC 1.4.11, 3:1 for the boundary of an input. Streamlit outlines a field with the
    theme's borderColor, the hairline of frames and tables: 1.18 to 1.41 on the app's surfaces
    (measured in the browser on the Audit page), so a field at rest read as part of the page.
    style.css outlines the fields with the text colour at a share of its own for each theme; the
    outline is drawn over the field's fill and read against what surrounds it."""
    css = (Path(xerscope.__file__).parent / "app" / "style.css").read_text(encoding="utf-8")
    mixed = r"color-mix\(in srgb, currentColor (\d+)%, transparent\)"
    shares = re.search(rf"^  --xs-field: light-dark\({mixed}, {mixed}\);$", css, re.M).groups()
    for (mode, theme), share in zip(_themes().items(), shares, strict=True):  # light, then dark
        surfaces = _backgrounds(theme)
        assert max(_contrast(theme["borderColor"], surface) for surface in surfaces) < 1.5, mode  # the hairline
        for fill in surfaces:
            outline = _faded(theme["textColor"], fill, int(share) / 100)
            for around in surfaces:
                assert _contrast(outline, around) >= 3, (mode, share, fill, around)
    for field in FIELDS:  # at rest only: the field that has the focus keeps the theme's accent
        assert f"{field}:not(:focus-within)" in css, field


@pytest.mark.oracle("standard")
def test_a_text_button_under_the_pointer_takes_the_accent_not_the_primary_colour():
    """WCAG 2.2 SC 1.4.3. Streamlit colours the text of a text-only button with primaryColor under the
    pointer; the dark theme's primaryColor is for white text on it (3.6:1 on the sidebar, 3.4:1 on the
    page). style.css gives it the accent, which reads on every surface of each theme."""
    css = (Path(xerscope.__file__).parent / "app" / "style.css").read_text(encoding="utf-8")
    states = [f'[data-testid="stBaseButton-tertiary"]:{state}' for state in ("hover", "focus-visible", "active")]
    assert ",\n".join(states) + " { color: var(--accent); }\n" in css
    for mode, theme in _themes().items():
        for background in _backgrounds(theme):
            assert _contrast(ACCENT[mode], background) >= 4.5, (mode, background)
    dark = _themes()["dark"]
    assert _contrast(dark["primaryColor"], dark["sidebar"]["backgroundColor"]) < 4.5  # why the rule exists


@pytest.mark.oracle("standard")
def test_gantt_rows_scroll_from_the_keyboard():
    """WCAG 2.2 SC 2.1.1: the box that scrolls the rows takes the keyboard focus, so the arrow and page
    keys move it; it holds no focusable element of its own."""
    script = gantt_assets()["js"]
    assert 'const scroll = element("div", "scroll");\n  scroll.tabIndex = 0;' in script


def test_fonts_are_served_by_the_app_and_used_everywhere():
    config_file = Path(xerscope.__file__).parent / "app" / ".streamlit" / "config.toml"
    config = tomllib.loads(config_file.read_text(encoding="utf-8"))
    static = config_file.parent.parent / "static"
    assert config["server"]["enableStaticServing"] is True
    faces = config["theme"]["fontFaces"]
    for face in faces:  # every declared face is a file of app/static/, no font host
        assert face["url"].startswith("app/static/") and (static / face["url"].removeprefix("app/static/")).is_file()
    families = {face["family"] for face in faces}
    for option in ("font", "headingFont", "codeFont"):
        assert config["theme"][option].split(",")[0].strip() in families, option
    for family in families:  # each family ships with its licence
        assert (static / f"OFL-{family.replace(' ', '')}.txt").is_file(), family
    body = config["theme"]["font"].split(",")[0].strip()
    assert FONT_FAMILY.split(",")[0] == body  # Plotly charts
    # the Gantt takes the theme's font through --st-font (test_gantt_page_colours_and_font_follow_the_theme…)


def test_menu_offers_the_theme_switch_and_no_developer_options():
    config = Path(xerscope.__file__).parent / "app" / ".streamlit" / "config.toml"
    # "minimal" hides the whole menu, theme switch included; "developer" / "auto" add rerun and deploy
    assert tomllib.loads(config.read_text(encoding="utf-8"))["client"]["toolbarMode"] == "viewer"


def test_tables_offer_no_raw_data_export():
    # The tables show real schedule data; sharing goes through the app's anonymised exports.
    config = Path(xerscope.__file__).parent / "app" / ".streamlit" / "config.toml"
    assert tomllib.loads(config.read_text(encoding="utf-8"))["client"]["disableDataExport"] is True


def test_text_colours_reach_wcag_aa_on_both_backgrounds():
    # 4.5:1 for normal text (WCAG 2.2 SC 1.4.3): page text, links, table headers per theme; status
    # labels are white on their own background, the same on both themes.
    for mode, theme in _themes().items():
        texts = [theme["textColor"], theme["linkColor"], theme["dataframeHeaderTextColor"]]
        for background in (theme["backgroundColor"], theme["secondaryBackgroundColor"]):
            for colour in texts:
                assert _contrast(colour, background) >= 4.5, (mode, colour, background)
    for style in ui.STATUS_STYLE.values():
        assert _contrast("#ffffff", STATUS[style.tone]) >= 4.5, style.label


def test_hover_text_is_the_text_colour_of_each_theme():
    # ui.chart sets the Plotly hover text to TEXT[theme] (Streamlit's own fades it to 3.5:1)
    for mode, theme in _themes().items():
        assert TEXT[mode].lower() == theme["textColor"].lower(), mode


def test_the_spi_over_four_weeks_is_titled_and_written_as_the_other_indices_in_a_table():
    """Without its line in ``ui.COLUMNS`` the column is titled after its name ("Spi 4w") and written with
    one decimal: 0.5 for 0.48."""
    frame = pd.DataFrame({"spi_4w": [None, 0.4799], "spi": [None, 0.9412]})
    shown, overrides = ui.numbers_as_text(frame, ["spi", "spi_4w"])
    assert list(shown["spi_4w"]) == ["–", "0.48"] and list(shown["spi"]) == ["–", "0.94"]
    assert (overrides["spi"]["label"], overrides["spi_4w"]["label"]) == ("SPI (labor units)", "SPI (4 weeks)")


def test_fmt_number_and_tables_write_a_dash_for_a_missing_value():
    assert ui.fmt_number(1.26) == "1.3" and ui.fmt_number(None) == "–" and ui.fmt_number(float("nan"), "{:d}", "") == ""
    frame = pd.DataFrame({"total_float_d": [2.0, None], "spi": [None, 0.896], "note": [None, "x"]})
    shown, overrides = ui.numbers_as_text(frame, ["total_float_d", "spi", "absent"])
    assert list(shown["total_float_d"]) == ["2.0", "–"] and list(shown["spi"]) == ["–", "0.90"]
    assert set(overrides) == {"total_float_d", "spi"}
    assert list(ui.blank_missing(frame)["note"]) == ["–", "x"]
    assert ui.blank_missing(frame)["spi"].isna().sum() == 1  # numbers are left to numbers_as_text
