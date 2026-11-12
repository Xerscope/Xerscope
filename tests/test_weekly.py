"""Changelog, earned value, PPC, progress delta, WBS roll-ups, MTA: hand-checked numbers."""

import pandas as pd
import pytest
from xerkit import FM, SM, active, done, snap, todo

from xerscope.analysis import Baseline
from xerscope.analysis.changelog import changelog, summary
from xerscope.analysis.evm import (
    earned,
    etc_settings,
    etc_technique,
    etc_technique_counts,
    ev_point,
    ev_technique,
    evm_series,
    forecast_curve,
    pv_curve,
    pv_labor_check,
    schedule_pct,
    uses_pf,
)
from xerscope.analysis.progress import (
    VARIANCE_COLUMNS,
    committed,
    date_variances,
    milestone_codes,
    milestone_slips,
    milestone_trend,
    plotted_trend,
    ppc_series,
    progress_delta,
    renumbered,
    rollup_delta,
)
from xerscope.analysis.wbs import ROOT, rollup, subtree_ids
from xerscope.store import SnapshotStore

# --- changelog -------------------------------------------------------------------------------

OLD = snap(
    [
        todo("A", early_end_date="2026-03-13 17:00"),
        todo("B", target_drtn_hr_cnt="80"),
        active("C"),
        todo("D"),
        todo("GONE"),
    ],
    [("A", "B", "FS", 0), ("B", "D", "FS", 0), ("C", "D", "SS", 8), ("GONE", "D", "FS", 0)],
)
NEW = snap(
    [
        todo("A", early_end_date="2026-03-16 17:00", task_name="A renamed"),
        todo("B", target_drtn_hr_cnt="120"),
        active("C", act_start_date="2026-02-24 08:00", cstr_type="CS_MSOA", cstr_date="2026-03-02 08:00"),
        todo("D"),
        todo("NEW"),
    ],
    [("A", "B", "FS", 0), ("B", "D", "SS", 0), ("C", "D", "SS", 16), ("NEW", "D", "FS", 0)],
    data_date="2026-03-09 08:00",
)


def by(log, change, category=None):
    hit = log["change"] == change
    return log[hit & (log["category"] == category)] if category else log[hit]


def test_changelog_finds_each_kind_of_change():
    log = changelog(OLD, NEW)
    assert by(log, "added", "Scope")["task_code"].tolist() == ["NEW"]
    assert by(log, "deleted", "Scope")["task_code"].tolist() == ["GONE"]
    assert by(log, "renamed").iloc[0][["before", "after"]].tolist() == ["A", "A renamed"]
    dur = by(log, "original duration changed").iloc[0]
    assert (dur["task_code"], dur["delta"]) == ("B", 5)  # 80 h -> 120 h on 8 h days
    fin = log[(log["change"] == "finish moved") & (log["task_code"] == "A")].iloc[0]
    assert fin["delta"] == -1  # Fri 13 -> Mon 16 = one working day later (lost), not three calendar days
    retro = by(log, "actual start changed (retroactive)").iloc[0]
    assert (retro["task_code"], retro["before"], retro["after"]) == ("C", "2026-02-23 08:00", "2026-02-24 08:00")
    assert by(log, "primary constraint added").iloc[0]["after"] == "CS_MSOA 2026-03-02 08:00"


def test_changelog_relationships():
    log = changelog(OLD, NEW)
    rel = log[log["category"] == "Relationships"].set_index("field")["change"].to_dict()
    assert rel == {"NEW → D": "added", "GONE → D": "deleted", "B → D": "type changed", "C → D": "lag changed"}


def test_changelog_project_rows_and_summary():
    log = changelog(OLD, NEW)
    proj = log[log["category"] == "Project"].set_index("change")
    assert proj.loc["status date", "delta"] == 5
    s = summary(log)
    assert "Project" not in set(s["category"])
    assert s["count"].sum() == len(log) - 4


def test_identical_files_have_no_changes():
    assert summary(changelog(OLD, OLD)).empty


# --- earned value --------------------------------------------------------------------------------


def _bl(**a):
    return Baseline.from_snapshot(snap([todo("A", target_work_qty="80", **a)]))


def _pv_at(baseline, when):
    """Cumulative PV at an instant, read off an update whose data date is that instant."""
    return ev_point(snap([todo("A")], data_date=when), baseline).pv_hr


def test_pv_spreads_over_working_days():
    bl = _bl(early_start_date="2026-03-02 08:00", early_end_date="2026-03-13 17:00")  # 10 working days
    curve = pv_curve(bl)
    assert curve["pv_cum_hr"].iloc[-1] == pytest.approx(80)
    assert curve.set_index("date").loc["2026-03-08", "pv_hr"] == 0  # Saturday (a row holds the day before it)
    assert _pv_at(bl, "2026-03-04 08:00") == pytest.approx(16)  # Mon + Tue
    assert _pv_at(bl, "2026-03-04 12:00") == pytest.approx(20)  # + half of Wed
    assert _pv_at(bl, "2026-03-04 12:30") == pytest.approx(20)  # lunch is not working time


def test_pv_is_schedule_pct_complete_in_working_time():
    """Oracle: PV labour units = BL labour units x Schedule % Complete; an activity starting
    at 13:00 has done 4 of its 12 working hours by the evening, not a third of a day."""
    bl = _bl(early_start_date="2026-03-02 13:00", early_end_date="2026-03-03 17:00", target_drtn_hr_cnt="12")
    assert _pv_at(bl, "2026-03-02 17:00") == pytest.approx(80 * 4 / 12)
    assert schedule_pct(bl, pd.Timestamp("2026-03-03 08:00")).loc["A"] == pytest.approx(100 / 3)
    assert pv_curve(bl).set_index("date").loc["2026-03-03", "pv_hr"] == pytest.approx(80 / 3)  # 03-02 by midnight


def test_per_activity_pv_sums_to_the_headline_pv():
    """A third of 80 h: a Schedule % rounded to 33.33 would give 26.664 h, not 26.667 h."""
    bl = _bl(early_start_date="2026-03-02 13:00", early_end_date="2026-03-03 17:00", target_drtn_hr_cnt="12")
    now = snap([todo("A")], data_date="2026-03-02 17:00")
    assert earned(now, bl)["pv_hr"].sum() == pytest.approx(ev_point(now, bl).pv_hr, abs=1e-9)


def test_pv_skips_calendar_holiday():
    bl = _bl(early_start_date="2026-03-30 08:00", early_end_date="2026-04-03 17:00")  # Mon-Fri, Fri = Good Friday
    curve = pv_curve(bl).set_index("date")
    assert curve.loc["2026-04-04", "pv_hr"] == 0  # the hours of 04-03, at its midnight
    assert curve.loc["2026-03-31", "pv_hr"] == pytest.approx(20)  # 80 h over 4 working days


def test_ev_spi_and_unbaselined():
    bl = _bl(early_start_date="2026-03-02 08:00", early_end_date="2026-03-13 17:00")
    now = snap(
        [
            active(
                "A",
                phys_complete_pct="25",
                complete_pct_type="CP_Phys",
                target_work_qty="80",
                act_work_qty="30",
                remain_work_qty="60",
            ),
            active("X", target_work_qty="40", act_work_qty="10", remain_work_qty="40"),  # not in the baseline
        ],
        data_date="2026-03-04 08:00",
    )
    p = ev_point(now, bl)
    assert (p.pv_hr, p.ev_hr, p.ac_hr, p.etc_hr) == (16, 20, 40, 100)  # AC and ETC cover the whole scope
    assert p.eac_hr == 140
    assert p.spi == pytest.approx(1.25)
    assert p.productivity == pytest.approx(20 / 30)  # EV per hour spent on baselined work: X's 10 h left out
    assert p.ac_unbaselined_hr == 10
    assert p.unbaselined == ["X"]


