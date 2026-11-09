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
pull request that rewrites only those. Exit status 1 when a definition differs: each one is
printed with its file on each side and, when it changed, the lines that differ, before and
after, with their line numbers.

What it does not see: the order modules are imported in, and what a name now resolves to.
The test suite and the comparison of outputs cover those.
"""

import argparse
import ast
import difflib
import subprocess
import sys
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


def definitions(
    sources: dict[str, str], ignore_docstrings: bool = False
) -> dict[tuple[str, str], list[tuple[str, str, int]]]:
    """Return the top-level definitions of ``sources`` (path -> text), each with where it lives.

    Key: the label and the syntax tree. The label is the kind and the name ("def schedule",
    "class Snapshot", "FLOAT_TYPE ="), or "statement" for anything else. Value: one (path,
    source text, first line in the file) per file holding that definition, so the same one in
    two files counts twice.
    """
    found: dict[tuple[str, str], list[tuple[str, str, int]]] = {}
    for path, text in sources.items():
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
            source = ast.get_source_segment(text, node) or ""
            tree = ast.dump(_Normalise(ignore_docstrings).visit(node))
            found.setdefault((label, tree), []).append((path, source, node.lineno))
    return found


def differences(base: dict[str, str], head: dict[str, str], ignore_docstrings: bool = False) -> list[dict]:
    """Return the definitions that differ between ``base`` and ``head``, sorted by label.

    One entry per label: ``kind`` ("changed", "removed" or "added"), ``label``, and the
    (path, source text, first line) of what is only in ``base`` (``before``) or ``head`` (``after``).
    """
    old, new = definitions(base, ignore_docstrings), definitions(head, ignore_docstrings)
    before: dict[str, list] = {}
    after: dict[str, list] = {}
    for key in old.keys() | new.keys():
        surplus = len(old.get(key, [])) - len(new.get(key, []))
        if surplus > 0:
            before.setdefault(key[0], []).extend(old[key][:surplus])
        elif surplus < 0:
            after.setdefault(key[0], []).extend(new[key][:-surplus])
    out = []
    for label in sorted(before.keys() | after.keys()):
        kind = "changed" if label in before and label in after else "removed" if label in before else "added"
        out.append({"kind": kind, "label": label, "before": before.get(label, []), "after": after.get(label, [])})
    return out


def compare(base: dict[str, str], head: dict[str, str], ignore_docstrings: bool = False) -> list[str]:
    """Return one line per definition that differs between ``base`` and ``head``, sorted by label; [] when none does."""
    return [f"{item['kind']}: {item['label']}" for item in differences(base, head, ignore_docstrings)]


def _imported_names(lines: list[str]) -> set[str] | None:
    """Return the names ``lines`` import, or None when one of them is not a one-line import."""
    names: set[str] = set()
    for line in lines:
        try:
            (node,) = ast.parse(line.strip()).body
        except (SyntaxError, ValueError):
            return None
        if not isinstance(node, ast.Import | ast.ImportFrom):
            return None
        names.update(alias.asname or alias.name for alias in node.names)
    return names


def _same_imported_names(old: list[str], new: list[str]) -> bool:
    before, after = _imported_names(old), _imported_names(new)
    return bool(old and new) and before is not None and before == after


def _changed_lines(before: tuple[str, str, int], after: tuple[str, str, int]) -> list[str]:
    """Return the lines that differ between two versions of a definition, with their line in each file."""
    (_, old_text, old_start), (_, new_text, new_start) = before, after
    old, new = old_text.splitlines(), new_text.splitlines()
    out = []
    for kind, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if kind == "equal" or _same_imported_names(old[i1:i2], new[j1:j2]):
            continue  # an import inside a function counts by its names, not by the module they come from
        out += [f"    before, line {old_start + i}:  {old[i].strip()}" for i in range(i1, i2)]
        out += [f"    after,  line {new_start + j}:  {new[j].strip()}" for j in range(j1, j2)]
        out.append("")
    return out[:-1]


def report(items: list[dict]) -> str:
    """Return the differences as text a reader can follow without opening either version.

    First what differs in all, then one block per definition: its name, the file it is in (or
    was in, and is in now), and for a changed one each differing line, before and after, with
    its line number in its file.
    """
    count = {kind: sum(item["kind"] == kind for item in items) for kind in ("changed", "removed", "added")}
    lines = [f"{len(items)} definition(s) differ: " + ", ".join(f"{n} {kind}" for kind, n in count.items() if n), ""]
    for item in items:
        before, after = (sorted({path for path, _, _ in item[side]}) for side in ("before", "after"))
        if item["kind"] == "removed":
            where = f"was in {', '.join(before)}"
        elif item["kind"] == "added":
            where = f"now in {', '.join(after)}"
        elif before == after:
            where = f"in {', '.join(after)}"
        else:
            where = f"was in {', '.join(before)}, now in {', '.join(after)}"
        lines.append(f"{item['kind'].upper()}  {item['label']}  ({where})")
        if item["kind"] == "changed" and len(item["before"]) == len(item["after"]) == 1:
            lines += _changed_lines(item["before"][0], item["after"][0])
        lines.append("")
    return "\n".join(lines).rstrip()


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
    items = differences(read_version(args.base), read_version(args.head), args.ignore_docstrings)
    print(report(items) if items else "same code")
    return 1 if items else 0


if __name__ == "__main__":
    sys.exit(main())
