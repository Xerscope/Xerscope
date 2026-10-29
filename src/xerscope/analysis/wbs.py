"""WBS tree with roll-ups: every node summarises all activities below it.

% complete is weighted by budgeted labour hours, falling back to original duration for
nodes without hours (``weight`` column says which was used).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..xer import Snapshot
from .baseline import Baseline


def tree(snap: Snapshot) -> pd.DataFrame:
    """WBS nodes (project node excluded) with depth and the list of ancestor ids."""
    w = snap.wbs
    if w.empty:
        return pd.DataFrame(columns=["wbs_id", "wbs_code", "wbs_name", "wbs_sort", "depth", "parent", "ancestors"])
    w = w[w["proj_node_flag"] != "Y"].copy()
    by_id = w.set_index("wbs_id")
    parent = by_id["parent_wbs_id"].where(by_id["parent_wbs_id"].isin(by_id.index))

    def chain(wid):
        out, seen = [], set()
        while isinstance(wid, str) and wid in by_id.index and wid not in seen:
            seen.add(wid)
            out.append(wid)
            wid = parent.get(wid)
        return out

    w["ancestors"] = [chain(i) for i in w["wbs_id"]]  # self first, then up to the top
    w["depth"] = w["ancestors"].map(len)
    w["parent"] = w["wbs_id"].map(parent)
    return (
        w[["wbs_id", "wbs_code", "wbs_name", "wbs_sort", "depth", "parent", "ancestors"]]
        .sort_values("wbs_sort")
        .reset_index(drop=True)
    )


ROOT = "__project__"


def rollup(snap: Snapshot, baseline: Baseline | None = None) -> pd.DataFrame:
    """One row per WBS node plus a project row (``wbs_id == ROOT``, depth 0), in P6 order."""
    tr = tree(snap)
    root = pd.DataFrame(
        [
            {
                "wbs_id": ROOT,
                "wbs_code": snap.project_code,
                "wbs_name": snap.project_name,
                "wbs_sort": "",
                "depth": 0,
                "parent": None,
                "ancestors": [ROOT],
            }
        ]
    )
    tr = pd.concat([root, tr], ignore_index=True)
    tr["ancestors"] = [
        anc if wid == ROOT else anc + [ROOT] for wid, anc in zip(tr["wbs_id"], tr["ancestors"], strict=True)
    ]
    a = snap.activities.copy()
    anc = tr.set_index("wbs_id")["ancestors"]
    a["node"] = [anc.get(w, [ROOT]) for w in a["wbs_id"]]
    a = a.explode("node")
    if baseline is not None:
        a = a.join(baseline.frame[["bl_finish"]], on="task_code")
    else:
        a["bl_finish"] = pd.NaT
    a["w_hr"] = a["labor_budget_hr"].fillna(0)
    a["w_d"] = a["original_d"].fillna(0)
    a["open"] = ~a["is_complete"]
    g = a.groupby("node")
    r = pd.DataFrame(
        {
            "activities": g.size(),
            "complete": g["is_complete"].sum(),
            "critical": g.apply(lambda x: int((x["is_critical"] & x["open"]).sum()), include_groups=False),
            "min_float_d": g["total_float_d"].min(),
            "start": g["start"].min(),
            "finish": g["finish"].max(),
            "bl_finish": g["bl_finish"].max(),
            "budget_hr": g["w_hr"].sum(),
            "actual_hr": g["labor_actual_hr"].sum(),
            "remaining_hr": g["labor_remaining_hr"].sum(),
            "_pct_hr": g.apply(lambda x: (x["w_hr"] * x["pct_complete"]).sum(), include_groups=False),
            "_pct_d": g.apply(lambda x: (x["w_d"] * x["pct_complete"]).sum(), include_groups=False),
            "_w_d": g["w_d"].sum(),
        }
    )
    use_hr = r["budget_hr"] > 0
    r["pct_complete"] = np.where(
        use_hr, r["_pct_hr"] / r["budget_hr"].where(use_hr), r["_pct_d"] / r["_w_d"].where(r["_w_d"] > 0)
    )
    r["weight"] = np.where(use_hr, "hours", "duration")
    # project calendar: a WBS node has no calendar of its own
    r["finish_var_wd"] = snap.working_days(pd.Series("", index=r.index), r["bl_finish"], r["finish"]).round(1)
    r = r.drop(columns=["_pct_hr", "_pct_d", "_w_d"])
    out = tr.join(r, on="wbs_id", how="left")
    out[["activities", "complete", "critical"]] = out[["activities", "complete", "critical"]].fillna(0).astype(int)
    out["label"] = [
        n if d == 0 else "   " * (d - 1) + f"{c.split('.')[-1]} · {n}"
        for d, c, n in zip(out["depth"], out["wbs_code"], out["wbs_name"], strict=True)
    ]
    return out


def subtree_ids(tr: pd.DataFrame, wbs_id: str) -> set[str]:
    """``wbs_id`` and every node below it."""
    return {i for i, anc in zip(tr["wbs_id"], tr["ancestors"], strict=True) if wbs_id in anc}
