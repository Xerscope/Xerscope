"""The layer rules of docs/architecture.md (Layer rules), checked against every import of src/xerscope."""

import ast
from pathlib import Path

SRC = Path(__file__).parents[1] / "src" / "xerscope"

LAYERS = {  # layer -> exactly what it imports from the other layers
    "xer": {"config"},
    "store": {"xer", "config"},
    "export": {"store", "config", "csv_safe"},
    "anonymize": {"xer", "export"},
    "analysis": {"xer", "store"},
    "viz": {"config", "analysis.wbs.ROOT"},
    "verify": {"xer", "analysis.cpm", "config"},
    "crosscheck": {"verify"},
    "sample": {"xer", "analysis.cpm", "config"},
    "app": {"xer", "store", "analysis", "viz", "export", "anonymize", "config"},
    "cli": {
        "xer",
        "store",
        "analysis",
        "viz",
        "export",
        "sample",
        "verify",
        "crosscheck",
        "anonymize",
        "app.diagnostic",
        "config",
    },
}


def imports(path):  # every name the file imports, absolute: 'xerscope.layer.module.name'
    package = ["xerscope", *path.relative_to(SRC).parts[:-1]]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):  # relative: drop node.level - 1 trailing packages
            base = ".".join(filter(None, [*package[: len(package) - node.level + 1 if node.level else 0], node.module]))
            yield from (f"{base}.{a.name}" for a in node.names)


def rule_for(name, allowed):
    """The rule of LAYERS that admits an imported name, else the name itself (so it shows in the diff)."""
    return next((rule for rule in allowed if f"{name}.".startswith(f"{rule}.")), name)


def test_layer_imports_match_the_architecture_doc():
    layer = {p: p.relative_to(SRC).parts[0].removesuffix(".py") for p in SRC.rglob("*.py")}
    cross = set()  # (layer, imported name) for every import that leaves its layer
    for path, source in layer.items():
        for name in imports(path):
            if name.startswith("xerscope."):
                target = name.removeprefix("xerscope.")
                if target.split(".")[0] != source:
                    cross.add((source, target))
    for source, allowed in LAYERS.items():
        used = {rule_for(target, allowed) for s, target in cross if s == source}
        assert used == allowed, source
    assert {source for source, target in cross if target.split(".")[0] == "app"} == {"cli"}
