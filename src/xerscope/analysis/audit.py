"""What the Audit page shows: a check's sets, the check re-run with audited settings, its TOML.

    audited = with_settings(metric, target="< 3%", params={"limit_hours": 264})
    result = run_metric(audited, context)
    sets = split(result, snapshot)   # counted / checked, not counted / excluded
    sets_long(results, snapshot)     # every check's sets in one table, one row per item
    print(toml_block(audited))       # the [[metric]] table to paste into a standard file

The sets are cut from what the rule returned (``CheckResult.checked`` / ``counted`` /
``flagged``): nothing here decides which item a check counts.
"""

from __future__ import annotations

import dataclasses
import json
import typing
from dataclasses import dataclass

import pandas as pd

from .checks import CheckResult
from .populations import ACTIVITY_COLS, LINK_COLS, Funnel, Step, flagged_activities, flagged_relationships
from .rules import ALLOWED, RULES, Names
from .standards import Metric, parse_target

LINK_KEY = ["pred_code", "succ_code", "type"]


@dataclass
class AuditSets:
    counted: pd.DataFrame  # rows of the numerator
    not_counted: pd.DataFrame  # checked rows outside the numerator
    excluded: pd.DataFrame | None  # rows of the file outside the checked set; None when not comparable
    counted_outside: int = 0  # numerator rows outside the checked set (BEI: early completions)
    subject: str = "activities"


def _key(frame: pd.DataFrame, subject: str) -> pd.Series:
    if subject == "relationships":
        return frame[LINK_KEY].astype(str).agg("|".join, axis=1)
    if subject == "assignments":
        return frame["taskrsrc_id"].astype(str)
    return frame["task_code"].astype(str)


def _subject(frame: pd.DataFrame) -> str:
    if "taskrsrc_id" in frame.columns:
        return "assignments"
    return "relationships" if "pred_code" in frame.columns else "activities"


def _shown(frame: pd.DataFrame, subject: str) -> pd.DataFrame:
    """The standard columns of a set, as the flagged lists show them."""
    if subject == "assignments":
        return frame.copy()
    columns = LINK_COLS if subject == "relationships" else ACTIVITY_COLS
    return frame[[column for column in columns if column in frame.columns]].copy()


def step_rows(funnel: Funnel) -> list[dict]:
    """Start, then one row per population step (rows removed, rows left)."""
    rows = [{"step": "start", "source": "", "removed": None, "left": funnel.start}]
    rows += [
        {"step": step.label, "source": step.source, "removed": len(step.removed), "left": step.left}
        for step in funnel.steps
    ]
    return rows


def funnel_table(funnel: Funnel, counted: int | None) -> pd.DataFrame:
    """The steps of a check's population, then the items it counted (its numerator)."""
    rows = step_rows(funnel)
    rows.append({"step": "counted", "source": "", "removed": None, "left": counted})
    return pd.DataFrame(rows)


def step_sources(funnel: Funnel) -> list[str]:
    """The sources the steps of a funnel follow (keys of ``STEP_SOURCES``), once each, sorted."""
    return sorted({step.source for step in funnel.steps})


def removing_steps(funnel: Funnel) -> list[Step]:
    """The steps that took rows out, in the funnel's order."""
    return [step for step in funnel.steps if not step.removed.empty]


def removed_set(step: Step) -> tuple[str, pd.DataFrame]:
    """What a step removed, in the standard columns of its subject: "relationships" when the rows
    are links, "activities" otherwise."""
    if "pred_code" in step.removed.columns:
        return "relationships", flagged_relationships(step.removed)
    return "activities", flagged_activities(step.removed)


def counted_count(result: CheckResult, sets: AuditSets) -> int:
    """How many items the check counts: its numerator, or the rows of the counted set for a check
    without one."""
    return result.numerator if result.numerator is not None else len(sets.counted)


