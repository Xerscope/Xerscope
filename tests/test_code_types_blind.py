"""Activity code types are identified by ``actv_code_type_id``, not by their name.

P6 model (XER Import/Export Data Map): ACTVTYPE holds one row per code type, keyed by
``actv_code_type_id``, with its name ``actv_code_type`` and its scope
``actv_code_type_scope`` (AS_Global, AS_EPS, AS_Project). ACTVCODE values point to their type by
``actv_code_type_id``; TASKACTV assignments carry ``actv_code_type_id`` and ``actv_code_id``.
Nothing in P6 makes a type name unique across scopes: a global "Phase" and a project "Phase" are
two types, each with its own values. A value's ``short_name`` is unique only within its type, so
"P1" under each "Phase" is two values.

The public surface that names a code type is the ``code_type`` string: column of
``Snapshot.code_values`` and ``Snapshot.task_codes``, argument of ``Snapshot.code_paths`` and
``Snapshot.tasks_with_codes`` (Gantt filter), ``query.Filter.code_type`` and the
``query.vocabulary`` entries (Ask), the "Activity codes" line of the task card. These tests take
the label a type receives from ``code_values`` (found through a value's ``code_id``, which is
unique in P6) and check that every consumer keeps the two types apart:

1. two same-name types get two different labels, each telling its scope ("Phase (global)",
   "Phase (project)"); the exact wording is not imposed, only that the scope word appears;
2. filtering on one type returns only the activities assigned a value of that type;
3. a name used by a single type keeps its plain label ("Phase");
4. the same ``short_name`` under two types stays two values.

xerkit's ``codes=`` keys types by name, so it cannot build two types named alike; the tables are
written here with its generic ``_table`` and appended before the ``%E`` line.
"""

from __future__ import annotations

import pandas as pd
import pytest
from xerkit import _table, snap, todo, xer_text

from xerscope.analysis import query
from xerscope.app.task_panel import card_sections
from xerscope.xer import Snapshot, build_snapshot, parse_text

GLOBAL_P1, PROJECT_P1, GLOBAL_P2 = "7001", "7002", "7003"


def _code_snapshot(scopes: tuple[str, str] = ("AS_Global", "AS_Project")) -> Snapshot:
    """A, B, C: A gets "P1" of the first "Phase" type, B "P1" of the second, C nothing.
    The first type also has a value "P2" assigned to nobody."""
    first, second = scopes
    types = [
        {
            "actv_code_type_id": "701",
            "seq_num": "1",
            "actv_code_type": "Phase",
            "proj_id": "1" if first == "AS_Project" else "",
            "actv_code_type_scope": first,
        },
        {
            "actv_code_type_id": "702",
            "seq_num": "2",
            "actv_code_type": "Phase",
            "proj_id": "1" if second == "AS_Project" else "",
            "actv_code_type_scope": second,
        },
    ]
    values = [
        {
            "actv_code_id": GLOBAL_P1,
            "parent_actv_code_id": "",
            "actv_code_type_id": "701",
            "actv_code_name": "First P1",
            "short_name": "P1",
            "seq_num": "1",
        },
        {
            "actv_code_id": PROJECT_P1,
            "parent_actv_code_id": "",
            "actv_code_type_id": "702",
            "actv_code_name": "Second P1",
            "short_name": "P1",
            "seq_num": "1",
        },
        {
            "actv_code_id": GLOBAL_P2,
            "parent_actv_code_id": "",
            "actv_code_type_id": "701",
            "actv_code_name": "First P2",
            "short_name": "P2",
            "seq_num": "2",
        },
    ]
    links = [
        {"task_id": "1", "actv_code_type_id": "701", "actv_code_id": GLOBAL_P1, "proj_id": "1"},
        {"task_id": "2", "actv_code_type_id": "702", "actv_code_id": PROJECT_P1, "proj_id": "1"},
    ]
    tables = _table("ACTVTYPE", types) + _table("ACTVCODE", values) + _table("TASKACTV", links)
    text = xer_text([todo("A"), todo("B"), todo("C")])
    assert text.endswith("%E\n")
    text = text[: -len("%E\n")] + "\n".join(tables) + "\n%E\n"
    return build_snapshot(parse_text(text, source="test.xer"))


def _label(s: Snapshot, code_id: str) -> str:
    """The code type label the snapshot gives to the type of value ``code_id``."""
    rows = s.code_values[s.code_values["code_id"] == code_id]
    assert len(rows) == 1, f"value {code_id} listed {len(rows)} times in code_values"
    return rows["code_type"].iloc[0]


