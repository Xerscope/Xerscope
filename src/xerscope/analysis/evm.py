"""Earned value in labour hours, computed the way P6 computes its labour-unit EV fields.

- BAC = the baseline's labour units on the EV basis chosen (P6 Admin Preferences, Earned
  Value): budgeted units by default, at-completion units (actual + remaining) under
  "at completion".
- PV = BL labour units x Schedule % Complete. Oracle: Schedule % Complete is the share of
  the activity's baseline duration elapsed at the data date (0 before the baseline start,
  100 after the baseline finish), so PV grows linearly in *working time* of the
  activity's calendar between its baseline start and finish. Computed exactly with the
  calendar's TimeAxis, to the minute.
- EV = BL labour units x Performance % Complete. The technique is set per WBS element
  (PROJWBS.ev_compute_type): activity % complete (P6 default, per the activity's % complete
  type), 0/100, 50/50, or a custom % once started. "WBS milestones" and "resource curves"
  are not modelled: they fall back to activity % complete and are reported.
- Activities not in the baseline earn nothing (listed). BAC, PV and EV are summed over the
  activities of the update: P6 totals its earned value fields over the activities of the current
  project ("adding the values for each activity in the summary", P6 Professional 25, How data is
  summarized), so a baseline activity deleted since has no BAC, PV or EV there. It stays in
  ``earned()`` (``in_snapshot`` False) and its PV is reported apart (``EvPoint.pv_deleted_hr``).
- AC = actual labour units and ETC = remaining labour units of every activity in the
  update, baselined or not; EAC = AC + ETC.
- ETC technique: P6 sets it per WBS element too (PROJWBS.ev_etc_compute_type): remaining
  units, or a performance factor PF with ETC = PF x (BAC - EV) (Oracle Pro 25, Earned Value
  tab - WBS Details). xerscope always uses the remaining units; ``etc_settings`` reports
  the WBS that use a PF.
- SPI = EV / PV, SV = EV - PV; CPI = EV / AC as P6 gives it (all actual labour units);
  ``productivity`` = EV / AC measured on baselined work only (EV exists for nothing else),
  the hours spent outside the baseline being reported apart.

Cost (P6 Professional 26 help, glossary, "Budget At Completion", "Planned Value Cost",
"Earned Value Cost", "Schedule Performance Index"; version 26 read from the PDF G57535-02):

- BAC cost = BL total cost = Σ TASKRSRC.target_cost (labour, nonlabour, material) +
  Σ PROJCOST.target_cost of the baseline (``bl_cost``).
- PV cost = per resource assignment, BAC of the assignment x (data date - assignment start) /
  (assignment finish - assignment start), clipped to 0..1; the activity's PV cost is the sum.
  Expenses and activities without a resource: BAC x the same ratio on the activity's BL dates.
  The text writes a difference of dates: working time (the assignment's resource calendar,
  else the activity's) is assumed, unverified; ``PV_COST_WORKING_TIME = False`` switches to
  calendar time. Resource curves (``curv_id``) are not modelled and listed in
  ``EvPoint.not_modelled_cost``; manual future-period values are not read.
- EV cost = BAC cost x Performance % Complete (same technique as the hours).
- SPI (cost) = EV cost / PV cost, the P6 column "Schedule Performance Index"; the labour
  units index (``spi``) stays beside it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..store import SnapshotStore
from ..xer import Snapshot
from ..xer.calendar import TimeAxis
from .baseline import Baseline
from .checks import AnalysisContext, CheckResult, run_metric
from .standards import Metric

# Planned Value Cost spreads an assignment over the date difference of the P6 glossary: working
# time of the assignment's calendar (assumed, no P6 output settles it) or calendar time (False).
PV_COST_WORKING_TIME = True


def ev_technique(code: object) -> str:
    """PROJWBS.ev_compute_type -> technique key (EC_Cmp_pct = activity % complete)."""
    text = str(code or "").strip().lower()
    if text in ("", "nan", "none") or "cmp" in text:
        return "activity"
    if "user" in text or "custom" in text:
        return "custom"
    if "50" in text:
        return "50/50"
    if "wbs" in text or "mile" in text:
        return "wbs_milestones"
    if "crv" in text or "curve" in text or "rsrc" in text:
        return "resource_curves"
    if "0" in text:
        return "0/100"
    return "activity"


# PROJWBS.ev_etc_compute_type values found in the reference files; any other value is shown as it is.
ETC_TECHNIQUES = {"EE_Rem_hr": "remaining units", "EE_PF_1": "PF = 1", "EE_PF_cpi": "PF = 1/CPI"}


def etc_technique(code: object) -> str:
    """PROJWBS.ev_etc_compute_type -> label; an unknown code is returned as it is, a blank one as "(blank)"."""
    text = str(code or "").strip()
    return ETC_TECHNIQUES.get(text, text or "(blank)")


def uses_pf(code: object) -> bool:
    """The WBS computes its ETC with a performance factor (Oracle: PF = 1, 1/CPI, 1/(CPI x SPI) or entered)."""
    return str(code or "").strip().startswith("EE_PF")


def etc_settings(snapshot: Snapshot) -> pd.DataFrame:
    """One row per WBS element of the project (the project node left out): EV and ETC techniques
    as stored (``ev_compute_type``, ``ev_etc_compute_type``, ``ev_etc_user_value``), their labels,
    and the number of activities on the element."""
    wbs = snapshot.wbs
    wbs = wbs[wbs["proj_node_flag"] != "Y"] if "proj_node_flag" in wbs else wbs
    activities = snapshot.activities["wbs_id"].value_counts()
    return pd.DataFrame(
        {
            "wbs_code": wbs["wbs_code"],
            "ev_compute_type": wbs["ev_compute_type"],
            "ev_technique": wbs["ev_compute_type"].map(ev_technique),
            "ev_etc_compute_type": wbs["ev_etc_compute_type"],
            "etc_technique": wbs["ev_etc_compute_type"].map(etc_technique),
            "ev_etc_user_value": wbs["ev_etc_user_value"],
            "activities": wbs["wbs_id"].map(activities).fillna(0).astype(int),
        }
    ).reset_index(drop=True)


def etc_technique_counts(settings: pd.DataFrame) -> pd.DataFrame:
    """WBS elements and activities per ETC technique, from ``etc_settings``."""
    return (
        settings.groupby(["ev_etc_compute_type", "etc_technique"], as_index=False)
        .agg(wbs=("wbs_code", "size"), activities=("activities", "sum"))
        .sort_values(["wbs", "etc_technique"], ascending=[False, True])
        .reset_index(drop=True)
    )


def _ramp_sum(work_starts: np.ndarray, work_finishes: np.ndarray, hours: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Sum over rows of hours * clip((g - start) / (finish - start), 0, 1) at every grid value g.

    Piecewise linear: one slope change at each start and finish, so the sum is
    evaluated in O((rows + grid) log rows) instead of rows x grid.
    """
    if len(work_starts) == 0:
        return np.zeros(len(grid))
    durations = (work_finishes - work_starts).astype(float)
    breakpoints = np.concatenate([work_starts, work_finishes]).astype(float)
    slope_changes = np.concatenate([hours / durations, -hours / durations])
    order = np.argsort(breakpoints, kind="stable")
    sorted_breakpoints, slope = breakpoints[order], np.cumsum(slope_changes[order])  # slope just after each one
    values = np.concatenate([[0.0], np.cumsum(slope[:-1] * np.diff(sorted_breakpoints))])  # value at each one
    position = np.searchsorted(sorted_breakpoints, grid, side="right") - 1
    nearest = np.clip(position, 0, len(sorted_breakpoints) - 1)
    result = values[nearest] + slope[nearest] * (grid - sorted_breakpoints[nearest])
    return np.where(position < 0, 0.0, result)


