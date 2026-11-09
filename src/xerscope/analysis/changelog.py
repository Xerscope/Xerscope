"""What changed between two XER files of the same project (activities matched by ID).

One row per change: ``category, change, task_code, task_name, wbs_code, field, before,
after, delta, unit``. ``before`` / ``after`` are display strings (dates, numbers and text
mix in one column); ``delta`` is numeric where it means something: working days on the
activity's calendar for dates and durations, points for % complete, hours for budgets.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..store import SnapshotStore
from ..xer import Snapshot
from .populations import joined_sorted

CATEGORIES = [
    "Project",
    "Scope",
    "Tasks",
    "Durations",
    "Relationships",
    "Progress",
    "Dates",
    "Float",
    "Constraints",
    "Resources",
]
COLS = ["category", "change", "task_code", "task_name", "wbs_code", "field", "before", "after", "delta", "unit"]


def _format_value(value) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    if isinstance(value, pd.Timestamp):
        return f"{value:%Y-%m-%d %H:%M}"
    if isinstance(value, (float, np.floating)):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _change(category, change, task_code, field, before, after, delta=None, unit=""):
    """One change as a plain tuple; :func:`_to_frame` adds the activity name and WBS."""
    return (category, change, task_code, field, before, after, delta, unit)


def _to_frame(changes: list[tuple], previous: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Rows with the activity name and WBS looked up in the new update, else in the old one."""
    rows = []
    for category, change, task_code, field, before, after, delta, unit in changes:
        source = current if task_code in current.index else previous
        known = task_code in source.index
        rows.append(
            {
                "category": category,
                "change": change,
                "task_code": task_code,
                "task_name": source.loc[task_code, "task_name"] if known else None,
                "wbs_code": source.loc[task_code, "wbs_code"] if known else None,
                "field": field,
                "before": before,
                "after": after,
                "delta": delta,
                "unit": unit,
            }
        )
    frame = pd.DataFrame(rows, columns=COLS)
    for column in ("before", "after"):
        frame[column] = frame[column].map(_format_value)
    frame["delta"] = pd.to_numeric(frame["delta"], errors="coerce")
    return frame


def _differs(before: pd.Series, after: pd.Series) -> pd.Series:
    """True where the value changed (two missing values are equal)."""
    return ~((before == after) | (before.isna() & after.isna()))


def changelog(old: Snapshot, new: Snapshot) -> pd.DataFrame:
    previous_all = old.by_code
    current_all = new.by_code
    common = sorted(set(previous_all.index) & set(current_all.index))
    previous, current = previous_all.loc[common], current_all.loc[common]
    changes = (
        _project_changes(old, new, previous_all, current_all)
        + _scope_changes(previous_all, current_all)
        + _activity_changes(old, new, previous, current)
        + _duration_changes(previous, current)
        + _progress_changes(previous, current)
        + _date_and_float_changes(new, previous, current)
        + _constraint_changes(previous, current)
        + _budget_changes(previous, current)
        + _assignment_changes(old, new, previous_all, current_all)
        + _relationship_changes(old, new)
    )
    frame = _to_frame(changes, previous_all, current_all)
    frame["category"] = pd.Categorical(frame["category"], CATEGORIES, ordered=True)
    return frame.sort_values(["category", "change", "task_code"], kind="stable").reset_index(drop=True)


def _project_changes(old: Snapshot, new: Snapshot, previous_all: pd.DataFrame, current_all: pd.DataFrame) -> list:
    data_date_shift = new.project_working_days(old.data_date, new.data_date) if old.data_date is not None else None
    finish_shift = new.project_working_days(old.finish_date, new.finish_date) if old.finish_date is not None else None
    old_links, new_links = len(old.relationships), len(new.relationships)
    old_count, new_count = len(previous_all), len(current_all)
    return [
        _change("Project", "status date", "", "status date", old.data_date, new.data_date, data_date_shift, "wd"),
        _change(
            "Project", "forecast finish", "", "forecast finish", old.finish_date, new.finish_date, finish_shift, "wd"
        ),
        _change("Project", "activities", "", "activities", old_count, new_count, new_count - old_count),
        _change("Project", "relationships", "", "relationships", old_links, new_links, new_links - old_links),
    ]


