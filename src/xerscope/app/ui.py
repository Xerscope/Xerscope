"""Shared presentation: KPI readout, labelled tables, status colours (the page header and its
context banner are state.page_header: they read the session's choices).

Every page goes through these helpers so the app reads as one product: same readout style,
the same column names and number formats everywhere.

    ui.kpis([("Pass", 3), ("Fail", 11, None, "Checks above target")])
    ui.table(flagged)                     # labelled, formatted, technical columns hidden
"""

from __future__ import annotations

import os
import re
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import streamlit as st

from xerscope.analysis.explain import READINGS
from xerscope.analysis.query import fold as _fold
from xerscope.analysis.task_filters import search_mask as _search_mask
from xerscope.app.glossary import GLOSSARY, spelled_out
from xerscope.app.table_filters import FILTER_HINT, FILTER_RULE, as_dates, keep_mask
from xerscope.app.theme import STYLE, theme_loaded
from xerscope.config import DEFAULT_SETTINGS
from xerscope.viz import gantt_assets
from xerscope.viz.charts import STATUS, TEXT


class StatusStyle(NamedTuple):
    label: str
    tone: str  # key of the label's background in STATUS
    mark: str  # Markdown, coloured by the theme


# Check status -> style. Red / amber / green are reserved for status.
STATUS_STYLE = {
    "pass": StatusStyle("Pass", "good", ":green[**PASS**]"),
    "fail": StatusStyle("Fail", "critical", ":red[**FAIL**]"),
    "info": StatusStyle("Info", "info", ":blue[**INFO**]"),
    "n/a": StatusStyle("N/A", "muted", ":gray[**N/A**]"),
    "error": StatusStyle("Error", "warning", ":orange[**ERROR**]"),
}


# The WBS Gantt (viz/gantt.js), registered once: this module is imported once per process. A
# component, not an iframe, so its colours follow the theme's --st-* variables in the browser.
# gantt_assets() holds only the html, css and js strings; mypy reads its dict[str, str] as also feeding the bool option
GANTT = st.components.v2.component("xerscope_gantt", **gantt_assets())  # type: ignore[arg-type]


STRICT_READINGS = "XERSCOPE_STRICT_READINGS"  # set by the tests: a figure without a reading raises


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


ROW_HEIGHT = 33  # pixels per dataframe row, header included in HEADER_HEIGHT
HEADER_HEIGHT = 38
# Tallest a table grows before it scrolls: a table of parameters or a summary, and a list of items.
TABLE_SHORT = 420
TABLE_LONG = 640

# The sentences that several columns share (the help of each column is the third field of COLUMNS).
HELP_TYPE = (
    "P6 task type: Task dependent, Resource dependent, Start or Finish milestone, Level of effort, WBS "
    "summary (TASK.task_type). Milestones and LOE are left out of most checks."
)

HELP_START = (
    "The task's current dates: actual when there is one, else remaining early dates "
    '(docs/architecture.md: "actual > remaining > early"). Date and time of the file.'
)

HELP_ACT_START_DATE = (
    "Dates reported as done (TASK.act_start_date, act_end_date). An actual after the status date is "
    "flagged by P6-10b, DCMA-09, 06A506a."
)

HELP_TARGET_START_DATE = (
    "P6 Planned dates (TASK.target_start_date, target_end_date): the baseline when no baseline file is "
    "set (Baseline: planned dates)."
)

HELP_EARLY_START_DATE = "Earliest dates the CPM forward pass gives (TASK.early_start_date, early_end_date)."

HELP_LATE_START_DATE = (
    "Latest dates without delaying the project (or its Must Finish By), from the backward pass "
    "(TASK.late_start_date, late_end_date)."
)

HELP_CONSTRAINT = (
    "P6 primary / secondary constraint (TASK.cstr_type, cstr_type2) with its date. Hard: Mandatory "
    "Start/Finish (DCMA adds Start/Finish On and On or Before); soft: On or After, As Late As Possible "
    "(`standards/p6.toml:47, 56`, `dcma.toml:61`)."
)

HELP_PRED_CODE = "Task ID (task_code) of the relationship's predecessor / successor."

HELP_PRED_NAME = "Their names in the update."

HELP_PRED_START = "Current dates of the two ends of the relationship, as Start / Finish above."

HELP_LABOR_BUDGET_HR = (
    "Labor hours: TASK.target_work_qty / act_work_qty / remain_work_qty, else the sums of the task's "
    "labor assignments (docs/formulas.md)."
)

HELP_ACTIVITIES = "Counts of tasks in the update; in progress = started and not complete (`store.py`)."

HELP_CATEGORY = (
    "Changelog: the family of the change (Scope, Dates, Logic, Durations, Resources…), its kind, and the "
    "XER field that changed (docs/formulas.md §5)."
)

HELP_BEFORE = "The field's value in From and in To."

HELP_PCT_PREV = "Task % complete in W−1 / W; 0 when the task is absent (docs/formulas.md)."

