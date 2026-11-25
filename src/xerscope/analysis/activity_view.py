"""The activities of one update as a table of named, typed columns, and a structured query over it.

The view (``activity_view``) holds what a planner asks about, as P6 reads it: the dates, floats and
durations of ``Snapshot.activities`` in days of each activity's calendar, the flags (milestone, LOE,
critical, longest path, hard constraint), the WBS node, the resources, one column per activity code
type of the file (``code: <type>``, its value and name), and, given the update before, how many
working days each finish moved since. Every column is described in ``Column`` (kind, English and
French words), so a reader, or the local agent, can name one without seeing the data.

A query (``Query``) is a list of conditions, a sort, a limit and an optional grouping. ``run`` checks
it against the columns (a column, an operator or a value of the wrong kind is a ``QueryError``) and
applies it as the steps of a ``populations.Funnel``, one named step per condition, source ``ask``: the
Gantt Ask field shows them as it shows the grammar's. A text value compared with ``=`` must be one the
column holds: a value the file does not hold is refused, never matched loosely.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..xer import Snapshot
from ..xer.model import STATUS
from .ask.text import fold
from .populations import Funnel

TEXT, NUMBER, DATE, FLAG = "text", "number", "date", "flag"
OPERATORS = {
    TEXT: ("=", "!=", "contains", "not_contains"),
    NUMBER: ("=", "!=", "<", "<=", ">", ">="),
    DATE: ("=", "!=", "<", "<=", ">", ">="),
    FLAG: ("is_true", "is_false"),
}
ALL_OPERATORS = tuple(dict.fromkeys(op for ops in OPERATORS.values() for op in ops))
CODE_PREFIX = "code: "
SOURCE = "ask"
MAX_LIMIT = 50
STATUSES = tuple(STATUS.values())  # the model's own words: "Not started", "In progress", "Complete"


class QueryError(ValueError):
    """A query names a column, an operator or a value the view does not have."""


@dataclass(frozen=True)
class Column:
    """One column of the view.

    Its name, kind, the words that say it, and the values it takes when they are a fixed list.
    """

    name: str
    kind: str
    english: str
    french: str
    values: tuple[str, ...] = ()


# name, source column of Snapshot.activities, kind, English, French
_BASE = [
    ("activity_id", "task_code", TEXT, "Activity ID", "ID d'activité"),
    ("activity_name", "task_name", TEXT, "activity name", "nom de l'activité"),
    ("status", "status", TEXT, "status", "statut"),
    ("start", "start", DATE, "start (actual once started)", "début (réel une fois commencée)"),
    ("finish", "finish", DATE, "finish (actual once finished)", "fin (réelle une fois terminée)"),
    ("total_float_d", "total_float_d", NUMBER, "total float, working days", "marge totale, jours ouvrés"),
    ("free_float_d", "free_float_d", NUMBER, "free float, working days", "marge libre, jours ouvrés"),
    ("remaining_d", "remaining_d", NUMBER, "remaining duration, working days", "durée restante, jours ouvrés"),
    ("original_d", "original_d", NUMBER, "original duration, working days", "durée initiale, jours ouvrés"),
    ("percent_complete", "pct_complete", NUMBER, "percent complete", "avancement en %"),
    ("milestone", "is_milestone", FLAG, "is a milestone", "est un jalon"),
    ("level_of_effort", "is_loe", FLAG, "is a level of effort", "est une activité LOE"),
    ("critical", "is_critical", FLAG, "critical (total float at or under the critical float)", "critique"),
    ("on_longest_path", "on_longest_path", FLAG, "on the longest path", "sur le chemin le plus long"),
    ("hard_constraint", "has_hard_constraint", FLAG, "has a hard constraint", "a une contrainte forte"),
    ("wbs", "wbs_code", TEXT, "WBS code", "code WBS"),
    ("labor_budget_hr", "labor_budget_hr", NUMBER, "labour budget, hours", "budget main-d'œuvre, heures"),
    ("labor_remaining_hr", "labor_remaining_hr", NUMBER, "labour remaining, hours", "main-d'œuvre restante, heures"),
]


@dataclass(frozen=True)
class View:
    """The view of one update: one row per activity, indexed by Activity ID, and its columns.

    ``names``: for a code column, the name of each row's value ("Génie civil" for "GC"), compared
    with ``=`` as the value is. A value of a column's fixed list (``Column.values``) that no
    activity holds keeps none; any other value no activity holds is refused.
    """

    frame: pd.DataFrame
    columns: tuple[Column, ...]
    names: dict[str, pd.Series] = field(default_factory=dict)

    def column(self, name: str) -> Column:
        """Return the column named ``name``; ``QueryError`` when the view has none."""
        for column in self.columns:
            if column.name == name:
                return column
        raise QueryError(f"no column {name!r}")


def activity_view(snapshot: Snapshot, previous: Snapshot | None = None) -> View:
    """Build the view of ``snapshot``; with ``previous``, ``finish_moved_wd`` since that update."""
    activities = snapshot.activities.drop_duplicates("task_code").set_index("task_code", drop=False)
    frame = pd.DataFrame({name: activities[source] for name, source, *_ in _BASE}, index=activities.index)
    columns = [Column(name, kind, en, fr, STATUSES if name == "status" else ()) for name, _, kind, en, fr in _BASE]
    wbs_names = snapshot.wbs.set_index("wbs_id")["wbs_name"] if "wbs_name" in snapshot.wbs else pd.Series(dtype=str)
    frame["wbs_name"] = activities["wbs_id"].map(wbs_names)
    columns.append(Column("wbs_name", TEXT, "WBS node name", "nom du nœud WBS"))
    frame["resources"] = _resources(snapshot).reindex(frame.index).fillna("")
    columns.append(Column("resources", TEXT, "resources assigned (short names and names)", "ressources affectées"))
    if previous is not None:
        frame["finish_moved_wd"] = _finish_moved_wd(snapshot, previous, activities)
        columns.append(
            Column(
                "finish_moved_wd",
                NUMBER,
                "working days the finish moved since the update before (later is negative)",
                "jours ouvrés de décalage de la fin depuis la mise à jour précédente (plus tard = négatif)",
            )
        )
    names = {}
    for type_name, values, value_names in _code_columns(snapshot):
        name = f"{CODE_PREFIX}{type_name}"
        frame[name] = values.reindex(frame.index)
        names[name] = value_names.reindex(frame.index)
        columns.append(
            Column(name, TEXT, f"activity code {type_name} (its value or name)", f"code d'activité {type_name}")
        )
    return View(frame, tuple(columns), names)


def _resources(snapshot: Snapshot) -> pd.Series:
    assignments = snapshot.assignments
    if assignments.empty:
        return pd.Series(dtype=str)
    words = (
        assignments["rsrc_short_name"].fillna("").astype(str) + " " + assignments["rsrc_name"].fillna("").astype(str)
    )
    return words.str.strip().groupby(assignments["task_code"]).agg(lambda held: "; ".join(sorted(set(held))))


def _finish_moved_wd(snapshot: Snapshot, previous: Snapshot, activities: pd.DataFrame) -> pd.Series:
    before = activities["task_code"].map(previous.by_code["finish"]) if not previous.by_code.empty else None
    if before is None:
        return pd.Series(float("nan"), index=activities.index)
    known = before.notna() & activities["finish"].notna()
    moved = pd.Series(float("nan"), index=activities.index)
    worked = snapshot.working_days(activities.loc[known, "clndr_id"], before[known], activities.loc[known, "finish"])
    moved[known] = 0.0 - worked.round(2)  # a finish that went later reads negative, as everywhere in xerscope
    return moved


def _code_columns(snapshot: Snapshot):
    """Per activity code type of the file: its name, the value per activity, the value's name."""
    links, values = snapshot.task_codes, snapshot.code_values
    if links.empty or values.empty:
        return
    held = links.merge(values[["code_type", "code_id", "value", "name", "type_name"]], on=["code_type", "code_id"])
    for type_name, group in held.groupby("type_name", sort=True):
        rows = group.drop_duplicates("task_code").set_index("task_code")
        yield str(type_name), rows["value"].astype(str), rows["name"].astype(str)


