"""Low-level XER reader: bytes -> {TABLE: DataFrame of strings}.

XER layout (P6 export, tab separated, usually CRLF):

    ERMHDR  <version>  <export date>  ...   header line
    %T      TABLE_NAME                       table start
    %F      col1  col2  ...                  field names
    %R      v1    v2    ...                  one row
    %E                                       end of file

Everything stays a string here. Typing and business rules live in model.py,
so this layer never has to change when the analysis does.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# P6 writes the Windows ANSI code page; newer exports may be UTF-8.
ENCODINGS = ("utf-8-sig", "cp1252")


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
    """The text of an XER file and the encoding that read it."""
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", errors="replace"), "cp1252 (lossy)"


def parse_text(text: str, source: str = "", encoding: str = "", keep: Mapping[str, Columns] | None = None) -> RawXer:
    """Every table of the file, or only the tables named in ``keep``, each with the listed
    columns (``None``: all of them). Rows of the other tables are not split."""
    rows: dict[str, list[list[str]]] = {}
    cols: dict[str, list[str]] = {}
    picked: dict[str, list[int]] = {}  # positions of the kept columns, for a projected table
    current: str | None = None
    skipping = False  # inside a table left out by ``keep``
    version = export_date = None
    header: list[str] = []
    saw_header = False
    orphans = 0  # %R rows outside any %T table

    # split("\n") rather than splitlines(): task names may contain characters
    # that splitlines() treats as line breaks (\x0b, \x1c,  ...).
    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        if not line or (skipping and line.startswith("%R\t")):
            continue
        parts = line.split("\t")
        tag = parts[0]
        if tag == "%R":
            if skipping:
                continue
            if current in picked:
                rows[current].append([parts[i + 1] if i + 1 < len(parts) else "" for i in picked[current]])
            elif current is not None:
                rows[current].append(parts[1:])
            else:
                orphans += 1
        elif tag == "%T":
            current = parts[1].strip() if len(parts) > 1 else None
            skipping = bool(current) and keep is not None and current not in keep
            if skipping:
                current = None
            elif current:
                rows.setdefault(current, [])
        elif tag == "%F":
            if current:
                names = [c.strip() for c in parts[1:]]
                wanted = keep.get(current) if keep is not None else None
                if wanted is None:
                    cols[current] = names
                else:
                    picked[current] = [i for i, name in enumerate(names) if name in wanted]
                    cols[current] = [names[i] for i in picked[current]]
        elif tag == "ERMHDR":
            saw_header = True
            header = parts[1:]
            version = parts[1] if len(parts) > 1 else None
            export_date = parts[2] if len(parts) > 2 else None
        elif tag == "%E":
            break

    if not saw_header and not rows:
        raise XerError(f"{source or 'input'}: not an XER file (no ERMHDR header, no tables)")

    tables: dict[str, pd.DataFrame] = {}
    warnings: list[str] = []
    if orphans:
        warnings.append(f"{orphans} %R row(s) before any %T table line; skipped")
    if "lossy" in encoding:
        warnings.append("neither UTF-8 nor Windows-1252: undecodable bytes replaced, names may be garbled")
    for name, table_rows in rows.items():
        names = cols.get(name)
        if not names:
            warnings.append(f"table {name} has rows but no %F field line; skipped")
            continue
        n = len(names)
        # Trailing empty fields are sometimes dropped by exporters: pad, never shift.
        # Extra non-empty fields mean a broken row (a tab inside a value): keep the
        # declared columns, but say so.
        long_rows = sum(1 for r in table_rows if len(r) > n and any(v.strip() for v in r[n:]))
        if long_rows:
            warnings.append(f"table {name}: {long_rows} row(s) with more fields than its %F line; extra fields dropped")
        fixed = [(r + [""] * n)[:n] for r in table_rows]
        tables[name] = pd.DataFrame(fixed, columns=names, dtype=object)

    return RawXer(tables, source, version, export_date, encoding, warnings, header)


def parse_bytes(data: bytes, source: str = "", keep: Mapping[str, Columns] | None = None) -> RawXer:
    text, encoding = decode_xer(data)
    return parse_text(text, source=source, encoding=encoding, keep=keep)


def read_xer(path: str | Path, keep: Mapping[str, Columns] | None = None) -> RawXer:
    path = Path(path)
    return parse_bytes(path.read_bytes(), source=path.name, keep=keep)
