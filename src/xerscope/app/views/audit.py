"""Audit one check: the sets behind its count, and the check re-run with other settings.

The settings changed here (target, x threshold, populations) apply to this page only and to
this session: Schedule health keeps reporting the loaded standards. The block under
"Calculation sheet" is how a change becomes permanent, in a standard file.
"""

import pandas as pd
import streamlit as st

from xerscope.analysis import AnalysisContext
from xerscope.analysis.audit import choices, is_list, sheet, split, toml_block, with_settings
from xerscope.analysis.checks import run_metric
from xerscope.analysis.explain import explain, fmt_value, noun
from xerscope.analysis.populations import STEP_SOURCES, flagged_activities, flagged_relationships
from xerscope.analysis.rules import RULES
from xerscope.app import ui
from xerscope.app.state import baseline_for, csv_download, memo, require_store, snapshot_picker, sources_of, standards


def value_text(result) -> str:
    return "–" if result.status in ("n/a", "error") else fmt_value(result.value, result.metric.unit)


def count_text(result) -> str:
    if result.numerator is not None and result.denominator is not None:
        return f"{result.numerator} / {result.denominator}"
    return "" if result.numerator is None else str(result.numerator)


def target_label(metric) -> str:
    return "info" if metric.comparator is None else metric.threshold_label


# Streamlit drops a widget's value once its page is left: the audit settings are kept here,
# in the session only, so they survive a visit to another page until Reset.
SAVED = "audit_settings"


def settings_form(metric, prefix: str) -> tuple[str, dict]:
    """Target and parameters as widgets, starting from the standard's values or this session's."""
    rule = RULES[metric.rule]
    saved = st.session_state.setdefault(SAVED, {})
    target = st.text_input(
        "Target",
        saved.get(f"{prefix}:target", target_label(metric)),
        key=f"{prefix}:target",
        help="e.g. < 5%, <= 0, >= 0.95, pass, info",
    )
    saved[f"{prefix}:target"] = target
    params = {}
    for name, default in rule.params.items():
        key = f"{prefix}:{name}"
        current = saved.get(key, metric.params.get(name, default))
        allowed = choices(metric.rule, name)
        if is_list(metric.rule, name):
            params[name] = st.multiselect(name, allowed or list(current), default=list(current), key=key)
        elif allowed is not None:
            params[name] = st.selectbox(name, allowed, index=allowed.index(current), key=key)
        elif isinstance(current, bool):
            params[name] = st.checkbox(name, value=current, key=key)
        else:
            params[name] = st.number_input(name, value=float(current), key=key)
        saved[key] = params[name]
    # only what the standard sets or this page changes goes into the metric, as a standard file would hold it
    params = {name: list(value) if isinstance(value, (list, tuple)) else value for name, value in params.items()}
    defaults = {name: list(value) if isinstance(value, tuple) else value for name, value in rule.params.items()}
    return target, {name: value for name, value in params.items() if value != defaults[name] or name in metric.params}