# --- the query ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Condition:
    """One condition on a column: ``column op value`` ("total_float_d < 5"; a flag takes no value)."""

    column: str
    op: str
    value: str = ""


@dataclass(frozen=True)
class Query:
    """Conditions (all must hold), then a sort, a limit and an optional grouping."""

    conditions: tuple[Condition, ...] = ()
    sort_by: str = ""
    descending: bool = False
    limit: int = 10
    group_by: str = ""


@dataclass(frozen=True)
class Result:
    """The funnel of the conditions, the rows sorted and cut to the limit, the groups (value -> count)."""

    funnel: Funnel
    first: pd.DataFrame
    groups: dict[str, int]

    @property
    def count(self) -> int:
        """How many activities meet every condition."""
        return len(self.funnel.rows)


def run(view: View, query: Query, data_date=None) -> Result:
    """Apply ``query`` to ``view``; ``QueryError`` when it names what the view does not have."""
    funnel = Funnel(view.frame.copy(), data_date=data_date)
    for condition in query.conditions:
        column = view.column(condition.column)
        if condition.op not in OPERATORS[column.kind]:
            raise QueryError(f"{condition.op!r} does not apply to {column.name} ({column.kind})")
        test = _test(view, column, condition)
        funnel.keep(describe(condition), SOURCE, test)
    rows = funnel.rows
    if query.sort_by:
        view.column(query.sort_by)
        rows = rows.sort_values(query.sort_by, ascending=not query.descending, na_position="last")
    groups: dict[str, int] = {}
    if query.group_by:
        if view.column(query.group_by).kind != TEXT:
            raise QueryError(f"{query.group_by} is not a column of words to group by")
        groups = {str(k): int(v) for k, v in rows[query.group_by].fillna("(none)").value_counts().items()}
    return Result(funnel, rows.head(max(1, min(query.limit, MAX_LIMIT))), groups)


