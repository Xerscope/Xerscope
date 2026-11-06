"""Baselines read from a P6 XML export (xer/pmxml.py): the baseline chosen, the fields and calendars
converted to the XER's, and the result identical to the same baseline read from XER."""

from datetime import date

import pandas as pd
import pytest
from pmxmlkit import activity, baseline, pmxml_bytes
from xerkit import snap, todo

from xerscope.analysis import Baseline
from xerscope.analysis.evm import ev_point
from xerscope.xer import XerError, is_pmxml, list_baselines, load_snapshot
from xerscope.xer.pmxml import read_pmxml_baseline

# activity dates as P6 XML writes them: the true end of the last period (17:00), unlike calendar periods
A1 = activity("A1", "1001", "2026-03-02T08:00:00", "2026-03-06T17:00:00", 40)
A2 = activity("A2", "1002", "2026-03-09T08:00:00", "2026-03-13T17:00:00", 40)
TWO = pmxml_bytes([baseline("370", "BL-1", [A1]), baseline("380", "BL-2", [A1, A2])], current_baseline="380")


def test_a_p6_xml_export_is_recognised_and_its_baselines_listed():
    assert is_pmxml(TWO) and not is_pmxml(b"ERMHDR\t23.12")
    baselines, current = list_baselines(TWO, "export.xml")
    assert [(b.object_id, b.code, b.activities) for b in baselines] == [("370", "BL-1", 1), ("380", "BL-2", 2)]
    assert current == "380" and baselines[0].original_project_id == "1"


def test_the_baseline_read_is_the_one_asked_for_else_the_project_baseline():
    assert load_snapshot(TWO, name="export.xml").project_id == "380"  # CurrentBaselineProjectObjectId
    assert load_snapshot(TWO, name="export.xml", project_id="370").project_id == "370"  # an update's pointer
    only = pmxml_bytes([baseline("370", "BL-1", [A1])])
    assert load_snapshot(only, name="one.xml").project_id == "370"  # the only one, none named


def test_an_ambiguous_or_absent_baseline_is_refused_with_the_list():
    several = pmxml_bytes([baseline("370", "BL-1", [A1]), baseline("380", "BL-2", [A1])])
    with pytest.raises(XerError, match=r"2 baselines and none named.*370 \(BL-1\), 380 \(BL-2\)"):
        load_snapshot(several, name="export.xml")
    with pytest.raises(XerError, match=r"baseline 999 is not in this file"):
        load_snapshot(TWO, name="export.xml", project_id="999")
    with pytest.raises(XerError, match="no baseline in this P6 XML export"):
        load_snapshot(pmxml_bytes([]), name="export.xml")


def test_a_calendar_reads_as_the_xer_writes_it():
    """XML work periods end on their last working minute (11:59), the XER's on the next one (12:00);
    an exception without work time is a holiday, one with work time a worked day."""
    calendar = load_snapshot(TWO, name="export.xml").calendar("8")
    assert calendar.week[0] == ((480, 720), (780, 1020))  # Monday 08:00-12:00, 13:00-17:00
    assert calendar.week[6] == ()  # Sunday
    assert calendar.exceptions[date(2026, 4, 3)] == ()
    assert calendar.exceptions[date(2026, 3, 7)] == ((480, 720),)
    assert calendar.hours_per_day == 8


def test_fields_are_converted_to_the_xer_codes():
    started = activity(
        "B1", "2001", "2026-03-02T08:00:00", "2026-03-06T17:00:00", 40,
        Status="In Progress", Type="Resource Dependent", PercentCompleteType="Physical",
        PhysicalPercentComplete=0.25, PrimaryConstraintType="Start On or After",
        PrimaryConstraintDate="2026-03-02T08:00:00", ActualStartDate="2026-03-02T08:00:00",
    )  # fmt: skip
    raw = read_pmxml_baseline(pmxml_bytes([baseline("370", "BL-1", [started])]), "export.xml")
    row = raw.table("TASK").iloc[0]
    assert (row["status_code"], row["task_type"], row["complete_pct_type"]) == ("TK_Active", "TT_Rsrc", "CP_Phys")
    assert row["phys_complete_pct"] == "25"  # a fraction in XML, 0-100 in XER
    assert (row["cstr_type"], row["cstr_date"]) == ("CS_MSOA", "2026-03-02 08:00")
    assert (row["target_start_date"], row["act_start_date"]) == ("2026-03-02 08:00", "2026-03-02 08:00")


def dates(start: str, finish: str) -> dict:
    """Planned and current dates alike, as in a baseline taken before any progress."""
    return dict(target_start_date=start, target_end_date=finish, early_start_date=start, early_end_date=finish)


def test_the_same_baseline_read_from_xml_or_xer_gives_the_same_planned_value():
    """The XER of the baseline (xerkit) and its XML export give the same baseline frame and the same PV
    on an update: A1 runs 2026-03-02 08:00 to 2026-03-06 17:00 (40 h), A2 the next week; on Wednesday
    08:00, 16 of A1's 40 working hours are past: PV = 40 x 16 / 40 = 16 h."""
    from_xml = Baseline.from_snapshot(load_snapshot(TWO, name="export.xml"))
    planned = dict(target_work_qty="40", target_drtn_hr_cnt="40", remain_drtn_hr_cnt="40")
    from_xer = Baseline.from_snapshot(
        snap(
            [
                todo("A1", **dates("2026-03-02 08:00", "2026-03-06 17:00"), **planned),
                todo("A2", **dates("2026-03-09 08:00", "2026-03-13 17:00"), **planned),
            ]
        )
    )
    columns = ["bl_start", "bl_finish", "bl_labor_hr", "ev_start", "ev_finish", "ev_labor_hr"]
    pd.testing.assert_frame_equal(
        from_xml.frame[columns], from_xer.frame[columns], check_dtype=False, check_index_type=False
    )
    update = snap([todo("A1"), todo("A2")], data_date="2026-03-04 08:00")
    assert ev_point(update, from_xml).pv_hr == pytest.approx(16) == ev_point(update, from_xer).pv_hr


