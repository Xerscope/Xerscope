"""Smoke test of the Streamlit UI: every page renders, key options don't crash.

Uses Streamlit's headless AppTest, so it runs the same on Linux, Windows and macOS
without a browser. It checks that pages run; test_app_parity.py checks that they show the analyses' numbers.
"""

import json
from pathlib import Path

import pandas as pd
import pytest
from conftest import P6_CORPUS_HINT, missing
from streamlit.testing.v1 import AppTest
from xerkit import xer_text

import xerscope
from xerscope.app import ui

APP = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
PAGES = [
    "views/overview.py",
    "views/gantt.py",
    "views/activity.py",
    "views/health.py",
    "views/audit.py",
    "views/changelog.py",
    "views/earned_value.py",
    "views/milestones.py",
    "views/ppc.py",
    "views/export.py",
    "views/debug.py",
]


@pytest.fixture
def app(sample_dir, monkeypatch):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    return _tick_all(AppTest.from_file(APP, default_timeout=120).run())


def _file_boxes(at):
    return [box for box in at.sidebar.checkbox if box.key.startswith("read:")]


def _tick_all(at):
    """Nothing is read until files are ticked: tick every file of the folder."""
    for box in _file_boxes(at):
        box.check()
    return at.run()


def test_file_list_stays_open_while_files_are_ticked(sample_dir, monkeypatch):
    # The expander label holds the tick count. Keyed on its label, Streamlit would redraw it as a
    # new, closed expander at every tick; a fixed key keeps the one the user opened.
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    at = AppTest.from_file(APP, default_timeout=120).run()
    before = at.sidebar.expander[0]
    _file_boxes(at)[0].check()
    at.run()
    after = at.sidebar.expander[0]
    assert before.label != after.label  # "0 of 8 ticked" -> "1 of 8 ticked"
    assert before.key is not None and after.key == before.key


def test_widget_keys_do_not_show_the_folder_path(sample_dir, monkeypatch):
    # A widget key is written into the page as a CSS class (st-key-...). On the remote image the
    # folder is the server's and the visitor never sees it (_data_locked), so no key may hold it.
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.setenv("XERSCOPE_DATA_LOCKED", "1")
    at = _tick_all(AppTest.from_file(APP, default_timeout=120).run())
    keys = [element.key for element in [*at.sidebar.checkbox, *at.sidebar.expander] if element.key]
    assert len(_file_boxes(at)) == len(list(sample_dir.glob("*.xer")))
    assert keys and not [key for key in keys if str(sample_dir) in key]


def _ok(at):
    assert not at.exception, [e.value for e in at.exception]


def test_every_page_renders(app):
    _ok(app)
    for page in PAGES:
        app.switch_page(page).run()
        _ok(app)
        assert app.title, f"{page} rendered no title"


def _gantt_data(at) -> dict:
    """The Gantt component's data, as the browser receives it."""
    return json.loads(at.get("bidi_component")[0].proto.json)


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


def test_health_compares_counts_typed_from_a_p6_report(app):
    app.switch_page("views/health.py").run()
    app.get("button_group")[0].set_value("P6").run()

    def report():
        return next(u for u in app.file_uploader if u.key == "report_csv_P6")

    report().set_value(("report.csv", b"id,found,total\nP6-01,99999,99999\n", "text/csv")).run()
    _ok(app)
    assert [e.value for e in app.error] == ["1 of 1 checks differ from the report"]
    compared = next(d.value for d in app.dataframe if "match" in d.value.columns)
    row = compared.iloc[0]  # xerscope's own counts, typed back as the report
    text = f"id,found,total\nP6-01,{row['found']},{row['total']}\n".encode()
    report().set_value(("report.csv", text, "text/csv")).run()
    _ok(app)
    assert not app.error and [s.value for s in app.success] == ["All 1 checks match the report"]


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
    return _tick_all(AppTest.from_file(APP, default_timeout=120).run())


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


