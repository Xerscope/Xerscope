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
- Activities not in the baseline earn nothing (listed); activities deleted since earn
  nothing either.
- AC = actual labour units and ETC = remaining labour units of every activity in the
  update, baselined or not; EAC = AC + ETC.
- ETC technique: P6 sets it per WBS element too (PROJWBS.ev_etc_compute_type): remaining
  units, or a performance factor PF with ETC = PF x (BAC - EV) (Oracle Pro 25, Earned Value
  tab - WBS Details). xerscope always uses the remaining units; ``etc_settings`` reports
  the WBS that use a PF.
- SPI = EV / PV, SV = EV - PV; EV / AC is measured on baselined work only (EV exists
  for nothing else), the hours spent outside the baseline being reported apart.
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
from .checks import AnalysisContext, run_metric
from .standards import Metric


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
    """Daily and cumulative planned labour hours of the baseline (cumulative = end of day)."""
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


def schedule_pct(baseline: Baseline, when: pd.Timestamp) -> pd.Series:
    """P6 Schedule % Complete of each baseline activity at ``when`` (on the EV basis dates)."""
    frame = baseline.frame
    percent = pd.Series(np.nan, index=frame.index)
    has_dates = frame["ev_start"].notna() & frame["ev_finish"].notna()
    if not has_dates.any():
        return percent
    first_day = min(frame.loc[has_dates, "ev_start"].min(), when).date()
    last_day = max(frame.loc[has_dates, "ev_finish"].max(), when).date()
    for calendar_id, group in frame[has_dates].groupby(frame.loc[has_dates, "bl_clndr_id"].fillna(""), sort=False):
        axis = TimeAxis(baseline.snapshot.calendar(calendar_id), first_day, last_day)
        work_starts, work_finishes = axis.work_many(group["ev_start"]), axis.work_many(group["ev_finish"])
        work_now = axis.work(when)
        durations = (work_finishes - work_starts).astype(float)
        # a zero-length activity is 0% before its instant and 100% from then on
        fraction = np.where(
            durations > 0,
            np.clip((work_now - work_starts) / np.where(durations > 0, durations, 1), 0, 1),
            (group["ev_finish"].to_numpy("datetime64[ns]") <= np.datetime64(when)).astype(float),
        )
        percent.loc[group.index] = 100 * fraction
    return percent  # unrounded: per-activity PV must sum to ev_point's PV; tables round on display


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

    @property
    def eac_hr(self) -> float:
        return self.ac_hr + self.etc_hr

    @property
    def spi(self) -> float | None:
        return self.ev_hr / self.pv_hr if self.pv_hr else None

    @property
    def productivity(self) -> float | None:
        """EV per hour spent on baselined work: EV only exists for baselined activities,
        so hours spent on the others would make the ratio look worse than the work is."""
        baselined_actual_hr = self.ac_hr - self.ac_unbaselined_hr
        return self.ev_hr / baselined_actual_hr if baselined_actual_hr else None

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
            "unbaselined": len(self.unbaselined),
            "ac_unbaselined_hr": self.ac_unbaselined_hr,
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
    """Per baseline activity: BL hours, Schedule % and Performance % now, PV and EV hours.

    ``bl_labor_hr`` / ``bl_start`` / ``bl_finish`` here are the EV basis values (see
    baseline.EV_BASES): the hours and dates PV and EV are computed from.
    """
    activities = snapshot.by_code
    baseline_ev = baseline.frame.drop(columns=["bl_labor_hr", "bl_start", "bl_finish"]).rename(
        columns={"ev_labor_hr": "bl_labor_hr", "ev_start": "bl_start", "ev_finish": "bl_finish"}
    )
    current_columns = ["task_name", "wbs_code", "wbs_l1", "pct_complete", "labor_actual_hr", "labor_remaining_hr"]
    result = (
        baseline_ev[["bl_name", "bl_labor_hr", "bl_start", "bl_finish"]]
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
    return result


def ev_point(snapshot: Snapshot, baseline: Baseline, spread: _Spread | None = None) -> EvPoint:
    spread = _pv_spread(baseline) if spread is None else spread
    earned_values = earned(snapshot, baseline)
    activities = snapshot.activities
    unbaselined = sorted(set(activities["task_code"]) - set(baseline.frame.index))
    on_fallback = earned_values["ev_technique"].isin(["wbs_milestones", "resource_curves"])
    fallback = sorted(earned_values.index[on_fallback & earned_values["in_snapshot"]])
    planned_hr = float(spread.at([snapshot.data_date])[0]) if snapshot.data_date is not None else 0.0
    return EvPoint(
        snapshot.data_date,
        baseline.bac_hours,
        planned_hr,
        float(earned_values["ev_hr"].sum()),
        float(activities["labor_actual_hr"].sum()),
        float(activities["labor_remaining_hr"].sum()),
        unbaselined,
        fallback,
        ac_unbaselined_hr=float(activities.loc[activities["task_code"].isin(unbaselined), "labor_actual_hr"].sum()),
    )


def evm_series(store: SnapshotStore, baseline: Baseline) -> pd.DataFrame:
    spread = _pv_spread(baseline)
    return pd.DataFrame([ev_point(snapshot, baseline, spread).as_row() for snapshot in store])


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
    store: SnapshotStore, bei_metrics: Mapping[str, Metric], baseline_for: Callable[[Snapshot], Baseline | None]
) -> pd.DataFrame:
    """Baseline Execution Index of every update under the P6 and DCMA definitions.

    ``bei_metrics`` holds the ``bei`` metric of the "P6" and "DCMA" standards; ``baseline_for``
    gives each snapshot its own baseline. Columns: data_date, bei_p6, bei_dcma.
    """
    rows = []
    for snapshot in store:
        context = AnalysisContext(snapshot, baseline=baseline_for(snapshot))
        rows.append(
            {
                "data_date": snapshot.data_date,
                "bei_p6": run_metric(bei_metrics["P6"], context).value,
                "bei_dcma": run_metric(bei_metrics["DCMA"], context).value,
            }
        )
    return pd.DataFrame(rows)
