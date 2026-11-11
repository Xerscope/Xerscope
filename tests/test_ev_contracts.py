"""Earned value contracts on random schedules (seeded, so a failure always reproduces).

No P6 output exists for these schedules: they check what the labour-unit earned value must
satisfy whatever the schedule, from its definitions (``analysis/evm.py``): PV = baseline hours x
Schedule % Complete and EV = baseline hours x Performance % Complete, each percentage between 0
and 100, summed over the baseline activities the update holds.

- BAC >= 0, 0 <= PV <= BAC, 0 <= EV <= BAC
- per activity, PV and EV between 0 and its baseline hours; the BAC, the PV and the EV are the
  sums over the baseline activities the update holds
- the planned value curve never goes down, has no negative day, ends at the baseline's hours,
  and at the status date holds the PV

Each schedule sits under one WBS with an earned value technique drawn at random, and is tried
under every earned value basis, in four shapes: plain; a percent complete, actual hours or custom
WBS percent outside their range (150 %, twice the budget); a planned finish before the planned
start; a baseline that is another schedule, with tasks deleted and added since.
Labour hours are never negative here: a negative budget is read as written and none of the
bounds then holds.
"""

from __future__ import annotations

import random

import pandas as pd
import pytest
from xerkit import snap

from xerscope.analysis import Baseline
from xerscope.analysis.baseline import EV_BASES
from xerscope.analysis.evm import earned, ev_point, pv_curve

pytestmark = pytest.mark.oracle("property")

SEEDS = range(25)
SHAPES = ["plain", "progress out of range", "inverted dates", "separate baseline"]
DAY_0 = pd.Timestamp("2026-03-02")
TOLERANCE = 1e-6  # hours
TECHNIQUES = ["", "EC_Cmp_pct", "EC_0_100", "EC_50_50", "EC_User_pct"]  # PROJWBS.ev_compute_type


def _stamp(day: int, end: bool = False) -> str:
    return (DAY_0 + pd.Timedelta(days=day)).strftime("%Y-%m-%d") + (" 17:00" if end else " 08:00")


def _random_wbs(rnd: random.Random, shape: str) -> list[dict]:
    percent = rnd.choice([150, -20, 30]) if shape == "progress out of range" else rnd.randint(0, 100)
    return [
        {
            "wbs_id": "W1",
            "proj_id": "1",
            "wbs_short_name": "W1",
            "wbs_name": "W1",
            "proj_node_flag": "N",
            "parent_wbs_id": "",
            "seq_num": "1",
            "ev_compute_type": rnd.choice(TECHNIQUES),
            "ev_user_pct": str(percent),
        }
    ]


def _random_tasks(rnd: random.Random, status_day: int, shape: str, codes: list[str]) -> list[dict]:
    tasks = []
    for code in codes:
        start, length, hours = rnd.randint(0, 60), rnd.randint(0, 30), rnd.choice([0, 0, 8, 40, 80, 400])
        finish = start + length
        if shape == "inverted dates" and rnd.random() < 0.3:
            start, finish = finish + 1, start
        task = {
            "task_code": code,
            "wbs_id": "W1",
            "clndr_id": rnd.choice(["C8", "C8", "C10", "C7D"]),
            "task_type": rnd.choice(["TT_Task"] * 6 + ["TT_Rsrc", "TT_LOE", "TT_FinMile"]),
            "complete_pct_type": rnd.choice(["CP_Drtn", "CP_Units", "CP_Phys"]),
            "target_start_date": _stamp(start),
            "target_end_date": _stamp(finish, end=True),
            "early_start_date": _stamp(start + rnd.randint(0, 10)),
            "early_end_date": _stamp(max(start, finish) + rnd.randint(0, 15), end=True),
            "target_drtn_hr_cnt": str(8 * (length + 1)),
            "remain_drtn_hr_cnt": str(8 * (length + 1)),
            "target_work_qty": str(hours),
            "remain_work_qty": str(hours),
        }
        progress = rnd.random()
        if progress < 0.3:
            spent, percent = round(hours * rnd.random(), 1), rnd.randint(0, 100)
            if shape == "progress out of range":
                spent, percent = rnd.choice([spent, hours * 2]), rnd.choice([150, 250, -20, percent])
            task |= {
                "status_code": "TK_Active",
                "act_start_date": _stamp(min(start, status_day)),
                "remain_drtn_hr_cnt": str(rnd.randint(0, 8 * (length + 1))),
                "act_work_qty": str(spent),
                "remain_work_qty": str(round(hours - min(spent, hours), 1)),
                "phys_complete_pct": str(percent),
            }
        elif progress < 0.55:
            task |= {
                "status_code": "TK_Complete",
                "act_start_date": _stamp(min(start, status_day)),
                "act_end_date": _stamp(min(max(start, finish), status_day), end=True),
                "remain_drtn_hr_cnt": "0",
                "act_work_qty": str(hours),
                "remain_work_qty": "0",
                "phys_complete_pct": "100",
            }
        if task["task_type"] == "TT_FinMile":
            task |= {"target_drtn_hr_cnt": "0", "remain_drtn_hr_cnt": "0"}
        tasks.append(task)
    return tasks


