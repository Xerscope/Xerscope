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
)


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


def test_gantt_compare_with_no_common_tasks(store):
    """Comparison sharing no task code (another project): no outline, no shift, rows still build."""
    s = store.latest
    other = store.first.activities.assign(task_code=lambda f: "ZZ-" + f["task_code"].astype(str))
    tasks = s.activities.assign(category=categorise(s.activities))
    rows = gantt_rows(tasks, rollup(s), compare=other, snapshot=s)
    assert all(r["cmp_finish"] is None and r["shift_wd"] is None for r in rows if r["kind"] == "task")


def test_activity_charts_follow_the_history(store):
    code = store.latest.activities["task_code"].iloc[0]
    history = store.history
    history = history[history["task_code"] == code].sort_values("data_date")
    dates, float_chart = build_activity_dates(history), build_activity_float(history)
    assert [trace.name for trace in dates.data] == ["Start", "Finish"]
    assert [trace.name for trace in float_chart.data] == ["Total float"]
    assert len(float_chart.data[0].x) == len(history)
    assert float_chart.layout.yaxis.title.text == "Working days"


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
    assert 'const scroll = el("div", "scroll");\n  scroll.tabIndex = 0;' in script


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
        assert _contrast("#ffffff", ui.BADGE[style.tone]) >= 4.5, style.label


def test_hover_text_is_the_text_colour_of_each_theme():
    # ui.chart sets the Plotly hover text to TEXT[theme] (Streamlit's own fades it to 3.5:1)
    for mode, theme in _themes().items():
        assert TEXT[mode].lower() == theme["textColor"].lower(), mode


def test_fmt_number_and_tables_write_a_dash_for_a_missing_value():
    assert ui.fmt_number(1.26) == "1.3" and ui.fmt_number(None) == "–" and ui.fmt_number(float("nan"), "{:d}", "") == ""
    frame = pd.DataFrame({"total_float_d": [2.0, None], "spi": [None, 0.896], "note": [None, "x"]})
    shown, overrides = ui.numbers_as_text(frame, ["total_float_d", "spi", "absent"])
    assert list(shown["total_float_d"]) == ["2.0", "–"] and list(shown["spi"]) == ["–", "0.90"]
    assert set(overrides) == {"total_float_d", "spi"}
    assert list(ui.blank_missing(frame)["note"]) == ["–", "x"]
    assert ui.blank_missing(frame)["spi"].isna().sum() == 1  # numbers are left to numbers_as_text