def show_results(standard_result, audit_result) -> None:
    changed = audit_result is not standard_result
    items = [
        (
            "Standard",
            value_text(standard_result),
            count_text(standard_result) or None,
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
            ("Audit", value_text(audit_result), count_text(audit_result) or None, "With the settings of this page"),
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
        with st.container(border=True):
            st.caption("Calculation")
            st.markdown(f"#### {explanation.formula}")
            st.markdown(explanation.verdict)
        if explanation.population:
            st.markdown("**Population**")
            st.markdown("\n".join(f"- {line}" for line in explanation.population))
        if result.note and result.note not in explanation.formula:
            st.markdown(f"**Note** · {ui.md_text(result.note)}")
    with right:
        st.markdown("**Method**")
        st.caption(explanation.method.replace("``", "`"))
        if result.metric.source:
            source = result.metric.source
            st.caption("Source: " + (f"[{source}]({source})" if source.startswith("http") else source))


def show_set(frame: pd.DataFrame, title: str, filename: str, key: str) -> None:
    if frame.empty:
        st.caption(f"No {title.lower()}.")
        return
    ui.table(frame, max_height=480, key=f"table_{key}")
    # anonymised or raw as the sidebar switch says; only the files behind this result are read
    csv_download(frame, filename, "Download CSV", key=f"dl_{key}", sources=SOURCES)


def funnel_table(result) -> pd.DataFrame:
    """Start, one row per population step (rows removed, rows left), then the counted items."""
    funnel = result.funnel
    rows = [{"step": "start", "source": "", "removed": None, "left": funnel.start}]
    rows += [
        {"step": step.label, "source": step.source, "removed": len(step.removed), "left": step.left}
        for step in funnel.steps
    ]
    rows.append({"step": "counted", "source": "", "removed": None, "left": result.numerator})
    return pd.DataFrame(rows)


def show_funnel(result, snapshot) -> None:
    """How the denominator was cut from the file, step by step, each step with the text it follows."""
    funnel = result.funnel
    if funnel is None:
        return
    st.markdown("**Population, step by step**")
    ui.table(
        funnel_table(result),
        raw_labels=True,
        key="funnel",
        overrides={name: st.column_config.NumberColumn(name, format="%d") for name in ("removed", "left")},
    )
    used = sorted({step.source for step in funnel.steps})
    if used:
        st.caption(
            " · ".join(
                f"[{key}]({STEP_SOURCES[key]})"
                if STEP_SOURCES[key].startswith("http")
                else f"{key}: {STEP_SOURCES[key]}"
                for key in used
            )
        )
    removing = [step for step in funnel.steps if not step.removed.empty]
    if not removing:
        return
    label = st.selectbox(
        "Rows removed by", [step.label for step in removing], index=None, key=f"funnel_step:{result.metric.id}"
    )
    if label is not None:
        step = next(step for step in removing if step.label == label)
        subject = "relationships" if "pred_code" in step.removed.columns else "activities"
        frame = flagged_relationships(step.removed) if subject == "relationships" else flagged_activities(step.removed)
        show_set(
            frame, f"{subject} removed", f"{result.metric.id}_{ui.stamp(snapshot.data_date)}_removed.csv", "removed"
        )


def show_sets(result, snapshot) -> None:
    show_funnel(result, snapshot)
    sets = split(result, snapshot)
    if sets is None:
        st.caption("This check has no population to list (a ratio or a pass/fail test).")
        return
    stamp = f"{result.metric.id}_{ui.stamp(snapshot.data_date)}"
    labels = [
        f"Counted ({result.numerator if result.numerator is not None else len(sets.counted)})",
        f"Checked, not counted ({len(sets.not_counted)})",
    ]
    if sets.excluded is not None:
        labels.append(f"Excluded ({len(sets.excluded)})")
    tabs = st.tabs(labels)
    with tabs[0]:
        if sets.counted_outside:
            st.caption(
                f"{sets.counted_outside} {noun(sets.subject, sets.counted_outside)} counted here are not in the "
                "checked set (the numerator is not a part of the denominator for this check)."
            )
        show_set(sets.counted, "Counted items", f"{stamp}_counted.csv", "counted")
    with tabs[1]:
        show_set(sets.not_counted, "Checked items not counted", f"{stamp}_not_counted.csv", "not_counted")
    if sets.excluded is not None:
        with tabs[2]:
            st.caption(f"The file's {sets.subject} outside the checked set; their status and type say why.")
            show_set(sets.excluded, "Excluded items", f"{stamp}_excluded.csv", "excluded")


def show_sheet(standard, metric) -> None:
    """How the check is set and where to change it for good."""
    rule = RULES[metric.rule]
    with st.expander("Settings: how to change this check for good"):
        rows = [
            {
                "setting": "target",
                "now": target_label(metric),
                "default": target_label(standard[metric.id]),
                "accepts": "< x%, <= x%, > x%, >= x% (unit %), <= n (count), >= r (ratio), pass, info",
            }
        ] + [
            {
                "setting": name,
                "now": str(metric.params.get(name, default)),
                "default": str(default),
                "accepts": ", ".join(map(str, choices(metric.rule, name) or []))
                or ("true / false" if isinstance(default, bool) else "a number"),
            }
            for name, default in rule.params.items()
        ]
        ui.table(pd.DataFrame(rows), raw_labels=True, key="sheet_settings")
        where = standard.path or f"the built-in standards/{standard.id.lower()}.toml"
        st.markdown(
            f"Replace the `[[metric]]` table with id `{metric.id}` in **{ui.md_text(where)}**, or copy the whole "
            "file into a folder of your own standards (`xerscope app --standards <folder>`, or upload it on "
            "Schedule health) with a new standard id. Thresholds are in the unit the parameter names "
            "(`limit_hours`: hours as P6 stores them; `limit_days`: working days of each activity's calendar)."
        )
        st.code(toml_block(metric), language="toml")
        st.caption(
            "After a change, run `uv run pytest tests/test_rules.py tests/test_calendar_and_standards.py` "
            "and `xerscope check FILE.xer --standard <id>` to see the new counts."
        )


store = require_store()
available = standards()
top = st.container()
standard_column, snapshot_column, check_column = st.columns([3, 2, 3], vertical_alignment="bottom")
with standard_column:
    standard_id = st.segmented_control(
        "Standard", list(available), format_func=lambda key: available[key].name, key="audit_std"
    )
with snapshot_column:
    snapshot = snapshot_picker(store, "Update", key="audit_snap")
baseline = baseline_for(snapshot)
with top:
    ui.header(
        "Audit",
        store,
        snapshot,
        baseline,
        lead="The sets behind a check, and the check re-run with other settings. Changes here stay on this "
        "page: Schedule health keeps the loaded standards.",
    )
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
context = AnalysisContext(snapshot, store, baseline)
baseline_key = st.session_state.get("bl_choice"), baseline.label if baseline else None

ui.section("Settings for this audit", "Start from the standard's values; the check reruns on every change.")
form_column, reset_column = st.columns([5, 1], vertical_alignment="bottom")
with form_column:
    target, params = settings_form(metric, prefix)
with reset_column:
    if st.button("Reset", icon=":material/restart_alt:", key=f"{prefix}:reset"):
        for key in [key for key in st.session_state if str(key).startswith(f"{prefix}:")]:
            del st.session_state[key]
        saved = st.session_state.get(SAVED, {})
        for key in [key for key in saved if key.startswith(f"{prefix}:")]:
            del saved[key]
        st.rerun()
try:
    audited = with_settings(metric, target, params)
except ValueError as exc:
    st.error(str(exc), icon=":material/block:")
    st.stop()

standard_result = memo(
    ("audit", repr(metric), snapshot.source, str(snapshot.data_date), baseline_key), run_metric, metric, context
)
same = (audited.params, audited.comparator, audited.threshold) == (metric.params, metric.comparator, metric.threshold)
audit_result = standard_result if same else run_metric(audited, context)

show_results(standard_result, audit_result)
written = sheet(standard.id, metric)
if written is not None:
    with st.expander("Calculation sheet: population, fields, sources, worked example"):
        st.markdown(written)
ui.section("Calculation", "With the settings of this page.")
show_explanation(audit_result)
ui.section("Sets", "Every item the check looked at, so the count can be redone by hand.")
show_sets(audit_result, snapshot)
show_sheet(standard, audited)
