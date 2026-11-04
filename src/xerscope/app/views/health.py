from functools import partial

import pandas as pd
import streamlit as st

from xerscope.analysis import (
    AnalysisContext,
    builtin_standards,
    compare_counts,
    health_history,
    loads_standard,
    results_frame,
    run_standard,
    template_text,
)
from xerscope.analysis.checks import health_wide
from xerscope.analysis.explain import explain, noun
from xerscope.analysis.rules import ACTIVITY_COLS, LINK_COLS
from xerscope.app import ui
from xerscope.app.state import (
    baseline_for,
    csv_download,
    downloads_ready,
    memo,
    require_store,
    snapshot_picker,
    sources_of,
    standards,
)
from xerscope.viz.charts import build_metric_trend

IDENTITY_COLUMNS = ("task_code", "task_name", "pred_code", "pred_name", "succ_code", "succ_name", "type")


def typeset(target: str) -> str:
    return target.replace("<=", "≤").replace(">=", "≥")


def check_label(standard, metric_id: str) -> str:
    return f"{metric_id} · {standard[metric_id].name}"


def culprits_first(frame: pd.DataFrame) -> pd.DataFrame:
    """ID and name, then the columns this check adds (reason, BL finish, variance…), then the rest."""
    identity = [column for column in IDENTITY_COLUMNS if column in frame.columns]
    extra = [column for column in frame.columns if column not in ACTIVITY_COLS + LINK_COLS]
    return frame[identity + extra + [column for column in frame.columns if column not in identity + extra]]


def show_kpis(results) -> None:
    counts = pd.Series([result.status for result in results]).value_counts()
    scored = int(counts.get("pass", 0) + counts.get("fail", 0))
    ui.kpis(
        [
            ("Checks passed", f"{int(counts.get('pass', 0))} / {scored}", None, "Checks with a target that meet it"),
            ("Checks failed", int(counts.get("fail", 0)), None, "Checks with a target that miss it"),
            ("For review", int(counts.get("info", 0)), None, "Reported without a pass/fail target"),
            (
                "Not applicable",
                int(counts.get("n/a", 0) + counts.get("error", 0)),
                None,
                "No population, or no baseline",
            ),
        ]
    )


def show_summary(results, standard, snapshot, sources: list[str]) -> None:
    summary = results_frame(results).assign(flagged=[len(result.flagged) for result in results])
    summary["target"] = summary["target"].map(typeset)
    summary = summary[["status", "id", "group", "check", "result", "count", "target", "flagged"]]
    if not summary["group"].astype(bool).any():
        summary = summary.drop(columns="group")

    ui.section(
        "Results",
        "One row per check, in the standard's order. "
        "Open a check below for its calculation and the activities behind it.",
    )
    ui.table(
        summary,
        status="status",
        max_height=700,
        overrides={"flagged": st.column_config.NumberColumn("Items listed", format="%d")},
    )

    # Every flagged item of every check in one file: the audit trail behind the scores.
    trail = pd.concat(
        [
            result.flagged.assign(check_id=result.metric.id, check=result.metric.name, check_status=result.status)
            for result in results
            if not result.flagged.empty
        ]
        or [pd.DataFrame()],
        ignore_index=True,
    )
    summary_column, trail_column, _ = st.columns([1, 1.3, 4])
    with summary_column:
        # check names, targets and results only, no schedule data: the same with the switch on or off
        csv_download(
            summary,
            f"{standard.id}_{ui.stamp(snapshot.data_date)}_summary.csv",
            "Summary (CSV)",
            key="dl_sum",
            sensitive=False,
        )
    with trail_column:
        if trail.empty:
            return
        front = ["check_id", "check", "check_status"]
        csv_download(
            trail[front + [column for column in trail.columns if column not in front]],
            f"{standard.id}_{ui.stamp(snapshot.data_date)}_flagged.csv",
            "All flagged items (CSV)",
            key="dl_trail",
            sources=sources,
        )


