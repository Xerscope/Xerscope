"""WBS earned value technique: exact code mapping, unknown codes, populations that do not move."""

import math

import pytest
from xerkit import active, done, snap, todo

from xerscope.analysis import Baseline
from xerscope.analysis.evm import earned, ev_point, ev_technique

DATES = {"early_start_date": "2026-03-02 08:00", "early_end_date": "2026-03-13 17:00", "target_work_qty": "80"}


@pytest.mark.parametrize(
    "code,technique",
    [
        ("EC_Cmp_pct", "activity"),
        ("EC_0_100", "0/100"),
        ("EC_50_50", "50/50"),
        ("EC_User_pct", "custom"),
        ("EC_WBS_pct", "wbs_milestones"),
        ("  EC_0_100 ", "0/100"),
        ("", "activity"),
        ("   ", "activity"),
        (None, "activity"),
        (math.nan, "activity"),
        ("EC_Rsrc_crv", "unknown"),
        ("EC_100", "unknown"),
        ("EC_0_100_x", "unknown"),
        ("X50", "unknown"),
        ("ec_0_100", "unknown"),
    ],
)
def test_ev_technique_maps_the_exact_code(code, technique):
    assert ev_technique(code) == technique


def _wbs(code):
    return [
        {
            "wbs_id": "W1",
            "proj_id": "1",
            "wbs_short_name": "W1",
            "wbs_name": "W1",
            "proj_node_flag": "N",
            "parent_wbs_id": "",
            "seq_num": "1",
            "ev_compute_type": code,
            "ev_user_pct": "30",
        }
    ]


def _baseline():
    return Baseline.from_snapshot(snap([todo("A", **DATES), todo("GONE", **DATES)]))


def _update(code):
    """A is 25 % physically complete; X is not in the baseline; GONE was deleted since the baseline."""
    a = active("A", wbs_id="W1", phys_complete_pct="25", complete_pct_type="CP_Phys", **DATES)
    x = active("X", wbs_id="W1", target_work_qty="40", act_work_qty="10", remain_work_qty="40")
    return snap([a, x], wbs=_wbs(code), data_date="2026-03-04 08:00")


@pytest.mark.parametrize("code", ["EC_Rsrc_crv", "EC_100", "EC_0_100_x", "X50", "ec_0_100"])
def test_unknown_code_earns_like_activity_and_is_listed_as_not_modelled(code):
    baseline = _baseline()
    unknown = earned(_update(code), baseline).loc["A"]
    activity = earned(_update("EC_Cmp_pct"), baseline).loc["A"]
    assert unknown["perf_pct"] == activity["perf_pct"] == 25
    assert unknown["ev_hr"] == pytest.approx(activity["ev_hr"]) == pytest.approx(20)
    assert "A" in ev_point(_update(code), baseline).not_modelled


@pytest.mark.parametrize("code", ["EC_Rsrc_crv", "EC_100", "EC_0_100_x", "X50", "ec_0_100"])
def test_unknown_code_moves_no_population(code):
    baseline = _baseline()
    unknown = ev_point(_update(code), baseline)
    reference = ev_point(_update("EC_Cmp_pct"), baseline)
    for field in ("bac_hr", "pv_hr", "ev_hr", "ac_hr", "etc_hr", "eac_hr", "ac_unbaselined_hr", "pv_deleted_hr"):
        assert getattr(unknown, field) == pytest.approx(getattr(reference, field)), field
    assert unknown.unbaselined == reference.unbaselined == ["X"]
    assert unknown.deleted == reference.deleted == ["GONE"]
    assert reference.not_modelled == []
    assert unknown.not_modelled == ["A"]


@pytest.mark.parametrize(
    "code,state,pct",
    [
        ("EC_Cmp_pct", "active", 25),
        ("EC_0_100", "active", 0),
        ("EC_0_100", "done", 100),
        ("EC_50_50", "active", 50),
        ("EC_50_50", "todo", 0),
        ("EC_User_pct", "active", 30),
    ],
)
def test_known_codes_keep_their_results(code, state, pct):
    a = {"active": active, "done": done, "todo": todo}[state](
        "A", wbs_id="W1", target_work_qty="80", phys_complete_pct="25", complete_pct_type="CP_Phys"
    )
    baseline = Baseline.from_snapshot(snap([todo("A", **DATES)]))
    row = earned(snap([a], wbs=_wbs(code)), baseline).loc["A"]
    assert row["perf_pct"] == pct and row["ev_hr"] == pytest.approx(80 * pct / 100)
    assert ev_point(snap([a], wbs=_wbs(code)), baseline).not_modelled == []
