"""The Earned Schedule figures of an update put into words (``explain.schedule_reading``).

Hand cases: each sentence follows from the figures given, in the order a reader asks them (where the project
stands, at what pace, whether it ends on the planned finish). The TSPI band is Lipke's: up to 1.00 the date
holds, up to 1.10 it can be caught up, above it rarely is (the TSPI help of the page cites it).
"""

import pytest

from xerscope.analysis.explain import schedule_reading

pytestmark = pytest.mark.oracle("standard")


def test_a_late_project_slowing_down_that_cannot_hold_its_date():
    text = schedule_reading(-26, "20 Oct 2026", 0.80, 0.93, "15 Oct 2027", "20 Aug 2027", "30 Jun 2027", 1.12)
    assert text == (
        "26 calendar days behind the plan: the work done was planned for 20 Oct 2026. "
        "Pace over the last 4 weeks 0.80, slower than since the first update (0.93). "
        "The plan ends at the recent pace on 15 Oct 2027 and at the overall pace on 20 Aug 2027. "
        "Ending on the planned finish (30 Jun 2027) needs a pace of 1.12: it is rarely caught up (Lipke)."
    )


@pytest.mark.parametrize(
    ("tspi", "verdict"),
    [(0.95, "the date holds"), (1.00, "the date holds"), (1.10, "it can be caught up"), (1.11, "rarely caught up")],
)
def test_the_tspi_band_is_lipke_s(tspi, verdict):
    assert verdict in schedule_reading(None, "", None, None, "", "", "30 Jun 2027", tspi)


def test_ahead_on_plan_and_done():
    assert schedule_reading(3, "18 Nov 2026", None, None, "", "", "", None).startswith("3 calendar days ahead of")
    assert schedule_reading(0.2, "15 Nov 2026", None, None, "", "", "", None).startswith("On plan")
    assert schedule_reading(None, "", None, None, "", "", "", None) == "Every planned hour is earned."


def test_a_missing_figure_leaves_its_sentence_out():
    """No window yet (fewer than 28 days of updates): no pace sentence, the overall forecast alone; no TSPI
    once the planned finish is passed."""
    text = schedule_reading(-5, "10 Nov 2026", None, 0.9, "", "20 Aug 2027", "30 Jun 2027", None)
    assert "Pace" not in text and "needs a pace" not in text
    assert "The plan ends at the overall pace on 20 Aug 2027." in text
