"""The Debug table of the expected finishes by form: counts only, no Activity ID and no date.

The forms are what the scheduling rules key on (status, type, constraints, a date after the primary
constraint, a date off the working time, a finish-to-finish or start-to-finish predecessor). Its own
module: ``app/diagnostic.py`` is at the edge of the maintainability rank A.
"""

from __future__ import annotations

import pandas as pd

from xerscope.analysis.cpm import compare_with_stored
from xerscope.xer.model import CONSTRAINT, Snapshot

EXPECTED_FINISH_FORM = [
    "status", "type", "constraint", "after_constraint_date", "off_working_time", "ff_sf_predecessor",
]  # fmt: skip


def expected_finish_forms(snapshot: Snapshot) -> pd.DataFrame:
    """Unfinished activities with an expected finish, counted by form: one row per combination.

    The form: status, type, constraints (primary + secondary), an expected finish after the primary
    constraint date, an expected finish off the working time of the activity's calendar, a
    finish-to-finish or start-to-finish predecessor. ``stored_identical`` / ``stored_different``:
    activities whose stored dates and floats the recalculation reproduces, or not (an activity with no
    stored value is in neither). Counts only: 3 finish milestones with an expected finish on a Saturday
    read "Not started, Finish milestone, off_working_time True, tasks 3".
    """
    counts = ["tasks", "stored_identical", "stored_different"]
    tasks = snapshot.by_code
    if "expect_end_date" not in tasks:
        return pd.DataFrame(columns=EXPECTED_FINISH_FORM + counts)
    unfinished = tasks[tasks["expect_end_date"].notna() & (tasks["status_code"] != "TK_Complete")]
    if unfinished.empty:
        return pd.DataFrame(columns=EXPECTED_FINISH_FORM + counts)
    links = snapshot.relationships
    bound_at_finish = set(links.loc[links["type"].isin(["FF", "SF"]), "succ_code"])
    identical, different = _reproduction(snapshot)
    rows = []
    for code, task in unfinished.iterrows():
        constraints = [task.get(column) for column in ("cstr_type", "cstr_type2")]
        constraint_date = task.get("cstr_date")
        after_constraint_date = pd.NA
        if pd.notna(constraint_date):
            after_constraint_date = task["expect_end_date"] > constraint_date
        rows.append(
            {
                "status": task["status"],
                "type": task["type"],
                "constraint": " + ".join(CONSTRAINT.get(c, c) for c in constraints if isinstance(c, str) and c),
                "after_constraint_date": after_constraint_date,
                "off_working_time": not snapshot.calendar(task["clndr_id"]).axis().is_working(task["expect_end_date"]),
                "ff_sf_predecessor": code in bound_at_finish,
                "stored_identical": code in identical,
                "stored_different": code in different,
            }
        )
    forms = pd.DataFrame(rows).astype({"after_constraint_date": "boolean"})
    grouped = forms.groupby(EXPECTED_FINISH_FORM, dropna=False)
    out = grouped.agg(
        tasks=("status", "size"),
        stored_identical=("stored_identical", "sum"),
        stored_different=("stored_different", "sum"),
    )
    return out.sort_values("tasks", ascending=False, kind="stable").reset_index()


def _reproduction(snapshot: Snapshot) -> tuple[set[str], set[str]]:
    """Activities the recalculation reproduces, and those it does not.

    Reproduced: every date and float P6 stored is the recalculated one. Not reproduced: at least one
    differs. An activity with no stored value is in neither set.
    """
    comparison = compare_with_stored(snapshot)
    compared = comparison[comparison["stored"].notna()]
    different = set(compared.loc[~compared["agree"], "task_code"])
    return set(compared["task_code"]) - different, different