HELP_STARTS_KEPT = "The week's counts behind PPC Start and PPC Finish; milestones and LOE left out (docs/formulas.md)."

HELP_NEW = "Task absent from W−1 / absent from W (docs/formulas.md)."

HELP_EARNED_HR_WEEK = (
    "Labor hours earned (budget × Δ% complete, or EV(W) − EV(W−1) with a baseline) / actual hours added "
    "between the two updates (docs/formulas.md)."
)


# column -> (label, kind, help). kind: text | wide | wider | date | datetime | d0 | d1 | d2 | h0 | pct | signed |
# int | bool. help is the sentence of the tooltip; the glossary adds the acronyms of the label.
COLUMNS: dict[str, tuple[str, str, str]] = {
    "task_code": ("Task ID", "text", ""),
    "task_name": (
        "Task name",
        "wide",
        (
            "The task's name as the file writes it (TASK.task_name). Anonymized in downloads when the sidebar "
            "switch is on."
        ),
    ),
    "bl_name": (
        "Task name",
        "wide",
        "The name the baseline gives the task (baseline TASK.task_name), matched on task_code.",
    ),
    "wbs_code": ("WBS", "text", ""),
    "wbs_l1": ("WBS level 1", "text", ""),
    "wbs_name": ("WBS name", "text", ""),
    "type": ("Type", "text", HELP_TYPE),
    "task_type": ("Type", "text", HELP_TYPE),
    "status": ("Status", "text", "P6 status: Not started, In progress, Complete (TASK.status_code)."),
    "start": ("Start", "datetime", HELP_START),
    "finish": ("Finish", "datetime", HELP_START),
    "bl_start": ("BL start", "datetime", ""),
    "bl_finish": ("BL finish", "datetime", ""),
    "ev_start": ("EV start", "datetime", ""),  # the EV basis dates (analysis/baseline.py EV_BASES)
    "ev_finish": ("EV finish", "datetime", ""),
    "act_start_date": ("Actual start", "datetime", HELP_ACT_START_DATE),
    "act_end_date": ("Actual finish", "datetime", HELP_ACT_START_DATE),
    "target_start_date": ("Planned start", "datetime", HELP_TARGET_START_DATE),
    "target_end_date": ("Planned finish", "datetime", HELP_TARGET_START_DATE),
    "early_start_date": ("Early start", "datetime", HELP_EARLY_START_DATE),
    "early_end_date": ("Early finish", "datetime", HELP_EARLY_START_DATE),
    "late_start_date": ("Late start", "datetime", HELP_LATE_START_DATE),
    "late_end_date": ("Late finish", "datetime", HELP_LATE_START_DATE),
    "total_float_d": ("Total float (wd)", "d1", ""),
    "free_float_d": ("Free float (wd)", "d1", ""),
    "remaining_d": ("Remaining duration (wd)", "d1", ""),
    "original_d": ("Original duration (wd)", "d1", ""),
    "finish_variance_wd": ("Finish variance (wd)", "signed", ""),
    "constraint": ("Constraint", "text", HELP_CONSTRAINT),
    "constraint2": ("Secondary constraint", "text", HELP_CONSTRAINT),
    "reason": ("Reason", "wide", "Why the check lists this row, as the rule writes it."),
    "lagged_from": ("Lag from", "text", "The predecessor the listed lag comes from (a relationship check)."),
    "drives": ("Drives", "text", "The successor this task drives (critical path or dangling checks)."),
    "previous": (
        "Previous update",
        "datetime",
        ("The value in the update one status period earlier (28 days, 06A504a/b): an actual date that changed since."),
    ),
    "now": ("This update", "datetime", "The same field in the update shown."),
    "pred_code": ("Predecessor", "text", HELP_PRED_CODE),
    "pred_name": ("Predecessor name", "wide", HELP_PRED_NAME),
    "succ_code": ("Successor", "text", HELP_PRED_CODE),
    "succ_name": ("Successor name", "wide", HELP_PRED_NAME),
    "lag_hr": ("Lag (h)", "d1", "Relationship lag in hours as P6 stores it (TASKPRED lag). Negative = lead."),
    "lag_d": ("Lag (wd)", "d1", ""),
    "pred_start": ("Pred. start", "datetime", HELP_PRED_START),
    "pred_finish": ("Pred. finish", "datetime", HELP_PRED_START),
    "succ_start": ("Succ. start", "datetime", HELP_PRED_START),
    "succ_finish": ("Succ. finish", "datetime", HELP_PRED_START),
    "pct_complete": (
        "% complete",
        "pct",
        (
            "P6 task % Complete following the task's percent complete type: duration, physical or units "
            "(docs/formulas.md §1.3)."
        ),
    ),
    "is_critical": (
        "Critical",
        "bool",
        (
            "P6 critical flag: total float ≤ the project's critical threshold, or on the longest path when the "
            "project's critical path type says so (`explain.critical_definition`, `explain.py`)."
        ),
    ),
    "in_snapshot": (
        "In update",
        "bool",
        ("Baseline task still present in the update shown (BAC, PV and EV sum over these; docs/formulas.md §3)."),
    ),
    "labor_budget_hr": ("Budget (h)", "h0", HELP_LABOR_BUDGET_HR),
    "labor_actual_hr": ("Actual (h)", "h0", HELP_LABOR_BUDGET_HR),
    "labor_remaining_hr": ("Remaining (h)", "h0", HELP_LABOR_BUDGET_HR),
    "bl_labor_hr": ("BL budget (h)", "h0", ""),
    "ev_labor_hr": ("EV budget (h)", "h0", ""),
    "schedule_pct": (
        "Schedule %",
        "pct",
        (
            "P6 Schedule % Complete: share of the baseline duration elapsed at the status date, in working time "
            "of the baseline calendar (docs/formulas.md §3)."
        ),
    ),
    "perf_pct": (
        "Performance %",
        "pct",
        "P6 Performance % Complete by the WBS's earned value technique (task %, 0/100, 50/50, custom).",
    ),
    "pv_hr": ("PV (h)", "h0", ""),
    "ev_hr": ("EV (h)", "h0", ""),
    "ac_hr": ("AC (h)", "h0", ""),
    "etc_hr": ("ETC (h)", "h0", ""),
    "eac_hr": ("EAC (h)", "h0", ""),
    "sv_hr": ("SV (h)", "h0", ""),
    "bac_hr": ("BAC (h)", "h0", ""),
    "bac_cost": ("BAC (cost)", "h0", ""),
    "pv_cost": ("PV (cost)", "h0", ""),
    "ev_cost": ("EV (cost)", "h0", ""),
    "spi_cost": ("SPI", "d2", ""),
    "pv_pct": ("Percent scheduled", "pct", "PV / BAC in %, labor hours (P6 Planned Value / Budget At Completion)."),
    "ev_pct": ("Percent complete", "pct", "EV / BAC in %, labor hours (P6 Earned Value / Budget At Completion)."),
    "spi": ("SPI (labor units)", "d2", ""),
    "spi_4w": ("SPI (4 weeks)", "d2", ""),
    "productivity": ("EV / AC (baselined work)", "d2", ""),
    "cpi": ("CPI (labor units)", "d2", ""),
    "ac_unbaselined_hr": ("AC outside BL (h)", "h0", ""),
    "deleted_since_bl": ("Deleted since BL", "int", ""),
    "pv_deleted_hr": ("PV of deleted (h)", "h0", ""),
    "bei_p6": ("BEI (P6)", "d2", ""),
    "bei_dcma": ("BEI (DCMA)", "d2", ""),
    "ev_technique": ("EV technique", "text", ""),
    "data_date": (
        "Status date",
        "date",
        (
            "The project's status date (PROJECT.last_recalc_date; the model falls back to plan_start_date, "
            '`xer/model.py`). Every "before / after the status date" check counts from it.'
        ),
    ),  # the PPC tables label it "Week ending" on purpose: one row per week
    "source": ("File", "text", "The XER file the update was read from."),
    "forecast_finish": (
        "Forecast finish",
        "datetime",
        (
            "Latest finish of the project's tasks in this update (actual, else remaining, else early finish; "
            '`KPI_FORMULAS` "Forecast finish").'
        ),
    ),
    "first_forecast": ("First forecast", "date", "The milestone's forecast date in the first update loaded."),
    "latest_forecast": ("Latest forecast", "date", "The milestone's forecast date in the latest update."),
    "last_week_wd": (
        "Last update (wd)",
        "signed",
        (
            "Move of the milestone's forecast between the last two updates, in working days of its calendar; a "
            "later forecast reads negative."
        ),
    ),
    "finish_shift_wd": ("Finish shift (wd)", "signed", ""),
    "activities": ("Tasks", "int", HELP_ACTIVITIES),
    "complete": ("Complete", "int", HELP_ACTIVITIES),
    "in_progress": ("In progress", "int", HELP_ACTIVITIES),
    "not_started": ("Not started", "int", HELP_ACTIVITIES),
    "critical": ("Critical", "int", "Count of tasks flagged critical (`store.py`)."),
    "relationships": ("Relationships", "int", "Count of TASKPRED rows of the update (`store.py`)."),
    "pct_complete_count": ("% complete (count)", "pct", "100 × complete / tasks, a count, not hours (`store.py`)."),
    "category": ("Category", "text", HELP_CATEGORY),
    "change": ("Change", "text", HELP_CATEGORY),
    "field": ("Field", "text", HELP_CATEGORY),
    "total": ("Changes", "int", "Number of changes in the category."),
    "kinds": ("Kinds of change", "wider", "The kinds of change seen in the category, sorted."),
    "before": ("Before", "text", HELP_BEFORE),
    "after": ("After", "text", HELP_BEFORE),
    "delta": (
        "Δ",
        "signed",
        (
            "After − before; for a start or finish, working days gained (+) or lost (−) on the task's calendar, a"
            " later date reads negative (`changelog.py`)."
        ),
    ),
    "pct_prev": ("% previous", "pct", HELP_PCT_PREV),
    "pct_now": ("% now", "pct", HELP_PCT_PREV),
    "pct_delta": ("Δ % complete", "signed", "pct_now − pct_prev, points (docs/formulas.md)."),
    "commitment": (
        "Commitment",
        "text",
        (
            "Start or Finish: what W−1 forecast on or before W's status date (Last Planner System (PPC); "
            "docs/formulas.md)."
        ),
    ),
    "kept": ("Kept", "bool", "The commitment was met in W: started / complete on or before the status date."),
    "in_update": (
        "In update",
        "bool",
        "The committed task is still in W; a deleted task is listed and left out of the counts.",
    ),
    "status_now": ("Status now", "text", "The task's status in W (deleted when absent)."),
    "planned_date": ("Forecast at W−1", "datetime", "The start or finish W−1 forecast for the committed end."),
    "starts_kept": ("Starts kept", "int", HELP_STARTS_KEPT),
    "starts_committed": ("Starts committed", "int", HELP_STARTS_KEPT),
    "finishes_kept": ("Finishes kept", "int", HELP_STARTS_KEPT),
    "finishes_committed": ("Finishes committed", "int", HELP_STARTS_KEPT),
    "ppc_start": ("PPC Start", "pct", ""),
    "ppc_finish": ("PPC Finish", "pct", ""),
    "ppc_week": ("PPC W/W−1", "pct", ""),
    "start_var_w1": ("Start var. vs W−1 (wd)", "signed", ""),
    "finish_var_w1": ("Finish var. vs W−1 (wd)", "signed", ""),
    "start_var_w2": ("Start var. vs W−2 (wd)", "signed", ""),
    "finish_var_w2": ("Finish var. vs W−2 (wd)", "signed", ""),
    "actual_date": ("Actual", "datetime", "The actual start or finish W reports, when kept."),
    "forecast_now": ("Forecast now", "datetime", "W's forecast for the committed end when it was not kept."),
    "new": ("New", "bool", HELP_NEW),
    "deleted": ("Deleted", "bool", HELP_NEW),
    "earned_hr_week": ("Earned this week (h)", "h0", HELP_EARNED_HR_WEEK),
    "actual_hr_week": ("Actual this week (h)", "h0", HELP_EARNED_HR_WEEK),
    "budget_hr": ("Budget (h)", "h0", "Σ labor budget hours of the WBS node's tasks (docs/formulas.md)."),
    "activities_progressed": (
        "Tasks progressed",
        "int",
        "Tasks of the node whose % complete rose this week (docs/formulas.md).",
    ),
    "progress_pts": (
        "Progress (pts)",
        "signed",
        ("100 × earned hours this week / budget hours of the node, points of % complete (docs/formulas.md)."),
    ),
    "id": ("ID", "text", ""),
    "group": ("Group", "text", "The standard's grouping of the check (the TOML's group)."),
    "check": ("Check", "wide", "The check's name in the standard."),
    "target": ("Target", "text", "The threshold the standard sets, in the check's unit (%, count, ratio, pass/fail)."),
    "result": (
        "Result",
        "text",
        ("The value found, in the check's unit; n/a when the population is empty or an input (baseline) is missing."),
    ),
    "count": ("Found / checked", "text", "Numerator / denominator behind the result (`checks.py`)."),
    "note": (
        "Note",
        "wide",
        "What the check could not count or read, and the baseline it was computed on (`checks.py`).",
    ),
    "flagged": ("Items listed", "int", "Number of tasks or links the check lists."),
    "found_exp": ("Found (report)", "int", "The found count typed from the P6 Check Schedule report."),
    "total_exp": ("Total (report)", "int", "The total count typed from the P6 Check Schedule report."),
    "match": ("Match", "bool", "Ticked when xerscope's counts equal the report's."),
    "table": ("Table", "text", "The name of an export table."),
    "columns": ("Columns", "int", "Number of columns of the table."),
    "formula": ("Formula", "wider", "How the measure is computed."),
    "horizon": ("Updates ahead", "int", "How many updates before the week the plan read is."),
    "wwp": ("Weekly plan", "int", "Commitments of the weekly work plan of the week."),
    "ta_pct": ("TA (%)", "d0", "Tasks Anticipated: the share of the week's commitments the earlier plan already held."),
    "tmr_pct": (
        "TMR (%)",
        "d0",
        "Tasks Made Ready: the share of what the earlier plan held for the week that was kept.",
    ),
    # Delay analysis (analysis/forensics.py, analysis/longest_path.py)
    "step": (
        "Step",
        "text",
        "The label of the step: a kind of change in the half-step reading, a population step in a funnel.",
    ),
    "removed": ("Removed", "int", "Rows the step took out of the population."),
    "left": ("Left", "int", "Rows left after the step; the last step's left is the denominator."),
    "shift_wd": ("Shift (wd)", "signed", ""),
    "changes": ("Changes applied", "int", ""),
    "finish_case": ("Finish held by", "text", ""),
    "held_by": ("Date that holds it", "datetime", ""),
    "finish_before_replanning": ("Finish before replanning", "datetime", ""),
    "slip_wd": (
        "Slip (wd)",
        "signed",
        (
            "Shift of the finish due to progress, in working days of the project calendar; a later finish reads "
            "negative (AACE RP 29R-03 3.4.K.4.d)."
        ),
    ),
    "replanning_wd": ("Replanning (wd)", "signed", ""),
    "residual_wd": ("Residual (wd)", "signed", ""),
    "period_wd": ("Period (wd)", "d1", ""),
    "engine_gap_wd": ("Recalculated vs file (wd)", "signed", ""),
    "longest_path_float_d": ("Longest path float (wd)", "d1", ""),
    "tasks_matched": ("Tasks matched", "int", ""),
    "tasks_added": ("Tasks added", "int", ""),
    "tasks_deleted": ("Tasks deleted", "int", ""),
    "matched": ("Matched", "int", "Tasks found in both updates, matched by Task ID."),
    "added": ("Added", "int", "Tasks the update holds and the previous one did not."),
    "float_before_d": ("Total float before (wd)", "d1", ""),
    "path_source": ("Path read from", "text", ""),
    "on_path": ("On the path", "int", ""),
    "stayed": ("Stayed", "int", ""),
    "entered": ("Entered", "int", ""),
    "left_finished": ("Left: finished", "int", ""),
    "left_open": ("Left: still open", "int", ""),
    "left_deleted": ("Left: deleted", "int", ""),
    "stability": ("Stability", "d2", ""),
    "path_committed": ("Commitments on the path", "int", ""),
    "path_kept": ("Kept on the path", "int", ""),
    "ppc_path": ("PPC on the path", "pct", ""),
    "within the lookahead": ("Within the lookahead", "int", ""),
    "beyond the lookahead": ("Beyond the lookahead", "int", ""),
    "beyond_pct": ("Share beyond", "pct", ""),
}
HIDDEN = {"total_float_hr_cnt"}  # stored P6 units, kept in exports but not shown
MISSING = "–"  # written for a value that is not there: a date, a number, a cell of a table
SHIFT_WD_FORMAT = "{:+.1f} wd"  # a move of a finish, in working days, the same on every page
SHIFT_WD_SENTENCE = "Working days gained (+) or lost (−); a later finish reads negative."


