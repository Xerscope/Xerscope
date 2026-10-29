"""Shared presentation: page header, KPI cards, labelled tables, status colours.

Every page goes through these helpers so the app reads as one product: same header,
same card style, the same column names and number formats everywhere.

    ui.header("Schedule health", store, snap, bl)
    ui.kpis([("Pass", 3), ("Fail", 11, None, "Checks above target")])
    ui.table(flagged)                     # labelled, formatted, technical columns hidden
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import pandas as pd
import streamlit as st

# Status colours (text on white): red / amber / green are reserved for status.
STATUS_COLOUR = {"pass": "#2E7D32", "fail": "#C0392B", "info": "#1F4E79", "n/a": "#7B8794", "error": "#B26A00"}
STATUS_LABEL = {"pass": "Pass", "fail": "Fail", "info": "Info", "n/a": "N/A", "error": "Error"}

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
    "finish_variance_wd": ("Finish variance (wd)", "signed"),
    "finish_var_wd": ("Δ finish vs BL (wd)", "signed"),
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


def md_text(value: object) -> str:
    """Text from a schedule file, shown literally inside Markdown: no link, image, emphasis
    or LaTeX ($...$) can come from an activity name or code."""
    return str(value).translate(_MD_SPECIAL)


def header(title: str, store=None, snap=None, baseline=None, lead: str = "") -> None:
    """Page title, then one context line: project · data date · baseline, then an optional lead."""
    st.title(title)
    bits = []
    if store is not None:
        bits.append(f"**{md_text(store.latest.project_code)}** {md_text(store.latest.project_name)}")
    if snap is not None:
        bits.append(f"Data date **{snap.data_date:%d %b %Y}**")
    if baseline is not None:
        bits.append(f"Baseline **{md_text(baseline.label)}**")
    if bits:
        st.markdown(" · ".join(bits))
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


def _has_time(s: pd.Series) -> bool:
    v = pd.to_datetime(s, errors="coerce").dropna()
    return bool(len(v)) and bool(((v.dt.hour != 0) | (v.dt.minute != 0)).any())


def column_config(df: pd.DataFrame, overrides: dict | None = None) -> dict:
    cfg: dict = {}
    for c in df.columns:
        label, kind = COLUMNS.get(c, (str(c).replace("_", " ").capitalize(), ""))
        if not kind:
            s = df[c]
            kind = (
                "datetime"
                if pd.api.types.is_datetime64_any_dtype(s)
                else "bool"
                if pd.api.types.is_bool_dtype(s)
                else "d1"
                if pd.api.types.is_float_dtype(s)
                else "int"
                if pd.api.types.is_integer_dtype(s)
                else "text"
            )
        if kind in ("date", "datetime"):
            fmt = "YYYY-MM-DD HH:mm" if kind == "datetime" and _has_time(df[c]) else "YYYY-MM-DD"
            cfg[c] = st.column_config.DatetimeColumn(label, format=fmt)
        elif kind == "d1":
            cfg[c] = st.column_config.NumberColumn(label, format="%.1f")
        elif kind == "d2":
            cfg[c] = st.column_config.NumberColumn(label, format="%.2f")
        elif kind == "h0":
            cfg[c] = st.column_config.NumberColumn(label, format="%,.0f")
        elif kind == "pct":
            cfg[c] = st.column_config.NumberColumn(label, format="%.1f %%")
        elif kind == "signed":
            cfg[c] = st.column_config.NumberColumn(label, format="%+.1f")
        elif kind == "int":
            cfg[c] = st.column_config.NumberColumn(label, format="%d")
        elif kind == "bool":
            cfg[c] = st.column_config.CheckboxColumn(label)
        elif kind == "wide":
            cfg[c] = st.column_config.TextColumn(label, width="medium")
        else:
            cfg[c] = st.column_config.TextColumn(label)
    cfg.update(overrides or {})
    return cfg


def table(
    df: pd.DataFrame,
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
        df = df[[c for c in columns if c in df.columns]]
    df = df.drop(columns=[c for c in HIDDEN if c in df.columns])
    kwargs.setdefault("hide_index", True)
    kwargs.setdefault("height", min(33 * len(df) + 38, max_height))
    kwargs.setdefault("width", "stretch")
    cfg = column_config(df, overrides)
    data = status_style(df, status) if status else df
    return st.dataframe(data, column_config=cfg, **kwargs)


def csv_button(df: pd.DataFrame, filename: str, label: str = "Download CSV", key: str | None = None) -> None:
    st.download_button(
        label, df.to_csv(index=False).encode("utf-8-sig"), filename, "text/csv", icon=":material/download:", key=key
    )


def status_style(df: pd.DataFrame, column: str = "status"):
    """Styler colouring the status column (pass green, fail red…), labels capitalised."""
    out = df.copy()
    out[column] = out[column].map(lambda s: STATUS_LABEL.get(s, s))
    reverse = {v: STATUS_COLOUR[k] for k, v in STATUS_LABEL.items()}
    return out.style.map(lambda v: f"color: {reverse.get(v, 'inherit')}; font-weight: 600", subset=[column])
