"""Schedule risk analysis: every expected number below is computed by hand in the test."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from xerkit import FM, hours, snap, todo

from xerscope.analysis import cpm
from xerscope.analysis.sra import read_ranges, simulate
from xerscope.xer.calendar import TimeAxis


def _two_parallel_tasks():
    """A and B, 80 h each on the Mon-Fri 8 h calendar, both FS into the finish milestone M."""
    return snap([todo("A"), todo("B"), todo("M", **FM)], [("A", "M", "FS", 0), ("B", "M", "FS", 0)])


def test_without_ranges_every_iteration_is_the_plain_recalculation():
    snapshot = _two_parallel_tasks()
    result = simulate(snapshot, iterations=5, seed=1)
    plain = cpm.schedule(snapshot)
    assert (result.finishes == plain.finish).all()
    assert result.deterministic_confidence == 1.0
    assert result.criticality.to_dict() == plain.frame["longest_path"].astype(float).to_dict()


def test_merging_paths_push_the_median_finish_past_the_most_likely_one():
    """Merge bias, by hand. Each task lasts T(0, 40, 80) hours (factors 0 / 0.5 / 1 of 80 h).
    One task: P(d <= x) = 1 - (80 - x)^2 / 3200 above 40 h. M waits for the longer of two
    independent draws: P(max <= x) = P(d <= x)^2. Its median solves P(d <= x) = sqrt(0.5):
    x = 80 - sqrt(3200 (1 - sqrt(0.5))) = 49.38 h, where the most likely durations give 40 h.
    The finish meets 40 h only when both draws do: 0.5^2 = 25 %."""
    snapshot = _two_parallel_tasks()
    ranges = {"A": (0.0, 0.5, 1.0), "B": (0.0, 0.5, 1.0)}
    result = simulate(snapshot, ranges, iterations=1000, seed=7)
    axis = TimeAxis(snapshot.calendar(), snapshot.data_date.date(), (snapshot.data_date + pd.Timedelta(days=60)).date())
    finish_hours = result.finishes.map(lambda finish: axis.between(snapshot.data_date, finish) / 60)
    expected_median = 80 - math.sqrt(3200 * (1 - math.sqrt(0.5)))
    assert abs(finish_hours.median() - expected_median) < 2.0  # standard error of the median ~0.6 h at 1,000 draws
    assert abs((finish_hours <= 40).mean() - 0.25) < 0.04
    assert result.criticality["M"] == 1.0
    assert abs(result.criticality["A"] - 0.5) < 0.05  # each task is the longer one half of the time


CREW_7D = {"rsrc_id": "R7", "rsrc_short_name": "CREW", "rsrc_type": "RT_Labor", "clndr_id": "C7D"}
FITTER_5D = {"rsrc_id": "R8", "rsrc_short_name": "FITTER", "rsrc_type": "RT_Labor", "clndr_id": "C8"}


def _driving(code, rsrc, units):
    """A driving, unstarted assignment at 1 unit per hour: ``units`` hours of work."""
    return {
        "task_code": code,
        "rsrc_id": rsrc,
        "target_qty": str(units),
        "remain_qty": str(units),
        "target_qty_per_hr": "1",
        "remain_qty_per_hr": "1",
        "rollup_dates_flag": "Y",
    }


def test_scale_multiplies_a_task_dependent_duration():
    """A, 80 h on Mon-Fri 08-12 / 13-17 from Mon 2 March 08:00: x0.5 = 40 h ends Fri 6 March
    17:00; x2 = 160 h = 20 working days ends Fri 27 March 17:00."""
    snapshot = snap([todo("A")])
    assert cpm.schedule(snapshot, scale={"A": 0.5}).frame.at["A", "ef"] == pd.Timestamp("2026-03-06 17:00")
    assert cpm.schedule(snapshot, scale={"A": 2.0}).frame.at["A", "ef"] == pd.Timestamp("2026-03-27 17:00")
    with pytest.raises(ValueError, match="must not be negative"):
        cpm.schedule(snapshot, scale={"A": -0.1})


def test_scale_multiplies_each_driving_assignment_of_resource_dependent_work():
    """A resource dependent, two driving assignments from Mon 2 March 08:00: a crew working every
    day 08-16 (40 h) and a fitter on Mon-Fri 08-12 / 13-17 (16 h). x0.5 halves each one: the crew's
    20 h end Wed 4 March 12:00 (8 + 8 + 4), the fitter's 8 h end Mon 2 March 17:00, and A ends
    with the crew. Taking 20 h off each assignment instead would leave the fitter at -4 h."""
    snapshot = snap(
        [todo("A", task_type="TT_Rsrc", **hours(40))],
        resources=[CREW_7D, FITTER_5D],
        assign=[_driving("A", "R7", 40), _driving("A", "R8", 16)],
    )
    plain = cpm.schedule(snapshot)
    assert plain.frame.at["A", "resource_dependent"]
    assert plain.frame.at["A", "ef"] == pd.Timestamp("2026-03-06 16:00")  # 40 h of crew, 5 days
    halved = cpm.schedule(snapshot, scale={"A": 0.5})
    assert halved.frame.at["A", "ef"] == pd.Timestamp("2026-03-04 12:00")
    ends = halved.assignments.set_index("rsrc")["reend"]
    assert ends["CREW"] == pd.Timestamp("2026-03-04 12:00")
    assert ends["FITTER"] == pd.Timestamp("2026-03-02 17:00")


def test_resource_dependent_work_is_drawn_too():
    snapshot = snap(
        [todo("A", task_type="TT_Rsrc", **hours(40)), todo("M", **FM)],
        [("A", "M", "FS", 0)],
        resources=[CREW_7D],
        assign=[_driving("A", "R7", 40)],
    )
    result = simulate(snapshot, {"A": (2.0, 2.0, 2.0)}, iterations=1)
    assert result.varied == ["A"]
    assert result.finishes.iloc[0] == pd.Timestamp("2026-03-11 16:00")  # 80 h of crew: 10 days of 8 h


def test_a_draw_never_goes_below_zero_duration():
    snapshot = _two_parallel_tasks()
    result = simulate(snapshot, {"A": (0.0, 0.0, 0.0), "B": (0.0, 0.0, 0.0)}, iterations=1, seed=0)
    assert result.finishes.iloc[0] == snapshot.data_date  # both tasks last 0 h: M finishes at the data date


@pytest.mark.parametrize(
    "ranges,error",
    [
        ({"A": (1.2, 1.0, 1.5)}, "0 <= minimum <= most likely <= maximum"),
        ({"A": (-0.1, 1.0, 1.5)}, "0 <= minimum <= most likely <= maximum"),
        ({"Z": (0.9, 1.0, 1.2)}, "does not have: ['Z']"),
    ],
)
def test_ranges_are_checked_at_the_boundary(ranges, error):
    with pytest.raises(ValueError, match=error.replace("[", r"\[").replace("]", r"\]")):
        simulate(_two_parallel_tasks(), ranges, iterations=1)


def test_ranges_file(tmp_path):
    path = tmp_path / "ranges.csv"
    path.write_text("task_code,min,most_likely,max\nA,0.9,1.0,1.3\n", encoding="utf-8")
    assert read_ranges(path) == {"A": (0.9, 1.0, 1.3)}
    path.write_text("task_code,low,max\nA,0.9,1.3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing column"):
        read_ranges(path)


def test_same_seed_same_result():
    snapshot = _two_parallel_tasks()
    ranges = {"A": (0.5, 1.0, 2.0)}
    first = simulate(snapshot, ranges, iterations=20, seed=3)
    again = simulate(snapshot, ranges, iterations=20, seed=3)
    assert first.finishes.equals(again.finishes)
