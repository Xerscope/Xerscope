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
    yield from imported_names(path.read_text(encoding="utf-8"), package)


def imported_names(text, package):  # every name the source imports, absolute, ``package`` the source's own
    for node in ast.walk(ast.parse(text)):
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


# The app's own modules, as docs/architecture.md §7 lays them out (Import edges). Every module of app/
# has an entry and its edges are compared exactly: a new module, a new edge or an edge no longer used
# fails here, and is written in the doc in the same change.
APP = Path(__file__).resolve().parents[1] / "src" / "xerscope" / "app"
APP_EDGES = {  # module -> exactly the app modules it imports
    "__init__": set(),
    "code_picker": set(),
    "expected_finish_forms": set(),
    "glossary": set(),
    "reading": set(),
    "recalculation_departures": set(),
    "table_filters": set(),
    "theme": set(),
    "ui": {"glossary", "table_filters", "theme"},
    "explanation_panel": {"ui"},
    "task_panel": {"ui"},
    "activity_details": {"ui"},
    "xml_baselines": {"ui"},
    "session": {"ui"},
    "baseline_file": {"session"},
    "baseline_export": {"baseline_file", "session", "xml_baselines"},
    "baselines": {"baseline_export", "baseline_file", "session", "ui"},
    "cache": {"baselines"},
    "baseline_window": {"baseline_export", "baseline_file", "baselines", "session", "ui", "xml_baselines"},
    "baseline_warnings": {
        "baseline_export",
        "baseline_file",
        "baseline_window",
        "baselines",
        "cache",
        "session",
        "ui",
    },
    "files_window": {"baseline_window", "session", "ui"},
    "loading": {"baseline_warnings", "files_window", "reading", "session", "ui"},
    "downloads": {"baseline_file", "session"},
    "sets": {"downloads", "ui"},
    "diagnostic": {"expected_finish_forms", "recalculation_departures", "ui"},
    "state": {
        "baseline_export",
        "baseline_warnings",
        "baseline_window",
        "baselines",
        "downloads",
        "loading",
        "session",
        "ui",
    },
    "streamlit_app": {"loading", "session", "theme", "ui"},
}
BASELINE_DOMAIN = {"baseline_file", "baseline_export", "baselines", "baseline_window", "baseline_warnings"}


def app_modules(names):
    """The app module each absolute imported name lies in: ``xerscope.app.ui.table`` and
    ``xerscope.app.ui`` both give ``ui``."""
    return {name.split(".")[2] for name in names if name.startswith("xerscope.app.")}


def app_imports(path):
    """The app modules ``path`` imports, in every form (``from xerscope.app import ui``,
    ``from xerscope.app.ui import table``, ``import xerscope.app.ui``, relative), itself left out."""
    return app_modules(imports(path)) - {path.stem}


def test_every_form_of_an_import_of_an_app_module_is_read():
    """The reader behind the graph below, one line per form Python allows. The first form is the one
    the reader missed until 2026-11-22: 22 imports of ``ui`` were invisible to the graph."""
    source = "\n".join(
        [
            "from xerscope.app import ui, theme",
            "from xerscope.app.session import counted",
            "import xerscope.app.cache",
            "from .downloads import show_download",
            "from xerscope.analysis import cpm",
        ]
    )
    names = imported_names(source, ["xerscope", "app"])
    assert app_modules(names) == {"ui", "theme", "session", "cache", "downloads"}


def test_the_app_modules_import_one_way_and_the_pages_read_each_name_from_its_module():
    """The import graph of app/*.py: the edges written above, exactly, for every module; the baseline
    domain reading none of the pages' machinery (state, loading, downloads, cache); state.py imported by
    the pages only; no module importing a page and no page importing another; no cycle."""
    graph = {path.stem: app_imports(path) for path in APP.glob("*.py")}
    assert set(graph) == set(APP_EDGES), sorted(set(graph) ^ set(APP_EDGES))
    for module, allowed in APP_EDGES.items():
        edges = {target for target in graph[module] if target in graph}
        assert edges == allowed, (module, "not written:", sorted(edges - allowed), "unused:", sorted(allowed - edges))
    pages = {path.stem: app_imports(path) for path in (APP / "views").glob("*.py")}
    assert not {module for module, targets in graph.items() if "views" in targets}
    assert not {page for page, targets in pages.items() if "views" in targets}
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
