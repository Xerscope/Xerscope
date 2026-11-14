"""The files' own variants: words of one source column read as one ("Fondation" / "Fondations",
"Mec." / "Mechanical"), generated from every loaded file, in memory.

A. Every term keeps its source column (``COLUMNS``, XER table.field). A group never crosses a
   column, so a common word of an activity name never joins a WBS name.
B. Written rules only, no clustering:
   - folding: case and accents ("Béton" / "beton" are one word);
   - plural, French or English: w / w+s, w / w+es, -al / -aux;
   - an abbreviation written with its dot ("Mec.", "Elec.", 3+ letters) and the one longer
     word of the column it begins.
C. Two words of 6+ letters with the same first letter, one letter added, removed or changed
   ("Instalation" / "Installation"), are never grouped: on public XER files the rule joined
   different words ("screed" / "screen", "coarse" / "course", "lighting" / "lightning") and no
   frequency told them from a typo ("gybsum" / "gypsum"). ``near_spellings`` lists them;
   ``xerscope lexicon build`` writes them to generated/report.txt for review, and the maintainer
   copies the true typos into curated/. Neither the app nor the Ask field reads that list.
Pure and deterministic: the same files give the same groups, sorted. ``xerscope lexicon build``
writes them to generated/variants.toml; the app derives them per session and never writes them."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from pathlib import Path

from ...xer import Snapshot
from .lexicon import Lexicon, json_quote, lexicon_from_groups, tables, words_of
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
Terms = dict[str, tuple[set[str], set[str]]]  # column: (words, abbreviated)


def terms(snapshots: Iterable[Snapshot]) -> Terms:
    """Per column: its folded words (letters only, 3+), and those written as an abbreviation."""
    found: Terms = {}
    for snapshot in snapshots:
        add_terms(found, snapshot)
    return found


def add_terms(found: Terms, snapshot: Snapshot) -> None:
    """Adds one file's terms to ``found``: ``xerscope lexicon build`` reads one export at a time
    and keeps its words only, never the snapshot."""
    for column, values in _column_values(snapshot).items():
        words, abbreviated = found.setdefault(column, (set(), set()))
        for value in values:
            text = fold(value)
            words.update(w for w in re.findall(r"[a-z]+", text) if len(w) >= 3)
            abbreviated.update(w for w in re.findall(r"([a-z]+)\.", text) if len(w) >= MIN_ABBREVIATION)


def variants(snapshots: Iterable[Snapshot]) -> dict[str, list[list[str]]]:
    """Per grouped column, its groups of variants (each sorted, the groups sorted); a column
    with no group is left out."""
    return variants_from(terms(snapshots))


def variants_from(found: Terms) -> dict[str, list[list[str]]]:
    """``variants`` of the files whose terms are ``found``."""
    groups = {column: group_words(*found[column]) for column in GROUPED if column in found}
    return {column: g for column, g in groups.items() if g}


def near_spellings(snapshots: Iterable[Snapshot]) -> dict[str, list[tuple[str, str]]]:
    """Per grouped column, its pairs one letter apart (rule C) that its groups do not already
    join (a plural is one letter apart too), sorted; a column with no pair is left out."""
    return near_spellings_from(terms(snapshots))


def near_spellings_from(found: Terms) -> dict[str, list[tuple[str, str]]]:
    """``near_spellings`` of the files whose terms are ``found``."""
    pairs: dict[str, list[tuple[str, str]]] = {}
    for column in GROUPED:
        if column in found:
            groups = [set(g) for g in group_words(*found[column])]
            near = [(a, b) for a, b in _near_spellings(found[column][0]) if not any({a, b} <= g for g in groups)]
            if near:
                pairs[column] = sorted(near)
    return pairs


def group_words(words: set[str], abbreviated: AbstractSet[str] = frozenset()) -> list[list[str]]:
    """The words of one column joined by the rules B of the module docstring."""
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


def _pairs(words: set[str], abbreviated: AbstractSet[str]) -> list[tuple[str, str]]:
    pairs = [(w, p) for w in words for p in _plurals(w) if p in words]
    for short in abbreviated & words:
        longer = [w for w in words if w != short and w.startswith(short)]
        if len(longer) == 1:  # the one word of the column it can stand for
            pairs.append((short, longer[0]))
    return pairs


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
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # TOMLDecodeError, UnicodeDecodeError
            continue
        for table in tables(data, "group"):
            if (words := words_of(table)) is not None and isinstance(table.get("column"), str):
                found.setdefault(table["column"], []).append([w for w in words if isinstance(w, str)])
    return found


def load_refusals(*dirs: str | Path) -> tuple[list[tuple[str, frozenset[str]]], list[str]]:
    """The ``[[refuse]] column = ..., words = [...]`` tables of the ``*.toml`` of ``dirs`` (the
    hand-edited curated/ folder): words of one column never to read as one. Returns the refusals
    (folded words) and the tables that cannot apply (no column, fewer than two words), named."""
    refusals: list[tuple[str, frozenset[str]]] = []
    errors: list[str] = []
    for file in [f for d in dirs if Path(d).expanduser().is_dir() for f in sorted(Path(d).expanduser().glob("*.toml"))]:
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # TOMLDecodeError, UnicodeDecodeError: load_lexicon names it
            continue
        for number, table in enumerate(tables(data, "refuse"), start=1):
            words = frozenset(fold(w) for w in words_of(table) or [] if isinstance(w, str) and fold(w))
            if len(words) < 2 or not isinstance(table.get("column"), str):
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
