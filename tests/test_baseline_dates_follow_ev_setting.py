"""Which dates of a separate baseline are its "BL Project Start / Finish".

Source, read before the code: Nasui and Winter, "When is a Baseline Not a Baseline? Problems and Solutions
of Using the P6 Baseline Function" (2020, P6 Professional 17.12): "When a project or primary baseline is
assigned by the user, the dates of the baselines are determined by the EV calculation option", "Budgeted
values with planned dates" giving the baseline's planned dates and the two "current dates" options "the
start and finish dates of the assigned baselines' activities". P. Harris, "Oracle Primavera P6 Planned Date
Issues" (2022): "The Planned Dates from a Baseline schedule will be displayed as the Baseline Bars when the
[...] Earned Value tab is set to Budget values with planned dates." Oracle P6 EPPM help, "Updating
Baselines" (88388), ties the BL Project Start / Finish dates to the same setting and refers to Doc ID
893342.1, which was not read: no Oracle text states the rule in full, and no P6 26.8 reading has been made.
"""

import pandas as pd
import pytest
from xerkit import active, done, snap, todo

from xerscope.analysis.baseline import Baseline

pytestmark = pytest.mark.oracle("standard")

# The baseline project as it was when the baseline was taken. Each activity's planned dates differ from
# its current dates: A is complete, B in progress (planned dates frozen at its start), C not started
# (changed and not rescheduled).
BASELINE_TASKS = [
    done("A", target_start_date="2026-02-02 08:00", target_end_date="2026-02-06 17:00"),
    active(
        "B",
        target_start_date="2026-02-16 08:00",
        target_end_date="2026-02-27 17:00",
        restart_date="2026-03-02 08:00",
        reend_date="2026-03-13 17:00",
    ),
    todo(
        "C",
        target_start_date="2026-03-16 08:00",
        target_end_date="2026-03-20 17:00",
        restart_date="2026-03-23 08:00",
        reend_date="2026-03-27 17:00",
        early_start_date="2026-03-23 08:00",
        early_end_date="2026-03-27 17:00",
    ),
]
PLANNED = {
    "A": ("2026-02-02 08:00", "2026-02-06 17:00"),
    "B": ("2026-02-16 08:00", "2026-02-27 17:00"),
    "C": ("2026-03-16 08:00", "2026-03-20 17:00"),
}
CURRENT = {  # actual, else remaining early (Oracle, "Dates Columns of the Activity Table": Start, Finish)
    "A": ("2026-02-02 08:00", "2026-02-13 17:00"),
    "B": ("2026-02-23 08:00", "2026-03-13 17:00"),
    "C": ("2026-03-23 08:00", "2026-03-27 17:00"),
}


def _baseline_dates(ev_basis: str) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    frame = Baseline.from_snapshot(snap(BASELINE_TASKS), ev_basis).frame
    return {code: (row.bl_start, row.bl_finish) for code, row in frame.iterrows()}


def _timestamps(dates: dict[str, tuple[str, str]]) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    return {code: (pd.Timestamp(start), pd.Timestamp(finish)) for code, (start, finish) in dates.items()}


def test_with_planned_dates_the_baseline_dates_are_the_planned_dates_of_the_baseline():
    assert _baseline_dates("budgeted_planned") == _timestamps(PLANNED)


@pytest.mark.parametrize("ev_basis", ["budgeted_current", "at_completion_current"])
def test_with_current_dates_the_baseline_dates_are_the_start_and_finish_of_the_baseline(ev_basis):
    assert _baseline_dates(ev_basis) == _timestamps(CURRENT)


def test_a_baseline_activity_without_planned_dates_keeps_its_current_dates():
    """Some exporters write no planned date: the activity keeps a baseline date instead of losing it
    (xerscope's choice, no source)."""
    frame = Baseline.from_snapshot(snap([done("A")]), "budgeted_planned").frame
    assert (frame.loc["A", "bl_start"], frame.loc["A", "bl_finish"]) == _timestamps(CURRENT)["A"]


def test_the_planned_dates_of_an_update_that_is_its_own_baseline_do_not_follow_the_setting():
    """No baseline assigned: the baseline dates are the update's planned dates whatever the setting (Nasui
    and Winter: "When no baseline is assigned by the user, the baseline start and finish dates reflect the
    planned start and planned finish dates"; report R1 of docs/standards.md)."""
    for ev_basis in ("budgeted_planned", "budgeted_current", "at_completion_current"):
        frame = Baseline.planned(snap(BASELINE_TASKS), ev_basis).frame
        got = {code: (row.bl_start, row.bl_finish) for code, row in frame.iterrows()}
        assert got == _timestamps(PLANNED)
