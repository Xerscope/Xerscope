"""The Filter over the page's rows, as the steps of a population funnel."""

from __future__ import annotations

import operator
from dataclasses import dataclass

import pandas as pd

from ...xer import Snapshot
from ..baseline import Baseline
from ..populations import Funnel
from .filters import Filter
from .grammar import And, Atom, Expr, Not, Or
from .text import fold


@dataclass(frozen=True)
class Context:
    """What an atom may read besides the rows: the file (codes, assignments, links, calendars),
    the WBS tree and the page's baseline (for late)."""

    snapshot: Snapshot
    nodes: pd.DataFrame | None = None
    baseline: Baseline | None = None


def apply(
    ask: Filter,
    tasks: pd.DataFrame,
    snapshot: Snapshot,
    nodes: pd.DataFrame | None = None,
    baseline: Baseline | None = None,
) -> Funnel:
    """The sentence's filters as the steps of a ``Funnel`` over ``tasks`` (the page's frame, with
    its ``category`` column), one named step per filter understood, source ``ask``: a reader
    sees what each removed and how many are left, as under every check. ``nodes`` is the WBS
    tree (``analysis.wbs.tree``) for the branch step; without it a WBS filter is skipped.
    ``baseline``: the page's baseline, which "late" reads (P6-12); none: the planned finish. A
    sentence of which nothing was understood but words were left out keeps no row (the page
    then offers the closest labels), never every row."""
    funnel = Funnel(tasks, snapshot.data_date)
    if ask.empty and ask.ignored:
        return funnel.keep("nothing understood", "ask", lambda rows: pd.Series(False, index=rows.index))
    context = Context(snapshot, nodes, baseline)
    for label, expr in [*facet_steps(ask, tasks, snapshot, nodes), *ask.clauses]:
        # the default argument pins this step's expression; mypy rejects any lambda with one against Callable[[X], Y]
        funnel.keep(label, "ask", lambda rows, expr=expr: mask(expr, rows, context))  # type: ignore[misc]
    return funnel


def facet_steps(
    ask: Filter, tasks: pd.DataFrame, snapshot: Snapshot, nodes: pd.DataFrame | None
) -> list[tuple[str, Expr]]:
    """(step label, expression) of each facet the filter holds, as the funnel names them."""
    steps: list[tuple[str, Expr]] = []
    if ask.wbs_id and nodes is not None:  # a node of another update only: no row here
        node = nodes.loc[nodes["wbs_id"] == ask.wbs_id]
        label = f"{node.iloc[0]['wbs_code']} · {node.iloc[0]['wbs_name']}" if len(node) else "not in this update"
        steps.append((f"WBS {label}", Atom("wbs", ask.wbs_id)))
    if ask.status:
        steps.append((f"status {' / '.join(ask.status)}", _any("status", ask.status)))
    if ask.categories and "category" in tasks:
        steps.append((f"float {' / '.join(ask.categories)}", _any("float", ask.categories)))
    if ask.code_type and ask.code_ids:
        values = snapshot.code_values
        named = sorted(values.loc[values["code_id"].isin(ask.code_ids), "value"])
        steps.append((f"{ask.code_type} {' / '.join(named)}", _any("code", sorted(ask.code_ids))))
    if ask.resources:
        assigned = snapshot.assignments
        names = assigned.loc[assigned["rsrc_id"].isin(ask.resources), "rsrc_short_name"].dropna().unique()
        steps.append((f"resource {' / '.join(map(str, sorted(names)))}", _any("resource", sorted(ask.resources))))
    steps += [("milestones", Atom("milestone"))] if ask.milestones else []
    steps += [("level of effort", Atom("loe"))] if ask.loe else []
    if ask.search:  # every word, in any order (an AND of words, not one phrase)
        words = ask.search.split()
        steps.append(
            ("name contains " + " and ".join(f'"{w}"' for w in words), And(tuple(Atom("word", w) for w in words)))
        )
    return steps


def _any(kind: str, values) -> Expr:
    atoms = tuple(Atom(kind, v) for v in values)
    return atoms[0] if len(atoms) == 1 else Or(atoms)


def funnel_line(funnel: Funnel) -> str:
    """ "212 → WBS CIV · Civil works 48 → status Not started 30 → float Critical 3": the population
    step by step, in one line, for the page's caption."""
    return " → ".join([str(funnel.start), *(f"{step.label} {step.left}" for step in funnel.steps)])


def mask(expr: Expr, rows: pd.DataFrame, context: Context) -> pd.Series:
    """The rows in the set ``expr`` names: NOT the complement in ``rows``, OR the union, AND
    the intersection, each atom as ``ATOMS`` reads it (docs/architecture.md, Ask)."""
    if isinstance(expr, Not):
        return ~mask(expr.item, rows, context)
    if isinstance(expr, And | Or):
        parts = [mask(e, rows, context) for e in expr.items]
        out = parts[0]
        for part in parts[1:]:
            out = out & part if isinstance(expr, And) else out | part
        return out
    return ATOMS[expr.kind](rows, expr.value, context).fillna(False).astype(bool)


def all_words(rows: pd.DataFrame, words: list[str]) -> pd.Series:
    """Rows whose Activity ID or name holds every word, accents and case ignored, in any order."""
    text = rows["task_code"].map(fold) + " " + rows["task_name"].map(fold)
    kept = pd.Series(True, index=rows.index)
    for word in words:
        kept &= text.str.contains(fold(word), regex=False)
    return kept


