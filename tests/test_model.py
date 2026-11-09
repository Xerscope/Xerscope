import contextlib
from pathlib import Path

import pandas as pd
import pytest
from xerkit import active, done, snap, todo, xer_text

from xerscope.xer import HEADER_TABLES, XerError, build_snapshot, parse_text, read_header, read_xer, xer_files


def test_snapshot_identity(store):
    s = store.first
    assert s.project_code == "PRJ-ALPHA"
    assert s.project_name == "Usine de traitement – Phase 1"  # from the PROJWBS project node
    assert s.data_date == pd.Timestamp("2026-08-31 08:00")
    assert s.finish_date is not None


def test_types_and_units(store):
    t = store.first.tasks
    assert pd.api.types.is_datetime64_any_dtype(t["early_start_date"])
    fab = t.set_index("task_code").loc["P2030"]
    assert fab["original_d"] == 60  # 480 h / 8 h per day
    assert fab["type"] == "Task dependent"


def test_wbs_path(store):
    t = store.first.tasks.set_index("task_code")
    assert t.loc["E1010", "wbs_code"] == "ENG"
    assert t.loc["E1010", "wbs_l1"] == "ENG · Ingénierie"
    # siblings follow P6 seq_num (ENG before PRC before CIV), not the alphabet
    assert t.loc["E1010", "wbs_sort"] < t.loc["P2010", "wbs_sort"] < t.loc["C3010", "wbs_sort"]


# --- WBS paths: every lookup goes by wbs_id ----------------------------------------------------


def _node(wbs_id, parent, *, seq="1", root="N", proj="1", short=None):
    return {
        "wbs_id": wbs_id,
        "proj_id": proj,
        "wbs_short_name": short or wbs_id,
        "wbs_name": f"name {wbs_id}",
        "proj_node_flag": root,
        "parent_wbs_id": parent,
        "seq_num": seq,
    }


def _wbs_paths(nodes, task_wbs=()):
    """wbs_id -> (wbs_code, wbs_l1, wbs_sort) of the snapshot built on ``nodes``."""
    tasks = [todo(f"T{i}", wbs_id=w) for i, w in enumerate(task_wbs)] or [todo("T0")]
    s = build_snapshot(parse_text(xer_text(tasks, wbs=nodes), source="w.xer"))
    return {row.wbs_id: (row.wbs_code, row.wbs_l1, row.wbs_sort) for row in s.wbs.itertuples()}, s


def test_wbs_path_goes_by_id_not_by_short_name():
    """Three nodes share one short name, as P6 allows under different parents: each path is built
    from the node's own id up, so B (child of A) is S.S and C (child of the root) is S."""
    paths, _ = _wbs_paths(
        [_node("R", "", root="Y"), _node("A", "R", short="S"), _node("B", "A", short="S"), _node("C", "R", short="S")]
    )
    assert paths["A"] == ("S", "S · name A", "000001")
    assert paths["B"] == ("S.S", "S · name A", "000001.000001")
    assert paths["C"] == ("S", "S · name C", "000001")


def test_wbs_path_stops_at_the_project_node_and_sorts_by_seq_num():
    """The project node (proj_node_flag Y) is not part of the path; siblings sort by seq_num, so
    Z (seq 1) comes before A (seq 2) whatever their names."""
    paths, _ = _wbs_paths([_node("R", "", root="Y"), _node("Z", "R", seq="1"), _node("A", "R", seq="2")])
    assert paths["R"] == ("", "", "")
    assert paths["Z"][2] < paths["A"][2]


@pytest.mark.parametrize(
    ("case", "nodes", "expected"),
    [
        (
            "parent not in the file: the path stops at the last known node",
            [_node("R", "", root="Y"), _node("A", "GONE"), _node("B", "A")],
            {"A": "A", "B": "A.B"},
        ),
        (
            "parent in another project: not followed",
            [_node("R", "", root="Y"), _node("X", "", proj="2"), _node("A", "X")],
            {"A": "A"},
        ),
        (
            "no project node: the path runs to the top",
            [_node("A", ""), _node("B", "A"), _node("C", "B")],
            {"A": "A", "B": "A.B", "C": "A.B.C"},
        ),
        (
            "a node its own parent: one step, the walk does not spin",
            [_node("R", "", root="Y"), _node("A", "A")],
            {"A": "A"},
        ),
        (
            "two nodes each the other's parent: the walk stops on the first node seen twice",
            [_node("R", "", root="Y"), _node("A", "B"), _node("B", "A")],
            {"A": "B.A", "B": "A.B"},
        ),
    ],
)
def test_wbs_path_on_a_damaged_tree(case, nodes, expected):
    """P6 writes a tree under one project node; a hand-edited file may not. Each shape ends, in a
    path built from the ids that exist, and never reads a node of another project."""
    paths, _ = _wbs_paths(nodes)
    assert {wbs_id: paths[wbs_id][0] for wbs_id in expected} == expected, case


