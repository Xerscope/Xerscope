"""Where a recalculation differs from the dates stored in a file, grouped by the shape of
the activity: the view that turns one week's differences into the rule to look at.

A shape is what the CPM rules key on: status, activity type, the constraint, the kinds of
predecessor and successor links, lag, and the file's progressed-activities option. Each
line of the report is one shape with its number of compared values and of differences, so
"started + FF predecessor + progress override: 12 / 12 wrong" points at one rule and
"not started + FS only: 2 / 4,000 wrong" at a detail.
"""

from __future__ import annotations

import pandas as pd

from xerscope.xer.model import CONSTRAINT, Snapshot


def join_unique(types: pd.Series) -> str:
    return "+".join(sorted(set(types)))


def join_fields(fields: pd.Series) -> str:
    return ", ".join(sorted(set(fields)))


def shapes(snapshot: Snapshot) -> pd.Series:
    """One label per activity (indexed by task_code)."""
    activities = snapshot.by_code
    relationships = snapshot.relationships
    predecessors = relationships.groupby("succ_code")["type"].agg(join_unique)
    successors = relationships.groupby("pred_code")["type"].agg(join_unique)
    lagged_links = relationships[relationships["lag_hr"] != 0]
    lagged = set(lagged_links["succ_code"]) | set(lagged_links["pred_code"])
    option = snapshot.options.get("progressed", "retained_logic").replace("_", " ")

    def label(code: str) -> str:
        row = activities.loc[code]
        parts = [str(row["status"]).lower(), str(row["type"]).lower()]
        for constraint_column in ("cstr_type", "cstr_type2"):
            constraint = row.get(constraint_column)
            if isinstance(constraint, str) and constraint:
                label = CONSTRAINT.get(constraint)
                parts.append(label.lower() if label else constraint)
        if row.get("expect_end_date") is not None and pd.notna(row.get("expect_end_date")):
            parts.append("expected finish")
        parts.append(f"pred {predecessors.get(code, 'none')}")
        parts.append(f"succ {successors.get(code, 'none')}")
        if code in lagged:
            parts.append("lag")
        if row.get("is_started") and option != "retained logic":
            parts.append(option)
        return " · ".join(parts)

    return pd.Series({code: label(code) for code in activities.index}, name="shape")


def count_wrong(agree: pd.Series) -> int:
    return int((~agree).sum())


def difference_report(snapshot: Snapshot, comparison: pd.DataFrame) -> pd.DataFrame:
    """``compare_with_stored`` rows grouped by shape: values compared, values wrong, the
    fields wrong, and one example activity. Worst share first."""
    compared = comparison[comparison["stored"].notna()].copy()
    if compared.empty:
        return pd.DataFrame(columns=["shape", "values", "wrong", "share", "fields", "example"])
    compared["shape"] = compared["task_code"].map(shapes(snapshot))
    wrong_rows = compared[~compared["agree"]]
    report = compared.groupby("shape")["agree"].agg(values="count", wrong=count_wrong)
    report["share"] = report["wrong"] / report["values"]
    report["fields"] = wrong_rows.groupby("shape")["field"].agg(join_fields)
    report["example"] = wrong_rows.groupby("shape")["task_code"].first()
    report = report[report["wrong"] > 0].sort_values(["share", "wrong"], ascending=False).reset_index()
    return report[["shape", "values", "wrong", "share", "fields", "example"]]
