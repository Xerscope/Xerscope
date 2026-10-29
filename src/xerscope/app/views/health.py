import pandas as pd
import streamlit as st

from xerscope.analysis import AnalysisContext, health_history, loads_standard, run_standard, template_text
from xerscope.analysis.explain import explain, fmt_value, noun
from xerscope.analysis.rules import ACTIVITY_COLS, LINK_COLS
from xerscope.app import ui
from xerscope.app.state import baseline_for, is_dark, memo, require_store, snapshot_picker, standards
from xerscope.viz.charts import build_metric_trend

store = require_store()
available = standards()
top = st.container()  # title and context, filled once the update is picked

c1, c2, c3 = st.columns([4, 2.2, 1.3], vertical_alignment="bottom")
with c1:
    std_id = st.segmented_control(
        "Standard",
        list(available),
        default="P6" if "P6" in available else None,
        format_func=lambda k: available[k].name,
        key="health_std",
    )
with c2:
    snap = snapshot_picker(store, "Update", key="health_snap")
with c3:
    only_failed = st.toggle("Failed checks only", value=False, key="health_failed")
std = available[std_id or next(iter(available))]
bl = baseline_for(snap)

with top:
    ui.header("Schedule health", store, snap, bl)
st.caption((std.description or std.name) + (f" · [reference]({std.source})" if std.source.startswith("http") else ""))
if bl is None:
    st.warning(
        "No baseline selected: checks against the baseline (late activities, BEI, missed tasks) "
        "are not applicable. Pick one in the sidebar.",
        icon=":material/info:",
    )

results = run_standard(std, AnalysisContext(snap, store, bl))
status = pd.Series([r.status for r in results])
scored = int(status.isin(["pass", "fail"]).sum())
ui.kpis(
    [
        ("Checks passed", f"{int((status == 'pass').sum())} / {scored}", None, "Checks with a target that meet it"),
        ("Checks failed", int((status == "fail").sum()), None, "Checks with a target that miss it"),
        ("For review", int((status == "info").sum()), None, "Reported without a pass/fail target"),
        ("Not applicable", int(status.isin(["n/a", "error"]).sum()), None, "No population, or no baseline"),
    ]
)

# --- summary --------------------------------------------------------------------------------------
explained = [explain(r) for r in results]
summary = pd.DataFrame(
    [
        {
            "status": r.status,
            "id": r.metric.id,
            "group": r.metric.group,
            "check": r.metric.name,
            "result": fmt_value(r.value, r.metric.unit) if r.status not in ("n/a", "error") else "–",
            "count": f"{r.numerator} / {r.denominator}"
            if r.numerator is not None and r.denominator is not None
            else ("" if r.numerator is None else str(r.numerator)),
            "target": r.metric.threshold_label.replace("<=", "≤").replace(">=", "≥"),
            "flagged": len(r.flagged),
        }
        for r in results
    ]
)
if not summary["group"].astype(bool).any():
    summary = summary.drop(columns="group")

ui.section(
    "Results",
    "One row per check, in the standard's order. Open a check below for its calculation and the activities behind it.",
)
ui.table(
    summary,
    status="status",
    max_height=700,
    overrides={
        "flagged": st.column_config.NumberColumn("Items listed", format="%d"),
    },
)

# Every flagged item of every check in one file: the audit trail behind the scores.
trail = pd.concat(
    [
        r.flagged.assign(check_id=r.metric.id, check=r.metric.name, check_status=r.status)
        for r in results
        if not r.flagged.empty
    ]
    or [pd.DataFrame()],
    ignore_index=True,
)
d1, d2, _ = st.columns([1, 1.3, 4])
with d1:
    ui.csv_button(summary, f"{std.id}_{snap.data_date:%Y-%m-%d}_summary.csv", "Summary (CSV)", key="dl_sum")
with d2:
    if not trail.empty:
        front = ["check_id", "check", "check_status"]
        ui.csv_button(
            trail[front + [c for c in trail.columns if c not in front]],
            f"{std.id}_{snap.data_date:%Y-%m-%d}_flagged.csv",
            "All flagged items (CSV)",
            key="dl_trail",
        )

# --- detail per check -----------------------------------------------------------------------------
ui.section("Detail by check")
expand_all = st.toggle("Expand all", value=False, key="health_expand")


def culprits_first(df: pd.DataFrame) -> pd.DataFrame:
    """ID and name, then the columns this check adds (reason, BL finish, variance…), then the rest."""
    ident = [
        c
        for c in ("task_code", "task_name", "pred_code", "pred_name", "succ_code", "succ_name", "type")
        if c in df.columns
    ]
    extra = [c for c in df.columns if c not in ACTIVITY_COLS + LINK_COLS]
    return df[ident + extra + [c for c in df.columns if c not in ident + extra]]


