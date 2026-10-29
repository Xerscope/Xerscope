"""Changelog, earned value, PPC, progress delta, WBS roll-ups, MTA: hand-checked numbers."""

import pandas as pd
import pytest
from xerkit import active, done, snap, todo

from xerscope.analysis import Baseline
from xerscope.analysis.changelog import changelog, summary
from xerscope.analysis.evm import earned, ev_point, ev_technique, pv_at, pv_curve, schedule_pct
from xerscope.analysis.progress import committed, milestone_slips, milestone_trend, progress_delta, rollup_delta
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
    assert fin["delta"] == 1  # Fri 13 -> Mon 16 = one working day, not three calendar days
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
    assert proj.loc["data date", "delta"] == 5
    s = summary(log)
    assert "Project" not in set(s["category"])
    assert s["count"].sum() == len(log) - 4


def test_identical_files_have_no_changes():
    assert summary(changelog(OLD, OLD)).empty


# --- earned value --------------------------------------------------------------------------------


def _bl(**a):
    return Baseline.from_snapshot(snap([todo("A", target_work_qty="80", **a)]))


def test_pv_spreads_over_working_days():
    bl = _bl(early_start_date="2026-03-02 08:00", early_end_date="2026-03-13 17:00")  # 10 working days
    curve = pv_curve(bl)
    assert curve["pv_cum_hr"].iloc[-1] == pytest.approx(80)
    assert curve.set_index("date").loc["2026-03-07", "pv_hr"] == 0  # Saturday
    assert pv_at(bl, pd.Timestamp("2026-03-04 08:00")) == pytest.approx(16)  # Mon + Tue
    assert pv_at(bl, pd.Timestamp("2026-03-04 12:00")) == pytest.approx(20)  # + half of Wed
    assert pv_at(bl, pd.Timestamp("2026-03-04 12:30")) == pytest.approx(20)  # lunch is not working time


def test_pv_is_schedule_pct_complete_in_working_time():
    """Oracle: PV labour units = BL labour units x Schedule % Complete; an activity starting
    at 13:00 has done 4 of its 12 working hours by the evening, not a third of a day."""
    bl = _bl(early_start_date="2026-03-02 13:00", early_end_date="2026-03-03 17:00", target_drtn_hr_cnt="12")
    assert pv_at(bl, pd.Timestamp("2026-03-02 17:00")) == pytest.approx(80 * 4 / 12)
    assert schedule_pct(bl, pd.Timestamp("2026-03-03 08:00")).loc["A"] == pytest.approx(33.33)
    assert pv_curve(bl).set_index("date").loc["2026-03-02", "pv_hr"] == pytest.approx(80 / 3)


def test_pv_skips_calendar_holiday():
    bl = _bl(early_start_date="2026-03-30 08:00", early_end_date="2026-04-03 17:00")  # Mon-Fri, Fri = Good Friday
    curve = pv_curve(bl).set_index("date")
    assert curve.loc["2026-04-03", "pv_hr"] == 0
    assert curve.loc["2026-03-30", "pv_hr"] == pytest.approx(20)  # 80 h over 4 working days


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
            todo("X", target_work_qty="40", remain_work_qty="40"),
        ],
        data_date="2026-03-04 08:00",
    )
    p = ev_point(now, bl)
    assert (p.pv_hr, p.ev_hr, p.ac_hr, p.etc_hr) == (16, 20, 30, 100)
    assert p.spi == pytest.approx(1.25)
    assert p.productivity == pytest.approx(20 / 30)
    assert p.unbaselined == ["X"]


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


def test_ppc_counts_only_commitments_still_in_the_update():
    c = committed(W1, W2)
    assert sorted(c["task_code"]) == ["A", "B", "DEL"]  # C was due after the W2 data date
    kept = c[c["in_update"]]
    assert kept["completed"].sum() / len(kept) == 0.5


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


# --- milestone trend -----------------------------------------------------------------------------


def test_milestone_slip_in_working_days(tmp_path):
    ms = dict(task_type="TT_FinMile", target_drtn_hr_cnt="0", remain_drtn_hr_cnt="0")
    for i, (dd, end) in enumerate([("2026-03-02 08:00", "2026-04-10 17:00"), ("2026-03-09 08:00", "2026-04-14 17:00")]):
        (tmp_path / f"w{i}.xer").write_text(
            __import__("xerkit").xer_text([todo("M1", early_end_date=end, **ms)], data_date=dd), encoding="utf-8"
        )
    store = SnapshotStore.from_folder(tmp_path)
    s = milestone_slips(milestone_trend(store), store).set_index("task_code").loc["M1"]
    assert s["slip_wd"] == 2  # Fri 10 -> Tue 14 April = Mon + Tue


# --- CLI ---------------------------------------------------------------------------------------------


def test_cli_check_and_standards(sample_dir, tmp_path, capsys):
    from xerscope.cli import main

    out = tmp_path / "r.csv"
    files = sorted(sample_dir.glob("*.xer"))
    assert main(["check", str(files[-1]), "--standard", "DCMA", "--baseline", str(files[0]), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "DCMA-14" in text and "baseline BL" in text
    assert len(pd.read_csv(out)) == 14
    assert main(["standards", "--rules"]) == 0
    assert "missing_logic" in capsys.readouterr().out
    assert main(["changelog", str(files[3]), str(files[4])]) == 0
    assert "added" in capsys.readouterr().out


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
    assert curve.loc[curve["pv_hr"] > 0, "date"].min() == pd.Timestamp(first_day)
    assert bl.frame.at["A", "bl_start"] == pd.Timestamp("2026-03-02 08:00")  # variances: current dates


def test_ev_basis_rejects_unknown_values():
    with pytest.raises(ValueError):
        Baseline.from_snapshot(snap([todo("A")]), ev_basis="planned")
