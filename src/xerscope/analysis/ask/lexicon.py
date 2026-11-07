"""A company's trade words, read as one: "mécanique" for "Mechanical", "CVC" for "HVAC".

None ships with the package: the words live in the private folder XERSCOPE_LEXICON names,
outside the repository, as ``[[group]] words = [...]`` tables."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from .text import fold, plain

Lexicon = dict[str, tuple[str, ...]]  # folded word -> the other words of its group


def lexicon_from_groups(groups: list[list[str]]) -> Lexicon:
    """Groups of words read as one (each word folded; a group of fewer than two is dropped)."""
    lexicon: dict[str, list[str]] = {}
    for group in groups:
        words = [fold(w) for w in group if isinstance(w, str) and fold(w)]
        if len(words) < 2:
            continue
        for word in words:
            lexicon.setdefault(word, []).extend(w for w in words if w != word)
    return {word: tuple(dict.fromkeys(others)) for word, others in lexicon.items()}


def load_lexicon(*dirs: str | Path) -> tuple[Lexicon, list[str]]:
    """Every ``*.toml`` of ``dirs`` (the folder XERSCOPE_LEXICON names). Returns the lexicon and
    the load errors (a bad file is skipped and named, never fatal)."""
    groups: list[list[str]] = []
    errors: list[str] = []
    files = [f for d in dirs if Path(d).expanduser().is_dir() for f in sorted(Path(d).expanduser().glob("*.toml"))]
    for file in files:
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
            groups += [list(table.get("words", [])) for table in data.get("group", [])]
        except (OSError, tomllib.TOMLDecodeError, AttributeError, TypeError) as exc:
            errors.append(f"{file.name}: {exc}")
    return lexicon_from_groups(groups), errors


def learn(lexicon: Lexicon, word: str, label: str) -> Lexicon:
    """The lexicon with ``word`` read as ``label`` (a WBS label "CODE · name", or a resource name):
    one group of the word, the code and the name, so the grammar's node candidates reach it."""
    code, _, name = label.partition(" · ")
    group = [w for w in dict.fromkeys(plain(t) for t in (word, code, name)) if w]
    merged = {k: list(v) for k, v in lexicon.items()}
    for member in group:
        merged.setdefault(member, []).extend(w for w in group if w != member and w not in merged.get(member, []))
    return {k: tuple(dict.fromkeys(v)) for k, v in merged.items()}


def learned_toml(pairs: list[tuple[str, str]]) -> str:
    """The words taught this session as a lexicon file (``[[group]] words = [...]``), to put in the
    folder XERSCOPE_LEXICON names so every session reads them."""
    lines = ["# Words taught in the Gantt Ask field: each read as the label it was matched to.", ""]
    for word, label in pairs:
        code, _, name = label.partition(" · ")
        words = list(dict.fromkeys(t for t in (word, code, name) if t))
        lines += ["[[group]]", "words = [" + ", ".join(json_quote(w) for w in words) + "]", ""]
    return "\n".join(lines)


def json_quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)
