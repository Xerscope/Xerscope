import contextlib
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
from xerscope.analysis.checks import (
    flagged_codes,
    flagged_trail,
    health_wide,
    mismatch_count,
    report_counts,
    shown_by_group,
    standard_score,
    status_counts,
    summary_frame,
)
from xerscope.analysis.explain import explain, noun
from xerscope.analysis.rules import ACTIVITY_COLS, LINK_COLS
from xerscope.app import ui
from xerscope.app.baselines import (
    baseline_for_checks,
    data_identity,
)
from xerscope.app.cache import (
    memo,
    metric_result,
    standard_results,
)
from xerscope.app.downloads import (
    anonymous_exports,
    build_and_hold,
    csv_download,
    download_text,
    downloads_ready,
    show_held,
    sources_of,
)
from xerscope.app.explanation_panel import metric_panel
from xerscope.app.session import (
    SNAP_CHOICE,
)
from xerscope.app.sets import show_sets
from xerscope.app.state import (
    baseline_warnings,
    checks_rule,
    go_to,
    open_in_gantt,
    page_header,
    require_store,
    snapshot_picker,
    standards,
)
from xerscope.export import csv_bytes, zip_frames
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
    counts = status_counts(results)
    ui.kpis(
        [
            ("Checks passed", f"{counts['pass']} / {counts['scored']}", None, "Checks with a target that meet it"),
            ("Checks failed", counts["fail"], None, "Checks with a target that miss it"),
            ("For review", counts["info"], None, "Reported without a pass/fail target"),
            ("Not applicable", counts["n/a"], None, "No population, or no baseline"),
            # a rule that raised: a defect of the check, shown apart from n/a, only when there is one
            *(
                [("Errors", counts["error"], None, "Checks that could not be computed: see their note")]
                if counts["error"]
                else []
            ),
        ]
    )


def show_summary(results, standard, snapshot, sources: list[str]) -> None:
    full = summary_frame(results)  # its note names the baseline, for the export
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
        max_height=ui.TABLE_LONG,
        key="health_results",
        reading="health_results",
    )

    # Every flagged item of every check in one file: the audit trail behind the scores.
    trail = flagged_trail(results)
    summary_column, trail_column, sets_column, _ = st.columns([1, 1.3, 1.6, 3])
    with sets_column:  # first, so that the Prepare click also readies the downloads beside it
        prepare_sets(results, standard, snapshot, sources)
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
        # the same files as the summary: its Prepare button readies this download too
        if not trail.empty and downloads_ready(sources):
            csv_download(
                trail,
                f"{standard.id}_{ui.stamp(snapshot.data_date)}_flagged.csv",
                "All flagged items (CSV)",
                key="dl_trail",
                sources=sources,
            )


def prepare_sets(results, standard, snapshot, sources: list[str]) -> None:
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
        build_and_hold(
            "health_sets_csv", tag, lambda: csv_bytes(table), lambda anonymizer: anonymizer.csv(table), sources
        )
        build_and_hold(
            "health_sets_zip",
            tag,
            lambda: zip_frames(per_check, "csv"),
            lambda anonymizer: zip_frames({name: anonymizer.frame(frame) for name, frame in per_check.items()}, "csv"),
            sources,
        )
    stamp = f"{standard.id}_{ui.stamp(snapshot.data_date)}"
    for slot, label, name, mime in (
        ("health_sets_csv", "All sets (CSV)", f"{stamp}_sets.csv", "text/csv"),
        ("health_sets_zip", "All sets (ZIP)", f"{stamp}_sets.zip", "application/zip"),
    ):
        show_held(slot, tag, label, name, mime, key=f"dl_{slot}")


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
        help="Lists, for one check, the items it counted, the items checked but not counted and the items "
        "excluded from the file. Use it to see the tasks or links behind a count without leaving the page.",
    )
    if chosen is not None:
        show_sets(next(result for result in results if result.metric.id == chosen), snapshot, sources, f"{chosen}:")


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


def check_title(result) -> str:
    """The expander's title: status mark, check, its result with the counts, its target."""
    metric = result.metric
    row = results_frame([result]).iloc[0]
    counts = f" ({row['count']})" if result.numerator is not None and result.denominator else ""
    value = result.status if result.status in ("n/a", "error") else row["result"]
    return (
        f"{ui.STATUS_STYLE[result.status].mark}  {metric.id} · **{metric.name}** — {value}{counts}"
        f" · target {typeset(row['target'])}"
    )


