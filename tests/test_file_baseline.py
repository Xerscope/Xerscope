"""The PROJECT rows of a file and the P6 Project Baseline pointer (sum_base_proj_id / orig_proj_id)."""

import io
import zipfile

import pandas as pd
import pytest
from conftest import baseline_box, files_done, pick_project, project_box, read_folder, selection
from file_projects import BASELINE_DATE, two_projects

from xerscope.analysis import builtin_standards
from xerscope.anonymize import Anonymizer
from xerscope.app.diagnostic import (
    ANALYSED,
    BASELINE_OF_ANALYSED,
    baseline_pointers,
    diagnostic_frames,
    projects_table,
)
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


def test_projects_block_of_an_anonymous_download_renames_the_codes_and_the_ids():
    """proj_id 1 points to its baseline 2 (sum_base_proj_id), 2 was copied from 1 (orig_proj_id): the new
    ids keep both pointers, and are those of the anonymised XER."""
    raw = parse_text(two_projects(), source="two.xer")
    anonymizer = Anonymizer.from_raws([raw])
    frames = {"01b_projects": diagnostic_frames(build_snapshot(raw), None, builtin_standards()["P6"])["01b_projects"]}
    with zipfile.ZipFile(io.BytesIO(anonymizer.zip_frames(frames))) as archive:
        text = archive.read("01b_projects.csv").decode("utf-8-sig")
    shown = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    assert "UPD" not in text and "BL," not in text
    assert shown["proj_short_name"].str.startswith("XP").all()
    new = anonymizer.project_ids
    assert shown[["proj_id", "sum_base_proj_id", "orig_proj_id"]].values.tolist() == [
        [new["1"], new["2"], ""],
        [new["2"], "", new["1"]],
    ]
    assert not {"1", "2"} & set(shown["proj_id"])
    extract = build_snapshot(parse_text(anonymizer.xer(raw).decode(), source="anon.xer"))
    assert extract.file_projects["proj_id"].tolist() == [new["1"], new["2"]]


def _update(source, proj_id, data_date, pointer, added, flag):
    from xerkit import xer_text

    project = {"proj_id": proj_id, "sum_base_proj_id": pointer, "add_date": added, "use_project_baseline_flag": flag}
    text = xer_text([{"task_code": "A1", "proj_id": proj_id}], project=project, data_date=data_date)
    return build_snapshot(parse_text(text, source=source))


def test_the_baseline_pointers_of_a_series_are_listed_in_data_date_order():
    # three weekly files, read in file-name order, each a project of its own pointing to a baseline it does not hold
    from xerscope.store import SnapshotStore

    store = SnapshotStore(
        [
            _update("c.xer", "30", "2026-03-16 08:00", "31", "2026-03-13 16:00", "Y"),
            _update("a.xer", "10", "2026-03-02 08:00", "7", "2026-02-27 16:00", "Y"),
            _update("b.xer", "20", "2026-03-09 08:00", "22", "2026-03-06 16:00", "N"),
        ]
    )
    table = baseline_pointers(store)
    assert table.columns.tolist() == [
        "file", "data_date", "proj_id", "add_date", "sum_base_proj_id", "baseline_in_file",
        "baseline_in_xml_file", "use_project_baseline_flag",
    ]  # fmt: skip
    assert table.drop(columns="data_date").values.tolist() == [
        ["a.xer", "10", "2026-02-27 16:00", "7", False, None, "Y"],
        ["b.xer", "20", "2026-03-06 16:00", "22", False, None, "N"],
        ["c.xer", "30", "2026-03-13 16:00", "31", False, None, "Y"],
    ]
    assert table["data_date"].tolist() == [
        pd.Timestamp(f"{day} 08:00") for day in ("2026-03-02", "2026-03-09", "2026-03-16")
    ]


def test_the_baselines_of_a_p6_xml_file_are_held_against_the_baseline_each_update_names():
    # three updates name baselines 7, 22 and 31; the XML export holds 7, 22 and 99, which no update names;
    # its project names 22 as its Project Baseline
    from pmxmlkit import activity, baseline, pmxml_bytes

    from xerscope.app.xml_baselines import xml_baselines_table
    from xerscope.store import SnapshotStore
    from xerscope.xer.pmxml import index_pmxml

    store = SnapshotStore(
        [
            _update("a.xer", "10", "2026-03-02 08:00", "7", "2026-02-27 16:00", "Y"),
            _update("b.xer", "20", "2026-03-09 08:00", "22", "2026-03-06 16:00", "Y"),
            _update("c.xer", "30", "2026-03-16 08:00", "31", "2026-03-13 16:00", "Y"),
        ]
    )
    planned = activity("A1", "11", "2026-03-02T08:00:00", "2026-03-06T17:00:00", 40)
    later = activity("A2", "12", "2026-03-09T08:00:00", "2026-03-13T17:00:00", 40)
    export = pmxml_bytes(
        [baseline("7", "BL-7", [planned]), baseline("22", "BL-22", [planned, later]), baseline("99", "BL-99", [])],
        current_baseline="22",
    )
    index = index_pmxml(export, "export.xml")

    assert baseline_pointers(store, index.baselines)["baseline_in_xml_file"].tolist() == [True, True, False]
    assert xml_baselines_table(index, ["7", "22", "31"]).values.tolist() == [
        ["7", "BL-7", "BL-7 name", "2026-02-23 08:00", "1", 1, False, 1],
        ["22", "BL-22", "BL-22 name", "2026-02-23 08:00", "1", 2, True, 1],
        ["99", "BL-99", "BL-99 name", "2026-02-23 08:00", "1", 0, False, 0],
    ]