def test_each_update_is_measured_against_the_baseline_its_file_names_in_the_xml(tmp_path, monkeypatch):
    """The series' Project Baseline changed: a.xer names 370, b.xer 380, neither file holds it. With the
    P6 XML export as the separate baseline file, each update takes its own from it, as P6 measures it."""
    from pathlib import Path

    from conftest import baseline_box, read_folder
    from file_projects import two_projects
    from streamlit.testing.v1 import AppTest

    import xerscope
    from xerscope.app.state import BL_EACH, BL_FILE

    data = tmp_path / "updates"
    data.mkdir()
    (data / "a.xer").write_text(two_projects(pointer="370", with_baseline=False, data_date="2026-03-02 08:00"))
    (data / "b.xer").write_text(two_projects(pointer="380", with_baseline=False, data_date="2026-03-09 08:00"))
    export = tmp_path / "export.xml"
    export.write_bytes(TWO)
    monkeypatch.setenv("XERSCOPE_DATA", str(data))
    monkeypatch.setenv("XERSCOPE_BASELINE", str(export))
    at = read_folder(
        AppTest.from_file(str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py"), default_timeout=120).run()
    )
    baseline_box(at, "bl_choice").select(BL_EACH)
    baseline_box(at, "bl_fallback").select(BL_FILE)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    used = {}
    at = at.switch_page("views/health.py").run()
    for stamp in ("2026-03-02", "2026-03-09"):
        picker = next(box for box in at.selectbox if box.key == "health_snap")
        picker.select(next(option for option in picker.options if option.startswith(stamp)))
        at.run()
        help_lines = at.button(key="context_banner").help.replace("\\", "").split("  \n")
        used[stamp] = next(line for line in help_lines if line.startswith(f"Baseline used for {stamp}"))
    assert used["2026-03-02"].endswith("P6 Project Baseline 370 from export.xml")
    assert used["2026-03-09"].endswith("P6 Project Baseline 380 from export.xml")


def test_a_name_found_only_in_the_xml_baseline_never_reaches_an_anonymized_download(tmp_path, monkeypatch):
    """An activity deleted since the baseline exists in the XML only, so the anonymizer, which reads the
    updates, never saw its name. The earned value CSV lists it (plain: yes); anonymized, neither its name
    nor its Activity ID is written."""
    from pathlib import Path

    from conftest import read_folder
    from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage
    from streamlit.testing.v1 import AppTest

    import xerscope
    from xerscope.sample import generate

    saved: dict[str, bytes] = {}
    real = MemoryMediaFileStorage.load_and_get_id

    def keep(self, path_or_data, mimetype, kind, filename=None):
        file_id = real(self, path_or_data, mimetype, kind, filename)
        saved[file_id] = self._files_by_id[file_id].content
        return file_id

    monkeypatch.setattr(MemoryMediaFileStorage, "load_and_get_id", keep)
    data = tmp_path / "updates"
    generate(data, weeks=2)
    from xerscope.xer import load_snapshot as read

    first = read(sorted(data.glob("*.xer"))[0])
    kept = [
        activity(
            row.task_code,
            str(row.task_id),
            row.target_start_date.isoformat(),
            row.target_end_date.isoformat(),
            float(row.labor_budget_hr),
            CalendarObjectId=row.clndr_id,
        )
        for row in first.activities.dropna(subset=["target_start_date", "target_end_date"]).itertuples()
    ]
    gone = activity("ZZGONE", "990001", "2026-08-31T08:00:00", "2026-09-04T17:00:00", 40, Name="Secret gone activity")
    export = tmp_path / "export.xml"
    export.write_bytes(pmxml_bytes([baseline("370", "BL-1", [*kept, gone], data_date="2026-08-31T08:00:00")]))
    monkeypatch.setenv("XERSCOPE_DATA", str(data))
    monkeypatch.setenv("XERSCOPE_BASELINE", str(export))
    app = str(Path(xerscope.__file__).parent / "app" / "streamlit_app.py")
    at = read_folder(AppTest.from_file(app, default_timeout=300).run()).switch_page("views/earned_value.py").run()

    def ev_csv(at) -> bytes:
        next(b for b in at.button if b.label == "Prepare anonymized downloads").click().run() if any(
            b.label == "Prepare anonymized downloads" for b in at.button
        ) else None
        button = next(b for b in at.get("download_button") if b.proto.label.startswith("Download CSV"))
        return saved[button.proto.url.rsplit("/", 1)[-1].split(".")[0]]

    anonymized = ev_csv(at)
    assert b"Secret gone activity" not in anonymized and b"ZZGONE" not in anonymized
    at.session_state["anon_exports"] = False
    plain = ev_csv(at.run())
    assert b"ZZGONE" in plain  # the test exercises the case: the plain download does list it
