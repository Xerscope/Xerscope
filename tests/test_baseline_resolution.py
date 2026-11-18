"""Which baseline an update is measured against when its file does not hold the one it names: each
way of finding it on a case small enough to follow by hand."""

import pandas as pd
from pmxmlkit import NAMESPACE, _fields, activity, baseline, calendar
from xerkit import snap, todo

from xerscope.analysis import Baseline
from xerscope.analysis.baseline import EV_BASES, content_digest
from xerscope.analysis.baseline_resolution import (
    IN_EXPORT,
    IN_FILE,
    LOADED_UPDATE,
    NOT_FOUND,
    SAME_GENERATION,
    UNDECIDED,
    Export,
    Resolution,
    resolution,
    versions_around,
)
from xerscope.analysis.evm import ev_point
from xerscope.xer import load_snapshot

# An export of five versions of one project, each with its Project Baseline. Baselines 101, 201 and 301
# are copies of one baseline ("june"); 401 and 501 are copies of the next one ("september").
CONTENT = {"101": "june", "201": "june", "301": "june", "401": "september", "501": "september"}
EXPORT = Export(
    baseline_ids=frozenset(CONTENT),
    project_baselines={"100": "101", "200": "201", "300": "301", "400": "401", "500": "501"},
    same_content=lambda one, other: CONTENT[one] == CONTENT[other],
)


def resolve(pointer: str, project_id: str, in_file: bool = False, loaded=(), export: Export | None = EXPORT):
    return resolution(pointer, project_id, in_file, frozenset(loaded), export)


def test_the_baseline_of_its_own_file_comes_first():
    assert resolve("151", "150", in_file=True) == Resolution(IN_FILE, "151")
    assert resolve("201", "200", in_file=True) == Resolution(IN_FILE, "201")  # also in the export: its file first


def test_a_baseline_the_export_holds_under_the_id_named_is_exact():
    assert resolve("201", "200") == Resolution(IN_EXPORT, "201")
    # exact comes before any other way, even when a loaded update carries the same id
    assert resolve("201", "200", loaded=["201"]) == Resolution(IN_EXPORT, "201")
    assert resolve("201", "200").is_exact and resolve("151", "150", in_file=True).is_exact


def test_a_pointer_that_is_the_project_of_a_loaded_update_is_that_update():
    # project 300 names 150 as its baseline: the project another loaded file was exported from
    found = resolve("150", "300", loaded=["150", "300"])
    assert found == Resolution(LOADED_UPDATE, "150") and not found.is_exact
    assert resolve("150", "300", loaded=["150"], export=None) == Resolution(LOADED_UPDATE, "150")


def test_between_two_versions_that_hold_copies_of_one_baseline_that_baseline_is_taken():
    # project 150 (baseline 151, not exported) was created between versions 100 and 200, both "june"
    found = resolve("151", "150")
    assert found == Resolution(SAME_GENERATION, "101", "100", "200")
    assert not found.is_exact
    # 250: between 200 and 300, both "june"; the copy read is the one of the version before
    assert resolve("251", "250") == Resolution(SAME_GENERATION, "201", "200", "300")


def test_between_two_versions_that_hold_different_baselines_nothing_is_taken():
    # 350: between 300 ("june") and 400 ("september"): the baseline changed around it
    found = resolve("351", "350")
    assert (found.found_by, found.baseline_id) == (UNDECIDED, "")
    assert (found.version_before, found.version_after) == ("300", "400")
    assert found.note == "the versions around it hold different baselines"


def test_with_a_version_on_one_side_only_nothing_is_taken():
    # 550 is later than every version of the export: 500 holds "september", nothing says it still held
    after = resolve("551", "550")
    assert (after.found_by, after.baseline_id, after.version_before, after.version_after) == (UNDECIDED, "", "500", "")
    assert after.note == "no version of the export after it"
    before = resolve("51", "50")
    assert (before.found_by, before.version_before, before.version_after) == (UNDECIDED, "", "100")
    assert before.note == "no version of the export before it"


def test_the_version_of_the_update_itself_is_not_one_of_the_versions_around_it():
    # project 300 is in the export with baseline 301, but the update names 299, a baseline it had before
    found = resolve("299", "300")
    assert (found.version_before, found.version_after) == ("200", "400")
    assert found.found_by == UNDECIDED  # 200 holds "june", 400 "september"


