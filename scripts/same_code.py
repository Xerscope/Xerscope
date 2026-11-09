"""Compare the code of src/xerscope between two versions, wherever each definition lives.

A pull request that only moves code (a function to another module, a module split in two)
leaves every definition as it was. This script reads both versions as text, never runs them,
and reads no schedule: it compares the syntax tree of each top-level definition, so comments,
blank lines and formatting do not count, and neither does the file a definition is in.

    uv run python scripts/same_code.py origin/main                  # against the working tree
    uv run python scripts/same_code.py origin/main HEAD
    uv run python scripts/same_code.py origin/main --ignore-docstrings

Not compared: import statements at module level (a move rewrites them) and module docstrings.
Inside a function, an import counts by the names it brings in, not by the module they come
from. ``--ignore-docstrings`` also leaves out the docstrings of functions and classes, for a
pull request that rewrites only those. Exit status 1 when a definition differs.

What it does not see: the order modules are imported in, and what a name now resolves to.
The test suite and the comparison of outputs cover those.
"""

import argparse
import ast
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = "src/xerscope"


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


class _Normalise(ast.NodeTransformer):
    """Rewrite what a move legitimately changes, so that two moved copies dump the same."""

    def __init__(self, ignore_docstrings: bool):
        self.ignore_docstrings = ignore_docstrings

    def _body(self, node):
        self.generic_visit(node)
        if self.ignore_docstrings and node.body and _is_docstring(node.body[0]):
            node.body = node.body[1:] or [ast.Pass()]
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _body

    def visit_Import(self, node: ast.Import):
        return ast.Expr(ast.Constant(sorted(alias.asname or alias.name for alias in node.names)))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        return ast.Expr(ast.Constant(sorted(alias.asname or alias.name for alias in node.names)))


def definitions(sources: dict[str, str], ignore_docstrings: bool = False) -> Counter:
    """Count the top-level definitions of ``sources`` (path -> text) as (label, syntax tree) pairs.

    The label is the kind and the name ("def schedule", "class Snapshot", "FLOAT_TYPE ="), or
    "statement" for anything else. Two files holding the same definition count it twice.
    """
    found: Counter = Counter()
    for text in sources.values():
        body = ast.parse(text).body
        if body and _is_docstring(body[0]):
            body = body[1:]
        for node in body:
            if isinstance(node, ast.Import | ast.ImportFrom):
                continue
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                label = f"def {node.name}"
            elif isinstance(node, ast.ClassDef):
                label = f"class {node.name}"
            elif isinstance(node, ast.Assign | ast.AnnAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                label = ", ".join(ast.unparse(target) for target in targets) + " ="
            else:
                label = "statement"
            found[(label, ast.dump(_Normalise(ignore_docstrings).visit(node)))] += 1
    return found


def compare(base: dict[str, str], head: dict[str, str], ignore_docstrings: bool = False) -> list[str]:
    """Return one line per definition that differs between ``base`` and ``head``, sorted; [] when none does."""
    before, after = definitions(base, ignore_docstrings), definitions(head, ignore_docstrings)
    gone, new = (
        Counter(label for label, _ in (before - after).elements()),
        Counter(label for label, _ in (after - before).elements()),
    )
    lines = []
    for label in sorted(gone.keys() | new.keys()):
        if gone[label] and new[label]:
            lines.append(f"changed: {label}")
        elif gone[label]:
            lines.append(f"removed: {label}")
        else:
            lines.append(f"added: {label}")
    return lines


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def read_version(ref: str | None) -> dict[str, str]:
    """Return the Python files of src/xerscope at ``ref`` (path -> text); the working tree when None."""
    if ref is None:
        return {
            path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted((ROOT / SRC).rglob("*.py"))
        }
    paths = [path for path in _git("ls-tree", "-r", "--name-only", ref, SRC).splitlines() if path.endswith(".py")]
    return {path: _git("show", f"{ref}:{path}") for path in paths}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("base", help="git revision to compare from, e.g. origin/main")
    parser.add_argument("head", nargs="?", help="git revision to compare to (default: the working tree)")
    parser.add_argument("--ignore-docstrings", action="store_true", help="leave function and class docstrings out")
    args = parser.parse_args(argv)
    lines = compare(read_version(args.base), read_version(args.head), args.ignore_docstrings)
    for line in lines:
        print(line)
    print(f"{len(lines)} definition(s) differ" if lines else "same code")
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main())
