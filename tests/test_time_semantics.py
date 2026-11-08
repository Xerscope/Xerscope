"""Time as xerscope reads it: date grain against the data date, working time on calendars, the data
date itself, weekly pairing, milestone slips, earned value elapsed time, P6 export text and XER dates.

Every schedule is built with xerkit on calendar C8 (Mon-Fri 08:00-12:00, 13:00-17:00, holiday Fri
2026-04-03) unless a test says otherwise. Monday 2026-03-02 is the data date's day throughout.
"""

import codecs
from dataclasses import replace

import pandas as pd
import pytest
from rulekit import STANDARDS, codes, run
from xerkit import FM, active, clndr_data, done, hours, snap, todo

from xerscope.analysis import Baseline
from xerscope.analysis.evm import schedule_pct
from xerscope.analysis.progress import committed, milestone_slips, milestone_trend, ppc_series
from xerscope.app.diagnostic import p6_export_columns, p6_export_frame, read_p6_export
from xerscope.store import SnapshotStore
from xerscope.xer.model import to_datetime

P6, DCMA, DECM, INTEGRITY = (STANDARDS[name] for name in ("P6", "DCMA", "DECM", "INTEGRITY"))
T = pd.Timestamp
DAY = "2026-03-02"
DD_HOURS = ["00:00", "08:00", "17:00"]  # midnight, start of the working day, end of it
SAME_DAY = f"{DAY} 12:00"  # an activity date on the data date's day, inside working time

# Extra calendars: 4 x 10 h (Mon-Thu 07:00-12:00, 12:30-17:30) and 24 h, 7 days.
FOUR_TENS = {
    "clndr_id": "40",
    "clndr_name": "4x10",
    "day_hr_cnt": "10",
    "week_hr_cnt": "40",
    "clndr_data": clndr_data(range(2, 6), [("07:00", "12:00"), ("12:30", "17:30")]),
}
ROUND_THE_CLOCK = {
    "clndr_id": "24",
    "clndr_name": "24h",
    "day_hr_cnt": "24",
    "week_hr_cnt": "168",
    "clndr_data": clndr_data(range(1, 8), [("00:00", "00:00")]),
}


def at(hour: str) -> str:
    return f"{DAY} {hour}"


# --- 1. date grain against the data date -----------------------------------------------------------
# P6 rule (101248; P6 Pro 26 help, Check Schedule, l.30734-30741): "Invalid dates for in progress
# activities are ... actual start dates later than the data date", read on the stored timestamp, the
# p6.toml default. Help l.15836 only says the data date opens the work period. DCMA-EA PAM 200.1
# reasons in dates (§4.9, §4.11): dcma.toml sets date_grain = "day". DECM's status date maps to
# "before P6's data date" (decm.toml header). An activity date at 12:00 on the data date's day is after
# a data date at 00:00 or 08:00 and before one at 17:00. The 17:00 case is not verified against a P6
# report.

ACTUAL_AFTER = {"00:00": True, "08:00": True, "17:00": False}  # 12:00 > data date, by timestamp


@pytest.mark.parametrize("dd", DD_HOURS)
@pytest.mark.parametrize(
    ("std", "metric_id"),
    [(P6, "P6-10b"), (INTEGRITY, "INT-06"), (DECM, "06A506a")],
    ids=["P6-10b 101248", "INT-06 log 99350", "DECM 06A506a"],
)
def test_actual_start_same_day_is_compared_by_timestamp(std, metric_id, dd):
    """Timestamp grain (101248 / 99350 / decm.toml): an actual start at 12:00 is after a data date at
    00:00 and 08:00, not after one at 17:00."""
    s = snap([active("A", act_start_date=SAME_DAY, early_start_date=at("17:00"))], data_date=at(dd))
    assert codes(run(std, metric_id, s)) == (["A"] if ACTUAL_AFTER[dd] else [])


@pytest.mark.parametrize("dd", DD_HOURS)
@pytest.mark.parametrize(
    ("std", "metric_id"),
    [(P6, "P6-10b"), (INTEGRITY, "INT-06"), (DECM, "06A506a")],
    ids=["P6-10b", "INT-06", "06A506a"],
)
def test_actual_finish_same_day_is_compared_by_timestamp(std, metric_id, dd):
    """101248: "Invalid dates for completed activities are actual finish dates later than the data date"."""
    s = snap([done("A", act_end_date=SAME_DAY)], data_date=at(dd))
    assert codes(run(std, metric_id, s)) == (["A"] if ACTUAL_AFTER[dd] else [])


