"""scripts/duplication.py: structural clones read from the syntax tree."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from duplication import clones, functions, near_clones  # noqa: E402

ORIGINAL = '''
def late_tasks(frame, limit):
    """Tasks finishing after the limit."""
    late = []
    for row in frame.itertuples():
        if row.finish > limit and row.status != "complete":
            late.append((row.task_code, row.finish - limit))
    total = sum(days for _, days in late)
    return late, total / max(len(late), 1)
'''

# type 1: same code, another name and a comment
EXACT = """
def overdue(frame, limit):
    # a comment is not in the tree
    late = []
    for row in frame.itertuples():
        if row.finish > limit and row.status != "complete":
            late.append((row.task_code, row.finish - limit))
    total = sum(days for _, days in late)
    return late, total / max(len(late), 1)
"""

# type 2: every variable renamed, one literal changed
RENAMED = """
def overdue(table, cutoff):
    out = []
    for r in table.itertuples():
        if r.finish > cutoff and r.status != "done":
            out.append((r.task_code, r.finish - cutoff))
    s = sum(d for _, d in out)
    return out, s / max(len(out), 1)
"""

# another computation of the same size
DIFFERENT = """
def float_bands(frame, limit):
    bands = {}
    for row in frame.itertuples():
        key = "critical" if row.total_float <= 0 else "near" if row.total_float < limit else "free"
        bands.setdefault(key, []).append(row.task_code)
    return {key: len(codes) for key, codes in bands.items()}
"""

# type 3: the original plus one statement
EXTENDED = '''
def late_tasks(frame, limit):
    """Tasks finishing after the limit."""
    late = []
    for row in frame.itertuples():
        if row.finish > limit and row.status != "complete":
            late.append((row.task_code, row.finish - limit))
    late.sort()
    total = sum(days for _, days in late)
    return late, total / max(len(late), 1)
'''

# same shape as ORIGINAL with another attribute: what is read differs, so not a type 2 clone
OTHER_COLUMN = ORIGINAL.replace("row.finish > limit", "row.start > limit")


def scan(*sources):
    return [f for i, source in enumerate(sources) for f in functions(source, f"m{i}.py")]


def names(groups):
    return [sorted(f"{f.path}:{f.name}" for f in group) for group in groups]


def test_type_1_exact_copy_is_a_clone():
    assert names(clones(scan(ORIGINAL, EXACT))) == [["m0.py:late_tasks", "m1.py:overdue"]]


def test_type_2_renamed_variables_and_changed_literal_is_a_clone():
    assert names(clones(scan(ORIGINAL, RENAMED))) == [["m0.py:late_tasks", "m1.py:overdue"]]


def test_different_functions_are_not_clones():
    funcs = scan(ORIGINAL, DIFFERENT)
    assert clones(funcs) == []
    assert near_clones(funcs) == []


def test_another_attribute_is_not_a_type_2_clone():
    assert clones(scan(ORIGINAL, OTHER_COLUMN)) == []


def test_type_3_added_statement_is_a_near_clone_above_the_threshold_only():
    funcs = scan(ORIGINAL, EXTENDED)
    assert clones(funcs) == []
    [(ratio, a, b)] = near_clones(funcs, threshold=0.9)
    assert {a.path, b.path} == {"m0.py", "m1.py"}
    assert 0.9 <= ratio < 1
    assert near_clones(funcs, threshold=ratio + 0.001) == []


def test_small_functions_are_left_out():
    small = "def a(x):\n    return x + 1\n"
    assert clones(scan(small, small.replace("def a", "def b"))) == []
    assert len(clones(scan(small, small.replace("def a", "def b")), min_nodes=1)) == 1


def test_methods_and_nested_functions_are_named_by_their_scope():
    source = "class Axis:\n    def snap(self):\n        def inner():\n            pass\n"
    assert [f.name for f in functions(source)] == ["Axis.snap", "Axis.snap.inner"]