def _scope_changes(previous_all: pd.DataFrame, current_all: pd.DataFrame) -> list:
    changes = []
    for code in sorted(set(current_all.index) - set(previous_all.index)):
        changes.append(_change("Scope", "added", code, "activity", None, current_all.loc[code, "task_name"]))
    for code in sorted(set(previous_all.index) - set(current_all.index)):
        changes.append(_change("Scope", "deleted", code, "activity", previous_all.loc[code, "task_name"], None))
    return changes


def _activity_changes(old: Snapshot, new: Snapshot, previous: pd.DataFrame, current: pd.DataFrame) -> list:
    # show calendar names rather than ids; the old update's name wins when both define an id
    calendar_names = {cid: cal.name for cid, cal in new.work_calendars.items()} | {
        cid: cal.name for cid, cal in old.work_calendars.items()
    }
    changes = []
    for column, change in [
        ("task_name", "renamed"),
        ("wbs_code", "moved to another WBS"),
        ("type", "type changed"),
        ("clndr_id", "calendar changed"),
    ]:
        for code in previous.index[_differs(previous[column], current[column])]:
            before, after = previous.loc[code, column], current.loc[code, column]
            if column == "clndr_id":
                before, after = calendar_names.get(before, before), calendar_names.get(after, after)
            changes.append(_change("Tasks", change, code, column, before, after))
    return changes


def _duration_changes(previous: pd.DataFrame, current: pd.DataFrame) -> list:
    """Durations compared in hours, as P6 stores them: a calendar change alone re-expresses the same
    hours in other days. The delta is in days of the new calendar, the old duration converted on it."""
    changes = []
    old_in_new_days = previous[["target_drtn_hr_cnt", "remain_drtn_hr_cnt"]].div(current["hours_per_day"], axis=0)
    for code in previous.index[_differs(previous["target_drtn_hr_cnt"], current["target_drtn_hr_cnt"])]:
        before, after = previous.loc[code, "original_d"], current.loc[code, "original_d"]
        delta = after - old_in_new_days.loc[code, "target_drtn_hr_cnt"]
        changes.append(
            _change("Durations", "original duration changed", code, "original duration", before, after, delta, "wd")
        )
    grew = (current["remain_drtn_hr_cnt"] > previous["remain_drtn_hr_cnt"] + 1e-9) & ~current["is_complete"]
    for code in previous.index[grew]:
        before, after = previous.loc[code, "remaining_d"], current.loc[code, "remaining_d"]
        delta = after - old_in_new_days.loc[code, "remain_drtn_hr_cnt"]
        changes.append(
            _change("Durations", "remaining duration increased", code, "remaining duration", before, after, delta, "wd")
        )
    return changes


def _progress_changes(previous: pd.DataFrame, current: pd.DataFrame) -> list:
    changes = []
    status_rank = {"Not started": 0, "In progress": 1, "Complete": 2}
    for code in previous.index[_differs(previous["status"], current["status"])]:
        before, after = previous.loc[code, "status"], current.loc[code, "status"]
        if status_rank.get(after, 0) < status_rank.get(before, 0):
            change = "status reverted"
        elif after == "Complete":
            change = "finished"
        else:
            change = "started"
        changes.append(_change("Progress", change, code, "status", before, after))
    for column, label in [("act_start_date", "actual start"), ("act_end_date", "actual finish")]:
        before, after = previous[column], current[column]
        moved = before.notna() & after.notna() & (before != after)
        removed = before.notna() & after.isna()
        for code in previous.index[moved]:
            changes.append(
                _change("Progress", f"{label} changed (retroactive)", code, label, before[code], after[code])
            )
        for code in previous.index[removed]:
            changes.append(_change("Progress", f"{label} removed", code, label, before[code], None))
    pct_gain = (current["pct_complete"] - previous["pct_complete"]).round(2)
    for code in previous.index[pct_gain.fillna(0) != 0]:
        before, after = previous.loc[code, "pct_complete"], current.loc[code, "pct_complete"]
        changes.append(_change("Progress", "% complete", code, "% complete", before, after, pct_gain[code], "pts"))
    return changes