def test_a_wbs_loop_is_named_in_the_warnings():
    """P6 refuses a hierarchy loop (Oracle error reference PRM 009009044: "You cannot create a
    hierarchy loop"), so a loop comes from a damaged or hand-edited file. Its paths are then
    made up (A shows under B and B under A, neither under the project) and so are the groupings
    by top level: the loop is named, the file still loads. None of the 394 reference exports has one."""
    _, s = _wbs_paths([_node("R", "", root="Y"), _node("A", "B"), _node("B", "A"), _node("C", "R")])
    assert [w for w in s.warnings if "WBS" in w] == [
        "w.xer: WBS loop through ['A', 'B']: their paths and top levels are not reliable"
    ]
    _, s = _wbs_paths([_node("R", "", root="Y"), _node("A", "A")])  # its own parent: a loop of one
    assert [w for w in s.warnings if "WBS" in w] == [
        "w.xer: WBS loop through ['A']: their paths and top levels are not reliable"
    ]
    # a node leading into the loop is not part of it: only A and B are named
    _, s = _wbs_paths([_node("R", "", root="Y"), _node("A", "B"), _node("B", "A"), _node("D", "A")])
    assert [w for w in s.warnings if "WBS" in w] == [
        "w.xer: WBS loop through ['A', 'B']: their paths and top levels are not reliable"
    ]
    _, s = _wbs_paths([_node("R", "", root="Y"), _node("A", "R"), _node("B", "A")])
    assert not [w for w in s.warnings if "WBS" in w]


def test_an_activity_on_an_unknown_wbs_gets_no_path():
    """TASK.wbs_id naming no PROJWBS row: blank path, the activity is kept."""
    _, s = _wbs_paths([_node("R", "", root="Y"), _node("A", "R")], task_wbs=["A", "NOPE"])
    t = s.tasks.set_index("task_code")
    assert t.loc["T0", "wbs_code"] == "A" and t.loc["T1", "wbs_code"] == "" and len(t) == 2


def test_relationships_use_codes_and_days(store):
    r = store.first.relationships
    lead = r[(r["pred_code"] == "E1040") & (r["succ_code"] == "E1050")].iloc[0]
    assert lead["type"] == "FS"
    assert lead["lag_d"] == -3


def test_hard_constraint_flag(store):
    t = store.first.tasks.set_index("task_code")
    assert t.loc["X4050", "has_hard_constraint"]  # CS_MEOB = finish on or before
    assert not t.loc["P2040", "has_hard_constraint"]  # CS_MSOA = soft


def test_completed_tasks_have_no_float(store):
    t = store.latest.activities
    assert t.loc[t["is_complete"], "total_float_d"].isna().all()


def test_blank_data_date_falls_back_to_planned_start():
    xer = (
        "ERMHDR\t23.12\t2026-10-20\n"
        "%T\tPROJECT\n%F\tproj_id\tproj_short_name\tlast_recalc_date\tplan_start_date\n"
        "%R\t1\tP\t\t2026-09-01 08:00\n"
        "%T\tTASK\n%F\ttask_id\tproj_id\ttask_code\ttask_name\ttask_type\tstatus_code\n"
        "%R\t1\t1\tA\tA\tTT_Task\tTK_NotStart\n"
        "%E\n"
    )
    s = build_snapshot(parse_text(xer))
    assert s.data_date == pd.Timestamp("2026-09-01 08:00")
    assert s.data_date_source == "plan_start_date"


def _xer(project_extra: dict, sched: dict | None = None, tasks=None, preds=None):
    """Minimal XER text (see xerkit.xer_text); ``project_extra`` overrides PROJECT columns."""
    return xer_text(tasks or [], preds or (), project=project_extra, sched=sched)


