"""The PROJECT rows of a file and the P6 Project Baseline pointer (sum_base_proj_id / orig_proj_id)."""

import io
import zipfile

import pandas as pd
from file_projects import BASELINE_DATE, two_projects

from xerscope.analysis import builtin_standards
from xerscope.anonymize import Anonymizer
from xerscope.app.diagnostic import ANALYSED, BASELINE_OF_ANALYSED, diagnostic_frames, projects_table
from xerscope.xer import build_snapshot, parse_text


def _snapshot(**kw):
    return build_snapshot(parse_text(two_projects(**kw), source="two.xer"))


def test_projects_block_has_one_row_per_project_with_pointers_and_role():
    table = projects_table(_snapshot()).set_index("proj_id")
    assert table.index.tolist() == ["1", "2"]
    assert table["tasks"].tolist() == [2, 2]
    assert table.loc["1", ["sum_base_proj_id", "orig_proj_id", "role"]].tolist() == ["2", "", ANALYSED]
    assert table.loc["2", ["sum_base_proj_id", "orig_proj_id", "last_baseline_update_date", "role"]].tolist() == [
        "",
        "1",
        BASELINE_DATE,
        BASELINE_OF_ANALYSED,
    ]


def test_projects_block_leaves_the_role_empty_when_the_pointer_names_another_project():
    table = projects_table(_snapshot(pointer="3")).set_index("proj_id")
    assert table["role"].tolist() == [ANALYSED, ""]


def test_projects_block_of_a_file_without_pointer_columns():
    from xerkit import snap

    table = projects_table(snap([{"task_code": "A1"}]))
    assert table[["proj_id", "tasks", "sum_base_proj_id", "role"]].values.tolist() == [["1", 1, "", ANALYSED]]


def test_projects_block_of_an_anonymous_download_renames_the_codes_and_keeps_the_ids():
    raw = parse_text(two_projects(), source="two.xer")
    anonymizer = Anonymizer.from_raws([raw])
    frames = {"01b_projects": diagnostic_frames(build_snapshot(raw), None, builtin_standards()["P6"])["01b_projects"]}
    with zipfile.ZipFile(io.BytesIO(anonymizer.zip_frames(frames))) as archive:
        text = archive.read("01b_projects.csv").decode("utf-8-sig")
    shown = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    assert "UPD" not in text and "BL," not in text
    assert shown["proj_short_name"].str.startswith("XP").all()
    assert shown[["proj_id", "sum_base_proj_id", "orig_proj_id"]].values.tolist() == [["1", "2", ""], ["2", "", "1"]]


# --- the baseline a file names for its analysed project --------------------------------------------


def test_the_pointed_project_is_the_default_baseline_with_its_own_finish():
    from xerscope.analysis import Baseline

    raw = parse_text(two_projects(), source="two.xer")
    analysed = build_snapshot(raw)
    pointer = analysed.file_baseline
    assert (pointer.usable, pointer.proj_id, pointer.code) == (True, "2", "BL")
    assert pointer.text == "Baseline: BL (from the file)"
    baseline = Baseline.from_snapshot(build_snapshot(raw, project_id=pointer.proj_id))
    # project 2 is built by hand with both activities finishing Fri 2026-03-06 17:00, the analysed A1 and A2
    # finish Fri 2026-03-13 17:00
    assert baseline.frame["bl_finish"].tolist() == [pd.Timestamp("2026-03-06 17:00")] * 2
    assert analysed.activities["finish"].tolist() == [pd.Timestamp("2026-03-13 17:00")] * 2


def test_a_pointer_to_a_project_that_is_not_in_the_file_gives_no_baseline():
    # a file exported without its baseline: sum_base_proj_id names a project (370) the file does not hold
    pointer = _snapshot(pointer="370", with_baseline=False).file_baseline
    assert not pointer.usable
    assert pointer.text == "Baseline: none in file (points to project 370, which is not in the file)"


def test_a_pointer_to_a_project_without_activities_gives_no_baseline():
    raw = parse_text(two_projects(), source="two.xer")
    tasks = raw.tables["TASK"]
    raw.tables["TASK"] = tasks[tasks["proj_id"] != "2"]
    assert build_snapshot(raw).file_baseline.note == "project 2 has no activities"


def test_no_pointer_means_none_in_file():
    pointer = _snapshot(pointer="").file_baseline
    assert not pointer.usable and pointer.text == "Baseline: none in file"


