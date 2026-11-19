"""Earned value and Earned Schedule on a part of the project: the tasks of an activity code (CodeFilter).

The rule is a design decision, as for the PPC (``test_ppc_code_filter``): the tasks are those assigned
the values picked in the update measured, whatever the baseline's own codes; BAC, PV, EV, AC and ETC
then count these tasks only, by the same formulas as for the whole project. Every value below is
computed by hand in its docstring. Calendar C8 (Monday to Friday, 8 h a day); week 1 is 2026-03-02
to 03-06, week 2 03-09 to 03-13.
"""

from __future__ import annotations

import pytest
from test_earned_schedule import DAY_MIN, planned, progressed
from xerkit import snap

from xerscope.analysis import Baseline
from xerscope.analysis.baseline import restricted
from xerscope.analysis.evm import (
    earned_schedule,
    ev_point,
    evm_series,
    schedule_gap_by_status,
    update_and_baseline_of_code,
)
from xerscope.analysis.task_filters import CodeFilter
from xerscope.store import SnapshotStore

pytestmark = pytest.mark.oracle("standard")

WEEK_1, WEEK_2 = ("2026-03-02 08:00", "2026-03-06 17:00"), ("2026-03-09 08:00", "2026-03-13 17:00")
PLAN = {"A": WEEK_1, "B": WEEK_2, "C": WEEK_1, "D": WEEK_2, "E": WEEK_1}  # 40 h each
DISCIPLINE = {"A": "CIV", "B": "CIV", "C": "MEC", "D": "MEC"}  # E has no discipline
CIV, MEC = CodeFilter("Discipline", ("CIV",)), CodeFilter("Discipline", ("MEC",))
SUMMED = ("bac_hr", "pv_hr", "ev_hr", "ac_hr", "etc_hr")


def update_on(data_date: str, progress: dict[str, tuple[int, int, int]]):
    """The five tasks at ``data_date``; ``progress``: % complete, actual hours, remaining hours of each
    task that has started. The disciplines are in the update only."""
    tasks = []
    for code, (start, finish) in PLAN.items():
        task = planned(code, start, finish)
        if code in progress:
            percent, actual_hr, remaining_hr = progress[code]
            task = {**progressed(task, percent), "act_work_qty": str(actual_hr), "remain_work_qty": str(remaining_hr)}
        tasks.append(task)
    codes = [(code, "Discipline", value) for code, value in DISCIPLINE.items()]
    return snap(tasks, codes=codes, data_date=data_date)


def the_plan() -> Baseline:
    return Baseline.from_snapshot(snap([planned(code, *dates) for code, dates in PLAN.items()], data_date=WEEK_1[0]))


def end_of_week_2():
    """Friday 03-13 17:00: A done (44 h spent), B at 50 % (16 h spent, 20 h left), C at 50 % (30 h spent,
    25 h left), D not started (40 h left), E done (40 h spent)."""
    return update_on(WEEK_2[1], {"A": (100, 44, 0), "B": (50, 16, 20), "C": (50, 30, 25), "E": (100, 40, 0)})


def summed(point) -> tuple[float, ...]:
    return tuple(getattr(point, name) for name in SUMMED)


def test_the_earned_value_of_a_discipline_counts_its_tasks_only():
    """CIV is A and B: BAC 80, PV 80 (both weeks elapsed), EV 40 + 20 = 60, AC 44 + 16 = 60, ETC 0 + 20.
    MEC is C and D: BAC 80, PV 80, EV 20 + 0 = 20, AC 30, ETC 25 + 40 = 65. The whole project adds E
    (40, 40, 40, 40, 0): BAC 200, PV 200, EV 120, AC 130, ETC 85."""
    update, baseline = end_of_week_2(), the_plan()
    assert summed(ev_point(*update_and_baseline_of_code(update, baseline, CIV))) == (80.0, 80.0, 60.0, 60.0, 20.0)
    assert summed(ev_point(*update_and_baseline_of_code(update, baseline, MEC))) == (80.0, 80.0, 20.0, 30.0, 65.0)
    assert summed(ev_point(update, baseline)) == (200.0, 200.0, 120.0, 130.0, 85.0)


def test_a_task_of_another_discipline_is_neither_missing_from_the_baseline_nor_deleted():
    """On CIV, C, D and E are out of the measure on both sides: none is listed as a task the baseline
    does not hold, none as a baseline task the update no longer holds."""
    point = ev_point(*update_and_baseline_of_code(end_of_week_2(), the_plan(), CIV))
    assert point.unbaselined == [] and point.deleted == [] and point.ac_unbaselined_hr == 0.0


