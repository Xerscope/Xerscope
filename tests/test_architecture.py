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


# The app's own modules, as docs/architecture.md §7 lays them out (asked by the maintainer, 2026-11-20:
# the baseline domain and the caches cut by responsibility, the pages importing each name from its
# module). An edge added here is a design decision, written in the doc first.
APP = Path(__file__).resolve().parents[1] / "src" / "xerscope" / "app"
APP_EDGES = {  # module -> the app modules it may import
    "session": set(),
    "xml_baselines": set(),
    "reading": set(),
    "ui": {"glossary"},
    "baseline_file": {"session"},
    "baseline_export": {"baseline_file", "session", "xml_baselines"},
    "baselines": {"baseline_export", "baseline_file", "session"},
    "cache": {"baselines"},
    "baseline_window": {"baseline_export", "baseline_file", "baselines", "session", "xml_baselines"},
    "baseline_warnings": {"baseline_export", "baseline_file", "baseline_window", "baselines", "cache", "session"},
    "files_window": {"baseline_window", "session"},
    "loading": {"baseline_warnings", "files_window", "reading", "session"},
    "downloads": {"baseline_file", "session"},
}
BASELINE_DOMAIN = {"baseline_file", "baseline_export", "baselines", "baseline_window", "baseline_warnings"}


def app_imports(path):
    """The app modules ``path`` imports (``xerscope.app.<module>``), itself left out."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {
        node.module.split(".")[2]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("xerscope.app.")
    }
    return modules - {path.stem}


def test_the_app_modules_import_one_way_and_the_pages_read_each_name_from_its_module():
    """The import graph of app/*.py: the edges written above, the baseline domain reading none of the
    pages' machinery (state, loading, downloads, cache), state.py imported by the pages only, no cycle."""
    graph = {path.stem: app_imports(path) for path in APP.glob("*.py")}
    for module, allowed in APP_EDGES.items():
        edges = {target for target in graph[module] if target in graph}
        assert edges <= allowed, (module, sorted(edges - allowed))
    for module in BASELINE_DOMAIN:
        assert not graph[module] & {"state", "loading", "downloads", "cache"} - APP_EDGES[module], module
    importers_of_state = {module for module, targets in graph.items() if "state" in targets}
    assert importers_of_state <= {"streamlit_app"}, sorted(
        importers_of_state
    )  # the pages read state.py, nothing else does

    def reaches(start, seen):
        for target in graph.get(start, ()):
            if target in seen:
                return seen + [target]
            found = reaches(target, seen + [target])
            if found:
                return found
        return []

    cycles = [reaches(module, [module]) for module in graph]
    assert not any(cycles), [cycle for cycle in cycles if cycle]