def show_check(result, explanation, snapshot, expanded: bool, sources: list[str]) -> None:
    """One expander: what the check measures, its calculation, method and the flagged items."""
    metric = result.metric
    row = results_frame([result]).iloc[0]
    counts = f" ({row['count']})" if result.numerator is not None and result.denominator else ""
    value = "n/a" if result.status in ("n/a", "error") else row["result"]
    label = (
        f"{ui.STATUS_STYLE[result.status].mark}  {metric.id} · **{metric.name}** — {value}{counts}"
        f" · target {typeset(row['target'])}"
    )
    with st.expander(label, expanded=expanded):
        left, right = st.columns([3, 2], gap="large")
        with left:
            st.markdown(f"**What it measures** · {explanation.measured}")
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
            if explanation.parameters:
                st.markdown("**Parameters**")
                ui.table(pd.DataFrame(explanation.parameters, columns=["parameter", "value", "set by"]), max_height=260)
            if metric.source:
                st.caption(
                    "Source: "
                    + (f"[{metric.source}]({metric.source})" if metric.source.startswith("http") else metric.source)
                )

        if result.flagged.empty:
            st.caption("No item listed for this check.")
        else:
            st.markdown(
                f"**{explanation.flagged_label}** · {len(result.flagged)} "
                f"{noun(explanation.subject, len(result.flagged))}"
            )
            ui.table(culprits_first(result.flagged), max_height=420, key=f"flag_{metric.id}")
            if not downloads_ready(sources):
                st.caption("Download: prepare the anonymised downloads under Results.")
            else:
                csv_download(
                    result.flagged,
                    f"{metric.id}_{ui.stamp(snapshot.data_date)}.csv",
                    "Download list (CSV)",
                    key=f"dl_{metric.id}",
                    sources=sources,
                )


def show_details(results, snapshot, only_failed: bool, sources: list[str]) -> None:
    ui.section("Detail by check")
    expand_all = st.toggle("Expand all", value=False, key="health_expand")
    group = None
    for result in results:
        if only_failed and result.status != "fail":
            continue
        if result.metric.group and result.metric.group != group:
            group = result.metric.group
            st.markdown(f"##### {group}")
        show_check(result, explain(result), snapshot, expand_all, sources)


def show_trend(store, standard) -> None:
    ui.section("Trend across updates", "The same check on every loaded update, against its target.")
    history = memo(("health", repr(standard)), health_history, store, standard, baseline_for)
    metric_ids = [metric.id for metric in standard.metrics]
    metric_id = st.selectbox("Check", metric_ids, key="health_trend_metric", format_func=partial(check_label, standard))
    metric = standard[metric_id]
    st.plotly_chart(
        build_metric_trend(
            history[history["id"] == metric_id],
            metric.name,
            metric.threshold,
            metric.threshold_label,
            metric.unit,
        ),
        width="stretch",
    )
    by_update = health_wide(history, standard)
    with st.expander("All checks, all updates"):
        ui.table(
            by_update,
            max_height=640,
            # dates follow the id and check columns
            overrides={name: st.column_config.NumberColumn(name, format="%.2f") for name in by_update.columns[2:]},
        )


def show_report_comparison(results, standard) -> None:
    """Counts typed from a P6 Check Schedule report (or its id,found,total CSV) against this
    page's results, on the update and baseline picked above. Nothing typed is kept on the server."""
    with st.expander("Compare with a P6 Check Schedule report"):
        st.markdown(
            "Type the report's *found* and *total* for each check, or upload them as a CSV "
            "(`id,found,total`). Lines left empty are not compared. Run the report on the same "
            "update and baseline as this page."
        )
        got = results_frame(results)
        upload = st.file_uploader("Report counts (.csv)", type=["csv"], key=f"report_csv_{standard.id}")
        if upload is not None:
            try:
                typed = pd.read_csv(upload, dtype={"id": str}).rename(columns=str.strip)
                missing = {"id", "found", "total"} - set(typed.columns)
                if missing:
                    st.error(f"Columns missing: {', '.join(sorted(missing))}")
                    return
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(f"Unreadable CSV: {exc}")
                return
            typed = got[["id", "check"]].merge(typed[["id", "found", "total"]], on="id", how="left")
        else:
            typed = got[["id", "check"]].assign(found=pd.NA, total=pd.NA).astype({"found": "Int64", "total": "Int64"})
        edited = st.data_editor(
            typed,
            disabled=["id", "check"],
            hide_index=True,
            column_config={
                "found": st.column_config.NumberColumn("Found (report)", min_value=0, step=1),
                "total": st.column_config.NumberColumn("Total (report)", min_value=0, step=1),
            },
            key=f"report_counts_{standard.id}_{upload.file_id if upload else 'typed'}",  # a new upload resets the edits
        )
        compared = compare_counts(got, edited)
        if compared.empty:
            return
        bad = int((~compared["match"]).sum())
        if bad:
            st.error(f"{bad} of {len(compared)} checks differ from the report", icon=":material/error:")
        else:
            st.success(f"All {len(compared)} checks match the report", icon=":material/check_circle:")
        ui.table(
            compared,
            overrides={
                "found_exp": st.column_config.NumberColumn("Found (report)", format="%d"),
                "found": st.column_config.NumberColumn("Found (xerscope)", format="%d"),
                "total_exp": st.column_config.NumberColumn("Total (report)", format="%d"),
                "total": st.column_config.NumberColumn("Total (xerscope)", format="%d"),
                "match": st.column_config.CheckboxColumn("Match"),
            },
        )


