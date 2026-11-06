"""Low-level XER reader: bytes -> {TABLE: DataFrame of strings}.

XER layout (P6 export, tab separated, usually CRLF):

    ERMHDR  <version>  <export date>  ...   header line
    %T      TABLE_NAME                       table start
    %F      col1  col2  ...                  field names
    %R      v1    v2    ...                  one row
    %E                                       end of file

Everything stays a string here. Typing and business rules live in model.py,
so this layer never has to change when the analysis does.

The text is read line by line, in one pass, as a state machine on the line tag: the file is
never split into a list of lines, each row goes straight into its table's cell array (padded
or cut to the %F width as it is appended) and a table's DataFrame is built as soon as its
block ends. Equal cell values of one table share one string object, so the many repeated
codes, ids and dates of an export cost their text once. Peak memory stays a small multiple
of the file size (tests/test_audit_edges_xer.py measures it).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# P6 writes the Windows ANSI code page; newer exports may be UTF-8.
ENCODINGS = ("utf-8-sig", "cp1252")
# Byte order marks of the wide encodings: P6 never writes them, an editor may (longest first).
WIDE_BOMS = (
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)
INTERNED_PER_TABLE = 1 << 16  # distinct cell values shared per table before interning stops adding


Columns = Collection[str] | None  # columns to keep from a table, None for all


class XerError(ValueError):
    """Raised when a file is not a usable XER export."""


@dataclass
class RawXer:
    tables: dict[str, pd.DataFrame]
    source: str = ""
    version: str | None = None
    export_date: str | None = None
    encoding: str = ""
    warnings: list[str] = field(default_factory=list)
    header: list[str] = field(default_factory=list)  # ERMHDR fields after the tag

    def table(self, name: str) -> pd.DataFrame:
        """Return a table, or an empty frame if the export does not contain it."""
        return self.tables.get(name, pd.DataFrame())


def decode_xer(data: bytes) -> tuple[str, str]:
    """The text of an XER file and the encoding that read it.

    A UTF-16 or UTF-32 byte order mark is honoured (``XerError`` names the encoding when the
    bytes do not decode as it); otherwise UTF-8, then cp1252, which decodes any byte sequence.
    """
    for bom, encoding in WIDE_BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError as exc:
                raise XerError(
                    f"file starts with a {encoding.upper()} byte order mark but does not decode as it"
                ) from exc
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", errors="replace"), "cp1252 (lossy)"


def _unique_names(names: list[str], notes: list[str], table: str) -> list[str]:
    """``names`` with a repeated name suffixed ``.1``, ``.2``... (the first keeps its name), noted."""
    seen: dict[str, int] = {}
    out = []
    for name in names:
        n = seen.get(name, 0)
        seen[name] = n + 1
        out.append(name if n == 0 else f"{name}.{n}")
    duplicates = [name for name, n in seen.items() if n > 1]
    if duplicates:
        notes.append(f"table {table}: duplicate column(s) {duplicates[:5]} renamed with a .1, .2 suffix")
    return out


class _Rows:
    """The rows of one table block in a 2-D cell array, padded with "" to the table's width.

    ``capacity`` is the count of %R lines ahead in the block (an upper bound, counted on the
    text), so the array is allocated once; it doubles if the count was short.
    """

    def __init__(self, width: int, capacity: int):
        self.width = width
        self.count = 0
        self.cells = self._blank(max(capacity, 1))

    def _blank(self, rows: int) -> np.ndarray:
        cells = np.empty((rows, self.width), dtype=object)
        cells.fill("")
        return cells

    def add(self, values: list[str]) -> None:
        if self.count == len(self.cells):
            bigger = self._blank(2 * len(self.cells))
            bigger[: self.count] = self.cells
            self.cells = bigger
        if values:
            self.cells[self.count, : len(values)] = values
        self.count += 1

    def frame(self, names: list[str]) -> pd.DataFrame:
        return pd.DataFrame(self.cells[: self.count], columns=names, dtype=object, copy=False)


class _Table:
    """One %T table while the file is read: its columns, the block being read, the blocks done."""

    def __init__(self, name: str, wanted: Columns):
        self.name = name
        self.wanted = wanted  # columns to keep (keep=), None for all
        self.names: list[str] | None = None  # the table's columns (the kept ones), from its first %F line
        self.declared: list[str] | None = None  # every column of that %F line
        self.picked: list[int] | None = None  # positions in a %R line of the kept columns
        self.rows: _Rows | None = None  # the block being read
        self.frames: list[pd.DataFrame] = []  # the blocks read before it
        self.seen: dict[str, str] = {}  # one object per distinct cell value
        self.notes: list[str] = []
        self.long_rows = 0  # rows with non-blank fields beyond the %F width
        self.unlabelled = 0  # rows read before the table's %F line
        self.ignoring = False  # rows under a %F line that contradicts the table's columns

    def fields(self, names: list[str], capacity: int) -> None:
        """A %F line: the table's columns when it has none yet, else it must repeat them."""
        names = _unique_names([name.strip() for name in names], self.notes, self.name)
        if self.declared is None:
            self.declared = names
            if self.wanted is None:
                self.picked, self.names = None, names
            else:
                self.picked = [i + 1 for i, name in enumerate(names) if name in self.wanted]
                self.names = [names[i - 1] for i in self.picked]
            self.open(capacity)
        elif names != self.declared:
            self.ignoring = True
            self.notes.append(
                f"table {self.name}: a %F line with other columns than its first one; the rows under it are ignored"
            )

    def open(self, capacity: int) -> None:
        """Start a block: the rows read so far go to ``frames``."""
        self.close()
        self.ignoring = False
        if self.names is not None:
            self.rows = _Rows(len(self.names), capacity)

    def close(self) -> None:
        """End the block being read: its frame joins ``frames`` (an empty block only as the first)."""
        if self.rows is not None:
            if self.rows.count or not self.frames:
                self.frames.append(self.rows.frame(self.names or []))
            self.rows = None

    def add(self, parts: list[str]) -> None:
        """A %R line, split on tabs (``parts[0]`` is the tag)."""
        if self.ignoring:
            return
        if self.rows is None:
            self.unlabelled += 1
            return
        if self.picked is None:
            values = parts[1:]
            width = self.rows.width
            if len(values) > width:
                if any(v.strip() for v in values[width:]):
                    self.long_rows += 1
                values = values[:width]
        else:
            values = [parts[i] if i < len(parts) else "" for i in self.picked]
        seen = self.seen
        intern = seen.setdefault if len(seen) < INTERNED_PER_TABLE else seen.get
        self.rows.add([intern(v, v) for v in values])

    def finish(self, warnings: list[str]) -> pd.DataFrame | None:
        """The table's frame, or None (and a warning) when it never had a usable %F line."""
        self.close()
        self.seen = {}
        if not self.names:
            warnings.append(f"table {self.name} has rows but no %F field line; skipped")
            return None
        warnings.extend(self.notes)
        if self.unlabelled:
            warnings.append(f"table {self.name}: {self.unlabelled} row(s) before its %F line; skipped")
        if self.long_rows:
            # Trailing empty fields are sometimes dropped by exporters: pad, never shift.
            # Extra non-empty fields mean a broken row (a tab inside a value): keep the
            # declared columns, but say so.
            warnings.append(
                f"table {self.name}: {self.long_rows} row(s) with more fields than its %F line; extra fields dropped"
            )
        if len(self.frames) == 1:
            return self.frames[0]
        return pd.concat(self.frames, ignore_index=True)


