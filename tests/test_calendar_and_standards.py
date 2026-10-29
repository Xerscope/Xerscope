from datetime import date

import pandas as pd
import pytest
from xerkit import MON_FRI_8H

from xerscope.analysis import builtin_standards, loads_standard, template_text
from xerscope.xer.calendar import WorkCalendar, parse_clndr_data

# --- calendars ------------------------------------------------------------------------------


def test_p6_day_numbers_start_on_sunday():
    week, exc = parse_clndr_data(MON_FRI_8H)
    assert [sum(b - a for a, b in d) / 60 for d in week] == [8, 8, 8, 8, 8, 0, 0]  # Mon..Sun
    assert exc == {date(2026, 4, 3): ()}  # Excel serial 46115, non-working


def test_working_exception_and_midnight_end():
    blob = (
        "(0||CalendarData()((0||DaysOfWeek()((0||1()((0||0(s|00:00|f|00:00)())))"
        "(0||2()())(0||3()())(0||4()())(0||5()())(0||6()())(0||7()())))"
        "(0||Exceptions()((0||0(d|46118)((0||0(s|08:00|f|12:00)())))))))"
    )
    cal = WorkCalendar.from_row(pd.Series({"clndr_id": "X", "day_hr_cnt": "24", "clndr_data": blob}))
    assert cal.hours_on(date(2026, 3, 1)) == 24  # Sunday, 00:00 -> 00:00 = whole day
    assert cal.hours_on(date(2026, 4, 6)) == 4  # Monday exception with its own hours
    assert cal.hours_on(date(2026, 4, 7)) == 0


def test_work_hours_are_exact_within_days():
    cal = WorkCalendar.from_row(pd.Series({"clndr_id": "C", "day_hr_cnt": "8", "clndr_data": MON_FRI_8H}))
    mon8, fri17 = pd.Timestamp("2026-03-02 08:00"), pd.Timestamp("2026-03-06 17:00")
    assert cal.work_hours(mon8, fri17) == 40
    assert cal.work_hours(mon8, pd.Timestamp("2026-03-02 12:30")) == 4  # lunch is not work
    assert cal.work_hours(fri17, mon8) == -40
    assert cal.work_hours(pd.Timestamp("2026-04-02 17:00"), pd.Timestamp("2026-04-06 08:00")) == 0  # Good Friday


def test_missing_blob_infers_workweek_from_hour_counts():
    seven = WorkCalendar.from_row(pd.Series({"clndr_id": "7", "day_hr_cnt": "8", "week_hr_cnt": "56"}))
    assert seven.week_hours == (8,) * 7 and not seven.from_data
    five = WorkCalendar.from_row(pd.Series({"clndr_id": "5", "day_hr_cnt": "10", "week_hr_cnt": ""}))
    assert five.week_hours == (10,) * 5 + (0, 0)


def test_reference_calendars_parse(store):
    cal = store.first.calendar()
    assert cal.week_hours == (8,) * 7  # sample: 7 days x 8 h, no blob


# --- standards as data ---------------------------------------------------------------------


def test_builtin_standards():
    std = builtin_standards()
    assert set(std) >= {"P6", "DCMA", "DECM", "INTEGRITY"}
    assert len(std["DCMA"].metrics) == 14
    assert len(std["P6"].metrics) == 14  # P6 Professional 24
    assert len(std["DECM"].metrics) == 16
    assert std["DCMA"]["DCMA-13"].threshold == 0.95
    assert std["P6"]["P6-05"].params["value"] == 352


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
        ('rule = "cpli"\ntarget = "<= 5%"', "is a percentage but the metric unit is 'ratio'"),
        ('rule = "lag"\nparams = { links = "some" }', "links must be one of"),
        ('rule = "float"\ncolour = "red"', "unknown key(s) ['colour']"),
    ],
)
def test_invalid_standard_fails_loudly(metric, error):
    text = HEAD + f'[[metric]]\nid = "X-1"\nname = "m"\n{metric}\n'
    with pytest.raises(ValueError, match=pytest.importorskip("re").escape(error)):
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


def test_cli_writes_template(tmp_path):
    from xerscope.cli import main

    out = tmp_path / "mine.toml"
    assert main(["standards", "--template", str(out)]) == 0
    assert loads_standard(out.read_bytes()).id == "CUSTOM"


def test_time_axis_values_survive_growing_backwards():
    """A work value taken before the axis grew must still map to the same instant."""
    from datetime import date

    import pandas as pd
    from xerkit import snap, todo

    from xerscope.xer.calendar import TimeAxis

    T = pd.Timestamp
    ax = TimeAxis(snap([todo("A")]).calendar("C8"), date(2026, 3, 2), date(2026, 3, 31))
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
