"""The Debug tables of where the recalculation first departs from the dates P6 stored.

The Delay analysis page reads the recalculated finish, so it is worth what the recalculation is
worth on the file (``analysis.forensics.engine_gap_wd``). When the two finishes differ, most of
the activities whose dates differ only follow an activity upstream: these tables keep the
activities where the difference starts, and count them by the form the scheduling rules key on.
Its own module: ``app/diagnostic.py`` is at the edge of the maintainability rank A.
"""

from __future__ import annotations

import pandas as pd

from xerscope.analysis.cpm import compare_with_stored, schedule
from xerscope.analysis.populations import Funnel, activity_funnel
from xerscope.xer.model import Snapshot, constraints_label

EARLY_FIELDS = ["early_start_date", "early_end_date"]
DEPARTURE_FORM = ["status", "type", "constraint", "expected_finish", "resource_dependent", "longest_path"]
DEPARTURE_COLUMNS = [
    "task_code",
    "early_end_date",
    "early_end_date_recalc",
    "gap_hr",
    *DEPARTURE_FORM,
]


def _early_comparison(snapshot: Snapshot) -> pd.DataFrame:
    """Rows of ``compare_with_stored`` for the early dates the file stores."""
    comparison = compare_with_stored(snapshot)
    return comparison[comparison["field"].isin(EARLY_FIELDS) & comparison["stored"].notna()]


def departure_funnel(snapshot: Snapshot) -> Funnel:
    """Funnel of ``departures``, step by step, as the checks build theirs (``analysis.populations``).

    Every activity; not complete and not level of effort (the recalculation compares no other);
    with a stored early date; one of them not the recalculated one; no predecessor in that case.
    """
    early = _early_comparison(snapshot)
    compared = set(early["task_code"])
    differing = set(early.loc[~early["agree"], "task_code"])
    links = snapshot.relationships
    follows_a_difference = set(links.loc[links["pred_code"].isin(differing), "succ_code"])
    funnel = activity_funnel(snapshot).exclude("complete", "xerscope").exclude("loe", "xerscope")
    funnel.keep("with a stored early date", "xerscope", lambda rows: rows["task_code"].isin(compared))
    funnel.keep(
        "a stored early date is not the recalculated one", "xerscope", lambda rows: rows["task_code"].isin(differing)
    )
    funnel.keep(
        "no predecessor in the same case", "xerscope", lambda rows: ~rows["task_code"].isin(follows_a_difference)
    )
    return funnel


def departures(snapshot: Snapshot) -> pd.DataFrame:
    """Unfinished activities where the recalculated early dates first differ from the stored ones.

    An activity is kept when one of its stored early dates is not the recalculated one and none of
    its predecessors is in the same case: what differs downstream of it follows from it. Per
    activity: the stored and recalculated early finish, their gap in working hours of its calendar
    (recalculated minus stored), then its form: status, type, constraints, an expected finish,
    resource dependent, on the recalculated longest path. Empty when every stored early date is
    reproduced. The population is ``departure_funnel``'s.
    """
    codes = sorted(set(departure_funnel(snapshot).rows["task_code"]))
    if not codes:
        return pd.DataFrame(columns=DEPARTURE_COLUMNS)
    tasks, frame = snapshot.by_code, schedule(snapshot).frame
    early = _early_comparison(snapshot)
    finishes = early[early["field"] == "early_end_date"].set_index("task_code")
    rows = []
    for code in codes:
        task = tasks.loc[code]
        rows.append(
            {
                "task_code": code,
                "early_end_date": task.get("early_end_date"),
                "early_end_date_recalc": frame.at[code, "ef"],
                "gap_hr": finishes["gap_hr"].get(code),
                "status": task["status"],
                "type": task["type"],
                "constraint": constraints_label(task),
                "expected_finish": pd.notna(task.get("expect_end_date")),
                "resource_dependent": bool(frame.at[code, "resource_dependent"]),
                "longest_path": bool(frame.at[code, "longest_path"]),
            }
        )
    return pd.DataFrame(rows, columns=DEPARTURE_COLUMNS)


def departure_forms(snapshot: Snapshot) -> pd.DataFrame:
    """Rows of ``departures`` counted by form: one row per combination, the most frequent first.

    Counts only, no Activity ID and no date: 3 resource-dependent activities under a Mandatory
    Finish read "Not started, Resource dependent, Mandatory finish, ..., tasks 3".
    """
    roots = departures(snapshot)
    if roots.empty:
        return pd.DataFrame(columns=[*DEPARTURE_FORM, "tasks"])
    counted = roots.groupby(DEPARTURE_FORM, dropna=False).size().rename("tasks")
    return counted.sort_values(ascending=False, kind="stable").reset_index()
