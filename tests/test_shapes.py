"""`xerscope recalc --report`: differences grouped by the shape of the activity."""

from xerscope.analysis.cpm import compare_with_stored
from xerscope.verify.shapes import difference_report, shapes
from xerscope.xer import load_snapshot


def test_shape_names_status_type_links_and_option(require_reference):
    snap = load_snapshot(require_reference("xerlock/sample-schedule.xer"))
    s = shapes(snap)
    assert len(s) == len(snap.activities)
    assert s["EW-030"] == "in progress · task dependent · pred FS · succ FS · progress override"
    assert s["MS-010"].startswith("complete · start milestone")


def test_report_groups_the_known_xerlock_difference(require_reference):
    """xerlock's sample stores late dates P6 would not write for EW-030 (tests/test_cpm.py
    NOT_P6): the report must land on that one shape and name the activity."""
    snap = load_snapshot(require_reference("xerlock/sample-schedule.xer"))
    rep = difference_report(snap, compare_with_stored(snap))
    assert len(rep) == 1
    row = rep.iloc[0]
    assert row["example"] == "EW-030" and row["wrong"] == 3 and "late_end_date" in row["fields"]
    assert row["shape"] == "in progress · task dependent · pred FS · succ FS · progress override"


def test_report_is_empty_when_everything_agrees(require_reference):
    snap = load_snapshot(require_reference("xereditor/sample.xer"))
    assert difference_report(snap, compare_with_stored(snap)).empty
