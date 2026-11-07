import re
from datetime import date

import pandas as pd
import pytest
from xerkit import CALENDAR_IDS, MON_FRI_8H, clndr_data, snap, todo
from xerkit import hours as duration

from xerscope.analysis import builtin_standards, loads_standard, template_text
from xerscope.xer.calendar import WorkCalendar, parse_clndr_data

# --- calendars ------------------------------------------------------------------------------


def hours(periods):
    return sum(end - start for start, end in periods) / 60


def test_p6_day_numbers_start_on_sunday():
    week, exc = parse_clndr_data(MON_FRI_8H)
    assert [hours(day) for day in week] == [8, 8, 8, 8, 8, 0, 0]  # Mon..Sun
    assert exc == {date(2026, 4, 3): ()}  # Excel serial 46115, non-working


def test_working_exception_and_midnight_end():
    blob = (
        "(0||CalendarData()((0||DaysOfWeek()((0||1()((0||0(s|00:00|f|00:00)())))"
        "(0||2()())(0||3()())(0||4()())(0||5()())(0||6()())(0||7()())))"
        "(0||Exceptions()((0||0(d|46118)((0||0(s|08:00|f|12:00)())))))))"
    )
    cal = WorkCalendar.from_row(pd.Series({"clndr_id": "X", "day_hr_cnt": "24", "clndr_data": blob}))
    assert hours(cal.periods(date(2026, 3, 1))) == 24  # Sunday, 00:00 -> 00:00 = whole day
    assert hours(cal.periods(date(2026, 4, 6))) == 4  # Monday exception with its own hours
    assert hours(cal.periods(date(2026, 4, 7))) == 0


def test_a_period_ending_at_or_before_its_start_is_no_work():
    """Only "f|00:00" ends at midnight (MPXJ, LocalTimeHelper.getMillisecondsInRange: an end at
    MIDNIGHT runs to the end of the day, any other end is end - start). 13:00-13:00 is empty;
    22:00-06:00 has no P6 meaning (P6 writes no period across midnight: none in 394 reference
    files): ignored and noted, not read as 22:00-24:00."""
    periods = "(0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|13:00)())(0||2(s|22:00|f|06:00)())"
    late = "(0||0(s|22:00|f|00:00)())"
    blob = f"(0||CalendarData()((0||DaysOfWeek()((0||2()({periods}))(0||3()({late}))))))"
    cal = WorkCalendar.from_row(pd.Series({"clndr_id": "X", "day_hr_cnt": "4", "clndr_data": blob}))
    assert cal.week[0] == ((480, 720),)  # Monday: 08:00-12:00 only
    assert cal.week[1] == ((1320, 1440),)  # Tuesday: 22:00 to midnight
    assert cal.notes == ("work period 22:00-06:00 ends before it starts; ignored",)
    snapshot = snap([{"task_code": "A"}], calendars=[{"clndr_id": "40", "day_hr_cnt": "4", "clndr_data": blob}])
    assert "test.xer: calendar 40 (): work period 22:00-06:00 ends before it starts; ignored" in snapshot.warnings


def test_work_hours_are_exact_within_days():
    cal = WorkCalendar.from_row(pd.Series({"clndr_id": "C", "day_hr_cnt": "8", "clndr_data": MON_FRI_8H}))
    mon8, fri17 = pd.Timestamp("2026-03-02 08:00"), pd.Timestamp("2026-03-06 17:00")
    assert cal.work_hours(mon8, fri17) == 40
    assert cal.work_hours(mon8, pd.Timestamp("2026-03-02 12:30")) == 4  # lunch is not work
    assert cal.work_hours(fri17, mon8) == -40
    assert cal.work_hours(pd.Timestamp("2026-04-02 17:00"), pd.Timestamp("2026-04-06 08:00")) == 0  # Good Friday


def test_missing_blob_infers_workweek_from_hour_counts():
    seven = WorkCalendar.from_row(pd.Series({"clndr_id": "7", "day_hr_cnt": "8", "week_hr_cnt": "56"}))
    assert [hours(day) for day in seven.week] == [8] * 7
    five = WorkCalendar.from_row(pd.Series({"clndr_id": "5", "day_hr_cnt": "10", "week_hr_cnt": ""}))
    assert [hours(day) for day in five.week] == [10] * 5 + [0, 0]


def test_unknown_task_calendar_falls_back_to_the_project_calendar():
    """A clndr_id absent from CALENDAR: hours per day from the project's calendar, as
    Snapshot.calendar resolves it, and the file is flagged."""
    snapshot = snap(
        [{"task_code": "A", "clndr_id": "999"}, {"task_code": "B", "clndr_id": "C10"}],
        project={"clndr_id": "C10"},
    )
    tasks = snapshot.tasks.set_index("task_code")
    assert snapshot.calendar("999").hours_per_day == 10.0  # the project's calendar, not 8 h
    assert tasks.at["A", "hours_per_day"] == 10.0
    assert tasks.at["A", "original_d"] == tasks.at["B", "original_d"]  # same stored duration
    assert any("999" in warning for warning in snapshot.warnings)