def _codes(rows: pd.DataFrame) -> set[str]:
    return set(rows["task_code"])


# (1) two labels, each telling its scope


def test_same_name_types_get_distinct_labels():
    s = _code_snapshot()
    first, second = _label(s, GLOBAL_P1), _label(s, PROJECT_P1)
    assert first != second
    assert set(s.code_values["code_type"]) == {first, second}
    assert first.startswith("Phase") and second.startswith("Phase")
    assert "global" in first.lower() and "project" not in first.lower()
    assert "project" in second.lower() and "global" not in second.lower()
    # Values of one type share its label.
    assert _label(s, GLOBAL_P2) == first


@pytest.mark.parametrize("scopes", [("AS_EPS", "AS_Project"), ("AS_Global", "AS_EPS")])
def test_same_name_types_distinct_for_every_scope_pair(scopes):
    s = _code_snapshot(scopes)
    assert _label(s, GLOBAL_P1) != _label(s, PROJECT_P1)


def test_task_codes_use_the_type_label_of_the_value():
    s = _code_snapshot()
    tc = s.task_codes.set_index("task_code")
    assert tc.loc["A", "code_type"] == _label(s, GLOBAL_P1)
    assert tc.loc["B", "code_type"] == _label(s, PROJECT_P1)


# (2) + (4) filters keep the types apart; same short_name is not merged


def test_code_paths_lists_only_the_values_of_one_type():
    s = _code_snapshot()
    assert s.code_paths(_label(s, GLOBAL_P1)) == {GLOBAL_P1: "P1", GLOBAL_P2: "P2"}
    assert s.code_paths(_label(s, PROJECT_P1)) == {PROJECT_P1: "P1"}


def test_gantt_filter_on_global_phase_p1_returns_a_only():
    s = _code_snapshot()
    label = _label(s, GLOBAL_P1)
    p1 = {k for k, v in s.code_paths(label).items() if v == "P1"}
    assert s.tasks_with_codes(label, p1) == {"A"}


def test_gantt_filter_on_project_phase_p1_returns_b_only():
    s = _code_snapshot()
    label = _label(s, PROJECT_P1)
    p1 = {k for k, v in s.code_paths(label).items() if v == "P1"}
    assert s.tasks_with_codes(label, p1) == {"B"}


def test_gantt_filter_does_not_cross_types_by_value_id():
    """A value id of the other type, passed with this type's label, matches nothing."""
    s = _code_snapshot()
    assert s.tasks_with_codes(_label(s, GLOBAL_P1), {PROJECT_P1}) == set()
    assert s.tasks_with_codes(_label(s, PROJECT_P1), {GLOBAL_P1}) == set()


@pytest.mark.parametrize(("code_id", "kept"), [(GLOBAL_P1, {"A"}), (PROJECT_P1, {"B"})])
def test_ask_filter_on_one_phase_type(code_id, kept):
    s = _code_snapshot()
    f = query.Filter(code_type=_label(s, code_id), code_ids=frozenset({code_id}))
    funnel = query.apply(f, s.activities.assign(category=""), s)
    assert _codes(funnel.rows) == kept


def test_ask_vocabulary_names_each_value_with_its_own_type():
    s = _code_snapshot()
    codes = query.vocabulary(s).codes
    assert codes[GLOBAL_P1][0] == _label(s, GLOBAL_P1)
    assert codes[PROJECT_P1][0] == _label(s, PROJECT_P1)
    assert codes[GLOBAL_P1][0] != codes[PROJECT_P1][0]


def test_task_card_shows_the_type_label():
    s = _code_snapshot()
    rows = s.activities.set_index("task_code", drop=False)
    for code, code_id in (("A", GLOBAL_P1), ("B", PROJECT_P1)):
        identity = dict(card_sections(s, rows.loc[code])[0][1])
        assert identity["Activity codes"] == f"{_label(s, code_id)}: P1"


# (3) a name used by one type keeps its plain label


def test_single_phase_type_keeps_plain_label():
    s = snap([todo("A"), todo("B")], codes=[("A", "Phase", "P1"), ("B", "Phase", "P2")])
    assert set(s.code_values["code_type"]) == {"Phase"}
    assert set(s.task_codes["code_type"]) == {"Phase"}
    p1 = {k for k, v in s.code_paths("Phase").items() if v == "P1"}
    assert s.tasks_with_codes("Phase", p1) == {"A"}
