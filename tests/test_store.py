from xerscope.export import write_tables, zip_tables


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
