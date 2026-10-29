from __future__ import annotations

from pathlib import Path

from .model import HARD_CONSTRAINTS, Snapshot, build_snapshot, percent_complete
from .parser import RawXer, XerError, parse_bytes, parse_text, read_xer


def load_snapshot(path, project_code=None) -> Snapshot:
    """Parse an XER file and build the typed snapshot in one call."""
    return build_snapshot(read_xer(path), project_code=project_code)


def xer_files(folder: str | Path) -> list[Path]:
    """The .xer files of a folder, sorted by name; P6 writes .XER on some setups."""
    return sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() == ".xer")


__all__ = [
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
