"""Which calendar measures a shift in working days (docs/formulas.md, 1.5).

Every case builds the same schedule twice, C8 (Mon-Fri 8 h) and C10 (Mon-Fri 10 h), and
puts the project and the activities on different ones, so the calendar a consumer picks
shows in the number. The interval Mon 2026-03-02 08:00 -> Tue 2026-03-03 12:00 is
12 working hours on C8 (1.5 d) and 14 on C10 (1.4 d).
"""

import pandas as pd
import pytest
from rulekit import STANDARDS, codes, run
from xerkit import FM, MON_FRI_10H, active, clndr_data, hours, snap, todo

from xerscope.analysis import AnalysisContext, Baseline, run_metric
from xerscope.analysis.changelog import changelog
from xerscope.analysis.progress import (
    activity_finish_shift,
    finish_shift_since_first,
    milestone_slips,
    milestone_trend,
)
from xerscope.analysis.wbs import ROOT, rollup
from xerscope.store import SnapshotStore
from xerscope.viz import categorise, gantt_rows

FIRST, LAST = "2026-03-02 08:00", "2026-03-03 12:00"
WD = {"C8": 1.5, "C10": 1.4}
OTHER = {"C8": "C10", "C10": "C8"}
# (calendar of the project, calendar of the activities): each calendar on each side
PAIRS = pytest.mark.parametrize("project, activity", [("C8", "C10"), ("C10", "C8")])
ACTIVITY_CALENDAR = pytest.mark.parametrize("project, activity", [("C8", "C8"), ("C8", "C10"), ("C10", "C8")])

P6 = STANDARDS["P6"]
DCMA = STANDARDS["DCMA"]
DECM = STANDARDS["DECM"]


def two_updates(project: str, activity: str, **task):
    """Two updates, data dates FIRST and LAST; Z's forecast finish moves from FIRST to LAST."""

    def update(finish: str, data_date: str):
        z = todo("Z", clndr_id=activity, early_start_date=FIRST, early_end_date=finish, **task)
        return snap([z], data_date=data_date, project={"clndr_id": project})

    return update(FIRST, FIRST), update(LAST, LAST)


# --- project dates: the project calendar -----------------------------------------------------


@PAIRS
def test_store_finish_shift_is_on_the_project_calendar(project, activity):
    store = SnapshotStore(two_updates(project, activity))
    assert store.summary["finish_shift_wd"].iloc[1] == pytest.approx(round(WD[project], 1))


@PAIRS
def test_finish_shift_since_first_is_on_the_project_calendar(project, activity):
    assert finish_shift_since_first(SnapshotStore(two_updates(project, activity))) == pytest.approx(WD[project])


@PAIRS
def test_changelog_project_rows_are_on_the_project_calendar(project, activity):
    log = changelog(*two_updates(project, activity)).query("category == 'Project'").set_index("field")
    assert log.loc["status date", "delta"] == pytest.approx(WD[project])
    assert log.loc["forecast finish", "delta"] == pytest.approx(WD[project])


@PAIRS
def test_wbs_finish_variance_is_on_the_project_calendar(project, activity):
    old, new = two_updates(project, activity)
    nodes = rollup(new, Baseline.from_snapshot(old)).set_index("wbs_id")
    assert nodes.loc[ROOT, "finish_variance_wd"] == pytest.approx(-round(WD[project], 1))  # later: negative


@PAIRS
def test_dcma_13_length_and_float_are_on_the_project_calendar(project, activity):
    # CPL = FIRST -> LAST; total float -8 h is one day on C8, 0.8 day on C10
    task = todo("Z", clndr_id=activity, early_start_date=FIRST, early_end_date=LAST, total_float_hr_cnt="-8")
    s = snap([task], data_date=FIRST, project={"clndr_id": project, "plan_end_date": LAST})
    r = run(DCMA, "DCMA-13", s)
    length, total_float = WD[project], -8 / {"C8": 8, "C10": 10}[project]
    assert r.note.startswith(f"CPL {length:g} wd")
    assert r.value == pytest.approx((length + total_float) / length)


# --- activity dates: the activity's calendar -------------------------------------------------


@PAIRS
def test_changelog_date_moves_are_on_the_activity_calendar(project, activity):
    log = changelog(*two_updates(project, activity)).query("category == 'Dates'")
    assert list(log["change"]) == ["finish moved"]
    assert log["delta"].iloc[0] == pytest.approx(WD[activity], abs=0.005)


