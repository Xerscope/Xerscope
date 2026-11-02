from __future__ import annotations

from pathlib import Path

from .model import HARD_CONSTRAINTS, Snapshot, build_snapshot, percent_complete
from .parser import RawXer, XerError, parse_bytes, parse_text, read_xer

XER_SUFFIXES = (".xer",)  # compared case-insensitively: P6 writes .XER on some setups


def _is_xer(path: str | Path) -> bool:
    return Path(path).suffix.lower() in XER_SUFFIXES


def load_snapshot(source: str | Path | bytes, project_code=None, name: str | None = None) -> Snapshot:
    """Parse an XER file (a path, or its bytes plus the file ``name``) and build the snapshot."""
    if isinstance(source, bytes) and not name:
        # The name becomes Snapshot.source, which keys caches and orders the series.
        raise ValueError("load_snapshot(bytes) needs the file name")
    raw = parse_bytes(source, source=name) if isinstance(source, bytes) else read_xer(source)
    return build_snapshot(raw, project_code=project_code)


def xer_files(folder: str | Path) -> list[Path]:
    """The .xer files of a folder, sorted by name."""
    return sorted(p for p in Path(folder).iterdir() if p.is_file() and _is_xer(p))


__all__ = [
    "XER_SUFFIXES",
    "HARD_CONSTRAINTS",
    "RawXer",
    "Snapshot",
    "XerError",
    "build_snapshot",
    "load_snapshot",
    "parse_bytes",
    "parse_text",
    "percent_complete",
    "read_xer",
    "xer_files",
]