def test_nothing_is_found_without_a_pointer_an_export_or_a_version():
    assert resolve("", "150") == Resolution(NOT_FOUND, note="the update names no baseline")
    assert resolve("151", "150", export=None) == Resolution(NOT_FOUND, note="no P6 XML export of baselines")
    empty = Export(frozenset(), {}, lambda one, other: False)
    assert resolve("151", "150", export=empty) == Resolution(
        NOT_FOUND, note="no project of the export names a baseline it holds"
    )


def test_versions_are_ordered_by_object_id_as_numbers():
    versions = ["100", "200", "1000", "90"]
    assert versions_around("150", versions) == ("100", "200")
    assert versions_around("950", versions) == ("200", "1000")  # 1000 after 200: numbers, not text
    assert versions_around("95", versions) == ("90", "100")
    assert versions_around("200", versions) == ("100", "1000")  # itself is left out
    assert versions_around("80", versions) == ("", "90")
    assert versions_around("2000", versions) == ("1000", "")


def test_an_id_that_is_not_a_number_has_no_version_around_it():
    assert versions_around("abc", ["100", "200"]) == ("", "")
    assert versions_around("150", ["100", "x7", "200"]) == ("100", "200")  # the id that is no number is skipped
    assert resolve("151", "abc").found_by == NOT_FOUND


# --- copies of one baseline have the same content, whatever ids P6 gave them ----------------------------


def _baseline_copy(object_id: str, first_task_id: int, calendar_id: str, hours: int = 40, holiday: str = ""):
    """A baseline of two activities on a calendar of its own, as P6 stores one copy of it: ``object_id``,
    the ids of its activities and of its calendar belong to the copy; its code follows its version."""
    work_week = calendar(calendar_id, "Site calendar")
    if holiday:
        work_week = work_week.replace("2026-04-03", holiday)
    first = activity(
        "A", str(first_task_id), "2026-03-02T08:00:00", "2026-03-06T17:00:00", hours, CalendarObjectId=calendar_id
    )
    second = activity(
        "B", str(first_task_id + 1), "2026-03-09T08:00:00", "2026-03-13T17:00:00", 40, CalendarObjectId=calendar_id
    )
    crew = {"ObjectId": first_task_id + 100, "ActivityObjectId": first_task_id, "ResourceObjectId": "3"}
    assignment = (
        f"<ResourceAssignment>{_fields({**crew, 'ResourceType': 'Labor', 'PlannedUnits': hours})}</ResourceAssignment>"
    )
    body = baseline(object_id, f"V{object_id} - B1", [work_week, first, second, assignment])
    export = f'<?xml version="1.0"?><APIBusinessObjects xmlns="{NAMESPACE}">{body}</APIBusinessObjects>'
    return load_snapshot(export.encode(), name="export.xml", project_id=object_id)


def test_two_copies_of_a_baseline_have_one_digest_and_give_the_same_measure():
    one = _baseline_copy("501", first_task_id=11, calendar_id="21")
    other = _baseline_copy("601", first_task_id=9011, calendar_id="31")
    assert one.project_code != other.project_code and one.activities["task_id"].tolist() == ["11", "12"]
    assert other.activities["task_id"].tolist() == ["9011", "9012"]
    assert (one.assignments["taskrsrc_id"].tolist(), other.assignments["taskrsrc_id"].tolist()) == (["111"], ["9111"])
    assert content_digest(one) == content_digest(other)

    update = snap([todo("A", target_work_qty="40"), todo("B", target_work_qty="40")], data_date="2026-03-09 08:00")
    for basis in EV_BASES:
        against_one, against_other = Baseline.from_snapshot(one, basis), Baseline.from_snapshot(other, basis)
        pd.testing.assert_frame_equal(
            against_one.frame.drop(columns="bl_clndr_id"), against_other.frame.drop(columns="bl_clndr_id")
        )
        assert ev_point(update, against_one).as_row() == ev_point(update, against_other).as_row()
    # hand check on the default basis: A (40 h, 2 to 6 March) is all planned by 9 March 08:00, B not started
    measured = ev_point(update, Baseline.from_snapshot(one))
    assert (measured.bac_hr, measured.pv_hr) == (80.0, 40.0)


def test_any_change_of_what_is_measured_changes_the_digest():
    reference = content_digest(_baseline_copy("501", first_task_id=11, calendar_id="21"))
    more_hours = _baseline_copy("601", first_task_id=9011, calendar_id="31", hours=48)
    other_holiday = _baseline_copy("601", first_task_id=9011, calendar_id="31", holiday="2026-03-04")
    assert content_digest(more_hours) != reference
    assert content_digest(other_holiday) != reference
