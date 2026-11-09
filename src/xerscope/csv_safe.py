"""CSV cells a spreadsheet would run as a formula (CWE-1236), neutralised before any CSV leaves.

Every CSV xerscope writes goes through :func:`csv_safe`: the Power BI tables (``export.py``),
``check --out`` / ``--flagged`` and the other CLI CSVs (``cli._write_csv``), the page downloads
(``app/state.py``, ``app/views/health.py``) and the anonymised tables (``anonymize.py``). The
text in those cells comes from the XER file, and a crafted file must not run in the reader's
spreadsheet. The Power BI CSVs are covered too: Power BI itself does not evaluate formulas, but
the same files are opened in Excel. A reader that wants the raw text strips the apostrophe
(Excel: Data > Text to Columns, or read the Parquet export, which is untouched).
"""

from __future__ import annotations

import pandas as pd

# OWASP CSV injection guidance: a text cell starting with one of these is read as a formula by
# Excel and LibreOffice; a leading apostrophe makes the cell text.
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(frame: pd.DataFrame) -> pd.DataFrame:
    """The frame with ``'`` prefixed to every ``str`` cell starting with ``= + - @``, a tab or a
    carriage return. Only text cells change: numeric and date columns keep their values and dtype,
    and a negative number stays a number."""
    out = frame.copy()
    for column in out.columns:
        values = out[column]
        if values.dtype != object and values.dtype != "string":
            continue
        hit = values.map(lambda value: isinstance(value, str) and value.startswith(FORMULA_STARTS)).astype(bool)
        if hit.any():
            out[column] = values.where(~hit, "'" + values.astype(str))
    return out
