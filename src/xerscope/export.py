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
from pathlib import Path
from typing import Literal

import pandas as pd

from .store import SnapshotStore

Fmt = Literal["parquet", "csv"]


def export_tables(store: SnapshotStore) -> dict[str, pd.DataFrame]:
    return {
        "dim_snapshot": store.summary,
        "fact_activity": store.history,
        "fact_relationship": store.relationship_history,
        "fact_assignment": store.assignment_history,
    }


def _bytes(df: pd.DataFrame, fmt: Fmt) -> bytes:
    buf = io.BytesIO()
    if fmt == "parquet":
        df.to_parquet(buf, index=False)
    else:
        df.to_csv(buf, index=False, date_format="%Y-%m-%d %H:%M", encoding="utf-8-sig")
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


def zip_tables(store: SnapshotStore, fmt: Fmt = "parquet") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in export_tables(store).items():
            z.writestr(f"{name}.{fmt}", _bytes(df, fmt))
    return buf.getvalue()