_MD_SPECIAL = str.maketrans({character: "\\" + character for character in "\\`*_{}[]()#+-.!|<>~$"})


# A date in a KPI or a caption is read inside a sentence, so its month is a word ("02 Nov 2026");
# a date in a table or a chart hover is a column to compare and sort, so it stays ISO
# (2026-11-02), the order P6 shows in its own grids.
def fmt_date(timestamp, missing: str = MISSING) -> str:
    """A date for display ("02 Nov 2026"); ``missing`` stands for NaT / None."""
    return missing if pd.isna(timestamp) else f"{timestamp:%d %b %Y}"


def stamp(timestamp) -> str:
    """A date for file names and titles (2026-11-02)."""
    return f"{timestamp:%Y-%m-%d}"


def fmt_number(value, template: str = "{:.1f}", missing: str = MISSING) -> str:
    """A number for display; ``missing`` stands for NaN / None."""
    return missing if value is None or pd.isna(value) else template.format(value)


def numbers_as_text(frame: pd.DataFrame, columns: Iterable[str], missing: str = MISSING) -> tuple[pd.DataFrame, dict]:
    """``columns`` written as text in their usual format, ``missing`` for NaN: st.dataframe writes
    "None" for a missing number. Returns the frame and the column_config overrides for ``table``
    (right-aligned text under the usual label)."""
    frame = frame.copy()
    overrides = {}
    for column in columns:
        if column not in frame.columns:
            continue
        label, kind, _ = COLUMNS.get(column, (str(column).replace("_", " ").capitalize(), "", ""))
        template = PY_FORMATS.get(kind or _infer_kind(frame[column]), "{:.1f}")
        frame[column] = [fmt_number(value, template, missing) for value in frame[column]]
        overrides[column] = st.column_config.TextColumn(label, alignment="right", help=column_help(column, label))
    return frame, overrides