# A global calendar with two holidays, Fri 3 and Mon 6 April 2026 (Excel serials 46115, 46118),
# and project calendars built on it: P6's "Inherit Holidays and Exceptions from Global Calendar".
GLOBAL = {
    "clndr_id": "30",
    "clndr_name": "Global",
    "clndr_type": "CA_Base",
    "day_hr_cnt": "8",
    "week_hr_cnt": "40",
    "clndr_data": clndr_data(range(2, 7), [("08:00", "12:00"), ("13:00", "17:00")], (46115, 46118)),
}
# its own exception on 6 April: a working morning, which wins over the base's holiday
OWN_MORNING = "(0||0(d|46118)((0||0(s|08:00|f|12:00)())))"
DERIVED = {
    **GLOBAL,
    "clndr_id": "31",
    "clndr_name": "Project",
    "clndr_type": "CA_Project",
    "base_clndr_id": "30",
    "clndr_data": clndr_data(range(2, 7), [("08:00", "12:00"), ("13:00", "17:00")]).replace(
        "Exceptions()()", f"Exceptions()({OWN_MORNING})"
    ),
}
DERIVED_TWICE = {**DERIVED, "clndr_id": "32", "base_clndr_id": "31", "clndr_data": DERIVED["clndr_data"]}


def test_a_derived_calendar_inherits_the_holidays_of_its_base():
    """Oracle: "Assign a base calendar to determine holidays and exceptions for the selected
    project calendar." MPXJ (ProjectCalendar.getException) looks in the base when the calendar
    has no exception of its own on the date, up the chain of bases."""
    snapshot = snap([{"task_code": "A", "clndr_id": "31"}], calendars=[GLOBAL, DERIVED, DERIVED_TWICE])
    derived, twice = snapshot.calendar("31"), snapshot.calendar("32")
    for calendar in (derived, twice):
        assert hours(calendar.periods(date(2026, 4, 3))) == 0  # the base's holiday
        assert hours(calendar.periods(date(2026, 4, 6))) == 4  # its own exception wins
        assert hours(calendar.periods(date(2026, 4, 7))) == 8  # its own work week
    assert hours(snapshot.calendar("30").periods(date(2026, 4, 6))) == 0  # the base is unchanged
    assert [w for w in snapshot.warnings if "inherited" in w] == [
        "test.xer: calendar 31: 1 holiday or exception inherited from base calendar 30",
        "test.xer: calendar 32: 1 holiday or exception inherited from base calendar 31",
    ]


def test_a_derived_calendar_moves_the_cpm_dates():
    """16 h from Thu 2 April 08:00 on a calendar whose base has Good Friday off: P6's holiday,
    so the finish is Mon 6 April 17:00 (MPXJ gives the same, tests/test_crosscheck_mpxj.py)."""
    from xerscope.analysis.cpm import schedule

    week = clndr_data(range(2, 7), [("08:00", "12:00"), ("13:00", "17:00")])  # no exception of its own
    derived = {**DERIVED, "base_clndr_id": CALENDAR_IDS["C8"], "clndr_data": week}
    a = todo("A", clndr_id="31", cstr_type="CS_MSOA", cstr_date="2026-04-02 08:00", **duration(16))
    frame = schedule(snap([a], calendars=[derived])).frame
    assert frame.at["A", "ef"] == pd.Timestamp("2026-04-06 17:00")


def test_a_missing_base_or_a_loop_of_bases_is_flagged_and_reads_the_calendar_alone():
    missing = {**DERIVED, "base_clndr_id": "99"}
    snapshot = snap([{"task_code": "A", "clndr_id": "31"}], calendars=[missing])
    assert hours(snapshot.calendar("31").periods(date(2026, 4, 3))) == 8
    assert "test.xer: calendar 31: base calendar 99 is not in the file" in snapshot.warnings
    loop = [{**GLOBAL, "base_clndr_id": "31"}, DERIVED]
    snapshot = snap([{"task_code": "A", "clndr_id": "31"}], calendars=loop)
    assert hours(snapshot.calendar("31").periods(date(2026, 4, 3))) == 0  # 30's holiday, read once
    assert any("loop" in w and "31" in w for w in snapshot.warnings)


# --- standards as data ---------------------------------------------------------------------


def test_builtin_standards():
    std = builtin_standards()
    assert set(std) >= {"P6", "DCMA", "DECM", "INTEGRITY"}
    assert len(std["DCMA"].metrics) == 14
    # the 14 of the help + out of sequence, dangling start and finish; Invalid Progress Dates on two lines
    assert len(std["P6"].metrics) == 18
    assert len(std["DECM"].metrics) == 16
    assert std["DCMA"]["DCMA-13"].threshold == 0.95
    assert std["P6"]["P6-05"].rule == "p6_05_long_lags"


