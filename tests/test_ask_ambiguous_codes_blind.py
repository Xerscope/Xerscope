"""Ask asks back when a word names several activity-code values or types of the same name.

Rule (maintainer decision, 2026-11-08). P6 keeps a code type's name unique only within its
scope, and a value's ``short_name`` unique only within its type (see
``test_code_types_blind``): "P1" can be a value of "Phase (global)" and of "Phase (project)".
A question word that matches several such values carries no information on which one the user
meant, so picking one would filter on a guess:

1. an ambiguous value word ("P1") applies no code filter and returns a clarification listing
   every candidate with where its label comes from: value, type, scope ("P1 — Phase (global)",
   "P1 — Phase (project)");
2. the choice is passed back by value id; the filter then keeps that value only (A or B);
3. a type name shared by two types ("Phase") asks the same way, between the type labels;
4. a word naming one value ("P2") is filtered at once, nothing is asked.

The planning is the one of ``test_code_types_blind``: type 701 "Phase" global, type 702
"Phase" project; value 7001 "P1" of 701 on A, 7002 "P1" of 702 on B, 7003 "P2" of 701 on
nobody; C has no code.

Public surface used: ``query.vocabulary``, ``query.parse`` (keyword grammar, no backend),
``query.apply``. ``query.Filter`` has no field for a clarification and ``query.parse`` no
argument for a choice, so the tests that need them are strict xfails naming the API proposed:

- ``Filter.clarify: tuple[Choice, ...]``, empty when nothing is ambiguous;
- ``query.Choice(word, value, label)``: ``word`` as typed, ``value`` the id passed back
  (``actv_code_id`` for a value, the type label for a type), ``label`` the text shown;
- ``query.parse(text, vocab, chosen={word: value})``: the user's answer to ``clarify``.

The tests that need no new API (rule 1 "no filter", rule 4) run as plain tests.
"""

from __future__ import annotations

import pytest
from test_code_types_blind import GLOBAL_P1, GLOBAL_P2, PROJECT_P1, _code_snapshot, _label
from xerkit import snap, todo

from xerscope.analysis import query

CLARIFY_API = "API à créer : Filter.clarify (tuple de query.Choice(word, value, label)), vide quand rien n'est ambigu"
CHOICE_API = "API à créer : query.parse(text, vocab, chosen={mot: identifiant de valeur})"


def _ask(text: str, s, **kwargs) -> tuple[query.Filter, set[str]]:
    vocab = query.vocabulary(s)
    f = query.parse(text, vocab, **kwargs)
    funnel = query.apply(f, s.activities.assign(category=""), s)
    return f, set(funnel.rows["task_code"])


def _choices(f: query.Filter) -> dict[str, str]:
    """{value passed back: label shown} of the clarification."""
    return {c.value: c.label for c in f.clarify}


# (1) an ambiguous value word filters nothing and asks


def test_ambiguous_value_applies_no_code_filter():
    s = _code_snapshot()
    f, kept = _ask("P1", s)
    assert f.code_type is None
    assert f.code_ids == frozenset()
    assert kept == {"A", "B", "C"}


@pytest.mark.xfail(strict=True, raises=AttributeError, reason=CLARIFY_API)
def test_ambiguous_value_lists_each_candidate_with_type_and_scope():
    s = _code_snapshot()
    f, _ = _ask("P1", s)
    assert {c.word for c in f.clarify} == {"P1"}
    assert _choices(f) == {
        GLOBAL_P1: f"P1 — {_label(s, GLOBAL_P1)}",
        PROJECT_P1: f"P1 — {_label(s, PROJECT_P1)}",
    }
    assert "global" in _choices(f)[GLOBAL_P1].lower()
    assert "project" in _choices(f)[PROJECT_P1].lower()


# (2) the choice, passed by value id, keeps that value only


@pytest.mark.xfail(strict=True, raises=TypeError, reason=CHOICE_API)
@pytest.mark.parametrize(("code_id", "expected"), [(GLOBAL_P1, {"A"}), (PROJECT_P1, {"B"})])
def test_chosen_value_filters_on_it_alone(code_id, expected):
    s = _code_snapshot()
    f, kept = _ask("P1", s, chosen={"P1": code_id})
    assert f.code_ids == frozenset({code_id})
    assert f.code_type == _label(s, code_id)
    assert f.clarify == ()
    assert kept == expected


# (3) a type name shared by two types asks between the type labels


@pytest.mark.xfail(strict=True, raises=AttributeError, reason=CLARIFY_API)
def test_ambiguous_type_name_asks_between_type_labels():
    s = _code_snapshot()
    f, kept = _ask("Phase", s)
    assert f.code_type is None and f.code_ids == frozenset()
    assert kept == {"A", "B", "C"}
    assert {c.word for c in f.clarify} == {"Phase"}
    labels = {_label(s, GLOBAL_P1), _label(s, PROJECT_P1)}
    assert {c.value for c in f.clarify} == labels
    assert {c.label for c in f.clarify} == labels


# (4) a single candidate: filtered at once, nothing asked


def test_unambiguous_value_is_filtered_without_asking():
    s = _code_snapshot()
    f, kept = _ask("P2", s)
    assert f.code_type == _label(s, GLOBAL_P2)
    assert f.code_ids == frozenset({GLOBAL_P2})
    assert getattr(f, "clarify", ()) == ()
    assert kept == set()  # P2 is assigned to nobody


def test_single_type_name_asks_nothing():
    """One "Phase" type: its name is not ambiguous, whatever it filters."""
    s = snap([todo("A"), todo("B")], codes=[("A", "Phase", "P1"), ("B", "Phase", "P2")])
    f, _ = _ask("Phase", s)
    assert getattr(f, "clarify", ()) == ()


def test_single_type_value_is_filtered_without_asking():
    s = snap([todo("A"), todo("B")], codes=[("A", "Phase", "P1"), ("B", "Phase", "P2")])
    f, kept = _ask("P1", s)
    assert f.code_type == "Phase"
    assert getattr(f, "clarify", ()) == ()
    assert kept == {"A"}