def blank_missing(frame: pd.DataFrame, missing: str = MISSING) -> pd.DataFrame:
    """None / NaN in the text columns written as ``missing``: st.dataframe would write "None"."""
    out = None
    for column in frame.columns:
        values = frame[column]
        if (pd.api.types.is_object_dtype(values) or pd.api.types.is_string_dtype(values)) and values.isna().any():
            out = frame.copy() if out is None else out
            out[column] = values.astype(object).where(values.notna(), missing)
    return frame if out is None else out


def chart(figure, reading: str | None = None, **kwargs) -> None:
    """A Plotly figure in the house style: no mode bar (it stays on screen on a touch screen), the
    hover text in the theme's text colour (Streamlit's Plotly theme fades it to 3.5:1).

    A "How to read" popover goes above it: the READINGS key given as ``reading``, else the one the
    builder set in the figure's layout. Under XERSCOPE_STRICT_READINGS=1 a figure with neither raises."""
    key = reading
    if key is None and figure.layout.meta:
        key = figure.layout.meta.get("reading")
    if key is None and os.environ.get(STRICT_READINGS) == "1":
        raise ValueError("A figure without a reading key: its builder sets layout.meta['reading'].")
    reading_popover(key)
    theme = getattr(st.context.theme, "type", None) or "light"
    figure.update_layout(hoverlabel=dict(font=dict(color=TEXT.get(theme, TEXT["light"]))))
    kwargs.setdefault("width", "stretch")
    st.plotly_chart(figure, config={"displayModeBar": False}, **kwargs)


