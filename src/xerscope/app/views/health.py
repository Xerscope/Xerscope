from functools import partial

import pandas as pd
import streamlit as st

from xerscope.analysis import (
    builtin_standards,
    compare_counts,
    health_history,
    loads_standard,
    results_frame,
    template_text,
)
from xerscope.analysis.audit import by_check, sets_long
from xerscope.analysis.checks import health_wide, standard_score
from xerscope.analysis.explain import explain, noun
from xerscope.analysis.rules import ACTIVITY_COLS, LINK_COLS
from xerscope.app import ui
from xerscope.app.sets import show_sets
from xerscope.app.state import (
    SNAP_CHOICE,
    anonymous_exports,
    baseline_for,
    baseline_warnings,
    csv_download,
    data_identity,
    downloads_ready,
    fetch,
    go_to,
    held,
    hold,
    memo,
    metric_result,
    open_in_gantt,
    page_header,
    require_store,
    show_download,
    snapshot_picker,
    sources_of,
    standard_results,
    standards,
)
from xerscope.export import zip_frames
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


def show_kpis(results, standard) -> None:
    ui.score_cards({standard.name: standard_score(results)})
    counts = pd.Series([result.status for result in results]).value_counts()
    scored = int(counts.get("pass", 0) + counts.get("fail", 0))
    ui.kpis(
        [
            ("Checks passed", f"{int(counts.get('pass', 0))} / {scored}", None, "Checks with a target that meet it"),
            ("Checks failed", int(counts.get("fail", 0)), None, "Checks with a target that miss it"),
            ("For review", int(counts.get("info", 0)), None, "Reported without a pass/fail target"),
            ("Not applicable", int(counts.get("n/a", 0)), None, "No population, or no baseline"),
            # a rule that raised: a defect of the check, shown apart from n/a, only when there is one
            *(
                [("Errors", int(counts["error"]), None, "Checks that could not be computed: see their note")]
                if counts.get("error", 0)
                else []
            ),
        ]
    )


