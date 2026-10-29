import pandas as pd
import streamlit as st

from xerscope.analysis import AnalysisContext, builtin_standards, run_metric
from xerscope.analysis.baseline import EV_BASES
from xerscope.analysis.evm import earned, evm_series, forecast_curve, pv_curve
from xerscope.app import ui
from xerscope.app.state import baseline_for, is_dark, memo, require_store, snapshot_picker
from xerscope.viz.charts import build_index_trend, build_scurve

store = require_store()
top = st.container()
snap = snapshot_picker(store, "Update", key="ev_snap")
bl = baseline_for(snap)
with top:
    ui.header(
        "Earned value",
        store,
        snap,
        bl,
        lead="Labour hours, computed like P6's earned value fields. Planned value follows the baseline dates, "
        "earned value follows the % complete reported in the update.",
    )
if bl is None or bl.snapshot is None:
    st.info("Choose a baseline in the sidebar (a loaded snapshot or a separate BL file).")
    st.stop()
if bl.bac_hours <= 0:
    st.warning(
        f"The baseline ({bl.label}) has no budgeted labour hours, so there is nothing to earn. "
        "Export the BL with resource assignments (TASK.target_work_qty / TASKRSRC)."
    )
    st.stop()

key = ("evm", st.session_state.get("bl_choice"), bl.label, bl.ev_basis)
curve = memo(key + ("pv",), lambda: pv_curve(bl))
series = memo(key + ("series",), lambda: evm_series(store, bl))
std = builtin_standards()
BEI = {k: next(m for m in std[k].metrics if m.rule == "bei") for k in ("P6", "DCMA")}


def bei_series():
    rows = []
    for s in store:
        b = baseline_for(s)
        rows.append(
            {
                "data_date": s.data_date,
                "bei_p6": run_metric(BEI["P6"], AnalysisContext(s, baseline=b)).value,
                "bei_dcma": run_metric(BEI["DCMA"], AnalysisContext(s, baseline=b)).value,
            }
        )
    return pd.DataFrame(rows)


series = series.merge(memo(key + ("bei",), bei_series), on="data_date", how="left")
row = series[series["data_date"] == snap.data_date].iloc[-1]
prev = series[series["data_date"] < snap.data_date].tail(1)


def delta(col, fmt):
    return None if prev.empty or pd.isna(prev[col].iloc[0]) or pd.isna(row[col]) else fmt(row[col] - prev[col].iloc[0])


def num(v, fmt="{:,.0f}"):
    return "–" if pd.isna(v) else fmt.format(v)


ui.kpis(
    [
        ("EV %", f"{row['ev_pct']:.1f} %", delta("ev_pct", lambda d: f"{d:+.1f} pts this week"), "Earned / BAC"),
        ("PV %", f"{row['pv_pct']:.1f} %", None, "Planned / BAC"),
        ("SPI", num(row["spi"], "{:.2f}"), delta("spi", lambda d: f"{d:+.2f}"), "EV / PV (hours)"),
        ("SV", f"{row['sv_hr']:+,.0f} h", None, "EV − PV"),
        (
            "BEI (P6 / DCMA)",
            " / ".join(num(v, "{:.2f}") for v in (row["bei_p6"], row["bei_dcma"])),
            None,
            "P6 counts activities without a baseline finish as due; DCMA leaves them out",
        ),
        (
            "EAC",
            f"{row['eac_hr']:,.0f} h",
            f"{row['eac_hr'] - row['bac_hr']:+,.0f} h vs BAC",
            "AC + remaining hours",
            "inverse",
        ),
    ]
)

with st.expander("How it is calculated", icon=":material/calculate:"):
    bac, pv, ev, ac = row["bac_hr"], row["pv_hr"], row["ev_hr"], row["ac_hr"]
    calc = pd.DataFrame(
        [
            ("BAC", f"Σ baseline labour hours ({EV_BASES[bl.ev_basis]})", f"{bac:,.0f} h"),
            (
                "PV",
                "Σ BL hours × Schedule % Complete (working time elapsed between BL start and BL finish, "
                "on the activity's calendar, at the data date)",
                f"{pv:,.0f} h  ({row['pv_pct']:.1f} % of BAC)",
            ),
            (
                "EV",
                "Σ BL hours × Performance % Complete (WBS EV technique: activity %, 0/100, 50/50 or custom)",
                f"{ev:,.0f} h  ({row['ev_pct']:.1f} % of BAC)",
            ),
            ("AC", "Σ actual labour hours", f"{ac:,.0f} h"),
            ("SPI", "EV / PV", f"{ev:,.0f} / {pv:,.0f} = {num(row['spi'], '{:.2f}')}"),
            ("SV", "EV − PV", f"{ev:,.0f} − {pv:,.0f} = {row['sv_hr']:+,.0f} h"),
            ("ETC", "Σ remaining labour hours", f"{row['etc_hr']:,.0f} h"),
            ("EAC", "AC + ETC", f"{ac:,.0f} + {row['etc_hr']:,.0f} = {row['eac_hr']:,.0f} h"),
            ("EV / AC", "Earned hours per hour spent on baselined work", num(row["productivity"], "{:.2f}")),
        ],
        columns=["measure", "formula", "this update"],
    )
    ui.table(
        calc,
        overrides={
            "formula": st.column_config.TextColumn("Formula", width="large"),
            "this update": st.column_config.TextColumn(f"{snap.data_date:%Y-%m-%d}"),
        },
    )
    st.caption(
        "BEI is a count, not hours: completed activities / activities due by the data date "
        "(see Schedule health for the list)."
    )

ui.section(
    "S-curve",
    "Planned value from the baseline, earned value and actual hours per update, then the forecast of remaining hours.",
)
pct = st.toggle("Show as % of BAC", value=False, key="ev_pct_toggle")
st.plotly_chart(
    build_scurve(
        curve,
        series[series["data_date"] <= snap.data_date],
        memo(("forecast", snap.source), lambda: forecast_curve(snap)),
        snap.data_date,
        pct,
        is_dark(),
    ),
    width="stretch",
)

ui.section("Performance indices by update", "1.00 = on plan; the dotted line marks 0.95, the usual alert threshold.")
st.plotly_chart(
    build_index_trend(series, {"spi": "SPI", "bei_dcma": "BEI (DCMA)", "productivity": "EV / AC"}, is_dark()),
    width="stretch",
)
ui.table(series.drop(columns=["bac_hr"]))

with st.expander(f"Earned hours by activity ({snap.data_date:%Y-%m-%d})"):
    e = earned(snap, bl).reset_index()
    cols = [
        "task_code",
        "bl_name",
        "wbs_code",
        "bl_labor_hr",
        "schedule_pct",
        "pv_hr",
        "ev_technique",
        "perf_pct",
        "ev_hr",
        "labor_actual_hr",
        "bl_finish",
        "in_snapshot",
    ]
    ui.table(e, columns=cols, max_height=640)
    ui.csv_button(e[cols], f"earned_{snap.data_date:%Y-%m-%d}.csv")
    fallback = sorted(e.loc[e["ev_technique"].isin(["wbs_milestones", "resource_curves"]), "task_code"])
    if fallback:
        st.caption(
            f"EV technique not modelled (activity % complete used instead): {ui.md_text(', '.join(fallback[:20]))}"
        )
    missing = sorted(set(snap.activities["task_code"]) - set(bl.frame.index))
    if missing:
        st.caption(f"Not in the baseline (earn nothing): {ui.md_text(', '.join(missing))}")