def test_activities_deleted_since_the_baseline_are_left_out_of_bac_pv_and_ev():
    """P6 totals its earned value fields over the activities of the current project ("adding the
    values for each activity in the summary", P6 Professional 25, How data is summarized): a baseline
    activity deleted from the update has no row there, so no BAC, PV or EV.
    Baseline: A and GONE, 80 h and an expense of 300 each, 2026-03-02 08:00 -> 03-13 17:00 (10 working
    days). Update at 2026-03-04 08:00 (2 working days elapsed) holds A only: BAC 80 h, PV 80 x 2/10 = 16 h,
    BAC cost 300, PV cost 300 x 2/10 = 60; the 16 h GONE would add are reported apart."""
    dates = {"early_start_date": "2026-03-02 08:00", "early_end_date": "2026-03-13 17:00", "target_work_qty": "80"}
    bl = Baseline.from_snapshot(
        snap(
            [todo("A", **dates), todo("GONE", **dates)],
            costs=[{"task_code": "A", "target_cost": "300"}, {"task_code": "GONE", "target_cost": "300"}],
        )
    )
    now = snap([todo("A")], data_date="2026-03-04 08:00")
    p = ev_point(now, bl)
    assert (p.bac_hr, p.pv_hr, p.ev_hr) == pytest.approx((80, 16, 0))
    assert (p.bac_cost, p.pv_cost) == pytest.approx((300, 60))
    assert p.deleted == ["GONE"] and p.pv_deleted_hr == pytest.approx(16)
    table = earned(now, bl)
    assert not table.loc["GONE", "in_snapshot"] and table.loc["GONE", "pv_hr"] == pytest.approx(16)  # listed
    totals, _ = pv_labor_check(now, bl)
    assert (totals.loc[0, "bac_activity_hr"], totals.loc[0, "pv_activity_hr"]) == pytest.approx((80, 16))


def test_ev_uses_the_unrounded_percent_complete():
    """Oracle, Earned Value Columns of the Activity Table: EV labour units = BL labour units x
    Performance % Complete; Percent Complete Columns: Duration % Complete = (planned - remaining)
    / planned x 100. Neither rounds. 30 h planned, 20 h remaining is 1/3: on 30,000 BL hours EV is
    10,000 h, where 33.33 % gave 9,999 h."""
    bl = Baseline.from_snapshot(snap([todo("A", target_work_qty="30000")]))
    now = snap(
        [active("A", target_drtn_hr_cnt="30", remain_drtn_hr_cnt="20", target_work_qty="30000")],
        data_date="2026-03-04 08:00",
    )
    assert ev_point(now, bl).ev_hr == pytest.approx(10000, rel=1e-12)


def test_cpi_divides_by_all_actual_hours_and_ev_per_ac_by_the_baselined_ones():
    """A (in the baseline) earns 20 h for 30 h spent; X (not in the baseline) spent 10 h more.
    P6's Cost Performance Index - Labor Units uses every actual hour: 20 / 40; EV / AC on
    baselined work leaves X out: 20 / 30. The denominators differ by exactly X's 10 h."""
    bl = _bl(early_start_date="2026-03-02 08:00", early_end_date="2026-03-13 17:00")
    now = snap(
        [
            active(
                "A",
                phys_complete_pct="25",
                complete_pct_type="CP_Phys",
                target_work_qty="80",
                act_work_qty="30",
                remain_work_qty="60",
            ),
            active("X", target_work_qty="40", act_work_qty="10", remain_work_qty="40"),
        ],
        data_date="2026-03-04 08:00",
    )
    p = ev_point(now, bl)
    assert (p.ev_hr, p.ac_hr, p.ac_unbaselined_hr) == (20, 40, 10)
    assert p.cpi == pytest.approx(20 / 40) and p.productivity == pytest.approx(20 / 30)
    assert 20 / p.cpi - 20 / p.productivity == pytest.approx(10)
    row = evm_series(SnapshotStore([now]), bl).iloc[0]
    assert row["cpi"] == pytest.approx(0.5) and row["productivity"] == pytest.approx(20 / 30)
    assert list(row.index[:14]) == [
        "data_date", "bac_hr", "pv_hr", "ev_hr", "ac_hr", "etc_hr", "eac_hr", "pv_pct", "ev_pct", "sv_hr",
        "spi", "productivity", "cpi", "unbaselined",
    ]  # fmt: skip