def split(result: CheckResult, snapshot) -> AuditSets | None:
    """Counted, checked but not counted, and excluded rows of one result; None without a checked set."""
    if result.checked is None:
        return None
    checked = result.checked
    counted = result.counted if result.counted is not None else result.flagged
    subject = _subject(checked) if not checked.empty else _subject(counted)
    checked_keys = _key(checked, subject) if not checked.empty else pd.Series(dtype=str)
    counted_keys = set(_key(counted, subject)) if not counted.empty else set()
    not_counted = checked[~checked_keys.isin(counted_keys)] if not checked.empty else checked

    universe = {"activities": snapshot.activities, "relationships": snapshot.relationships}.get(subject)
    excluded = None
    if universe is not None:
        if subject == "relationships":
            names = snapshot.activities.drop_duplicates("task_code").set_index("task_code")["task_name"]
            universe = universe.assign(
                pred_name=universe["pred_code"].map(names), succ_name=universe["succ_code"].map(names)
            )
        excluded = _shown(universe[~_key(universe, subject).isin(set(checked_keys))], subject)
    return AuditSets(
        counted=_shown(counted, subject) if result.counted is not None else counted.copy(),
        not_counted=_shown(not_counted, subject),
        excluded=excluded,
        counted_outside=len(counted_keys - set(checked_keys)),
        subject=subject,
    )


SET_NAMES = ("counted", "checked", "excluded")  # the Counted / Checked, not counted / Excluded tabs
FRONT = ["check_id", "set", "note"]
PREFIXED_FIELDS = ["wbs_code", "status", "start", "finish", "total_float_d"]  # of a relationship's two activities


def sets_long(results: list[CheckResult], snapshot) -> pd.DataFrame:
    """The sets of every result as one table: ``check_id``, ``set``, ``note``, then the item's fields.

    The rows are those ``split`` returns, the ones the Audit page shows. A relationship also carries
    ``PREFIXED_FIELDS`` of its two activities as ``pred_*`` and ``succ_*``. A check with no row to list
    (a test, or nothing in any set) has one row with its note and an empty ``set``.
    """
    activities = snapshot.activities.drop_duplicates("task_code").set_index("task_code")
    parts = []
    for result in results:
        sets = split(result, snapshot)
        rows = []
        if sets is not None:
            for name, frame in zip(SET_NAMES, (sets.counted, sets.not_counted, sets.excluded), strict=True):
                if frame is not None and not frame.empty:
                    rows.append(
                        (_with_ends(frame, activities) if sets.subject == "relationships" else frame).assign(set=name)
                    )
        part = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame({"set": [""]})
        parts.append(part.assign(note=result.note_with_baseline, check_id=result.metric.id))
    table = pd.concat(parts, ignore_index=True)
    return table[FRONT + [column for column in table.columns if column not in FRONT]]


def _with_ends(links: pd.DataFrame, activities: pd.DataFrame) -> pd.DataFrame:
    """``links`` with the fields of the predecessor and the successor activity."""
    out = links.copy()
    for end in ("pred", "succ"):
        for field in PREFIXED_FIELDS:
            out[f"{end}_{field}"] = out[f"{end}_code"].map(activities[field]) if field in activities.columns else None
    return out


