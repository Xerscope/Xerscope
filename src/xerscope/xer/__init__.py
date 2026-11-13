from __future__ import annotations

from pathlib import Path

from .model import (
    HARD_CONSTRAINTS,
    HEADER_TABLES,
    FileHeader,
    Snapshot,
    baseline_copies,
    build_snapshot,
    percent_complete,
    read_header,
)
from .parser import RawXer, XerError, parse_bytes, parse_text, read_xer
from .pmxml import is_pmxml, list_baselines, read_pmxml_baseline

XER_SUFFIXES = (".xer",)  # compared case-insensitively: P6 writes .XER on some setups


def _is_xer(path: str | Path) -> bool:
    return Path(path).suffix.lower() in XER_SUFFIXES


def load_snapshot(
    source: str | Path | bytes, project_code=None, name: str | None = None, project_id: str | None = None
) -> Snapshot:
    """Parse an XER file (a path, or its bytes plus the file ``name``) and build the snapshot.

    A P6 XML export is read for one of its baselines (``pmxml``): ``project_id`` then names the
    baseline (an update's PROJECT.sum_base_proj_id), else the file's Project Baseline is read."""
    if isinstance(source, bytes):
        if not name:
            # The name becomes Snapshot.source, which keys caches and orders the series.
            raise ValueError("load_snapshot(bytes) needs the file name")
        data, source_name = source, name
    else:
        data, source_name = Path(source).read_bytes(), Path(source).name
    if is_pmxml(data):
        raw = read_pmxml_baseline(data, source_name, project_id)
        return build_snapshot(raw, project_code=project_code)
    raw = parse_bytes(data, source=source_name)
    return build_snapshot(raw, project_code=project_code, project_id=project_id)


def load_header(path: str | Path) -> FileHeader:
    """Default project and data date of an XER file, without building the snapshot: only the
    PROJECT rows and the TASK identity columns are kept while reading."""
    return read_header(read_xer(path, keep=HEADER_TABLES))


def xer_files(folder: str | Path) -> list[Path]:
    """The .xer files of a folder, sorted by name."""
    return sorted(p for p in Path(folder).iterdir() if p.is_file() and _is_xer(p))


__all__ = [
    "is_pmxml",
    "list_baselines",
    "XER_SUFFIXES",
    "HARD_CONSTRAINTS",
    "FileHeader",
    "RawXer",
    "Snapshot",
    "XerError",
    "baseline_copies",
    "build_snapshot",
    "load_header",
    "load_snapshot",
    "parse_bytes",
    "parse_text",
    "percent_complete",
    "read_xer",
    "xer_files",
]
