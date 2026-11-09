"""Code fitness measures of src/xerscope, written as JSON, checked against a committed baseline.

Per module: maintainability index (radon MI and its rank: A >= 20, B 10-19, C < 10),
cyclomatic complexity (radon: highest, and functions above 15), cognitive complexity
(complexipy: highest, and functions above 15), structural clones (scripts/duplication.py:
functions of the module with a type 1/2 copy anywhere in src, and type 3 near clones).
Global: mypy errors, deptry violations, broken import-linter contracts. The contracts are
generated from LAYERS in tests/test_architecture.py, one per layer: the layer may import
nothing of the other layers but what LAYERS lists.

    uv run python scripts/fitness.py --out fitness.json --markdown summary.md
    uv run python scripts/fitness.py --check tests/fitness_baseline.json

--check fails when a measure is worse than in the baseline: a lower MI rank, any count or
maximum that went up, or a new module that is not rank A with no function above 15 and no
clone. Near clones are reported, not checked (a ratio crosses the threshold too easily).
An improvement is listed so the baseline can be regenerated and the gain kept.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import complexipy
import duplication
import mypy.api
from radon.complexity import cc_visit
from radon.metrics import mi_rank, mi_visit

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "xerscope"
LIMIT = 15  # cyclomatic and cognitive: complexipy's default ceiling (--max-complexity-allowed)
RANKS = "ABC"
UNCHECKED = {"mi", "near_clones", "import_contracts"}

sys.path.insert(0, str(ROOT / "tests"))
from test_architecture import LAYERS  # noqa: E402


def _cyclomatic(blocks):  # functions, methods and nested functions; a class is not a function
    for block in blocks:
        if hasattr(block, "closures"):
            yield block.complexity
            yield from _cyclomatic(block.closures)


def modules():
    measures = {}
    funcs = duplication.scan(SRC)
    cloned = [f.path for group in duplication.clones(funcs) for f in group]
    near = [f.path for _, a, b in duplication.near_clones(funcs) for f in (a, b)]
    for path in sorted(SRC.rglob("*.py")):
        name = path.relative_to(SRC).as_posix()
        code = path.read_text(encoding="utf-8")
        mi = mi_visit(code, multi=True)
        cc = list(_cyclomatic(cc_visit(code)))
        cognitive = [f.complexity for f in complexipy.file_complexity(str(path)).functions]
        measures[name] = {
            "mi": round(mi, 1),
            "mi_rank": mi_rank(mi),
            "cc_max": max(cc, default=0),
            "cc_over_15": sum(c > LIMIT for c in cc),
            "cognitive_max": max(cognitive, default=0),
            "cognitive_over_15": sum(c > LIMIT for c in cognitive),
            "clones": cloned.count(name),
            "near_clones": near.count(name),
        }
    return measures


def _dotted(path):
    parts = path.relative_to(SRC.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def contracts():
    """import-linter configuration from LAYERS: for each layer, every module of the other layers
    it may not import. Direct imports only, module by module, as tests/test_architecture.py reads.
    import-linter sees regular packages only: app/views (Streamlit pages, no __init__.py) is left
    to tests/test_architecture.py."""
    packages = {p.parent for p in SRC.rglob("__init__.py")}
    regular = (p for p in SRC.rglob("*.py") if all(d in packages for d in p.parents if d.is_relative_to(SRC)))
    modules = {_dotted(p) for p in regular} - {"xerscope"}

    def layer(module):
        return module.split(".")[1]

    def allowed(rule):  # 'analysis.wbs.ROOT' allows the module xerscope.analysis.wbs
        parts = ["xerscope", *rule.split(".")]
        module = next(m for k in range(len(parts), 1, -1) if (m := ".".join(parts[:k])) in modules)
        return {m for m in modules if m == module or m.startswith(f"{module}.")}

    lines = ["[importlinter]", "root_package = xerscope"]
    for source, rules in sorted(LAYERS.items()):
        ok = set().union(*map(allowed, rules))
        lines += [
            "",
            f"[importlinter:contract:{source}]",
            f"name = {source} imports only {', '.join(sorted(rules))}",
            "type = forbidden",
            "as_packages = False",
            "allow_indirect_imports = True",
            "source_modules =",
            *(f"    {m}" for m in sorted(modules) if layer(m) == source),
            "forbidden_modules =",
            *(f"    {m}" for m in sorted(modules) if layer(m) != source and m not in ok),
        ]
    return "\n".join(lines) + "\n"


def import_contracts():
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "importlinter.ini"
        config.write_text(contracts(), encoding="utf-8")
        cmd = ["lint-imports", "--config", str(config), "--no-cache", "--no-logo"]
        out = subprocess.run(cmd, check=False, cwd=ROOT, capture_output=True, text=True).stdout
    found = re.search(r"Contracts: (\d+) kept, (\d+) broken", out)
    if not found:
        raise SystemExit(f"lint-imports gave no summary:\n{out}")
    return int(found[1]) + int(found[2]), int(found[2])


def mypy_errors():
    out, _, _ = mypy.api.run([str(SRC.relative_to(ROOT)), "--no-error-summary"])
    return sum(" error: " in line for line in out.splitlines())


def deptry_violations():
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "deptry.json"
        subprocess.run(["deptry", "src", "-o", str(report)], check=False, cwd=ROOT, capture_output=True)
        return len(json.loads(report.read_text(encoding="utf-8")))


def measure():
    total, broken = import_contracts()
    return {
        "modules": modules(),
        "global": {
            "mypy_errors": mypy_errors(),
            "deptry_violations": deptry_violations(),
            "import_contracts": total,
            "import_contracts_broken": broken,
        },
    }


def compare(current, baseline):
    """(regressions, improvements) of current against baseline, one line each."""
    worse, better = [], []

    def numbers(where, now, before):
        for key, value in now.items():
            if key in UNCHECKED or key not in before:
                continue
            if key == "mi_rank":
                old, new = RANKS.index(before[key]), RANKS.index(value)
            else:
                old, new = before[key], value
            if new != old:
                (worse if new > old else better).append(f"{where} {key}: {before[key]} -> {value}")

    for name, now in current["modules"].items():
        before = baseline["modules"].get(name)
        if before is not None:
            numbers(name, now, before)
            continue
        bad = {"mi_rank": now["mi_rank"] != "A"} | {
            k: now[k] > 0 for k in ("cc_over_15", "cognitive_over_15", "clones")
        }
        worse += [f"{name} (new) {key}: {now[key]}" for key, failed in bad.items() if failed]
    numbers("global", current["global"], baseline["global"])
    return worse, better


COLUMNS = ["mi", "mi_rank", "cc_max", "cc_over_15", "cognitive_max", "cognitive_over_15", "clones", "near_clones"]


def markdown(result, worse=(), better=()):
    lines = ["## Code fitness", "", "| module | " + " | ".join(COLUMNS) + " |", "|---" * (len(COLUMNS) + 1) + "|"]
    for name, row in result["modules"].items():
        lines.append(f"| {name} | " + " | ".join(str(row[c]) for c in COLUMNS) + " |")
    lines += ["", "| global | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in result["global"].items()]
    if worse or better:
        lines += ["", "### Against the baseline", ""]
        lines += [f"- worse: {line}" for line in worse] + [f"- better: {line}" for line in better]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=ROOT / "fitness.json")
    parser.add_argument("--markdown", type=Path, help="append a Markdown summary to this file")
    parser.add_argument("--check", type=Path, metavar="BASELINE", help="fail when a measure is worse than here")
    args = parser.parse_args(argv)

    result = measure()
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    worse, better = [], []
    if args.check:
        worse, better = compare(result, json.loads(args.check.read_text(encoding="utf-8")))
        for line in better:
            print("better:", line)
        for line in worse:
            print("worse:", line)
    if args.markdown:
        with args.markdown.open("a", encoding="utf-8") as summary:
            summary.write(markdown(result, worse, better))
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main())
