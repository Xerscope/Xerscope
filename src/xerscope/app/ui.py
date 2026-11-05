"""Shared presentation: page header, KPI cards, labelled tables, status colours.

Every page goes through these helpers so the app reads as one product: same header,
same card style, the same column names and number formats everywhere.

    ui.header("Schedule health", store, snap, bl)
    ui.kpis([("Pass", 3), ("Fail", 11, None, "Checks above target")])
    ui.table(flagged)                     # labelled, formatted, technical columns hidden
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import streamlit as st

from xerscope.app.glossary import GLOSSARY, spelled_out
from xerscope.viz import gantt_assets
from xerscope.viz.charts import ACCENT, SERIES, STATUS


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
GANTT = st.components.v2.component("xerscope_gantt", **gantt_assets())


STYLE = Path(__file__).parent / "style.css"


def apply_style() -> None:
    """style.css with the app's colours (sent once per run, takes no space). The series colours
    hold on both themes, the accent is a CSS light-dark() pair resolved by the color-scheme
    Streamlit sets on the app, and the rest follows the page's text colour, so a theme switch
    needs no rerun."""
    accent = f"light-dark({ACCENT['light']}, {ACCENT['dark']})"
    colours = {"accent": accent} | {f"s{index}": colour for index, colour in enumerate(SERIES, start=1)}
    variables = "".join(f"--{name}: {value};" for name, value in colours.items())
    st.html(f"<style>:root {{{variables}}}\n{STYLE.read_text(encoding='utf-8')}</style>")


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
    "spi_cost": ("SPI", "d3"),
    "pv_pct": ("Percent scheduled", "pct"),
    "ev_pct": ("Percent complete", "pct"),
    "spi": ("SPI (labor units)", "d3"),
    "productivity": ("EV / AC (baselined work)", "d2"),
    "cpi": ("CPI (labor units)", "d2"),
    "ac_unbaselined_hr": ("AC outside BL (h)", "h0"),
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
    "completed": ("Complete", "bool"),
    "in_update": ("In update", "bool"),
    "status_now": ("Status now", "text"),
    "planned_finish": ("Forecast at W−1", "datetime"),
    "actual_finish": ("Actual finish", "datetime"),
    "forecast_finish_now": ("Forecast now", "datetime"),
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


def table_height(rows: int, max_height: int) -> int:
    """Pixel height of a dataframe with ``rows`` rows, capped at ``max_height``."""
    return min(ROW_HEIGHT * rows + HEADER_HEIGHT, max_height)


def md_text(value: object) -> str:
    """Text from a schedule file, shown literally inside Markdown: no link, image, emphasis
    or LaTeX ($...$) can come from an activity name or code."""
    return str(value).translate(_MD_SPECIAL)


def header(title: str, store=None, snapshot=None, baseline=None, lead: str = "") -> None:
    """Page title, then one context line: project · data date · baseline, then an optional lead."""
    st.title(title)
    parts = []
    if store is not None:
        parts.append(f"**{md_text(store.latest.project_code)}** {md_text(store.latest.project_name)}")
    if snapshot is not None:
        parts.append(f"Status date **{fmt_date(snapshot.data_date)}**")
    if baseline is not None:
        parts.append(f"Baseline **{md_text(baseline.label)}**")
    if parts:
        st.markdown(" · ".join(parts))
    if lead:
        st.caption(lead)


def kpis(items: Sequence[tuple]) -> None:
    """One row of bordered cards: (label, value[, delta[, help[, delta_color]]])."""
    cols = st.columns(len(items))
    for col, item in zip(cols, items, strict=True):
        label, value, *rest = item
        delta = rest[0] if len(rest) > 0 else None
        help_ = rest[1] if len(rest) > 1 else None
        colour = rest[2] if len(rest) > 2 else "normal"
        help_ = "\n\n".join(part for part in (help_, spelled_out(label)) if part) or None
        col.metric(label, value, delta=delta, help=help_, delta_color=colour, border=True)


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


def section(title: str, caption: str = "") -> None:
    st.subheader(title)
    if caption:
        st.caption(caption)


def _has_time(values: pd.Series) -> bool:
    timestamps = pd.to_datetime(values, errors="coerce").dropna()
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


def table(
    frame: pd.DataFrame,
    *,
    columns: Iterable[str] | None = None,
    max_height: int = 560,
    overrides: dict | None = None,
    status: str | None = None,
    raw_labels: bool = False,
    **kwargs,
):
    """A labelled, formatted dataframe; height follows the rows up to ``max_height``.

    ``status`` names a pass/fail column to show as coloured labels; ``raw_labels`` keeps the
    column names as headers (see ``column_config``).
    """
    if columns is not None:
        frame = frame[[column for column in columns if column in frame.columns]]
    frame = frame.drop(columns=[column for column in HIDDEN if column in frame.columns])
    kwargs.setdefault("hide_index", True)
    kwargs.setdefault("height", table_height(len(frame), max_height))
    kwargs.setdefault("width", "stretch")
    config = column_config(frame, overrides, raw_labels)
    data = status_style(frame, status) if status else frame
    return st.dataframe(data, column_config=config, **kwargs)


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
    """Lower-case without accents, for searching: fold("Béton") == "beton"."""
    text = "" if pd.isna(text) else str(text)
    return "".join(
        character for character in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(character)
    )


def search_mask(frame: pd.DataFrame, columns: Sequence[str], text: str) -> pd.Series:
    """Rows where any of ``columns`` contains ``text``, ignoring case and accents."""
    needle = fold(text)
    hits = {column: frame[column].map(fold).str.contains(needle, regex=False) for column in columns}
    return pd.DataFrame(hits).any(axis=1)