def _export_of_versions(versions: dict[str, tuple[str, int]]) -> bytes:
    """A P6 XML export of several versions of one project: ``{project id: (baseline id, hours)}``. Each
    version names its baseline as its Project Baseline; each baseline holds A1 with ``hours``, under ids of
    its own."""
    from pmxmlkit import NAMESPACE, _fields, activity, baseline, calendar

    body = calendar()
    for project_id, (baseline_id, hours) in versions.items():
        fields = {"ObjectId": project_id, "Id": f"V{project_id}", "CurrentBaselineProjectObjectId": baseline_id}
        planned = activity("A1", f"{baseline_id}1", "2026-03-02T08:00:00", "2026-03-06T17:00:00", hours)
        copy = baseline(baseline_id, f"V{project_id} - B1", [planned])
        body += f"<Project>{_fields(fields)}</Project>"
        body += copy.replace("<OriginalProjectObjectId>1<", f"<OriginalProjectObjectId>{project_id}<")
    return f'<?xml version="1.0"?><APIBusinessObjects xmlns="{NAMESPACE}">{body}</APIBusinessObjects>'.encode()


def test_each_update_is_given_the_baseline_it_would_be_measured_against_and_what_found_it():
    """The export holds versions 100, 200 and 400 of the project. Baselines 101 and 201 are copies of one
    baseline (40 h on A1); 401 is another one (48 h). Five updates, none with its baseline in its file."""
    from xerscope.app.xml_baselines import export_of, resolution_table
    from xerscope.store import SnapshotStore
    from xerscope.xer.pmxml import index_pmxml

    store = SnapshotStore(
        [
            _update("a.xer", "150", "2026-03-02 08:00", "151", "2026-02-27 16:00", "Y"),  # between 100 and 200
            _update("b.xer", "200", "2026-03-09 08:00", "201", "2026-03-06 16:00", "Y"),  # its baseline is exported
            _update("c.xer", "300", "2026-03-16 08:00", "301", "2026-03-13 16:00", "Y"),  # between 200 and 400
            _update("d.xer", "350", "2026-03-23 08:00", "150", "2026-03-20 16:00", "Y"),  # names the project of a.xer
            _update("e.xer", "450", "2026-03-30 08:00", "451", "2026-03-27 16:00", "Y"),  # later than every version
        ]
    )
    export = _export_of_versions({"100": ("101", 40), "200": ("201", 40), "400": ("401", 48)})
    table = resolution_table(store, export_of("export.xml", export, index_pmxml(export, "export.xml")))

    found = table[["file", "found_by", "baseline", "version_before", "version_after", "note"]].values.tolist()
    assert found == [
        ["a.xer", "in the export, the same baseline before and after", "101", "100", "200", ""],
        ["b.xer", "in the export, by id", "201", "", "", ""],
        ["c.xer", "undecided", "", "200", "400", "the versions around it hold different baselines"],
        ["d.xer", "a loaded update, by id", "150", "", "", ""],
        ["e.xer", "undecided", "", "400", "", "no version of the export after it"],
    ]
    assert table[["proj_id", "sum_base_proj_id"]].values.tolist() == [
        ["150", "151"], ["200", "201"], ["300", "301"], ["350", "150"], ["450", "451"],
    ]  # fmt: skip

    without_export = resolution_table(store, None)
    assert without_export["found_by"].tolist() == [
        "not found",
        "not found",
        "not found",
        "a loaded update, by id",
        "not found",
    ]


def test_the_projects_of_the_export_are_listed_with_their_status_date_and_the_updates_that_share_it():
    """An export of three projects. 100: status date 2 March, added 27 February, names baseline 101, which the
    export holds. 200: status date 9 March, names 999, which it does not hold. 300: no date, no baseline.
    Three updates: a.xer read from project 150 on 2 March; b.xer and c.xer read from project 200, on 9 March
    at another hour and on 16 March."""
    from pmxmlkit import NAMESPACE, _fields, activity, baseline, calendar

    from xerscope.app.xml_baselines import xml_projects_table
    from xerscope.store import SnapshotStore
    from xerscope.xer.pmxml import index_pmxml

    projects = [
        {"ObjectId": "100", "DataDate": "2026-03-02T08:00:00", "DateAdded": "2026-02-27T10:15:00",
         "CurrentBaselineProjectObjectId": "101"},
        {"ObjectId": "200", "DataDate": "2026-03-09T08:00:00", "DateAdded": "2026-03-06T10:15:00",
         "CurrentBaselineProjectObjectId": "999"},
        {"ObjectId": "300"},
    ]  # fmt: skip
    planned = activity("A1", "1011", "2026-03-02T08:00:00", "2026-03-06T17:00:00", 40)
    body = calendar() + "".join(f"<Project>{_fields(fields)}</Project>" for fields in projects)
    body += baseline("101", "V100 - B1", [planned])
    export = f'<?xml version="1.0"?><APIBusinessObjects xmlns="{NAMESPACE}">{body}</APIBusinessObjects>'.encode()
    store = SnapshotStore(
        [
            _update("a.xer", "150", "2026-03-02 08:00", "151", "2026-02-27 16:00", "Y"),
            _update("b.xer", "200", "2026-03-09 17:00", "201", "2026-03-06 16:00", "Y"),
            _update("c.xer", "200", "2026-03-16 08:00", "201", "2026-03-06 16:00", "Y"),
        ]
    )

    table = xml_projects_table(index_pmxml(export, "export.xml"), store)

    assert list(table.columns) == [
        "object_id", "data_date", "date_added", "current_baseline_id", "baseline_in_export", "updates_from_it",
        "updates_same_status_date",
    ]  # fmt: skip
    assert table.values.tolist() == [
        ["100", "2026-03-02 08:00", "2026-02-27 10:15", "101", True, 0, 1],
        ["200", "2026-03-09 08:00", "2026-03-06 10:15", "999", False, 2, 1],
        ["300", "", "", "", False, 0, 0],
    ]