def test_the_earned_schedule_of_a_discipline_is_read_on_its_own_plan():
    """CIV: its plan runs 10 working days and holds 60 h on Wednesday 03-11 at 12:00 (A's 40 h, then B's
    Monday 8, Tuesday 8, Wednesday 4): ES = 7.5 wd, AT = 10 wd. MEC: its plan holds 20 h on Wednesday
    03-04 at 12:00 (C alone in week 1): ES = 2.5 wd, AT = 10 wd."""
    update, baseline = end_of_week_2(), the_plan()
    civ = earned_schedule(*update_and_baseline_of_code(update, baseline, CIV))
    mec = earned_schedule(*update_and_baseline_of_code(update, baseline, MEC))
    assert (civ.es_min / DAY_MIN, civ.at_min / DAY_MIN, civ.ev_hr) == (7.5, 10.0, 60.0)
    assert (mec.es_min / DAY_MIN, mec.at_min / DAY_MIN, mec.ev_hr) == (2.5, 10.0, 20.0)


def test_the_gap_by_status_of_a_discipline_holds_its_tasks_only():
    """MEC: C in progress (PV 40, EV 20: -20 h), D not started (PV 40, EV 0: -40 h), nothing complete."""
    gaps = schedule_gap_by_status(*update_and_baseline_of_code(end_of_week_2(), the_plan(), MEC))
    assert gaps.set_index("status")[["tasks", "behind_hr"]].to_dict("index") == {
        "In progress": {"tasks": 1, "behind_hr": -20.0},
        "Not started": {"tasks": 1, "behind_hr": -40.0},
    }


def test_without_a_filter_the_update_and_its_baseline_are_the_ones_given():
    update, baseline = end_of_week_2(), the_plan()
    kept_update, kept_baseline = update_and_baseline_of_code(update, baseline, None)
    assert kept_update is update and kept_baseline is baseline


def test_a_restricted_baseline_keeps_the_tasks_named_and_their_assignment_costs():
    """A and B each carry a priced assignment (40 h; 1 000 and 500). Restricted to B and to Z, a task the
    baseline does not hold: one row, 40 h, B's assignment alone, cost 500."""
    assignments = [
        {"task_code": code, "rsrc_id": "R1", "rsrc_type": "RT_Labor", "target_qty": "40", "target_cost": cost}
        for code, cost in (("A", "1000"), ("B", "500"))
    ]
    tasks = [planned("A", *WEEK_1), planned("B", *WEEK_2)]
    kept = restricted(Baseline.from_snapshot(snap(tasks, assign=assignments, data_date=WEEK_1[0])), {"B", "Z"})
    assert kept.frame.index.tolist() == ["B"] and kept.bac_hours == 40.0
    assert kept.assignment_costs["task_code"].tolist() == ["B"] and kept.assignment_costs["cost"].tolist() == [500.0]


def test_the_series_of_a_discipline_reads_the_code_in_each_update():
    """Two updates. Friday 03-06 17:00: A at 50 % (20 h spent, 20 h left), C at 25 %. Friday 03-13: as
    above. CIV, update 1: BAC 80, PV 40 (week 1 only), EV 20, AC 20. Update 2: BAC 80, PV 80, EV 60, AC 60.
    Without a filter the series is the one of the whole project: EV 20 + 10 = 30, then 120."""
    first = update_on(WEEK_1[1], {"A": (50, 20, 20), "C": (25, 10, 30)})
    store, baseline = SnapshotStore([first, end_of_week_2()]), the_plan()
    civ = evm_series(store, baseline, code_filter=CIV)
    assert civ[["bac_hr", "pv_hr", "ev_hr", "ac_hr"]].to_numpy().tolist() == [[80, 40, 20, 20], [80, 80, 60, 60]]
    assert evm_series(store, baseline)["ev_hr"].tolist() == [30.0, 120.0]


@pytest.mark.parametrize("data_date", [WEEK_1[1], "2026-03-11 12:00", WEEK_2[1]])
def test_the_disciplines_and_the_tasks_without_one_add_up_to_the_project(data_date):
    """Hours add up across a partition of the tasks (days do not): CIV + MEC + the tasks of neither."""
    update, baseline = update_on(data_date, {"A": (100, 44, 0), "B": (50, 16, 20), "C": (50, 30, 25)}), the_plan()
    neither = restricted(baseline, {"E"}), update.by_code.loc[["E"]]
    parts = [ev_point(*update_and_baseline_of_code(update, baseline, code)) for code in (CIV, MEC)]
    whole = ev_point(update, baseline)
    assert whole.bac_hr == pytest.approx(sum(part.bac_hr for part in parts) + neither[0].bac_hours)
    assert whole.ac_hr == pytest.approx(sum(part.ac_hr for part in parts) + neither[1]["labor_actual_hr"].sum())
    pv_of_e = 40.0  # week 1 is over at each of the three dates
    assert whole.pv_hr == pytest.approx(sum(part.pv_hr for part in parts) + pv_of_e)
