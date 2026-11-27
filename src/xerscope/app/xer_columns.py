"""Debug block 09: the columns an XER file carries, read as stored, whether xerscope reads them or not.

Labels: XER Import/Export Data Map Guide (Project) v26, G57491-01, October 2026 (P6 EPPM), table TASK.
"""

from __future__ import annotations

import pandas as pd

from xerscope.app.ui import as_dates
from xerscope.xer import RawXer, Snapshot

# TASK columns holding a date, and the users who added and last changed the activity, with their labels in
# the XER Import/Export Data Map Guide (Project) v26, G57491-01, October 2026, table TASK. The guide lists no
# baseline date in TASK: a column named after a baseline (base_*, bl_*) is shown with NOT_IN_DATA_MAP.
TASK_DATE_LABELS = {
    "act_start_date": "Actual Start", "act_end_date": "Actual Finish",
    "early_start_date": "Early Start", "early_end_date": "Early Finish",
    "late_start_date": "Late Start", "late_end_date": "Late Finish",
    "target_start_date": "Planned Start", "target_end_date": "Planned Finish",
    "restart_date": "Remaining Early Start", "reend_date": "Remaining Early Finish",
    "rem_late_start_date": "Remaining Late Start", "rem_late_end_date": "Remaining Late Finish",
    "expect_end_date": "Expected Finish",
    "cstr_date": "Primary Constraint Date", "cstr_date2": "Secondary Constraint Date",
    "external_early_start_date": "External Early Start", "external_late_end_date": "External Late Finish",
    "suspend_date": "Suspend Date", "resume_date": "Resume Date",
    "review_end_date": "Review Finish (P6 Professional only)",
    "create_date": "Added Date", "create_user": "Added By",
    "update_date": "Last Modified Date", "update_user": "Last Modified By",
}  # fmt: skip
TASK_USER_COLUMNS = ("create_user", "update_user")  # names of people: counted, never shown
NOT_IN_DATA_MAP = "not in data map v26"


def xer_columns_table(snapshot: Snapshot) -> pd.DataFrame:
    """Return every column of every %T table of the file, in the file's order, with its rows holding a value.

    All projects of the file are counted. Column names only, no cell value.
    """
    rows = [
        {"table": table, "column": column, "rows_with_value": filled}
        for table, columns in snapshot.xer_columns.items()
        for column, filled in columns.items()
    ]
    return pd.DataFrame(rows, columns=["table", "column", "rows_with_value"])


def _is_date_or_baseline_column(name: str) -> bool:
    return name in TASK_DATE_LABELS or name.endswith("_date") or name.startswith(("base_", "bl_"))


def task_date_columns_table(snapshot: Snapshot) -> pd.DataFrame:
    """Return the TASK columns holding a date or named after a baseline, with label, count and date range.

    One row per column of the update: its data map v26 label, the tasks holding a value and the earliest
    and latest date stored.

    A column the data map does not list (base_start_date, base_end_date) is read as stored, whatever it
    holds in P6. The user columns are counted only: their values are names.
    """
    tasks = snapshot.tasks
    rows = []
    for column in [name for name in tasks.columns if _is_date_or_baseline_column(name)]:
        values = tasks[column]
        filled = values.notna() & (values.astype("string").str.strip() != "")
        dates = pd.Series(pd.NaT, index=values.index) if column in TASK_USER_COLUMNS else as_dates(values)
        rows.append(
            {
                "column": column,
                "label": TASK_DATE_LABELS.get(column, NOT_IN_DATA_MAP),
                "tasks": int(filled.sum()),
                "earliest": dates.min(),
                "latest": dates.max(),
            }
        )
    return pd.DataFrame(rows, columns=["column", "label", "tasks", "earliest", "latest"])


def file_fields_table(raw: RawXer) -> pd.DataFrame:
    """Return every field of every table of a file as the parser read it, whatever xerscope makes of it.

    One row per %F field: its table, its place in the %F line (from 1), the table's rows and the rows holding a
    value in it. The model is not involved: a table or a field it ignores or refuses is listed all the same.
    Field names only, no cell value.
    """
    rows = []
    for table, frame in raw.tables.items():
        for position, column in enumerate(frame.columns, start=1):
            filled = (frame[column].astype("string").str.strip().fillna("") != "").sum()
            rows.append(
                {
                    "table": table,
                    "position": position,
                    "column": column,
                    "rows": len(frame),
                    "rows_with_value": int(filled),
                }
            )
    return pd.DataFrame(rows, columns=["table", "position", "column", "rows", "rows_with_value"])