def random_update(seed: int, shape: str):
    """An update and the snapshot its baseline is taken from: itself (planned dates), or under
    "separate baseline" another schedule holding four in five of its tasks and up to five more."""
    rnd = random.Random(seed)
    status_day = rnd.randint(0, 70)
    codes = [f"T{i:02d}" for i in range(rnd.randint(1, 25))]
    wbs = _random_wbs(rnd, shape)
    update = snap(_random_tasks(rnd, status_day, shape, codes), wbs=wbs, data_date=_stamp(status_day))
    if shape != "separate baseline":
        return update, None
    kept = [code for code in codes if rnd.random() < 0.8] + [f"N{i:02d}" for i in range(rnd.randint(0, 5))]
    return update, snap(_random_tasks(rnd, 0, shape, kept or codes[:1]), wbs=wbs, data_date=_stamp(0))


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("seed", SEEDS)
def test_earned_value_stays_within_its_bounds(seed, shape):
    update, baseline_snapshot = random_update(seed, shape)
    for basis in EV_BASES:
        where = (seed, shape, basis)
        if baseline_snapshot is None:
            baseline = Baseline.planned(update, ev_basis=basis)
        else:
            baseline = Baseline.from_snapshot(baseline_snapshot, ev_basis=basis)
        point = ev_point(update, baseline)
        assert point.bac_hr >= -TOLERANCE, (where, "BAC")
        assert -TOLERANCE <= point.pv_hr <= point.bac_hr + TOLERANCE, (where, "PV")
        assert -TOLERANCE <= point.ev_hr <= point.bac_hr + TOLERANCE, (where, "EV")

        tasks = earned(update, baseline)
        tasks = tasks[tasks["in_snapshot"]]
        for column in ("pv_hr", "ev_hr"):
            assert (tasks[column] >= -TOLERANCE).all(), (where, column, "negative")
            assert (tasks[column] <= tasks["bl_labor_hr"] + TOLERANCE).all(), (where, column, "above the hours")
        assert tasks["bl_labor_hr"].sum() == pytest.approx(point.bac_hr, abs=1e-3), (where, "sum of hours")
        assert tasks["pv_hr"].sum() == pytest.approx(point.pv_hr, abs=1e-3), (where, "sum of PV")
        assert tasks["ev_hr"].sum() == pytest.approx(point.ev_hr, abs=1e-3), (where, "sum of EV")

        curve = pv_curve(baseline)
        if len(curve):
            assert (curve["pv_hr"] >= -TOLERANCE).all(), (where, "a negative day")
            assert (curve["pv_cum_hr"].diff().dropna() >= -TOLERANCE).all(), (where, "the curve goes down")
            assert curve["pv_cum_hr"].iloc[-1] == pytest.approx(baseline.bac_hours, abs=1e-3), (where, "curve end")
        held = pv_curve(baseline, update)
        at_status_date = held.loc[held["date"] == update.data_date, "pv_cum_hr"]
        if len(at_status_date):
            assert float(at_status_date.iloc[0]) == pytest.approx(point.pv_hr, abs=1e-3), (where, "curve")
