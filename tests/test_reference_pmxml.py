"""The P6 XML reader against the XER reader, on projects P6 itself exported in both formats.

Two public pairs of MPXJ's test data (tests/reference/sources.py): resource-rates-test (P6 20.12, one
activity, assignments with rates) and percent-complete-8.4 (P6 8.4, twelve activities, not started and in
progress). The XER is the oracle: what xerscope reads of P6's own XER is what it must read of P6's XML of
the same project, for everything a baseline is read for (xer/pmxml.py reads baselines only). The XML holds
a ``Project``, not a ``BaselineProject``; renaming the element is the only change made to it.

Left out on purpose, as xer/pmxml.py documents: the GUID (another encoding, written blank), the longest
path flag and the WBS earned value technique, which a baseline is never read for.
"""

import dataclasses
import re

import pandas as pd
import pytest

from xerscope.analysis.baseline import Baseline
from xerscope.analysis.evm import ev_point
from xerscope.xer import load_snapshot

pytestmark = pytest.mark.oracle("p6")

PAIRS = [
    ("mpxj/resource-rates-test.xer", "mpxj/resource-rates-test.xml"),
    ("mpxj/percent-complete-8.4.xer", "mpxj/percent-complete-8.4.pmxml"),
]


def _as_baseline_export(data: bytes) -> bytes:
    """The project of a P6 XML export written as the BaselineProject the reader reads."""
    return re.sub(rb"<(/?)Project>", rb"<\1BaselineProject>", data)


def _baselines(require_reference, xer: str, xml: str):
    from_xer = load_snapshot(require_reference(xer))
    xml_path = require_reference(xml)
    from_xml = load_snapshot(_as_baseline_export(xml_path.read_bytes()), name=xml_path.name)
    return from_xer, Baseline.from_snapshot(from_xer), Baseline.from_snapshot(from_xml)


def _working_noon(baseline: Baseline) -> pd.Timestamp:
    """Noon of the first weekday at or after 40 % of the baseline's span: inside a working day, so a working
    day's length weighs on the planned value (between two days every day scales alike and it would not)."""
    start, finish = baseline.frame["bl_start"].min(), baseline.frame["bl_finish"].max()
    day = (start + 0.4 * (finish - start)).normalize()
    while day.weekday() >= 5:
        day += pd.Timedelta(days=1)
    return day + pd.Timedelta(hours=12)


@pytest.mark.parametrize(("xer", "xml"), PAIRS)
def test_the_xml_gives_the_baseline_the_xer_gives(require_reference, xer, xml):
    """Planned and forecast dates, labour hours, durations, calendar, names and costs, task by task. The
    cost of resource-rates-test reads 27600.0 from the XER and 27600 from the XML, and the Activity IDs
    index is a string column on one side and an object column on the other: same values, dtypes not compared."""
    _, from_xer, from_xml = _baselines(require_reference, xer, xml)
    pd.testing.assert_frame_equal(
        from_xml.frame.sort_index(), from_xer.frame.sort_index(), check_dtype=False, check_index_type=False
    )


@pytest.mark.parametrize(("xer", "xml"), PAIRS)
def test_an_update_measured_against_the_xml_baseline_reads_as_against_the_xer_baseline(require_reference, xer, xml):
    """BAC, planned value and earned value of the XER as an update, against the baseline of each format, at
    noon of a working day 40 % through the baseline (``_working_noon``): the files' own status dates fall
    before its first start, where the planned value is 0 whatever is read. There it is spread on the
    baseline's calendars, so the calendars are compared too."""
    update, from_xer, from_xml = _baselines(require_reference, xer, xml)
    update = dataclasses.replace(update, data_date=_working_noon(from_xer))
    measured = {name: ev_point(update, baseline) for name, baseline in (("xer", from_xer), ("xml", from_xml))}
    for field in ("bac_hr", "pv_hr", "ev_hr"):
        assert getattr(measured["xml"], field) == pytest.approx(getattr(measured["xer"], field)), field
    assert measured["xer"].pv_hr > 0
