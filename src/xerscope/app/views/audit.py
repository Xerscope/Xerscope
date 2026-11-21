"""Audit one check: the sets behind its count, and the check re-run with other settings.

The settings changed here (target, x threshold, populations) apply to this page only and to
this session: Schedule health keeps reporting the loaded standards. The block under
"Calculation sheet" is how a change becomes permanent, in a standard file.
"""

import streamlit as st

from xerscope.analysis.audit import (
    TARGET_FORMS,
    choices,
    form_rows,
    has_same_settings,
    is_list,
    kept_params,
    settings_table,
    sheet,
    toml_block,
    with_settings,
)
from xerscope.analysis.checks import results_frame
from xerscope.analysis.explain import explain, settings_lines
from xerscope.analysis.rules import RULES, is_read
from xerscope.app import ui
from xerscope.app.explanation_panel import show_calculation, show_method
from xerscope.app.sets import show_funnel, show_sets
from xerscope.app.state import (
    baseline_for,
    baseline_warnings,
    metric_result,
    page_header,
    require_store,
    snapshot_picker,
    sources_of,
    standards,
)

# Streamlit drops a widget's value once its page is left: the audit settings are kept here,
# in the session only, so they survive a visit to another page until Reset.
SAVED = "audit_settings"
PARAMETERS_BLOCK, TARGET_BLOCK = "Rule parameters", "Target"


def parameter_widget(rule_name: str, name: str, current, key: str):
    """Draw one parameter by what it accepts (several names, one of a list, yes / no, a number); return its value."""
    allowed = choices(rule_name, name)
    if is_list(rule_name, name):
        return st.multiselect(name, allowed or list(current), default=list(current), key=key)
    if allowed is not None:
        return st.selectbox(name, allowed, index=allowed.index(current), key=key)
    if isinstance(current, bool):
        return st.checkbox(name, value=current, key=key)
    return st.number_input(name, value=float(current), format="%g", key=key)  # %g: 44, not 44.00


def draw_row(metric, prefix: str, row: tuple[str, ...], values: dict, saved: dict) -> None:
    """Draw the parameters of one row that the rule reads with the ``values`` picked so far, and add theirs.

    A parameter the rule does not read (``value_max`` without a band) is not drawn and gets no value.
    """
    columns = iter(st.columns(len(row)))
    for name in (name for name in row if is_read(name, values)):  # read one at a time: the operator decides
        key = f"{prefix}:{name}"
        current = saved.get(key, metric.params.get(name, RULES[metric.rule].params[name]))
        with next(columns):
            values[name] = saved[key] = parameter_widget(metric.rule, name, current, key)


def parameters_form(metric, prefix: str, saved: dict) -> dict:
    """Draw the parameters of the rule row by row; return the value of each one the rule reads.

    The check and its TOML block then never hold a value that is ignored.
    """
    values: dict[str, object] = {}
    for row in form_rows(metric.rule):
        draw_row(metric, prefix, row, values, saved)
    return values


def settings_form(metric, prefix: str) -> tuple[str, dict]:
    """Draw the parameters of the rule, then the target: two blocks, because they are two questions.

    The widgets start from the standard's values, or from those this session picked.
    """
    saved = st.session_state.setdefault(SAVED, {})
    values = {}
    if RULES[metric.rule].params:
        ui.block(PARAMETERS_BLOCK, "Which items the rule checks and which it counts.")
        values = parameters_form(metric, prefix, saved)
    ui.block(TARGET_BLOCK, f"The result that passes. Written as: {TARGET_FORMS}.")
    target = st.text_input(
        TARGET_BLOCK,  # named by the block's title: the label is not drawn twice
        saved.get(f"{prefix}:target", metric.threshold_label),
        key=f"{prefix}:target",
        label_visibility="collapsed",
    )
    saved[f"{prefix}:target"] = target
    return target, kept_params(metric, values)


def forget_settings(prefix: str) -> None:
    """Drop what the widgets of this check hold and what the session kept of them."""
    for held in (st.session_state, st.session_state.get(SAVED, {})):
        for key in [key for key in held if str(key).startswith(f"{prefix}:")]:
            del held[key]


def reset_button(prefix: str) -> None:
    """Put every setting of this check back to the standard's."""
    if st.button("Reset", icon=":material/restart_alt:", key=f"{prefix}:reset", help="Back to the standard's values"):
        forget_settings(prefix)
        st.rerun()