def _wbs(rows: pd.DataFrame, value, context: Context) -> pd.Series:
    from ..wbs import subtree_ids

    if context.nodes is None or value not in set(context.nodes["wbs_id"]):
        return rows["wbs_id"] == value
    return rows["wbs_id"].isin(subtree_ids(context.nodes, value))


def _code(rows: pd.DataFrame, value, context: Context) -> pd.Series:
    values = context.snapshot.code_values
    code_type = values.loc[values["code_id"] == value, "code_type"]
    if code_type.empty:
        return pd.Series(False, index=rows.index)
    return rows["task_code"].isin(context.snapshot.tasks_with_codes(code_type.iloc[0], {value}))


def _resource(rows: pd.DataFrame, value, context: Context) -> pd.Series:
    assigned = context.snapshot.assignments
    return rows["task_code"].isin(set(assigned.loc[assigned["rsrc_id"] == value, "task_code"]))


def _category(rows: pd.DataFrame, value, context: Context) -> pd.Series:
    return rows["category"] == value if "category" in rows else pd.Series(False, index=rows.index)


def _compare(rows: pd.DataFrame, value, context: Context) -> pd.Series:
    """measure op number unit: hours against hours (a number of days times the activity's own
    hours per day), % complete against its percentage; total float only on open work."""
    measure, op, number, unit = value
    column = rows[MEASURE_COLUMNS[measure]]
    if measure == "tf":
        column = column.where(~rows["is_complete"].astype(bool))
    limit = number * rows["hours_per_day"] if unit == "d" else number
    return OPERATORS[op](column, limit)


def _dated(rows: pd.DataFrame, value, context: Context) -> pd.Series:
    """start or finish in [low, high); active: the activity overlaps [low, high)."""
    column, low, high = value
    first = rows["start"] if column == "active" else rows[column]
    last = rows["finish"] if column == "active" else rows[column]
    kept = pd.Series(True, index=rows.index)
    if high is not None:
        kept &= first < high
    if low is not None:
        kept &= last >= low
    return kept


def _constrained(rows: pd.DataFrame, value, context: Context) -> pd.Series:
    """Any primary or secondary constraint, or P6 Professional's hard / soft set (101248) with a
    start constraint ignored once started, as P6-02 and P6-03 count."""
    from ..p6.check_schedule import P6_HARD_CONSTRAINTS, SOFT_CONSTRAINTS
    from ..populations import constrained_by

    if value == "any":
        return rows["cstr_type"].fillna("").astype(str).ne("") | rows["cstr_type2"].fillna("").astype(str).ne("")
    kinds = P6_HARD_CONSTRAINTS if value == "hard" else SOFT_CONSTRAINTS
    return constrained_by(rows, kinds, ignore_started_starts=True)


def _late(rows: pd.DataFrame, value, context: Context) -> pd.Series:
    """P6 Check Schedule Late Activities (P6-12, 101248; finish variance in working time, 46278):
    open activities forecast to finish later than their baseline finish, the planned finish
    when the baseline has none (or no baseline is given). The set only: P6-12's population
    (milestones and LOE out) is the check's, so "jalons en retard" keeps its milestones."""
    finish = pd.Series(pd.NaT, index=rows.index, dtype="datetime64[ns]")
    if context.baseline is not None:
        finish = rows[["task_code"]].join(context.baseline.frame[["bl_finish"]], on="task_code")["bl_finish"]
    finish = finish.combine_first(rows["target_end_date"])
    variance = context.snapshot.work_hours(rows["clndr_id"], finish, rows["finish"])
    return ~rows["is_complete"].astype(bool) & (variance > 0)


def _linked(rows: pd.DataFrame, value, context: Context) -> pd.Series:
    """A predecessor (pred) or successor (succ) in the project, or in another project (as P6-01)."""
    from ..populations import has_predecessor_in_project, has_successor_in_project

    if value == "pred":
        return has_predecessor_in_project(context.snapshot, rows) | rows["has_external_pred"].astype(bool)
    return has_successor_in_project(context.snapshot, rows) | rows["has_external_succ"].astype(bool)


MEASURE_COLUMNS = {
    "tf": "total_float_hr_cnt",
    "od": "target_drtn_hr_cnt",
    "rd": "remain_drtn_hr_cnt",
    "pct": "pct_complete",
}
OPERATORS = {"<": operator.lt, "<=": operator.le, "=": operator.eq, ">=": operator.ge, ">": operator.gt}

ATOMS = {  # atom kind -> the rows it names
    "status": lambda rows, value, context: rows["status"] == value,
    "float": _category,  # viz.gantt.categorise: Critical follows the project's critical path definition
    "wbs": _wbs,  # the node's branch
    "code": _code,
    "resource": _resource,
    "milestone": lambda rows, value, context: rows["is_milestone"],
    "loe": lambda rows, value, context: rows["is_loe"],
    "word": lambda rows, value, context: all_words(rows, [value]),
    "late": _late,  # finish later than the baseline finish (P6-12); "negative float" is a tf comparison
    "id": lambda rows, value, context: rows["task_code"] == value,
    "cmp": _compare,
    "date": _dated,
    "constraint": _constrained,
    "pred": lambda rows, value, context: _linked(rows, "pred", context),
    "succ": lambda rows, value, context: _linked(rows, "succ", context),
    "longest": lambda rows, value, context: rows["on_longest_path"],  # P6's Longest Path flag (driving_path_flag)
}