def reading_popover(key: str | None) -> None:
    """A "How to read" popover with the paragraphs of ``READINGS[key]``, the empty ones left out;
    nothing when ``key`` is None. The source is shown without web addresses, as ``show_method``
    shows a check's."""
    if key is None:
        return
    reading = READINGS[key]
    paragraphs = {
        "How to read": reading.how,
        "What it means": reading.meaning,
        "What to conclude": reading.conclude,
        "Source": without_addresses(reading.source),
    }
    with st.popover("How to read", icon=":material/help:"):
        st.markdown("\n\n".join(f"**{title}.** {text}" for title, text in paragraphs.items() if text))


def table_height(rows: int, max_height: int) -> int:
    """Pixel height of a dataframe with ``rows`` rows, capped at ``max_height``."""
    return min(ROW_HEIGHT * rows + HEADER_HEIGHT, max_height)


_ADDRESS_IN_BRACKETS = re.compile(r"\s*\((?:https?://|www\.)[^\s)]*\)")
_ADDRESS = re.compile(r"(?:https?://|www\.)\S+")


def without_addresses(text: str) -> str:
    """``text`` less its web addresses, an address in brackets going with its brackets: the app
    shows no external link, and Streamlit turns a bare address into one. The addresses of the
    sources are in docs/standards.md, Sources."""
    return " ".join(_ADDRESS.sub("", _ADDRESS_IN_BRACKETS.sub("", text)).split())


