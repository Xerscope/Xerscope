"""The view of one update's activities and its structured query (analysis/activity_view.py), and the
delay of one activity in the engine (cpm.delay_impact).

Every schedule is on the C8 calendar (Mon-Fri, 8 h a day), data date Monday 2 March 2026 08:00: a
40 h activity runs Monday to Friday 17:00.
"""

import pandas as pd
import pytest
from xerkit import active, done, hours, labour_assignment, parse_text, todo, xer_text

from xerscope.analysis import activity_view as views
from xerscope.analysis.cpm import delay_impact
from xerscope.xer import build_snapshot

WEEK_LATER = "2026-03-09 08:00"


def snapshot_of(tasks, preds=(), **kw):
    text = xer_text(tasks, preds, **kw)
    names = {"Discipline GC": "Génie civil", "Discipline EL": "Électricité"}
    for generated, name in names.items():  # the value's name as a planner writes it
        text = text.replace(generated, name)
    return build_snapshot(parse_text(text, source="t.xer"))


@pytest.fixture(scope="module")
def site():
    """A1 (GC, done), A2 (GC, under way, CREW), A3 (EL, 40 h to do), A4 (EL milestone), A5 (no code)."""
    tasks = [
        done("A1", task_name="Terrassement"),
        active("A2", task_name="Coffrage voile"),
        todo("A3", task_name="Tirage câbles", **hours(40)),
        todo("A4", task_name="Mise sous tension", task_type="TT_FinMile", **hours(0)),
        todo("A5", task_name="Réunion", **hours(8)),
    ]
    codes = [
        ("A1", "Discipline", "GC"),
        ("A2", "Discipline", "GC"),
        ("A3", "Discipline", "EL"),
        ("A4", "Discipline", "EL"),
    ]
    return snapshot_of(
        tasks,
        [("A3", "A4", "FS", 0)],
        codes=codes,
        assign=[labour_assignment("A2", "R1", 40)],
        resources=({"rsrc_id": "R1", "rsrc_short_name": "CREW", "rsrc_name": "Équipe béton"},),
    )


def ids(view, *conditions, **query):
    return list(views.run(view, views.Query(tuple(conditions), **query)).funnel.rows.index)


# --- the view ---------------------------------------------------------------------------------


@pytest.mark.oracle("standard")
def test_an_activity_code_is_a_column_read_by_its_value_or_its_name(site):
    view = views.activity_view(site)
    assert "code: Discipline" in [column.name for column in view.columns]
    assert ids(view, views.Condition("code: Discipline", "=", "GC")) == ["A1", "A2"]
    assert ids(view, views.Condition("code: Discipline", "=", "génie civil")) == [
        "A1",
        "A2",
    ]  # the name, accents folded
    assert ids(view, views.Condition("code: Discipline", "!=", "EL")) == ["A1", "A2", "A5"]  # no code: not EL


@pytest.mark.oracle("standard")
def test_conditions_are_funnel_steps_and_hold_together(site):
    """A3 is EL and not started; A4 is EL but a milestone: one step each, what each removed counted."""
    view = views.activity_view(site)
    query = views.Query(
        (views.Condition("code: Discipline", "=", "EL"), views.Condition("milestone", "is_false")),
        sort_by="activity_id",
    )
    result = views.run(view, query)
    assert list(result.funnel.rows.index) == ["A3"]
    assert [(step.label, step.left) for step in result.funnel.steps] == [
        ("code: Discipline = EL", 2),
        ("not milestone", 1),
    ]
    assert {step.source for step in result.funnel.steps} == {"ask"}


@pytest.mark.oracle("standard")
def test_numbers_dates_words_and_resources_are_compared_as_their_kind(site):
    view = views.activity_view(site)
    assert ids(view, views.Condition("remaining_d", ">=", "5")) == ["A2", "A3"]  # 40 h = 5 working days
    assert ids(view, views.Condition("finish", "<", "2026-03-02")) == ["A1"]  # finished 13 February
    assert ids(view, views.Condition("activity_name", "contains", "cable")) == ["A3"]  # "câbles", accents folded
    assert ids(view, views.Condition("resources", "contains", "béton")) == ["A2"]
    assert ids(view, views.Condition("status", "=", "not started"), sort_by="activity_id") == ["A3", "A4", "A5"]