def test_a_baseline_copied_from_another_project_is_refused_and_says_so():
    pointer = _snapshot(original="7").file_baseline
    assert not pointer.usable
    assert pointer.note == "project 2 was copied from project 7, not from the analysed project 1"


def test_a_baseline_without_orig_proj_id_is_accepted():
    assert _snapshot(original="").file_baseline.usable


def test_project_id_selects_exactly_when_two_projects_share_a_code():
    raw = parse_text(two_projects(baseline_code="UPD"), source="two.xer")
    assert build_snapshot(raw, project_id="2").project_id == "2"
    assert build_snapshot(raw, project_id="1").project_id == "1"
    assert build_snapshot(raw).file_baseline.code == "UPD"


def test_p6_12_and_p6_13_take_the_baseline_they_are_given():
    # P6-12 / P6-13 read context.baseline and nothing else: the file's baseline gives, by hand,
    # A1 and A2 forecast Fri 03-13 against a baseline finish Fri 03-06 (2 late of 2), and none completed
    # of 2 baseline activities
    from rulekit import STANDARDS, counts, run

    from xerscope.analysis import Baseline

    raw = parse_text(two_projects(), source="two.xer")
    baseline = Baseline.from_snapshot(build_snapshot(raw, project_id="2"))
    p6 = STANDARDS["P6"]
    assert counts(run(p6, "P6-12", build_snapshot(raw), baseline)) == (2, 2)
    assert counts(run(p6, "P6-13", build_snapshot(raw), baseline)) == (0, 2)


# --- the app ---------------------------------------------------------------------------------------


def _app(tmp_path, monkeypatch, **kw):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    import xerscope

    (tmp_path / "two.xer").write_text(two_projects(**kw))
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120)
    at.run()
    for box in at.sidebar.checkbox:
        if box.key.startswith("read:"):
            box.check()
    return at.run()


def _baseline_box(at):
    return next(box for box in at.sidebar.selectbox if box.key == "bl_choice")


def _selection(at):
    return next(frame for frame in at.sidebar.dataframe if "baseline" in frame.value.columns).value


def test_the_sidebar_defaults_to_the_baseline_in_the_file_and_the_panel_names_it(tmp_path, monkeypatch):
    from xerscope.app.state import BL_EACH

    at = _app(tmp_path, monkeypatch, baseline_ids=("A1", "A2"))
    assert not at.exception
    assert _baseline_box(at).value == BL_EACH and _baseline_box(at).options[0] == BL_EACH
    assert _selection(at)["baseline"].tolist() == ["Baseline: BL (from the file)"]


def test_the_sidebar_keeps_its_choice_when_the_pointer_names_an_absent_project(tmp_path, monkeypatch):
    from xerscope.app.state import BL_EACH

    at = _app(tmp_path, monkeypatch, pointer="370", with_baseline=False)
    assert not at.exception
    assert BL_EACH not in _baseline_box(at).options and _baseline_box(at).value != BL_EACH
    assert _selection(at)["baseline"].tolist() == [
        "Baseline: none in file (points to project 370, which is not in the file)"
    ]


def test_the_panel_says_why_an_inconsistent_baseline_is_not_used(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch, original="7")
    assert "copied from project 7" in _selection(at)["baseline"].iloc[0]


def test_schedule_health_runs_on_the_baseline_of_the_file(tmp_path, monkeypatch):
    from xerscope.app.state import BL_EACH

    at = _app(tmp_path, monkeypatch).switch_page("views/health.py").run()
    assert not at.exception
    # the memo key names the project each file points to, so a changed pointer is a new key
    identities = [part for key in at.session_state["_memo"] for part in key if isinstance(part, tuple)]
    assert any(part[0] == BL_EACH and part[2] == (("two.xer", "2", True),) for part in identities)


# --- the fallback, update by update, and the baseline every result names ----------------------------


def _series(tmp_path, monkeypatch):
    """Two updates: ``a`` (2026-03-02) points to its baseline copy, ``b`` (2026-03-09) points to none."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    import xerscope

    (tmp_path / "a.xer").write_text(two_projects(data_date="2026-03-02 08:00"))
    (tmp_path / "b.xer").write_text(two_projects(pointer="", data_date="2026-03-09 08:00", with_baseline=False))
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120)
    at.run()
    for box in at.sidebar.checkbox:
        if box.key.startswith("read:"):
            box.check()
    return at.run()


def _health(at, update_stamp, fallback=None):
    """The Health page on one update; ``fallback`` sets the sidebar's second selector first."""
    if fallback is not None:
        next(box for box in at.sidebar.selectbox if box.key == "bl_fallback").select(fallback)
        at.run()
    at = at.switch_page("views/health.py").run()
    snapshot = next(box for box in at.selectbox if box.key == "health_snap")
    snapshot.select(next(option for option in snapshot.options if option.startswith(update_stamp)))
    return at.run()


