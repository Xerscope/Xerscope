"""Anonymous exports carry no source file name: it holds the real project code.

Every export is built from files named ``PROJ-SECRET-01.xer`` (baseline) and ``PROJ-SECRET-02.xer``
(update); the anonymised bytes, read cell by cell, must hold neither the name nor its stem.
"""

import io
import zipfile

import pandas as pd
import pytest
from xerkit import done, todo, xer_text

from xerscope.analysis import AnalysisContext, Baseline, builtin_standards, run_standard
from xerscope.analysis.changelog import changelog
from xerscope.analysis.evm import earned
from xerscope.analysis.progress import progress_delta
from xerscope.anonymize import Anonymizer, LeakError
from xerscope.app.diagnostic import diagnostic_frames
from xerscope.export import zip_tables
from xerscope.store import SnapshotStore
from xerscope.xer import load_snapshot
from xerscope.xer.parser import parse_bytes

OLD_NAME, NEW_NAME = "PROJ-SECRET-01.xer", "PROJ-SECRET-02.xer"
STEM = "PROJ-SECRET"
TASKS = [done("A1"), todo("B2"), todo("C3")]
PREDS = [("A1", "B2", "PR_FS", 0), ("B2", "C3", "PR_FS", 0)]


def _bytes(data_date: str) -> bytes:
    return xer_text(TASKS, PREDS, data_date=data_date, rsrc=["A1", "B2", "C3"]).encode("utf-8")


@pytest.fixture(scope="module")
def files():
    return {OLD_NAME: _bytes("2026-03-02 08:00"), NEW_NAME: _bytes("2026-03-09 08:00")}


@pytest.fixture(scope="module")
def snapshots(files):
    return [load_snapshot(data, name=name) for name, data in files.items()]


@pytest.fixture(scope="module")
def anonymizer(files):
    return Anonymizer.from_raws(parse_bytes(data, source=name) for name, data in files.items())


def _cells_of_zip(data: bytes) -> list[str]:
    cells = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        cells += archive.namelist()
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8-sig")
            cells.append(text)
            if name.endswith(".csv"):
                cells += [str(value) for value in pd.read_csv(io.StringIO(text), dtype=str).to_numpy().ravel()]
    return cells


def _assert_no_name(cells) -> None:
    held = [cell for cell in cells if STEM.lower() in str(cell).lower()]
    assert held == []


def test_the_diagnostic_holds_no_file_name_with_a_planned_dates_baseline(snapshots, anonymizer):
    new = snapshots[1]
    frames = diagnostic_frames(new, Baseline.planned(new), builtin_standards()["P6"], anonymous=True)
    _assert_no_name(_cells_of_zip(anonymizer.zip_frames(frames)))


def test_the_diagnostic_holds_no_file_name_with_a_baseline_file(snapshots, anonymizer):
    old, new = snapshots
    frames = diagnostic_frames(new, Baseline.from_snapshot(old), builtin_standards()["P6"], anonymous=True)
    _assert_no_name(_cells_of_zip(anonymizer.zip_frames(frames)))


def test_the_plain_diagnostic_keeps_the_baseline_label(snapshots):
    new = snapshots[1]
    frames = diagnostic_frames(new, Baseline.planned(new), builtin_standards()["P6"])
    assert frames["05_baseline"].loc[0, "baseline"] == f"planned dates (target_*) of {new.label}"


def test_the_diagnostic_zip_refuses_a_baseline_label_that_names_the_file(snapshots, anonymizer):
    new = snapshots[1]
    frames = diagnostic_frames(new, Baseline.planned(new), builtin_standards()["P6"])
    with pytest.raises(LeakError, match="file name"):
        anonymizer.zip_frames(frames)


def test_the_power_bi_tables_hold_no_file_name(snapshots, anonymizer):
    store = SnapshotStore(snapshots)
    _assert_no_name(_cells_of_zip(zip_tables(store, "csv", anonymizer.frame)))


def test_the_selection_list_holds_no_file_name(snapshots, anonymizer):
    selection = SnapshotStore(snapshots).selection()
    assert NEW_NAME in selection["file"].tolist()
    _assert_no_name(anonymizer.csv(selection).decode("utf-8-sig").splitlines())


def test_the_schedule_health_lists_hold_no_file_name(snapshots, anonymizer):
    old, new = snapshots
    store = SnapshotStore(snapshots)
    baseline = Baseline.from_snapshot(old)
    cells = []
    for standard in builtin_standards().values():
        for result in run_standard(standard, AnalysisContext(new, store, baseline)):
            if not result.flagged.empty:
                cells += anonymizer.csv(result.flagged).decode("utf-8-sig").splitlines()
    _assert_no_name(cells)


def test_the_changelog_earned_hours_and_progress_csv_hold_no_file_name(snapshots, anonymizer):
    old, new = snapshots
    baseline = Baseline.from_snapshot(old)
    for frame in (changelog(old, new), earned(new, baseline).reset_index(), progress_delta(old, new, baseline)):
        _assert_no_name(anonymizer.csv(frame).decode("utf-8-sig").splitlines())


def test_the_anonymised_xer_extract_holds_no_file_name(files, snapshots, anonymizer):
    data_dates = {snapshot.source: snapshot.data_date for snapshot in snapshots}
    extract = anonymizer.zip_xers((parse_bytes(data, source=name), data_dates[name]) for name, data in files.items())
    _assert_no_name(_cells_of_zip(extract))


def test_a_cell_that_embeds_a_file_name_is_refused(anonymizer):
    for text in (f"planned dates of 2026-03-09 · {NEW_NAME}", f"BL 2026-03-02 · {OLD_NAME.lower()}", f"x {STEM}-01 y"):
        with pytest.raises(LeakError, match="file name"):
            anonymizer.csv(pd.DataFrame({"reason": [text]}))


def test_a_stem_inside_a_longer_word_is_not_a_file_name(anonymizer):
    assert anonymizer.csv(pd.DataFrame({"reason": ["PROJ-SECRET-011"]}))  # stems are PROJ-SECRET-01 and -02