TASKS = [  # A is critical by float and on the driving path, B is 40 h and C 48 h from critical
    {"task_code": "A", "clndr_id": "C8", "total_float_hr_cnt": "0", "driving_path_flag": "Y"},
    {"task_code": "B", "clndr_id": "C10", "total_float_hr_cnt": "40", "driving_path_flag": "N"},
    {"task_code": "C", "clndr_id": "C8", "total_float_hr_cnt": "48", "driving_path_flag": "Y"},
]


def test_critical_uses_project_float_threshold_in_hours():
    s = build_snapshot(
        parse_text(_xer({"critical_path_type": "CT_TotFloat", "critical_drtn_hr_cnt": "40"}, tasks=TASKS))
    )
    crit = s.activities.set_index("task_code")["is_critical"].to_dict()
    assert crit == {"A": True, "B": True, "C": False}  # 0 h, 40 h <= 40 h; 48 h > 40 h


def test_critical_can_be_longest_path():
    s = build_snapshot(
        parse_text(_xer({"critical_path_type": "CT_DrivPath", "critical_drtn_hr_cnt": "0"}, tasks=TASKS))
    )
    crit = s.activities.set_index("task_code")["is_critical"].to_dict()
    assert crit == {"A": True, "B": False, "C": True}  # driving_path_flag, not float


def test_options_keep_the_raw_project_fields_they_derive_from():
    """``options["project"]`` holds the PROJECT strings as written, "" when absent, so a page
    can tell a stored CT_TotFloat from the default one."""
    s = build_snapshot(
        parse_text(_xer({"critical_path_type": "CT_TotFloat", "critical_drtn_hr_cnt": "40"}, tasks=TASKS))
    )
    assert s.options["project"] == {
        "critical_path_type": "CT_TotFloat",
        "critical_drtn_hr_cnt": "40",
        "plan_end_date": "",
    }
    s = build_snapshot(parse_text(_xer({}, tasks=TASKS)))
    assert s.options["project"]["critical_path_type"] == "" and s.options["critical_path_type"] == "CT_TotFloat"


def test_scheduling_options_of_another_project_only_warn_that_p6_defaults_are_used():
    """SCHEDOPTIONS holds a row for project 1 (Actual Dates) and none for project 2: project 2
    is scheduled under P6's defaults (Retained Logic), and the file says so."""
    from xerkit import with_second_project

    text = with_second_project(
        xer_text([todo("A")], sched={"sched_retained_logic": "N", "sched_progress_override": "N"}),
        "B",
        ["X"],
        "2026-03-02 08:00",
    )
    first = build_snapshot(parse_text(text, source="t.xer"), project_code="T")
    assert first.options["progressed"] == "actual_dates"
    assert not any("SCHEDOPTIONS" in w for w in first.warnings)
    second = build_snapshot(parse_text(text, source="t.xer"), project_code="B")
    assert second.options["progressed"] == "retained_logic" and second.options["sched"] == {}
    assert "t.xer: SCHEDOPTIONS has no row for project B: P6's default scheduling options used" in second.warnings
    assert "has_schedoptions" not in second.options


def test_critical_defaults_to_zero_float_when_project_is_silent():
    s = build_snapshot(parse_text(_xer({}, tasks=TASKS)))
    assert s.activities.set_index("task_code")["is_critical"].to_dict() == {"A": True, "B": False, "C": False}


@pytest.mark.parametrize("setting", ["rcal_Predecessor", "rcal_Successor", "rcal_24Hour", "rcal_ProjDefault"])
def test_lag_days_use_the_predecessor_calendar_whatever_the_lag_calendar(setting):
    """Oracle (Schedule Options): "Lag entered in a unit other than hours is converted to
    hours based on the predecessor activity's calendar." The lag calendar option only
    decides where the CPM counts the lag (analysis/cpm.py)."""
    lag_days = 30 / 8  # pred A on C8
    xer = _xer(
        {},
        {"sched_calendar_on_relationship_lag": setting},
        tasks=TASKS,
        preds=[("A", "B", "FS", 30)],
    )
    s = build_snapshot(parse_text(xer))
    assert s.options["lag_calendar"] == setting
    assert s.relationships.loc[0, "lag_d"] == pytest.approx(lag_days)


