"""What the Audit page shows: a check's sets, the check re-run with audited settings, its TOML.

    audited = with_settings(metric, target="< 3%", params={"limit_hours": 264})
    result = run_metric(audited, context)
    sets = split(result, snapshot)   # counted / checked, not counted / excluded
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
from .populations import ACTIVITY_COLS, LINK_COLS
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


def with_settings(metric: Metric, target: str | None = None, params: dict | None = None) -> Metric:
    """The metric with another target and/or parameters, checked as a standard file would be."""
    rule = RULES[metric.rule]
    params = dict(metric.params if params is None else params)
    rule.validate(params)
    comparator, threshold = (
        (metric.comparator, metric.threshold) if target is None else parse_target(target, metric.unit)
    )
    return dataclasses.replace(metric, params=params, comparator=comparator, threshold=threshold)


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
    return json.dumps(str(value))  # a JSON string is a TOML basic string


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
