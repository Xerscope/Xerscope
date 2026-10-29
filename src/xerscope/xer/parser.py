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

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# P6 writes the Windows ANSI code page; newer exports may be UTF-8.
ENCODINGS = ("utf-8-sig", "cp1252")


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

    def table(self, name: str) -> pd.DataFrame:
        """Return a table, or an empty frame if the export does not contain it."""
        return self.tables.get(name, pd.DataFrame())


def decode(data: bytes) -> tuple[str, str]:
    for enc in ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", errors="replace"), "cp1252 (lossy)"


def parse_text(text: str, source: str = "", encoding: str = "") -> RawXer:
    rows: dict[str, list[list[str]]] = {}
    cols: dict[str, list[str]] = {}
    current: str | None = None
    version = export_date = None
    saw_header = False

    # split("\n") rather than splitlines(): task names may contain characters
    # that splitlines() treats as line breaks (\x0b, \x1c,  ...).
    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        if not line:
            continue
        parts = line.split("\t")
        tag = parts[0]
        if tag == "%R":
            if current is not None:
                rows[current].append(parts[1:])
        elif tag == "%T":
            current = parts[1].strip() if len(parts) > 1 else None
            if current:
                rows.setdefault(current, [])
        elif tag == "%F":
            if current:
                cols[current] = [c.strip() for c in parts[1:]]
        elif tag == "ERMHDR":
            saw_header = True
            version = parts[1] if len(parts) > 1 else None
            export_date = parts[2] if len(parts) > 2 else None
        elif tag == "%E":
            break

    if not saw_header and not rows:
        raise XerError(f"{source or 'input'}: not an XER file (no ERMHDR header, no tables)")

    tables: dict[str, pd.DataFrame] = {}
    warnings: list[str] = []
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

    return RawXer(tables, source, version, export_date, encoding, warnings)


def parse_bytes(data: bytes, source: str = "") -> RawXer:
    text, enc = decode(data)
    return parse_text(text, source=source, encoding=enc)


def read_xer(path: str | Path) -> RawXer:
    path = Path(path)
    return parse_bytes(path.read_bytes(), source=path.name)
