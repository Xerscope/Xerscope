"""Week by week earned value, read on the plan in force each week, then summed over four weeks.

The rule is a design decision: the week from an update to the next is measured against the baseline of
the first of the two, so a baseline made again adds no jump to the series. SPI over four weeks = sum of
the weeks' earned hours / sum of their planned hours, the weekly SPI weighted by the planned hours
(Lipke's pace over a window, in time: sum of ES gained / sum of time elapsed). Every value below is
computed by hand in its docstring.

Calendar C8 (Monday to Friday, 8 h a day). Four tasks of 40 h. Plan 1: A week 1 (02-23 to 02-27), B week
2 (03-02), C week 3 (03-09), D week 4 (03-16). Plan 2, made after week 2: A week 1, nothing in week 2, B
week 3, C week 4, D week 5 (03-23 to 03-27). Updates on Fridays at 17:00: U0 02-20 (before the plan), U1
02-27, U2 03-06, U3 03-13, U4 03-20, U5 03-27. U0 to U2 name plan 1, U3 to U5 plan 2.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest
from test_earned_schedule import DAY_MIN, planned, progressed
from xerkit import snap

from xerscope.analysis import Baseline
from xerscope.analysis.evm import (
    baseline_changes,
    copied_lag,
    earned_schedule,
    evm_series,
    gain_ratio,
    gains_since_first,
    moving_window,
    spi_by_window,
    weekly_gains,
    window_weeks,
)
from xerscope.store import SnapshotStore

pytestmark = pytest.mark.oracle("standard")

MONDAYS = [pd.Timestamp("2026-02-23 08:00") + pd.Timedelta(weeks=week) for week in range(5)]
WEEKS = [(f"{monday:%Y-%m-%d %H:%M}", f"{monday + pd.Timedelta(days=4, hours=9):%Y-%m-%d %H:%M}") for monday in MONDAYS]
PLAN_1 = dict(zip("ABCD", WEEKS[:4], strict=True))
PLAN_2 = {"A": WEEKS[0], "B": WEEKS[2], "C": WEEKS[3], "D": WEEKS[4]}
FRIDAYS = [f"{pd.Timestamp('2026-02-20 17:00') + pd.Timedelta(weeks=week):%Y-%m-%d %H:%M}" for week in range(6)]
PROGRESS = [{}, {"A": 50}, {"A": 100, "B": 50}, {"A": 100, "B": 100}, {"A": 100, "B": 100, "C": 50}]
PROGRESS.append({"A": 100, "B": 100, "C": 100, "D": 50})


def tasks_at(dates: dict, percents: dict[str, int]) -> list[dict]:
    """A to D dated as ``dates`` plans them, each task of ``percents`` at its % complete."""
    tasks = {code: planned(code, *dates[code]) for code in "ABCD"}
    return [progressed(task, percents[code]) if code in percents else task for code, task in tasks.items()]


def plan(dates: dict) -> Baseline:
    return Baseline.from_snapshot(snap(tasks_at(dates, {}), data_date=WEEKS[0][0]))


def series(plan_of_update: list[dict]):
    """The six updates, the tasks dated as their own plan dates them, and the baseline each one names."""
    updates, baselines = [], {}
    for friday, percents, dates in zip(FRIDAYS, PROGRESS, plan_of_update, strict=True):
        update = snap(tasks_at(dates, percents), data_date=friday)
        updates.append(update)
        baselines[id(update)] = plan(dates)
    return SnapshotStore(updates), lambda update: baselines[id(update)]


def two_plans():
    return series([PLAN_1] * 3 + [PLAN_2] * 3)


def test_each_week_is_read_on_the_baseline_of_the_update_that_opens_it():
    """Earned / planned hours of the weeks. W1 on plan 1: 20 / 40. W2 on plan 1: 60 - 20 = 40 / 40. W3 on
    plan 1, the plan U2 names (U3 reads 80 h earned, A, B and C planned: 120): 20 / 40. W4 on plan 2 (U3:
    80 earned, 80 planned; U4: 100 earned, A, B and C planned: 120): 20 / 40. W5 on plan 2: 40 / 40."""
    store, baseline_for = two_plans()
    gains = weekly_gains(store, baseline_for)
    assert gains["data_date"].tolist() == [pd.Timestamp(friday) for friday in FRIDAYS[1:]]
    assert gains["ev_gain_hr"].tolist() == [20.0, 40.0, 20.0, 20.0, 40.0]
    assert gains["pv_gain_hr"].tolist() == [40.0, 40.0, 40.0, 40.0, 40.0]


def test_the_time_gained_on_the_plan_each_week():
    """ES in working days. W1: U0 is before the plan, no ES: no gain read. W2 on plan 1: 2.5 (20 h, Wednesday
    of week 1 at noon) to 7.5: 5 gained in 5 elapsed. W3 on plan 1: 7.5 to 10 (80 h, the end of week 2):
    2.5 in 5. W4 on plan 2: 15 (80 h, the end of week 3) to 17.5: 2.5 in 5. W5 on plan 2: 17.5 to 22.5: 5 in 5."""
    store, baseline_for = two_plans()
    gains = weekly_gains(store, baseline_for)
    assert pd.isna(gains.loc[0, "es_gain_min"])
    assert (gains["es_gain_min"].iloc[1:] / DAY_MIN).tolist() == [5.0, 2.5, 2.5, 5.0]
    assert (gains["at_gain_min"].iloc[1:] / DAY_MIN).tolist() == [5.0, 5.0, 5.0, 5.0]


def test_the_four_weeks_window_starts_at_the_last_update_at_least_28_days_before():
    """At U5 (03-27) the window starts at U1 (02-27, 28 days before): W2 to W5. Earned 40 + 20 + 20 + 40 =
    120 h for 160 planned: SPI 0.75, the weekly 1, 0.5, 0.5, 1 weighted by 40 h each. Time: 15 working
    days gained in 20: pace 0.75. One week of the four, W3, closes on another plan than it is read on. At
    U4 the window starts at U0: 100 / 160 = 0.625, and no pace in time, W1 having none. At U3, 21 days
    after U0, there is no window."""
    store, baseline_for = two_plans()
    gains = weekly_gains(store, baseline_for)
    at_u5 = moving_window(gains, pd.Timestamp(FRIDAYS[5]))
    assert (at_u5["ev_gain_hr"], at_u5["pv_gain_hr"]) == (120.0, 160.0)
    assert at_u5["es_gain_min"] / at_u5["at_gain_min"] == 0.75
    assert (at_u5["window_start"], at_u5["weeks"], at_u5["baseline_changes"]) == (pd.Timestamp(FRIDAYS[1]), 4, 1)
    at_u4 = moving_window(gains, pd.Timestamp(FRIDAYS[4]))
    assert at_u4["ev_gain_hr"] / at_u4["pv_gain_hr"] == 0.625 and pd.isna(at_u4["es_gain_min"])
    assert moving_window(gains, pd.Timestamp(FRIDAYS[3])) is None


def test_a_window_is_weighted_by_the_planned_hours_not_the_mean_of_the_weekly_spi():
    """Weeks planned 500, 500, 500, 20 h and earned 400, 400, 400, 60 h: the weekly SPI are 0.8, 0.8, 0.8
    and 3.0, mean 1.35; the window reads 1 260 / 1 520 = 0.829."""
    dates = pd.date_range("2026-03-06", periods=5, freq="7D")
    gains = pd.DataFrame(
        {
            "data_date": dates[1:],
            "week_start": dates[:-1],
            "ev_gain_hr": [400.0, 400.0, 400.0, 60.0],
            "pv_gain_hr": [500.0, 500.0, 500.0, 20.0],
            "es_gain_min": [1.0] * 4,
            "at_gain_min": [1.0] * 4,
            "baseline_changed": [False] * 4,
        }
    )
    window = moving_window(gains, dates[-1])
    assert window["ev_gain_hr"] / window["pv_gain_hr"] == pytest.approx(1260 / 1520)


def test_without_a_change_of_baseline_the_weeks_are_the_differences_of_the_series():
    """Every update on plan 1: the gains are the differences of ``evm_series`` from one update to the next."""
    store, baseline_for = series([PLAN_1] * 6)
    gains = weekly_gains(store, baseline_for)
    whole = evm_series(store, plan(PLAN_1))
    assert gains["ev_gain_hr"].tolist() == whole["ev_hr"].diff().iloc[1:].tolist()
    assert gains["pv_gain_hr"].tolist() == whole["pv_hr"].diff().iloc[1:].tolist()


def test_the_finish_forecast_spreads_what_is_left_of_the_plan_at_a_pace():
    """U5 on plan 2: 25 working days planned, 22.5 reached, 2.5 left. At a pace of 0.75 they take 3.333
    days from Friday 03-27 17:00: Monday, Tuesday, Wednesday, then 2 h 40 on Thursday 04-02: 10:40. At a
    pace of 1 they take 2.5 days: Wednesday 04-01 at 12:00. No pace, or none above zero: no date; nor
    at a pace so low that no calendar holds the date."""
    store, baseline_for = two_plans()
    schedule = earned_schedule(store[5], baseline_for(store[5]))
    assert schedule.finish_at(0.75) == pd.Timestamp("2026-04-02 10:40")
    assert schedule.finish_at(1.0) == pd.Timestamp("2026-04-01 12:00")
    assert schedule.finish_at(0.0) is None and schedule.finish_at(None) is None
    assert schedule.finish_at(float("nan")) is None and schedule.finish_at(1e-9) is None


def test_once_every_hour_is_earned_there_is_no_finish_to_forecast():
    done = snap(tasks_at(PLAN_1, dict.fromkeys("ABCD", 100)), data_date=FRIDAYS[5])
    assert earned_schedule(done, plan(PLAN_1)).finish_at(0.5) is None


def test_the_ratios_of_a_window_and_of_every_week_since_the_first_update():
    """At U5: SPI of the four weeks 120 / 160 = 0.75. Since the first update: earned 20 + 40 + 20 + 20 + 40
    = 140 h, but W1 has no ES and is left out of all four sums: 120 / 160 and 15 days in 20, pace 0.75.
    At U4: W2 to W4, 80 / 120 = 0.667 and 10 days in 15. Nothing asked, a sum missing, no window: none."""
    store, baseline_for = two_plans()
    gains = weekly_gains(store, baseline_for)
    window = moving_window(gains, pd.Timestamp(FRIDAYS[5]))
    assert gain_ratio(window, "ev_gain_hr", "pv_gain_hr") == 0.75
    assert gain_ratio(gains_since_first(gains, pd.Timestamp(FRIDAYS[5])), "es_gain_min", "at_gain_min") == 0.75
    at_u4 = gains_since_first(gains, pd.Timestamp(FRIDAYS[4]))
    assert gain_ratio(at_u4, "ev_gain_hr", "pv_gain_hr") == pytest.approx(80 / 120)
    assert gain_ratio(at_u4, "es_gain_min", "at_gain_min") == pytest.approx(10 / 15)
    assert gain_ratio(None, "ev_gain_hr", "pv_gain_hr") is None
    assert gain_ratio(pd.Series({"ev_gain_hr": 5.0, "pv_gain_hr": 0.0}), "ev_gain_hr", "pv_gain_hr") is None
    assert gain_ratio(moving_window(gains, pd.Timestamp(FRIDAYS[4])), "es_gain_min", "at_gain_min") is None


def test_the_spi_over_four_weeks_of_each_update():
    """U1 to U3 have no update 28 days before them: none. U4: 100 / 160 = 0.625. U5: 120 / 160 = 0.75."""
    store, baseline_for = two_plans()
    moving = spi_by_window(weekly_gains(store, baseline_for))
    assert moving["data_date"].tolist() == [pd.Timestamp(friday) for friday in FRIDAYS[1:]]
    assert moving["spi_4w"].isna().tolist() == [True, True, True, False, False]
    assert moving["spi_4w"].iloc[3:].tolist() == [0.625, 0.75]


def test_the_weeks_of_the_window_are_listed_one_by_one():
    """At U5 the window holds W2 to W5 (the test above): earned 40, 20, 20, 40 h, 5, 2.5, 2.5 and 5 plan
    days gained in 5 elapsed each, W3 closing on plan 2 while read on plan 1. At U3 there is no window."""
    store, baseline_for = two_plans()
    gains = weekly_gains(store, baseline_for)
    weeks = window_weeks(gains, pd.Timestamp(FRIDAYS[5]), hours_per_day=8)
    assert weeks["week_start"].tolist() == [pd.Timestamp(friday) for friday in FRIDAYS[1:5]]
    assert weeks["ev_gain_hr"].tolist() == [40.0, 20.0, 20.0, 40.0]
    assert weeks["es_gain_plan_d"].tolist() == [5.0, 2.5, 2.5, 5.0]
    assert weeks["at_gain_plan_d"].tolist() == [5.0] * 4
    assert weeks["baseline_changed"].tolist() == [False, True, False, False]
    assert weeks["baseline"].tolist() == [baseline_for(store[index]).label for index in range(1, 5)]
    assert window_weeks(gains, pd.Timestamp(FRIDAYS[3]), hours_per_day=8).empty


def test_a_baseline_copied_from_a_project_under_way_keeps_the_lag_of_its_started_tasks():
    """A copy of the project at U3 (03-13): A done in week 1, B started in week 2 and 50 % done, its
    planned dates frozen at week 2 (P6, Planned Dates), C and D in weeks 4 and 5. Against that copy at
    U3: B's planned finish (03-06) is passed, 20 h behind; the ES is Wednesday 03-04 13:00, 9.17 calendar
    days behind. One week later B is done: 10 plan days gained in 5, pace 2.0: the lag the copy made is
    read as a catch-up. C, not started at the copy, is not counted a week later though half done on its
    planned finish day. Against plan 1, made before anything started, B late is plainly late: nothing."""
    frozen = {"A": WEEKS[0], "B": WEEKS[1], "C": WEEKS[3], "D": WEEKS[4]}
    copy = Baseline.from_snapshot(snap(tasks_at(frozen, {"A": 100, "B": 50}), data_date=FRIDAYS[3]))
    at_copy = snap(tasks_at(frozen, {"A": 100, "B": 50}), data_date=FRIDAYS[3])
    week_after = snap(tasks_at(frozen, {"A": 100, "B": 100, "C": 50}), data_date=FRIDAYS[4])
    assert copied_lag(at_copy, copy) == (1, 20.0)
    schedule = earned_schedule(at_copy, copy)
    assert schedule.es_date == pd.Timestamp("2026-03-04 13:00")
    assert schedule.gap_calendar_d == pytest.approx(-9.1667, abs=1e-3)
    gains = weekly_gains(SnapshotStore([at_copy, week_after]), lambda update: copy)
    assert gains["es_gain_min"].tolist() == [10 * DAY_MIN] and gains["at_gain_min"].tolist() == [5 * DAY_MIN]
    assert copied_lag(week_after, copy) == (0, 0.0)
    assert copied_lag(at_copy, plan(PLAN_1)) == (0, 0.0)


def test_a_change_of_baseline_counts_the_tasks_it_adds_and_the_tasks_it_drops():
    """The update holds A to E, 40 h each. The old plan holds A, B, C, D (BAC 160 h) and not E. The new plan
    holds A, B, E (BAC 120 h): it drops C and D (removed 2) and takes in E, which the old plan did not
    hold (added 1). Per baseline_changes: added = tasks of the update the old plan did not hold and the
    new one does; removed = tasks of the old plan the new one drops."""
    on_plan = {"A": WEEKS[0], "B": WEEKS[1], "C": WEEKS[2], "D": WEEKS[3], "E": WEEKS[4]}
    old_plan = Baseline.from_snapshot(snap([planned(code, *on_plan[code]) for code in "ABCD"], data_date=WEEKS[0][0]))
    new_plan = Baseline.from_snapshot(snap([planned(code, *on_plan[code]) for code in "ABE"], data_date=WEEKS[0][0]))
    first = snap([planned(code, *on_plan[code]) for code in "ABCDE"], data_date=FRIDAYS[0])
    second = snap([planned(code, *on_plan[code]) for code in "ABCDE"], data_date=FRIDAYS[1])
    plan_of = {id(first): old_plan, id(second): new_plan}
    changes = baseline_changes(SnapshotStore([first, second]), lambda update: plan_of[id(update)])
    row = changes.iloc[0]
    assert changes["data_date"].tolist() == [pd.Timestamp(FRIDAYS[1])]
    assert (row["bac_old_hr"], row["bac_new_hr"]) == (160.0, 120.0)
    assert (row["added"], row["removed"]) == (1, 2)


def test_the_weeks_and_the_change_of_baseline_name_the_source_of_a_baseline_when_it_has_one():
    """A baseline the app chose carries its ``source`` ("probable ...", a fallback), shown instead of its
    label (weekly_gains, baseline_changes). Plan 1 is given the source "S1", plan 2 "S2"; U0 to U2 name
    plan 1 and U3 to U5 plan 2, so the weeks opened by U0 to U4 read S1, S1, S1, S2, S2. A baseline
    without a source is named by its label."""
    store, baseline_for = two_plans()

    def with_source(update):
        source = "S1" if update.data_date <= pd.Timestamp(FRIDAYS[2]) else "S2"
        return replace(baseline_for(update), source=source)

    assert weekly_gains(store, with_source)["baseline"].tolist() == ["S1", "S1", "S1", "S2", "S2"]
    row = baseline_changes(store, with_source).iloc[0]
    assert (row["baseline_old"], row["baseline_new"]) == ("S1", "S2")
    no_source = weekly_gains(store, baseline_for)["baseline"].tolist()
    assert no_source == [plan(PLAN_1).label] * 3 + [plan(PLAN_2).label] * 2


def test_what_a_change_of_baseline_absorbs_is_read_at_the_update_that_changes_it():
    """U3 (03-13 17:00, A and B done, 80 h) is the first update on plan 2. On plan 1 the PV at U3 is A, B
    and C, 120 h: the 80 h earned were planned by the end of week 2, and the PV holds 80 h over the weekend
    until Monday 03-09 08:00, the instant reached (the plan asks for nothing in between): 4 days 9 hours
    behind, 4.375. On plan 2 (B in week 3) the PV is 80 h: the plan is reached on the status date, gap 0.
    The change absorbs 4.375 days; both plans hold the same 160 h and the same four tasks. U1, U2, U4 and U5 keep their
    predecessor's plan: no row. A series on one plan has none."""
    store, baseline_for = two_plans()
    changes = baseline_changes(store, baseline_for)
    assert changes["data_date"].tolist() == [pd.Timestamp(FRIDAYS[3])]
    row = changes.iloc[0]
    assert (row["gap_old_d"], row["gap_new_d"], row["absorbed_d"]) == (-4.375, 0.0, 4.375)
    assert (row["bac_old_hr"], row["bac_new_hr"], row["added"], row["removed"]) == (160.0, 160.0, 0, 0)
    assert (row["baseline_old"], row["baseline_new"]) == (plan(PLAN_1).label, plan(PLAN_2).label)
    one_plan, baseline_for = series([PLAN_1] * 6)
    assert baseline_changes(one_plan, baseline_for).empty
