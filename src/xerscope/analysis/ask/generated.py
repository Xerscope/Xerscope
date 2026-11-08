"""The files' own variants: words of one source column read as one ("Fondation" / "Fondations",
"Mec." / "Mechanical"), generated from every loaded file, in memory.

A. Every term keeps its source column (``COLUMNS``, XER table.field). A group never crosses a
   column, so a common word of an activity name never joins a WBS name.
B. Written rules only, no clustering:
   - folding: case and accents ("Béton" / "beton" are one word);
   - plural, French or English: w / w+s, w / w+es, -al / -aux;
   - an abbreviation written with its dot ("Mec.", "Elec.", 3+ letters) and the one longer
     word of the column it begins;
   - one letter added, removed or changed between two words of 6+ letters with the same first
     letter ("Instalation" / "Installation").
Pure and deterministic: the same files give the same groups, sorted. ``xerscope lexicon build``
writes them to a file for review; the app derives them per session and never writes them."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from pathlib import Path

from ...xer import Snapshot
from .lexicon import Lexicon, json_quote, lexicon_from_groups
from .text import fold

MIN_ABBREVIATION = 3  # letters of an abbreviation ("Mec.")
MIN_EDITED = 6  # letters of two words one edit apart


def _column_values(snapshot: Snapshot) -> dict[str, list[str]]:
    """The text values of each source column of one file."""
    wbs, tasks, codes, assigned = snapshot.wbs, snapshot.activities, snapshot.code_values, snapshot.assignments
    values = {
        "PROJWBS.wbs_short_name": wbs.get("wbs_short_name"),
        "PROJWBS.wbs_name": wbs.get("wbs_name"),
        "TASK.task_code": tasks.get("task_code"),
        "TASK.task_name": tasks.get("task_name"),
        "ACTVTYPE.actv_code_type": codes.get("code_type"),
        "ACTVCODE.short_name": codes.get("value"),
        "ACTVCODE.actv_code_name": codes.get("name"),
        "RSRC.rsrc_short_name": assigned.get("rsrc_short_name"),
        "RSRC.rsrc_name": assigned.get("rsrc_name"),
    }
    return {column: list(series.dropna().astype(str)) for column, series in values.items() if series is not None}


COLUMNS = (
    "PROJWBS.wbs_short_name",
    "PROJWBS.wbs_name",
    "TASK.task_code",
    "TASK.task_name",
    "ACTVTYPE.actv_code_type",
    "ACTVCODE.short_name",
    "ACTVCODE.actv_code_name",
    "RSRC.rsrc_short_name",
    "RSRC.rsrc_name",
)
GROUPED = tuple(c for c in COLUMNS if c != "TASK.task_code")  # Activity IDs are never variants


def terms(snapshots: Iterable[Snapshot]) -> dict[str, tuple[set[str], set[str]]]:
    """Per column: its folded words (letters only, 3+), and those written as an abbreviation."""
    found: dict[str, tuple[set[str], set[str]]] = {}
    for snapshot in snapshots:
        for column, values in _column_values(snapshot).items():
            words, abbreviated = found.setdefault(column, (set(), set()))
            for value in values:
                text = fold(value)
                words.update(w for w in re.findall(r"[a-z]+", text) if len(w) >= 3)
                abbreviated.update(w for w in re.findall(r"([a-z]+)\.", text) if len(w) >= MIN_ABBREVIATION)
    return found


def variants(snapshots: Iterable[Snapshot]) -> dict[str, list[list[str]]]:
    """Per grouped column, its groups of variants (each sorted, the groups sorted); a column
    with no group is left out."""
    found = terms(snapshots)
    groups = {column: group_words(*found[column]) for column in GROUPED if column in found}
    return {column: g for column, g in groups.items() if g}


def group_words(words: set[str], abbreviated: set[str] = frozenset()) -> list[list[str]]:
    """The words of one column joined by the rules of the module docstring."""
    parent = {w: w for w in words}

    def root(w: str) -> str:
        while parent[w] != w:
            parent[w] = parent[parent[w]]
            w = parent[w]
        return w

    for a, b in _pairs(words, abbreviated):
        parent[root(a)] = root(b)
    groups: dict[str, list[str]] = {}
    for w in sorted(words):
        groups.setdefault(root(w), []).append(w)
    return sorted(g for g in groups.values() if len(g) > 1)


def _pairs(words: set[str], abbreviated: set[str]) -> list[tuple[str, str]]:
    pairs = [(w, p) for w in words for p in _plurals(w) if p in words]
    for short in abbreviated & words:
        longer = [w for w in words if w != short and w.startswith(short)]
        if len(longer) == 1:  # the one word of the column it can stand for
            pairs.append((short, longer[0]))
    return pairs + _near_spellings(words)


def _near_spellings(words: set[str]) -> list[tuple[str, str]]:
    """Words of 6+ letters, same first letter, one edit apart; compared within length buckets."""
    buckets: dict[tuple[str, int], list[str]] = {}
    for w in sorted(words):
        if len(w) >= MIN_EDITED:
            buckets.setdefault((w[0], len(w)), []).append(w)
    pairs = []
    for (first, size), bucket in buckets.items():
        for other in (*bucket, *buckets.get((first, size + 1), [])):
            pairs += [(w, other) for w in bucket if w < other and _one_edit(w, other)]
    return pairs


def _plurals(word: str) -> list[str]:
    forms = [word + "s", word + "es"]
    return forms + ([word[:-2] + "aux"] if word.endswith("al") else [])


def _one_edit(a: str, b: str) -> bool:
    """One letter added, removed or changed (Levenshtein distance 1)."""
    if len(a) > len(b):
        a, b = b, a
    if len(b) - len(a) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    i = next((k for k in range(len(a)) if a[k] != b[k]), len(a))
    return a[i:] == b[i + 1 :]


def lexicons(*sources: dict[str, list[list[str]]]) -> dict[str, Lexicon]:
    """Each column's groups, from every source (generated in memory, read from a file), as a
    lexicon (word -> the other words of its groups)."""
    columns = sorted({column for groups in sources for column in groups})
    return {
        column: lexicon_from_groups([g for groups in sources for g in groups.get(column, [])]) for column in columns
    }


def load_variants(*dirs: str | Path) -> dict[str, list[list[str]]]:
    """The groups that name their ``column`` in the ``*.toml`` of ``dirs`` (a file ``xerscope
    lexicon build`` wrote and the company reviewed), per column; a bad file is skipped
    (``load_lexicon`` names it)."""
    found: dict[str, list[list[str]]] = {}
    for file in [f for d in dirs if Path(d).expanduser().is_dir() for f in sorted(Path(d).expanduser().glob("*.toml"))]:
        try:
            tables = tomllib.loads(file.read_text(encoding="utf-8")).get("group", [])
        except (OSError, tomllib.TOMLDecodeError):
            continue
        for table in tables:
            if isinstance(table, dict) and isinstance(table.get("column"), str):
                found.setdefault(table["column"], []).append([w for w in table.get("words", []) if isinstance(w, str)])
    return found


def load_refusals(*dirs: str | Path) -> tuple[list[tuple[str, frozenset[str]]], list[str]]:
    """The ``[[refuse]] column = ..., words = [...]`` tables of the ``*.toml`` of ``dirs`` (the
    hand-edited curated/ folder): words of one column never to read as one. Returns the refusals
    (folded words) and the tables that cannot apply (no column, fewer than two words), named."""
    refusals: list[tuple[str, frozenset[str]]] = []
    errors: list[str] = []
    for file in [f for d in dirs if Path(d).expanduser().is_dir() for f in sorted(Path(d).expanduser().glob("*.toml"))]:
        try:
            tables = tomllib.loads(file.read_text(encoding="utf-8")).get("refuse", [])
        except (OSError, tomllib.TOMLDecodeError):
            continue  # load_lexicon names it
        for number, table in enumerate(tables, start=1):
            words = frozenset(fold(w) for w in table.get("words", []) if isinstance(w, str) and fold(w))
            if not isinstance(table.get("column"), str) or len(words) < 2:
                errors.append(f"{file.name}: refuse #{number} needs a column and two words or more")
                continue
            refusals.append((table["column"], words))
    return refusals, errors


def refuse(
    groups: dict[str, list[list[str]]], refusals: list[tuple[str, frozenset[str]]]
) -> dict[str, list[list[str]]]:
    """The generated groups less those holding every word of a refusal of their column (dropped
    whole); a column left with no group is left out."""
    kept = {
        column: [
            g for g in column_groups if not any(c == column and words <= {fold(w) for w in g} for c, words in refusals)
        ]
        for column, column_groups in groups.items()
    }
    return {column: g for column, g in kept.items() if g}


def counts(groups: dict[str, list[list[str]]]) -> dict[str, int]:
    """Groups per column: what the Debug page shows (counts, never the words)."""
    return {column: len(g) for column, g in sorted(groups.items())}


def to_toml(groups: dict[str, list[list[str]]]) -> str:
    """The groups as a lexicon file (``[[group]] column = ..., words = [...]``), for review; the
    folder XERSCOPE_LEXICON names reads it as any lexicon file (the column is kept as a note)."""
    lines = ["# Variants generated from the files, one source column per group (xerscope lexicon build).", ""]
    for column, column_groups in sorted(groups.items()):
        for group in column_groups:
            lines += [
                "[[group]]",
                f"column = {json_quote(column)}",
                f"words = [{', '.join(map(json_quote, group))}]",
                "",
            ]
    return "\n".join(lines)
