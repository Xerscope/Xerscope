from functools import partial

import pandas as pd
import streamlit as st

from xerscope.analysis import builtin_standards
from xerscope.analysis.baseline import EV_BASES
from xerscope.analysis.evm import (
    bei_series,
    change_since_previous,
    earned,
    etc_settings,
    etc_technique_counts,
    ev_point,
    evm_series,
    forecast_curve,
    priced_assignment_count,
    pv_curve,
    settings_using_pf,
    update_and_baseline_of_code,
    update_and_previous,
)
from xerscope.analysis.explain import KPI_FORMULAS
from xerscope.app import ui
from xerscope.app.code_picker import pick_code_filter
from xerscope.app.state import (
    baseline_for,
    baseline_warnings,
    costs_shown,
    csv_download,
    memo,
    metric_result,
    page_header,
    require_store,
    snapshot_picker,
    sources_of,
)
from xerscope.viz.charts import INDEX_ALERT, build_index_trend, build_scurve

COST_COLUMNS = ["bac_cost", "pv_cost", "ev_cost", "spi_cost"]
COST_MEASURES = ["BAC cost", "PV cost", "EV cost", "SPI"]  # the rows of the calculation table that read costs
BEI_METRIC_IDS = {"P6": "P6-13", "DCMA": "DCMA-14"}  # the BEI check of each built-in standard
INDEX_COLUMNS = ["spi", "spi_cost", "productivity", "cpi", "bei_p6", "bei_dcma"]  # ratios, missing on the first update
ACTIVITY_COLUMNS = [
    "task_code",
    "bl_name",
    "wbs_code",
    "ev_labor_hr",
    "schedule_pct",
    "pv_hr",
    "ev_technique",
    "perf_pct",
    "ev_hr",
    "labor_actual_hr",
    "ev_finish",
]


EV_BASIS_COLUMNS = {"bl_labor_hr": "ev_labor_hr", "bl_start": "ev_start", "bl_finish": "ev_finish"}


def format_points(change: float) -> str:
    return f"{change:+.1f} pts this week"


def format_index_change(change: float) -> str:
    return f"{change:+.2f}"


def format_number(value: float, template: str = "{:,.0f}") -> str:
    return "–" if pd.isna(value) else template.format(value)


def formatted_change(row: pd.Series, previous: pd.Series | None, column: str, formatter) -> str | None:
    """Formatted change of ``column`` against the previous update, None when either side is missing."""
    change = change_since_previous(row, previous, column)
    return None if change is None else formatter(change)


def cost_spi_text(row: pd.Series, template: str = "{:.2f}") -> str:
    """The cost SPI, or why there is none."""
    if pd.notna(row["spi_cost"]):
        return template.format(row["spi_cost"])
    return "n/a — no cost in the baseline" if not row["bac_cost"] else "n/a — no planned value cost yet"


def show_kpis(row: pd.Series, previous: pd.Series | None, costs: bool) -> None:
    cost_card = (
        "SPI",
        cost_spi_text(row),
        formatted_change(row, previous, "spi_cost", format_index_change),
        "EV cost / PV cost; P6 column: Schedule Performance Index",
    )
    ui.kpis(
        [
            (
                "Percent complete",
                f"{row['ev_pct']:.1f} %",
                formatted_change(row, previous, "ev_pct", format_points),
                "EV / BAC (BCWP / BAC)",
            ),
            ("Percent scheduled", f"{row['pv_pct']:.1f} %", None, "PV / BAC (BCWS / BAC)"),
            *([cost_card] if costs else []),
            (
                "SPI (labor units)",
                format_number(row["spi"], "{:.2f}"),
                formatted_change(row, previous, "spi", format_index_change),
                "EV / PV in labor hours; P6 column: Schedule Performance Index - Labor Units",
            ),
            ("SV", f"{row['sv_hr']:+,.0f} h", None, "EV − PV"),
            (
                "BEI (P6 / DCMA)",
                " / ".join(format_number(value, "{:.2f}") for value in (row["bei_p6"], row["bei_dcma"])),
                None,
                (
                    "P6 (P6-13): completed / every baseline task, milestones and LOE out; "
                    "DCMA (DCMA-14): completed / due by the status date, no baseline finish = due"
                ),
            ),
            (
                "EAC",
                f"{row['eac_hr']:,.0f} h",
                # the signed number first: st.metric colours the delta by the sign it starts with
                f"{row['vac_hr']:+,.0f} h",
                "AC + remaining hours. The delta is the VAC = BAC − EAC: negative = overrun",
            ),
        ],
        formulas=KPI_FORMULAS,
    )