@pytest.mark.parametrize("dd", DD_HOURS)
def test_dcma_09_reads_actual_dates_by_day(dd):
    """PAM 200.1 §4.9 ("not after 8/1/09"), dcma.toml date_grain = "day": an actual start or finish on
    the status date's day is never beyond it, whatever the hours."""
    s = snap(
        [active("S", act_start_date=SAME_DAY, early_start_date=at("17:00")), done("F", act_end_date=SAME_DAY)],
        data_date=at(dd),
    )
    assert codes(run(DCMA, "DCMA-09", s)) == []


@pytest.mark.parametrize("dd", DD_HOURS)
@pytest.mark.parametrize(("std", "metric_id"), [(P6, "P6-10a"), (DECM, "06A506b")], ids=["P6-10a 101248", "06A506b"])
def test_forecast_start_same_day_is_compared_by_timestamp(std, metric_id, dd):
    """101248: "Invalid dates for not started activities are start dates earlier than the data date";
    06A506b "on or before the status date" = before P6's data date (decm.toml). A forecast start at 12:00
    is before a data date at 17:00 only."""
    s = snap([todo("A", early_start_date=SAME_DAY, early_end_date="2026-03-13 17:00")], data_date=at(dd))
    assert codes(run(std, metric_id, s)) == (["A"] if dd == "17:00" else [])


@pytest.mark.parametrize("dd", DD_HOURS)
def test_dcma_09_reads_forecast_dates_by_day(dd):
    """PAM 200.1 §4.9 by calendar day: a forecast start on the status date's day is not before it."""
    s = snap([todo("A", early_start_date=SAME_DAY, early_end_date="2026-03-13 17:00")], data_date=at(dd))
    assert codes(run(DCMA, "DCMA-09", s)) == []


@pytest.mark.parametrize("dd", DD_HOURS)
def test_dcma_11_due_by_day(dd):
    """PAM 200.1 §4.11, dcma.toml date_grain = "day": a baseline finish on the status date's day is due at
    any hour of the data date; forecast Thursday, so it is missed."""
    s = snap(
        [todo("A", target_start_date="2026-02-02 08:00", target_end_date=SAME_DAY, early_end_date="2026-03-05 17:00")],
        data_date=at(dd),
    )
    r = run(DCMA, "DCMA-11", s, Baseline.planned(s))
    assert (codes(r), r.denominator) == (["A"], 1)


@pytest.mark.parametrize("dd", DD_HOURS)
def test_p6_13_lists_due_by_timestamp(dd):
    """101248, BEI: baseline activities "calculated to finish before the open project's data date", read
    on the stored timestamp (p6.toml default), so a baseline finish at 12:00 is due by a data date at
    17:00 only; 17:00 case not verified against a P6 report. The index itself (completed / every
    baseline activity, R1) does not move."""
    bl = dict(target_start_date="2026-02-02 08:00", target_end_date=SAME_DAY, early_end_date="2026-03-05 17:00")
    s = snap([todo("A", **bl), done("B")], data_date=at(dd))
    r = run(P6, "P6-13", s, Baseline.planned(s))
    assert codes(r) == (["A"] if dd == "17:00" else [])
    assert (r.numerator, r.denominator) == (1, 2)


@pytest.mark.parametrize("dd", DD_HOURS)
def test_p6_12_late_does_not_depend_on_the_data_date_hour(dd):
    """101248 / 46278: late = finish variance in working time > 0, no data date in the test. Forecast
    17:00 against a baseline 12:00 the same day = 4 working hours late at any data date hour."""
    s = snap(
        [todo("A", target_start_date="2026-02-02 08:00", target_end_date=SAME_DAY, early_end_date=at("17:00"))],
        data_date=at(dd),
    )
    assert codes(run(P6, "P6-12", s, Baseline.planned(s))) == ["A"]


