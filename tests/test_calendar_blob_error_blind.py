"""A malformed CALENDAR.clndr_data is refused with an XerError naming the calendar and the faulty text.

P6 never writes a malformed blob, so a file carrying one is damaged or edited by hand.
"""

from __future__ import annotations

import pytest
from xerkit import clndr_data, hours, todo, xer_text

from xerscope.xer import build_snapshot, parse_text
from xerscope.xer.parser import XerError

CLNDR_ID = "77"
CLNDR_NAME = "Chantier Nord"

GOOD = clndr_data(range(2, 7), [("08:00", "12:00"), ("13:00", "17:00")], (46115,))

HOUR_8H00 = GOOD.replace("s|08:00|f|12:00", "s|8h00|f|12:00", 1)
PERIOD_XX = GOOD.replace("s|08:00|f|12:00", "s|xx:yy", 1)
SERIAL_BIG = GOOD.replace("d|46115", "d|99999999", 1)
UNBALANCED = GOOD[:-1]


def load(blob: str):
    row = {
        "clndr_id": CLNDR_ID,
        "clndr_name": CLNDR_NAME,
        "day_hr_cnt": "8",
        "week_hr_cnt": "40",
        "clndr_data": blob,
    }
    text = xer_text([todo("A", **hours(8))], calendars=[row])
    return build_snapshot(parse_text(text, source="t.xer"))


@pytest.mark.parametrize(
    ("blob", "token"),
    [
        pytest.param(HOUR_8H00, "8h00", id="hour-8h00"),
        pytest.param(PERIOD_XX, "xx:yy", id="period-xx-yy"),
        pytest.param(SERIAL_BIG, "99999999", id="exception-serial"),
        pytest.param(UNBALANCED, None, id="unbalanced-parenthesis"),
    ],
)
def test_malformed_blob_raises_xer_error_naming_the_calendar(blob, token):
    assert blob != GOOD
    try:
        load(blob)
    except Exception as err:  # noqa: BLE001 - the point is that nothing else escapes
        assert type(err) is XerError, f"{type(err).__name__}: {err}"
        message = str(err)
        assert CLNDR_ID in message
        assert CLNDR_NAME in message
        if token is not None:
            assert token in message
    else:
        pytest.fail("a malformed clndr_data was loaded without error")


def test_well_formed_blob_loads():
    assert load(GOOD) is not None


def test_empty_blob_still_loads():
    assert load("") is not None