def show_costs_ignored(snapshot) -> None:
    """Costs off: say how many assignments of the file carry a cost, so the switch is findable."""
    priced = priced_assignment_count(snapshot)
    if priced:
        st.caption(
            f"Costs ignored: {priced} of {len(snapshot.assignments)} assignments carry a cost in the file "
            "(resource prices). Turn on Costs in the sidebar to see P6's cost SPI."
        )


def show_calculation(row: pd.Series, baseline, snapshot, point, costs: bool) -> None:
    with st.expander("How it is calculated", icon=":material/calculate:"):
        bac, planned, earned_hours, actual = row["bac_hr"], row["pv_hr"], row["ev_hr"], row["ac_hr"]
        baselined_actual = row["ac_baselined_hr"]
        # one decimal: a result and the operands shown beside it agree to 0.1 h
        settings = etc_settings(snapshot)
        counts = etc_technique_counts(settings)
        etc_counts = " · ".join(f"{item.etc_technique}: {item.wbs} WBS" for item in counts.itertuples())
        with_pf = settings_using_pf(settings)
        calculation = pd.DataFrame(
            [
                (
                    "BAC",
                    f"Σ baseline labor hours of the tasks the update holds ({EV_BASES[baseline.ev_basis]})",
                    f"{bac:,.1f} h",
                    "Budget At Completion - Labor Units",
                ),
                (
                    "PV",
                    "Σ BL hours × Schedule % Complete (working time elapsed between the EV start and EV finish "
                    "of the earned value basis, on the task's calendar, at the status date)",
                    f"{planned:,.1f} h  ({row['pv_pct']:.1f} % of BAC)",
                    "Planned Value Labor Units",
                ),
                (
                    "EV",
                    "Σ BL hours × Performance % Complete (WBS EV technique: task %, 0/100, 50/50 or custom)",
                    f"{earned_hours:,.1f} h  ({row['ev_pct']:.1f} % of BAC)",
                    "Earned Value Labor Units",
                ),
                ("AC", "Σ actual labor hours", f"{actual:,.1f} h", "Actual Labor Units"),
                (
                    "SPI (labor units)",
                    "EV / PV",
                    f"{earned_hours:,.1f} / {planned:,.1f} = {format_number(row['spi'], '{:.2f}')}",
                    "Schedule Performance Index - Labor Units",
                ),
                (
                    "BAC cost",
                    "Σ TASKRSRC.target_cost (all resource types) + Σ PROJCOST.target_cost of the baseline",
                    f"{row['bac_cost']:,.1f}",
                    "Budget At Completion (BL Total Cost)",
                ),
                (
                    "PV cost",
                    "Σ over assignments of BL cost × share of the assignment's dates elapsed at the status date "
                    "(date difference; working time assumed, unverified); expenses and tasks without "
                    "resource: BL cost × Schedule % Complete",
                    f"{row['pv_cost']:,.1f}",
                    "Planned Value Cost",
                ),
                (
                    "EV cost",
                    "Σ BL cost × Performance % Complete",
                    f"{row['ev_cost']:,.1f}",
                    "Earned Value Cost",
                ),
                (
                    "SPI",
                    "EV cost / PV cost",
                    f"{row['ev_cost']:,.1f} / {row['pv_cost']:,.1f} = {cost_spi_text(row)}",
                    "Schedule Performance Index",
                ),
                (
                    "SV",
                    "EV − PV",
                    f"{earned_hours:,.1f} − {planned:,.1f} = {row['sv_hr']:+,.1f} h",
                    "Schedule Variance - Labor Units",
                ),
                (
                    "ETC",
                    "Σ remaining labor hours",
                    f"{row['etc_hr']:,.1f} h",
                    "Estimate To Complete Labor Units (Remaining Total Units)",
                ),
                (
                    "ETC technique",
                    "Per WBS: remaining units, or PF × (BAC − EV). ETC above is always the remaining hours",
                    etc_counts,
                    "ETC technique (ev_etc_compute_type), Earned Value tab - WBS Details, Pro 25",
                ),
                (
                    "EAC",
                    "AC + ETC",
                    f"{actual:,.1f} + {row['etc_hr']:,.1f} = {row['eac_hr']:,.1f} h",
                    "Estimate At Completion - Labor Units",
                ),
                (
                    "CPI (labor units)",
                    "EV / AC, all actual hours",
                    f"{earned_hours:,.1f} / {actual:,.1f} = {format_number(row['cpi'], '{:.2f}')}",
                    "Cost Performance Index - Labor Units",
                ),
                (
                    "EV / AC (baselined work)",
                    "EV / AC without the hours of tasks the baseline does not have: EV exists only for "
                    "baselined tasks, so those hours would lower the ratio",
                    f"{earned_hours:,.1f} / {baselined_actual:,.1f} = {format_number(row['productivity'], '{:.2f}')}",
                    "not a P6 column: P6 divides by all actual units (CPI above)",
                ),
            ],
            columns=["measure", "formula", "this update", "P6 column"],
        )[["measure", "P6 column", "formula", "this update"]]  # the value stays last
        if not costs:
            calculation = calculation[~calculation["measure"].isin(COST_MEASURES)]
        ui.table(
            calculation,
            key="ev_calculation",
            overrides={
                "formula": st.column_config.TextColumn("Formula", width="large"),
                "this update": st.column_config.TextColumn(ui.stamp(snapshot.data_date)),
            },
        )
        if not with_pf.empty:
            st.warning(
                f"ETC / EAC computed as remaining hours; {len(with_pf)} WBS use a performance factor: "
                + ", ".join(f"{ui.md_text(item.wbs_code)} ({item.etc_technique})" for item in with_pf.itertuples()),
                icon=":material/warning:",
            )
        curves = point.not_modelled_cost if costs else []
        if curves:
            st.caption(
                "PV cost: resource curves not modelled (linear spread used) for " + ui.md_text(", ".join(curves[:20]))
            )
        st.caption(
            "BEI is a count, not hours: completed tasks / tasks due by the status date "
            "(see Schedule health for the list)."
        )


