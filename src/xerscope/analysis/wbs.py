"""WBS tree with roll-ups: every node summarises all activities below it.

% complete is weighted by budgeted labour hours, falling back to original duration for
nodes without hours (``weight`` column says which was used). It is xerscope's measure, not
a P6 field: each activity contributes its own % complete whatever its % complete type
(duration, physical, units), so the roll-up mixes those types as P6's WBS summary bars do.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..xer import Snapshot
from .baseline import Baseline


def tree(snapshot: Snapshot) -> pd.DataFrame:
    """WBS nodes (project node excluded) with depth and the list of ancestor ids."""
    nodes = snapshot.wbs
    if nodes.empty:
        return pd.DataFrame(columns=["wbs_id", "wbs_code", "wbs_name", "wbs_sort", "depth", "parent", "ancestors"])
    nodes = nodes[nodes["proj_node_flag"] != "Y"].copy()
    by_id = nodes.set_index("wbs_id")
    parent = by_id["parent_wbs_id"].where(by_id["parent_wbs_id"].isin(by_id.index))

    def chain(wbs_id):
        ancestors, seen = [], set()
        while isinstance(wbs_id, str) and wbs_id in by_id.index and wbs_id not in seen:
            seen.add(wbs_id)
            ancestors.append(wbs_id)
            wbs_id = parent.get(wbs_id)
        return ancestors

    nodes["ancestors"] = [chain(wbs_id) for wbs_id in nodes["wbs_id"]]  # self first, then up to the top
    nodes["depth"] = nodes["ancestors"].map(len)
    nodes["parent"] = nodes["wbs_id"].map(parent)
    return (
        nodes[["wbs_id", "wbs_code", "wbs_name", "wbs_sort", "depth", "parent", "ancestors"]]
        .sort_values("wbs_sort")
        .reset_index(drop=True)
    )


ROOT = "__project__"


def rollup(snapshot: Snapshot, baseline: Baseline | None = None) -> pd.DataFrame:
    """One row per WBS node plus a project row (``wbs_id == ROOT``, depth 0), in P6 order."""
    nodes = tree(snapshot)
    root = pd.DataFrame(
        [
            {
                "wbs_id": ROOT,
                "wbs_code": snapshot.project_code,
                "wbs_name": snapshot.project_name,
                "wbs_sort": "",
                "depth": 0,
                "parent": None,
                "ancestors": [ROOT],
            }
        ]
    )
    nodes = pd.concat([root, nodes], ignore_index=True)
    nodes["ancestors"] = [
        ancestors if wbs_id == ROOT else ancestors + [ROOT]
        for wbs_id, ancestors in zip(nodes["wbs_id"], nodes["ancestors"], strict=True)
    ]
    activities = snapshot.activities.copy()
    ancestors_of = nodes.set_index("wbs_id")["ancestors"]
    activities["node"] = [ancestors_of.get(wbs_id, [ROOT]) for wbs_id in activities["wbs_id"]]
    activities = activities.explode("node")  # an activity counts in every node above it
    if baseline is not None:
        activities = activities.join(baseline.frame[["bl_finish"]], on="task_code")
    else:
        activities["bl_finish"] = pd.NaT
    activities["w_hr"] = activities["labor_budget_hr"].fillna(0)
    activities["w_d"] = activities["original_d"].fillna(0)
    # the finish compared with the baseline: over the activities the baseline holds, so an
    # activity added since does not show as a slip of the node
    activities["finish_in_bl"] = activities["finish"].where(activities["bl_finish"].notna())
    activities["outside_bl"] = activities["bl_finish"].isna()
    activities["open_critical"] = activities["is_critical"] & ~activities["is_complete"]
    activities["weighted_pct_hr"] = activities["w_hr"] * activities["pct_complete"]
    activities["weighted_pct_d"] = activities["w_d"] * activities["pct_complete"]
    by_node = activities.groupby("node")
    totals = pd.DataFrame(
        {
            "activities": by_node.size(),
            "complete": by_node["is_complete"].sum(),
            "critical": by_node["open_critical"].sum(),
            "min_float_d": by_node["total_float_d"].min(),
            "start": by_node["start"].min(),
            "finish": by_node["finish"].max(),
            "bl_finish": by_node["bl_finish"].max(),
            "_finish_in_bl": by_node["finish_in_bl"].max(),
            "outside_bl": by_node["outside_bl"].sum(),
            "budget_hr": by_node["w_hr"].sum(),
            "actual_hr": by_node["labor_actual_hr"].sum(),
            "remaining_hr": by_node["labor_remaining_hr"].sum(),
            "_pct_hr": by_node["weighted_pct_hr"].sum(),
            "_pct_d": by_node["weighted_pct_d"].sum(),
            "_w_d": by_node["w_d"].sum(),
        }
    )
    use_hours = totals["budget_hr"] > 0
    totals["pct_complete"] = np.where(
        use_hours,
        totals["_pct_hr"] / totals["budget_hr"].where(use_hours),
        totals["_pct_d"] / totals["_w_d"].where(totals["_w_d"] > 0),
    )
    totals["weight"] = np.where(use_hours, "hours", "duration")
    # project calendar: a WBS node has no calendar of its own
    no_calendar = pd.Series("", index=totals.index)
    totals["finish_variance_wd"] = snapshot.working_days(
        no_calendar, totals["bl_finish"], totals["_finish_in_bl"]
    ).round(1)
    totals = totals.drop(columns=["_pct_hr", "_pct_d", "_w_d", "_finish_in_bl"])
    out = nodes.join(totals, on="wbs_id", how="left")
    counts = ["activities", "complete", "critical", "outside_bl"]
    out[counts] = out[counts].fillna(0).astype(int)
    out["label"] = [
        name if depth == 0 else f"{code.split('.')[-1]} · {name}"
        for depth, code, name in zip(out["depth"], out["wbs_code"], out["wbs_name"], strict=True)
    ]
    return out


def subtree_ids(nodes: pd.DataFrame, wbs_id: str) -> set[str]:
    """``wbs_id`` and every node below it."""
    return {
        node_id for node_id, ancestors in zip(nodes["wbs_id"], nodes["ancestors"], strict=True) if wbs_id in ancestors
    }
