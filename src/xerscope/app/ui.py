"""Shared presentation: KPI readout, labelled tables, status colours (the page header and its
context banner are state.page_header: they read the session's choices).

Every page goes through these helpers so the app reads as one product: same readout style,
the same column names and number formats everywhere.

    ui.kpis([("Pass", 3), ("Fail", 11, None, "Checks above target")])
    ui.table(flagged)                     # labelled, formatted, technical columns hidden
"""

from __future__ import annotations

import base64
import functools
import re
import sys
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import streamlit as st

from xerscope.analysis.query import fold as _fold
from xerscope.app.glossary import GLOSSARY, spelled_out
from xerscope.config import DEFAULT_SETTINGS
from xerscope.viz import gantt_assets
from xerscope.viz.charts import ACCENT, SERIES, STATUS, TEXT
from xerscope.xer.model import to_datetime


class StatusStyle(NamedTuple):
    label: str
    tone: str  # key of the label's background in BADGE
    mark: str  # Markdown, coloured by the theme


# Check status -> style. Red / amber / green are reserved for status.
STATUS_STYLE = {
    "pass": StatusStyle("Pass", "good", ":green[**PASS**]"),
    "fail": StatusStyle("Fail", "critical", ":red[**FAIL**]"),
    "info": StatusStyle("Info", "info", ":blue[**INFO**]"),
    "n/a": StatusStyle("N/A", "muted", ":gray[**N/A**]"),
    "error": StatusStyle("Error", "warning", ":orange[**ERROR**]"),
}


# Background of each status label in tables, white text on it (>= 4.5:1). A label carries its
# own background, so it reads the same on the light and the dark theme without a redraw.
BADGE = {**STATUS, "muted": "#5b6b82"}


# The WBS Gantt (viz/gantt.js), registered once: this module is imported once per process. A
# component, not an iframe, so its colours follow the theme's --st-* variables in the browser.
# gantt_assets() holds only the html, css and js strings; mypy reads its dict[str, str] as also feeding the bool option
GANTT = st.components.v2.component("xerscope_gantt", **gantt_assets())  # type: ignore[arg-type]


STYLE = Path(__file__).parent / "style.css"
STATIC = Path(__file__).parent / "static"
# The theme's fonts (.streamlit/config.toml, [[theme.fontFaces]]): family -> file in app/static/.
FONT_FILES = {"Onest": "Onest-latin-wght.woff2", "JetBrains Mono": "JetBrainsMono-latin-wght.woff2"}


def theme_loaded() -> bool:
    """Whether Streamlit read the app's .streamlit/config.toml: ``xerscope app`` runs from that folder,
    and Streamlit 1.66 also reads it next to the script. An older Streamlit started from another
    folder reads none: the page then shows Streamlit's defaults (its own fonts and colours, no
    static folder, every interface listened on)."""
    return st.get_option("theme.font") is not None and bool(st.get_option("server.enableStaticServing"))


@functools.cache
def font_fallback_css() -> str:
    """@font-face rules with the two fonts inlined (data: URLs, ~100 KB), for a run without the
    config: the static folder is not served then, so the theme's font URLs would 404."""
    rules = []
    for family, name in FONT_FILES.items():
        data = base64.b64encode((STATIC / name).read_bytes()).decode("ascii")
        rules.append(
            f'@font-face {{ font-family: "{family}"; font-weight: 100 900; font-display: swap; '
            f"src: url(data:font/woff2;base64,{data}) format('woff2'); }}"
        )
    rules.append('.stApp { font-family: "Onest", sans-serif; }')
    rules.append('.stApp code, .stApp pre { font-family: "JetBrains Mono", monospace; }')
    return "\n".join(rules)


