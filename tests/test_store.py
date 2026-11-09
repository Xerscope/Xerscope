import pytest

from xerscope.export import write_tables, zip_tables
from xerscope.xer import load_snapshot, xer_files


def test_sorted_by_data_date(store):
    dates = [s.data_date for s in store]
    assert dates == sorted(dates)
    assert len(store) == 8
    assert store.warnings == []


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
    assert s.loc[5, "finish_shift_wd"] > 0  # vendor delay week
    assert s["complete"].iloc[-1] > s["complete"].iloc[0]


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