class _Reader:
    """The state machine over the lines of one file: current table, skipped table, header."""

    def __init__(self, text: str, keep: Mapping[str, Columns] | None):
        self.text = text
        self.keep = keep
        self.tables: dict[str, _Table] = {}  # in order of first appearance
        self.current: _Table | None = None
        self.skipping = False  # inside a table left out by ``keep``
        self.header: list[str] | None = None
        self.orphans = 0  # %R rows outside any named %T table

    def run(self) -> None:
        text, n = self.text, len(self.text)
        pos = 0
        # split on "\n" only: task names may contain characters that splitlines() treats
        # as line breaks (\x0b, \x1c, ...), and calendar blobs contain lone "\r".
        while pos < n:
            end = text.find("\n", pos)
            if end < 0:
                end = n
            line = text[pos:end].rstrip("\r")
            pos = end + 1
            if not line:
                continue
            if line.startswith("%R"):
                if self.skipping:
                    continue
                parts = line.split("\t")
                if parts[0] == "%R":
                    self.row(parts)
            elif line.startswith("%T"):
                parts = line.split("\t")
                if parts[0] == "%T":
                    self.table(parts, pos)
            elif line.startswith("%F"):
                parts = line.split("\t")
                if parts[0] == "%F" and self.current is not None:
                    self.current.fields(parts[1:], self.rows_ahead(pos))
            elif line.startswith("ERMHDR"):
                parts = line.split("\t")
                if parts[0] == "ERMHDR":
                    self.header = parts[1:]
            elif line == "%E":
                break

    def row(self, parts: list[str]) -> None:
        if self.current is None:
            self.orphans += 1
        else:
            self.current.add(parts)

    def table(self, parts: list[str], pos: int) -> None:
        name = parts[1].strip() if len(parts) > 1 else None
        self.skipping = bool(name) and self.keep is not None and name not in self.keep
        if self.skipping or not name:
            self.current = None
            return
        table = self.tables.get(name)
        if table is None:
            table = self.tables[name] = _Table(name, self.keep.get(name) if self.keep is not None else None)
        else:
            table.open(self.rows_ahead(pos))  # a table in two blocks: same columns, more rows
        self.current = table

    def rows_ahead(self, pos: int) -> int:
        """Upper bound of the %R lines between ``pos`` and the next %T line (sizes a block's array)."""
        stop = self.text.find("\n%T", pos)
        return self.text.count("\n%R", pos - 1, len(self.text) if stop < 0 else stop)

    def result(self, source: str, encoding: str) -> RawXer:
        if self.header is None and not self.tables:
            raise XerError(f"{source or 'input'}: not an XER file (no ERMHDR header, no tables)")
        warnings: list[str] = []
        if self.orphans:
            warnings.append(f"{self.orphans} %R row(s) outside any named %T table; skipped")
        if "lossy" in encoding:
            warnings.append("neither UTF-8 nor Windows-1252: undecodable bytes replaced, names may be garbled")
        tables: dict[str, pd.DataFrame] = {}
        for name, table in self.tables.items():
            frame = table.finish(warnings)
            if frame is not None:
                tables[name] = frame
        header = self.header or []
        version = header[0] if len(header) > 0 else None
        export_date = header[1] if len(header) > 1 else None
        return RawXer(tables, source, version, export_date, encoding, warnings, header)


def parse_text(text: str, source: str = "", encoding: str = "", keep: Mapping[str, Columns] | None = None) -> RawXer:
    """Every table of the file, or only the tables named in ``keep``, each with the listed
    columns (``None``: all of them). Rows of the other tables are not split."""
    reader = _Reader(text, keep)
    reader.run()
    return reader.result(source, encoding)


def parse_bytes(data: bytes, source: str = "", keep: Mapping[str, Columns] | None = None) -> RawXer:
    text, encoding = decode_xer(data)
    return parse_text(text, source=source, encoding=encoding, keep=keep)


def read_xer(path: str | Path, keep: Mapping[str, Columns] | None = None) -> RawXer:
    path = Path(path)
    return parse_bytes(path.read_bytes(), source=path.name, keep=keep)
