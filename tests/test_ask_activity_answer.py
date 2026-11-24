"""The Ask field's sentence on one activity (analysis/ask/answer.py ``activity_answer``).

Schedules as in test_activity_forensics: C8 calendar (Mon-Fri 08:00-17:00), a 40 h activity runs
Monday to Friday 17:00. Expected sentences are written by hand from the shifts computed there."""

import pytest
from xerkit import snap, todo

from xerscope.analysis import query
from xerscope.analysis.activity_forensics import EARLIER_UPDATE, activity_half_step

WEEK_LATER = "2026-03-09 08:00"
A_THEN_B = [("A", "B", "FS", 0)]
FORTY_HOURS = dict(target_drtn_hr_cnt="40", remain_drtn_hr_cnt="40")


def _week(a_finish: str, b_finish: str) -> list[dict]:
    """A then B, each finishing as stored (the stored dates are the recalculated ones: no engine gap)."""
    return [todo("A", early_end_date=a_finish, **FORTY_HOURS), todo("B", early_end_date=b_finish, **FORTY_HOURS)]


EARLIER = _week("2026-03-06 17:00", "2026-03-13 17:00")


def _read(code: str, later_tasks: list[dict] | None = None):
    later = snap(later_tasks or _week("2026-03-13 17:00", "2026-03-20 17:00"), A_THEN_B, data_date=WEEK_LATER)
    return activity_half_step(snap(EARLIER, A_THEN_B), later, code)


@pytest.mark.oracle("standard")
@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        (
            "en",
            "B finishes 5.0 wd later than in the previous update (20/03/2026): progress -5.0 wd, "
            "replanning +0.0 wd, residual +0.0 wd.",
        ),
        (
            "fr",
            "B finit 5.0 j plus tard qu'à la mise à jour précédente (20/03/2026) : avancement -5.0 j, "
            "replanification +0.0 j, résidu +0.0 j.",
        ),
    ],
)
def test_a_week_of_progress_is_said_as_a_slip_in_the_sentence_language(lang, expected):
    """B follows A (40 h each), neither started a week later: B's finish moves 5 wd, all at progress."""
    assert query.activity_answer("B", _read("B"), lang) == expected


@pytest.mark.oracle("standard")
def test_an_activity_that_did_not_move_says_so():
    same = [todo("A", early_end_date="2026-03-06 17:00", **FORTY_HOURS)]
    read = activity_half_step(snap(same), snap(same), "A")
    assert query.activity_answer("A", read, "en") == "A has not moved since the previous update (finish 06/03/2026)."


@pytest.mark.oracle("standard")
def test_a_stored_finish_the_engine_does_not_reproduce_adds_the_reliability_note():
    """Boundary: the later update stores B's finish 5 wd after the recalculation: gap +5.0 wd."""
    stored_late = _week("2026-03-13 17:00", "2026-03-27 17:00")
    sentence = query.activity_answer("B", _read("B", later_tasks=stored_late), "en")
    assert sentence.endswith(
        "Read as an indication: the recalculation does not reproduce the finish P6 stored "
        "(gap +0.0 wd in the earlier update, +5.0 wd in the later one)."
    )


@pytest.mark.oracle("standard")
def test_the_states_without_a_reading_say_what_is_missing():
    absent = _read("Z")
    assert absent.missing_from == f"{EARLIER_UPDATE} and the later update"
    assert (
        query.activity_answer("Z", absent, "en")
        == "Z is missing from the earlier update and the later update: nothing to compare."
    )
    assert (
        query.activity_answer("B", None, "en")
        == "B: a second update is needed to read why it moved; only one is loaded."
    )
    assert query.activity_answer("", None, "fr").startswith("Nommez un code d'activité")