@dataclass
class _Spread:
    """Hours spread linearly in working time between two dates, per calendar."""

    groups: list[tuple[TimeAxis, np.ndarray, np.ndarray, np.ndarray]] = field(default_factory=list)
    steps: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)  # zero-duration rows

    @classmethod
    def build(
        cls, snapshot: Snapshot, frame: pd.DataFrame, hours: str, start: str, finish: str, calendar: str
    ) -> _Spread:
        rows = frame[(frame[hours] > 0) & frame[start].notna() & frame[finish].notna()]
        spread = cls()
        if rows.empty:
            return spread
        first_day, last_day = rows[start].min().date(), rows[finish].max().date()
        for calendar_id, group in rows.groupby(rows[calendar].fillna(""), sort=False):
            axis = TimeAxis(snapshot.calendar(calendar_id), first_day, last_day)
            work_starts, work_finishes = axis.work_many(group[start]), axis.work_many(group[finish])
            work_starts, work_finishes = np.minimum(work_starts, work_finishes), np.maximum(work_starts, work_finishes)
            group_hours = group[hours].to_numpy(float)
            instant = work_finishes == work_starts
            if (~instant).any():
                spread.groups.append((axis, work_starts[~instant], work_finishes[~instant], group_hours[~instant]))
            if instant.any():  # all at once when its (single) instant is reached
                spread.steps.append((group[finish].to_numpy("datetime64[ns]")[instant], group_hours[instant]))
        return spread

    def at(self, stamps) -> np.ndarray:
        stamps = pd.DatetimeIndex(pd.to_datetime(pd.Series(stamps).reset_index(drop=True))).as_unit("ns")
        total = np.zeros(len(stamps))
        for axis, work_starts, work_finishes, hours in self.groups:
            total += _ramp_sum(work_starts, work_finishes, hours, axis.work_many(stamps).astype(float))
        for instants, hours in self.steps:
            order = np.argsort(instants)
            cumulative = np.concatenate([[0.0], np.cumsum(hours[order])])
            total += cumulative[np.searchsorted(instants[order], stamps.values, side="right")]
        return total


def _pv_spread(baseline: Baseline) -> _Spread:
    return _Spread.build(baseline.snapshot, baseline.frame, "ev_labor_hr", "ev_start", "ev_finish", "bl_clndr_id")