def runtime_table() -> pd.DataFrame:
    """Debug block 12: where the app runs and what Streamlit read, one row per setting."""
    import platform

    import streamlit as st_module

    fonts = ", ".join(f"{face.get('family')} ({face.get('url')})" for face in st.get_option("theme.fontFaces") or [])
    rows = [
        ("Config read", "yes" if theme_loaded() else "no — start with `xerscope app`"),
        ("Working directory (config is read here)", str(Path.cwd())),
        ("theme.font", str(st.get_option("theme.font"))),
        ("theme.fontFaces", fonts or "none"),
        ("server.enableStaticServing (fonts folder)", str(st.get_option("server.enableStaticServing"))),
        ("Fonts inlined as fallback", "no" if theme_loaded() else "yes"),
        ("Style sheet", f"{STYLE} ({STYLE.stat().st_size} bytes)"),
        ("Package", str(Path(__file__).resolve().parents[1])),
        ("Streamlit", st_module.__version__),
        ("Python", platform.python_version()),
    ]
    return pd.DataFrame(rows, columns=["setting", "value"])


def apply_style() -> None:
    """style.css with the app's colours (sent once per run, takes no space). The series colours
    hold on both themes, the accent is a CSS light-dark() pair resolved by the color-scheme
    Streamlit sets on the app, and the rest follows the page's text colour, so a theme switch
    needs no rerun. Without the config (``theme_loaded``), the fonts are inlined so the page at
    least reads in the app's faces."""
    accent = f"light-dark({ACCENT['light']}, {ACCENT['dark']})"
    colours = {"accent": accent} | {f"s{index}": colour for index, colour in enumerate(SERIES, start=1)}
    variables = "".join(f"--{name}: {value};" for name, value in colours.items())
    fallback = "" if theme_loaded() else font_fallback_css()
    st.html(f"<style>:root {{{variables}}}\n{fallback}\n{STYLE.read_text(encoding='utf-8')}</style>")


ROW_HEIGHT = 33  # pixels per dataframe row, header included in HEADER_HEIGHT
HEADER_HEIGHT = 38