def test_start_finish_follow_p6_columns_after_leveling():
    """Oracle: Start = actual start, else the remaining early start once scheduled; leveling
    moves the remaining early dates away from the early dates."""
    s = snap(
        [
            todo(
                "A",
                early_start_date="2026-03-02 08:00",
                early_end_date="2026-03-13 17:00",
                restart_date="2026-03-09 08:00",
                reend_date="2026-03-20 17:00",
            ),
            active(
                "B", early_start_date="2026-03-02 08:00", restart_date="2026-03-02 08:00", reend_date="2026-03-06 17:00"
            ),
        ]
    )
    a = s.activities.set_index("task_code")
    assert a.at["A", "start"] == pd.Timestamp("2026-03-09 08:00")
    assert a.at["A", "finish"] == pd.Timestamp("2026-03-20 17:00")
    assert a.at["B", "start"] == pd.Timestamp("2026-02-23 08:00")  # actual start
    assert a.at["B", "finish"] == pd.Timestamp("2026-03-06 17:00")


def test_parser_reports_rows_longer_than_their_header():
    raw = parse_text("ERMHDR\t23.12\n%T\tX\n%F\ta\tb\n%R\t1\t2\textra\n%R\t3\n", source="t.xer")
    assert raw.tables["X"].values.tolist() == [["1", "2"], ["3", ""]]
    assert any("more fields" in w for w in raw.warnings)


# --- minimal XERs: columns missing from a table ------------------------------------


def drop_column(text: str, table: str, column: str) -> str:
    """Remove one column from one table of an XER text (its %F field and every %R value)."""
    out, in_table, idx = [], False, -1
    for line in text.split("\n"):
        parts = line.split("\t")
        if parts[0] == "%T":
            in_table = parts[1] == table
        elif in_table and parts[0] == "%F":
            idx = parts.index(column) if column in parts else -1
            if idx >= 0:
                del parts[idx]
        elif in_table and parts[0] == "%R" and idx >= 0:
            del parts[idx]
        out.append("\t".join(parts))
    return "\n".join(out)


def _linked_text() -> str:
    return xer_text([active("A"), active("B"), active("C")], [("A", "B", "FS", 8), ("B", "C", "SS", 16)])


def _rels(s):
    return s.relationships[["pred_code", "succ_code", "type", "lag_hr", "is_external"]].values.tolist()


@pytest.mark.parametrize("column", ["proj_id", "pred_proj_id"])
def test_taskpred_without_project_column_is_derived(column):
    full = build_snapshot(parse_text(_linked_text(), source="t.xer"))
    s = build_snapshot(parse_text(drop_column(_linked_text(), "TASKPRED", column), source="t.xer"))
    assert _rels(s) == _rels(full) and len(s.relationships) == 2
    assert any(f"TASKPRED.{column} missing" in w for w in s.warnings)


def test_task_without_proj_id_takes_the_only_project():
    s = build_snapshot(parse_text(drop_column(_linked_text(), "TASK", "proj_id"), source="t.xer"))
    assert len(s.activities) == 3 and len(s.relationships) == 2
    assert any("TASK.proj_id missing" in w for w in s.warnings)


def test_task_without_proj_id_and_several_projects_raises():
    project_row = next(line for line in _linked_text().split("\n") if line.startswith("%R\t1\tT\t"))
    text = _linked_text().replace(project_row, f"{project_row}\n%R\t2\tU", 1)  # a second project, no task
    with pytest.raises(XerError, match=r"t\.xer.*TASK.*proj_id"):
        build_snapshot(parse_text(drop_column(text, "TASK", "proj_id"), source="t.xer"))


def test_task_without_task_code_raises_xer_error():
    with pytest.raises(XerError, match="table TASK has no column task_code"):
        build_snapshot(parse_text(drop_column(_linked_text(), "TASK", "task_code"), source="t.xer"))


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("TASK", "task_id"),
        ("TASK", "task_code"),
        ("TASK", "proj_id"),
        ("TASK", "status_code"),
        ("TASKPRED", "task_id"),
        ("TASKPRED", "pred_task_id"),
        ("TASKPRED", "proj_id"),
        ("TASKPRED", "pred_proj_id"),
        ("PROJECT", "proj_id"),
        ("PROJECT", "proj_short_name"),
        ("CALENDAR", "clndr_id"),
        ("PROJWBS", "proj_id"),
        ("PROJWBS", "wbs_id"),
        ("TASKRSRC", "task_id"),
    ],
)
def test_missing_column_never_leaks_a_key_error(table, column):
    text = xer_text(
        [active("A"), active("B")],
        [("A", "B", "FS", 0)],
        rsrc=["A"],
        wbs=[{"wbs_id": "10", "proj_id": "1", "wbs_short_name": "W", "wbs_name": "W", "proj_node_flag": "Y"}],
    )
    with contextlib.suppress(XerError):  # a clear XerError is fine, a KeyError is not
        build_snapshot(parse_text(drop_column(text, table, column), source="t.xer"))