@pytest.mark.parametrize(
    ("std", "metric_id"),
    [(P6, "P6-10a"), (P6, "P6-10b"), (INTEGRITY, "INT-06"), (DECM, "06A506a"), (DECM, "06A506b"), (DCMA, "DCMA-09")],
)
def test_dates_exactly_on_the_data_date_are_valid(std, metric_id):
    """Help l.15836: the data date starts the work period. An actual start, a remaining early start or a
    forecast start exactly on it is neither before nor after it."""
    dd = at("08:00")
    s = snap(
        [
            active("S", act_start_date=dd, early_start_date=dd),
            todo("N", early_start_date=dd, early_end_date="2026-03-13 17:00"),
        ],
        data_date=dd,
    )
    assert codes(run(std, metric_id, s)) == []


# --- 2. calendars -----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def calendars():
    s = snap([todo("A")], calendars=[FOUR_TENS, ROUND_THE_CLOCK])
    return {key: s.calendar(key) for key in ("8", "40", "24")}


@pytest.mark.parametrize(
    ("clndr", "start", "end", "work"),
    [
        ("8", "2026-03-06 15:00", "2026-03-09 10:00", 4),  # Fri 15-17, weekend, Mon 08-10
        ("8", "2026-03-02 17:00", "2026-03-03 08:00", 0),  # night
        ("40", "2026-03-05 15:00", "2026-03-09 09:00", 4.5),  # Thu 15:00-17:30, Fri off, Mon 07-09
        ("40", "2026-03-02 11:00", "2026-03-02 13:00", 1.5),  # 11-12, 12:30-13
        ("24", "2026-03-06 22:00", "2026-03-07 02:00", 4),  # through midnight
    ],
)
def test_working_hours_between_two_instants(calendars, clndr, start, end, work):
    """Working time to the minute on the activity's calendar (docs/cpm.md, TimeAxis): weekends,
    exceptions and breaks count nothing."""
    assert calendars[clndr].work_hours(T(start), T(end)) == pytest.approx(work)


def test_working_days_use_the_calendar_hours_per_day(calendars):
    """A day is day_hr_cnt hours of that calendar: 4.5 h on the 4 x 10 calendar is 0.45 day, 4 h on C8 half a day."""
    assert calendars["40"].working_days(T("2026-03-05 15:00"), T("2026-03-09 09:00")) == pytest.approx(0.45)
    assert calendars["8"].working_days(T("2026-03-06 15:00"), T("2026-03-09 10:00")) == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("start", "end", "work"),
    [
        ("2026-03-28 00:00", "2026-03-30 00:00", 48),  # Europe springs forward Sun 29 Mar 02:00
        ("2026-03-29 01:00", "2026-03-29 04:00", 3),
        ("2026-10-24 00:00", "2026-10-26 00:00", 48),  # Europe falls back Sun 25 Oct 03:00
        ("2026-10-25 01:00", "2026-10-25 04:00", 3),
    ],
)
def test_daylight_saving_changes_nothing(calendars, start, end, work):
    """XER dates carry no time zone (`YYYY-MM-DD HH:MM`, P6 data map): working time between two naive
    instants on a 24 h calendar is their wall-clock difference, 23 h and 25 h days do not exist."""
    assert calendars["24"].work_hours(T(start), T(end)) == pytest.approx(work)
    axis = calendars["24"].axis()
    assert axis.add(T("2026-03-28 22:00"), 6 * 60) == T("2026-03-29 04:00")
    assert axis.add(T("2026-10-24 22:00"), 6 * 60) == T("2026-10-25 04:00")


def test_xer_dates_are_naive():
    s = snap([todo("A")], data_date="2026-03-29 02:30")  # a wall-clock time that does not exist in Paris
    assert s.data_date == T("2026-03-29 02:30") and s.data_date.tz is None
    assert s.tasks["early_start_date"].dt.tz is None


def test_day_columns_divide_by_the_activity_calendar_not_the_project_one():
    """SKILL / model.py: `_d` columns are working days of the activity's own calendar (day_hr_cnt). The
    project calendar is C8 (8 h): 50 h on C10 is 5 days, 40 h on 4 x 10 is 4, 48 h on 24 h is 2."""
    s = snap(
        [
            todo("TEN", clndr_id="C10", total_float_hr_cnt="20", **hours(50)),
            todo("FOUR", clndr_id="40", total_float_hr_cnt="10", **hours(40)),
            todo("CLOCK", clndr_id="24", total_float_hr_cnt="24", **hours(48)),
            todo("EIGHT", total_float_hr_cnt="16", **hours(40)),
        ],
        calendars=[FOUR_TENS, ROUND_THE_CLOCK],
    )
    tasks = s.activities.set_index("task_code")
    assert tasks["original_d"].to_dict() == {"TEN": 5, "FOUR": 4, "CLOCK": 2, "EIGHT": 5}
    assert tasks["remaining_d"].to_dict() == {"TEN": 5, "FOUR": 4, "CLOCK": 2, "EIGHT": 5}
    assert tasks["total_float_d"].to_dict() == {"TEN": 2, "FOUR": 1, "CLOCK": 1, "EIGHT": 2}