def _date_and_float_changes(new: Snapshot, previous: pd.DataFrame, current: pd.DataFrame) -> list:
    """Open work only: actuals of finished work are covered by the progress changes."""
    changes = []
    is_open = ~current["is_complete"]
    for column, label in [("start", "start moved"), ("finish", "finish moved")]:
        move = new.working_days(current["clndr_id"], previous[column], current[column]).round(2)
        for code in previous.index[is_open & (move.abs() > 0.005)]:
            before, after = previous.loc[code, column], current.loc[code, column]
            changes.append(_change("Dates", label, code, column, before, after, move[code], "wd"))
    # in hours, as P6 stores float (a calendar change alone re-expresses the same hours in other
    # days), the delta in days of the new calendar, as for durations
    float_change = ((current["total_float_hr_cnt"] - previous["total_float_hr_cnt"]) / current["hours_per_day"]).where(
        previous["total_float_d"].notna() & current["total_float_d"].notna()
    )
    float_change = float_change.round(2)
    for code in previous.index[is_open & (float_change.abs() > 0.005)]:
        before, after = previous.loc[code, "total_float_d"], current.loc[code, "total_float_d"]
        changes.append(
            _change("Float", "total float changed", code, "total float", before, after, float_change[code], "wd")
        )
    for code in previous.index[~previous["is_critical"] & current["is_critical"]]:
        changes.append(_change("Float", "became critical", code, "critical", "no", "yes"))
    for code in previous.index[previous["is_critical"] & ~current["is_critical"] & is_open]:
        changes.append(_change("Float", "no longer critical", code, "critical", "yes", "no"))
    return changes


def _constraint_changes(previous: pd.DataFrame, current: pd.DataFrame) -> list:
    changes = []
    for type_column, date_column, label in [
        ("cstr_type", "cstr_date", "primary constraint"),
        ("cstr_type2", "cstr_date2", "secondary constraint"),
    ]:
        type_before = previous[type_column].replace("", np.nan)
        type_after = current[type_column].replace("", np.nan)
        date_changed = _differs(previous[date_column], current[date_column])
        differs = _differs(type_before, type_after) | (type_before.notna() & date_changed)
        for code in previous.index[differs]:
            had_before, has_after = pd.notna(type_before[code]), pd.notna(type_after[code])
            before = f"{type_before[code]} {_format_value(previous.loc[code, date_column])}" if had_before else ""
            after = f"{type_after[code]} {_format_value(current.loc[code, date_column])}" if has_after else ""
            if not had_before:
                change = "added"
            elif not has_after:
                change = "removed"
            else:
                change = "changed"
            changes.append(_change("Constraints", f"{label} {change}", code, label, before.strip(), after.strip()))
    return changes


def _budget_changes(previous: pd.DataFrame, current: pd.DataFrame) -> list:
    hours_change = (current["labor_budget_hr"] - previous["labor_budget_hr"]).round(2)
    changes = []
    for code in previous.index[hours_change.fillna(0) != 0]:
        before, after = previous.loc[code, "labor_budget_hr"], current.loc[code, "labor_budget_hr"]
        changes.append(
            _change(
                "Resources",
                "budgeted labour hours changed",
                code,
                "budget labour h",
                before,
                after,
                hours_change[code],
                "h",
            )
        )
    return changes


def _assignment_changes(old: Snapshot, new: Snapshot, previous_all: pd.DataFrame, current_all: pd.DataFrame) -> list:
    """Resource assignments added / removed, and budgeted units changed, per activity and resource."""

    def units(snapshot: Snapshot) -> pd.Series:
        assignments = snapshot.assignments
        if assignments.empty:
            return pd.Series(dtype=float)
        who = assignments["rsrc_short_name"].fillna(assignments["rsrc_name"]).fillna(assignments["rsrc_id"]).astype(str)
        role_name = "role " + assignments["rsrc_name"].fillna(assignments["role_id"]).astype(str)
        who = who.where(assignments["rsrc_type"] != "role", role_name)
        return assignments["target_qty"].fillna(0.0).groupby([assignments["task_code"], who]).sum()

    def assignment_change(change, task_code, who, before, after, delta=None):
        unit = "units" if delta is not None else ""
        return _change("Resources", change, task_code, f"assignment {who}", before, after, delta, unit)

    old_units, new_units = units(old), units(new)
    changes = []
    # added / deleted activities are in Scope already
    both = set(previous_all.index) & set(current_all.index)
    for code, who in sorted(set(new_units.index) - set(old_units.index)):
        if code in both:
            changes.append(assignment_change("resource assigned", code, who, None, new_units[(code, who)]))
    for code, who in sorted(set(old_units.index) - set(new_units.index)):
        if code in both:
            changes.append(assignment_change("resource removed", code, who, old_units[(code, who)], None))
    for key in sorted(set(old_units.index) & set(new_units.index)):
        delta = round(float(new_units[key] - old_units[key]), 2)
        if delta:
            changes.append(assignment_change("budgeted units changed", *key, old_units[key], new_units[key], delta))
    return changes