def _series_and_export(folder) -> None:
    """Four updates of 40 h on A1, none with its baseline in its file, next to an export of versions 100,
    200 and 400 of the project: baselines 101 and 201 are copies of one baseline (40 h), 401 is another (48 h).

    a.xer, project 150, names 151: not exported; versions 100 and 200 around it hold the same baseline.
    b.xer, project 200, names 201: exported. c.xer, project 300, names 301: not exported; versions 200 and
    400 around it hold different baselines. d.xer, project 400, names 401: exported."""
    from xerkit import todo, xer_text

    updates = {
        "a.xer": ("150", "151", "2026-03-02 08:00"),
        "b.xer": ("200", "201", "2026-03-09 08:00"),
        "c.xer": ("300", "301", "2026-03-16 08:00"),
        "d.xer": ("400", "401", "2026-03-23 08:00"),
    }
    for name, (project_id, pointer, data_date) in updates.items():
        project = {"proj_id": project_id, "sum_base_proj_id": pointer}
        activity = todo("A1", proj_id=project_id, target_work_qty="40")
        (folder / name).write_text(xer_text([activity], project=project, data_date=data_date), encoding="utf-8")
    export = _export_of_versions({"100": ("101", 40), "200": ("201", 40), "400": ("401", 48)})
    (folder / "export.xml").write_bytes(export)


def test_the_baseline_found_for_each_update_is_applied_and_a_probable_one_is_announced(tmp_path, monkeypatch):
    """ "Baseline in each file" with the export of the folder picked and no fallback. b and d are measured
    against the baseline they name; a against the copy the versions around it hold, and the app says it is
    a probable baseline in the sidebar and under the title of the page; c, undecided, is not measured."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    import xerscope
    from xerscope.app.state import BL_EACH, BL_FILE, BL_NONE

    _series_and_export(tmp_path)
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = read_folder(
        AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120).run()
    )
    baseline_box(at, "bl_choice").select(BL_EACH)  # offered: the folder holds an export of baselines
    baseline_box(at, "bl_folder_file").select("export.xml")  # asked for without making it the fallback
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["fallback_choice"] == BL_NONE

    used, said_on_the_page = {}, {}
    at = at.switch_page("views/health.py").run()
    for stamp in ("2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23"):
        picker = next(box for box in at.selectbox if box.key == "health_snap")
        picker.select(next(option for option in picker.options if option.startswith(stamp)))
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        help_lines = at.button(key="context_banner").help.replace("\\", "").split("  \n")
        line = next(line for line in help_lines if line.startswith(f"Baseline used for {stamp}"))
        used[stamp] = line.split(": ", 1)[1]
        said_on_the_page[stamp] = [w.value.replace("\\", "") for w in at.main.warning if "probable" in w.value]

    assert used["2026-03-02"] == (
        "probable: baseline V100 - B1 of export.xml, held by the versions created before and after the "
        "update's project (100 and 200); the one its file names (151) is not in the export"
    )
    assert used["2026-03-09"] == "P6 Project Baseline V200 - B1 from export.xml"
    assert used["2026-03-16"] == "none"
    assert used["2026-03-23"] == "P6 Project Baseline V400 - B1 from export.xml"
    # under the title of the page of the update concerned, in full, and of no other
    assert said_on_the_page["2026-03-02"] == [f"Baseline of this update: {used['2026-03-02']}."]
    assert not any(said_on_the_page[stamp] for stamp in ("2026-03-09", "2026-03-16", "2026-03-23"))

    # the three baselines read from the export, each with the hours of its A1
    built = {key[2]: baseline.bac_hours for key, baseline in at.session_state["_xml_baselines"].items()}
    assert built == {"101": 40.0, "201": 40.0, "401": 48.0}

    sidebar = [w.value.replace("\\", "") for w in at.sidebar.warning]
    assert any(
        text.startswith("a.xer: measured against a probable baseline, not the one its file names.") for text in sidebar
    ), sidebar
    assert any(
        text.startswith("c.xer: the baseline its file names is not in the export, and the versions around it")
        for text in sidebar
    ), sidebar
    assert any("The series mixes baseline sources" in text and "a probable baseline" in text for text in sidebar)

    # the baseline named is missing for a and c only: b and d are measured against the one they name
    errors = [e.value.replace("\\", "") for e in at.sidebar.error]
    assert any(text.startswith("P6 Project Baseline missing for 2 updates of 4") for text in errors), errors

    # with the export as the fallback too, c alone falls back on it (baseline 401, named by the last update),
    # and is the only update said to name another baseline than the one it is measured against
    baseline_box(at, "bl_fallback").select(BL_FILE)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    other = [w.value.replace("\\", "") for w in at.sidebar.warning if "name another P6 Project Baseline" in w.value]
    assert len(other) == 1 and other[0].count(" update)") == 1, other  # one baseline named, by one update


def test_each_baseline_of_the_export_is_read_once_for_the_pages_and_the_debug_table(tmp_path, monkeypatch):
    """Baselines 101 and 201 are compared for a.xer, 201 and 401 for c.xer; 101, 201 and 401 are the ones
    a, b and d are measured against; the Debug page lists what was found. One read of each serves all three."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    import xerscope
    from xerscope.analysis.baseline_resolution import IN_EXPORT, SAME_GENERATION, UNDECIDED
    from xerscope.app.state import BL_EACH
    from xerscope.xer.pmxml import read_pmxml_baseline

    reads: dict[str, int] = {}

    def counted(data, source, baseline_id=None, index=None):
        reads[baseline_id] = reads.get(baseline_id, 0) + 1
        return read_pmxml_baseline(data, source, baseline_id, index)

    monkeypatch.setattr("xerscope.xer.read_pmxml_baseline", counted)  # the name load_snapshot calls
    _series_and_export(tmp_path)
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = read_folder(
        AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120).run()
    )
    baseline_box(at, "bl_choice").select(BL_EACH)
    baseline_box(at, "bl_folder_file").select("export.xml")
    at.run()
    at = at.switch_page("views/health.py").run()
    assert not at.exception, [e.value for e in at.exception]
    at = at.switch_page("views/debug.py").run()
    assert not at.exception, [e.value for e in at.exception]
    found = next(table.value for table in at.dataframe if "found_by" in table.value.columns)
    assert found["found_by"].tolist() == [SAME_GENERATION, IN_EXPORT, UNDECIDED, IN_EXPORT]
    assert reads == {"101": 1, "201": 1, "401": 1}