def describe(condition: Condition) -> str:
    """Write the condition as one funnel step's label: "total_float_d < 5", "critical"."""
    if condition.op == "is_true":
        return condition.column
    if condition.op == "is_false":
        return f"not {condition.column}"
    return f"{condition.column} {condition.op.replace('_', ' ')} {condition.value}"


def _test(view: View, column: Column, condition: Condition):
    series = view.frame[column.name]
    if column.kind == FLAG:
        flags = series.fillna(False).astype(bool)
        return lambda rows: flags.reindex(rows.index) if condition.op == "is_true" else ~flags.reindex(rows.index)
    if column.kind == TEXT:
        return _text_test(view, column, condition, series)
    value = _number(condition.value) if column.kind == NUMBER else _date(condition.value)
    compare = {
        "=": series.eq,
        "!=": series.ne,
        "<": series.lt,
        "<=": series.le,
        ">": series.gt,
        ">=": series.ge,
    }[condition.op](value)
    return lambda rows: compare.reindex(rows.index).fillna(False)


def _text_test(view: View, column: Column, condition: Condition, series: pd.Series):
    wanted = fold(condition.value).strip()
    if not wanted:
        raise QueryError(f"no value given for {column.name}")
    said = series.fillna("").astype(str).map(fold)
    named = view.names.get(column.name, pd.Series(dtype=str)).reindex(series.index).fillna("").astype(str).map(fold)
    if condition.op in ("contains", "not_contains"):
        found = said.str.contains(wanted, regex=False) | named.str.contains(wanted, regex=False)
        return lambda rows: (found if condition.op == "contains" else ~found).reindex(rows.index).fillna(False)
    equal = said.eq(wanted) | named.eq(wanted)
    known = {fold(value) for value in column.values}  # a fixed list: a value of it may hold no activity
    if not equal.any() and wanted not in known:
        raise QueryError(f"{column.name} holds no value {condition.value!r} in this update")
    return lambda rows: (equal if condition.op == "=" else ~equal).reindex(rows.index).fillna(False)


def _number(text: str) -> float:
    try:
        return float(str(text).replace(",", ".").strip())
    except ValueError as error:
        raise QueryError(f"{text!r} is not a number") from error


def _date(text: str) -> pd.Timestamp:
    try:
        return pd.Timestamp(str(text).strip())
    except ValueError as error:
        raise QueryError(f"{text!r} is not a date (YYYY-MM-DD)") from error
