"""scripts/fitness.py --check: a measure worse than the baseline fails, a better one is listed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from fitness import compare  # noqa: E402


def module(**changes):
    row = {
        "mi": 45.0,
        "mi_rank": "A",
        "cc_max": 12,
        "cc_over_15": 0,
        "cognitive_max": 14,
        "cognitive_over_15": 0,
        "clones": 0,
        "near_clones": 0,
    }
    return row | changes


GLOBAL = {"mypy_errors": 100, "deptry_violations": 9, "import_contracts": 11, "import_contracts_broken": 0}


def result(modules, **changes):
    return {"modules": modules, "global": GLOBAL | changes}


BASELINE = result({"a.py": module(), "big.py": module(mi=0.0, mi_rank="C", cc_max=42, cc_over_15=11)})


def test_same_measures_pass():
    assert compare(BASELINE, BASELINE) == ([], [])


def test_module_leaving_rank_a_fails_while_mi_inside_the_rank_is_free():
    assert compare(result({"a.py": module(mi=21.0), "big.py": BASELINE["modules"]["big.py"]}), BASELINE) == ([], [])
    worse, _ = compare(result({"a.py": module(mi=19.9, mi_rank="B")}), BASELINE)
    assert worse == ["a.py mi_rank: A -> B"]


def test_each_count_or_maximum_that_goes_up_fails():
    current = result(
        {"a.py": module(cc_over_15=1, cc_max=16, cognitive_max=20, cognitive_over_15=1, clones=2)},
        mypy_errors=101,
        deptry_violations=10,
        import_contracts_broken=1,
    )
    worse, better = compare(current, BASELINE)
    assert sorted(worse) == [
        "a.py cc_max: 12 -> 16",
        "a.py cc_over_15: 0 -> 1",
        "a.py clones: 0 -> 2",
        "a.py cognitive_max: 14 -> 20",
        "a.py cognitive_over_15: 0 -> 1",
        "global deptry_violations: 9 -> 10",
        "global import_contracts_broken: 0 -> 1",
        "global mypy_errors: 100 -> 101",
    ]
    assert better == []


def test_near_clones_and_the_contract_count_are_reported_not_checked():
    current = result({"a.py": module(near_clones=5)}, import_contracts=12)
    assert compare(current, BASELINE) == ([], [])


def test_improvements_are_listed_and_pass():
    current = result({"big.py": module(mi=12.0, mi_rank="B", cc_max=30, cc_over_15=4)}, mypy_errors=90)
    worse, better = compare(current, BASELINE)
    assert worse == []
    assert sorted(better) == [
        "big.py cc_max: 42 -> 30",
        "big.py cc_over_15: 11 -> 4",
        "big.py mi_rank: C -> B",
        "global mypy_errors: 100 -> 90",
    ]


def test_new_module_must_be_rank_a_without_complex_function_or_clone():
    assert compare(result({"new.py": module(cc_max=15, cognitive_max=15)}), BASELINE) == ([], [])
    worse, _ = compare(result({"new.py": module(mi_rank="B", cc_over_15=1, cognitive_over_15=2, clones=1)}), BASELINE)
    assert sorted(worse) == [
        "new.py (new) cc_over_15: 1",
        "new.py (new) clones: 1",
        "new.py (new) cognitive_over_15: 2",
        "new.py (new) mi_rank: B",
    ]


def test_removed_module_is_not_a_regression():
    assert compare(result({}), BASELINE) == ([], [])
