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
    # By hand from the XER (TASKPRED lag_hr_cnt, TASK cstr_type; CS_MEOB = finish on or before):
    # ST-010 is active, its successors MEP-030 and MEP-040 carry a 40 h lag; MEP-080 has a SS (lag 40) and a FS
    # predecessor; CX-040 and MS-030 carry CS_MEOB; MS-030, a finish milestone, has no successor.
    assert s["ST-010"] == "in progress · task dependent · pred FS · succ FS · lag · progress override"
    assert s["MEP-080"] == "not started · task dependent · pred FS+SS · succ FS · lag"
    assert s["CX-040"] == "not started · task dependent · finish on or before · pred FS · succ FS"
    assert s["MS-030"] == "not started · finish milestone · finish on or before · pred FS · succ none"
    # Four lagged links join 7 activities (ST-010, MEP-030, MEP-040, MEP-060, MEP-080, FIT-010, FIT-020);
    # two activities hold a constraint.
    assert sum("lag" in label.split(" · ") for label in s) == 7
    assert sum("finish on or before" in label.split(" · ") for label in s) == 2


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