def test_the_debug_page_lists_the_projects_of_the_export_in_use(tmp_path, monkeypatch):
    """The export of the folder holds versions 100, 200 and 400; b.xer was read from 200, d.xer from 400."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    import xerscope
    from xerscope.app.state import BL_EACH

    _series_and_export(tmp_path)
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = read_folder(
        AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120).run()
    )
    baseline_box(at, "bl_choice").select(BL_EACH)
    baseline_box(at, "bl_folder_file").select("export.xml")
    at.run()
    at = at.switch_page("views/debug.py").run()
    assert not at.exception, [e.value for e in at.exception]
    projects = next(table.value for table in at.dataframe if "updates_from_it" in table.value.columns)
    listed = projects[["object_id", "current_baseline_id", "baseline_in_export", "updates_from_it"]]
    assert listed.values.tolist() == [["100", "101", True, 0], ["200", "201", True, 1], ["400", "401", True, 1]]


def test_the_export_of_baselines_is_read_for_the_downloads_in_the_per_file_mode(tmp_path, monkeypatch):
    """What an anonymized download is built from (``baseline_items``): in "Baseline in each file", the
    export picked in the folder, whose baselines the updates are measured against; a separate XER only
    when it is the fallback."""
    from xerkit import todo, xer_text

    from xerscope.app.state import BL_EACH, BL_FILE, baseline_items

    _series_and_export(tmp_path)
    session = {"bl_choice": BL_EACH, "files_source": ("folder", str(tmp_path), ("a.xer",))}
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    ((name, export),) = baseline_items({**session, "bl_folder_file": "export.xml"})
    assert (name, export[:]) == ("export.xml", (tmp_path / "export.xml").read_bytes())
    assert baseline_items(session) == []

    separate = tmp_path.parent / "separate.xer"
    separate.write_text(xer_text([todo("A1")]), encoding="utf-8")
    monkeypatch.setenv("XERSCOPE_BASELINE", str(separate))
    assert baseline_items(session) == []
    assert [name for name, _ in baseline_items({**session, "bl_fallback": BL_FILE})] == ["separate.xer"]


def test_a_baseline_held_by_the_file_is_marked_in_file():
    from xerscope.store import SnapshotStore

    (row,) = baseline_pointers(SnapshotStore([_snapshot()])).to_dict("records")
    assert (row["proj_id"], row["sum_base_proj_id"], row["baseline_in_file"]) == ("1", "2", True)
    assert (row["add_date"], row["use_project_baseline_flag"]) == ("", "")


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
    assert pointer.text == ("Baseline: none in file (the project it names is not in the file)")


def test_a_pointer_to_a_project_without_activities_gives_no_baseline():
    raw = parse_text(two_projects(), source="two.xer")
    tasks = raw.tables["TASK"]
    raw.tables["TASK"] = tasks[tasks["proj_id"] != "2"]
    assert build_snapshot(raw).file_baseline.note == "project BL has no tasks"


def test_no_pointer_means_none_in_file():
    pointer = _snapshot(pointer="").file_baseline
    assert not pointer.usable and pointer.text == "Baseline: none in file"


def test_a_baseline_copied_from_another_project_is_refused_and_says_so():
    pointer = _snapshot(original="7").file_baseline
    assert not pointer.usable
    assert pointer.note == "project BL was copied from a project not in the file, not from the analysed project"


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
    return read_folder(at.run())


def _baseline_box(at):
    return baseline_box(at)


def _selection(at):
    return selection(at)


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
    assert _selection(at)["baseline"].tolist() == ["Baseline: none in file (the project it names is not in the file)"]


def test_the_panel_says_why_an_inconsistent_baseline_is_not_used(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch, original="7")
    assert "copied from a project not in the file" in _selection(at)["baseline"].iloc[0]


def test_schedule_health_runs_on_the_baseline_of_the_file(tmp_path, monkeypatch):
    from xerscope.app.state import BL_EACH

    at = _app(tmp_path, monkeypatch).switch_page("views/health.py").run()
    assert not at.exception
    # the memo key names the project each file points to, so a changed pointer is a new key
    identities = [part for key in at.session_state["_memo"] for part in key if isinstance(part, tuple)]
    assert any(part[0] == BL_EACH and part[2] == (("two.xer", "2", True),) for part in identities)


# --- the fallback, update by update, and the baseline every result names ----------------------------


def _series(tmp_path, monkeypatch, files=None, transform=lambda text: text, keep_env=False):
    """Updates in a folder, ``{name: two_projects arguments}``; by default ``a`` (2026-03-02) points to its
    baseline copy and ``b`` (2026-03-09) points to none. ``transform`` edits each file's text."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    import xerscope

    files = files or {
        "a.xer": {"data_date": "2026-03-02 08:00"},
        "b.xer": {"pointer": "", "data_date": "2026-03-09 08:00", "with_baseline": False},
    }
    for name, arguments in files.items():
        (tmp_path / name).write_text(transform(two_projects(**arguments)))
    monkeypatch.setenv("XERSCOPE_DATA", str(tmp_path))
    if not keep_env:
        monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    at = AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120)
    return read_folder(at.run())