def test_working_days_row_by_row_on_each_activity_calendar():
    """Snapshot.working_days: Mon 08:00 to Fri 18:00 is 5 days on C10 (50 h); on 4 x 10 the day starts at
    07:00, so 39 h = 3.9 days; Mon 08:00 to the next Mon 08:00 is 7 on 24 h (168 h)."""
    s = snap([todo("A")], calendars=[FOUR_TENS, ROUND_THE_CLOCK])
    clndr = pd.Series(["10", "40", "24"])
    start = pd.Series([T("2026-03-02 08:00")] * 3)
    end = pd.Series([T("2026-03-06 18:00"), T("2026-03-06 18:00"), T("2026-03-09 08:00")])
    assert s.working_days(clndr, start, end).tolist() == pytest.approx([5, 3.9, 7])


# --- 3. the data date ------------------------------------------------------------------------------

MFB = {"project": {"plan_end_date": "2026-03-25 17:00"}}  # Must Finish By: the float's reference
CHAIN = [
    todo("A", total_float_hr_cnt="0"),
    todo("B", total_float_hr_cnt="0"),
    todo("Z", **FM, total_float_hr_cnt="-16", early_end_date="2026-03-27 17:00"),
]


@pytest.mark.parametrize("dd", ["00:00", "08:00"])
def test_data_date_at_midnight_or_at_the_day_start_measures_the_same_working_time(dd):
    """00:00 to 08:00 is not working time on C8: the data date at either hour gives the same working days
    (project calendar, Mon 2 to Fri 27 Mar = 20 wd) and the same CPLI ((20 - 2) / 20, PAM §3.1.2.3)."""
    s = snap(CHAIN, [("A", "B", "FS", 0), ("B", "Z", "FS", 0)], data_date=at(dd), **MFB)
    assert s.project_working_days(s.data_date, T("2026-03-27 17:00")) == pytest.approx(20)
    assert run(DCMA, "DCMA-13", s).value == pytest.approx(0.9)


def test_data_date_at_the_end_of_the_day_starts_the_next_working_day():
    """A data date at 17:00 is the same working instant as the next morning's 08:00: 19 wd to Fri 27 Mar."""
    s = snap([todo("A")], data_date=at("17:00"))
    assert s.project_working_days(s.data_date, T("2026-03-27 17:00")) == pytest.approx(19)
    assert s.project_working_days(s.data_date, T("2026-03-03 08:00")) == 0


def test_two_files_of_the_same_day_at_other_hours_warn():
    """Two files dated 08:00 and 17:00 the same day are both kept, in time order, and the store warns,
    naming the day (store.warnings: shown on the overview and by the CLI). The same timestamp twice
    stays DuplicateDataDate (test_store.py)."""
    morning, evening = snap([todo("A")], data_date=at("08:00")), snap([todo("A")], data_date=at("17:00"))
    store = SnapshotStore([replace(evening, source="pm.xer"), replace(morning, source="am.xer")])
    assert [u.source for u in store] == ["am.xer", "pm.xer"]
    assert any(DAY in warning for warning in store.warnings)


# --- 4. PPC: the week is the span between two data dates ---------------------------------------------

THU_PM, FRI_AM = "2026-03-05 17:00", "2026-03-13 08:00"  # ISO weeks 10 and 11, 8 calendar days apart


def _week(previous_tasks, current_tasks):
    first = replace(snap(previous_tasks, data_date=THU_PM), source="w1.xer")
    second = replace(snap(current_tasks, data_date=FRI_AM), source="w2.xer")
    return SnapshotStore([first, second])