def test_same_data_date_twice_is_refused(sample_dir, tmp_path, monkeypatch):
    """No series is built while two ticked files share a data date: the user unticks one."""
    files = sorted(sample_dir.glob("*.xer"))
    for f in files[:2]:
        (tmp_path / f.name).write_bytes(f.read_bytes())
    (tmp_path / "zz-copy.xer").write_bytes(files[0].read_bytes())
    at = _run(tmp_path, monkeypatch)
    _ok(at)
    assert any(f"{files[0].name}, zz-copy.xer" in e.value and "Untick" in e.value for e in at.sidebar.error)
    assert not any("snapshot(s)" in c.value for c in at.sidebar.caption)


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
    """No file is read until ticked; only the ticked files enter the series."""
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = AppTest.from_file(APP, default_timeout=120).run()
    _ok(at)
    boxes = _file_boxes(at)
    assert len(boxes) == 8 and not any(box.value for box in boxes)
    assert "store" not in at.session_state or at.session_state["store"] is None
    assert any("Tick at least one file" in i.value for i in at.sidebar.info)
    for box in boxes[:3]:
        box.check()
    at.run()
    _ok(at)
    assert any("3 snapshot(s)" in c.value for c in at.sidebar.caption)
    assert len(_selection(at)) == 3  # unticked files are not read at all


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
    assert table.loc["w1.xer", ["project", "selected_by", "projects_in_file"]].tolist() == [
        "NEW",
        "most TASK rows",
        "NEW (3) · OLD (2)",
    ]
    assert table.loc["w2.xer", ["project", "selected_by", "data_date_from"]].tolist() == [
        "NEW",
        "only project",
        "last_recalc_date",
    ]
    _pick_project(at, "OLD")
    _ok(at)
    table = _selection(at).set_index("file")
    assert table.loc["w1.xer", ["project", "selected_by", "activities"]].tolist() == ["OLD", "chosen", 2]
    assert table.loc["w2.xer", "project"] == "NEW"


def test_file_boxes_describe_each_file_before_it_is_read(renamed_project, monkeypatch):
    """Unticked files are described from PROJECT and TASK only: default project, data date,
    projects in the file; none of them is parsed into a snapshot."""
    monkeypatch.setenv("XERSCOPE_DATA", str(renamed_project))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = AppTest.from_file(APP, default_timeout=120).run()
    _ok(at)
    boxes = {box.key.rsplit(":", 1)[1]: box for box in _file_boxes(at)}
    assert boxes["w1.xer"].label == "w1.xer — NEW · 02 Mar 2026 · 2 projects"
    assert boxes["w2.xer"].label == "w2.xer — NEW · 09 Mar 2026"
    assert "NEW (3) · OLD (2)" in boxes["w1.xer"].help and "most TASK rows" in boxes["w1.xer"].help
    assert "from last_recalc_date" in boxes["w2.xer"].help
    assert "_parsed" not in at.session_state or not at.session_state["_parsed"]


def test_unreadable_file_is_named_in_the_picker(tmp_path, monkeypatch):
    (tmp_path / "broken.xer").write_text("ERMHDR\t23.12\t2026-03-02\n%T\tPROJECT\n%F\tproj_id\n%R\t1\n")
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = AppTest.from_file(APP, default_timeout=120).run()
    _ok(at)
    (box,) = _file_boxes(at)
    assert box.label == "broken.xer — unreadable" and "TASK table missing" in box.help


@pytest.fixture
def downloads(monkeypatch):
    """Every file the app hands to a download button, by its media id (AppTest keeps them in memory)."""
    from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage

    saved: dict[str, bytes] = {}
    real = MemoryMediaFileStorage.load_and_get_id

    def keep(self, path_or_data, mimetype, kind, filename=None):
        file_id = real(self, path_or_data, mimetype, kind, filename)
        saved[file_id] = self._files_by_id[file_id].content
        return file_id

    monkeypatch.setattr(MemoryMediaFileStorage, "load_and_get_id", keep)
    return saved


