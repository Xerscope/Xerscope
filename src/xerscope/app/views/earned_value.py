import pandas as pd
import streamlit as st

from xerscope.analysis import builtin_standards
from xerscope.analysis.baseline import EV_BASES
from xerscope.analysis.evm import bei_series, earned, evm_series, forecast_curve, pv_curve
from xerscope.app import ui
from xerscope.app.state import baseline_for, csv_download, memo, require_store, snapshot_picker, sources_of
from xerscope.viz.charts import INDEX_ALERT, build_index_trend, build_scurve

BEI_METRIC_IDS = {"P6": "P6-13", "DCMA": "DCMA-14"}  # the BEI check of each built-in standard
ACTIVITY_COLUMNS = [
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


def format_points(change: float) -> str:
    return f"{change:+.1f} pts this week"


def format_index_change(change: float) -> str:
    return f"{change:+.3f}"


def format_number(value: float, template: str = "{:,.0f}") -> str:
    return "–" if pd.isna(value) else template.format(value)


def change_since_previous(row: pd.Series, previous: pd.DataFrame, column: str, formatter) -> str | None:
    """Formatted change of ``column`` against the previous update, None when either side is missing."""
    if previous.empty or pd.isna(previous[column].iloc[0]) or pd.isna(row[column]):
        return None
    return formatter(row[column] - previous[column].iloc[0])


def show_kpis(row: pd.Series, previous: pd.DataFrame) -> None:
    ui.kpis(
        [
            (
                "EV %",
                f"{row['ev_pct']:.1f} %",
                change_since_previous(row, previous, "ev_pct", format_points),
                "Earned / BAC",
            ),
            ("PV %", f"{row['pv_pct']:.1f} %", None, "Planned / BAC"),
            (
                "SPI",
                format_number(row["spi"], "{:.3f}"),
                change_since_previous(row, previous, "spi", format_index_change),
                "EV / PV (hours)",
            ),
            ("SV", f"{row['sv_hr']:+,.0f} h", None, "EV − PV"),
            (
                "BEI (P6 / DCMA)",
                " / ".join(format_number(value, "{:.2f}") for value in (row["bei_p6"], row["bei_dcma"])),
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


def show_calculation(row: pd.Series, baseline, snapshot) -> None:
    with st.expander("How it is calculated", icon=":material/calculate:"):
        bac, planned, earned_hours, actual = row["bac_hr"], row["pv_hr"], row["ev_hr"], row["ac_hr"]
        baselined_actual = actual - row["ac_unbaselined_hr"]
        # one decimal: a result and the operands shown beside it agree to 0.1 h
        calculation = pd.DataFrame(
            [
                ("BAC", f"Σ baseline labour hours ({EV_BASES[baseline.ev_basis]})", f"{bac:,.1f} h"),
                (
                    "PV",
                    "Σ BL hours × Schedule % Complete (working time elapsed between BL start and BL finish, "
                    "on the activity's calendar, at the data date)",
                    f"{planned:,.1f} h  ({row['pv_pct']:.1f} % of BAC)",
                ),
                (
                    "EV",
                    "Σ BL hours × Performance % Complete (WBS EV technique: activity %, 0/100, 50/50 or custom)",
                    f"{earned_hours:,.1f} h  ({row['ev_pct']:.1f} % of BAC)",
                ),
                ("AC", "Σ actual labour hours", f"{actual:,.1f} h"),
                (
                    "SPI",
                    "EV / PV",
                    f"{earned_hours:,.1f} / {planned:,.1f} = {format_number(row['spi'], '{:.3f}')}",
                ),
                ("SV", "EV − PV", f"{earned_hours:,.1f} − {planned:,.1f} = {row['sv_hr']:+,.1f} h"),
                ("ETC", "Σ remaining labour hours", f"{row['etc_hr']:,.1f} h"),
                ("EAC", "AC + ETC", f"{actual:,.1f} + {row['etc_hr']:,.1f} = {row['eac_hr']:,.1f} h"),
                (
                    "EV / AC",
                    "EV / AC on baselined work (AC less the hours of activities the baseline does not have)",
                    f"{earned_hours:,.1f} / {baselined_actual:,.1f} = {format_number(row['productivity'], '{:.2f}')}",
                ),
            ],
            columns=["measure", "formula", "this update"],
        )
        ui.table(
            calculation,
            overrides={
                "formula": st.column_config.TextColumn("Formula", width="large"),
                "this update": st.column_config.TextColumn(ui.stamp(snapshot.data_date)),
            },
        )
        st.caption(
            "BEI is a count, not hours: completed activities / activities due by the data date "
            "(see Schedule health for the list)."
        )


def show_charts(series: pd.DataFrame, curve: pd.DataFrame, snapshot) -> None:
    ui.section(
        "S-curve",
        "Planned value from the baseline, earned value and actual hours per update, "
        "then the forecast of remaining hours.",
    )
    as_percent = st.toggle("Show as % of BAC", value=False, key="ev_pct_toggle")
    forecast = memo(("forecast", snapshot.source), forecast_curve, snapshot)
    st.plotly_chart(
        build_scurve(
            curve,
            series[series["data_date"] <= snapshot.data_date],
            forecast,
            snapshot.data_date,
            as_percent,
        ),
        width="stretch",
    )

    ui.section(
        "Performance indices by update",
        f"1.00 = on plan; the dotted line marks {INDEX_ALERT:g}, the usual alert threshold.",
    )
    st.plotly_chart(
        build_index_trend(series, {"spi": "SPI", "bei_dcma": "BEI (DCMA)", "productivity": "EV / AC"}),
        width="stretch",
    )
    ui.table(series.drop(columns=["bac_hr"]))


def show_activity_detail(snapshot, baseline) -> None:
    with st.expander(f"Earned hours by activity ({ui.stamp(snapshot.data_date)})"):
        activities = earned(snapshot, baseline).reset_index()
        ui.table(activities, columns=ACTIVITY_COLUMNS, max_height=640)
        csv_download(
            activities[ACTIVITY_COLUMNS],
            f"earned_{ui.stamp(snapshot.data_date)}.csv",
            sources=sources_of(snapshot, baseline=baseline),
        )
        fallback_mask = activities["ev_technique"].isin(["wbs_milestones", "resource_curves"])
        fallback = sorted(activities.loc[fallback_mask, "task_code"])
        if fallback:
            st.caption(
                f"EV technique not modelled (activity % complete used instead): {ui.md_text(', '.join(fallback[:20]))}"
            )
        missing = sorted(set(snapshot.activities["task_code"]) - set(baseline.frame.index))
        if missing:
            st.caption(f"Not in the baseline (earn nothing): {ui.md_text(', '.join(missing))}")


store = require_store()
top = st.container()
snapshot = snapshot_picker(store, "Update", key="ev_snap")
baseline = baseline_for(snapshot)
with top:
    ui.header(
        "Earned value",
        store,
        snapshot,
        baseline,
        lead="Labour hours, computed like P6's earned value fields. Planned value follows the baseline dates, "
        "earned value follows the % complete reported in the update.",
    )
if baseline is None:
    st.info("Choose a baseline in the sidebar (a loaded snapshot or a separate BL file).")
    st.stop()
if baseline.bac_hours <= 0:
    st.warning(
        f"The baseline ({baseline.label}) has no budgeted labour hours, so there is nothing to earn. "
        "Export the BL with resource assignments (TASK.target_work_qty / TASKRSRC)."
    )
    st.stop()

cache_key = ("evm", st.session_state.get("bl_choice"), baseline.label, baseline.ev_basis)
curve = memo(cache_key + ("pv",), pv_curve, baseline)
series = memo(cache_key + ("series",), evm_series, store, baseline)
standards = builtin_standards()
bei_metrics = {code: standards[code][metric_id] for code, metric_id in BEI_METRIC_IDS.items()}
series = series.merge(
    memo(cache_key + ("bei",), bei_series, store, bei_metrics, baseline_for), on="data_date", how="left"
)
row = series[series["data_date"] == snapshot.data_date].iloc[-1]
previous = series[series["data_date"] < snapshot.data_date].tail(1)

show_kpis(row, previous)
show_calculation(row, baseline, snapshot)
show_charts(series, curve, snapshot)
show_activity_detail(snapshot, baseline)
