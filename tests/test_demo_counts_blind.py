"""Pins four counts on the generated PRJ-ALPHA demo series (8 weekly updates).

Expected values counted from the generated demo files, independently of the checks.
"""

import pytest
from rulekit import codes, counts, run_on_store

from xerscope.analysis import Baseline, builtin_standards
from xerscope.analysis.evm import bei_series

pytestmark = pytest.mark.oracle("standard")


def test_p6_bei_series(store):
    """BEI = completed tasks / tasks, milestones, LOE and WBS excluded.

    Completed codes per update: 0 none; 1 C3010; 2 C3010; 3 C3010 E1010;
    4 C3010 E1010 P2010; 5 + E1040; 6 + P2020; 7 + E1020.
    Denominator: 24 tasks for updates 0-3, 25 from update 4 (one task added).
    """
    std = builtin_standards()
    bei = {k: next(m for m in std[k].metrics if m.name == "BEI") for k in ("P6", "DCMA")}
    out = bei_series(store, bei, Baseline.planned)
    expected = [0 / 24, 1 / 24, 1 / 24, 2 / 24, 3 / 25, 4 / 25, 5 / 25, 6 / 25]
    assert out["bei_p6"].tolist() == pytest.approx(expected)


def test_dcma_07_negative_float(store):
    """Incomplete tasks (LOE, milestones excluded) with total float below 0.

    Update 4: 0 of 22, none flagged. Update 5: 5 of 21, flagged P2020 P2030
    P2040 X4010 X4020 (P2030 remaining duration 480 h -> 560 h pushes the chain
    P2030 > P2040 > X4010 > X4020 > X4050, which is held by a finish-on-or-before
    constraint; X4050 is a milestone and is not counted).
    """
    r4 = run_on_store(store, 4, "DCMA-07")
    assert counts(r4) == (0, 22)
    assert codes(r4) == []
    r5 = run_on_store(store, 5, "DCMA-07")
    assert counts(r5) == (5, 21)
    assert codes(r5) == ["P2020", "P2030", "P2040", "X4010", "X4020"]


def test_dcma_01_logic_update_0(store):
    """Incomplete tasks missing a predecessor and/or a successor.

    Update 0: 1 of 24; flagged K5040 (has a predecessor, no successor).
    """
    r = run_on_store(store, 0, "DCMA-01")
    assert counts(r) == (1, 24)
    assert codes(r) == ["K5040"]


def test_dcma_08_high_duration_update_0(store):
    """Incomplete tasks whose baseline duration exceeds 44 working days.

    Update 0, 8 h days: P2030 = 480 h = 60 days. Next longest is 30 days
    (P2050, X4020, X4030). 1 of 24, flagged P2030.
    """
    r = run_on_store(store, 0, "DCMA-08")
    assert counts(r) == (1, 24)
    assert codes(r) == ["P2030"]