def show_own_standard() -> None:
    with st.expander("Use your own standard"):
        st.markdown(
            "A standard is a TOML file: each check picks a rule, its parameters and a target. "
            "Start from the template, edit it, upload it here (or put it in the folder given to "
            "`xerscope app --standards`)."
        )
        st.download_button(
            "Download the template",
            template_text().encode("utf-8"),
            "my-standard.toml",
            "application/toml",
            icon=":material/download:",
        )
        upload = st.file_uploader("Upload a standard (.toml)", type=["toml"], key="std_upload")
        if upload is not None:
            try:
                custom = loads_standard(upload.getvalue(), upload.name)
                if custom.id in builtin_standards():
                    raise ValueError(f"{upload.name}: id {custom.id!r} is a built-in standard's; give yours another id")
                st.session_state.setdefault("uploaded_standards", {})[custom.id] = custom
                st.success(f"Loaded {custom.name} ({len(custom.metrics)} checks): pick it above.")
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(str(exc))
        for error in st.session_state.get("standard_errors", []):
            st.error(error)


store = require_store()
available = standards()


def standard_name(standard_id: str) -> str:
    return available[standard_id].name


top = st.container()  # title and context, filled once the update is picked

standard_column, snapshot_column, failed_column = st.columns([4, 2.2, 1.3], vertical_alignment="bottom")
with standard_column:
    standard_id = st.segmented_control(
        "Standard",
        list(available),
        default="P6" if "P6" in available else None,
        format_func=standard_name,
        key="health_std",
    )
with snapshot_column:
    snapshot = snapshot_picker(store, "Update", key="health_snap")
with failed_column:
    only_failed = st.toggle("Failed checks only", value=False, key="health_failed")
standard = available[standard_id or next(iter(available))]
baseline = baseline_for(snapshot)

with top:
    ui.header("Schedule health", store, snapshot, baseline)
reference = f" · [reference]({standard.source})" if standard.source.startswith("http") else ""
st.caption((standard.description or standard.name) + reference)
if baseline is None:
    st.warning(
        "No baseline selected: checks against the baseline (late activities, BEI, missed tasks) "
        "are not applicable. Pick one in the sidebar.",
        icon=":material/info:",
    )

# memoised per (data set, standard, update, baseline): the DECM critical path test alone
# takes ~2 s on a 4,000-activity file, and every widget change reruns the page
results = memo(
    ("health_results", repr(standard), snapshot.source, str(snapshot.data_date)),
    run_standard,
    standard,
    AnalysisContext(snapshot, store, baseline),
)
show_kpis(results)
sources = sources_of(snapshot, baseline=baseline)  # the files the lists come from
show_summary(results, standard, snapshot, sources)
show_details(results, snapshot, only_failed, sources)
if len(store) > 1:
    show_trend(store, standard)

if baseline is not None:
    missing = sorted(set(snapshot.activities["task_code"]) - set(baseline.frame.index))
    if missing:
        st.caption(
            f"{len(missing)} activities are not in the baseline: "
            f"{ui.md_text(', '.join(missing[:10]))}{'…' if len(missing) > 10 else ''}"
        )

show_report_comparison(results, standard)
show_own_standard()
