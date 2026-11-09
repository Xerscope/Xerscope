"""A company's trade words, read as one: "mécanique" for "Mechanical", "CVC" for "HVAC".

None ships with the package: the words live in the private folder XERSCOPE_LEXICON names,
outside the repository, as ``[[group]] words = [...]`` tables. That folder holds three:
``generated/`` (the files' variants, written by ``xerscope lexicon build`` only), ``curated/``
(edited by hand: trade words, refusals of generated groups) and ``suggested/`` (the words taught
in the app, appended there and read by nothing until copied into ``curated/``)."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from pathlib import Path

from .text import fold, plain

Lexicon = dict[str, tuple[str, ...]]  # folded word -> the other words of its group
GENERATED, CURATED, SUGGESTED = "generated", "curated", "suggested"  # the folders of XERSCOPE_LEXICON


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
            # a group naming its source column (generated.load_variants) holds within that column only
            groups += [list(table.get("words", [])) for table in data.get("group", []) if "column" not in table]
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


def write_private(path: Path, text: str) -> None:
    """Replace ``path`` whole: a temporary file of the same folder (0600, not *.toml, so no reader
    takes it for a lexicon), then a rename; a reader sees the old file or the new one."""
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def json_quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)