def _download(at, downloads: dict[str, bytes], label: str) -> bytes:
    button = next(b for b in at.get("download_button") if b.proto.label == label)
    return downloads[button.proto.url.rsplit("/", 1)[-1].split(".")[0]]


def test_flagged_lists_and_xer_leave_the_app_anonymised_only(app, store, downloads):
    """No download names an activity of the loaded files; the lists and the XER extract share the new IDs."""
    import io
    import zipfile

    import pandas as pd

    from xerscope.xer import load_snapshot

    originals = set(store.history["task_code"]) | set(store.history["task_name"])
    app.switch_page("views/health.py").run()
    app.get("button_group")[0].set_value("P6").run()
    _ok(app)
    assert [b.proto.label for b in app.get("download_button")] == ["Summary (CSV)", "Download the template"]
    next(b for b in app.button if b.label == "Prepare anonymised downloads").click().run()
    _ok(app)
    flagged = pd.read_csv(
        io.BytesIO(_download(app, downloads, "All flagged items (CSV) · anonymised")), encoding="utf-8-sig"
    )
    assert not set(flagged.astype(str).to_numpy().ravel()) & originals
    codes = pd.concat([flagged[column].dropna() for column in ("task_code", "pred_code", "succ_code")])
    assert len(codes) and codes.str.fullmatch(r"XA[0-9A-F]{8}").all()

    app.switch_page("views/export.py").run()
    next(b for b in app.button if b.label == "Build anonymised extract").click().run()
    _ok(app)
    with zipfile.ZipFile(io.BytesIO(_download(app, downloads, "Download anonymised XER (.zip)"))) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    assert len(files) == len(store)
    for name, data in files.items():
        text = data.decode("utf-8")
        assert not [value for value in originals if len(value) >= 4 and value in text], name
    latest = load_snapshot(files[max(files)], name="latest.xer")
    assert set(codes) <= set(latest.activities["task_code"])


HELD_OUT_CASE = (
    Path(__file__).parent
    / "reference"
    / "data"
    / "p6-heldout"
    / "validation"
    / "held-out"
    / "H1"
    / "cases"
    / "H1-02.xer"
)


def _debug_zip(at, downloads) -> dict[str, pd.DataFrame]:
    import io
    import zipfile

    at.switch_page("views/debug.py").run()
    _ok(at)
    next(b for b in at.button if b.label == "Build diagnostic").click().run()
    _ok(at)
    assert not at.error, [e.value for e in at.error]
    with zipfile.ZipFile(io.BytesIO(_download(at, downloads, "Download diagnostic (.zip) · anonymised"))) as archive:
        return {name: pd.read_csv(io.BytesIO(archive.read(name)), encoding="utf-8-sig") for name in archive.namelist()}


def _assert_anonymised(tables: dict, store, anonymous) -> None:
    """Nothing of the originals' text in any table; Activity IDs are the extract's codes."""
    names = set(store.history["task_name"]) | set(store.history["task_code"]) | {store.latest.project_name}
    cells = {str(value) for table in tables.values() for value in table.astype(str).to_numpy().ravel()}
    assert anonymous.leaks(cells) == {}
    assert not cells & {name for name in names if len(name) >= 3}
    codes = pd.concat([table["task_code"].dropna() for table in tables.values() if "task_code" in table])
    assert codes.str.fullmatch(r"XA[0-9A-F]{8}").all()


def test_debug_diagnostic_leaves_the_app_anonymised(app, store, downloads):
    from xerscope.app.diagnostic import diagnostic_frames

    tables = _debug_zip(app, downloads)
    assert set(tables) == {f"{name}.csv" for name in diagnostic_frames(store.latest, None, _p6())}
    assert tables["01_options.csv"]["option"].tolist()[0] == "use_expected_finish"
    _assert_anonymised(tables, store, _session_anonymizer(app))


