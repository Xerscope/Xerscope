"""Every value a pull request moves in the golden file, FLOORS or a standard TOML is justified
in its description, and so is every measure it lets get worse in the fitness baseline; no FLOORS
value goes down.

    PR_BODY="..." python scripts/check_value_justification.py BASE_SHA

Compares the files at BASE_SHA with the working tree. Each moved value needs one line of the
description, copied from what this script prints and completed with its evidence:

    ID: old -> new — source

``old`` and ``new`` are written as JSON (``absent`` for a value added or removed). Prose fields
of a standard (name, description, source) are not values. In tests/fitness_baseline.json only a
measure that gets worse needs a line (a count or a maximum that goes up, a maintainability rank
that drops, as scripts/fitness.py reads them): an improvement is free. Standard library only: the CI job
runs it without installing the project.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tomllib

GOLDEN = "tests/golden/standards.json"
FLOORS_FILE = "tests/test_p6_heldout.py"
STANDARDS_DIR = "src/xerscope/standards/"
PROSE = frozenset({"name", "description", "source"})
ABSENT = "absent"
FITNESS = "tests/fitness_baseline.json"
# as scripts/fitness.py: measures it reports without checking, and the order of the ranks
FITNESS_UNCHECKED = frozenset({"mi", "near_clones", "import_contracts"})
RANKS = "ABC"


def _show(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _leaves(node, prefix: str, sep: str = "/") -> dict[str, str]:
    """{path: JSON text} of every non-dict value under ``node``; a list is one value."""
    if not isinstance(node, dict):
        return {prefix: _show(node)}
    out = {}
    for key, value in node.items():
        out |= _leaves(value, f"{prefix}{sep}{key}" if prefix else str(key), sep)
    return out


def golden_values(text: str | None) -> dict[str, str]:
    """Values of tests/golden/standards.json, by path: ``demo/<file>/DCMA/DCMA-01/value``."""
    return _leaves(json.loads(text), "") if text else {}


def standard_values(stem: str, text: str | None) -> dict[str, str]:
    """Values of a standard TOML, by ``<file stem>/<metric id>.<field>`` (``<file stem>.<field>``
    for the [standard] table); prose fields left out."""
    if not text:
        return {}
    data = tomllib.loads(text)
    out = {}
    for key, value in data.get("standard", {}).items():
        if key not in PROSE:
            out |= _leaves(value, f"{stem}.{key}", ".")
    for metric in data.get("metric", []):
        for key, value in metric.items():
            if key not in PROSE and key != "id":
                out |= _leaves(value, f"{stem}/{metric['id']}.{key}", ".")
    return out


def floors(text: str | None) -> dict[str, float]:
    """The FLOORS dict literal of tests/test_p6_heldout.py."""
    if not text:
        return {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "FLOORS" for t in node.targets):
            return ast.literal_eval(node.value)
    return {}


def floor_values(text: str | None) -> dict[str, str]:
    return {f"FLOORS/{key}": _show(value) for key, value in floors(text).items()}


def fitness_values(text: str | None) -> dict[str, str]:
    """Checked measures of the fitness baseline, by ``fitness/<module>.<measure>`` (``fitness/global.<measure>``)."""
    if not text:
        return {}
    data = json.loads(text)
    rows = {**data.get("modules", {}), "global": data.get("global", {})}
    return {
        f"fitness/{name}.{measure}": _show(value)
        for name, row in rows.items()
        for measure, value in row.items()
        if measure not in FITNESS_UNCHECKED
    }


def _worse(key: str, old: str, new: str) -> bool:
    """A fitness measure went the wrong way; one that is new counts from 0, or from rank A."""
    if new == ABSENT:
        return False  # a module removed
    if key.endswith(".mi_rank"):
        return RANKS.index(json.loads(new)) > (0 if old == ABSENT else RANKS.index(json.loads(old)))
    return json.loads(new) > (0 if old == ABSENT else json.loads(old))


def moved(old: dict[str, str], new: dict[str, str]) -> list[tuple[str, str, str]]:
    """(id, old, new) of each value that differs, ``absent`` on the side that lacks it."""
    return [
        (key, old.get(key, ABSENT), new.get(key, ABSENT))
        for key in sorted(old.keys() | new.keys())
        if old.get(key) != new.get(key)
    ]


def justified(body: str) -> set[str]:
    """The ``ID: old -> new`` part of each description line that ends with ``— source``; the
    template's HTML comments (its examples) do not count."""
    out = set()
    for raw in re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).splitlines():
        line = re.sub(r"^\s*(?:[-*]\s+)?", "", raw).strip()
        match = re.fullmatch(r"(.+? -> .+?)\s+—\s+\S.*", line)
        if match:
            out.add(match.group(1))
    return out


