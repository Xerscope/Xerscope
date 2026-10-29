"""What changed between two XER files of the same project (activities matched by ID).

One row per change: ``category, change, task_code, task_name, wbs_code, field, before,
after, delta, unit``. ``before`` / ``after`` are display strings (dates, numbers and text
mix in one column); ``delta`` is numeric where it means something: working days on the
activity's calendar for dates and durations, points for % complete, hours for budgets.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..xer import Snapshot

CATEGORIES = [
    "Project",
    "Scope",
    "Activities",
    "Durations",
    "Relationships",
    "Progress",
    "Dates",
    "Float",
    "Constraints",
    "Resources",
]
COLS = ["category", "change", "task_code", "task_name", "wbs_code", "field", "before", "after", "delta", "unit"]


def _fmt(v) -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return ""
    if isinstance(v, pd.Timestamp):
        return f"{v:%Y-%m-%d %H:%M}"
    if isinstance(v, (float, np.floating)):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return str(v)


def _rows(changes: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(changes, columns=COLS)
    for c in ("before", "after"):
        df[c] = df[c].map(_fmt)
    df["delta"] = pd.to_numeric(df["delta"], errors="coerce")
    return df


def changelog(old: Snapshot, new: Snapshot) -> pd.DataFrame:
    a = old.activities.drop_duplicates("task_code").set_index("task_code")
    b = new.activities.drop_duplicates("task_code").set_index("task_code")
    rows: list[dict] = []

    def add(cat, change, code, field, before, after, delta=None, unit=""):
        src = b.loc[code] if code in b.index else a.loc[code] if code in a.index else None
        rows.append(
            dict(
                category=cat,
                change=change,
                task_code=code,
                task_name=None if src is None else src["task_name"],
                wbs_code=None if src is None else src["wbs_code"],
                field=field,
                before=before,
                after=after,
                delta=delta,
                unit=unit,
            )
        )

    # --- project -------------------------------------------------------------------------
    cal = new.calendar()
    add(
        "Project",
        "data date",
        "",
        "data date",
        old.data_date,
        new.data_date,
        cal.working_days(old.data_date, new.data_date) if old.data_date is not None else None,
        "wd",
    )
    add(
        "Project",
        "forecast finish",
        "",
        "forecast finish",
        old.finish_date,
        new.finish_date,
        cal.working_days(old.finish_date, new.finish_date) if old.finish_date is not None else None,
        "wd",
    )
    add("Project", "activities", "", "activities", len(a), len(b), len(b) - len(a))
    add(
        "Project",
        "relationships",
        "",
        "relationships",
        len(old.relationships),
        len(new.relationships),
        len(new.relationships) - len(old.relationships),
    )

    # --- scope -----------------------------------------------------------------------------
    for code in sorted(set(b.index) - set(a.index)):
        add("Scope", "added", code, "activity", None, b.loc[code, "task_name"])
    for code in sorted(set(a.index) - set(b.index)):
        add("Scope", "deleted", code, "activity", a.loc[code, "task_name"], None)

    common = sorted(set(a.index) & set(b.index))
    A, B = a.loc[common], b.loc[common]

    def changed(col):
        x, y = A[col], B[col]
        return ~((x == y) | (x.isna() & y.isna()))

    cal_name = {cid: c.name for cid, c in new.work_calendars.items()} | {
        cid: c.name for cid, c in old.work_calendars.items()
    }
    for col, change in [
        ("task_name", "renamed"),
        ("wbs_code", "moved to another WBS"),
        ("type", "type changed"),
        ("clndr_id", "calendar changed"),
    ]:
        for code in A.index[changed(col)]:
            x, y = A.loc[code, col], B.loc[code, col]
            if col == "clndr_id":
                x, y = cal_name.get(x, x), cal_name.get(y, y)
            add("Activities", change, code, col, x, y)

    # --- durations ------------------------------------------------------------------------------
    for code in A.index[changed("original_d")]:
        x, y = A.loc[code, "original_d"], B.loc[code, "original_d"]
        add("Durations", "original duration changed", code, "original duration", x, y, y - x, "wd")
    grew = (B["remaining_d"] > A["remaining_d"] + 1e-9) & ~B["is_complete"]
    for code in A.index[grew]:
        x, y = A.loc[code, "remaining_d"], B.loc[code, "remaining_d"]
        add("Durations", "remaining duration increased", code, "remaining duration", x, y, y - x, "wd")

    # --- progress --------------------------------------------------------------------------------
    order = {"Not started": 0, "In progress": 1, "Complete": 2}
    for code in A.index[changed("status")]:
        x, y = A.loc[code, "status"], B.loc[code, "status"]
        step = order.get(y, 0) - order.get(x, 0)
        change = "status reverted" if step < 0 else ("finished" if y == "Complete" else "started")
        add("Progress", change, code, "status", x, y)
    for col, label in [("act_start_date", "actual start"), ("act_end_date", "actual finish")]:
        x, y = A[col], B[col]
        moved = x.notna() & y.notna() & (x != y)
        removed = x.notna() & y.isna()
        for code in A.index[moved]:
            add("Progress", f"{label} changed (retroactive)", code, label, x[code], y[code])
        for code in A.index[removed]:
            add("Progress", f"{label} removed", code, label, x[code], None)
    dp = (B["pct_complete"] - A["pct_complete"]).round(2)
    for code in A.index[dp.fillna(0) != 0]:
        add(
            "Progress",
            "% complete",
            code,
            "% complete",
            A.loc[code, "pct_complete"],
            B.loc[code, "pct_complete"],
            dp[code],
            "pts",
        )

    # --- dates and float (open work only: actuals are covered above) --------------------------------
    open_ = ~B["is_complete"]
    for col, label in [("start", "start moved"), ("finish", "finish moved")]:
        move = new.working_days(B["clndr_id"], A[col], B[col]).round(2)
        for code in A.index[open_ & (move.abs() > 0.005)]:
            add("Dates", label, code, col, A.loc[code, col], B.loc[code, col], move[code], "wd")
    dtf = (B["total_float_d"] - A["total_float_d"]).round(2)
    for code in A.index[open_ & (dtf.abs() > 0.005)]:
        add(
            "Float",
            "total float changed",
            code,
            "total float",
            A.loc[code, "total_float_d"],
            B.loc[code, "total_float_d"],
            dtf[code],
            "wd",
        )
    for code in A.index[~A["is_critical"] & B["is_critical"]]:
        add("Float", "became critical", code, "critical", "no", "yes")
    for code in A.index[A["is_critical"] & ~B["is_critical"] & open_]:
        add("Float", "no longer critical", code, "critical", "yes", "no")

    # --- constraints -------------------------------------------------------------------------------------
    for typ, date, label in [
        ("cstr_type", "cstr_date", "primary constraint"),
        ("cstr_type2", "cstr_date2", "secondary constraint"),
    ]:
        tx, ty = A[typ].replace("", np.nan), B[typ].replace("", np.nan)
        diff = ~((tx == ty) | (tx.isna() & ty.isna())) | (tx.notna() & changed(date))
        for code in A.index[diff]:
            before = "" if pd.isna(tx[code]) else f"{tx[code]} {_fmt(A.loc[code, date])}"
            after = "" if pd.isna(ty[code]) else f"{ty[code]} {_fmt(B.loc[code, date])}"
            change = "added" if pd.isna(tx[code]) else "removed" if pd.isna(ty[code]) else "changed"
            add("Constraints", f"{label} {change}", code, label, before.strip(), after.strip())

    # --- resources ------------------------------------------------------------------------------------
    dh = (B["labor_budget_hr"] - A["labor_budget_hr"]).round(2)
    for code in A.index[dh.fillna(0) != 0]:
        add(
            "Resources",
            "budgeted labour hours changed",
            code,
            "budget labour h",
            A.loc[code, "labor_budget_hr"],
            B.loc[code, "labor_budget_hr"],
            dh[code],
            "h",
        )

    rows += _assignment_changes(old, new, a, b)

    # --- relationships -------------------------------------------------------------------------------------
    rows += _relationship_changes(old, new, b, a)
    df = _rows(rows)
    df["category"] = pd.Categorical(df["category"], CATEGORIES, ordered=True)
    return df.sort_values(["category", "change", "task_code"], kind="stable").reset_index(drop=True)


def _assignment_changes(old: Snapshot, new: Snapshot, a: pd.DataFrame, b: pd.DataFrame) -> list[dict]:
    """Resource assignments added / removed, and budgeted units changed, per activity and resource."""

    def units(snap: Snapshot) -> pd.Series:
        x = snap.assignments
        if x.empty:
            return pd.Series(dtype=float)
        who = x["rsrc_short_name"].fillna(x["rsrc_name"]).fillna(x["rsrc_id"]).astype(str)
        who = who.where(x["rsrc_type"] != "role", "role " + x["rsrc_name"].fillna(x["role_id"]).astype(str))
        return x["target_qty"].fillna(0.0).groupby([x["task_code"], who]).sum()

    uo, un = units(old), units(new)
    rows = []

    def add(change, code, who, before, after, delta=None):
        src = b if code in b.index else a
        rows.append(
            dict(
                category="Resources",
                change=change,
                task_code=code,
                task_name=src.loc[code, "task_name"] if code in src.index else None,
                wbs_code=src.loc[code, "wbs_code"] if code in src.index else None,
                field=f"assignment {who}",
                before=before,
                after=after,
                delta=delta,
                unit="units" if delta is not None else "",
            )
        )

    common = set(a.index) & set(b.index)  # added / deleted activities are in Scope already
    for code, who in sorted(set(un.index) - set(uo.index)):
        if code in common:
            add("resource assigned", code, who, None, un[(code, who)])
    for code, who in sorted(set(uo.index) - set(un.index)):
        if code in common:
            add("resource removed", code, who, uo[(code, who)], None)
    for key in sorted(set(uo.index) & set(un.index)):
        d = round(float(un[key] - uo[key]), 2)
        if d:
            add("budgeted units changed", key[0], key[1], uo[key], un[key], d)
    return rows


def _relationship_changes(old: Snapshot, new: Snapshot, b: pd.DataFrame, a: pd.DataFrame) -> list[dict]:
    def by_pair(rel: pd.DataFrame) -> dict[tuple[str, str], set[tuple[str, float, float]]]:
        # identity on the lag in hours (what P6 stores); days only for display, since they
        # depend on the predecessor's calendar
        out: dict = {}
        for p, s, t, lag_h, lag_d in rel[["pred_code", "succ_code", "type", "lag_hr", "lag_d"]].itertuples(index=False):
            out.setdefault((p, s), set()).add((t, round(float(lag_h or 0), 2), round(float(lag_d or 0), 2)))
        return out

    def label(links: set) -> str:
        return ", ".join(f"{t}{lag_d:+g}d" if lag_h else t for t, lag_h, lag_d in sorted(links))

    po, pn = by_pair(old.relationships), by_pair(new.relationships)
    rows = []

    def add(change, pred, succ, before, after):
        src = b if succ in b.index else a
        rows.append(
            dict(
                category="Relationships",
                change=change,
                task_code=succ,
                task_name=src.loc[succ, "task_name"] if succ in src.index else None,
                wbs_code=src.loc[succ, "wbs_code"] if succ in src.index else None,
                field=f"{pred} → {succ}",
                before=before,
                after=after,
                delta=None,
                unit="",
            )
        )

    for pair in sorted(set(pn) - set(po)):
        add("added", *pair, "", label(pn[pair]))
    for pair in sorted(set(po) - set(pn)):
        add("deleted", *pair, label(po[pair]), "")
    for pair in sorted(set(po) & set(pn)):
        if {x[:2] for x in po[pair]} != {x[:2] for x in pn[pair]}:
            same_types = {x[0] for x in po[pair]} == {x[0] for x in pn[pair]}
            add("lag changed" if same_types else "type changed", *pair, label(po[pair]), label(pn[pair]))
    return rows


def summary(log: pd.DataFrame) -> pd.DataFrame:
    """Count of changes per category and kind (project rows excluded)."""
    x = log[log["category"] != "Project"]
    return x.groupby(["category", "change"], observed=True).size().rename("count").reset_index()
