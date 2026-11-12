"""Mutation score of the modules named in [tool.mutmut], checked against a committed baseline.

mutmut changes one thing at a time in a module (an operator, a constant, an argument) and runs
the tests that reach the changed function: a mutant is killed when a test fails. The score of a
module is killed / mutants. This script reads the results mutmut left in mutants/ and compares
them with tests/mutation_baseline.json.

    uv run mutmut run
    uv run python scripts/mutation.py --out mutation.json --markdown summary.md
    uv run python scripts/mutation.py --check tests/mutation_baseline.json

--check fails when the score of a module is lower than in the baseline, when a module of the
baseline was not measured, or when a mutant was left unchecked (an interrupted run). A higher
score is listed so the baseline can be regenerated and the gain kept. A module absent from the
baseline is listed, not checked.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
KILLED = {1, 3}  # mutmut 3.8.1, stats.status_by_exit_code: a failed test, or an internal error of pytest
SURVIVED = {0}
NO_TESTS = {5, 33}  # no test reaches the mutated function


def measure(mutants: Path) -> dict[str, dict[str, int]]:
    """Per mutated module (path from the repository root): mutants, killed, survived, no_tests, unchecked."""
    result = {}
    for meta in sorted(mutants.rglob("*.py.meta")):
        codes = json.loads(meta.read_text(encoding="utf-8"))["exit_code_by_key"].values()
        name = meta.relative_to(mutants).as_posix().removesuffix(".meta")
        result[name] = {
            "mutants": len(codes),
            "killed": sum(code in KILLED for code in codes),
            "survived": sum(code in SURVIVED for code in codes),
            "no_tests": sum(code in NO_TESTS for code in codes),
            "unchecked": sum(code is None for code in codes),
        }
    return result


def score(row) -> str:
    return (
        f"{row['killed']}/{row['mutants']} ({100 * row['killed'] / row['mutants']:.1f} %)" if row["mutants"] else "0/0"
    )


def compare(current, baseline):
    """(regressions, improvements) of current against baseline, one line each."""
    worse, better = [], []
    for name, before in baseline.items():
        now = current.get(name)
        if now is None:
            worse.append(f"{name}: not measured")
            continue
        if now["unchecked"]:
            worse.append(f"{name}: {now['unchecked']} mutants left unchecked")
        # killed / mutants compared without a division: the mutant count moves with the code
        gap = now["killed"] * before["mutants"] - before["killed"] * now["mutants"]
        if gap:
            (worse if gap < 0 else better).append(f"{name}: {score(before)} -> {score(now)}")
    better += [f"{name} (new): {score(now)}" for name, now in current.items() if name not in baseline]
    return worse, better


COLUMNS = ["mutants", "killed", "survived", "no_tests", "unchecked"]


def markdown(result, worse=(), better=()):
    lines = [
        "## Mutation score",
        "",
        "| module | score | " + " | ".join(COLUMNS) + " |",
        "|---" * (len(COLUMNS) + 2) + "|",
    ]
    for name, row in result.items():
        lines.append(f"| {name} | {score(row)} | " + " | ".join(str(row[c]) for c in COLUMNS) + " |")
    if worse or better:
        lines += ["", "### Against the baseline", ""]
        lines += [f"- worse: {line}" for line in worse] + [f"- better: {line}" for line in better]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mutants", type=Path, default=ROOT / "mutants", help="where mutmut wrote its results")
    parser.add_argument("--out", type=Path, default=ROOT / "mutation.json")
    parser.add_argument("--markdown", type=Path, help="append a Markdown summary to this file")
    parser.add_argument("--check", type=Path, metavar="BASELINE", help="fail when a score is lower than here")
    args = parser.parse_args(argv)

    result = measure(args.mutants)
    if not result:
        print(f"no mutmut result under {args.mutants}: run `uv run mutmut run` first")
        return 1
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
