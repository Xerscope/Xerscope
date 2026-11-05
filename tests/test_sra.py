"""Schedule risk analysis: every expected number below is computed by hand in the test."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from xerkit import FM, snap, todo

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
    hours = result.finishes.map(lambda finish: axis.between(snapshot.data_date, finish) / 60)
    expected_median = 80 - math.sqrt(3200 * (1 - math.sqrt(0.5)))
    assert abs(hours.median() - expected_median) < 2.0  # standard error of the median ~0.6 h at 1,000 draws
    assert abs((hours <= 40).mean() - 0.25) < 0.04
    assert result.criticality["M"] == 1.0
    assert abs(result.criticality["A"] - 0.5) < 0.05  # each task is the longer one half of the time


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
