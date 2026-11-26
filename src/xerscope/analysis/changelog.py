"""What changed between two XER files of the same project (activities matched by ID).

One row per change: ``category, change, task_code, task_name, wbs_code, field, before,
after, delta, unit``. ``before`` / ``after`` are display strings (dates, numbers and text
mix in one column); ``delta`` is numeric where it means something: working days on the
activity's calendar for dates and durations, points for % complete, hours for budgets.

Sign of ``delta``. A start, a finish or the forecast finish of the project: working days gained
(+) or lost (-), so a date that goes later reads negative, as the finish variances do. Every
other row is after minus before (a duration from 10 to 15 days reads +5); the status date row
is the working days elapsed between the two updates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..store import SnapshotStore
from ..xer import Snapshot
from ..xer.model import SCHEDULE_OPTIONS
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
    "Calendars",
    "Options",
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
        + _calendar_definition_changes(old, new)
        + _option_changes(old, new)
    )
    frame = _to_frame(changes, previous_all, current_all)
    frame["category"] = pd.Categorical(frame["category"], CATEGORIES, ordered=True)
    return frame.sort_values(["category", "change", "task_code"], kind="stable").reset_index(drop=True)


def _project_changes(old: Snapshot, new: Snapshot, previous_all: pd.DataFrame, current_all: pd.DataFrame) -> list:
    data_date_shift = new.project_working_days(old.data_date, new.data_date) if old.data_date is not None else None
    # days lost read negative; 0.0 - x, not -x: a finish that did not move stays 0.0, never -0.0
    finish_shift = (
        0.0 - new.project_working_days(old.finish_date, new.finish_date) if old.finish_date is not None else None
    )
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
    # work under way loses remaining duration as it progresses; on work not started a cut is a plan change
    cut = (current["remain_drtn_hr_cnt"] < previous["remain_drtn_hr_cnt"] - 1e-9) & ~current["is_started"]
    for code in previous.index[cut]:
        before, after = previous.loc[code, "remaining_d"], current.loc[code, "remaining_d"]
        delta = after - old_in_new_days.loc[code, "remain_drtn_hr_cnt"]
        changes.append(
            _change("Durations", "remaining duration cut", code, "remaining duration", before, after, delta, "wd")
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
        # working days gained (+) or lost (-): a date that goes later reads negative
        move = 0.0 - new.working_days(current["clndr_id"], previous[column], current[column]).round(2)
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


def constraint_changes(old: Snapshot, new: Snapshot, task_codes: list[str]) -> pd.DataFrame:
    """The changelog's Constraints rows (primary and secondary: added, removed, changed) of the
    activities ``task_codes`` present in both updates; the same rows ``changelog`` lists for them."""
    common = [code for code in task_codes if code in old.by_code.index and code in new.by_code.index]
    previous, current = old.by_code.loc[common], new.by_code.loc[common]
    return _to_frame(_constraint_changes(previous, current), previous, current)


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
            # key is a (task_code, resource) pair, the two index levels of ``units``: *key fills task_code and who
            changes.append(
                assignment_change(  # type: ignore[call-arg]
                    "budgeted units changed", *key, old_units[key], new_units[key], delta
                )
            )
    return changes


Link = tuple[str, float, float]  # relationship type, lag in hours, lag in days


def _relationship_changes(old: Snapshot, new: Snapshot) -> list:
    old_links, new_links = _links_by_pair(old.relationships), _links_by_pair(new.relationships)
    changes = []
    for pair in sorted(set(new_links) - set(old_links)):
        changes.append(_relationship_change("added", pair, "", _links_label(new_links[pair])))
    for pair in sorted(set(old_links) - set(new_links)):
        changes.append(_relationship_change("deleted", pair, _links_label(old_links[pair]), ""))
    for pair in sorted(set(old_links) & set(new_links)):
        change = _what_changed(old_links[pair], new_links[pair])
        if change:
            before, after = _links_label(old_links[pair]), _links_label(new_links[pair])
            changes.append(_relationship_change(change, pair, before, after))
    return changes


def _links_by_pair(relationships: pd.DataFrame) -> dict[tuple[str, str], set[Link]]:
    """The links of each (predecessor, successor) pair: two activities may be tied more than once.

    A link is identified by its lag in hours (what P6 stores); the days are kept for display only,
    since they depend on the predecessor's calendar."""
    pairs: dict[tuple[str, str], set[Link]] = {}
    columns = ["pred_code", "succ_code", "type", "lag_hr", "lag_d"]
    for predecessor, successor, link_type, lag_hr, lag_d in relationships[columns].itertuples(index=False):
        link = (link_type, round(float(lag_hr or 0), 2), round(float(lag_d or 0), 2))
        pairs.setdefault((predecessor, successor), set()).add(link)
    return pairs