def show_flagged(result, explanation, snapshot, sources: list[str]) -> None:
    """The items the check lists, and their download once the anonymized downloads are prepared."""
    metric = result.metric
    if result.flagged.empty:
        st.caption("No item listed for this check.")
        return
    st.markdown(
        f"**{explanation.flagged_label}** · {len(result.flagged)} {noun(explanation.subject, len(result.flagged))}"
    )
    ui.table(
        culprits_first(result.flagged),
        max_height=ui.TABLE_SHORT,
        key=f"flag_{metric.id}",
        reading="check_flagged",
        open_task=partial(open_in_gantt, snapshot=snapshot),
    )
    if not downloads_ready(sources):
        st.caption("Download: prepare the anonymized downloads under Results.")
        return
    csv_download(
        result.flagged,
        f"{metric.id}_{ui.stamp(snapshot.data_date)}.csv",
        "Download list (CSV)",
        key=f"dl_{metric.id}",
        sources=sources,
    )


def show_check(result, explanation, snapshot, expanded: bool, sources: list[str], standard=None) -> None:
    """One expander: what the check measures, its calculation, method and the flagged items."""
    with st.expander(check_title(result), expanded=expanded):
        metric_panel(result, explanation, detailed=True)
        if standard is not None:
            show_links(result, snapshot, standard)
        show_flagged(result, explanation, snapshot, sources)


def show_details(results, snapshot, only_failed: bool, sources: list[str], standard) -> None:
    ui.section("Detail by check")
    expand_all = st.toggle(
        "Expand all",
        value=False,
        key="health_expand",
        help="Opens every check's panel at once (calculation, method, flagged items). "
        "Use it to read or print the whole standard; off, open checks one by one.",
    )
    for group, shown in shown_by_group(results, only_failed).items():
        if group:
            st.markdown(f"#### {group}")
        for result in shown:
            show_check(result, explain(result), snapshot, expand_all, sources, standard)


def show_trend(store, standard) -> None:
    """Computed on request: every metric on every update. Each update's results come from the
    session's cache when there, are not kept otherwise; the trend keeps only its numbers."""
    ui.section("Trend across updates", "The same check on every loaded update, against its target.")
    key = ("health_history", repr(standard))
    history = memo(key, lambda: None, keep=False, ev_basis=False)  # None until computed for this key
    if history is None:
        if not st.button(
            f"Compute the trend on the {len(store)} updates",
            icon=":material/show_chart:",
            key="health_trend_btn",
            help="Runs every check of the standard on every loaded update, once per session; each update's "
            "result comes from the cache when it is there. Use it to see a check across weeks; it takes "
            "several seconds on a large file.",
        ):
            return
        result_of = partial(metric_result, store=store, keep=False)
        history = memo(key, health_history, store, standard, None, result_of, ev_basis=False)
    metric_ids = [metric.id for metric in standard.metrics]
    metric_id = st.selectbox(
        "Check",
        metric_ids,
        key="health_trend_metric",
        format_func=partial(check_label, standard),
        help="The check drawn in the trend chart below: its value per update against its target.",
    )
    metric = standard[metric_id]
    ui.chart(
        build_metric_trend(
            history[history["id"] == metric_id],
            metric.name,
            metric.threshold,
            metric.threshold_label,
            metric.unit,
        )
    )
    by_update = health_wide(history, standard)
    with st.expander("All checks, all updates"):
        ui.table(
            by_update,
            max_height=ui.TABLE_LONG,
            # one column per update, named by its date: written with two decimals, a check's value
            overrides=ui.number_columns("d2", *by_update.columns[2:]),
            key="health_trend",
            reading="health_trend",
        )


def _uploaded_counts(upload, got: pd.DataFrame) -> pd.DataFrame | None:
    """Return the counts of the uploaded ``id,found,total`` CSV set against this page's results.

    Shows the error and returns None when the file is unreadable or lacks one of the three columns.
    """
    try:
        typed = pd.read_csv(upload, dtype={"id": str}).rename(columns=str.strip)
    except (ValueError, UnicodeDecodeError) as exc:
        st.error(f"Unreadable CSV: {ui.md_text(exc)}")
        return None
    missing = {"id", "found", "total"} - set(typed.columns)
    if missing:
        st.error(f"Columns missing: {ui.md_text(', '.join(sorted(missing)))}")
        return None
    return report_counts(got, typed)


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
        upload = st.file_uploader(
            "Report counts (.csv)",
            type=["csv"],
            key=f"report_csv_{standard.id}",
            help="A CSV `id,found,total` typed from a P6 Check Schedule report run on the same update and "
            "baseline. Use it instead of typing the counts in the table below; nothing typed is kept on the server.",
        )
        if upload is None:
            typed = report_counts(got)
        else:
            typed = _uploaded_counts(upload, got)
        if typed is None:
            return
        edited = st.data_editor(
            typed,
            disabled=["id", "check"],
            hide_index=True,
            column_config={
                "found": st.column_config.NumberColumn(
                    "Found (report)",
                    min_value=0,
                    step=1,
                    help="Type the report's found for this check; a line left empty is not compared. "
                    "Use it to prove the page's counts against P6's.",
                ),
                "total": st.column_config.NumberColumn(
                    "Total (report)",
                    min_value=0,
                    step=1,
                    help="Type the report's total for this check; a line left empty is not compared. "
                    "Use it to prove the page's counts against P6's.",
                ),
            },
            key=f"report_counts_{standard.id}_{upload.file_id if upload else 'typed'}",  # a new upload resets the edits
        )
        compared = compare_counts(got, edited)
        if compared.empty:
            return
        bad = mismatch_count(compared)
        if bad:
            st.error(f"{bad} of {len(compared)} checks differ from the report", icon=":material/error:")
        else:
            st.success(f"All {len(compared)} checks match the report", icon=":material/check_circle:")
        ui.table(
            compared,
            # found and total mean the report's in the editor above and xerscope's here
            overrides=ui.count_columns(found="Found (xerscope)", total="Total (xerscope)"),
            key="health_report",
            reading="health_report",
        )


