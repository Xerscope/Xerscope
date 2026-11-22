"""Tasks Anticipated and Tasks Made Ready, checked by hand on tiny weekly XER.

Hamzeh, Ballard & Tommelein (2012), "Rethinking Lookahead Planning to Optimize Construction Workflow",
Lean Construction Journal, figure 5: TA = tasks of the weekly work plan anticipated on the lookahead
plan / tasks of the weekly work plan (14/18 = 78 %); TMR(i, 0) = tasks of the lookahead plan i weeks
ahead done at the end of the week / tasks of that lookahead plan (11/20 = 55 %); PPC = done / weekly
work plan (13/18 = 72 %). Here a commitment (Start or Finish) is the unit, as for xerscope's PPC.

Four Monday 08:00 updates: U0 02-09, U1 02-16, U2 02-23 (W-1, the weekly work plan) and U3 03-02 (W).
The week is 02-23 08:00 to 03-02 08:00. Every finish is planned after 03-02: only starts commit.
"""

from __future__ import annotations

import pandas as pd
import pytest
from xerkit import active, snap, todo

from xerscope.analysis.progress import lookahead_of_week, lookahead_series, planned_for_week
from xerscope.store import SnapshotStore

pytestmark = pytest.mark.oracle("standard")

MONDAYS = ["2026-02-09 08:00", "2026-02-16 08:00", "2026-02-23 08:00", "2026-03-02 08:00"]
LATER = "2026-03-20 17:00"


def planned(code: str, start: str) -> dict:
    return todo(code, early_start_date=start, early_end_date=LATER)


def started(code: str, start: str) -> dict:
    return active(code, act_start_date=start, early_end_date=LATER)


def series() -> SnapshotStore:
    """U0 plans A 02-24, B 02-25, D 02-26 in the week, C 03-10 after it; G 02-20, before the week,
    everywhere. U1 pushes B to 03-16 and pulls C to 02-27. U2, the weekly work plan, adds E 02-27 and
    F 02-26. U3: A and C started on their day, D and E not started, F gone, B and G not started."""
    g = planned("G", "2026-02-20 08:00")
    a, d = planned("A", "2026-02-24 08:00"), planned("D", "2026-02-26 08:00")
    b_pushed, c_pulled = planned("B", "2026-03-16 08:00"), planned("C", "2026-02-27 08:00")
    u0 = snap([g, a, planned("B", "2026-02-25 08:00"), planned("C", "2026-03-10 08:00"), d], data_date=MONDAYS[0])
    u1 = snap([g, a, b_pushed, c_pulled, d], data_date=MONDAYS[1])
    e, f = planned("E", "2026-02-27 08:00"), planned("F", "2026-02-26 08:00")
    u2 = snap([g, a, b_pushed, c_pulled, d, e, f], data_date=MONDAYS[2])
    u3 = snap(
        [
            g,
            started("A", "2026-02-24 08:00"),
            b_pushed,
            started("C", "2026-02-27 08:00"),
            planned("D", "2026-03-04 08:00"),
            planned("E", "2026-03-05 08:00"),
        ],
        data_date=MONDAYS[3],
    )
    return SnapshotStore([u0, u1, u2, u3])


def test_the_week_only_anticipated_and_made_ready_at_one_and_two_updates():
    """Week to U3 without overdue dates. Weekly work plan (U2, in U3): A, C, D, E starts; F is gone,
    out of the count; G is before the week. Kept: A, C: PPC 2/4 = 50 %.
    One update before (U1): A, C, D planned in the week. TA(1) = {A, C, D} / 4 = 75 %; TMR(1) = A and
    C kept of 3 = 66.7 %. Two before (U0): A, B, D. TA(2) = {A, D} / 4 = 50 %; TMR(2) = A of 3 = 33.3 %
    (B, moved out of the week since, counts as not made ready)."""
    rows = lookahead_of_week(lookahead_series(series(), include_overdue=False), 3)
    assert rows["horizon"].tolist() == [1, 2]
    assert rows["lookahead_date"].tolist() == [pd.Timestamp(MONDAYS[1]), pd.Timestamp(MONDAYS[0])]
    assert rows["wwp"].tolist() == [4, 4] and rows["ppc_week"].tolist() == [50.0, 50.0]
    assert rows["anticipated"].tolist() == [3, 2] and rows["ta_pct"].tolist() == [75.0, 50.0]
    assert rows["lookahead"].tolist() == [3, 3] and rows["lookahead_kept"].tolist() == [2, 1]
    assert rows["tmr_pct"].tolist() == pytest.approx([200 / 3, 100 / 3])


def test_overdue_dates_join_the_weekly_work_plan_and_the_lookahead_when_asked():
    """With overdue dates (the default of the PPC), G, planned 02-20 and still not started, is in the
    weekly work plan and in every earlier plan: plan 5, kept 2, PPC 40 %; U1 holds A, C, D, G: TA(1) =
    4/5 = 80 %, TMR(1) = 2/4 = 50 %; U0 holds A, B, D, G: TA(2) = 3/5 = 60 %, TMR(2) = 1/4 = 25 %."""
    rows = lookahead_of_week(lookahead_series(series()), 3)
    assert rows["wwp"].tolist() == [5, 5] and rows["ppc_week"].tolist() == [40.0, 40.0]
    assert rows["ta_pct"].tolist() == [80.0, 60.0] and rows["tmr_pct"].tolist() == [50.0, 25.0]


def test_a_horizon_the_series_does_not_reach_has_no_row():
    """Four updates: the week to U1 has no earlier plan, the week to U2 has one (U0), the week to U3
    two. Horizons 4 and 8 are never reached."""
    table = lookahead_series(series())
    assert list(zip(table["snapshot_idx"], table["horizon"], strict=True)) == [(2, 1), (3, 1), (3, 2)]
    assert lookahead_of_week(table, 1).empty


def test_the_plan_of_an_earlier_update_for_the_week_is_its_commitments_due_by_w():
    """At horizon 0 the plan is the weekly work plan itself: `committed` (W-1, W). At horizon 2,
    U0's A, B, D (and G with overdue dates), their outcome read in U3."""
    store = series()
    assert planned_for_week(store, 3, 0, False)["task_code"].tolist() == ["A", "C", "D", "E", "F"]
    two_before = planned_for_week(store, 3, 2, False)
    assert two_before["task_code"].tolist() == ["A", "B", "D"] and two_before["kept"].tolist() == [True, False, False]
    assert sorted(planned_for_week(store, 3, 2, True)["task_code"]) == ["A", "B", "D", "G"]