def _links_label(links: set[Link]) -> str:
    """The links of a pair as the log writes them: "FS, SS+2d"."""
    return ", ".join(f"{link_type}{lag_d:+g}d" if lag_hr else link_type for link_type, lag_hr, lag_d in sorted(links))


def _what_changed(old_links: set[Link], new_links: set[Link]) -> str:
    """What moved between two updates of a pair's links: "type changed", "lag changed", or "" for neither."""
    if {link[:2] for link in old_links} == {link[:2] for link in new_links}:
        return ""
    same_types = {link[0] for link in old_links} == {link[0] for link in new_links}
    return "lag changed" if same_types else "type changed"


def _relationship_change(change: str, pair: tuple[str, str], before: str, after: str):
    predecessor, successor = pair
    return _change("Relationships", change, successor, f"{predecessor} → {successor}", before, after)


def _calendar_definition(calendar) -> tuple:
    """What makes a calendar's working time: hours per day, the week, the dated exceptions.
    ``WorkCalendar`` compares without its exceptions (they are a cache-friendly dict); a holiday
    added or removed moves dates all the same, so they are compared here."""
    return (calendar.hours_per_day, calendar.week, tuple(sorted(calendar.exceptions.items())))


def _calendar_definition_changes(old: Snapshot, new: Snapshot) -> list:
    """One row per calendar of both updates whose working time differs: a calendar edited in P6
    moves every date on it without any activity row changing."""
    changes = []
    for clndr_id in sorted(set(old.work_calendars) & set(new.work_calendars)):
        before, after = old.work_calendars[clndr_id], new.work_calendars[clndr_id]
        if _calendar_definition(before) != _calendar_definition(after):
            changes.append(_change("Calendars", "working time changed", "", after.name, before.name, after.name))
    return changes


def _option_value(options: dict, keys: tuple[str, ...]):
    """Value at ``keys`` in ``Snapshot.options`` (``options["sched"][...]`` for the raw row); None when absent
    or blank, so a blank and an absent option read equal."""
    value: object = options
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return None if value in ("", None) else value


def _option_changes(old: Snapshot, new: Snapshot) -> list:
    """One row per scheduling option of ``SCHEDULE_OPTIONS`` that differs: the same file scheduled
    under another option gives other dates, so a half-step reading must know of it. The option and
    its values carry their P6 names (``xer.model.ScheduleOption``)."""
    changes = []
    for option in SCHEDULE_OPTIONS:
        before, after = _option_value(old.options, option.keys), _option_value(new.options, option.keys)
        if before != after:
            named = option.value_name(before), option.value_name(after)
            changes.append(_change("Options", "scheduling option changed", "", option.name, *named))
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


# the kinds _progress_changes writes for an actual date edited or removed after being reported
RETROACTIVE_ACTUALS = (
    "actual start changed (retroactive)",
    "actual finish changed (retroactive)",
    "actual start removed",
    "actual finish removed",
)


def count_changes(counts: pd.DataFrame, category: str, *changes: str) -> int:
    """Number of changes in a category, optionally only of the given kinds (from :func:`summary`)."""
    in_category = counts["category"] == category
    wanted = counts["change"].isin(changes) if changes else True
    return int(counts[in_category & wanted]["count"].sum())


def headline_counts(counts: pd.DataFrame) -> dict[str, int]:
    """The counts the Changelog page shows above its tables (from :func:`summary`): tasks added
    and deleted, relationship changes, duration changes, actual dates edited or removed after
    being reported, tasks that became critical."""
    return {
        "added": count_changes(counts, "Scope", "added"),
        "deleted": count_changes(counts, "Scope", "deleted"),
        "logic": count_changes(counts, "Relationships"),
        "durations": count_changes(counts, "Durations"),
        "retroactive_actuals": count_changes(counts, "Progress", *RETROACTIVE_ACTUALS),
        "became_critical": count_changes(counts, "Float", "became critical"),
    }


def forecast_finish(log: pd.DataFrame) -> tuple[pd.Timestamp | None, float | None]:
    """The forecast finish of the newer update and its shift since the older one, read in the
    project row every log has (:func:`_project_changes`). The finish is None when the newer
    update has none. The shift is in working days of the project calendar, days lost negative;
    None when the older update has no finish."""
    row = log[(log["category"] == "Project") & (log["change"] == "forecast finish")].iloc[0]
    finish = pd.Timestamp(row["after"]) if row["after"] else None
    shift_wd = None if pd.isna(row["delta"]) else float(row["delta"])
    return finish, shift_wd


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