def pv_curve(baseline: Baseline) -> pd.DataFrame:
    """Daily and cumulative planned labour hours of the baseline (cumulative = end of day), every
    baseline activity: the plan itself. An update's PV (``ev_point``) leaves out the activities it
    no longer holds."""
    frame = baseline.frame
    frame = frame[(frame["ev_labor_hr"] > 0) & frame["ev_start"].notna() & frame["ev_finish"].notna()]
    if frame.empty:
        return pd.DataFrame(columns=["date", "pv_hr", "pv_cum_hr", "pv_pct"])
    days = pd.date_range(frame["ev_start"].min().normalize(), frame["ev_finish"].max().normalize(), freq="D")
    curve = pd.DataFrame({"date": days, "pv_cum_hr": _pv_spread(baseline).at(days + pd.Timedelta(days=1))})
    curve["pv_hr"] = curve["pv_cum_hr"].diff().fillna(curve["pv_cum_hr"])
    bac = baseline.bac_hours
    curve["pv_pct"] = 100 * curve["pv_cum_hr"] / bac if bac else np.nan
    return curve[["date", "pv_hr", "pv_cum_hr", "pv_pct"]]


def _elapsed(
    snapshot: Snapshot, frame: pd.DataFrame, start: str, finish: str, calendar: str, when: pd.Timestamp,
    working_time: bool = True,
) -> pd.Series:  # fmt: skip
    """Share (0..1) of each row's start-to-finish span elapsed at ``when``, NaN where a date is
    missing. Working time of the row's calendar, or calendar time when ``working_time`` is False;
    a zero-length span is 0 before its instant and 1 from then on."""
    share = pd.Series(np.nan, index=frame.index)
    has_dates = frame[start].notna() & frame[finish].notna()
    if not has_dates.any():
        return share
    first_day = min(frame.loc[has_dates, start].min(), when).date()
    last_day = max(frame.loc[has_dates, finish].max(), when).date()
    for calendar_id, group in frame[has_dates].groupby(frame.loc[has_dates, calendar].fillna(""), sort=False):
        if working_time:
            axis = TimeAxis(snapshot.calendar(calendar_id), first_day, last_day)
            starts, finishes = axis.work_many(group[start]), axis.work_many(group[finish])
            now = axis.work(when)
        else:
            starts = group[start].to_numpy("datetime64[ns]").astype("int64")
            finishes = group[finish].to_numpy("datetime64[ns]").astype("int64")
            now = np.datetime64(when, "ns").astype("int64")
        durations = (finishes - starts).astype(float)
        fraction = np.where(
            durations > 0,
            np.clip((now - starts) / np.where(durations > 0, durations, 1), 0, 1),
            (group[finish].to_numpy("datetime64[ns]") <= np.datetime64(when)).astype(float),
        )
        share.loc[group.index] = fraction
    return share


def schedule_pct(baseline: Baseline, when: pd.Timestamp) -> pd.Series:
    """P6 Schedule % Complete of each baseline activity at ``when`` (on the EV basis dates)."""
    # unrounded: per-activity PV must sum to ev_point's PV; tables round on display
    return 100 * _elapsed(baseline.snapshot, baseline.frame, "ev_start", "ev_finish", "bl_clndr_id", when)


def planned_value_cost(baseline: Baseline, when: pd.Timestamp) -> pd.Series:
    """Planned Value Cost of each baseline activity at ``when``: its assignments one by one on their
    own dates, the rest of its budget (expenses, no resource) on the activity's dates."""
    snapshot, frame, costs = baseline.snapshot, baseline.frame, baseline.assignment_costs
    by_assignment = costs["cost"] * _elapsed(
        snapshot, costs, "start", "finish", "clndr_id", when, PV_COST_WORKING_TIME
    ).fillna(0.0)
    planned = by_assignment.groupby(costs["task_code"]).sum().reindex(frame.index).fillna(0.0)
    assigned = costs.groupby("task_code")["cost"].sum().reindex(frame.index).fillna(0.0)
    activity_share = _elapsed(snapshot, frame, "ev_start", "ev_finish", "bl_clndr_id", when, PV_COST_WORKING_TIME)
    return planned + (frame["bl_cost"] - assigned) * activity_share.fillna(0.0)


PV_LABOR_COLUMNS = [
    "data_date", "activities", "assignments", "labor_assignments", "labor_assignments_with_curve",
    "bl_hr_with_curve", "bac_activity_hr", "bac_assignment_hr", "pv_activity_hr", "pv_assignment_hr", "gap_hr",
    "pv_calendar_time_hr", "pv_end_of_day_hr", "pv_calendar_time_end_of_day_hr",
]  # fmt: skip
PV_LABOR_STATUS_COLUMNS = ["status", "activities", "pv_activity_hr", "pv_assignment_hr", "gap_hr"]
SCHEDULE_STATUSES = ["not started", "in progress", "complete"]