def _health(at, update_stamp, fallback=None):
    """The Health page on one update; ``fallback`` sets the sidebar's second selector first."""
    if fallback is not None:
        baseline_box(at, "bl_fallback").select(fallback)
        at.run()
    at = at.switch_page("views/health.py").run()
    snapshot = next(box for box in at.selectbox if box.key == "health_snap")
    snapshot.select(next(option for option in snapshot.options if option.startswith(update_stamp)))
    return at.run()


def _markdown(at):
    return [element.value.replace("\\", "") for element in at.markdown]  # ui.md_text escapes


def _banner(at):
    """The lines of the context banner's help, under the page title (state.context_banner)."""
    return at.button(key="context_banner").help.replace("\\", "").split("  \n")


def test_the_fallback_selector_defaults_to_none_and_is_shown_with_the_file_mode(tmp_path, monkeypatch):
    at = _series(tmp_path, monkeypatch)
    fallback = baseline_box(at, "bl_fallback")
    assert fallback.label == "When a file has no baseline"
    assert fallback.value == "None"
    assert fallback.options[0] == "Separate baseline file" and fallback.options[-2:] == [
        "Planned dates in each file (target_*)",
        "None",
    ]


def test_each_update_uses_its_file_baseline_else_the_fallback(tmp_path, monkeypatch):
    at = _series(tmp_path, monkeypatch)
    file_text = "P6 Project Baseline in the file (BL, last update 2026-01-12)"
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


# --- warnings, naming the files -----------------------------------------------------------------------

A = {"data_date": "2026-03-02 08:00"}
B_NONE = {"pointer": "", "data_date": "2026-03-09 08:00", "with_baseline": False}


def _warnings(at):
    return [element.value.replace("\\", "") for element in at.sidebar.warning]


def _page_warnings(at):
    return [element.value.replace("\\", "") for element in at.warning]


def test_no_warning_when_every_file_has_a_usable_baseline_that_matches(tmp_path, monkeypatch):
    at = _series(tmp_path, monkeypatch, {"a.xer": A, "c.xer": {"data_date": "2026-03-09 08:00"}})
    assert not _warnings(at)
    assert not _page_warnings(_health(at, "2026-03-02"))


def test_a_file_without_baseline_is_named_with_what_applies_instead(tmp_path, monkeypatch):
    at = _series(tmp_path, monkeypatch)
    assert any("b.xer" in w and "baseline checks are n/a" in w for w in _warnings(at))
    baseline_box(at, "bl_fallback").select("Planned dates in each file (target_*)")
    assert any("b.xer" in w and "fallback: Planned dates in each file (target_*)" in w for w in _warnings(at.run()))


def test_a_pointer_to_an_absent_project_is_named(tmp_path, monkeypatch):
    c = {"pointer": "370", "data_date": "2026-03-09 08:00", "with_baseline": False}
    at = _series(tmp_path, monkeypatch, {"a.xer": A, "c.xer": c})
    assert any("c.xer: Baseline: none in file (the project it names is not in the file)" in w for w in _warnings(at))


def _absent_baseline_boxes(at):
    return [element.value.replace("\\", "") for element in at.sidebar.error if "Baseline missing" in element.value]


