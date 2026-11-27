import pytest
from xerkit import active, done, snap, todo

from xerscope.export import write_tables, zip_tables
from xerscope.store import SnapshotStore
from xerscope.xer import load_snapshot, xer_files


def test_sorted_by_data_date(store):
    dates = [s.data_date for s in store]
    assert dates == sorted(dates)
    assert len(store) == 8
    assert store.warnings == []  # one project, one status per day: nothing to warn about


@pytest.mark.oracle("property")
def test_two_project_codes_warn_with_both_codes_sorted():
    """store.py: more than one project code across the snapshots is a warning listing the sorted codes."""
    old = snap([todo("A")], data_date="2026-03-02 08:00", project={"proj_short_name": "OLD"})
    new = snap([todo("A")], data_date="2026-03-09 08:00", project={"proj_short_name": "NEW"})
    warnings = SnapshotStore([old, new]).warnings
    assert warnings == ["project code differs across snapshots (renamed or other project): ['NEW', 'OLD']"]


@pytest.mark.oracle("property")
def test_two_updates_on_one_day_warn_once_naming_the_day():
    morning = snap([todo("A")], data_date="2026-03-02 08:00")
    evening = snap([todo("A")], data_date="2026-03-02 17:00")
    warnings = SnapshotStore([evening, morning]).warnings
    assert warnings == ["several updates on 2026-03-02 at other hours: test.xer, test.xer"]


def test_task_ids_change_but_codes_join(store):
    a = store.first.tasks.set_index("task_code")["task_id"]
    b = store.latest.tasks.set_index("task_code")["task_id"]
    assert (a != b.reindex(a.index)).all()  # every internal id changed
    h = store.history
    assert (h.groupby("task_code")["snapshot_idx"].nunique().loc["E1010"]) == len(store)


def test_added_activity_appears_from_week_4(store):
    h = store.history
    assert sorted(h.loc[h["task_code"] == "C3045", "snapshot_idx"]) == [4, 5, 6, 7]


def test_summary_tracks_slip(store):
    s = store.summary
    assert s["forecast_finish"].is_monotonic_increasing
    assert s.loc[5, "finish_shift_wd"] < 0  # vendor delay week: the finish goes later, days lost
    assert str(s.loc[2, "finish_shift_wd"]) == "0.0"  # a week without a move: 0.0, never -0.0
    assert s["complete"].iloc[-1] > s["complete"].iloc[0]


@pytest.mark.oracle("property")
def test_summary_counts_activities_by_status_and_links():
    """Hand-made, two updates. Week 1: D1, D2 complete, A1 in progress, N1, N2 not started; 3 links.
    Week 2: N1 finished too. The columns of dim_snapshot, by hand: complete / in progress / not started
    2 / 1 / 2 then 3 / 1 / 1 (they add up to the 5 activities); percent complete by count 40.0 then 60.0."""
    links = [("D1", "A1", "FS", 0), ("A1", "N1", "FS", 0), ("N1", "N2", "FS", 0)]
    week_1 = snap([done("D1"), done("D2"), active("A1"), todo("N1"), todo("N2")], links, data_date="2026-03-02 08:00")
    week_2 = snap([done("D1"), done("D2"), active("A1"), done("N1"), todo("N2")], links, data_date="2026-03-09 08:00")
    summary = SnapshotStore([week_1, week_2]).summary
    assert summary["activities"].tolist() == [5, 5]
    assert summary["complete"].tolist() == [2, 3]
    assert summary["in_progress"].tolist() == [1, 1]
    assert summary["not_started"].tolist() == [2, 1]
    assert summary["relationships"].tolist() == [3, 3]
    assert summary["pct_complete_count"].tolist() == [40.0, 60.0]


def test_previous(store):
    assert store.previous(store.first) is None
    assert store.previous(store.latest) is store[len(store) - 2]


def test_export(store, tmp_path):
    paths = write_tables(store, tmp_path, "parquet")
    assert {p.name for p in paths} == {
        "dim_snapshot.parquet",
        "fact_activity.parquet",
        "fact_relationship.parquet",
        "fact_assignment.parquet",
    }
    assert zip_tables(store, "csv")[:2] == b"PK"