def test_debug_renders_a_held_out_case_with_an_expected_finish(tmp_path, monkeypatch, downloads):
    """H1-02 (corpus witness of ``expected_finish``): the page renders, block 2 lists A1170 with its
    remaining brought to 0, and the diagnostic leaves anonymised."""
    if not HELD_OUT_CASE.exists():
        missing("p6-corpus", P6_CORPUS_HINT)
    (tmp_path / HELD_OUT_CASE.name).write_bytes(HELD_OUT_CASE.read_bytes())
    at = _run(tmp_path, monkeypatch)
    tables = _debug_zip(at, downloads)
    expected = tables["02_expected_finish.csv"]
    assert len(expected) == 1 and bool(expected["remaining_set_to_0"].iloc[0])
    _assert_anonymised(tables, at.session_state["store"], _session_anonymizer(at))


def test_debug_block_6_lists_the_leveled_activities_anonymised(tmp_path, monkeypatch, downloads):
    """One activity moved by leveling: the warning, block 6 and the zip name it, the zip by its
    extract code only."""
    tasks = [
        {"task_code": "LEVELED-1", "early_start_date": "2026-03-02 08:00", "restart_date": "2026-03-09 08:00"},
        {"task_code": "PLAIN-2"},
    ]
    (tmp_path / "w1.xer").write_text(xer_text(tasks))
    at = _run(tmp_path, monkeypatch)
    tables = _debug_zip(at, downloads)
    assert any("1 open activities have a remaining early start" in c.value for c in at.main.caption)
    leveling = tables["06_leveling.csv"]
    assert len(leveling) == 1 and leveling["task_code"].str.fullmatch(r"XA[0-9A-F]{8}").all()
    _assert_anonymised(tables, at.session_state["store"], _session_anonymizer(at))


def test_debug_page_keeps_p6_field_names_and_its_blocks_open(app):
    """Debug columns carry the XER / analysis field names as written, to set beside P6; each block
    is keyed, so a count in its label changing with the update does not redraw it closed."""
    app.switch_page("views/debug.py").run()
    _ok(app)
    blocks = list(app.main.expander)
    assert len(blocks) == 6 and all(block.key and block.key.startswith("debug_") for block in blocks)
    assert app.main.selectbox(key="debug_snap").label == "Update"


def test_raw_labels_are_the_column_names():
    frame = pd.DataFrame({"task_code": ["A1"], "remain_drtn_hr_cnt": [8.0]})
    config = ui.column_config(frame, raw_labels=True)
    assert [config[column]["label"] for column in frame] == ["task_code", "remain_drtn_hr_cnt"]
    assert ui.column_config(frame)["task_code"]["label"] == "Activity ID"  # the default stays


def _csv(data: bytes):
    import io

    return pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")


def _zip(data: bytes) -> dict[str, bytes]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_exports_are_anonymised_by_default_and_plain_when_switched_off(app, store, downloads):
    """The sidebar switch decides every export: on (default) new IDs and names, off the file's own."""
    originals = set(store.history["task_code"]) | set(store.history["task_name"])
    assert app.sidebar.toggle(key="anon_exports").value is True
    app.switch_page("views/gantt.py").run()
    _ok(app)
    assert not [b for b in app.get("download_button") if b.proto.label.startswith("Download CSV")]
    next(b for b in app.button if b.label == "Prepare anonymised downloads").click().run()
    _ok(app)
    gantt = _csv(_download(app, downloads, "Download CSV · anonymised"))
    assert not set(gantt.astype(str).to_numpy().ravel()) & originals
    assert gantt["task_code"].dropna().str.fullmatch(r"XA[0-9A-F]{8}").all()

    app.switch_page("views/export.py").run()
    _ok(app)
    # the Gantt's anonymizer read one update; the Power BI tables cover the series: prepared again
    next(b for b in app.button if b.label == "Prepare anonymised downloads").click().run()
    _ok(app)
    tables = _zip(_download(app, downloads, "Download PARQUET tables (.zip) · anonymised"))
    activity = pd.read_parquet(__import__("io").BytesIO(tables["fact_activity.parquet"]))
    assert not set(activity.astype(str).to_numpy().ravel()) & originals
    assert len(activity) == len(store.history)  # same rows, renamed

    app.sidebar.toggle(key="anon_exports").set_value(False).run()
    _ok(app)
    tables = _zip(_download(app, downloads, "Download PARQUET tables (.zip)"))
    activity = pd.read_parquet(__import__("io").BytesIO(tables["fact_activity.parquet"]))
    assert set(activity["task_code"]) == set(store.history["task_code"])
    app.switch_page("views/gantt.py").run()
    _ok(app)
    assert set(_csv(_download(app, downloads, "Download CSV"))["task_code"]) <= set(store.history["task_code"])


