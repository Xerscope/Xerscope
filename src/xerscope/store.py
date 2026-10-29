"""A time-ordered series of weekly snapshots of the same project.

Everything the trend analysis needs is exposed as long-format ("tidy") frames keyed by
(snapshot_idx, task_code). Long format is what pandas, Plotly and Power BI all consume
directly, and it makes "compare week N with week N-1" a groupby + diff.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from functools import cached_property
from pathlib import Path

import pandas as pd

from .xer import Snapshot, load_snapshot
from .xer.model import LABOR_COLS

HISTORY_COLS = [
    "task_code",
    "task_name",
    "wbs_code",
    "wbs_l1",
    "wbs_sort",
    "task_type",
    "type",
    "status",
    "clndr_id",
    "start",
    "finish",
    "early_start_date",
    "early_end_date",
    "late_start_date",
    "late_end_date",
    "act_start_date",
    "act_end_date",
    "target_start_date",
    "target_end_date",
    "total_float_d",
    "free_float_d",
    "remaining_d",
    "original_d",
    "pct_complete",
    "complete_pct_type",
    "is_complete",
    "is_started",
    "is_milestone",
    "is_start_milestone",
    "is_loe",
    "is_critical",
    "on_longest_path",
    "cstr_type",
    "has_hard_constraint",
    *LABOR_COLS,
    "ev_compute_type",
]
REL_COLS = ["pred_code", "succ_code", "type", "lag_hr", "lag_d", "is_external"]
ASSIGNMENT_COLS = [
    "taskrsrc_id",
    "task_code",
    "rsrc_id",
    "rsrc_short_name",
    "rsrc_name",
    "rsrc_type",
    "driving",
    "target_qty",
    "act_qty",
    "remain_qty",
    "restart_date",
    "reend_date",
    "act_start_date",
    "act_end_date",
]


def _sort_key(s: Snapshot):
    return (s.data_date if s.data_date is not None else pd.Timestamp.max, s.source)


class SnapshotStore:
    def __init__(self, snapshots: Iterable[Snapshot]):
        self._snaps: list[Snapshot] = sorted(snapshots, key=_sort_key)
        self.warnings: list[str] = [w for s in self._snaps for w in s.warnings]
        codes = {s.project_code for s in self._snaps}
        if len(codes) > 1:
            self.warnings.append(f"snapshots mix several projects: {sorted(codes)}")
        dates = pd.Series([s.data_date for s in self._snaps])
        if dates.duplicated().any():
            self.warnings.append("several snapshots share the same data date")

    # --- construction ----------------------------------------------------------
    @classmethod
    def from_paths(cls, paths: Iterable[str | Path], project_code: str | None = None) -> SnapshotStore:
        return cls(load_snapshot(p, project_code) for p in paths)

    @classmethod
    def from_folder(cls, folder: str | Path, pattern: str = "*.xer", project_code: str | None = None) -> SnapshotStore:
        paths = sorted(Path(folder).glob(pattern))
        if not paths:
            raise FileNotFoundError(f"no {pattern} files in {folder}")
        return cls.from_paths(paths, project_code)

    # --- access ----------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._snaps)

    def __iter__(self) -> Iterator[Snapshot]:
        return iter(self._snaps)

    def __getitem__(self, i: int) -> Snapshot:
        return self._snaps[i]

    @property
    def first(self) -> Snapshot:
        return self._snaps[0]

    @property
    def latest(self) -> Snapshot:
        return self._snaps[-1]

    @property
    def labels(self) -> list[str]:
        return [s.label for s in self._snaps]

    def index_of(self, snap: Snapshot) -> int:
        return next(i for i, s in enumerate(self._snaps) if s is snap)

    def by_label(self, label: str) -> Snapshot:
        return self._snaps[self.labels.index(label)]

    def previous(self, snap: Snapshot) -> Snapshot | None:
        i = self.index_of(snap)
        return self._snaps[i - 1] if i > 0 else None

    # --- tidy frames -------------------------------------------------------------
    def _stack(self, attr: str, cols: list[str]) -> pd.DataFrame:
        frames = []
        for i, s in enumerate(self._snaps):
            df = getattr(s, attr)
            df = df[[c for c in cols if c in df.columns]].copy()
            df.insert(0, "snapshot_idx", i)
            df.insert(1, "data_date", s.data_date)
            frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)

    @cached_property
    def history(self) -> pd.DataFrame:
        """One row per (snapshot, activity), WBS summary rows excluded."""
        frames = []
        for i, s in enumerate(self._snaps):
            df = s.activities
            df = df[[c for c in HISTORY_COLS if c in df.columns]].copy()
            df.insert(0, "snapshot_idx", i)
            df.insert(1, "data_date", s.data_date)
            frames.append(df)
        return pd.concat(frames, ignore_index=True)

    @cached_property
    def relationship_history(self) -> pd.DataFrame:
        return self._stack("relationships", REL_COLS)

    @cached_property
    def assignment_history(self) -> pd.DataFrame:
        """One row per (snapshot, resource assignment): units budgeted, actual, remaining."""
        return self._stack("assignments", ASSIGNMENT_COLS)

    @cached_property
    def summary(self) -> pd.DataFrame:
        rows = []
        for i, s in enumerate(self._snaps):
            a = s.activities
            n = len(a)
            rows.append(
                {
                    "snapshot_idx": i,
                    "data_date": s.data_date,
                    "source": s.source,
                    "project": s.project_code,
                    "forecast_finish": s.finish_date,
                    "activities": n,
                    "complete": int(a["is_complete"].sum()),
                    "in_progress": int((a["is_started"] & ~a["is_complete"]).sum()),
                    "not_started": int((~a["is_started"]).sum()),
                    "critical": int(a["is_critical"].sum()),
                    "relationships": len(s.relationships),
                    "pct_complete_count": round(100 * a["is_complete"].mean(), 1) if n else 0.0,
                }
            )
        df = pd.DataFrame(rows)
        df["finish_shift_d"] = (df["forecast_finish"].diff().dt.total_seconds() / 86400).round(1)
        return df