def _markdown(at):
    return [element.value.replace("\\", "") for element in at.markdown]  # ui.md_text escapes


def test_the_fallback_selector_defaults_to_none_and_is_shown_with_the_file_mode(tmp_path, monkeypatch):
    at = _series(tmp_path, monkeypatch)
    fallback = next(box for box in at.sidebar.selectbox if box.key == "bl_fallback")
    assert fallback.label == "When a file has no baseline"
    assert fallback.value == "None"
    assert fallback.options[0] == "Separate baseline file" and fallback.options[-2:] == [
        "Planned dates in each file (target_*)",
        "None",
    ]


def test_each_update_uses_its_file_baseline_else_the_fallback(tmp_path, monkeypatch):
    at = _series(tmp_path, monkeypatch)
    file_text = "P6 Project Baseline in the file (proj_id 2, last update 2026-01-12)"
    a = _health(at, "2026-03-02")
    assert not a.exception and f"**Baseline** · {file_text}" in _markdown(a)
    b = _health(a, "2026-03-09")
    assert "**Baseline** · none" in _markdown(b) and not [m for m in _markdown(b) if file_text in m]
    planned = _health(b, "2026-03-09", fallback="Planned dates in each file (target_*)")
    assert "**Baseline** · fallback (Planned dates in each file (target_*))" in _markdown(planned)
    # the first update keeps its own file's baseline whatever the fallback
    assert f"**Baseline** · {file_text}" in _markdown(_health(planned, "2026-03-02"))


def test_p6_12_and_p6_13_are_computed_on_the_source_each_update_uses(tmp_path, monkeypatch):
    at = _series(tmp_path, monkeypatch)
    a = _health(at, "2026-03-02")
    # file baseline, by hand: A1 and A2 forecast 03-13 against 03-06 -> 2 late of 2; 0 complete of 2 baseline
    assert "#### 2 late / 2 checked = 100.0 %" in _markdown(a)
    assert any(m.startswith("#### 0 completed / 2") for m in _markdown(a))
    # planned dates carry no target_end_date here: nothing is late, and the 2 activities are their own baseline
    b = _health(a, "2026-03-09", fallback="Planned dates in each file (target_*)")
    assert "#### 0 late / 2 checked = 0.0 %" in _markdown(b)


def test_a_result_names_the_baseline_it_was_computed_on():
    from dataclasses import replace

    from rulekit import STANDARDS, run

    from xerscope.analysis import Baseline
    from xerscope.analysis.explain import explain

    raw = parse_text(two_projects(), source="two.xer")
    snapshot = build_snapshot(raw)
    chosen = replace(
        Baseline.from_snapshot(build_snapshot(raw, project_id="2")), source="P6 Project Baseline in the file"
    )
    late = run(STANDARDS["P6"], "P6-12", snapshot, chosen)
    assert late.baseline == "P6 Project Baseline in the file" == explain(late).baseline
    assert run(STANDARDS["P6"], "P6-12", snapshot, None).baseline == "none"
    assert run(STANDARDS["P6"], "P6-01", snapshot, chosen).baseline == ""  # logic does not depend on it
    assert run(STANDARDS["P6"], "P6-01", snapshot, None).baseline == ""
    assert late.note_with_baseline == "baseline: P6 Project Baseline in the file"


def test_the_exports_carry_the_baseline_of_the_result():
    from dataclasses import replace

    from rulekit import STANDARDS

    from xerscope.analysis import AnalysisContext, Baseline, run_standard
    from xerscope.analysis.audit import sets_long

    raw = parse_text(two_projects(), source="two.xer")
    snapshot = build_snapshot(raw)
    chosen = replace(
        Baseline.from_snapshot(build_snapshot(raw, project_id="2")), source="P6 Project Baseline in the file"
    )
    results = run_standard(STANDARDS["P6"], AnalysisContext(snapshot, None, chosen))
    table = sets_long(results, snapshot)
    notes = table.groupby("check_id")["note"].first()
    assert notes["P6-12"].endswith("baseline: P6 Project Baseline in the file")
    assert "baseline:" not in notes["P6-01"]