def test_ppc_commitments_are_the_dates_between_the_two_data_dates():
    """progress.py (Last Planner, W-1 commitments vs W outcome): committed = forecast before W's data
    date, so the week is [Thu 17:00, Fri 08:00), not an ISO week nor 7 days. C (Fri 6 Mar, ISO week 10 like
    W-1) is committed; B starting Fri 08:00 and finishing Fri 12:00, at or after W's data date, is not
    (strict "before": consistent with the engine, no P6 source)."""
    store = _week(
        [
            todo("A", early_start_date="2026-03-09 08:00", early_end_date="2026-03-12 17:00", **hours(32)),
            todo("B", early_start_date="2026-03-13 08:00", early_end_date="2026-03-13 12:00", **hours(4)),
            todo("C", early_start_date="2026-03-06 08:00", early_end_date="2026-03-06 17:00", **hours(8)),
        ],
        [
            done("A", act_start_date="2026-03-09 08:00", act_end_date="2026-03-12 17:00"),
            todo("B", early_start_date="2026-03-13 08:00", early_end_date="2026-03-13 12:00", **hours(4)),
            active("C", act_start_date="2026-03-06 08:00", early_start_date="2026-03-13 08:00"),
        ],
    )
    plan = committed(store[0], store[1])
    assert sorted(zip(plan["task_code"], plan["commitment"], plan["kept"], strict=True)) == [
        ("A", "Finish", True),
        ("A", "Start", True),
        ("C", "Finish", False),
        ("C", "Start", True),
    ]
    week = ppc_series(store).iloc[0]
    assert (week["week_start"], week["data_date"]) == (T(THU_PM), T(FRI_AM))
    assert (week["ppc"], week["ppc_start"]) == (50, 100)


# --- 5. MTA: slips in working days of the milestone's calendar ---------------------------------------


def _milestone_store(*finishes, clndr="C8"):
    updates = [
        replace(snap([todo("M", **FM, clndr_id=clndr, early_end_date=f)], data_date=dd), source=f"w{i}.xer")
        for i, (dd, f) in enumerate(zip(("2026-03-02 08:00", "2026-03-09 08:00"), finishes, strict=True))
    ]
    return SnapshotStore(updates)


def _slip(store):
    return milestone_slips(milestone_trend(store), store).set_index("task_code").loc["M", "slip_wd"]


def test_milestone_slip_counts_working_days_of_its_own_calendar():
    """progress.py `milestone_slips`: one calendar week on the 7-day calendar is 7 wd (5 on the project's C8)."""
    assert _slip(_milestone_store("2026-03-13 16:00", "2026-03-20 16:00", clndr="C7D")) == 7


@pytest.mark.parametrize(
    ("first", "latest", "slip"),
    [
        ("2026-03-13 17:00", "2026-03-16 08:00", 0),  # Fri end of day = Mon start: no working time
        ("2026-03-16 08:00", "2026-03-16 17:00", 1),  # Mon 08:00 as a finish = Fri 17:00: a working day
        ("2026-03-16 12:00", "2026-03-16 13:00", 0),  # across lunch
    ],
)
def test_milestone_slip_is_working_time_not_calendar_date(first, latest, slip):
    """The slip is working time on the milestone's calendar (TimeAxis: a finish at a period start is the
    end of the previous period), not a difference of calendar dates. Oracle defines the variance as a
    difference of finish dates: help l.38054-38060 ("Finish Date Variance (days) ... calculated as BL
    Finish - Finish Date") and "Durations Columns of the Activity Table" (47223.htm: "Variance - BL
    Project Finish Date ... calculated as Finish minus BL Project Finish"). Working vs calendar days not
    stated by Oracle; engine convention, to verify against a P6 column. Mon 08:00 to Mon 17:00 = 1 wd:
    consistent with the engine, no P6 source."""
    assert _slip(_milestone_store(first, latest)) == slip


# --- 6. earned value: Schedule % Complete ------------------------------------------------------------

EV_TASK = todo(
    "A", target_start_date="2026-03-02 08:00", target_end_date="2026-03-13 17:00", target_work_qty="80", **hours(80)
)  # 80 working hours on C8, two weeks


@pytest.fixture(scope="module")
def ev_baseline():
    return Baseline.from_snapshot(snap([EV_TASK]))


def _schedule_pct(baseline, when):
    return float(schedule_pct(baseline, T(when)).loc["A"])