def load_uploaded_standard(upload) -> str:
    """The uploaded TOML registered for the session; returns the message to show, "" for no upload.
    Raises ValueError for a bad file or a built-in id."""
    if upload is None:
        return ""
    custom = loads_standard(upload.getvalue(), upload.name)
    if custom.id in builtin_standards():
        raise ValueError(f"{upload.name}: id {custom.id!r} is a built-in standard's; give yours another id")
    st.session_state.setdefault("uploaded_standards", {})[custom.id] = custom
    return f"Loaded {ui.md_text(custom.name)} ({len(custom.metrics)} checks): pick it above."


def read_upload_before_the_picker() -> None:
    """The file in the upload box (drawn lower on the page) is registered before the picker is drawn,
    so the standard just uploaded is listed at once; its message and errors are shown by the box."""
    with contextlib.suppress(ValueError, UnicodeDecodeError):
        load_uploaded_standard(st.session_state.get("std_upload"))


def show_own_standard() -> None:
    with st.expander("Use your own standard"):
        st.markdown(
            "A standard is a TOML file: each check picks a rule, its parameters and a target. "
            "Start from the template, edit it, upload it here (or put it in the folder given to "
            "`xerscope app --standards`)."
        )
        download_text(
            "Download the template",
            template_text(),
            "my-standard.toml",
            "application/toml",
            help_text="A TOML file with every rule, its parameters and a target, to edit into your own standard. "
            "Use it as the starting point; upload the result below.",
        )
        upload = st.file_uploader(
            "Upload a standard (.toml)",
            type=["toml"],
            key="std_upload",
            help="Registers your standard for this session and lists it in the Standard picker above; a "
            "built-in id is refused. Use it to run your company's checks; the folder given to "
            "`xerscope app --standards` does the same for every session.",
        )
        try:
            message = load_uploaded_standard(upload)
        except (ValueError, UnicodeDecodeError) as exc:
            st.error(ui.md_text(exc))
        else:
            if message:
                st.success(message)
        for error in st.session_state.get("standard_errors", []):
            st.error(ui.md_text(error))


store = require_store()
read_upload_before_the_picker()
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
    help="The checklist run on the update: P6 Check Schedule (the P6 Professional dialog's checks), DCMA "
    "14-Point, DCMA DECM v8.0, Integrity (the Schedule Project Log checks), or an uploaded one. Pick the one "
    "your report follows; P6 is the default.",
)
snapshot_column, failed_column = st.columns([3, 1], vertical_alignment="bottom")
with snapshot_column:
    snapshot = snapshot_picker(store, "Update", key="health_snap")
with failed_column:
    only_failed = st.toggle(
        "Failed checks only",
        value=False,
        key="health_failed",
        help="Hides the checks in pass, info or n/a in the detail below. Use it to read what needs attention first.",
    )
standard = available[standard_id or next(iter(available))]
baseline = baseline_for_checks(snapshot)

with top:
    page_header("Schedule health", store, snapshot, baseline=baseline, rule=checks_rule(baseline))
    baseline_warnings(snapshot, baseline)
st.caption(standard.description or standard.name)
if baseline is None:
    ui.need(
        "No baseline selected: checks against the baseline (late tasks, BEI, missed tasks) "
        "are not applicable. Pick one in the sidebar."
    )

# memoised per (data set, metric, update, baseline): the DECM critical path test alone
# takes ~2 s on a 4,000-activity file, and every widget change reruns the page
results = standard_results(standard, snapshot, store)
show_kpis(results, standard)
sources = sources_of(snapshot, baseline=baseline)  # the files the lists come from
show_summary(results, standard, snapshot, sources)
show_check_sets(results, standard, snapshot, sources)
show_details(results, snapshot, only_failed, sources, standard)
if len(store) > 1:
    show_trend(store, standard)

if baseline is not None:
    missing = baseline.unbaselined(snapshot)
    if missing:
        st.caption(
            f"{len(missing)} tasks are not in the baseline: "
            f"{ui.md_text(', '.join(missing[:10]))}{'…' if len(missing) > 10 else ''}"
        )

show_report_comparison(results, standard)
show_own_standard()