def by_check(table: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """``sets_long`` cut into one table per check, without the columns that check never fills."""
    kept = {check_id: part.dropna(axis=1, how="all") for check_id, part in table.groupby("check_id", sort=False)}
    return {
        check_id: part[FRONT + [column for column in part.columns if column not in FRONT]]
        for check_id, part in kept.items()
    }


def with_settings(metric: Metric, target: str | None = None, params: dict | None = None) -> Metric:
    """The metric with another target and/or parameters, checked as a standard file would be."""
    rule = RULES[metric.rule]
    params = dict(metric.params if params is None else params)
    rule.validate(params)
    comparator, threshold = (
        (metric.comparator, metric.threshold) if target is None else parse_target(target, metric.unit)
    )
    return dataclasses.replace(metric, params=params, comparator=comparator, threshold=threshold)


def kept_params(metric: Metric, values: dict) -> dict:
    """The parameters an audited metric holds, of the ``values`` picked for the parameters its rule
    reads: those that differ from the rule's default and those the standard already sets, as a
    standard file would hold them. A tuple is held as a list, as TOML reads it."""
    defaults = RULES[metric.rule].params
    kept = {}
    for name, picked in values.items():
        value = _as_toml_reads(picked)
        if value != _as_toml_reads(defaults[name]) or name in metric.params:
            kept[name] = value
    return kept


def _as_toml_reads(value):
    """Several names as the list a standard file gives; any other value as it is."""
    return list(value) if isinstance(value, (list, tuple)) else value


def has_same_settings(audited: Metric, metric: Metric) -> bool:
    """Whether ``audited`` asks what ``metric`` asks: same parameters, same target. Its result is
    then the standard's own."""
    return (audited.params, audited.comparator, audited.threshold) == (
        metric.params,
        metric.comparator,
        metric.threshold,
    )


TARGET_FORMS = "< x%, <= x%, > x%, >= x% (unit %), <= n (count), >= r (ratio), pass, info"


def settings_table(metric: Metric, standard_metric: Metric) -> pd.DataFrame:
    """The target and every parameter of the rule, one row each: its value in ``metric`` (``now``),
    in the standard for the target and in the rule for a parameter (``default``), and what it
    accepts."""
    rows = [
        {
            "setting": "target",
            "now": metric.threshold_label,
            "default": standard_metric.threshold_label,
            "accepts": TARGET_FORMS,
        }
    ]
    for name, default in RULES[metric.rule].params.items():
        allowed = ", ".join(map(str, choices(metric.rule, name) or []))
        rows.append(
            {
                "setting": name,
                "now": str(metric.params.get(name, default)),
                "default": str(default),
                "accepts": allowed or ("true / false" if isinstance(default, bool) else "a number"),
            }
        )
    return pd.DataFrame(rows)


COMPARISON = ("op", "value", "value_max", "unit")  # what a rule compares its measure with, in reading order


def form_rows(rule_name: str) -> list[tuple[str, ...]]:
    """The parameters of a rule as the rows of a form, in the rule's order: ``COMPARISON`` on one
    row where the rule has an operator, every other parameter on a row of its own."""
    names = list(RULES[rule_name].params)
    compared = tuple(name for name in COMPARISON if name in names) if "op" in names else ()
    rows = []
    for name in names:
        if name == "op":
            rows.append(compared)
        elif name not in compared:
            rows.append((name,))
    return rows


def choices(rule_name: str, parameter: str) -> list | None:
    """The values a parameter accepts when it is a closed list (Literal or vocabulary), else None."""
    rule = RULES[rule_name]
    if parameter in ALLOWED:
        return sorted(ALLOWED[parameter])
    hint = typing.get_type_hints(rule.fn).get(parameter)
    if typing.get_origin(hint) is typing.Literal:
        return list(typing.get_args(hint))
    return None


def is_list(rule_name: str, parameter: str) -> bool:
    return typing.get_type_hints(RULES[rule_name].fn).get(parameter) == Names


def sheet(standard_id: str, metric: Metric) -> str | None:
    """The calculation sheet of a built-in metric (``sheets/<standard>/<id>.md``), None when there is
    none or when ``metric`` is not the built-in one (an uploaded standard reusing the id)."""
    from importlib.resources import files

    from .standards import builtin_standards

    builtin = builtin_standards().get(standard_id)
    if builtin is None or metric.id not in {m.id for m in builtin.metrics} or builtin[metric.id].rule != metric.rule:
        return None
    path = files("xerscope") / "sheets" / standard_id / f"{metric.id}.md"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)  # a JSON string is a TOML basic string; the file is UTF-8


def toml_block(metric: Metric) -> str:
    """The [[metric]] table of ``metric``, ready to paste into a standard file."""
    lines = ["[[metric]]", f"id = {_toml_value(metric.id)}"]
    if metric.group:
        lines.append(f"group = {_toml_value(metric.group)}")
    lines += [f"name = {_toml_value(metric.name)}", f"rule = {_toml_value(metric.rule)}"]
    if metric.description:
        lines.append(f"description = {_toml_value(metric.description)}")
    if metric.unit != RULES[metric.rule].unit:
        lines.append(f"unit = {_toml_value(metric.unit)}")
    lines.append(f"target = {_toml_value(metric.threshold_label)}")
    if metric.params:
        inner = ", ".join(f"{name} = {_toml_value(value)}" for name, value in metric.params.items())
        lines.append(f"params = {{ {inner} }}")
    if metric.source:
        lines.append(f"source = {_toml_value(metric.source)}")
    return "\n".join(lines)