def show_results(standard_result, audit_result) -> None:
    changed = audit_result is not standard_result
    standard_row = results_frame([standard_result]).iloc[0]
    audit_row = results_frame([audit_result]).iloc[0]
    items = [
        (
            "Standard",
            standard_row["result"],
            standard_row["count"] or None,
            "As the loaded standard sets it",
        ),
        (
            "Standard status",
            ui.status_label(standard_result.status),
            None,
            f"Target {standard_result.metric.threshold_label}",
        ),
    ]
    if changed:
        items += [
            ("Audit", audit_row["result"], audit_row["count"] or None, "With the settings of this page"),
            (
                "Audit status",
                ui.status_label(audit_result.status),
                None,
                f"Target {audit_result.metric.threshold_label}",
            ),
        ]
    ui.kpis(items)


def show_explanation(result) -> None:
    explanation = explain(result)
    left, right = st.columns([3, 2], gap="large")
    with left:
        show_calculation(result, explanation)
    with right:
        show_method(result.metric, explanation)


def show_sheet(standard, metric) -> None:
    """How the check is set and where to change it for good."""
    with st.expander("Settings: how to change this check for good"):
        text_column = {"now": st.column_config.TextColumn("now")}  # ui.COLUMNS has a "now" that is a date
        ui.table(
            settings_table(metric, standard[metric.id]), raw_labels=True, overrides=text_column, key="sheet_settings"
        )
        where = standard.path or f"the built-in standards/{standard.id.lower()}.toml"
        st.markdown(
            f"Replace the `[[metric]]` table with id `{metric.id}` in **{ui.md_text(where)}**, or copy the whole "
            "file into a folder of your own standards (`xerscope app --standards <folder>`, or upload it on "
            "Schedule health) with a new standard id. Thresholds are in the unit the parameter names "
            "(`limit_hours`: hours as P6 stores them; `limit_days`: working days of each task's calendar)."
        )
        st.code(toml_block(metric), language="toml")
        st.caption(
            "After a change, run `uv run pytest tests/test_rules.py tests/test_calendar_and_standards.py` "
            "and `xerscope check FILE.xer --standard <id>` to see the new counts."
        )


store = require_store()
available = standards()
top = st.container()
# the standards on a row of their own (as on Schedule health): in a column their names were cut
standard_id = st.segmented_control(
    "Standard", list(available), format_func=lambda key: available[key].name, key="audit_std"
)
snapshot_column, check_column = st.columns(2, vertical_alignment="bottom")
with snapshot_column:
    snapshot = snapshot_picker(store, "Update", key="audit_snap")
baseline = baseline_for(snapshot)
with top:
    page_header(
        "Audit",
        store,
        snapshot,
        lead="The sets behind a check, and the check re-run with other settings. Changes here stay on this "
        "page: Schedule health keeps the loaded standards.",
    )
    baseline_warnings(snapshot, baseline)
if standard_id is None:
    st.info("Pick a standard, then a check.", icon=":material/fact_check:")
    st.stop()
standard = available[standard_id]
with check_column:
    metric_id = st.selectbox(
        "Check",
        [metric.id for metric in standard.metrics],
        index=None,
        format_func=lambda key: f"{key} · {standard[key].name}",
        key=f"audit_check:{standard_id}",
    )
if metric_id is None:
    st.info("Pick a check.", icon=":material/fact_check:")
    st.stop()

metric = standard[metric_id]
prefix = f"audit:{standard_id}:{metric_id}"
SOURCES = sources_of(snapshot, baseline=baseline)  # the files a download of this page comes from

title_column, reset_column = st.columns([5, 1], vertical_alignment="bottom")
with title_column:
    ui.section("Settings for this audit", "Start from the standard's values; the check reruns on every change.")
with reset_column:
    reset_button(prefix)
target, params = settings_form(metric, prefix)
try:
    audited = with_settings(metric, target, params)
except ValueError as exc:
    st.error(str(exc), icon=":material/block:")
    st.stop()
st.info("  \n".join(settings_lines(audited)), icon=":material/rule:")

standard_result = metric_result(metric, snapshot, store)
# through the session's cache, like the standard's: a redraw that changes no setting computes nothing
audit_result = standard_result if has_same_settings(audited, metric) else metric_result(audited, snapshot, store)

show_results(standard_result, audit_result)
written = sheet(standard.id, metric)
if written is not None:
    with st.expander("Calculation sheet: population, fields, sources, worked example"):
        st.markdown(written)
ui.section("Calculation", "With the settings of this page.")
show_explanation(audit_result)
ui.section("Sets", "Every item the check looked at, so the count can be redone by hand.")
show_funnel(audit_result, snapshot, SOURCES)
show_sets(audit_result, snapshot, SOURCES)
show_sheet(standard, audited)