@PAIRS
def test_gantt_finish_shift_is_on_the_activity_calendar(project, activity):
    old, new = two_updates(project, activity)
    tasks = new.activities.assign(category=categorise(new.activities))
    rows = gantt_rows(tasks, rollup(new), compare=old.activities, snapshot=new)
    shift = next(r for r in rows if r["id"] == "a:Z")["shift_wd"]
    assert shift == pytest.approx(-round(WD[activity], 1))  # later than the comparison: negative


@PAIRS
def test_milestone_slip_is_on_the_milestone_calendar(project, activity):
    updates = [
        snap(
            [todo("M", clndr_id=activity, early_start_date=finish, early_end_date=finish, **FM)],
            data_date=finish,
            project={"clndr_id": project},
        )
        for finish in (FIRST, LAST)
    ]
    store = SnapshotStore(updates)
    slip = milestone_slips(milestone_trend(store), store).set_index("task_code").loc["M"]
    assert slip["slip_wd"] == pytest.approx(-round(WD[activity], 1))  # later than first forecast: negative
    assert slip["last_week_wd"] == pytest.approx(-round(WD[activity], 1))


@PAIRS
def test_activity_page_slip_is_on_the_activity_calendar(project, activity):
    store = SnapshotStore(two_updates(project, activity))
    history = store.history.query("task_code == 'Z'").sort_values("data_date")
    assert activity_finish_shift(store, history) == pytest.approx(WD[activity])


def test_activity_page_slip_needs_two_forecast_finishes():
    store = SnapshotStore(two_updates("C8", "C8"))
    history = store.history.query("task_code == 'Z'").sort_values("data_date")
    assert activity_finish_shift(store, history.iloc[:1]) is None
    assert activity_finish_shift(store, history.assign(finish=[pd.NaT, history["finish"].iloc[1]])) is None


# --- hours-per-day rules: the activity's calendar --------------------------------------------


@ACTIVITY_CALENDAR
def test_p6_12_variance_is_on_the_activity_calendar(project, activity):
    task = dict(clndr_id=activity, early_start_date=FIRST)
    baseline = Baseline.from_snapshot(snap([todo("Z", early_end_date=FIRST, **task)], project={"clndr_id": project}))
    now = snap([todo("Z", early_end_date=LAST, **task)], project={"clndr_id": project})
    r = run(P6, "P6-12", now, baseline)
    assert codes(r) == ["Z"]
    assert r.flagged.iloc[0]["finish_variance_wd"] == pytest.approx(-WD[activity], abs=0.005)  # late: negative


@pytest.mark.parametrize("project", ["C8", "C10"])
def test_dcma_08_limit_is_in_days_of_the_activity_calendar(project):
    # 400 h baseline: 50 d on C8 (over 44), 40 d on C10
    tasks = [todo(code, clndr_id=calendar, **hours(400)) for code, calendar in (("A8", "C8"), ("A10", "C10"))]
    baseline = Baseline.from_snapshot(snap(tasks, project={"clndr_id": project}))
    r = run(DCMA, "DCMA-08", snap(tasks, project={"clndr_id": project}), baseline)
    assert codes(r) == ["A8"]


@pytest.mark.parametrize("project", ["C8", "C10"])
def test_06a506c_windows_are_in_days_of_the_activity_calendar(project):
    """Not started: a start 3 wd after the data date rides (Thu 08:00 = 24 h on C8, 30 h on C10),
    a start four hours later does not. Started: a remaining duration that moved by 2 wd or less
    rides (80 h -> 60 h is 2.5 d on C8, 2.0 d on C10)."""

    def week(data_date: str, near: str, far: str, remaining: str):
        tasks = [
            todo(f"{kind}{calendar}", clndr_id=calendar, early_start_date=start, **hours(8))
            for kind, start in (("near", near), ("far", far))
            for calendar in ("C8", "C10")
        ]
        tasks += [active(f"S{calendar}", clndr_id=calendar, remain_drtn_hr_cnt=remaining) for calendar in ("C8", "C10")]
        return snap(tasks, data_date=data_date, project={"clndr_id": project})

    old = week("2026-03-02 08:00", "2026-03-05 08:00", "2026-03-05 12:00", "80")
    new = week("2026-03-30 08:00", "2026-04-02 08:00", "2026-04-02 12:00", "60")
    store = SnapshotStore([old, new])
    r = run_metric(DECM["06A506c"], AnalysisContext(store[1], store))
    assert codes(r) == ["SC10", "nearC10", "nearC8"]


# --- whole working days on calendars whose hours per day are not binary fractions -----------