def test_parser_keeps_only_the_tables_asked_for():
    text = xer_text([{"task_code": "A"}, {"task_code": "B"}])
    full, light = parse_text(text), parse_text(text, keep=HEADER_TABLES)
    assert set(light.tables) == {"PROJECT", "TASK"} < set(full.tables)
    assert light.table("PROJECT").equals(full.table("PROJECT"))
    task = full.table("TASK")  # projected columns stay in file order
    assert light.table("TASK").equals(task[[c for c in task.columns if c in ("task_id", "task_code", "proj_id")]])
    assert light.warnings == full.warnings


def _two_projects(main: dict, other: dict) -> str:
    """One file, two projects: ``main`` (proj_id 1, 3 tasks) and ``other`` (proj_id 2, 2 tasks)."""
    tasks = [{"task_code": c} for c in ("A1", "A2", "A3")]
    tasks += [{"task_code": c, "task_id": str(100 + i), "proj_id": "2"} for i, c in enumerate(("B1", "B2"))]
    text = xer_text(tasks, project=main)
    second = xer_text([], project={"proj_id": "2", **other}).splitlines()
    row = second[second.index("%T\tPROJECT") + 2]
    lines = text.splitlines()
    lines.insert(lines.index("%T\tPROJECT") + 3, row)
    return "\n".join(lines) + "\n"


HEADER_CASES = {
    "one project": xer_text([{"task_code": "A"}], data_date="2026-03-02 08:00"),
    "no recalc date": xer_text(
        [{"task_code": "A"}], project={"last_recalc_date": "", "plan_start_date": "2026-01-05 08:00"}
    ),
    "two projects": _two_projects(
        {"proj_short_name": "UPD"}, {"proj_short_name": "BL", "last_recalc_date": "2025-12-01 08:00"}
    ),
}


def _same_as_snapshot(raw_full, raw_light):
    header, snapshot = read_header(raw_light), build_snapshot(raw_full)
    assert (header.project_code, header.selected_by, header.project_task_counts) == (
        snapshot.project_code,
        snapshot.selected_by,
        snapshot.project_task_counts,
    )
    assert (header.data_date, header.data_date_source) == (snapshot.data_date, snapshot.data_date_source)
    return header


@pytest.mark.parametrize("case", HEADER_CASES)
def test_header_takes_what_build_snapshot_takes(case):
    text = HEADER_CASES[case]
    header = _same_as_snapshot(parse_text(text, source=case), parse_text(text, source=case, keep=HEADER_TABLES))
    if case == "two projects":
        assert header.project_task_counts == {"1": 3, "2": 2} and header.selected_by == "most TASK rows"
        assert header.project_codes == {"1": "UPD", "2": "BL"}
    if case == "no recalc date":
        assert header.data_date_source == "plan_start_date"


def _default(text: str):
    snapshot = build_snapshot(parse_text(text, source="two.xer"))
    return snapshot.project_id, snapshot.selected_by


def test_a_baseline_copy_with_as_many_activities_is_not_the_default():
    from file_projects import two_projects

    # project 2 is named by project 1's sum_base_proj_id and copied from it (orig_proj_id)
    text = two_projects(baseline_date="2026-03-02 08:00")
    assert _default(text) == ("1", "only project not a baseline copy")


def test_a_baseline_copy_with_more_activities_and_the_same_code_is_not_the_default():
    from file_projects import two_projects

    text = two_projects(baseline_code="UPD", baseline_ids=("A1", "A2", "A3"), baseline_date="2026-03-02 08:00")
    assert _default(text) == ("1", "only project not a baseline copy")
    chosen = build_snapshot(parse_text(text, source="two.xer"), project_code="UPD")
    assert (chosen.project_id, chosen.selected_by) == ("1", "chosen")


def test_a_copy_named_only_by_orig_proj_id_is_set_aside():
    from file_projects import two_projects

    text = two_projects(pointer="", baseline_ids=("A1", "A2", "A3"), baseline_date="2026-03-02 08:00")
    assert _default(text)[0] == "1"