@pytest.mark.parametrize(
    ("when", "pct"),
    [
        ("2026-03-02 08:00", 0),  # data date = baseline start
        ("2026-03-13 17:00", 100),  # data date = baseline finish
        ("2026-03-01 10:00", 0),  # before the start
        ("2026-03-20 10:00", 100),  # after the finish
        ("2026-03-04 17:00", 30),  # 24 of 80 h
    ],
)
def test_schedule_pct_at_the_bounds(ev_baseline, when, pct):
    """Help l.38630-38636 (Planned Value Labor Units): Schedule % Complete = share of the baseline
    duration completed at the data date, a duration being working time."""
    assert _schedule_pct(ev_baseline, when) == pytest.approx(pct)


@pytest.mark.parametrize(
    ("off", "last_working"),
    [
        ("2026-03-07 10:00", "2026-03-06 17:00"),  # Saturday = Friday end of day
        ("2026-03-09 06:00", "2026-03-06 17:00"),  # Monday before 08:00
        ("2026-03-03 03:00", "2026-03-02 17:00"),  # night
        ("2026-03-02 12:30", "2026-03-02 12:00"),  # lunch break
    ],
)
def test_schedule_pct_outside_working_time_is_the_last_working_minute(ev_baseline, off, last_working):
    """Non-working time adds no duration: a data date at night, on a weekend or in a break gives the value
    of the end of the last working period. Help l.38630-38636 states working time; the lunch break case
    is consistent with the engine, no P6 source."""
    assert _schedule_pct(ev_baseline, off) == pytest.approx(_schedule_pct(ev_baseline, last_working))


# --- 7. P6 export text (Activities view saved as CSV) ------------------------------------------------

EXPORT_HEADERS = [
    "Activity ID",
    "Planned Value Labor Units",
    "Earned Value Labor Units",
    "Schedule % Complete",
    "BL Project Start",
    "Planned Finish",
]


def _export(rows, sep=";", encoding="utf-8", bom=b""):
    return bom + "\n".join(sep.join(row) for row in [EXPORT_HEADERS, *rows]).encode(encoding)


def _frame(content):
    raw = read_p6_export("export.csv", content)
    return p6_export_frame(raw, p6_export_columns(raw))[0]


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("02/03/2026 08:00 A", "02/03/2026 08:00"),  # dd/MM/yyyy HH:mm, actual
        ("03/02/2026 A", "03/02/2026"),  # MM/dd/yyyy, actual
        ("2026-03-02 *", "2026-03-02"),  # yyyy-MM-dd, constraint
        ("02-Mar-26 08:00", "02-Mar-26 08:00"),
        ("02/03/2026 08:00 AM A", "02/03/2026 08:00 AM"),  # only the flag goes, not the "A" of AM
    ],
)
def test_export_dates_keep_their_text_and_lose_the_flag(text, kept):
    """diagnostic.py: P6 marks actual dates "A" and constraint dates "*"; the dates are shown as P6 wrote
    them, never re-read in another day/month order."""
    frame = _frame(_export([["A1", "1", "0", "0%", text, text]]))
    assert (frame.loc["A1", "bl_start"], frame.loc["A1", "finish"]) == (kept, kept)


@pytest.mark.parametrize(
    ("sep", "pv"),
    [
        (";", "1 234,50"),
        (";", "1\u00a0234,50"),  # French Windows locale groups digits with a no-break space
        ("\t", "1,234.50"),
        ("\t", "1234.5"),
        (";", "1.234,5"),
    ],
    ids=["space-comma", "nbsp-comma", "comma-dot", "plain", "dot-comma"],
)
def test_export_numbers_in_any_locale(sep, pv):
    frame = _frame(_export([["A1", pv, "0", "40,5 %", "", ""]], sep=sep))
    assert (frame.loc["A1", "pv_hr"], frame.loc["A1", "schedule_pct"]) == pytest.approx((1234.5, 40.5))


def test_export_comma_separated_with_quoted_thousands():
    content = "\n".join(
        ",".join(f'"{v}"' for v in row)
        for row in [EXPORT_HEADERS, ["A1", "1,234.50", "12.5", "40%", "2026-03-02 08:00 A", "2026-03-13 17:00"]]
    ).encode()
    frame = _frame(content)
    assert (frame.loc["A1", "pv_hr"], frame.loc["A1", "ev_hr"]) == pytest.approx((1234.5, 12.5))