def show_summary(results, standard, snapshot, baseline, sources: list[str]) -> None:
    full = results_frame(results).assign(flagged=[len(result.flagged) for result in results])
    full["note"] = [result.note_with_baseline for result in results]  # the export names the baseline
    full["target"] = full["target"].map(typeset)
    columns = ["status", "id", "group", "check", "result", "count", "target", "flagged"]
    if not full["group"].astype(bool).any():
        columns.remove("group")
    summary = full[columns]

    ui.section(
        "Results",
        "One row per check, in the standard's order. Open a check below for its calculation and the tasks behind it.",
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
    summary_column, trail_column, sets_column, _ = st.columns([1, 1.3, 1.6, 3])
    with sets_column:  # first, so that the Prepare click also readies the downloads beside it
        prepare_sets(results, standard, snapshot, baseline, sources)
    with summary_column:
        # the notes name activities and files: anonymised like the lists
        csv_download(
            full[[*columns, "note"]],
            f"{standard.id}_{ui.stamp(snapshot.data_date)}_summary.csv",
            "Summary (CSV)",
            key="dl_sum",
            sources=sources,
        )
    with trail_column:
        if not trail.empty:
            front = ["check_id", "check", "check_status"]
            csv_download(
                trail[front + [column for column in trail.columns if column not in front]],
                f"{standard.id}_{ui.stamp(snapshot.data_date)}_flagged.csv",
                "All flagged items (CSV)",
                key="dl_trail",
                sources=sources,
            )


def prepare_sets(results, standard, snapshot, baseline, sources: list[str]) -> None:
    """All sets of the standard as one CSV (a row per item) and as one CSV per check in a zip,
    built when the button is pressed, anonymised or not as the sidebar switch says."""
    anonymous = anonymous_exports()
    # what the sets are built from, as metric_result's key: files, projects, baseline, standard, update
    tag = (*data_identity(ev_basis=False), repr(standard), snapshot.source, str(snapshot.data_date), anonymous)
    if st.button(
        "Prepare all sets",
        icon=":material/folder_zip:",
        key="sets_build",
        help="Counted, checked and excluded items of every check of this standard, as the Audit page lists them.",
    ):
        table = sets_long(results, snapshot)
        per_check = by_check(table)
        csv_file = fetch(
            st.session_state,
            lambda: table.to_csv(index=False).encode("utf-8-sig"),
            lambda anonymizer: anonymizer.csv(table),
            sources,
            prepare=True,
        )
        zip_file = fetch(
            st.session_state,
            lambda: zip_frames(per_check, "csv"),
            lambda anonymizer: zip_frames({name: anonymizer.frame(frame) for name, frame in per_check.items()}, "csv"),
            sources,
            prepare=True,
        )
        hold(st.session_state, "health_sets_csv", tag, csv_file)
        hold(st.session_state, "health_sets_zip", tag, zip_file)
    stamp = f"{standard.id}_{ui.stamp(snapshot.data_date)}"
    for slot, label, name, mime in (
        ("health_sets_csv", "All sets (CSV)", f"{stamp}_sets.csv", "text/csv"),
        ("health_sets_zip", "All sets (ZIP)", f"{stamp}_sets.zip", "application/zip"),
    ):
        built = held(st.session_state, slot, tag)
        if built is not None:
            show_download(built, label, name, mime, key=f"dl_{slot}")


@st.fragment
def show_check_sets(results, standard, snapshot, sources: list[str]) -> None:
    """Nothing is listed until a check is picked: its Counted / Checked, not counted / Excluded sets."""
    ids = [result.metric.id for result in results]
    chosen = st.selectbox(
        "Show the sets of",
        ids,
        index=None,
        placeholder="Pick a check to list the items it counted, checked and excluded",
        format_func=lambda key: f"{key} · {next(r.metric.name for r in results if r.metric.id == key)}",
        key=f"health_sets_check:{standard.id}",
    )
    if chosen is not None:
        show_sets(next(result for result in results if result.metric.id == chosen), snapshot, sources, f"{chosen}:")


def flagged_codes(flagged: pd.DataFrame) -> list[str]:
    """The Activity IDs a check's list names: its tasks, or both ends of its links."""
    codes: list[str] = []
    for column in ("task_code", "pred_code", "succ_code"):
        if column in flagged.columns:
            codes += [str(code) for code in flagged[column].dropna() if not str(code).startswith("[ext]")]
    return list(dict.fromkeys(codes))


def show_links(result, snapshot, standard) -> None:
    """Where to go next with this check: the Gantt on the tasks it lists, the Audit on its sets."""
    metric = result.metric
    codes = flagged_codes(result.flagged)
    with st.container(horizontal=True, gap="small"):
        if codes and st.button(
            f"Show the {len(codes)} tasks in the Gantt",
            icon=":material/view_timeline:",
            key=f"gantt_{metric.id}",
            help="The Gantt filtered on the tasks this check lists, on this update",
        ):
            go_to(
                "gantt",
                gantt_focus={"codes": codes, "label": f"{metric.id} · {metric.name}"},
                gantt_node=None,
                gantt_task=None,
                **{SNAP_CHOICE: snapshot.label},
            )
        if st.button(
            "Audit this check",
            icon=":material/manage_search:",
            key=f"audit_{metric.id}",
            help="The sets it counted, checked and excluded, and the check re-run with other settings",
        ):
            go_to(
                "audit",
                audit_std=standard.id,
                **{f"audit_check:{standard.id}": metric.id, SNAP_CHOICE: snapshot.label},
            )


def show_check(result, explanation, snapshot, expanded: bool, sources: list[str], standard=None) -> None:
    """One expander: what the check measures, its calculation, method and the flagged items."""
    metric = result.metric
    row = results_frame([result]).iloc[0]
    counts = f" ({row['count']})" if result.numerator is not None and result.denominator else ""
    value = result.status if result.status in ("n/a", "error") else row["result"]
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
            if explanation.baseline:
                st.markdown(f"**Baseline** · {ui.md_text(explanation.baseline)}")
        with right:
            st.markdown("**Method**")
            st.caption(explanation.method.replace("``", "`"))
            if explanation.parameters:
                st.markdown("**Parameters**")
                ui.table(
                    pd.DataFrame(explanation.parameters, columns=["parameter", "value", "set by"]),
                    max_height=260,
                    key=f"params_{metric.id}",  # one table per check: filters keyed per check
                )
            if metric.source:
                st.caption(
                    "Source: "
                    + (f"[{metric.source}]({metric.source})" if metric.source.startswith("http") else metric.source)
                )

        if standard is not None:
            show_links(result, snapshot, standard)
        if result.flagged.empty:
            st.caption("No item listed for this check.")
        else:
            st.markdown(
                f"**{explanation.flagged_label}** · {len(result.flagged)} "
                f"{noun(explanation.subject, len(result.flagged))}"
            )
            ui.table(
                culprits_first(result.flagged),
                max_height=420,
                key=f"flag_{metric.id}",
                open_task=partial(open_in_gantt, snapshot=snapshot),
            )
            if not downloads_ready(sources):
                st.caption("Download: prepare the anonymized downloads under Results.")
            else:
                csv_download(
                    result.flagged,
                    f"{metric.id}_{ui.stamp(snapshot.data_date)}.csv",
                    "Download list (CSV)",
                    key=f"dl_{metric.id}",
                    sources=sources,
                )


def show_details(results, snapshot, only_failed: bool, sources: list[str], standard) -> None:
    ui.section("Detail by check")
    expand_all = st.toggle("Expand all", value=False, key="health_expand")
    group = None
    for result in results:
        if only_failed and result.status != "fail":
            continue
        if result.metric.group and result.metric.group != group:
            group = result.metric.group
            st.markdown(f"##### {group}")
        show_check(result, explain(result), snapshot, expand_all, sources, standard)


def show_trend(store, standard) -> None:
    """Computed on request: every metric on every update. Each update's results come from the
    session's cache when there, are not kept otherwise; the trend keeps only its numbers."""
    ui.section("Trend across updates", "The same check on every loaded update, against its target.")
    key = ("health_history", repr(standard))
    history = memo(key, lambda: None, keep=False, ev_basis=False)  # None until computed for this key
    if history is None:
        if not st.button(
            f"Compute the trend on the {len(store)} updates", icon=":material/show_chart:", key="health_trend_btn"
        ):
            return
        result_of = partial(metric_result, store=store, keep=False)
        history = memo(key, health_history, store, standard, None, result_of, ev_basis=False)
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
                    st.error(f"Columns missing: {ui.md_text(', '.join(sorted(missing)))}")
                    return
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(f"Unreadable CSV: {ui.md_text(exc)}")
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
                st.success(f"Loaded {ui.md_text(custom.name)} ({len(custom.metrics)} checks): pick it above.")
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(ui.md_text(exc))
        for error in st.session_state.get("standard_errors", []):
            st.error(ui.md_text(error))


store = require_store()
available = standards()


def standard_name(standard_id: str) -> str:
    return available[standard_id].name


top = st.container()  # title and context, filled once the update is picked

# the standards on a row of their own: beside the update picker their names did not fit
standard_id = st.segmented_control(
    "Standard",
    list(available),
    default="P6" if "P6" in available else None,
    format_func=standard_name,
    key="health_std",
)
snapshot_column, failed_column = st.columns([3, 1], vertical_alignment="bottom")
with snapshot_column:
    snapshot = snapshot_picker(store, "Update", key="health_snap")
with failed_column:
    only_failed = st.toggle("Failed checks only", value=False, key="health_failed")
standard = available[standard_id or next(iter(available))]
baseline = baseline_for(snapshot)

with top:
    page_header("Schedule health", store, snapshot)
    baseline_warnings(snapshot, baseline)
reference = f" · [reference]({standard.source})" if standard.source.startswith("http") else ""
st.caption((standard.description or standard.name) + reference)
if baseline is None:
    st.warning(
        "No baseline selected: checks against the baseline (late tasks, BEI, missed tasks) "
        "are not applicable. Pick one in the sidebar.",
        icon=":material/info:",
    )

# memoised per (data set, metric, update, baseline): the DECM critical path test alone
# takes ~2 s on a 4,000-activity file, and every widget change reruns the page
results = standard_results(standard, snapshot, store)
show_kpis(results, standard)
sources = sources_of(snapshot, baseline=baseline)  # the files the lists come from
show_summary(results, standard, snapshot, baseline, sources)
show_check_sets(results, standard, snapshot, sources)
show_details(results, snapshot, only_failed, sources, standard)
if len(store) > 1:
    show_trend(store, standard)

if baseline is not None:
    missing = sorted(set(snapshot.activities["task_code"]) - set(baseline.frame.index))
    if missing:
        st.caption(
            f"{len(missing)} tasks are not in the baseline: "
            f"{ui.md_text(', '.join(missing[:10]))}{'…' if len(missing) > 10 else ''}"
        )

show_report_comparison(results, standard)
show_own_standard()
