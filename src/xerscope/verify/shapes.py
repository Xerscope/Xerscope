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

from xerscope.xer.model import Snapshot

CONSTRAINT = {
    "CS_MSO": "start on",
    "CS_MSOA": "start on or after",
    "CS_MSOB": "start on or before",
    "CS_MEO": "finish on",
    "CS_MEOA": "finish on or after",
    "CS_MEOB": "finish on or before",
    "CS_MANDSTART": "mandatory start",
    "CS_MANDFIN": "mandatory finish",
    "CS_ALAP": "as late as possible",
}


def shapes(snap: Snapshot) -> pd.Series:
    """One label per activity (indexed by task_code)."""
    t = snap.activities.drop_duplicates("task_code").set_index("task_code")
    rel = snap.relationships
    preds = rel.groupby("succ_code")["type"].agg(lambda s: "+".join(sorted(set(s))))
    succs = rel.groupby("pred_code")["type"].agg(lambda s: "+".join(sorted(set(s))))
    lagged = set(rel.loc[rel["lag_hr"] != 0, "succ_code"]) | set(rel.loc[rel["lag_hr"] != 0, "pred_code"])
    option = snap.options.get("progressed", "retained_logic").replace("_", " ")

    def label(code: str) -> str:
        row = t.loc[code]
        parts = [str(row["status"]).lower(), str(row["type"]).lower()]
        for col in ("cstr_type", "cstr_type2"):
            c = row.get(col)
            if isinstance(c, str) and c:
                parts.append(CONSTRAINT.get(c, c))
        if row.get("expect_end_date") is not None and pd.notna(row.get("expect_end_date")):
            parts.append("expected finish")
        parts.append(f"pred {preds.get(code, 'none')}")
        parts.append(f"succ {succs.get(code, 'none')}")
        if code in lagged:
            parts.append("lag")
        if row.get("is_started") and option != "retained logic":
            parts.append(option)
        return " · ".join(parts)

    return pd.Series({c: label(c) for c in t.index}, name="shape")


def difference_report(snap: Snapshot, cmp: pd.DataFrame) -> pd.DataFrame:
    """``compare_with_stored`` rows grouped by shape: values compared, values wrong, the
    fields wrong, and one example activity. Worst share first."""
    d = cmp[cmp["stored"].notna()].copy()
    if d.empty:
        return pd.DataFrame(columns=["shape", "values", "wrong", "share", "fields", "example"])
    d["shape"] = d["task_code"].map(shapes(snap))
    bad = d[~d["agree"]]
    g = d.groupby("shape")["agree"].agg(values="count", wrong=lambda s: int((~s).sum()))
    g["share"] = g["wrong"] / g["values"]
    g["fields"] = bad.groupby("shape")["field"].agg(lambda s: ", ".join(sorted(set(s))))
    g["example"] = bad.groupby("shape")["task_code"].first()
    g = g[g["wrong"] > 0].sort_values(["share", "wrong"], ascending=False).reset_index()
    return g[["shape", "values", "wrong", "share", "fields", "example"]]