def test_an_absent_baseline_is_asked_for_as_its_own_xer(tmp_path, monkeypatch):
    # b.xer points to no baseline, c.xer and d.xer to project 370 which neither file holds: one box
    # names 370 once, with its two files; nothing for b.xer or for the usable a.xer
    c = {"pointer": "370", "data_date": "2026-03-09 08:00", "with_baseline": False}
    d = {"pointer": "370", "data_date": "2026-03-16 08:00", "with_baseline": False}
    boxes = _absent_baseline_boxes(_series(tmp_path, monkeypatch, {"a.xer": A, "c.xer": c, "d.xer": d}))
    assert len(boxes) == 1
    # counts and dates, no file name: a long series of long names made the line unreadable
    assert "P6 Project Baseline missing for 2 updates of 3" in boxes[0]
    unknown = "a project no loaded file holds (its code is unknown)"
    assert f"{unknown}, named by 2 updates (09 Mar 2026 → 16 Mar 2026" in boxes[0]
    assert "370" not in boxes[0]  # P6's internal project id: never shown
    assert "planned value, BEI, Late Activities and Missed tasks" in boxes[0]
    assert ".xer" not in boxes[0].replace("XER", "") and "Separate baseline file" in boxes[0]


def test_an_absent_baseline_is_named_by_its_code_when_another_loaded_file_holds_it(tmp_path, monkeypatch):
    # e.xer names project 2, held (code BL5) by a.xer only: the request gives the code to export
    e = {"pointer": "2", "data_date": "2026-03-16 08:00", "with_baseline": False, "flag": "Y"}
    a = {**A, "baseline_code": "BL5"}
    (box,) = _absent_baseline_boxes(_series(tmp_path, monkeypatch, {"a.xer": a, "e.xer": e}))
    assert "BL5, named by 1 update (16 Mar 2026)" in box
    assert "without use_project_baseline_flag" not in box


def test_no_request_for_updates_whose_earned_value_uses_each_users_primary_baseline(tmp_path, monkeypatch):
    # use_project_baseline_flag N: P6 measures against each user's primary baseline, not the pointer
    c = {"pointer": "370", "data_date": "2026-03-09 08:00", "with_baseline": False, "flag": "N"}
    assert not _absent_baseline_boxes(_series(tmp_path, monkeypatch, {"a.xer": A, "c.xer": c}))


def test_the_request_gives_no_p6_procedure(tmp_path, monkeypatch):
    # restoring, unassigning or converting a baseline changes the project in P6: the box only asks for the file
    c = {"pointer": "370", "data_date": "2026-03-09 08:00", "with_baseline": False}
    (box,) = _absent_baseline_boxes(_series(tmp_path, monkeypatch, {"a.xer": A, "c.xer": c}))
    assert not any(step in box for step in ("Restore", "Assign Baselines", "Maintain Baselines", "Convert"))


def test_no_request_when_no_pointer_names_an_absent_project(tmp_path, monkeypatch):
    assert not _absent_baseline_boxes(_series(tmp_path, monkeypatch))


def test_a_baseline_copied_from_another_project_is_refused_and_named(tmp_path, monkeypatch):
    c = {"original": "7", "data_date": "2026-03-09 08:00"}
    at = _series(tmp_path, monkeypatch, {"a.xer": A, "c.xer": c})
    assert any("c.xer" in w and "copied from a project not in the file" in w and "Not used" in w for w in _warnings(at))


def test_a_series_that_mixes_baseline_sources_says_so_with_the_files(tmp_path, monkeypatch):
    at = _series(tmp_path, monkeypatch)
    assert any(
        "mixes baseline sources" in w
        and "1 on the baseline of its file (a.xer)" in w
        and "1 on no baseline (b.xer)" in w
        for w in _warnings(at)
    )
    baseline_box(at, "bl_fallback").select("Planned dates in each file (target_*)")
    assert any("1 on the fallback (b.xer)" in w for w in _warnings(at.run()))


def test_a_baseline_dated_after_its_update_is_flagged_on_the_pages(tmp_path, monkeypatch):
    late = {"data_date": "2026-03-02 08:00", "baseline_date": "2026-04-06 08:00"}
    at = _health(_series(tmp_path, monkeypatch, {"a.xer": late}), "2026-03-02")
    assert any("a.xer" in w and "is after the update" in w for w in _page_warnings(at))


def test_a_baseline_that_finds_few_activities_is_flagged_on_the_pages(tmp_path, monkeypatch):
    few = {"data_date": "2026-03-02 08:00", "baseline_ids": ("A1", "X2")}  # finds 1 of 2: 50 %
    for page in ("views/health.py", "views/audit.py", "views/earned_value.py"):
        at = _series(tmp_path, monkeypatch, {"a.xer": few}).switch_page(page).run()
        assert any("a.xer" in w and "finds 1 of 2 tasks" in w for w in _page_warnings(at)), page


def test_the_pages_say_which_baseline_the_update_uses(tmp_path, monkeypatch):
    at = _series(tmp_path, monkeypatch)
    for page in ("views/health.py", "views/audit.py", "views/earned_value.py"):
        assert "Baseline used for 2026-03-09: none" in _banner(at.switch_page(page).run()), page


# --- a file exported with several projects -------------------------------------------------------------


def _portfolio(tmp_path, monkeypatch):
    """``a`` holds UPD, its baseline copy BL (as many activities as UPD) and three other projects; ``b`` holds
    UPD without baseline and the three others."""
    from file_projects import with_other_projects

    return _series(
        tmp_path,
        monkeypatch,
        {
            "a.xer": {"data_date": "2026-03-02 08:00"},
            "b.xer": {"pointer": "", "data_date": "2026-03-09 08:00", "with_baseline": False},
        },
        transform=with_other_projects,
    )