def calendar(clndr_id: str, hours_per_day: str, afternoon_end: str) -> dict:
    """Mon-Fri, 08:00-12:00 and 13:00-``afternoon_end``, declared at ``hours_per_day``."""
    periods = [("08:00", "12:00"), ("13:00", afternoon_end)]
    week = str(round(5 * float(hours_per_day), 1))
    data = clndr_data(range(2, 7), periods)
    return {
        "clndr_id": clndr_id,
        "clndr_name": clndr_id,
        "day_hr_cnt": hours_per_day,
        "week_hr_cnt": week,
        "clndr_data": data,
    }


H82 = calendar("82", "8.2", "17:12")  # 41 h week
H76 = calendar("76", "7.6", "16:36")  # 38 h week
H74 = calendar("74", "7.4", "16:24")  # 37 h week


def test_44_working_days_is_not_greater_than_44_on_an_8_2_hour_calendar():
    """DCMA-EA PAM 200.1 4.6 / 4.8 count float or baseline duration *greater than* 44 working days,
    DECM 06A211a high float the same. P6 stores 44 days of an 8.2 h calendar as 360.8 h, and
    360.8 / 8.2 is 44.00000000000001 in binary floating point: A must not be counted, B (361 h,
    44.02 d) must."""
    tasks = [
        todo("A", clndr_id="82", total_float_hr_cnt="360.8", **hours(0) | {"target_drtn_hr_cnt": "360.8"}),
        todo("B", clndr_id="82", total_float_hr_cnt="361", **hours(0) | {"target_drtn_hr_cnt": "361"}),
    ]
    s = snap(tasks, calendars=[H82])
    assert s.by_code.at["A", "total_float_d"] == 44
    assert codes(run(DCMA, "DCMA-06", s)) == ["B"]
    assert codes(run(DECM, "06A211a", s)) == ["B"]
    assert codes(run(DCMA, "DCMA-08", s, Baseline.planned(s))) == ["B"]


def test_06a506c_boundaries_hold_on_any_calendar():
    """06A506c counts a start *within* 3 wd of the status date and a remaining duration that moved
    by 2 wd or less (test above). On a 7.6 h calendar a start 3 wd after the data date is 22.8 h,
    and 3 * 7.6 = 22.799999999999997; on a 7.4 h calendar 148 h -> 133.2 h is 2 wd, computed
    2.0000000000000036. Both sit exactly on the boundary and both ride."""

    def update(data_date: str, start: str, remaining: str):
        tasks = [
            todo("near", clndr_id="76", early_start_date=start, **hours(8)),
            active("S", clndr_id="74", remain_drtn_hr_cnt=remaining),
        ]
        return snap(tasks, data_date=data_date, calendars=[H76, H74])

    old = update("2026-03-02 08:00", "2026-03-05 08:00", "148")
    new = update("2026-03-30 08:00", "2026-04-02 08:00", "133.2")
    store = SnapshotStore([old, new])
    r = run_metric(DECM["06A506c"], AnalysisContext(store[1], store))
    assert codes(r) == ["S", "near"]


# --- changelog durations: hours, not days of a changing calendar -----------------------------


@pytest.mark.parametrize("before, after", [("C8", "C10"), ("C10", "C8")])
def test_changelog_ignores_a_calendar_change_at_constant_hours(before, after):
    """P6 stores a duration in hours and only displays it in days of the activity's calendar
    (Oracle P6 EPPM 23 Application Administration Guide, "Using Calendars to Define Hours Per Time
    Period Settings"): 80 h is 10 d on C8 and 8 d on C10, the same duration. Only the calendar change is listed."""

    def update(calendar: str, data_date: str):
        return snap([todo("A", clndr_id=calendar, **hours(80))], data_date=data_date)

    log = changelog(update(before, FIRST), update(after, LAST)).query("category != 'Project'")
    assert list(log["change"]) == ["calendar changed"]


def test_changelog_lists_an_hours_change_hidden_by_a_calendar_change():
    # 80 h on C8 is 10 d, 100 h on C10 is 10 d: the days are equal, the duration grew by 20 h
    old = snap([todo("A", clndr_id="C8", **hours(80))], data_date=FIRST)
    new = snap([todo("A", clndr_id="C10", **hours(100))], data_date=LAST)
    log = changelog(old, new).query("category == 'Durations'")
    assert sorted(log["change"]) == ["original duration changed", "remaining duration increased"]


def test_weekly_finish_shifts_add_up_to_the_total_shift():
    """Four updates, the finish moving 2 h a week on C8: 0.25 wd each, 1.0 wd in all. Stored
    rounded to 0.1 (half to even: 0.2) they summed to 0.8 wd, in Power BI as on the page."""
    finishes = ["2026-03-13 17:00", "2026-03-16 10:00", "2026-03-16 12:00", "2026-03-16 15:00", "2026-03-16 17:00"]
    data_dates = ["2026-03-02 08:00", "2026-03-09 08:00", "2026-03-10 08:00", "2026-03-11 08:00", "2026-03-12 08:00"]
    updates = [
        snap([todo("A", early_end_date=finish)], data_date=data_date)
        for finish, data_date in zip(finishes, data_dates, strict=True)
    ]
    shifts = SnapshotStore(updates).summary["finish_shift_wd"]
    assert shifts.iloc[1:].tolist() == [0.25, 0.25, 0.25, 0.25]
    assert shifts.sum() == 1.0