def test_a_status_no_activity_holds_keeps_none_and_is_not_refused(site):
    """Seen with a real model: "how many are complete" on an update where none is: 0, not a refusal.
    The statuses are the model's own words (xer.model.STATUS)."""
    view = views.activity_view(snapshot_of([todo("A", **hours(8))]))
    assert views.run(view, views.Query((views.Condition("status", "=", "Complete"),))).count == 0
    assert views.activity_view(site).column("status").values == ("Not started", "In progress", "Complete")


def test_groups_count_the_activities_per_value(site):
    result = views.run(views.activity_view(site), views.Query(group_by="code: Discipline"))
    assert result.groups == {"GC": 2, "EL": 2, "(none)": 1}


@pytest.mark.parametrize(
    ("condition", "said"),
    [
        (views.Condition("code: Discipline", "=", "CVC"), "holds no value 'CVC'"),  # never matched loosely
        (views.Condition("nowhere", "=", "x"), "no column"),
        (views.Condition("total_float_d", "contains", "5"), "does not apply"),
        (views.Condition("finish", "<", "mars"), "not a date"),
        (views.Condition("remaining_d", ">", "five"), "not a number"),
        (views.Condition("status", "=", ""), "no value"),
    ],
)
def test_a_query_naming_what_the_view_does_not_have_is_refused(site, condition, said):
    with pytest.raises(views.QueryError, match=said):
        views.run(views.activity_view(site), views.Query((condition,)))


@pytest.mark.oracle("standard")
def test_the_finish_moved_since_the_update_before_in_working_days(site):
    """A3 not started a week later: the finish P6 stored went from Friday 6 to Friday 13, 5 working
    days later, which reads negative."""
    later = snapshot_of([todo("A3", early_end_date="2026-03-13 17:00", **hours(40))], data_date=WEEK_LATER)
    earlier = snapshot_of([todo("A3", early_end_date="2026-03-06 17:00", **hours(40))])
    view = views.activity_view(later, earlier)
    assert view.frame.loc["A3", "finish_moved_wd"] == pytest.approx(-5.0)
    assert "finish_moved_wd" not in views.activity_view(later).frame  # no update before: no column


# --- the delay in the engine ------------------------------------------------------------------


@pytest.mark.oracle("standard")
def test_a_delay_on_the_path_moves_the_finish_by_the_delay():
    """A (40 h) then B (40 h): B finishes Fri 13. Two more working days on A: Tue 17, +2 wd."""
    plan = snapshot_of([todo("A", **hours(40)), todo("B", **hours(40))], [("A", "B", "FS", 0)])
    impact = delay_impact(plan, "A", 2)
    assert impact.finish_before == pd.Timestamp("2026-03-13 17:00") and impact.finish_after == pd.Timestamp(
        "2026-03-17 17:00"
    )
    assert impact.finish_move_wd == 2.0 and impact.reached and impact.float_before_d == impact.float_after_d == 0.0


@pytest.mark.oracle("standard")
def test_a_delay_off_the_path_eats_the_float_and_holds_the_finish():
    """A (1 week) beside C (3 weeks), unlinked: A has 10 working days of float. Three more days on A:
    the finish holds (Fri 20), A's float goes to 7 and nothing reached the end."""
    plan = snapshot_of([todo("A", **hours(40)), todo("C", **hours(120))])
    impact = delay_impact(plan, "A", 3)
    assert impact.finish_move_wd == 0.0 and not impact.reached
    assert (impact.float_before_d, impact.float_after_d) == (10.0, 7.0)


@pytest.mark.parametrize(("code", "said"), [("Z", "not an activity"), ("D", "finished")])
def test_a_delay_on_what_cannot_move_is_refused(code, said):
    plan = snapshot_of([todo("A", **hours(40)), done("D")])
    with pytest.raises(ValueError, match=said):
        delay_impact(plan, code, 1)