def test_debug_diagnostic_in_plain_when_anonymous_exports_are_off(app, store, downloads):
    app.sidebar.toggle(key="anon_exports").set_value(False).run()
    app.switch_page("views/debug.py").run()
    _ok(app)
    next(b for b in app.button if b.label == "Build diagnostic").click().run()
    _ok(app)
    tables = _zip(_download(app, downloads, "Download diagnostic (.zip)"))
    assert set(tables) >= {"01_options.csv", "04_check_parameters.csv"}


def _session_anonymizer(at):
    """The anonymizer the session built last (one per set of files read)."""
    return list(at.session_state["_anonymizers"][1].values())[-1]


def test_a_page_download_reads_its_update_only_and_keeps_the_series_codes(app, store, downloads):
    """Preparing the Gantt download reads the update shown, not the series; its codes are those
    of the anonymised XER extract of every file, made later in the same session."""
    app.switch_page("views/gantt.py").run()
    next(b for b in app.button if b.label == "Prepare anonymised downloads").click().run()
    _ok(app)
    shown = app.session_state["gantt_snap"]
    assert list(app.session_state["_anonymizers"][1]) == [frozenset({store.by_label(shown).source})]
    gantt = _csv(_download(app, downloads, "Download CSV · anonymised"))

    app.switch_page("views/export.py").run()
    next(b for b in app.button if b.label == "Build anonymised extract").click().run()
    _ok(app)
    series = _session_anonymizer(app)
    assert len(app.session_state["_anonymizers"][1]) == 2  # the update alone, then every file
    new_of = series.codes["A"]
    original = store.by_label(shown).activities.sort_values("task_code")["task_code"]
    shown_codes = set(gantt["task_code"])  # LOE hidden by default: a part of the update
    assert shown_codes and shown_codes <= {new_of[code] for code in original}


def _p6():
    from xerscope.analysis import builtin_standards

    return builtin_standards()["P6"]


def test_audit_downloads_follow_the_anonymous_exports_switch(app, store, downloads):
    """Audit's set downloads (Counted tab): on, new IDs after Prepare and nothing original; off, the file's own."""
    originals = set(store.history["task_code"]) | set(store.history["task_name"])
    app.sidebar.toggle(key="anon_exports").set_value(True).run()
    app.switch_page("views/audit.py").run()
    _ok(app)
    app.get("button_group")[0].set_value("P6").run()
    app.selectbox(key="audit_check:P6").set_value("P6-01").run()
    _ok(app)
    assert not [b for b in app.get("download_button") if b.proto.label == "Download CSV"]
    next(b for b in app.button if b.label == "Prepare anonymised downloads").click().run()
    _ok(app)
    counted = _csv(_download(app, downloads, "Download CSV · anonymised"))
    assert len(counted) and not set(counted.astype(str).to_numpy().ravel()) & originals

    app.sidebar.toggle(key="anon_exports").set_value(False).run()
    _ok(app)
    counted = _csv(_download(app, downloads, "Download CSV"))
    assert set(counted["task_code"]) <= set(store.history["task_code"])