# --- a missing date: the shift is missing, not zero ------------------------------------------

NO_DATES = dict(early_start_date="", early_end_date="", target_start_date="", target_end_date="")


def test_working_days_to_a_missing_date_is_nan():
    """The scalar version agrees with the row-wise one (NaN where a date is missing): 0 would
    read as "did not move"."""
    s = snap([todo("A")], data_date=FIRST)
    assert pd.isna(s.calendar().working_days(pd.NaT, pd.Timestamp(LAST)))
    assert pd.isna(s.project_working_days(s.data_date, None))
    assert pd.isna(s.activity_working_days("C10", None, pd.Timestamp(LAST)))
    assert s.calendar().working_days(pd.Timestamp(FIRST), pd.Timestamp(LAST)) == pytest.approx(WD["C8"])


def test_changelog_status_date_shift_is_blank_when_the_new_update_has_none():
    old = snap([todo("A")], data_date=FIRST)
    new = snap([todo("A")], data_date="", project={"plan_start_date": ""})
    assert new.data_date is None
    row = changelog(old, new).query("category == 'Project'").set_index("field").loc["status date"]
    assert pd.isna(row["delta"])


def test_milestone_slip_is_blank_when_the_latest_forecast_is_missing():
    """M forecast Fri 10 April, then no date at all in the latest update: no slip is known,
    and the earlier date is not carried over as the latest forecast."""
    updates = [
        snap([todo("M", early_end_date="2026-04-10 17:00", **FM)], data_date=FIRST),
        snap([todo("M", **FM, **NO_DATES)], data_date=LAST),
    ]
    store = SnapshotStore(updates)
    slip = milestone_slips(milestone_trend(store), store).set_index("task_code").loc["M"]
    assert pd.isna(slip["latest_forecast"])
    assert pd.isna(slip["slip_wd"]) and pd.isna(slip["last_week_wd"])


# --- changelog float: hours, not days of a changing calendar ----------------------------------


@pytest.mark.parametrize("before, after", [("C8", "C10"), ("C10", "C8")])
def test_changelog_float_ignores_a_calendar_change_at_constant_hours(before, after):
    """80 h of total float is 10 d on C8 and 8 d on C10: the same float, as P6 stores it in hours."""

    def update(calendar: str, data_date: str):
        return snap([todo("A", clndr_id=calendar, total_float_hr_cnt="80")], data_date=data_date)

    log = changelog(update(before, FIRST), update(after, LAST)).query("category != 'Project'")
    assert list(log["change"]) == ["calendar changed"]


def test_changelog_float_change_hidden_by_a_calendar_change_is_listed_in_new_days():
    """80 h on C8 (10 d) -> 100 h on C10 (10 d): +20 h, 2 d of the new 10 h calendar."""
    old = snap([todo("A", clndr_id="C8", total_float_hr_cnt="80")], data_date=FIRST)
    new = snap([todo("A", clndr_id="C10", total_float_hr_cnt="100")], data_date=LAST)
    row = changelog(old, new).query("change == 'total float changed'").iloc[0]
    assert row["delta"] == pytest.approx(2.0)


def test_activity_page_slip_of_a_deleted_activity_is_on_its_own_calendar():
    """Z is on calendar 12 (Mon-Fri 10 h), which only the two updates holding Z define; the
    latest update has neither. Its slip is measured on calendar 12 (1.4 wd), not on the latest
    update's project calendar C8 (1.5 wd)."""
    ten_hours = {"clndr_id": "12", "clndr_name": "Mon-Fri 10h bis", "day_hr_cnt": "10", "week_hr_cnt": "50"}
    ten_hours["clndr_data"] = MON_FRI_10H

    def update(finish: str, data_date: str):
        z = todo("Z", clndr_id="12", early_start_date=FIRST, early_end_date=finish)
        return snap([z], data_date=data_date, calendars=[ten_hours])

    gone = snap([todo("Y")], data_date="2026-03-09 08:00")
    store = SnapshotStore([update(FIRST, FIRST), update(LAST, LAST), gone])
    history = store.history.query("task_code == 'Z'").sort_values("data_date")
    assert activity_finish_shift(store, history) == pytest.approx(WD["C10"])
