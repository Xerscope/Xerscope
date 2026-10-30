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
- SPI = EV / PV, SV = EV - PV; EV / AC is measured on baselined work only (EV exists
  for nothing else), the hours spent outside the baseline being reported apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..store import SnapshotStore
from ..xer import Snapshot
from ..xer.calendar import TimeAxis
from .baseline import Baseline


def ev_technique(code: object) -> str:
    """PROJWBS.ev_compute_type -> technique key (EC_Cmp_pct = activity % complete)."""
    c = str(code or "").strip().lower()
    if c in ("", "nan", "none") or "cmp" in c:
        return "activity"
    if "user" in c or "custom" in c:
        return "custom"
    if "50" in c:
        return "50/50"
    if "wbs" in c or "mile" in c:
        return "wbs_milestones"
    if "crv" in c or "curve" in c or "rsrc" in c:
        return "resource_curves"
    if "0" in c:
        return "0/100"
    return "activity"


def _ramp_sum(ws: np.ndarray, wf: np.ndarray, h: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Sum over rows of h * clip((g - ws) / (wf - ws), 0, 1) at every grid value g.

    Piecewise linear: one slope change at each start and finish, so the sum is
    evaluated in O((rows + grid) log rows) instead of rows x grid.
    """
    if len(ws) == 0:
        return np.zeros(len(grid))
    d = (wf - ws).astype(float)
    x = np.concatenate([ws, wf]).astype(float)
    ds = np.concatenate([h / d, -h / d])
    o = np.argsort(x, kind="stable")
    xs, slope = x[o], np.cumsum(ds[o])  # slope just after each breakpoint
    vals = np.concatenate([[0.0], np.cumsum(slope[:-1] * np.diff(xs))])  # value at each breakpoint
    j = np.searchsorted(xs, grid, side="right") - 1
    jc = np.clip(j, 0, len(xs) - 1)
    out = vals[jc] + slope[jc] * (grid - xs[jc])
    return np.where(j < 0, 0.0, out)


@dataclass
class _Spread:
    """Hours spread linearly in working time between two dates, per calendar."""

    groups: list[tuple[TimeAxis, np.ndarray, np.ndarray, np.ndarray]] = field(default_factory=list)
    steps: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)  # zero-duration rows

    @classmethod
    def build(cls, snap: Snapshot, frame: pd.DataFrame, hours: str, start: str, finish: str, cal: str) -> _Spread:
        f = frame[(frame[hours] > 0) & frame[start].notna() & frame[finish].notna()]
        out = cls()
        if f.empty:
            return out
        lo, hi = f[start].min().date(), f[finish].max().date()
        for cid, g in f.groupby(f[cal].fillna(""), sort=False):
            ax = TimeAxis(snap.calendar(cid), lo, hi)
            ws, wf = ax.work_many(g[start]), ax.work_many(g[finish])
            ws, wf = np.minimum(ws, wf), np.maximum(ws, wf)
            h = g[hours].to_numpy(float)
            zero = wf == ws
            if (~zero).any():
                out.groups.append((ax, ws[~zero], wf[~zero], h[~zero]))
            if zero.any():  # all at once when its (single) instant is reached
                out.steps.append((g[finish].to_numpy("datetime64[ns]")[zero], h[zero]))
        return out

    def at(self, stamps) -> np.ndarray:
        stamps = pd.DatetimeIndex(pd.to_datetime(pd.Series(stamps).reset_index(drop=True))).as_unit("ns")
        total = np.zeros(len(stamps))
        for ax, ws, wf, h in self.groups:
            total += _ramp_sum(ws, wf, h, ax.work_many(stamps).astype(float))
        for when, h in self.steps:
            o = np.argsort(when)
            cum = np.concatenate([[0.0], np.cumsum(h[o])])
            total += cum[np.searchsorted(when[o], stamps.values, side="right")]
        return total


def _pv_spread(baseline: Baseline) -> _Spread:
    return _Spread.build(baseline.snapshot, baseline.frame, "ev_labor_hr", "ev_start", "ev_finish", "bl_clndr_id")


def pv_curve(baseline: Baseline) -> pd.DataFrame:
    """Daily and cumulative planned labour hours of the baseline (cumulative = end of day)."""
    f = baseline.frame
    f = f[(f["ev_labor_hr"] > 0) & f["ev_start"].notna() & f["ev_finish"].notna()]
    if f.empty:
        return pd.DataFrame(columns=["date", "pv_hr", "pv_cum_hr", "pv_pct"])
    days = pd.date_range(f["ev_start"].min().normalize(), f["ev_finish"].max().normalize(), freq="D")
    cum = _pv_spread(baseline).at(days + pd.Timedelta(days=1))
    df = pd.DataFrame({"date": days, "pv_cum_hr": cum})
    df["pv_hr"] = df["pv_cum_hr"].diff().fillna(df["pv_cum_hr"])
    bac = baseline.bac_hours
    df["pv_pct"] = 100 * df["pv_cum_hr"] / bac if bac else np.nan
    return df[["date", "pv_hr", "pv_cum_hr", "pv_pct"]]


def pv_at(baseline: Baseline, when: pd.Timestamp | None) -> float:
    """Cumulative PV at an instant: sum of BL hours x Schedule % Complete, exact."""
    if when is None or pd.isna(when):
        return 0.0
    return float(_pv_spread(baseline).at([when])[0])


def schedule_pct(baseline: Baseline, when: pd.Timestamp) -> pd.Series:
    """P6 Schedule % Complete of each baseline activity at ``when`` (on the EV basis dates)."""
    f = baseline.frame
    out = pd.Series(np.nan, index=f.index)
    snap = baseline.snapshot
    ok = f["ev_start"].notna() & f["ev_finish"].notna()
    if not ok.any():
        return out
    lo, hi = min(f.loc[ok, "ev_start"].min(), when).date(), max(f.loc[ok, "ev_finish"].max(), when).date()
    for cid, g in f[ok].groupby(f.loc[ok, "bl_clndr_id"].fillna(""), sort=False):
        ax = TimeAxis(snap.calendar(cid), lo, hi)
        ws, wf, w = ax.work_many(g["ev_start"]), ax.work_many(g["ev_finish"]), ax.work(when)
        d = (wf - ws).astype(float)
        pct = np.where(
            d > 0,
            np.clip((w - ws) / np.where(d > 0, d, 1), 0, 1),
            (g["ev_finish"].to_numpy("datetime64[ns]") <= np.datetime64(when)).astype(float),
        )
        out.loc[g.index] = 100 * pct
    return out.round(2)


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
        ac = self.ac_hr - self.ac_unbaselined_hr
        return self.ev_hr / ac if ac else None

    def as_row(self) -> dict:
        def pct(v: float) -> float | None:
            return 100 * v / self.bac_hr if self.bac_hr else None

        return {
            "data_date": self.data_date,
            "bac_hr": self.bac_hr,
            "pv_hr": self.pv_hr,
            "ev_hr": self.ev_hr,
            "ac_hr": self.ac_hr,
            "etc_hr": self.etc_hr,
            "eac_hr": self.eac_hr,
            "pv_pct": pct(self.pv_hr),
            "ev_pct": pct(self.ev_hr),
            "sv_hr": self.ev_hr - self.pv_hr,
            "spi": self.spi,
            "productivity": self.productivity,
            "unbaselined": len(self.unbaselined),
            "ac_unbaselined_hr": self.ac_unbaselined_hr,
        }


def performance_pct(snap: Snapshot) -> pd.DataFrame:
    """Per activity (index task_code): EV technique of its WBS and Performance % Complete."""
    a = snap.activities.drop_duplicates("task_code").set_index("task_code")
    tech = a["ev_compute_type"].map(ev_technique) if "ev_compute_type" in a else pd.Series("activity", index=a.index)
    user = pd.to_numeric(a["ev_user_pct"], errors="coerce") if "ev_user_pct" in a else pd.Series(np.nan, index=a.index)
    done, started = a["is_complete"], a["is_started"]
    pct = a["pct_complete"].astype(float)
    pct = pct.mask(tech == "0/100", np.where(done, 100.0, 0.0))
    pct = pct.mask(tech == "50/50", np.where(done, 100.0, np.where(started, 50.0, 0.0)))
    pct = pct.mask(tech == "custom", np.where(done, 100.0, np.where(started, user.fillna(0.0), 0.0)))
    return pd.DataFrame({"ev_technique": tech, "perf_pct": pct.clip(0, 100)})


def earned(snap: Snapshot, baseline: Baseline) -> pd.DataFrame:
    """Per baseline activity: BL hours, Schedule % and Performance % now, PV and EV hours.

    ``bl_labor_hr`` / ``bl_start`` / ``bl_finish`` here are the EV basis values (see
    baseline.EV_BASES): the hours and dates PV and EV are computed from.
    """
    a = snap.activities.drop_duplicates("task_code").set_index("task_code")
    bl = baseline.frame.drop(columns=["bl_labor_hr", "bl_start", "bl_finish"]).rename(
        columns={"ev_labor_hr": "bl_labor_hr", "ev_start": "bl_start", "ev_finish": "bl_finish"}
    )
    df = (
        bl[["bl_name", "bl_labor_hr", "bl_start", "bl_finish"]]
        .join(
            a[["task_name", "wbs_code", "wbs_l1", "pct_complete", "labor_actual_hr", "labor_remaining_hr"]], how="left"
        )
        .join(performance_pct(snap), how="left")
    )
    df["in_snapshot"] = df["task_name"].notna()
    df["pct_complete"] = df["pct_complete"].fillna(0.0)
    df["perf_pct"] = df["perf_pct"].fillna(0.0)
    df["ev_technique"] = df["ev_technique"].fillna("activity")
    df["schedule_pct"] = schedule_pct(baseline, snap.data_date) if snap.data_date is not None else np.nan
    df["pv_hr"] = df["bl_labor_hr"] * df["schedule_pct"].fillna(0.0) / 100
    df["ev_hr"] = df["bl_labor_hr"] * df["perf_pct"] / 100
    return df


def ev_point(snap: Snapshot, baseline: Baseline, spread: _Spread | None = None) -> EvPoint:
    spread = _pv_spread(baseline) if spread is None else spread
    e = earned(snap, baseline)
    a = snap.activities
    unbaselined = sorted(set(a["task_code"]) - set(baseline.frame.index))
    fallback = sorted(e.index[e["ev_technique"].isin(["wbs_milestones", "resource_curves"]) & e["in_snapshot"]])
    pv = float(spread.at([snap.data_date])[0]) if snap.data_date is not None else 0.0
    return EvPoint(
        snap.data_date,
        baseline.bac_hours,
        pv,
        float(e["ev_hr"].sum()),
        float(a["labor_actual_hr"].sum()),
        float(a["labor_remaining_hr"].sum()),
        unbaselined,
        fallback,
        ac_unbaselined_hr=float(a.loc[a["task_code"].isin(unbaselined), "labor_actual_hr"].sum()),
    )


def evm_series(store: SnapshotStore, baseline: Baseline) -> pd.DataFrame:
    spread = _pv_spread(baseline)
    return pd.DataFrame([ev_point(s, baseline, spread).as_row() for s in store])


def forecast_curve(snap: Snapshot) -> pd.DataFrame:
    """Cumulative hours, one row per day from the data date's day to the last finish: AC
    plus the remaining hours of open work spread over working time to each activity's
    finish. As in ``pv_curve``, a row names a day and holds the cumulative at its end."""
    a = snap.activities
    open_ = a[~a["is_complete"]].copy()
    dd = snap.data_date
    ac = float(a["labor_actual_hr"].sum())
    if dd is None:
        return pd.DataFrame({"date": [], "fc_cum_hr": []})
    open_["fc_start"] = open_["start"].where(open_["start"] > dd, dd)
    open_["fc_finish"] = open_["finish"].where(open_["finish"] > open_["fc_start"], open_["fc_start"])
    f = open_[(open_["labor_remaining_hr"] > 0) & open_["fc_finish"].notna()]
    if f.empty:
        return pd.DataFrame({"date": [dd.normalize()], "fc_cum_hr": [ac]})
    days = pd.date_range(dd.normalize(), f["fc_finish"].max().normalize(), freq="D")
    cum = ac + _Spread.build(snap, f, "labor_remaining_hr", "fc_start", "fc_finish", "clndr_id").at(
        days + pd.Timedelta(days=1)
    )
    return pd.DataFrame({"date": days, "fc_cum_hr": cum})