def test_template_is_a_valid_standard():
    s = loads_standard(template_text())
    assert s.id == "CUSTOM" and len(s.metrics) >= 10


HEAD = '[standard]\nid = "X"\nname = "X"\n'


@pytest.mark.parametrize(
    "metric,error",
    [
        ('rule = "nope"', "unknown rule 'nope'"),
        ('rule = "float"\nparams = { treshold = 3 }', "no parameter(s) ['treshold']"),
        ('rule = "float"\nparams = { exclude = ["finished"] }', "unknown value(s) ['finished']"),
        ('rule = "float"\ntarget = "about 5"', "write e.g."),
        ('rule = "bei"\ntarget = "<= 5%"', "is a percentage but the metric unit is 'ratio'"),
        ('rule = "lag"\nparams = { links = "some" }', "lag.links: 'some' is not one of"),
        ('rule = "float"\ncolour = "red"', "unknown key(s) ['colour']"),
        ('rule = "float"\nparams = { op = "=>" }', "float.op: '=>' is not one of"),
        ('rule = "float"\nparams = { value = "352" }', "float.value: expected a number"),
        ('rule = "float"\nparams = { exclude = "complete" }', "float.exclude: expected a list of names"),
        ('rule = "lag"\nparams = { exclude_loe = "yes" }', "lag.exclude_loe: expected true or false"),
        ('rule = "constraints"\nparams = { types = ["CS_MANDATORY"] }', "constraints.types: unknown"),
        ('rule = "bei"\nunit = "count"\ntarget = "<= 5"', "unit 'count' does not fit rule 'bei'"),
    ],
)
def test_invalid_standard_fails_loudly(metric, error):
    text = HEAD + f'[[metric]]\nid = "X-1"\nname = "m"\n{metric}\n'
    with pytest.raises(ValueError, match=re.escape(error)):
        loads_standard(text)


def test_duplicate_ids_rejected():
    m = '[[metric]]\nid = "A"\nname = "a"\nrule = "float"\n'
    with pytest.raises(ValueError, match="duplicate id"):
        loads_standard(HEAD + m + m)


def test_standard_files_in_utf16_and_bom_load(tmp_path):
    from xerscope.analysis import load_standard

    for enc in ("utf-16", "utf-8-sig"):
        p = tmp_path / f"{enc}.toml"
        p.write_text(template_text(), encoding=enc)
        assert load_standard(p).id == "CUSTOM"


def test_time_axis_values_survive_growing_backwards():
    """A work value taken before the axis grew must still map to the same instant."""
    from datetime import date

    import pandas as pd
    from xerkit import snap, todo

    from xerscope.xer.calendar import TimeAxis

    T = pd.Timestamp
    ax = TimeAxis(snap([todo("A")]).calendar(CALENDAR_IDS["C8"]), date(2026, 3, 2), date(2026, 3, 31))
    w = ax.work(T("2026-03-10 10:00"))
    assert ax.work(T("2025-01-06 08:00")) < 0  # the axis grew a year back
    assert ax.at(w, finish=True) == T("2026-03-10 10:00")
    assert ax.add(T("2026-03-02 08:00"), -5 * 480, finish=False) == T("2026-02-23 08:00")
    assert ax.between(T("2026-02-27 17:00"), T("2026-03-02 17:00")) == 480


def test_overlapping_periods_count_once():
    from xerscope.xer.calendar import parse_clndr_data

    blob = (
        "(0||CalendarData()((0||DaysOfWeek()((0||2()((0||0(s|08:00|f|12:00)())(0||1(s|10:00|f|14:00)())"
        "(0||2(s|14:00|f|16:00)())))))))"
    )
    week, _ = parse_clndr_data(blob)
    assert week[0] == ((480, 960),)  # 08:00-16:00 once, not 4 + 4 + 2 hours


def test_threshold_defaults_of_the_rules_equal_the_standard_files():
    """A threshold lives in the standard file and as the rule's default; the two never disagree, and
    every built-in metric states each threshold its rule takes, so the explanation shows 'standard'."""
    from xerscope.analysis.rules import RULES

    checked = 0
    for standard in builtin_standards().values():
        for metric in standard.metrics:
            for name, default in RULES[metric.rule].params.items():
                if not name.endswith(("_hours", "_days", "_wd")):
                    continue
                assert name in metric.params, (metric.id, name)
                assert metric.params[name] == default, (metric.id, name, metric.params[name], default)
                checked += 1
    assert checked == 13  # P6-04/05/06, DCMA-06/08/12, 06A211a, 06A401a, 06A504a, 06A504b, 06A506c (3 parameters)