@pytest.mark.parametrize(
    "code,state,pct",
    [
        ("EC_Cmp_pct", "active", 25),
        ("", "active", 25),  # activity % complete (P6 default)
        ("EC_0_100", "active", 0),
        ("EC_0_100", "done", 100),  # 0 / 100
        ("EC_50_50", "active", 50),
        ("EC_50_50", "todo", 0),  # 50 / 50
        ("EC_User_pct", "active", 30),  # custom % once started
    ],
)
def test_performance_pct_follows_the_wbs_ev_technique(code, state, pct):
    wbs = [
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
    a = {"active": active, "done": done, "todo": todo}[state](
        "A", wbs_id="W1", target_work_qty="80", phys_complete_pct="25", complete_pct_type="CP_Phys"
    )
    bl = _bl(early_start_date="2026-03-02 08:00", early_end_date="2026-03-13 17:00")
    e = earned(snap([a], wbs=wbs), bl).loc["A"]
    assert e["perf_pct"] == pct and e["ev_hr"] == pytest.approx(80 * pct / 100)


def _wbs(code, etc, user_value="0.88"):
    return {
        "wbs_id": code,
        "proj_id": "1",
        "wbs_short_name": code,
        "wbs_name": code,
        "proj_node_flag": "N",
        "parent_wbs_id": "",
        "seq_num": "1",
        "ev_compute_type": "EC_Cmp_pct",
        "ev_etc_compute_type": etc,
        "ev_etc_user_value": user_value,
    }


def test_etc_settings_count_the_wbs_by_etc_technique():
    """W1 on remaining units with two activities, W2 on PF = 1 with one: one WBS of each, W2 alone uses a PF,
    and the ETC, EAC and EV do not move with the technique."""
    wbs = [_wbs("W1", "EE_Rem_hr"), _wbs("W2", "EE_PF_1", "1"), _wbs("W3", "EE_Rem_hr")]
    tasks = [
        todo("A", wbs_id="W1", target_work_qty="80", remain_work_qty="80"),
        todo("B", wbs_id="W1", target_work_qty="40", remain_work_qty="40"),
        active("C", wbs_id="W2", target_work_qty="60", remain_work_qty="30", act_work_qty="30"),
    ]
    s = snap(tasks, wbs=wbs)
    settings = etc_settings(s).set_index("wbs_code")
    assert settings["activities"].to_dict() == {"W1": 2, "W2": 1, "W3": 0}
    assert settings.loc["W2", "etc_technique"] == "PF = 1" and settings.loc["W2", "ev_etc_user_value"] == "1"
    counts = etc_technique_counts(etc_settings(s)).set_index("etc_technique")
    assert counts["wbs"].to_dict() == {"remaining units": 2, "PF = 1": 1}
    assert counts["activities"].to_dict() == {"remaining units": 2, "PF = 1": 1}
    assert settings.index[settings["ev_etc_compute_type"].map(uses_pf)].tolist() == ["W2"]
    plain = snap(tasks, wbs=[_wbs("W1", "EE_Rem_hr"), _wbs("W2", "EE_Rem_hr"), _wbs("W3", "EE_Rem_hr")])
    bl = _bl(early_start_date="2026-03-02 08:00", early_end_date="2026-03-13 17:00")
    for field in ("etc_hr", "eac_hr", "ev_hr", "pv_hr"):
        assert getattr(ev_point(s, bl), field) == getattr(ev_point(plain, bl), field)


def test_etc_technique_labels_known_codes_and_shows_the_others_as_stored():
    assert [etc_technique(c) for c in ["EE_Rem_hr", "EE_PF_1", "EE_PF_cpi", "EE_PF_cpi_spi", "", None]] == [
        "remaining units",
        "PF = 1",
        "PF = 1/CPI",
        "EE_PF_cpi_spi",
        "(blank)",
        "(blank)",
    ]
    assert [uses_pf(c) for c in ["EE_Rem_hr", "EE_PF_1", "EE_PF_cpi_spi", ""]] == [False, True, True, False]


def test_ev_technique_codes():
    assert [ev_technique(c) for c in ["EC_Cmp_pct", "EC_0_100", "EC_50_50", "EC_User_pct", "EC_WBS_pct", None]] == [
        "activity",
        "0/100",
        "50/50",
        "custom",
        "wbs_milestones",
        "activity",
    ]


def test_labour_hours_fall_back_to_assignments():
    s = snap([todo("A"), todo("B")], rsrc=["A"])  # TASK has no work quantities
    assert s.options["labor_source"] == "TASKRSRC"
    assert s.activities.set_index("task_code")["labor_budget_hr"].to_dict() == {"A": 80, "B": 0}


# --- PPC and progress --------------------------------------------------------------------------

W1 = snap(
    [
        todo("A", early_end_date="2026-03-05 17:00", target_work_qty="100"),
        todo("B", early_end_date="2026-03-06 17:00", target_work_qty="300"),
        todo("C", early_end_date="2026-03-20 17:00"),
        todo("DEL", early_end_date="2026-03-04 17:00"),
    ]
)
W2 = snap(
    [
        done(
            "A",
            act_end_date="2026-03-05 17:00",
            target_work_qty="100",
            phys_complete_pct="100",
            complete_pct_type="CP_Phys",
        ),
        active("B", target_work_qty="300", phys_complete_pct="50", complete_pct_type="CP_Phys"),
        todo("C"),
    ],
    data_date="2026-03-09 08:00",
)


def _commitments(c: pd.DataFrame) -> list[tuple[str, str]]:
    return sorted(zip(c["task_code"], c["commitment"], strict=True))


def test_ppc_counts_only_commitments_still_in_the_update():
    c = committed(W1, W2)
    # all four were not started and forecast to start on W1's data date; C finishes after W2's
    assert _commitments(c) == [
        ("A", "Finish"), ("A", "Start"), ("B", "Finish"), ("B", "Start"),
        ("C", "Start"), ("DEL", "Finish"), ("DEL", "Start"),
    ]  # fmt: skip
    finishes = c[c["in_update"] & (c["commitment"] == "Finish")]
    assert finishes["kept"].sum() / len(finishes) == 0.5


def test_ppc_commits_started_and_not_started_work():
    """W-1 in progress (E) and not started (N), both forecast to finish before W's data date:
    both finishes are committed, and N's start. E finished in W, N only started."""
    w1 = snap(
        [
            active("E", act_start_date="2026-03-02 08:00", early_end_date="2026-03-05 17:00"),
            todo("N", early_end_date="2026-03-06 17:00"),
        ]
    )
    w2 = snap(
        [done("E", act_end_date="2026-03-05 17:00"), active("N", act_start_date="2026-03-04 08:00")],
        data_date="2026-03-09 08:00",
    )
    c = committed(w1, w2).set_index(["task_code", "commitment"])
    assert sorted(c.index) == [("E", "Finish"), ("N", "Finish"), ("N", "Start")]
    assert (c.loc[("E", "Finish"), "kept"], c.loc[("N", "Finish"), "kept"]) == (True, False)
    assert c.loc[("N", "Start"), "kept"]
    assert c.loc[("N", "Start"), "actual_date"] == pd.Timestamp("2026-03-04 08:00")
    assert c.loc[("N", "Finish"), "status_now"] == "In progress"


def test_ppc_counts_starts_and_finishes_and_leaves_milestones_out():
    """Week 2026-03-02 -> 2026-03-09. W-1 commits:
    S1, S2 start only (finish after W); SF starts and finishes within the week (two commitments);
    E in progress, finish only; DEL start and finish, then deleted (scope change, not counted);
    LATE nothing (both dates after W). FM and SM are milestones: a milestone repeats its
    predecessor's date, so counting it would add a commitment the week the predecessor ends.
    W: S1 started, S2 slipped, SF started not finished, E finished, both milestones done.
    Finishes kept 1 / 2 (E, not SF): PPC 50 %; starts kept 2 / 3 (S1, SF, not S2): PPC Start
    66.7 %; all commitments 3 / 5 = 60 %."""
    w1 = snap(
        [
            todo("S1", early_start_date="2026-03-03 08:00", early_end_date="2026-03-20 17:00"),
            todo("S2", early_start_date="2026-03-04 08:00", early_end_date="2026-03-20 17:00"),
            todo("SF", early_start_date="2026-03-04 08:00", early_end_date="2026-03-06 17:00"),
            active("E", early_end_date="2026-03-05 17:00"),
            todo("DEL", early_start_date="2026-03-03 08:00", early_end_date="2026-03-05 17:00"),
            todo("LATE", early_start_date="2026-03-10 08:00", early_end_date="2026-03-12 17:00"),
            todo("FM", **FM, early_start_date="2026-03-05 17:00", early_end_date="2026-03-05 17:00"),
            todo("SM", **SM, early_start_date="2026-03-03 08:00", early_end_date="2026-03-03 08:00"),
        ]
    )
    w2 = snap(
        [
            active("S1", act_start_date="2026-03-03 08:00"),
            todo("S2", early_start_date="2026-03-10 08:00", early_end_date="2026-03-24 17:00"),
            active("SF", act_start_date="2026-03-04 08:00"),
            done("E", act_end_date="2026-03-05 17:00"),
            todo("LATE", early_start_date="2026-03-10 08:00", early_end_date="2026-03-12 17:00"),
            done("FM", **FM, act_start_date="2026-03-05 17:00", act_end_date="2026-03-05 17:00"),
            done("SM", **SM, act_start_date="2026-03-03 08:00", act_end_date="2026-03-03 08:00"),
        ],
        data_date="2026-03-09 08:00",
    )
    c = committed(w1, w2)
    assert _commitments(c) == [
        ("DEL", "Finish"), ("DEL", "Start"), ("E", "Finish"), ("S1", "Start"),
        ("S2", "Start"), ("SF", "Finish"), ("SF", "Start"),
    ]  # fmt: skip
    row = ppc_series(SnapshotStore([w1, w2])).iloc[0]
    assert (row["finishes_kept"], row["finishes_committed"]) == (1, 2)
    assert (row["starts_kept"], row["starts_committed"]) == (2, 3)
    assert (row["kept"], row["committed"], row["ppc_week"]) == (3, 5, 60.0)
    assert (row["ppc_finish"], row["ppc_start"]) == (50.0, pytest.approx(200 / 3))


def test_ppc_series_one_row_per_week():
    s = ppc_series(SnapshotStore([W1, W2]))
    assert len(s) == 1
    row = s.iloc[0]
    # W1 forecast A, B, DEL to finish and A, B, C, DEL to start before W2's data date; DEL is
    # gone (scope change, not a miss). Finishes: A done, B not: 1 / 2, PPC 50 %. Starts: A, B
    # started, C not: 2 / 3, PPC Start 66.7 %. All commitments (1 + 2) / (2 + 3) = 60 %
    assert (row["finishes_kept"], row["finishes_committed"], row["starts_kept"], row["starts_committed"]) == (
        1, 2, 2, 3,
    )  # fmt: skip
    assert (row["committed"], row["kept"], row["ppc_week"]) == (5, 3, 60.0)
    assert (row["ppc_finish"], row["ppc_start"]) == (50.0, pytest.approx(200 / 3))
    assert row["week_start"] == W1.data_date and row["data_date"] == W2.data_date


def test_ppc_notes_a_point_that_spans_a_missing_update():
    """Updates on 03-02, 03-09 and 03-23 (the 03-16 one missing): the second point holds two weeks
    of commitments and says so; the first, seven days, has no note. The counts are unchanged."""
    w1 = snap([todo("A", early_end_date="2026-03-20 17:00")], data_date="2026-03-02 08:00")
    w2 = snap([todo("A", early_end_date="2026-03-20 17:00")], data_date="2026-03-09 08:00")
    w4 = snap([done("A", act_end_date="2026-03-20 17:00")], data_date="2026-03-23 08:00")
    s = ppc_series(SnapshotStore([w1, w2, w4]))
    assert pd.isna(s["note"].iloc[0])
    assert s["note"].iloc[1] == "14 days since the previous update: this point covers more than one week"
    assert (s["finishes_kept"].iloc[1], s["finishes_committed"].iloc[1]) == (1, 1)


def test_ppc_point_without_a_status_date_commits_nothing_and_says_why():
    """The newer file has no data date (no last_recalc_date, no plan_start_date): nothing can
    be due before it, so the point has no commitment and a note instead of a TypeError."""
    w1 = snap([todo("A", early_end_date="2026-03-05 17:00")], data_date="2026-03-02 08:00")
    w2 = snap([todo("A", early_end_date="2026-03-05 17:00")], data_date="", project={"plan_start_date": ""})
    assert w2.data_date is None
    assert committed(w1, w2).empty
    row = ppc_series(SnapshotStore([w1, w2])).iloc[0]
    assert (row["finishes_committed"], row["starts_committed"], row["committed"]) == (0, 0, 0)
    assert row["ppc_finish"] is None and row["ppc_start"] is None and row["ppc_week"] is None
    assert row["note"] == "no status date in this update: its commitments cannot be read"


def test_ppc_notes_a_previous_update_without_any_planned_date():
    """xerscope definition (docs/formulas.md section 4, 08/11 case 8): an empty planned date falls
    back as the model does (actual, forecast, planned); when no open task of W-1 has any date, the
    point says so. A and B open in W-1 with no start nor finish: 0 committed and the note. With C
    dated beside them, C commits its start and finish and there is no note."""
    undated = dict(early_start_date="", early_end_date="")
    w2 = snap([todo("A"), todo("B"), todo("C")], data_date="2026-03-09 08:00")
    w1 = snap([todo("A", **undated), todo("B", **undated)], data_date="2026-03-02 08:00")
    row = ppc_series(SnapshotStore([w1, w2])).iloc[0]
    assert row["committed"] == 0
    assert row["note"] == "no start or finish date on any open task of the previous update: nothing could be committed"
    w1_mixed = snap([todo("A", **undated), todo("C", early_end_date="2026-03-06 17:00")], data_date="2026-03-02 08:00")
    row = ppc_series(SnapshotStore([w1_mixed, w2])).iloc[0]
    assert row["committed"] == 2 and pd.isna(row["note"])


def test_ppc_renumbering_found_by_guid_as_by_task_id():
    """08/11 case 3: a renumbered Activity ID counts as deleted + new, with a warning. A (task_id
    10) becomes A2 (task_id 20) with the same GUID: found by GUID, the link the baseline uses
    (task_id alone would miss it). X is new with its own GUID and task_id: not a renumbering."""
    w1 = snap([todo("A", task_id="10", guid="{G1}")], data_date="2026-03-02 08:00")
    w2 = snap(
        [todo("X", task_id="30", guid="{G3}"), todo("A2", task_id="20", guid="{G1}")], data_date="2026-03-09 08:00"
    )
    assert renumbered(w1, w2).values.tolist() == [["A", "A2"]]
    note = ppc_series(SnapshotStore([w1, w2])).iloc[0]["note"]
    assert note == "1 Activity ID(s) changed since W-1, counted as deleted + new: A → A2"


def test_ppc_regular_weekly_series_has_no_note():
    dates = ["2026-03-02 08:00", "2026-03-09 08:00", "2026-03-16 08:00"]
    s = ppc_series(SnapshotStore([snap([todo("A")], data_date=d) for d in dates]))
    assert s["note"].isna().all()


def test_ppc_week_at_another_hour_has_no_note():
    """Monday 08:00 to the next Monday 17:00: seven calendar days, one week."""
    dates = ["2026-03-02 08:00", "2026-03-09 17:00"]
    s = ppc_series(SnapshotStore([snap([todo("A")], data_date=d) for d in dates]))
    assert s["note"].isna().all()


def _kept(c: pd.DataFrame) -> dict[tuple[str, str], bool]:
    rows = zip(c["task_code"], c["commitment"], c["kept"], strict=True)
    return {(code, kind): bool(kept) for code, kind, kept in rows}


def test_ppc_start_on_the_status_date_is_committed_and_an_actual_a_minute_after_is_missed():
    """xerscope definition (docs/formulas.md section 4): "committed_starts = activities whose start
    update W-1 planned on or before the status date (data date) of W and not started in W-1;
    kept = actually started at W's data date." W-1 (Mon 2 Mar 08:00) plans AT and MIN to start
    Mon 9 Mar 08:00, W's data date: both committed. W: AT actual start 08:00, on the data date:
    kept; MIN actual start 08:01, a minute after: missed. Their finishes (Fri 13) are after W:
    not committed. PPC Start 1 / 2 = 50 %; PPC Finish n/a (none committed); PPC W/W-1
    (1 + 0) / (2 + 0) = 50 %."""
    plan = dict(early_start_date="2026-03-09 08:00", early_end_date="2026-03-13 17:00")
    w1 = snap([todo("AT", **plan), todo("MIN", **plan)])
    w2 = snap(
        [active("AT", act_start_date="2026-03-09 08:00"), active("MIN", act_start_date="2026-03-09 08:01")],
        data_date="2026-03-09 08:00",
    )
    assert _kept(committed(w1, w2)) == {("AT", "Start"): True, ("MIN", "Start"): False}
    row = ppc_series(SnapshotStore([w1, w2])).iloc[0]
    assert (row["starts_kept"], row["starts_committed"], row["ppc_start"]) == (1, 2, 50.0)
    assert (row["finishes_committed"], row["ppc_finish"]) == (0, None)
    assert row["ppc_week"] == 50.0


def test_ppc_finish_on_the_status_date_is_committed_and_an_actual_a_minute_after_is_missed():
    """xerscope definition (docs/formulas.md section 4): "PPC Finish = same for finishes (planned
    finish on or before W's data date in W-1, not finished in W-1; kept = finished at W's data
    date)." Status dates Fri 27 Feb 17:00 and Fri 6 Mar 17:00. In progress at W-1: F0 and F1
    planned to finish Fri 6 Mar 17:00, W's data date: committed; F2 Mon 9 Mar: not. W: F0
    actual finish 17:00: kept; F1 17:01, a minute after: missed. No start is due (all three
    started). PPC Finish 1 / 2 = 50 %; PPC Start n/a; PPC W/W-1 1 / 2 = 50 %."""
    started = "2026-02-23 08:00"
    w1 = snap(
        [
            active("F0", act_start_date=started, early_end_date="2026-03-06 17:00"),
            active("F1", act_start_date=started, early_end_date="2026-03-06 17:00"),
            active("F2", act_start_date=started, early_end_date="2026-03-09 17:00"),
        ],
        data_date="2026-02-27 17:00",
    )
    w2 = snap(
        [
            done("F0", act_start_date=started, act_end_date="2026-03-06 17:00"),
            done("F1", act_start_date=started, act_end_date="2026-03-06 17:01"),
            active("F2", act_start_date=started, early_end_date="2026-03-09 17:00"),
        ],
        data_date="2026-03-06 17:00",
    )
    assert _kept(committed(w1, w2)) == {("F0", "Finish"): True, ("F1", "Finish"): False}
    row = ppc_series(SnapshotStore([w1, w2])).iloc[0]
    assert (row["finishes_kept"], row["finishes_committed"], row["ppc_finish"]) == (1, 2, 50.0)
    assert (row["starts_committed"], row["ppc_start"]) == (0, None)
    assert row["ppc_week"] == 50.0


def test_ppc_commitment_deleted_in_w_is_a_scope_change_not_a_miss():
    """xerscope definition (docs/formulas.md section 4): "An activity committed in W-1 and deleted
    in W: report as scope change, not missed." W-1 commits GO and K to start and finish within the
    week; W: K complete, GO deleted. GO is listed (status "deleted", not in the update) and left
    out of every count: PPC Start 1 / 1, PPC Finish 1 / 1, PPC W/W-1 2 / 2 = 100 % (50 % if GO
    counted as missed)."""
    plan = dict(early_start_date="2026-03-03 08:00", early_end_date="2026-03-05 17:00")
    w1 = snap([todo("GO", **plan), todo("K", **plan)])
    w2 = snap(
        [done("K", act_start_date="2026-03-03 08:00", act_end_date="2026-03-05 17:00")],
        data_date="2026-03-09 08:00",
    )
    gone = committed(w1, w2).set_index(["task_code", "commitment"]).loc["GO"]
    assert sorted(gone.index) == ["Finish", "Start"]
    assert (gone["status_now"] == "deleted").all() and not gone["in_update"].any()
    row = ppc_series(SnapshotStore([w1, w2])).iloc[0]
    assert (row["starts_kept"], row["starts_committed"], row["finishes_kept"], row["finishes_committed"]) == (
        1, 1, 1, 1,
    )  # fmt: skip
    assert (row["ppc_start"], row["ppc_finish"], row["ppc_week"]) == (100.0, 100.0, 100.0)


def test_ppc_week_without_commitment_is_none_not_zero():
    """xerscope definition (docs/formulas.md section 4): "A week with no commitment: n/a, not 0."
    W-1 plans LATER to start Mon 16 Mar, after W's data date (Mon 9 Mar): nothing is committed,
    so the three PPC are none, not 0 %."""
    later = dict(early_start_date="2026-03-16 08:00", early_end_date="2026-03-20 17:00")
    w1 = snap([todo("LATER", **later)])
    w2 = snap([todo("LATER", **later)], data_date="2026-03-09 08:00")
    assert committed(w1, w2).empty
    row = ppc_series(SnapshotStore([w1, w2])).iloc[0]
    assert (row["committed"], row["kept"]) == (0, 0)
    assert row["ppc_start"] is None and row["ppc_finish"] is None and row["ppc_week"] is None


def test_ppc_leaves_milestones_out_of_starts_and_finishes():
    """xerscope definition (docs/formulas.md section 4): population as before the three-indicator
    definition, milestones and LOE left out. W-1 plans T (task), SM (start milestone, Tue 08:00)
    and FM (finish milestone, Thu 17:00) within the week; W: all three done. Only T commits: PPC
    Start 1 / 1, PPC Finish 1 / 1 (3 / 3 for each if the milestones counted)."""
    w1 = snap(
        [
            todo("T", early_start_date="2026-03-03 08:00", early_end_date="2026-03-05 17:00"),
            todo("SM", **SM, early_start_date="2026-03-03 08:00", early_end_date="2026-03-03 08:00"),
            todo("FM", **FM, early_start_date="2026-03-05 17:00", early_end_date="2026-03-05 17:00"),
        ]
    )
    w2 = snap(
        [
            done("T", act_start_date="2026-03-03 08:00", act_end_date="2026-03-05 17:00"),
            done("SM", **SM, act_start_date="2026-03-03 08:00", act_end_date="2026-03-03 08:00"),
            done("FM", **FM, act_start_date="2026-03-05 17:00", act_end_date="2026-03-05 17:00"),
        ],
        data_date="2026-03-09 08:00",
    )
    assert _kept(committed(w1, w2)) == {("T", "Start"): True, ("T", "Finish"): True}
    row = ppc_series(SnapshotStore([w1, w2])).iloc[0]
    assert (row["starts_committed"], row["finishes_committed"], row["committed"]) == (1, 1, 2)


# --- start and finish variances vs W-1 and W-2 ---------------------------------------------------


def _dates(start: str, finish: str, **kw) -> dict:
    return dict(early_start_date=start, early_end_date=finish, **kw)


# Three updates, a week apart. Fri 3 Apr 2026 is a holiday on C8 (Mon-Fri 8 h), not on C7D
# (7 days, 08:00-16:00). H (C8) and S7 (C7D) slip the same way; E is new in W-1 and moves earlier
# in W; SMS / FMS are start / finish milestones; N is new in W.
VAR_W2 = snap(
    [
        todo("H", **_dates("2026-03-30 08:00", "2026-04-01 17:00")),
        todo("S7", clndr_id="C7D", **_dates("2026-03-30 08:00", "2026-04-01 16:00")),
        todo("SMS", **SM, **_dates("2026-03-31 08:00", "2026-03-31 08:00")),
        todo("FMS", **FM, **_dates("2026-04-02 17:00", "2026-04-02 17:00")),
    ],
    data_date="2026-03-16 08:00",
)
VAR_W1 = snap(
    [
        todo("H", **_dates("2026-03-31 08:00", "2026-04-02 17:00")),
        todo("S7", clndr_id="C7D", **_dates("2026-03-31 08:00", "2026-04-02 16:00")),
        todo("E", **_dates("2026-04-06 08:00", "2026-04-08 17:00")),
        todo("SMS", **SM, **_dates("2026-03-31 08:00", "2026-03-31 08:00")),
        todo("FMS", **FM, **_dates("2026-04-02 17:00", "2026-04-02 17:00")),
    ],
    data_date="2026-03-23 08:00",
)
VAR_W = snap(
    [
        todo("H", **_dates("2026-04-02 08:00", "2026-04-06 17:00")),
        todo("S7", clndr_id="C7D", **_dates("2026-04-02 08:00", "2026-04-06 16:00")),
        todo("E", **_dates("2026-04-06 08:00", "2026-04-07 17:00")),
        todo("SMS", **SM, **_dates("2026-04-02 08:00", "2026-04-02 08:00")),
        todo("FMS", **FM, **_dates("2026-04-06 17:00", "2026-04-06 17:00")),
        todo("N", **_dates("2026-04-06 08:00", "2026-04-10 17:00")),
    ],
    data_date="2026-03-30 08:00",
)


def _variances(index: int) -> pd.DataFrame:
    return date_variances(SnapshotStore([VAR_W2, VAR_W1, VAR_W]), index).set_index("task_code")[VARIANCE_COLUMNS]


def test_variances_count_working_days_of_the_activity_calendar_holiday_included():
    """xerscope definition (docs/formulas.md section 4): "for each activity, four columns (start W-1,
    finish W-1, start W-2, finish W-2) in working days of the activity's calendar, sign NEGATIVE = late
    (reference − current)." H on C8: start Tue 31 Mar (W-1) / Mon 30 Mar (W-2) -> Thu 2 Apr: -2 / -3
    wd. Finish Thu 2 Apr 17:00 (W-1) -> Mon 6 Apr 17:00: Fri 3 Apr is a holiday, so -1 wd (4
    calendar days); from Wed 1 Apr (W-2): Thu + Mon = -2 wd. S7 has the same moves on C7D, which
    works Fri to Sun: finish -4 wd vs W-1 and -5 wd vs W-2, starts -2 / -3 as on C8."""
    v = _variances(2)
    assert v.loc["H"].tolist() == [-2, -1, -3, -2]
    assert v.loc["S7"].tolist() == [-2, -4, -3, -5]


def test_variance_sign_is_reference_minus_current():
    """xerscope definition (docs/formulas.md section 4): "sign NEGATIVE = late (reference − current)".
    E finishes Wed 8 Apr in W-1 and Tue 7 Apr in W: one working day earlier, +1; its start does not
    move: 0, not blank. H is later in W than in W-1: negative (test above)."""
    e = _variances(2).loc["E"]
    assert (e["start_var_w1"], e["finish_var_w1"]) == (0, 1)


def test_variance_missing_reference_is_blank_not_zero():
    """xerscope definition (docs/formulas.md section 4): "Missing date → blank, not 0." E is not in
    W-2: its two W-2 columns are blank; N is only in W: all four blank. Read at W-1 (index 1) there
    is no W-2: every W-2 column blank, and H moved Mon 30 -> Tue 31 Mar (start) and Wed 1 -> Thu 2
    Apr (finish): -1 wd each. The first update has nothing to compare with: all blank."""
    v = _variances(2)
    assert v.loc["E", ["start_var_w2", "finish_var_w2"]].isna().all()
    assert v.loc["N"].isna().all()
    at_w1 = _variances(1)
    assert at_w1[["start_var_w2", "finish_var_w2"]].isna().all().all()
    assert (at_w1.loc["H", "start_var_w1"], at_w1.loc["H", "finish_var_w1"]) == (-1, -1)
    assert _variances(0).isna().all().all()


def test_variance_of_a_milestone_has_only_its_own_end():
    """xerscope definition (docs/formulas.md section 4): "A milestone has only the relevant end."
    SMS (start milestone) Tue 31 Mar -> Thu 2 Apr: start -2 wd vs W-1 and W-2, finish blank. FMS
    (finish milestone) Thu 2 Apr 17:00 -> Mon 6 Apr 17:00 across the C8 holiday: finish -1 wd vs W-1
    and W-2, start blank."""
    v = _variances(2)
    assert v.loc["SMS", ["start_var_w1", "start_var_w2"]].tolist() == [-2, -2]
    assert v.loc["SMS", ["finish_var_w1", "finish_var_w2"]].isna().all()
    assert v.loc["FMS", ["finish_var_w1", "finish_var_w2"]].tolist() == [-1, -1]
    assert v.loc["FMS", ["start_var_w1", "start_var_w2"]].isna().all()


def test_evm_series_one_point_per_update_against_one_baseline():
    from xerscope.store import SnapshotStore

    bl = Baseline.from_snapshot(W1)
    s = evm_series(SnapshotStore([W1, W2]), bl)
    assert list(s["data_date"]) == [W1.data_date, W2.data_date]
    assert s["bac_hr"].nunique() == 1  # the baseline does not move
    assert s["ev_hr"].iloc[0] == 0 and s["ev_hr"].iloc[1] == 100 + 150  # A done (100 h), B half (300 h)


def test_forecast_curve_starts_at_ac_and_ends_at_eac():
    # 80 h remaining on A over 2026-03-02 08:00 -> 03-13 17:00 (10 working days), 20 h spent:
    # AC at the data date, then one row per midnight, 8 h per working day on top of AC, ending at AC + 80
    s = snap(
        [
            active(
                "A",
                early_start_date="2026-03-02 08:00",
                early_end_date="2026-03-13 17:00",
                target_work_qty="100",
                act_work_qty="20",
                remain_work_qty="80",
            )
        ],
        data_date="2026-03-02 08:00",
    )
    c = forecast_curve(s)
    assert c["date"].is_monotonic_increasing and c["date"].iloc[0] == s.data_date
    assert c["fc_cum_hr"].iloc[0] == pytest.approx(20)
    assert c["fc_cum_hr"].iloc[-1] == pytest.approx(100)
    by_day = c.set_index("date")["fc_cum_hr"].rename(index=str)
    assert by_day["2026-03-03 00:00:00"] == pytest.approx(28)  # end of the first working day
    assert by_day["2026-03-08 00:00:00"] == by_day["2026-03-07 00:00:00"]  # Saturday: nothing spread


def test_progress_delta_weighted_by_hours():
    d = progress_delta(W1, W2).set_index("task_code")
    assert d.loc["A", "pct_delta"] == 100 and d.loc["B", "pct_delta"] == 50
    assert d.loc["B", "earned_hr_week"] == 150
    total = rollup_delta(progress_delta(W1, W2)).set_index("wbs_l1").loc["Project"]
    assert total["progress_pts"] == pytest.approx(100 * 250 / 400)  # not the plain average 75


# --- WBS -------------------------------------------------------------------------------------------

WBS = [
    {
        "wbs_id": "W0",
        "proj_id": "1",
        "parent_wbs_id": "",
        "proj_node_flag": "Y",
        "wbs_short_name": "T",
        "wbs_name": "Project",
        "seq_num": "0",
    },
    {
        "wbs_id": "W1",
        "proj_id": "1",
        "parent_wbs_id": "W0",
        "proj_node_flag": "N",
        "wbs_short_name": "E",
        "wbs_name": "Eng",
        "seq_num": "1",
    },
    {
        "wbs_id": "W11",
        "proj_id": "1",
        "parent_wbs_id": "W1",
        "proj_node_flag": "N",
        "wbs_short_name": "D",
        "wbs_name": "Design",
        "seq_num": "1",
    },
    {
        "wbs_id": "W2",
        "proj_id": "1",
        "parent_wbs_id": "W0",
        "proj_node_flag": "N",
        "wbs_short_name": "C",
        "wbs_name": "Civil",
        "seq_num": "2",
    },
]


def test_wbs_rollup_hours_weighting_and_tree():
    s = snap(
        [
            done("A", wbs_id="W11", target_work_qty="100", phys_complete_pct="100", complete_pct_type="CP_Phys"),
            todo("B", wbs_id="W1", target_work_qty="300"),
            todo("C", wbs_id="W2", target_drtn_hr_cnt="80"),
            active("D", wbs_id="W2", target_drtn_hr_cnt="240", remain_drtn_hr_cnt="120"),
        ],
        wbs=WBS,
    )
    r = rollup(s).set_index("wbs_id")
    assert r.loc["W11", "wbs_code"] == "E.D" and r.loc["W11", "depth"] == 2
    assert r.loc["W1", "activities"] == 2  # B plus A from the child node
    assert r.loc["W1", "pct_complete"] == pytest.approx(25)  # 100 h done of 400 h
    assert r.loc["W2", "weight"] == "duration"  # no hours: (0 x 10 + 50 x 30) / 40
    assert r.loc["W2", "pct_complete"] == pytest.approx(37.5)
    assert r.loc[ROOT, "activities"] == 4
    assert subtree_ids(rollup(s), "W1") == {"W1", "W11"}


CIVIL = [
    {
        "wbs_id": "10",
        "proj_id": "1",
        "parent_wbs_id": "",
        "wbs_short_name": "T",
        "wbs_name": "P",
        "proj_node_flag": "Y",
        "seq_num": "0",
    },
    {
        "wbs_id": "11",
        "proj_id": "1",
        "parent_wbs_id": "10",
        "wbs_short_name": "CIV",
        "wbs_name": "Civil",
        "seq_num": "1",
    },
]


@pytest.mark.parametrize("a_now, variance", [("2026-03-13 17:00", 0.0), ("2026-03-16 17:00", -1.0)])
def test_wbs_finish_variance_compares_the_baselined_activities_only(a_now, variance):
    """A is in the baseline (finish Fri 13 March), NEW was added after it (finish Fri 10 April).
    The node's finish against its baseline finish is read on A only: 0 wd while A holds, -1 wd
    when A moves to Mon 16 March (baseline finish minus finish: one working day lost reads -1,
    and no move reads 0.0, never -0.0). Reading the node's finish over every activity gave
    13 March -> 10 April = 20 weekdays less Good Friday (3 April, a C8 holiday) = 19 wd."""
    baseline = snap([todo("A", wbs_id="11", early_end_date="2026-03-13 17:00")], wbs=CIVIL)
    now = snap(
        [todo("A", wbs_id="11", early_end_date=a_now), todo("NEW", wbs_id="11", early_end_date="2026-04-10 17:00")],
        wbs=CIVIL,
    )
    node = rollup(now, Baseline.from_snapshot(baseline)).set_index("wbs_id").loc["11"]
    assert node["finish"] == pd.Timestamp("2026-04-10 17:00")  # the bar still ends with NEW
    assert node["finish_variance_wd"] == variance and str(node["finish_variance_wd"]) == str(variance)
    assert node["outside_bl"] == 1


# --- milestone trend -----------------------------------------------------------------------------


def test_milestone_slip_in_working_days(tmp_path):
    ms = dict(task_type="TT_FinMile", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0")
    for i, (dd, end) in enumerate([("2026-03-02 08:00", "2026-04-10 17:00"), ("2026-03-09 08:00", "2026-04-14 17:00")]):
        (tmp_path / f"w{i}.xer").write_text(
            __import__("xerkit").xer_text([todo("M1", early_end_date=end, **ms)], data_date=dd), encoding="utf-8"
        )
    store = SnapshotStore.from_folder(tmp_path)
    s = milestone_slips(milestone_trend(store), store).set_index("task_code").loc["M1"]
    assert s["slip_wd"] == -2  # Fri 10 -> Tue 14 April = Mon + Tue, later: negative


def test_mta_drops_a_milestone_complete_before_the_data_date(tmp_path):
    """An update hides a milestone only if it is complete and its date is before that update's
    data date; every other update keeps it, even after a completion."""
    ms = dict(task_type="TT_FinMile", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0")
    weeks = {  # data date: tasks
        "2026-03-02 08:00": [todo("M1", early_end_date="2026-03-12 17:00", **ms), done("M0", **ms)],
        # M1 reached on 12 March; M3 marked complete on a date after this data date
        "2026-03-16 08:00": [
            done("M1", act_end_date="2026-03-12 17:00", **ms),
            done("M0", **ms),
            done("M3", act_end_date="2026-03-20 17:00", **ms),
        ],
        # M1 reopened: open again, kept
        "2026-03-23 08:00": [todo("M1", early_end_date="2026-03-27 17:00", **ms), done("M0", **ms)],
    }
    for i, (dd, tasks) in enumerate(weeks.items()):
        rows = [*tasks, todo("M2", early_end_date="2026-05-29 17:00", **ms)]
        (tmp_path / f"w{i}.xer").write_text(__import__("xerkit").xer_text(rows, data_date=dd), encoding="utf-8")
    store = SnapshotStore.from_folder(tmp_path)
    plotted = plotted_trend(milestone_trend(store))
    assert len(plotted) == len(milestone_trend(store))  # hidden updates are blanked, not dropped
    shown = plotted.dropna(subset=["forecast"])
    kept = shown.groupby("task_code")["data_date"].apply(lambda d: [x.strftime("%m-%d") for x in d]).to_dict()
    assert kept == {"M1": ["03-02", "03-23"], "M2": ["03-02", "03-16", "03-23"], "M3": ["03-16"]}  # M0 never
    assert milestone_codes(store, open_only=True) == ["M1", "M2"]
    s = milestone_slips(milestone_trend(store), store).set_index("task_code")
    assert s.loc["M1", "updates"] == 3  # the table keeps every update


def test_mta_marks_a_deleted_milestone_and_leaves_it_out_of_the_open_ones():
    """M1 moves Fri 10 -> Fri 17 April in the second update and is deleted in the third. It
    is not open: it is deleted, as the changelog says. Its last move (-5 wd) dates from two
    updates back, not from the last one: the last update has no move for it. M2 holds."""
    weeks = {
        "2026-03-02 08:00": [todo("M1", early_end_date="2026-04-10 17:00", **FM)],
        "2026-03-09 08:00": [todo("M1", early_end_date="2026-04-17 17:00", **FM)],
        "2026-03-16 08:00": [],
    }
    updates = [
        snap([*tasks, todo("M2", early_end_date="2026-04-10 17:00", **FM)], data_date=dd) for dd, tasks in weeks.items()
    ]
    store = SnapshotStore(updates)
    s = milestone_slips(milestone_trend(store), store).set_index("task_code")
    assert s["deleted"].to_dict() == {"M1": True, "M2": False}
    assert s.loc["M1", "slip_wd"] == -5  # 10 -> 17 April while it existed, later: negative
    assert pd.isna(s.loc["M1", "last_week_wd"])
    assert s.loc["M2", "last_week_wd"] == 0 and str(s.loc["M2", "last_week_wd"]) == "0.0"  # never -0.0
    assert milestone_codes(store, open_only=True) == ["M2"]
    assert milestone_codes(store) == ["M2", "M1"]  # the trend still draws its history


def test_changelog_lists_assignment_changes():
    res = [
        {"rsrc_id": "R1", "rsrc_short_name": "CRANE", "rsrc_type": "RT_Equip", "clndr_id": "C8"},
        {"rsrc_id": "R2", "rsrc_short_name": "FITTER", "rsrc_type": "RT_Labor", "clndr_id": "C8"},
    ]
    w1 = snap(
        [todo("A"), todo("B")],
        resources=res,
        assign=[
            {"task_code": "A", "rsrc_id": "R1", "target_qty": "40"},
            {"task_code": "B", "rsrc_id": "R2", "target_qty": "80"},
        ],
    )
    w2 = snap(
        [todo("A"), todo("B")],
        resources=res,
        assign=[
            {"task_code": "A", "rsrc_id": "R1", "target_qty": "60"},
            {"task_code": "A", "rsrc_id": "R2", "target_qty": "16"},
        ],
    )
    log = changelog(w1, w2)
    r = log[log["category"] == "Resources"].set_index(["task_code", "change"])
    assert r.loc[("A", "budgeted units changed"), "delta"] == 20
    assert r.loc[("A", "resource assigned"), "field"] == "assignment FITTER"
    assert r.loc[("B", "resource removed"), "field"] == "assignment FITTER"


def test_progress_delta_with_a_baseline_adds_up_to_ev():
    bl = Baseline.from_snapshot(W1)
    d = progress_delta(W1, W2, bl).set_index("task_code")
    assert d.loc["B", "earned_hr_week"] == 150  # BL 300 h x 50 points
    assert d["earned_hr_week"].sum() == ev_point(W2, bl).ev_hr - ev_point(W1, bl).ev_hr
    assert d.loc["DEL", "status"] == "deleted" and d.loc["DEL", "earned_hr_week"] == 0  # no progress to give back


def test_progress_delta_gives_back_the_hours_of_a_deleted_activity():
    # W1: D half done (50 of 100 h earned). W2: D is gone. The week's earned hours are -50,
    # the change in EV; a frame built from W2 alone would say 0.
    w1 = snap(
        [active("D", target_work_qty="100", phys_complete_pct="50", complete_pct_type="CP_Phys"), todo("K")],
        data_date="2026-03-02 08:00",
    )
    w2 = snap([todo("K")], data_date="2026-03-09 08:00")
    bl = Baseline.from_snapshot(w1)
    d = progress_delta(w1, w2, bl).set_index("task_code")
    assert d.loc["D", "deleted"] and d.loc["D", "earned_hr_week"] == -50
    assert d["earned_hr_week"].sum() == ev_point(w2, bl).ev_hr - ev_point(w1, bl).ev_hr == -50
    # without a baseline the same, on W1's budget hours
    assert progress_delta(w1, w2).set_index("task_code").loc["D", "earned_hr_week"] == -50


@pytest.mark.parametrize(
    "basis,hours,first_day",
    [
        ("budgeted_planned", 80, "2026-03-09"),  # planned dates: the week of 9 March
        ("budgeted_current", 80, "2026-03-02"),  # the baseline's current Start / Finish
        ("at_completion_current", 96, "2026-03-02"),  # actual + remaining units
    ],
)
def test_ev_basis_follows_p6_admin_preference(basis, hours, first_day):
    """P6 Admin Preferences > Earned Value: "When calculating earned value from a baseline use"."""
    bl_snap = snap(
        [
            active(
                "A",
                target_work_qty="80",
                act_work_qty="40",
                remain_work_qty="56",
                act_start_date="2026-03-02 08:00",
                early_start_date="2026-03-02 08:00",
                early_end_date="2026-03-13 17:00",
                restart_date="2026-03-02 08:00",
                reend_date="2026-03-13 17:00",
                target_start_date="2026-03-09 08:00",
                target_end_date="2026-03-20 17:00",
            )
        ]
    )
    bl = Baseline.from_snapshot(bl_snap, ev_basis=basis)
    assert bl.bac_hours == hours
    curve = pv_curve(bl)
    assert curve.loc[curve["pv_hr"] > 0, "date"].min() == pd.Timestamp(first_day) + pd.Timedelta(days=1)
    assert bl.frame.at["A", "bl_start"] == pd.Timestamp("2026-03-02 08:00")  # variances: current dates


@pytest.mark.parametrize(
    "basis,pct", [("budgeted_planned", 0), ("budgeted_current", 100), ("at_completion_current", 100)]
)
def test_planned_dates_baseline_spreads_on_the_current_dates_with_a_current_dates_basis(basis, pct):
    """P6 Pro 26, Admin Preferences > Earned Value: "The current dates options use the Start/Finish dates
    for an activity or resource assignment." A, done 02-02 → 02-13, planned (target_*) 03-09 → 03-20, data
    date 03-02: by hand, 0 % of its planned span is elapsed, 100 % of its current span."""
    dates = {
        "target_start_date": "2026-03-09 08:00",
        "target_end_date": "2026-03-20 17:00",
        "act_start_date": "2026-02-02 08:00",
        "act_end_date": "2026-02-13 17:00",
    }
    s = snap(
        [done("A", target_work_qty="80", **dates)],
        assign=[{"task_code": "A", "rsrc_id": "R1", "target_qty": "80", **dates}],
        data_date="2026-03-02 08:00",
    )
    bl = Baseline.planned(s, ev_basis=basis)
    assert schedule_pct(bl, s.data_date).loc["A"] == pct
    current = basis != "budgeted_planned"
    expected = ("2026-02-02 08:00", "2026-02-13 17:00") if current else ("2026-03-09 08:00", "2026-03-20 17:00")
    assert tuple(bl.assignment_costs.loc[0, ["start", "finish"]]) == tuple(map(pd.Timestamp, expected))
    # the planned dates stay the baseline dates whatever the basis
    assert (bl.frame.at["A", "bl_start"], bl.frame.at["A", "bl_finish"]) == (
        pd.Timestamp("2026-03-09 08:00"),
        pd.Timestamp("2026-03-20 17:00"),
    )


def test_current_dates_on_a_planned_dates_baseline_move_pv_only():
    """EV = BL labour units x Performance % (P6 Pro 26, Earned Value): the dates of the basis do not enter it.
    A done early, B 50 % physical, both planned after the data date: EV 80 + 40 h on both bases; PV 0 h on
    the planned dates, A's 80 h on its current (actual) dates."""
    planned = {"target_start_date": "2026-03-09 08:00", "target_end_date": "2026-03-20 17:00"}
    s = snap(
        [
            done("A", target_work_qty="80", **planned),
            active("B", target_work_qty="80", phys_complete_pct="50", complete_pct_type="CP_Phys", **planned),
        ],
        data_date="2026-03-02 08:00",
    )
    on_planned = earned(s, Baseline.planned(s, "budgeted_planned"))
    on_current = earned(s, Baseline.planned(s, "budgeted_current"))
    assert on_planned["ev_hr"].tolist() == on_current["ev_hr"].tolist() == [80, 40]
    assert on_planned["pv_hr"].tolist() == [0, 0]
    assert on_current.at["A", "pv_hr"] == 80


def test_ev_basis_rejects_unknown_values():
    with pytest.raises(ValueError):
        Baseline.from_snapshot(snap([todo("A")]), ev_basis="planned")


# --- pure computations formerly inside the Streamlit pages (pinned from the page output) -------------


def test_bei_series_one_row_per_update_p6_and_dcma(store):
    from xerscope.analysis import builtin_standards
    from xerscope.analysis.evm import bei_series

    std = builtin_standards()
    bei = {k: next(m for m in std[k].metrics if m.name == "BEI") for k in ("P6", "DCMA")}
    out = bei_series(store, bei, Baseline.planned)
    assert list(out.columns) == ["data_date", "bei_p6", "bei_dcma"]
    assert out["data_date"].tolist() == [s.data_date for s in store]
    assert out["bei_p6"].dtype == out["bei_dcma"].dtype == "float64"
    assert pd.isna(out["bei_dcma"].iloc[0])
    # Updates 6 and 7: one completed activity has its actual finish after the status date (the
    # planted invalid date). DCMA-EA PAM 200.1 §3.1.2.4 step 5 keeps "only dates up to the current
    # reporting period", so it is due and not completed: 4 / 7 and 5 / 9. Step 2 filters the baseline
    # finish with the same bound, by calendar day (dcma.toml date_grain): E1010 (update 2, 2026-09-14)
    # and C3020 (update 7, 2026-10-19) have their baseline finish at 16:00 on the data date's day
    # (data date 08:00) and are not complete: due, not completed, so 1 / 2 and 5 / 9.
    assert out["bei_dcma"].iloc[1:].tolist() == pytest.approx([1, 0.5, 1, 0.75, 2 / 3, 4 / 7, 5 / 9])
    # P6 Professional: completed / every baseline activity, milestones and LOE out (the planned
    # baseline is the snapshot itself)
    expected_p6 = []
    for snapshot in store:
        counted = snapshot.activities[~snapshot.activities["is_milestone"] & ~snapshot.activities["is_loe"]]
        expected_p6.append(counted["is_complete"].sum() / len(counted))
    assert out["bei_p6"].tolist() == pytest.approx(expected_p6)


def test_health_wide_has_one_row_per_check_and_one_column_per_update(store):
    from xerscope.analysis import builtin_standards, health_history
    from xerscope.analysis.checks import health_wide

    std = builtin_standards()["P6"]
    wide = health_wide(health_history(store, std, Baseline.planned), std)
    assert list(wide.columns) == ["id", "check", *(f"{s.data_date:%Y-%m-%d}" for s in store)]
    assert wide["id"].tolist() == [m.id for m in std.metrics]
    assert wide["check"].iloc[:4].tolist() == ["Logic", "Hard Constraints", "Soft Constraints", "Large Durations"]
    # Logic: 3 / 29 (K5040, M9999 and the not-started start milestone M1000)
    assert wide.iloc[:4, 2].tolist() == pytest.approx([10.344828, 0, 7.142857, 4.166667])
    assert wide.shape == (18, 10)
    assert (wide.dtypes.iloc[2:] == "float64").all()


def test_category_totals_sums_counts_and_lists_kinds(store):
    from xerscope.analysis.changelog import category_totals

    out = category_totals(summary(changelog(store[0], store[1])))
    assert out["category"].astype(str).tolist() == ["Progress", "Dates", "Float"]
    assert out["total"].tolist() == [9, 50, 1]
    assert out["total"].dtype == "int64"
    assert out["kinds"].tolist() == [
        "% complete, finished, started",
        "finish moved, start moved",
        "total float changed",
    ]


def test_weekly_change_matrix_counts_per_category_kind_and_week(store):
    from xerscope.analysis.changelog import weekly_change_counts, weekly_change_matrix

    matrix = weekly_change_matrix(weekly_change_counts(store))
    assert list(matrix.columns) == ["category", "change", *(f"{s.data_date:%Y-%m-%d}" for s in list(store)[1:])]
    assert matrix.shape == (13, 9)
    assert matrix.iloc[0][["category", "change"]].astype(str).tolist() == ["Scope", "added"]
    assert matrix.iloc[0, 2:].tolist() == [0, 0, 0, 1, 0, 0, 0]
    assert (matrix.dtypes.iloc[2:] == "int64").all()
    assert int(matrix.iloc[:, 2:].to_numpy().sum()) == 365


def test_forecast_finish_shift_since_first_update_in_working_days(store):
    from xerscope.analysis.progress import finish_shift_since_first

    assert finish_shift_since_first(store) == -15.0  # the forecast finish went 15 working days later
    assert finish_shift_since_first(SnapshotStore([store.first])) is None


def test_inverted_ev_dates_are_one_step_at_the_finish_in_the_kpi_and_the_curve():
    """A, 40 h, EV start Fri 03-06 17:00 after its EV finish Mon 03-02 08:00 (an invalid import): the
    Schedule % convention (zero or negative span = 0 before the finish, 100 from it) applies to the
    curve too, so both give 40 h at Wed 03-04 08:00 and 0 h before Mon 08:00."""
    inverted = {"target_start_date": "2026-03-06 17:00", "target_end_date": "2026-03-02 08:00", "target_work_qty": "40"}
    baseline = Baseline.from_snapshot(snap([todo("A", **inverted)]))
    update = snap([todo("A")], data_date="2026-03-04 08:00")
    curve = pv_curve(baseline, update).set_index("date")["pv_cum_hr"]
    assert ev_point(update, baseline).pv_hr == pytest.approx(40) == curve[update.data_date]
    assert curve[pd.Timestamp("2026-03-02")] == 0 and curve.iloc[-1] == pytest.approx(40)


def test_a_negative_budget_counts_in_the_curve_as_in_the_kpi():
    """A 40 h and B -8 h (an invalid import) over Mon-Fri; Wed 08:00 is 2 of 5 days: by hand,
    PV = (40 - 8) x 0.4 = 12.8 h in the KPI and in the curve at the data date."""
    hours = {"early_start_date": "2026-03-02 08:00", "early_end_date": "2026-03-06 17:00"}
    baseline = Baseline.from_snapshot(
        snap([todo("A", target_work_qty="40", **hours), todo("B", target_work_qty="-8", **hours)])
    )
    update = snap([todo("A"), todo("B")], data_date="2026-03-04 08:00")
    curve = pv_curve(baseline, update).set_index("date")["pv_cum_hr"]
    assert ev_point(update, baseline).pv_hr == pytest.approx(12.8) == curve[update.data_date]
