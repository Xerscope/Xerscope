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
from typing import NamedTuple

import pandas as pd
import streamlit as st

from xerscope.viz.charts import INK, STATUS


class StatusStyle(NamedTuple):
    label: str
    tone: str  # key of the colour in status_colours()
    mark: str  # Markdown, coloured by the theme


# Check status -> style. Red / amber / green are reserved for status.
STATUS_STYLE = {
    "pass": StatusStyle("Pass", "good", ":green[**PASS**]"),
    "fail": StatusStyle("Fail", "critical", ":red[**FAIL**]"),
    "info": StatusStyle("Info", "info", ":blue[**INFO**]"),
    "n/a": StatusStyle("N/A", "muted", ":gray[**N/A**]"),
    "error": StatusStyle("Error", "warning", ":orange[**ERROR**]"),
}


def status_colours(dark: bool) -> dict[str, str]:
    """Text colour of each status tone on the page background of the theme."""
    mode = "dark" if dark else "light"
    return {**STATUS[mode], "muted": INK[mode]["muted"]}


def is_dark() -> bool:
    """Whether the page uses the dark theme (Streamlit infers it from the background)."""
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


ROW_HEIGHT = 33  # pixels per dataframe row, header included in HEADER_HEIGHT
HEADER_HEIGHT = 38

# column -> (label, kind). kind: text | date | datetime | d1 | d2 | h0 | pct | signed | int | bool
COLUMNS: dict[str, tuple[str, str]] = {
    "task_code": ("Activity ID", "text"),
    "task_name": ("Activity name", "wide"),
    "bl_name": ("Activity name", "wide"),
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
    "total_float_d": ("Total float (d)", "d1"),
    "free_float_d": ("Free float (d)", "d1"),
    "remaining_d": ("Remaining (d)", "d1"),
    "original_d": ("Original (d)", "d1"),
    "finish_variance_wd": ("Δ finish vs BL (wd)", "signed"),
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
    "lag_d": ("Lag (d)", "d1"),
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
    "pv_pct": ("PV %", "pct"),
    "ev_pct": ("EV %", "pct"),
    "spi": ("SPI", "d2"),
    "productivity": ("EV / AC", "d2"),
    "ac_unbaselined_hr": ("AC outside BL (h)", "h0"),
    "bei_p6": ("BEI (P6)", "d2"),
    "bei_dcma": ("BEI (DCMA)", "d2"),
    "ev_technique": ("EV technique", "text"),
    "data_date": ("Data date", "date"),
    "source": ("File", "text"),
    "forecast_finish": ("Forecast finish", "datetime"),
    "finish_shift_wd": ("Finish shift (wd)", "signed"),
    "activities": ("Activities", "int"),
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
    "completed": ("Finished", "bool"),
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
    "activities_progressed": ("Activities progressed", "int"),
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
        parts.append(f"Data date **{fmt_date(snapshot.data_date)}**")
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
        col.metric(label, value, delta=delta, help=help_, delta_color=colour, border=True)


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


NUMBER_FORMATS = {"d1": "%.1f", "d2": "%.2f", "h0": "%,.0f", "pct": "%.1f %%", "signed": "%+.1f", "int": "%d"}


def _column_for(label: str, kind: str, values: pd.Series):
    if kind in ("date", "datetime"):
        with_time = kind == "datetime" and _has_time(values)
        return st.column_config.DatetimeColumn(label, format="YYYY-MM-DD HH:mm" if with_time else "YYYY-MM-DD")
    if kind in NUMBER_FORMATS:
        return st.column_config.NumberColumn(label, format=NUMBER_FORMATS[kind])
    if kind == "bool":
        return st.column_config.CheckboxColumn(label)
    if kind == "wide":
        return st.column_config.TextColumn(label, width="medium")
    return st.column_config.TextColumn(label)


def column_config(frame: pd.DataFrame, overrides: dict | None = None) -> dict:
    config: dict = {}
    for column in frame.columns:
        label, kind = COLUMNS.get(column, (str(column).replace("_", " ").capitalize(), ""))
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
    **kwargs,
):
    """A labelled, formatted dataframe; height follows the rows up to ``max_height``.

    ``status`` names a pass/fail column to show as coloured labels.
    """
    if columns is not None:
        frame = frame[[column for column in columns if column in frame.columns]]
    frame = frame.drop(columns=[column for column in HIDDEN if column in frame.columns])
    kwargs.setdefault("hide_index", True)
    kwargs.setdefault("height", table_height(len(frame), max_height))
    kwargs.setdefault("width", "stretch")
    config = column_config(frame, overrides)
    data = status_style(frame, status) if status else frame
    return st.dataframe(data, column_config=config, **kwargs)


def anonymised_csv_button(anonymizer, frame: pd.DataFrame, filename: str, label: str, key: str | None = None) -> None:
    """The table with new Activity IDs and names; refused (and said why, by column) if anything original is left."""
    from xerscope.anonymize import LeakError

    try:
        data = anonymizer.csv(frame)
    except LeakError as exc:
        st.error(str(exc), icon=":material/block:")
        return
    st.download_button(label, data, filename, "text/csv", icon=":material/download:", key=key)


def csv_button(frame: pd.DataFrame, filename: str, label: str = "Download CSV", key: str | None = None) -> None:
    st.download_button(
        label, frame.to_csv(index=False).encode("utf-8-sig"), filename, "text/csv", icon=":material/download:", key=key
    )


def status_style(frame: pd.DataFrame, column: str = "status"):
    """Styler colouring the status column (pass green, fail red…), labels capitalised."""
    out = frame.copy()
    out[column] = out[column].map(status_label)
    colours = status_colours(is_dark())
    colour_of_label = {style.label: colours[style.tone] for style in STATUS_STYLE.values()}

    def colour_cell(label: str) -> str:
        return f"color: {colour_of_label.get(label, 'inherit')}; font-weight: 600"

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