MARK = {
    "pass": ":green[**PASS**]",
    "fail": ":red[**FAIL**]",
    "info": ":blue[**INFO**]",
    "n/a": ":gray[**N/A**]",
    "error": ":orange[**ERROR**]",
}
group = None
for r, e in zip(results, explained, strict=True):
    if only_failed and r.status != "fail":
        continue
    if r.metric.group and r.metric.group != group:
        group = r.metric.group
        st.markdown(f"##### {group}")
    result_txt = fmt_value(r.value, r.metric.unit) if r.status not in ("n/a", "error") else "n/a"
    counts = f" ({r.numerator} / {r.denominator})" if r.numerator is not None and r.denominator else ""
    target = r.metric.threshold_label.replace("<=", "≤").replace(">=", "≥")
    label = f"{MARK[r.status]}  {r.metric.id} · **{r.metric.name}** — {result_txt}{counts} · target {target}"
    with st.expander(label, expanded=expand_all):
        left, right = st.columns([3, 2], gap="large")
        with left:
            st.markdown(f"**What it measures** · {e.measured}")
            with st.container(border=True):
                st.caption("Calculation")
                st.markdown(f"#### {e.formula}")
                st.markdown(e.verdict)
            if e.population:
                st.markdown("**Population**")
                st.markdown("\n".join(f"- {line}" for line in e.population))
            if r.note and r.note not in e.formula:
                st.markdown(f"**Note** · {r.note}")
        with right:
            st.markdown("**Method**")
            st.caption(e.method.replace("``", "`"))
            if e.parameters:
                st.markdown("**Parameters**")
                ui.table(pd.DataFrame(e.parameters, columns=["parameter", "value", "set by"]), max_height=260)
            if r.metric.source:
                src = r.metric.source
                st.caption("Source: " + (f"[{src}]({src})" if src.startswith("http") else src))

        if r.flagged.empty:
            st.caption("No item listed for this check.")
        else:
            st.markdown(f"**{e.flagged_label}** · {len(r.flagged)} {noun(e.subject, len(r.flagged))}")
            ui.table(culprits_first(r.flagged), max_height=420, key=f"flag_{r.metric.id}")
            ui.csv_button(
                r.flagged,
                f"{r.metric.id}_{snap.data_date:%Y-%m-%d}.csv",
                "Download list (CSV)",
                key=f"dl_{r.metric.id}",
            )

# --- week over week -------------------------------------------------------------------------------
if len(store) > 1:
    ui.section("Trend across updates", "The same check on every loaded update, against its target.")
    bl_key = st.session_state.get("bl_choice"), bl.label if bl else None
    hist = memo(("health", repr(std), bl_key), lambda: health_history(store, std, baseline_for))
    metric_ids = [m.id for m in std.metrics]
    mid = st.selectbox("Check", metric_ids, key="health_trend_metric", format_func=lambda i: f"{i} · {std[i].name}")
    m = std[mid]
    st.plotly_chart(
        build_metric_trend(hist[hist["id"] == mid], m.name, m.threshold, m.threshold_label, m.unit, is_dark()),
        width="stretch",
    )
    wide = hist.pivot_table(index="id", columns="data_date", values="actual", aggfunc="first").reindex(metric_ids)
    wide.columns = [f"{c:%Y-%m-%d}" for c in wide.columns]
    wide.insert(0, "check", [std[i].name for i in wide.index])
    with st.expander("All checks, all updates"):
        ui.table(
            wide.reset_index(),
            max_height=640,
            overrides={c: st.column_config.NumberColumn(c, format="%.2f") for c in wide.columns[1:]},
        )

if bl is not None:
    missing = sorted(set(snap.activities["task_code"]) - set(bl.frame.index))
    if missing:
        st.caption(
            f"{len(missing)} activities are not in the baseline: "
            f"{', '.join(missing[:10])}{'…' if len(missing) > 10 else ''}"
        )

# --- your own standard ----------------------------------------------------------------------------
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
    up = st.file_uploader("Upload a standard (.toml)", type=["toml"], key="std_upload")
    if up is not None:
        try:
            custom = loads_standard(up.getvalue(), up.name)
            st.session_state.setdefault("uploaded_standards", {})[custom.id] = custom
            st.success(f"Loaded {custom.name} ({len(custom.metrics)} checks): pick it above.")
        except (ValueError, UnicodeDecodeError) as exc:
            st.error(str(exc))
    for err in st.session_state.get("standard_errors", []):
        st.error(err)
