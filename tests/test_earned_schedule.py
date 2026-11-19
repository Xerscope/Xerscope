"""Earned Schedule (Lipke, "Schedule is Different", The Measurable News, 2003): ES is the instant of
the plan at which the planned value equals the earned value; SV(t) = ES - AT, SPI(t) = ES / AT.

No P6 output exists: P6 does not compute ES (Alshaheen, The Measurable News 2018.02). Every value
below is computed by hand in its docstring. Durations are counted in plan time, the working time of at
least one calendar of the tasks measured; with every task on C8 (Monday to Friday, 08:00-12:00 and
13:00-17:00, 8 h a day) it is C8's working time. A plan day is 8 h, C8 being the project calendar.
Week 1 is 2026-03-02 to 03-06, week 2 03-09 to 03-13, week 3 03-16 to 03-20.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from test_ev_contracts import SHAPES, random_update
from xerkit import snap

from xerscope.analysis import Baseline
from xerscope.analysis.evm import earned_schedule, ev_point, schedule_gap_by_status
from xerscope.xer.calendar import WorkCalendar, union_of

pytestmark = pytest.mark.oracle("standard")

DAY_MIN = 8 * 60  # working minutes in a day of C8


def planned(code: str, start: str, finish: str, hours: int = 40) -> dict:
    """A task not started, planned from ``start`` to ``finish`` with ``hours`` labour hours."""
    return {
        "task_code": code,
        "complete_pct_type": "CP_Phys",
        "target_start_date": start,
        "target_end_date": finish,
        "early_start_date": start,
        "early_end_date": finish,
        "target_work_qty": str(hours),
        "remain_work_qty": str(hours),
    }


def progressed(task: dict, percent: int) -> dict:
    """``task`` at ``percent`` physical % complete: started, or complete at 100."""
    status = "TK_Complete" if percent == 100 else "TK_Active"
    progress = {"status_code": status, "phys_complete_pct": str(percent), "act_start_date": task["target_start_date"]}
    if percent == 100:
        progress["act_end_date"] = task["target_end_date"]
    return {**task, **progress}


A = planned("A", "2026-03-02 08:00", "2026-03-06 17:00")  # week 1
B = planned("B", "2026-03-09 08:00", "2026-03-13 17:00")  # week 2
B_WEEK_3 = planned("B", "2026-03-16 08:00", "2026-03-20 17:00")


def schedule_of(tasks: list[dict], percents: dict[str, int], data_date: str):
    """The Earned Schedule of an update holding ``tasks`` at ``percents``, against their plan."""
    baseline = Baseline.from_snapshot(snap(tasks, data_date="2026-03-02 08:00"))
    update = snap([progressed(task, percents.get(task["task_code"], 0)) for task in tasks], data_date=data_date)
    return earned_schedule(update, baseline)


def in_days(minutes: int) -> float:
    return minutes / DAY_MIN


def test_two_tasks_in_a_row_half_of_the_second_done_at_the_end_of_its_week():
    """A (40 h, week 1) done, B (40 h, week 2) at 50 % on Friday 03-13 17:00. EV = 40 + 20 = 60 h. The plan
    reached 60 h on Wednesday 03-11 at 12:00 (B's 20 h: Monday 8, Tuesday 8, Wednesday 4), 7.5 working days
    after Monday 03-02 08:00: ES = 7.5 wd. AT = 10 wd, PD = 10 wd. SV(t) = -2.5 wd, SPI(t) = 0.75."""
    schedule = schedule_of([A, B], {"A": 100, "B": 50}, "2026-03-13 17:00")
    assert (schedule.bac_hr, schedule.pv_hr, schedule.ev_hr) == (80.0, 80.0, 60.0)
    assert in_days(schedule.es_min) == 7.5
    assert in_days(schedule.at_min) == 10.0
    assert in_days(schedule.pd_min) == 10.0
    assert in_days(schedule.sv_min) == -2.5
    assert schedule.spi_t == 0.75
    assert schedule.plan_start == pd.Timestamp("2026-03-02 08:00")
    assert schedule.plan_finish == pd.Timestamp("2026-03-13 17:00")
    assert schedule.note == ""


def test_on_plan_mid_day_the_earned_schedule_is_the_actual_time():
    """Wednesday 03-11 12:00, A done, B at 50 %: EV = 60 h = PV. ES = AT = 7.5 wd, SPI(t) = 1."""
    schedule = schedule_of([A, B], {"A": 100, "B": 50}, "2026-03-11 12:00")
    assert schedule.pv_hr == schedule.ev_hr == 60.0
    assert in_days(schedule.es_min) == in_days(schedule.at_min) == 7.5
    assert schedule.spi_t == 1.0


def test_all_earned_on_a_saturday_the_earned_schedule_is_the_planned_duration():
    """Saturday 03-14 10:00, A and B done: EV = BAC = 80 h, so ES = PD = 10 wd (Lipke). A Saturday holds no
    working time on C8: AT is the working time to Friday 17:00, 10 wd. SPI(t) = 1."""
    schedule = schedule_of([A, B], {"A": 100, "B": 100}, "2026-03-14 10:00")
    assert in_days(schedule.es_min) == in_days(schedule.pd_min) == in_days(schedule.at_min) == 10.0
    assert schedule.spi_t == 1.0


def test_finished_late_the_last_index_is_the_planned_duration_over_the_actual_time():
    """A and B done on Friday 03-20 17:00, a week after the plan: ES = PD = 10 wd, AT = 15 wd, SPI(t) = 2/3
    and SV(t) = -5 wd: the delay stays measured at the end, where EV / PV is back to 1 (Lipke)."""
    schedule = schedule_of([A, B], {"A": 100, "B": 100}, "2026-03-20 17:00")
    assert in_days(schedule.es_min) == 10.0
    assert in_days(schedule.at_min) == 15.0
    assert in_days(schedule.sv_min) == -5.0
    assert schedule.spi_t == pytest.approx(2 / 3)


def test_while_the_plan_asks_for_no_hours_the_status_date_is_the_earned_schedule():
    """A in week 1, B in week 3: the plan asks for no hours in week 2. Wednesday 03-11 12:00, A done, B not
    started: EV = 40 h, which the plan holds from Friday 03-06 17:00 (5 wd) to Monday 03-16 08:00 (10 wd).
    The status date, 7.5 wd, lies in between: ES = AT = 7.5 wd, no delay counted."""
    schedule = schedule_of([A, B_WEEK_3], {"A": 100}, "2026-03-11 12:00")
    assert in_days(schedule.es_min) == in_days(schedule.at_min) == 7.5
    assert schedule.spi_t == 1.0


def test_after_a_stretch_without_planned_hours_a_late_start_is_counted_from_its_end():
    """Same plan, Wednesday 03-18 12:00 (AT = 12.5 wd), B still not started: EV = 40 h, held from 5 wd to
    10 wd. The status date is past that stretch: ES = 10 wd, SV(t) = -2.5 wd, the time B has lost."""
    schedule = schedule_of([A, B_WEEK_3], {"A": 100}, "2026-03-18 12:00")
    assert in_days(schedule.es_min) == 10.0
    assert in_days(schedule.sv_min) == -2.5


def test_nothing_earned_at_the_start_of_the_plan_the_earned_schedule_is_zero():
    """Wednesday 03-04 12:00 (AT = 2.5 wd), nothing done: EV = 0, the plan holds 0 h only at its start."""
    schedule = schedule_of([A, B], {}, "2026-03-04 12:00")
    assert schedule.es_min == 0
    assert schedule.spi_t == 0.0


def test_a_status_date_before_the_plan_starts_gives_no_earned_schedule():
    schedule = schedule_of([A, B], {}, "2026-02-27 08:00")
    assert schedule.es_min is None and schedule.spi_t is None
    assert schedule.note == "status date before the plan starts"


def test_hours_earned_on_a_task_without_planned_dates_are_left_out_and_reported():
    """C (16 h) has no planned date: there is no plan to read its hours on. It is 50 % done: 8 h earned,
    left out of the EV the ES is read with, and reported. A and B as in the first test: ES = 7.5 wd."""
    c = {**planned("C", "", "", hours=16), "early_start_date": "", "early_end_date": ""}
    schedule = schedule_of([A, B, c], {"A": 100, "B": 50, "C": 50}, "2026-03-13 17:00")
    assert schedule.ev_hr == 60.0 and schedule.ev_left_out_hr == 8.0
    assert in_days(schedule.es_min) == 7.5


@pytest.mark.oracle("property")
@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("seed", range(25))
def test_on_random_schedules_the_planned_value_is_the_one_of_ev_point_and_the_es_lies_in_the_plan(seed, shape):
    """The PV read at the status date is ev_point's, on every EV basis; the ES lies between 0 and PD."""
    update, other = random_update(seed, shape)
    baseline = Baseline.from_snapshot(other) if other is not None else Baseline.planned(update)
    schedule = earned_schedule(update, baseline)
    assert schedule.pv_hr == pytest.approx(ev_point(update, baseline).pv_hr, abs=1e-6)
    if schedule.es_min is not None:
        assert 0 <= schedule.es_min <= schedule.pd_min


@pytest.mark.parametrize("hours", [13.7, 23.3])
def test_hours_that_do_not_add_up_exactly_in_floating_point_still_find_the_stretch(hours):
    """As above with A of 13.7 h or 23.3 h, done: the PV summed over the stretch of week 2 comes out a hair
    above or below A's hours. Read as equal, the status date stays in the stretch: ES = AT = 7.5 wd. Read
    exactly, the ES fell to 10 wd or 5 wd."""
    a = planned("A", "2026-03-02 08:00", "2026-03-06 17:00", hours=hours)
    schedule = schedule_of([a, B_WEEK_3], {"A": 100}, "2026-03-11 12:00")
    assert in_days(schedule.es_min) == 7.5


def test_the_weekend_worked_by_a_seven_day_task_is_plan_time_on_a_five_day_project():
    """A (56 h) on the 7-day calendar C7D (08:00-16:00), Monday 03-02 08:00 to Sunday 03-08 16:00, the project
    on C8. Plan time is C7D's working time, A being the only task measured. Monday 03-09 08:00, A at 5/7:
    EV = 40 h, PV = 56 h. The plan reached 40 h on Friday 03-06 at 16:00, 5 days of 8 h after the start: ES =
    40 h = 5 plan days. AT = PD = 7 days of 8 h = 7 plan days. SV(t) = -2 plan days, the weekend's 16 h;
    SPI(t) = 40 / 56."""
    a = {**planned("A", "2026-03-02 08:00", "2026-03-08 16:00", hours=56), "clndr_id": "C7D"}
    baseline = Baseline.from_snapshot(snap([a], data_date="2026-03-02 08:00"))
    update = snap([progressed(a, 0) | {"status_code": "TK_Active", "phys_complete_pct": str(500 / 7)}],
                  data_date="2026-03-09 08:00")  # fmt: skip
    schedule = earned_schedule(update, baseline)
    assert (schedule.ev_hr, schedule.pv_hr) == (pytest.approx(40.0), 56.0)
    assert in_days(schedule.es_min) == 5.0
    assert in_days(schedule.at_min) == in_days(schedule.pd_min) == 7.0
    assert in_days(schedule.sv_min) == -2.0
    assert schedule.spi_t == pytest.approx(40 / 56)


FIVE_DAYS = ((480, 720), (780, 1020))  # 08:00-12:00 and 13:00-17:00
SEVEN_DAYS = ((480, 960),)  # 08:00-16:00
NONE: tuple = ()
GOOD_FRIDAY, MAY_DAY, CHRISTMAS = date(2026, 4, 3), date(2026, 5, 1), date(2026, 12, 25)


def test_plan_time_works_when_one_calendar_works_and_stops_when_all_of_them_stop():
    """A five-day calendar off on Good Friday and Christmas, a seven-day one off on Christmas and on Friday
    05-01. Their union: Monday to Friday 08:00-17:00 (the two calendars' periods merged), the weekend
    08:00-16:00 (the seven-day one), Good Friday 08:00-16:00 (worked by the seven-day one), 05-01 the five-day
    calendar's day (08:00-12:00, 13:00-17:00), Christmas off (both off)."""
    five_days = WorkCalendar(
        "5", "five days", 8.0, (FIVE_DAYS,) * 5 + (NONE, NONE), {GOOD_FRIDAY: NONE, CHRISTMAS: NONE}
    )
    seven_days = WorkCalendar("7", "seven days", 8.0, (SEVEN_DAYS,) * 7, {CHRISTMAS: NONE, MAY_DAY: NONE})
    plan_time = union_of([five_days, seven_days], 8.0)
    assert plan_time.periods(date(2026, 3, 2)) == ((480, 1020),)  # a Monday
    assert plan_time.periods(date(2026, 3, 7)) == SEVEN_DAYS  # a Saturday
    assert plan_time.periods(GOOD_FRIDAY) == SEVEN_DAYS
    assert plan_time.periods(MAY_DAY) == FIVE_DAYS
    assert plan_time.periods(CHRISTMAS) == NONE
    assert plan_time.hours_per_day == 8.0


def test_the_union_of_one_calendar_is_that_calendar():
    five_days = WorkCalendar("5", "five days", 8.0, (FIVE_DAYS,) * 5 + (NONE, NONE), {GOOD_FRIDAY: NONE})
    plan_time = union_of([five_days], 8.0)
    assert (plan_time.week, plan_time.exceptions) == (five_days.week, five_days.exceptions)


def test_the_gap_between_earned_and_planned_hours_is_split_by_status_of_the_update():
    """Six tasks of 40 h read on Wednesday 03-11 at 08:00, two days into week 2 (PV of a week 2 task: 16 h).
    Not started: E (week 1, PV 40, EV 0: -40 h, planned finish passed) and F (week 3, nothing). In progress:
    B (week 2, 25 %: EV 10, -6 h, started on its planned day, two hours in) and C (week 2, 75 %: EV 30,
    +14 h, started a day late). Complete: A (week 1, PV 40 = EV 40, planned finish passed, started on its
    planned start) and D (week 3, done early: PV 0, EV 40, +40 h). G, complete without hours, and H, half
    done without planned dates, are not measured. Total: EV 120 - PV 112 = +54 - 46 = +8 h."""
    tasks = {code: planned(code, "2026-03-09 08:00", "2026-03-13 17:00") for code in "BC"}
    tasks |= {code: planned(code, "2026-03-02 08:00", "2026-03-06 17:00") for code in "AE"}
    tasks |= {code: planned(code, "2026-03-16 08:00", "2026-03-20 17:00") for code in "DF"}
    tasks["G"] = planned("G", "2026-03-02 08:00", "2026-03-06 17:00", hours=0)
    tasks["H"] = {**planned("H", "", "", hours=16), "early_start_date": "", "early_end_date": ""}
    baseline = Baseline.from_snapshot(snap(list(tasks.values()), data_date="2026-03-02 08:00"))
    two_hours_in = {"act_start_date": "2026-03-09 10:00"}
    late_start = {"act_start_date": "2026-03-10 08:00"}
    done_early = {"act_start_date": "2026-03-09 08:00", "act_end_date": "2026-03-10 17:00"}
    update = snap(
        [
            progressed(tasks["A"], 100),
            {**progressed(tasks["B"], 25), **two_hours_in},
            {**progressed(tasks["C"], 75), **late_start},
            {**progressed(tasks["D"], 100), **done_early},
            tasks["E"],
            tasks["F"],
            progressed(tasks["G"], 100),
            progressed(tasks["H"], 50),
        ],
        data_date="2026-03-11 08:00",
    )
    gaps = schedule_gap_by_status(update, baseline).set_index("status")
    columns = ["tasks", "bl_labor_hr", "pv_hr", "ev_hr", "ahead_hr", "behind_hr"]
    assert gaps.loc["Not started", columns].tolist() == [2, 80.0, 40.0, 0.0, 0.0, -40.0]
    assert gaps.loc["In progress", columns].tolist() == [2, 80.0, 32.0, 40.0, 14.0, -6.0]
    assert gaps.loc["Complete", columns].tolist() == [2, 80.0, 40.0, 80.0, 40.0, 0.0]
    assert gaps["planned_finish_passed"].to_dict() == {"Not started": 1, "In progress": 0, "Complete": 1}
    assert gaps["started_on_planned_start"].to_dict() == {"Not started": 0, "In progress": 1, "Complete": 1}


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("seed", range(25))
def test_on_random_schedules_the_gaps_by_status_add_up_to_the_earned_schedule_s_hours(seed, shape):
    """Same tasks as the Earned Schedule: the PV, the EV and the BL hours of the statuses sum to its own."""
    update, other = random_update(seed, shape)
    baseline = Baseline.from_snapshot(other) if other is not None else Baseline.planned(update)
    schedule, gaps = earned_schedule(update, baseline), schedule_gap_by_status(update, baseline)
    assert gaps["pv_hr"].sum() == pytest.approx(schedule.pv_hr, abs=1e-6)
    assert gaps["ev_hr"].sum() == pytest.approx(schedule.ev_hr, abs=1e-6)
    assert gaps["bl_labor_hr"].sum() == pytest.approx(schedule.bac_hr, abs=1e-6)
    assert (gaps["ahead_hr"] + gaps["behind_hr"]).sum() == pytest.approx(schedule.ev_hr - schedule.pv_hr, abs=1e-6)


def test_the_planned_dates_of_the_update_are_no_baseline_to_read_an_earned_schedule_on():
    """Baseline "Planned dates in each file": B, not started on Wednesday 03-11, has the planned dates P6 keeps
    equal to its early dates until it starts (Oracle, P6 EPPM User Guide, "Planned Dates"), so they move with
    every scheduling and its late start never shows. No ES: the reason is given."""
    update = snap([progressed(A, 100), B], data_date="2026-03-11 12:00")
    schedule = earned_schedule(update, Baseline.planned(update))
    assert schedule.es_min is None and schedule.spi_t is None
    assert schedule.note == "baseline = the planned dates of the update: a late start does not show in them"


def test_the_date_the_plan_is_reached_and_the_gap_in_calendar_days():
    """A done, B at 50 % on Friday 03-13 17:00: the plan reached these 60 h on Wednesday 03-11 at 12:00 and
    asked for no more until 13:00, the end of the lunch break. As after any stretch without planned
    hours, the gap runs from its end: -2 d 4 h = -52 h / 24 = -2.1667 calendar days."""
    schedule = schedule_of([A, B], {"A": 100, "B": 50}, "2026-03-13 17:00")
    assert schedule.es_date == pd.Timestamp("2026-03-11 13:00")
    assert schedule.gap_calendar_d == pytest.approx(-52 / 24)


def test_the_gap_in_calendar_days_counts_the_weekend_between_the_two_dates():
    """A done, B at 50 % on Monday 03-16 08:00, after a weekend: the date reached is Wednesday 03-11 at
    13:00 (as above), 4 days and 19 hours earlier, Saturday and Sunday included: -115 h / 24."""
    schedule = schedule_of([A, B], {"A": 100, "B": 50}, "2026-03-16 08:00")
    assert schedule.es_date == pd.Timestamp("2026-03-11 13:00")
    assert schedule.gap_calendar_d == pytest.approx(-115 / 24)


def test_where_the_plan_asks_for_no_hours_the_date_reached_is_the_status_date():
    """A in week 1, B in week 3, Wednesday 03-11 12:00, A done: the plan holds 40 h from Friday 03-06 17:00
    to Monday 03-16 08:00 and the status date lies in between: it is the date reached, no gap. A week
    later, Wednesday 03-18 12:00, B not started: the date reached is the end of that stretch, Monday
    03-16 08:00, 2 d 4 h earlier: -52 h / 24."""
    in_the_stretch = schedule_of([A, B_WEEK_3], {"A": 100}, "2026-03-11 12:00")
    assert in_the_stretch.es_date == pd.Timestamp("2026-03-11 12:00") and in_the_stretch.gap_calendar_d == 0.0
    past_it = schedule_of([A, B_WEEK_3], {"A": 100}, "2026-03-18 12:00")
    assert past_it.es_date == pd.Timestamp("2026-03-16 08:00")
    assert past_it.gap_calendar_d == pytest.approx(-52 / 24)


def test_once_every_hour_is_earned_no_gap_in_days_is_read():
    """A and B done, read on Friday 03-20 17:00, a week after the plan's end: the date reached is that end,
    Friday 03-13 17:00, and stays there whatever the status date. The gap of finished work is its finish
    against the plan's, which the status date does not give: none is read."""
    schedule = schedule_of([A, B], {"A": 100, "B": 100}, "2026-03-20 17:00")
    assert schedule.es_date == pd.Timestamp("2026-03-13 17:00")
    assert schedule.gap_calendar_d is None


def test_without_an_earned_schedule_there_is_no_date_reached():
    schedule = schedule_of([A, B], {}, "2026-02-27 08:00")
    assert schedule.es_date is None and schedule.gap_calendar_d is None


def test_the_pace_and_the_hours_needed_to_end_on_the_planned_finish():
    """A done, B at 50 % on Wednesday 03-11 12:00, on plan: 2.5 working days of plan are left (PD 10, ES
    7.5) for 2.5 of time (AT 7.5): TSPI = 1. 20 h are left to earn before Friday 03-13 17:00, 53 h away:
    20 / (53 / 168) = 63.4 h per week. A week late (ES 2.5 on Wednesday 03-11 12:00, A at 50 %): 7.5 days
    of plan in 2.5 of time, TSPI = 3; 60 h left: 190.2 h per week."""
    on_plan = schedule_of([A, B], {"A": 100, "B": 50}, "2026-03-11 12:00")
    assert on_plan.tspi == 1.0
    assert on_plan.hours_per_week_needed == pytest.approx(20 / (53 / 168))
    late = schedule_of([A, B], {"A": 50}, "2026-03-11 12:00")
    assert late.tspi == 3.0
    assert late.hours_per_week_needed == pytest.approx(60 / (53 / 168))


def test_no_pace_is_needed_once_the_planned_finish_is_passed_or_every_hour_earned():
    """Friday 03-20 17:00, a week after the planned finish, B at 50 %: no time is left to the planned
    finish, no pace holds it. A and B done on the planned finish itself, or two days before it: nothing
    is left to earn."""
    past = schedule_of([A, B], {"A": 100, "B": 50}, "2026-03-20 17:00")
    assert past.tspi is None and past.hours_per_week_needed is None
    done = schedule_of([A, B], {"A": 100, "B": 100}, "2026-03-13 17:00")
    assert done.tspi is None and done.hours_per_week_needed is None
    early = schedule_of([A, B], {"A": 100, "B": 100}, "2026-03-11 12:00")
    assert early.tspi is None and early.hours_per_week_needed is None
