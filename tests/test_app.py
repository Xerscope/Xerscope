"""Smoke test of the Streamlit UI: every page renders, key options don't crash.

Uses Streamlit's headless AppTest, so it runs the same on Linux, Windows and macOS
without a browser. It checks that pages run; the numbers are tested elsewhere.
"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from xerkit import xer_text

import xerscope

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
PAGES = [
    "views/overview.py",
    "views/gantt.py",
    "views/activity.py",
    "views/health.py",
    "views/changelog.py",
    "views/earned_value.py",
    "views/milestones.py",
    "views/ppc.py",
    "views/export.py",
]


@pytest.fixture
def app(sample_dir, monkeypatch):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    return AppTest.from_file(APP, default_timeout=120).run()


def _ok(at):
    assert not at.exception, [e.value for e in at.exception]


def test_every_page_renders(app):
    _ok(app)
    for page in PAGES:
        app.switch_page(page).run()
        _ok(app)
        assert app.title, f"{page} rendered no title"


def _gantt_data(at) -> dict:
    """The rows and options the Gantt page hands to its component."""
    page = at.get("iframe")[0].proto.srcdoc
    return json.loads(page.split("const DATA = ")[1].split(";</script>")[0])


def _toggle(at, label: str, value: bool) -> None:
    next(toggle for toggle in at.toggle if toggle.label == label).set_value(value).run()
    _ok(at)


def test_gantt_wbs_choice_filters_and_options(app):
    app.switch_page("views/gantt.py").run()
    _ok(app)
    data = _gantt_data(app)
    tasks = [r for r in data["rows"] if r["kind"] == "task"]
    assert data["rows"][0]["id"] == "w:__project__" and data["open"] == ["w:__project__"]
    assert {r["code"] for r in tasks} >= {"C3020", "M9999"} and data["links"] == []
    app.selectbox(key="gantt_node").set_value("7003").run()  # demo WBS "CIV"
    _ok(app)
    data = _gantt_data(app)
    assert data["rows"][0]["id"] == "w:7003" and data["selected"] == "w:7003"
    assert {r["code"][0] for r in data["rows"] if r["kind"] == "task"} <= {"C", "M"}  # CIV only
    assert any(m.label == "Focus" and m.value == "CIV" for m in app.metric)
    _toggle(app, "Logic links", True)
    assert _gantt_data(app)["links"]
    app.multiselect[0].set_value(["Not started", "In progress", "Complete"]).run()
    assert _gantt_data(app)["open"] == ["w:7003"]  # every status ticked: nothing filtered, nothing opened
    app.multiselect[0].set_value([]).run()
    app.text_input[0].set_value("earthworks").run()  # a search opens every branch on the matches
    data = _gantt_data(app)
    assert [r["code"] for r in data["rows"] if r["kind"] == "task"] == ["C3020"]
    assert set(data["open"]) == {r["id"] for r in data["rows"] if r["kind"] == "wbs"}
    app.get("button_group")[0].set_value("Week").run()
    assert _gantt_data(app)["timescale"] == "week"
    app.selectbox(key="gantt_cmp").set_value("Baseline (BL)").run()
    first = app.selectbox(key="gantt_snap").options[0]
    app.selectbox(key="gantt_snap").set_value(first).run()
    _ok(app)


@pytest.mark.parametrize("std", ["P6", "DCMA", "INTEGRITY"])
@pytest.mark.parametrize("baseline", ["Planned dates in each file (target_*)", "None"])
def test_health_standards_and_baselines(app, std, baseline):
    app.sidebar.selectbox(key="bl_choice").set_value(baseline).run()
    app.switch_page("views/health.py").run()
    app.get("button_group")[0].set_value(std).run()  # segmented control
    _ok(app)
    assert app.dataframe[0].value["status"].notna().all()


def test_health_lists_culprits_of_every_check(app):
    app.switch_page("views/health.py").run()
    app.get("button_group")[0].set_value("P6").run()
    _ok(app)
    summary = app.dataframe[0].value
    listed = summary.loc[summary["flagged"] > 0]
    # one table per check that flags something, holding exactly the flagged items
    tables = {e.label.split(" · ")[0].split()[-1]: e for e in app.expander if "target" in e.label}
    for _, row in listed.iterrows():
        frames = tables[row["id"]].dataframe
        assert frames and len(frames[-1].value) == row["flagged"], row["id"]


def test_earned_value_needs_hours_and_baseline(app):
    app.switch_page("views/earned_value.py").run()
    _ok(app)
    assert app.metric[0].label == "EV %"
    app.sidebar.selectbox(key="bl_choice").set_value("None").run()
    _ok(app)
    assert any("Choose a baseline" in i.value for i in app.info)


def test_changelog_and_ppc_pick_weeks(app):
    app.switch_page("views/changelog.py").run()
    labels = app.selectbox(key="cl_new").options
    app.selectbox(key="cl_old").set_value(labels[3]).run()
    app.selectbox(key="cl_new").set_value(labels[4]).run()
    _ok(app)
    app.switch_page("views/ppc.py").run()
    app.selectbox(key="ppc_week").set_value(app.selectbox(key="ppc_week").options[2]).run()
    _ok(app)


def test_empty_state_explains_what_to_do(monkeypatch):
    monkeypatch.delenv("XERSCOPE_DATA", raising=False)
    at = AppTest.from_file(APP, default_timeout=60).run()
    _ok(at)
    assert any("xerscope sample" in i.value for i in at.info)


def _run(data_dir, monkeypatch, baseline=None):
    monkeypatch.setenv("XERSCOPE_DATA", str(data_dir))
    if baseline is None:
        monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    else:
        monkeypatch.setenv("XERSCOPE_BASELINE", str(baseline))
    return AppTest.from_file(APP, default_timeout=120).run()


def test_one_snapshot_renders_every_page(sample_dir, tmp_path, monkeypatch):
    """Series pages (PPC, trend, earned value) need two updates; with one they say so."""
    first = sorted(sample_dir.glob("*.xer"))[0]
    (tmp_path / first.name).write_bytes(first.read_bytes())
    at = _run(tmp_path, monkeypatch)
    _ok(at)
    for page in PAGES:
        at.switch_page(page).run()
        _ok(at)


def test_baseline_file_from_env_and_its_date_check(sample_dir, tmp_path, monkeypatch):
    files = sorted(sample_dir.glob("*.xer"))
    for f in files[:3]:
        (tmp_path / f.name).write_bytes(f.read_bytes())
    # the first export as the baseline: read, named in the sidebar, no warning
    at = _run(tmp_path, monkeypatch, baseline=files[0])
    _ok(at)
    assert at.sidebar.selectbox(key="bl_choice").value == "Separate baseline file"
    assert any(files[0].stem in c.value and "labour h" in c.value for c in at.sidebar.caption)
    assert not at.sidebar.warning
    # the last export as the baseline: newer than every loaded update
    at = _run(tmp_path, monkeypatch, baseline=files[-1])
    _ok(at)
    assert any("after the first update" in w.value for w in at.sidebar.warning)


def test_same_data_date_twice_is_one_update(sample_dir, tmp_path, monkeypatch):
    files = sorted(sample_dir.glob("*.xer"))
    for f in files[:2]:
        (tmp_path / f.name).write_bytes(f.read_bytes())
    (tmp_path / "zz-copy.xer").write_bytes(files[0].read_bytes())
    at = _run(tmp_path, monkeypatch)
    _ok(at)
    assert any("2 snapshot(s)" in c.value for c in at.sidebar.caption)
    assert any("same data date" in w.value for w in at.warning)


def test_folder_not_found_clears_the_data(sample_dir, monkeypatch):
    at = _run(sample_dir / "missing", monkeypatch)
    _ok(at)
    assert any("Folder not found" in e.value for e in at.sidebar.error)
    assert any("xerscope sample" in i.value for i in at.info)


def _with_baseline_file_choice(at):
    at.sidebar.selectbox(key="bl_choice").set_value(at.sidebar.selectbox(key="bl_choice").options[0]).run()
    _ok(at)
    return at


def test_locked_folder_gives_the_visitor_no_path_field_and_no_upload(sample_dir, monkeypatch):
    """Remote deployment (XERSCOPE_DATA_LOCKED): the server's folder is read, no field can point
    elsewhere and nothing can be uploaded (exports and baseline: each parsed one costs memory)."""
    monkeypatch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
    at = _with_baseline_file_choice(_run(sample_dir, monkeypatch))
    assert "…or read a folder" in [t.label for t in at.sidebar.text_input]
    assert len(at.get("file_uploader")) == 2  # exports and baseline
    monkeypatch.setenv("XERSCOPE_DATA_LOCKED", "true")
    at = _with_baseline_file_choice(_run(sample_dir, monkeypatch))
    assert "…or read a folder" not in [t.label for t in at.sidebar.text_input]
    assert len(at.get("file_uploader")) == 0
    assert any("8 snapshot(s)" in c.value for c in at.sidebar.caption)
    assert any("No baseline file on this server" in c.value for c in at.sidebar.caption)


def test_a_new_session_reuses_nothing_parsed_by_another(sample_dir, monkeypatch):
    """Parsed files live in their session only: once it ends, nothing of them stays in the process."""
    from xerscope.app import state

    calls = []
    real = state.load_snapshot

    def counting(data, **kwargs):
        calls.append(kwargs.get("name"))
        return real(data, **kwargs)

    monkeypatch.setattr(state, "load_snapshot", counting)
    first = _run(sample_dir, monkeypatch)
    _ok(first)
    parsed_once = len(calls)
    assert parsed_once == 8  # the eight demo weeks
    second = _run(sample_dir, monkeypatch)  # another browser session, same files
    _ok(second)
    assert len(calls) == 2 * parsed_once


def test_folder_files_can_be_picked(sample_dir, monkeypatch):
    """Every XER of the folder is read by default; unticking files leaves them out of the series."""
    at = _run(sample_dir, monkeypatch)
    _ok(at)
    picker = next(m for m in at.sidebar.multiselect if m.label == "Files to read")
    assert len(picker.value) == 8
    picker.set_value(picker.value[:3]).run()
    _ok(at)
    assert any("3 snapshot(s)" in c.value for c in at.sidebar.caption)


def _with_second_project(main: str, code: str, task_codes: list[str], data_date: str) -> str:
    """``main`` plus a second PROJECT (proj_id 2) owning ``task_codes``, as P6 writes a file
    exported with a baseline copy or a second project."""
    extra = xer_text(
        [{"task_code": c, "task_id": str(100 + i), "proj_id": "2"} for i, c in enumerate(task_codes)],
        data_date=data_date,
        project={"proj_id": "2", "proj_short_name": code},
    ).splitlines()
    project_row = extra[extra.index("%T\tPROJECT") + 2]
    task_rows = [line for line in extra[extra.index("%T\tTASK") + 2 :] if line.startswith("%R")]
    lines = main.splitlines()
    lines.insert(lines.index("%T\tPROJECT") + 3, project_row)
    end = lines.index("%T\tTASK") + 2
    while end < len(lines) and lines[end].startswith("%R"):
        end += 1
    lines[end:end] = task_rows
    return "\n".join(lines) + "\n"


@pytest.fixture
def renamed_project(tmp_path):
    """Week 1 holds project NEW plus a second project OLD; week 2 holds NEW only."""
    tasks = [{"task_code": c} for c in ("A1", "A2", "A3")]
    week1 = xer_text(tasks, data_date="2026-03-02 08:00", project={"proj_short_name": "NEW"})
    (tmp_path / "w1.xer").write_text(_with_second_project(week1, "OLD", ["A1", "A2"], "2026-03-02 08:00"))
    (tmp_path / "w2.xer").write_text(xer_text(tasks, data_date="2026-03-09 08:00", project={"proj_short_name": "NEW"}))
    return tmp_path


def _pick_project(at, code: str) -> None:
    next(box for box in at.sidebar.selectbox if box.label == "Project").set_value(code).run()


def test_project_choice_applies_to_the_files_that_hold_it(renamed_project, monkeypatch):
    """A project in one file only: the other files keep their own project, none is rejected."""
    at = _run(renamed_project, monkeypatch)
    _ok(at)
    _pick_project(at, "OLD")
    _ok(at)
    assert not at.sidebar.error
    store = at.session_state["store"]
    assert [s.project_code for s in store] == ["OLD", "NEW"]
    assert [len(s.activities) for s in store] == [2, 3]


def test_switching_project_recomputes_cached_tables(renamed_project, monkeypatch):
    """Analyses cached for one project are not served for another."""
    at = _run(renamed_project, monkeypatch)
    at.switch_page("views/export.py").run()
    _ok(at)
    _pick_project(at, "OLD")
    _ok(at)
    exported = [list(v["dim_snapshot"]["project"]) for k, v in at.session_state["_memo"].items() if k[-1] == "export"]
    assert ["OLD", "NEW"] in exported


def _selection(at):
    return next(frame for frame in at.sidebar.dataframe).value


def test_selection_panel_shows_each_file_its_project_and_why(renamed_project, monkeypatch):
    """w1 holds NEW (3 TASK rows) and OLD (2): NEW wins on TASK rows; w2 holds NEW only."""
    at = _run(renamed_project, monkeypatch)
    _ok(at)
    table = _selection(at).set_index("file")
    assert table.loc["w1.xer", ["project", "selected_by", "projects_in_file", "status"]].tolist() == [
        "NEW",
        "most TASK rows",
        "NEW (3) · OLD (2)",
        "in series",
    ]
    assert table.loc["w2.xer", ["project", "selected_by"]].tolist() == ["NEW", "only project"]
    _pick_project(at, "OLD")
    _ok(at)
    table = _selection(at).set_index("file")
    assert table.loc["w1.xer", ["project", "selected_by", "activities"]].tolist() == ["OLD", "chosen", 2]
    assert table.loc["w2.xer", "project"] == "NEW"


def test_selection_panel_names_the_file_skipped_for_its_data_date(tmp_path, monkeypatch):
    """Two planners, same data date: the second by name is out of the series, and says why."""
    tasks = [{"task_code": c} for c in ("A1", "A2")]
    for name, code in (("a.xer", "PLAN-A"), ("b.xer", "PLAN-B")):
        (tmp_path / name).write_text(xer_text(tasks, data_date="2026-03-02 08:00", project={"proj_short_name": code}))
    at = _run(tmp_path, monkeypatch)
    _ok(at)
    table = _selection(at).set_index("file")
    assert table.loc["a.xer", "status"] == "in series"
    assert table.loc["b.xer", ["project", "status", "reason"]].tolist() == [
        "PLAN-B",
        "skipped",
        "same data date as a.xer",
    ]