# column -> (label, kind). kind: text | date | datetime | d1 | d2 | h0 | pct | signed | int | bool
COLUMNS: dict[str, tuple[str, str]] = {
    "task_code": ("Task ID", "text"),
    "task_name": ("Task name", "wide"),
    "bl_name": ("Task name", "wide"),
    "wbs_code": ("WBS", "text"),
    "wbs_l1": ("WBS level 1", "text"),
    "wbs_name": ("WBS name", "text"),
    "type": ("Type", "text"),
    "task_type": ("Type", "text"),
    "status": ("Status", "text"),
    "start": ("Start", "datetime"),
    "finish": ("Finish", "datetime"),
    "bl_start": ("BL start", "datetime"),
    "bl_finish": ("BL finish", "datetime"),
    "ev_start": ("EV start", "datetime"),  # the EV basis dates (analysis/baseline.py EV_BASES)
    "ev_finish": ("EV finish", "datetime"),
    "act_start_date": ("Actual start", "datetime"),
    "act_end_date": ("Actual finish", "datetime"),
    "target_start_date": ("Planned start", "datetime"),
    "target_end_date": ("Planned finish", "datetime"),
    "early_start_date": ("Early start", "datetime"),
    "early_end_date": ("Early finish", "datetime"),
    "late_start_date": ("Late start", "datetime"),
    "late_end_date": ("Late finish", "datetime"),
    "total_float_d": ("Total float (wd)", "d1"),
    "free_float_d": ("Free float (wd)", "d1"),
    "remaining_d": ("Remaining duration (wd)", "d1"),
    "original_d": ("Original duration (wd)", "d1"),
    "finish_variance_wd": ("Finish variance (wd)", "signed"),
    "constraint": ("Constraint", "text"),
    "constraint2": ("Secondary constraint", "text"),
    "reason": ("Reason", "wide"),
    "lagged_from": ("Lag from", "text"),
    "drives": ("Drives", "text"),
    "previous": ("Previous update", "datetime"),
    "now": ("This update", "datetime"),
    "pred_code": ("Predecessor", "text"),
    "pred_name": ("Predecessor name", "wide"),
    "succ_code": ("Successor", "text"),
    "succ_name": ("Successor name", "wide"),
    "lag_hr": ("Lag (h)", "d1"),
    "lag_d": ("Lag (wd)", "d1"),
    "pred_start": ("Pred. start", "datetime"),
    "pred_finish": ("Pred. finish", "datetime"),
    "succ_start": ("Succ. start", "datetime"),
    "succ_finish": ("Succ. finish", "datetime"),
    "pct_complete": ("% complete", "pct"),
    "is_critical": ("Critical", "bool"),
    "in_snapshot": ("In update", "bool"),
    "labor_budget_hr": ("Budget (h)", "h0"),
    "labor_actual_hr": ("Actual (h)", "h0"),
    "labor_remaining_hr": ("Remaining (h)", "h0"),
    "bl_labor_hr": ("BL budget (h)", "h0"),
    "ev_labor_hr": ("EV budget (h)", "h0"),
    "schedule_pct": ("Schedule %", "pct"),
    "perf_pct": ("Performance %", "pct"),
    "pv_hr": ("PV (h)", "h0"),
    "ev_hr": ("EV (h)", "h0"),
    "ac_hr": ("AC (h)", "h0"),
    "etc_hr": ("ETC (h)", "h0"),
    "eac_hr": ("EAC (h)", "h0"),
    "sv_hr": ("SV (h)", "h0"),
    "bac_hr": ("BAC (h)", "h0"),
    "bac_cost": ("BAC (cost)", "h0"),
    "pv_cost": ("PV (cost)", "h0"),
    "ev_cost": ("EV (cost)", "h0"),
    "spi_cost": ("SPI", "d2"),
    "pv_pct": ("Percent scheduled", "pct"),
    "ev_pct": ("Percent complete", "pct"),
    "spi": ("SPI (labor units)", "d2"),
    "productivity": ("EV / AC (baselined work)", "d2"),
    "cpi": ("CPI (labor units)", "d2"),
    "ac_unbaselined_hr": ("AC outside BL (h)", "h0"),
    "deleted_since_bl": ("Deleted since BL", "int"),
    "pv_deleted_hr": ("PV of deleted (h)", "h0"),
    "bei_p6": ("BEI (P6)", "d2"),
    "bei_dcma": ("BEI (DCMA)", "d2"),
    "ev_technique": ("EV technique", "text"),
    "data_date": ("Status date", "date"),
    "source": ("File", "text"),
    "forecast_finish": ("Forecast finish", "datetime"),
    "finish_shift_wd": ("Finish shift (wd)", "signed"),
    "activities": ("Tasks", "int"),
    "complete": ("Complete", "int"),
    "in_progress": ("In progress", "int"),
    "not_started": ("Not started", "int"),
    "critical": ("Critical", "int"),
    "relationships": ("Relationships", "int"),
    "pct_complete_count": ("% complete (count)", "pct"),
    "category": ("Category", "text"),
    "change": ("Change", "text"),
    "field": ("Field", "text"),
    "before": ("Before", "text"),
    "after": ("After", "text"),
    "delta": ("Δ", "signed"),
    "pct_prev": ("% previous", "pct"),
    "pct_now": ("% now", "pct"),
    "pct_delta": ("Δ % complete", "signed"),
    "commitment": ("Commitment", "text"),
    "kept": ("Kept", "bool"),
    "in_update": ("In update", "bool"),
    "status_now": ("Status now", "text"),
    "planned_date": ("Forecast at W−1", "datetime"),
    "starts_kept": ("Starts kept", "int"),
    "starts_committed": ("Starts committed", "int"),
    "finishes_kept": ("Finishes kept", "int"),
    "finishes_committed": ("Finishes committed", "int"),
    "ppc_start": ("PPC Start", "pct"),
    "ppc_finish": ("PPC Finish", "pct"),
    "ppc_week": ("PPC W/W−1", "pct"),
    "start_var_w1": ("Start var. vs W−1 (wd)", "signed"),
    "finish_var_w1": ("Finish var. vs W−1 (wd)", "signed"),
    "start_var_w2": ("Start var. vs W−2 (wd)", "signed"),
    "finish_var_w2": ("Finish var. vs W−2 (wd)", "signed"),
    "actual_date": ("Actual", "datetime"),
    "forecast_now": ("Forecast now", "datetime"),
    "new": ("New", "bool"),
    "deleted": ("Deleted", "bool"),
    "earned_hr_week": ("Earned this week (h)", "h0"),
    "actual_hr_week": ("Actual this week (h)", "h0"),
    "budget_hr": ("Budget (h)", "h0"),
    "activities_progressed": ("Tasks progressed", "int"),
    "progress_pts": ("Progress (pts)", "signed"),
    "id": ("ID", "text"),
    "group": ("Group", "text"),
    "check": ("Check", "wide"),
    "target": ("Target", "text"),
    "result": ("Result", "text"),
    "count": ("Found / checked", "text"),
    "note": ("Note", "wide"),
}
HIDDEN = {"total_float_hr_cnt"}  # stored P6 units, kept in exports but not shown


