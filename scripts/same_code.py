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
after, with their line numbers and the method they are in. A definition that only changed its
name is reported as renamed.

What it does not see: the order modules are imported in, and what a name now resolves to.
The test suite and the comparison of outputs cover those.
"""

import argparse
import ast
import difflib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = "src/xerscope"


def _lines(text: str) -> list[str]:
    """Split source text where Python counts a new line: on \\n, \\r\\n or \\r only.

    ``str.splitlines`` also splits on a form feed, on U+2028 and on a few others, which a string
    literal or a comment may hold: the lines would no longer match those of the syntax tree.
    """
    return re.split(r"\r\n|\r|\n", text)


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

    # ast.NodeTransformer looks these three names up
    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _body  # noqa: N815

    def visit_Import(self, node: ast.Import):
        return ast.Expr(ast.Constant(sorted(alias.asname or alias.name for alias in node.names)))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        return ast.Expr(ast.Constant(sorted(alias.asname or alias.name for alias in node.names)))


KINDS = ("changed", "renamed", "removed", "added")


def _label(node: ast.stmt) -> str:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return f"def {node.name}"
    if isinstance(node, ast.ClassDef):
        return f"class {node.name}"
    if isinstance(node, ast.Assign | ast.AnnAssign):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return ", ".join(ast.unparse(target) for target in targets) + " ="
    return "statement"


def definitions(sources: dict[str, str], ignore_docstrings: bool = False) -> dict[tuple[str, str], list[dict]]:
    """Return the top-level definitions of ``sources`` (path -> text), each with where it lives.

    Key: the label and the syntax tree. The label is the kind and the name ("def schedule",
    "class Snapshot", "FLOAT_TYPE ="), or "statement" for anything else. Value: one entry per
    file holding that definition (the same one in two files counts twice): ``path``, ``text``
    (decorators included), ``line`` (its first line in the file) and ``unnamed``, the syntax
    tree of a function or class with its name blanked, by which a rename is recognised.
    """
    found: dict[tuple[str, str], list[dict]] = {}
    for path, text in sources.items():
        lines = _lines(text)
        body = ast.parse(text).body
        if body and _is_docstring(body[0]):
            body = body[1:]
        for node in body:
            if isinstance(node, ast.Import | ast.ImportFrom):
                continue
            label = _label(node)
            first = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
            entry = {"path": path, "text": "\n".join(lines[first - 1 : node.end_lineno]), "line": first, "unnamed": ""}
            tree = ast.dump(_Normalise(ignore_docstrings).visit(node))
            if hasattr(node, "name"):
                name, node.name = node.name, "_"
                entry["unnamed"] = ast.dump(node)
                node.name = name
            found.setdefault((label, tree), []).append(entry)
    return found


def _renames(before: dict[str, list], after: dict[str, list]) -> dict[str, str]:
    """Return {removed label: added label} where a definition only changed its name.

    A removed and an added definition of the same kind, alone to share one unnamed syntax tree.
    """
    removed = {label: entries for label, entries in before.items() if label not in after and len(entries) == 1}
    added = {label: entries for label, entries in after.items() if label not in before and len(entries) == 1}
    by_tree: dict[str, list[str]] = {}
    for label, (entry,) in added.items():
        if entry["unnamed"]:
            by_tree.setdefault(label.split()[0] + entry["unnamed"], []).append(label)
    pairs = {}
    for label, (entry,) in removed.items():
        same = by_tree.get(label.split()[0] + entry["unnamed"], []) if entry["unnamed"] else []
        if len(same) == 1:
            pairs.setdefault(same[0], []).append(label)
    return {olds[0]: new for new, olds in pairs.items() if len(olds) == 1}


def differences(base: dict[str, str], head: dict[str, str], ignore_docstrings: bool = False) -> list[dict]:
    """Return the definitions that differ between ``base`` and ``head``, sorted by label.

    One entry each: ``kind`` (one of KINDS), ``label`` ("def a", or "def a -> def b" for a
    rename), and the ``definitions`` entries found only in ``base`` (``before``) and only in
    ``head`` (``after``).
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
    renamed = _renames(before, after)
    out = []
    for label in sorted(before.keys() | after.keys()):
        if label in renamed.values():
            continue  # listed with its former name
        if label in renamed:
            item = {"kind": "renamed", "label": f"{label} -> {renamed[label]}", "after": after[renamed[label]]}
        else:
            kind = "changed" if label in before and label in after else "removed" if label in before else "added"
            item = {"kind": kind, "label": label, "after": after.get(label, [])}
        out.append(item | {"before": before.get(label, [])})
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


def _owners(text: str) -> list[str]:
    """Return, for each line of a definition's ``text``, the method or nested function it is in.

    "" for a line of the definition itself: only a line deeper than that needs naming.
    """
    owners = [""] * len(_lines(text))

    def walk(node: ast.AST, prefix: str, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            name = prefix
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                name = f"{prefix}.{child.name}" if prefix else child.name
                if depth:
                    first = min([child.lineno, *(d.lineno for d in child.decorator_list)])
                    owners[first - 1 : child.end_lineno] = [name] * (child.end_lineno - first + 1)
                walk(child, name, depth + 1)
            else:
                walk(child, name, depth)

    walk(ast.parse(text), "", 0)
    return owners


def _changed_lines(before: dict, after: dict) -> list[str]:
    """Return the lines that differ between two versions of a definition, with their line in each file.

    Each group of lines is headed by the method it is in, when it is in one.
    """
    old, new = _lines(before["text"]), _lines(after["text"])
    old_owner, new_owner = _owners(before["text"]), _owners(after["text"])
    out, last = [], None
    for kind, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if kind == "equal" or _same_imported_names(old[i1:i2], new[j1:j2]):
            continue  # an import inside a function counts by its names, not by the module they come from
        owner = old_owner[i1] if i1 < i2 else new_owner[j1]
        if owner and owner != last:
            out.append(f"  in {owner}")
        last = owner
        out += [f"    before, line {before['line'] + i}:  {old[i].strip()}" for i in range(i1, i2)]
        out += [f"    after,  line {after['line'] + j}:  {new[j].strip()}" for j in range(j1, j2)]
        out.append("")
    return out[:-1]


def report(items: list[dict]) -> str:
    """Return the differences as text a reader can follow without opening either version.

    First what differs in all, then one block per definition: its name, the file it is in (or
    was in, and is in now), and for a changed one each differing line, before and after, with
    its line number in its file and the method it belongs to.
    """
    count = {kind: sum(item["kind"] == kind for item in items) for kind in KINDS}
    lines = [f"{len(items)} definition(s) differ: " + ", ".join(f"{n} {kind}" for kind, n in count.items() if n), ""]
    for item in items:
        before, after = (sorted({entry["path"] for entry in item[side]}) for side in ("before", "after"))
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
