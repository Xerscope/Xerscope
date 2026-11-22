"""``TimeAxis.work`` on one timestamp gives what the array search gives, minute by minute.

``work`` searches the working periods of the axis for one minute offset with ``bisect`` on Python lists
(``_raw_one``), because a numpy call per value cost more than the search; ``work_many`` and the axis
origin keep the numpy search (``_raw``). The two must agree on every minute: inside a period, on its
bounds, between periods, before the first and after the last, and once the axis has grown.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from xerscope.xer.calendar import TimeAxis, WorkCalendar

pytestmark = pytest.mark.oracle("property")

DAY = (480, 720), (780, 1020)  # 08:00-12:00, 13:00-17:00
NIGHT_START = ((1320, 1440),)  # 22:00-24:00 on Sunday, the start of a night shift
WEEK = (((0, 360), *DAY), DAY, DAY, DAY, DAY, (), NIGHT_START)  # Monday also works 00:00-06:00
EXCEPTIONS = {
    date(2026, 3, 11): (),  # a Wednesday holiday
    date(2026, 3, 14): ((480, 600),),  # a Saturday worked 08:00-10:00
}
CALENDAR = WorkCalendar("X", "shifts, a holiday, a worked Saturday", 8.0, WEEK, EXCEPTIONS, from_data=True)


def _scalar_and_array(axis: TimeAxis) -> tuple[list[int], list[int]]:
    """Every minute offset from one day before the axis to one day after it, by both searches."""
    minutes = np.arange(-1440, axis.span_min + 1440, dtype=np.int64)
    return [axis._raw_one(int(m)) for m in minutes], axis._raw(minutes).tolist()


def test_every_minute_of_the_axis_reads_the_same_by_both_searches():
    axis = TimeAxis(CALENDAR, date(2026, 3, 2), date(2026, 3, 22))
    scalar, array = _scalar_and_array(axis)
    assert scalar == array


def test_the_searches_still_agree_once_the_axis_has_grown():
    axis = TimeAxis(CALENDAR, date(2026, 3, 2), date(2026, 3, 22))
    axis.work(pd.Timestamp("2027-06-01 09:30"))  # beyond the window: the axis is rebuilt wider
    scalar, array = _scalar_and_array(axis)
    assert scalar == array


def test_work_on_one_timestamp_equals_work_many():
    axis = TimeAxis(CALENDAR, date(2026, 3, 2), date(2026, 3, 22))
    stamps = pd.date_range("2026-03-01 00:00", "2026-03-24 00:00", freq="7min")
    assert [axis.work(stamp) for stamp in stamps] == axis.work_many(stamps).tolist()