def test_a_file_whose_baseline_copy_ties_on_activities_is_read_for_its_project(tmp_path, monkeypatch):
    # a's baseline copy BL has as many TASK rows as UPD: set aside as a baseline copy, a is read for UPD,
    # and its P6 Project Baseline is found
    from xerscope.app.state import BL_EACH

    at = _portfolio(tmp_path, monkeypatch)
    assert not at.exception
    assert [s.project_code for s in at.session_state["store"]] == ["UPD", "UPD"]
    assert _baseline_box(at).value == BL_EACH


def test_the_fallback_applies_on_the_earned_value_page_of_a_portfolio_file(tmp_path, monkeypatch):
    at = _portfolio(tmp_path, monkeypatch)
    baseline_box(at, "bl_fallback").select("Planned dates in each file (target_*)")
    at = at.run().switch_page("views/earned_value.py").run()
    assert any(
        m.startswith("Baseline used for 2026-03-09: fallback (Planned dates in each file (target_*))")
        for m in _banner(at)
    )


def test_an_update_without_baseline_says_where_to_pick_one(tmp_path, monkeypatch):
    at = _series(tmp_path, monkeypatch).switch_page("views/earned_value.py").run()
    assert any(
        "b.xer: Baseline: none in file" in i and "When a file has no baseline" in i
        for i in (element.value.replace("\\", "") for element in at.info)
    )
    baseline_box(at, "bl_fallback").select("Separate baseline file")
    at.run()
    assert any("upload the baseline XER" in element.value for element in at.info)


@pytest.mark.parametrize("key", ["bl_choice", "bl_fallback"])
def test_the_baseline_upload_goes_away_with_another_choice(tmp_path, monkeypatch, key):
    at = _series(tmp_path, monkeypatch)
    baseline_box(at, key).select("Separate baseline file")
    assert [u.key for u in at.run().get("file_uploader")].count("bl_upload") == 1
    baseline_box(at, key).select("None")
    assert "bl_upload" not in [u.key for u in at.run().get("file_uploader")]


def test_the_projects_of_a_file_carry_their_data_date_and_which_are_baseline_copies():
    from xerscope.xer import baseline_copies

    table = _snapshot(baseline_code="UPD").file_projects
    assert table["data_date"].tolist() == [pd.Timestamp("2026-03-02 08:00"), pd.Timestamp("2026-01-05 08:00")]
    assert baseline_copies(table) == {"2": "1"}  # named by project 1's sum_base_proj_id, copied from it


def _file_box(at, name):
    return project_box(at, name)


def test_the_file_picker_tells_two_projects_of_the_same_code_apart(tmp_path, monkeypatch):
    from file_projects import with_other_projects

    files = {"a.xer": {"baseline_code": "UPD", "baseline_date": "2026-03-02 08:00"}}
    at = _series(tmp_path, monkeypatch, files, transform=with_other_projects)
    assert not at.exception
    box = _file_box(at, "a.xer")
    assert box.value == "1"
    assert [o for o in box.options if o.startswith("UPD")] == [
        "UPD · 02 Mar 2026 · 2 tasks",
        "UPD · 02 Mar 2026 · 2 tasks · baseline of UPD",
    ]
    assert _selection(at).set_index("file").loc["a.xer", "selected_by"] == "most TASK rows, 1 baseline copy set aside"


def test_a_project_picked_for_one_file_reads_that_file_only_and_its_baseline_again(tmp_path, monkeypatch):
    from file_projects import with_other_projects

    at = _health(_series(tmp_path, monkeypatch, transform=with_other_projects), "2026-03-02")
    used = "Baseline used for 2026-03-02: P6 Project Baseline in the file (BL"
    assert any(m.startswith(used) for m in _banner(at))
    before = {s.source: s for s in at.session_state["store"]}
    parsed = set(at.session_state["_parsed"])
    pick_project(at, "a.xer", "3")
    assert not at.exception
    after = {s.source: s for s in at.session_state["store"]}
    assert (after["a.xer"].project_id, after["a.xer"].project_code) == ("3", "P3")
    assert after["b.xer"] is before["b.xer"]
    assert [key[0] for key in set(at.session_state["_parsed"]) - parsed] == ["a.xer"]
    row = _selection(at).set_index("file").loc["a.xer"]
    assert row[["project", "selected_by", "baseline"]].tolist() == ["P3", "chosen", "Baseline: none in file"]
    at = _health(at, "2026-03-02")
    # P3 names no baseline: the file's P6 Project Baseline is no longer used for this update
    shown = [m for m in _banner(at) if m.startswith("Baseline used for 2026-03-02")]
    assert shown and not any("in the file (BL" in m for m in shown)
    # the memo is keyed on the project read from each file: nothing computed for project 1 is served
    keyed = [part for key in at.session_state["_memo"] for part in key if isinstance(part, tuple)]
    assert (("a.xer", "3"), ("b.xer", "1")) in keyed


def test_projects_picked_for_two_files_in_one_window_apply_together(tmp_path, monkeypatch):
    from file_projects import with_other_projects

    at = _series(tmp_path, monkeypatch, transform=with_other_projects)
    _file_box(at, "a.xer").set_value("3").run()
    _file_box(at, "b.xer").set_value("4").run()
    files_done(at)
    assert not at.exception
    assert [(s.source, s.project_code) for s in at.session_state["store"]] == [("a.xer", "P3"), ("b.xer", "P4")]


