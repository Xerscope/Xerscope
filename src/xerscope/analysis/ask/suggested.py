"""The corrections made in the Gantt Ask field, kept for review in the folder ``suggested/`` of
XERSCOPE_LEXICON: one ``[[suggestion]]`` per click on a suggested label, holding the unknown word,
the label picked, the label's source column, the filter it gives (facet, value) and the date,
never the sentence asked. The app appends; nothing reads them for the Ask field until the
maintainer copies a word into ``curated/``; ``xerscope lexicon build`` (the init service) purges
a suggestion not copied after RETENTION.

The folder is written from a web page, hence the guards: the file name is fixed; word and label
are NFKC-normalised, bounded (MAX_WORD, MAX_LABEL) and made of letters, digits and PUNCTUATION
only, refused otherwise (no control character, newline, bracket, quote, backslash or '='); each
value goes through ``json_quote``; an exclusive ``flock`` serialises the size check and the
append; the file stops at MAX_BYTES; it is created 0600 and never opened through a symlink;
nothing is printed or logged. ``flock`` is POSIX: on Windows nothing is recorded."""

from __future__ import annotations

import os
import tomllib
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from .lexicon import Lexicon, json_quote, write_private
from .text import fold

FILE = "suggestions.toml"
MAX_WORD = 64  # characters of the unknown word
MAX_LABEL = 160  # characters of the label picked (a WBS "CODE · name", a resource)
MAX_BYTES = 256 * 1024  # about a thousand suggestions; past it a click records nothing
RETENTION = timedelta(days=90)  # a suggestion not copied into curated/ is purged after this
PUNCTUATION = frozenset(" .-_'&/()·,:+#")  # what a WBS or resource label may hold besides letters and digits
# the kind of label suggestions() offers -> the column it comes from, the facet it filters
SOURCES = {"wbs": ("PROJWBS.wbs_name", "wbs"), "resource": ("RSRC.rsrc_short_name", "resource")}


def clean(text: str, limit: int) -> str | None:
    """``text`` NFKC-normalised and stripped, or None when empty, longer than ``limit`` or holding
    a character outside letters, digits and PUNCTUATION."""
    text = unicodedata.normalize("NFKC", text).strip()
    allowed = all(unicodedata.category(c)[0] in "LN" or c in PUNCTUATION for c in text)
    return text if 0 < len(text) <= limit and allowed else None


def entry(word: str, label: str, kind: str, at: datetime) -> str:
    """One ``[[suggestion]]`` table; word and label already cleaned, ``at`` in UTC."""
    column, facet = SOURCES[kind]
    value = label.partition(" · ")[0] if kind == "wbs" else label
    fields = {"word": word, "label": label, "column": column, "facet": facet, "value": value}
    lines = ["[[suggestion]]", *(f"{key} = {json_quote(text)}" for key, text in fields.items())]
    return "\n".join([*lines, f"at = {at:%Y-%m-%dT%H:%M:%SZ}", "", ""])


def record(folder: str | Path, word: str, label: str, kind: str, at: datetime) -> bool:
    """Append one correction to ``folder``/FILE; False, and nothing written, when a guard refuses."""
    try:
        import fcntl
    except ImportError:
        return False
    word, label = clean(word, MAX_WORD), clean(label, MAX_LABEL)
    if word is None or label is None or kind not in SOURCES or not Path(folder).is_dir():
        return False
    text = entry(word, label, kind, at).encode()
    try:
        fd = _locked(Path(folder) / FILE, fcntl)
    except OSError:  # a symlink in place of the file (ELOOP), a folder not writable
        return False
    with os.fdopen(fd, "ab") as file:
        if os.fstat(fd).st_size + len(text) > MAX_BYTES:
            return False
        file.write(text)
    return True


def _locked(path: Path, fcntl) -> int:
    """``path`` opened for appending under an exclusive lock, on the file the path names once
    locked (a purge replaces it: a writer that waited on the old one opens the new one)."""
    while True:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        if os.fstat(fd).st_ino == os.stat(path, follow_symlinks=False).st_ino:
            return fd
        os.close(fd)


def purge(folder: str | Path, curated: Lexicon, now: datetime) -> tuple[int, int]:
    """Drop the suggestions older than RETENTION whose word ``curated`` does not hold; the file is
    replaced whole under the lock. Returns (kept, purged); (0, 0) without a file or on Windows.
    A file that is not TOML raises ``tomllib.TOMLDecodeError`` and is left as it is."""
    path = Path(folder) / FILE
    try:
        import fcntl

        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except (ImportError, FileNotFoundError):
        return 0, 0
    with os.fdopen(fd, "rb") as file:
        fcntl.flock(fd, fcntl.LOCK_EX)
        entries = tomllib.loads(file.read().decode("utf-8")).get("suggestion", [])
        kept = [text for text in (_rewritten(e) for e in entries if not _expired(e, curated, now)) if text]
        if len(kept) < len(entries):
            write_private(path, "".join(kept))
    return len(kept), len(entries) - len(kept)


def _expired(suggestion: dict, curated: Lexicon, now: datetime) -> bool:
    at, word = suggestion.get("at"), suggestion.get("word")
    old = isinstance(at, datetime) and at.tzinfo is not None and now - at >= RETENTION
    return old and not (isinstance(word, str) and fold(word) in curated)


def _rewritten(suggestion: dict) -> str:
    """A table read back, written again as ``entry`` wrote it; "" (purged) when a value edited by
    hand fails the guards."""
    word, label = clean(str(suggestion.get("word", "")), MAX_WORD), clean(str(suggestion.get("label", "")), MAX_LABEL)
    kind, at = suggestion.get("facet"), suggestion.get("at")
    if word is None or label is None or kind not in SOURCES or not isinstance(at, datetime):
        return ""
    return entry(word, label, kind, at)