def test_folder_scan_accepts_upper_case_extension(tmp_path):
    """P6 on some setups writes .XER; the app, the CLI and SnapshotStore must see those files."""
    from xerscope.xer import xer_files

    for name in ("b.XER", "a.xer", "c.txt"):
        (tmp_path / name).write_bytes(b"")
    assert [p.name for p in xer_files(tmp_path)] == ["a.xer", "b.XER"]


def test_folder_scan_lists_the_p6_xml_exports_apart_from_the_updates(tmp_path):
    """A P6 XML export next to the updates is a baseline file, never an update."""
    from xerscope.xer import pmxml_files, xer_files

    for name in ("b.XML", "a.xml", "w1.xer", "c.txt"):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "folder.xml").mkdir()
    assert [p.name for p in pmxml_files(tmp_path)] == ["a.xml", "b.XML"]
    assert [p.name for p in xer_files(tmp_path)] == ["w1.xer"]


def test_load_snapshot_from_bytes_equals_from_path(sample_dir):

    path = xer_files(sample_dir)[0]
    a, b = load_snapshot(path), load_snapshot(path.read_bytes(), name=path.name)
    assert len(a.tasks) == len(b.tasks)
    assert a.data_date == b.data_date


def test_same_data_date_twice_is_refused(store):
    """Two files with one data date (a draft and its next version, an update and its baseline
    copy): the store does not guess which one is the update, it names every file of the date."""
    from dataclasses import replace

    import pytest

    from xerscope.store import DuplicateDataDate, SnapshotStore

    first = store.first
    twins = [replace(first, source="v0.8.xer"), replace(first, source="v0.5.xer")]
    with pytest.raises(DuplicateDataDate) as caught:
        SnapshotStore([*twins, *store])
    assert str(caught.value) == (
        f"several files per status date, keep one per date: "
        f"{first.data_date:%Y-%m-%d}: {first.source}, v0.5.xer, v0.8.xer"
    )


def test_selection_lists_every_file_in_the_series(store):
    table = store.selection()
    assert table["file"].tolist() == sorted(s.source for s in store)
    assert "status" not in table and "reason" not in table


def test_store_column_lists_exist_in_snapshot_frames(store):
    from xerscope import store as store_mod
    from xerscope.xer import model

    for cols, declared in (
        (store_mod.HISTORY_COLS, [*model.TASK_COLS, *model.LABOR_COLS]),
        (store_mod.REL_COLS, model.REL_COLS_MODEL),
        (store_mod.ASSIGNMENT_COLS, model.ASSIGNMENT_COLS_MODEL),
    ):
        assert set(cols) <= set(declared), set(cols) - set(declared)
    s = store.latest
    for cols, frame in (
        (store_mod.HISTORY_COLS, s.activities),
        (store_mod.REL_COLS, s.relationships),
        (store_mod.ASSIGNMENT_COLS, s.assignments),
    ):
        assert set(cols) <= set(frame.columns), set(cols) - set(frame.columns)


def test_load_snapshot_from_bytes_needs_a_name():
    with pytest.raises(ValueError, match="file name"):
        load_snapshot(b"ERMHDR\t24.12")


def test_fact_activity_carries_hours_per_day_so_days_convert_back():
    """total_float_d is in days of each activity's calendar: 80 h is 10 d on C8, 8 d on C10.
    Power BI needs hours_per_day to sum or compare them (days x hours_per_day = P6's hours)."""
    from xerkit import snap, todo

    from xerscope.export import export_tables
    from xerscope.store import SnapshotStore

    s = snap([todo("A", clndr_id="C8", total_float_hr_cnt="80"), todo("B", clndr_id="C10", total_float_hr_cnt="80")])
    fact = export_tables(SnapshotStore([s]))["fact_activity"].set_index("task_code")
    assert fact["total_float_d"].to_dict() == {"A": 10.0, "B": 8.0}
    assert fact["hours_per_day"].to_dict() == {"A": 8.0, "B": 10.0}
    assert (fact["total_float_d"] * fact["hours_per_day"]).tolist() == [80.0, 80.0]