def show_charts(series: pd.DataFrame, curve: pd.DataFrame, snapshot, baseline, costs: bool, code_filter) -> None:
    ui.section(
        "S-curve",
        "Planned value from the baseline, earned value and actual hours per update, "
        "then the forecast of remaining hours.",
    )
    as_percent = st.toggle("Show as % of BAC", value=False, key="ev_pct_toggle")
    forecast = memo(("forecast", snapshot.source, code_filter), forecast_curve, snapshot, baseline=False)
    ui.chart(
        build_scurve(
            curve,
            series[series["data_date"] <= snapshot.data_date],
            forecast,
            snapshot.data_date,
            as_percent,
        )
    )

    ui.section(
        "Performance indices by update",
        f"1.00 = on plan; the dotted line marks {INDEX_ALERT:g}, the usual alert threshold.",
    )
    indices = {"spi": "SPI (labor units)", "bei_dcma": "BEI (DCMA)", "productivity": "EV / AC (baselined work)"}
    if costs and series["spi_cost"].notna().any():
        indices = {"spi_cost": "SPI", **indices}
    ui.chart(build_index_trend(series, indices))
    if baseline.is_planned:
        st.caption(
            f"Baseline = the planned dates (`target_*`) of the update shown, {ui.md_text(snapshot.label)}: every "
            "update's PV and SPI above is measured against them. Showing another update measures the whole "
            "history against that update's planned dates."
        )
    # VAC and the actual hours of baselined work are read above, for the update shown
    hidden = ["bac_hr", "vac_hr", "ac_baselined_hr"] + ([] if costs else COST_COLUMNS)
    # the first update has no PV yet: its indices are missing, written as a dash
    shown, overrides = ui.numbers_as_text(series.drop(columns=hidden), INDEX_COLUMNS)
    ui.table(shown, overrides=overrides, key="ev_updates")