def pv_labor_check(snapshot: Snapshot, baseline: Baseline | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Diagnostic, not used by any KPI: planned value labour units by activity (``earned`` pv_hr)
    against the same by assignment, at the data date.

    By assignment (P6 Pro 26 glossary, "Planned Value Labor Units"): Σ ``target_qty`` of the
    labour assignments x the share of their own start-to-finish elapsed, with the convention of the
    PV cost (``PV_COST_WORKING_TIME``); an activity without labour assignment keeps its activity
    value. The glossary's resource-curve distribution is not modelled; assignments naming a curve
    are counted. ``gap_hr`` = assignment - activity. Variants of the activity value, to tell which
    convention P6 uses: ``pv_calendar_time_hr`` (Schedule % in calendar time, the glossary writes a
    date difference), ``pv_end_of_day_hr`` (working time, at the end of the data date's day) and
    both together. Baseline activities the update holds, as ``ev_point``. Returns the totals (one
    row) and the split by Schedule % (0 not started, 100 complete). No activity code in either.
    """
    if baseline is None or snapshot.data_date is None:
        return pd.DataFrame(columns=PV_LABOR_COLUMNS), pd.DataFrame(columns=PV_LABOR_STATUS_COLUMNS)
    values = earned(snapshot, baseline)
    values = values[values["in_snapshot"]]  # the population of ev_point
    costs = baseline.assignment_costs
    costs = costs[costs["task_code"].isin(values.index)]
    labor = costs[costs["labor"].astype(bool)]
    share = _elapsed(
        baseline.snapshot, labor, "start", "finish", "clndr_id", snapshot.data_date, PV_COST_WORKING_TIME
    ).fillna(0.0)
    by_assignment = (labor["labor_hr"] * share).groupby(labor["task_code"]).sum()
    assigned_hr = labor.groupby("task_code")["labor_hr"].sum()
    has_labor = values.index.isin(labor["task_code"])
    values["pv_assignment_hr"] = np.where(has_labor, values.index.map(by_assignment).fillna(0.0), values["pv_hr"])
    values["gap_hr"] = values["pv_assignment_hr"] - values["pv_hr"]
    percent = values["schedule_pct"].fillna(0.0)
    values["status"] = np.where(percent <= 0, "not started", np.where(percent >= 100, "complete", "in progress"))
    curved = labor[labor["curve"].astype(bool)]
    end_of_day = snapshot.data_date.normalize() + pd.Timedelta(days=1)

    def activity_pv(when: pd.Timestamp, working_time: bool) -> float:
        frame = baseline.frame.loc[values.index]
        share = _elapsed(baseline.snapshot, frame, "ev_start", "ev_finish", "bl_clndr_id", when, working_time)
        return float((frame["ev_labor_hr"] * share.fillna(0.0)).sum())

    totals = pd.DataFrame(
        [
            {
                "data_date": snapshot.data_date,
                "activities": len(values),
                "assignments": len(costs),
                "labor_assignments": len(labor),
                "labor_assignments_with_curve": len(curved),
                "bl_hr_with_curve": float(curved["labor_hr"].sum()),
                "bac_activity_hr": float(values["bl_labor_hr"].sum()),
                "bac_assignment_hr": float(assigned_hr.sum() + values.loc[~has_labor, "bl_labor_hr"].sum()),
                "pv_activity_hr": float(values["pv_hr"].sum()),
                "pv_assignment_hr": float(values["pv_assignment_hr"].sum()),
                "gap_hr": float(values["gap_hr"].sum()),
                "pv_calendar_time_hr": activity_pv(snapshot.data_date, working_time=False),
                "pv_end_of_day_hr": activity_pv(end_of_day, working_time=True),
                "pv_calendar_time_end_of_day_hr": activity_pv(end_of_day, working_time=False),
            }
        ]
    )
    split = values.groupby("status").agg(
        activities=("pv_hr", "size"), pv_activity_hr=("pv_hr", "sum"),
        pv_assignment_hr=("pv_assignment_hr", "sum"), gap_hr=("gap_hr", "sum"),
    ).reindex(SCHEDULE_STATUSES).fillna(0.0)  # fmt: skip
    split["activities"] = split["activities"].astype(int)
    return totals, split.rename_axis("status").reset_index()


PV_P6_TOLERANCE_HR = 0.01  # P6 shows two decimals: below this a difference is rounding
PV_P6_PCT_TOLERANCE = 0.01  # same, in percentage points of Schedule % Complete
PCT_BANDS = ["0", "in progress", "100", "absent"]
PV_P6_OPTIONAL = ["status", "bl_hr", "bl_start", "bl_finish", "start", "finish"]
PV_P6_REQUIRED = ["pv_hr", "ev_hr", "schedule_pct"]


@dataclass
class PvComparison:
    """``pv_p6_comparison``: four frames without activity code or name, and the per-activity list."""

    totals: pd.DataFrame
    cross: pd.DataFrame
    causes: pd.DataFrame
    by_calendar: pd.DataFrame
    activities: pd.DataFrame


def _pct_band(percent: pd.Series, present: pd.Series) -> pd.Series:
    rounded = percent.round(2)
    band = np.select([rounded <= 0, rounded >= 100], ["0", "100"], "in progress")
    return pd.Series(np.where(present, band, "absent"), index=percent.index)


def pv_p6_comparison(
    snapshot: Snapshot,
    baseline: Baseline,
    p6: pd.DataFrame,
    tolerance_hr: float = PV_P6_TOLERANCE_HR,
    p6_total_pv_hr: float | None = None,
) -> PvComparison:
    """Diagnostic, not used by any KPI: PV and EV labour units of ``earned`` against the same columns
    of a P6 Activities export, joined on Activity ID. ``p6`` is indexed by task_code with ``pv_hr``,
    ``ev_hr`` and ``schedule_pct``, and optionally ``PV_P6_OPTIONAL`` columns (``bl_hr`` the BL
    labour units; the others, P6 text shown as is). A blank value counts as 0. An update activity
    the baseline does not know has PV and EV 0 here, as in ``earned``. ``*_gap_hr`` = xerscope - P6;
    an activity is "in gap" when its PV or its EV gap exceeds ``tolerance_hr``.

    Returns, in this order:
    - ``totals``: one row per group with the activities, PV and EV on both sides and the gap. The
      groups all = matched + only P6 + only xerscope (xerscope = baseline plus update activities);
      "in update, not in baseline" and "in baseline, not in update" cut across matched / only.
      With ``p6_total_pv_hr`` (the project PV total read in P6, typed by hand), a last row
      "P6 total - export rows": that total less the PV of the export's rows, the PV P6 counts
      on activities its view does not show.
    - ``cross``: the PV gap by Schedule % band of xerscope x P6 (``absent``: no value on that side).
    - ``causes``: the count of activities in gap by candidate cause (several can hold for one
      activity; ``bl_hr_differs`` is blank without the BL hours column).
    - ``by_calendar``: the matched activities by calendar (``clndr_id``: the baseline's, else the update's).
    - ``activities``: the activities in gap, largest gap first. Only this one holds codes and names.
    """
    values = earned(snapshot, baseline)
    in_update_index = snapshot.by_code.index
    codes = values.index.union(in_update_index)
    values, update = values.reindex(codes), snapshot.by_code.reindex(codes)
    in_baseline, in_update = codes.isin(baseline.frame.index), codes.isin(in_update_index)
    ours = pd.DataFrame(
        {
            "task_name": update["task_name"].fillna(values["bl_name"]),
            "status": update["status"].where(in_update, "not in update"),
            "not_started": in_update & ~update["is_started"].fillna(True).astype(bool),
            "bl_labor_hr": values["bl_labor_hr"].fillna(0.0),
            "schedule_pct": values["schedule_pct"],
            "pv_hr": values["pv_hr"].fillna(0.0),
            "ev_hr": values["ev_hr"].fillna(0.0),
            "bl_start": values["bl_start"],
            "bl_finish": values["bl_finish"],
            "start": update["start"],
            "finish": update["finish"],
        }
    )
    theirs = p6.rename(columns={"pv_hr": "p6_pv_hr", "ev_hr": "p6_ev_hr", "schedule_pct": "p6_schedule_pct"}).rename(
        columns={name: f"p6_{name}" for name in PV_P6_OPTIONAL}
    )
    joined = ours.join(theirs, how="outer")
    in_ours, in_p6 = joined.index.isin(ours.index), joined.index.isin(p6.index)
    joined = joined.assign(
        in_baseline=pd.Series(in_baseline, index=ours.index).reindex(joined.index, fill_value=False),
        in_update=pd.Series(in_update, index=ours.index).reindex(joined.index, fill_value=False),
    )
    in_baseline, in_update = joined["in_baseline"].to_numpy(), joined["in_update"].to_numpy()
    for column in ["pv_hr", "ev_hr", "p6_pv_hr", "p6_ev_hr"]:
        joined[column] = joined[column].fillna(0.0)
    joined["pv_gap_hr"] = joined["pv_hr"] - joined["p6_pv_hr"]
    joined["ev_gap_hr"] = joined["ev_hr"] - joined["p6_ev_hr"]
    in_gap = (joined["pv_gap_hr"].abs() > tolerance_hr) | (joined["ev_gap_hr"].abs() > tolerance_hr)
    matched = in_ours & in_p6

    groups = {
        "all": np.ones(len(joined), dtype=bool),
        "matched": matched,
        "only P6": ~in_ours,
        "only xerscope": ~in_p6,
        "in update, not in baseline": in_update & ~in_baseline,
        "in baseline, not in update": in_baseline & ~in_update,
    }
    totals = pd.DataFrame(
        [
            {
                "group": name,
                "activities": int(mask.sum()),
                "pv_xerscope_hr": float(joined.loc[mask, "pv_hr"].sum()),
                "pv_p6_hr": float(joined.loc[mask, "p6_pv_hr"].sum()),
                "pv_gap_hr": float(joined.loc[mask, "pv_gap_hr"].sum()),
                "ev_xerscope_hr": float(joined.loc[mask, "ev_hr"].sum()),
                "ev_p6_hr": float(joined.loc[mask, "p6_ev_hr"].sum()),
                "ev_gap_hr": float(joined.loc[mask, "ev_gap_hr"].sum()),
            }
            for name, mask in groups.items()
        ]
    ).astype({"activities": "Int64"})
    if p6_total_pv_hr is not None:
        outside = p6_total_pv_hr - float(p6["pv_hr"].fillna(0.0).sum())
        totals.loc[len(totals)] = {"group": "P6 total - export rows", "pv_p6_hr": outside}

    ours_band = _pct_band(joined["schedule_pct"].fillna(0.0), in_baseline)
    p6_band = _pct_band(joined["p6_schedule_pct"].fillna(0.0), in_p6)
    cross = (
        joined.assign(xerscope_pct_band=ours_band, p6_pct_band=p6_band)
        .groupby(["xerscope_pct_band", "p6_pct_band"])
        .agg(activities=("pv_hr", "size"), pv_xerscope_hr=("pv_hr", "sum"), pv_p6_hr=("p6_pv_hr", "sum"),
             pv_gap_hr=("pv_gap_hr", "sum"))
        .reset_index()
    )  # fmt: skip
    for column in ["xerscope_pct_band", "p6_pct_band"]:
        cross[column] = pd.Categorical(cross[column], PCT_BANDS)
    cross = cross.sort_values(["xerscope_pct_band", "p6_pct_band"]).reset_index(drop=True)
    for column in ["xerscope_pct_band", "p6_pct_band"]:
        cross[column] = cross[column].astype(str)

    pct_differs = (
        matched
        & in_baseline
        & ((joined["schedule_pct"] - joined["p6_schedule_pct"].fillna(0.0)).abs() > PV_P6_PCT_TOLERANCE)
    )
    bl_differs = pd.NA
    if "p6_bl_hr" in joined:
        bl_differs = int((in_gap & matched & ((joined["bl_labor_hr"] - joined["p6_bl_hr"]).abs() > tolerance_hr)).sum())
    causes = pd.DataFrame(
        [
            {
                "gap_activities": int(in_gap.sum()),
                "pv_gap_hr": float(joined.loc[in_gap, "pv_gap_hr"].sum()),
                "ev_gap_hr": float(joined.loc[in_gap, "ev_gap_hr"].sum()),
                "only_p6": int((in_gap & ~in_ours).sum()),
                "only_xerscope": int((in_gap & ~in_p6).sum()),
                "bl_hr_differs": bl_differs,
                "schedule_pct_differs": int((in_gap & pct_differs).sum()),
                "not_started_in_update": int((in_gap & joined["not_started"].fillna(False).astype(bool)).sum()),
            }
        ]
    ).astype({"bl_hr_differs": "Int64"})

    own_calendar = baseline.frame["bl_clndr_id"].reindex(joined.index)
    calendar = own_calendar.where(joined["in_baseline"], update["clndr_id"].reindex(joined.index))
    by_calendar = (
        joined.loc[matched]
        .assign(clndr_id=calendar[matched], in_gap=in_gap[matched])
        .groupby("clndr_id", dropna=False)
        .agg(matched=("pv_hr", "size"), in_gap=("in_gap", "sum"), pv_xerscope_hr=("pv_hr", "sum"),
             pv_p6_hr=("p6_pv_hr", "sum"), pv_gap_hr=("pv_gap_hr", "sum"), ev_xerscope_hr=("ev_hr", "sum"),
             ev_p6_hr=("p6_ev_hr", "sum"), ev_gap_hr=("ev_gap_hr", "sum"))
        .reset_index()
    )  # fmt: skip

    listed = [
        "task_name", "status", "p6_status", "bl_labor_hr", "p6_bl_hr", "schedule_pct", "p6_schedule_pct",
        "pv_hr", "p6_pv_hr", "pv_gap_hr", "ev_hr", "p6_ev_hr", "ev_gap_hr", "start", "finish", "p6_start",
        "p6_finish", "bl_start", "bl_finish", "p6_bl_start", "p6_bl_finish",
    ]  # fmt: skip
    activities = joined.loc[in_gap, [column for column in listed if column in joined]]
    size = np.maximum(activities["pv_gap_hr"].abs(), activities["ev_gap_hr"].abs()).to_numpy()
    activities = activities.iloc[np.argsort(-size, kind="stable")].rename_axis("task_code").reset_index()
    return PvComparison(totals, cross, causes, by_calendar, activities)


@dataclass
class EvPoint:
    data_date: pd.Timestamp
    bac_hr: float
    pv_hr: float
    ev_hr: float
    ac_hr: float
    etc_hr: float
    unbaselined: list[str]
    not_modelled: list[str] = field(default_factory=list)  # activities on a fallback technique
    ac_unbaselined_hr: float = 0.0  # part of ac_hr spent on activities the baseline does not know
    bac_cost: float = 0.0
    pv_cost: float = 0.0
    ev_cost: float = 0.0
    not_modelled_cost: list[str] = field(default_factory=list)  # activities with a resource curve (PV cost)
    deleted: list[str] = field(default_factory=list)  # baseline activities the update no longer holds
    pv_deleted_hr: float = 0.0  # their PV, left out of pv_hr

    @property
    def eac_hr(self) -> float:
        return self.ac_hr + self.etc_hr

    @property
    def spi(self) -> float | None:
        return self.ev_hr / self.pv_hr if self.pv_hr else None

    @property
    def spi_cost(self) -> float | None:
        """P6 "Schedule Performance Index": EV cost / PV cost; None without planned value cost."""
        return self.ev_cost / self.pv_cost if self.pv_cost else None

    @property
    def productivity(self) -> float | None:
        """EV per hour spent on baselined work: EV only exists for baselined activities,
        so hours spent on the others would make the ratio look worse than the work is."""
        baselined_actual_hr = self.ac_hr - self.ac_unbaselined_hr
        return self.ev_hr / baselined_actual_hr if baselined_actual_hr else None

    @property
    def cpi(self) -> float | None:
        """P6 "Cost Performance Index - Labor Units": EV / all actual labour units."""
        return self.ev_hr / self.ac_hr if self.ac_hr else None

    def as_row(self) -> dict:
        def percent_of_bac(hours: float) -> float | None:
            return 100 * hours / self.bac_hr if self.bac_hr else None

        return {
            "data_date": self.data_date,
            "bac_hr": self.bac_hr,
            "pv_hr": self.pv_hr,
            "ev_hr": self.ev_hr,
            "ac_hr": self.ac_hr,
            "etc_hr": self.etc_hr,
            "eac_hr": self.eac_hr,
            "pv_pct": percent_of_bac(self.pv_hr),
            "ev_pct": percent_of_bac(self.ev_hr),
            "sv_hr": self.ev_hr - self.pv_hr,
            "spi": self.spi,
            "productivity": self.productivity,
            "cpi": self.cpi,
            "unbaselined": len(self.unbaselined),
            "ac_unbaselined_hr": self.ac_unbaselined_hr,
            "deleted_since_bl": len(self.deleted),
            "pv_deleted_hr": self.pv_deleted_hr,
            "bac_cost": self.bac_cost,
            "pv_cost": self.pv_cost,
            "ev_cost": self.ev_cost,
            "spi_cost": self.spi_cost,
        }


def performance_pct(snapshot: Snapshot) -> pd.DataFrame:
    """Per activity (index task_code): EV technique of its WBS and Performance % Complete."""
    activities = snapshot.by_code
    if "ev_compute_type" in activities:
        technique = activities["ev_compute_type"].map(ev_technique)
    else:
        technique = pd.Series("activity", index=activities.index)
    if "ev_user_pct" in activities:
        custom_pct = pd.to_numeric(activities["ev_user_pct"], errors="coerce")
    else:
        custom_pct = pd.Series(np.nan, index=activities.index)
    done = activities["is_complete"]
    in_progress = ~done & activities["is_started"]
    # the stepped techniques: 100 once done, 0 before starting, a fixed value in between
    zero_hundred = pd.Series(np.where(done, 100.0, 0.0), index=activities.index)
    fifty_fifty = zero_hundred.mask(in_progress, 50.0)
    custom = zero_hundred.mask(in_progress, custom_pct.fillna(0.0))
    percent = activities["pct_complete"].astype(float)
    percent = percent.mask(technique == "0/100", zero_hundred)
    percent = percent.mask(technique == "50/50", fifty_fifty)
    percent = percent.mask(technique == "custom", custom)
    return pd.DataFrame({"ev_technique": technique, "perf_pct": percent.clip(0, 100)})


def earned(snapshot: Snapshot, baseline: Baseline) -> pd.DataFrame:
    """Per baseline activity: BL hours, Schedule % and Performance % now, PV and EV hours, BL cost, PV and EV cost.

    ``bl_labor_hr`` / ``bl_start`` / ``bl_finish`` here are the EV basis values (see
    baseline.EV_BASES): the hours and dates PV and EV are computed from.
    """
    activities = snapshot.by_code
    baseline_ev = baseline.frame.drop(columns=["bl_labor_hr", "bl_start", "bl_finish"]).rename(
        columns={"ev_labor_hr": "bl_labor_hr", "ev_start": "bl_start", "ev_finish": "bl_finish"}
    )
    current_columns = ["task_name", "wbs_code", "wbs_l1", "pct_complete", "labor_actual_hr", "labor_remaining_hr"]
    result = (
        baseline_ev[["bl_name", "bl_labor_hr", "bl_start", "bl_finish", "bl_cost"]]
        .join(activities[current_columns], how="left")
        .join(performance_pct(snapshot), how="left")
    )
    result["in_snapshot"] = result["task_name"].notna()
    result["pct_complete"] = result["pct_complete"].fillna(0.0)
    result["perf_pct"] = result["perf_pct"].fillna(0.0)
    result["ev_technique"] = result["ev_technique"].fillna("activity")
    result["schedule_pct"] = schedule_pct(baseline, snapshot.data_date) if snapshot.data_date is not None else np.nan
    result["pv_hr"] = result["bl_labor_hr"] * result["schedule_pct"].fillna(0.0) / 100
    result["ev_hr"] = result["bl_labor_hr"] * result["perf_pct"] / 100
    has_data_date = snapshot.data_date is not None
    result["pv_cost"] = planned_value_cost(baseline, snapshot.data_date) if has_data_date else 0.0
    result["ev_cost"] = result["bl_cost"] * result["perf_pct"] / 100
    return result


def ev_point(snapshot: Snapshot, baseline: Baseline) -> EvPoint:
    """BAC, PV, EV (hours and cost) over the baseline activities the update holds; AC and ETC over
    every activity of the update."""
    earned_values = earned(snapshot, baseline)
    current = earned_values[earned_values["in_snapshot"]]
    deleted = earned_values[~earned_values["in_snapshot"]]
    activities = snapshot.activities
    unbaselined = sorted(set(activities["task_code"]) - set(baseline.frame.index))
    on_fallback = current["ev_technique"].isin(["wbs_milestones", "resource_curves"])
    curves = baseline.assignment_costs
    curve_codes = set(curves.loc[curves["curve"].astype(bool), "task_code"]) & set(current.index)
    return EvPoint(
        snapshot.data_date,
        float(current["bl_labor_hr"].sum()),
        float(current["pv_hr"].sum()),
        float(current["ev_hr"].sum()),
        float(activities["labor_actual_hr"].sum()),
        float(activities["labor_remaining_hr"].sum()),
        unbaselined,
        sorted(current.index[on_fallback]),
        ac_unbaselined_hr=float(activities.loc[activities["task_code"].isin(unbaselined), "labor_actual_hr"].sum()),
        bac_cost=float(current["bl_cost"].sum()),
        pv_cost=float(current["pv_cost"].sum()),
        ev_cost=float(current["ev_cost"].sum()),
        not_modelled_cost=sorted(curve_codes),
        deleted=sorted(deleted.index),
        pv_deleted_hr=float(deleted["pv_hr"].sum()),
    )


def evm_series(store: SnapshotStore, baseline: Baseline) -> pd.DataFrame:
    return pd.DataFrame([ev_point(snapshot, baseline).as_row() for snapshot in store])


def forecast_curve(snapshot: Snapshot) -> pd.DataFrame:
    """Cumulative hours, one row per day from the data date's day to the last finish: AC
    plus the remaining hours of open work spread over working time to each activity's
    finish. As in ``pv_curve``, a row names a day and holds the cumulative at its end."""
    activities = snapshot.activities
    open_work = activities[~activities["is_complete"]].copy()
    data_date = snapshot.data_date
    actual_hr = float(activities["labor_actual_hr"].sum())
    if data_date is None:
        return pd.DataFrame({"date": [], "fc_cum_hr": []})
    # remaining work cannot happen before the data date, nor finish before it starts
    open_work["fc_start"] = open_work["start"].where(open_work["start"] > data_date, data_date)
    open_work["fc_finish"] = open_work["finish"].where(
        open_work["finish"] > open_work["fc_start"], open_work["fc_start"]
    )
    with_remaining = open_work[(open_work["labor_remaining_hr"] > 0) & open_work["fc_finish"].notna()]
    if with_remaining.empty:
        return pd.DataFrame({"date": [data_date.normalize()], "fc_cum_hr": [actual_hr]})
    days = pd.date_range(data_date.normalize(), with_remaining["fc_finish"].max().normalize(), freq="D")
    spread = _Spread.build(snapshot, with_remaining, "labor_remaining_hr", "fc_start", "fc_finish", "clndr_id")
    return pd.DataFrame({"date": days, "fc_cum_hr": actual_hr + spread.at(days + pd.Timedelta(days=1))})


def bei_series(
    store: SnapshotStore,
    bei_metrics: Mapping[str, Metric],
    baseline_for: Callable[[Snapshot], Baseline | None],
    result_of: Callable[[Metric, Snapshot], CheckResult] | None = None,
) -> pd.DataFrame:
    """Baseline Execution Index of every update under the P6 and DCMA definitions.

    ``bei_metrics`` holds the ``bei`` metric of the "P6" and "DCMA" standards; ``baseline_for``
    gives each snapshot its own baseline. ``result_of(metric, snapshot)``, when given, supplies
    each result instead (the app's per-session cache). Columns: data_date, bei_p6, bei_dcma.
    """

    def run(metric: Metric, snapshot: Snapshot) -> CheckResult:
        if result_of is not None:
            return result_of(metric, snapshot)
        return run_metric(metric, AnalysisContext(snapshot, baseline=baseline_for(snapshot)))

    rows = [
        {
            "data_date": snapshot.data_date,
            "bei_p6": run(bei_metrics["P6"], snapshot).value,
            "bei_dcma": run(bei_metrics["DCMA"], snapshot).value,
        }
        for snapshot in store
    ]
    return pd.DataFrame(rows)