# Streamlit's Markdown links a bare web or mail address by itself, escaped or not. A word joiner
# (invisible, no line break) after "http", "https", "www" or "@" keeps it from reading one.
NO_LINK = "\u2060"
_LINKED_BY_ITSELF = re.compile(r"https?(?=://)|www(?=\.)|(?<=[\w.+-])@(?=[\w-])", re.IGNORECASE)


def md_text(value: object) -> str:
    """Text from a schedule file, shown literally inside Markdown: no link, image, emphasis
    or LaTeX ($...$) can come from an activity name or code, an address in it included."""
    unlinked = _LINKED_BY_ITSELF.sub(lambda found: found.group() + NO_LINK, str(value))
    return unlinked.translate(_MD_SPECIAL)


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
            _figure(columns[index // per_column], index, item)
    if formulas:
        _formulas_popover(labels, formulas)


def _figure(box, index: int, item: tuple) -> None:
    """One line of a readout, drawn in ``box``: (label, value[, delta[, help[, delta_color]]])."""
    label, value, *rest = item
    delta = rest[0] if len(rest) > 0 else None
    help_ = rest[1] if len(rest) > 1 else None
    colour = rest[2] if len(rest) > 2 else "normal"
    help_ = "\n\n".join(part for part in (help_, spelled_out(label)) if part) or None
    delta_color = delta_colour(delta, colour)
    if delta_color == "off":
        # marked for style.css: Streamlit's neutral chip is a fixed grey, too faint on the
        # light theme, and the page's text colour replaces it
        box = box.container(key=f"kpi_off_{index}_{zlib.crc32(label.encode()):08x}")
    # delta_color is "off" or the caller's colour name; st.metric checks it, its stub lists the names
    box.metric(label, value, delta=delta, help=help_, delta_color=delta_color)  # type: ignore[arg-type]


def _formulas_popover(labels: Sequence[str], formulas: Mapping[str, Mapping[str, str]]) -> None:
    """A "Formulas" popover: how each figure of the readout is computed, by standard. Nothing when
    ``formulas`` knows none of the labels."""
    known = [label for label in labels if label in formulas]
    if not known:
        return
    with st.popover("Formulas", icon=":material/function:", help="How each figure is computed, by standard"):
        for label in known:
            lines = "\n".join(f"- *{standard}* · {formula}" for standard, formula in formulas[label].items())
            st.markdown(f"**{label}**\n{lines}")


SCORE_HELP = (
    "Criteria in pass / criteria evaluated (pass + fail); info and n/a checks are not evaluated; a criterion "
    "written as several metrics (the same item) fails when one of them fails. "
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
                label, MISSING, delta="not computed yet", delta_color="off", delta_arrow="off", help=help_, border=True
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


def section(title: str, caption: str = "") -> None:
    st.subheader(title)
    if caption:
        st.caption(caption)


# Message boxes, one rule for every page. info: a choice the user still has to make, or a page that does
# not apply (need). warning: a result is shown but is to be read with care (caveat). error: nothing can
# be shown, and the page stops (st.error where it stops).
def need(text: str) -> None:
    """Show ``text`` as the choice still to make, or the reason the page does not apply."""
    st.info(text)


def caveat(text: str) -> None:
    """Show ``text`` as the care to take in reading the result under it."""
    st.warning(text)


def block(title: str, caption: str = "") -> None:
    """A titled part of a section: one question of a form among several."""
    st.markdown(f"##### {title}")
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
    "d0": "%.0f",
    "d1": "%.1f",
    "d2": "%.2f",
    "d3": "%.3f",
    "h0": "%,.0f",
    "thousands": "%,d",
    "pct": "%.1f %%",
    "signed": "%+.1f",
    "int": "%d",
}
# The same formats for Python (numbers_as_text writes a column as text).
PY_FORMATS = {
    "d0": "{:.0f}",
    "d1": "{:.1f}",
    "d2": "{:.2f}",
    "d3": "{:.3f}",
    "h0": "{:,.0f}",
    "pct": "{:.1f} %",
    "signed": "{:+.1f}",
    "int": "{:.0f}",
}


def column_help(column: str, label: str) -> str | None:
    """The tooltip of a column: its sentence in COLUMNS, then the acronyms its label holds, spelled out."""
    sentence = COLUMNS.get(column, ("", "", ""))[2]
    return "\n\n".join(part for part in (sentence, spelled_out(label)) if part) or None


def _column_for(label: str, kind: str, values: pd.Series, help_: str | None):
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
    if kind == "wider":
        return st.column_config.TextColumn(label, width="large", help=help_)
    return st.column_config.TextColumn(label, help=help_)


def number_columns(kind: str, *names: str, **labels: str) -> dict:
    """Return the ``overrides`` of ``table`` that write columns in the ``kind`` format of NUMBER_FORMATS.

    A column of ``names`` is labelled with its field name; ``labels`` gives column=label for the others.
    """
    labelled = {**{name: name for name in names}, **labels}
    return {
        column: st.column_config.NumberColumn(label, format=NUMBER_FORMATS[kind]) for column, label in labelled.items()
    }


def count_columns(*names: str, **labels: str) -> dict:
    """Return the ``overrides`` of ``table`` that write whole-number columns as counts (see ``number_columns``)."""
    return number_columns("int", *names, **labels)


def column_config(frame: pd.DataFrame, overrides: dict | None = None, raw_labels: bool = False) -> dict:
    """Label, format and tooltip of each column. ``raw_labels`` keeps the field names as written (the XER
    field, the analysis column), for tables read beside P6: formats are unchanged and the tooltip is the
    glossary's acronyms only, since a field name can mean another thing there than in COLUMNS."""
    config: dict = {}
    for column in frame.columns:
        label, kind, _ = COLUMNS.get(column, (str(column).replace("_", " ").capitalize(), "", ""))
        if raw_labels:
            help_ = spelled_out(str(column)) or None
            config[column] = _column_for(str(column), kind or _infer_kind(frame[column]), frame[column], help_)
        else:
            config[column] = _column_for(
                label, kind or _infer_kind(frame[column]), frame[column], column_help(column, label)
            )
    config.update(overrides or {})
    return config


# How a filter text is read is in table_filters; the kind of a column comes from COLUMNS, which is here.
def filter_kind(column: str, values: pd.Series) -> str:
    """text | number | date: how a column's filter text is read."""
    kind = COLUMNS.get(column, ("", "", ""))[1] or _infer_kind(values)
    if kind in ("date", "datetime"):
        return "date"
    if kind in NUMBER_FORMATS and pd.api.types.is_numeric_dtype(values):
        return "number"
    return "text"


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
            keep &= keep_mask(kind, text, values)
        except ValueError:
            errors[column] = f"Not read as a {kind} filter. Examples: {FILTER_HINT[kind]}"
    return frame[keep], errors


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
    with st.popover(title, icon=":material/filter_list:"):
        filters, statuses_picked = _filter_inputs(frame, labels, prefix, status)
        rows, errors = filter_rows(frame, filters)
        for column, message in errors.items():
            st.caption(f":red[{md_text(labels[column])}: {md_text(message)}]")
    if status is not None and statuses_picked:
        rows = rows[rows[status].map(status_label).isin(statuses_picked)]
    if len(rows) != len(frame):
        st.caption(f"{len(rows):,} of {len(frame):,} rows")
    return rows


def _filter_help(label: str, *sentences: str) -> str:
    """The tooltip of a column filter: the column's help (the acronyms its label holds), then ``sentences``."""
    return "\n\n".join(part for part in (spelled_out(label), *sentences) if part)


def _filter_inputs(
    frame: pd.DataFrame, labels: dict, prefix: str, status: str | None
) -> tuple[dict[str, str], list[str]]:
    """One input per column: a text filter, or for the status column a choice among its labels.
    Returns the texts typed, by column, and the status labels picked."""
    filters: dict[str, str] = {}
    statuses_picked: list[str] = []
    for column in frame.columns:
        label, widget_key = labels[column], prefix + str(column)
        if column == status:
            options = sorted({status_label(value) for value in frame[column].dropna()})
            help_text = _filter_help(label, FILTER_RULE)
            statuses_picked = st.multiselect(label, options, key=widget_key, placeholder="any", help=help_text)
        else:
            hint = FILTER_HINT[filter_kind(column, frame[column])]
            help_text = _filter_help(label, f"Operators: {hint}", FILTER_RULE)
            filters[column] = st.text_input(label, key=widget_key, placeholder=hint, help=help_text)
    return filters, statuses_picked


def table(
    frame: pd.DataFrame,
    *,
    key: str,
    columns: Iterable[str] | None = None,
    max_height: int = 560,
    overrides: dict | None = None,
    status: str | None = None,
    raw_labels: bool = False,
    open_task: Callable[[str], None] | None = None,
    reading: str | None = None,
    empty: str | None = None,
    **kwargs,
):
    """A labelled, formatted dataframe; height follows the rows up to ``max_height``.

    ``status`` names a pass/fail column to show as coloured labels; ``raw_labels`` keeps the
    column names as headers (see ``column_config``). A table longer than
    ``Settings.table_filter_min_rows`` gets column filters, kept under ``key``, the table's own name on its page.
    ``open_task`` (state.open_in_gantt) makes the rows selectable: a selected row's Task ID gets a
    button that opens the Gantt on it. ``reading``, a READINGS key, puts a "How to read" popover above the table.
    ``empty``, the page's sentence on what was looked for and why nothing came out, is shown in place of the grid
    when ``frame`` has no row: an empty grid is only a header.
    """
    reading_popover(reading)
    if empty is not None and frame.empty:
        st.caption(empty)
        return None
    frame = shown_columns(frame, columns)
    config = column_config(frame, overrides, raw_labels)
    if len(frame) > DEFAULT_SETTINGS.table_filter_min_rows:
        frame = _filtered(frame, config, key, status)
    kwargs.setdefault("hide_index", True)
    kwargs.setdefault("height", table_height(len(frame), max_height))
    kwargs.setdefault("width", "stretch")
    kwargs.setdefault("placeholder", MISSING)  # st.dataframe writes "None" for a missing number or date
    linked = open_task is not None and "task_code" in frame.columns and not frame.empty
    if linked:
        kwargs.update(on_select="rerun", selection_mode="single-row")
    data = status_style(frame, status) if status else frame
    event = st.dataframe(data, column_config=config, key=key, **kwargs)
    if open_task is not None and linked:
        _open_in_gantt_button(event, frame, key, open_task)
    return event


def shown_columns(frame: pd.DataFrame, columns: Iterable[str] | None) -> pd.DataFrame:
    """``frame`` reduced to ``columns`` when they are given, less the technical columns, a missing text as MISSING."""
    if columns is not None:
        frame = frame[[column for column in columns if column in frame.columns]]
    return blank_missing(frame.drop(columns=[column for column in HIDDEN if column in frame.columns]))


def caption_why_empty(frame: pd.DataFrame, reason: str) -> None:
    """Under a grid kept although it has no row, because its header is the information: ``reason`` it is empty."""
    if frame.empty:
        st.caption(reason)


def _open_in_gantt_button(event, frame: pd.DataFrame, table_key: str, open_task: Callable[[str], None]) -> None:
    """Under a table with selectable rows: a button opening the Gantt on the row selected, or the
    invitation to select one."""
    selected = event.selection.rows if event is not None and hasattr(event, "selection") else []
    if not selected:
        st.caption("Select a row to open its task in the Gantt.")
        return
    code = str(frame.iloc[selected[0]]["task_code"])
    if st.button(
        f"Open {md_text(code)} in the Gantt",
        icon=":material/view_timeline:",
        key=f"{table_key}:open",
        help="Switches to the Gantt on the selected row's task, in the update shown. "
        "Use it to see the task's bar, logic and card.",
    ):
        open_task(code)


def status_style(frame: pd.DataFrame, column: str = "status"):
    """Styler drawing the status column as labels (pass green, fail red…), capitalised."""
    out = frame.copy()
    out[column] = out[column].map(status_label)
    # white text on a STATUS colour (>= 4.5:1): a label carries its own background, so it reads the
    # same on the light and the dark theme without a redraw
    background_of_label = {style.label: STATUS[style.tone] for style in STATUS_STYLE.values()}

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
    """Rows where any of ``columns`` contains ``text``, ignoring case and accents
    (analysis.task_filters.search_mask)."""
    return _search_mask(frame, columns, text)