def lowered_floors(old_text: str | None, new_text: str | None) -> list[str]:
    """FLOORS entries lower at the head than at the base, or removed."""
    old, new = floors(old_text), floors(new_text)
    out = []
    for key in sorted(old):
        if key not in new:
            out.append(f"FLOORS/{key}: {old[key]} removed")
        elif new[key] < old[key]:
            out.append(f"FLOORS/{key}: {old[key]} -> {new[key]} lowered")
    return out


def values(path: str, text: str | None) -> dict[str, str]:
    if path == GOLDEN:
        return golden_values(text)
    if path == FLOORS_FILE:
        return floor_values(text)
    if path == FITNESS:
        return fitness_values(text)
    return standard_values(path.removeprefix(STANDARDS_DIR).removesuffix(".toml"), text)


def check(files: dict[str, tuple[str | None, str | None]], body: str) -> tuple[list[str], list[str]]:
    """(lowered FLOORS, missing justification lines) for ``{path: (base text, head text)}``,
    None standing for a file absent on that side."""
    lowered = lowered_floors(*files.get(FLOORS_FILE, (None, None)))
    done = justified(body)
    missing = []
    for path, (old_text, new_text) in sorted(files.items()):
        for key, old, new in moved(values(path, old_text), values(path, new_text)):
            if path == FITNESS and not _worse(key, old, new):
                continue
            if f"{key}: {old} -> {new}" not in done:
                missing.append(f"{key}: {old} -> {new} — <source>")
    return lowered, missing


def _git(*args: str) -> str | None:
    run = subprocess.run(["git", *args], check=False, capture_output=True, text=True, encoding="utf-8")
    return run.stdout if run.returncode == 0 else None


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def watched(base: str) -> dict[str, tuple[str | None, str | None]]:
    """Base and head text of every watched file present on either side."""
    paths = {GOLDEN, FLOORS_FILE, FITNESS}
    paths |= set((_git("ls-tree", "--name-only", base, STANDARDS_DIR) or "").split())
    paths |= {STANDARDS_DIR + name for name in os.listdir(STANDARDS_DIR)}
    return {p: (_git("show", f"{base}:{p}"), _read(p)) for p in paths if p.endswith((".json", ".py", ".toml"))}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    if _git("cat-file", "-e", f"{argv[1]}^{{commit}}") is None:
        print(f"base commit {argv[1]} not found (fetch it first)")
        return 2
    lowered, missing = check(watched(argv[1]), os.environ.get("PR_BODY") or "")
    if lowered:
        print("FLOORS only go up (tests/test_p6_heldout.py):\n" + "\n".join(lowered) + "\n")
    if missing:
        print("Values moved without a justification line. Add each line below to the pull request")
        print("description, <source> replaced by its evidence (P6 export, held-out corpus, MPXJ, standard text;")
        print("for a fitness measure, why it gets worse and the pull request that will bring it back):\n")
        print("\n".join(missing))
    if lowered or missing:
        return 1
    print("Every moved value is justified; no FLOORS value lowered; no fitness measure worse without its line.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