def test_a_locked_server_offers_no_separate_baseline_file_as_fallback(tmp_path, monkeypatch):
    """XERSCOPE_DATA_LOCKED: a separate file could only be uploaded, so neither selector offers it."""
    monkeypatch.setenv("XERSCOPE_DATA_LOCKED", "true")
    at = _series(tmp_path, monkeypatch)
    assert not at.exception
    assert "Separate baseline file" not in baseline_box(at).options
    assert "Separate baseline file" not in baseline_box(at, "bl_fallback").options
    assert not at.get("file_uploader")


def test_the_uploaded_baseline_applies_on_done_and_is_kept_once_the_window_closes(tmp_path, monkeypatch):
    """The upload box is a draft like the selectors: its file is the fallback once Done is pressed, and
    stays so when the window, and its emptied upload box, are gone."""
    from xerscope.analysis import Baseline

    monkeypatch.delenv("XERSCOPE_DATA_LOCKED", raising=False)
    at = _series(tmp_path, monkeypatch)
    baseline_box(at, "bl_fallback").select("Separate baseline file")
    data = (tmp_path / "a.xer").read_bytes()
    at.file_uploader(key="bl_upload").set_value([("bl.xer", data, "text/plain")]).run()
    assert not at.exception and at.session_state["fallback"] is None  # not applied before Done
    files_done(at)
    at.run()
    assert not at.get("file_uploader") and isinstance(at.session_state["fallback"], Baseline)
    assert at.session_state["bl_file"][0] == "bl.xer"


def test_the_banner_names_the_baseline_the_page_uses_when_the_file_baseline_cannot_be_read(tmp_path, monkeypatch):
    """a.xer names a usable P6 Project Baseline; if it cannot be built, the update falls back, and the
    banner says so as the page does instead of "in file"."""
    from xerscope.app import state

    at = _series(tmp_path, monkeypatch)
    baseline_box(at, "bl_fallback").select("Planned dates in each file (target_*)")
    monkeypatch.setattr(state, "_file_baseline", lambda snapshot: None)  # as when the copy fails to parse
    at = _health(at.run(), "2026-03-02")
    label = at.button(key="context_banner").label.replace("\\", "")
    assert " · BL fallback, planned dates · " in label
    assert "Baseline used for 2026-03-02: fallback (Planned dates in each file (target_*))" in _banner(at)


def _project_row(at, name):
    """The window's row of file ``name``: ``<project> · <picked by>[ · + baseline copy]``."""
    rows = [m.value.replace("\\", "") for m in at.markdown if m.value.replace("\\", "").startswith(f"{name} — ")]
    return rows[0].split(" — ", 1)[1]


def test_a_file_holding_its_project_and_its_baseline_copy_has_no_project_list(tmp_path, monkeypatch):
    at = _series(tmp_path, monkeypatch)  # a.xer: UPD and its baseline copy BL
    assert project_box(at, "a.xer") is None
    assert _project_row(at, "a.xer") == "**UPD** · only project not a baseline copy · + baseline copy"
    assert _project_row(at, "b.xer") == "**UPD** · only project"


def test_a_separate_baseline_file_of_another_project_is_named_against_the_pointer(tmp_path, monkeypatch):
    """The updates name project 370 (flag Y); the separate baseline file is project 1 (code OLDBL):
    a warning names both, since the numbers will not be P6's."""
    from xerkit import todo, xer_text

    from xerscope.app.state import BL_FILE

    c = {"pointer": "370", "data_date": "2026-03-09 08:00", "with_baseline": False, "flag": "Y"}
    baseline_file = tmp_path.parent / f"{tmp_path.name}-bl.xer"
    baseline_file.write_text(
        xer_text([todo("A1"), todo("A2")], project={"proj_short_name": "OLDBL"}, data_date="2026-03-02 08:00")
    )
    monkeypatch.setenv("XERSCOPE_BASELINE", str(baseline_file))
    at = _series(tmp_path, monkeypatch, {"c.xer": c}, keep_env=True)
    assert baseline_box(at).value == BL_FILE
    (warning,) = [w for w in _warnings(at) if "separate baseline file is" in w]
    assert "is OLDBL, status date 02 Mar 2026, but" in warning
    assert "a project no loaded file holds (1 update)" in warning
    assert "370" not in warning


def test_a_loaded_update_as_baseline_is_named_against_the_pointer(tmp_path, monkeypatch):
    """Both updates name project 370 (flag Y), absent; the user takes the first update as baseline:
    the same warning, since P6 measures against 370, not against that update."""
    from xerscope.app.state import BL_EACH, BL_FILE, BL_NONE, BL_PLANNED

    files = {
        name: {"pointer": "370", "data_date": stamp, "with_baseline": False, "flag": "Y"}
        for name, stamp in (("c.xer", "2026-03-09 08:00"), ("d.xer", "2026-03-16 08:00"))
    }
    at = _series(tmp_path, monkeypatch, files)
    box = baseline_box(at)
    first = next(o for o in box.options if o not in (BL_EACH, BL_FILE, BL_NONE, BL_PLANNED))
    box.select(first)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    (warning,) = [w for w in _warnings(at) if "baseline (a loaded update) is" in w]
    assert "is UPD, status date" in warning and "a project no loaded file holds (2 updates)" in warning
    assert "370" not in warning
