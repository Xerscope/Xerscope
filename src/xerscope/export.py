"""Star-schema export for Power BI (or any BI tool).

    dim_snapshot (snapshot_idx)  1─*  fact_activity     (snapshot_idx, task_code)
                                 1─*  fact_relationship (snapshot_idx, pred_code, succ_code)
                                 1─*  fact_assignment   (snapshot_idx, taskrsrc_id; task_code)

Relate on snapshot_idx; use task_code to follow one activity across weeks (and to join
assignments to their activity).
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pandas as pd

from .config import DATETIME_FMT
from .store import SnapshotStore

Fmt = Literal["parquet", "csv"]


def export_tables(store: SnapshotStore) -> dict[str, pd.DataFrame]:
    return {
        "dim_snapshot": store.summary,
        "fact_activity": store.history,
        "fact_relationship": store.relationship_history,
        "fact_assignment": store.assignment_history,
    }


CSV_FLOAT_FORMAT = "%.4f"  # hours to the minute (0.0167 h): no float noise (12345.999999, a gap of 1e-13)


def csv_bytes(frame: pd.DataFrame, *, index: bool = False) -> bytes:
    """The one CSV writer of xerscope (app downloads, plain or anonymised, alone or zipped; Power BI
    tables; CLI files): UTF-8 with BOM (Excel), floats to 4 decimals, dates as P6 writes them."""
    return frame.to_csv(index=index, float_format=CSV_FLOAT_FORMAT, date_format=DATETIME_FMT).encode("utf-8-sig")


def _bytes(df: pd.DataFrame, fmt: Fmt) -> bytes:
    if fmt == "csv":
        return csv_bytes(df)
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def write_tables(store: SnapshotStore, out_dir: str | Path, fmt: Fmt = "parquet") -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, df in export_tables(store).items():
        p = out / f"{name}.{fmt}"
        p.write_bytes(_bytes(df, fmt))
        paths.append(p)
    return paths


def zip_tables(
    store: SnapshotStore, fmt: Fmt = "parquet", transform: Callable[[pd.DataFrame], pd.DataFrame] | None = None
) -> bytes:
    """The export tables in one zip; ``transform`` (e.g. ``Anonymizer.frame``) is applied to each."""
    tables = export_tables(store)
    return zip_frames({name: transform(df) if transform else df for name, df in tables.items()}, fmt)


def zip_frames(frames: dict[str, pd.DataFrame], fmt: Fmt = "csv") -> bytes:
    """One ``<name>.<fmt>`` file per frame, in one zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in frames.items():
            z.writestr(f"{name}.{fmt}", _bytes(df, fmt))
    return buf.getvalue()
