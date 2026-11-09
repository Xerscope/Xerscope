"""Docstring standard of src/xerscope (CONTRIBUTING.md, Docstrings): what ruff does not check.

ruff checks the PEP 257 form (job lint). Here: a function or class docstring holds at most
MAX_LINES lines, and the debt recorded in pyproject.toml only shrinks.
"""

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "xerscope"
MAX_LINES = 12
# Docstrings over MAX_LINES on main at f98589e. An entry goes when its docstring is shortened
# (a worked example moves to docs/, next to the test that proves its values); none is added.
LONG = {
    "analysis/cpm.py:_Run.backward",
    "analysis/cpm.py:_Run.expected_finish",
    "analysis/cpm.py:_Run.floats",
    "analysis/cpm.py:_Run.forward",
    "analysis/cpm.py:_Run.level_of_effort",
    "analysis/cpm.py:_Run.pred_bounds",
    "analysis/cpm.py:_Run.rsrc_early",
    "analysis/cpm.py:_late",
    "analysis/cpm.py:schedule",
    "analysis/dcma/fourteen_point.py:dcma_11_missed_tasks",
    "analysis/dcma/fourteen_point.py:dcma_13_cpli",
    "analysis/dcma/fourteen_point.py:dcma_14_bei",
    "analysis/decm/schedule_metrics.py:decm_06a212a_out_of_sequence",
    "analysis/decm/schedule_metrics.py:decm_06a506b_forecast_dates_before_status_date",
    "analysis/decm/schedule_metrics.py:decm_06a506c_riding_status_date",
    "analysis/evm.py:pv_labor_check",
    "analysis/evm.py:pv_p6_comparison",
    "analysis/integrity.py:int_08_unsatisfied_relationships",
    "analysis/p6/check_schedule.py:p6_16_dangling_start",
    "analysis/p6/check_schedule.py:p6_17_dangling_finish",
    "viz/charts.py:build_mta",
    "xer/calendar.py:TimeAxis",
}
MAX_DEBT = 267  # (file, rule) pairs of [tool.ruff.lint.per-file-ignores] under src/


def _docstrings(tree: ast.AST, prefix: str = ""):
    """Yield (qualified name, docstring line count) of every function and class of ``tree``."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            name = f"{prefix}{node.name}"
            text = ast.get_docstring(node)
            if text:
                yield name, len(text.splitlines())
            yield from _docstrings(node, f"{name}.")
        else:
            yield from _docstrings(node, prefix)


def over_limit() -> set[str]:
    found = set()
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found |= {
            f"{path.relative_to(SRC).as_posix()}:{name}" for name, lines in _docstrings(tree) if lines > MAX_LINES
        }
    return found


def test_no_new_docstring_over_the_limit():
    new = over_limit() - LONG
    assert not new, f"docstrings over {MAX_LINES} lines: {sorted(new)}"


def test_listed_long_docstrings_are_still_long():
    """A shortened docstring leaves LONG, so that it cannot grow back unseen."""
    gone = LONG - over_limit()
    assert not gone, f"no longer over {MAX_LINES} lines, remove from LONG: {sorted(gone)}"


def test_docstring_debt_only_shrinks():
    ignores = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["lint"][
        "per-file-ignores"
    ]
    debt = {(path, rule) for path, rules in ignores.items() if path.startswith("src/") for rule in rules}
    assert all(rule.startswith("D") for _, rule in debt), "src/ entries hold docstring rules only"
    assert all((ROOT / path).is_file() for path, _ in debt), "an entry names a file that is gone"
    assert len(debt) <= MAX_DEBT, f"{len(debt)} (file, rule) pairs, {MAX_DEBT} allowed: the debt only shrinks"