_MD_SPECIAL = str.maketrans({c: "\\" + c for c in "\\`*_{}[]()#+-.!|<>~$"})


def fmt_date(timestamp, missing: str = "–") -> str:
    """A date for display ("02 Nov 2026"); ``missing`` stands for NaT / None."""
    return missing if pd.isna(timestamp) else f"{timestamp:%d %b %Y}"


def stamp(timestamp) -> str:
    """A date for file names and titles (2026-11-02)."""
    return f"{timestamp:%Y-%m-%d}"


def fmt_number(value, template: str = "{:.1f}", missing: str = "–") -> str:
    """A number for display; ``missing`` stands for NaN / None."""
    return missing if value is None or pd.isna(value) else template.format(value)


def numbers_as_text(frame: pd.DataFrame, columns: Iterable[str], missing: str = "–") -> tuple[pd.DataFrame, dict]:
    """``columns`` written as text in their usual format, ``missing`` for NaN: st.dataframe writes
    "None" for a missing number. Returns the frame and the column_config overrides for ``table``
    (right-aligned text under the usual label)."""
    frame = frame.copy()
    overrides = {}
    for column in columns:
        if column not in frame.columns:
            continue
        label, kind = COLUMNS.get(column, (str(column).replace("_", " ").capitalize(), ""))
        template = PY_FORMATS.get(kind or _infer_kind(frame[column]), "{:.1f}")
        frame[column] = [fmt_number(value, template, missing) for value in frame[column]]
        overrides[column] = st.column_config.TextColumn(label, alignment="right", help=spelled_out(label) or None)
    return frame, overrides


def blank_missing(frame: pd.DataFrame, missing: str = "–") -> pd.DataFrame:
    """None / NaN in the text columns written as ``missing``: st.dataframe would write "None"."""
    out = None
    for column in frame.columns:
        values = frame[column]
        if (pd.api.types.is_object_dtype(values) or pd.api.types.is_string_dtype(values)) and values.isna().any():
            out = frame.copy() if out is None else out
            out[column] = values.astype(object).where(values.notna(), missing)
    return frame if out is None else out


def chart(fig, **kwargs) -> None:
    """A Plotly figure in the house style: no mode bar (it stays on screen on a touch screen), the
    hover text in the theme's text colour (Streamlit's Plotly theme fades it to 3.5:1)."""
    theme = getattr(st.context.theme, "type", None) or "light"
    fig.update_layout(hoverlabel=dict(font=dict(color=TEXT.get(theme, TEXT["light"]))))
    kwargs.setdefault("width", "stretch")
    st.plotly_chart(fig, config={"displayModeBar": False}, **kwargs)


def table_height(rows: int, max_height: int) -> int:
    """Pixel height of a dataframe with ``rows`` rows, capped at ``max_height``."""
    return min(ROW_HEIGHT * rows + HEADER_HEIGHT, max_height)


def md_text(value: object) -> str:
    """Text from a schedule file, shown literally inside Markdown: no link, image, emphasis
    or LaTeX ($...$) can come from an activity name or code."""
    return str(value).translate(_MD_SPECIAL)


_ZERO = re.compile(r"^[+\-\u2212]?0(\.0+)?(?![\d.])")


def delta_colour(delta, colour: str) -> str:
    """st.metric's delta_color, with a change of zero ("+0 this week", "+0.0 wd") drawn neutral:
    st.metric colours it by its sign, red or green, as if something had moved."""
    return "off" if delta is not None and _ZERO.match(str(delta).strip()) else colour