def test_of_two_unrelated_projects_the_most_tasks_win():
    from file_projects import two_projects

    # project 2 has a later data date but fewer activities (a small project of the portfolio)
    text = two_projects(pointer="", original="", baseline_ids=("B1",), baseline_date="2026-03-09 08:00")
    assert _default(text) == ("1", "most TASK rows")


def test_as_many_tasks_then_latest_data_date_then_file_order():
    from file_projects import two_projects

    text = two_projects(pointer="", original="", baseline_ids=("B1", "B2"), baseline_date="2026-03-09 08:00")
    assert _default(text) == ("2", "latest data date")
    text = two_projects(pointer="", original="", baseline_ids=("B1", "B2"), baseline_date="2026-03-02 08:00")
    assert _default(text) == ("1", "first in file")


def test_when_every_project_is_a_baseline_copy_the_most_tasks_win():
    from file_projects import two_projects

    # each names the other: no project is left, the old rule applies (TASK rows, then file order)
    text = two_projects(original="", baseline_ids=("B1", "B2", "B3"), baseline_date="2026-03-02 08:00")
    lines = text.splitlines()
    at = lines.index("%T\tPROJECT")
    fields = lines[at + 1].split("\t")[1:]
    for i in (at + 2, at + 3):
        row = dict(zip(fields, lines[i].split("\t")[1:], strict=True))
        row["sum_base_proj_id"] = "2" if row["proj_id"] == "1" else "1"
        lines[i] = "%R\t" + "\t".join(row[f] for f in fields)
    assert _default("\n".join(lines) + "\n") == ("2", "most TASK rows, every project a baseline copy")


def test_header_matches_build_snapshot_on_sample_and_reference_files(sample_dir):
    from reference.sources import FILES

    data = Path(__file__).parent / "reference" / "data"
    paths = xer_files(sample_dir) + [data / name for name in FILES if (data / name).suffix.lower() == ".xer"]
    checked = 0
    for path in paths:
        if not path.exists():
            continue
        try:
            full = read_xer(path)
            build_snapshot(full)
        except XerError:
            with pytest.raises(XerError):
                read_header(read_xer(path, keep=HEADER_TABLES))
            continue
        _same_as_snapshot(full, read_xer(path, keep=HEADER_TABLES))
        checked += 1
    assert checked >= len(xer_files(sample_dir))


# --- P6 activity codes (ACTVTYPE, ACTVCODE, TASKACTV) ----------------------------------------

CODES = [
    ("A", "Zone", "B1/L1"),
    ("A", "Discipline", "CIV"),
    ("B", "Zone", "B1/L2"),
    ("C", "Zone", "B2"),
    ("C", "Discipline", "MEC"),
]


def _value_id(s, code_type: str, value: str) -> str:
    values = s.code_values
    return values[(values["code_type"] == code_type) & (values["value"] == value)]["code_id"].iloc[0]


def test_activity_codes_are_read_per_activity_with_their_hierarchy():
    s = snap([todo("A"), todo("B"), todo("C"), todo("D")], codes=CODES)
    assert sorted(s.code_values["code_type"].unique()) == ["Discipline", "Zone"]
    zone = s.code_values[s.code_values["code_type"] == "Zone"].set_index("value")
    assert zone.loc["L1", "parent_id"] == zone.loc["B1", "code_id"] and zone.loc["B1", "parent_id"] == ""
    assert sorted(map(tuple, s.task_codes[["task_code", "code_type"]].to_numpy())) == [
        ("A", "Discipline"), ("A", "Zone"), ("B", "Zone"), ("C", "Discipline"), ("C", "Zone"),
    ]  # fmt: skip


def test_a_code_value_selects_the_activities_assigned_that_exact_value():
    # as P6's "equals": a parent value does not take the activities of its sub-values
    s = snap([todo("A"), todo("B"), todo("C"), todo("D")], codes=CODES)
    assert s.tasks_with_codes("Zone", [_value_id(s, "Zone", "L1")]) == {"A"}
    assert s.tasks_with_codes("Zone", [_value_id(s, "Zone", "B1")]) == set()  # B1 holds L1, L2: none is B1 itself
    assert s.tasks_with_codes("Discipline", [_value_id(s, "Discipline", v) for v in ("CIV", "MEC")]) == {"A", "C"}
    assert s.tasks_with_codes("Zone", []) == set()