def show_activity_detail(snapshot, baseline, point, earned_values: pd.DataFrame) -> None:
    with st.expander(f"Earned hours by task ({ui.stamp(snapshot.data_date)})"):
        # earned() names the EV basis values bl_*: here they carry their own name, apart from the BL columns
        values = earned_values.reset_index().rename(columns=EV_BASIS_COLUMNS)
        # the tasks BAC, PV and EV total: the baseline tasks the update holds (deleted ones below)
        activities, gone = values[values["in_snapshot"]], values[~values["in_snapshot"]]
        ui.table(activities, columns=ACTIVITY_COLUMNS, max_height=640, key="ev_tasks")
        st.caption(
            f"EV budget and EV finish: the hours and finish PV and EV are computed from, under the earned value "
            f"basis {EV_BASES[baseline.ev_basis]} (Baseline window); not P6's BL Project columns."
        )
        csv_download(
            activities[ACTIVITY_COLUMNS],
            f"earned_{ui.stamp(snapshot.data_date)}.csv",
            sources=sources_of(snapshot, baseline=baseline),
        )
        fallback = point.not_modelled
        if fallback:
            st.caption(
                f"EV technique not modelled (task % complete used instead): {ui.md_text(', '.join(fallback[:20]))}"
            )
        missing = point.unbaselined
        if missing:
            st.caption(
                f"Not in the baseline (earn nothing; their actual hours count in AC, not in this table): "
                f"{ui.md_text(', '.join(missing))}"
            )
        if not gone.empty:
            st.caption(
                f"In the baseline, no longer in the update ({point.pv_deleted_hr:,.1f} h of PV): left out of "
                "this table, BAC, PV and EV, as P6 totals the tasks of the current project: "
                f"{ui.md_text(', '.join(gone['task_code']))}"
            )
            csv_download(
                gone[ACTIVITY_COLUMNS],
                f"earned_deleted_{ui.stamp(snapshot.data_date)}.csv",
                label="Download deleted tasks (CSV)",
                key="ev_deleted_csv",
                sources=sources_of(snapshot, baseline=baseline),
            )


store = require_store()
top = st.container()
snapshot = snapshot_picker(store, "Update", key="ev_snap")
baseline = baseline_for(snapshot)
with top:
    page_header(
        "Earned value",
        store,
        snapshot,
        lead="Labor hours, computed like P6's earned value fields. Planned value follows the baseline dates, "
        "earned value follows the % complete reported in the update.",
    )
    baseline_warnings(snapshot, baseline, series=True)
if baseline is None:
    st.info("Choose a baseline from the sidebar's Baseline line (a loaded snapshot or a separate BL file).")
    st.stop()
if baseline.bac_hours <= 0:
    st.warning(
        f"The baseline ({ui.md_text(baseline.label)}) has no budgeted labor hours, so there is nothing to earn. "
        "Export the BL with resource assignments (TASK.target_work_qty / TASKRSRC)."
    )
    st.stop()

code_filter = pick_code_filter(snapshot, "ev")
part, part_baseline = update_and_baseline_of_code(snapshot, baseline, code_filter)
if code_filter is not None:
    st.caption(
        f"Filtered on {ui.md_text(code_filter.type_name)}: BAC, PV, EV, AC, ETC and the curves count only the "
        "tasks of the values picked, read in each update. BEI counts tasks over the whole project: it is "
        "not shown on a part of it."
    )
    if part_baseline.bac_hours <= 0:
        st.info("The tasks of the values picked hold no budgeted labor hours in the baseline: nothing to earn.")
        st.stop()

# which baseline: its label alone is not unique (two baselines of one P6 XML export with the same data
# date); its source and the project it was read from are ("planned dates" baselines differ per update)
identity = (baseline.label, baseline.source, baseline.snapshot.source, baseline.snapshot.project_id)
cache_key = ("evm", *identity, baseline.ev_basis, code_filter)
update_key = (snapshot.source, str(snapshot.data_date))
# the update's lists (techniques not modelled, tasks not in the baseline, curves) as its KPIs computed them
point = memo(cache_key + ("point", *update_key), ev_point, part, part_baseline)
earned_values = memo(cache_key + ("earned", *update_key), earned, part, part_baseline)
curve = memo(cache_key + ("pv", *update_key), pv_curve, part_baseline, part)
series = memo(
    cache_key + ("series",),
    evm_series,
    store,
    baseline_for(snapshot, link=False),  # each update linked to it on its own renumbered tasks
    st.session_state.get("guid_link", False),
    code_filter,
)
if code_filter is None:
    standards = builtin_standards()
    bei_metrics = {code: standards[code][metric_id] for code, metric_id in BEI_METRIC_IDS.items()}
    # each update's BEI from the session's cache when Health or Audit computed it, not kept otherwise
    bei = memo(
        ("bei", repr(bei_metrics)),
        bei_series,
        store,
        bei_metrics,
        baseline_for,
        partial(metric_result, store=store, keep=False),
        ev_basis=False,
    )
    series = series.merge(bei, on="data_date", how="left")
else:  # the BEI is a check of the whole project
    series = series.assign(bei_p6=float("nan"), bei_dcma=float("nan"))
row, previous = update_and_previous(series, snapshot.data_date)

costs = costs_shown()
show_kpis(row, previous, costs)
if not costs:
    show_costs_ignored(snapshot)
show_calculation(row, baseline, snapshot, point, costs)
show_charts(series, curve, part, part_baseline, costs, code_filter)
show_activity_detail(snapshot, baseline, point, earned_values)