def kpis(items: Sequence[tuple], formulas: Mapping[str, Mapping[str, str]] | None = None) -> None:
    """A readout, one line per figure: (label, value[, delta[, help[, delta_color]]]). Past four
    figures the lines run in two columns. The lines are st.metric, drawn as rows by style.css.
    ``formulas`` (label -> standard -> formula, analysis/explain.py KPI_FORMULAS) opens a
    "Formulas" popover under the readout for the labels it knows."""
    labels = tuple(str(item[0]) for item in items)
    with st.container(key=f"kpis_{zlib.crc32('|'.join(labels).encode()):08x}"):
        columns = st.columns(2, gap="large") if len(items) > 4 else [st.container()]
        per_column = -(-len(items) // len(columns))  # read down the first column, then the second
        for index, item in enumerate(items):
            label, value, *rest = item
            delta = rest[0] if len(rest) > 0 else None
            help_ = rest[1] if len(rest) > 1 else None
            colour = rest[2] if len(rest) > 2 else "normal"
            help_ = "\n\n".join(part for part in (help_, spelled_out(label)) if part) or None
            delta_color = delta_colour(delta, colour)
            box = columns[index // per_column]
            if delta_color == "off":
                # marked for style.css: Streamlit's neutral chip is a fixed grey, too faint on the
                # light theme, and the page's text colour replaces it
                box = box.container(key=f"kpi_off_{index}_{zlib.crc32(label.encode()):08x}")
            # delta_color is "off" or the caller's colour name; st.metric checks it, its stub lists the names
            box.metric(label, value, delta=delta, help=help_, delta_color=delta_color)  # type: ignore[arg-type]
    known = [label for label in labels if formulas and label in formulas]
    if known:
        with st.popover("Formulas", icon=":material/function:", help="How each figure is computed, by standard"):
            for label in known:
                by_standard = formulas[label].items()  # type: ignore[index]
                lines = "\n".join(f"- *{standard}* · {formula}" for standard, formula in by_standard)
                st.markdown(f"**{label}**\n{lines}")


SCORE_HELP = (
    "Checks in pass / checks evaluated (pass + fail); info and n/a checks are not evaluated. "
    "A xerscope convention: no source defines a global score, and a failed check is a flag to read, "
    "not a verdict on the schedule."
)


def score_cards(scores: dict) -> None:
    """One card per standard: ``"<name> score"``, the share of evaluated checks that pass, then the
    count evaluated and the failed ids. A standard whose score is None is not computed yet."""
    with st.container(key="score_cards"):
        cols = st.columns(len(scores))
    for col, (name, score) in zip(cols, scores.items(), strict=True):
        label = f"{name} score"
        help_ = "\n\n".join(part for part in (SCORE_HELP, spelled_out(label)) if part)
        if score is None:
            # a short value: a long one is cut with an ellipsis in a card
            col.metric(
                label, "–", delta="not computed yet", delta_color="off", delta_arrow="off", help=help_, border=True
            )
        else:
            col.metric(
                label,
                score.value,
                delta=score.detail,
                delta_color="off",
                delta_arrow="off",
                # the card cuts a long list of failed checks: the help carries the whole of it
                help="\n\n".join((help_, md_text(score.detail))),
                border=True,
            )


def glossary() -> None:
    """Every acronym of the pages, spelled out with its definition and source, in the sidebar: it
    shows on every page, including those that stop early."""
    with st.sidebar.expander("Glossary", icon=":material/menu_book:"):
        st.markdown(
            "\n".join(
                f"- **{token}**: {name}. {definition} *({source})*"
                for token, (name, definition, source) in sorted(GLOSSARY.items(), key=lambda item: item[0].lower())
            )
        )


def as_dates(values: pd.Series) -> pd.Series:
    """A column as dates: left as it is when already one, else read as the XER writes dates
    ("YYYY-MM-DD HH:MM", ISO 8601, seconds tolerated). Never a guess from the first value, which
    pandas would otherwise make and then apply to the rest (a date without time becomes NaT after
    one with seconds), nor a dateutil fallback on a label."""
    if pd.api.types.is_datetime64_any_dtype(values):
        return values
    return to_datetime(values.astype("string").fillna(""))


def section(title: str, caption: str = "") -> None:
    st.subheader(title)
    if caption:
        st.caption(caption)


def _has_time(values: pd.Series) -> bool:
    timestamps = as_dates(values).dropna()
    return bool(len(timestamps)) and bool(((timestamps.dt.hour != 0) | (timestamps.dt.minute != 0)).any())


def _infer_kind(values: pd.Series) -> str:
    """Display kind of a column that is not in COLUMNS, from its dtype."""
    if pd.api.types.is_datetime64_any_dtype(values):
        return "datetime"
    if pd.api.types.is_bool_dtype(values):
        return "bool"
    if pd.api.types.is_float_dtype(values):
        return "d1"
    if pd.api.types.is_integer_dtype(values):
        return "int"
    return "text"


NUMBER_FORMATS = {
    "d1": "%.1f",
    "d2": "%.2f",
    "d3": "%.3f",
    "h0": "%,.0f",
    "pct": "%.1f %%",
    "signed": "%+.1f",
    "int": "%d",
}
# The same formats for Python (numbers_as_text writes a column as text).
PY_FORMATS = {
    "d1": "{:.1f}",
    "d2": "{:.2f}",
    "d3": "{:.3f}",
    "h0": "{:,.0f}",
    "pct": "{:.1f} %",
    "signed": "{:+.1f}",
    "int": "{:.0f}",
}


def _column_for(label: str, kind: str, values: pd.Series):
    help_ = spelled_out(label) or None
    if kind in ("date", "datetime"):
        with_time = kind == "datetime" and _has_time(values)
        return st.column_config.DatetimeColumn(
            label, format="YYYY-MM-DD HH:mm" if with_time else "YYYY-MM-DD", help=help_
        )
    if kind in NUMBER_FORMATS:
        return st.column_config.NumberColumn(label, format=NUMBER_FORMATS[kind], help=help_)
    if kind == "bool":
        return st.column_config.CheckboxColumn(label, help=help_)
    if kind == "wide":
        return st.column_config.TextColumn(label, width="medium", help=help_)
    return st.column_config.TextColumn(label, help=help_)


def column_config(frame: pd.DataFrame, overrides: dict | None = None, raw_labels: bool = False) -> dict:
    """Label and format of each column. ``raw_labels`` keeps the field names as written (the XER
    field, the analysis column), for tables read beside P6; formats are unchanged."""
    config: dict = {}
    for column in frame.columns:
        label, kind = COLUMNS.get(column, (str(column).replace("_", " ").capitalize(), ""))
        label = str(column) if raw_labels else label
        config[column] = _column_for(label, kind or _infer_kind(frame[column]), frame[column])
    config.update(overrides or {})
    return config


# Column filters. One text per column, all of them must hold (AND); an empty text filters nothing.
#   text     beton            contains, ignoring case and accents
#   number   <0  >=5  =3  -10..0
#   date     >2026-11-01  2026-11  2026-11..2026-12   (a year, month or day; ranges are inclusive)
FILTER_HINT = {
    "text": "contains…",
    "number": "<0, >=5, -10..0",
    "date": ">2026-11-01, 2026-11, 2026-11..2026-12",
}
_OPERATOR = re.compile(r"^(<=|>=|<|>|=)?\s*(.+)$")
_YEAR_MONTH_OR_DAY = re.compile(r"\d{4}(-\d{2}(-\d{2})?)?")


def filter_kind(column: str, values: pd.Series) -> str:
    """text | number | date: how a column's filter text is read."""
    kind = COLUMNS.get(column, ("", ""))[1] or _infer_kind(values)
    if kind in ("date", "datetime"):
        return "date"
    if kind in NUMBER_FORMATS and pd.api.types.is_numeric_dtype(values):
        return "number"
    return "text"


def _number(text: str) -> float:
    return float(text.replace("−", "-").replace(",", "").replace("%", "").strip())


def _range(text: str) -> tuple[str, str] | None:
    """Bounds of "a..b"; the split skips the first character so "-10..0" keeps its sign."""
    cut = text.find("..", 1)
    return (text[:cut], text[cut + 2 :]) if cut > 0 else None


def _operator_and_value(text: str) -> tuple[str, str]:
    """The comparison a filter starts with ("" when it has none) and the value after it."""
    found = _OPERATOR.match(text)
    if found is None:  # the pattern reads one line: a value holding a line break is not a filter
        raise ValueError(f"not a filter: {text!r}")
    operator, value = found.groups()
    return operator or "", value


def _number_test(text: str) -> Callable[[pd.Series], pd.Series]:
    bounds = _range(text)
    if bounds:
        low, high = _number(bounds[0]), _number(bounds[1])
        return lambda values: values.between(low, high)
    operator, value = _operator_and_value(text)
    number = _number(value)
    return {
        "<": lambda values: values < number,
        "<=": lambda values: values <= number,
        ">": lambda values: values > number,
        ">=": lambda values: values >= number,
    }.get(operator or "=", lambda values: values == number)


def _period(text: str) -> pd.Period:
    """The year, month or day a filter names (2026, 2026-11, 2026-11-01). Any other text is refused:
    read loosely, "3 4" would be 4 March of the year 1."""
    written = text.strip()
    if not _YEAR_MONTH_OR_DAY.fullmatch(written):
        raise ValueError(f"not a year, a month or a day: {text!r}")
    return pd.Period(written)


def _date_test(text: str) -> Callable[[pd.Series], pd.Series]:
    """A date may be a year, a month or a day: "=" keeps the whole period, ">" what is after it."""
    bounds = _range(text)
    if bounds:
        start, end = _period(bounds[0]).start_time, _period(bounds[1]).end_time
        return lambda values: (values >= start) & (values <= end)
    operator, value = _operator_and_value(text)
    period = _period(value)
    start, end = period.start_time, period.end_time
    return {
        "<": lambda values: values < start,
        "<=": lambda values: values <= end,
        ">": lambda values: values > end,
        ">=": lambda values: values >= start,
    }.get(operator or "=", lambda values: (values >= start) & (values <= end))


def filter_rows(frame: pd.DataFrame, filters: Mapping[str, str]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Rows of ``frame`` that every filter keeps, and the filters that could not be read
    (column -> message). A filter that cannot be read is skipped, not applied."""
    keep = pd.Series(True, index=frame.index)
    errors: dict[str, str] = {}
    for column, raw in filters.items():
        text = (raw or "").strip()
        if not text or column not in frame.columns:
            continue
        values = frame[column]
        kind = filter_kind(column, values)
        try:
            if kind == "number":
                keep &= _number_test(text)(values).fillna(False)
            elif kind == "date":
                keep &= _date_test(text)(as_dates(values)).fillna(False)
            else:
                keep &= values.map(fold).str.contains(fold(text), regex=False)
        except ValueError:
            errors[column] = f"Not read as a {kind} filter. Examples: {FILTER_HINT[kind]}"
    return frame[keep], errors


def _caller_key() -> str:
    """Where table() was called from (file:line): a table without a key keeps its filters per
    call site. Call sites that draw several tables in a loop pass ``key``."""
    caller = sys._getframe(2)
    return f"{Path(caller.f_code.co_filename).stem}:{caller.f_lineno}"


def _filtered(frame: pd.DataFrame, config: dict, key: str, status: str | None) -> pd.DataFrame:
    """A popover of column filters above the table; the rows they keep."""
    prefix = f"filter:{key}:"
    labels = {
        column: (spec.get("label") if isinstance(spec, dict) else spec) or str(column)
        for column, spec in config.items()
        if column in frame.columns
    }
    active = sum(bool(st.session_state.get(prefix + str(column))) for column in frame.columns)
    title = f"Filter columns · {active}" if active else "Filter columns"
    filters: dict[str, str] = {}
    choices: dict[str, list] = {}
    with st.popover(title, icon=":material/filter_list:"):
        for column in frame.columns:
            label, widget_key = labels[column], prefix + str(column)
            if column == status:
                options = sorted({status_label(value) for value in frame[column].dropna()})
                choices[column] = st.multiselect(label, options, key=widget_key, placeholder="any")
            else:
                hint = FILTER_HINT[filter_kind(column, frame[column])]
                filters[column] = st.text_input(label, key=widget_key, placeholder=hint)
        rows, errors = filter_rows(frame, filters)
        for column, message in errors.items():
            st.caption(f":red[{md_text(labels[column])}: {md_text(message)}]")
    for column, picked in choices.items():
        if picked:
            rows = rows[rows[column].map(status_label).isin(picked)]
    if len(rows) != len(frame):
        st.caption(f"{len(rows):,} of {len(frame):,} rows")
    return rows


def table(
    frame: pd.DataFrame,
    *,
    columns: Iterable[str] | None = None,
    max_height: int = 560,
    overrides: dict | None = None,
    status: str | None = None,
    raw_labels: bool = False,
    open_task: Callable[[str], None] | None = None,
    **kwargs,
):
    """A labelled, formatted dataframe; height follows the rows up to ``max_height``.

    ``status`` names a pass/fail column to show as coloured labels; ``raw_labels`` keeps the
    column names as headers (see ``column_config``). A table longer than
    ``Settings.table_filter_min_rows`` gets column filters, kept per ``key`` (or per call site).
    ``open_task`` (state.open_in_gantt) makes the rows selectable: a selected row's Task ID gets a
    button that opens the Gantt on it.
    """
    if columns is not None:
        frame = frame[[column for column in columns if column in frame.columns]]
    frame = blank_missing(frame.drop(columns=[column for column in HIDDEN if column in frame.columns]))
    config = column_config(frame, overrides, raw_labels)
    key = kwargs.get("key") or _caller_key()
    if len(frame) > DEFAULT_SETTINGS.table_filter_min_rows:
        frame = _filtered(frame, config, key, status)
    kwargs.setdefault("hide_index", True)
    kwargs.setdefault("height", table_height(len(frame), max_height))
    kwargs.setdefault("width", "stretch")
    linked = open_task is not None and "task_code" in frame.columns and not frame.empty
    if linked:
        kwargs.setdefault("key", f"table:{key}")
        kwargs.update(on_select="rerun", selection_mode="single-row")
    data = status_style(frame, status) if status else frame
    event = st.dataframe(data, column_config=config, **kwargs)
    if linked:
        rows = event.selection.rows if event is not None and hasattr(event, "selection") else []
        if rows:
            code = str(frame.iloc[rows[0]]["task_code"])
            if st.button(
                f"Open {md_text(code)} in the Gantt", icon=":material/view_timeline:", key=f"{kwargs['key']}:open"
            ):
                open_task(code)  # type: ignore[misc]  # linked is True only when open_task is not None
        else:
            st.caption("Select a row to open its task in the Gantt.")
    return event


def status_style(frame: pd.DataFrame, column: str = "status"):
    """Styler drawing the status column as labels (pass green, fail red…), capitalised."""
    out = frame.copy()
    out[column] = out[column].map(status_label)
    background_of_label = {style.label: BADGE[style.tone] for style in STATUS_STYLE.values()}

    def colour_cell(label: str) -> str:
        background = background_of_label.get(label)
        if background is None:
            return ""
        return f"background-color: {background}; color: #ffffff; font-weight: 600"

    return out.style.map(colour_cell, subset=[column])


def status_label(status: str) -> str:
    return STATUS_STYLE[status].label if status in STATUS_STYLE else status


def latest_names(store) -> pd.Series:
    """Latest task name of every Activity ID in any update, indexed by task_code."""
    return store.history.drop_duplicates("task_code", keep="last").set_index("task_code")["task_name"]


def code_label(names: pd.Series, task_code: str) -> str:
    """Selectbox label for an Activity ID: the code and its latest name."""
    return f"{task_code} · {names.get(task_code, '')}"


def fold(text) -> str:
    """Lower-case without accents, for searching: fold("Béton") == "beton" (analysis.query.fold)."""
    return _fold(text)


def search_mask(frame: pd.DataFrame, columns: Sequence[str], text: str) -> pd.Series:
    """Rows where any of ``columns`` contains ``text``, ignoring case and accents."""
    needle = fold(text)
    hits = {column: frame[column].map(fold).str.contains(needle, regex=False) for column in columns}
    return pd.DataFrame(hits).any(axis=1)
