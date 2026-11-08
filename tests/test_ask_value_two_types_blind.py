"""Ask asks back when one value name exists under two code types of different names.

Rule (maintainer decision, 2026-11-08). A value's ``short_name`` is unique only within its code
type (XER Import/Export Data Map, ACTVCODE: values point to their type by
``actv_code_type_id``). Two types of different names can therefore each hold a value "A": "A"
of "Zone" and "A" of "Room" are two values. ``test_ask_ambiguous_codes_blind`` covers the same
question for two types sharing a name; here the type names differ, so the type label alone
tells the candidates apart:

1. the word "A" names two values: Ask applies no code filter (filtering on one would be a
   guess) and ``Filter.clarify`` lists both, labelled value — type label ("A — Zone",
   "A — Room");
2. the choice is passed back by value id (``chosen={"A": code_id}``); the filter then keeps that
   value only: X for Zone's A, Y for Room's A;
3. "Zone A" names the type, so it names one value: filtered at once on X, nothing asked;
4. "B" exists under one type only: filtered at once, nothing asked.

Planning (xerkit ``codes=``, one AS_Project type per name): X has Zone "A", Y has Room "A",
Z has Zone "B", W has no code. Every test runs twice: with the one-letter names of the decision
("A", "B") and with "A1", "B1", so that a grammar dropping one-letter words cannot hide what it
does with a value name shared by two types. Value ids are read from ``Snapshot.code_values`` by
(type label, value), not assumed from the builder's numbering.

Public surface used: ``query.vocabulary``, ``query.parse`` (keyword grammar, no backend, with
``chosen``), ``query.apply``, ``Filter.clarify`` of ``query.Choice(word, value, label)``.
"""

from __future__ import annotations

import pytest
from xerkit import snap, todo

from xerscope.analysis import query

NAMES = pytest.mark.parametrize(("a", "b"), [("A", "B"), ("A1", "B1")])


def _snapshot(a: str, b: str):
    return snap(
        [todo("X"), todo("Y"), todo("Z"), todo("W")],
        codes=[("X", "Zone", a), ("Y", "Room", a), ("Z", "Zone", b)],
    )


def _id(s, code_type: str, value: str) -> str:
    cv = s.code_values
    rows = cv[(cv["code_type"] == code_type) & (cv["value"] == value)]
    assert len(rows) == 1, f"{value} of {code_type} listed {len(rows)} times in code_values"
    return rows["code_id"].iloc[0]


def _ask(text: str, s, **kwargs) -> tuple[query.Filter, set[str]]:
    f = query.parse(text, query.vocabulary(s), **kwargs)
    funnel = query.apply(f, s.activities.assign(category=""), s)
    return f, set(funnel.rows["task_code"])


@NAMES
def test_snapshot_keeps_two_values_named_a(a, b):
    """Precondition: the two "A" are two values, each under its own type label."""
    s = _snapshot(a, b)
    assert _id(s, "Zone", a) != _id(s, "Room", a)


# (1) "A" alone: no filter, a question


@NAMES
def test_value_under_two_types_applies_no_code_filter(a, b):
    s = _snapshot(a, b)
    f, kept = _ask(a, s)
    assert f.code_type is None
    assert f.code_ids == frozenset()
    assert kept == {"X", "Y", "Z", "W"}


@NAMES
def test_value_under_two_types_lists_value_and_type_label(a, b):
    s = _snapshot(a, b)
    f, _ = _ask(a, s)
    assert set(f.clarify) == {
        query.Choice(a, _id(s, "Zone", a), f"{a} — Zone"),
        query.Choice(a, _id(s, "Room", a), f"{a} — Room"),
    }
    assert len(f.clarify) == 2


# (2) the choice keeps that value only


@NAMES
@pytest.mark.parametrize(("code_type", "expected"), [("Zone", {"X"}), ("Room", {"Y"})])
def test_chosen_value_filters_on_it_alone(a, b, code_type, expected):
    s = _snapshot(a, b)
    code_id = _id(s, code_type, a)
    f, kept = _ask(a, s, chosen={a: code_id})
    assert f.code_type == code_type
    assert f.code_ids == frozenset({code_id})
    assert f.clarify == ()
    assert kept == expected


# (3) type name + value: one value, no question


@NAMES
def test_type_and_value_filters_without_asking(a, b):
    s = _snapshot(a, b)
    f, kept = _ask(f"Zone {a}", s)
    assert f.clarify == ()
    assert f.code_type == "Zone"
    assert f.code_ids == frozenset({_id(s, "Zone", a)})
    assert kept == {"X"}


# (4) a value under one type only: no question


@NAMES
def test_value_under_one_type_filters_without_asking(a, b):
    s = _snapshot(a, b)
    f, kept = _ask(b, s)
    assert f.clarify == ()
    assert f.code_type == "Zone"
    assert f.code_ids == frozenset({_id(s, "Zone", b)})
    assert kept == {"Z"}
