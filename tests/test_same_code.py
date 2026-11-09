"""scripts/same_code.py: a move leaves no difference, any change to a definition is one."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from same_code import compare  # noqa: E402

BASE = {
    "pkg/model.py": '''"""The model."""
import math
from .calendar import hours

LIMIT = 15


def total(values, scale=1.0):
    """Return the sum of ``values``, scaled."""
    from .units import to_days  # deferred

    return to_days(sum(values)) * scale


class Snapshot:
    """One file."""

    def label(self):
        return "x"
''',
    "pkg/units.py": "def to_days(hours):\n    return hours / 8\n",
}


def moved(**changes) -> dict[str, str]:
    """BASE with ``total`` moved to a new module one package deeper, then ``changes`` applied to it."""
    text = BASE["pkg/model.py"]
    start, end = text.index("def total"), text.index("class Snapshot")
    function = text[start:end].replace("from .units import to_days", "from ..units import to_days")
    for old, new in changes.items():
        assert old in function, old
        function = function.replace(old, new)
    return {
        "pkg/model.py": text[:start] + text[end:],
        "pkg/sub/values.py": '"""Values."""\nfrom ..calendar import hours\n\n\n' + function,
        "pkg/units.py": BASE["pkg/units.py"],
    }


def test_a_move_with_its_imports_rewritten_is_the_same_code():
    assert compare(BASE, moved()) == []


def test_comments_and_layout_do_not_count():
    head = dict(BASE, **{"pkg/units.py": "def to_days(hours):  # 8 h a day\n\n    return hours / 8\n"})
    assert compare(BASE, head) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("sum(values)", "max(values)"),  # the body
        ("scale=1.0", "scale=2.0"),  # a default
        ("values, scale", "scale, values"),  # the order of the parameters
        ("import to_days", "import to_hours"),  # the name a deferred import brings in
    ],
)
def test_a_change_inside_a_moved_function_is_reported(old, new):
    assert compare(BASE, moved(**{old: new})) == ["changed: def total"]


def test_a_definition_removed_or_added_is_reported():
    head = dict(BASE, **{"pkg/units.py": "def to_weeks(hours):\n    return hours / 40\n"})
    assert compare(BASE, head) == ["removed: def to_days", "added: def to_weeks"]  # by name


def test_a_constant_and_a_method_count():
    text = BASE["pkg/model.py"]
    assert compare(BASE, dict(BASE, **{"pkg/model.py": text.replace("LIMIT = 15", "LIMIT = 16")})) == [
        "changed: LIMIT ="
    ]
    assert compare(BASE, dict(BASE, **{"pkg/model.py": text.replace('return "x"', 'return "y"')})) == [
        "changed: class Snapshot"
    ]


def test_a_decorator_counts():
    head = dict(BASE, **{"pkg/units.py": "@cache\ndef to_days(hours):\n    return hours / 8\n"})
    assert compare(BASE, head) == ["changed: def to_days"]


def test_docstrings_count_unless_left_out():
    head = moved(**{"Return the sum of ``values``, scaled.": "Sum ``values`` and scale the result."})
    assert compare(BASE, head) == ["changed: def total"]
    assert compare(BASE, head, ignore_docstrings=True) == []
    code = moved(**{"sum(values)": "max(values)"})
    assert compare(BASE, code, ignore_docstrings=True) == ["changed: def total"]  # the code still counts


def test_a_docstring_added_to_a_function_without_one_is_left_out_too():
    head = dict(BASE, **{"pkg/units.py": 'def to_days(hours):\n    """Convert."""\n    return hours / 8\n'})
    assert compare(BASE, head) == ["changed: def to_days"]
    assert compare(BASE, head, ignore_docstrings=True) == []


def test_the_same_definition_in_two_files_is_counted_twice():
    twice = dict(BASE, **{"pkg/other.py": BASE["pkg/units.py"]})
    assert compare(twice, BASE) == ["removed: def to_days"]
