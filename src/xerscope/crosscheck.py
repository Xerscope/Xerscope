"""Façade over :mod:`xerscope.verify`: every independent check in one import.

uv sync --extra crosscheck          # MPXJ + jpype, needs a Java runtime (JDK 11+)
uv run xerscope crosscheck ~/exports/project-x --out crosscheck.csv   # reader comparison
uv run xerscope crosscheck --cpm FILE.xer     # the CPM against MPXJ's scheduler and P6's stored dates
uv run xerscope crosscheck --p6 SET_DIR       # the CPM against P6's held-out corpus
"""

from __future__ import annotations

from .verify.mpxj_cpm import (
    CPM_FIELDS,
    P6_SETTLED,
    UNRESOLVED,
    cpm_crosscheck,
    excused_row,
    mpxj_inconsistent,
    mpxj_schedule,
    mpxj_scheduler_source,
    mpxj_unsupported,
    settled_patterns,
    unresolved_patterns,
)
from .verify.mpxj_reader import compare_file, compare_paths
from .verify.p6_corpus import P6_FIELDS, p6_heldout_score

__all__ = [
    "CPM_FIELDS",
    "P6_FIELDS",
    "P6_SETTLED",
    "UNRESOLVED",
    "compare_file",
    "compare_paths",
    "cpm_crosscheck",
    "excused_row",
    "mpxj_inconsistent",
    "mpxj_schedule",
    "mpxj_scheduler_source",
    "mpxj_unsupported",
    "p6_heldout_score",
    "settled_patterns",
    "unresolved_patterns",
]
