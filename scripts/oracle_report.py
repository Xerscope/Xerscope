"""Count the collected tests by ``oracle`` kind, and those without one.

    uv run python scripts/oracle_report.py

A witness, not a gate: it always exits 0 once collection succeeds. The kinds are those of
``ORACLE_KINDS`` in tests/conftest.py, which rejects any other at collection.
"""

from __future__ import annotations

import contextlib
import io
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UNMARKED = "(none)"


def tally(kinds: list[str | None]) -> Counter:
    """Number of tests per kind; a test without the marker counts under UNMARKED."""
    return Counter(UNMARKED if kind is None else kind for kind in kinds)


def render(counts: Counter) -> str:
    """Markdown table, kinds by name then the unmarked tests, then the total."""
    total = sum(counts.values())
    rows = [kind for kind in sorted(counts) if kind != UNMARKED] + [UNMARKED]
    lines = ["| oracle | tests | share |", "|---|---:|---:|"]
    for kind in rows:
        n = counts.get(kind, 0)
        lines.append(f"| {kind} | {n} | {n / total:.0%} |" if total else f"| {kind} | {n} | - |")
    lines.append(f"| total | {total} | |")
    return "\n".join(lines)


class _Collector:
    def __init__(self):
        self.kinds: list[str | None] = []

    def pytest_collection_finish(self, session):
        for item in session.items:
            mark = item.get_closest_marker("oracle")
            self.kinds.append(mark.args[0] if mark else None)


def collect(tests: Path = ROOT / "tests") -> list[str | None]:
    """The oracle kind of each test pytest collects under ``tests`` (None when unmarked)."""
    collector = _Collector()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider", str(tests)], plugins=[collector])
    if code != 0:
        sys.stdout.write(out.getvalue())
        raise SystemExit(code)
    return collector.kinds


if __name__ == "__main__":
    print(render(tally(collect())))