def test_a_file_without_activity_codes_has_none():
    s = snap([todo("A")])
    assert s.code_values.empty and s.task_codes.empty
    assert s.tasks_with_codes("Zone", ["7000"]) == set()


@pytest.mark.parametrize(("code", "name"), [("", "blank"), ("TK_Suspended", "'TK_Suspended'")])
def test_unknown_status_code_warns_and_reads_as_started(code, name):
    s = snap([todo("A", status_code=code), todo("B", status_code=code), todo("C")])
    assert [w for w in s.warnings if "status_code" in w] == [
        f"test.xer: TASK.status_code {name} is not a P6 code (2 rows): read as started"
    ]
    assert s.tasks.set_index("task_code")["is_started"].to_dict() == {"A": True, "B": True, "C": False}


def test_p6_status_codes_do_not_warn():
    s = snap([todo("A"), active("B"), done("C")])
    assert not [w for w in s.warnings if "not a P6 code" in w]


def test_unknown_percent_complete_type_warns_and_reads_as_physical():
    """Oracle names a fourth type, Scope (from Oracle Primavera Cloud; its XER code is not
    documented): any code but CP_Phys / CP_Drtn / CP_Units reads the physical %, and says so."""
    s = snap(
        [todo("A", complete_pct_type="CP_Scope", phys_complete_pct="30"), todo("B"), todo("C", complete_pct_type="")]
    )
    assert [w for w in s.warnings if "complete_pct_type" in w] == [
        "test.xer: TASK.complete_pct_type 'CP_Scope' is not a P6 code (1 row): % complete read as Physical"
    ]
    assert s.tasks.set_index("task_code").at["A", "pct_complete"] == 30.0


def test_unknown_task_type_warns_once_per_code():
    s = snap([todo("A", task_type="TT_TASK"), todo("B", task_type="TT_TASK"), todo("C", task_type="TT_X"), todo("D")])
    assert [w for w in s.warnings if "task_type" in w] == [
        "test.xer: TASK.task_type 'TT_TASK' is not a P6 code (2 rows): read as Task Dependent",
        "test.xer: TASK.task_type 'TT_X' is not a P6 code (1 row): read as Task Dependent",
    ]
    assert not s.tasks[["is_milestone", "is_loe", "is_wbs_summary"]].any().any()


def test_unknown_pred_type_warns_and_keeps_its_code():
    s = snap([todo("A"), todo("B"), todo("C")], [("A", "B", "FS", 0), ("B", "C", "XX", 0)])
    assert [w for w in s.warnings if "pred_type" in w] == [
        "test.xer: TASKPRED.pred_type 'PR_XX' is not a P6 code (1 row): "
        "kept with its code, ignored by the recalculation"
    ]
    assert sorted(s.relationships["type"]) == ["FS", "PR_XX"]


def test_taskrsrc_without_task_id_raises_xer_error():
    text = xer_text([todo("A")], rsrc=["A"])
    with pytest.raises(XerError, match="table TASKRSRC has no column task_id"):
        build_snapshot(parse_text(drop_column(text, "TASKRSRC", "task_id"), source="t.xer"))


def test_blank_task_units_fall_back_to_assignments_column_by_column():
    s = snap(
        [todo("A", target_work_qty="40"), todo("B"), todo("C"), todo("D", act_work_qty="5")],
        rsrc=["A", "B", "D"],
    )
    assert s.options["labor_source"] == "TASK+TASKRSRC"
    labour = s.activities.set_index("task_code")[["labor_budget_hr", "labor_actual_hr"]]
    assert labour.to_dict("index") == {
        "A": {"labor_budget_hr": 40, "labor_actual_hr": 0},
        "B": {"labor_budget_hr": 80, "labor_actual_hr": 0},
        "C": {"labor_budget_hr": 0, "labor_actual_hr": 0},
        "D": {"labor_budget_hr": 80, "labor_actual_hr": 5},
    }


def test_blank_task_units_without_assignments_are_zero():
    s = snap([todo("A", target_work_qty="40"), todo("B", act_work_qty="5")])
    assert s.options["labor_source"] == "TASK"
    labour = s.activities.set_index("task_code")[["labor_budget_hr", "labor_actual_hr"]]
    assert labour.to_dict("index") == {
        "A": {"labor_budget_hr": 40, "labor_actual_hr": 0},
        "B": {"labor_budget_hr": 0, "labor_actual_hr": 5},
    }