@pytest.mark.parametrize(
    ("sep", "encoding", "bom"),
    [
        (sep, encoding, bom)
        for sep in (";", ",", "\t")
        for encoding, bom in (("utf-8", codecs.BOM_UTF8), ("utf-8", b""), ("cp1252", b""))
        if (sep, encoding) != (";", "cp1252")  # test_pv_p6.test_semicolon_csv_in_cp1252
    ],
)
def test_export_encodings_and_separators(sep, encoding, bom):
    """read_p6_export: UTF-8 with or without BOM, else Windows-1252; comma, semicolon or tab. The BOM does
    not stick to the first header, and "é" survives both encodings."""
    frame = _frame(_export([["É-1", "8", "0", "50", "", ""]], sep=sep, encoding=encoding, bom=bom))
    assert frame.index.tolist() == ["É-1"]
    assert frame.loc["É-1", "pv_hr"] == 8


@pytest.mark.parametrize(
    "content",
    [b"", ";".join(EXPORT_HEADERS).encode(), b"PK\x03\x04" + b"\x00" * 50],
    ids=["empty", "header only", "xlsx bytes"],
)
def test_export_unreadable_is_a_clean_value_error(content):
    with pytest.raises(ValueError, match="cannot be read as a CSV table|no header row"):
        read_p6_export("export.csv", content)


def test_export_in_utf16_is_read_or_refused():
    """Excel's "Unicode Text" (UTF-16 with BOM, tab-separated): it decoded as cp1252 with NUL bytes and
    gave a frame of garbled headers. Now read by its BOM."""
    content = "\n".join("\t".join(r) for r in [EXPORT_HEADERS, ["A1", "8", "0", "50", "", ""]]).encode("utf-16")
    try:
        raw = read_p6_export("export.csv", content)
    except ValueError:
        return  # refused cleanly: acceptable
    assert p6_export_columns(raw)["task_code"] == "Activity ID"


@pytest.mark.parametrize("body", [["A1;1;2;3;4;5;6;7"], ["A1;1;2;3;4;5;6;7", "B1;1"]], ids=["long", "long+short"])
def test_export_row_longer_than_header_is_refused(body):
    """A row longer than the header shifted the columns silently (pandas took the extra leading fields as
    the index: Activity ID became the 3rd field); with a short row as well, AttributeError ('float' has no
    'strip') escaped. read_p6_export's docstring: ValueError for a file that is not a CSV table."""
    content = (";".join(EXPORT_HEADERS) + "\n" + "\n".join(body)).encode()
    with pytest.raises(ValueError):
        read_p6_export("export.csv", content)


def test_export_row_shorter_than_header_reads_blank_cells():
    """B1 stops after its PV: the cells it lacks are blank, as P6 leaves an empty field."""
    frame = _frame(_export([["A1", "8", "4", "50", "", ""], ["B1", "6"]]))
    assert frame.loc["B1", "pv_hr"] == 6 and pd.isna(frame.loc["B1", "ev_hr"])


# --- 8. XER date fields ------------------------------------------------------------------------------


def test_xer_date_forms():
    """XER dates are `YYYY-MM-DD HH:MM` (P6 data map); a date without hour is midnight; blank is missing.
    Mixed forms in one column are each read, in any order. `0000-00-00` read as missing: consistent with
    the engine, no P6 source."""
    values = pd.Series(["2026-11-01 08:00", "2026-11-01", "", "0000-00-00", "2026-11-02 17:00"])
    assert to_datetime(values).tolist()[:2] == [T("2026-11-01 08:00"), T("2026-11-01 00:00")]
    assert to_datetime(values).isna().tolist() == [False, False, True, True, False]
    assert to_datetime(values[::-1]).tolist()[0] == T("2026-11-02 17:00")


def test_xer_date_without_hour_is_midnight_in_the_snapshot():
    """An actual finish written without an hour reads as 00:00: before a 08:00 data date the same day,
    so it is not an actual date after the data date (P6-10b)."""
    s = snap([done("A", act_end_date="2026-03-02"), todo("B", act_start_date="", cstr_date="0000-00-00")])
    tasks = s.activities.set_index("task_code")
    assert tasks.loc["A", "act_end_date"] == T("2026-03-02 00:00")
    assert pd.isna(tasks.loc["B", "cstr_date"])
    assert codes(run(P6, "P6-10b", s)) == []
