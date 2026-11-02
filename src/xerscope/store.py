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

from .config import DATE_FMT
from .xer import Snapshot, load_snapshot, xer_files
from .xer.model import ASSIGNMENT_COLS_MODEL, LABOR_COLS, REL_COLS_MODEL

# The columns of fact_activity, in the order Power BI users know them: a subset of the model's
# TASK_COLS + LABOR_COLS (tests/test_store.py checks it). Left out on purpose, the internal keys
# and the raw P6 values that a derived column replaces: task_id, wbs_id, hours_per_day,
# is_wbs_summary, status_code, ev_user_pct, cstr_date, cstr_type2, cstr_date2, total_float_hr_cnt,
# free_float_hr_cnt, target_drtn_hr_cnt, remain_drtn_hr_cnt, restart_date, reend_date, constraint,
# has_resource, has_expense, has_external_pred, has_external_succ.
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
REL_COLS = REL_COLS_MODEL
# every assignment column of the model but the internal keys
ASSIGNMENT_COLS = [column for column in ASSIGNMENT_COLS_MODEL if column not in {"task_id", "role_id"}]


def _sort_key(s: Snapshot):
    return (s.data_date if s.data_date is not None else pd.Timestamp.max, s.source)


class SnapshotStore:
    def __init__(self, snapshots: Iterable[Snapshot]):
        snaps = sorted(snapshots, key=_sort_key)
        self.warnings: list[str] = [w for s in snaps for w in s.warnings]
        # One update per data date: the weekly series, the earned-value and health
        # histories are keyed on it. Of two files with the same data date the first by
        # name is kept.
        self._snaps: list[Snapshot] = []
        for s in snaps:
            kept = next((k for k in self._snaps if k.data_date == s.data_date), None)
            if kept is not None and s.data_date is not None:
                self.warnings.append(f"{s.source}: same data date as {kept.source} ({s.data_date:{DATE_FMT}}), skipped")
            else:
                self._snaps.append(s)
        codes = {s.project_code for s in self._snaps}
        if len(codes) > 1:
            self.warnings.append(f"project code differs across snapshots (renamed or other project): {sorted(codes)}")

    # --- construction ----------------------------------------------------------
    @classmethod
    def from_paths(cls, paths: Iterable[str | Path], project_code: str | None = None) -> SnapshotStore:
        return cls(load_snapshot(p, project_code) for p in paths)

    @classmethod
    def from_folder(
        cls, folder: str | Path, pattern: str | None = None, project_code: str | None = None
    ) -> SnapshotStore:
        paths = xer_files(folder) if pattern is None else sorted(Path(folder).glob(pattern))
        if not paths:
            raise FileNotFoundError(f"no {pattern or '.xer'} files in {folder}")
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
    def _stack(self, attribute: str, columns: list[str]) -> pd.DataFrame:
        frames = []
        for index, snapshot in enumerate(self._snaps):
            frame = getattr(snapshot, attribute)[columns].copy()
            frame.insert(0, "snapshot_idx", index)
            frame.insert(1, "data_date", snapshot.data_date)
            frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)

    @cached_property
    def history(self) -> pd.DataFrame:
        """One row per (snapshot, activity), WBS summary rows excluded."""
        return self._stack("activities", HISTORY_COLS)

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
        # working days on the newer update's project calendar, like every other "wd" figure
        shifts = [None]
        for prev, cur in zip(self._snaps, self._snaps[1:], strict=False):
            a, b = prev.finish_date, cur.finish_date
            shifts.append(None if a is None or b is None else round(cur.calendar().working_days(a, b), 1))
        df["finish_shift_wd"] = pd.Series(shifts, dtype=float)
        return df
