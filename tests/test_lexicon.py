"""The words of the interface: one term per concept, as the project's lexicon sets them. DCMA's term
first, else P6's name: "status date" (not data date), "task" and "Task ID" (not activity, Activity
ID), US spelling ("anonymized", as "labor"). Every string literal of app/ is read, docstrings and
identifiers (no space) aside; P6's own names, quoted where the page points at a P6 field, dialog or
export column, are the exceptions."""

import ast
import re
from pathlib import Path

import xerscope

APP = Path(xerscope.__file__).parent / "app"

OFF_LEXICON = {
    r"\bdata dates?\b": "status date",
    r"\bActivity IDs?\b": "Task ID",
    r"\bactivit(?:y|ies)\b": "task",
    r"anonymis": "anonymiz",
}

# P6's names (Oracle P6 Professional help, XER data map, Activities export columns), kept as P6 writes them
P6_NAMES = {
    "diagnostic.py": [
        "Ignore in-progress activities",
        "Ignore activities with soft constraints",
        "Ignore activities with hard constraints",
        "Defaults for New Activities",
        "of new activities",
        "for not started activities",
        "Default Activity Type",
        "Activity type",
        "Activity % Complete Type",
        "Activity Percent Complete",
        "Activity ID",
        "Activity Status",
    ],
    "glossary.py": ["P6 Activity ID", "Level of Effort activity type"],
    "state.py": ["Renumber Activity IDs", "Renumber Selected Activities in Baselines"],
    "views/debug.py": [
        "P6 links a task to its baseline by Activity ID",
        "Activities view of P6",
        "with Activity ID",
        "Joined on Activity ID",
        "Activity Status",
        "P6 Activities export",
        "without Activity ID",
        "repeated Activity IDs",
        "its activity list",  # Debug zip caption, changed on export/obfuscate-proj-id
    ],
    "views/gantt.py": ["P6 activity code"],
}


def _literals(path: Path):
    """(line, text) of every string constant of ``path`` but docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


def test_the_interface_speaks_the_lexicon():
    found = []
    for path in sorted(APP.rglob("*.py")):
        name = path.relative_to(APP).as_posix()
        for line, text in _literals(path):
            if " " not in text.strip():
                continue  # a key, a column or a file name
            ours = text
            for phrase in P6_NAMES.get(name, []):
                ours = ours.replace(phrase, "")
            found += [
                f"{name}:{line}: {match.group(0)!r} -> {term}"
                for pattern, term in OFF_LEXICON.items()
                for match in re.finditer(pattern, ours, re.IGNORECASE)
            ]
    assert not found, "\n".join(found)