def _relationship_changes(old: Snapshot, new: Snapshot) -> list:
    def by_pair(relationships: pd.DataFrame) -> dict[tuple[str, str], set[tuple[str, float, float]]]:
        # identity on the lag in hours (what P6 stores); days only for display, since they
        # depend on the predecessor's calendar
        pairs: dict = {}
        columns = ["pred_code", "succ_code", "type", "lag_hr", "lag_d"]
        for predecessor, successor, link_type, lag_hr, lag_d in relationships[columns].itertuples(index=False):
            pairs.setdefault((predecessor, successor), set()).add(
                (link_type, round(float(lag_hr or 0), 2), round(float(lag_d or 0), 2))
            )
        return pairs

    def label(links: set) -> str:
        return ", ".join(
            f"{link_type}{lag_d:+g}d" if lag_hr else link_type for link_type, lag_hr, lag_d in sorted(links)
        )

    def relationship_change(change, predecessor, successor, before, after):
        return _change("Relationships", change, successor, f"{predecessor} → {successor}", before, after)

    old_pairs, new_pairs = by_pair(old.relationships), by_pair(new.relationships)
    changes = []
    for pair in sorted(set(new_pairs) - set(old_pairs)):
        changes.append(relationship_change("added", *pair, "", label(new_pairs[pair])))
    for pair in sorted(set(old_pairs) - set(new_pairs)):
        changes.append(relationship_change("deleted", *pair, label(old_pairs[pair]), ""))
    for pair in sorted(set(old_pairs) & set(new_pairs)):
        if {link[:2] for link in old_pairs[pair]} != {link[:2] for link in new_pairs[pair]}:
            same_types = {link[0] for link in old_pairs[pair]} == {link[0] for link in new_pairs[pair]}
            change = "lag changed" if same_types else "type changed"
            changes.append(relationship_change(change, *pair, label(old_pairs[pair]), label(new_pairs[pair])))
    return changes


def summary(log: pd.DataFrame) -> pd.DataFrame:
    """Count of changes per category and kind (project rows excluded)."""
    without_project = log[log["category"] != "Project"]
    return without_project.groupby(["category", "change"], observed=True).size().rename("count").reset_index()


def category_totals(counts: pd.DataFrame) -> pd.DataFrame:
    """Per category: total number of changes and the sorted kinds of change seen (from :func:`summary`)."""
    totals = counts.groupby("category", observed=True)["count"].sum().rename("total").reset_index()
    kinds = counts.groupby("category", observed=True)["change"].apply(joined_sorted).rename("kinds")
    return totals.merge(kinds.reset_index(), on="category")


def weekly_change_counts(store: SnapshotStore) -> pd.DataFrame:
    """:func:`summary` of every consecutive pair of updates, tagged with the newer data date as ``week``."""
    frames = []
    for index in range(1, len(store)):
        counts = summary(changelog(store[index - 1], store[index]))
        counts["week"] = f"{store[index].data_date:%Y-%m-%d}"
        frames.append(counts)
    return pd.concat(frames, ignore_index=True)


def weekly_change_matrix(weekly: pd.DataFrame) -> pd.DataFrame:
    """Counts per (category, change) as rows and one column per week, from :func:`weekly_change_counts`."""
    return (
        weekly.pivot_table(index=["category", "change"], columns="week", values="count", aggfunc="sum", observed=True)
        .fillna(0)
        .astype(int)
        .reset_index()
    )
