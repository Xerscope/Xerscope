"""Structural duplication between Python functions, read from their syntax trees.

Each function is normalised: its name, decorators and docstring dropped, every name
(variables, arguments, called functions, module constants) replaced by `_`, every literal
by `...`. Attribute names, operators and the shape of the tree are kept: `row.finish` and
`row.start` differ, `_links(context)` and `_links_into_open_tasks(context)` do not.

- type 1 (exact) and type 2 (renamed variables, changed literals): normalised trees equal;
- type 3 (statements added, removed or changed): the normalised node sequences match at
  `threshold` or above (difflib ratio), reported as near clones.

Functions under `min_nodes` normalised nodes are left out: short wrappers and accessors
look alike without being copies.

    uv run python scripts/duplication.py src [--threshold 0.9] [--min-nodes 30]
"""

import argparse
import ast
import copy
import difflib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

THRESHOLD = 0.9
MIN_NODES = 30


@dataclass(frozen=True)
class Function:
    path: str
    name: str  # Class.method for a method, outer.inner for a nested function
    line: int
    shape: str  # ast.dump of the normalised tree: equal shapes are type 1/2 clones
    tokens: tuple[str, ...]  # normalised nodes in source order, for the type 3 ratio


class _Normalise(ast.NodeTransformer):
    def visit_Name(self, node):
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_arg(self, node):
        self.generic_visit(node)
        node.arg = "_"
        return node

    def visit_Constant(self, node):
        return ast.copy_location(ast.Constant(value=...), node)


def _tokens(node):
    yield type(node).__name__ + (f".{node.attr}" if isinstance(node, ast.Attribute) else "")
    for child in ast.iter_child_nodes(node):
        yield from _tokens(child)


def _normalised(node):
    tree = copy.deepcopy(node)  # the caller's tree stays intact
    body = tree.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:] or [ast.Pass()]  # the docstring documents, it does not compute
    tree.name, tree.body, tree.decorator_list = "_", body, []
    return _Normalise().visit(tree)


def functions(source, path=""):
    """Every function and method of a module, nested ones included, with its normalised shape."""
    found = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                tree = _normalised(child)
                tokens = tuple(_tokens(tree))
                found.append(Function(path, prefix + child.name, child.lineno, ast.dump(tree), tokens))
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(ast.parse(source), "")
    return found


def clones(funcs, min_nodes=MIN_NODES):
    """Groups of two or more functions whose normalised trees are equal (type 1 and 2)."""
    groups = defaultdict(list)
    for f in funcs:
        if len(f.tokens) >= min_nodes:
            groups[f.shape].append(f)
    return [g for g in groups.values() if len(g) > 1]


def near_clones(funcs, threshold=THRESHOLD, min_nodes=MIN_NODES):
    """Pairs (ratio, a, b) of functions with different shapes whose node sequences match at
    `threshold` or above (type 3). Sizes are sorted so a pair whose length ratio already rules
    out the threshold is never compared: ratio <= 2 * min(len) / (len a + len b)."""
    big = sorted((f for f in funcs if len(f.tokens) >= min_nodes), key=lambda f: len(f.tokens))
    pairs = []
    for i, a in enumerate(big):
        matcher = difflib.SequenceMatcher(None, autojunk=False)
        matcher.set_seq2(a.tokens)
        for b in big[i + 1 :]:
            if 2 * len(a.tokens) / (len(a.tokens) + len(b.tokens)) < threshold:
                break
            if a.shape == b.shape:
                continue
            matcher.set_seq1(b.tokens)
            if matcher.real_quick_ratio() >= threshold and matcher.quick_ratio() >= threshold:
                ratio = matcher.ratio()
                if ratio >= threshold:
                    pairs.append((round(ratio, 3), a, b))
    return pairs


def scan(root):
    """Every function of every .py file under root, paths relative to root."""
    root = Path(root)
    return [
        f
        for path in sorted(root.rglob("*.py"))
        for f in functions(path.read_text(encoding="utf-8"), path.relative_to(root).as_posix())
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("root", type=Path)
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    parser.add_argument("--min-nodes", type=int, default=MIN_NODES)
    args = parser.parse_args(argv)
    funcs = scan(args.root)
    for group in clones(funcs, args.min_nodes):
        print("clone:", ", ".join(f"{f.path}:{f.line} {f.name}" for f in group))
    for ratio, a, b in near_clones(funcs, args.threshold, args.min_nodes):
        print(f"near clone {ratio:.2f}: {a.path}:{a.line} {a.name}, {b.path}:{b.line} {b.name}")


if __name__ == "__main__":
    main()
